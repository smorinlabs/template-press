"""Occurrence-level scanner for `press verify` — the paranoid scan at the
heart of the no-leak gate (Task 7).

Unlike `doctor.find_leaks` (presence/absence only), `scan` returns one
`Finding` per OCCURRENCE — with line/column for content matches — so a
caller (Task 8) can report exactly where and how many times a source
identity value survives. This module composes neutral primitives without
importing table consumers:

- `matcher.find_occurrences` (Task 5) — boundary-aware occurrence search,
  with an opt-in `substring` escape hatch per field.
- `inventory.SurfaceSnapshot` and its selectors — the kind-tagged candidate
  inventory and pre-press source facts used to derive scoped path-rule
  ancestor triggers independently.
- `pathing` — neutral path translation, rule-scope, root-protection, and
  symlink-target helpers.
- `safety.is_regular_lstat` (Task 0.5) — a no-follow regular-file guard so
  content is never read through a link.

Never-follow guarantee: a `kind == "symlink"` entry is scanned by its
`os.readlink` text ONLY — the destination is NEVER opened, dir or dangling
alike. This closes the Task-3 I2 gap: a dir/dangling symlink whose readlink
text embeds a changed identity value now produces a `where="symlink"`
finding regardless of what (if anything) it points at.

Changed-fields only: a field that is IDENTICAL between `source` and `dest`
is not a leak (its token legitimately remains everywhere) and is never
scanned. Raw findings only — no ignoring, no deduping (Task 8's job); no
`Identity.validate()` call either (the caller's concern, same as
`doctor.find_leaks`).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.identity import Identity
from template_press.rebrand.inventory import (
    SurfaceSnapshot,
    capture_surface_snapshot,
    select_rename_entries,
    select_verifier_entries,
)
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.pathing import (
    ROOT_CONTROL,
    exempt_regenerated_paths,
    is_root_press,
    reverse_renamed_path,
    rule_scope_hits,
    symlink_target_posix,
)
from template_press.rebrand.rules import (
    ReplaceRule,
    Rules,
    render_replace_pattern,
    rule_matches_path,
)
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    is_regular_lstat,
    read_regular_nofollow,
    readlink_nofollow,
)


@dataclass(frozen=True)
class Finding:
    """One occurrence of a changed source-identity value in the target.

    ``where`` is one of ``"content" | "filename" | "dirname" | "symlink" |
    "binary" | "unscannable"``. ``line``/``col`` are populated only for
    ``"content"`` (1-based line number, character offset within the line)
    and ``"binary"`` (``line=None``, byte offset into the file); every other
    ``where`` carries ``line=None, col=None``.

    An ``"unscannable"`` finding is field-agnostic (an I/O error prevents
    scanning regardless of which field might have been present) but still
    needs a non-``None`` ``field``/``value`` pair so it remains ignorable by
    a `field` + path-anchor ignore rule (Task 8): it carries
    ``field="io", value="unreadable"``, mirroring the existing
    ``doctor.Leak(rel, "io", "unreadable", ...)`` convention.
    """

    path: str
    field: str
    value: str
    where: str
    line: int | None
    col: int | None
    context: str


@dataclass(frozen=True)
class _ScanEntry:
    """Verifier-local view of one neutral inventory entry."""

    rel: Path
    kind: str


@dataclass(frozen=True)
class _RuleScanSpec:
    """One independently rendered rule plus its source ancestor triggers."""

    rule: ReplaceRule
    from_value: str
    to_value: str
    trigger_prefixes: tuple[str, ...]


def _rule_scan_specs(
    source: Identity,
    dest: Identity,
    rules: Rules,
    source_snapshot: SurfaceSnapshot,
) -> tuple[_RuleScanSpec, ...]:
    """Render rules and derive path triggers from the neutral source snapshot."""

    rename_entries = select_rename_entries(
        source_snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    specs: list[_RuleScanSpec] = []
    for rule in rules.replace:
        from_value = render_replace_pattern(rule.pattern, source)
        to_value = render_replace_pattern(rule.pattern, dest)
        if from_value == to_value:
            continue
        trigger_prefixes: set[str] = set()
        if rule.paths:
            for entry in rename_entries:
                posix = entry.rel.as_posix()
                if not rule_matches_path(rule, posix):
                    continue
                for index, component in enumerate(entry.rel.parts):
                    if is_root_press(entry.rel, index):
                        continue
                    if component.replace(from_value, to_value) == component:
                        continue
                    trigger_prefixes.add(Path(*entry.rel.parts[: index + 1]).as_posix())
                    break
        specs.append(
            _RuleScanSpec(
                rule=rule,
                from_value=from_value,
                to_value=to_value,
                trigger_prefixes=tuple(sorted(trigger_prefixes)),
            )
        )
    return tuple(specs)


def _changed_fields(
    source: Identity, dest: Identity, fields: Sequence[str]
) -> list[tuple[str, str]]:
    """(field, source_value) pairs for fields that actually differ.

    An unchanged field (e.g. an unchanged `author` across a rename) is not a
    leak — its token legitimately remains everywhere — so it is never
    scanned for. Total under the sparse identity dicts: a field absent on
    either side (optional `display_name`) is simply not scanned.
    """
    src, dst = source.as_dict(), dest.as_dict()
    return [(f, src[f]) for f in fields if f in src and f in dst and src[f] != dst[f]]


def _substring_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    """Non-overlapping start/end spans of a LITERAL substring.

    A rendered ``[[replace]]`` FROM literal is an exact string (no boundary
    heuristics — codesign sec-02), unlike an identity field's
    `find_occurrences`. Mirrors `_scan_binary`'s own needle-find loop; an
    empty needle would match everywhere (`str.find("", pos) == pos`) so it
    is guarded out rather than looping forever.
    """
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx == -1:
            break
        spans.append((idx, idx + len(needle)))
        pos = idx + len(needle)
    return spans


def _rule_path_matches(
    posix: str,
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
    *,
    paths: bool,
) -> list[_RuleScanSpec]:
    """Independently rendered rules whose declared scope includes a path."""

    return [
        spec
        for spec in rule_specs
        if (spec.rule.paths if paths else spec.rule.content)
        and rule_scope_hits(spec.rule, posix, renamed)
    ]


def _rule_symlink_matches(
    target_posix: str,
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
) -> list[_RuleScanSpec]:
    """Select path rules by direct scope or a source ancestor trigger."""

    source_target = reverse_renamed_path(target_posix, renamed)
    return [
        spec
        for spec in rule_specs
        if spec.rule.paths
        and (
            rule_scope_hits(spec.rule, target_posix, renamed)
            or any(
                source_target == prefix or source_target.startswith(f"{prefix}/")
                for prefix in spec.trigger_prefixes
            )
        )
    ]


def _scan_path_components(
    rel: Path,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
) -> list[Finding]:
    """Every path component (all kinds) — a hit on the LAST part is a
    ``filename`` finding, on any earlier part a ``dirname`` finding. The
    protected root ``press/`` control-dir component is skipped.
    """
    findings: list[Finding] = []
    last_index = len(rel.parts) - 1
    path_rules = _rule_path_matches(posix, rule_specs, renamed, paths=True)
    for i, comp in enumerate(rel.parts):
        if is_root_press(rel, i):
            continue
        where = "filename" if i == last_index else "dirname"
        for f, value in changed:
            substring = f in substring_fields
            for _start, _end in find_occurrences(comp, f, value, substring=substring):
                findings.append(Finding(posix, f, value, where, None, None, comp))
        for spec in path_rules:
            for _start, _end in _substring_occurrences(comp, spec.from_value):
                findings.append(
                    Finding(
                        posix,
                        "replace_rule",
                        spec.from_value,
                        where,
                        None,
                        None,
                        comp,
                    )
                )
    return findings


def _scan_symlink(
    target: Path,
    rel: Path,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
) -> list[Finding]:
    """Scan the symlink's `readlink` STRING only — never the destination.

    Applies unconditionally to dir and dangling symlinks alike: the
    destination is never opened, so whether it exists (or what kind of node
    it is) is irrelevant to this scan.
    """
    try:
        link = readlink_nofollow(target / rel)
    except (OSError, SafetyError):
        # `scan_paths` tagged this entry "symlink" from an earlier lstat that
        # may be stale by now (TOCTOU), or a transient I/O error prevents the
        # read. Never guess — flag it unscannable, mirroring `_scan_file`.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    findings: list[Finding] = []
    for f, value in changed:
        substring = f in substring_fields
        for _start, _end in find_occurrences(link, f, value, substring=substring):
            findings.append(Finding(posix, f, value, "symlink", None, None, link))
    # Rule scope for symlink text is the link's TARGET, normalized — mirroring
    # `_retarget_symlinks`/`doctor.find_leaks` — never the link's own location.
    link_target_posix = symlink_target_posix(rel, link)
    rule_hits = _rule_symlink_matches(link_target_posix, rule_specs, renamed)
    for spec in rule_hits:
        for _start, _end in _substring_occurrences(link, spec.from_value):
            findings.append(
                Finding(
                    posix,
                    "replace_rule",
                    spec.from_value,
                    "symlink",
                    None,
                    None,
                    link,
                )
            )
    return findings


def _scan_content(
    text: str,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
) -> list[Finding]:
    """Line-by-line content scan; two matches on one line yield two findings
    with distinct ``col`` (the span start, `find_occurrences` is already
    non-overlapping)."""
    findings: list[Finding] = []
    content_rules = _rule_path_matches(posix, rule_specs, renamed, paths=False)
    for lineno, line in enumerate(text.splitlines(), start=1):
        for f, value in changed:
            substring = f in substring_fields
            for start, _end in find_occurrences(line, f, value, substring=substring):
                findings.append(
                    Finding(posix, f, value, "content", lineno, start, line)
                )
        for spec in content_rules:
            for start, _end in _substring_occurrences(line, spec.from_value):
                findings.append(
                    Finding(
                        posix,
                        "replace_rule",
                        spec.from_value,
                        "content",
                        lineno,
                        start,
                        line,
                    )
                )
    return findings


def _scan_binary(
    data: bytes,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
) -> list[Finding]:
    """Byte-scan a non-UTF-8 file for surviving identity — VARIANT-aware.

    ``apply()`` cannot rewrite binary content, so a separator/case variant of a
    source value (``demo-widget`` / ``demoWidget`` for ``demo_widget``) survives
    the press. An exact-only byte scan missed it (a FALSE CLEAN in a binary
    artifact). The bytes are decoded latin-1 (1:1 byte<->codepoint, always
    succeeds) and run through the SAME identifier-aware matcher used for text
    (`find_occurrences`), so separator/case/camelCase variants are caught
    consistently; because latin-1 is 1:1, a match's char span start IS its byte
    offset (``col``), with ``line=None``.

    The raw exact-byte occurrences are unioned in as well: a binary offers no
    notion of "word boundary", so an exact value glued to surrounding
    letters/digits (which the identifier-boundary matcher deliberately rejects)
    must still be flagged. Offsets are deduplicated so an exact match that both
    scans find yields a single ``binary`` finding.
    """
    latin1 = data.decode("latin-1")
    findings: list[Finding] = []
    for f, value in changed:
        needle = value.encode("utf-8")
        if not needle:
            # An empty value matches at every offset (both the matcher and
            # `data.find(b"")`), so it is skipped. Identity is validated
            # non-empty upstream; this keeps the invariant local (and bounded).
            continue
        substring = f in substring_fields
        offsets = {
            start
            for start, _end in find_occurrences(latin1, f, value, substring=substring)
        }
        pos = 0
        while True:
            idx = data.find(needle, pos)
            if idx == -1:
                break
            offsets.add(idx)
            pos = idx + len(needle)
        findings.extend(
            Finding(posix, f, value, "binary", None, idx, "") for idx in sorted(offsets)
        )
    return findings


def _scan_file(
    target: Path,
    rel: Path,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
    rule_specs: Sequence[_RuleScanSpec],
    renamed: list[tuple[str, str]],
) -> list[Finding]:
    path = target / rel
    try:
        assert_ancestors_real(path, target)
    except SafetyError:
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    if not is_regular_lstat(path):
        # Defense-in-depth TOCTOU guard: `scan_paths` tagged this entry
        # "file" from an earlier lstat that may be stale by now (or, in
        # principle, an on-disk node git cannot represent). Never follow,
        # never guess — flag it unscannable rather than silently skip.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    try:
        data = read_regular_nofollow(path)
    except (OSError, SafetyError):
        # `where="unscannable"` is reserved for real I/O errors ONLY.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # `apply()` cannot rewrite binary content via a [[replace]] rule any
        # more than it can via the token pass, so a rule-literal scan of
        # binary bytes is not attempted (mirrors `doctor.find_leaks`, which
        # only rule-scans `_read_for_scan`-returned TEXT).
        return _scan_binary(data, posix, changed, substring_fields)
    return _scan_content(text, posix, changed, substring_fields, rule_specs, renamed)


def scan(
    target: Path,
    source: Identity,
    dest: Identity,
    *,
    fields: Sequence[str],
    substring_fields: Collection[str],
    rules: Rules,
    renamed: list[tuple[str, str]] | None = None,
    source_snapshot: SurfaceSnapshot | None = None,
) -> list[Finding]:
    """Occurrence-level scan of ``target`` for surviving SOURCE identity.

    Changed-fields only (see `_changed_fields`); scans the SOURCE value.
    Iterates a neutral verifier selection. For every entry, ALL kinds get a
    path-component scan (`_scan_path_components`); a `gitlink` entry gets
    nothing more (submodule boundary — no content/byte read); a `symlink`
    entry additionally gets its `readlink` text scanned
    (`_scan_symlink` — never the destination); a `file` entry additionally
    gets its content or bytes scanned (`_scan_file`).

    Declared rules are rendered independently from ``source``, ``dest``, and
    ``rules``. Their exact source literals provide a rule-only matcher for a
    boundary-unmatched rendered FROM literal that survives an unrewriteable
    spot (an escaping symlink target the retarget pass refuses to touch, a
    stale filename left by 0008's rewrite-side scope-migration limitation)
    is otherwise invisible to the ordinary field-based scan above. Each
    rule is scanned scoped by what it was supposed to touch, mirroring
    ``doctor.find_leaks`` exactly: content rules against file CONTENT
    (glob-scoped via ``rule_matches_path`` against the file's own rel
    posix), and paths rules against PATH COMPONENTS (glob-scoped the same
    way) and SYMLINK text (scoped against the link TARGET's normalized rel
    path via ``pathing.symlink_target_posix``). ``renamed`` (``ApplyReport.
    renamed`` — available at the verify sandbox's press call site) lets
    each scope check recover a scanned path/symlink-target's PRE-rename
    original before testing ``rule.files``, exactly as
    ``pathing.rule_scope_hits`` does; omitted, this degrades to
    current-path-only scoping. ``source_snapshot`` is the neutral pre-press
    inventory used to derive scoped ancestor triggers independently from the
    table's rename plan. Findings carry ``field="replace_rule"``.

    Raw findings only — no ignoring, no deduping (Task 8's job). Order is
    stable by selected path and then scan order (path components followed by
    symlink, content, or binary evidence).
    """
    changed = _changed_fields(source, dest, fields)
    renamed = renamed or []
    findings: list[Finding] = []
    # `renamed` also drives the regeneration exemption (P04 D3): declared
    # source-coordinate outputs are exempt at their POST-rename locations.
    exempt_paths = frozenset(
        path for path, _reason in exempt_regenerated_paths(rules, renamed)
    )
    snapshot = capture_surface_snapshot(target)
    rule_specs = _rule_scan_specs(
        source,
        dest,
        rules,
        source_snapshot or snapshot,
    )
    selected = select_verifier_entries(
        snapshot,
        verify_ignore=rules.verify_ignore,
        root_control=ROOT_CONTROL,
        exempt_paths=exempt_paths,
    )
    entries: list[_ScanEntry] = []
    for entry in selected:
        if entry.worktree_kind == "symlink":
            kind = "symlink"
        elif entry.worktree_kind == "file":
            kind = "file"
        elif entry.index_kind == "gitlink" and entry.worktree_kind in (
            "directory",
            "missing",
        ):
            kind = "gitlink"
        else:
            kind = "unscannable"
        entries.append(_ScanEntry(entry.rel, kind))
    for entry in entries:
        rel = entry.rel
        posix = rel.as_posix()
        findings.extend(
            _scan_path_components(
                rel, posix, changed, substring_fields, rule_specs, renamed
            )
        )
        if entry.kind == "gitlink":
            continue
        if entry.kind == "symlink":
            findings.extend(
                _scan_symlink(
                    target,
                    rel,
                    posix,
                    changed,
                    substring_fields,
                    rule_specs,
                    renamed,
                )
            )
            continue
        if entry.kind == "unscannable":
            findings.append(
                Finding(
                    posix,
                    "io",
                    "unreadable",
                    "unscannable",
                    None,
                    None,
                    "",
                )
            )
            continue
        findings.extend(
            _scan_file(
                target, rel, posix, changed, substring_fields, rule_specs, renamed
            )
        )
    return findings
