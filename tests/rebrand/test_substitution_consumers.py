"""P06-TS09: inline consumers derive their hunts from table rows."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import apply, build_plan
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.regen import (
    RegenerationPlan,
    final_validation_pass,
    scan_regenerated_output,
)
from template_press.rebrand.reset import (
    preflight_reset_targets,
    scan_reset_path,
    scan_stub_text,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    RegenerateRule,
    ReplaceRule,
    ResetRule,
)
from template_press.rebrand.substitutions import RenamePlan
from template_press.rebrand.verifier import scan

from .conftest import DEST, SOURCE, requires_symlink


def _git(target: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def test_nested_reset_and_regeneration_paths_use_final_table_location(
    src_target: Path,
) -> None:
    rel = "src/demo_widget/demo_widget.lock"
    nested = src_target / rel
    nested.write_text("clean\n", encoding="utf-8")
    _git(src_target, "add", rel)
    _git(src_target, "commit", "-q", "-m", "add nested output")
    rules = replace(
        DEFAULT_RULES,
        reset=(ResetRule(file=rel, stub="clean\n"),),
        regenerate=(RegenerateRule(file=rel, command=("unused",)),),
    )
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None
    assert plan.table.rename_plan.translate(rel) == (
        "src/potato_launcher/potato_launcher.lock"
    )

    previews, problems = preflight_reset_targets(
        src_target,
        rules,
        source=SOURCE,
        dest=DEST,
        renames=plan.renames,
        table=plan.table,
    )
    assert len(previews) == 1
    assert problems == []

    report = apply(src_target, SOURCE, DEST, rules, table=plan.table)
    final_problems = final_validation_pass(
        src_target,
        (
            RegenerationPlan(
                rule=rules.regenerate[0],
                executable="/unused",
                env_present=(),
                env_absent=(),
            ),
        ),
        (),
        dict(report.renamed),
        source=SOURCE,
        dest=DEST,
        rules=rules,
        table=plan.table,
    )
    assert final_problems == []


def test_doctor_reverse_translates_each_entry_once(
    src_target: Path, monkeypatch
) -> None:
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    assert all(
        entry.worktree_kind != "symlink"
        for entry in plan.table.rename_plan.source_entries
    )
    real_reverse_translate = RenamePlan.reverse_translate
    calls = 0

    def counted_reverse_translate(self, posix, *, executed_step_ids=None):
        nonlocal calls
        calls += 1
        return real_reverse_translate(
            self,
            posix,
            executed_step_ids=executed_step_ids,
        )

    monkeypatch.setattr(RenamePlan, "reverse_translate", counted_reverse_translate)

    find_leaks(
        src_target,
        SOURCE,
        DEFAULT_RULES,
        dest=DEST,
        table=plan.table,
    )

    assert 0 < calls <= len(plan.table.rename_plan.source_entries)


@requires_symlink
def test_scoped_descendant_trigger_covers_ancestor_symlink_hunts(
    src_target: Path,
) -> None:
    descendant = src_target / "docs" / "press-web" / "data.txt"
    descendant.parent.mkdir(parents=True)
    descendant.write_text("clean\n", encoding="utf-8")
    link = src_target / "web-link"
    os.symlink("docs/press-web", link)
    _git(src_target, "add", "-A")
    rule = ReplaceRule(
        pattern="{app_name}-web",
        reason="scoped descendant ancestor fixture",
        files=("docs/press-web/**",),
        paths=True,
        content=False,
    )
    rules = replace(DEFAULT_RULES, replace=(rule,))
    source_snapshot = capture_surface_snapshot(src_target)
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None

    report = apply(src_target, SOURCE, DEST, rules, table=plan.table)
    assert os.readlink(link) == "docs/potato-web"
    link.unlink()
    os.symlink("docs/press-web", link)

    leaks = find_leaks(
        src_target,
        SOURCE,
        rules,
        dest=DEST,
        renamed=report.renamed,
        table=plan.table,
    )
    assert any(
        leak.path == "web-link"
        and leak.field == "replace_rule"
        and leak.where == "symlink"
        for leak in leaks
    )
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=(),
        substring_fields=frozenset(),
        rules=rules,
        renamed=report.renamed,
        source_snapshot=source_snapshot,
    )
    assert any(
        finding.path == "web-link"
        and finding.field == "replace_rule"
        and finding.where == "symlink"
        for finding in findings
    )


def test_new_declared_row_drives_doctor_reset_and_regeneration_hunts(
    src_target: Path,
) -> None:
    rule = ReplaceRule(
        pattern="x{app_name}owned",
        reason="table consumer fixture",
        paths=True,
        content=True,
    )
    rules = replace(DEFAULT_RULES, replace=(rule,))
    residual = src_target / "row-consumer.txt"
    residual.write_text("xpressowned\n", encoding="utf-8")
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None

    leaks = find_leaks(
        src_target,
        SOURCE,
        rules,
        dest=DEST,
        table=plan.table,
    )
    assert any(
        leak.path == "row-consumer.txt"
        and leak.field == "replace_rule"
        and leak.where == "content"
        for leak in leaks
    )
    assert any(
        "rendered [[replace]] literal 'xpressowned'" in problem
        for problem in scan_stub_text(
            "xpressowned\n",
            rel="CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            table=plan.table,
        )
    )
    reset_path_problems = scan_reset_path(
        "docs/xpressowned.md",
        "docs/xpressowned.md",
        source=SOURCE,
        dest=DEST,
        rules=rules,
        table=plan.table,
    )
    assert any(
        "rendered [[replace]] literal 'xpressowned'" in problem
        for problem in reset_path_problems
    )
    regeneration_problems = scan_regenerated_output(
        "xpressowned\n",
        "docs/xpressowned.md",
        source=SOURCE,
        dest=DEST,
        rules=rules,
        renames={},
        table=plan.table,
    )
    assert any(
        "output contains rendered [[replace]]" in item for item in regeneration_problems
    )
    assert any("its path" in item for item in regeneration_problems)


def test_substring_identity_hunts_cover_reset_and_regeneration_surfaces(
    src_target: Path,
) -> None:
    rules = replace(
        DEFAULT_RULES,
        substring_rewrite_fields=frozenset({"app_name"}),
    )
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None

    assert any(
        "source app_name 'press'" in problem
        for problem in scan_stub_text(
            "xpressowned\n",
            rel="CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            table=plan.table,
        )
    )
    assert any(
        "source app_name 'press'" in problem
        for problem in scan_reset_path(
            "xpressowned.lock",
            "xpressowned.lock",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            table=plan.table,
        )
    )
    regeneration_problems = scan_regenerated_output(
        "xpressowned\n",
        "xpressowned.lock",
        source=SOURCE,
        dest=DEST,
        rules=rules,
        renames={},
        table=plan.table,
    )
    assert any(
        "output still carries source app_name 'press' (1 occurrence(s))" in item
        for item in regeneration_problems
    )
    assert any(
        "its path" in item and "app_name" in item for item in regeneration_problems
    )
