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
import unicodedata
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
class EditRule:
    """One declared in-place edit: run ``command`` against ``file`` AFTER the
    replace pass has rewritten it (E4).

    The inverse of :class:`RegenerateRule` in both directions. Where a
    regeneration OVERWRITES a file the replace pass must therefore skip, an
    edit AMENDS the file the replace pass has already rewritten — so the
    target is not excluded on an active edit platform (the platform-disjoint
    writer exception is resolved during selection), and the edit mechanism
    grants no command-based ``press verify`` exemption (no ``verify_exempt``,
    no ``scan`` downgrade to buy) and does not alter doctor inventory policy.
    A target's independent path-component ``verify_ignore`` still applies.
    ``expect`` is the post-condition: a literal substring the edited file must
    contain once the command has run, so a silently no-op command fails loudly
    instead of shipping.
    """

    file: str  # canonical POSIX rel path, SOURCE coordinates
    command: tuple[str, ...]
    expect: str
    env: tuple[str, ...]


@dataclass(frozen=True)
class _RemoveDeclaration:
    """One parsed removal plus its environment-independent selector."""

    rule: RemoveRule
    platforms: frozenset[str]


@dataclass(frozen=True)
class _EditDeclaration:
    """One parsed edit plus its environment-independent selector."""

    rule: EditRule
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
    # The deliberate, committed ignore set: path components whose surviving
    # source-identity content is VALID (vendored trees, historical docs, files).
    # Exempts matching entries from later doctor and hermetic-verify inventories
    # only — never from rewriting or direct command postconditions.
    # Matched like exclude_dirs: by single path COMPONENT at any depth
    # ("legacy" ignores every file or directory named legacy; "docs/old" never
    # matches).
    verify_ignore: frozenset[str] = frozenset()
    replace: tuple[ReplaceRule, ...] = ()
    # Fields rewritten by plain substring replacement instead of the
    # boundary-guarded token pattern (codesign sec-02 secondary). Opt-in,
    # per field, for provably word-disjoint tokens ONLY — a word-embedded
    # value here WILL corrupt prose; that risk is the author's to accept.
    substring_rewrite_fields: frozenset[str] = frozenset()
    display_forms: tuple[str, ...] = DISPLAY_FORM_NAMES
    # Declared in-place edits (E4). Appended AFTER every pre-existing field
    # on purpose: Rules is constructed positionally in places, and an
    # insertion higher up rebinds every later argument silently.
    edit: tuple[EditRule, ...] = ()


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
    edit: tuple[_EditDeclaration, ...] = ()


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
# [rules], [[replace]], [[regenerate]], [[reset]], [[remove]], and [[edit]]
# here, [verify] in verify_cli.py's _load_verify_config (same file). An
# unknown root key (e.g. a `[[replace]]` typo like `[[replcae]]`) must fail
# loud instead of silently loading as zero rules.
_ROOT_KEYS = frozenset(
    {"rules", "replace", "verify", "regenerate", "reset", "remove", "edit"}
)
_REMOVE_KEYS = frozenset({"file", "reason", "platforms"})

_REGENERATE_KEYS = frozenset(
    {"file", "command", "env", "platforms", "scan", "verify_exempt", "reason"}
)
_REGENERATE_SCAN_VALUES = frozenset({"strict", "boundary"})
_RESET_KEYS = frozenset({"file", "stub", "stub_file", "platforms"})
# Deliberately WITHOUT `verify_exempt`/`scan`: an edit cannot buy a command-
# based exemption, so both keys are unknown here rather than merely ignored.
# The separate path-component `verify_ignore` policy remains unchanged.
_EDIT_KEYS = frozenset({"file", "command", "expect", "env", "platforms"})


def _str_list(table: dict, key: str, default: list[str]) -> list[str]:
    value = table.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{RULES_REL}: [rules] {key} must be a list of strings")
    if key in _COMPONENT_KEYS:
        nested = [v for v in value if "/" in v or "\\" in v]
        if nested:
            raise ValidationError(
                f"{RULES_REL}: [rules] {key} entries are single path-component "
                "names matched at any depth, including basenames; "
                f"multi-component paths are invalid: {nested}"
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


def _control_alias_key(file: str) -> str:
    """Collapse a POSIX relative path to its filesystem-alias identity."""
    return "/".join(_alias_component(part) for part in file.split("/"))


def _alias_component(part: str) -> str:
    """Reduce one path component to the identity a filesystem may collapse.

    Three real aliasing rules, applied in the order the filesystem does:

    1. Windows drops trailing dots and spaces from every component, so
       `meta.toml.` and `meta.toml ` open `meta.toml`.
    2. Windows and default macOS are case-insensitive, so `META.TOML` is the
       same entry as `meta.toml`.
    3. APFS and HFS+ are normalization-insensitive, so the composed and
       decomposed spellings of one grapheme — `cafe\u0301.toml` and its
       precomposed NFC form — are also one entry.

    The normalization is a canonical caseless match (Unicode 3.13, D145):
    NFD, then casefold, then NFD again. The trailing NFD is what the plain
    casefold misses, because casefold is not closed under canonical
    equivalence — it can emit a base character where a combining mark stood
    (U+0345 is the standard example), leaving two canonically equal inputs
    with unequal folded forms. In a fail-closed refusal key an unequal form
    is a missed alias, which fails OPEN, so the sandwich is used rather than
    a single trailing normalize. The leading `rstrip` stays outermost:
    canonical normalization never produces an ASCII dot or space, so it
    cannot expose a component the strip would have taken.
    """
    stripped = part.rstrip(" .")
    return unicodedata.normalize(
        "NFD", unicodedata.normalize("NFD", stripped).casefold()
    )


def _reject_reserved(kind: str, file: str) -> None:
    # Deferred import avoids a module-load cycle: pathing imports Rules for
    # neutral scope helpers, while this validator needs the control paths.
    from template_press.rebrand.pathing import ROOT_CONTROL

    # A SUPERSET of the same-file test used elsewhere for filesystem path
    # comparisons (safety.py's `_is_dotgit`, which case-folds only — `.git`
    # is ASCII, so the rest is moot there). _alias_component adds a
    # per-component strip of trailing dots/spaces and a canonical caseless
    # normalization. All three are real filesystem aliases, not cosmetics —
    # on a case-insensitive filesystem (Windows, default macOS)
    # `PRESS/press-source.toml` is the SAME file as `press/press-source.toml`;
    # on Windows so are `press/press-source.toml.` and
    # `press/press-source.toml ` (the filesystem drops trailing dots/spaces
    # from every component); and on normalization-insensitive APFS/HFS+ so are
    # the composed and decomposed spellings of one grapheme. Rules are
    # validated identically on every platform, so the check rejects the union
    # of aliases rather than the host's own set.
    if _control_alias_key(file) in {_control_alias_key(e) for e in ROOT_CONTROL}:
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


def _parse_command(entry: dict, kind: str, file: str) -> tuple[str, ...]:
    """The declared argv: a non-empty list of non-empty, control-free strings.

    Shared by [[regenerate]] and [[edit]] so the two mechanisms cannot drift
    apart — both hand the same argv shape to the same runner.
    """
    raw_command = entry.get("command")
    if not isinstance(raw_command, list) or not raw_command:
        raise ValidationError(
            f"{RULES_REL}: {kind} {file!r}: command must be a "
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
                f"{RULES_REL}: {kind} {file!r}: command elements must "
                f"be non-empty strings without control characters: {element!r}"
            )
        command.append(element)
    return tuple(command)


def _parse_env(entry: dict, kind: str, file: str) -> tuple[str, ...]:
    """Variable NAMES (never values) copied into the deny-by-default child env."""
    raw_env = entry.get("env", [])
    if not isinstance(raw_env, list):
        raise ValidationError(
            f"{RULES_REL}: {kind} {file!r}: env must be a list of variable names"
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
                f"{RULES_REL}: {kind} {file!r}: env entries are "
                f"variable NAMES (non-empty, no '=', no control characters): "
                f"{name!r}"
            )
        env.append(name)
    return tuple(env)


def _parse_regenerate(entry: object) -> _RegenerateDeclaration:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[regenerate]] entry must be a table")
    unknown = set(entry) - _REGENERATE_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[regenerate]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    file = _declared_rel_path("[[regenerate]] file", entry.get("file"))
    _reject_reserved("[[regenerate]]", file)
    command = _parse_command(entry, "[[regenerate]]", file)
    env = _parse_env(entry, "[[regenerate]]", file)
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
            command=command,
            env=env,
            scan=scan,
            verify_exempt=verify_exempt,
            reason=reason,
        ),
        platforms=_parse_platforms(entry, "[[regenerate]]", file),
    )


def _parse_reset(entry: object) -> _ResetDeclaration:
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


def _parse_edit(entry: object) -> _EditDeclaration:
    """One [[edit]] table: mirrors [[regenerate]] with two inversions (E4).

    `verify_exempt`/`scan` are absent from _EDIT_KEYS on purpose, so both land
    in the unknown-key refusal: an edit cannot buy a command-based leak-scan
    exemption, and there is no hash-dense-output escape hatch to grant. The
    target-wide ``verify_ignore`` policy is independent. The exclude_files
    contract is inverted too, and lives in
    _validate_exclude_membership so the one-writer diagnostic wins first.
    """
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[edit]] entry must be a table")
    unknown = set(entry) - _EDIT_KEYS
    if unknown:
        hint = (
            " (an edit earns no command-based verify exemption — use the "
            "separate [rules] verify_ignore policy for deliberate ignores)"
            if unknown & {"verify_exempt", "scan"}
            else ""
        )
        raise ValidationError(
            f"{RULES_REL}: [[edit]] unknown key(s): {', '.join(sorted(unknown))}{hint}"
        )
    file = _declared_rel_path("[[edit]] file", entry.get("file"))
    _reject_reserved("[[edit]]", file)
    command = _parse_command(entry, "[[edit]]", file)
    env = _parse_env(entry, "[[edit]]", file)
    expect = entry.get("expect")
    # E4 binds this exactly: a NON-EMPTY PRINTABLE string. Three shapes fail —
    # a non-string, the empty string, and anything carrying a character
    # `str.isprintable` rejects (it could not be shown in the rendered plan or
    # the receipt; that check also catches every whitespace character except
    # the plain space, tabs included). A run of spaces is a weak post-condition
    # but a legal one, and the parser does not get to tighten the spec.
    if not isinstance(expect, str) or not expect:
        raise ValidationError(
            f"{RULES_REL}: [[edit]] {file!r}: expect is required and must be a "
            f"non-empty string — it is the post-condition substring the edited "
            f"file must contain once the command has run: {expect!r}"
        )
    if any(not ch.isprintable() for ch in expect):
        raise ValidationError(
            f"{RULES_REL}: [[edit]] {file!r}: expect must not contain control "
            f"or non-printable characters — it is interpolated into the "
            f"rendered plan and the receipt"
        )
    return _EditDeclaration(
        rule=EditRule(file=file, command=command, expect=expect, env=env),
        platforms=_parse_platforms(entry, "[[edit]]", file),
    )


def _validate_exclude_membership(
    regenerate: tuple[_RegenerateDeclaration, ...],
    reset: tuple[_ResetDeclaration, ...],
    edit: tuple[_EditDeclaration, ...],
    exclude_files: frozenset[str],
) -> None:
    """Each mechanism's exclude_files contract, checked AFTER writer overlaps.

    The three contracts are not independent: a [[regenerate]] output and a
    [[reset]] target MUST be excluded, while an [[edit]] target must NOT be —
    so a file declared as both can satisfy neither, and running these checks
    inside the per-entry parsers made the real fault (two writers for one
    file) unreachable behind an exclusion message its author could not act
    on. Overlaps are settled first; only then does membership speak.

    That inversion also means one platform-neutral exclude_files cannot
    answer for a file whose writers are platform-disjoint (an [[edit]] on
    darwin, a [[reset]] on win32) — so the edit refusal stands down for
    exactly that pairing, and _select_rules drops the path from the
    exclusions of the platforms where the edit is the active writer.

    That stand-down is EXACT-SPELLING only: the edit target must appear
    verbatim in exclude_files and the paired [[reset]]/[[regenerate]] must
    name that same verbatim path. Alias identity widens what counts as one
    file, which is the safe direction for a refusal and the unsafe direction
    for a grant — `meta.toml` and `META.TOML.`, like a composed and a
    decomposed spelling of one name, really are two files on Linux and on
    case- and normalization-sensitive APFS, so licensing on alias identity
    would let an edit on one of them un-exclude the other, a path no
    declaration writes at all.
    Anything matching only by alias is refused here instead.

    That stand-down reaches TARGET-added exclusions only. A path in
    DEFAULT_RULES.exclude_files is press's own answer, not the target's: a
    lockfile or a changelog is excluded because the replace pass must never
    rewrite it, whatever else the file is declared as. Letting a disjoint
    [[reset]]/[[regenerate]] license it would turn a pairing the author
    controls into a lever that hands those files to the replace pass.

    Every REFUSAL here tests by filesystem-alias identity
    (_control_alias_key), not raw string — the union _reject_reserved
    documents. A raw comparison fails OPEN: `BUN.lock.` aliases `bun.lock` on
    case-insensitive filesystems and Windows, so the exclusion could simply be
    out-spelled. Only the licence above reads exact strings, and only because
    it grants rather than denies.
    """
    paired_files = [declaration.rule.file for declaration in regenerate] + [
        declaration.rule.file for declaration in reset
    ]
    paired = {_control_alias_key(file) for file in paired_files}
    paired_exact = set(paired_files)
    # Alias key -> one declared writer spelling, so the licence diagnostic can
    # quote the path the discarding writer actually names.
    paired_spelling: dict[str, str] = {}
    for file in sorted(paired_files):
        paired_spelling.setdefault(_control_alias_key(file), file)
    default_keys = {_control_alias_key(file) for file in DEFAULT_RULES.exclude_files}
    # Alias key -> one declared spelling, so a diagnostic can name the entry
    # the author actually wrote rather than the normalized key.
    excluded: dict[str, str] = {}
    for entry in sorted(exclude_files):
        excluded.setdefault(_control_alias_key(entry), entry)
    for regenerate_declaration in regenerate:
        file = regenerate_declaration.rule.file
        if file not in exclude_files:
            raise ValidationError(
                f"{RULES_REL}: [[regenerate]] output {file!r} must be listed in "
                f"exclude_files (add it to [rules] extra_exclude_files) — a "
                f"non-excluded output is rewritten by the replace pass and then "
                f"immediately overwritten by the declared command"
            )
    for reset_declaration in reset:
        file = reset_declaration.rule.file
        if file not in exclude_files:
            raise ValidationError(
                f"{RULES_REL}: [[reset]] target {file!r} must be listed in "
                f"exclude_files (add it to [rules] extra_exclude_files) — a "
                f"non-excluded target is also rewritten by the replace pass, so "
                f"the result would depend on pass order"
            )
    for edit_declaration in edit:
        file = edit_declaration.rule.file
        key = _control_alias_key(file)
        if key not in excluded:
            continue
        # Name the exact entry when there is one; the alias note fires only
        # when the exclusion really is spelled differently from the edit.
        listed = file if file in exclude_files else excluded[key]
        alias_note = (
            ""
            if listed == file
            else f" (listed as {listed!r} — one file on a case-insensitive, "
            f"normalization-insensitive, or Windows filesystem)"
        )
        if key in default_keys:
            raise ValidationError(
                f"{RULES_REL}: [[edit]] target {file!r} must not be listed in "
                f"exclude_files{alias_note} — an edit target is rewritten by "
                f"the replace pass first, then edited in place; press excludes "
                f"this path by default, so no target declaration makes it "
                f"editable (a platform-disjoint [[reset]]/[[regenerate]] "
                f"included)"
            )
        # `paired` is only reachable across disjoint platforms — a shared one
        # was already refused as two writers by _validate_writer_overlaps.
        if key not in paired:
            raise ValidationError(
                f"{RULES_REL}: [[edit]] target {file!r} must not be listed in "
                f"exclude_files{alias_note} — an edit target is rewritten by "
                f"the replace pass first, then edited in place"
            )
        # The licence GRANTS, so it may not widen: alias-equal spellings are
        # distinct files wherever the filesystem is case-sensitive, and
        # un-excluding by alias would expose one that has no writer.
        if file not in exclude_files or file not in paired_exact:
            mismatches: list[str] = []
            if file not in exclude_files:
                mismatches.append(f"the exclude_files entry reads {listed!r}")
            if file not in paired_exact:
                mismatches.append(
                    f"the paired [[reset]]/[[regenerate]] target reads "
                    f"{paired_spelling[key]!r}"
                )
            raise ValidationError(
                f"{RULES_REL}: [[edit]] target {file!r} must not be listed in "
                f"exclude_files — the platform-disjoint exception requires the "
                f"edit target, the exclusion entry, and the discarding "
                f"[[reset]]/[[regenerate]] target to be spelled identically, "
                f"but {' and '.join(mismatches)}; those spellings name one "
                f"file only where the filesystem is case- or normalization-"
                f"insensitive, so honoring the pairing would un-exclude a "
                f"path nothing writes"
            )


def _validate_writer_overlaps(
    regenerate: tuple[_RegenerateDeclaration, ...],
    reset: tuple[_ResetDeclaration, ...],
    remove: tuple[_RemoveDeclaration, ...] = (),
    edit: tuple[_EditDeclaration, ...] = (),
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

    # Keyed by filesystem-alias identity, not by declared string: `meta.toml`
    # and `META.TOML.` can be one file on case-insensitive macOS or Windows,
    # as can two canonically equivalent spellings on APFS or HFS+.
    # Rules validate the conservative union documented by _reject_reserved, so
    # a raw-string ledger would let the second writer in under another spelling.
    # Diagnostics still quote what was written.
    seen_edit: dict[str, list[tuple[str, frozenset[str]]]] = {}
    for declaration in edit:
        file = declaration.rule.file
        key = _control_alias_key(file)
        for earlier_file, earlier in seen_edit.get(key, []):
            overlap = earlier & declaration.platforms
            if overlap:
                alias_note = (
                    ""
                    if earlier_file == file
                    else f"; {file!r} and {earlier_file!r} are one file on a "
                    f"case-insensitive, normalization-insensitive, or Windows "
                    f"filesystem"
                )
                raise ValidationError(
                    f"{RULES_REL}: duplicate [[edit]] target {file!r} has "
                    f"platform overlap {sorted(overlap)!r} — each platform "
                    f"permits one writer{alias_note}"
                )
        seen_edit.setdefault(key, []).append((file, declaration.platforms))
    # An edit AMENDS what the replace pass wrote; a reset, removal, or
    # regeneration DISCARDS it. Both on one file is not an ordering question
    # with a right answer — it is two writers, so it is refused.
    for edit_declaration in edit:
        file = edit_declaration.rule.file
        key = _control_alias_key(file)
        for other_kind, others in (
            ("[[regenerate]]", regenerate),
            ("[[reset]]", reset),
            ("[[remove]]", remove),
        ):
            for other in others:
                other_file = other.rule.file
                if _control_alias_key(other_file) != key:
                    continue
                overlap = other.platforms & edit_declaration.platforms
                if overlap:
                    alias_note = (
                        ""
                        if other_file == file
                        else f" as {other_file!r} (the two spellings are one "
                        f"file on a case-insensitive, normalization-"
                        f"insensitive, or Windows filesystem)"
                    )
                    raise ValidationError(
                        f"{RULES_REL}: [[edit]] target {file!r} may not also "
                        f"be a reset/remove/regenerate target — {other_kind} "
                        f"declares it on {sorted(overlap)!r}{alias_note}"
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
    raw_edit = data.get("edit", [])
    if not isinstance(raw_edit, list) or any(not isinstance(e, dict) for e in raw_edit):
        raise ValidationError(f"{RULES_REL}: [[edit]] must be an array of tables")
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
    regenerate = tuple(_parse_regenerate(e) for e in raw_regenerate)
    reset = tuple(_parse_reset(e) for e in raw_reset)
    remove = tuple(_parse_remove(e) for e in raw_remove)
    edit = tuple(_parse_edit(e) for e in raw_edit)
    _validate_writer_overlaps(regenerate, reset, remove, edit)
    _validate_exclude_membership(regenerate, reset, edit, exclude_files)
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
        edit=edit,
    )


def _select_rules(parsed: _ParsedRules, platform: str) -> SelectedRules:
    """Purely select active rules for one already-captured runtime value."""

    if platform not in SUPPORTED_PLATFORMS:
        raise ValidationError(
            f"unsupported runtime platform {platform!r}; expected one of "
            f"{sorted(SUPPORTED_PLATFORMS)!r}"
        )
    active_edits = tuple(
        declaration.rule
        for declaration in parsed.edit
        if platform in declaration.platforms
    )
    # Exact strings, deliberately: config load already refused every pairing
    # whose exclusion entry or discarding writer was spelled differently from
    # the edit target, so the licensed path is always listed verbatim. An
    # alias-keyed subtraction would additionally drop alias-equivalent
    # entries, which are separate files on Linux and case-sensitive APFS with
    # no writer of their own.
    active_edit_paths = {rule.file for rule in active_edits}
    rules = replace(
        parsed.rules,
        # An edit target must be reachable by the replace pass. It can only be
        # in exclude_files at all when the TARGET added it (via [rules]
        # extra_exclude_files) and a [[reset]]/[[regenerate]] on a DISJOINT
        # platform needs it there; config load refuses every other case,
        # DEFAULT_RULES.exclude_files paths included. Dropping the active edit
        # paths is exactly that exception — the discarding platform, where no
        # edit is active, keeps them.
        exclude_files=frozenset(
            path for path in parsed.rules.exclude_files if path not in active_edit_paths
        ),
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
        edit=active_edits,
    )
    return SelectedRules(platform=platform, rules=rules)


def load_selected_rules(target: Path, *, platform: str | None = None) -> SelectedRules:
    """Parse all declarations, then select once for the captured platform."""

    parsed = _parse_rules(target)
    return _select_rules(parsed, sys.platform if platform is None else platform)


def load_rules(target: Path) -> Rules:
    """Compatibility view of active rules for callers not yet carrying selection."""

    return load_selected_rules(target).rules
