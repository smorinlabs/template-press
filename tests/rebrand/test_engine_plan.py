import dataclasses
import subprocess
from pathlib import Path

from template_press.rebrand.engine import (
    _rename_covered_paths,
    build_plan,
    iter_target_files,
    replacement_pairs,
)
from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
from template_press.rebrand.substitutions import RenameStep

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


class TestRenameCoveredPaths:
    """Round 2 fix (E5a): rewrite-coverage candidacy for a rename must read
    RenameStep.source_entries, not compare tracked paths against old_prefix
    — a step from pass 2+ carries an INTERMEDIATE old_prefix (the path an
    earlier pass already moved it to), which a pre-rename tracked path
    would never match."""

    def _step(self, **overrides) -> RenameStep:
        base = {
            "step_id": "rename:1:1",
            "old_prefix": "pkg_a",
            "new_prefix": "pkg_b",
            "pass_number": 1,
            "row_ids": (),
            "source_entries": (),
            "expected_kind": "file",
        }
        base.update(overrides)
        return RenameStep(**base)

    def test_single_pass_step_covers_its_source_entries(self):
        step = self._step(source_entries=("pkg_a/file.py", "pkg_a/sub/other.py"))
        assert _rename_covered_paths((step,)) == {
            "pkg_a/file.py",
            "pkg_a/sub/other.py",
        }

    def test_chained_step_resolves_through_intermediate_old_prefix(self):
        """A pass-2 step's old_prefix ("pkg_b") is the CURRENT path left by
        a pass-1 step that already moved "pkg_a" -> "pkg_b" — the true
        SOURCE-coordinate file never had that name. The buggy old_prefix
        comparison would miss it entirely; source_entries must not."""
        chained_step = self._step(
            step_id="rename:2:1",
            old_prefix="pkg_b",  # intermediate coordinate, not a real source path
            new_prefix="pkg_c",
            pass_number=2,
            source_entries=("pkg_a/file.py",),  # true SOURCE coordinate
        )
        covered = _rename_covered_paths((chained_step,))
        assert covered == {"pkg_a/file.py"}
        # Demonstrate the old (buggy) approach would have missed it: the
        # tracked SOURCE path never equals, or nests under, this step's
        # intermediate old_prefix.
        tracked_source_path = "pkg_a/file.py"
        old_prefix_would_match = tracked_source_path == chained_step.old_prefix or (
            tracked_source_path.startswith(f"{chained_step.old_prefix}/")
        )
        assert not old_prefix_would_match

    def test_multiple_steps_union(self):
        step1 = self._step(source_entries=("a/x.py",))
        step2 = self._step(
            step_id="rename:1:2",
            old_prefix="pkg_c",
            new_prefix="pkg_d",
            source_entries=("c/y.py", "c/z.py"),
        )
        assert _rename_covered_paths((step1, step2)) == {"a/x.py", "c/y.py", "c/z.py"}
