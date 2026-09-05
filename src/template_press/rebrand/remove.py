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
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.pathing import translate_path
from template_press.rebrand.regen import has_uncommitted_changes, tracked_paths
from template_press.rebrand.rules import Rules, _control_alias_key
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


def preflight_remove_targets(
    target: Path,
    rules: Rules,
    *,
    previously_removed: frozenset[str] = frozenset(),
) -> list[str]:
    """Problems that make a declared removal unpressable (exit 2, nothing
    written). Empty list = every declared target is contained, tracked,
    a clean regular file (no-follow) — or already removed by a prior press
    (``previously_removed``, the prior receipt's ``[[press.remove]]`` set:
    a removal deletes its own precondition, so a forced re-press must not
    refuse over its predecessor's success)."""

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
            if rule.file in previously_removed:
                continue  # satisfied by the prior press (receipt-recorded)
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
    """The plan's removal section — every deletion visible before approval.

    Ends with a per-directory summary (spec E5b): one ``removing N file(s)
    under <dir>/`` line (singular for ``N == 1``) per top-level directory
    (the removal's SOURCE-path first component) that holds at least one
    declared removal — a quick count check against the per-file lines
    above it, not a replacement for them. A removal at the target root
    (no directory component) has nothing to group under and contributes
    no summary line.
    """

    lines = ["Remove (declared deletions, applied after the rewrite pass):"]
    for rule in rules.remove:
        lines.append(f"  [remove ] {rule.file}  —  {rule.reason}")
    counts: dict[str, int] = {}
    for rule in rules.remove:
        head, sep, _ = rule.file.partition("/")
        if sep:
            counts[head] = counts.get(head, 0) + 1
    for dirname in sorted(counts):
        count = counts[dirname]
        noun = "file" if count == 1 else "files"
        lines.append(f"  removing {count} {noun} under {dirname}/")
    return "\n".join(lines)


def remove_command_conflicts(rules: Rules, renamed: Mapping[str, str]) -> list[str]:
    """Refuse standalone target-relative argv paths an active removal deletes.

    Removals run before edits and regenerations. Without this plan-time gate,
    dry-run succeeds but apply deletes the argv path before the command can
    launch. Compare original and final paths, normalizing path syntax and
    filesystem aliases. Like ``stale_argv_elements``, this is best-effort:
    absolute paths, attached options, and command-language strings are not
    interpreted as target-relative paths.
    """

    removed = {
        _control_alias_key(path): r.file
        for r in rules.remove
        for path in (r.file, translate_path(r.file, renamed))
    }
    if not removed:
        return []
    problems: list[str] = []
    for kind, declarations in (
        ("edit", rules.edit),
        ("regenerate", rules.regenerate),
    ):
        for declaration in declarations:
            for element in declaration.command:
                norm = posixpath.normpath(element.replace("\\", "/"))
                removed_file = removed.get(_control_alias_key(norm))
                if removed_file is None:
                    continue
                problems.append(
                    f"remove target {removed_file!r}: argv element {element!r} "
                    f"in the [[{kind}]] command for {declaration.file!r} names "
                    f"its original or renamed location (including filesystem "
                    f"aliases) — the removal would delete it before the command "
                    f"runs; drop one declaration"
                )
    return problems


def apply_removals(
    target: Path,
    rules: Rules,
    renamed: dict[str, str],
    *,
    previously_removed: frozenset[str] = frozenset(),
) -> list[str]:
    """Delete every declared target at its post-rename location; return the
    removed rels (CURRENT coordinates) for the report and receipt. The
    write-path predicates re-run immediately before each unlink — the
    rewrite pass has run since the preflight. A target already removed by
    a prior press (receipt-recorded) is skipped, matching the preflight."""

    removed: list[str] = []
    for rule in rules.remove:
        rel = translate_path(rule.file, renamed)
        path = target / rel
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
        if not os.path.lexists(path):
            if rule.file in previously_removed:
                continue  # satisfied by the prior press
            raise SafetyError(f"remove target {rel} does not exist at apply time")
        if not is_regular_lstat(path):
            raise SafetyError(
                f"remove target {rel} is not a regular file at apply time "
                f"(no-follow check)"
            )
        os.unlink(path)
        removed.append(rel)
    return removed
