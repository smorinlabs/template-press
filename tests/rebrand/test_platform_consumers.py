"""P07-TS02 — one captured selection and active-only environmental gates."""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

import template_press.rebrand.check_tools as check_tools_module
import template_press.rebrand.cli as cli_module
import template_press.rebrand.verify_cli as verify_cli_module
from template_press.rebrand.config import render_source_config
from template_press.rebrand.regen import (
    plan_regenerate_commands,
    preflight_excluded_files,
)
from template_press.rebrand.reset import preflight_reset_targets
from template_press.rebrand.rules import load_selected_rules

from .conftest import DEST, SOURCE, write_answers_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _write_rules(target: Path, body: str) -> Path:
    press = target / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def _called_names(module: ModuleType) -> list[str]:
    tree = ast.parse(inspect.getsource(module), filename=inspect.getfile(module))
    return [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


@pytest.mark.parametrize(
    "module",
    [cli_module, check_tools_module, verify_cli_module],
    ids=["rebrand", "check-tools", "verify"],
)
def test_each_command_boundary_loads_selected_rules_exactly_once(
    module: ModuleType,
) -> None:
    calls = _called_names(module)

    assert calls.count("load_selected_rules") == 1
    assert "load_rules" not in calls


def test_rebrand_threads_the_one_active_rules_object_through_consumers(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    press = src_target / "press"
    press.mkdir(exist_ok=True)
    (press / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    _write_rules(src_target, '[rules]\nextra_exclude_dirs = ["vendor"]\n')
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add press config")
    selected = load_selected_rules(src_target, platform="darwin")
    answers = write_answers_file(tmp_path, DEST)
    loads: list[Path] = []

    def load_once(target: Path):
        loads.append(target)
        return selected

    monkeypatch.setattr(cli_module, "load_selected_rules", load_once, raising=False)
    seen: set[str] = set()

    def guard_rules(name: str, index: int) -> None:
        original = getattr(cli_module, name)

        def guarded(*args, **kwargs):
            assert args[index] is selected.rules
            seen.add(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(cli_module, name, guarded)

    for name, index in (
        ("build_plan", 3),
        ("preflight_excluded_files", 1),
        ("preflight_regenerate_outputs", 1),
        ("preflight_reset_targets", 1),
        ("apply", 3),
    ):
        guard_rules(name, index)

    code = cli_module.main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )

    assert code == 0
    assert loads == [src_target.resolve()]
    assert seen == {
        "build_plan",
        "preflight_excluded_files",
        "preflight_regenerate_outputs",
        "preflight_reset_targets",
        "apply",
    }


def test_inactive_missing_regeneration_tool_is_not_preflighted(
    tmp_path: Path,
) -> None:
    target = _write_rules(
        tmp_path,
        '[[regenerate]]\nfile = "bun.lock"\ncommand = ["git"]\n'
        'platforms = ["darwin", "linux"]\n'
        '[[regenerate]]\nfile = "bun.lock"\n'
        'command = ["press-test-absent-windows-tool-7c1b"]\n'
        'platforms = ["win32"]\n',
    )

    posix = load_selected_rules(target, platform="darwin")
    _, posix_problems = plan_regenerate_commands(
        target, posix.rules.regenerate, renamed=()
    )
    windows = load_selected_rules(target, platform="win32")
    _, windows_problems = plan_regenerate_commands(
        target, windows.rules.regenerate, renamed=()
    )

    assert posix_problems == []
    assert any("press-test-absent-windows-tool-7c1b" in p for p in windows_problems)


@pytest.mark.parametrize("stub_state", ["missing", "non-utf8"])
def test_inactive_bad_reset_stub_file_is_not_preflighted(
    src_target: Path, stub_state: str
) -> None:
    (src_target / "CHANGELOG.md").write_text("## history\n", encoding="utf-8")
    _write_rules(
        src_target,
        '[[reset]]\nfile = "CHANGELOG.md"\n'
        'stub_file = "press/stubs/CHANGELOG.md"\n'
        'platforms = ["win32"]\n',
    )
    if stub_state == "non-utf8":
        stub = src_target / "press" / "stubs" / "CHANGELOG.md"
        stub.parent.mkdir(parents=True)
        stub.write_bytes(b"\xff\xfe broken")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add platform reset")

    inactive = load_selected_rules(src_target, platform="darwin")
    inactive_previews, inactive_problems = preflight_reset_targets(
        src_target,
        inactive.rules,
        source=SOURCE,
        dest=DEST,
        renames={},
    )
    active = load_selected_rules(src_target, platform="win32")
    _, active_problems = preflight_reset_targets(
        src_target,
        active.rules,
        source=SOURCE,
        dest=DEST,
        renames={},
    )

    assert inactive_previews == []
    assert inactive_problems == []
    assert active_problems
    assert any("stub" in problem or "UTF-8" in problem for problem in active_problems)


def test_excluded_file_neutralization_uses_selected_platform(
    src_target: Path,
) -> None:
    (src_target / "bun.lock").write_text("lock\n", encoding="utf-8")
    _write_rules(
        src_target,
        '[[regenerate]]\nfile = "bun.lock"\ncommand = ["git"]\n'
        'platforms = ["darwin", "linux"]\n',
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add platform regeneration")

    posix = load_selected_rules(src_target, platform="darwin")
    windows = load_selected_rules(src_target, platform="win32")

    assert preflight_excluded_files(src_target, posix.rules) == []
    windows_problems = preflight_excluded_files(src_target, windows.rules)
    assert any("bun.lock" in problem for problem in windows_problems)


def test_platform_selection_does_not_expand_verifier_scan_inputs() -> None:
    parameters = inspect.signature(verify_cli_module.scan).parameters

    assert set(parameters).isdisjoint(
        {"selected", "platform", "platforms", "table", "rendered_rules"}
    )
    source = inspect.getsource(verify_cli_module.verify_command)
    assert "platforms" not in source
