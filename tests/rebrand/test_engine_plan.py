import dataclasses
import subprocess
from pathlib import Path

from template_press.rebrand.engine import (
    build_plan,
    iter_target_files,
    replacement_pairs,
)
from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule

from .conftest import DEST, SOURCE


def _git_add_all(repo: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _rules_with(**overrides):
    return dataclasses.replace(DEFAULT_RULES, **overrides)


def _identity(**overrides):
    base = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    base.update(overrides)
    return Identity(**base)


def test_iter_target_files_respects_gitignore_and_excludes(src_target: Path):
    (src_target / ".venv").mkdir()
    (src_target / ".venv" / "junk.py").write_text("x", encoding="utf-8")
    files = iter_target_files(src_target, DEFAULT_RULES)
    rels = {f.relative_to(src_target).as_posix() for f in files}
    assert "README.md" in rels and "src/demo_widget/cli.py" in rels
    assert not any(r.startswith(".venv") for r in rels)
    assert not any(r.startswith(".git/") for r in rels)


def test_iter_target_files_sees_non_ascii_paths(src_target: Path):
    doc = src_target / "文档.py"
    doc.write_text("import demo_widget\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    files = iter_target_files(src_target, DEFAULT_RULES)
    rels = {f.relative_to(src_target).as_posix() for f in files}
    assert "文档.py" in rels


def test_replacement_pairs_longest_first():
    pairs = replacement_pairs(SOURCE, DEST)
    currents = [cur for _, cur, _ in pairs]
    assert currents == sorted(currents, key=len, reverse=True)
    assert ("app_name", "press", "potato") in pairs


def test_build_plan_lists_files_with_occurrences(src_target: Path):
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    replace_paths = {i.path for i in plan.items if i.kind == "replace"}
    assert "README.md" in replace_paths
    assert "pyproject.toml" in replace_paths
    rename_paths = {i.path for i in plan.items if i.kind == "rename"}
    assert "src/demo_widget" in rename_paths
    assert "press_config.toml" in rename_paths


class TestReplaceRulePlan:
    def test_plan_lists_rule_hits(self, src_target: Path):
        (src_target / "conftest.py").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(
            replace=(ReplaceRule(pattern="_{app_name}_owned", reason="guard"),)
        )
        plan = build_plan(src_target, _identity(), _identity(app_name="acme"), rules)
        assert any(
            i.kind == "replace" and "_plbp_owned" in i.detail for i in plan.items
        )


class TestSubstringPlan:
    def test_substring_field_hit_detected_via_plain_membership(self, src_target: Path):
        # "_plbp_owned" is glued on both sides — the boundary-guarded
        # token_occurs would reject it (underscore is not a boundary char
        # for app_name), so a plan item here can only come from the
        # substring branch's `cur in text` check, not the token-pass branch.
        (src_target / "note.txt").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        plan = build_plan(src_target, _identity(), _identity(app_name="acme"), rules)
        assert any(
            i.kind == "replace" and i.path == "note.txt" and "app_name" in i.detail
            for i in plan.items
        )

    def test_default_rules_do_not_detect_glued_token(self, src_target: Path):
        # Same fixture, DEFAULT_RULES (empty substring_rewrite_fields): the
        # ternary must fall through to token_occurs, which sees no boundary
        # and reports no hit — proving the substring branch, not the token
        # pass, produced the prior test's hit.
        (src_target / "note.txt").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(src_target)
        plan = build_plan(
            src_target, _identity(), _identity(app_name="acme"), DEFAULT_RULES
        )
        assert not any(i.kind == "replace" and i.path == "note.txt" for i in plan.items)
