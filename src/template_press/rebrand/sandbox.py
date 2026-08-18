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
  — the target TEXT is never rewritten (rewriting is apply's job) — and are
  followed ONLY once proven, in two CONSERVATIVE layers, to stay inside the
  target tree: pure string computation on the raw, unfollowed link text
  (``_link_text_is_safe``) rejects a leading ``/``, a backslash, a colon, or
  ANY ``..`` component outright — even a legitimate in-tree ``..`` hop,
  because normalizing first risks lexically erasing a pivot component
  before it can be checked — and an incremental no-follow ``lstat`` walk
  over every remaining component (``_dir_chain_is_safely_contained``)
  rejects a target reached through an in-tree PIVOT symlink or Windows
  junction — a tracked symlink or mount point whose OWN target points
  outside, which a lexically-safe-looking path could still cross. Neither
  layer ever follows an unverified symlink to check it, so a symlink
  pointing outside the target (a UNC share, an automount, anything that
  could hang or trigger network I/O to stat) can never be touched; a
  rejection under either layer costs only a broken-looking directory
  symlink on Windows (POSIX ignores ``target_is_directory`` entirely) —
  deliberately cheap next to the alternative;
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
import stat
import subprocess  # nosec B404 — sandbox git init/add/commit, all hardened `git -C`
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.config import assert_control_real
from template_press.rebrand.engine import copy_paths
from template_press.rebrand.pathing import symlink_target_posix
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    git_hardening_args,
    read_regular_nofollow,
    readlink_nofollow,
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


def _link_text_is_safe(link: str) -> bool:
    """True only if the raw, UNFOLLOWED symlink target text itself carries
    no escape or platform-anchor signal — checked before any join or
    normalization runs.

    Checked on the raw text, not the normalized ``target_posix``, because
    ``os.path.normpath`` (inside ``symlink_target_posix``) LEXICALLY
    collapses a ``..`` against a preceding component — `"pivot/../dir"`
    normalizes to `"dir"` — which would silently erase a pivot component
    before the containment walk below ever sees it. Any ``..`` anywhere in
    the link text is rejected outright here, even a legitimate in-tree
    up-then-down hop, because the text alone cannot distinguish the two
    cases and a rejected link only costs `target_is_directory=False`
    (Python's own default; POSIX ignores it entirely).

    A leading ``/``, a backslash, or a colon is rejected too:
    ``os.path.isabs()`` does not recognize Windows root- or drive-relative
    forms (``"\\external"``, ``"C:external"``) under POSIX semantics, so
    those are rejected directly on the raw characters instead of relying on
    ``isabs()``.
    """
    if link.startswith("/") or "\\" in link or ":" in link:
        return False
    return not any(part == ".." for part in link.split("/"))


def _dir_chain_is_safely_contained(target: Path, target_posix: str) -> bool:
    """True if EVERY component of ``target_posix`` — including its final
    one — is a real, non-symlink, non-junction node: an incremental,
    LEFT-TO-RIGHT, no-follow ``lstat`` walk.

    Deliberately NOT ``safety.assert_ancestors_real``/``assert_under_root``:
    both open with ``path.parent.resolve()``, which follows every ancestor
    symlink to compute the real parent — exactly the filesystem access this
    function exists to avoid. A symlink `link -> pivot/dir` can look
    lexically contained (``symlink_target_posix`` sees only the string
    ``pivot/dir``) while `pivot` is ITSELF a tracked symlink pointing
    outside the target (a UNC share, an automount) — ``.resolve()`` would
    follow straight through it.

    The walk covers the FINAL component too, not just its ancestors: for a
    single-component target text (`link -> pivot`, no further path under
    it), stopping one short of the end would check nothing at all and
    `pivot` itself — the direct destination — would go unverified. Checking
    it costs nothing when it genuinely is a plain directory (``lstat``
    reports it as neither a symlink nor a junction and the walk simply
    completes).

    The walk is safe against a pivot at any depth because each step's
    ``lstat`` only ever traverses through components THIS SAME WALK has
    already confirmed are real, non-symlink, non-junction directories: by
    the time component N is checked, components 0..N-1 are already proven
    safe, so resolving the path down to component N cannot pass through
    anything unverified. A symlink or junction found at any step ends the
    walk immediately, before its target is ever read or followed. Junctions
    are checked via ``Path.is_junction()`` because on Windows a directory
    junction is a mount-point reparse point, not an ``S_IFLNK`` node — a
    plain ``stat.S_ISLNK`` check does not see it; ``is_junction()`` is
    unconditionally ``False`` on POSIX, so this line is a no-op there.
    """
    cur = target
    for part in target_posix.split("/"):
        cur = cur / part
        try:
            st = cur.lstat()
        except OSError:
            return False  # fail closed: unreadable/missing component
        if stat.S_ISLNK(st.st_mode):
            return False  # a pivot — stop before it is ever followed
        if cur.is_junction():
            return False  # a Windows mount-point reparse point — same stop
    return True


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
        assert_ancestors_real(src, target)
        if rel.parent != Path("."):
            safe_mkdir(sandbox, rel.parent)
        if entry.kind == "file":
            # The descriptor reader refuses a changed or non-regular source.
            safe_write(sandbox, rel, read_regular_nofollow(src))
            added.append(rel.as_posix())
        elif entry.kind == "symlink":
            # Recreate VERBATIM: the target TEXT is never rewritten
            # (rewriting is apply's job; scanning never follows it for
            # content). Windows distinguishes file and directory symlinks:
            # a directory-target link created without target_is_directory
            # comes back as a broken file link there. `src.is_dir()` would
            # supply it by following the symlink — but this codebase never
            # follows a symlink whose target could be outside the target
            # tree (a UNC share, an automount, anything `stat`-able that
            # could hang or trigger network I/O), matching
            # `engine._retarget_planned_symlinks`'s own posture. Containment
            # is checked in two layers, CONSERVATIVELY, before `.is_dir()`
            # is ever allowed to touch the real filesystem: (1)
            # `_link_text_is_safe` rejects a leading `/`, a backslash, a
            # colon, or ANY `..` component in the raw UNFOLLOWED link text
            # (zero filesystem I/O) — even a legitimate in-tree `..` hop,
            # because normalizing first would risk lexically erasing a
            # pivot component before it can be checked; (2)
            # `_dir_chain_is_safely_contained` walks every component of the
            # normalized target and rejects one reached through an in-tree
            # PIVOT symlink or Windows junction — a tracked
            # `pivot -> /mnt/external` with `link -> pivot` (or
            # `link -> pivot/dir`) looks lexically safe to layer 1 but a
            # naive follow would still cross `pivot` to reach outside the
            # target. Either layer failing leaves
            # `target_is_directory=False` (Python's own default) rather
            # than following — the asymmetry is deliberate: a false
            # rejection costs only a broken-looking directory symlink on
            # Windows (POSIX ignores target_is_directory entirely), while a
            # false acceptance is the containment breach this exists to
            # prevent.
            link = readlink_nofollow(src)
            assert_ancestors_real(dest, sandbox)
            target_posix = symlink_target_posix(rel, link)
            safely_contained = _link_text_is_safe(
                link
            ) and _dir_chain_is_safely_contained(target, target_posix)
            target_is_directory = safely_contained and src.is_dir()
            os.symlink(link, dest, target_is_directory=target_is_directory)
            added.append(rel.as_posix())
        elif entry.kind == "gitlink":
            # Inner content is not enumerable from the superproject — make the
            # NAME scannable and record the path as unavailable.
            safe_mkdir(sandbox, rel)
            safe_write(sandbox, rel / _SUBMODULE_PLACEHOLDER, b"")
            added.append(rel.as_posix())
            unavailable.append(rel.as_posix())
        else:
            raise SafetyError(f"cannot materialize worktree node: {rel.as_posix()}")

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
