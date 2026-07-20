"""List-driven, ARG_MAX-safe, submodule-aware verify sandbox (Task 11).

``make_sandbox`` builds a faithful, isolated git copy of the target that
``press verify`` presses. The overriding invariant: EVERY git op and file
write lands inside the owned sandbox — NEVER the real target, cwd, or $HOME
(the 152-file-wipe lesson). It is achieved by construction, not convention:

* the control-path-symlink rejection (``assert_control_real``) runs FIRST, so
  a symlinked ``press/`` control dir/artifact is refused before any copy;
* the sandbox dir is ``dest_root/self`` and ``dest_root`` is re-validated with
  ``refuse_unsafe_root`` (defensive — Task 12 wraps the call in
  ``owned_sandbox``);
* every file write goes through ``safe_write``/``safe_mkdir`` (contained,
  no-follow, atomic); symlinks are recreated VERBATIM with ``os.symlink``
  (never followed, never rewritten — rewriting is apply's job);
* every git op is ``git -C <sandbox>`` (NEVER cwd) with a scrubbed +
  hardened env and a SYNTHETIC author/committer identity, and the add list is
  fed on STDIN via ``--pathspec-from-file=- --pathspec-file-nul`` (ARG_MAX-safe
  — never argv);
* a gitlink's inner content is not enumerable from the superproject, so the
  NAME is made scannable via a tracked placeholder and the path recorded in
  ``unavailable_submodules`` (Task 12 makes a non-empty list a NONZERO result,
  never a silent pass).
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — sandbox git init/add/commit, all hardened `git -C`
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.config import assert_control_real
from template_press.rebrand.engine import copy_paths
from template_press.rebrand.safety import (
    assert_ancestors_real,
    git_hardening_args,
    is_regular_lstat,
    refuse_unsafe_root,
    safe_mkdir,
    safe_write,
    scrubbed_git_env,
)

__all__ = ["Sandbox", "make_sandbox"]

# The commit is authored by a synthetic identity — never the user's git config
# — so a poisoned target cannot make the verify commit impersonate anyone and
# the sandbox needs no ambient ``user.name``/``user.email``.
_SYNTHETIC_IDENTITY: dict[str, str] = {
    "GIT_AUTHOR_NAME": "press-verify",
    "GIT_AUTHOR_EMAIL": "verify@localhost",
    "GIT_COMMITTER_NAME": "press-verify",
    "GIT_COMMITTER_EMAIL": "verify@localhost",
}

# A gitlink dir gets this tracked placeholder so its path components are in the
# sandbox and get scanned by name (submodule content is unavailable).
_SUBMODULE_PLACEHOLDER = ".press-submodule-unavailable"


@dataclass(frozen=True)
class Sandbox:
    """Result of :func:`make_sandbox`.

    ``path`` is the sandbox worktree (``dest_root/self``).
    ``unavailable_submodules`` lists the POSIX rel paths of gitlinks whose
    content could not be copied — a non-empty tuple makes the verify run
    NONZERO (Task 12), never a silent pass.
    """

    path: Path
    unavailable_submodules: tuple[str, ...]


def _run_git(
    sandbox: Path, env: dict[str, str], *args: str, stdin: bytes | None = None
) -> None:
    """Run one ``git -C <sandbox>`` op — scrubbed, hardened, contained.

    Every git invocation is pinned to the sandbox via ``-C`` (NEVER the process
    cwd), so no op can walk up into the real target or the checkout. Raises
    ``CalledProcessError`` on failure (propagates to Task 12).
    """
    subprocess.run(  # noqa: S603 # nosec B603 B607
        ["git", "-C", str(sandbox), *git_hardening_args(), *args],  # noqa: S607
        check=True,
        capture_output=True,
        env=env,
        input=stdin,
    )


def make_sandbox(target: Path, dest_root: Path) -> Sandbox:
    """Build a faithful, isolated git copy of ``target`` under ``dest_root``.

    ``dest_root`` is the already-validated owned root (Task 12 wraps this call
    in ``safety.owned_sandbox``). Returns a :class:`Sandbox`; raises
    ``ContainmentError`` (a ``SafetyError``/``ValueError``) if the control
    location is a symlink, or ``SafetyError`` if ``dest_root`` is unsafe.
    """
    # 1. Control-path-symlink rejection FIRST — before ANY copy — so a
    #    symlinked press/ control dir/artifact cannot redirect a write.
    assert_control_real(target)

    # 2. Owned sandbox dir (defensive re-validation of the root).
    refuse_unsafe_root(dest_root, target=target)
    sandbox = safe_mkdir(dest_root, "self")

    # 3. Materialize copy_paths faithfully — every write contained/no-follow.
    added: list[str] = []
    unavailable: list[str] = []
    for entry in copy_paths(target):
        rel = entry.rel
        src = target / rel
        dest = sandbox / rel
        if rel.parent != Path("."):
            safe_mkdir(sandbox, rel.parent)
        if entry.kind == "file":
            # Never follow: only an lstat-regular file is copied as bytes.
            if not is_regular_lstat(src):
                continue
            safe_write(sandbox, rel, src.read_bytes())
            added.append(rel.as_posix())
        elif entry.kind == "symlink":
            # Recreate VERBATIM: do not follow and do not rewrite the target
            # (rewriting is apply's job; scanning never follows).
            link = os.readlink(src)
            assert_ancestors_real(dest, sandbox)
            os.symlink(link, dest)
            added.append(rel.as_posix())
        elif entry.kind == "gitlink":
            # Inner content is not enumerable from the superproject — make the
            # NAME scannable and record the path as unavailable.
            safe_mkdir(sandbox, rel)
            safe_write(sandbox, rel / _SUBMODULE_PLACEHOLDER, b"")
            added.append(rel.as_posix())
            unavailable.append(rel.as_posix())

    # 4. Sandbox git — ALL ops `git -C <sandbox>`, scrubbed + hardened +
    #    synthetic identity; the add list is fed on STDIN (ARG_MAX-safe).
    env = scrubbed_git_env(extra=_SYNTHETIC_IDENTITY)
    _run_git(sandbox, env, "init", "-q")
    _run_git(
        sandbox,
        env,
        "add",
        "-f",
        "--pathspec-from-file=-",
        "--pathspec-file-nul",
        # ``surrogateescape`` mirrors how ``copy_paths`` decoded the git path
        # bytes: a non-UTF-8 tracked filename round-trips back to its original
        # bytes here instead of raising ``UnicodeEncodeError`` (a crash that
        # would escape the exit-code taxonomy).
        stdin="\0".join(added).encode("utf-8", "surrogateescape"),
    )
    _run_git(
        sandbox,
        env,
        "commit",
        "-q",
        "-m",
        "press-verify sandbox",
        "--no-verify",
        "--allow-empty",
    )
    return Sandbox(sandbox, tuple(unavailable))
