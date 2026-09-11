"""Control-directory advice describes the same target inventory as the plan."""

from pathlib import Path

import pytest

from template_press.rebrand import engine
from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE, _git
from .test_cli import write_answers


def _add_notes(target: Path) -> None:
    for directory in (target / "press", target / "docs" / "press"):
        directory.mkdir(parents=True)
        (directory / "notes.md").write_text("press build notes\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "add ordinary press directories")


@pytest.mark.parametrize("dry_run", [True, False])
def test_existing_root_notice_explains_reuse_and_preserves_ordinary_content(
    src_target: Path, tmp_path: Path, capsys, dry_run: bool
) -> None:
    _add_notes(src_target)
    before = {
        path.relative_to(src_target): path.read_bytes()
        for path in src_target.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(src_target).parts
    }
    args = [
        "--target",
        str(src_target),
        "--config",
        str(write_answers(tmp_path)),
        "--accept-discovery",
    ]
    if dry_run:
        args.append("--dry-run")

    assert main(args) == 0
    captured = capsys.readouterr()
    action = "would" if dry_run else "will"
    assert f"existing press/ {action} also hold" in captured.err
    assert "Template Press configuration and receipts" in captured.err
    assert "other files remain subject to rewriting and leak scanning" in captured.err
    assert "  docs/press\n" in captured.err
    assert "  press\n" not in captured.err
    assert f"existing press/ {action} also hold" not in captured.out
    assert "NOT this tool's control dir" not in captured.out
    if dry_run:
        after = {
            path.relative_to(src_target): path.read_bytes()
            for path in src_target.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(src_target).parts
        }
        assert after == before
        assert "would write press/press-source.toml from discovery" in captured.out
    else:
        assert (src_target / "press" / "notes.md").read_text() == "potato build notes\n"
        assert (src_target / "docs" / "potato" / "notes.md").is_file()
        assert (src_target / "press" / "press-source.toml").is_file()
        assert (src_target / "press" / "press-receipt.toml").is_file()


@pytest.mark.parametrize("root_has_marker", [True, False])
def test_plan_directory_advice_reuses_its_validated_snapshot(
    src_target: Path, monkeypatch, root_has_marker: bool
) -> None:
    _add_notes(src_target)
    if root_has_marker:
        (src_target / "press" / "press-source.toml").write_text(
            render_source_config(SOURCE), encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-qm", "add control marker")
    capture = engine.capture_surface_snapshot
    captures = []

    def record_capture(target: Path):
        snapshot = capture(target)
        captures.append(snapshot)
        return snapshot

    monkeypatch.setattr(engine, "capture_surface_snapshot", record_capture)
    plan = engine.build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert plan.stray_press_dirs == (
        ["docs/press"] if root_has_marker else ["docs/press", "press"]
    )
    assert len(captures) == 1


def test_new_plan_refreshes_directory_advice(src_target: Path) -> None:
    before = engine.build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    _add_notes(src_target)
    after = engine.build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert before.stray_press_dirs == []
    assert after.stray_press_dirs == ["docs/press", "press"]
