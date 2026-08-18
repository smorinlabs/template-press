"""P06-TS04: contract tests for the pure pipeline-stability validator."""

from __future__ import annotations

import os
import subprocess

import pytest

from template_press.rebrand import cli as cli_module
from template_press.rebrand import engine
from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.engine import build_plan, rendered_replace_rules
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.pipeline import (
    MatcherSpec,
    PipelineCandidate,
    StabilitySink,
    validate_pipeline,
)
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, ResetRule, Rules

from .conftest import DEST, SOURCE, requires_symlink


def _candidate(
    row_id: str,
    source: str,
    destination: str,
    *,
    surfaces: frozenset[str] = frozenset({"content"}),
    matcher: MatcherSpec | None = None,
    files: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    ambiguity_family: str | None = None,
) -> PipelineCandidate:
    return PipelineCandidate(
        row_id=row_id,
        from_value=source,
        to_value=destination,
        rewrite_surfaces=surfaces,
        matcher=matcher or MatcherSpec("literal", None, False),
        files=files,
        provenance=provenance or (f"test:{row_id}",),
        ambiguity_family=ambiguity_family,
    )


def _identity(**overrides: str) -> Identity:
    values = {
        "email": "dev@example.com",
        "package_name": "demo_widget",
        "repo_name": "demo-widget",
        "author": "Demo Author",
        "owner": "demo",
        "app_name": "demo",
    }
    values.update(overrides)
    return Identity(**values)


def _rules(*replace: ReplaceRule) -> Rules:
    return Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        replace=replace,
        regenerate=DEFAULT_RULES.regenerate,
        reset=DEFAULT_RULES.reset,
        substring_rewrite_fields=DEFAULT_RULES.substring_rewrite_fields,
        display_forms=DEFAULT_RULES.display_forms,
        verify_ignore=DEFAULT_RULES.verify_ignore,
    )


def test_compatible_duplicates_coalesce_without_losing_provenance() -> None:
    first = _candidate(
        "first",
        "old",
        "new",
        files=("a.txt",),
        provenance=("identity:app",),
    )
    second = _candidate(
        "second",
        "old",
        "new",
        files=("a.txt",),
        provenance=("rule:owned",),
    )

    normalized = validate_pipeline((first, second))

    assert len(normalized) == 1
    assert normalized[0].files == ("a.txt",)
    assert normalized[0].provenance == ("identity:app", "rule:owned")


def test_equal_source_and_destination_is_omitted() -> None:
    assert validate_pipeline((_candidate("noop", "same", "same"),)) == ()


def test_compatible_rows_with_different_scopes_do_not_coalesce() -> None:
    first = _candidate("first", "old", "new", files=("a.txt",))
    second = _candidate("second", "old", "new", files=("b.txt",))

    assert validate_pipeline((first, second)) == (first, second)


def test_display_family_ambiguity_keeps_first_configured_destination() -> None:
    spaced = _candidate(
        "spaced", "NumPy", "Acme Widget", ambiguity_family="display_name"
    )
    pascal = _candidate(
        "pascal", "NumPy", "AcmeWidget", ambiguity_family="display_name"
    )

    assert validate_pipeline((spaced, pascal)) == (spaced,)


def test_hunt_only_row_does_not_create_rewrite_conflicts() -> None:
    rewrite = _candidate("rewrite", "old", "one")
    hunt = _candidate(
        "hunt", "old", "two", surfaces=frozenset(), provenance=("hunt:only",)
    )

    assert validate_pipeline((rewrite, hunt)) == (rewrite, hunt)


def test_destination_stability_sink_rejects_changed_token_in_unchanged_field() -> None:
    app = _candidate(
        "identity:app_name",
        "foo",
        "bar",
        matcher=MatcherSpec("conservative", "app_name", False),
        provenance=("identity:app_name",),
    )
    author = StabilitySink(
        "destination:author",
        "foo owner",
        provenance=("destination identity field:author",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((app,), stability_sinks=(author,))

    message = str(exc_info.value)
    assert "identity:app_name" in message
    assert "destination:author" in message


def test_same_source_different_destinations_reports_both_provenances() -> None:
    first = _candidate("first", "old", "one", provenance=("identity:app",))
    second = _candidate("second", "old", "two", provenance=("rule:owned",))

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "first" in message and "identity:app" in message
    assert "second" in message and "rule:owned" in message


def test_same_source_different_destinations_accepts_disjoint_exact_content_scopes() -> (
    None
):
    first = _candidate("first", "old", "one", files=("a.txt",))
    second = _candidate("second", "old", "two", files=("b.txt",))

    assert validate_pipeline((first, second)) == (first, second)


def test_same_exact_path_scope_cannot_choose_two_destinations() -> None:
    first = _candidate(
        "first",
        "old",
        "one",
        surfaces=frozenset({"path"}),
        files=("old/file.txt",),
    )
    second = _candidate(
        "second",
        "old",
        "two",
        surfaces=frozenset({"path"}),
        files=("old/file.txt",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline(
            (first, second),
            initial_paths=("old/file.txt",),
        )

    message = str(exc_info.value)
    assert "different destinations" in message
    assert "first" in message and "test:first" in message
    assert "second" in message and "test:second" in message


def test_known_empty_target_allows_disjoint_exact_path_scopes() -> None:
    first = _candidate(
        "first",
        "old",
        "one",
        surfaces=frozenset({"path"}),
        files=("left/old.txt",),
    )
    second = _candidate(
        "second",
        "old",
        "two",
        surfaces=frozenset({"path"}),
        files=("right/old.txt",),
    )

    with pytest.raises(ValidationError, match="different destinations"):
        validate_pipeline((first, second))
    assert validate_pipeline((first, second), initial_paths=()) == (first, second)


def test_wildcard_content_scopes_remain_conservatively_overlapping() -> None:
    first = _candidate("first", "old", "one", files=("src/*.txt",))
    second = _candidate("second", "old", "two", files=("tests/*.txt",))

    with pytest.raises(ValidationError, match="different destinations"):
        validate_pipeline((first, second))


def test_ordered_content_output_dependency_is_rejected() -> None:
    first = _candidate("first", "alpha", "bravo", provenance=("rule:first",))
    second = _candidate("second", "bravo", "charlie", provenance=("rule:second",))

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "ordered content dependency" in message
    assert "first" in message and "rule:first" in message
    assert "second" in message and "rule:second" in message


def test_ordered_symlink_output_dependency_is_rejected() -> None:
    first = _candidate(
        "first",
        "alpha",
        "bravo",
        surfaces=frozenset({"symlink"}),
        provenance=("rule:first",),
    )
    second = _candidate(
        "second",
        "bravo",
        "charlie",
        surfaces=frozenset({"symlink"}),
        provenance=("identity:author",),
    )

    with pytest.raises(ValidationError, match="ordered symlink dependency"):
        validate_pipeline((first, second))


def test_issue_44_nested_rendered_source_in_symlink_targets_is_rejected() -> None:
    # The symlink-surface twin of the content-surface case: an earlier row's
    # rendered FROM found inside a later row's rendered FROM, in link text.
    first = _candidate(
        "first",
        "demo",
        "spud",
        surfaces=frozenset({"symlink"}),
        provenance=("rule:first",),
    )
    second = _candidate(
        "second",
        "demo_widget",
        "potato_launcher",
        surfaces=frozenset({"symlink"}),
        matcher=MatcherSpec("conservative", "package_name", False),
        provenance=("identity:package_name",),
    )

    with pytest.raises(
        ValidationError, match="nested rendered source in symlink targets"
    ):
        validate_pipeline((first, second))


def test_issue_44_compatible_nested_symlink_rewrite_is_accepted() -> None:
    # The symlink twin of the compatible content case: the earlier row
    # already rewrites the link text into the later row's own destination,
    # so nothing is corrupted and the pipeline stays valid.
    first = _candidate(
        "first",
        "demo",
        "spud",
        surfaces=frozenset({"symlink"}),
        provenance=("rule:first",),
    )
    second = _candidate(
        "second",
        "demo_widget",
        "spud_widget",
        surfaces=frozenset({"symlink"}),
        matcher=MatcherSpec("conservative", "package_name", False),
        provenance=("identity:package_name",),
    )

    assert validate_pipeline((first, second)) == (first, second)


def test_content_output_cannot_emit_an_earlier_source() -> None:
    first = _candidate("first", "alpha", "bravo", provenance=("rule:first",))
    second = _candidate("second", "charlie", "alpha", provenance=("rule:second",))

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "stale-source emission" in message
    assert "first" in message and "rule:first" in message
    assert "second" in message and "rule:second" in message


def test_issue_44_nested_rendered_source_is_rejected() -> None:
    # A row whose rendered FROM is a plain substring of a LATER row's
    # rendered FROM, on overlapping scope: the earlier row's own pass
    # corrupts the exact text the later row needs intact, starving it
    # silently (exit 0, internally inconsistent output) before this guard.
    first = _candidate("first", "demo", "spud", provenance=("rule:first",))
    second = _candidate(
        "second",
        "demo_widget",
        "potato_launcher",
        matcher=MatcherSpec("conservative", "package_name", False),
        provenance=("identity:package_name",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "nested rendered source" in message
    assert "first" in message and "rule:first" in message
    assert "second" in message and "identity:package_name" in message


def test_issue_44_compatible_nested_rewrite_is_accepted() -> None:
    # Nesting alone is not corruption: the earlier row's own pass already
    # renders the later row's FROM into exactly the later row's TO
    # ("demo_widget" -> "spud_widget"), so the later row is left with
    # nothing to do and the pressed text is the one it wanted. Only an
    # INCOMPATIBLE result is #44's silent corruption.
    first = _candidate("first", "demo", "spud", provenance=("rule:first",))
    second = _candidate(
        "second",
        "demo_widget",
        "spud_widget",
        matcher=MatcherSpec("conservative", "package_name", False),
        provenance=("identity:package_name",),
    )

    assert validate_pipeline((first, second)) == (first, second)


def test_issue_44_reverse_order_is_safe() -> None:
    # The identity-vs-identity shape this guard must NOT reject: the longer
    # FROM ("demo_widget") is length-sorted ahead of the shorter one
    # ("demo") in real usage, so a longer-FROM row can never be "found
    # inside" a shorter-FROM row that runs after it.
    first = _candidate(
        "first",
        "demo_widget",
        "potato_launcher",
        matcher=MatcherSpec("conservative", "package_name", False),
        provenance=("identity:package_name",),
    )
    second = _candidate(
        "second",
        "demo",
        "spud",
        matcher=MatcherSpec("conservative", "app_name", False),
        provenance=("identity:app_name",),
    )

    assert validate_pipeline((first, second)) == (first, second)


def test_issue_44_disjoint_exact_content_scopes_exempt_nested_source() -> None:
    # Mirrors #45's exemption: two rules provably scoped to disjoint exact
    # files never actually run over the same text, so nesting between their
    # FROMs is not a real hazard.
    first = _candidate("first", "demo", "spud", files=("a.txt",))
    second = _candidate("second", "demo_widget", "potato_launcher", files=("b.txt",))

    assert validate_pipeline((first, second)) == (first, second)


def test_issue_44_intersecting_exact_content_scopes_keep_nested_source() -> None:
    first = _candidate("first", "demo", "spud", files=("a.txt", "shared.txt"))
    second = _candidate(
        "second", "demo_widget", "potato_launcher", files=("shared.txt", "b.txt")
    )

    with pytest.raises(ValidationError, match="nested rendered source"):
        validate_pipeline((first, second))


def test_disjoint_exact_content_scopes_exempt_output_dependency() -> None:
    first = _candidate("first", "alpha", "bravo", files=("a.txt",))
    second = _candidate("second", "bravo", "charlie", files=("b.txt",))

    assert validate_pipeline((first, second)) == (first, second)


def test_disjoint_exact_content_scopes_exempt_stale_source_emission() -> None:
    first = _candidate("first", "alpha", "bravo", files=("a.txt",))
    second = _candidate("second", "charlie", "alpha", files=("b.txt",))

    assert validate_pipeline((first, second)) == (first, second)


def test_intersecting_exact_content_scopes_keep_output_dependency() -> None:
    first = _candidate("first", "alpha", "bravo", files=("a.txt", "shared.txt"))
    second = _candidate("second", "bravo", "charlie", files=("shared.txt", "b.txt"))

    with pytest.raises(ValidationError, match="ordered content dependency"):
        validate_pipeline((first, second))


@pytest.mark.parametrize(
    ("matcher", "output", "conflicts"),
    (
        (MatcherSpec("conservative", "app_name", False), "compress", False),
        (MatcherSpec("conservative", "app_name", False), "press-tool", False),
        (MatcherSpec("conservative", "repo_name", False), "press-tool", True),
        (MatcherSpec("conservative", "app_name", True), "compress", True),
    ),
)
def test_dependency_uses_receiving_rows_exact_matcher(
    matcher: MatcherSpec, output: str, conflicts: bool
) -> None:
    producer = _candidate("producer", "alpha", output)
    receiver = _candidate("receiver", "press", "done", matcher=matcher)

    if conflicts:
        with pytest.raises(ValidationError, match="ordered content dependency"):
            validate_pipeline((producer, receiver))
    else:
        assert validate_pipeline((producer, receiver)) == (producer, receiver)


def test_stale_source_uses_earlier_rows_exact_matcher() -> None:
    earlier = _candidate(
        "earlier",
        "press",
        "done",
        matcher=MatcherSpec("conservative", "app_name", False),
    )
    later = _candidate("later", "charlie", "compress")

    assert validate_pipeline((earlier, later)) == (earlier, later)


def test_stale_source_positive_conservative_match() -> None:
    earlier = _candidate(
        "earlier",
        "press",
        "done",
        matcher=MatcherSpec("conservative", "repo_name", False),
    )
    later = _candidate("later", "charlie", "press-tool")

    with pytest.raises(ValidationError, match="stale-source emission"):
        validate_pipeline((earlier, later))


def test_path_dependency_uses_receiving_rows_exact_matcher() -> None:
    producer = _candidate("producer", "alpha", "compress", surfaces=frozenset({"path"}))
    receiver = _candidate(
        "receiver",
        "press",
        "done",
        surfaces=frozenset({"path"}),
        matcher=MatcherSpec("conservative", "app_name", False),
    )

    assert validate_pipeline((producer, receiver)) == (producer, receiver)


def test_path_dependency_positive_conservative_match() -> None:
    producer = _candidate(
        "producer", "alpha", "press-tool", surfaces=frozenset({"path"})
    )
    receiver = _candidate(
        "receiver",
        "press",
        "done",
        surfaces=frozenset({"path"}),
        matcher=MatcherSpec("conservative", "repo_name", False),
    )

    with pytest.raises(ValidationError, match="path dependency"):
        validate_pipeline((producer, receiver))


def test_path_dependency_cycle_reports_every_row_and_provenance() -> None:
    first = _candidate(
        "first",
        "alpha",
        "bravo",
        surfaces=frozenset({"path"}),
        provenance=("rule:first",),
    )
    second = _candidate(
        "second",
        "bravo",
        "alpha",
        surfaces=frozenset({"path"}),
        provenance=("rule:second",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "cycle" in message
    assert "first" in message and "rule:first" in message
    assert "second" in message and "rule:second" in message


def test_one_way_cross_row_path_dependency_is_rejected() -> None:
    first = _candidate("first", "alpha", "bravo", surfaces=frozenset({"path"}))
    second = _candidate("second", "bravo", "charlie", surfaces=frozenset({"path"}))

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "path dependency" in message
    assert "first" in message and "test:first" in message
    assert "second" in message and "test:second" in message


def test_three_row_path_cycle_reports_complete_cycle() -> None:
    candidates = (
        _candidate("one", "alpha", "bravo", surfaces=frozenset({"path"})),
        _candidate("two", "bravo", "charlie", surfaces=frozenset({"path"})),
        _candidate("three", "charlie", "alpha", surfaces=frozenset({"path"})),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline(candidates)

    message = str(exc_info.value)
    assert "cycle" in message
    assert all(row_id in message for row_id in ("one", "two", "three"))
    assert all(f"test:{row_id}" in message for row_id in ("one", "two", "three"))


def test_path_output_cannot_rematch_itself() -> None:
    candidate = _candidate(
        "growing",
        "alpha",
        "alpha-x",
        surfaces=frozenset({"path"}),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((candidate,))

    message = str(exc_info.value)
    assert "path dependency" in message
    assert "growing" in message and "test:growing" in message


@pytest.mark.parametrize(
    ("source", "destination"),
    (
        ("a/b", "safe"),
        (r"a\b", "safe"),
        ("safe", "a/b"),
        ("safe", r"a\b"),
        ("safe", ""),
        ("safe", "."),
        ("safe", ".."),
    ),
)
def test_path_component_structural_safety(source: str, destination: str) -> None:
    candidate = _candidate(
        "unsafe",
        source,
        destination,
        surfaces=frozenset({"path"}),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((candidate,))

    message = str(exc_info.value)
    assert "path component" in message
    assert "unsafe" in message and "test:unsafe" in message


def test_path_scope_reachability_rejects_rename_entering_later_scope() -> None:
    first = _candidate(
        "move-parent",
        "old",
        "new",
        surfaces=frozenset({"path"}),
        files=("old/file.txt",),
    )
    second = _candidate(
        "move-leaf",
        "file",
        "renamed",
        surfaces=frozenset({"path"}),
        files=("new/file.txt",),
    )

    with pytest.raises(ValidationError, match="path dependency"):
        validate_pipeline((first, second), initial_paths=("old/file.txt",))


def test_path_scope_reachability_error_names_rows_and_provenance() -> None:
    first = _candidate(
        "move-parent",
        "old",
        "new",
        surfaces=frozenset({"path"}),
        files=("old/file.txt",),
        provenance=("rule:parent",),
    )
    second = _candidate(
        "move-leaf",
        "file",
        "renamed",
        surfaces=frozenset({"path"}),
        files=("new/file.txt",),
        provenance=("rule:leaf",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second), initial_paths=("old/file.txt",))

    message = str(exc_info.value)
    assert "path dependency" in message
    assert "move-parent" in message and "rule:parent" in message
    assert "move-leaf" in message and "rule:leaf" in message


def test_sibling_move_into_opposing_scope_is_rejected_as_cycle() -> None:
    forward = _candidate(
        "forward",
        "xold",
        "xnew",
        surfaces=frozenset({"path"}),
        files=("xold/a.txt",),
        provenance=("rule:forward",),
    )
    backward = _candidate(
        "backward",
        "xnew",
        "xold",
        surfaces=frozenset({"path"}),
        files=("xnew/b.txt",),
        provenance=("rule:backward",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline(
            (forward, backward),
            initial_paths=("xold/a.txt", "xold/b.txt"),
        )

    message = str(exc_info.value)
    assert "path dependency" in message or "cycle" in message
    assert "forward" in message and "rule:forward" in message
    assert "backward" in message and "rule:backward" in message


@pytest.mark.parametrize("inert_scope", (("new/b.txt",), ("new/*.txt",)))
def test_sibling_move_into_inert_scope_remains_stable(
    inert_scope: tuple[str, ...],
) -> None:
    mover = _candidate(
        "mover",
        "old",
        "new",
        surfaces=frozenset({"path"}),
        files=("old/a.txt",),
    )
    inert = _candidate(
        "inert",
        "never",
        "changed",
        surfaces=frozenset({"path"}),
        files=inert_scope,
    )

    assert validate_pipeline(
        (mover, inert),
        initial_paths=("old/a.txt", "old/b.txt"),
    ) == (mover, inert)


def test_build_plan_rejects_sibling_move_into_opposing_scope(src_target) -> None:
    first = src_target / "xold" / "a.txt"
    second = src_target / "xold" / "b.txt"
    first.parent.mkdir()
    first.write_text("clean\n", encoding="utf-8")
    second.write_text("clean\n", encoding="utf-8")
    rules = _rules(
        ReplaceRule(
            pattern="x{owner}",
            reason="move sibling parent forward",
            files=("xold/a.txt",),
            paths=True,
            content=False,
        ),
        ReplaceRule(
            pattern="{author}",
            reason="move sibling parent backward",
            files=("xnew/b.txt",),
            paths=True,
            content=False,
        ),
    )
    source = _identity(owner="old", author="xnew")
    destination = _identity(owner="new", author="xold")

    with pytest.raises(ValidationError, match=r"path dependency|cycle"):
        build_plan(src_target, source, destination, rules)

    assert first.is_file()
    assert second.is_file()


def test_leaf_scopes_cannot_assign_one_ancestor_two_destinations() -> None:
    first = _candidate(
        "left",
        "shared",
        "one",
        surfaces=frozenset({"path"}),
        files=("shared/left.txt",),
        provenance=("rule:left",),
    )
    second = _candidate(
        "right",
        "shared",
        "two",
        surfaces=frozenset({"path"}),
        files=("shared/right.txt",),
        provenance=("rule:right",),
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline(
            (first, second),
            initial_paths=("shared/left.txt", "shared/right.txt"),
        )

    message = str(exc_info.value)
    assert "shared prefix" in message
    assert "left" in message and "rule:left" in message
    assert "right" in message and "rule:right" in message


def test_build_plan_rejects_distinct_prefixes_converging_on_one_destination(
    src_target,
) -> None:
    package_path = src_target / "oldpkg" / "package.txt"
    app_path = src_target / "oldapp" / "app.txt"
    package_path.parent.mkdir()
    app_path.parent.mkdir()
    package_path.write_text("package\n", encoding="utf-8")
    app_path.write_text("app\n", encoding="utf-8")
    source = _identity(package_name="oldpkg", app_name="oldapp")
    destination = _identity(package_name="new", app_name="new")

    with pytest.raises(ValidationError, match="converging path prefixes"):
        build_plan(src_target, source, destination, DEFAULT_RULES)

    assert package_path.is_file()
    assert app_path.is_file()


def test_path_move_cannot_overwrite_unchanged_target() -> None:
    mover = _candidate(
        "move",
        "a",
        "b",
        surfaces=frozenset({"path"}),
    )

    with pytest.raises(ValidationError, match="converging target paths"):
        validate_pipeline(
            (mover,),
            initial_paths=("a/file.txt", "b/file.txt"),
        )

    assert validate_pipeline(
        (mover,),
        initial_paths=("a/file.txt", "b/file.txt"),
        initial_symlink_paths=frozenset({"b/file.txt"}),
    ) == (mover,)


def test_disjoint_rewrite_surfaces_do_not_conflict() -> None:
    content = _candidate("content", "old", "one")
    path = _candidate("path", "old", "two", surfaces=frozenset({"path"}))

    assert validate_pipeline((content, path)) == (content, path)


def test_issue_45_disjoint_rendered_rule_scopes_are_accepted(src_target) -> None:
    rules = _rules(
        ReplaceRule(
            pattern="{app_name}",
            reason="first leaf",
            files=("a.txt",),
            paths=False,
        ),
        ReplaceRule(
            pattern="f{package_name}",
            reason="second leaf",
            files=("b.txt",),
            paths=False,
        ),
    )
    source = _identity(app_name="foo", package_name="oo")
    destination = _identity(app_name="bar", package_name="zz")

    build_plan(src_target, source, destination, rules)
    rendered = rendered_replace_rules(rules, source, destination)

    assert [(item[1], item[2]) for item in rendered] == [
        ("foo", "bar"),
        ("foo", "fzz"),
    ]


def test_build_plan_calls_the_shared_pipeline_validator(
    src_target, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[
        tuple[
            tuple[PipelineCandidate, ...],
            tuple[str, ...],
            frozenset[str],
            tuple[StabilitySink, ...],
        ]
    ] = []
    real_validator = engine.validate_pipeline

    def recording_validator(
        candidates,
        *,
        initial_paths=None,
        initial_symlink_paths=frozenset(),
        stability_sinks=(),
    ):
        assert isinstance(initial_paths, tuple)
        calls.append(
            (
                tuple(candidates),
                initial_paths,
                initial_symlink_paths,
                tuple(stability_sinks),
            )
        )
        return real_validator(
            candidates,
            initial_paths=initial_paths,
            initial_symlink_paths=initial_symlink_paths,
            stability_sinks=stability_sinks,
        )

    monkeypatch.setattr(engine, "validate_pipeline", recording_validator)
    rules = _rules(
        ReplaceRule(
            pattern="{owner}-owned",
            reason="literal matcher probe",
            files=["README.md"],
            paths=False,
        )
    )

    build_plan(
        src_target,
        _identity(owner="source"),
        _identity(owner="dest"),
        rules,
    )

    assert len(calls) == 1
    candidates, initial_paths, initial_symlink_paths, stability_sinks = calls[0]
    owner = next(
        item
        for item in candidates
        if item.from_value == "source" and item.to_value == "dest"
    )
    declared = next(
        item
        for item in candidates
        if item.from_value == "source-owned" and item.to_value == "dest-owned"
    )
    assert owner.matcher == MatcherSpec("conservative", "owner", False)
    assert declared.matcher == MatcherSpec("literal", None, False)
    assert declared.files == ("README.md",)
    assert "README.md" in initial_paths
    assert initial_symlink_paths == frozenset()
    assert any(sink.sink_id == "destination:author" for sink in stability_sinks)


def test_build_plan_rejects_scoped_path_reachability(src_target) -> None:
    nested = src_target / "old" / "file.txt"
    nested.parent.mkdir()
    nested.write_text("fixture\n", encoding="utf-8")
    rules = _rules(
        ReplaceRule(
            pattern="{owner}",
            reason="move parent",
            files=("old/file.txt",),
            paths=True,
            content=False,
        ),
        ReplaceRule(
            pattern="{author}",
            reason="move leaf",
            files=("new/file.txt",),
            paths=True,
            content=False,
        ),
    )
    source = _identity(owner="old", author="file")
    destination = _identity(owner="new", author="renamed")

    with pytest.raises(ValidationError, match="path dependency"):
        build_plan(src_target, source, destination, rules)


@requires_symlink
def test_build_plan_rejects_dangling_target_scoped_path_reachability(
    src_target,
) -> None:
    os.symlink("old/file.txt", src_target / "link")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    rules = _rules(
        ReplaceRule(
            pattern="{owner}",
            reason="move parent",
            files=("old/file.txt",),
            paths=True,
            content=False,
        ),
        ReplaceRule(
            pattern="{author}",
            reason="move leaf",
            files=("new/file.txt",),
            paths=True,
            content=False,
        ),
    )
    source = _identity(owner="old", author="file")
    destination = _identity(owner="new", author="renamed")

    with pytest.raises(ValidationError, match="path dependency"):
        build_plan(src_target, source, destination, rules)


def test_independent_path_rows_on_one_path_are_stable(src_target) -> None:
    nested = src_target / "old" / "file.txt"
    nested.parent.mkdir()
    nested.write_text("fixture\n", encoding="utf-8")
    parent = _candidate(
        "parent",
        "old",
        "new",
        surfaces=frozenset({"path"}),
    )
    leaf = _candidate(
        "leaf",
        "file",
        "doc",
        surfaces=frozenset({"path"}),
    )

    assert validate_pipeline((parent, leaf), initial_paths=("old/file.txt",)) == (
        parent,
        leaf,
    )

    source = _identity(repo_name="old", app_name="file")
    destination = _identity(repo_name="new", app_name="doc")
    build_plan(src_target, source, destination, DEFAULT_RULES)


def test_one_stable_row_can_rewrite_every_repeated_path_component() -> None:
    row = _candidate(
        "repeat",
        "old",
        "new",
        surfaces=frozenset({"path"}),
    )

    assert validate_pipeline((row,), initial_paths=("old/old/old/old.txt",)) == (row,)


def test_path_pipeline_accepts_fixpoint_on_runtime_pass_32() -> None:
    row = _candidate(
        "repeat",
        "old",
        "new",
        surfaces=frozenset({"path"}),
    )
    path = "/".join((*(("old",) * 31), "leaf.txt"))

    assert validate_pipeline((row,), initial_paths=(path,)) == (row,)


def test_path_pipeline_refuses_32_mutations_without_runtime_fixpoint() -> None:
    row = _candidate(
        "repeat",
        "old",
        "new",
        surfaces=frozenset({"path"}),
    )
    path = "/".join((*(("old",) * 32), "leaf.txt"))

    with pytest.raises(ValidationError, match="did not terminate"):
        validate_pipeline((row,), initial_paths=(path,))


def test_build_plan_rejects_identity_output_emitting_earlier_rule_source(
    src_target,
) -> None:
    rules = _rules(
        ReplaceRule(
            pattern="legacy_{app_name}",
            reason="earlier declared source",
            paths=False,
        )
    )
    source = _identity(app_name="old")
    destination = _identity(app_name="legacy_old")

    with pytest.raises(ValidationError, match="stale-source emission"):
        build_plan(src_target, source, destination, rules)


@requires_symlink
def test_build_plan_rejects_rule_output_consumed_in_symlink_target(
    src_target,
) -> None:
    link = src_target / "link"
    os.symlink("xold", link)
    rules = _rules(
        ReplaceRule(
            pattern="x{owner}",
            reason="retarget dangling symlink",
            paths=True,
            content=False,
        )
    )
    source = _identity(owner="old", author="xnew")
    destination = _identity(owner="new", author="zed")

    with pytest.raises(ValidationError, match="ordered symlink dependency"):
        build_plan(src_target, source, destination, rules)

    assert os.readlink(link) == "xold"


def test_build_plan_rejects_token_in_unchanged_destination_field(src_target) -> None:
    source = _identity(app_name="foo", author="foo owner")
    destination = _identity(app_name="bar", author="foo owner")

    with pytest.raises(ValidationError) as exc_info:
        build_plan(src_target, source, destination, DEFAULT_RULES)

    message = str(exc_info.value)
    assert "identity:app_name" in message
    assert "destination:author" in message


def test_build_plan_rejects_token_in_derived_destination_field(src_target) -> None:
    source = _identity(app_name="foo", owner="FOO")
    destination = _identity(app_name="foo", owner="BAR")

    with pytest.raises(ValidationError) as exc_info:
        build_plan(src_target, source, destination, DEFAULT_RULES)

    message = str(exc_info.value)
    assert "identity:owner" in message
    assert "destination:app_name_upper" in message


def test_disabled_display_form_is_not_a_destination_stability_sink(
    src_target,
) -> None:
    source = _identity(author="fooBar", display_name="Source Name")
    destination = _identity(author="Bar Author", display_name="Foo bar")
    rules = Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        regenerate=DEFAULT_RULES.regenerate,
        display_forms=("spaced",),
    )

    build_plan(src_target, source, destination, rules)


def test_disabled_spaced_display_form_is_not_a_destination_stability_sink(
    src_target,
) -> None:
    source = _identity(owner="foo", display_name="Source Suite")
    destination = _identity(owner="bar", display_name="foo suite")
    rules = Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        regenerate=DEFAULT_RULES.regenerate,
        display_forms=("camel",),
    )

    build_plan(src_target, source, destination, rules)


def test_equal_identity_values_keep_first_matcher_and_all_provenance(
    src_target,
) -> None:
    source = _identity(app_name="foo", owner="foo", author="_foo owner")
    destination = _identity(app_name="bar", owner="bar", author="_foo owner")

    plan = build_plan(src_target, source, destination, DEFAULT_RULES)
    assert plan.table is not None
    row = next(
        item
        for item in plan.table.rows
        if item.from_value == "foo" and item.to_value == "bar"
    )

    assert row.row_id == "identity:app_name"
    assert row.matcher == MatcherSpec("conservative", "app_name", False)
    assert [item.name for item in row.provenance] == ["app_name", "owner"]


def test_duplicate_identity_provenance_survives_shared_validation(src_target) -> None:
    source = _identity(package_name="foo", repo_name="foo", owner="foo")
    destination = _identity(package_name="bar", repo_name="bar", owner="baz")

    with pytest.raises(ValidationError) as exc_info:
        build_plan(src_target, source, destination, DEFAULT_RULES)

    message = str(exc_info.value)
    assert "identity:package_name" in message
    assert "repo_name" in message
    assert "identity:owner" in message


def test_duplicate_rule_provenance_survives_shared_validation(src_target) -> None:
    duplicate = ReplaceRule(pattern="{app_name}", reason="same declaration")
    rules = _rules(
        duplicate,
        duplicate,
        ReplaceRule(pattern="f{package_name}", reason="conflict"),
    )
    source = _identity(app_name="foo", package_name="oo")
    destination = _identity(app_name="bar", package_name="zz")

    with pytest.raises(ValidationError) as exc_info:
        build_plan(src_target, source, destination, rules)

    message = str(exc_info.value)
    assert "replace[1]" in message
    assert "replace[2]" in message
    assert "replace[3]" in message


def test_press_reuses_target_validated_disjoint_path_rules(
    src_target,
) -> None:
    left = src_target / "a" / "foo" / "left.txt"
    right = src_target / "b" / "foo" / "right.txt"
    left.parent.mkdir(parents=True)
    right.parent.mkdir(parents=True)
    left.write_text("clean\n", encoding="utf-8")
    right.write_text("clean\n", encoding="utf-8")
    rules = _rules(
        ReplaceRule(
            pattern="{app_name}",
            reason="left path",
            files=("a/foo/left.txt",),
            paths=True,
            content=False,
        ),
        ReplaceRule(
            pattern="f{package_name}",
            reason="right path",
            files=("b/foo/right.txt",),
            paths=True,
            content=False,
        ),
    )
    source = _identity(app_name="foo", package_name="oo")
    destination = _identity(app_name="one", package_name="zz")

    outcome = cli_module._press(src_target, source, destination, rules, [], [])

    assert outcome.env_error is None
    assert (src_target / "a" / "one" / "left.txt").is_file()
    assert (src_target / "b" / "fzz" / "right.txt").is_file()


def test_press_fallback_returns_validation_error_before_writes(
    src_target, capsys: pytest.CaptureFixture[str]
) -> None:
    rules = _rules(
        ReplaceRule(
            pattern="legacy_{app_name}",
            reason="earlier declared source",
            paths=False,
        )
    )
    source = _identity(app_name="old")
    destination = _identity(app_name="legacy_old")
    before = (src_target / "README.md").read_text(encoding="utf-8")

    outcome = cli_module._press(src_target, source, destination, rules, [], [])

    assert outcome.env_error is not None
    assert outcome.renamed == []
    assert (src_target / "README.md").read_text(encoding="utf-8") == before
    assert "nothing applied" in capsys.readouterr().err


def test_press_returns_partial_outcome_for_validation_error_after_reset(
    src_target,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reset = ResetRule(file="README.md", stub="reset\n")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None

    def fail_validation(*_args, **_kwargs):
        raise ValidationError("apply-time target paths changed")

    monkeypatch.setattr(cli_module, "apply", fail_validation)

    outcome = cli_module._press(
        src_target,
        SOURCE,
        DEST,
        DEFAULT_RULES,
        [],
        [(reset, "reset\n")],
        rendered_rules=plan.rendered_rules,
        table=plan.table,
    )

    assert outcome.env_error == "apply-time target paths changed"
    assert (src_target / "README.md").read_text(encoding="utf-8") == "reset\n"
    assert "target may be PARTIALLY rewritten" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("source", "destination", "rules"),
    (
        (
            _identity(app_name="press", display_name="press"),
            _identity(app_name="tool", display_name="Tool Pro"),
            DEFAULT_RULES,
        ),
        (
            _identity(app_name="a"),
            _identity(app_name="aa"),
            _rules(
                ReplaceRule(
                    pattern="{app_name}",
                    reason="path self rematch",
                    paths=True,
                    content=False,
                )
            ),
        ),
        (
            _identity(app_name="foo", package_name="oo"),
            _identity(app_name="bar", package_name="zz"),
            _rules(
                ReplaceRule(pattern="{app_name}", reason="first"),
                ReplaceRule(pattern="f{package_name}", reason="second"),
            ),
        ),
        (
            _identity(app_name="foo", repo_name="oldrepo"),
            _identity(app_name="bar", repo_name="oo"),
            _rules(
                ReplaceRule(pattern="f{repo_name}_Owned", reason="ordered output"),
            ),
        ),
    ),
)
def test_legacy_refusal_families_route_through_shared_validator(
    src_target,
    monkeypatch: pytest.MonkeyPatch,
    source: Identity,
    destination: Identity,
    rules: Rules,
) -> None:
    class SentinelError(RuntimeError):
        pass

    def sentinel(*_args, **_kwargs):
        raise SentinelError("shared validator reached")

    monkeypatch.setattr(engine, "validate_pipeline", sentinel)

    with pytest.raises(SentinelError, match="shared validator reached"):
        build_plan(src_target, source, destination, rules)


def test_cli_collision_preflight_routes_through_shared_validator(
    src_target, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SOURCE
    destination = Identity(**{**SOURCE.as_dict_prompted(), "app_name": "press_two"})
    source_path = src_target / SOURCE_CONFIG_REL
    source_path.parent.mkdir(exist_ok=True)
    source_path.write_text(render_source_config(source), encoding="utf-8")
    answers = tmp_path / "answers.toml"
    answers.write_text(
        "[answers]\n"
        + "\n".join(
            f'{key} = "{value}"'
            for key, value in destination.as_dict_prompted().items()
        )
        + "\n",
        encoding="utf-8",
    )

    class SentinelError(RuntimeError):
        pass

    def sentinel(*_args, **_kwargs):
        raise SentinelError("shared validator reached")

    monkeypatch.setattr(engine, "validate_pipeline", sentinel)

    with pytest.raises(SentinelError, match="shared validator reached"):
        main(
            [
                "--target",
                str(src_target),
                "--config",
                str(answers),
                "--allow-dirty",
            ]
        )
