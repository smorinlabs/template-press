"""P06-TS09: frozen-plan closure and Git-visibility safety gates."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.engine import apply, build_plan
from template_press.rebrand.reset import preflight_reset_targets
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, ResetRule
from template_press.rebrand.safety import SafetyError
from template_press.rebrand.substitutions import validate_reset_visibility

from .conftest import DEST, SOURCE


def _git(target: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(target), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _exclude_without_identity(target: Path, pattern: str) -> None:
    info_exclude = target / ".git" / "info" / "exclude"
    with info_exclude.open("a", encoding="utf-8") as stream:
        stream.write(f"\n{pattern}\n")


def test_prefix_closure_refuses_ignored_untracked_descendant(
    src_target: Path,
) -> None:
    _exclude_without_identity(src_target, "src/*/ignored.txt")
    ignored = src_target / "src" / "demo_widget" / "ignored.txt"
    ignored.write_text("operator data\n", encoding="utf-8")
    assert _git(src_target, "check-ignore", ignored.relative_to(src_target).as_posix())

    with pytest.raises(SafetyError, match="absent from the authorized surface"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_prefix_closure_refuses_uninventoried_empty_directory(
    src_target: Path,
) -> None:
    (src_target / "src" / "demo_widget" / "empty").mkdir()

    with pytest.raises(SafetyError, match="uninventoried empty directory"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


@pytest.mark.parametrize("checked_out", [False, True])
def test_prefix_closure_refuses_missing_and_checked_out_gitlink(
    src_target: Path,
    checked_out: bool,
) -> None:
    sha = _git(src_target, "rev-parse", "HEAD")
    rel = "src/demo_widget/submodule"
    _git(src_target, "update-index", "--add", "--cacheinfo", f"160000,{sha},{rel}")
    if checked_out:
        path = src_target / rel
        path.mkdir()
        (path / "worktree.txt").write_text("opaque\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="would carry gitlink"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_apply_refuses_live_prefix_closure_divergence_before_content_write(
    src_target: Path,
) -> None:
    _exclude_without_identity(src_target, "src/*/late-secret.txt")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    late = src_target / "src" / "demo_widget" / "late-secret.txt"
    late.write_text("late operator data\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="absent from the authorized surface"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before


def test_apply_refuses_destination_state_divergence_before_content_write(
    src_target: Path,
) -> None:
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    destination = src_target / "src" / "potato_launcher"
    destination.mkdir()

    with pytest.raises(SafetyError, match="rename destination changed"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before


def test_content_rewrite_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    (src_target / ".gitignore").write_text(
        "demo_widget-secret\n",
        encoding="utf-8",
    )
    (src_target / "demo_widget-secret").write_text("ignored\n", encoding="utf-8")

    with pytest.raises(SafetyError, match=r"content rewrite.*Git visibility input"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_ancestor_rename_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    directory = src_target / "demo_widget_ignore"
    directory.mkdir()
    (directory / ".gitignore").write_text("secret\n", encoding="utf-8")
    (directory / "keep.txt").write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "-A")

    with pytest.raises(SafetyError, match=r"Git visibility input.*would move"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_direct_rename_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    source = replace(SOURCE, app_name="ignore")
    destination = replace(source, app_name="safe")
    rules = replace(
        DEFAULT_RULES,
        replace=(
            ReplaceRule(
                pattern=".git{app_name}",
                reason="direct visibility-input rename fixture",
                paths=True,
                content=False,
            ),
        ),
    )

    with pytest.raises(SafetyError, match=r"Git visibility input.*would move"):
        build_plan(src_target, source, destination, rules)


def test_position_zero_reset_of_gitignore_is_refused(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("secret\n", encoding="utf-8")
    _git(src_target, "add", ".gitignore")
    _git(src_target, "commit", "-q", "-m", "track ignore policy")
    rules = replace(
        DEFAULT_RULES,
        reset=(ResetRule(file=".gitignore", stub="other\n"),),
    )
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None
    previews, problems = preflight_reset_targets(
        src_target,
        rules,
        source=SOURCE,
        dest=DEST,
        renames=plan.renames,
        table=plan.table,
    )
    assert not problems

    with pytest.raises(SafetyError, match="reset would change Git visibility"):
        validate_reset_visibility(
            src_target,
            plan.table.rename_plan,
            tuple((preview.rule.file, preview.stub_text) for preview in previews),
        )


def test_apply_refuses_live_visibility_input_change_before_content_write(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("secret\n", encoding="utf-8")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    gitignore.write_text("other\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="Git visibility inputs changed"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before
