"""P10-TS02/TS03 — `press clean` (E10): rendering, the exact git argv, the
standalone verb, and its integrations (E2 hint, check-tools, receipt, verify).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import CleanRule
from template_press.rebrand.safety import git_hardening_args

from .conftest import SOURCE


class TestRender:
    def test_renders_from_source_in_declaration_order(self):
        rules = (
            CleanRule(paths=("src/{package_name}", "tests")),
            CleanRule(paths=("build/{repo_name}",)),
        )
        assert render_clean_paths(rules, SOURCE) == (
            "src/demo_widget",
            "tests",
            "build/demo-widget",
        )

    def test_optional_field_absent_from_source_refuses(self):
        rules = (CleanRule(paths=("docs/{display_name}",)),)
        with pytest.raises(ValidationError, match="does not declare it"):
            render_clean_paths(rules, SOURCE)

    def test_rendered_path_that_escapes_is_refused(self):
        class _Hostile:
            def as_dict(self) -> dict[str, str]:
                return {**SOURCE.as_dict(), "package_name": "../escape"}

        rules = (CleanRule(paths=("src/{package_name}",)),)
        with pytest.raises(ValidationError, match="rendered path"):
            render_clean_paths(rules, _Hostile())  # type: ignore[arg-type]


class TestArgv:
    def test_preview_and_run_argv(self, tmp_path: Path):
        git = Path("git-placeholder")
        paths = ("src/demo_widget", "tests")
        preview = clean_argv(git, tmp_path, paths, show=True)
        run = clean_argv(git, tmp_path, paths, show=False)
        assert preview[0] == str(git)
        assert preview[1:3] == ["-C", str(tmp_path)]
        assert f"--work-tree={tmp_path.absolute()}" in preview
        for flag in git_hardening_args():
            assert flag in preview
        assert preview[-6:] == [
            "--literal-pathspecs",
            "clean",
            "-ndX",
            "--",
            "src/demo_widget",
            "tests",
        ]
        assert run[-6:] == [
            "--literal-pathspecs",
            "clean",
            "-fdX",
            "--",
            "src/demo_widget",
            "tests",
        ]

    def test_shell_join_displays_argv_with_spaces(self):
        joined = shell_join(["git", "clean", "-ndX", "--", "src/demo widget"])
        assert "src/demo widget" in joined or "'src/demo widget'" in joined
        assert joined.startswith("git clean -ndX --")

    def test_execute_returns_nonzero_without_raising(self, tmp_path: Path):
        result = execute_clean([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
        assert result.returncode == 3
