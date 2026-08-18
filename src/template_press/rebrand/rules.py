"""Scan rules the tool carries + per-target overrides (OQ4 hybrid model).

The tool never carries a target's identity or file list — only generic
rules: what to skip and which lockfiles to regenerate after a rebrand.
A target may extend them via <target>/press/press-rules.toml.
"""

from __future__ import annotations

import fnmatch
import re
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    REQUIRED_FIELDS,
    Identity,
    ValidationError,
)
from template_press.rebrand.safety import SafeRelPath, UnsafePathError

RULES_REL = Path("press") / "press-rules.toml"

SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"darwin", "linux", "win32"})

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# Every {field} a [[replace]] pattern may reference: the six required
# identity fields, the derived uppercase app form, and the optional
# display name (rendering fails loud at press time if the identity in
# play doesn't declare it).
ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset(REQUIRED_FIELDS) | {
    "app_name_upper",
    "display_name",
}

_REPLACE_KEYS = frozenset({"pattern", "files", "paths", "content", "reason"})


@dataclass(frozen=True)
class ReplaceRule:
    """One exact-match rewrite rule: a template rendered twice.

    The SOURCE identity renders `pattern` into the literal to find; the
    DESTINATION identity renders it into the literal to write. Exact string
    replacement of the rendered forms — no fuzzy matching, no boundary
    heuristics (codesign sec-02: rules are the primary glued-token
    mechanism). Interpolation is what keeps a committed rule correct across
    repeated presses: press rewrites press-source.toml to the new identity
    after apply, so the same rule re-renders for every future fork.
    """

    pattern: str
    reason: str
    files: tuple[str, ...] = ()
    paths: bool = False
    content: bool = True


def render_replace_pattern(pattern: str, identity: Identity) -> str:
    """Substitute {field} placeholders with this identity's values.

    Called twice per rule per press: once with the SOURCE identity (the
    literal to find) and once with the DESTINATION (the literal to write).
    """
    values = identity.as_dict()

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in values:
            raise ValidationError(
                f"[[replace]] pattern {pattern!r} references {{{name}}} but "
                f"this identity does not declare it (display_name is optional "
                f"— add it to the identity or drop the rule)"
            )
        return values[name]

    return _PLACEHOLDER_RE.sub(_sub, pattern)


@dataclass(frozen=True)
class RegenerateRule:
    """One declared regeneration: the output file and the argv that rebuilds
    it (P04 D1). Nothing is inferred from a filename — the target supplies
    the command, and ``env`` lists variable NAMES (never values) copied from
    the operator's environment into the deny-by-default child env.
    """

    file: str  # canonical POSIX rel path, SOURCE coordinates
    command: tuple[str, ...]
    env: tuple[str, ...] = ()
    # Post-command content-scan policy. "strict" (default) hunts with the
    # paranoid matcher including per-field substring mode; "boundary" is the
    # declared escape hatch for hash-dense outputs (lockfile integrity
    # hashes false-positive a short substring-mode app_name by construction)
    # — the content scan downgrades to boundary-safe matching, while the
    # path scan and rendered [[replace]] literal checks stay strict.
    scan: str = "strict"
    # Hermetic-verify exemption beyond the tool cap (issue #81). The cap
    # (REGENERATE_EXEMPTIBLE) stays the silent default; any other declared
    # output buys its exemption only loudly — verify_exempt = true with a
    # required reason, committed where reviewers see it. The reason flows
    # into verify's not-verified listing and the press receipt.
    verify_exempt: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ResetRule:
    """One declared reset: blank ``file`` to a stub (P05 D1/D6).

    Stub content comes from exactly ONE of ``stub`` (inline string) or
    ``stub_file`` (a contained local path) — enforced at config load.
    """

    file: str  # canonical POSIX rel path, SOURCE coordinates
    stub: str | None = None
    stub_file: str | None = None


@dataclass(frozen=True)
class RemoveRule:
    """One declared removal: delete ``file`` from the pressed tree (P08 T2,
    issue #80). Template-only files (maintenance CI, dogfood history) must
    not ship to forks; removal is their neutralization. It executes AFTER
    ``apply()`` with the path translated through the rename report, and
    hermetic verify performs it in the sandbox — no command, so no
    exemption and no coverage gap.
    """

    file: str  # canonical POSIX rel path, SOURCE coordinates
    reason: str


@dataclass(frozen=True)
class _RemoveDeclaration:
    """One parsed removal plus its environment-independent selector."""

    rule: RemoveRule
    platforms: frozenset[str]


@dataclass(frozen=True)
class _RegenerateDeclaration:
    """One parsed regeneration plus its environment-independent selector."""

    rule: RegenerateRule
    platforms: frozenset[str]


@dataclass(frozen=True)
class _ResetDeclaration:
    """One parsed reset plus its environment-independent selector."""

    rule: ResetRule
    platforms: frozenset[str]


def rule_matches_path(rule: ReplaceRule, posix: str) -> bool:
    """POSIX rel-path scope check: empty files = every file; else fnmatch.

    ``fnmatchcase``, not ``fnmatch``: the plain form runs both arguments
    through ``os.path.normcase``, which case-folds on Windows — a glob would
    match case-insensitively there and case-sensitively on POSIX. Matching
    is defined against the POSIX relative path, so it must be deterministic
    across platforms.
    """
    if not rule.files:
        return True
    return any(fnmatch.fnmatchcase(posix, glob) for glob in rule.files)


@dataclass(frozen=True)
class Rules:
    exclude_dirs: frozenset[str]
    exclude_files: frozenset[str]  # POSIX paths relative to the target root
    regenerate: tuple[RegenerateRule, ...]  # declared-command regenerations
    reset: tuple[ResetRule, ...] = ()  # declared file resets (blank to stub)
    remove: tuple[RemoveRule, ...] = ()  # declared file removals (issue #80)
    # The deliberate, committed ignore set: directories whose surviving
    # source-identity content is VALID (vendored trees, historical docs).
    # Exempts them from the doctor's leak scan only — never from rewriting.
    # Matched like exclude_dirs: by single path COMPONENT at any depth
    # ("legacy" ignores every dir named legacy; "docs/old" never matches).
    verify_ignore: frozenset[str] = frozenset()
    replace: tuple[ReplaceRule, ...] = ()
    # Fields rewritten by plain substring replacement instead of the
    # boundary-guarded token pattern (codesign sec-02 secondary). Opt-in,
    # per field, for provably word-disjoint tokens ONLY — a word-embedded
    # value here WILL corrupt prose; that risk is the author's to accept.
    substring_rewrite_fields: frozenset[str] = frozenset()
    display_forms: tuple[str, ...] = DISPLAY_FORM_NAMES


@dataclass(frozen=True)
class SelectedRules:
    """The captured runtime platform and its active, selector-free rules."""

    platform: str
    rules: Rules


@dataclass(frozen=True)
class _ParsedRules:
    """Private pre-selection declarations plus platform-neutral base rules."""

    rules: Rules
    regenerate: tuple[_RegenerateDeclaration, ...] = ()
    reset: tuple[_ResetDeclaration, ...] = ()
    remove: tuple[_RemoveDeclaration, ...] = ()


DEFAULT_RULES = Rules(
    exclude_dirs=frozenset(
        {
            # NB: the control "press/" dir is NOT excluded here — the engine
            # exempts it content-keyed (only when it holds a press-*.toml
            # marker), so an unrelated press/ dir in a target is still
            # rewritten and leak-scanned. See engine.CONTROL_MARKERS.
            ".git",
            "node_modules",
            ".venv",
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
        }
    ),
    exclude_files=frozenset(
        {"uv.lock", "bun.lock", "package-lock.json", "CHANGELOG.md"}
    ),
    # No hidden default (P04 D1): every regeneration is target-declared via
    # [[regenerate]]; the old implicit ("uv.lock",) entry is deliberately gone.
    regenerate=(),
)


_COMPONENT_KEYS = frozenset({"extra_exclude_dirs", "verify_ignore"})

# The exact set of keys load_rules reads from [rules] — a typo (e.g.
# substring_rewrite_field, singular) must fail loud instead of silently
# degrading to defaults. `regenerate` is deliberately ABSENT: the legacy
# list-of-strings form is intercepted with a schema template (see
# _legacy_regenerate_error), never treated as an unknown key.
_RULES_KEYS = frozenset(
    {
        "extra_exclude_dirs",
        "extra_exclude_files",
        "verify_ignore",
        "substring_rewrite_fields",
        "display_forms",
    }
)

# The exact set of ROOT-level tables press-rules.toml legitimately carries —
# every table some loader in this codebase actually reads from the file:
# [rules], [[replace]], [[regenerate]], and [[reset]] here, [verify] in
# verify_cli.py's _load_verify_config (same file). An unknown root key (e.g.
# a `[[replace]]` typo like `[[replcae]]`) must fail loud instead of silently
# loading as zero rules.
_ROOT_KEYS = frozenset({"rules", "replace", "verify", "regenerate", "reset", "remove"})
_REMOVE_KEYS = frozenset({"file", "reason", "platforms"})

_REGENERATE_KEYS = frozenset(
    {"file", "command", "env", "platforms", "scan", "verify_exempt", "reason"}
)
_REGENERATE_SCAN_VALUES = frozenset({"strict", "boundary"})
_RESET_KEYS = frozenset({"file", "stub", "stub_file", "platforms"})


def _str_list(table: dict, key: str, default: list[str]) -> list[str]:
    value = table.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{RULES_REL}: [rules] {key} must be a list of strings")
    if key in _COMPONENT_KEYS:
        nested = [v for v in value if "/" in v or "\\" in v]
        if nested:
            raise ValidationError(
                f"{RULES_REL}: [rules] {key} entries are single directory "
                f"NAMES matched at any depth, not paths — invalid: {nested}"
            )
    return value


def _parse_replace(entry: object) -> ReplaceRule:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[replace]] entry must be a table")
    unknown = set(entry) - _REPLACE_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    pattern = entry.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] pattern must be a non-empty string"
        )
    brace_tokens = re.findall(r"\{[^{}]*\}", pattern)
    if not brace_tokens:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] pattern {pattern!r} references no identity "
            f"field — a placeholder-free rule renders FROM == TO (a committed "
            f"no-op); use e.g. {{app_name}}"
        )
    # Scan every brace-delimited token, not just the ones _PLACEHOLDER_RE
    # happens to match: a malformed token like {app_name1} or {App_Name}
    # doesn't match `[a-z_]+` and so was previously invisible to a
    # names-based check, rendering LITERALLY in the pattern's output as long
    # as at least one OTHER, valid placeholder existed elsewhere (the
    # "references no identity field" guard above was satisfied by the valid
    # one). Reject any brace token whose inner text isn't exactly a known
    # field — this subsumes the former unknown-name check.
    for token in brace_tokens:
        inner = token[1:-1]
        if not re.fullmatch(r"[a-z_]+", inner) or inner not in ALLOWED_PLACEHOLDERS:
            raise ValidationError(
                f"{RULES_REL}: [[replace]] pattern {pattern!r} references an "
                f"invalid or unknown placeholder {token!r}"
            )
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError(
            f"{RULES_REL}: [[replace]] {pattern!r}: reason is required"
        )
    raw_files = entry.get("files", [])
    if not isinstance(raw_files, list):
        raise ValidationError(
            f"{RULES_REL}: [[replace]] files must be a list of glob strings"
        )
    files: list[str] = []
    for f in raw_files:
        if not isinstance(f, str):
            raise ValidationError(
                f"{RULES_REL}: [[replace]] files must be a list of glob strings"
            )
        files.append(f)
    paths = entry.get("paths", False)
    if not isinstance(paths, bool):
        raise ValidationError(f"{RULES_REL}: [[replace]] paths must be a boolean")
    content = entry.get("content", True)
    if not isinstance(content, bool):
        raise ValidationError(f"{RULES_REL}: [[replace]] content must be a boolean")
    if not paths and not content:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] {pattern!r}: paths and content are both "
            f"false — the rule would do nothing"
        )
    return ReplaceRule(
        pattern=pattern,
        reason=reason,
        files=tuple(files),
        paths=paths,
        content=content,
    )


def _legacy_regenerate_error(value: object) -> ValidationError:
    """The old list-of-strings `regenerate` form, rejected with a TEMPLATE.

    The template carries a PLACEHOLDER command — never an argv derived from
    the filename, which would reinstate the filename→command inference D1
    removes (the legacy-form error is exactly where that inference re-tempts).
    """
    if isinstance(value, str):
        names: list[str] = [value]
    elif isinstance(value, list):
        names = [v for v in value if isinstance(v, str)] or ["<file>"]
    else:
        names = ["<file>"]
    blocks = "\n\n".join(
        f'[[regenerate]]\nfile    = "{name}"\ncommand = ["<command>", "<args>", "..."]'
        for name in names
    )
    return ValidationError(
        f"{RULES_REL}: `regenerate` is no longer a list of filenames — declare "
        f"each regeneration as a root-level [[regenerate]] table naming the "
        f"exact command that rebuilds the file (press infers nothing from a "
        f"filename):\n\n{blocks}"
    )


def _declared_rel_path(context: str, value: object) -> str:
    """Validate a declared path as a contained relative path; return POSIX."""
    if not isinstance(value, str) or not value:
        raise ValidationError(
            f"{RULES_REL}: {context} must be a non-empty relative path string"
        )
    if "\x00" in value:
        raise ValidationError(f"{RULES_REL}: {context} must not contain NUL")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        # Plan visibility is the approval guard (wave-3 3654059282); a
        # declared path is interpolated into the rendered plan exactly like
        # argv elements, so terminal controls are rejected the same way.
        raise ValidationError(
            f"{RULES_REL}: {context} must not contain control characters: {value!r}"
        )
    try:
        rel = SafeRelPath(value)
    except UnsafePathError as exc:
        raise ValidationError(f"{RULES_REL}: {context}: {exc}") from exc
    return rel.as_posix()


def _reject_reserved(kind: str, file: str) -> None:
    # Deferred import avoids a module-load cycle: pathing imports Rules for
    # neutral scope helpers, while this validator needs the control paths.
    from template_press.rebrand.pathing import ROOT_CONTROL

    # Casefolded, matching the same-file test used elsewhere for filesystem
    # path comparisons (safety.py's `_is_dotgit`): on a case-insensitive
    # filesystem (Windows, default macOS), `PRESS/press-source.toml` and
    # `press/press-source.toml` are the SAME file, so the reserved check
    # must not be case-sensitive either.
    if file.casefold() in {entry.casefold() for entry in ROOT_CONTROL}:
        raise ValidationError(
            f"{RULES_REL}: {kind} may not target press-owned control file "
            f"{file!r} — press itself writes it after validation (reserved)"
        )


def _parse_platforms(entry: dict, kind: str, file: str) -> frozenset[str]:
    """Validate one optional selector without consulting the host environment."""

    if "platforms" not in entry:
        return SUPPORTED_PLATFORMS
    raw = entry["platforms"]
    if not isinstance(raw, list) or not raw:
        raise ValidationError(
            f"{RULES_REL}: {kind} {file!r}: platforms must be a non-empty list "
            f"containing only {sorted(SUPPORTED_PLATFORMS)!r}"
        )
    platforms: list[str] = []
    for value in raw:
        if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
            raise ValidationError(
                f"{RULES_REL}: {kind} {file!r}: platforms values must be exact "
                f"members of {sorted(SUPPORTED_PLATFORMS)!r}: {value!r}"
            )
        if value in platforms:
            raise ValidationError(
                f"{RULES_REL}: {kind} {file!r}: platforms contains duplicate "
                f"value {value!r}"
            )
        platforms.append(value)
    return frozenset(platforms)


def _parse_regenerate(
    entry: object, exclude_files: frozenset[str]
) -> _RegenerateDeclaration:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[regenerate]] entry must be a table")
    unknown = set(entry) - _REGENERATE_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    file = _declared_rel_path("[[regenerate]] file", entry.get("file"))
    _reject_reserved("[[regenerate]]", file)
    if file not in exclude_files:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] output {file!r} must be listed in "
            f"exclude_files (add it to [rules] extra_exclude_files) — a "
            f"non-excluded output is rewritten by the replace pass and then "
            f"immediately overwritten by the declared command"
        )
    raw_command = entry.get("command")
    if not isinstance(raw_command, list) or not raw_command:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: command must be a "
            f"non-empty list of strings (the exact argv — no shell)"
        )
    command: list[str] = []
    for element in raw_command:
        # Control characters (NUL, newline/CR, ANSI ESC, tab) are rejected,
        # not escaped: plan visibility is the approval guard, and a literal
        # renderer could be forged by an argv element carrying its own
        # plan-shaped lines (wave-3 thread 3654059282).
        if (
            not isinstance(element, str)
            or not element
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in element)
        ):
            raise ValidationError(
                f"{RULES_REL}: [[regenerate]] {file!r}: command elements must "
                f"be non-empty strings without control characters: {element!r}"
            )
        command.append(element)
    raw_env = entry.get("env", [])
    if not isinstance(raw_env, list):
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: env must be a list of "
            f"variable names"
        )
    env: list[str] = []
    for name in raw_env:
        if (
            not isinstance(name, str)
            or not name
            or "=" in name
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name)
        ):
            raise ValidationError(
                f"{RULES_REL}: [[regenerate]] {file!r}: env entries are "
                f"variable NAMES (non-empty, no '=', no control characters): "
                f"{name!r}"
            )
        env.append(name)
    scan = entry.get("scan", "strict")
    if not isinstance(scan, str) or scan not in _REGENERATE_SCAN_VALUES:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: scan must be one of "
            f"{sorted(_REGENERATE_SCAN_VALUES)}: {scan!r}"
        )
    verify_exempt = entry.get("verify_exempt", False)
    if not isinstance(verify_exempt, bool):
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: verify_exempt must be a "
            f"boolean: {verify_exempt!r}"
        )
    reason = entry.get("reason", "")
    if not isinstance(reason, str):
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: reason must be a string: {reason!r}"
        )
    # Rendered in reports and the receipt — control characters are rejected,
    # not escaped, mirroring the argv rule (report visibility is the
    # approval guard, so a reason must not be able to forge report lines).
    if any(not ch.isprintable() for ch in reason):
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: reason must not contain "
            f"control or non-printable characters"
        )
    # The pair is all-or-nothing: an exemption without a reason is a silent
    # coverage purchase, and a reason without the exemption — including an
    # explicitly empty one — is dead config.
    if verify_exempt and not reason.strip():
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: verify_exempt = true "
            f"requires a non-empty reason — the exemption is bought loudly "
            f"or not at all"
        )
    if "reason" in entry and not verify_exempt:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] {file!r}: reason is only valid "
            f"with verify_exempt = true"
        )
    return _RegenerateDeclaration(
        rule=RegenerateRule(
            file=file,
            command=tuple(command),
            env=tuple(env),
            scan=scan,
            verify_exempt=verify_exempt,
            reason=reason,
        ),
        platforms=_parse_platforms(entry, "[[regenerate]]", file),
    )


def _parse_reset(entry: object, exclude_files: frozenset[str]) -> _ResetDeclaration:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[reset]] entry must be a table")
    unknown = set(entry) - _RESET_KEYS
    if unknown:
        hint = (
            " (the target key is 'file', not prior art's 'path')"
            if "path" in unknown
            else ""
        )
        raise ValidationError(
            f"{RULES_REL}: [[reset]] unknown key(s): {', '.join(sorted(unknown))}{hint}"
        )
    file = _declared_rel_path("[[reset]] file", entry.get("file"))
    _reject_reserved("[[reset]]", file)
    if file not in exclude_files:
        raise ValidationError(
            f"{RULES_REL}: [[reset]] target {file!r} must be listed in "
            f"exclude_files (add it to [rules] extra_exclude_files) — a "
            f"non-excluded target is also rewritten by the replace pass, so "
            f"the result would depend on pass order"
        )
    has_stub = "stub" in entry
    has_stub_file = "stub_file" in entry
    if has_stub == has_stub_file:
        raise ValidationError(
            f"{RULES_REL}: [[reset]] {file!r}: declare exactly one of stub "
            f"(inline string) or stub_file (contained local path)"
        )
    if has_stub:
        stub = entry.get("stub")
        if not isinstance(stub, str):
            raise ValidationError(
                f"{RULES_REL}: [[reset]] {file!r}: stub must be a string"
            )
        rule = ResetRule(file=file, stub=stub)
    else:
        stub_file = _declared_rel_path(
            f"[[reset]] {file!r} stub_file", entry.get("stub_file")
        )
        rule = ResetRule(file=file, stub_file=stub_file)
    return _ResetDeclaration(
        rule=rule,
        platforms=_parse_platforms(entry, "[[reset]]", file),
    )


def _parse_remove(entry: object) -> _RemoveDeclaration:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[remove]] entry must be a table")
    unknown = set(entry) - _REMOVE_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[remove]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    file = _declared_rel_path("[[remove]] file", entry.get("file"))
    _reject_reserved("[[remove]]", file)
    if file.rsplit("/", 1)[-1] in {".gitignore", ".gitattributes", ".gitmodules"}:
        raise ValidationError(
            f"{RULES_REL}: [[remove]] {file!r}: Git visibility inputs cannot "
            f"be removed by declaration — deleting one changes Git's surface "
            f"after the rewrite plan was validated against it"
        )
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError(
            f"{RULES_REL}: [[remove]] {file!r}: reason is required and must "
            f"be a non-empty string — a removal is a deliberate, documented "
            f"decision, never a silent deletion"
        )
    if any(not ch.isprintable() for ch in reason):
        raise ValidationError(
            f"{RULES_REL}: [[remove]] {file!r}: reason must not contain "
            f"control or non-printable characters — it is interpolated into "
            f"the rendered plan"
        )
    return _RemoveDeclaration(
        rule=RemoveRule(file=file, reason=reason),
        platforms=_parse_platforms(entry, "[[remove]]", file),
    )


def _validate_writer_overlaps(
    regenerate: tuple[_RegenerateDeclaration, ...],
    reset: tuple[_ResetDeclaration, ...],
    remove: tuple[_RemoveDeclaration, ...] = (),
) -> None:
    """Reject any same-file writer pair active on at least one platform."""

    seen_regenerate: dict[str, list[frozenset[str]]] = {}
    for declaration in regenerate:
        file = declaration.rule.file
        for earlier in seen_regenerate.get(file, []):
            overlap = earlier & declaration.platforms
            if overlap:
                raise ValidationError(
                    f"{RULES_REL}: {file} declared by more than one "
                    f"[[regenerate]] table with platform overlap "
                    f"{sorted(overlap)!r} — each platform permits one writer"
                )
        seen_regenerate.setdefault(file, []).append(declaration.platforms)

    seen_reset: dict[str, list[frozenset[str]]] = {}
    for declaration in reset:
        file = declaration.rule.file
        for earlier in seen_reset.get(file, []):
            overlap = earlier & declaration.platforms
            if overlap:
                raise ValidationError(
                    f"{RULES_REL}: duplicate [[reset]] target {file!r} has "
                    f"platform overlap {sorted(overlap)!r} — each platform "
                    f"permits one writer"
                )
        seen_reset.setdefault(file, []).append(declaration.platforms)

    for regenerate_declaration in regenerate:
        for reset_declaration in reset:
            if regenerate_declaration.rule.file != reset_declaration.rule.file:
                continue
            overlap = regenerate_declaration.platforms & reset_declaration.platforms
            if overlap:
                file = regenerate_declaration.rule.file
                raise ValidationError(
                    f"{RULES_REL}: {file!r} has [[regenerate]] and [[reset]] "
                    f"writer overlap on {sorted(overlap)!r} — each platform "
                    f"permits exactly one mechanism per file"
                )

    seen_remove: dict[str, list[frozenset[str]]] = {}
    for declaration in remove:
        file = declaration.rule.file
        for earlier in seen_remove.get(file, []):
            overlap = earlier & declaration.platforms
            if overlap:
                raise ValidationError(
                    f"{RULES_REL}: duplicate [[remove]] target {file!r} has "
                    f"platform overlap {sorted(overlap)!r}"
                )
        seen_remove.setdefault(file, []).append(declaration.platforms)
    for remove_declaration in remove:
        for reset_declaration in reset:
            stub_file = reset_declaration.rule.stub_file
            if stub_file is None or stub_file != remove_declaration.rule.file:
                continue
            overlap = reset_declaration.platforms & remove_declaration.platforms
            if overlap:
                raise ValidationError(
                    f"{RULES_REL}: {stub_file!r} is a [[reset]] stub_file and "
                    f"a [[remove]] target on {sorted(overlap)!r} — the "
                    f"removal would destroy the stub source; drop one "
                    f"declaration"
                )
        for other_kind, others in (
            ("[[regenerate]]", regenerate),
            ("[[reset]]", reset),
        ):
            for other in others:
                if other.rule.file != remove_declaration.rule.file:
                    continue
                overlap = other.platforms & remove_declaration.platforms
                if overlap:
                    file = remove_declaration.rule.file
                    raise ValidationError(
                        f"{RULES_REL}: {file!r} has [[remove]] and "
                        f"{other_kind} overlap on {sorted(overlap)!r} — a "
                        f"removed file cannot also be rebuilt or reset"
                    )


def _parse_rules(target: Path) -> _ParsedRules:
    """Parse and globally validate declarations before platform selection."""

    override_path = target / RULES_REL
    if not override_path.is_file():
        return _ParsedRules(rules=DEFAULT_RULES)
    data = tomllib.loads(override_path.read_text(encoding="utf-8"))
    unknown_root = set(data) - _ROOT_KEYS
    if unknown_root:
        raise ValidationError(
            f"{RULES_REL}: unknown root-level table(s): "
            f"{', '.join(sorted(unknown_root))}"
        )
    table = data.get("rules", {})
    if not isinstance(table, dict):
        raise ValidationError(f"{RULES_REL}: [rules] must be a table")
    if "regenerate" in table:
        raise _legacy_regenerate_error(table["regenerate"])
    unknown_keys = set(table) - _RULES_KEYS
    if unknown_keys:
        raise ValidationError(
            f"{RULES_REL}: [rules] unknown key(s): {', '.join(sorted(unknown_keys))}"
        )
    raw_replace = data.get("replace", [])
    if not isinstance(raw_replace, list):
        raise ValidationError(f"{RULES_REL}: [[replace]] must be an array of tables")
    raw_regenerate = data.get("regenerate", [])
    if not isinstance(raw_regenerate, list) or any(
        not isinstance(e, dict) for e in raw_regenerate
    ):
        raise _legacy_regenerate_error(raw_regenerate)
    raw_reset = data.get("reset", [])
    if not isinstance(raw_reset, list) or any(
        not isinstance(e, dict) for e in raw_reset
    ):
        raise ValidationError(f"{RULES_REL}: [[reset]] must be an array of tables")
    raw_remove = data.get("remove", [])
    if not isinstance(raw_remove, list) or any(
        not isinstance(e, dict) for e in raw_remove
    ):
        raise ValidationError(f"{RULES_REL}: [[remove]] must be an array of tables")
    substring_fields = frozenset(_str_list(table, "substring_rewrite_fields", []))
    bad_substring = substring_fields - ALLOWED_PLACEHOLDERS
    if bad_substring:
        raise ValidationError(
            f"{RULES_REL}: [rules] substring_rewrite_fields unknown field(s): "
            f"{', '.join(sorted(bad_substring))}"
        )
    if "display_name" in substring_fields:
        # A no-op disguised as a valid config: "display_name" IS in
        # ALLOWED_PLACEHOLDERS (render_replace_pattern can reference it), but
        # the runtime pair tags substring_rewrite_fields actually dispatches
        # on are display_name_spaced/pascal/camel, never bare "display_name"
        # — so this entry would never match anything. Display forms are
        # exact-by-design (codesign sec-04); use [rules] display_forms to
        # narrow which forms rewrite instead.
        raise ValidationError(
            f"{RULES_REL}: [rules] substring_rewrite_fields must not include "
            f"'display_name' — it is a no-op (runtime pair tags are "
            f"display_name_spaced/pascal/camel, never bare 'display_name'); "
            f"use [rules] display_forms instead"
        )
    display_forms_list = _str_list(table, "display_forms", list(DISPLAY_FORM_NAMES))
    bad_forms = set(display_forms_list) - set(DISPLAY_FORM_NAMES)
    if bad_forms or not display_forms_list:
        raise ValidationError(
            f"{RULES_REL}: [rules] display_forms must be a non-empty subset of "
            f"{list(DISPLAY_FORM_NAMES)}: {display_forms_list!r}"
        )
    exclude_files = DEFAULT_RULES.exclude_files | frozenset(
        _str_list(table, "extra_exclude_files", [])
    )
    regenerate = tuple(_parse_regenerate(e, exclude_files) for e in raw_regenerate)
    reset = tuple(_parse_reset(e, exclude_files) for e in raw_reset)
    remove = tuple(_parse_remove(e) for e in raw_remove)
    _validate_writer_overlaps(regenerate, reset, remove)
    return _ParsedRules(
        rules=Rules(
            exclude_dirs=DEFAULT_RULES.exclude_dirs
            | frozenset(_str_list(table, "extra_exclude_dirs", [])),
            exclude_files=exclude_files,
            regenerate=(),
            reset=(),
            verify_ignore=frozenset(_str_list(table, "verify_ignore", [])),
            replace=tuple(_parse_replace(e) for e in raw_replace),
            substring_rewrite_fields=substring_fields,
            display_forms=tuple(dict.fromkeys(display_forms_list)),
        ),
        regenerate=regenerate,
        reset=reset,
        remove=remove,
    )


def _select_rules(parsed: _ParsedRules, platform: str) -> SelectedRules:
    """Purely select active rules for one already-captured runtime value."""

    if platform not in SUPPORTED_PLATFORMS:
        raise ValidationError(
            f"unsupported runtime platform {platform!r}; expected one of "
            f"{sorted(SUPPORTED_PLATFORMS)!r}"
        )
    rules = replace(
        parsed.rules,
        regenerate=tuple(
            declaration.rule
            for declaration in parsed.regenerate
            if platform in declaration.platforms
        ),
        reset=tuple(
            declaration.rule
            for declaration in parsed.reset
            if platform in declaration.platforms
        ),
        remove=tuple(
            declaration.rule
            for declaration in parsed.remove
            if platform in declaration.platforms
        ),
    )
    return SelectedRules(platform=platform, rules=rules)


def load_selected_rules(target: Path, *, platform: str | None = None) -> SelectedRules:
    """Parse all declarations, then select once for the captured platform."""

    parsed = _parse_rules(target)
    return _select_rules(parsed, sys.platform if platform is None else platform)


def load_rules(target: Path) -> Rules:
    """Compatibility view of active rules for callers not yet carrying selection."""

    return load_selected_rules(target).rules
