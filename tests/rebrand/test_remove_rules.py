"""P08-T02/TS02/TS03 — [[remove]] schema, guards, apply, and verify modeling.

Issue #80: blueprint-only files (maintenance CI, dogfood history) must not
ship to pressed forks. A declared removal is their neutralization. It
executes AFTER apply() with the declared path translated through the
rename report (the regeneration pattern — apply() revalidates the tree
against its plan-time snapshot, so deleting before it would break the
mutation boundary), and hermetic verify APPLIES removals in the sandbox —
no command needed — so removed files vanish from the scan with no
exemption and no coverage gap.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.regen import preflight_excluded_files
from template_press.rebrand.remove import (
    preflight_remove_targets,
    render_remove_plan,
)
from template_press.rebrand.rules import RemoveRule, load_rules, load_selected_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, write_answers_file
from .test_verify_cli import _commit, make_pressable

REMOVE_NOTES = (
    "[[remove]]\n"
    'file = "docs/legacy-notes.md"\n'
    'reason = "maintenance history is blueprint-only; forks must not inherit it"\n'
)


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Schema — shape, types, and config-load validation
# ---------------------------------------------------------------------------
class TestRemoveSchema:
    def test_valid_remove_parses(self, tmp_path: Path):
        target = _write_rules(tmp_path, REMOVE_NOTES)
        (rule,) = load_rules(target).remove
        assert isinstance(rule, RemoveRule)
        assert rule.file == "docs/legacy-notes.md"
        assert "blueprint-only" in rule.reason

    def test_reason_is_required(self, tmp_path: Path):
        target = _write_rules(tmp_path, '[[remove]]\nfile = "docs/legacy-notes.md"\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_empty_reason_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path, '[[remove]]\nfile = "docs/legacy-notes.md"\nreason = "  "\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_key_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = "a.md"\nreason = "r"\nrecursive = true\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_control_file_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = "press/press-source.toml"\nreason = "nope"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_control_file_rejected_case_insensitive(self, tmp_path: Path):
        """Issue #86: on a case-insensitive filesystem (Windows, default
        macOS), `PRESS/press-source.toml` is the SAME file as the control
        path — the reserved check must not be exact-case only."""
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = "PRESS/press-source.toml"\nreason = "nope"\n',
        )
        with pytest.raises(ValidationError, match="control"):
            load_rules(target)

    @pytest.mark.parametrize(
        "alias",
        [
            "press/press-source.toml.",
            "press/press-source.toml ",
            "press./press-source.toml",
        ],
    )
    def test_control_file_rejected_windows_trailing_alias(
        self, tmp_path: Path, alias: str
    ):
        """Windows drops trailing dots/spaces from every path component, so
        each of these declarations names the press-owned control file exactly
        like the plain lowercase form."""
        target = _write_rules(
            tmp_path,
            f'[[remove]]\nfile = "{alias}"\nreason = "nope"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_overlap_with_reset_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n'
            '[[remove]]\nfile = "CHANGELOG.md"\nreason = "r"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_platform_disjoint_remove_selected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = "a.md"\nreason = "r"\nplatforms = ["win32"]\n',
        )
        assert load_selected_rules(target, platform="darwin").rules.remove == ()
        (rule,) = load_selected_rules(target, platform="win32").rules.remove
        assert rule.file == "a.md"


# ---------------------------------------------------------------------------
# Plan-time preflight — stale config is drift, guards are the named set
# ---------------------------------------------------------------------------
class TestRemovePreflight:
    def test_missing_target_is_a_problem(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        _commit(repo)
        problems = preflight_remove_targets(repo, load_rules(repo))
        assert any("docs/legacy-notes.md" in p for p in problems)

    def test_untracked_target_is_a_problem(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        _commit(repo)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        problems = preflight_remove_targets(repo, load_rules(repo))
        assert any("not git-tracked" in p for p in problems)

    def test_tracked_clean_target_passes_and_renders(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        rules = load_rules(repo)
        assert preflight_remove_targets(repo, rules) == []
        plan = render_remove_plan(rules)
        assert "docs/legacy-notes.md" in plan
        assert "blueprint-only" in plan


# ---------------------------------------------------------------------------
# Apply — post-apply removal, report, receipt, dry-run untouched
# ---------------------------------------------------------------------------
class TestRemoveApply:
    def _repo(self, tmp_path: Path) -> Path:
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        return repo

    def test_dry_run_shows_plan_and_deletes_nothing(self, tmp_path: Path, capsys):
        repo = self._repo(tmp_path)
        answers = write_answers_file(tmp_path, DEST)
        code = main(["--target", str(repo), "--config", str(answers), "--dry-run"])
        assert code == 0
        out = capsys.readouterr().out
        assert "docs/legacy-notes.md" in out
        assert (repo / "docs" / "legacy-notes.md").is_file()

    def test_apply_removes_file_and_records_receipt(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        answers = write_answers_file(tmp_path, DEST)
        code = main(["--target", str(repo), "--config", str(answers)])
        assert code == 0
        assert not (repo / "docs" / "legacy-notes.md").exists()
        receipt = (repo / RECEIPT_REL).read_text(encoding="utf-8")
        assert "docs/legacy-notes.md" in receipt

    def test_stale_remove_refuses_the_press(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)  # declared but target never created
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        code = main(["--target", str(repo), "--config", str(answers)])
        assert code == 2
        assert not (repo / RECEIPT_REL).exists()


# ---------------------------------------------------------------------------
# Verify — removal modeled hermetically; §6 accepts it as neutralization
# ---------------------------------------------------------------------------
class TestRemoveVerify:
    def test_removed_excluded_file_verifies_clean(self, tmp_path: Path):
        """An EXCLUDED identity-bearing file is never rewritten; with only a
        [[remove]] declared, verify must model the removal (delete it in the
        sandbox) or the file leaks."""
        repo = make_pressable(tmp_path)
        _write_rules(
            repo,
            '[rules]\nextra_exclude_files = ["docs/legacy-notes.md"]\n' + REMOVE_NOTES,
        )
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 0

    def test_excluded_file_gate_accepts_removal(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        _write_rules(
            repo,
            '[rules]\nextra_exclude_files = ["docs/legacy-notes.md"]\n' + REMOVE_NOTES,
        )
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        assert preflight_excluded_files(repo, load_rules(repo)) == []


# ---------------------------------------------------------------------------
# Re-press, stale-verify, regen conflict, reason hygiene (PR #85 review)
# ---------------------------------------------------------------------------
class TestRemoveLifecycle:
    def test_forced_re_press_after_removal_succeeds(self, tmp_path: Path):
        """A removal deletes its own precondition; the prior receipt's
        [[press.remove]] record must satisfy the next press's preflight."""
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers)]) == 0
        _commit(repo)
        # Re-point origin to the pressed identity — discovery cross-checks
        # the source-config against the remote, exactly as a real fork must.
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(repo),
                "remote",
                "set-url",
                "origin",
                f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
            ],
            check=True,
            capture_output=True,
        )
        second = dataclasses.replace(
            DEST,
            package_name="carrot_launcher",
            repo_name="carrot-launcher",
            app_name="carrot",
            author="Carrot Author",
            email="hello@carrot.example",
            owner="carrotlabs",
        )
        answers2 = tmp_path / "answers2.toml"
        answers2.write_text(
            "[answers]\n"
            + "\n".join(f'{k} = "{v}"' for k, v in second.as_dict_prompted().items())
            + "\n",
            encoding="utf-8",
        )
        assert main(["--target", str(repo), "--config", str(answers2), "--force"]) == 0

    def test_verify_fails_loud_on_stale_removal(self, tmp_path: Path):
        """No receipt record + missing target = config drift; verify must
        refuse (exit 2), never silently scan clean."""
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)  # target never created
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 2

    def test_remove_regen_argv_conflict_refused(self, tmp_path: Path):
        repo = make_pressable(tmp_path)
        script = repo / "scripts" / "regen.sh"
        script.parent.mkdir(exist_ok=True)
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        _write_rules(
            repo,
            "[rules]\n"
            'extra_exclude_files = ["uv.lock"]\n'
            "[[regenerate]]\n"
            'file = "uv.lock"\n'
            'command = ["scripts/regen.sh"]\n'
            "[[remove]]\n"
            'file = "scripts/regen.sh"\n'
            'reason = "maintenance script"\n',
        )
        (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers)]) == 2

    def test_control_characters_in_remove_reason_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = "a.md"\nreason = "line\\u001b[31mforged"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestRemoveReceiptChain:
    def test_receipt_records_source_coordinates(self, tmp_path: Path):
        """[[press.remove]] records the DECLARED path (like
        [[press.regenerate]]) — the coordinate re-press and verify compare,
        since press-rules.toml is never rewritten."""
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers)]) == 0
        from template_press.rebrand.receipt import removed_files_from_receipt

        recorded = removed_files_from_receipt(
            (repo / RECEIPT_REL).read_text(encoding="utf-8")
        )
        assert set(recorded) == {"docs/legacy-notes.md"}
        assert "blueprint-only" in recorded["docs/legacy-notes.md"]

    def test_tampered_receipt_press_value_is_tolerated(self):
        from template_press.rebrand.receipt import removed_files_from_receipt

        assert removed_files_from_receipt('press = "legacy"\n') == {}

    def test_stub_file_remove_overlap_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            "[[reset]]\n"
            'file = "CHANGELOG.md"\n'
            'stub_file = "press/stubs/CHANGELOG.md"\n'
            "[[remove]]\n"
            'file = "press/stubs/CHANGELOG.md"\n'
            'reason = "r"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_foreign_platform_records_carry_forward(self, tmp_path: Path):
        """A prior receipt entry with no active declaration on this platform
        must survive into the replacement receipt."""
        repo = make_pressable(tmp_path)
        _write_rules(repo, REMOVE_NOTES)
        notes = repo / "docs" / "legacy-notes.md"
        notes.parent.mkdir(exist_ok=True)
        notes.write_text("# demo_widget maintenance\n", encoding="utf-8")
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers)]) == 0
        # Inject a foreign-platform record into the receipt, as if another
        # OS's press had satisfied its own removal.
        receipt_path = repo / RECEIPT_REL
        receipt_path.write_text(
            receipt_path.read_text(encoding="utf-8")
            + '\n[[press.remove]]\nfile = "scripts/win-only.ps1"\n'
            'reason = "windows maintenance script"\n',
            encoding="utf-8",
        )
        _commit(repo)
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(repo),
                "remote",
                "set-url",
                "origin",
                f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
            ],
            check=True,
            capture_output=True,
        )
        second = dataclasses.replace(
            DEST,
            package_name="carrot_launcher",
            repo_name="carrot-launcher",
            app_name="carrot",
            author="Carrot Author",
            email="hello@carrot.example",
            owner="carrotlabs",
        )
        answers2 = tmp_path / "answers2.toml"
        answers2.write_text(
            "[answers]\n"
            + "\n".join(f'{k} = "{v}"' for k, v in second.as_dict_prompted().items())
            + "\n",
            encoding="utf-8",
        )
        assert main(["--target", str(repo), "--config", str(answers2), "--force"]) == 0
        from template_press.rebrand.receipt import removed_files_from_receipt

        recorded = removed_files_from_receipt(receipt_path.read_text(encoding="utf-8"))
        assert "scripts/win-only.ps1" in recorded
        assert recorded["scripts/win-only.ps1"] == "windows maintenance script"

    def test_gitignore_removal_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[remove]]\nfile = ".gitignore"\nreason = "r"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)
