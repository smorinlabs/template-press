"""`press rebrand` and `press verify` honor the target-language guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, _git, write_answers_file
from .test_cli import write_source_config

PACKAGE_JSON = '{"name": "web-tools", "version": "1.0.0"}\n'
DECLARED = '[rules]\nlanguages = ["python"]\n'


def _multi_language_target(src_target: Path, rules: str | None = None) -> Path:
    write_source_config(src_target)
    (src_target / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
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
