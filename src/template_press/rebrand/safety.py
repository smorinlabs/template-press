"""Safe-I/O primitives — the Defensive-Hardening foundation (Task 0.5).

Overriding invariant: *nothing is written, renamed, or deleted outside the
intended root* — the target for rebrand, the sandbox for verify — in
production or in tests. Every file write, rename, mkdir, git call, and scan in
the engine and verifier routes through these primitives instead of raw
``write_text`` / ``rename`` / ``subprocess`` / ``open``.

Guards implemented here (see the plan's Defensive Hardening section):

* **G2 / G2+** ``SafeRelPath`` — typed gate rejecting empty / ``.`` / ``..`` /
  absolute / rooted / drive / UNC / noncanonical / ``.git`` (casefold + 8.3
  shortname + trailing dot/space) relative paths.
* **G3 / G3+** ``assert_under_root`` + ``safe_write`` / ``safe_rename`` /
  ``safe_mkdir`` — containment (no ancestor symlink, resolves under root),
  no-follow, atomic (temp + ``os.replace`` = new inode = hardlink-safe), and
  ``st_nlink > 1`` refusal for tracked/target sinks.
* **G4** ``write_control`` — sink-local re-check immediately before each
  control-artifact write (D8 applied per write, not once at preflight).
* **G5 / G5+** ``scrubbed_git_env`` / ``scrubbed_uv_env`` / ``git_hardening_args``
  — neutralize a poisoned ``GIT_DIR`` / global config / ``UV_*`` and disable
  on-target ``core.fsmonitor`` / ``core.hooksPath`` / ext transport. Residual:
  a repo-local clean/smudge filter driver cannot be disabled by name via
  ``-c`` (see ``git_hardening_args`` docstring), so on-target callers should
  prefer index/object reads (``git ls-files`` / ``git ls-tree`` /
  ``git cat-file`` / ``git write-tree``) over working-tree-reading
  ``git status`` where feasible.
* **G6** ``owned_sandbox`` / ``refuse_unsafe_root`` — a ``mkdtemp`` 0700 root,
  disjoint from the target, cleaned up as the only owned child.
* **G8** ``is_regular_lstat`` — scan only ``lstat``-regular files (no
  FIFO/socket/device hang, no symlink follow).

The concurrent-local ancestor-swap TOCTOU (between the lstat-walk and
``os.replace``/``os.rename``) is a documented residual: leaf writes are atomic
and static hostile ancestors are caught by the pre-write walk, but fully
closing it would need ``openat``/``dir_fd`` no-follow handles.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

__all__ = [
    "ContainmentError",
    "HardlinkError",
    "SafeRelPath",
    "SafetyError",
    "UnsafePathError",
    "assert_under_root",
    "git_hardening_args",
    "is_regular_lstat",
    "owned_sandbox",
    "refuse_unsafe_root",
    "safe_mkdir",
    "safe_rename",
    "safe_write",
    "scrubbed_git_env",
    "scrubbed_uv_env",
    "write_control",
]


class SafetyError(Exception):
    """Base class for every containment / safe-I/O violation."""


class UnsafePathError(SafetyError, ValueError):
    """A relative path failed the ``SafeRelPath`` gate (G2 / G2+)."""


class ContainmentError(SafetyError, ValueError):
    """A sink would escape its root (symlink ancestor or resolves outside)."""


class HardlinkError(SafetyError, ValueError):
    """A tracked/target sink has ``st_nlink > 1`` (G3 / G3+ / G5)."""


# ---------------------------------------------------------------------------
# G2 / G2+ — SafeRelPath
# ---------------------------------------------------------------------------
def _is_dotgit(part: str) -> bool:
    """Whether ``part`` normalizes to ``.git``.

    Casefolds, strips trailing dots/spaces (Windows), and recognizes 8.3
    shortnames (which drop the leading dot): ``.GIT``, ``.Git``, ``.git.``,
    ``.git`` (trailing space), and ``git~1`` all normalize to ``.git``. A bare
    ``git`` directory (no dot, no shortname suffix) is ordinary content.
    """
    p = part.rstrip(" .").casefold()
    if p == ".git":
        return True
    if "~" in p:
        base = p.split("~", 1)[0]
        return base in ("git", ".git")
    return False


class SafeRelPath:
    """A validated, canonical, root-relative path — a pressed template is
    third-party input, so every ``git ls-files`` entry and every renamed path
    is forced through this gate (G2 / G2+). Construction raises
    ``UnsafePathError`` on anything unsafe.
    """

    __slots__ = ("_parts",)

    def __init__(self, raw: str | os.PathLike[str]) -> None:
        text = os.fspath(raw)
        if not isinstance(text, str):  # pragma: no cover - defensive
            raise UnsafePathError(f"path must be str-like: {raw!r}")
        if text == "":
            raise UnsafePathError("path must not be empty")
        if "\\" in text:
            raise UnsafePathError(f"backslash (Windows/UNC) not allowed: {text!r}")
        if ":" in text:
            raise UnsafePathError(f"drive/colon not allowed: {text!r}")
        if text.startswith("/"):
            raise UnsafePathError(f"absolute/rooted path not allowed: {text!r}")
        parts = text.split("/")
        for part in parts:
            if part == "":
                raise UnsafePathError(
                    f"empty component (doubled/trailing separator): {text!r}"
                )
            if part in (".", ".."):
                raise UnsafePathError(f"'.'/'..' component not allowed: {text!r}")
            if _is_dotgit(part):
                raise UnsafePathError(f"'.git' component not allowed: {text!r}")
        self._parts: tuple[str, ...] = tuple(parts)

    @property
    def parts(self) -> tuple[str, ...]:
        return self._parts

    def as_posix(self) -> str:
        return "/".join(self._parts)

    def as_path(self) -> PurePosixPath:
        return PurePosixPath(*self._parts)

    def __fspath__(self) -> str:
        return self.as_posix()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SafeRelPath({self.as_posix()!r})"


# ---------------------------------------------------------------------------
# G3 — containment
# ---------------------------------------------------------------------------
def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def assert_under_root(path: Path, root: Path) -> None:
    """Assert ``path`` is safely contained in ``root`` (G3).

    Two independent checks:

    1. ``path.parent.resolve()`` (which follows every ancestor symlink) is
       under ``root`` — catches ``..`` and symlink-ancestor escapes.
    2. No path component from ``root`` down to ``path`` is a symlink — a
       literal ``lstat`` walk, so a symlink pointing *back inside* the root is
       still rejected. The leaf may be absent (a write target) but must not be
       a symlink itself (no-follow).
    """
    root_r = root.resolve()
    parent_r = path.parent.resolve()
    if not _is_within(parent_r, root_r):
        raise ContainmentError(f"sink parent {parent_r} resolves outside root {root_r}")
    rel_parts = _literal_rel_parts(path, root, root_r)
    cur = root_r
    for part in rel_parts:
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            break  # remaining (leaf) components do not exist yet
        if stat.S_ISLNK(st.st_mode):
            raise ContainmentError(f"symlink component in sink path: {cur}")


def _literal_rel_parts(path: Path, root: Path, root_r: Path) -> tuple[str, ...]:
    """Literal (no-follow) parts of ``path`` relative to ``root``.

    Tries the resolved and unresolved root as a literal prefix (macOS reports
    tmp dirs under both ``/var`` and ``/private/var``); the resolved-parent
    check upstream has already proven containment.
    """
    for base in (root_r, root):
        try:
            return path.relative_to(base).parts
        except ValueError:
            continue
    raise ContainmentError(f"{path} is not literally under {root_r}")


def _reject_hardlink(path: Path) -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if st.st_nlink > 1:
        raise HardlinkError(
            f"refusing to write hardlinked sink (st_nlink={st.st_nlink}): {path}"
        )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via temp + ``os.replace`` (new inode).

    The temp file is created in the already-validated parent (same
    filesystem), so ``os.replace`` is atomic and never edits an existing
    inode in place — a hardlinked sink's other links keep the old content.
    """
    parent = path.parent
    os.makedirs(parent, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".press-tmp-", suffix="~")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _as_bytes(data: str | bytes) -> bytes:
    return data if isinstance(data, bytes) else data.encode("utf-8")


def safe_write(
    root: Path,
    rel: str | os.PathLike[str] | SafeRelPath,
    data: str | bytes,
    *,
    refuse_hardlink: bool = True,
) -> Path:
    """Atomically write ``root/rel`` with full containment (G3 / G3+).

    Validates ``rel`` (``SafeRelPath``), asserts containment + no symlink
    ancestor/leaf, refuses a hardlinked target (``st_nlink > 1``) unless
    ``refuse_hardlink=False``, then writes a new inode via temp + rename.
    """
    rel_sp = rel if isinstance(rel, SafeRelPath) else SafeRelPath(os.fspath(rel))
    root_r = root.resolve()
    path = root_r / Path(*rel_sp.parts)
    assert_under_root(path, root_r)
    if refuse_hardlink:
        _reject_hardlink(path)
    _atomic_write_bytes(path, _as_bytes(data))
    return path


def write_control(
    root: Path,
    rel: str | os.PathLike[str] | SafeRelPath,
    text: str,
) -> Path:
    """Write one control artifact, re-checking containment at the sink (G4).

    D8 is enforced *per write* (not once at preflight): the no-ancestor-symlink
    + resolves-under-root check runs immediately before this write. The atomic
    temp + rename makes the write hardlink-safe (a new inode), so even a
    hostile hardlinked control file leaves its outside link untouched.
    """
    return safe_write(root, rel, text, refuse_hardlink=False)


def safe_mkdir(root: Path, rel: str | os.PathLike[str] | SafeRelPath) -> Path:
    """Create ``root/rel`` (with parents) under full containment (G3)."""
    rel_sp = rel if isinstance(rel, SafeRelPath) else SafeRelPath(os.fspath(rel))
    root_r = root.resolve()
    path = root_r / Path(*rel_sp.parts)
    assert_under_root(path, root_r)
    os.makedirs(path, exist_ok=True)
    return path


def safe_rename(
    root: Path,
    src_rel: str | os.PathLike[str] | SafeRelPath,
    dst_rel: str | os.PathLike[str] | SafeRelPath,
) -> None:
    """Rename ``root/src_rel`` -> ``root/dst_rel`` under containment (G3).

    Both endpoints are validated and checked for symlink ancestors; the
    destination's parent is created (contained) before ``os.rename``.
    """
    src_sp = (
        src_rel if isinstance(src_rel, SafeRelPath) else SafeRelPath(os.fspath(src_rel))
    )
    dst_sp = (
        dst_rel if isinstance(dst_rel, SafeRelPath) else SafeRelPath(os.fspath(dst_rel))
    )
    root_r = root.resolve()
    src = root_r / Path(*src_sp.parts)
    dst = root_r / Path(*dst_sp.parts)
    assert_under_root(src, root_r)
    assert_under_root(dst, root_r)
    os.makedirs(dst.parent, exist_ok=True)
    os.rename(src, dst)


# ---------------------------------------------------------------------------
# G5 / G5+ — subprocess env scrub + on-target git hardening
# ---------------------------------------------------------------------------
GIT_ENV_UNSET: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def scrubbed_git_env(
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A git-safe environment (G5): global/system config neutralized and every
    location override (``GIT_DIR`` etc.) cleared so a poisoned env cannot
    redirect an on-target git op.
    """
    env = dict(os.environ if base is None else base)
    for key in GIT_ENV_UNSET:
        env.pop(key, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


def scrubbed_uv_env(
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A uv-safe environment (G5): every ``UV_*`` override (working dir, cache,
    index, ...) is dropped so ``uv lock`` cannot be steered off the target.
    """
    env = dict(os.environ if base is None else base)
    for key in [k for k in env if k.startswith("UV_")]:
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def git_hardening_args() -> list[str]:
    """``-c`` flags for EVERY on-target git invocation (G5+).

    The target's own ``.git/config`` is attacker-controlled input. These flags
    neutralize four specific on-target surfaces: a committed
    ``core.fsmonitor`` hook, a committed ``core.hooksPath`` redirect, the
    ``ext::`` transport, and an unwanted GPG-signing prompt on commit.

    Residual (NOT covered by these flags): a repo-local ``.git/config``
    ``[filter "<name>"] clean = <cmd>`` / ``smudge = <cmd>`` definition. Git
    filter drivers are arbitrarily named, so no fixed set of ``-c`` overrides
    can disable one by name — there is no wildcard equivalent to
    ``core.fsmonitor=`` for filters. If the target's working tree has a
    stat-mismatched file wired to such a filter, a working-tree-reading
    command (e.g. ``git status``) can still execute attacker-controlled code
    on this machine. Global/system filter *definitions* are already
    neutralized by ``scrubbed_git_env`` (``GIT_CONFIG_GLOBAL`` /
    ``GIT_CONFIG_SYSTEM`` redirected to ``os.devnull``); only a repo-local
    definition survives, and only when it is exercised by a working-tree
    read.

    Design note for callers (see also the module docstring): on-target
    enumeration and read-only checks should PREFER index/object reads
    (``git ls-files``, ``git ls-tree``, ``git cat-file``, ``git write-tree``)
    over working-tree-reading commands (``git status``) wherever the check
    can be expressed that way, since index/object reads do not invoke
    clean/smudge filters. Treat ``git_hardening_args()`` as covering
    fsmonitor/hooksPath/ext-transport/gpgsign only — not as blanket cover for
    a working-tree read on a hostile target.
    """
    return [
        "-c",
        "core.fsmonitor=",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "commit.gpgsign=false",
    ]


# ---------------------------------------------------------------------------
# G6 — owned sandbox
# ---------------------------------------------------------------------------
def refuse_unsafe_root(root: Path, *, target: Path | None = None) -> None:
    """Refuse a sandbox root that is dangerous to own or clean up (G6).

    Rejects the filesystem root, ``$HOME``, the cwd, any ancestor of the cwd /
    home / target, a symlinked root, or a root that is not disjoint from the
    target.
    """
    root_r = root.resolve()
    if os.path.islink(root):
        raise SafetyError(f"sandbox root must not be a symlink: {root}")
    forbidden = {
        Path(os.path.abspath(os.sep)).resolve(),
        Path.home().resolve(),
        Path.cwd().resolve(),
    }
    if root_r in forbidden:
        raise SafetyError(f"refusing dangerous sandbox root: {root_r}")
    for anchor in (Path.cwd().resolve(), Path.home().resolve()):
        if _is_within(anchor, root_r):
            raise SafetyError(f"sandbox root {root_r} is an ancestor of {anchor}")
    if target is not None:
        target_r = target.resolve()
        if _is_within(root_r, target_r) or _is_within(target_r, root_r):
            raise SafetyError(
                f"sandbox root {root_r} is not disjoint from target {target_r}"
            )


def _owned_rmtree(root: Path) -> None:
    """Remove ``root`` only if it is our owned ``press-verify-*`` temp child."""
    if not root.exists():
        return
    root_r = root.resolve()
    tmp_r = Path(tempfile.gettempdir()).resolve()
    if root.name.startswith("press-verify-") and _is_within(root_r, tmp_r):
        shutil.rmtree(root)
    else:  # pragma: no cover - defensive
        raise SafetyError(f"refusing to rmtree non-owned path: {root}")


@contextmanager
def owned_sandbox(target: Path | None = None) -> Iterator[Path]:
    """Yield a private 0700 sandbox root created via ``mkdtemp`` (G6).

    The root is created internally (never a caller-supplied ``dest_root``),
    disjoint from ``target``, and torn down in ``finally`` as the only owned
    child — ``shutil.rmtree`` never touches anything else.
    """
    root = Path(tempfile.mkdtemp(prefix="press-verify-"))
    try:
        os.chmod(root, 0o700)
        refuse_unsafe_root(root, target=target)
        yield root.resolve()
    finally:
        _owned_rmtree(root)


# ---------------------------------------------------------------------------
# G8 — scanner input discipline
# ---------------------------------------------------------------------------
def is_regular_lstat(path: Path | str) -> bool:
    """True only for a regular file, using ``lstat`` (no follow, no open).

    A symlink, directory, submodule/gitlink dir (G7), FIFO, socket, or device
    returns False — so the byte-scan never follows a link and never blocks on
    a FIFO/device.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)
