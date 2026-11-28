"""Tests for undeclared tracked BAML client refusal (Decision 8) and regen message (Decision 6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config

from .conftest import DEST, SOURCE, _git, init_git_repo, make_target, write_answers_file


def _write_source(repo: Path) -> None:
    (repo / "press").mkdir(exist_ok=True)
    (repo / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )


def _write_answers(tmp_path: Path) -> Path:
    return write_answers_file(tmp_path, DEST)


def _make_python_baml_target(
    tmp_path: Path,
    client_rel: str,
    *,
    rules_toml: str = "",
    gitignore_client: bool = False,
) -> Path:
    repo = make_target(tmp_path)
    _write_source(repo)
    (repo / "baml_src").mkdir(exist_ok=True)
    (repo / "baml_src" / "clients.baml").write_text(
        'client<llm> MainClient {\n  provider openai\n  options { model "gpt-4o-mini" }\n}\n',
        encoding="utf-8",
    )
    client_dir = repo / client_rel
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "inlinedbaml.py").write_text(
        '_FILE_MAP = {"clients.baml": "demo_widget"}\n',
        encoding="utf-8",
    )
    if gitignore_client:
        gi = repo / ".gitignore"
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        gi.write_text(existing + f"\n{client_rel}/\n", encoding="utf-8")
    if rules_toml:
        (repo / "press" / "press-rules.toml").write_text(rules_toml, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add baml fixture")
    return repo


def _make_ts_baml_target(
    tmp_path: Path,
    client_rel: str,
    *,
    rules_toml: str = "",
    gitignore_client: bool = False,
) -> Path:
    repo = tmp_path / "ts_target"
    repo.mkdir()
    init_git_repo(
        repo,
        origin="https://github.com/demolabs/demo-widget.git",
        commit_message=None,
    )
    (repo / "package.json").write_text(
        '{\n  "name": "demo-widget",\n  "version": "0.1.0",\n'
        '  "author": "Demo Author <demo@example.com>"\n}\n',
        encoding="utf-8",
    )
    _write_source(repo)
    (repo / "baml_src").mkdir(exist_ok=True)
    (repo / "baml_src" / "clients.baml").write_text(
        'client<llm> MainClient {\n  provider openai\n  options { model "gpt-4o-mini" }\n}\n',
        encoding="utf-8",
    )
    client_dir = repo / client_rel
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "inlinedbaml.ts").write_text(
        'export const _FILE_MAP = { "clients.baml": "demo_widget" };\n',
        encoding="utf-8",
    )
    if gitignore_client:
        (repo / ".gitignore").write_text(f"{client_rel}/\n", encoding="utf-8")
    if rules_toml:
        (repo / "press" / "press-rules.toml").write_text(rules_toml, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init ts baml fixture")
    return repo


def _git_status(repo: Path) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "status", "--porcelain"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_tracked_python_baml_client_at_root_refused(tmp_path: Path, capsys) -> None:
    repo = _make_python_baml_target(tmp_path, "baml_client")
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers)])
    assert code == 2
    err = capsys.readouterr().err
    assert "baml client baml_client has no [[regenerate]] declaration" in err
    assert 'dir = "baml_client"' in err
    assert 'command = ["uv", "run", "--offline", "baml-cli", "generate"]' in err
    assert "verify_exempt = true" in err
    assert 'reason = "BAML client, rebuilt from baml_src"' in err
    assert _git_status(repo) == ""


def test_tracked_python_baml_client_in_package_suggests_placeholder(
    tmp_path: Path, capsys
) -> None:
    repo = _make_python_baml_target(tmp_path, "src/demo_widget/baml_client")
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers)])
    assert code == 2
    err = capsys.readouterr().err
    assert (
        "baml client src/demo_widget/baml_client has no [[regenerate]] declaration"
        in err
    )
    assert 'dir = "src/{package_name}/baml_client"' in err
    assert 'command = ["uv", "run", "--offline", "baml-cli", "generate"]' in err
    assert "verify_exempt = true" in err
    assert 'reason = "BAML client, rebuilt from baml_src"' in err
    assert _git_status(repo) == ""


def test_tracked_ts_baml_client_at_root_and_nested_refused(
    tmp_path: Path, capsys
) -> None:
    for rel in ("baml_client", "src/baml_client"):
        sub = tmp_path / rel.replace("/", "_")
        sub.mkdir()
        repo = _make_ts_baml_target(sub, rel)
        answers = _write_answers(sub)
        code = main(["--target", str(repo), "--config", str(answers)])
        assert code == 2
        err = capsys.readouterr().err
        assert f"baml client {rel} has no [[regenerate]] declaration" in err
        assert f'dir = "{rel}"' in err
        assert 'command = ["npx", "baml-cli", "generate"]' in err
        assert "verify_exempt = true" in err
        assert _git_status(repo) == ""


def test_baml_client_covered_by_regenerate_dir_passes(tmp_path: Path) -> None:
    dest_pkg = DEST.package_name
    script = (
        "import pathlib; "
        f"d = pathlib.Path('src/{dest_pkg}/baml_client'); "
        "d.mkdir(parents=True, exist_ok=True); "
        f"(d / 'inlinedbaml.py').write_text('_FILE_MAP = {{\"a\": \"{dest_pkg}\"}}\\n')"
    )
    rules = (
        "[[regenerate]]\n"
        'dir = "src/{package_name}/baml_client"\n'
        f'command = [{json.dumps(sys.executable)}, "-c", {json.dumps(script)}]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo = _make_python_baml_target(
        tmp_path, "src/demo_widget/baml_client", rules_toml=rules
    )
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers), "--dry-run"])
    assert code == 0


def test_baml_client_covered_by_regenerate_file_passes(tmp_path: Path) -> None:
    rules = (
        "[rules]\n"
        'extra_exclude_files = ["baml_client/inlinedbaml.py"]\n\n'
        "[[regenerate]]\n"
        'file = "baml_client/inlinedbaml.py"\n'
        f'command = [{json.dumps(sys.executable)}, "-c", "pass"]\n'
    )
    repo = _make_python_baml_target(tmp_path, "baml_client", rules_toml=rules)
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers), "--dry-run"])
    assert code == 0


def test_baml_client_covered_by_remove_dir_or_file_passes(tmp_path: Path) -> None:
    sub_dir = tmp_path / "by_dir"
    sub_dir.mkdir()
    repo_dir = _make_python_baml_target(
        sub_dir,
        "baml_client",
        rules_toml='[[remove]]\ndir = "baml_client"\nreason = "drop baml client"\n',
    )
    assert (
        main(
            [
                "--target",
                str(repo_dir),
                "--config",
                str(_write_answers(sub_dir)),
                "--dry-run",
            ]
        )
        == 0
    )

    sub_file = tmp_path / "by_file"
    sub_file.mkdir()
    repo_file = _make_python_baml_target(
        sub_file,
        "baml_client",
        rules_toml=(
            '[[remove]]\nfile = "baml_client/inlinedbaml.py"\n'
            'reason = "drop baml marker"\n'
        ),
    )
    assert (
        main(
            [
                "--target",
                str(repo_file),
                "--config",
                str(_write_answers(sub_file)),
                "--dry-run",
            ]
        )
        == 0
    )


def test_gitignored_baml_client_is_not_refused(tmp_path: Path) -> None:
    repo = _make_python_baml_target(tmp_path, "baml_client", gitignore_client=True)
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers), "--dry-run"])
    assert code == 0


def test_languages_baml_rejected_as_unknown_language(tmp_path: Path, capsys) -> None:
    repo = _make_python_baml_target(
        tmp_path,
        "baml_client",
        rules_toml='[rules]\nlanguages = ["baml"]\n',
        gitignore_client=True,
    )
    answers = _write_answers(tmp_path)
    code = main(["--target", str(repo), "--config", str(answers), "--dry-run"])
    assert code == 2
    err = capsys.readouterr().err
    assert "baml" in err


def test_regeneration_failure_message_names_output_not_lockfile(
    tmp_path: Path, capsys
) -> None:
    # Test [[regenerate]] dir failure message
    sub_dir = tmp_path / "dir_fail"
    sub_dir.mkdir()
    rules_dir = (
        "[[regenerate]]\n"
        'dir = "baml_client"\n'
        f'command = [{json.dumps(sys.executable)}, "-c", "import sys; sys.exit(1)"]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo_dir = _make_python_baml_target(sub_dir, "baml_client", rules_toml=rules_dir)
    code_dir = main(
        ["--target", str(repo_dir), "--config", str(_write_answers(sub_dir))]
    )
    assert code_dir == 1
    err_dir = capsys.readouterr().err
    assert "regeneration of baml_client failed" in err_dir
    assert "lockfile" not in err_dir.lower()

    # Test [[regenerate]] file failure message
    sub_file = tmp_path / "file_fail"
    sub_file.mkdir()
    rules_file = (
        "[rules]\n"
        'extra_exclude_files = ["generated.txt"]\n\n'
        "[[regenerate]]\n"
        'file = "generated.txt"\n'
        f'command = [{json.dumps(sys.executable)}, "-c", "import sys; sys.exit(1)"]\n'
    )
    repo_file = make_target(sub_file)
    _write_source(repo_file)
    (repo_file / "generated.txt").write_text("demo_widget\n", encoding="utf-8")
    (repo_file / "press" / "press-rules.toml").write_text(rules_file, encoding="utf-8")
    _git(repo_file, "add", "-A")
    _git(repo_file, "commit", "-m", "add generated file")
    code_file = main(
        ["--target", str(repo_file), "--config", str(_write_answers(sub_file))]
    )
    assert code_file == 1
    err_file = capsys.readouterr().err
    assert "regeneration of generated.txt failed" in err_file
    assert "lockfile" not in err_file.lower()
