"""Declared-command regeneration — plan-time state preflight (P04 D1/D5).

Regeneration outputs must be git-tracked and clean at plan time, refused
even under ``--allow-dirty`` (the functions here take no such flag at all):
the declared command overwrites the file wholesale, and git restores only
committed content, so uncommitted edits to a declared output have no
recoverable copy. The sink predicates (containment, no-follow regular file,
``st_nlink == 1``) run here too — an in-place-truncating regenerator on a
hardlinked output would corrupt the external inode, and unlike reset, no
``safe_write`` new-inode guarantee applies.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — git state reads on the target
from pathlib import Path

from template_press.rebrand.rules import Rules
from template_press.rebrand.safety import (
    SafetyError,
    assert_under_root,
    git_hardening_args,
    is_regular_lstat,
    scrubbed_git_env,
)


def _git_stdout(target: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        ["git", "-C", str(target), *git_hardening_args(), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    return result.stdout


def tracked_paths(target: Path) -> frozenset[str]:
    """POSIX rel paths git tracks — an index read (no clean/smudge filters)."""
    out = _git_stdout(target, "ls-files", "-z")
    return frozenset(p for p in out.split("\0") if p)


def preflight_regenerate_outputs(target: Path, rules: Rules) -> list[str]:
    """Problems that make a declared regeneration output unpressable.

    Empty list = every declared output is contained, a regular file
    (no-follow), sole-linked, git-tracked, and clean. Runs at plan time in
    SOURCE coordinates (before the rename pass moves anything), under the
    exit-2-nothing-written contract.
    """
    if not rules.regenerate:
        return []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.regenerate:
        prefix = f"regenerate output {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (outputs must be committed so git "
                "provides the undo path)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        st = os.lstat(path)
        if st.st_nlink > 1:
            problems.append(
                prefix + f"hardlinked (st_nlink={st.st_nlink}) — an in-place-"
                f"truncating regenerator would corrupt the external inode"
            )
            continue
        status = _git_stdout(target, "status", "--porcelain", "--", rule.file)
        if status.strip():
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (git restores only committed content)"
            )
    return problems
