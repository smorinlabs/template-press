"""Discovery and cross-check of a target's root ``package.json``."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.discovery import discover, manifest_warnings, mismatches
from template_press.rebrand.node_manifest import read_node_manifest

from .conftest import SOURCE, requires_symlink

SOURCE_NODE = replace(
    SOURCE,
    package_name="acme_widget",
    repo_name="acme-widget",
    app_name="acme",
    author="Ann Lee",
    email="ann@example.test",
    owner="example-org",
)


def _write(target: Path, manifest: object) -> None:
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")


def _node(tmp_path: Path, **keys: object) -> Path:
    manifest: dict[str, object] = {
        "name": "@acme/widget-api",
        "author": "Ann Lee <ann@example.test> (https://example.test)",
        "bin": {"acme-cli": "cli.js"},
        "repository": "git+https://github.com/example-org/acme-widget.git",
    }
    manifest.update(keys)
    _write(tmp_path, manifest)
    return tmp_path


def test_pyproject_without_project_table_uses_package_json(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
    _node(tmp_path)
    found = discover(tmp_path)
    assert found.source_kind == "node"
    assert found.npm_name == "@acme/widget-api"


def test_python_target_keeps_python_kind(src_target: Path):
    found = discover(src_target)
    assert found.source_kind == "python"
    assert found.npm_name is None
    assert found.package_name == "demo_widget"


def test_no_manifest_has_no_kind(tmp_path: Path):
    assert discover(tmp_path).source_kind is None


def test_node_target_leaves_fatal_check_fields_undiscovered(tmp_path: Path):
    found = discover(_node(tmp_path))
    assert (found.package_name, found.app_names, found.author, found.email) == (
        None,
        (),
        None,
        None,
    )
    assert (found.owner, found.repo_name) == (None, None)  # git origin only
    assert (found.manifest_owner, found.manifest_repo_name) == (
        "example-org",
        "acme-widget",
    )


def test_author_string_form(tmp_path: Path):
    m = read_node_manifest(_node(tmp_path))
    assert m is not None
    assert (m.author, m.email) == ("Ann Lee", "ann@example.test")


def test_author_object_form(tmp_path: Path):
    m = read_node_manifest(
        _node(tmp_path, author={"name": "Ann Lee", "email": "ann@example.test"})
    )
    assert m is not None
    assert (m.author, m.email) == ("Ann Lee", "ann@example.test")


def test_string_bin_on_scoped_name_uses_unscoped_name(tmp_path: Path):
    m = read_node_manifest(_node(tmp_path, bin="cli.js"))
    assert m is not None
    assert m.bins == ("widget-api",)


def test_object_bin_preserves_order(tmp_path: Path):
    m = read_node_manifest(_node(tmp_path, bin={"first-cli": "a.js", "second": "b.js"}))
    assert m is not None
    assert m.bins == ("first-cli", "second")


def test_repository_string_and_object_forms(tmp_path: Path):
    for repo in (
        "git+https://github.com/example-org/acme-widget.git",
        {"type": "git", "url": "git+https://github.com/example-org/acme-widget.git"},
    ):
        m = read_node_manifest(_node(tmp_path, repository=repo))
        assert m is not None
        assert (m.owner, m.repo_name) == ("example-org", "acme-widget")


def test_valid_manifest_with_bom_parses(tmp_path: Path):
    (tmp_path / "package.json").write_bytes(b"\xef\xbb\xbf" + b'{"name": "pkg"}')
    m = read_node_manifest(tmp_path)
    assert m is not None
    assert m.name == "pkg"


@pytest.mark.parametrize("raw", ["{not json", "[]", "﻿{bad"])
def test_malformed_manifest_is_undiscoverable(tmp_path: Path, raw: str):
    (tmp_path / "package.json").write_text(raw, encoding="utf-8")
    assert read_node_manifest(tmp_path) is None
    assert discover(tmp_path).source_kind is None


@requires_symlink
def test_symlinked_manifest_is_not_followed(tmp_path: Path):
    real = tmp_path / "elsewhere.json"
    real.write_text('{"name": "pkg"}')
    target = tmp_path / "t"
    target.mkdir()
    (target / "package.json").symlink_to(real)
    assert read_node_manifest(target) is None


def test_declared_npm_name_mismatch_is_fatal(tmp_path: Path):
    found = discover(_node(tmp_path))
    source = replace(SOURCE_NODE, npm_name="@acme/other", cli_name="acme-cli")
    assert any("npm_name" in p for p in mismatches(source, found))


def test_declared_cli_name_must_be_bin_key(tmp_path: Path):
    found = discover(_node(tmp_path))
    source = replace(SOURCE_NODE, npm_name="@acme/widget-api", cli_name="nope")
    problems = mismatches(source, found)
    assert any("cli_name" in p for p in problems)
    assert not any("npm_name" in p for p in problems)


def test_matching_declared_names_are_clean(tmp_path: Path):
    found = discover(_node(tmp_path))
    source = replace(SOURCE_NODE, npm_name="@acme/widget-api", cli_name="acme-cli")
    assert mismatches(source, found) == []


def test_undeclared_manifest_disagreement_only_warns(tmp_path: Path):
    found = discover(_node(tmp_path, author="Bob <bob@example.test>"))
    assert mismatches(SOURCE_NODE, found) == []
    warnings = manifest_warnings(SOURCE_NODE, found)
    assert any("author" in w for w in warnings)
    assert any("email" in w for w in warnings)
    assert any("package_name" in w for w in warnings)
    assert any("app_name" in w for w in warnings)
    assert all(w.startswith("warning: ") for w in warnings)


def test_python_target_has_no_manifest_warnings(src_target: Path):
    assert manifest_warnings(SOURCE, discover(src_target)) == []


def test_node_target_skips_python_layout_check(tmp_path: Path):
    found = discover(_node(tmp_path))
    assert not any("layout" in p for p in mismatches(SOURCE_NODE, found))


def _node_press_target(tmp_path: Path) -> Path:
    target = tmp_path / "acme-widget"
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        "[identity]\n"
        'package_name = "acme_widget"\n'
        'repo_name = "acme-widget"\n'
        'app_name = "acme"\n'
        'author = "Ann Lee"\n'
        'email = "ann@example.test"\n'
        'owner = "example-org"\n',
        encoding="utf-8",
    )
    _node(target, author="Bob <bob@example.test>")
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.test"],
        ["config", "user.name", "t"],
        ["remote", "add", "origin", "https://github.com/example-org/acme-widget.git"],
        ["add", "-A"],
        ["commit", "-q", "-m", "seed"],
    ):
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )
    return target


def test_rebrand_and_verify_print_warnings_to_stderr(tmp_path: Path, capsys):
    from template_press.rebrand.cli import main
    from template_press.rebrand.verify_cli import verify_command

    target = _node_press_target(tmp_path)
    answers = tmp_path / "answers.toml"
    answers.write_text(
        "[answers]\n"
        'package_name = "new_widget"\n'
        'repo_name = "new-widget"\n'
        'app_name = "newapp"\n'
        'author = "Cy Doe"\n'
        'email = "cy@example.test"\n'
        'owner = "new-org"\n',
        encoding="utf-8",
    )
    main(["--target", str(target), "--config", str(answers), "--dry-run"])
    assert "warning: author:" in capsys.readouterr().err
    verify_command(["--target", str(target), "--json"])
    captured = capsys.readouterr()
    assert "warning: author:" in captured.err
    assert "warning:" not in captured.out
