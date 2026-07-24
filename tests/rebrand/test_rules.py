from pathlib import Path

import pytest

from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    ReplaceRule,
    load_rules,
    pattern_static_segments,
    render_replace_pattern,
    rule_matches_path,
)


def test_defaults_exclude_state_and_vcs_dirs():
    assert ".git" in DEFAULT_RULES.exclude_dirs
    # The control press/ dir is exempted content-keyed by the engine
    # (CONTROL_MARKERS), NOT via a blanket any-depth exclude_dirs entry —
    # so an unrelated press/ in a target is still rewritten + leak-scanned.
    assert "press" not in DEFAULT_RULES.exclude_dirs
    assert "uv.lock" in DEFAULT_RULES.exclude_files
    assert "uv.lock" in DEFAULT_RULES.regenerate


def test_load_rules_without_override_returns_defaults(tmp_path: Path):
    assert load_rules(tmp_path) == DEFAULT_RULES


def test_load_rules_merges_target_overrides(tmp_path: Path):
    press = tmp_path / "press"
    press.mkdir()
    (press / "press-rules.toml").write_text(
        "[rules]\n"
        'extra_exclude_dirs = ["vendored"]\n'
        'extra_exclude_files = ["docs/history.md"]\n'
        'regenerate = ["uv.lock", "bun.lock"]\n',
        encoding="utf-8",
    )
    rules = load_rules(tmp_path)
    assert "vendored" in rules.exclude_dirs
    assert ".git" in rules.exclude_dirs  # defaults kept
    assert "docs/history.md" in rules.exclude_files
    assert rules.regenerate == ("uv.lock", "bun.lock")


def test_load_rules_rejects_non_list_override(tmp_path: Path):
    import pytest

    from template_press.rebrand.identity import ValidationError

    press = tmp_path / "press"
    press.mkdir()
    (press / "press-rules.toml").write_text(
        '[rules]\nextra_exclude_files = "just-a-string"\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="list of strings"):
        load_rules(tmp_path)


def test_unknown_rules_key_rejected(tmp_path: Path):
    press = tmp_path / "press"
    press.mkdir()
    (press / "press-rules.toml").write_text(
        '[rules]\nsubstring_rewrite_field = ["app_name"]\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="substring_rewrite_field"):
        load_rules(tmp_path)


def test_nested_dir_entries_are_rejected_loudly(tmp_path: Path):
    import pytest

    from template_press.rebrand.identity import ValidationError

    press = tmp_path / "press"
    press.mkdir()
    (press / "press-rules.toml").write_text(
        '[rules]\nverify_ignore = ["docs/history"]\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="single directory"):
        load_rules(tmp_path)


def _write_rules(tmp_path, body: str):
    d = tmp_path / "press"
    d.mkdir(exist_ok=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path


class TestReplaceRules:
    def test_defaults_empty(self):
        assert DEFAULT_RULES.replace == ()
        assert DEFAULT_RULES.substring_rewrite_fields == frozenset()
        assert DEFAULT_RULES.display_forms == ("spaced", "pascal", "camel")

    def test_parse_full_rule(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "_{app_name}_owned"\n'
            'files = ["tests/**"]\npaths = false\ncontent = true\n'
            'reason = "logging ownership guard"\n',
        )
        rules = load_rules(target)
        (rule,) = rules.replace
        assert rule.pattern == "_{app_name}_owned"
        assert rule.files == ("tests/**",)
        assert rule.paths is False and rule.content is True
        assert rule.reason == "logging ownership guard"

    def test_reason_is_required(self, tmp_path):
        target = _write_rules(tmp_path, '[[replace]]\npattern = "{app_name}-web"\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_pattern_must_reference_a_field(self, tmp_path):
        target = _write_rules(
            tmp_path, '[[replace]]\npattern = "plbp-web"\nreason = "r"\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_placeholder_rejected(self, tmp_path):
        target = _write_rules(
            tmp_path, '[[replace]]\npattern = "{appname}-web"\nreason = "r"\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_paths_and_content_not_both_false(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "{app_name}-web"\nreason = "r"\n'
            "paths = false\ncontent = false\n",
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_key_rejected(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "{app_name}-web"\nreason = "r"\nglob = "x"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestRewriteKnobs:
    def test_substring_fields_parse_and_validate(self, tmp_path):
        target = _write_rules(
            tmp_path, '[rules]\nsubstring_rewrite_fields = ["app_name"]\n'
        )
        assert load_rules(target).substring_rewrite_fields == frozenset({"app_name"})
        target = _write_rules(
            tmp_path, '[rules]\nsubstring_rewrite_fields = ["nope"]\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_display_forms_subset(self, tmp_path):
        target = _write_rules(tmp_path, '[rules]\ndisplay_forms = ["spaced"]\n')
        assert load_rules(target).display_forms == ("spaced",)
        target = _write_rules(tmp_path, "[rules]\ndisplay_forms = []\n")
        with pytest.raises(ValidationError):
            load_rules(target)
        target = _write_rules(tmp_path, '[rules]\ndisplay_forms = ["kebab"]\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_display_name_in_substring_rewrite_fields_is_rejected(self, tmp_path):
        """F4: substring_rewrite_fields = ["display_name"] validates (it is
        in ALLOWED_PLACEHOLDERS) but is a complete no-op — runtime pair tags
        are display_name_spaced/pascal/camel, never bare "display_name".
        Fail closed at parse time instead of silently doing nothing."""
        target = _write_rules(
            tmp_path, '[rules]\nsubstring_rewrite_fields = ["display_name"]\n'
        )
        with pytest.raises(ValidationError, match="display_forms"):
            load_rules(target)


def _identity(**overrides):
    base = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    base.update(overrides)
    return Identity(**base)


class TestRuleRendering:
    def test_renders_both_sides(self):
        src = _identity()
        dst = _identity(app_name="acme")
        assert render_replace_pattern("_{app_name}_owned", src) == "_plbp_owned"
        assert render_replace_pattern("_{app_name}_owned", dst) == "_acme_owned"

    def test_app_name_upper_placeholder(self):
        assert (
            render_replace_pattern("{app_name_upper}_HOME", _identity()) == "PLBP_HOME"
        )

    def test_missing_display_name_fails_loud(self):
        with pytest.raises(ValidationError):
            render_replace_pattern("{display_name}!", _identity())

    def test_display_name_renders_when_declared(self):
        ident = _identity(display_name="Py Launch Blueprint")
        assert (
            render_replace_pattern("{display_name}!", ident) == "Py Launch Blueprint!"
        )


class TestPatternStaticSegments:
    """F2: the literal (non-placeholder) text of a rule pattern — used by
    `engine.rendered_replace_rules` to guard against a rule's own static
    text colliding with a changing identity token."""

    def test_single_placeholder_splits_before_and_after(self):
        assert pattern_static_segments("foo_{app_name}Owned") == ["foo_", "Owned"]

    def test_leading_placeholder_yields_empty_leading_segment(self):
        assert pattern_static_segments("{app_name}-web") == ["", "-web"]

    def test_multiple_placeholders(self):
        assert pattern_static_segments("{owner}/{repo_name}") == ["", "/", ""]

    def test_no_placeholder_is_a_single_segment(self):
        # Not a legal committed rule (parsing requires >=1 placeholder), but
        # the splitter itself must not choke on it.
        assert pattern_static_segments("plain") == ["plain"]


class TestRuleScoping:
    def test_empty_files_matches_everything(self):
        rule = ReplaceRule(pattern="{app_name}", reason="r")
        assert rule_matches_path(rule, "any/where.py")

    def test_glob_scopes(self):
        rule = ReplaceRule(pattern="{app_name}", reason="r", files=("tests/**",))
        assert rule_matches_path(rule, "tests/core/test_logging.py")
        assert not rule_matches_path(rule, "src/pkg/mod.py")


class TestFailClosedParserGaps:
    """F5: the parser's root-level and brace-token fail-opens."""

    def test_unknown_root_key_rejected(self, tmp_path):
        """(a) An unknown ROOT table (e.g. a `[[replace]]` typo) previously
        loaded silently as zero rules instead of failing loud."""
        target = _write_rules(
            tmp_path, '[[replcae]]\npattern = "{app_name}-web"\nreason = "r"\n'
        )
        with pytest.raises(ValidationError, match="replcae"):
            load_rules(target)

    def test_malformed_brace_token_rejected_even_with_a_valid_placeholder(
        self, tmp_path
    ):
        """(b) A malformed brace token (e.g. `{app_name1}`) previously
        rendered literally when at least one valid placeholder existed
        elsewhere in the pattern, instead of failing loud at parse time."""
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "{package_name}/{app_name1}-web"\nreason = "r"\n',
        )
        with pytest.raises(ValidationError, match=r"\{app_name1\}"):
            load_rules(target)
