"""P04-TS03 — plan-time resolution, stale-argv refusal, and plan rendering.

D2: every declared command's executable resolves at plan time, under the
deny-by-default effective environment, and the resolved absolute path is
PINNED (no second runtime PATH lookup) and rendered in the plan beside the
verbatim argv. D1: argv elements naming paths in the plan's rename set are
a plan-time refusal (normalized, prefix-aware, best-effort). Wave-3
3654059282 (P1): control characters in argv are rejected — plan visibility
is the entire approval guard, so a literal renderer must not be forgeable.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.regen import (
    COMMAND_ENV_BASE,
    EditPlan,
    RegenerationPlan,
    command_env,
    plan_edits,
    plan_regenerate_commands,
    render_edit_plan,
    render_regenerate_plan,
    resolve_executable,
    stale_argv_elements,
)
from template_press.rebrand.rules import (
    SUPPORTED_PLATFORMS,
    EditRule,
    RegenerateRule,
    load_rules,
)

from .conftest import DEST, SOURCE, posix_only, write_answers_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ---------------------------------------------------------------------------
# Deny-by-default effective environment (D1, decided 2026-07-26)
# ---------------------------------------------------------------------------
class TestCommandEnv:
    def test_ambient_variables_do_not_leak(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GITHUB_TOKEN", "hunter2")
        monkeypatch.setenv("UV_INDEX_URL", "https://evil.example/simple")
        env = command_env(())
        assert "GITHUB_TOKEN" not in env
        assert "UV_INDEX_URL" not in env

    def test_only_base_plus_declared_names(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NODE_ENV", "production")
        env = command_env(("NODE_ENV",))
        assert env["NODE_ENV"] == "production"
        allowed = set(COMMAND_ENV_BASE) | {"NODE_ENV"}
        assert set(env) <= allowed

    def test_declared_but_absent_name_is_omitted(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PRESS_TEST_UNSET_VAR", raising=False)
        env = command_env(("PRESS_TEST_UNSET_VAR",))
        assert "PRESS_TEST_UNSET_VAR" not in env


# ---------------------------------------------------------------------------
# Executable resolution (D2) — bare → PATH, slash → target root, pinned
# ---------------------------------------------------------------------------
class TestResolveExecutable:
    @posix_only
    def test_bare_name_resolves_on_effective_path(self, tmp_path: Path):
        exe = _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        resolved = resolve_executable(
            target, "faketool", {"PATH": str(tmp_path / "bin")}
        )
        assert resolved is not None
        assert resolved.is_absolute()
        assert resolved == exe

    def test_bare_name_missing_returns_none(self, tmp_path: Path):
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        assert resolve_executable(target, "faketool", {"PATH": str(empty)}) is None

    def test_bare_name_bound_to_effective_env_not_ambient(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Resolution runs under the deny-by-default env: an executable only
        on the OPERATOR's ambient PATH must not resolve when the effective
        env's PATH lacks it."""
        _make_exe(tmp_path / "ambient-bin" / "faketool")
        monkeypatch.setenv("PATH", str(tmp_path / "ambient-bin"))
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        assert resolve_executable(target, "faketool", {"PATH": str(empty)}) is None

    @posix_only
    def test_path_qualified_resolves_against_target_root(self, tmp_path: Path):
        """`./tools/regen` resolves relative to the TARGET root (the
        execution cwd) — never the press caller's directory (the autouse
        fixture has chdir'd elsewhere)."""
        target = tmp_path / "target"
        exe = _make_exe(target / "tools" / "regen")
        resolved = resolve_executable(target, "./tools/regen", {"PATH": ""})
        assert resolved == exe
        assert resolve_executable(target, "tools/regen", {"PATH": ""}) == exe

    @posix_only
    def test_backslash_form_is_path_qualified(self, tmp_path: Path):
        target = tmp_path / "target"
        exe = _make_exe(target / "tools" / "regen")
        resolved = resolve_executable(target, ".\\tools\\regen", {"PATH": ""})
        assert resolved == exe

    def test_path_qualified_never_falls_back_to_path(self, tmp_path: Path):
        """A slash-qualified argv0 resolves ONLY against the target root —
        a same-named tool on the effective PATH must not be found."""
        _make_exe(tmp_path / "bin" / "regen")
        target = tmp_path / "target"
        target.mkdir()
        assert (
            resolve_executable(target, "./regen", {"PATH": str(tmp_path / "bin")})
            is None
        )

    @posix_only
    def test_relative_path_entry_pins_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Codex 3654736767 (P1): a relative PATH entry resolves against the
        press caller's cwd at plan time, but execution launches with
        cwd=target — the pin must freeze an ABSOLUTE path so the launched
        binary is exactly the one planning verified."""
        _make_exe(tmp_path / "relbin" / "reltool")
        monkeypatch.chdir(tmp_path)
        found = resolve_executable(tmp_path / "target", "reltool", {"PATH": "relbin"})
        assert found is not None
        assert found.is_absolute()
        assert found == tmp_path / "relbin" / "reltool"

    @posix_only
    def test_absolute_argv0_pins_itself(self, tmp_path: Path):
        exe = _make_exe(tmp_path / "abs-bin" / "pinned")
        target = tmp_path / "target"
        target.mkdir()
        assert resolve_executable(target, str(exe), {"PATH": ""}) == exe


# ---------------------------------------------------------------------------
# Stale-argv refusal (D1) — normalized, prefix-aware, best-effort
# ---------------------------------------------------------------------------
class TestStaleArgv:
    RENAMED = frozenset({"packages/demo_widget"})

    @pytest.mark.parametrize(
        "element",
        [
            "packages/demo_widget",  # exact
            "packages/demo_widget/regenerate.py",  # descendant
            "./packages/demo_widget",  # dot-prefixed spelling
            "packages/demo_widget/../demo_widget",  # dotdot spelling
            ".\\packages\\demo_widget",  # windows separators
        ],
    )
    def test_renamed_path_spellings_detected(self, element: str):
        stale = stale_argv_elements(("bun", "--cwd", element, "install"), self.RENAMED)
        assert stale == [element]

    @pytest.mark.parametrize(
        "command",
        [
            ("bun", "install"),  # no paths at all
            ("python", "packages/other/regen.py"),  # unrenamed path
            ("bun", "--cwd", "packages", "install"),  # ancestor, not descendant
        ],
    )
    def test_unrenamed_elements_pass(self, command: tuple[str, ...]):
        assert stale_argv_elements(command, self.RENAMED) == []

    def test_empty_rename_set_never_stale(self):
        assert stale_argv_elements(("bun", "--cwd", "packages/demo_widget"), ()) == []

    def test_attached_option_payload_is_a_recorded_residual(self):
        """Best-effort over recognized shapes (D1): an attached-option
        payload carries a path the membership test cannot see without
        guessing argv semantics. NOT detected — the command fails loudly
        mid-press instead and D4's abort withholds the receipt."""
        stale = stale_argv_elements(
            ("tool", "--config=packages/demo_widget/c.toml"), self.RENAMED
        )
        assert stale == []


# ---------------------------------------------------------------------------
# Control characters in argv / env names — reject at config load (wave-3)
# ---------------------------------------------------------------------------
class TestControlCharactersRejected:
    def _write(self, tmp_path: Path, body: str) -> Path:
        d = tmp_path / "press"
        d.mkdir(exist_ok=True, parents=True)
        (d / "press-rules.toml").write_text(body, encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize(
        "element_toml",
        [
            'command = ["bun\\ninstall"]',  # newline forges a plan line
            'command = ["bun\\rinstall"]',  # CR overwrites a plan line
            'command = ["bun\\u001B[31minstall"]',  # ANSI escape
            'command = ["bun\\tinstall"]',  # tab
        ],
    )
    def test_control_chars_in_command_rejected(self, tmp_path: Path, element_toml):
        target = self._write(
            tmp_path, f'[[regenerate]]\nfile = "uv.lock"\n{element_toml}\n'
        )
        with pytest.raises(ValidationError, match="control"):
            load_rules(target)

    def test_control_chars_in_env_name_rejected(self, tmp_path: Path):
        target = self._write(
            tmp_path,
            '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n'
            'env = ["NODE\\u001BENV"]\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


# ---------------------------------------------------------------------------
# plan_regenerate_commands + rendering
# ---------------------------------------------------------------------------
class TestPlanRegenerateCommands:
    @posix_only
    def test_resolvable_command_planned_with_pinned_path(self, tmp_path: Path):
        exe = _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        rule = RegenerateRule(file="bun.lock", command=("faketool", "install"), env=())
        plans, problems = plan_regenerate_commands(
            target,
            (rule,),
            renamed=frozenset(),
            base_env={"PATH": str(tmp_path / "bin")},
        )
        assert problems == []
        (plan,) = plans
        assert plan.rule is rule
        assert plan.executable == str(exe)
        assert os.path.isabs(plan.executable)

    def test_missing_tool_is_a_problem_naming_it(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        rule = RegenerateRule(file="bun.lock", command=("press-no-such-tool-xyz",))
        plans, problems = plan_regenerate_commands(
            target, (rule,), renamed=frozenset(), base_env={"PATH": ""}
        )
        assert plans == []
        assert problems and "press-no-such-tool-xyz" in problems[0]
        assert "bun.lock" in problems[0]

    def test_stale_argv_is_a_problem_even_when_tool_resolves(self, tmp_path: Path):
        _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        rule = RegenerateRule(
            file="bun.lock",
            command=("faketool", "--cwd", "packages/demo_widget", "install"),
        )
        _, problems = plan_regenerate_commands(
            target,
            (rule,),
            renamed=frozenset({"packages/demo_widget"}),
            base_env={"PATH": str(tmp_path / "bin")},
        )
        assert problems and "packages/demo_widget" in problems[0]

    def test_render_shows_verbatim_argv_pinned_path_and_env_names(self):
        plan = RegenerationPlan(
            rule=RegenerateRule(
                file="bun.lock",
                command=("bun", "install"),
                env=("NODE_ENV", "CI_ABSENT"),
            ),
            executable="/opt/tools/bin/bun",
            env_present=("NODE_ENV",),
            env_absent=("CI_ABSENT",),
        )
        out = render_regenerate_plan([plan])
        assert "bun.lock" in out
        assert "bun install" in out  # verbatim argv
        assert "/opt/tools/bin/bun" in out  # the pinned path that will launch
        assert "NODE_ENV" in out
        assert "CI_ABSENT (absent)" in out
        # Byte-for-byte preservation: [[edit]] shares this renderer, so the
        # regeneration section's heading, row tag, and indentation are pinned
        # exactly as they read before the two mechanisms were joined.
        lines = out.splitlines()
        assert lines[0] == "Regenerate (declared commands, run after apply):"
        assert lines[1] == "  [regen  ] bun.lock  —  bun install"
        assert lines[2] == "            executable: /opt/tools/bin/bun"


# ---------------------------------------------------------------------------
# CLI wiring — exit 2 means nothing written; dry-run renders the commands
# ---------------------------------------------------------------------------
def _declare_and_commit(target: Path, rules_body: str) -> None:
    (target / "press").mkdir(exist_ok=True)
    (target / "press" / "press-source.toml").write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    (target / "press" / "press-rules.toml").write_text(rules_body, encoding="utf-8")
    (target / "bun.lock").write_text("lock demo\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "declare regeneration")


class TestCliPlanGates:
    def test_missing_tool_exits_2_nothing_written(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        _declare_and_commit(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["press-no-such-tool-xyz"]\n',
        )
        answers = write_answers_file(tmp_path, DEST)
        before = snapshot_target(src_target)
        code = main(["--target", str(src_target), "--config", str(answers)])
        assert code == 2
        assert "press-no-such-tool-xyz" in capsys.readouterr().err
        assert snapshot_target(src_target) == before

    def test_dry_run_missing_tool_also_exits_2(
        self, src_target: Path, tmp_path: Path, snapshot_target
    ):
        _declare_and_commit(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["press-no-such-tool-xyz"]\n',
        )
        answers = write_answers_file(tmp_path, DEST)
        before = snapshot_target(src_target)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        assert code == 2
        assert snapshot_target(src_target) == before

    @posix_only
    def test_dry_run_renders_command_pinned_path_and_env(
        self, src_target: Path, tmp_path: Path, capsys, monkeypatch
    ):
        monkeypatch.setenv("PRESS_REGEN_SET_VAR", "1")
        monkeypatch.delenv("PRESS_REGEN_UNSET_VAR", raising=False)
        _declare_and_commit(
            src_target,
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["true"]\n'
            'env = ["PRESS_REGEN_SET_VAR", "PRESS_REGEN_UNSET_VAR"]\n',
        )
        answers = write_answers_file(tmp_path, DEST)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "bun.lock" in out
        assert "true" in out  # verbatim argv
        # the pinned absolute path that will actually launch
        line = next(ln for ln in out.splitlines() if "executable:" in ln)
        assert os.path.isabs(line.split("executable:", 1)[1].strip())
        assert "PRESS_REGEN_SET_VAR" in out
        assert "PRESS_REGEN_UNSET_VAR (absent)" in out
        # No [[edit]] declared: the edit section must not appear at all.
        assert "Edit (declared" not in out


# ---------------------------------------------------------------------------
# plan_edits + rendering (E4 / Task 13) — the [[edit]] mechanism reuses D2's
# resolution and D1's stale-argv refusal wholesale, so the two mechanisms
# cannot drift in what they pin, refuse, or show.
# ---------------------------------------------------------------------------
class TestPlanEdits:
    @posix_only
    def test_resolvable_command_planned_with_pinned_path(self, tmp_path: Path):
        exe = _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        rule = EditRule(
            file="pyproject.toml",
            command=("faketool", "version", "0.1.0"),
            expect='version = "0.1.0"',
            env=(),
        )
        plans, problems = plan_edits(
            target,
            (rule,),
            renamed=frozenset(),
            base_env={"PATH": str(tmp_path / "bin")},
        )
        assert problems == []
        (plan,) = plans
        assert plan.rule is rule
        assert plan.executable == str(exe)
        assert os.path.isabs(plan.executable)

    def test_missing_tool_is_a_problem_naming_the_edit_target(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        rule = EditRule(
            file="pyproject.toml",
            command=("press-no-such-tool-xyz",),
            expect="x",
            env=(),
        )
        plans, problems = plan_edits(
            target, (rule,), renamed=frozenset(), base_env={"PATH": ""}
        )
        assert plans == []
        assert problems and problems[0].startswith("edit pyproject.toml:")
        assert "press-no-such-tool-xyz" in problems[0]

    @posix_only
    def test_stale_argv_is_a_problem_even_when_tool_resolves(self, tmp_path: Path):
        _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        rule = EditRule(
            file="pyproject.toml",
            command=("faketool", "--cwd", "packages/demo_widget"),
            expect="x",
            env=(),
        )
        plans, problems = plan_edits(
            target,
            (rule,),
            renamed=frozenset({"packages/demo_widget"}),
            base_env={"PATH": str(tmp_path / "bin")},
        )
        assert plans == []
        assert problems and "packages/demo_widget" in problems[0]
        assert problems[0].startswith("edit pyproject.toml:")

    @posix_only
    def test_declared_env_split_into_present_and_absent(self, tmp_path: Path):
        _make_exe(tmp_path / "bin" / "faketool")
        target = tmp_path / "target"
        target.mkdir()
        rule = EditRule(
            file="pyproject.toml",
            command=("faketool",),
            expect="x",
            env=("PRESS_EDIT_SET", "PRESS_EDIT_UNSET"),
        )
        plans, _ = plan_edits(
            target,
            (rule,),
            renamed=frozenset(),
            base_env={"PATH": str(tmp_path / "bin"), "PRESS_EDIT_SET": "1"},
        )
        (plan,) = plans
        assert plan.env_present == ("PRESS_EDIT_SET",)
        assert plan.env_absent == ("PRESS_EDIT_UNSET",)

    @posix_only
    def test_path_qualified_argv0_resolves_against_the_target_root(
        self, tmp_path: Path
    ):
        target = tmp_path / "target"
        target.mkdir()
        exe = _make_exe(target / "scripts" / "bump")
        rule = EditRule(
            file="pyproject.toml",
            command=("scripts/bump",),
            expect="x",
            env=(),
        )
        plans, problems = plan_edits(
            target, (rule,), renamed=frozenset(), base_env={"PATH": ""}
        )
        assert problems == []
        (plan,) = plans
        assert plan.executable == str(exe)

    def test_render_shows_heading_row_pinned_path_and_env_names(self):
        plan = EditPlan(
            rule=EditRule(
                file="pyproject.toml",
                command=("uv", "version", "0.1.0", "--frozen"),
                expect='version = "0.1.0"',
                env=("NODE_ENV", "CI_ABSENT"),
            ),
            executable="/opt/tools/bin/uv",
            env_present=("NODE_ENV",),
            env_absent=("CI_ABSENT",),
        )
        out = render_edit_plan([plan])
        assert out.splitlines()[0] == (
            "Edit (declared in-place edits, run after apply, before regenerations):"
        )
        assert "  [edit   ] pyproject.toml  —  uv version 0.1.0 --frozen" in out
        assert "            executable: /opt/tools/bin/uv" in out
        assert "NODE_ENV" in out
        assert "CI_ABSENT (absent)" in out


class TestCliEditPlanGates:
    @posix_only
    def test_dry_run_renders_edit_row_before_the_regenerate_section(
        self,
        src_target: Path,
        tmp_path: Path,
        capsys,
        monkeypatch: pytest.MonkeyPatch,
    ):
        bindir = tmp_path / "bin"
        _make_exe(bindir / "uv")
        real_git = shutil.which("git")
        assert real_git is not None
        os.symlink(real_git, bindir / "git")
        monkeypatch.setenv("PATH", str(bindir))
        _declare_and_commit(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0", "--frozen"]\n'
            "expect = 'version = \"0.1.0\"'\n"
            '\n[[regenerate]]\nfile = "bun.lock"\ncommand = ["uv", "lock"]\n',
        )
        answers = write_answers_file(tmp_path, DEST)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert (
            "Edit (declared in-place edits, run after apply, before "
            "regenerations):" in out
        )
        assert "  [edit   ] pyproject.toml  —  uv version 0.1.0 --frozen" in out
        edit_line = next(
            i for i, ln in enumerate(out.splitlines()) if "[edit   ]" in ln
        )
        executable_line = out.splitlines()[edit_line + 1]
        assert executable_line.strip().startswith("executable:")
        assert os.path.isabs(executable_line.split("executable:", 1)[1].strip())
        # Phase order (E4): every edit runs before every regeneration, and the
        # plan the operator approves must read in that order.
        assert out.index("Edit (declared in-place edits") < out.index(
            "Regenerate (declared commands"
        )

    def test_missing_edit_tool_exits_2_before_the_plan_nothing_written(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        _declare_and_commit(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["press-no-such-tool-xyz", "version"]\n'
            "expect = 'version = \"0.1.0\"'\n",
        )
        answers = write_answers_file(tmp_path, DEST)
        before = snapshot_target(src_target)
        code = main(["--target", str(src_target), "--config", str(answers)])
        captured = capsys.readouterr()
        assert code == 2
        assert "press-no-such-tool-xyz" in captured.err
        assert "pyproject.toml" in captured.err
        # The refusal precedes the plan announcement, exactly as a missing
        # regeneration tool does — no Platform:/Plan: banner leaks first.
        assert "Platform:" not in captured.out
        assert "Plan:" not in captured.out
        assert snapshot_target(src_target) == before

    def test_dry_run_missing_edit_tool_also_exits_2(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        _declare_and_commit(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["press-no-such-tool-xyz", "version"]\n'
            "expect = 'version = \"0.1.0\"'\n",
        )
        answers = write_answers_file(tmp_path, DEST)
        before = snapshot_target(src_target)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        assert code == 2
        assert "Platform:" not in capsys.readouterr().out
        assert snapshot_target(src_target) == before

    @posix_only
    def test_only_the_active_platforms_edit_is_planned_and_rendered(
        self,
        src_target: Path,
        tmp_path: Path,
        capsys,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Platform selection reaches the plan: cli.py consumes the SELECTED
        rules, so an edit declared for another platform is neither rendered
        nor gated — were the raw declarations to leak through, the inactive
        edit's absent tool would refuse this press at exit 2."""
        bindir = tmp_path / "bin"
        _make_exe(bindir / "uv")
        real_git = shutil.which("git")
        assert real_git is not None
        os.symlink(real_git, bindir / "git")
        monkeypatch.setenv("PATH", str(bindir))
        inactive = next(p for p in sorted(SUPPORTED_PLATFORMS) if p != sys.platform)
        _declare_and_commit(
            src_target,
            '[[edit]]\nfile = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0", "--frozen"]\n'
            "expect = 'version = \"0.1.0\"'\n"
            f'platforms = ["{sys.platform}"]\n'
            '\n[[edit]]\nfile = "README.md"\n'
            'command = ["press-test-inactive-tool-f82d"]\n'
            'expect = "x"\n'
            f'platforms = ["{inactive}"]\n'
            '\n[[regenerate]]\nfile = "bun.lock"\ncommand = ["uv", "lock"]\n',
        )
        answers = write_answers_file(tmp_path, DEST)
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert [ln for ln in out.splitlines() if "[edit   ]" in ln] == [
            "  [edit   ] pyproject.toml  —  uv version 0.1.0 --frozen"
        ]
        assert "press-test-inactive-tool-f82d" not in out
