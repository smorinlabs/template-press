"""End-to-end live acceptance tests for BAML targets using real ``baml-cli``.

Exercises Python and TypeScript BAML targets (root client, in-package client,
nested client, repeat press, and gitignored client with ``press clean``). All
fixtures use synthetic ``example.test`` identities and invoke ``baml-cli
generate`` only (no network or live LLM calls).

Run explicitly:
    PATH="<venv-with-baml-cli>/bin:$PATH" uv run pytest -m "" tests/rebrand/test_baml_acceptance.py -v
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.clean_cli import clean_command
from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.identity import Identity
from template_press.rebrand.verify_cli import verify_command

from .conftest import _git, write_answers_file

ACME = Identity(
    package_name="acme_widget",
    repo_name="acme-widget",
    app_name="acme_cli",
    author="Acme Author",
    email="acme@example.test",
    owner="acmelabs",
    display_name="Acme Widget",
)

ZETA = Identity(
    package_name="zeta_tool",
    repo_name="zeta-tool",
    app_name="zeta_cli",
    author="Zeta Author",
    email="zeta@example.test",
    owner="zetalabs",
    display_name="Zeta Tool",
)

NOVA = Identity(
    package_name="nova_app",
    repo_name="nova-app",
    app_name="nova_cli",
    author="Nova Author",
    email="nova@example.test",
    owner="novalabs",
    display_name="Nova App",
)


def _require_baml_cli(monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    raw = os.environ.get("BAML_CLI_BIN") or shutil.which("baml-cli")
    if not raw:
        pytest.skip("baml-cli is not installed (set BAML_CLI_BIN or add to PATH)")
    baml_bin = Path(raw).resolve()
    if not baml_bin.is_file():
        pytest.skip(f"baml-cli binary not found at {baml_bin}")
    current_path = os.environ.get("PATH", "")
    bin_dir = str(baml_bin.parent)
    if bin_dir not in current_path.split(os.pathsep):
        monkeypatch.setenv(
            "PATH", f"{bin_dir}{os.pathsep}{current_path}" if current_path else bin_dir
        )
    result = subprocess.run(  # noqa: S603
        [str(baml_bin), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)
    if not match:
        pytest.fail(f"could not parse baml-cli version from: {result.stdout!r}")
    return baml_bin, match.group(0)


def _baml_generate(baml_bin: Path, repo: Path) -> None:
    subprocess.run(  # noqa: S603
        [str(baml_bin), "generate"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _assert_matches_fresh_generate(
    baml_bin: Path, repo: Path, client_rel: str, scratch: Path
) -> None:
    pressed_snapshot = _snapshot_tree(repo / client_rel)
    assert pressed_snapshot, f"expected regenerated files under {client_rel}"
    fresh_repo = scratch / "fresh_generate"
    shutil.copytree(repo, fresh_repo, ignore=shutil.ignore_patterns(".git"))
    shutil.rmtree(fresh_repo / client_rel)
    _baml_generate(baml_bin, fresh_repo)
    fresh_snapshot = _snapshot_tree(fresh_repo / client_rel)
    assert pressed_snapshot == fresh_snapshot


def _assert_python_target_works(
    baml_bin: Path,
    repo: Path,
    client_rel: str,
    pkg_name: str,
    import_path: str,
    reply_class: str,
    fn_name: str,
) -> None:
    # Every generated Python file must parse and compile cleanly.
    client_root = repo / client_rel
    py_files = sorted(client_root.rglob("*.py"))
    assert py_files, f"no generated .py files under {client_rel}"
    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        compile(source, str(py_file), "exec")
    types_tree = ast.parse((client_root / "types.py").read_text(encoding="utf-8"))
    class_names = {
        node.name for node in ast.walk(types_tree) if isinstance(node, ast.ClassDef)
    }
    assert reply_class in class_names
    sync_text = (client_root / "sync_client.py").read_text(encoding="utf-8")
    assert fn_name in sync_text

    # Host package imports and runs cleanly under the pressed package name.
    host_env = dict(os.environ)
    host_env["PYTHONPATH"] = str(repo / "src")
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-B",
            "-c",
            f"from {pkg_name}.cli import main; assert main() == 0",
        ],
        cwd=repo,
        env=host_env,
        check=True,
        capture_output=True,
        text=True,
    )

    # If the baml-cli venv also has pydantic installed, verify runtime import too.
    venv_python = baml_bin.parent / "python"
    if not venv_python.is_file():
        return
    probe = subprocess.run(  # noqa: S603
        [
            str(venv_python),
            "-c",
            (
                "import importlib.util, sys; "
                "sys.exit(0 if importlib.util.find_spec('pydantic') else 1)"
            ),
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(repo / "src") if client_rel.startswith("src/") else str(repo)
    )
    code = (
        f"from {import_path}.types import {reply_class}; "
        f"obj = {reply_class}(summary='ok'); "
        f"assert obj.summary == 'ok'"
    )
    subprocess.run(  # noqa: S603
        [str(venv_python), "-B", "-c", code],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_baml_sources(
    repo: Path, *, output_type: str, output_dir: str, version: str
) -> None:
    baml_src = repo / "baml_src"
    baml_src.mkdir(parents=True, exist_ok=True)
    extra_mode = (
        "\n  default_client_mode sync" if output_type.startswith("python") else ""
    )
    (baml_src / "generators.baml").write_text(
        "generator target {\n"
        f'  output_type "{output_type}"\n'
        f'  output_dir "{output_dir}"\n'
        f'  version "{version}"{extra_mode}\n'
        "}\n",
        encoding="utf-8",
    )
    (baml_src / "clients.baml").write_text(
        "client<llm> AcmeWidgetClient {\n"
        "  provider openai\n"
        "  options {\n"
        '    model "gpt-4o-mini"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (baml_src / "main.baml").write_text(
        "class AcmeWidgetReply {\n"
        "  summary string\n"
        "}\n\n"
        "function SummarizeForAcmeWidget(input: string) -> AcmeWidgetReply {\n"
        "  client AcmeWidgetClient\n"
        '  prompt #"\n'
        "    Summarize for Acme Widget: {{ input }}\n"
        '  "#\n'
        "}\n",
        encoding="utf-8",
    )


def _init_python_baml_repo(
    tmp_path: Path,
    baml_bin: Path,
    version: str,
    *,
    output_dir: str,
    rules_toml: str,
    gitignore_client: bool = False,
) -> Path:
    repo = tmp_path / "py_baml_target"
    pkg = repo / "src" / "acme_widget"
    pkg.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        'name = "acme_widget"\n'
        'version = "0.1.0"\n'
        'description = "Acme Widget"\n'
        'authors = [{ name = "Acme Author", email = "acme@example.test" }]\n'
        'requires-python = ">=3.13"\n\n'
        "[project.scripts]\n"
        'acme_cli = "acme_widget.cli:main"\n',
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Acme Widget\n\nRun `acme_cli` from https://github.com/acmelabs/acme-widget.\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text('"""Acme Widget package."""\n', encoding="utf-8")
    (pkg / "cli.py").write_text(
        '"""acme_widget CLI."""\n\n'
        "def main() -> int:\n"
        '    print("Acme Widget")\n'
        "    return 0\n",
        encoding="utf-8",
    )
    (repo / "press").mkdir()
    (repo / SOURCE_CONFIG_REL).write_text(render_source_config(ACME), encoding="utf-8")
    (repo / "press" / "press-rules.toml").write_text(rules_toml, encoding="utf-8")
    gi = ".venv/\n__pycache__/\n"
    if gitignore_client:
        gi += "baml_client/\n"
    (repo / ".gitignore").write_text(gi, encoding="utf-8")
    _write_baml_sources(
        repo,
        output_type="python/pydantic",
        output_dir=output_dir,
        version=version,
    )
    _baml_generate(baml_bin, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "acme@example.test")
    _git(repo, "config", "user.name", "Acme Author")
    _git(repo, "remote", "add", "origin", "https://github.com/acmelabs/acme-widget.git")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init python baml fixture")
    return repo


def _init_ts_baml_repo(
    tmp_path: Path,
    baml_bin: Path,
    version: str,
    *,
    output_dir: str,
    client_rel: str,
) -> Path:
    repo = tmp_path / "ts_baml_target"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text(
        "{\n"
        '  "name": "acme-widget",\n'
        '  "version": "0.1.0",\n'
        '  "bin": { "acme_cli": "src/index.ts" },\n'
        '  "author": "Acme Author <acme@example.test>",\n'
        '  "repository": "https://github.com/acmelabs/acme-widget"\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Acme Widget\n\nRun `acme_cli` from https://github.com/acmelabs/acme-widget\n",
        encoding="utf-8",
    )
    (repo / "src" / "index.ts").write_text(
        "export const APP_TITLE = 'Acme Widget';\n",
        encoding="utf-8",
    )
    (repo / "press").mkdir()
    (repo / SOURCE_CONFIG_REL).write_text(render_source_config(ACME), encoding="utf-8")
    (repo / "press" / "press-rules.toml").write_text(
        "[rules]\n"
        'substring_rewrite_fields = ["display_name_pascal"]\n\n'
        "[[regenerate]]\n"
        f'dir = "{client_rel}"\n'
        'command = ["baml-cli", "generate"]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n',
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _write_baml_sources(
        repo,
        output_type="typescript",
        output_dir=output_dir,
        version=version,
    )
    _baml_generate(baml_bin, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "acme@example.test")
    _git(repo, "config", "user.name", "Acme Author")
    _git(repo, "remote", "add", "origin", "https://github.com/acmelabs/acme-widget.git")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init ts baml fixture")
    return repo


def _set_origin(repo: Path, identity: Identity) -> None:
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{identity.owner}/{identity.repo_name}.git",
    )


@pytest.mark.live
@pytest.mark.slow
def test_python_root_baml_client_press_and_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baml_bin, version = _require_baml_cli(monkeypatch)
    rules = (
        "[rules]\n"
        'substring_rewrite_fields = ["display_name_pascal"]\n\n'
        "[[regenerate]]\n"
        'dir = "baml_client"\n'
        'command = ["baml-cli", "generate"]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo = _init_python_baml_repo(
        tmp_path, baml_bin, version, output_dir="../", rules_toml=rules
    )
    answers = write_answers_file(tmp_path, ZETA)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    _set_origin(repo, ZETA)
    _assert_matches_fresh_generate(baml_bin, repo, "baml_client", tmp_path / "cmp")
    _assert_python_target_works(
        baml_bin,
        repo,
        "baml_client",
        "zeta_tool",
        "baml_client",
        "ZetaToolReply",
        "SummarizeForZetaTool",
    )
    assert verify_command(["--target", str(repo)]) == 0


@pytest.mark.live
@pytest.mark.slow
def test_python_in_package_baml_client_and_repeat_press(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baml_bin, version = _require_baml_cli(monkeypatch)
    rules = (
        "[rules]\n"
        'substring_rewrite_fields = ["display_name_pascal"]\n\n'
        "[[regenerate]]\n"
        'dir = "src/{package_name}/baml_client"\n'
        'command = ["baml-cli", "generate"]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo = _init_python_baml_repo(
        tmp_path,
        baml_bin,
        version,
        output_dir="../src/acme_widget",
        rules_toml=rules,
    )

    first_dir = tmp_path / "first"
    first_dir.mkdir()
    first_answers = write_answers_file(first_dir, ZETA)
    assert main(["--target", str(repo), "--config", str(first_answers)]) == 0
    _set_origin(repo, ZETA)
    assert not (repo / "src" / "acme_widget").exists()
    assert (repo / "src" / "zeta_tool" / "baml_client" / "inlinedbaml.py").is_file()
    _assert_matches_fresh_generate(
        baml_bin, repo, "src/zeta_tool/baml_client", tmp_path / "cmp1"
    )
    _assert_python_target_works(
        baml_bin,
        repo,
        "src/zeta_tool/baml_client",
        "zeta_tool",
        "zeta_tool.baml_client",
        "ZetaToolReply",
        "SummarizeForZetaTool",
    )
    assert verify_command(["--target", str(repo)]) == 0

    # Commit the first press and repeat-press to NOVA without editing press-rules.toml.
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pressed to zeta")
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second_answers = write_answers_file(second_dir, NOVA)
    assert (
        main(["--target", str(repo), "--config", str(second_answers), "--force"]) == 0
    )
    _set_origin(repo, NOVA)
    assert not (repo / "src" / "zeta_tool").exists()
    assert (repo / "src" / "nova_app" / "baml_client" / "inlinedbaml.py").is_file()
    _assert_matches_fresh_generate(
        baml_bin, repo, "src/nova_app/baml_client", tmp_path / "cmp2"
    )
    _assert_python_target_works(
        baml_bin,
        repo,
        "src/nova_app/baml_client",
        "nova_app",
        "nova_app.baml_client",
        "NovaAppReply",
        "SummarizeForNovaApp",
    )
    assert verify_command(["--target", str(repo)]) == 0


@pytest.mark.live
@pytest.mark.slow
def test_typescript_root_baml_client_and_repeat_press(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baml_bin, version = _require_baml_cli(monkeypatch)
    repo = _init_ts_baml_repo(
        tmp_path, baml_bin, version, output_dir="../", client_rel="baml_client"
    )
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(write_answers_file(first_dir, ZETA)),
            ]
        )
        == 0
    )
    _set_origin(repo, ZETA)
    _assert_matches_fresh_generate(baml_bin, repo, "baml_client", tmp_path / "cmp1")
    assert "ZetaToolReply" in (repo / "baml_client" / "types.ts").read_text(
        encoding="utf-8"
    )
    assert verify_command(["--target", str(repo)]) == 0

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pressed ts to zeta")
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(write_answers_file(second_dir, NOVA)),
                "--force",
            ]
        )
        == 0
    )
    _set_origin(repo, NOVA)
    _assert_matches_fresh_generate(baml_bin, repo, "baml_client", tmp_path / "cmp2")
    assert "NovaAppReply" in (repo / "baml_client" / "types.ts").read_text(
        encoding="utf-8"
    )
    assert verify_command(["--target", str(repo)]) == 0


@pytest.mark.live
@pytest.mark.slow
def test_typescript_nested_baml_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baml_bin, version = _require_baml_cli(monkeypatch)
    repo = _init_ts_baml_repo(
        tmp_path, baml_bin, version, output_dir="../src", client_rel="src/baml_client"
    )
    answers = write_answers_file(tmp_path, ZETA)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    _set_origin(repo, ZETA)
    _assert_matches_fresh_generate(baml_bin, repo, "src/baml_client", tmp_path / "cmp")
    assert "ZetaToolReply" in (repo / "src" / "baml_client" / "types.ts").read_text(
        encoding="utf-8"
    )
    assert verify_command(["--target", str(repo)]) == 0


@pytest.mark.live
@pytest.mark.slow
def test_gitignored_in_package_baml_client_with_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baml_bin, version = _require_baml_cli(monkeypatch)
    rules = (
        "[rules]\n"
        'substring_rewrite_fields = ["display_name_pascal"]\n\n'
        "[[clean]]\n"
        'paths = ["src/{package_name}/baml_client"]\n\n'
        "[[regenerate]]\n"
        'dir = "src/{package_name}/baml_client"\n'
        'command = ["baml-cli", "generate"]\n'
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo = _init_python_baml_repo(
        tmp_path,
        baml_bin,
        version,
        output_dir="../src/acme_widget",
        rules_toml=rules,
        gitignore_client=True,
    )
    assert (repo / "src" / "acme_widget" / "baml_client" / "inlinedbaml.py").is_file()
    assert clean_command(["--target", str(repo)]) == 0
    assert not (repo / "src" / "acme_widget" / "baml_client").exists()
    answers = write_answers_file(tmp_path, ZETA)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    _set_origin(repo, ZETA)
    assert (repo / "src" / "zeta_tool" / "baml_client" / "inlinedbaml.py").is_file()
    _assert_matches_fresh_generate(
        baml_bin, repo, "src/zeta_tool/baml_client", tmp_path / "cmp"
    )
    _assert_python_target_works(
        baml_bin,
        repo,
        "src/zeta_tool/baml_client",
        "zeta_tool",
        "zeta_tool.baml_client",
        "ZetaToolReply",
        "SummarizeForZetaTool",
    )
    assert verify_command(["--target", str(repo)]) == 0
