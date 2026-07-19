import os
import subprocess
from pathlib import Path

from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE, requires_symlink


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
