import os
import shutil
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.safety import ContainmentError

from .conftest import DEST, SOURCE


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


def test_apply_leaves_escaping_symlink_target_untouched(src_target: Path):
    """A symlink whose (token-bearing) target escapes the root is NEVER
    rewritten — containment refuses it, the link string is left intact."""
    link = src_target / "link"
    os.symlink("../../outside/demo_widget", link)  # escapes root
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "../../outside/demo_widget"  # unchanged


def test_apply_leaves_absolute_symlink_target_untouched(src_target: Path):
    """An absolute symlink target is never rewritten or followed (isabs skip)."""
    link = src_target / "link"
    os.symlink("/srv/demo_widget/thing", link)  # absolute link STRING only
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "/srv/demo_widget/thing"  # unchanged


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
