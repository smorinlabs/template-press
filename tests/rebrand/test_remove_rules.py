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
import json
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.regen import preflight_excluded_files
from template_press.rebrand.remove import (
    preflight_remove_targets,
    remove_command_conflicts,
    render_remove_plan,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    EditRule,
    RegenerateRule,
    RemoveRule,
    load_rules,
    load_selected_rules,
)
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, SOURCE, _git, write_answers_file
from .test_cli import write_answers, write_source_config
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
@pytest.mark.parametrize("kind", ["edit", "regenerate"])
@pytest.mark.parametrize(
    "element",
    [
        "src/old/café.py",
        "src/final/café.py",
        "./src/final/café.py",
        "src\\final\\café.py",
        "src/final/unused/../café.py",
        "SRC/FINAL./CAFÉ.PY ",
    ],
)
def test_remove_argv_conflict_uses_both_path_coordinates_and_aliases(kind, element):
    command = ("python", element)
    rules = dataclasses.replace(
        DEFAULT_RULES,
        remove=(RemoveRule(file="src/old/café.py", reason="maintenance"),),
        edit=(EditRule(file="meta.toml", command=command, expect="x", env=()),)
        if kind == "edit"
        else (),
        regenerate=(RegenerateRule(file="uv.lock", command=command),)
        if kind == "regenerate"
        else (),
    )
    problems = remove_command_conflicts(
        rules, {"src/old": "src/intermediate", "src/intermediate": "src/final"}
    )
    assert len(problems) == 1
    assert f"[[{kind}]] command" in problems[0]
    assert repr(element) in problems[0]
    assert repr("src/old/café.py") in problems[0]


def test_remove_argv_conflict_does_not_match_path_substrings():
    rules = dataclasses.replace(
        DEFAULT_RULES,
        remove=(RemoveRule(file="scripts/edit.py", reason="maintenance"),),
        edit=(
            EditRule(
                file="meta.toml",
                command=("python", "scripts/edit.py.bak"),
                expect="x",
                env=(),
            ),
        ),
    )
    assert remove_command_conflicts(rules, {}) == []
    assert remove_command_conflicts(dataclasses.replace(rules, remove=()), {}) == []


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

    def test_remove_edit_argv_conflict_refused_before_dry_run_plan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        repo = make_pressable(tmp_path)
        script = repo / "scripts" / "edit.py"
        script.parent.mkdir(exist_ok=True)
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        command = json.dumps([sys.executable, "scripts/edit.py"])
        _write_rules(
            repo,
            "[[edit]]\n"
            'file = "pyproject.toml"\n'
            f"command = {command}\n"
            "expect = 'version = \"0.1.0\"'\n"
            "[[remove]]\n"
            'file = "scripts/edit.py"\n'
            'reason = "maintenance script"\n',
        )
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)

        assert (
            main(
                [
                    "--target",
                    str(repo),
                    "--config",
                    str(answers),
                    "--dry-run",
                ]
            )
            == 2
        )
        err = capsys.readouterr().err
        assert "remove target 'scripts/edit.py'" in err
        assert "[[edit]] command" in err
        assert script.is_file()
        assert not (repo / RECEIPT_REL).exists()

    @pytest.mark.parametrize("kind", ["edit", "regenerate"])
    @pytest.mark.parametrize("flags", [("--dry-run",), ()], ids=["preview", "apply"])
    def test_remove_command_at_renamed_path_refused_before_mutation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind, flags
    ):
        repo = make_pressable(tmp_path)
        script = repo / "src/demo_widget/maintenance.py"
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        command_path = "src/potato_launcher/maintenance.py"
        command = json.dumps([sys.executable, command_path])
        declaration = (
            f'[[edit]]\nfile = "pyproject.toml"\ncommand = {command}\n'
            "expect = 'version = \"0.1.0\"'\n"
            if kind == "edit"
            else f'[[regenerate]]\nfile = "uv.lock"\ncommand = {command}\n'
        )
        if kind == "regenerate":
            (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
        _write_rules(
            repo,
            declaration
            + '[[remove]]\nfile = "src/demo_widget/maintenance.py"\n'
            + 'reason = "maintenance script"\n',
        )
        _commit(repo)
        before = (repo / "pyproject.toml").read_bytes()
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers), *flags]) == 2
        err = capsys.readouterr().err
        assert f"[[{kind}]] command" in err
        assert command_path in err
        assert script.is_file()
        assert (repo / "pyproject.toml").read_bytes() == before
        assert not (repo / RECEIPT_REL).exists()

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


# ---------------------------------------------------------------------------
# E5(a)/(b) — declared-removal coverage warning and plan removal counts
# ---------------------------------------------------------------------------
class TestRemovalCoverageWarning:
    def test_plan_warns_when_a_rewritten_directory_has_no_removal(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        hist = src_target / "projects"
        hist.mkdir()
        (hist / "P01.md").write_text("demo_widget history\n", encoding="utf-8")
        (hist / "P02.md").write_text("more demo_widget\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "hist")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning: 2 tracked files under projects/ will be rewritten" in out
        assert "declare [[remove]] or [rules] verify_ignore" in out

    def test_no_warning_when_directory_is_declared_removed(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        hist = src_target / "projects"
        hist.mkdir()
        (hist / "P01.md").write_text("demo_widget history\n", encoding="utf-8")
        (hist / "P02.md").write_text("more demo_widget\n", encoding="utf-8")
        _write_rules(
            src_target,
            '[[remove]]\nfile = "projects/P01.md"\nreason = "hist"\n'
            '[[remove]]\nfile = "projects/P02.md"\nreason = "hist"\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "hist")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out
        assert "removing 2 files under projects/" in out  # (b)

    def test_no_warning_on_plain_src_target(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """A plain fixture with no undeclared, fully-rewritten directory
        (the src/ package itself is excluded per the heuristic) must stay
        silent — the warning is for surprising template history, not for
        every press."""
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out

    def test_no_warning_when_directory_name_in_verify_ignore(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        hist = src_target / "vendor"
        hist.mkdir()
        (hist / "NOTES.md").write_text("demo_widget vendor notes\n", encoding="utf-8")
        (hist / "MORE.md").write_text("more demo_widget notes\n", encoding="utf-8")
        _write_rules(src_target, '[rules]\nverify_ignore = ["vendor"]\n')
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "vendor")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out

    def test_no_warning_when_a_reset_rule_targets_the_directory(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """A [[reset]] (not [[remove]]) declared under the directory is
        also a human decision about it — suppresses the warning.

        The directory is the same rename-covered shape as
        ``test_plan_warns_on_rename_only_directory_with_no_content_hits``
        (its name embeds the source package_name, so it renames as a unit
        and every file under it counts as a rewrite candidate via the
        path, independent of content) — that keeps full coverage true even
        though the declared reset target is excluded from the content
        pass, isolating the [[reset]]-declares-the-directory suppression
        from requirement (4)'s own content-coverage check."""
        hist = src_target / "legacy_demo_widget_notes"
        hist.mkdir()
        (hist / "a.md").write_text("nothing identity-related here\n", encoding="utf-8")
        (hist / "b.md").write_text("plain unrelated text\n", encoding="utf-8")
        _write_rules(
            src_target,
            '[rules]\nextra_exclude_files = ["legacy_demo_widget_notes/a.md"]\n'
            '[[reset]]\nfile = "legacy_demo_widget_notes/a.md"\nstub = "stub\\n"\n',
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "legacy notes")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out

    def test_plan_warns_on_rename_only_directory_with_no_content_hits(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Item 1 fix: a directory whose top-level name itself embeds the
        source package_name gets renamed as a whole unit, so every tracked
        file under it is a rewrite candidate even though none of them
        contain the identity in their CONTENT — a path-only rewrite must
        still count."""
        hist = src_target / "legacy_demo_widget_notes"
        hist.mkdir()
        (hist / "a.md").write_text("nothing identity-related here\n", encoding="utf-8")
        (hist / "b.md").write_text("plain unrelated text\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "legacy notes")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: 2 tracked files under legacy_demo_widget_notes/ "
            "will be rewritten" in out
        )

    def test_no_warning_on_flat_layout_package_directory(
        self, flat_target: Path, tmp_path: Path, capsys
    ):
        """The flat-layout package root (named after source.package_name)
        is excluded the same way src/ is for a src-layout target."""
        write_source_config(flat_target)
        code = main(
            [
                "--target",
                str(flat_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out

    def test_directory_with_init_py_but_wrong_name_still_warns(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Round 2 discriminating test: item 3 dropped the __init__.py
        proxy for "the package directory" in favor of comparing the
        directory's name against source.package_name directly. A top-level
        directory that happens to hold an __init__.py but is NOT named
        after the source package must still warn when fully rewritten —
        the old __init__.py-based heuristic would have wrongly suppressed
        this one."""
        extra = src_target / "extra_pkg"
        extra.mkdir()
        (extra / "__init__.py").write_text(
            '"""demo_widget extra."""\n', encoding="utf-8"
        )
        (extra / "notes.md").write_text("demo_widget notes\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "extra pkg-shaped dir")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning: 2 tracked files under extra_pkg/ will be rewritten" in out

    def test_no_warning_on_pep420_style_package_dir_without_init_py(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Round 2 discriminating test: the flat-layout package exclusion
        must key on source.package_name alone, not on __init__.py presence
        — a PEP 420 namespace package (no __init__.py at all) named after
        the source package must still be silent. This top-level
        "demo_widget" directory is separate from src_target's existing
        src/demo_widget/ (src-layout); it exists only to isolate the
        name-based exclusion from the __init__.py-based one."""
        pkg = src_target / "demo_widget"
        pkg.mkdir()
        (pkg / "plugin.py").write_text("demo_widget plugin\n", encoding="utf-8")
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "pep420-style pkg dir")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "warning:" not in out


# ---------------------------------------------------------------------------
# E9(b) — prefix-only occurrence warning
# ---------------------------------------------------------------------------
class TestPrefixOnlyWarning:
    def test_plan_warns_when_source_value_occurs_only_as_prefix(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        for rel in ("README.md", "pyproject.toml"):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
                encoding="utf-8",
            )
        _git(src_target, "commit", "-qam", "renamed upstream")
        write_source_config(src_target)  # still declares repo_name = demo-widget
        _git(src_target, "remote", "remove", "origin")  # guard skips owner/repo_name
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: repo_name 'demo-widget' occurs only as a prefix of "
            "'demo-widget-2'" in out
        )
        assert "update press/press-source.toml" in out

    def test_places_count_sums_every_prefix_token_not_just_the_named_one(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """[Greptile fix] `(N places)` must count every prefix-token
        occurrence across the WHOLE corpus, not just the occurrences of the
        one example token named in the message. Two distinct longer tokens
        stand in for `demo-widget` here — 2x `demo-widget-api`, 3x
        `demo-widget-cli` — so `places` must be 5 (the sum), while the named
        example token stays the most-common one, `demo-widget-cli`."""
        readme = src_target / "README.md"
        text = readme.read_text(encoding="utf-8")
        text = text.replace("# demo-widget", "# demo-widget-api", 1)
        text = text.replace(
            "https://github.com/demolabs/demo-widget",
            "https://github.com/demolabs/demo-widget-cli",
            1,
        )
        text += (
            "\nSee also demo-widget-cli quickstart and demo-widget-cli docs, "
            "and demo-widget-api reference.\n"
        )
        readme.write_text(text, encoding="utf-8")
        _git(src_target, "commit", "-qam", "renamed upstream, two ways")
        write_source_config(src_target)  # still declares repo_name = demo-widget
        _git(src_target, "remote", "remove", "origin")  # guard skips owner/repo_name
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: repo_name 'demo-widget' occurs only as a prefix of "
            "'demo-widget-cli' (5 places)" in out
        )

    def test_untracked_whole_token_occurrence_does_not_suppress_warning(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """[Codex fix] The prefix tally must only count TRACKED content —
        `select_content_rewrite_entries` also walks non-ignored UNTRACKED
        files, and an untracked scratch file containing the whole token
        would otherwise silently suppress a genuine prefix-only warning
        that the tracked corpus (`demo-widget-2` only) actually earns."""
        for rel in ("README.md", "pyproject.toml"):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
                encoding="utf-8",
            )
        _git(src_target, "commit", "-qam", "renamed upstream")
        write_source_config(src_target)  # still declares repo_name = demo-widget
        # AFTER write_source_config's own `git add -A` + commit, so this
        # scratch file stays genuinely UNTRACKED (writing it any earlier
        # would sweep it into that commit and defeat the test).
        (src_target / "scratch.md").write_text(
            "an untracked mention of demo-widget, whole token\n", encoding="utf-8"
        )
        _git(src_target, "remote", "remove", "origin")  # guard skips owner/repo_name
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
                "--allow-dirty",  # the untracked scratch file is the point
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: repo_name 'demo-widget' occurs only as a prefix of "
            "'demo-widget-2'" in out
        )

    def test_untracked_prefix_only_file_does_not_create_a_warning(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """[Codex fix] An untracked prefix-only mention must not, on its own,
        manufacture a warning — with zero TRACKED occurrences of repo_name
        at all, excluding the untracked entry from the tally leaves
        `prefix_tokens` empty too, so `prefix_only_warnings` stays silent
        (it requires a nonempty `prefix_tokens`, not just an absent whole)."""
        readme = src_target / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("demo-widget", "widget-only"),
            encoding="utf-8",
        )
        _git(src_target, "commit", "-qam", "drop the tracked repo_name mention")
        write_source_config(src_target)  # still declares repo_name = demo-widget
        # AFTER write_source_config's own `git add -A` + commit, so this
        # scratch file stays genuinely UNTRACKED (writing it any earlier
        # would sweep it into that commit and defeat the test).
        (src_target / "scratch.md").write_text(
            "an untracked mention of demo-widget-untracked, prefix only\n",
            encoding="utf-8",
        )
        _git(src_target, "remote", "remove", "origin")  # guard skips owner/repo_name
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
                "--allow-dirty",  # the untracked scratch file is the point
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_no_prefix_warning_on_plain_src_target(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Plain fixture: repo_name/package_name/etc. occur as whole tokens
        (``# demo-widget``, ``name = "demo_widget"``) — no prefix-only
        signal."""
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_no_warning_when_both_whole_and_prefix_forms_exist(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Compound forms are a deliberate, rewritable naming convention
        (spec E9's hyphen-boundary decision) — a plain whole-token
        occurrence anywhere in the corpus suppresses the warning even when
        a compound form (``demo-widget-web``) also exists."""
        readme = src_target / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8")
            + "\nSee also demo-widget-web for the browser build.\n",
            encoding="utf-8",
        )
        _git(src_target, "commit", "-qam", "add compound-form mention")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    # -----------------------------------------------------------------
    # Fix round 1: `.` is not a rename continuation; display forms are
    # checked; real-apply and --diagnostics-json coverage.
    # -----------------------------------------------------------------

    def test_no_warning_when_only_mention_is_a_dot_extension(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """A dot right after the value is an extension/domain suffix
        (``demo-widget.git``), not a rename continuation — spec E9(b) fix
        round 1. The target's ONLY repo_name mention is the `.git` URL."""
        (src_target / "README.md").write_text(
            "See https://github.com/demolabs/demo-widget.git for source.\n",
            encoding="utf-8",
        )
        _git(src_target, "commit", "-qam", "only a .git mention")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_slash_after_value_is_a_whole_token_boundary(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Pin: a `/` right after the value was already correctly a
        whole-token boundary before the fix-round-1 `.` change, and stays
        one — `demo-widget/` is a path segment, not a rename suffix."""
        (src_target / "README.md").write_text(
            "Clone from demo-widget/releases for the latest build.\n",
            encoding="utf-8",
        )
        _git(src_target, "commit", "-qam", "only a trailing-slash mention")
        write_source_config(src_target)
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_hyphen_suffix_is_still_a_prefix_after_the_dot_fix(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Pin: `demo-widget-2` (hyphen + alphanumeric) is still classified
        prefix after excluding `.` from the continuation class — the P1 fix
        narrows the rule, it does not disable it."""
        for rel in ("README.md", "pyproject.toml"):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
                encoding="utf-8",
            )
        _git(src_target, "commit", "-qam", "renamed upstream")
        write_source_config(src_target)
        _git(src_target, "remote", "remove", "origin")
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: repo_name 'demo-widget' occurs only as a prefix of "
            "'demo-widget-2'" in out
        )

    def test_plan_warns_when_a_display_form_occurs_only_as_prefix(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """spec E9(b) fix round 1: a rendered display form (here,
        `display_name_spaced`) is exactly as checkable as a plain identity
        field — the same stale-rename shape can hide behind a spaced
        display name (``Demo Widget`` -> ``Demo Widget-2`` upstream) just
        as easily as behind a hyphenated repo_name."""
        (src_target / "NOTES.md").write_text(
            "See the Demo Widget-2 changelog for details.\n", encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "add notes mentioning the rename")
        src = Identity(**{**SOURCE.as_dict_prompted(), "display_name": "Demo Widget"})
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / SOURCE_CONFIG_REL).write_text(
            render_source_config(src), encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "add source config")
        dest = {**DEST.as_dict_prompted(), "display_name": "Potato Launcher"}
        answers = tmp_path / "answers.toml"
        answers.write_text(
            "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
            encoding="utf-8",
        )
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: display_name_spaced 'Demo Widget' occurs only as a "
            "prefix of 'Demo Widget-2'" in out
        )
        assert "update press/press-source.toml" in out

    def test_no_warning_on_display_form_when_whole_occurrence_also_exists(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """A plain whole-token mention of the spaced display name silences
        the warning even when a prefix form also exists — same rule as the
        hyphenated-value compound-form case."""
        (src_target / "NOTES.md").write_text(
            "Demo Widget is the project. See Demo Widget-2 for the fork.\n",
            encoding="utf-8",
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "add notes with both forms")
        src = Identity(**{**SOURCE.as_dict_prompted(), "display_name": "Demo Widget"})
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / SOURCE_CONFIG_REL).write_text(
            render_source_config(src), encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "add source config")
        dest = {**DEST.as_dict_prompted(), "display_name": "Potato Launcher"}
        answers = tmp_path / "answers.toml"
        answers.write_text(
            "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
            encoding="utf-8",
        )
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_prefix_warning_prints_on_real_apply_not_only_dry_run(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """The warning is not a `--dry-run`-only artifact: it prints on a
        real apply too, and does not change the (unchanged, success) exit
        code — it is advisory, per `Plan.prefix_warnings`'s own contract."""
        for rel in ("README.md", "pyproject.toml"):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
                encoding="utf-8",
            )
        _git(src_target, "commit", "-qam", "renamed upstream")
        write_source_config(src_target)
        _git(src_target, "remote", "remove", "origin")
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "warning: repo_name 'demo-widget' occurs only as a prefix of "
            "'demo-widget-2'" in out
        )
        assert (src_target / RECEIPT_REL).is_file()

    def test_substring_rewrite_field_is_excluded_from_prefix_check(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """[PR #109 review] A field listed in `[rules]
        substring_rewrite_fields` is rewritten by plain substring matching
        (`rewrite_with_row`), not `token_pattern`'s boundary-aware match — a
        glued occurrence (`xdemo_widgety`) is a real, correctly-rewritten
        whole occurrence to that rewriter but invisible to `token_pattern`
        (its own boundary lookbehind blocks a directly-attached alnum char
        on the left). Without excluding the field from this check, the
        tally would only see the corpus's lone `demo_widget_2` prefix-form
        occurrence and wrongly tell a correctly configured target to update
        `press-source.toml`."""
        pyproject = src_target / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        # Hyphenated form: discover()'s `raw_name.replace("-", "_")` still
        # resolves package_name to "demo_widget" (satisfying the source-
        # config cross-check), but the literal underscored value never
        # appears here — keeping this occurrence out of the tally entirely,
        # same as the glued occurrences below.
        text = text.replace('name = "demo_widget"', 'name = "demo-widget"', 1)
        text = text.replace("demo_widget.cli:main", "xdemo_widgety.cli:main")
        pyproject.write_text(text, encoding="utf-8")
        for rel in (
            "press_config.toml",
            "src/demo_widget/__init__.py",
            "src/demo_widget/cli.py",
        ):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo_widget", "xdemo_widgety"),
                encoding="utf-8",
            )
        readme = src_target / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\nSee also demo_widget_2.\n",
            encoding="utf-8",
        )
        _git(src_target, "commit", "-qam", "glue package_name, add prefix form")
        write_source_config(src_target)  # still declares package_name=demo_widget
        (src_target / "press" / "press-rules.toml").write_text(
            '[rules]\nsubstring_rewrite_fields = ["package_name"]\n',
            encoding="utf-8",
        )
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
                "--allow-dirty",  # press-rules.toml written after the commit above
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "occurs only as a prefix of" not in out

    def test_diagnostics_json_omits_prefix_warning_text(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """A closure refusal (spec E2) short-circuits before the plan's own
        advisories reach the terminal — `--diagnostics-json` must stay pure
        JSON, with no prefix-warning prose, even when the target ALSO
        carries a prefix-only occurrence that would otherwise warn."""
        for rel in ("README.md", "pyproject.toml"):
            p = src_target / rel
            p.write_text(
                p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
                encoding="utf-8",
            )
        _git(src_target, "commit", "-qam", "renamed upstream")
        write_source_config(src_target)
        (src_target / "src" / "demo_widget" / "__pycache__").mkdir()
        (src_target / "src" / "demo_widget" / "__pycache__" / "x.pyc").write_bytes(
            b"\0"
        )
        code = main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
                "--diagnostics-json",
            ]
        )
        out = capsys.readouterr().out
        assert code == 2
        assert "occurs only as a prefix of" not in out
        payload = json.loads(out)  # still pure JSON — no stray prose line
        assert payload["code"] == "rename_closure_unauthorized"
