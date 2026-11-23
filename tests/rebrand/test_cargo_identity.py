"""Cargo name table on Identity: parsing, rendering, problems, pairs, receipts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.config import (
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    cargo_ident,
    cargo_identity_problem,
    cargo_name_pairs,
    is_cargo_field,
)
from template_press.rebrand.receipt import (
    read_receipt,
    receipt_binding_problem,
    write_receipt,
)

BASE = {
    "package_name": "acme_core",
    "repo_name": "acme-repo",
    "app_name": "acme",
    "author": "Demo Author",
    "email": "demo@example.test",
    "owner": "demolabs",
}


def ident(cargo: dict[str, str] | None = None, **overrides: str) -> Identity:
    values = {**BASE, **overrides}
    return Identity(**values, cargo_names=tuple((cargo or {}).items()))


def src(core: str = "acme-core", widget: str | None = None) -> Identity:
    table = {"core": core}
    if widget is not None:
        table["widget"] = widget
    return ident(table)


def dst(core: str = "zeta-core", widget: str | None = None, **kw: str) -> Identity:
    table = {"core": core}
    if widget is not None:
        table["widget"] = widget
    return ident(table, package_name=kw.pop("package_name", "zeta_core"), **kw)


def test_absent_table_keeps_six_field_mapping() -> None:
    identity = ident()
    assert identity.cargo_names == ()
    assert identity.control_mapping() == identity.as_dict_prompted()
    assert "cargo_names" not in identity.as_dict()


def test_optional_node_fields_stay_in_control_mapping() -> None:
    identity = ident(npm_name="@acme/core", cli_name="acme-cli")
    assert identity.control_mapping() == identity.as_dict_prompted()
    assert identity.control_mapping()["npm_name"] == "@acme/core"


def test_table_is_sorted_and_in_control_mapping_only() -> None:
    identity = ident({"widget": "acme-widget", "core": "acme-core"})
    assert identity.cargo_names == (
        ("core", "acme-core"),
        ("widget", "acme-widget"),
    )
    assert "cargo_names" not in identity.as_dict()
    assert "cargo_names" not in identity.as_dict_prompted()
    assert identity.control_mapping()["cargo_names"] == {
        "core": "acme-core",
        "widget": "acme-widget",
    }


def test_loads_and_renders_table_round_trip(tmp_path: Path) -> None:
    identity = ident({"widget": "acme-widget", "core": "acme-core"})
    text = render_source_config(identity)
    assert "[identity.cargo_names]" in text
    assert text.index("[identity.cargo_names]") > text.index("owner =")
    target = tmp_path / "t"
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(text, encoding="utf-8")
    assert load_source_config(target, None) == identity


def test_render_without_table_is_unchanged() -> None:
    assert "cargo_names" not in render_source_config(ident())


def test_loads_answers_table(tmp_path: Path) -> None:
    path = tmp_path / "press-answers.toml"
    path.write_text(
        "[answers]\n"
        + "".join(f'{k} = "{v}"\n' for k, v in BASE.items())
        + '[answers.cargo_names]\ncore = "zeta-core"\n',
        encoding="utf-8",
    )
    assert load_answers(path).cargo_names == (("core", "zeta-core"),)


def _answers(tmp_path: Path, table: str) -> Path:
    path = tmp_path / "press-answers.toml"
    path.write_text(
        "[answers]\n" + "".join(f'{k} = "{v}"\n' for k, v in BASE.items()) + table,
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "table",
    ['Core = "acme-core"', 'core = "1x"', '"1x" = "acme-core"', 'core = "-x"'],
)
def test_rejects_bad_role_and_bad_name(tmp_path: Path, table: str) -> None:
    path = _answers(tmp_path, f"[answers.cargo_names]\n{table}\n")
    with pytest.raises(ValidationError):
        load_answers(path)


def test_rejects_non_string_table_value(tmp_path: Path) -> None:
    path = _answers(tmp_path, "[answers.cargo_names]\ncore = 3\n")
    with pytest.raises(ValidationError):
        load_answers(path)


def test_rejects_non_table_cargo_names(tmp_path: Path) -> None:
    path = _answers(tmp_path, "")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "[answers]\n", '[answers]\ncargo_names = "x"\n'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_answers(path)


def test_problem_none_without_tables() -> None:
    assert cargo_identity_problem(ident(), ident()) is None


def test_problem_none_for_consistent_tables() -> None:
    assert cargo_identity_problem(src(), dst()) is None


def test_problem_when_table_half_specified() -> None:
    problem = cargo_identity_problem(src(), ident(package_name="zeta_core"))
    assert problem is not None and "both" in problem
    assert cargo_identity_problem(ident(), dst()) is not None


def test_problem_when_role_sets_differ() -> None:
    problem = cargo_identity_problem(src(), dst(widget="zeta-widget"))
    assert problem is not None and "role" in problem


def test_problem_when_ident_forms_collide() -> None:
    source = ident({"a": "a-b", "b": "a_b"}, package_name="a_b")
    dest = ident({"a": "x-y", "b": "p-q"}, package_name="p_q")
    problem = cargo_identity_problem(source, dest)
    assert problem is not None and "same underscore" in problem
    dest_side = ident({"a": "x-y", "b": "x_y"}, package_name="x_y")
    ok_source = ident({"a": "a-b", "b": "c-d"}, package_name="c_d")
    assert cargo_identity_problem(ok_source, dest_side) is not None


def test_problem_when_destination_chains_into_other_source() -> None:
    source = ident({"a": "one-x", "b": "two-x"}, package_name="two_x")
    dest = ident({"a": "two-x", "b": "three-x"}, package_name="three_x")
    problem = cargo_identity_problem(source, dest)
    assert problem is not None and "chain" in problem


def test_chain_detection_compares_both_spellings() -> None:
    source = ident({"a": "one-x", "b": "two-x"}, package_name="two_x")
    dest = ident({"a": "two_x", "b": "three-x"}, package_name="three_x")
    assert "chain" in (cargo_identity_problem(source, dest) or "")


def test_problem_when_package_name_is_not_a_map_value() -> None:
    source = ident({"core": "acme-core"}, package_name="other_name")
    dest = ident({"core": "zeta-core"}, package_name="zeta_core")
    problem = cargo_identity_problem(source, dest)
    assert problem is not None and "package_name" in problem


def test_problem_when_package_destination_differs_from_role_destination() -> None:
    problem = cargo_identity_problem(src(), dst(package_name="zeta_other"))
    assert problem is not None and "package_name" in problem


def test_pairs_drop_duplicate_spelling_for_single_word_name() -> None:
    assert [p[1] for p in cargo_name_pairs(src("core"), dst("base"))] == ["core"]


def test_pairs_cover_both_spellings_longest_first() -> None:
    pairs = cargo_name_pairs(src("acme-core", "acme"), dst("zeta-core", "zeta"))
    assert pairs == [
        ("cargo_exact_core", "acme-core", "zeta-core"),
        ("cargo_ident_core", "acme_core", "zeta_core"),
        ("cargo_exact_widget", "acme", "zeta"),
    ]


def test_pairs_drop_unchanged_roles() -> None:
    assert cargo_name_pairs(src("acme-core"), src("acme-core")) == []


def test_cargo_cargo_ident_and_field_helpers() -> None:
    assert cargo_ident("a-b-c") == "a_b_c"
    assert is_cargo_field("cargo_exact_core")
    assert is_cargo_field("cargo_ident_core")
    assert not is_cargo_field("package_name")


def test_receipt_binding_accepts_table_and_rejects_changed_table(
    tmp_path: Path,
) -> None:
    source, dest = src(), dst()
    write_receipt(tmp_path, source, dest, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert receipt_binding_problem(raw, dest) is None
    changed = replace(dest, cargo_names=(("core", "zeta-other"),))
    assert receipt_binding_problem(raw, changed) == (
        "[press.to] does not match press-source.toml"
    )
    assert receipt_binding_problem(raw, replace(dest, cargo_names=())) is not None


def test_receipt_without_table_stays_valid_for_six_field_identity(
    tmp_path: Path,
) -> None:
    source, dest = ident(), ident(package_name="zeta_core")
    write_receipt(tmp_path, source, dest, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert "cargo_names" not in raw
    assert receipt_binding_problem(raw, dest) is None
