from pathlib import Path

from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_apply_rewrites_identity_everywhere(src_target: Path):
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert "README.md" in report.replaced
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "potato-launcher" in readme and "demo-widget" not in readme
    assert "potatolabs/potato-launcher" in readme
    assert "Potato Farmer <potato@example.com>" in readme
    pyproject = (src_target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "potato_launcher"' in pyproject
    assert 'potato = "potato_launcher.cli:main"' in pyproject


def test_apply_preserves_english_press_words(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "Compress" in readme and "express" in readme and "pressure" in readme
    assert "`potato --help`" in readme


def test_apply_rewrites_env_prefixes(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    cli = (src_target / "src" / "potato_launcher" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "POTATO_LOG_LEVEL" in cli and "_POTATO_COMPLETE" in cli
    assert "PRESS_" not in cli


def test_apply_skips_excluded_files(src_target: Path):
    (src_target / "CHANGELOG.md").write_text(
        "history of demo_widget\n", encoding="utf-8"
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    text = (src_target / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "demo_widget" in text  # excluded by default rules
