"""Source-coordinate, occurrence-pinned, self-policing ignores (Task 8).

The layer between `verifier.scan` (Task 7, raw findings) and the no-leak
gate: it silences the paranoid scanner's FALSE positives — content a fork
legitimately keeps — while REFUSING to let a stale ignore mask a real leak.

Three invariants make it self-policing:

- **Source coordinates.** A finding carries a SANDBOX (pressed) path; an
  ignore is written against the ORIGINAL target, so every finding's path is
  mapped back to source via `build_forward_map` (the reverse of
  `ApplyReport.renamed`) before matching. The newline invariant (identity
  values contain no ``\\n``, see ``identity.py``) guarantees line N in the
  source equals line N in the sandbox, so a content finding's ``line``
  indexes the source file directly — read via the injected ``source_line``.
- **Occurrence pinning, fail-closed.** An ``ordinal``-less ignore that
  matches >=2 findings (an ambiguous anchor+line) is a CONFIG ERROR
  (`ValidationError`) — never a silent multi-suppress. An ``ordinal`` pins
  exactly one occurrence.
- **Staleness = drift.** An ignore that suppresses ZERO findings and is not
  ``force`` is STALE and returned so the caller can flag it.

This module reads NOTHING itself: `source_line` is injected (Task 12 reads
the original target); it never follows anything.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.verifier import Finding

# A finding with no line number anchors against the SOURCE PATH, not a source
# line. The line-less kinds are filename/dirname/symlink components, binary
# byte hits, and unscannable I/O findings — all carry ``line=None`` (see
# verifier.Finding), so we key off ``line is None`` rather than the ``where``
# string: the discriminator can never drift from the data that way.


@dataclass(frozen=True)
class Ignore:
    """One source-anchored suppression rule.

    ``field``/``value`` pin the token (at least ONE required); ``file`` is the
    SOURCE path; ``anchor`` must be a substring of the source line (content) or
    the source path (line-less); ``line`` pins a 1-based source line (or
    ``None`` = any); ``ordinal`` pins the 0-based occurrence index within the
    ``(src_path, field, value, line)`` group (or ``None`` = the unique match);
    ``force`` keeps a zero-match ignore out of the stale set; ``reason`` is
    human rationale.
    """

    field: str | None
    value: str | None
    file: str
    anchor: str
    line: int | None
    ordinal: int | None
    force: bool
    reason: str

    def __post_init__(self) -> None:
        if self.field is None and self.value is None:
            raise ValidationError(
                "ignore must pin at least one of field/value "
                f"(file={self.file!r}, anchor={self.anchor!r})"
            )


def _is_path_prefix(prefix: str, path: str) -> bool:
    """Component-aware POSIX prefix: ``a/b`` prefixes ``a/b/c`` not ``a/bc``."""
    return path == prefix or path.startswith(prefix + "/")


def build_forward_map(renamed: list[tuple[str, str]]) -> Callable[[str], str]:
    """Sandbox (pressed) path -> source path, from ``ApplyReport.renamed``.

    ``renamed`` is a list of ``(old_prefix, new_prefix)`` SOURCE->DEST renames.
    ``engine._apply_renames`` runs MULTIPLE shallowest-prefix passes, so a
    later-pass pair's ``old_prefix`` is in INTERMEDIATE (already-partly-renamed)
    coordinates, not source — e.g. ``src/demo_widget/demo_widget_cli.py`` yields
    ``(src/demo_widget, src/<synth>)`` then
    ``(src/<synth>/demo_widget_cli.py, src/<synth>/<synth>_cli.py)``.

    The returned callable therefore applies the REVERSE longest-prefix
    substitution REPEATEDLY until the path stops changing (a fixpoint): each
    step finds the ``new_prefix`` that is a path-prefix of the current path
    (longest, by component count, wins) and swaps it back to the paired
    ``old_prefix``; unmatched paths pass through unchanged. Convergence is
    guaranteed because synthetic dest components are containment-free vs source
    variants (no rewrite cycles), so it is bounded to ``len(renamed) + 1`` steps
    and RAISES if it fails to converge (that would be a bug, never a hang).
    """

    def _reverse_once(path: str) -> str:
        best: tuple[int, str, str] | None = None
        for old_prefix, new_prefix in renamed:
            if _is_path_prefix(new_prefix, path):
                depth = len(PurePosixPath(new_prefix).parts)
                if best is None or depth > best[0]:
                    best = (depth, old_prefix, new_prefix)
        if best is None:
            return path
        _, old_prefix, new_prefix = best
        return old_prefix + path[len(new_prefix) :]

    def forward_map(path: str) -> str:
        current = path
        for _ in range(len(renamed) + 1):
            nxt = _reverse_once(current)
            if nxt == current:
                return current
            current = nxt
        raise ValidationError(
            f"forward map did not converge for {path!r} after "
            f"{len(renamed) + 1} passes (rename map: {renamed!r})"
        )

    return forward_map


def _occurrence_indices(findings: list[Finding], src_paths: list[str]) -> list[int]:
    """0-based occurrence index of each finding within its
    ``(src_path, field, value, line)`` group.

    Content groups (``line is not None``) are ordered by ``col``; line-less
    groups keep scan order. Computed once, up front, independent of any ignore.
    """
    groups: dict[tuple[str, str, str, int | None], list[int]] = defaultdict(list)
    for i, f in enumerate(findings):
        groups[(src_paths[i], f.field, f.value, f.line)].append(i)
    indices = [0] * len(findings)
    for (_, _, _, line), members in groups.items():
        if line is not None:
            # content: order by column, stable on original scan position
            members = sorted(members, key=lambda i: (findings[i].col or 0, i))
        for occ, i in enumerate(members):
            indices[i] = occ
    return indices


def _anchor_matches(
    ignore: Ignore,
    finding: Finding,
    src_path: str,
    source_line: Callable[[str, int], str | None],
) -> bool:
    """Anchor test: substring of the source line (content) or path (line-less).

    Fails CLOSED — if the source line cannot be read (``source_line`` returns
    ``None``) the anchor is treated as not present.
    """
    if finding.line is None:
        return ignore.anchor in src_path
    line_text = source_line(src_path, finding.line)
    return line_text is not None and ignore.anchor in line_text


def apply_ignores(
    findings: list[Finding],
    ignores: list[Ignore],
    *,
    forward_map: Callable[[str], str],
    source_line: Callable[[str, int], str | None],
) -> tuple[list[Finding], list[Ignore]]:
    """Apply source-anchored ignores to raw findings.

    Returns ``(surviving, stale)``: findings no ignore suppressed, and ignores
    that suppressed zero findings and are not ``force``. An ``ordinal``-less
    ignore matching >=2 findings — or ANY ignore that would suppress >=2 (an
    under-specified anchor spanning lines) — raises ``ValidationError``: fail
    closed, never silently multi-suppress.
    """
    src_paths = [forward_map(f.path) for f in findings]
    occ = _occurrence_indices(findings, src_paths)

    suppressed: set[int] = set()
    matched_counts = [0] * len(ignores)

    for j, ignore in enumerate(ignores):
        matches: list[int] = []
        for i, finding in enumerate(findings):
            src_path = src_paths[i]
            if ignore.file != src_path:
                continue
            if ignore.field is not None and ignore.field != finding.field:
                continue
            if ignore.value is not None and ignore.value != finding.value:
                continue
            if ignore.line is not None and ignore.line != finding.line:
                continue
            if ignore.ordinal is not None and ignore.ordinal != occ[i]:
                continue
            if not _anchor_matches(ignore, finding, src_path, source_line):
                continue
            matches.append(i)
        if len(matches) >= 2:
            # An ordinal pins a UNIQUE occurrence within one line group, so a
            # matched set of >=2 means the anchor+line is ambiguous (or the
            # ignore is under-specified, e.g. no line across repeated lines).
            # Refuse rather than multi-suppress.
            raise ValidationError(
                f"ambiguous ignore matches {len(matches)} findings "
                f"(file={ignore.file!r}, anchor={ignore.anchor!r}, "
                f"line={ignore.line!r}, ordinal={ignore.ordinal!r}); "
                "pin an ordinal to disambiguate"
            )
        matched_counts[j] = len(matches)
        suppressed.update(matches)

    surviving = [f for i, f in enumerate(findings) if i not in suppressed]
    stale = [
        ignore
        for j, ignore in enumerate(ignores)
        if matched_counts[j] == 0 and not ignore.force
    ]
    return surviving, stale
