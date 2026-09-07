"""P10-TS02/TS03 — `press clean` (E10): rendering, the exact git argv, the
standalone verb, and its integrations (E2 hint, check-tools, receipt, verify).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from template_press import press_cli
from template_press.rebrand import clean_cli
from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.cli import main
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import CleanRule
from template_press.rebrand.safety import git_hardening_args
from template_press.rebrand.verify_cli import verify_command

from .conftest import SOURCE, _git, posix_only, requires_symlink
from .test_cli import write_answers, write_source_config


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


@pytest.mark.parametrize(
    ("other", "same_node", "stored_names", "expected"),
    [
        pytest.param(
            "C:/repo/src/demo_widget/EXTRA.POLICY",
            False,
            ("extra.policy", "EXTRA.POLICY"),
            False,
            id="separate-case-differing-entries",
        ),
        pytest.param(
            "C:/repo/src/demo_widget/EXTRA.POLICY",
            True,
            ("extra.policy",),
            True,
            id="one-real-case-alias",
        ),
        pytest.param(
            "C:/repo/src/demo_widget/EXTRA.POLICY",
            True,
            ("extra.policy", "EXTRA.POLICY"),
            False,
            id="case-differing-hardlink-entries",
        ),
        pytest.param(
            "C:/repo/src/demo_widget/extra.policy",
            False,
            ("extra.policy",),
            True,
            id="identical-spelling",
        ),
    ],
)
def test_paths_are_same_entry_uses_exact_windows_spelling(
    other: str, same_node: bool, stored_names: tuple[str, ...], expected: bool
):
    left = PureWindowsPath("C:/repo/src/demo_widget/extra.policy")
    right = PureWindowsPath(other)
    with (
        patch.object(clean_cli, "Path", PureWindowsPath),
        patch.object(
            clean_cli.os.path,
            "abspath",
            side_effect=lambda path: os.fspath(path),
        ),
        patch.object(clean_cli.os.path, "samefile", return_value=same_node),
        patch.object(
            clean_cli.os,
            "scandir",
            return_value=[SimpleNamespace(name=name) for name in stored_names],
        ),
    ):
        assert clean_cli._paths_are_same_entry(left, right) is expected


@pytest.mark.parametrize(
    ("git_dir", "backlink", "aliases", "expected"),
    [
        pytest.param(
            "C:/unit/common/.git/worktrees/slot",
            "C:/unit/TARGET/.git",
            {},
            False,
            id="separate-case-differing-backlink",
        ),
        pytest.param(
            "C:/unit/common/.git/WORKTREES/slot",
            "C:/unit/target/.git",
            {},
            False,
            id="separate-case-differing-registry",
        ),
        pytest.param(
            "C:/unit/common/.git/worktrees/slot",
            "C:/unit/target/.git",
            {},
            True,
            id="ordinary-registration",
        ),
        pytest.param(
            "C:/unit/common/.git/worktrees/slot",
            "C:/unit/TARGET/.git",
            {
                "C:\\unit\\TARGET": "C:\\unit\\target",
                "C:\\unit\\TARGET\\.git": "C:\\unit\\target\\.git",
            },
            True,
            id="one-real-backlink-case-alias",
        ),
        pytest.param(
            "C:/unit/common/.git/WORKTREES/slot",
            "C:/unit/target/.git",
            {
                "C:\\unit\\common\\.git\\WORKTREES": (
                    "C:\\unit\\common\\.git\\worktrees"
                )
            },
            True,
            id="one-real-registry-case-alias",
        ),
    ],
)
def test_validate_git_metadata_uses_entry_identity_for_windows_paths(
    git_dir: str, backlink: str, aliases: dict[str, str], expected: bool
):
    class PhysicalWindowsPath(PureWindowsPath):
        def resolve(self):
            return self

        def is_dir(self):
            return False

    target = PhysicalWindowsPath("C:/unit/target")
    metadata = {
        "gitdir": f"{backlink}\n".encode(),
        "commondir": b"C:/unit/common/.git\n",
    }

    def identical_node(left, right):
        left_spelling = os.fspath(left)
        right_spelling = os.fspath(right)
        return aliases.get(left_spelling, left_spelling) == aliases.get(
            right_spelling, right_spelling
        )

    with (
        patch.object(clean_cli, "Path", PhysicalWindowsPath),
        patch.object(
            clean_cli.os.path,
            "abspath",
            side_effect=lambda path: os.fspath(path),
        ),
        patch.object(clean_cli.os.path, "samefile", side_effect=identical_node),
        patch.object(
            clean_cli.os,
            "scandir",
            return_value=[SimpleNamespace(name="worktrees")],
        ),
        patch.object(
            clean_cli,
            "execute_clean",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=f"{git_dir}\n".encode(), stderr=b""
            ),
        ),
        patch.object(
            clean_cli,
            "read_regular_nofollow",
            side_effect=lambda path: metadata[path.name],
        ),
    ):
        try:
            clean_cli._validate_git_metadata(
                PhysicalWindowsPath("C:/unit/git.exe"), target
            )
        except ValidationError:
            accepted = False
        else:
            accepted = True

    assert accepted is expected


CLEAN_SRC_TESTS = '[[clean]]\npaths = ["src/{package_name}", "tests"]\n'


def _declare(target: Path, body: str) -> None:
    """Write press/press-rules.toml and commit it (a press wants a clean tree)."""
    (target / "press").mkdir(exist_ok=True)
    (target / "press" / "press-rules.toml").write_text(body, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "declare rules")


class TestPressClean:
    def _target(self, src_target: Path, body: str = CLEAN_SRC_TESTS) -> Path:
        write_source_config(src_target)
        _declare(src_target, body)
        return src_target

    def test_show_previews_and_removes_nothing(self, src_target: Path, capsys):
        target = self._target(src_target)
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")
        assert press_cli.main(["clean", "--target", str(target), "--show"]) == 0
        out = capsys.readouterr().out
        assert "clean -ndX -- src/demo_widget tests" in out
        assert "Would remove src/demo_widget/__pycache__/" in out
        assert cache.exists()

    def test_run_removes_only_ignored_entries_under_declared_paths(
        self, src_target: Path, capsys
    ):
        target = self._target(src_target)
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")
        survivor = target / "src" / "demo_widget" / "new.py"
        survivor.write_text("# untracked, not ignored\n", encoding="utf-8")
        outside = target / ".venv" / "lib"
        outside.parent.mkdir()
        outside.write_text(
            "ignored, but outside the declared paths\n", encoding="utf-8"
        )
        before = capture_surface_snapshot(target)
        protected_bytes = {
            entry.rel: (target / entry.rel).read_bytes()
            for entry in before.entries
            if entry.worktree_kind == "file"
        }
        outside_bytes = outside.read_bytes()
        assert press_cli.main(["clean", "--target", str(target)]) == 0
        out = capsys.readouterr().out
        assert "clean -fdX -- src/demo_widget tests" in out
        assert "Removing src/demo_widget/__pycache__/" in out
        assert not cache.exists()
        assert survivor.exists()
        assert outside.exists()
        assert capture_surface_snapshot(target) == before
        assert {rel: (target / rel).read_bytes() for rel in protected_bytes} == (
            protected_bytes
        )
        assert outside.read_bytes() == outside_bytes

    def test_absent_declared_path_is_a_silent_no_op(self, src_target: Path, capsys):
        target = self._target(src_target, '[[clean]]\npaths = ["missing"]\n')
        assert press_cli.main(["clean", "--target", str(target)]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1 and lines[0].startswith("run: ")

    def test_no_active_rule_exits_2(self, src_target: Path, capsys):
        foreign = "linux" if sys.platform == "win32" else "win32"
        target = self._target(
            src_target, f'[[clean]]\npaths = ["src"]\nplatforms = ["{foreign}"]\n'
        )
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        assert (
            "no [[clean]] rules declared in press/press-rules.toml"
            in capsys.readouterr().err
        )

    def test_missing_source_config_exits_2(self, src_target: Path, capsys):
        _declare(src_target, CLEAN_SRC_TESTS)  # rules, but no press-source.toml
        assert press_cli.main(["clean", "--target", str(src_target)]) == 2
        assert "press-source.toml" in capsys.readouterr().err

    def test_unrenderable_placeholder_exits_2(self, src_target: Path, capsys):
        target = self._target(
            src_target, '[[clean]]\npaths = ["docs/{display_name}"]\n'
        )
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        assert "does not declare it" in capsys.readouterr().err

    def test_not_a_repository_exits_2(self, tmp_path: Path, capsys):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert press_cli.main(["clean", "--target", str(plain)]) == 2
        assert "not a git repository" in capsys.readouterr().err

    def test_corrupt_index_preflight_exits_2_before_clean(
        self, src_target: Path, capsys
    ):
        # The active-input preflight captures the surface before cleaning.
        # A corrupt index therefore fails as a precondition, before git clean.
        target = self._target(src_target)
        (target / ".git" / "index").write_bytes(b"corrupt")
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        captured = capsys.readouterr()
        assert "run:" not in captured.out
        assert "error:" in captured.err

    def test_executed_git_failure_exits_1(self, src_target: Path, capsys, monkeypatch):
        target = self._target(src_target)
        real_execute = clean_cli.execute_clean

        def fail_clean(argv, command_target):
            if "clean" in argv:
                return subprocess.CompletedProcess(
                    argv, 5, stdout=b"partial output\n", stderr=b"clean failure\n"
                )
            return real_execute(argv, command_target)

        monkeypatch.setattr(clean_cli, "execute_clean", fail_clean)
        assert press_cli.main(["clean", "--target", str(target)]) == 1
        captured = capsys.readouterr()
        assert "run:" in captured.out and "partial output" in captured.out
        assert "clean failure" in captured.err
        assert "git clean exited 5" in captured.err

    @pytest.mark.parametrize("show", [False, True])
    def test_foreign_gitfile_refuses_before_clean(
        self, src_target: Path, tmp_path: Path, capsys, show: bool
    ):
        target = self._target(src_target)
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        _git(foreign, "init", "-q")
        survivor = target / "src" / "demo_widget" / "protected.py"
        survivor.write_bytes(b"keep me")
        (foreign / ".git" / "info" / "exclude").write_text(
            "protected.py\n", encoding="utf-8"
        )
        shutil.rmtree(target / ".git")
        (target / ".git").write_text(f"gitdir: {foreign / '.git'}\n", encoding="utf-8")
        args = ["clean", "--target", str(target)] + (["--show"] if show else [])
        assert press_cli.main(args) == 2
        captured = capsys.readouterr()
        assert "error:" in captured.err
        assert "run:" not in captured.out and "preview:" not in captured.out
        assert survivor.read_bytes() == b"keep me"

    @pytest.mark.parametrize(
        ("name", "relative"),
        [
            ("linked worktree", False),
            ("linked relative", True),
            pytest.param("linked\nworktree", False, marks=posix_only),
        ],
    )
    def test_linked_worktree_is_accepted(
        self, src_target: Path, tmp_path: Path, name: str, relative: bool
    ):
        source = self._target(src_target)
        target = tmp_path / name
        _git(source, "worktree", "add", "--detach", str(target))
        if relative:
            git_dir = Path(
                (target / ".git")
                .read_text(encoding="utf-8")
                .removeprefix("gitdir: ")
                .removesuffix("\n")
            )
            if not git_dir.is_absolute():
                git_dir = (target / git_dir).resolve()
            (git_dir / "gitdir").write_text(
                os.path.relpath(target / ".git", git_dir) + "\n", encoding="utf-8"
            )
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"cache")
        assert (target / ".git").is_file()
        assert press_cli.main(["clean", "--target", str(target), "--show"]) == 0
        assert cache.read_bytes() == b"cache"
        assert press_cli.main(["clean", "--target", str(target)]) == 0
        assert not cache.exists()

    def test_sibling_worktree_gitfile_is_refused(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        source = self._target(src_target)
        first, second = tmp_path / "first", tmp_path / "second"
        _git(source, "worktree", "add", "--detach", str(first))
        _git(source, "worktree", "add", "--detach", str(second))
        protected = Path("src/demo_widget/__init__.py")
        original = (first / protected).read_bytes()
        _git(second, "rm", "--cached", "--", protected.as_posix())
        (source / ".git" / "info" / "exclude").write_text(
            protected.as_posix() + "\n", encoding="utf-8"
        )
        (first / ".git").write_bytes((second / ".git").read_bytes())
        assert press_cli.main(["clean", "--target", str(first)]) == 2
        captured = capsys.readouterr()
        assert "does not belong" in captured.err
        assert "run:" not in captured.out
        assert (first / protected).read_bytes() == original

    @pytest.mark.parametrize("malformed", [False, True])
    def test_invalid_gitfile_is_a_precondition_refusal(
        self, src_target: Path, tmp_path: Path, capsys, malformed: bool
    ):
        target = self._target(src_target)
        shutil.rmtree(target / ".git")
        (target / ".git").write_text(
            "not a gitfile\n"
            if malformed
            else f"gitdir: {tmp_path / 'missing-gitdir'}\n",
            encoding="utf-8",
        )
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        captured = capsys.readouterr()
        assert "cannot resolve .git gitfile" in captured.err
        assert "run:" not in captured.out

    @requires_symlink
    def test_symlinked_gitdir_backlink_is_refused(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        source = self._target(src_target)
        target = tmp_path / "linked"
        _git(source, "worktree", "add", "--detach", str(target))
        git_dir = Path(
            (target / ".git")
            .read_text(encoding="utf-8")
            .removeprefix("gitdir: ")
            .removesuffix("\n")
        )
        if not git_dir.is_absolute():
            git_dir = (target / git_dir).resolve()
        backlink = git_dir / "gitdir"
        saved = tmp_path / "saved-backlink"
        backlink.rename(saved)
        backlink.symlink_to(saved)
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"keep")
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        captured = capsys.readouterr()
        assert "error:" in captured.err and "run:" not in captured.out
        assert cache.read_bytes() == b"keep"

    def test_missing_target_exits_2(self, tmp_path: Path):
        assert press_cli.main(["clean", "--target", str(tmp_path / "nope")]) == 2

    @requires_symlink
    def test_symlinked_git_entry_exits_2(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        target = self._target(src_target)
        shutil.move(target / ".git", tmp_path / "moved-git")
        (target / ".git").symlink_to(tmp_path / "moved-git", target_is_directory=True)
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        captured = capsys.readouterr()
        assert ".git is a symlink" in captured.err
        assert "run:" not in captured.out

    @requires_symlink
    def test_symlinked_control_dir_exits_2(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        # load_source_config refuses a symlinked press/ with ContainmentError;
        # the verb must map that to exit 2 before any git command runs.
        target = self._target(src_target)
        shutil.move(target / "press", tmp_path / "real-press")
        (target / "press").symlink_to(tmp_path / "real-press", target_is_directory=True)
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        captured = capsys.readouterr()
        assert "symlink" in captured.err
        assert "run:" not in captured.out


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("forged_common", [False, True])
def test_forged_foreign_backlink_is_refused(
    src_target, tmp_path, capsys, show, forged_common
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    survivor = target / "src/demo_widget/__init__.py"
    before = survivor.read_bytes()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    _git(foreign, "init", "-q")
    (foreign / ".git/info/exclude").write_text("src/demo_widget/__init__.py\n")
    (foreign / ".git/gitdir").write_text(str(target / ".git") + "\n")
    if forged_common:
        (foreign / ".git/commondir").write_text(".\n")
    (target / ".git").rename(tmp_path / "original-git")
    (target / ".git").write_text(f"gitdir: {foreign / '.git'}\n")
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    result = press_cli.main(args)
    captured = capsys.readouterr()
    assert result == 2, (result, captured, survivor.exists())
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert survivor.read_bytes() == before


@pytest.mark.parametrize("show", [False, True])
def test_success_stderr_is_forwarded(src_target, capsys, monkeypatch, show):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    warning = b"warning: could not open directory: Permission denied\n"
    real_execute = clean_cli.execute_clean

    def warn_on_clean(argv, target):
        if "clean" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=warning)
        return real_execute(argv, target)

    monkeypatch.setattr(clean_cli, "execute_clean", warn_on_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert capsys.readouterr().err == warning.decode()


def test_junction_marker_is_refused(src_target, capsys, monkeypatch):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    marker = target / ".git"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == marker)
    result = press_cli.main(["clean", "--target", str(target)])
    captured = capsys.readouterr()
    assert result == 2, (result, captured)
    assert "junction" in captured.err
    assert "run:" not in captured.out


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("configured", ["absent", "empty", "relative", "absolute"])
def test_clean_excludes_match_inventory(
    src_target, tmp_path, monkeypatch, capsys, show, configured
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git/ignore").write_text("*.log\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    local = target / "clean-excludes"
    local.write_text("local.tmp\n")
    if configured != "absent":
        value = {"empty": "", "relative": local.name, "absolute": str(local)}[
            configured
        ]
        _git(target, "config", "core.excludesFile", value)
    decoy = target / "src/demo_widget/debug.log"
    decoy.write_bytes(b"keep default-excludes decoy")
    candidate = target / "src/demo_widget/local.tmp"
    candidate.write_bytes(b"local candidate")
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    before = capture_surface_snapshot(target)
    assert decoy.relative_to(target) in {e.rel for e in before.entries}
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert "debug.log" not in capsys.readouterr().out
    assert decoy.read_bytes() == b"keep default-excludes decoy"
    assert cache.exists() == show
    assert candidate.exists() == (show or configured in ("absent", "empty"))
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("relation", ["exact", "ancestor"])
@pytest.mark.parametrize("configured_form", ["relative", "absolute"])
def test_configured_excludes_overlap_refuses_before_clean(
    src_target, capsys, monkeypatch, show, relation, configured_form
):
    target = src_target
    write_source_config(target)
    if relation == "exact":
        declared = "src/{package_name}/core-excludes"
        excludes = target / "src/demo_widget/core-excludes"
        excludes_bytes = b"core-excludes\n__pycache__/\n"
    else:
        declared = "src/{package_name}"
        excludes = target / "src/demo_widget/.policy/core-excludes"
        # This variant proves the guard runs before Git removes an ignored
        # containing directory rather than naming the excludes file directly.
        excludes_bytes = b".policy/\n__pycache__/\n"
    _declare(target, f'[[clean]]\npaths = ["{declared}"]\n')
    excludes.parent.mkdir(parents=True, exist_ok=True)
    excludes.write_bytes(excludes_bytes)
    configured = (
        os.path.relpath(excludes, target)
        if configured_form == "relative"
        else str(excludes)
    )
    _git(target, "config", "core.excludesFile", configured)
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("configured-excludes overlap reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "configured core.excludesFile" in captured.err
    assert "overlaps [[clean]] path" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert excludes.read_bytes() == excludes_bytes
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
def test_missing_configured_excludes_under_clean_path_refuses(
    src_target, capsys, monkeypatch, show
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    excludes = target / "src/demo_widget/missing-excludes"
    _git(
        target,
        "config",
        "core.excludesFile",
        os.path.relpath(excludes, target),
    )
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("missing configured-excludes overlap reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "overlaps [[clean]] path" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert not excludes.exists()
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
def test_case_alias_configured_excludes_overlap_refuses(
    src_target, capsys, monkeypatch, show
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    excludes = target / "src/demo_widget/core-excludes"
    excludes.write_bytes(b"core-excludes\n__pycache__/\n")
    alias = target / "SRC/DEMO_WIDGET/CORE-EXCLUDES"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem path alias")
    assert os.path.samefile(excludes, alias)
    _git(target, "config", "core.excludesFile", str(alias))
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("case-aliased configured excludes reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "overlaps [[clean]] path" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert excludes.read_bytes() == b"core-excludes\n__pycache__/\n"
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("relation", ["exact", "ancestor"])
def test_active_self_ignored_gitignore_refuses_before_clean(
    src_target, capsys, monkeypatch, show, relation
):
    target = src_target
    write_source_config(target)
    declared = (
        "src/{package_name}/.gitignore" if relation == "exact" else "src/{package_name}"
    )
    _declare(target, f'[[clean]]\npaths = ["{declared}"]\n')
    policy = target / "src/demo_widget/.gitignore"
    policy_bytes = b".gitignore\n*.tmp\n"
    policy.write_bytes(policy_bytes)
    cache = target / "src/demo_widget/cache.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert any(
        item.origin == "gitignore" and item.path == policy
        for item in before.visibility_inputs
    )
    assert policy.relative_to(target) not in {entry.rel for entry in before.entries}
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("active self-ignored .gitignore reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "active Git input" in captured.err
    assert "overlaps [[clean]] path" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert policy.read_bytes() == policy_bytes
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@posix_only
@pytest.mark.parametrize("show", [False, True])
def test_active_input_hardlinked_to_disjoint_tracked_path_still_refuses(
    src_target, capsys, monkeypatch, show
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    tracked = target / "tracked-policy"
    policy_bytes = b".gitignore\n*.tmp\n"
    tracked.write_bytes(policy_bytes)
    _git(target, "add", tracked.relative_to(target).as_posix())
    _git(target, "commit", "-q", "-m", "track disjoint hardlink source")
    policy = target / "src/demo_widget/.gitignore"
    os.link(tracked, policy)
    cache = target / "src/demo_widget/cache.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert os.path.samefile(policy, tracked)
    assert policy.relative_to(target) not in {entry.rel for entry in before.entries}
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("distinct hardlinked active input reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "active Git input" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert policy.read_bytes() == policy_bytes
    assert tracked.read_bytes() == policy_bytes
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
def test_ignored_repository_config_include_refuses_before_clean(
    src_target, capsys, monkeypatch, show
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    (target / ".git/info/exclude").write_text("*.policy\n*.tmp\n", encoding="utf-8")
    policy = target / "src/demo_widget/extra.policy"
    policy_bytes = b"[probe]\n\tsentinel = stable-value\n"
    policy.write_bytes(policy_bytes)
    _git(target, "config", "--local", "include.path", str(policy))
    cache = target / "src/demo_widget/cache.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert any(
        item.path == policy and item.kind != "missing"
        for item in before.git_config_inputs
    )
    assert policy.relative_to(target) not in {entry.rel for entry in before.entries}
    real_execute = clean_cli.execute_clean

    def refuse_clean(argv, command_target):
        if "clean" in argv:
            pytest.fail("ignored repository config input reached git clean")
        return real_execute(argv, command_target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "active Git input" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert policy.read_bytes() == policy_bytes
    assert cache.read_bytes() == b"cache bytes"
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("protected", ["tracked", "nonignored"])
def test_listed_active_gitignore_is_preserved_and_clean_runs(
    src_target, show, protected
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    policy = target / "src/demo_widget/.gitignore"
    policy_bytes = b".gitignore\n*.tmp\n" if protected == "tracked" else b"*.tmp\n"
    policy.write_bytes(policy_bytes)
    if protected == "tracked":
        _git(target, "add", "-f", policy.relative_to(target).as_posix())
        _git(target, "commit", "-q", "-m", "track active policy")
    cache = target / "src/demo_widget/cache.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert policy.relative_to(target) in {entry.rel for entry in before.entries}
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert policy.read_bytes() == policy_bytes
    assert cache.exists() == show
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "protected", ["tracked-overlap", "tracked-case-alias", "ignored-disjoint"]
)
def test_safe_repository_config_include_is_preserved_and_clean_runs(
    src_target, show, protected
):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    (target / ".git/info/exclude").write_text("*.policy\n*.tmp\n", encoding="utf-8")
    policy = target / (
        "src/demo_widget/extra.policy"
        if protected.startswith("tracked")
        else "press/extra.policy"
    )
    policy_bytes = b"[probe]\n\tsentinel = stable-value\n"
    policy.write_bytes(policy_bytes)
    if protected.startswith("tracked"):
        _git(target, "add", "-f", policy.relative_to(target).as_posix())
        _git(target, "commit", "-q", "-m", "track config include")
    configured_policy = policy
    if protected == "tracked-case-alias":
        configured_policy = target / "SRC/DEMO_WIDGET/EXTRA.POLICY"
        if not configured_policy.exists():
            pytest.skip("requires a case-insensitive filesystem path alias")
        assert os.path.samefile(policy, configured_policy)
    _git(target, "config", "--local", "include.path", str(configured_policy))
    cache = target / "src/demo_widget/cache.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert any(
        item.path == configured_policy and item.kind != "missing"
        for item in before.git_config_inputs
    )
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert policy.read_bytes() == policy_bytes
    assert cache.exists() == show
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
def test_disjoint_self_ignored_gitignore_is_preserved_and_clean_runs(src_target, show):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    policy = target / "press/.gitignore"
    policy.write_bytes(b".gitignore\n")
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert any(
        item.origin == "gitignore" and item.path == policy
        for item in before.visibility_inputs
    )
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert policy.read_bytes() == b".gitignore\n"
    assert cache.exists() == show
    assert capture_surface_snapshot(target) == before


@pytest.mark.parametrize("show", [False, True])
def test_inactive_gitignore_under_ignored_parent_remains_cleanable(src_target, show):
    target = src_target
    write_source_config(target)
    _declare(target, CLEAN_SRC_TESTS)
    parent_policy = target / "src/demo_widget/.gitignore"
    parent_policy.write_bytes(b"cache/\n")
    _git(target, "add", parent_policy.relative_to(target).as_posix())
    _git(target, "commit", "-q", "-m", "ignore cache directory")
    inactive_policy = target / "src/demo_widget/cache/.gitignore"
    inactive_policy.parent.mkdir()
    inactive_policy.write_bytes(b"*.tmp\n")
    cache = inactive_policy.parent / "x.tmp"
    cache.write_bytes(b"cache bytes")
    before = capture_surface_snapshot(target)
    assert all(item.path != inactive_policy for item in before.visibility_inputs)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert inactive_policy.exists() == show
    assert cache.exists() == show
    assert capture_surface_snapshot(target) == before


def test_linked_worktree_with_absolute_common_dir_is_accepted(src_target, tmp_path):
    write_source_config(src_target)
    _declare(src_target, CLEAN_SRC_TESTS)
    target = tmp_path / "absolute-common"
    _git(src_target, "worktree", "add", "--detach", str(target))
    git_dir = Path(
        (target / ".git").read_text().removeprefix("gitdir: ").removesuffix("\n")
    )
    if not git_dir.is_absolute():
        git_dir = (target / git_dir).resolve()
    (git_dir / "commondir").write_text(str(src_target / ".git") + "\n")
    cache = target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    assert press_cli.main(["clean", "--target", str(target)]) == 0
    assert not cache.exists()


@pytest.mark.parametrize("show", [False, True])
def test_invalid_git_directory_cannot_discover_parent(
    src_target, tmp_path, capsys, show
):
    _git(tmp_path, "init", "-q")
    (tmp_path / ".git/info/exclude").write_text("*\n")
    write_source_config(src_target)
    _declare(src_target, CLEAN_SRC_TESTS)
    survivor = src_target / "src/demo_widget/__init__.py"
    before = survivor.read_bytes()
    (src_target / ".git/HEAD").unlink()
    args = ["clean", "--target", str(src_target)] + (["--show"] if show else [])
    result = press_cli.main(args)
    captured = capsys.readouterr()
    assert result == 2, (captured, survivor.exists())
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert survivor.read_bytes() == before


class TestClosureRefusalHint:
    def _stale_cache(self, target: Path) -> None:
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")

    def test_names_press_clean_when_declared(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        self._stale_cache(src_target)
        answers = write_answers(tmp_path)
        assert (
            main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
            == 2
        )
        out = capsys.readouterr().out
        assert "absent from the authorized surface" in out
        assert (
            f"declared clean rules exist — run: press clean --target {src_target}"
            in out
        )

    def test_silent_when_not_declared(self, src_target: Path, tmp_path: Path, capsys):
        write_source_config(src_target)
        self._stale_cache(src_target)
        answers = write_answers(tmp_path)
        assert (
            main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
            == 2
        )
        out = capsys.readouterr().out
        assert "absent from the authorized surface" in out
        assert "press clean" not in out


def test_dispatcher_lists_and_routes_clean(tmp_path: Path, capsys):
    assert press_cli.main([]) == 0
    assert "clean" in capsys.readouterr().out
    assert press_cli.main(["clean", "--target", str(tmp_path / "nope")]) == 2


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        pytest.param("fifo", marks=posix_only),
        "directory",
        pytest.param("symlink", marks=requires_symlink),
    ],
)
def test_nonregular_configured_excludes_refuse_before_clean(
    src_target, tmp_path, capsys, monkeypatch, show, kind
):
    write_source_config(src_target)
    _declare(src_target, CLEAN_SRC_TESTS)
    excludes = tmp_path / "excludes"
    if kind == "fifo":
        os.mkfifo(excludes)
    elif kind == "directory":
        excludes.mkdir()
    else:
        regular = tmp_path / "regular-excludes"
        regular.write_text("*.pyc\n")
        excludes.symlink_to(regular)
    _git(src_target, "config", "core.excludesFile", str(excludes))
    cache = src_target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"keep")
    real_execute = clean_cli.execute_clean

    def refuse_unsafe_clean(argv, target):
        # The old implementation fails promptly here instead of hanging
        # this test on the FIFO. Metadata/config queries still use real Git.
        if "clean" in argv:
            pytest.fail("unsafe git clean reached a nonregular excludes input")
        return real_execute(argv, target)

    monkeypatch.setattr(clean_cli, "execute_clean", refuse_unsafe_clean)
    args = ["clean", "--target", str(src_target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "run:" not in captured.out and "preview:" not in captured.out
    assert cache.read_bytes() == b"keep"


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("configured", ["missing", "null"])
def test_missing_or_null_configured_excludes_are_accepted(
    src_target, tmp_path, show, configured
):
    write_source_config(src_target)
    _declare(src_target, CLEAN_SRC_TESTS)
    path = (
        tmp_path / "missing-excludes" if configured == "missing" else Path(os.devnull)
    )
    _git(src_target, "config", "core.excludesFile", str(path))
    cache = src_target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    args = ["clean", "--target", str(src_target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert cache.exists() == show


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("launch_missing", [False, True])
def test_clean_launch_oserror_is_precondition_refusal(
    src_target, tmp_path, monkeypatch, capsys, show, launch_missing
):
    write_source_config(src_target)
    _declare(src_target, CLEAN_SRC_TESTS)
    cache = src_target / "src/demo_widget/__pycache__/x.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    before = capture_surface_snapshot(src_target)
    real_execute = clean_cli.execute_clean

    def execute_with_launch_control(argv, target):
        if launch_missing and "clean" in argv:
            argv = [str(tmp_path / "git-gone"), *argv[1:]]
        return real_execute(argv, target)

    monkeypatch.setattr(clean_cli, "execute_clean", execute_with_launch_control)
    args = ["clean", "--target", str(src_target)] + (["--show"] if show else [])
    assert press_cli.main(args) == (2 if launch_missing else 0)
    captured = capsys.readouterr()
    if launch_missing:
        assert "error:" in captured.err
        assert "git-gone" in captured.err
    assert cache.exists() == (show or launch_missing)
    assert capture_surface_snapshot(src_target) == before


class TestIntegrations:
    def test_check_tools_reports_one_row_per_clean_rule(self, src_target: Path, capsys):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS + '[[clean]]\npaths = ["build"]\n')
        assert press_cli.main(["check-tools", "--target", str(src_target)]) == 0
        out = capsys.readouterr().out
        assert "(cleans src/{package_name}, tests)" in out
        assert "(cleans build)" in out

    def test_receipt_records_the_declaration_unrendered(
        self, src_target: Path, tmp_path: Path
    ):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        raw = (src_target / RECEIPT_REL).read_text(encoding="utf-8")
        assert "[[press.clean]]" in raw
        assert 'paths = ["src/{package_name}", "tests"]' in raw
        receipt = tomllib.loads(raw)
        assert receipt["press"]["clean"] == [{"paths": ["src/{package_name}", "tests"]}]
        assert "ran" not in receipt["press"]["clean"][0]

    def test_receipt_has_no_clean_table_without_rules(
        self, src_target: Path, tmp_path: Path
    ):
        write_source_config(src_target)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        assert "[[press.clean]]" not in (src_target / RECEIPT_REL).read_text(
            encoding="utf-8"
        )

    def test_verify_is_unaffected_by_a_clean_declaration(
        self, src_target: Path, capsys
    ):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        code = verify_command(["--target", str(src_target)])
        with_rule = capsys.readouterr().out
        _declare(src_target, "[rules]\n")
        assert verify_command(["--target", str(src_target)]) == code
        assert capsys.readouterr().out == with_rule
