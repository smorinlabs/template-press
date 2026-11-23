"""Rewrite, path, leak, and synthesis behavior of npm_name and cli_name."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import apply, build_plan, replacement_pairs
from template_press.rebrand.identity import (
    Identity,
    field_renames_paths,
    replace_token,
)
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.substitutions import (
    SubstitutionTable,
    compile_substitution_table,
)
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verifier import scan
from template_press.rebrand.verify_cli import verify_command

from .conftest import requires_symlink

SOURCE = Identity(
    package_name="acme_core",
    repo_name="acme-core",
    app_name="acmeapp",
    author="Acme Author",
    email="author@example.test",
    owner="acme",
    npm_name="@acme/widget-api",
    cli_name="acme-cli",
)
DEST = Identity(
    package_name="other_core",
    repo_name="other-repo",
    app_name="otherapp",
    author="Other Author",
    email="other@example.test",
    owner="other-owner",
    npm_name="@new-org/new-api",
    cli_name="new-cli",
)
UNSCOPED_SOURCE = replace(SOURCE, npm_name="zeta-tool")
UNSCOPED_DEST = replace(DEST, npm_name="new-tool")
VERIFY_FIELDS = ("app_name", "package_name", "repo_name", "owner")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _toml_identity(identity: Identity, table: str) -> str:
    rows = identity.as_dict_prompted().items()
    return f"[{table}]\n" + "".join(f'{k} = "{v}"\n' for k, v in rows)


def _make_target(
    tmp_path: Path,
    source: Identity = SOURCE,
    files: dict[str, str] | None = None,
) -> Path:
    target = tmp_path / source.repo_name
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        _toml_identity(source, "identity"), encoding="utf-8"
    )
    (target / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{source.repo_name}"\n'
        'version = "0.1.0"\n'
        f'authors = [{{name = "{source.author}", email = "{source.email}"}}]\n'
        "[project.scripts]\n"
        f'{source.app_name} = "{source.package_name}.cli:main"\n',
        encoding="utf-8",
    )
    manifest: dict[str, object] = {"name": source.npm_name, "version": "0.1.0"}
    if source.cli_name is not None:
        manifest["bin"] = {source.cli_name: f"./bin/{source.cli_name}.js"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    package = target / "src" / source.package_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
    for rel, text in (files or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(
        target,
        "remote",
        "add",
        "origin",
        f"https://github.com/{source.owner}/{source.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def _press(target: Path, source: Identity, dest: Identity) -> SubstitutionTable:
    plan = build_plan(target, source, dest, DEFAULT_RULES)
    apply(target, source, dest, DEFAULT_RULES, table=plan.table)
    return plan.table


def _table(target: Path, source: Identity, dest: Identity) -> SubstitutionTable:
    snapshot = capture_surface_snapshot(target)
    return compile_substitution_table(
        source, dest, DEFAULT_RULES, snapshot, target=target
    )


def _row(table: SubstitutionTable, field: str):
    return next(
        row for row in table.rows if any(item.name == field for item in row.provenance)
    )


def test_scoped_rewrite_keeps_subpath():
    text = replace_token('"@acme/widget/sub"', "npm_name", "@acme/widget", "@new/x")
    assert text == '"@new/x/sub"'


def test_sibling_not_rewritten_by_npm_row():
    text = replace_token("@acme/widget-extra", "npm_name", "@acme/widget", "@new/x")
    assert text == "@acme/widget-extra"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("package_name", "acme_core", True),
        ("repo_name", "acme-core", True),
        ("app_name", "acme", True),
        ("app_name_upper", "ACME", True),
        ("cli_name", "acme-cli", True),
        ("npm_name", "acme-tool", True),
        ("npm_name", "@acme/tool", False),
        ("owner", "acme", False),
        ("author", "Acme", False),
        ("email", "a@example.test", False),
        ("display_name_spaced", "Acme", False),
    ],
)
def test_field_renames_paths(field, value, expected):
    assert field_renames_paths(field, value) is expected


def test_npm_row_runs_before_owner_row(tmp_path):
    target = _make_target(tmp_path)
    _press(target, SOURCE, DEST)
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pressed["name"] == "@new-org/new-api"


def test_equal_npm_and_repo_keep_npm_boundary(tmp_path):
    source = replace(
        SOURCE, owner="zetalabs", repo_name="acme-widget", npm_name="acme-widget"
    )
    dest = replace(DEST, repo_name="new-widget", npm_name="new-widget")
    target = _make_target(
        tmp_path,
        source,
        {"notes.md": "acme-widget and acme-widget-extra\n"},
    )
    table = _press(target, source, dest)
    pressed = (target / "notes.md").read_text(encoding="utf-8")
    assert pressed == "new-widget and acme-widget-extra\n"
    assert _row(table, "repo_name").matcher.identity_field == "npm_name"


def test_sort_key_leaves_rows_unchanged_without_npm(tmp_path):
    source = replace(SOURCE, npm_name=None, cli_name=None)
    dest = replace(DEST, npm_name=None, cli_name=None)
    target = _make_target(tmp_path, source)
    rows = _table(target, source, dest).rows
    lengths = [len(row.from_value) for row in rows]
    assert lengths == sorted(lengths, reverse=True)
    fields = [row.provenance[0].name for row in rows]
    expected = sorted(
        (k for k, v in source.as_dict().items() if v != dest.as_dict().get(k)),
        key=lambda k: -len(source.as_dict()[k]),
    )
    assert fields == expected


def test_compat_pairs_put_equal_npm_first():
    source = replace(SOURCE, repo_name="acme-widget", npm_name="acme-widget")
    dest = replace(DEST, repo_name="new-widget", npm_name="new-widget")
    fields = [field for field, cur, _ in replacement_pairs(source, dest)]
    assert "npm_name" in fields
    assert "repo_name" not in fields


def test_cli_name_renames_bin_file(tmp_path):
    target = _make_target(tmp_path, files={"bin/acme-cli.js": "#!/usr/bin/env node\n"})
    _press(target, SOURCE, DEST)
    assert (target / "bin/new-cli.js").exists()
    assert not (target / "bin/acme-cli.js").exists()


def test_unscoped_npm_name_renames_file(tmp_path):
    target = _make_target(
        tmp_path, UNSCOPED_SOURCE, {"lib/zeta-tool.js": "module.exports = 1;\n"}
    )
    _press(target, UNSCOPED_SOURCE, UNSCOPED_DEST)
    assert (target / "lib/new-tool.js").exists()
    assert not (target / "lib/zeta-tool.js").exists()


@requires_symlink
def test_symlink_follows_cli_rename(tmp_path):
    target = _make_target(tmp_path, files={"bin/acme-cli.js": "#!/usr/bin/env node\n"})
    os.symlink("bin/acme-cli.js", target / "entry")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "link")
    _press(target, SOURCE, DEST)
    assert os.readlink(target / "entry") == "bin/new-cli.js"


def test_cli_name_equal_to_owner_still_renames_file(tmp_path):
    source = replace(SOURCE, owner="acme-cli")
    dest = replace(DEST, owner="new-cli")
    target = _make_target(tmp_path, source, {"bin/acme-cli.js": "run\n"})
    _press(target, source, dest)
    assert (target / "bin/new-cli.js").exists()
    assert not (target / "bin/acme-cli.js").exists()


def test_scoped_npm_name_has_no_path_surface(tmp_path):
    target = _make_target(tmp_path)
    row = _row(_table(target, SOURCE, DEST), "npm_name")
    assert "path" not in row.rewrite_surfaces
    doctor = next(hunt for hunt in row.hunts if hunt.consumer == "doctor")
    assert "path" not in doctor.surfaces


def test_unscoped_to_scoped_is_content_only_and_keeps_path_hunt(tmp_path):
    dest = replace(UNSCOPED_DEST, npm_name="@new-org/new-tool")
    target = _make_target(tmp_path, UNSCOPED_SOURCE)
    row = _row(_table(target, UNSCOPED_SOURCE, dest), "npm_name")
    assert "path" not in row.rewrite_surfaces
    doctor = next(hunt for hunt in row.hunts if hunt.consumer == "doctor")
    assert "path" in doctor.surfaces


def test_unscoped_to_scoped_with_named_file_writes_no_receipt(tmp_path):
    dest = replace(UNSCOPED_DEST, npm_name="@new-org/new-tool")
    target = _make_target(
        tmp_path, UNSCOPED_SOURCE, {"lib/zeta-tool.js": "module.exports = 1;\n"}
    )
    answers = tmp_path / "answers.toml"
    answers.write_text(_toml_identity(dest, "answers"), encoding="utf-8")
    assert main(["--target", str(target), "--config", str(answers)]) == 1
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize(
    ("source", "dest", "leftover", "field"),
    [
        (SOURCE, DEST, "bin/acme-cli.js", "cli_name"),
        (UNSCOPED_SOURCE, UNSCOPED_DEST, "lib/zeta-tool.js", "npm_name"),
    ],
)
def test_path_leak_is_found_by_doctor_and_verifier(
    tmp_path, source, dest, leftover, field
):
    target = _make_target(tmp_path, source)
    table = _press(target, source, dest)
    planted = target / leftover
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("clean content\n", encoding="utf-8")

    for leaks in (
        find_leaks(target, source, DEFAULT_RULES, dest, table=table),
        find_leaks(target, source, DEFAULT_RULES, dest),
    ):
        assert any(
            leak.path == leftover and leak.field == field and leak.where == "path"
            for leak in leaks
        )
    findings = scan(
        target,
        source,
        dest,
        fields=(*VERIFY_FIELDS, field),
        substring_fields=frozenset(),
        rules=DEFAULT_RULES,
    )
    assert any(
        item.path == leftover and item.field == field and item.where == "filename"
        for item in findings
    )


def test_synthesis_preserves_scoped_shape():
    dest = synthesize_dest(SOURCE)
    assert re.fullmatch(r"@[a-z0-9-]+/[a-z0-9-]+", dest.npm_name)
    assert dest.cli_name is not None
    assert "/" not in dest.cli_name


def test_synthesis_preserves_unscoped_shape():
    dest = synthesize_dest(UNSCOPED_SOURCE)
    assert dest.npm_name is not None
    assert "/" not in dest.npm_name


def test_synthesis_preserves_npm_repo_equality():
    source = replace(SOURCE, repo_name="acme-widget", npm_name="acme-widget")
    dest = synthesize_dest(source)
    assert dest.npm_name == dest.repo_name


def test_synthesis_preserves_cli_app_equality():
    source = replace(SOURCE, cli_name="acmeapp")
    dest = synthesize_dest(source)
    assert dest.cli_name == dest.app_name


def test_synthesis_preserves_npm_cli_equality():
    source = replace(SOURCE, npm_name="zeta-tool", cli_name="zeta-tool")
    dest = synthesize_dest(source)
    assert dest.npm_name == dest.cli_name


def test_synthesis_preserves_equality_with_display_form():
    source = replace(SOURCE, npm_name="widget", display_name="widget")
    dest = synthesize_dest(source)
    dest.validate()
    assert dest.npm_name == dest.display_name


def test_synthesis_keeps_distinct_new_fields_distinct():
    dest = synthesize_dest(SOURCE)
    others = set(replace(dest, npm_name=None, cli_name=None).as_dict().values())
    assert dest.npm_name not in others
    assert dest.cli_name not in others
    assert dest.npm_name != dest.cli_name


def test_synthesis_unchanged_without_new_fields():
    base = replace(SOURCE, npm_name=None, cli_name=None)
    dest = synthesize_dest(base)
    assert dest.npm_name is None
    assert dest.cli_name is None


def test_verify_scans_declared_new_fields(tmp_path, capsys):
    source = replace(SOURCE, npm_name="@zeta/quux-lib")
    target = _make_target(
        tmp_path,
        source,
        {"docs/note.md": "see @zeta/quux-lib-extra for details\n"},
    )
    code = verify_command(["--target", str(target), "--json"])
    report = capsys.readouterr().out
    assert code == 1
    assert "npm_name" in report
    assert "quux-lib-extra" in report


def test_verify_is_clean_when_new_fields_are_fully_rewritten(tmp_path):
    target = _make_target(
        tmp_path,
        files={
            "bin/acme-cli.js": "#!/usr/bin/env node\n",
            "docs/note.md": "install @acme/widget-api/sub and run acme-cli\n",
        },
    )
    assert verify_command(["--target", str(target)]) == 0


def test_verify_flags_sibling_cli_name(tmp_path, capsys):
    source = replace(SOURCE, owner="zetalabs")
    target = _make_target(
        tmp_path, source, {"docs/note.md": "run acme-cli-extra to start\n"}
    )
    code = verify_command(["--target", str(target), "--json"])
    report = capsys.readouterr().out
    assert code == 1
    assert "cli_name" in report
