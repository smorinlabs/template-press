"""P03-M4c: the press/ collision guard (content-keyed exemption + warning).

Only a press/ dir that holds a control marker (press-*.toml, which
legitimately carries SOURCE identity) is exempt from rewriting and the
no-leak scan. Any other press/ dir is ordinary content — rewritten AND
scanned — so an unrelated press/ can never yield a false 'verified'.
"""

from pathlib import Path

from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import apply, iter_target_files, stray_press_dirs
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def _rel(target: Path, paths: list[Path]) -> set[str]:
    return {p.relative_to(target).as_posix() for p in paths}


def _add_control_press(target: Path) -> None:
    d = target / "press"
    d.mkdir(exist_ok=True)
    # press-source.toml legitimately records the SOURCE identity.
    (d / "press-source.toml").write_text(
        '[identity]\npackage_name = "demo_widget"\nowner = "demolabs"\n',
        encoding="utf-8",
    )


def _add_stray_press(target: Path, leftover: str = "demolabs") -> None:
    d = target / "docs" / "press"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text(
        f"legacy note mentioning {leftover}\n", encoding="utf-8"
    )


def _add_root_press_notes(target: Path) -> None:
    d = target / "press"
    d.mkdir(exist_ok=True)
    (d / "notes.md").write_text("press build notes\n", encoding="utf-8")


def test_control_press_dir_excluded_from_iteration(src_target: Path):
    _add_control_press(src_target)
    assert "press/press-source.toml" not in _rel(
        src_target, iter_target_files(src_target, DEFAULT_RULES)
    )


def test_stray_press_dir_included_in_iteration(src_target: Path):
    _add_stray_press(src_target)
    assert "docs/press/notes.md" in _rel(
        src_target, iter_target_files(src_target, DEFAULT_RULES)
    )


def test_stray_press_dirs_lists_strays_not_control(src_target: Path):
    _add_control_press(src_target)
    _add_stray_press(src_target)
    assert stray_press_dirs(src_target) == ["docs/press"]


def test_doctor_flags_source_leftover_in_stray_press(src_target: Path):
    # The distinguishing test: under the old any-depth exclusion this file
    # was never scanned, so a surviving source leftover produced a false clean.
    _add_stray_press(src_target, leftover="demo_widget")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "docs/press/notes.md" and e.field == "package_name" for e in leaks
    )


def test_doctor_exempts_source_leftover_in_control_press(src_target: Path):
    _add_control_press(src_target)  # holds source leftovers by design
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert not any(e.path.startswith("press/") for e in leaks)


def test_full_press_rewrites_stray_press_no_false_verified(src_target: Path):
    _add_stray_press(src_target, leftover="demolabs")
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    # scan is clean...
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES, dest=DEST) == []
    # ...because the stray dir was actually rewritten AND renamed
    # (app_name press -> potato), not skipped.
    renamed = src_target / "docs" / "potato" / "notes.md"
    assert renamed.is_file()
    body = renamed.read_text(encoding="utf-8")
    assert "potatolabs" in body and "demolabs" not in body


def test_doctor_no_path_leak_on_root_press(src_target: Path):
    _add_root_press_notes(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES, dest=DEST)
    assert not any(
        leak.where == "path" and leak.path.startswith("press/") for leak in leaks
    )
