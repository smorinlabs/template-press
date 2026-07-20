"""Exact-root control exemption + root `press` component rename protection.

ROOT_CONTROL exempts an exact artifact (rel path), never a whole subtree:
only the four literal `press/press-*.toml` control files are exempt from
iteration. Any other file under (or nested elsewhere as) a `press/` dir is
ordinary content — scanned and rewritten like anything else. Separately,
the literal root `press` dirname is protected from being renamed (and from
a false path-leak) because ROOT_CONTROL is keyed on that exact prefix.
"""

import subprocess
from pathlib import Path

from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import apply, iter_target_files
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def _rel(target: Path, paths: list[Path]) -> set[str]:
    return {p.relative_to(target).as_posix() for p in paths}


def test_root_control_file_exempt_from_iteration(src_target: Path):
    d = src_target / "press"
    d.mkdir(exist_ok=True)
    (d / "press-source.toml").write_text(
        '[identity]\npackage_name = "demo_widget"\nowner = "demolabs"\n',
        encoding="utf-8",
    )
    rels = _rel(src_target, iter_target_files(src_target, DEFAULT_RULES))
    assert "press/press-source.toml" not in rels


def test_nested_press_leak_is_scanned(src_target: Path):
    d = src_target / "docs" / "press"
    d.mkdir(parents=True, exist_ok=True)
    (d / "leak.md").write_text("legacy note mentioning demo_widget\n", encoding="utf-8")
    rels = _rel(src_target, iter_target_files(src_target, DEFAULT_RULES))
    assert "docs/press/leak.md" in rels


def test_root_press_dir_not_renamed(src_target: Path):
    d = src_target / "press"
    d.mkdir(exist_ok=True)
    (d / "notes.md").write_text("press build notes\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add root press notes"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    notes = src_target / "press" / "notes.md"
    assert notes.is_file()
    body = notes.read_text(encoding="utf-8")
    assert "potato" in body
    assert "press build" not in body
    assert not (src_target / "potato" / "notes.md").exists()


def test_root_press_descendant_renames_root_dir_preserved(src_target: Path):
    """A token-bearing DESCENDANT under the protected root press/ dir must
    still rename (press/press_notes.md -> press/potato_notes.md) while the
    root press/ control dir itself is preserved; no path-leak may survive
    (F4). Before the fix the rename builder abandoned the whole path at the
    root `press` component, leaving press/press_notes.md — a path leak.
    """
    d = src_target / "press"
    d.mkdir(exist_ok=True)
    # A root control file makes press/ this tool's legitimate control dir.
    (d / "press-source.toml").write_text(
        '[identity]\npackage_name = "demo_widget"\nowner = "demolabs"\n',
        encoding="utf-8",
    )
    (d / "press_notes.md").write_text("press build notes\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add press child"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "press" / "potato_notes.md").is_file()
    assert not (src_target / "press" / "press_notes.md").exists()
    assert (src_target / "press").is_dir()  # root control dir preserved
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES, DEST) == []


def test_nested_press_dir_still_renames(src_target: Path):
    d = src_target / "docs" / "press"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text("press build notes\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add nested press notes"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "docs" / "potato" / "notes.md").is_file()
    assert not (src_target / "docs" / "press").exists()
