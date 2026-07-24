import os
import subprocess
from pathlib import Path

from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import apply
from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule

from .conftest import DEST, SOURCE, requires_symlink


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


def test_clean_rebrand_has_no_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_content_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "notes.md").write_text(
        "demo_widget survived here\n", encoding="utf-8"
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "notes.md" and e.field == "package_name" and e.where == "content"
        for e in leaks
    )


def test_path_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "demo_widget_old.txt").write_text("x", encoding="utf-8")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(e.where == "path" for e in leaks)


def test_english_press_words_are_not_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    # README still contains Compress/express/pressure — must NOT count
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_render_leak_report_is_actionable():
    from template_press.rebrand.doctor import Leak

    text = render_leak_report(
        [Leak(path="a.md", field="app_name", value="press", where="content")]
    )
    assert "a.md" in text and "press" in text


def test_app_name_upper_path_leak_detected(src_target: Path):
    """Surviving uppercase app tokens in paths should be detected as leaks."""
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "PRESS_NOTES.md").write_text("x", encoding="utf-8")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "PRESS_NOTES.md" and e.field == "app_name_upper" and e.where == "path"
        for e in leaks
    )


@requires_symlink
def test_doctor_flags_symlink_target_embedding_identity(src_target: Path):
    """A symlink whose os.readlink target embeds a source token is a leak: a
    link target carrying identity would dangle/leak in a pressed fork."""
    link = src_target / "link.txt"
    # Points to an existing file (so is_file() follows and the link appears in
    # iter_target_files); the readlink string embeds package_name.
    os.symlink("src/demo_widget/cli.py", link)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "link.txt"
        and e.field == "package_name"
        and e.value == "demo_widget"
        and e.where == "symlink"
        for e in leaks
    )


@requires_symlink
def test_dangling_symlink_readlink_leak_detected(src_target: Path):
    """A DANGLING symlink whose readlink target embeds a source token must be
    flagged. `iter_target_files` filters on `is_file()` (which FOLLOWS links),
    so DIRECTORY and DANGLING symlinks never reached the doctor's readlink
    scan — a token-bearing link string in them slipped the gate."""
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    link = src_target / "dangling_link"
    os.symlink("nonexistent/demo_widget_backup", link)  # dangling; embeds token
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "dangling_link"
        and e.field == "package_name"
        and e.value == "demo_widget"
        and e.where == "symlink"
        for e in leaks
    )


@requires_symlink
def test_dir_symlink_without_token_is_clean(src_target: Path):
    """A directory symlink whose link string carries no identity token is not
    a leak — and the new symlink pass must not double-report symlinks."""
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    link = src_target / "src_link"
    os.symlink("src", link)  # points to the src/ dir; link string has no token
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert not any(e.path == "src_link" for e in leaks)


@requires_symlink
def test_symlink_to_file_leak_not_double_reported(src_target: Path):
    """A symlink-to-file (covered by the main loop) must be reported EXACTLY
    once — the new dir/dangling pass dedupes against it."""
    link = src_target / "link.txt"
    os.symlink("src/demo_widget/cli.py", link)  # target exists -> is_file True
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    symlink_hits = [
        e
        for e in leaks
        if e.path == "link.txt" and e.where == "symlink" and e.field == "package_name"
    ]
    assert len(symlink_hits) == 1


@requires_symlink
def test_dangling_symlink_name_embedding_identity_is_path_leak(src_target: Path):
    """F-e: doctor Pass 2 must scan a dir/dangling symlink's own NAME, not just
    its readlink target. A dangling symlink whose NAME carries a source token
    escapes the main loop (`iter_target_files` drops non-`is_file()` paths), so
    Pass 2 must scan `rel.parts` the way Pass 1 does. The link TARGET here is
    token-free, so only a name scan can flag it."""
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    link = src_target / "demo_widget_link"  # NAME carries package_name
    os.symlink("nonexistent/clean_target", link)  # dangling; target has no token
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "demo_widget_link"
        and e.field == "package_name"
        and e.value == "demo_widget"
        and e.where == "path"
        for e in leaks
    )


def test_unreadable_file_fails_verification(src_target: Path):
    import os

    if os.name == "nt" or os.geteuid() == 0:
        import pytest

        pytest.skip("permission semantics differ on Windows/root")
    from template_press.rebrand.engine import apply
    from template_press.rebrand.rules import DEFAULT_RULES

    from .conftest import DEST, SOURCE

    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    secret = src_target / "unreadable.md"
    secret.write_text("clean content\n", encoding="utf-8")
    secret.chmod(0o000)
    try:
        leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    finally:
        secret.chmod(0o644)
    assert any(e.where == "unverifiable" for e in leaks)


class TestDisplayNameLeaks:
    def test_surviving_pascal_form_is_a_leak(self, src_target: Path):
        (src_target / "README.md").write_text(
            "# PyLaunchBlueprint docs\n", encoding="utf-8"
        )
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        leaks = find_leaks(src_target, src, DEFAULT_RULES, dest=dst)
        assert any(
            lk.field == "display_name_pascal" and lk.where == "content" for lk in leaks
        )

    def test_unchanged_display_name_is_not_a_leak(self, src_target: Path):
        (src_target / "README.md").write_text("Py Launch Blueprint\n", encoding="utf-8")
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Py Launch Blueprint")
        leaks = find_leaks(src_target, src, DEFAULT_RULES, dest=dst)
        assert not any(lk.field.startswith("display_name") for lk in leaks)

    def test_surviving_pascal_form_in_path_is_a_leak(self, src_target: Path):
        """Both path-component loops must scan display-form fields too, not
        just PATH_FIELDS — a leftover PyLaunchBlueprint/ dir passes the
        content scan cleanly (no such text) but must still be flagged as a
        path leak (Fix 2)."""
        pascal_dir = src_target / "PyLaunchBlueprint"
        pascal_dir.mkdir()
        (pascal_dir / "notes.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        leaks = find_leaks(src_target, src, DEFAULT_RULES, dest=dst)
        assert any(
            lk.field == "display_name_pascal" and lk.where == "path" for lk in leaks
        )

    @requires_symlink
    def test_dangling_symlink_under_display_named_dir_is_a_path_leak(
        self, src_target: Path
    ):
        """F6: the FIRST (regular-file) path-component loop never reaches a
        DANGLING symlink — `iter_target_files` calls `is_file()`, which
        FOLLOWS the link and drops it entirely. Only the SECOND (dir/
        dangling-symlink) path-component loop scans it, and it must cover
        display-form fields too, not just PATH_FIELDS — a display-named
        directory holding nothing but a dangling symlink must still be
        flagged as a display-form path leak."""
        display_dir = src_target / "PyLaunchBlueprint"
        display_dir.mkdir()
        link = display_dir / "link"
        os.symlink("nonexistent-target", link)
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        leaks = find_leaks(src_target, src, DEFAULT_RULES, dest=dst)
        assert any(
            lk.path == "PyLaunchBlueprint/link"
            and lk.field == "display_name_pascal"
            and lk.where == "path"
            for lk in leaks
        )


class TestSubstringAwareLeaks:
    """Fix 3: when substring_rewrite_fields promises glued-token coverage,
    find_leaks must scan for it too, or a containment-skipped glued
    leftover (e.g. a symlink target the retarget pass refused to touch)
    would earn a receipt despite surviving."""

    def test_glued_content_leak_detected_in_substring_mode(self, src_target: Path):
        (src_target / "leftover.txt").write_text("plbpOwned\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target, src, DEFAULT_RULES, substring_fields=frozenset({"app_name"})
        )
        assert any(
            lk.path == "leftover.txt"
            and lk.field == "app_name"
            and lk.where == "content"
            for lk in leaks
        )

    def test_glued_content_not_a_leak_with_default_rules(self, src_target: Path):
        """Same fixture, no substring_fields: the boundary-guarded
        token_occurs must NOT flag "plbpOwned" — proving the prior test's
        hit came from the substring dispatch, not a loosened default."""
        (src_target / "leftover.txt").write_text("plbpOwned\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(src_target, src, DEFAULT_RULES)
        assert not any(lk.path == "leftover.txt" for lk in leaks)

    @requires_symlink
    def test_glued_symlink_text_leak_detected_in_substring_mode(self, src_target: Path):
        link = src_target / "link"
        os.symlink("../../outside/plbpOwned", link)
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target, src, DEFAULT_RULES, substring_fields=frozenset({"app_name"})
        )
        assert any(
            lk.path == "link" and lk.field == "app_name" and lk.where == "symlink"
            for lk in leaks
        )


class TestRenderedRuleLeaks:
    """F1: a [[replace]] rule can be the ONLY matcher for a boundary-unmatched
    rendered FROM literal — e.g. `_{app_name}_owned` renders to `_plbp_owned`,
    whose LEADING underscore blocks app_name's own boundary matcher on the
    left (identity.token_pattern excludes `_` from the left side for
    app_name). When the retarget pass skips an escaping symlink (containment
    refuses to rewrite outside the tree), the rendered rule's FROM literal
    survives verbatim in the link text — and only a rule-aware scan catches
    it."""

    def test_glued_content_leak_via_rule_only(self, src_target: Path):
        rule = ReplaceRule(pattern="_{app_name}_owned", reason="test")
        (src_target / "conftest.py").write_text("_plbp_owned\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "_plbp_owned", "_acme_owned")],
        )
        assert any(
            lk.path == "conftest.py"
            and lk.field == "replace_rule"
            and lk.value == "_plbp_owned"
            and lk.where == "content"
            for lk in leaks
        )
        # The plain app_name field scan must NOT have caught it on its own —
        # proving the hit came from rule-aware scanning, not a preexisting path.
        assert not any(lk.field == "app_name" for lk in leaks)

    def test_content_rule_scoped_by_files_glob(self, src_target: Path):
        """A rule scoped to `files` must not flag a FROM literal outside it."""
        rule = ReplaceRule(
            pattern="_{app_name}_owned", reason="test", files=("docs/**",)
        )
        (src_target / "conftest.py").write_text("_plbp_owned\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "_plbp_owned", "_acme_owned")],
        )
        assert not any(lk.field == "replace_rule" for lk in leaks)

    def test_path_component_leak_via_rule_only(self, src_target: Path):
        rule = ReplaceRule(
            pattern="-{app_name}.md", reason="test", paths=True, content=False
        )
        (src_target / "0001-plbp.md").write_text("x\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "-plbp.md", "-acme.md")],
        )
        assert any(
            lk.path == "0001-plbp.md"
            and lk.field == "replace_rule"
            and lk.value == "-plbp.md"
            and lk.where == "path"
            for lk in leaks
        )

    @requires_symlink
    def test_dangling_symlink_name_leak_via_rule_only(self, src_target: Path):
        """The dir/dangling-symlink pass (Pass 2) must also scan rule FROM
        literals against path COMPONENTS — mirroring the main loop."""
        rule = ReplaceRule(
            pattern="-{app_name}.md", reason="test", paths=True, content=False
        )
        os.symlink("nonexistent-target", src_target / "0001-plbp.md")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "-plbp.md", "-acme.md")],
        )
        assert any(
            lk.path == "0001-plbp.md"
            and lk.field == "replace_rule"
            and lk.value == "-plbp.md"
            and lk.where == "path"
            for lk in leaks
        )

    @requires_symlink
    def test_escaping_symlink_text_leak_via_rule_only(self, src_target: Path):
        """The exact F1 repro: an escaping symlink's target text carries the
        rendered FROM literal glued with underscores on both sides — the
        retarget pass refuses to rewrite it (containment), and the ordinary
        boundary-guarded app_name scan can't match it either (leading `_`
        blocks the left boundary). Only the rule-aware symlink scan, scoped
        against the link's normalized TARGET path, catches it."""
        rule = ReplaceRule(
            pattern="_{app_name}_owned", reason="test", paths=True, content=False
        )
        link = src_target / "escaping-link"
        os.symlink("../../outside/_plbp_owned", link)
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "_plbp_owned", "_acme_owned")],
        )
        assert any(
            lk.path == "escaping-link"
            and lk.field == "replace_rule"
            and lk.value == "_plbp_owned"
            and lk.where == "symlink"
            for lk in leaks
        )
        assert not any(lk.field == "app_name" for lk in leaks)

    def test_no_false_positive_after_rule_actually_applied(self, src_target: Path):
        """Negative control: once the rule's rendered FROM is genuinely gone
        (a normal rewrite ran), passing rendered_rules must not manufacture
        a leak — `to` is never itself scanned for."""
        rule = ReplaceRule(
            pattern="-{app_name}.md", reason="test", paths=True, content=False
        )
        (src_target / "0001-acme.md").write_text("x\n", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        src = _identity()
        leaks = find_leaks(
            src_target,
            src,
            DEFAULT_RULES,
            rendered_rules=[(rule, "-plbp.md", "-acme.md")],
        )
        assert not any(lk.field == "replace_rule" for lk in leaks)
