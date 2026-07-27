"""The [[reset]] mechanism — stub loading and the stub-content scan (P05).

Reset reads bytes as text, FAIL CLOSED (D6): the target's current content
and any ``stub_file`` must decode as UTF-8 at plan time — the line count,
the verbose excerpt, and the stub scan all interpret text — and undecodable
bytes refuse the press. And a stub may not itself restore the identity its
reset exists to remove: stub content passes the same changed-only paranoid
identity and rendered-``[[replace]]``-literal scan the post-command check
uses (P04 D3's evidence standard), whatever its source.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import rendered_replace_rules, translate_path
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.regen import (
    changed_identity_pairs,
    has_uncommitted_changes,
    tracked_paths,
)
from template_press.rebrand.rules import ResetRule, Rules, rule_matches_path
from template_press.rebrand.safety import (
    ContainmentError,
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    chmod_nofollow,
    is_regular_lstat,
    safe_write,
)

# D2 (decided 2026-07-26): the verbose preview excerpt is bounded — the
# motivating target is a release history running to thousands of lines.
VERBOSE_PREVIEW_LINES = 20


def _read_utf8(path: Path, what: str) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"{what}: cannot read: {exc}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{what} is not valid UTF-8 — reset reads bytes as text, fail "
            f"closed ({exc})"
        ) from exc


def _contained_regular(target: Path, rel: str, what: str) -> Path:
    path = target / rel
    try:
        assert_under_root(path, target)
    except SafetyError as exc:
        raise ValidationError(f"{what}: {exc}") from exc
    if not is_regular_lstat(path):
        raise ValidationError(
            f"{what} is not a regular file (missing, symlink, or special — "
            f"no-follow check)"
        )
    return path


def load_stub_content(target: Path, rule: ResetRule) -> str:
    """The stub text that will replace ``rule.file`` — UTF-8 fail-closed.

    Inline ``stub`` is returned verbatim (an empty string legitimately
    blanks the file); ``stub_file`` is read under the same containment
    predicates as every other declared path.
    """
    if rule.stub is not None:
        return rule.stub
    if rule.stub_file is None:  # config-load enforces the XOR; fail loud
        raise ValidationError(
            f"[[reset]] {rule.file}: neither stub nor stub_file present"
        )
    what = f"[[reset]] {rule.file}: stub_file {rule.stub_file}"
    path = _contained_regular(target, rule.stub_file, what)
    return _read_utf8(path, what)


def read_reset_target_text(target: Path, rule: ResetRule) -> str:
    """The reset target's CURRENT text (plan-time read, UTF-8 fail-closed)."""
    what = f"[[reset]] target {rule.file}"
    path = _contained_regular(target, rule.file, what)
    return _read_utf8(path, what)


def scan_stub_text(
    text: str,
    *,
    rel: str,
    source: Identity,
    dest: Identity,
    rules: Rules,
) -> list[str]:
    """Problems where the stub would RESTORE identity its reset removes.

    Changed-only (an unchanged field legitimately remains — flagging it
    would fail every partial rebrand), with the paranoid matcher for
    identity fields and exact literals for rendered ``[[replace]]`` FROM
    sides (``rendered_replace_rules`` already drops FROM == TO pairs).
    """
    problems: list[str] = []
    for field, value in changed_identity_pairs(source, dest):
        spans = find_occurrences(
            text, field, value, substring=field in rules.substring_rewrite_fields
        )
        if spans:
            problems.append(
                f"stub for {rel} contains source {field} {value!r} "
                f"({len(spans)} occurrence(s)) — a stub may not restore the "
                f"identity its reset removes"
            )
    for replace_rule, frm, _to in rendered_replace_rules(rules, source, dest):
        if not replace_rule.content:
            continue
        if not rule_matches_path(replace_rule, rel):
            continue
        if frm in text:
            problems.append(
                f"stub for {rel} contains rendered [[replace]] literal "
                f"{frm!r} ({replace_rule.reason})"
            )
    return problems


def scan_reset_path(
    translated: str,
    rel: str,
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
) -> list[str]:
    """The planned reset-path identity scan (wave-3 3654059289).

    An excluded filename can itself carry changed identity
    (``app_name = "changelog"`` → ``CHANGELOG.md``) and downstream
    inventories never look at it (thread 3653398575). Scanned on the
    TRANSLATED (post-rename) path — plan-time-knowable, so exit 2 before
    writes; the final apply-time recheck is retained separately.
    """
    problems: list[str] = []
    for field, value in changed_identity_pairs(source, dest):
        spans = find_occurrences(
            translated,
            field,
            value,
            substring=field in rules.substring_rewrite_fields,
        )
        if spans:
            problems.append(
                f"reset {rel}: its path after this press ({translated}) "
                f"still carries source {field} {value!r} — an excluded "
                f"filename is invisible to every downstream inventory; "
                f"rename the file or route it through verify_ignore"
            )
    for replace_rule, frm, _to in rendered_replace_rules(rules, source, dest):
        if (
            replace_rule.paths
            and rule_matches_path(replace_rule, rel)
            and frm in translated
        ):
            problems.append(
                f"reset {rel}: its path after this press ({translated}) "
                f"carries rendered [[replace]] literal {frm!r} "
                f"({replace_rule.reason})"
            )
    return problems


@dataclass(frozen=True)
class ResetPreview:
    """Plan-time preview of one reset — the always-present line count plus
    the bounded excerpts the --verbose rendering shows."""

    rule: ResetRule
    line_count: int
    current_head: tuple[str, ...]  # first VERBOSE_PREVIEW_LINES lines
    stub_head: tuple[str, ...]
    stub_text: str  # the full stub apply will write


def preflight_reset_targets(
    target: Path,
    rules: Rules,
    *,
    source: Identity,
    dest: Identity,
    renames: Mapping[str, str],
) -> tuple[list[ResetPreview], list[str]]:
    """Validate every reset target at plan time (D5) and build previews.

    Applies the NAMED write-path predicates (``assert_under_root``,
    ``assert_ancestors_real``, ``is_regular_lstat``) so plan-time and
    apply-time cannot drift; requires git-tracked and clean (refused even
    under ``--allow-dirty`` — this function takes no such flag); reads
    target and stub UTF-8 fail-closed; and runs the stub-content and
    translated-path identity scans. Problems refuse the press (exit 2,
    nothing written).
    """
    if not rules.reset:
        return [], []
    previews: list[ResetPreview] = []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.reset:
        prefix = f"reset {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (the guard's purpose is an undo "
                "path, and git restores only committed content)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        if has_uncommitted_changes(target, rule.file):
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (a tracked file carrying unstaged work has "
                "no recoverable copy of that work)"
            )
            continue
        try:
            text = read_reset_target_text(target, rule)
            stub = load_stub_content(target, rule)
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        problems.extend(
            scan_stub_text(stub, rel=rule.file, source=source, dest=dest, rules=rules)
        )
        problems.extend(
            scan_reset_path(
                translate_path(rule.file, renames),
                rule.file,
                source=source,
                dest=dest,
                rules=rules,
            )
        )
        lines = text.splitlines()
        previews.append(
            ResetPreview(
                rule=rule,
                line_count=len(lines),
                current_head=tuple(lines[:VERBOSE_PREVIEW_LINES]),
                stub_head=tuple(stub.splitlines()[:VERBOSE_PREVIEW_LINES]),
                stub_text=stub,
            )
        )
    return previews, problems


def apply_resets(target: Path, resets: Sequence[tuple[ResetRule, str]]) -> list[str]:
    """Write each declared stub — position ZERO, SOURCE coordinates (D5).

    Runs before every other pass: declared paths are written against the
    repo's current layout, so they must be consumed before the rename pass
    moves anything (a stale path would silently CREATE a spurious file).
    Re-applies the same predicates the preflight named, writes via
    ``safe_write`` (atomic temp+rename = new inode, so an external hardlink
    keeps the pre-reset content), and restores the target's original mode
    (thread 3653398581). Any failure PROPAGATES — a failed reset aborts the
    whole press with no receipt (D4); git is the undo button.
    """
    done: list[str] = []
    for rule, stub in resets:
        path = target / rule.file
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
        if not is_regular_lstat(path):
            raise ContainmentError(
                f"reset {rule.file}: not a regular file at apply time (no-follow check)"
            )
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        safe_write(target, rule.file, stub, refuse_hardlink=False)
        chmod_nofollow(path, mode)
        done.append(rule.file)
    return done


def render_reset_plan(previews: list[ResetPreview], *, verbose: bool) -> str:
    """The plan's reset section — never silent (one line per target with
    its lines-based size), with the bounded content excerpt verbose-gated.
    """
    lines = ["Reset (declared stubs, written before every other pass):"]
    for preview in previews:
        lines.append(
            f"  [reset  ] {preview.rule.file}  —  {preview.line_count:,} lines → stub"
        )
        if verbose:
            lines.append(
                f"            current (first {len(preview.current_head)} of "
                f"{preview.line_count:,} lines):"
            )
            lines.extend(f"              | {ln}" for ln in preview.current_head)
            lines.append("            stub:")
            lines.extend(f"              | {ln}" for ln in preview.stub_head)
    return "\n".join(lines)
