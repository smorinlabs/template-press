"""P06-TS04: contract tests for the pure pipeline-stability validator."""

from __future__ import annotations

import pytest
from template_press.rebrand.pipeline import (
    MatcherSpec,
    PipelineCandidate,
    validate_pipeline,
)

from template_press.rebrand import engine
from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.engine import build_plan, rendered_replace_rules
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, Rules


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
        extra_exclude_dirs=DEFAULT_RULES.extra_exclude_dirs,
        extra_exclude_files=DEFAULT_RULES.extra_exclude_files,
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


def test_content_output_cannot_emit_an_earlier_source() -> None:
    first = _candidate("first", "alpha", "bravo", provenance=("rule:first",))
    second = _candidate("second", "charlie", "alpha", provenance=("rule:second",))

    with pytest.raises(ValidationError) as exc_info:
        validate_pipeline((first, second))

    message = str(exc_info.value)
    assert "stale-source emission" in message
    assert "first" in message and "rule:first" in message
    assert "second" in message and "rule:second" in message


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
    calls: list[tuple[tuple[PipelineCandidate, ...], tuple[str, ...]]] = []
    real_validator = engine.validate_pipeline

    def recording_validator(candidates, *, initial_paths=()):
        calls.append((tuple(candidates), tuple(initial_paths)))
        return real_validator(candidates, initial_paths=initial_paths)

    monkeypatch.setattr(engine, "validate_pipeline", recording_validator)
    rules = _rules(
        ReplaceRule(
            pattern="{owner}-owned",
            reason="literal matcher probe",
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
    candidates, initial_paths = calls[0]
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
    assert "README.md" in initial_paths


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


def test_build_plan_rejects_identity_output_emitting_earlier_rule_source(
    src_target,
) -> None:
    rules = _rules(
        ReplaceRule(
            pattern="legacy-{app_name}",
            reason="earlier declared source",
            paths=False,
        )
    )
    source = _identity(app_name="old")
    destination = _identity(app_name="legacy-old")

    with pytest.raises(ValidationError, match="stale-source emission"):
        build_plan(src_target, source, destination, rules)


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
    source = _identity(app_name="press")
    destination = _identity(app_name="press_two")
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
