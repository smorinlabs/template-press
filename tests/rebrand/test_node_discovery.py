"""Discovery and cross-check of a target's root ``package.json``."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import load_source_config
from template_press.rebrand.discovery import (
    discover,
    manifest_warnings,
    mismatches,
    node_proposal,
)
from template_press.rebrand.node_manifest import NodeManifest, read_node_manifest

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


# --- proposal from package.json (no source config) ---------------------------


def _proposal(
    name: str | None = "@acme/widget-api",
    bins: tuple[str, ...] = ("acme",),
    repo_name: str | None = "acme-widget",
) -> dict[str, str | None]:
    manifest = NodeManifest(
        name=name,
        author="Ann Lee",
        email="ann@example.test",
        bins=bins,
        owner=None,
        repo_name=None,
        named_bins=bins,
    )
    return node_proposal(manifest, "example-org", repo_name)


def test_proposal_derives_package_from_unscoped_name():
    p = _proposal()
    assert p["package_name"] == "widget_api"
    assert (p["owner"], p["repo_name"]) == ("example-org", "acme-widget")
    assert (p["author"], p["email"]) == ("Ann Lee", "ann@example.test")


def test_proposal_omits_npm_name_equal_to_repo_name():
    assert _proposal(name="acme-widget")["npm_name"] is None


def test_proposal_omits_npm_name_equal_to_package_name():
    assert _proposal(name="widget_api")["npm_name"] is None


def test_proposal_keeps_scoped_npm_name():
    assert _proposal()["npm_name"] == "@acme/widget-api"


def test_proposal_hyphenated_bin_sets_cli_name():
    p = _proposal(bins=("acme-cli",))
    assert (p["app_name"], p["cli_name"]) == ("acme_cli", "acme-cli")


def test_proposal_identifier_bin_needs_no_cli_name():
    p = _proposal(bins=("acme",))
    assert (p["app_name"], p["cli_name"]) == ("acme", None)


def test_proposal_without_bin_or_name_leaves_gaps():
    p = _proposal(name=None, bins=())
    assert (p["package_name"], p["app_name"], p["npm_name"]) == (None, None, None)


def _node_cli(
    tmp_path: Path,
    manifest: dict[str, object],
    origin: bool = False,
    answers_extra: str = "",
):
    target = tmp_path / "t"
    target.mkdir()
    _write(target, manifest)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)  # noqa: S607
    for args in (
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", "-C", str(target), *args], check=True)  # noqa: S603,S607
    if origin:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(target),
                "remote",
                "add",
                "origin",
                "https://github.com/example-org/acme-widget.git",
            ],
            check=True,
        )
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)  # noqa: S603,S607
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "seed"], check=True)  # noqa: S603,S607
    answers = tmp_path / "answers.toml"
    answers.write_text(
        "[answers]\n"
        'package_name = "new_widget"\nrepo_name = "new-widget"\n'
        'app_name = "newapp"\nauthor = "New Author"\n'
        'email = "new@example.test"\nowner = "newlabs"\n' + answers_extra,
        encoding="utf-8",
    )
    return target, answers


def test_sparse_manifest_exit_2_names_missing_keys(tmp_path: Path, capsys):
    target, answers = _node_cli(tmp_path, {"name": "@acme/widget-api"})
    code = main(["--target", str(target), "--config", str(answers)])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert code == 2
    assert "author" in out and "bin" in out
    assert not (target / "press" / "press-source.toml").exists()


def test_full_manifest_proposes_source_config(tmp_path: Path, capsys):
    target, answers = _node_cli(
        tmp_path,
        {
            "name": "@acme/widget-api",
            "author": "Ann Lee <ann@example.test>",
            "bin": {"acme-cli": "cli.js"},
        },
        origin=True,
    )
    code = main(["--target", str(target), "--config", str(answers)])
    out = capsys.readouterr().out
    assert code == 2
    assert 'package_name = "widget_api"' in out
    assert 'npm_name = "@acme/widget-api"' in out
    assert 'cli_name = "acme-cli"' in out
    assert 'app_name = "acme_cli"' in out
    assert not (target / "press" / "press-source.toml").exists()


def test_accept_discovery_writes_parseable_source_config(tmp_path: Path):
    target, answers = _node_cli(
        tmp_path,
        {
            "name": "@acme/widget-api",
            "author": "Ann Lee <ann@example.test>",
            "bin": {"acme-cli": "cli.js"},
        },
        origin=True,
        answers_extra='npm_name = "@new/new-widget"\ncli_name = "new-cli"\n',
    )
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0
    # The press rewrites press-source.toml to the destination afterwards, so
    # the receipt's [press.from] table is the record of what discovery wrote.
    receipt = tomllib.loads(
        (target / "press" / "press-receipt.toml").read_text(encoding="utf-8")
    )
    assert receipt["press"]["from"] == {
        "package_name": "widget_api",
        "repo_name": "acme-widget",
        "app_name": "acme_cli",
        "author": "Ann Lee",
        "email": "ann@example.test",
        "owner": "example-org",
        "npm_name": "@acme/widget-api",
        "cli_name": "acme-cli",
    }
    written = load_source_config(target, None)
    assert written is not None
    assert (written.npm_name, written.cli_name) == ("@new/new-widget", "new-cli")


def test_origin_wins_over_manifest_repository(tmp_path: Path, capsys):
    target, answers = _node_cli(
        tmp_path,
        {
            "name": "widget-api",
            "author": "Ann Lee <ann@example.test>",
            "bin": {"acme": "cli.js"},
            "repository": "https://github.com/other-org/other-repo",
        },
        origin=True,
    )
    main(["--target", str(target), "--config", str(answers)])
    out = capsys.readouterr().out
    assert 'owner = "example-org"' in out and 'repo_name = "acme-widget"' in out


def test_manifest_repository_is_fallback_without_origin(tmp_path: Path, capsys):
    target, answers = _node_cli(
        tmp_path,
        {
            "name": "widget-api",
            "author": "Ann Lee <ann@example.test>",
            "bin": {"acme": "cli.js"},
            "repository": "https://github.com/other-org/other-repo",
        },
    )
    main(["--target", str(target), "--config", str(answers)])
    out = capsys.readouterr().out
    assert 'owner = "other-org"' in out and 'repo_name = "other-repo"' in out


def test_invalid_proposed_names_exit_2_cleanly(tmp_path: Path, capsys):
    target, answers = _node_cli(
        tmp_path,
        {
            "name": "9widget",
            "author": "Ann Lee <ann@example.test>",
            "bin": {"Acme.CLI": "cli.js"},
        },
        origin=True,
    )
    code = main(["--target", str(target), "--config", str(answers)])
    assert code == 2
    assert "invalid" in capsys.readouterr().err


def test_deeply_nested_manifest_is_undiscoverable(tmp_path: Path):
    (tmp_path / "package.json").write_text("[" * 200000, encoding="utf-8")
    assert read_node_manifest(tmp_path) is None


_PARSE_AUTHOR = """
import sys
from pathlib import Path
from template_press.rebrand.node_manifest import read_node_manifest
manifest = read_node_manifest(Path(sys.argv[1]))
assert manifest is not None
print(manifest.author, manifest.email)
"""


@pytest.mark.parametrize(
    "author",
    [" " * 300 + "<", " " * 5000 + "<", "a " * 3000 + "<", "<" * 5000, "(" * 5000],
    ids=["spaces-300", "spaces-5000", "words-3000", "angle-5000", "paren-5000"],
)
def test_hostile_author_string_parses_in_bounded_time(tmp_path: Path, author: str):
    _node(tmp_path, author=author)
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PARSE_AUTHOR, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ann Lee", ("Ann Lee", None)),
        ("Ann Lee <ann@example.test>", ("Ann Lee", "ann@example.test")),
        (
            "Ann Lee <ann@example.test> (https://example.test)",
            ("Ann Lee", "ann@example.test"),
        ),
        ("Ann Lee (https://example.test)", ("Ann Lee", None)),
        ("  Ann   <ann@example.test>  ", ("Ann", "ann@example.test")),
        ("<ann@example.test>", (None, "ann@example.test")),
        ("Ann <>", ("Ann", None)),
        ("Ann <ann@example.test", (None, None)),
        ("Ann (https://example.test) <ann@example.test>", (None, None)),
        ("Ann <a@example.test> <b@example.test>", (None, None)),
        ("x" * 1025, (None, None)),
    ],
    ids=[
        "name",
        "name-email",
        "name-email-url",
        "name-url",
        "padded",
        "email-only",
        "empty-email",
        "unclosed-email",
        "url-before-email",
        "two-emails",
        "over-cap",
    ],
)
def test_author_string_forms(tmp_path: Path, raw: str, expected: tuple):
    m = read_node_manifest(_node(tmp_path, author=raw))
    assert m is not None
    assert (m.author, m.email) == expected


def test_manifest_with_bom_is_read(tmp_path: Path):
    (tmp_path / "package.json").write_bytes(b"\xef\xbb\xbf" + b'{"name": "pkg"}')
    m = read_node_manifest(tmp_path)
    assert m is not None
    assert m.name == "pkg"


def test_manifest_directory_is_undiscoverable(tmp_path: Path):
    (tmp_path / "package.json").mkdir()
    assert read_node_manifest(tmp_path) is None


@requires_symlink
def test_target_reached_through_a_symlinked_parent_is_read(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "package.json").write_text('{"name": "pkg"}', encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    m = read_node_manifest(link)
    assert m is not None
    assert m.name == "pkg"


def test_manifest_reads_dependency_keys_from_all_sections(tmp_path: Path):
    m = read_node_manifest(
        _node(
            tmp_path,
            dependencies={"a": "1"},
            devDependencies={"b": "1"},
            peerDependencies={"c": "1", "a": "2"},
            optionalDependencies={"d": "1"},
            bundleDependencies=["ignored"],
        )
    )
    assert m is not None
    assert m.dependency_names == ("a", "b", "c", "d")


@pytest.mark.parametrize("value", [["a"], "a", 1, None])
def test_non_object_dependency_section_is_ignored(tmp_path: Path, value: object):
    m = read_node_manifest(_node(tmp_path, dependencies=value))
    assert m is not None
    assert m.dependency_names == ()
