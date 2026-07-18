import os
import subprocess
from pathlib import Path

from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def _git_add(repo: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


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
