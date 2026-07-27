"""P04-TS01 — [[regenerate]] schema + config-load validation + output preflight.

D1: regeneration commands are fully target-declared — a [[regenerate]] table
per output with `file`/`command`/`env` keys, validated at config load, with
no hidden default (DEFAULT_RULES.regenerate is removed) and no
filename→command inference anywhere, including in the legacy-form error.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.regen import preflight_regenerate_outputs
from template_press.rebrand.rules import DEFAULT_RULES, RegenerateRule, load_rules

from .conftest import requires_symlink


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Schema — shape, types, and config-load validation
# ---------------------------------------------------------------------------
class TestRegenerateSchema:
    def test_no_hidden_default(self):
        """T02 removes DEFAULT_RULES.regenerate = ("uv.lock",) entirely."""
        assert DEFAULT_RULES.regenerate == ()

    def test_valid_entry_parses(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            "[[regenerate]]\n"
            'file = "bun.lock"\n'
            'command = ["bun", "install"]\n'
            'env = ["NODE_ENV"]\n',
        )
        rules = load_rules(target)
        (rule,) = rules.regenerate
        assert isinstance(rule, RegenerateRule)
        assert rule.file == "bun.lock"
        assert rule.command == ("bun", "install")
        assert rule.env == ("NODE_ENV",)

    def test_env_is_optional_and_defaults_empty(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
        )
        (rule,) = load_rules(target).regenerate
        assert rule.env == ()

    def test_unknown_key_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n'
            "shell = true\n",
        )
        with pytest.raises(ValidationError, match="shell"):
            load_rules(target)

    def test_entry_must_be_table(self, tmp_path: Path):
        # An array-of-strings [[regenerate]] is the legacy shape at root —
        # routed to the legacy-form error (tested below), so use a scalar.
        target = _write_rules(tmp_path, 'regenerate = "uv.lock"\n')
        with pytest.raises(ValidationError):
            load_rules(target)


class TestDuplicateTargets:
    def test_duplicate_regenerate_targets_rejected(self, tmp_path: Path):
        """CodeRabbit 3654968985: same second-write-silently-wins hazard the
        reset duplicate ban prevents — and an ambiguous declaration."""
        target = _write_rules(
            tmp_path,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["a"]\n'
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["b"]\n',
        )
        with pytest.raises(ValidationError, match="more than one"):
            load_rules(target)


class TestLegacyFormRejected:
    """The old list-of-strings `regenerate` must fail with a schema TEMPLATE
    carrying a PLACEHOLDER command — never an argv derived from the filename,
    which would reinstate the inference D1 removes."""

    def test_rules_table_legacy_list_rejected_with_template(self, tmp_path: Path):
        target = _write_rules(
            tmp_path, '[rules]\nregenerate = ["uv.lock", "bun.lock"]\n'
        )
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        msg = str(exc.value)
        assert "[[regenerate]]" in msg  # points at the new form
        assert "uv.lock" in msg  # the declared filename is preserved
        assert "<command>" in msg  # placeholder command, never derived
        assert "uv lock" not in msg  # no filename→command inference
        assert "bun install" not in msg

    def test_root_level_legacy_list_rejected_with_template(self, tmp_path: Path):
        target = _write_rules(tmp_path, 'regenerate = ["uv.lock"]\n')
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        msg = str(exc.value)
        assert "[[regenerate]]" in msg
        assert "<command>" in msg


class TestCommandValidation:
    """`command` is a non-empty list of non-empty NUL-free strings."""

    @pytest.mark.parametrize(
        "command_toml",
        [
            "command = []",  # empty list
            'command = ["bun", ""]',  # empty element
            'command = ["bun", 3]',  # non-string element
            'command = "bun install"',  # string, not list
            'command = ["bun\\u0000x"]',  # NUL in element
            "",  # missing entirely
        ],
    )
    def test_malformed_command_rejected(self, tmp_path: Path, command_toml: str):
        target = _write_rules(
            tmp_path, f'[[regenerate]]\nfile = "uv.lock"\n{command_toml}\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestEnvValidation:
    """`env` lists platform-valid variable NAMES — no `=`, no NUL, strings."""

    @pytest.mark.parametrize(
        "env_toml",
        [
            'env = ["A=B"]',
            'env = [""]',
            'env = ["A\\u0000B"]',
            'env = "NODE_ENV"',  # string, not list
            "env = [3]",  # non-string element
        ],
    )
    def test_malformed_env_rejected(self, tmp_path: Path, env_toml: str):
        target = _write_rules(
            tmp_path,
            f'[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n{env_toml}\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestFileValidation:
    """`file` is a contained relative path (SafeRelPath), never ROOT_CONTROL,
    and must be listed in exclude_files (else the replace pass would rewrite
    it first and the command would overwrite that work)."""

    @pytest.mark.parametrize(
        "file_toml",
        [
            'file = "/etc/passwd"',  # absolute
            'file = "../outside.lock"',  # traversal
            'file = ".git/config"',  # .git component
            'file = ""',  # empty
            "file = 3",  # non-string
            "",  # missing
            # Codex thread 3654657431 (P1): plan visibility is the approval
            # guard — a declared path carrying a newline or ANSI escape can
            # forge the rendered preview, exactly like argv elements.
            'file = "bun\\nfake.lock"',  # newline
            'file = "bun\\u001b[2Jx.lock"',  # ANSI escape
            'file = "bun\\rx.lock"',  # carriage return
        ],
    )
    def test_unsafe_file_rejected(self, tmp_path: Path, file_toml: str):
        target = _write_rules(
            tmp_path, f'[[regenerate]]\n{file_toml}\ncommand = ["true"]\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    @pytest.mark.parametrize(
        "reserved",
        ["press/press-receipt.toml", "press/press-source.toml"],
    )
    def test_root_control_rejected(self, tmp_path: Path, reserved: str):
        target = _write_rules(
            tmp_path,
            f'[[regenerate]]\nfile = "{reserved}"\ncommand = ["true"]\n'
            f"[rules]\n"
            f'extra_exclude_files = ["{reserved}"]\n',
        )
        with pytest.raises(ValidationError, match="control"):
            load_rules(target)

    def test_output_not_in_exclude_files_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path, '[[regenerate]]\nfile = "some.lock"\ncommand = ["true"]\n'
        )
        with pytest.raises(ValidationError, match="exclude_files"):
            load_rules(target)

    def test_output_in_extra_exclude_files_accepted(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["custom.lock"]\n'
            '[[regenerate]]\nfile = "custom.lock"\ncommand = ["true"]\n',
        )
        (rule,) = load_rules(target).regenerate
        assert rule.file == "custom.lock"


# ---------------------------------------------------------------------------
# Plan-time output-state preflight (tracked, clean, real, sole-linked)
# ---------------------------------------------------------------------------
def _declare_bun_lock(target: Path) -> None:
    _write_rules(
        target,
        '[[regenerate]]\nfile = "bun.lock"\ncommand = ["true"]\n',
    )
    _git(target, "add", "press/press-rules.toml")
    _git(target, "commit", "-q", "-m", "declare regeneration")


class TestOutputPreflight:
    """D1: regeneration outputs must be git-tracked and clean at plan time —
    refused even under --allow-dirty (the preflight takes no such flag at
    all, so the refusal is structural). The sink predicates (containment,
    no-follow regular file, st_nlink == 1) run here too."""

    def test_tracked_clean_output_passes(self, src_target: Path):
        (src_target / "bun.lock").write_text("lock demo_widget\n", encoding="utf-8")
        _git(src_target, "add", "bun.lock")
        _git(src_target, "commit", "-q", "-m", "add lockfile")
        _declare_bun_lock(src_target)
        assert preflight_regenerate_outputs(src_target, load_rules(src_target)) == []

    def test_assume_unchanged_edit_refused(self, src_target: Path):
        """Codex 3654736772 (P1): the assume-unchanged bit hides edits from
        `status --porcelain`; hidden work is still work the guard promises
        not to destroy — the preflight must see through the bit."""
        (src_target / "bun.lock").write_text("lock\n", encoding="utf-8")
        _git(src_target, "add", "bun.lock")
        _git(src_target, "commit", "-q", "-m", "add lockfile")
        _declare_bun_lock(src_target)
        _git(src_target, "update-index", "--assume-unchanged", "bun.lock")
        (src_target / "bun.lock").write_text("hidden edit\n", encoding="utf-8")
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]

    def test_untracked_output_refused(self, src_target: Path):
        (src_target / "bun.lock").write_text("lock\n", encoding="utf-8")
        _declare_bun_lock(src_target)
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]
        assert any("tracked" in p for p in problems)

    def test_missing_output_refused(self, src_target: Path):
        _declare_bun_lock(src_target)
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]

    def test_dirty_output_refused(self, src_target: Path):
        (src_target / "bun.lock").write_text("lock\n", encoding="utf-8")
        _git(src_target, "add", "bun.lock")
        _git(src_target, "commit", "-q", "-m", "add lockfile")
        _declare_bun_lock(src_target)
        (src_target / "bun.lock").write_text("lock EDITED\n", encoding="utf-8")
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]
        assert any("uncommitted" in p or "dirty" in p for p in problems)

    @requires_symlink
    def test_symlink_output_refused(self, src_target: Path):
        (src_target / "real.lock").write_text("lock\n", encoding="utf-8")
        os.symlink("real.lock", src_target / "bun.lock")
        _git(src_target, "add", "real.lock", "bun.lock")
        _git(src_target, "commit", "-q", "-m", "symlink lockfile")
        _declare_bun_lock(src_target)
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]

    def test_hardlinked_output_refused(self, src_target: Path):
        (src_target / "bun.lock").write_text("lock\n", encoding="utf-8")
        _git(src_target, "add", "bun.lock")
        _git(src_target, "commit", "-q", "-m", "add lockfile")
        os.link(src_target / "bun.lock", src_target.parent / "outside-link")
        _declare_bun_lock(src_target)
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "bun.lock" in problems[0]
        assert any("hardlink" in p or "st_nlink" in p for p in problems)

    @requires_symlink
    def test_symlinked_ancestor_refused(self, src_target: Path):
        """A declared path under a symlinked directory would redirect the
        command's output outside the checked tree — refuse at plan time."""
        outside = src_target.parent / "outside-dir"
        outside.mkdir()
        (outside / "custom.lock").write_text("lock\n", encoding="utf-8")
        os.symlink(outside, src_target / "sub")
        _write_rules(
            src_target,
            '[rules]\nextra_exclude_files = ["sub/custom.lock"]\n'
            '[[regenerate]]\nfile = "sub/custom.lock"\ncommand = ["true"]\n',
        )
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert problems and "sub/custom.lock" in problems[0]
