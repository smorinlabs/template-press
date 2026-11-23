"""`press rebrand` and `press verify` honor the target-language guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, _git, write_answers_file
from .test_cli import write_source_config

PACKAGE_JSON = '{"name": "web-tools", "version": "1.0.0"}\n'
DECLARED = '[rules]\nlanguages = ["python"]\n'


def _multi_language_target(
    src_target: Path, rules: str | None = None, package_json: str = PACKAGE_JSON
) -> Path:
    write_source_config(src_target)
    (src_target / "package.json").write_text(package_json, encoding="utf-8")
    if rules is not None:
        (src_target / "press" / "press-rules.toml").write_text(rules, encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add node manifest")
    return src_target


def _status(target: Path) -> str:
    import subprocess

    return subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.mark.parametrize("extra", [[], ["--dry-run"]])
def test_rebrand_undeclared_exit2_no_writes(
    src_target: Path, tmp_path: Path, capsys, extra: list[str]
) -> None:
    target = _multi_language_target(src_target)
    answers = write_answers_file(tmp_path, DEST)
    code = main(["--target", str(target), "--config", str(answers), *extra])
    captured = capsys.readouterr()
    assert code == 2
    assert "[rules] languages is not declared" in captured.out + captured.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_verify_undeclared_exit2(src_target: Path, capsys) -> None:
    target = _multi_language_target(src_target)
    code = verify_command(["--target", str(target)])
    captured = capsys.readouterr()
    assert code == 2
    assert "[rules] languages is not declared" in captured.err
    assert _status(target) == ""


def test_declared_rebrand_then_verify_pass(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    target = _multi_language_target(src_target, DECLARED)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    rebrand_err = capsys.readouterr().err
    assert "package.json" in rebrand_err
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        "https://github.com/potatolabs/potato-launcher.git",
    )
    assert verify_command(["--target", str(target)]) == 0
    assert "ignored node (package.json)" in capsys.readouterr().err


def test_verify_json_stdout_is_one_object_when_ignoring(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    target = _multi_language_target(src_target, DECLARED)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    capsys.readouterr()
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        "https://github.com/potatolabs/potato-launcher.git",
    )
    assert verify_command(["--target", str(target), "--json"]) == 0
    captured = capsys.readouterr()
    assert isinstance(json.loads(captured.out), dict)
    assert "ignored node (package.json)" in captured.err


def test_rebrand_diagnostics_json_stdout_clean_when_ignoring(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    target = _multi_language_target(src_target, DECLARED)
    pycache = target / "src" / "demo_widget" / "__pycache__"
    pycache.mkdir()
    (pycache / "x.pyc").write_bytes(b"\0")
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(answers),
            "--dry-run",
            "--diagnostics-json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(captured.out)["code"] == "rename_closure_unauthorized"
    assert "ignored node" not in captured.err


def test_malformed_manifest_no_traceback_rebrand(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    target = _multi_language_target(src_target, DECLARED)
    (target / "package.json").write_text("{not json", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "break manifest")
    answers = write_answers_file(tmp_path, DEST)
    code = main(["--target", str(target), "--config", str(answers)])
    captured = capsys.readouterr()
    assert code == 2
    assert "cannot parse package.json" in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_malformed_manifest_no_traceback_verify(src_target: Path, capsys) -> None:
    target = _multi_language_target(src_target, DECLARED)
    (target / "package.json").write_text("{not json", encoding="utf-8")
    code = verify_command(["--target", str(target)])
    captured = capsys.readouterr()
    assert code == 2
    assert "cannot parse package.json" in captured.err
    assert "Traceback" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("rules", "package_json", "expected"),
    [
        pytest.param(
            '[rules]\nlanguages = ["python"]\n'
            'extra_exclude_files = ["pyproject.toml"]\n\n'
            '[[reset]]\nfile = "pyproject.toml"\nstub = "[tool.x]\\ny = 1\\n"\n',
            PACKAGE_JSON,
            "declares python",
            id="declared-manifest-loses-identity",
        ),
        pytest.param(
            '[rules]\nlanguages = ["python"]\n'
            'extra_exclude_files = ["package.json"]\n\n'
            '[[reset]]\nfile = "package.json"\nstub = "{not json\\n"\n',
            PACKAGE_JSON,
            "cannot parse package.json",
            id="ignored-manifest-becomes-invalid",
        ),
        pytest.param(
            '[rules]\nextra_exclude_files = ["package.json"]\n\n'
            '[[reset]]\nfile = "package.json"\n'
            'stub = "{\\"name\\": \\"tooling\\"}\\n"\n',
            '{"private": true}\n',
            "[rules] languages is not declared",
            id="undeclared-target-gains-second-language",
        ),
    ],
)
def test_rebrand_refuses_result_verify_would_refuse(
    src_target: Path,
    tmp_path: Path,
    capsys,
    rules: str,
    package_json: str,
    expected: str,
) -> None:
    target = _multi_language_target(src_target, rules, package_json)
    source_config = (target / SOURCE_CONFIG_REL).read_bytes()
    answers = write_answers_file(tmp_path, DEST)
    code = main(["--target", str(target), "--config", str(answers)])
    err = capsys.readouterr().err
    assert code == 1
    assert expected in err
    assert "PARTIALLY rewritten" in err
    assert not (target / RECEIPT_REL).exists()
    assert (target / SOURCE_CONFIG_REL).read_bytes() == source_config


def test_declared_manifest_in_remove_exit2_no_writes(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    other_platform = "linux" if sys.platform != "linux" else "darwin"
    rules = (
        DECLARED + '\n[[remove]]\nfile = "pyproject.toml"\nreason = "not shipped"\n'
        f'platforms = ["{other_platform}"]\n'
    )
    target = _multi_language_target(src_target, rules)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert verify_command(["--target", str(target)]) == 2
    captured = capsys.readouterr()
    assert "[[remove]] target" in captured.out + captured.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize(
    "authors",
    ['authors = { name = "Demo Author", email = "demo@example.test" }', "authors = 5"],
)
def test_malformed_authors_no_traceback(
    src_target: Path, tmp_path: Path, capsys, authors: str
) -> None:
    target = _multi_language_target(src_target, DECLARED)
    pyproject = target / "pyproject.toml"
    original = pyproject.read_text(encoding="utf-8")
    lines = [
        authors if line.startswith("authors") else line
        for line in original.splitlines()
    ]
    assert lines != original.splitlines()
    pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "malformed authors")
    answers = write_answers_file(tmp_path, DEST)
    rebrand_code = main(["--target", str(target), "--config", str(answers)])
    verify_code = verify_command(["--target", str(target)])
    captured = capsys.readouterr()
    assert isinstance(rebrand_code, int)
    assert isinstance(verify_code, int)
    assert "Traceback" not in captured.out + captured.err
