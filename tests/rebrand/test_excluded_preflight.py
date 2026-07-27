"""P04-TS11 — the §6 excluded-file contract preflight + the overlap ban.

D5: with the hidden regeneration default removed, an excluded file with no
declared neutralization is never rebuilt AND never scanned — source
identity would survive under a clean receipt. The preflight refuses the
press (exit 2) for any tracked excluded file that is neither regenerated,
reset, nor verify_ignore'd, naming the file and the three fixes. And a
file may not be BOTH a regeneration output and a reset target (P04 D1):
reset runs first, regeneration after apply — the stub would be written and
immediately overwritten, both counted successful. Rejected at config load.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.regen import preflight_excluded_files
from template_press.rebrand.rules import load_rules

from .conftest import DEST, SOURCE, write_answers_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


class TestOverlapBan:
    def test_file_in_both_mechanisms_rejected_at_config_load(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[regenerate]]\nfile = "CHANGELOG.md"\ncommand = ["gen-log"]\n'
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# C\\n"\n',
        )
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        msg = str(exc.value)
        assert "CHANGELOG.md" in msg
        assert "regenerate" in msg and "reset" in msg


class TestPreflightUnit:
    def test_undeclared_tracked_excluded_file_flagged(self, src_target: Path):
        (src_target / "CHANGELOG.md").write_text("## v1\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "add changelog")
        problems = preflight_excluded_files(src_target, load_rules(src_target))
        (problem,) = problems
        assert "CHANGELOG.md" in problem
        # the three fixes, all named
        assert "[[regenerate]]" in problem
        assert "[[reset]]" in problem
        assert "verify_ignore" in problem

    def test_untracked_excluded_file_not_flagged(self, src_target: Path):
        (src_target / "CHANGELOG.md").write_text("## v1\n", encoding="utf-8")
        problems = preflight_excluded_files(src_target, load_rules(src_target))
        assert problems == []

    def test_declared_regeneration_satisfies_the_contract(self, src_target: Path):
        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        _write_rules(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["bun", "install"]\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")
        problems = preflight_excluded_files(src_target, load_rules(src_target))
        assert problems == []

    def test_declared_reset_satisfies_the_contract(self, src_target: Path):
        (src_target / "CHANGELOG.md").write_text("## v1\n", encoding="utf-8")
        _write_rules(
            src_target,
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")
        problems = preflight_excluded_files(src_target, load_rules(src_target))
        assert problems == []

    def test_verify_ignore_satisfies_the_contract(self, src_target: Path):
        (src_target / "CHANGELOG.md").write_text("## v1\n", encoding="utf-8")
        _write_rules(
            src_target,
            '[rules]\nverify_ignore = ["CHANGELOG.md"]\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare")
        problems = preflight_excluded_files(src_target, load_rules(src_target))
        assert problems == []


class TestCliGate:
    def _setup(self, src_target: Path) -> None:
        (src_target / "CHANGELOG.md").write_text(
            "## demo_widget history\n", encoding="utf-8"
        )
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-source.toml").write_text(
            render_source_config(SOURCE), encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "changelog + source config")

    def test_undeclared_excluded_file_exits_2_nothing_written(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        self._setup(src_target)
        answers = write_answers_file(tmp_path, DEST)
        before = snapshot_target(src_target)
        code = main(["--target", str(src_target), "--config", str(answers)])
        assert code == 2
        err = capsys.readouterr().err
        assert "CHANGELOG.md" in err
        assert snapshot_target(src_target) == before

    def test_dry_run_also_gated(self, src_target: Path, tmp_path: Path):
        self._setup(src_target)
        answers = write_answers_file(tmp_path, DEST)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        assert code == 2

    def test_declared_reset_unblocks_the_press(self, src_target: Path, tmp_path: Path):
        self._setup(src_target)
        (src_target / "press" / "press-rules.toml").write_text(
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n',
            encoding="utf-8",
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "declare reset")
        answers = write_answers_file(tmp_path, DEST)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        assert code == 0
