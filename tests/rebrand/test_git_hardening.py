"""Concrete proof: on-target git READS neutralize a hostile `core.fsmonitor`.

Threat model (verify's exact one): a target directory is untrusted input — an
external template whose repo-local `.git/config` is attacker-controlled. A
committed `core.fsmonitor` pointing at an executable script must NOT run
merely because this tool *enumerates* or *discovers* the target, or checks
whether its working tree is dirty. Proven concretely: install a malicious
`core.fsmonitor` that touches a SENTINEL file, call each hardened on-target
git-reading entry point, and assert the SENTINEL was never created.

Confirmed empirically (see task report) that on this git build, `git status
--porcelain`, `git ls-files --cached --others --exclude-standard`, and `git
ls-files --stage` all invoke a configured `core.fsmonitor` hook when it is
NOT neutralized via `-c core.fsmonitor=` — so this is a real, exercised
surface, not a hypothetical one. `git remote get-url origin` does not touch
fsmonitor (it never reads the working tree), but its repo-local config read
still benefits from `scrubbed_git_env` against a poisoned global config.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from template_press.rebrand import cli as cli_mod
from template_press.rebrand import discovery, engine
from template_press.rebrand.rules import DEFAULT_RULES


def _install_malicious_fsmonitor(target: Path, sentinel: Path) -> None:
    """Wire a MALICIOUS repo-local `core.fsmonitor` into `target`'s own
    `.git/config` — an executable script that touches `sentinel` and prints a
    well-formed fsmonitor v2 response (so git accepts it and does not error
    out before the touch runs)."""
    hook = target / ".git" / "press-fsmonitor-hook.sh"
    hook.write_text(
        f'#!/bin/sh\ntouch "{sentinel}"\necho \'{{"version":2,"clean":true}}\'\n',
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # git is hardcoded; target is a test-owned tmp fixture — not untrusted
    # input to THIS subprocess call (only the config VALUE it writes is the
    # attacker-controlled fixture under test).
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "config", "core.fsmonitor", str(hook)],  # noqa: S607
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# The four hardened on-target read call sites — hardened call -> no sentinel.
# ---------------------------------------------------------------------------
def test_engine_git_listed_does_not_trigger_hostile_fsmonitor(
    src_target: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / "SENTINEL_git_listed"
    _install_malicious_fsmonitor(src_target, sentinel)
    engine._git_listed(src_target)
    assert not sentinel.exists()


def test_engine_iter_target_files_does_not_trigger_hostile_fsmonitor(
    src_target: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / "SENTINEL_iter_target_files"
    _install_malicious_fsmonitor(src_target, sentinel)
    engine.iter_target_files(src_target, DEFAULT_RULES)
    assert not sentinel.exists()


def test_engine_gitlink_rels_does_not_trigger_hostile_fsmonitor(
    src_target: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / "SENTINEL_gitlink_rels"
    _install_malicious_fsmonitor(src_target, sentinel)
    engine._gitlink_rels(src_target)
    assert not sentinel.exists()


def test_discovery_origin_does_not_trigger_hostile_fsmonitor(
    src_target: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / "SENTINEL_origin"
    _install_malicious_fsmonitor(src_target, sentinel)
    discovery._origin(src_target)
    assert not sentinel.exists()


def test_cli_dirty_check_does_not_trigger_hostile_fsmonitor(
    src_target: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / "SENTINEL_dirty_check"
    _install_malicious_fsmonitor(src_target, sentinel)
    problem = cli_mod.check_preconditions(src_target, force=False, allow_dirty=False)
    assert problem is None  # the fixture's working tree is clean
    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# Belt-and-suspenders: assert `-c core.fsmonitor=` is literally in argv for
# every one of the four calls (a passing sentinel test could in principle be
# a false green if the hook simply never ran for an unrelated reason).
# ---------------------------------------------------------------------------
def test_all_four_call_sites_pass_core_fsmonitor_hardening_flag(
    src_target: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)

    engine._git_listed(src_target)
    engine._gitlink_rels(src_target)
    discovery._origin(src_target)
    cli_mod.check_preconditions(src_target, force=False, allow_dirty=False)

    assert len(calls) == 4
    for cmd in calls:
        assert "core.fsmonitor=" in cmd, cmd
