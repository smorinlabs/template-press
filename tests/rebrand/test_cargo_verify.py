"""Cargo names in the independent verifier and the synthetic destination."""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.engine import build_plan
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    cargo_ident,
    cargo_identity_problem,
)
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.synthesize import (
    _assert_equality_signature,
    _source_variants,
    synthesize_dest,
)
from template_press.rebrand.verifier import scan
from template_press.rebrand.verify_cli import verify_command

SOURCE = Identity(
    package_name="acme_core",
    repo_name="acme-repo",
    app_name="acme_core",
    author="Ada Example",
    email="ada@example.test",
    owner="acme-org",
    cargo_names=(("core", "acme-core"), ("widget", "acme-widget")),
)
DEST = replace(
    SOURCE,
    package_name="zeta_core",
    repo_name="zeta-repo",
    app_name="zeta_core",
    author="Zed Example",
    email="zed@example.test",
    owner="zeta-org",
    cargo_names=(("core", "zeta-core"), ("widget", "zeta-gadget")),
)
# Captured from synthesize_dest before the Cargo table reached synthesis.
SIX_FIELD = Identity(
    package_name="demo_widget",
    repo_name="demo-widget",
    app_name="demo",
    author="Example Author",
    email="dev@example.test",
    owner="example-org",
)

GOLDEN = {
    "six": {
        "app_name": "f057575b38563d06f2d977a0",
        "author": "f057575b3837f615dec66090",
        "email": "f057575b38fe14d6@5e6bc72faf.63a",
        "owner": "f057575b38a2cf213e1676f1",
        "package_name": "f057575b38f6ca8d98b19f67",
        "repo_name": "f057575b38f0e82de8575a1e",
    },
    "display": {
        "app_name": "f057575b38563d06f2d977a0",
        "author": "f057575b3837f615dec66090",
        "display_name": "Axnrxh Kidypb",
        "email": "f057575b38fe14d6@5e6bc72faf.63a",
        "owner": "f057575b38a2cf213e1676f1",
        "package_name": "f057575b38f6ca8d98b19f67",
        "repo_name": "f057575b38f0e82de8575a1e",
    },
    "exact": {
        "app_name": "f057575b38563d06f2d977a0",
        "author": "f057575b3837f615dec66090",
        "cli_name": "f057575b38d547729efa0991",
        "email": "f057575b38fe14d6@5e6bc72faf.63a",
        "npm_name": "@f057575b38317b34f56ec9bf/f057575b38c22daac4ee3e8b",
        "owner": "f057575b38a2cf213e1676f1",
        "package_name": "f057575b38f6ca8d98b19f67",
        "repo_name": "f057575b38f0e82de8575a1e",
    },
}
GOLDEN_SOURCES = {
    "six": SIX_FIELD,
    "display": replace(SIX_FIELD, display_name="Demo Widget"),
    "exact": replace(
        SIX_FIELD, npm_name="@example-org/demo-widget", cli_name="demo-cli"
    ),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    target = (tmp_path / "target").resolve()
    target.mkdir()
    for rel, body in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "fixture")
    return target


def _scan(target: Path, fields: tuple[str, ...] = ("repo_name",)) -> list:
    return scan(
        target,
        SOURCE,
        DEST,
        fields=fields,
        substring_fields=frozenset(),
        rules=DEFAULT_RULES,
    )


@pytest.mark.parametrize("spelling", ["acme-widget", "acme_widget"])
def test_verifier_flags_hyphen_and_underscore_leaks(tmp_path, spelling) -> None:
    target = _repo(tmp_path, {"notes.txt": f"left {spelling} here\n"})
    found = [f for f in _scan(target) if f.field == "cargo_exact_widget"]
    assert [(f.path, f.value, f.line) for f in found] == [
        ("notes.txt", "acme-widget", 1)
    ]


def test_verifier_has_one_finding_per_occurrence_for_a_role(tmp_path) -> None:
    target = _repo(tmp_path, {"notes.txt": "acme-widget and acme_widget\n"})
    found = [f for f in _scan(target) if f.field.startswith("cargo_")]
    assert [(f.field, f.col) for f in found] == [
        ("cargo_exact_widget", 0),
        ("cargo_exact_widget", 16),
    ]


def test_verifier_hunts_cargo_names_outside_the_configured_fields(tmp_path) -> None:
    target = _repo(tmp_path, {"notes.txt": "acme-core\n"})
    assert [f.field for f in _scan(target, fields=("owner",))] == ["cargo_exact_core"]


def test_verifier_does_not_double_report_a_name_a_field_already_hunts(
    tmp_path,
) -> None:
    target = _repo(tmp_path, {"notes.txt": "acme_core\n"})
    found = _scan(target, fields=("package_name",))
    assert [f.field for f in found] == ["package_name"]


def test_verifier_skips_an_unchanged_role(tmp_path) -> None:
    dest = replace(DEST, cargo_names=(("core", "zeta-core"), ("widget", "acme-widget")))
    target = _repo(tmp_path, {"notes.txt": "acme-widget\n"})
    found = scan(
        target,
        SOURCE,
        dest,
        fields=("repo_name",),
        substring_fields=frozenset(),
        rules=DEFAULT_RULES,
    )
    assert found == []


def test_verifier_import_closure_is_unchanged() -> None:
    path = Path(__file__).parents[2] / "src/template_press/rebrand/verifier.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    for forbidden in ("substitutions", "engine", "doctor"):
        assert f"template_press.rebrand.{forbidden}" not in imported


def test_synthesized_primary_matches_package_destination() -> None:
    dest = synthesize_dest(SOURCE)
    names = dict(dest.cargo_names)
    assert cargo_ident(names["core"]) == dest.package_name
    assert cargo_identity_problem(SOURCE, dest) is None


def test_synthesized_names_preserve_hyphen_shape_and_contain_no_source_token() -> None:
    source = replace(
        SOURCE,
        cargo_names=(
            ("core", "acme-core"),
            ("tool", "acme_tool"),
            ("widget", "acme-widget"),
            ("zed", "zed"),
        ),
    )
    dest = synthesize_dest(source)
    names = dict(dest.cargo_names)
    variants = {v.lower() for v in _source_variants([n for _, n in source.cargo_names])}
    for role, old in source.cargo_names:
        assert ("-" in names[role]) == ("-" in old)
        assert role not in names[role].split("-")
        for form in (names[role], cargo_ident(names[role])):
            assert not any(v in form.lower() for v in variants)


def test_synthesis_is_deterministic() -> None:
    assert synthesize_dest(SOURCE) == synthesize_dest(SOURCE)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_six_field_synthesis_is_byte_identical(name) -> None:
    dest = synthesize_dest(GOLDEN_SOURCES[name])
    assert dest == Identity(**GOLDEN[name])


def test_substring_field_does_not_cover_the_other_cargo_spelling(tmp_path) -> None:
    target = _repo(tmp_path, {"notes.txt": "acme-core\n"})
    found = scan(
        target,
        SOURCE,
        DEST,
        fields=("package_name",),
        substring_fields=frozenset({"package_name"}),
        rules=DEFAULT_RULES,
    )
    assert [f.field for f in found] == ["cargo_exact_core"]


@pytest.mark.parametrize("owner", ["x", "1", "x1"])
def test_synthesis_avoids_a_short_source_value_in_the_role_suffix(
    tmp_path, owner
) -> None:
    source = replace(SOURCE, owner=owner)
    dest = synthesize_dest(source)
    assert cargo_identity_problem(source, dest) is None
    target = _repo(tmp_path, {"notes.txt": "placeholder\n"})
    build_plan(target, source, dest, DEFAULT_RULES)


@pytest.mark.parametrize(
    ("label", "changes"),
    [
        (
            "crate equals repo",
            {
                "package_name": "acme_widget",
                "app_name": "acme_widget",
                "repo_name": "acme-widget",
                "cargo_names": (("widget", "acme-widget"),),
            },
        ),
        (
            "second crate equals repo",
            {"repo_name": "acme-widget"},
        ),
        (
            "bin equals app",
            {
                "app_name": "acme_cli",
                "cargo_names": (("cli", "acme-cli"), ("core", "acme-core")),
            },
        ),
        (
            "single word crate equals owner",
            {
                "owner": "acme",
                "cargo_names": (("brand", "acme"), ("core", "acme-core")),
            },
        ),
        (
            "cli name equals crate",
            {"cli_name": "acme-widget"},
        ),
        (
            "display camel form equals a crate",
            {
                "display_name": "Gadget",
                "cargo_names": (("core", "acme-core"), ("gadget", "gadget")),
            },
        ),
        (
            "multi-word camel form equals a crate",
            {
                "display_name": "Acme Tool",
                "cargo_names": (("core", "acme-core"), ("tool", "acmeTool")),
            },
        ),
        (
            "display equals the primary crate",
            {"display_name": "acme-core"},
        ),
        (
            "display equals a crate's underscore form",
            {
                "display_name": "acme_tool",
                "cargo_names": (("core", "acme-core"), ("tool", "acme-tool")),
            },
        ),
        (
            "uppercase owner ties a crate through app_name",
            {
                "package_name": "acme_core",
                "app_name": "acme",
                "owner": "ACME",
                "cargo_names": (("brand", "acme"), ("core", "acme-core")),
            },
        ),
        (
            "crate equals app_name_upper",
            {
                "app_name": "acme",
                "cargo_names": (("core", "acme-core"), ("loud", "ACME")),
            },
        ),
        (
            "repeated separators",
            {
                "package_name": "acme__core",
                "app_name": "acme__core",
                "cargo_names": (("core", "acme--core"),),
            },
        ),
    ],
)
def test_synthesized_table_compiles_when_names_share_values(
    tmp_path, label, changes
) -> None:
    source = replace(SOURCE, **changes)
    dest = synthesize_dest(source)
    assert cargo_identity_problem(source, dest) is None, label
    target = _repo(tmp_path, {"notes.txt": "placeholder\n"})
    build_plan(target, source, dest, DEFAULT_RULES)


def test_equality_signature_covers_cargo_values() -> None:
    source = replace(SOURCE, repo_name="acme-widget")
    dest = replace(synthesize_dest(source), repo_name="unrelated-repo")
    with pytest.raises(ValidationError, match="equality signature"):
        _assert_equality_signature(source, dest)


def test_invalid_source_table_reports_the_table_problem(tmp_path) -> None:
    source = replace(SOURCE, cargo_names=(("other", "acme-other"),))
    dest = synthesize_dest(source)
    problem = cargo_identity_problem(source, dest)
    assert problem is not None
    assert "not the underscore form" in problem


@pytest.mark.parametrize(
    "destination", ["acme-widget-next", "my-acme-widget", "acme_widget"]
)
def test_non_primary_destination_extending_source_is_refused_before_write(
    tmp_path, destination
) -> None:
    dest = replace(DEST, cargo_names=(("core", "zeta-core"), ("widget", destination)))
    target = _repo(tmp_path, {"notes.txt": "acme-widget\n"})
    with pytest.raises(ValidationError, match="stale-source emission"):
        build_plan(target, SOURCE, dest, DEFAULT_RULES)
    assert (target / "notes.txt").read_text(encoding="utf-8") == "acme-widget\n"


def test_non_cargo_destination_extending_a_crate_name_still_compiles(tmp_path) -> None:
    # A regenerated lockfile never holds the author, so only Cargo outputs
    # are checked against the paranoid hunts.
    dest = replace(DEST, author="acme-widget-fan")
    target = _repo(tmp_path, {"notes.txt": "placeholder\n"})
    build_plan(target, SOURCE, dest, DEFAULT_RULES)


def _cargo_target(tmp_path: Path, extra: dict[str, str | bytes]) -> Path:
    source_config = (
        "[identity]\n"
        'package_name = "acme_core"\n'
        'repo_name = "acme-repo"\n'
        'app_name = "acme_core"\n'
        'author = "Ada Example"\n'
        'email = "ada@example.test"\n'
        'owner = "acme-org"\n\n'
        "[identity.cargo_names]\n"
        'core = "acme-core"\n'
        'widget = "acme-widget"\n'
    )
    author = 'authors = ["Ada Example <ada@example.test>"]\n'
    files: dict[str, str | bytes] = {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\n'
            'members = ["crates/acme-core", "crates/acme-widget"]\n'
        ),
        "crates/acme-core/Cargo.toml": (
            f'[package]\nname = "acme-core"\nversion = "0.1.0"\n{author}'
        ),
        "crates/acme-core/src/lib.rs": "pub fn hi() {}\n",
        "crates/acme-widget/Cargo.toml": (
            f'[package]\nname = "acme-widget"\nversion = "0.1.0"\n{author}'
            '\n[dependencies]\nacme-core = { path = "../acme-core" }\n'
        ),
        "crates/acme-widget/src/main.rs": "fn main() { acme_core::hi(); }\n",
        "README.md": "# acme-repo by acme-org, Ada Example, ada@example.test\n",
        "press/press-source.toml": source_config,
        **extra,
    }
    target = _repo(tmp_path, files)
    _git(target, "remote", "add", "origin", "https://github.com/acme-org/acme-repo.git")
    return target


def test_verify_passes_a_healthy_mapped_workspace(tmp_path, capsys) -> None:
    target = _cargo_target(tmp_path, {})
    assert verify_command(["--target", str(target)]) == 0, capsys.readouterr().err


@pytest.mark.parametrize("spelling", [b"acme-widget", b"acme_widget"])
def test_verify_fails_on_a_non_primary_leak_in_binary_content(
    tmp_path, capsys, spelling
) -> None:
    target = _cargo_target(tmp_path, {"data.bin": b"\xff\xfe " + spelling + b"\n"})
    assert verify_command(["--target", str(target), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert {f["field"] for f in report["surviving"]} == {"cargo_exact_widget"}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (b"_ZN11acme_widget4main17h0E", "cargo_exact_widget"),
        (b"xacme_widgety", "cargo_exact_widget"),
        (b"xacme-corey", "cargo_exact_core"),
    ],
)
def test_verify_finds_glued_cargo_spellings_in_binary_content(
    tmp_path, capsys, payload, field
) -> None:
    target = _cargo_target(tmp_path, {"data.bin": b"\xff\xfe" + payload + b"\n"})
    assert verify_command(["--target", str(target), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [f["field"] for f in report["surviving"]] == [field]


def test_binary_scan_keeps_one_finding_per_offset(tmp_path, capsys) -> None:
    target = _cargo_target(tmp_path, {"data.bin": b"\xff\xfe xacme_corey\n"})
    assert verify_command(["--target", str(target), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    cargo = [f for f in report["surviving"] if f["field"].startswith("cargo_")]
    assert cargo == []
    assert len({f["col"] for f in report["surviving"]}) == 1


@pytest.mark.parametrize(
    "destination",
    ["acme_repo_gadget", "acmerepo", "acme_org_gadget", "acmeorg", "ada-example"],
)
def test_cargo_destination_holding_another_source_field_is_refused(
    tmp_path, capsys, destination
) -> None:
    rules = (
        '[rules]\nextra_exclude_files = ["Cargo.lock"]\n\n[[regenerate]]\n'
        'file = "Cargo.lock"\n'
        'command = ["cargo", "update", "--workspace", "--offline"]\n'
        'verify_exempt = true\nreason = "regenerated lockfile"\n'
    )
    target = _cargo_target(
        tmp_path,
        {
            "press/press-rules.toml": rules,
            "Cargo.lock": 'version = 4\n\n[[package]]\nname = "acme-core"\n',
        },
    )
    answers = tmp_path / "answers.toml"
    answers.write_text(
        "[answers]\n"
        'package_name = "zeta_core"\n'
        'repo_name = "zeta-repo"\n'
        'app_name = "zeta_core"\n'
        'author = "Zed Example"\n'
        'email = "zed@example.test"\n'
        'owner = "zeta-org"\n\n'
        "[answers.cargo_names]\n"
        'core = "zeta-core"\n'
        f'widget = "{destination}"\n',
        encoding="utf-8",
    )
    code = main(["--target", str(target), "--config", str(answers)])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "stale-source emission" in err
    status = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
