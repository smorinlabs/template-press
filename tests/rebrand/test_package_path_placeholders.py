"""P19-TS03: {package_name} placeholders in regeneration paths and extra_exclude_files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from template_press.rebrand.check_tools import check_tools_command
from template_press.rebrand.cli import main
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules, render_package_paths
from template_press.rebrand.verify_cli import verify_command

from .test_glued_name_preflight import (
    ACME_SOURCE,
    ZETA_DEST,
    _git,
    _init_repo,
    _python_files,
    _write_answers,
)

PY = sys.executable

NOVA_DEST = Identity(
    package_name="nova_app",
    repo_name="nova-app",
    app_name="nova",
    author="Nova Author",
    email="nova@example.test",
    owner="novalabs",
    display_name="Nova App",
)


def _write_rules(tmp_path: Path, body: str) -> Path:
    press = tmp_path / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_package_name_placeholder_parses_and_validates(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path / "ok",
        "[rules]\n"
        'extra_exclude_files = ["src/{package_name}/generated.txt"]\n\n'
        "[[regenerate]]\n"
        'file = "src/{package_name}/generated.txt"\n'
        f"command = {json.dumps([PY, '-c', 'pass'])}\n",
    )
    rules = load_rules(target)
    assert "src/{package_name}/generated.txt" in rules.exclude_files
    assert rules.regenerate[0].file == "src/{package_name}/generated.txt"

    rendered = render_package_paths(rules, ACME_SOURCE)
    assert "src/acme_widget/generated.txt" in rendered.exclude_files
    assert rendered.regenerate[0].file == "src/acme_widget/generated.txt"


@pytest.mark.parametrize(
    "bad_path",
    [
        "src/{repo_name}/out.txt",
        "src/{app_name}/out.txt",
        "src/{package_name/out.txt",
        "src/package_name}/out.txt",
        "src/{{package_name}}/out.txt",
    ],
)
def test_unknown_or_malformed_placeholder_rejected(
    tmp_path: Path, bad_path: str
) -> None:
    target = _write_rules(
        tmp_path / "bad-regen",
        "[rules]\n"
        f"extra_exclude_files = {json.dumps([bad_path])}\n\n"
        "[[regenerate]]\n"
        f"file = {json.dumps(bad_path)}\n"
        f"command = {json.dumps([PY, '-c', 'pass'])}\n",
    )
    with pytest.raises(ValidationError):
        load_rules(target)


def test_package_name_rejected_in_extra_exclude_dirs(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path / "bad-dir",
        '[rules]\nextra_exclude_dirs = ["{package_name}"]\n',
    )
    with pytest.raises(ValidationError, match="extra_exclude_dirs"):
        load_rules(target)


def test_rendered_overlap_with_literal_rule_rejected(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path / "overlap",
        "[rules]\n"
        'extra_exclude_files = ["src/{package_name}/out.txt", "src/acme_widget/out.txt"]\n\n'
        "[[regenerate]]\n"
        'file = "src/{package_name}/out.txt"\n'
        f"command = {json.dumps([PY, '-c', 'pass'])}\n\n"
        "[[regenerate]]\n"
        'file = "src/acme_widget/out.txt"\n'
        f"command = {json.dumps([PY, '-c', 'pass'])}\n",
    )
    rules = load_rules(target)
    with pytest.raises(ValidationError, match="more than one"):
        render_package_paths(rules, ACME_SOURCE)


def test_package_name_placeholder_press_and_repeat_press(tmp_path: Path) -> None:
    regen_script = (
        "import pathlib, tomllib; "
        "pkg = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['name']; "
        "pathlib.Path(f'src/{pkg}/generated.txt').write_text(f'pkg={pkg}\\n', encoding='utf-8')"
    )
    rules_text = (
        "[rules]\n"
        'extra_exclude_files = ["src/{package_name}/generated.txt"]\n\n'
        "[[regenerate]]\n"
        'file = "src/{package_name}/generated.txt"\n'
        f"command = {json.dumps([PY, '-c', regen_script])}\n"
        "verify_exempt = true\n"
        'reason = "generated manifest"\n'
    )
    repo = _init_repo(
        tmp_path / "repeat",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"src/acme_widget/generated.txt": "pkg=acme_widget\n"},
        ),
        rules_text=rules_text,
    )

    assert check_tools_command(["--target", str(repo)]) == 0
    assert verify_command(["--target", str(repo)]) == 0

    # First press: acme_widget -> zeta_tool
    answers_1 = _write_answers(tmp_path / "a1", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers_1)]) == 0
    assert (repo / RECEIPT_REL).is_file()
    assert (repo / "src" / "zeta_tool" / "generated.txt").read_text(
        encoding="utf-8"
    ) == "pkg=zeta_tool\n"

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pressed to zeta")
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{ZETA_DEST.owner}/{ZETA_DEST.repo_name}.git",
    )
    assert verify_command(["--target", str(repo)]) == 0

    # Repeat press (--force): zeta_tool -> nova_app without touching press-rules.toml
    answers_2 = _write_answers(tmp_path / "a2", NOVA_DEST)
    assert main(["--target", str(repo), "--config", str(answers_2), "--force"]) == 0
    assert (repo / RECEIPT_REL).is_file()
    assert (repo / "src" / "nova_app" / "generated.txt").read_text(
        encoding="utf-8"
    ) == "pkg=nova_app\n"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pressed to nova")
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{NOVA_DEST.owner}/{NOVA_DEST.repo_name}.git",
    )
    assert verify_command(["--target", str(repo)]) == 0
