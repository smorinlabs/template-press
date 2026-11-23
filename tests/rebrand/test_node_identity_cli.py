"""CLI refusals for the optional npm_name / cli_name identity fields."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main

_BASE = (
    'package_name = "demo_widget"\n'
    'repo_name    = "demo-widget"\n'
    'app_name     = "demo"\n'
    'author       = "Demo Author"\n'
    'email        = "demo@example.test"\n'
    'owner        = "demolabs"\n'
)
_NEW = {"npm_name": '"@demo/widget-api"', "cli_name": '"demo-cli"'}


def _git(target: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _target(tmp_path: Path, source_extra: str = "") -> Path:
    target = tmp_path / "demo-widget"
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        "[identity]\n" + _BASE + source_extra, encoding="utf-8"
    )
    (target / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo-widget"\n'
        'version = "0.1.0"\n'
        'authors = [{name = "Demo Author", email = "demo@example.test"}]\n'
        "[project.scripts]\n"
        'demo = "demo_widget.cli:main"\n',
        encoding="utf-8",
    )
    (target / "src" / "demo_widget").mkdir(parents=True)
    (target / "src" / "demo_widget" / "__init__.py").write_text(
        '"""Demo."""\n', encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)  # noqa: S607
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "t")
    _git(
        target,
        "remote",
        "add",
        "origin",
        "https://github.com/demolabs/demo-widget.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def _answers(tmp_path: Path, extra: str = "", base: str | None = None) -> Path:
    path = tmp_path / "answers.toml"
    body = (
        base
        if base is not None
        else (
            'package_name = "acme_widget"\n'
            'repo_name    = "acme-widget"\n'
            'app_name     = "acme"\n'
            'author       = "Ada Lovelace"\n'
            'email        = "ada@example.test"\n'
            'owner        = "acmelabs"\n'
        )
    )
    path.write_text("[answers]\n" + body + extra, encoding="utf-8")
    return path


@pytest.mark.parametrize("field", ["npm_name", "cli_name"])
@pytest.mark.parametrize("side", ["source_only", "answers_only"])
def test_new_field_on_one_side_exits_2_without_writes(tmp_path, field, side):
    line = f"{field} = {_NEW[field]}\n"
    if side == "source_only":
        target = _target(tmp_path, source_extra=line)
        answers = _answers(tmp_path)
    else:
        target = _target(tmp_path)
        answers = _answers(tmp_path, extra=line)
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert _git(target, "status", "--porcelain") == ""


def test_source_equality_must_survive_in_answers(tmp_path):
    target = _target(tmp_path, source_extra='npm_name = "demo-widget"\n')
    answers = _answers(tmp_path, extra='npm_name = "something-else"\n')
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert _git(target, "status", "--porcelain") == ""
