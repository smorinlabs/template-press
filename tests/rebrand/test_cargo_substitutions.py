"""Cargo name rows: boundaries, order, ownership, paths, and keep_names."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import apply, build_plan, replacement_pairs
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    distinct_hyphen_form,
    field_renames_paths,
)
from template_press.rebrand.inventory import SurfaceSnapshot
from template_press.rebrand.keep_names import (
    check_keep_surfaces,
    validate_keep_names,
)
from template_press.rebrand.regen import changed_identity_pairs
from template_press.rebrand.rules import DEFAULT_RULES, Rules
from template_press.rebrand.substitutions import (
    RenderedSubstitution,
    SubstitutionTable,
    check_target_keep_names,
    compile_substitution_table,
    rewrite_with_row,
)

from .conftest import init_git_repo

BASE = {
    "package_name": "acme_core",
    "repo_name": "acme-repo",
    "app_name": "acme",
    "author": "Demo Author",
    "email": "demo@example.test",
    "owner": "demolabs",
}
TO = {
    "package_name": "zeta_core",
    "repo_name": "zeta-repo",
    "app_name": "zeta",
    "author": "Zeta Author",
    "email": "zeta@example.test",
    "owner": "zetalabs",
}
SOURCE = Identity(**BASE, cargo_names=(("core", "acme-core"),))
DEST = Identity(**TO, cargo_names=(("core", "zeta-core"),))


def _compile(
    source: Identity = SOURCE,
    dest: Identity = DEST,
    rules: Rules = DEFAULT_RULES,
) -> SubstitutionTable:
    return compile_substitution_table(
        source, dest, rules, SurfaceSnapshot(entries=(), visibility_inputs=())
    )


def _row(table: SubstitutionTable, row_id: str) -> RenderedSubstitution:
    return next(row for row in table.rows if row.row_id == row_id)


def _rewrite(table: SubstitutionTable, text: str) -> str:
    for row in table.rows:
        if "content" in row.rewrite_surfaces:
            text = rewrite_with_row(row, text)
    return text


def _git(target: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.test", *args],  # noqa: S607
        cwd=target,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    target = tmp_path / "target"
    target.mkdir(parents=True)
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    init_git_repo(target, commit_message="init")
    return target


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("acme-core/serde", "zeta-core/serde"),
        ("dep:acme-core", "dep:zeta-core"),
        ("acme_core::hi()", "zeta_core::hi()"),
        ("acme-core-extra", "acme-core-extra"),
        (
            'core = { package = "acme-core", path = "../acme-core" }',
            'core = { package = "zeta-core", path = "../zeta-core" }',
        ),
    ],
)
def test_cargo_row_boundaries(text: str, want: str) -> None:
    assert _rewrite(_compile(), text) == want


def test_longer_cargo_row_precedes_shorter_identity_row() -> None:
    ids = [row.row_id for row in _compile().rows]
    assert ids.index("identity:cargo_ident_core") < ids.index("identity:app_name")
    assert ids.index("identity:cargo_exact_core") < ids.index("identity:app_name")


def test_equal_length_cargo_row_owns_merged_matcher() -> None:
    source = replace(SOURCE, repo_name="acme-core")
    dest = replace(DEST, repo_name="zeta-core")
    row = _row(_compile(source, dest), "identity:cargo_exact_core")
    assert row.matcher.identity_field == "cargo_exact_core"
    assert {item.name for item in row.provenance} == {
        "cargo_exact_core",
        "repo_name",
    }
    assert all(r.row_id != "identity:repo_name" for r in _compile(source, dest).rows)


def test_app_name_cannot_rewrite_front_of_mapped_ident() -> None:
    dest = replace(
        DEST, package_name="zeta_gadget", cargo_names=(("core", "zeta-gadget"),)
    )
    # With app_name first, this would become zeta_core::hi.
    assert _rewrite(_compile(SOURCE, dest), "acme_core::hi") == "zeta_gadget::hi"


def test_package_name_row_merges_with_primary_ident_row() -> None:
    table = _compile()
    row = _row(table, "identity:cargo_ident_core")
    assert {item.name for item in row.provenance} == {
        "cargo_ident_core",
        "package_name",
    }
    assert all(r.row_id != "identity:package_name" for r in table.rows)
    # An app_name unrelated to the crate isolates the Cargo row's own boundary.
    isolated = _compile(replace(SOURCE, app_name="tool"), DEST)
    assert _rewrite(isolated, "acme_core_extra") == "acme_core_extra"


def test_app_prefixed_underscore_sibling_is_refused_until_kept(tmp_path: Path) -> None:
    # app_name treats `_` as a right separator, so this sibling would be rewritten.
    target = _repo(tmp_path, {"src/lib.rs": "use acme_core_extra::x;\n"})
    found = check_target_keep_names(
        target, SOURCE, DEST, DEFAULT_RULES, frozenset(), ("rust",)
    ).undeclared
    assert [item.token for item in found] == ["acme_core_extra"]
    rules = replace(DEFAULT_RULES, keep_names=("acme_core_extra",))
    assert (
        check_target_keep_names(
            target, SOURCE, DEST, rules, frozenset(), ("rust",)
        ).undeclared
        == ()
    )
    plan = build_plan(target, SOURCE, DEST, rules)
    apply(target, SOURCE, DEST, rules, table=plan.table)
    text = (target / "src/lib.rs").read_text(encoding="utf-8")
    assert text == "use acme_core_extra::x;\n"


def test_substring_row_survives_cargo_ownership_at_table_level_only(
    tmp_path: Path,
) -> None:
    rules = replace(DEFAULT_RULES, substring_rewrite_fields=frozenset({"package_name"}))
    assert _rewrite(_compile(rules=rules), "xacme_corey") == "xzeta_corey"
    # The table keeps the glued match, but preflight refuses a multi-part token.
    multi = _repo(tmp_path / "multi", {"src/lib.rs": "xacme_corey\n"})
    found = check_target_keep_names(
        multi, SOURCE, DEST, rules, frozenset(), ("rust",)
    ).undeclared
    assert [item.token for item in found] == ["xacme_corey"]


def test_single_part_glued_token_passes_preflight_and_rewrites(
    tmp_path: Path,
) -> None:
    rules = replace(DEFAULT_RULES, substring_rewrite_fields=frozenset({"package_name"}))
    source = replace(
        SOURCE,
        package_name="acmecore",
        app_name="tool",
        cargo_names=(("core", "acmecore"),),
    )
    dest = replace(
        DEST,
        package_name="zetacore",
        app_name="gear",
        cargo_names=(("core", "zetacore"),),
    )
    assert _rewrite(_compile(source, dest, rules), "xacmecorey") == "xzetacorey"
    single = _repo(tmp_path / "single", {"src/lib.rs": "xacmecorey\n"})
    check = check_target_keep_names(single, source, dest, rules, frozenset(), ("rust",))
    assert check.undeclared == ()


def test_cargo_rows_rename_crate_directory(tmp_path: Path) -> None:
    target = _repo(
        tmp_path,
        {
            "crates/acme-core/Cargo.toml": '[package]\nname = "acme-core"\n',
            "crates/acme-core/src/acme_core.rs": "pub fn hi() {}\n",
        },
    )
    plan = build_plan(target, SOURCE, DEST, DEFAULT_RULES)
    apply(target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)
    assert (target / "crates/zeta-core/src/zeta_core.rs").is_file()
    assert not (target / "crates/acme-core").exists()
    manifest = (target / "crates/zeta-core/Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "zeta-core"' in manifest
    assert find_leaks(target, SOURCE, DEFAULT_RULES, dest=DEST, table=plan.table) == []


def test_engine_pairs_match_table_rows_for_cargo_identity() -> None:
    pairs = replacement_pairs(SOURCE, DEST)
    rows = [row for row in _compile().rows if row.rewrite_surfaces]
    assert [(tag, cur, repl) for tag, cur, repl in pairs] == [
        (row.row_id.removeprefix("identity:"), row.from_value, row.to_value)
        for row in rows
    ]


def test_destination_extending_source_name_is_refused_before_write(
    tmp_path: Path,
) -> None:
    source = replace(SOURCE, app_name="demo")
    dest = replace(
        DEST,
        app_name="widget",
        package_name="acme_core_next",
        cargo_names=(("core", "acme-core-next"),),
    )
    # package_name's doctor hunt would match acme_core_next after the write.
    with pytest.raises(ValidationError, match="ordered content dependency"):
        replacement_pairs(source, dest)
    target = _repo(tmp_path, {"src/lib.rs": "use acme_core::x;\n"})
    with pytest.raises(ValidationError, match="stale-source emission"):
        build_plan(target, source, dest, DEFAULT_RULES)
    text = (target / "src/lib.rs").read_text(encoding="utf-8")
    assert text == "use acme_core::x;\n"


def test_identity_without_table_compiles_identical_rows() -> None:
    plain_source = replace(SOURCE, cargo_names=())
    plain_dest = replace(DEST, cargo_names=())
    table = _compile(plain_source, plain_dest)
    assert not any("cargo" in row.row_id for row in table.rows)
    assert [row.row_id for row in table.rows] == [
        "identity:email",
        "identity:author",
        "identity:package_name",
        "identity:repo_name",
        "identity:package_name_hyphen",
        "identity:owner",
        "identity:app_name",
        "identity:app_name_upper",
    ]
    assert distinct_hyphen_form(plain_source, plain_dest) == "acme-core"
    assert changed_identity_pairs(plain_source, plain_dest) == [
        (field, value)
        for field, value in plain_source.as_dict().items()
        if plain_dest.as_dict()[field] != value
    ]


def test_cargo_npm_and_cli_rows_sort_longest_first() -> None:
    source = replace(SOURCE, npm_name="acme-core", cli_name="acme-tool-long")
    dest = replace(DEST, npm_name="zeta-core", cli_name="zeta-tool-long")
    ids = [row.row_id for row in _compile(source, dest).rows]
    assert ids.index("identity:cli_name") < ids.index("identity:cargo_exact_core")
    row = _row(_compile(source, dest), "identity:cargo_exact_core")
    assert {item.name for item in row.provenance} >= {"npm_name", "cargo_exact_core"}
    lengths = [
        len(row.from_value)
        for row in _compile(source, dest).rows
        if row.provenance[0].kind == "identity"
    ]
    assert lengths == sorted(lengths, reverse=True)


def test_keep_names_protects_cargo_sibling(tmp_path: Path) -> None:
    target = _repo(tmp_path, {"Cargo.toml": 'extra = "acme-core-extra"\n'})
    found = check_target_keep_names(
        target, SOURCE, DEST, DEFAULT_RULES, frozenset(), ("rust",)
    ).undeclared
    assert [item.token for item in found] == ["acme-core-extra"]
    kept = replace(DEFAULT_RULES, keep_names=("acme-core-extra",))
    check = check_target_keep_names(target, SOURCE, DEST, kept, frozenset(), ("rust",))
    assert check.undeclared == ()
    assert check.stale == ()


def test_keep_names_refuses_normalized_cargo_name() -> None:
    with pytest.raises(ValidationError, match="identity value"):
        validate_keep_names(
            ["Acme_Widget"],
            replace(SOURCE, cargo_names=(("w", "acme-widget"),)),
            DEST,
        )


def test_keep_names_refuses_entry_holding_complete_cargo_name() -> None:
    with pytest.raises(ValidationError, match="as a complete name"):
        validate_keep_names(["vendor/acme-core"], SOURCE, DEST)


def test_undeclared_cargo_sibling_is_found_in_ident_spelling() -> None:
    surfaces = [("src/lib.rs", "content", "use acme_core_extra::x;")]
    check = check_keep_surfaces(surfaces, SOURCE, ())
    assert [item.token for item in check.undeclared] == ["acme_core_extra"]


def test_node_dependency_evidence_ignores_cargo_values() -> None:
    check = check_keep_surfaces((), SOURCE, (), dependency_names=("acme-core.x",))
    assert check.undeclared == ()


def test_declared_cargo_name_suppresses_hunt_only_hyphen_row() -> None:
    assert distinct_hyphen_form(SOURCE, DEST) is None
    assert all(row.row_id != "identity:package_name_hyphen" for row in _compile().rows)


def test_underscore_destination_keeps_cargo_rewrite(tmp_path: Path) -> None:
    dest = replace(DEST, cargo_names=(("core", "zeta_core"),))
    table = _compile(SOURCE, dest)
    assert _rewrite(table, "acme-core acme_core") == "zeta_core zeta_core"
    target = _repo(tmp_path, {"crates/acme-core/lib.rs": "acme_core\n"})
    plan = build_plan(target, SOURCE, dest, DEFAULT_RULES)
    apply(target, SOURCE, dest, DEFAULT_RULES, table=plan.table)
    assert (target / "crates/zeta_core/lib.rs").read_text() == "zeta_core\n"


def test_unchanged_role_ident_is_protected_from_app_row() -> None:
    source = replace(
        SOURCE, cargo_names=(("core", "acme-core"), ("widget", "acme-widget"))
    )
    dest = replace(DEST, cargo_names=(("core", "zeta-core"), ("widget", "acme-widget")))
    with pytest.raises(ValidationError, match="destination stability conflict"):
        _compile(source, dest)


def test_scan_consumers_see_cargo_values(tmp_path: Path) -> None:
    assert ("cargo_exact_core", "acme-core") in changed_identity_pairs(SOURCE, DEST)
    target = _repo(tmp_path, {"notes.md": "left acme-core here\n"})
    leaks = find_leaks(target, SOURCE, DEFAULT_RULES, dest=DEST)
    assert any(leak.field == "cargo_exact_core" for leak in leaks)


def test_cargo_fields_rename_paths() -> None:
    assert field_renames_paths("cargo_exact_core", "acme-core")
    assert field_renames_paths("cargo_ident_core", "acme_core")
