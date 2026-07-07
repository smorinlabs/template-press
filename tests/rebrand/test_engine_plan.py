from pathlib import Path

from template_press.rebrand.engine import (
    build_plan,
    iter_target_files,
    replacement_pairs,
)
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_iter_target_files_respects_gitignore_and_excludes(src_target: Path):
    (src_target / ".venv").mkdir()
    (src_target / ".venv" / "junk.py").write_text("x", encoding="utf-8")
    files = iter_target_files(src_target, DEFAULT_RULES)
    rels = {f.relative_to(src_target).as_posix() for f in files}
    assert "README.md" in rels and "src/demo_widget/cli.py" in rels
    assert not any(r.startswith(".venv") for r in rels)
    assert not any(r.startswith(".git/") for r in rels)


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
