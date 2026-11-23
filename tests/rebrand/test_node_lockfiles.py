"""First-class npm, Bun, and pnpm lockfile handling (Task 7).

A declared lockfile regeneration is exempt from hermetic verify when the
file is on the tool's own cap; press only SUGGESTS the command for an
undeclared one and never runs it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.engine import REGENERATE_EXEMPTIBLE, scan_paths
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    load_rules,
    regenerate_suggestion,
)

from .conftest import DEST, SOURCE, posix_only, write_answers_file

PY = sys.executable

_COMMANDS = {
    "package-lock.json": '["npm", "install", "--package-lock-only", "--silent"]',
    "bun.lock": (
        '["sh", "-c", "command -v bun >/dev/null 2>&1 || exit 127; '
        'rm -f bun.lock && exec bun install --lockfile-only"]'
    ),
    "pnpm-lock.yaml": '["pnpm", "install", "--lockfile-only"]',
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _rels(target: Path) -> set[str]:
    rules = load_rules(target)
    return {e.rel.as_posix() for e in scan_paths(target, rules)}


def _lock_target(src_target: Path, file: str, rules_body: str) -> Path:
    (src_target / file).write_text("{}\n", encoding="utf-8")
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(rules_body, encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "lockfile")
    return src_target


def test_exemptible_cap_names_all_four_lockfiles() -> None:
    assert REGENERATE_EXEMPTIBLE == frozenset(
        {"uv.lock", "bun.lock", "package-lock.json", "pnpm-lock.yaml"}
    )
    assert "CHANGELOG.md" not in REGENERATE_EXEMPTIBLE


@pytest.mark.parametrize("file", ["package-lock.json", "pnpm-lock.yaml"])
def test_declared_lockfile_is_verify_exempt(src_target: Path, file: str) -> None:
    extra = (
        '[rules]\nextra_exclude_files = ["pnpm-lock.yaml"]\n'
        if file == "pnpm-lock.yaml"
        else ""
    )
    body = extra + f'[[regenerate]]\nfile = "{file}"\ncommand = ["tool"]\n'
    _lock_target(src_target, file, body)
    assert file not in _rels(src_target)


@pytest.mark.parametrize("file", ["package-lock.json", "pnpm-lock.yaml"])
def test_undeclared_lockfile_is_not_exempt(src_target: Path, file: str) -> None:
    (src_target / file).write_text("{}\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "lockfile")
    assert file in _rels(src_target)


def test_declared_package_lock_passes_verify_without_verify_exempt(
    tmp_path: Path,
) -> None:
    from template_press.rebrand.verify_cli import verify_command

    from .test_verify_cli import _commit, make_pressable

    repo = make_pressable(tmp_path)
    (repo / "package-lock.json").write_text(
        '{"name": "demo_widget"}\n', encoding="utf-8"
    )
    (repo / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "package-lock.json"\ncommand = ["npm", "install"]\n',
        encoding="utf-8",
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 0


def test_undeclared_package_lock_fails_verify(tmp_path: Path) -> None:
    from template_press.rebrand.verify_cli import verify_command

    from .test_verify_cli import _commit, make_pressable

    repo = make_pressable(tmp_path)
    (repo / "package-lock.json").write_text(
        '{"name": "demo_widget"}\n', encoding="utf-8"
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) != 0


def test_default_excludes_do_not_gain_pnpm() -> None:
    assert "pnpm-lock.yaml" not in DEFAULT_RULES.exclude_files


@pytest.mark.parametrize("file", list(_COMMANDS))
def test_suggestion_names_command(file: str) -> None:
    suggestion = regenerate_suggestion(file)
    assert suggestion is not None
    assert _COMMANDS[file] in suggestion


@pytest.mark.parametrize("file", ["uv.lock", "CHANGELOG.md", "sub/package-lock.json"])
def test_no_suggestion_for_other_files(file: str) -> None:
    assert regenerate_suggestion(file) is None


@pytest.mark.parametrize("file", list(_COMMANDS))
def test_suggestion_is_valid_paste_ready_toml(tmp_path: Path, file: str) -> None:
    suggestion = regenerate_suggestion(file)
    assert suggestion is not None
    parsed = tomllib.loads(suggestion)
    (entry,) = parsed["regenerate"]
    assert entry["file"] == file
    assert entry["scan"] == "boundary"
    target = tmp_path / "t"
    (target / "press").mkdir(parents=True)
    # pnpm-lock.yaml is not excluded by default; a pnpm target adds it.
    prefix = '[rules]\nextra_exclude_files = ["pnpm-lock.yaml"]\n\n'
    (target / "press" / "press-rules.toml").write_text(
        prefix + suggestion, encoding="utf-8"
    )
    rules = load_rules(target)
    (rule,) = rules.regenerate
    assert rule.file == file
    assert rule.scan == "boundary"
    assert rule.command == tuple(entry["command"])


@pytest.mark.parametrize("file", ["bun.lock", "package-lock.json"])
def test_preflight_prints_block_and_runs_nothing(
    src_target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], file: str
) -> None:
    marker = tmp_path / "ran"
    fake = tmp_path / "bin"
    fake.mkdir()
    for tool in ("npm", "bun"):
        script = fake / tool
        script.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        script.chmod(0o755)
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    (src_target / file).write_text("{}\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "lockfile")
    answers = write_answers_file(tmp_path, DEST)
    code = main(["--target", str(src_target), "--config", str(answers)])
    err = capsys.readouterr().err
    assert code == 2
    assert "[[regenerate]]" in err
    assert _COMMANDS[file] in err
    assert not marker.exists()


def test_preflight_gives_no_block_for_changelog(
    src_target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    (src_target / "CHANGELOG.md").write_text("## demo_widget\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "changelog")
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(src_target), "--config", str(answers)]) == 2
    assert "scan = " not in capsys.readouterr().err


def test_leftover_identity_in_regenerated_lockfile_fails_without_receipt(
    src_target: Path, tmp_path: Path
) -> None:
    """The exemption only skips the hermetic sandbox; the real press still
    scans the regenerated output and refuses a leftover source identity."""
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    code = (
        "import pathlib; "
        "pathlib.Path('package-lock.json').write_text("
        '\'{"name": "demo_widget"}\')'
    )
    (src_target / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (src_target / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "package-lock.json"\n'
        f"command = {json.dumps([PY, '-c', code])}\n"
        'scan = "boundary"\n',
        encoding="utf-8",
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "declare")
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(src_target), "--config", str(answers)]) == 1
    assert not (src_target / RECEIPT_REL).exists()


@posix_only
def test_bun_suggestion_leaves_lock_intact_when_bun_is_missing(
    tmp_path: Path,
) -> None:
    suggestion = regenerate_suggestion("bun.lock")
    assert suggestion is not None
    argv = tomllib.loads(suggestion)["regenerate"][0]["command"]
    work = tmp_path / "work"
    work.mkdir()
    (work / "bun.lock").write_text("keep\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    sh = shutil.which("sh")
    assert sh is not None
    result = subprocess.run(  # noqa: S603
        [sh, *argv[1:]],
        cwd=work,
        env={"PATH": str(empty)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 127
    assert (work / "bun.lock").read_text(encoding="utf-8") == "keep\n"


def test_pnpm_suggestion_names_the_required_exclude_and_loads(
    src_target: Path,
) -> None:
    suggestion = regenerate_suggestion("pnpm-lock.yaml")
    assert suggestion is not None
    assert '"pnpm-lock.yaml"' in suggestion.splitlines()[0]
    assert "[rules] extra_exclude_files" in suggestion.splitlines()[0]
    body = '[rules]\nextra_exclude_files = ["pnpm-lock.yaml"]\n\n' + suggestion
    _lock_target(src_target, "pnpm-lock.yaml", body)
    rules = load_rules(src_target)
    assert [rule.file for rule in rules.regenerate] == ["pnpm-lock.yaml"]
    assert "pnpm-lock.yaml" not in _rels(src_target)
