"""Declared file removal (P08 T2, issue #80).

Template-only files — maintenance CI workflows, dogfood history docs —
must not ship to pressed forks, and the legacy embedded engines deleted
them via their own manifests. ``[[remove]]`` is the press's declared
equivalent. Contract:

- Plan-time preflight applies the NAMED write-path predicates
  (``assert_under_root``, ``assert_ancestors_real``, ``is_regular_lstat``)
  plus git-tracked and clean (refused even under ``--allow-dirty`` — git
  restores only committed content, so deleting uncommitted edits would
  lose data). A declared target that does not exist fails loud: a stale
  ``[[remove]]`` is config drift, never a silent no-op.
- Removal executes AFTER ``apply()`` with the declared SOURCE-coordinate
  path translated through the rename report — the regeneration pattern,
  not position zero: ``apply()`` revalidates the tree against its
  plan-time snapshot, so deleting files before it would break the
  mutation boundary.
- Hermetic verify performs the same removals inside its sandbox. No
  command is needed, so unlike regeneration there is no exemption and no
  coverage gap: a removed file simply vanishes from the scan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.pathing import translate_path
from template_press.rebrand.regen import has_uncommitted_changes, tracked_paths
from template_press.rebrand.rules import Rules
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    is_regular_lstat,
)


@dataclass(frozen=True)
class RemovePreview:
    """One planned removal: the SOURCE-coordinate path and its reason."""

    rel: str
    reason: str


def preflight_remove_targets(target: Path, rules: Rules) -> list[str]:
    """Problems that make a declared removal unpressable (exit 2, nothing
    written). Empty list = every declared target is contained, tracked,
    a clean regular file (no-follow)."""

    if not rules.remove:
        return []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.remove:
        prefix = f"remove target {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if not os.path.lexists(path):
            problems.append(
                prefix + "does not exist — a stale [[remove]] is config "
                "drift, never a silent no-op; delete the declaration or "
                "restore the file"
            )
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (targets must be committed so git "
                "provides the undo path)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        if has_uncommitted_changes(target, rule.file):
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (git restores only committed content)"
            )
    return problems


def render_remove_plan(rules: Rules) -> str:
    """The plan's removal section — every deletion visible before approval."""

    lines = ["Remove (declared deletions, applied after the rewrite pass):"]
    for rule in rules.remove:
        lines.append(f"  [remove ] {rule.file}  —  {rule.reason}")
    return "\n".join(lines)


def apply_removals(
    target: Path,
    rules: Rules,
    renamed: dict[str, str],
) -> list[str]:
    """Delete every declared target at its post-rename location; return the
    removed rels (CURRENT coordinates) for the report and receipt. The
    write-path predicates re-run immediately before each unlink — the
    rewrite pass has run since the preflight."""

    removed: list[str] = []
    for rule in rules.remove:
        rel = translate_path(rule.file, renamed)
        path = target / rel
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
        if not is_regular_lstat(path):
            raise SafetyError(
                f"remove target {rel} is not a regular file at apply time "
                f"(no-follow check)"
            )
        os.unlink(path)
        removed.append(rel)
    return removed
