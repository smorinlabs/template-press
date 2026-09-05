"""P04-TS13 — `press check-tools`, the standalone tool-availability verb.

D4 (decided 2026-07-26): reports ``argv[0]`` of every declared command plus
``git`` — the only tool press itself contributes after D1 — each found
(the resolved pinned path) or missing, using D2's exact resolution
semantics: path-qualified argv0 against the TARGET root, bare names on the
deny-by-default effective PATH. Reads config, writes nothing, executes
nothing. Exit 0 all found, 1 any missing, 2 config/usage error.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from template_press import press_cli
from template_press.rebrand.check_tools import check_tools_command
from template_press.rebrand.rules import SUPPORTED_PLATFORMS

from .conftest import posix_only


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def _make_exe(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _line_for(out: str, argv0: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.startswith(f"{argv0} ")]
    assert lines, f"no report line for {argv0!r} in:\n{out}"
    return lines[0]


class TestResolution:
    @posix_only
    def test_all_found_exit_0(self, src_target: Path, capsys: pytest.CaptureFixture):
        exe = _make_exe(src_target / "tools" / "gen.sh")
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["./tools/gen.sh"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")

        rc = check_tools_command(["--target", str(src_target)])
        out = capsys.readouterr().out
        assert rc == 0
        assert str(exe) in _line_for(out, "./tools/gen.sh")
        assert "git" in out  # press's own tool is always reported

    def test_missing_bare_tool_exit_1_named(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\n'
            'command = ["press-test-absent-tool-8f3a"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")

        rc = check_tools_command(["--target", str(src_target)])
        line = _line_for(capsys.readouterr().out, "press-test-absent-tool-8f3a")
        assert rc == 1
        assert "missing" in line
        assert "bun.lock" in line  # the declaration it would break

    @posix_only
    def test_slash_argv0_resolves_against_target_root(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        exe = _make_exe(src_target / "scripts" / "regen")
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["scripts/regen"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")

        rc = check_tools_command(["--target", str(src_target)])
        assert rc == 0
        assert str(exe) in _line_for(capsys.readouterr().out, "scripts/regen")

    @posix_only
    def test_bare_argv0_resolves_on_effective_path(
        self,
        src_target: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        bindir = tmp_path / "bin"
        fake = _make_exe(bindir / "faketool")
        real_git = shutil.which("git")
        assert real_git is not None
        os.symlink(real_git, bindir / "git")
        monkeypatch.setenv("PATH", str(bindir))
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["faketool"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")

        rc = check_tools_command(["--target", str(src_target)])
        out = capsys.readouterr().out
        assert rc == 0
        assert str(fake) in _line_for(out, "faketool")


class TestSafety:
    @posix_only
    def test_executes_nothing(self, src_target: Path):
        sentinel = src_target / "EXECUTED"
        _make_exe(
            src_target / "tools" / "gen.sh",
            f'#!/bin/sh\ntouch "{sentinel}"\nexit 0\n',
        )
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["./tools/gen.sh"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")

        rc = check_tools_command(["--target", str(src_target)])
        assert rc == 0
        assert not sentinel.exists()

    def test_writes_nothing(self, src_target: Path):
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["bun", "install"]\n',
        )
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")
        before = {p for p in src_target.rglob("*") if ".git" not in p.parts}

        check_tools_command(["--target", str(src_target)])
        after = {p for p in src_target.rglob("*") if ".git" not in p.parts}
        assert after == before


class TestConfigAndDispatch:
    def test_no_declarations_reports_git_only(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        rc = check_tools_command(["--target", str(src_target)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "git" in out
        lines = out.strip().splitlines()
        assert lines[0].startswith("Platform: ")
        assert len(lines) == 2

    def test_invalid_config_exit_2(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        _write_rules(src_target, '[[regenerate]]\nfile = "bun.lock"\n')  # no command
        rc = check_tools_command(["--target", str(src_target)])
        assert rc == 2
        assert "error" in capsys.readouterr().err

    def test_missing_target_exit_2(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        rc = check_tools_command(["--target", str(tmp_path / "absent")])
        assert rc == 2
        assert "error" in capsys.readouterr().err

    def test_dispatch_via_press_cli(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        rc = press_cli.main(["check-tools", "--target", str(src_target)])
        assert rc == 0
        assert "git" in capsys.readouterr().out

    def test_usage_lists_the_verb(self, capsys: pytest.CaptureFixture):
        press_cli.main(["--help"])
        assert "check-tools" in capsys.readouterr().out


class TestConfigErrorNormalization:
    @pytest.mark.parametrize(
        "body",
        [
            "not [ valid toml",  # TOMLDecodeError
            b"\xff\xfe broken".decode("latin-1"),  # invalid UTF-8 on disk
        ],
    )
    def test_unparseable_config_exits_2(
        self, src_target: Path, body: str, capsys: pytest.CaptureFixture
    ):
        """Codex thread 3654657449: every config failure is the documented
        exit-2, matching the rebrand and verify entry points — no tracebacks."""
        d = src_target / "press"
        d.mkdir(exist_ok=True)
        (d / "press-rules.toml").write_bytes(body.encode("latin-1"))
        rc = check_tools_command(["--target", str(src_target)])
        assert rc == 2
        assert "error" in capsys.readouterr().err


class TestEditCommands:
    """E4 / Task 13: an [[edit]] command is a declared tool too — the report
    must resolve it with D2's semantics and name the file it edits, so a
    missing edit tool is discoverable before the press refuses."""

    @posix_only
    def test_edit_tool_found_names_the_edited_file(
        self,
        src_target: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        bindir = tmp_path / "bin"
        fake = _make_exe(bindir / "uv")
        real_git = shutil.which("git")
        assert real_git is not None
        os.symlink(real_git, bindir / "git")
        monkeypatch.setenv("PATH", str(bindir))
        _write_rules(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0", "--frozen"]\n'
            "expect = 'version = \"0.1.0\"'\n",
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare edit")

        rc = check_tools_command(["--target", str(src_target)])
        out = capsys.readouterr().out
        assert rc == 0
        assert f"uv — {fake} (edits pyproject.toml)" in out

    def test_missing_edit_tool_exit_1_names_the_edited_file(
        self, src_target: Path, capsys: pytest.CaptureFixture
    ):
        _write_rules(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["press-test-absent-tool-8f3a", "version"]\n'
            "expect = 'version = \"0.1.0\"'\n",
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare edit")

        rc = check_tools_command(["--target", str(src_target)])
        line = _line_for(capsys.readouterr().out, "press-test-absent-tool-8f3a")
        assert rc == 1
        assert "missing" in line
        assert "pyproject.toml" in line  # the declaration it would break

    @posix_only
    def test_only_the_active_platforms_edit_is_reported(
        self,
        src_target: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        """check-tools reads the platform-SELECTED rules: the active edit gets
        its row, and an edit declared for another platform contributes none —
        so its absent tool cannot fail a report it will never run in."""
        bindir = tmp_path / "bin"
        fake = _make_exe(bindir / "uv")
        real_git = shutil.which("git")
        assert real_git is not None
        os.symlink(real_git, bindir / "git")
        monkeypatch.setenv("PATH", str(bindir))
        inactive = next(p for p in sorted(SUPPORTED_PLATFORMS) if p != sys.platform)
        _write_rules(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0", "--frozen"]\n'
            "expect = 'version = \"0.1.0\"'\n"
            f'platforms = ["{sys.platform}"]\n'
            '\n[[edit]]\nfile = "README.md"\n'
            'command = ["press-test-inactive-tool-f82d"]\n'
            'expect = "x"\n'
            f'platforms = ["{inactive}"]\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare edits per platform")

        rc = check_tools_command(["--target", str(src_target)])
        out = capsys.readouterr().out
        assert rc == 0
        assert f"uv — {fake} (edits pyproject.toml)" in out
        assert "press-test-inactive-tool-f82d" not in out
        assert "README.md" not in out
