"""`press rebrand` and `press verify` honor the target-language guard."""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.discovery import discover
from template_press.rebrand.identity import Identity
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.substitutions import compile_substitution_table
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, SOURCE, _git, write_answers_file
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


# --- Declaration shapes: which manifests each command cross-checks -----------

NODE_NAME = "@demolabs/demo-api"
NODE_SOURCE = replace(SOURCE, npm_name=NODE_NAME, cli_name="demo-cli")
NODE_DEST = replace(DEST, npm_name="@potatolabs/potato-api", cli_name="potato-cli")
PYTHON = ["python"]
NODE = ["node"]
BOTH = ["python", "node"]


def _toml_identity(identity: Identity, table: str) -> str:
    rows = identity.as_dict_prompted().items()
    return f"[{table}]\n" + "".join(f'{k} = "{v}"\n' for k, v in rows)


def _declared_target(
    target: Path,
    languages: list[str],
    *,
    drift: str | None = None,
    rules_extra: str = "",
    source_config: bool = True,
) -> Path:
    """A Python + Node target; ``drift`` makes one manifest disagree."""
    name = "@elsewhere/other" if drift == "node" else NODE_NAME
    manifest = {"name": name, "version": "1.0.0", "bin": {"demo-cli": "./cli.js"}}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    pyproject = target / "pyproject.toml"
    # The stock description is a separator variant verify would report.
    text = pyproject.read_text(encoding="utf-8").replace("Demo widget by ", "By ")
    if drift == "python":
        text = text.replace("demo@example.com", "drift@example.test")
    pyproject.write_text(text, encoding="utf-8")
    control = target / "press"
    control.mkdir(exist_ok=True)
    if source_config:
        (control / "press-source.toml").write_text(
            _toml_identity(NODE_SOURCE, "identity"), encoding="utf-8"
        )
    (control / "press-rules.toml").write_text(
        f"[rules]\nlanguages = {json.dumps(languages)}\n{rules_extra}",
        encoding="utf-8",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "declare languages")
    return target


def _node_answers(base: Path) -> Path:
    path = base / "node-answers.toml"
    path.write_text(_toml_identity(NODE_DEST, "answers"), encoding="utf-8")
    return path


DECLARATION_CASES = [
    (PYTHON, None, 0),
    (PYTHON, "node", 0),
    (PYTHON, "python", 2),
    (NODE, None, 0),
    (NODE, "python", 0),
    (NODE, "node", 2),
    (BOTH, None, 0),
    (BOTH, "python", 2),
    (BOTH, "node", 2),
]


@pytest.mark.parametrize(("languages", "drift", "expected"), DECLARATION_CASES)
def test_rebrand_checks_only_declared_manifests(
    src_target: Path, tmp_path: Path, languages, drift, expected
) -> None:
    target = _declared_target(src_target, languages, drift=drift)
    answers = _node_answers(tmp_path)
    code = main(["--target", str(target), "--config", str(answers), "--dry-run"])
    assert code == expected
    assert _status(target) == ""


@pytest.mark.parametrize(("languages", "drift", "expected"), DECLARATION_CASES)
def test_verify_checks_only_declared_manifests(
    src_target: Path, languages, drift, expected
) -> None:
    target = _declared_target(src_target, languages, drift=drift)
    assert verify_command(["--target", str(target)]) == expected
    assert _status(target) == ""


@pytest.mark.parametrize(
    ("languages", "kind", "python_fields", "node_fields"),
    [
        (PYTHON, "python", True, False),
        (NODE, "node", False, True),
        (BOTH, "python", True, True),
        (["node", "python"], "python", True, True),
        ((), "python", True, True),
        (("unknown",), "python", True, True),
    ],
)
def test_discover_follows_checked_languages(
    src_target: Path, languages, kind, python_fields, node_fields
) -> None:
    target = _declared_target(src_target, BOTH)
    found = discover(target, languages)
    assert found.source_kind == kind
    assert (found.package_name == "demo_widget") is python_fields
    assert (found.npm_name == NODE_NAME) is node_fields


@pytest.mark.parametrize("languages", [NODE, BOTH])
def test_pressed_node_target_passes_guard_and_writes_receipt(
    src_target: Path, tmp_path: Path, languages
) -> None:
    target = _declared_target(src_target, languages)
    answers = _node_answers(tmp_path)
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert (target / RECEIPT_REL).is_file()
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pressed["name"] == "@potatolabs/potato-api"


def test_pressed_tree_failing_node_guard_exits_1_without_receipt(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    extra = (
        'extra_exclude_files = ["package.json"]\n\n'
        '[[reset]]\nfile = "package.json"\nstub = "{}\\n"\n'
    )
    target = _declared_target(src_target, NODE, rules_extra=extra)
    answers = _node_answers(tmp_path)
    code = main(["--target", str(target), "--config", str(answers)])
    captured = capsys.readouterr()
    assert code == 1
    assert "declares node" in captured.out + captured.err
    assert not (target / RECEIPT_REL).exists()


def test_no_source_config_with_both_languages_proposes_distinct_npm_name(
    src_target: Path, tmp_path: Path
) -> None:
    target = _declared_target(src_target, BOTH, source_config=False)
    # The distinct package.json bin is proposed, so the answers must rename it.
    answers = write_answers_file(tmp_path, NODE_DEST)
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["from"]["package_name"] == "demo_widget"
    assert receipt["press"]["from"]["app_name"] == "press"
    assert receipt["press"]["from"]["npm_name"] == NODE_NAME
    assert receipt["press"]["from"]["cli_name"] == "demo-cli"
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pressed["name"] == NODE_DEST.npm_name


@pytest.mark.parametrize("name", ["demo-widget", "demo_widget"])
def test_no_source_config_omits_npm_name_equal_to_proposed_names(
    src_target: Path, tmp_path: Path, name: str
) -> None:
    target = _declared_target(src_target, BOTH, source_config=False)
    (target / "package.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "name equals identity")
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert "npm_name" not in receipt["press"]["from"]


def _nameless_node_target(base: Path) -> Path:
    target = base / "demo-widget"
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        _toml_identity(replace(SOURCE, cli_name="acme-cli"), "identity"),
        encoding="utf-8",
    )
    (target / "package.json").write_text(
        '{"version":"1.0.0","bin":{"other-cli":"./c.js"}}', encoding="utf-8"
    )
    (target / "README.md").write_text(
        "demo_widget demo-widget press demolabs acme-cli\n", encoding="utf-8"
    )
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(
        target, "remote", "add", "origin", "https://github.com/demolabs/demo-widget.git"
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def test_rebrand_keeps_cli_check_for_nameless_manifest(tmp_path, capsys) -> None:
    target = _nameless_node_target(tmp_path)
    answers = tmp_path / "answers.toml"
    answers.write_text(
        _toml_identity(replace(DEST, cli_name="new-cli"), "answers"), encoding="utf-8"
    )
    code = main(["--target", str(target), "--config", str(answers), "--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert "cli_name" in captured.out + captured.err
    assert _status(target) == ""


def test_verify_keeps_cli_check_for_nameless_manifest(tmp_path, capsys) -> None:
    target = _nameless_node_target(tmp_path)
    assert verify_command(["--target", str(target)]) == 2
    assert "cli_name" in capsys.readouterr().err
    assert _status(target) == ""


def _manifest_rows(target: Path, source, dest, languages):
    rules = replace(DEFAULT_RULES, languages=languages)
    table = compile_substitution_table(
        source, dest, rules, capture_surface_snapshot(target), target=target
    )
    return {row.row_id: row for row in table.rows}


@pytest.mark.parametrize(
    ("languages", "present"),
    [(None, True), (("python",), True), (("python", "node"), True), (("node",), False)],
)
def test_manifest_rows_read_pyproject_only_for_python(
    src_target: Path, languages, present: bool
) -> None:
    pyproject = src_target / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "demo_widget"', 'name = "demo-widget"'
        ),
        encoding="utf-8",
    )
    named = _manifest_rows(
        src_target, SOURCE, replace(DEST, repo_name="other-repo"), languages
    )
    assert ("manifest:name" in named) is present
    hyphen = _manifest_rows(
        src_target, replace(SOURCE, repo_name="elsewhere"), DEST, languages
    )["identity:package_name_hyphen"]
    assert bool(hyphen.rewrite_surfaces) is present
    assert hyphen.hunts
