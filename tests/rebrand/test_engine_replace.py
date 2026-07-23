from pathlib import Path

from template_press.rebrand.engine import apply, replacement_pairs
from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


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


def test_symlink_content_is_never_followed(src_target: Path, tmp_path: Path):
    import os
    import subprocess as sp

    if os.name == "nt":  # symlink creation needs privileges on Windows
        import pytest

        pytest.skip("symlink semantics differ on Windows")
    outside = tmp_path / "outside.txt"
    outside.write_text("demo_widget lives outside\n", encoding="utf-8")
    link = src_target / "link.txt"
    link.symlink_to(outside)
    sp.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert outside.read_text(encoding="utf-8") == "demo_widget lives outside\n"
    assert any("link.txt (symlink)" in s for s in report.skipped)


class TestDisplayPairs:
    def test_no_display_no_display_pairs(self):
        pairs = replacement_pairs(_identity(), _identity(app_name="acme"))
        assert not any(f.startswith("display_name") for f, _, _ in pairs)

    def test_three_form_pairs_when_both_sides_declare(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        pairs = {f: (c, r) for f, c, r in replacement_pairs(src, dst)}
        assert pairs["display_name_spaced"] == ("Py Launch Blueprint", "Acme Widget")
        assert pairs["display_name_pascal"] == ("PyLaunchBlueprint", "AcmeWidget")
        assert pairs["display_name_camel"] == ("pyLaunchBlueprint", "acmeWidget")
        assert "display_name" not in pairs

    def test_half_specified_emits_no_display_pairs(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme")  # no display_name
        pairs = replacement_pairs(src, dst)
        assert not any(f.startswith("display_name") for f, _, _ in pairs)

    def test_form_subset_is_honored(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(display_name="Acme Widget")
        pairs = replacement_pairs(src, dst, display_form_names=("spaced",))
        fields = [f for f, _, _ in pairs if f.startswith("display_name")]
        assert fields == ["display_name_spaced"]
