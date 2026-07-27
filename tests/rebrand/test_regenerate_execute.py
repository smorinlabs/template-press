"""P04-TS05 — the generic declared-command executor.

D1's execution contract: cwd = target root, NO shell (argv executed
directly), deny-by-default env (platform base + declared names, absent
names omitted), and the PINNED plan-time executable is what launches. Sink
guards re-run immediately before EACH command (an earlier command can plant
a symlink/hardlink at a later output's path). Wave-3 3654059287: a declared
command exiting nonzero aborts — reported failed, never regenerated.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.regen import RegenerationPlan, execute_regenerations
from template_press.rebrand.rules import RegenerateRule

from .conftest import requires_symlink

PY = sys.executable


def _plan(file: str, *args: str, env: tuple[str, ...] = ()) -> RegenerationPlan:
    """A RegenerationPlan whose pinned executable is this Python."""
    rule = RegenerateRule(file=file, command=(PY, *args), env=env)
    return RegenerationPlan(rule=rule, executable=PY, env_present=(), env_absent=())


def _target_with(tmp_path: Path, name: str = "bun.lock") -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / name).write_text("stale demo_widget\n", encoding="utf-8")
    return target


class TestExecutionContract:
    def test_cwd_is_target_root(self, tmp_path: Path):
        """The autouse fixture chdir'd elsewhere — a relative write from the
        command must land in the TARGET, not the press caller's cwd."""
        target = _target_with(tmp_path)
        plan = _plan(
            "bun.lock",
            "-c",
            "import pathlib; pathlib.Path('cwd-probe.txt').write_text('here')",
        )
        report = ApplyReport()
        failed = execute_regenerations(target, [plan], {}, report)
        assert failed == []
        assert (target / "cwd-probe.txt").read_text() == "here"
        assert not Path("cwd-probe.txt").exists()  # nothing in caller cwd
        assert report.regenerated == ["bun.lock"]

    def test_no_shell_metacharacters_stay_literal(self, tmp_path: Path):
        target = _target_with(tmp_path)
        plan = _plan(
            "bun.lock",
            "-c",
            "import sys, pathlib; pathlib.Path('args.txt').write_text(sys.argv[1])",
            "a && touch pwned; $(evil)",
        )
        report = ApplyReport()
        assert execute_regenerations(target, [plan], {}, report) == []
        assert (target / "args.txt").read_text() == "a && touch pwned; $(evil)"
        assert not (target / "pwned").exists()

    def test_env_is_deny_by_default_plus_declared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("GITHUB_TOKEN", "hunter2")
        monkeypatch.setenv("UV_INDEX_URL", "https://evil.example/simple")
        monkeypatch.setenv("PRESS_DECLARED_VAR", "declared-value")
        monkeypatch.delenv("PRESS_ABSENT_VAR", raising=False)
        target = _target_with(tmp_path)
        plan = _plan(
            "bun.lock",
            "-c",
            "import json, os, pathlib; "
            "pathlib.Path('env.json').write_text(json.dumps(dict(os.environ)))",
            env=("PRESS_DECLARED_VAR", "PRESS_ABSENT_VAR"),
        )
        report = ApplyReport()
        assert execute_regenerations(target, [plan], {}, report) == []
        child_env = json.loads((target / "env.json").read_text())
        assert child_env.get("PRESS_DECLARED_VAR") == "declared-value"
        assert "PRESS_ABSENT_VAR" not in child_env
        assert "GITHUB_TOKEN" not in child_env  # the CI-token case (D1)
        assert "UV_INDEX_URL" not in child_env  # subsumes the old uv scrub

    def test_nonzero_exit_fails_the_regeneration(self, tmp_path: Path):
        """Wave-3 3654059287: a declared command exiting nonzero aborts the
        press — even if the output file looks fine afterwards."""
        target = _target_with(tmp_path)
        plan = _plan("bun.lock", "-c", "raise SystemExit(3)")
        report = ApplyReport()
        failed = execute_regenerations(target, [plan], {}, report)
        assert failed == ["bun.lock"]
        assert report.regenerated == []
        assert any("bun.lock" in s and "3" in s for s in report.skipped)

    def test_pinned_executable_is_what_launches(self, tmp_path: Path):
        """The plan's resolved path executes — argv[0] from the declaration
        is NOT re-resolved at run time (no second PATH lookup)."""
        target = _target_with(tmp_path)
        rule = RegenerateRule(
            file="bun.lock",
            # A bare name that does NOT exist on any PATH: if the executor
            # re-resolved argv[0] instead of using the pinned path, launch
            # would fail and the regeneration would be reported failed.
            command=("press-not-on-path-xyz", "-c", "print('ok')"),
        )
        plan = RegenerationPlan(rule=rule, executable=PY, env_present=(), env_absent=())
        report = ApplyReport()
        assert execute_regenerations(target, [plan], {}, report) == []
        assert report.regenerated == ["bun.lock"]


class TestPerCommandSinkGuards:
    """The full sink set — containment, real ancestors, no-follow regular
    file, st_nlink == 1 — re-checked immediately before EACH launch."""

    @requires_symlink
    def test_symlink_planted_at_output_refuses_before_launch(self, tmp_path: Path):
        target = _target_with(tmp_path, name="real.lock")
        # simulate an earlier command planting a link at the later output
        os.symlink("real.lock", target / "bun.lock")
        plan = _plan(
            "bun.lock",
            "-c",
            "import pathlib; pathlib.Path('launched.txt').write_text('x')",
        )
        report = ApplyReport()
        failed = execute_regenerations(target, [plan], {}, report)
        assert failed == ["bun.lock"]
        assert not (target / "launched.txt").exists()  # never launched

    def test_hardlink_planted_at_output_refuses_before_launch(self, tmp_path: Path):
        target = _target_with(tmp_path)
        os.link(target / "bun.lock", tmp_path / "outside-link")
        plan = _plan(
            "bun.lock",
            "-c",
            "import pathlib; pathlib.Path('launched.txt').write_text('x')",
        )
        report = ApplyReport()
        failed = execute_regenerations(target, [plan], {}, report)
        assert failed == ["bun.lock"]
        assert not (target / "launched.txt").exists()

    @requires_symlink
    def test_symlinked_ancestor_refuses_before_launch(self, tmp_path: Path):
        outside = tmp_path / "outside-dir"
        outside.mkdir()
        (outside / "custom.lock").write_text("lock\n", encoding="utf-8")
        target = tmp_path / "target"
        target.mkdir()
        os.symlink(outside, target / "sub")
        rule = RegenerateRule(file="sub/custom.lock", command=(PY, "-c", "pass"))
        plan = RegenerationPlan(rule=rule, executable=PY, env_present=(), env_absent=())
        report = ApplyReport()
        failed = execute_regenerations(target, [plan], {}, report)
        assert failed == ["sub/custom.lock"]


class TestRenameTranslation:
    def test_declared_path_translated_through_renames(self, tmp_path: Path):
        """apply() renames identity-bearing directories BEFORE regeneration
        runs — the command must produce the file at the renamed location
        while the declaration stays in source coordinates."""
        target = tmp_path / "target"
        moved = target / "packages" / "potato_launcher"
        moved.mkdir(parents=True)
        (moved / "bun.lock").write_text("stale\n", encoding="utf-8")
        plan = _plan(
            "packages/demo_widget/bun.lock",
            "-c",
            "import pathlib; "
            "pathlib.Path('packages/potato_launcher/bun.lock')"
            ".write_text('fresh')",
        )
        report = ApplyReport()
        failed = execute_regenerations(
            target,
            [plan],
            {"packages/demo_widget": "packages/potato_launcher"},
            report,
        )
        assert failed == []
        assert (moved / "bun.lock").read_text() == "fresh"
        assert report.regenerated == ["packages/demo_widget/bun.lock"]


def test_replace_pass_preserves_file_mode(src_target: Path):
    """D1 (surviving requirement): safe_write's temp+rename creates a fresh
    inode and mkstemp's 0600 must not strip an 0755 script's execute bits —
    a rewritten helper would otherwise fail only at launch, post-mutation."""
    from template_press.rebrand.engine import apply
    from template_press.rebrand.rules import DEFAULT_RULES

    from .conftest import DEST, SOURCE, make_target  # noqa: F401

    script = src_target / "tools" / "run-press.sh"
    script.parent.mkdir()
    script.write_text('#!/bin/sh\nexec press "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    import subprocess

    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add script"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    rewritten = src_target / "tools" / "run-potato.sh"
    candidate = rewritten if rewritten.exists() else script
    assert "potato" in candidate.read_text(encoding="utf-8")
    mode = stat.S_IMODE(os.stat(candidate).st_mode)
    assert mode & stat.S_IXUSR, f"execute bit stripped (mode {oct(mode)})"
