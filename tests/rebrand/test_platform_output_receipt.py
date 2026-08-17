"""P07-TS03 — platform output, tool ordering, exits, and receipt evidence."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import template_press.rebrand.check_tools as check_tools_module
from template_press.rebrand.check_tools import check_tools_command
from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import SUPPORTED_PLATFORMS, load_selected_rules

from .conftest import DEST, SOURCE, posix_only, write_answers_file

PLATFORM = sys.platform
INACTIVE_PLATFORM = next(value for value in SUPPORTED_PLATFORMS if value != PLATFORM)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _write_rules(target: Path, body: str) -> None:
    press = target / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")


def _write_source_config(target: Path) -> None:
    press = target / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )


def _platform_rules(active_command: str = "git") -> str:
    return (
        '[[regenerate]]\nfile = "bun.lock"\n'
        f'command = ["{active_command}"]\nplatforms = ["{PLATFORM}"]\n'
        '[[regenerate]]\nfile = "package-lock.json"\n'
        'command = ["press-test-inactive-tool-f82d"]\n'
        f'platforms = ["{INACTIVE_PLATFORM}"]\n'
        '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n'
        f'platforms = ["{PLATFORM}"]\n'
        '[[reset]]\nfile = "uv.lock"\nstub_file = "press/stubs/missing.md"\n'
        f'platforms = ["{INACTIVE_PLATFORM}"]\n'
    )


def test_combined_plan_names_platform_once_and_omits_inactive_actions(
    src_target: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source_config(src_target)
    _write_rules(src_target, _platform_rules())
    (src_target / "bun.lock").write_text("demo_widget\n", encoding="utf-8")
    (src_target / "CHANGELOG.md").write_text(
        "## demo_widget history\n", encoding="utf-8"
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add platform actions")
    answers = write_answers_file(tmp_path, DEST)

    code = main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.count(f"Platform: {PLATFORM}") == 1
    assert "bun.lock" in out
    assert "CHANGELOG.md" in out
    assert "press-test-inactive-tool-f82d" not in out
    assert "package-lock.json" not in out
    assert "uv.lock" not in out


def test_check_tools_names_platform_once_and_orders_git_before_active_tools(
    src_target: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_rules(src_target, _platform_rules())

    code = check_tools_command(["--target", str(src_target)])
    lines = capsys.readouterr().out.splitlines()

    assert code == 0
    assert lines.count(f"Platform: {PLATFORM}") == 1
    git_lines = [index for index, line in enumerate(lines) if line.startswith("git —")]
    assert len(git_lines) == 2
    assert "press itself needs it" not in lines[git_lines[0]]
    assert "regenerates bun.lock" in lines[git_lines[1]]
    assert git_lines[0] < git_lines[1]
    assert not any("press-test-inactive-tool-f82d" in line for line in lines)


def test_check_tools_still_checks_git_when_no_action_is_active(
    src_target: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_rules(
        src_target,
        '[[regenerate]]\nfile = "bun.lock"\ncommand = ["inactive"]\n'
        f'platforms = ["{INACTIVE_PLATFORM}"]\n',
    )

    code = check_tools_command(["--target", str(src_target)])
    lines = capsys.readouterr().out.splitlines()

    assert code == 0
    assert len(lines) == 2
    assert lines[0] == f"Platform: {PLATFORM}"
    assert lines[1].startswith("git —")


def test_check_tools_missing_git_exits_1(
    src_target: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(check_tools_module, "resolve_executable", lambda *_args: None)

    code = check_tools_command(["--target", str(src_target)])
    out = capsys.readouterr().out

    assert code == 1
    assert "git — missing" in out


def test_check_tools_missing_active_tool_exits_1(
    src_target: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    absent = "press-test-absent-active-tool-3a91"
    _write_rules(
        src_target,
        '[[regenerate]]\nfile = "bun.lock"\n'
        f'command = ["{absent}"]\nplatforms = ["{PLATFORM}"]\n',
    )

    code = check_tools_command(["--target", str(src_target)])
    lines = capsys.readouterr().out.splitlines()

    assert code == 1
    assert lines[0] == f"Platform: {PLATFORM}"
    assert lines[1].startswith("git —")
    assert absent in lines[2] and "missing" in lines[2]


@pytest.mark.parametrize("failure", ["bad-config", "unsupported-runtime"])
def test_check_tools_config_or_runtime_error_exits_2(
    src_target: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if failure == "bad-config":
        _write_rules(src_target, '[[regenerate]]\nfile = "bun.lock"\n')
    else:
        monkeypatch.setattr(
            check_tools_module,
            "load_selected_rules",
            lambda target: load_selected_rules(target, platform="freebsd14"),
        )

    code = check_tools_command(["--target", str(src_target)])

    assert code == 2
    assert "error:" in capsys.readouterr().err


@posix_only
def test_success_receipt_records_platform_and_only_active_actions(
    src_target: Path,
    tmp_path: Path,
) -> None:
    _write_source_config(src_target)
    script = src_target / "scripts" / "p07-regen-bun.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "#!/bin/sh\nset -eu\nprintf 'potato_launcher\\n' > bun.lock\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    _write_rules(src_target, _platform_rules("scripts/p07-regen-bun.sh"))
    (src_target / "bun.lock").write_text("demo_widget\n", encoding="utf-8")
    (src_target / "CHANGELOG.md").write_text(
        "## demo_widget history\n", encoding="utf-8"
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add platform actions")
    answers = write_answers_file(tmp_path, DEST)

    code = main(["--target", str(src_target), "--config", str(answers)])

    assert code == 0
    data = tomllib.loads((src_target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert data["press"]["platform"] == PLATFORM
    assert data["press"]["reset"] == [{"file": "CHANGELOG.md"}]
    assert [item["file"] for item in data["press"]["regenerate"]] == ["bun.lock"]
    assert "package-lock.json" not in str(data)
    assert "uv.lock" not in str(data)
