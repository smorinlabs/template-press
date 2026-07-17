from pathlib import Path

from template_press.rebrand.rules import DEFAULT_RULES, load_rules


def test_defaults_exclude_state_and_vcs_dirs():
    assert ".git" in DEFAULT_RULES.exclude_dirs
    assert "press" in DEFAULT_RULES.exclude_dirs
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
