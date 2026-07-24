import dataclasses
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.engine import _rename_candidates, apply, build_plan
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
from template_press.rebrand.safety import ContainmentError, SafetyError

from .conftest import DEST, SOURCE, requires_symlink


def _git_add(repo: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
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


def _diverged_symlink_ancestor_repo(tmp_path: Path, leaf: str) -> tuple[Path, Path]:
    """A committed target whose real dir ``a/`` (holding ``a/<leaf>``) is, in a
    dirty working tree, swapped to a symlink pointing at an EXTERNAL dir.

    ``git ls-files`` still reports ``a/<leaf>`` from the INDEX, so any op on
    ``tgt/a/<leaf>`` that fails to validate ancestors traverses the ``a``
    symlink and mutates the external tree. Both dirs live under ``tmp_path``.
    """
    tgt = tmp_path / "tgt"
    ext = tmp_path / "ext"
    tgt.mkdir()
    ext.mkdir()
    _git(tgt, "init", "-q")
    _git(tgt, "config", "user.email", "a@b.c")
    _git(tgt, "config", "user.name", "x")
    (tgt / "a").mkdir()
    if leaf == "leaf":
        # token-bearing relative symlink (retarget candidate)
        os.symlink("../tgt/demo_widget/thing", tgt / "a" / "leaf")
    else:
        # token-bearing regular file (rename candidate)
        (tgt / "a" / leaf).write_text("in-repo content\n", encoding="utf-8")
    (tgt / "keep.txt").write_text("hi\n", encoding="utf-8")
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-q", "-m", "init")
    # DIVERGE: replace the real dir a/ with a symlink to the external dir.
    shutil.rmtree(tgt / "a")
    os.symlink(str(ext), tgt / "a")
    return tgt, ext


def test_package_dir_renamed_src_layout(src_target: Path):
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "src" / "potato_launcher" / "cli.py").is_file()
    assert not (src_target / "src" / "demo_widget").exists()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


def test_package_dir_renamed_flat_layout(flat_target: Path):
    apply(flat_target, SOURCE, DEST, DEFAULT_RULES)
    assert (flat_target / "potato_launcher" / "cli.py").is_file()
    assert not (flat_target / "demo_widget").exists()


def test_app_token_filename_renamed(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "potato_config.toml").is_file()
    assert not (src_target / "press_config.toml").exists()


def test_nested_token_bearing_paths_rename_fully(src_target: Path):
    extra = src_target / "src" / "demo_widget" / "demo_widget_extra.py"
    extra.write_text('"""demo_widget extra."""\n', encoding="utf-8")
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    moved = src_target / "src" / "potato_launcher" / "potato_launcher_extra.py"
    assert moved.is_file()
    assert not (src_target / "src" / "demo_widget").exists()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


@requires_symlink
def test_apply_rewrites_in_repo_relative_symlink_target(src_target: Path):
    """An in-repo relative symlink target embedding identity is retargeted so a
    pressed fork's links don't dangle — only the link STRING changes."""
    link = src_target / "link"
    os.symlink("demo_widget/thing", link)  # in-repo, relative, does not exist
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "potato_launcher/thing"
    # The pointed-to file was never created or followed.
    assert not (src_target / "potato_launcher" / "thing").exists()
    assert not (src_target / "demo_widget" / "thing").exists()


@requires_symlink
def test_apply_leaves_escaping_symlink_target_untouched(src_target: Path):
    """A symlink whose (token-bearing) target escapes the root is NEVER
    rewritten — containment refuses it, the link string is left intact."""
    link = src_target / "link"
    os.symlink("../../outside/demo_widget", link)  # escapes root
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "../../outside/demo_widget"  # unchanged


@requires_symlink
def test_apply_leaves_absolute_symlink_target_untouched(src_target: Path):
    """An absolute symlink target is never rewritten or followed (isabs skip)."""
    link = src_target / "link"
    os.symlink("/srv/demo_widget/thing", link)  # absolute link STRING only
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "/srv/demo_widget/thing"  # unchanged


@requires_symlink
def test_retarget_symlink_uses_substring_mode_for_opted_in_field(src_target: Path):
    """A field in substring_rewrite_fields must retarget symlinks via plain
    substring replace, not the boundary-guarded token pattern — mirroring
    _apply_replacements' dispatch (Fix 1). "plbpOwned" is glued (no boundary
    on the right side), so the default boundary match would leave it alone;
    substring mode must still catch it."""
    link = src_target / "link"
    os.symlink("targets/plbpOwned", link)
    _git_add(src_target)
    rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
    apply(src_target, _identity(), _identity(app_name="acme"), rules)
    assert os.readlink(link) == "targets/acmeOwned"


@requires_symlink
def test_retarget_excludes_display_form_pairs_dangling_link_guard(src_target: Path):
    """Display-form pairs rewrite symlink TEXT but display forms never rename
    paths (not in RENAME_FIELDS) — the target directory keeps its original
    name, so a display pair must not touch the link string either, or the
    link dangles (Fix 2)."""
    link = src_target / "link"
    os.symlink("PyLaunchBlueprint/data", link)
    _git_add(src_target)
    src = _identity(display_name="Py Launch Blueprint")
    dst = _identity(app_name="acme", display_name="Acme Widget")
    apply(src_target, src, dst, DEFAULT_RULES)
    assert os.readlink(link) == "PyLaunchBlueprint/data"


def test_app_name_upper_renamed(src_target: Path):
    """Uppercased app token in filenames should be renamed."""
    (src_target / "PRESS_GUIDE.md").write_text("# Press Guide\n", encoding="utf-8")
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "POTATO_GUIDE.md").is_file()
    assert not (src_target / "PRESS_GUIDE.md").exists()


@requires_symlink
def test_retarget_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """PoC mirror (C1): a token-bearing symlink whose ANCESTOR dir is (dirty
    state) a symlink to an external tree must NOT be retargeted through that
    ancestor. ``apply`` must fail closed (ContainmentError) and the external
    object's inode must be unchanged (nothing unlinked/recreated outside)."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="leaf")
    # External sink the escape would delete + recreate.
    os.symlink("../tgt/demo_widget/thing", ext / "leaf")
    ext_inode_before = os.lstat(ext / "leaf").st_ino
    ext_link_before = os.readlink(ext / "leaf")

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external object is byte-for-byte untouched: same inode, same target.
    assert (ext / "leaf").is_symlink()
    assert os.lstat(ext / "leaf").st_ino == ext_inode_before
    assert os.readlink(ext / "leaf") == ext_link_before


@requires_symlink
def test_rename_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """Same-class hole (I1) in the rename pass: a token-bearing path whose
    ANCESTOR dir is a symlink to an external tree must NOT be renamed through
    that ancestor. ``apply`` fails closed and the external file is untouched."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="demo_widget.txt")
    # External content the rename would move through the symlinked ancestor.
    (ext / "demo_widget.txt").write_text("external\n", encoding="utf-8")
    ext_inode_before = os.lstat(ext / "demo_widget.txt").st_ino

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external file was neither moved nor recreated.
    assert (ext / "demo_widget.txt").is_file()
    assert os.lstat(ext / "demo_widget.txt").st_ino == ext_inode_before
    assert not (ext / "potato_launcher.txt").exists()


@requires_symlink
def test_replace_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """Same-class hole in the CONTENT replace pass: a token-free-named regular
    file whose ANCESTOR dir is a symlink to an external tree, where the external
    file's CONTENT carries a source token, must NOT be rewritten through that
    ancestor. ``apply`` fails closed; the external file's inode + content are
    untouched (no write-through)."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="file.txt")
    # External file content embeds the source token — a write-through would
    # rewrite demo_widget -> potato_launcher in a file OUTSIDE the target.
    (ext / "file.txt").write_text("mentions demo_widget here\n", encoding="utf-8")
    ext_inode_before = os.lstat(ext / "file.txt").st_ino
    ext_content_before = (ext / "file.txt").read_text(encoding="utf-8")

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external file was neither rewritten nor recreated.
    assert (ext / "file.txt").is_file()
    assert os.lstat(ext / "file.txt").st_ino == ext_inode_before
    assert (ext / "file.txt").read_text(encoding="utf-8") == ext_content_before


class TestRulePathRenames:
    def test_paths_rule_renames_doc_filename(self, src_target: Path):
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "0001-plbp-cli-conventions.md").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="-{app_name}-",
                    reason="doc filename token",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-acme-cli-conventions.md").exists()
        assert not (docs / "0001-plbp-cli-conventions.md").exists()

    def test_paths_false_rule_never_renames(self, src_target: Path):
        (src_target / "plbp-web.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(ReplaceRule(pattern="{app_name}-web", reason="content only"),)
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (src_target / "plbp-web.txt").exists()

    def test_empty_component_fails_loud_at_plan_time(self, src_target: Path):
        (src_target / "plbp").mkdir()
        (src_target / "plbp" / "keep.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}",
                    reason="degenerate",
                    paths=True,
                    content=False,
                ),
            )
        )
        # A paths rule whose TO renders empty would collapse "plbp/" into its
        # parent — build a dest whose app_name yields an empty TO is not
        # constructible (validators forbid empty), so simulate the guard via
        # a rule that strips the whole component: FROM == component text.
        # Direct unit check on _renamed_rel:
        from template_press.rebrand.engine import _renamed_rel

        with pytest.raises(ValidationError):
            _renamed_rel(
                Path("plbp/keep.txt"),
                [],
                rendered=[(rules.replace[0], "plbp", "")],
            )

    def test_dest_component_collapsing_to_dotdot_raises_at_build_plan(
        self, src_target: Path
    ):
        (src_target / "sub").mkdir()
        (src_target / "sub" / "keep.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{author}",
                    reason="author-named dir (path-collapse guard)",
                    paths=True,
                    content=False,
                ),
            )
        )
        source = _identity(author="sub")
        dest = _identity(author="..")
        with pytest.raises(ValidationError):
            build_plan(src_target, source, dest, rules)


class TestSelfReapplyingPathsRule:
    """F2(a): a paths=true [[replace]] rule whose rendered TO still
    contains its rendered FROM re-matches its own output on every rename
    pass (a.txt -> ax.txt -> axx.txt -> ... for pattern "{app_name}x" with
    app_name a -> ax) — 32 destructive passes for nothing. Rejected loud at
    plan time, mirroring the substring self-embedding collision guard."""

    def test_self_reapplying_rule_raises_at_build_plan(self, src_target: Path):
        (src_target / "a.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}x",
                    reason="self-reapplying repro (a -> ax)",
                    paths=True,
                    content=False,
                ),
            )
        )
        source = _identity(app_name="a")
        dest = _identity(app_name="ax")
        with pytest.raises(ValidationError):
            build_plan(src_target, source, dest, rules)


class TestRenameFixpointExhaustion:
    """F2(b): _apply_renames must fail LOUD, never silently return, when 32
    passes still haven't reached a fixpoint.

    Fix (a) above rejects every [[replace]]-rule shape that could drive
    this (rendered FROM in rendered TO, checked at plan time in
    ``rendered_replace_rules``) — but that guard inspects rule literals
    ONLY. A plain identity field pair opted into substring rewrite mode
    (``rules.substring_rewrite_fields``) is applied with the same
    no-boundary ``str.replace`` and so can re-embed itself exactly like a
    rule can (app_name "ax" -> "axx": ax.txt -> axx.txt -> axxx.txt -> ...),
    entirely independent of any [[replace]] rule — this is the
    independently-constructible exhaustion case fix (a) does not (and
    cannot, being rule-scoped) cover.
    """

    def test_substring_field_self_reapply_raises(self, src_target: Path):
        (src_target / "ax.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        source = _identity(app_name="ax")
        dest = _identity(app_name="axx")
        with pytest.raises(SafetyError):
            apply(src_target, source, dest, rules)


class TestSubstringRenames:
    def test_doc_filename_renamed_with_substring_mode(self, src_target: Path):
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "0001-app-short-name-plbp.md").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-app-short-name-acme.md").exists()


class TestRenameDestinationSymlinkHardening:
    @requires_symlink
    def test_rename_skips_dangling_symlink_destination(self, src_target: Path):
        """F1: `dst.exists()` FOLLOWS symlinks, so a dangling symlink sitting
        at the rename destination reads as absent and POSIX rename() would
        silently replace it (in-tree destructive overwrite). The rename must
        be skipped instead, leaving both the source file and the dangling
        symlink exactly as they were."""
        source_file = src_target / "plbp-web.txt"
        source_file.write_text("original content\n", encoding="utf-8")
        dangling = src_target / "acme-web.txt"
        os.symlink("nonexistent-target", dangling)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="collision with a dangling symlink destination",
                    paths=True,
                    content=False,
                ),
            )
        )
        report = apply(src_target, _identity(), _identity(app_name="acme"), rules)
        # The rename was skipped: source untouched, symlink still dangling.
        assert source_file.is_file()
        assert source_file.read_text(encoding="utf-8") == "original content\n"
        assert dangling.is_symlink()
        assert not dangling.exists()  # still dangling — never replaced
        assert os.readlink(dangling) == "nonexistent-target"
        assert any(
            "plbp-web.txt" in entry and "symlink" in entry for entry in report.skipped
        )


class TestRetargetSymlinksFollowsPathsRules:
    @requires_symlink
    def test_paths_rule_dir_rename_retargets_symlink_text(self, src_target: Path):
        """F2: a paths=true [[replace]] rule renames plbp-web/ -> acme-web/,
        but `_retarget_symlinks` previously only saw plain field token pairs
        — a relative symlink pointing into the renamed dir would keep
        pointing at the now-gone old path. The rule must retarget the link
        text too, mirroring exactly what the rename pass moved."""
        webdir = src_target / "plbp-web"
        webdir.mkdir()
        (webdir / "data").write_text("x\n", encoding="utf-8")
        link = src_target / "link"
        os.symlink("plbp-web/data", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="dir rename retarget",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "acme-web/data"

    @requires_symlink
    def test_paths_rule_scope_matches_link_target_not_link_location(
        self, src_target: Path
    ):
        """F3: a `files` scope selects which TARGET paths a paths=true rule
        renames — `_retarget_symlinks` must match that scope against the
        symlink's TARGET (what actually got renamed), not the symlink's own
        location. A root-level link into docs/ must still be retargeted by a
        files=["docs/**"] rule even though the link itself lives at the
        repo root (outside that scope)."""
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "plbp-guide.md").write_text("x\n", encoding="utf-8")
        link = src_target / "guide"
        os.symlink("docs/plbp-guide.md", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-guide.md",
                    reason="doc rename retarget",
                    files=["docs/**"],
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "docs/acme-guide.md"


class TestRenameSeesSymlinkNames:
    """F2: retarget rewrites a symlink's TEXT only — the rename pass must
    ALSO see the symlink's own NAME as a candidate, or a token-bearing
    directory/dangling symlink's stale name survives every press forever
    (the doctor's dangling-symlink path scan then flags it permanently:
    `iter_target_files`'s `is_file()` FOLLOWS the link, so a symlink to a
    directory or to nothing drops out of both `_rename_pass_once` and
    `build_plan`'s rename-planning loop before this fix)."""

    @requires_symlink
    def test_dangling_symlink_name_renamed(self, src_target: Path):
        link = src_target / "plbp-link"
        os.symlink("nowhere", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dangling symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        report = apply(src_target, _identity(), _identity(app_name="acme"), rules)
        new_link = src_target / "acme-link"
        assert new_link.is_symlink()
        assert not new_link.exists()  # still dangling — target untouched
        assert os.readlink(new_link) == "nowhere"
        assert not link.is_symlink() and not link.exists()
        assert ("plbp-link", "acme-link") in report.renamed

    @requires_symlink
    def test_build_plan_lists_the_dangling_symlink_rename(self, src_target: Path):
        """Plan/apply parity: `build_plan` must see the same candidate
        `_rename_pass_once` does, or a dry-run silently under-reports what
        apply() will actually do."""
        link = src_target / "plbp-link"
        os.symlink("nowhere", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dangling symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        plan = build_plan(src_target, _identity(), _identity(app_name="acme"), rules)
        assert any(
            item.kind == "rename" and item.path == "plbp-link" for item in plan.items
        )

    @requires_symlink
    def test_directory_symlink_name_renamed(self, src_target: Path):
        """Cheap directory-symlink variant: the link's NAME renames, its
        target string is untouched, and it still resolves through."""
        real_dir = src_target / "realtarget"
        real_dir.mkdir()
        (real_dir / "f.txt").write_text("x\n", encoding="utf-8")
        link = src_target / "plbp-link"
        os.symlink("realtarget", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dir symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        new_link = src_target / "acme-link"
        assert new_link.is_symlink()
        assert os.readlink(new_link) == "realtarget"  # target string untouched
        assert (new_link / "f.txt").is_file()  # still resolves through
        assert not link.is_symlink()

    def test_gitlink_never_a_rename_candidate(self, src_target: Path, tmp_path: Path):
        """Gitlink exclusion: a submodule pointer must never be renamed by
        this pass, even when its own path carries an identity token.

        Not independently exercisable end-to-end via `apply()`: a real
        gitlink is a plain DIRECTORY when checked out (excluded already by
        the `is_file()`/`is_symlink()` filter — it is neither) and has no
        working-tree entry at all when not checked out (same exclusion, for
        the same reason) — a symlinked or regular-file gitlink is not a
        shape git produces. So this pins `_rename_candidates` directly
        (belt-and-suspenders defense-in-depth, mirroring `copy_paths`'
        established gitlink handling) rather than through a rename that
        could ever actually fire.
        """
        inner = tmp_path / "inner"
        inner.mkdir()
        _git(inner, "init", "-q", "-b", "main")
        _git(inner, "config", "user.email", "test@example.com")
        _git(inner, "config", "user.name", "Test")
        (inner / "f.txt").write_text("x\n", encoding="utf-8")
        _git_add(inner)
        _git(inner, "commit", "-q", "-m", "inner init")
        sha = subprocess.run(  # noqa: S603
            ["git", "-C", str(inner), "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
        _git(
            src_target, "update-index", "--add", "--cacheinfo", f"160000,{sha},plbp-sub"
        )
        _git(src_target, "commit", "-q", "-m", "add gitlink")
        candidates = {
            p.relative_to(src_target).as_posix()
            for p in _rename_candidates(src_target, DEFAULT_RULES)
        }
        assert "plbp-sub" not in candidates
