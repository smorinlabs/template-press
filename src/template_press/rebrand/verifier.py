"""Occurrence-level scanner for `press verify` — the paranoid scan at the
heart of the no-leak gate (Task 7).

Unlike `doctor.find_leaks` (presence/absence only), `scan` returns one
`Finding` per OCCURRENCE — with line/column for content matches — so a
caller (Task 8) can report exactly where and how many times a source
identity value survives. This module COMPOSES existing primitives rather
than reinventing them:

- `matcher.find_occurrences` (Task 5) — boundary-aware occurrence search,
  with an opt-in `substring` escape hatch per field.
- `engine.scan_paths` / `PathEntry` / `_is_root_press` (Task 6 / Task 2) —
  the no-leak scan's candidate inventory (type-tagged `file|symlink|
  gitlink`, already excluding regenerable lockfiles / `ROOT_CONTROL` /
  `verify_ignore`) and the protected-root `press/` component skip.
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

import os
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import _is_root_press, scan_paths
from template_press.rebrand.identity import Identity
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.rules import Rules
from template_press.rebrand.safety import is_regular_lstat


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


def _changed_fields(
    source: Identity, dest: Identity, fields: Sequence[str]
) -> list[tuple[str, str]]:
    """(field, source_value) pairs for fields that actually differ.

    An unchanged field (e.g. an unchanged `author` across a rename) is not a
    leak — its token legitimately remains everywhere — so it is never
    scanned for.
    """
    src, dst = source.as_dict(), dest.as_dict()
    return [(f, src[f]) for f in fields if src[f] != dst[f]]


def _scan_path_components(
    rel: Path,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
) -> list[Finding]:
    """Every path component (all kinds) — a hit on the LAST part is a
    ``filename`` finding, on any earlier part a ``dirname`` finding. The
    protected root ``press/`` control-dir component is skipped.
    """
    findings: list[Finding] = []
    last_index = len(rel.parts) - 1
    for i, comp in enumerate(rel.parts):
        if _is_root_press(rel, i):
            continue
        where = "filename" if i == last_index else "dirname"
        for f, value in changed:
            substring = f in substring_fields
            for _start, _end in find_occurrences(comp, f, value, substring=substring):
                findings.append(Finding(posix, f, value, where, None, None, comp))
    return findings


def _scan_symlink(
    target: Path,
    rel: Path,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
) -> list[Finding]:
    """Scan the symlink's `readlink` STRING only — never the destination.

    Applies unconditionally to dir and dangling symlinks alike: the
    destination is never opened, so whether it exists (or what kind of node
    it is) is irrelevant to this scan.
    """
    try:
        link = os.readlink(target / rel)
    except OSError:
        # `scan_paths` tagged this entry "symlink" from an earlier lstat that
        # may be stale by now (TOCTOU), or a transient I/O error prevents the
        # read. Never guess — flag it unscannable, mirroring `_scan_file`.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    findings: list[Finding] = []
    for f, value in changed:
        substring = f in substring_fields
        for _start, _end in find_occurrences(link, f, value, substring=substring):
            findings.append(Finding(posix, f, value, "symlink", None, None, link))
    return findings


def _scan_content(
    text: str,
    posix: str,
    changed: list[tuple[str, str]],
    substring_fields: Collection[str],
) -> list[Finding]:
    """Line-by-line content scan; two matches on one line yield two findings
    with distinct ``col`` (the span start, `find_occurrences` is already
    non-overlapping)."""
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for f, value in changed:
            substring = f in substring_fields
            for start, _end in find_occurrences(line, f, value, substring=substring):
                findings.append(
                    Finding(posix, f, value, "content", lineno, start, line)
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
) -> list[Finding]:
    path = target / rel
    if not is_regular_lstat(path):
        # Defense-in-depth TOCTOU guard: `scan_paths` tagged this entry
        # "file" from an earlier lstat that may be stale by now (or, in
        # principle, an on-disk node git cannot represent). Never follow,
        # never guess — flag it unscannable rather than silently skip.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    try:
        data = path.read_bytes()
    except OSError:
        # `where="unscannable"` is reserved for real I/O errors ONLY.
        return [Finding(posix, "io", "unreadable", "unscannable", None, None, "")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _scan_binary(data, posix, changed, substring_fields)
    return _scan_content(text, posix, changed, substring_fields)


def scan(
    target: Path,
    source: Identity,
    dest: Identity,
    *,
    fields: Sequence[str],
    substring_fields: Collection[str],
    rules: Rules,
) -> list[Finding]:
    """Occurrence-level scan of ``target`` for surviving SOURCE identity.

    Changed-fields only (see `_changed_fields`); scans the SOURCE value.
    Iterates `scan_paths(target, rules)`. For every entry, ALL kinds get a
    path-component scan (`_scan_path_components`); a `gitlink` entry gets
    nothing more (submodule boundary — no content/byte read); a `symlink`
    entry additionally gets its `readlink` text scanned
    (`_scan_symlink` — never the destination); a `file` entry additionally
    gets its content or bytes scanned (`_scan_file`).

    Raw findings only — no ignoring, no deduping (Task 8's job). Order is
    stable: `scan_paths` is already sorted by path, and within one path,
    findings are emitted in scan order (path components, then
    symlink/content/binary).
    """
    changed = _changed_fields(source, dest, fields)
    findings: list[Finding] = []
    for entry in scan_paths(target, rules):
        rel = entry.rel
        posix = rel.as_posix()
        findings.extend(_scan_path_components(rel, posix, changed, substring_fields))
        if entry.kind == "gitlink":
            continue
        if entry.kind == "symlink":
            findings.extend(
                _scan_symlink(target, rel, posix, changed, substring_fields)
            )
            continue
        findings.extend(_scan_file(target, rel, posix, changed, substring_fields))
    return findings
