"""P06-TS07: rendered substitution-table compiler contract."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from template_press.rebrand.identity import Identity
from template_press.rebrand.inventory import SurfaceEntry, SurfaceSnapshot
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, Rules
from template_press.rebrand.substitutions import (
    HuntPolicy,
    RenamePlan,
    RenderedSubstitution,
    SubstitutionTable,
    compile_substitution_table,
)

from .conftest import requires_symlink

SOURCE = Identity(
    package_name="demo_widget",
    repo_name="demo-widget",
    app_name="demo",
    author="Demo Author",
    email="demo@example.com",
    owner="demo",
)
DESTINATION = Identity(
    package_name="potato_launcher",
    repo_name="potato-launcher",
    app_name="potato",
    author="Potato Farmer",
    email="potato@example.com",
    owner="potato",
)


def _rules(
    *replace_rules: ReplaceRule,
    display_forms: tuple[str, ...] = DEFAULT_RULES.display_forms,
    substring_fields: frozenset[str] = frozenset(),
) -> Rules:
    return Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        regenerate=DEFAULT_RULES.regenerate,
        reset=DEFAULT_RULES.reset,
        verify_ignore=DEFAULT_RULES.verify_ignore,
        replace=replace_rules,
        substring_rewrite_fields=substring_fields,
        display_forms=display_forms,
    )


def _compile(
    source: Identity = SOURCE,
    destination: Identity = DESTINATION,
    rules: Rules = DEFAULT_RULES,
    snapshot: SurfaceSnapshot | None = None,
    target: Path | None = None,
) -> SubstitutionTable:
    return compile_substitution_table(
        source,
        destination,
        rules,
        snapshot or SurfaceSnapshot(entries=(), visibility_inputs=()),
        target=target,
    )


def _row(table: SubstitutionTable, name: str) -> RenderedSubstitution:
    return next(
        row for row in table.rows if any(item.name == name for item in row.provenance)
    )


def _hunt(row: RenderedSubstitution, consumer: str) -> HuntPolicy:
    return next(item for item in row.hunts if item.consumer == consumer)


def test_changed_path_identity_compiles_field_aware_rewrite_and_hunts() -> None:
    table = _compile()
    row = _row(table, "package_name")

    assert row.matcher.algorithm == "conservative"
    assert row.matcher.identity_field == "package_name"
    assert row.matcher.substring is False
    assert row.from_value == "demo_widget"
    assert row.to_value == "potato_launcher"
    assert row.rewrite_surfaces == frozenset({"content", "path"})
    assert row.scope.files == ()
    assert _hunt(row, "doctor") == HuntPolicy(
        consumer="doctor",
        matcher=row.matcher,
        surfaces=frozenset({"content", "path", "symlink"}),
        scope_coordinates="current_or_source",
    )
    assert _hunt(row, "reset_stub").matcher.algorithm == "paranoid"
    assert _hunt(row, "reset_stub").surfaces == frozenset({"content"})
    assert _hunt(row, "reset_path").surfaces == frozenset({"path"})
    assert _hunt(row, "regeneration").surfaces == frozenset({"content", "path"})


def test_changed_non_path_identity_does_not_rewrite_or_hunt_path_names() -> None:
    table = _compile()
    row = _row(table, "author")

    assert row.rewrite_surfaces == frozenset({"content"})
    assert _hunt(row, "doctor").surfaces == frozenset({"content", "symlink"})
    assert _hunt(row, "reset_path").surfaces == frozenset({"path"})


def test_declared_rule_compiles_exact_matchers_scope_and_ordered_provenance() -> None:
    rule = ReplaceRule(
        pattern="x{app_name}owned",
        reason="boundary-invisible fixture",
        files=("docs/**",),
        paths=True,
        content=False,
    )
    table = _compile(rules=_rules(rule))
    row = _row(table, "replace[1]")

    assert table.rows[0] is row
    assert row.row_id == "replace:1"
    assert row.provenance[0].kind == "replace_rule"
    assert row.provenance[0].declaration_index == 1
    assert row.provenance[0].pattern == "x{app_name}owned"
    assert row.provenance[0].reason == "boundary-invisible fixture"
    assert row.matcher.algorithm == "literal"
    assert row.from_value == "xdemoowned"
    assert row.to_value == "xpotatoowned"
    assert row.rewrite_surfaces == frozenset({"path"})
    assert row.scope.files == ("docs/**",)
    assert _hunt(row, "doctor").surfaces == frozenset({"path", "symlink"})
    assert _hunt(row, "reset_path").matcher.algorithm == "literal"
    assert _hunt(row, "regeneration").surfaces == frozenset({"path"})


def test_substring_identity_hunts_preserve_the_effective_flag() -> None:
    table = _compile(rules=_rules(substring_fields=frozenset({"app_name"})))
    row = _row(table, "app_name")

    assert row.matcher.substring is True
    paranoid_policies = tuple(
        policy
        for policy in row.hunts
        if policy.matcher.algorithm == "paranoid"
        and policy.matcher.identity_field == "app_name"
    )
    assert paranoid_policies
    assert all(policy.matcher.substring is True for policy in paranoid_policies)


def test_disabled_display_forms_have_hunts_but_no_rewrite_or_doctor_policy() -> None:
    source = replace(SOURCE, display_name="Demo Suite")
    destination = replace(DESTINATION, display_name="Potato Tool")
    table = _compile(
        source,
        destination,
        _rules(display_forms=("camel",)),
    )

    camel = _row(table, "display_name_camel")
    spaced = _row(table, "display_name_spaced")
    pascal = _row(table, "display_name_pascal")
    assert camel.rewrite_surfaces == frozenset({"content"})
    assert _hunt(camel, "doctor").surfaces == frozenset({"content", "path", "symlink"})
    for disabled in (spaced, pascal):
        assert disabled.rewrite_surfaces == frozenset()
        assert all(policy.consumer != "doctor" for policy in disabled.hunts)
        assert {policy.consumer for policy in disabled.hunts} == {
            "reset_stub",
            "reset_path",
            "regeneration",
        }


def test_equal_identity_values_share_one_executable_row_and_keep_all_hunts() -> None:
    table = _compile()
    shared = [
        row
        for row in table.rows
        if (row.from_value, row.to_value) == ("demo", "potato")
    ]

    assert len(shared) == 1
    row = shared[0]
    assert [item.name for item in row.provenance] == ["app_name", "owner"]
    assert row.row_id == "identity:app_name"
    assert row.matcher.identity_field == "app_name"
    assert row.rewrite_surfaces == frozenset({"content", "path"})
    doctor_matchers = [
        policy.matcher.identity_field
        for policy in row.hunts
        if policy.consumer == "doctor"
    ]
    assert doctor_matchers == ["app_name", "owner"]


def test_collapsed_display_forms_use_first_enabled_destination_and_keep_provenance() -> (
    None
):
    source = replace(SOURCE, display_name="NumPy")
    destination = replace(DESTINATION, display_name="Acme Widget")
    table = _compile(source, destination)

    row = next(item for item in table.rows if item.from_value == "NumPy")
    assert row.to_value == "Acme Widget"
    assert [item.name for item in row.provenance] == [
        "display_name_spaced",
        "display_name_pascal",
    ]
    assert row.row_id == "identity:display_name_spaced"
    assert row.matcher.identity_field == "display_name_spaced"
    assert row.rewrite_surfaces == frozenset({"content"})
    assert [
        policy.matcher.identity_field
        for policy in row.hunts
        if policy.consumer == "doctor"
    ] == ["display_name_spaced", "display_name_pascal"]


def test_collapsed_disabled_display_forms_keep_hunts_without_rewrite() -> None:
    source = replace(SOURCE, display_name="NumPy")
    destination = replace(DESTINATION, display_name="Acme Widget")
    table = _compile(
        source,
        destination,
        _rules(display_forms=("camel",)),
    )

    row = next(item for item in table.rows if item.from_value == "NumPy")
    assert row.to_value == "Acme Widget"
    assert [item.name for item in row.provenance] == [
        "display_name_spaced",
        "display_name_pascal",
    ]
    assert row.rewrite_surfaces == frozenset()
    assert all(policy.consumer != "doctor" for policy in row.hunts)


def test_later_display_matcher_does_not_expand_shared_identity_rewrite() -> None:
    source = replace(SOURCE, display_name="demo")
    destination = replace(DESTINATION, display_name="potato")
    table = _compile(source, destination)

    row = next(
        item
        for item in table.rows
        if (item.from_value, item.to_value) == ("demo", "potato")
    )
    assert [item.name for item in row.provenance] == [
        "app_name",
        "owner",
        "display_name_spaced",
        "display_name_camel",
    ]
    assert row.matcher.identity_field == "app_name"
    assert row.rewrite_surfaces == frozenset({"content", "path"})


def test_unchanged_identity_values_do_not_produce_rows() -> None:
    table = _compile(SOURCE, SOURCE, DEFAULT_RULES)

    assert table.rows == ()
    assert table.rename_plan.steps == ()


def test_nested_path_tokens_compile_ordered_fixed_point_steps() -> None:
    source_entry = "src/demo_widget/demo_widget.py"
    snapshot = SurfaceSnapshot(
        entries=(
            SurfaceEntry(
                rel=Path(source_entry),
                tracked=True,
                index_kind="file",
                worktree_kind="file",
            ),
        ),
        visibility_inputs=(),
    )
    table = _compile(
        destination=replace(SOURCE, package_name="potato_launcher"),
        snapshot=snapshot,
    )

    first, second = table.rename_plan.steps
    assert (first.pass_number, first.old_prefix, first.new_prefix) == (
        1,
        "src/demo_widget",
        "src/potato_launcher",
    )
    assert first.row_ids == ("identity:package_name",)
    assert first.source_entries == (source_entry,)
    assert first.predecessor_step_ids == ()
    assert (second.pass_number, second.old_prefix, second.new_prefix) == (
        2,
        "src/potato_launcher/demo_widget.py",
        "src/potato_launcher/potato_launcher.py",
    )
    assert second.row_ids == ("identity:package_name",)
    assert second.source_entries == (source_entry,)
    assert second.predecessor_step_ids == (first.step_id,)
    assert table.rename_plan.translate(source_entry) == (
        "src/potato_launcher/potato_launcher.py"
    )
    assert table.rename_plan.as_mapping() == {
        "src/demo_widget": "src/potato_launcher",
        "src/potato_launcher/demo_widget.py": (
            "src/potato_launcher/potato_launcher.py"
        ),
    }


def test_rename_plan_can_translate_only_the_executed_lifecycle_view() -> None:
    snapshot = SurfaceSnapshot(
        entries=(
            SurfaceEntry(
                rel=Path("src/demo_widget/demo_widget.py"),
                tracked=True,
                index_kind="file",
                worktree_kind="file",
            ),
        ),
        visibility_inputs=(),
    )
    plan = _compile(
        destination=replace(SOURCE, package_name="potato_launcher"),
        snapshot=snapshot,
    ).rename_plan

    assert (
        plan.translate(
            "src/demo_widget/demo_widget.py",
            executed_step_ids=frozenset({plan.steps[0].step_id}),
        )
        == "src/potato_launcher/demo_widget.py"
    )
    assert (
        plan.translate(
            "src/demo_widget/demo_widget.py",
            executed_step_ids=frozenset(),
        )
        == "src/demo_widget/demo_widget.py"
    )


@requires_symlink
def test_dangling_symlink_target_compiles_virtual_translation(tmp_path: Path) -> None:
    link = tmp_path / "guide"
    link.symlink_to("missing/demo_widget")
    snapshot = SurfaceSnapshot(
        entries=(
            SurfaceEntry(
                rel=Path("guide"),
                tracked=True,
                index_kind="symlink",
                worktree_kind="symlink",
            ),
        ),
        visibility_inputs=(),
    )

    plan: RenamePlan = _compile(
        destination=replace(SOURCE, package_name="potato_launcher"),
        snapshot=snapshot,
        target=tmp_path,
    ).rename_plan

    assert plan.virtual_translations == (
        (
            "guide",
            "missing/demo_widget",
            "missing/potato_launcher",
        ),
    )
