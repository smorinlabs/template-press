"""P05-TS05 — the reset apply pass.

D5: reset runs FIRST (position zero, source coordinates — declared paths
are consumed before the rename pass moves anything). The write goes through
safe_write (atomic temp+rename = new inode, so an external hardlink keeps
the pre-reset content) and preserves the target's original file mode
(thread 3653398581 — mkstemp's 0600 must not replace a 0644 changelog).
Every reset is recorded in ApplyReport.reset and the receipt's counts
table; a failed reset aborts the press with no receipt (D4 — not an
atomicity guarantee; git is the undo).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.reset import apply_resets
from template_press.rebrand.rules import ResetRule
from template_press.rebrand.safety import SafetyError

from .conftest import DEST, SOURCE, requires_symlink, write_answers_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


class TestApplyResets:
    def test_stub_written_verbatim_and_recorded(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "CHANGELOG.md").write_text("## v1\n## v2\n", encoding="utf-8")
        rule = ResetRule(file="CHANGELOG.md", stub="# Changelog\n")
        done = apply_resets(target, [(rule, "# Changelog\n")])
        assert done == ["CHANGELOG.md"]
        assert (target / "CHANGELOG.md").read_text(encoding="utf-8") == (
            "# Changelog\n"
        )

    def test_original_mode_preserved(self, tmp_path: Path):
        """Thread 3653398581: safe_write's fresh inode starts from mkstemp's
        0600 — the target's original permission bits must be restored."""
        target = tmp_path / "target"
        target.mkdir()
        changelog = target / "CHANGELOG.md"
        changelog.write_text("## v1\n", encoding="utf-8")
        changelog.chmod(0o640)
        rule = ResetRule(file="CHANGELOG.md", stub="# C\n")
        apply_resets(target, [(rule, "# C\n")])
        assert stat.S_IMODE(os.stat(changelog).st_mode) == 0o640

    def test_external_hardlink_keeps_old_content(self, tmp_path: Path):
        """safe_write's atomic temp+rename creates a NEW inode — an external
        hardlink must keep the pre-reset content, never be blanked through."""
        target = tmp_path / "target"
        target.mkdir()
        changelog = target / "CHANGELOG.md"
        changelog.write_text("## v1 history\n", encoding="utf-8")
        outside = tmp_path / "outside-link"
        os.link(changelog, outside)
        rule = ResetRule(file="CHANGELOG.md", stub="# C\n")
        apply_resets(target, [(rule, "# C\n")])
        assert changelog.read_text(encoding="utf-8") == "# C\n"
        assert outside.read_text(encoding="utf-8") == "## v1 history\n"

    @requires_symlink
    def test_symlink_target_aborts_nothing_written_through(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "real.md").write_text("## v1\n", encoding="utf-8")
        os.symlink("real.md", target / "CHANGELOG.md")
        rule = ResetRule(file="CHANGELOG.md", stub="# C\n")
        with pytest.raises(SafetyError):
            apply_resets(target, [(rule, "# C\n")])
        assert (target / "real.md").read_text(encoding="utf-8") == "## v1\n"

    @requires_symlink
    def test_symlinked_ancestor_aborts(self, tmp_path: Path):
        outside = tmp_path / "outside-docs"
        outside.mkdir()
        (outside / "HISTORY.md").write_text("## v1\n", encoding="utf-8")
        target = tmp_path / "target"
        target.mkdir()
        os.symlink(outside, target / "docs")
        rule = ResetRule(file="docs/HISTORY.md", stub="# H\n")
        with pytest.raises(SafetyError):
            apply_resets(target, [(rule, "# H\n")])
        assert (outside / "HISTORY.md").read_text(encoding="utf-8") == "## v1\n"


class TestPressIntegration:
    def _setup(self, src_target: Path) -> None:
        history = src_target / "src" / "demo_widget" / "HISTORY.md"
        history.write_text(
            "demo_widget release history for demolabs\n", encoding="utf-8"
        )
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            '[rules]\nextra_exclude_files = ["src/demo_widget/HISTORY.md"]\n'
            '[[reset]]\nfile = "src/demo_widget/HISTORY.md"\nstub = "# History\\n"\n',
            encoding="utf-8",
        )
        (src_target / "press" / "press-source.toml").write_text(
            render_source_config(SOURCE), encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare reset")

    def test_reset_runs_first_in_source_coordinates(
        self, src_target: Path, tmp_path: Path
    ):
        """The stub is written at the DECLARED source path and then travels
        with the rename pass — reset after renames would recreate the stale
        source path instead."""
        self._setup(src_target)
        answers = write_answers_file(tmp_path, DEST)
        code = main(["--target", str(src_target), "--config", str(answers)])
        assert code == 0
        moved = src_target / "src" / "potato_launcher" / "HISTORY.md"
        assert moved.read_text(encoding="utf-8") == "# History\n"
        assert not (src_target / "src" / "demo_widget").exists()

    def test_receipt_records_reset_count(self, src_target: Path, tmp_path: Path):
        self._setup(src_target)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        receipt = (src_target / RECEIPT_REL).read_text(encoding="utf-8")
        assert "reset = 1" in receipt

    def test_failed_reset_aborts_press_no_receipt(
        self, src_target: Path, tmp_path: Path, monkeypatch, capsys
    ):
        from template_press.rebrand import cli as cli_mod

        self._setup(src_target)

        def boom(*_args, **_kwargs):
            raise OSError("reset write failed")

        monkeypatch.setattr(cli_mod, "apply_resets", boom)
        answers = write_answers_file(tmp_path, DEST)
        code = main(["--target", str(src_target), "--config", str(answers)])
        assert code == 1
        assert "PARTIALLY" in capsys.readouterr().err
        assert not (src_target / RECEIPT_REL).exists()
