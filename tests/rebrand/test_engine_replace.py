import dataclasses
import subprocess
from pathlib import Path

from template_press.rebrand.engine import apply, replacement_pairs
from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule

from .conftest import DEST, SOURCE


def _git_add_all(repo: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _rules_with(**overrides):
    return dataclasses.replace(DEFAULT_RULES, **overrides)


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


class TestReplaceRuleContent:
    def test_glued_token_rewritten_by_rule(self, src_target: Path):
        (src_target / "conftest.py").write_text(
            'getattr(h, "_plbp_owned", False)\n', encoding="utf-8"
        )
        _git_add_all(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(pattern="_{app_name}_owned", reason="ownership guard"),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        text = (src_target / "conftest.py").read_text(encoding="utf-8")
        assert "_acme_owned" in text and "_plbp_owned" not in text

    def test_rules_run_before_token_pass(self, src_target: Path):
        # Discriminating probe: FROM spans TWO fields ("{package_name}/
        # {app_name}-web"). If the token pass ran first, package_name's
        # generic boundary (hyphen counts as a boundary either side) would
        # rewrite "py_launch_blueprint" on its own, leaving "plbp-web"
        # behind — at which point the rule's rendered FROM no longer
        # matches the (now-mixed) text and never fires, so app_name's
        # trailing-hyphen boundary guard (a token boundary, never a rule
        # boundary) leaves "plbp-web" stranded in the output. Rules-first
        # (the correct order) replaces the whole compound in one shot, so
        # "plbp-web" never survives. This makes the two orders produce
        # visibly different text, unlike a single-field FROM where the
        # generic boundary alone already matches (see prior version of
        # this test, which a review found non-discriminating).
        (src_target / "note.md").write_text(
            "image: py_launch_blueprint/plbp-web\n", encoding="utf-8"
        )
        _git_add_all(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{package_name}/{app_name}-web",
                    reason="compound image ref",
                ),
            )
        )
        apply(
            src_target,
            _identity(),
            _identity(package_name="acme_widget", app_name="acme"),
            rules,
        )
        text = (src_target / "note.md").read_text(encoding="utf-8")
        assert "acme_widget/acme-web" in text
        assert "plbp-web" not in text

    def test_files_glob_scopes_rule(self, src_target: Path):
        # fnmatch (rule_matches_path's matcher, Task 6) matches the FULL
        # posix rel-path with no path-separator boundary, so a bare "*.txt"
        # glob is not directory-scoped — it would hit "docs/out_of_scope.txt"
        # too. Scope via an exact rel-path glob instead, which fnmatch DOES
        # bound to that literal path.
        (src_target / "in_scope.txt").write_text("plbp-web\n", encoding="utf-8")
        sub = src_target / "docs"
        sub.mkdir()
        (sub / "out_of_scope.txt").write_text("plbp-web\n", encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="image name",
                    files=("in_scope.txt",),
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert "acme-web" in (src_target / "in_scope.txt").read_text(encoding="utf-8")
        assert "plbp-web" in (sub / "out_of_scope.txt").read_text(encoding="utf-8")

    def test_content_false_rule_leaves_content(self, src_target: Path):
        (src_target / "a.txt").write_text("plbp-web\n", encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="paths only",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert "plbp-web" in (src_target / "a.txt").read_text(encoding="utf-8")


class TestSubstringMode:
    def test_glued_token_rewritten_when_opted_in(self, src_target: Path):
        (src_target / "Justfile").write_text('tag="plbp-web:dev"\n', encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert 'tag="acme-web:dev"' in (src_target / "Justfile").read_text(
            encoding="utf-8"
        )

    def test_substring_mode_replaces_inside_words_by_design(self, src_target: Path):
        # THE documented risk (codesign sec-02): substring mode on a
        # word-embedded token corrupts prose. plbp is word-disjoint so this
        # uses a synthetic embedding to pin the behavior as intentional.
        (src_target / "note.txt").write_text("xplbpy\n", encoding="utf-8")
        _git_add_all(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (src_target / "note.txt").read_text(encoding="utf-8") == "xacmey\n"

    def test_default_stays_conservative(self, src_target: Path):
        (src_target / "note.txt").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(src_target)
        apply(src_target, _identity(), _identity(app_name="acme"), DEFAULT_RULES)
        assert "_plbp_owned" in (src_target / "note.txt").read_text(encoding="utf-8")
