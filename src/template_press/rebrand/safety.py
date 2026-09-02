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
* **G5 / G5+** ``scrubbed_git_env`` / ``git_hardening_args``
  — neutralize a poisoned ``GIT_DIR`` / global config and disable
  on-target ``core.fsmonitor`` / ``core.hooksPath`` / ext transport. Residual:
  a repo-local clean/smudge filter driver cannot be disabled by name via
  ``-c`` (see ``git_hardening_args`` docstring), so on-target callers should
  prefer index/object reads (``git ls-files`` / ``git ls-tree`` /
  ``git cat-file`` / ``git write-tree``) over working-tree-reading
  ``git status`` where feasible.
* **G6** ``owned_sandbox`` / ``refuse_unsafe_root`` — a ``mkdtemp`` 0700 root,
  disjoint from the target, cleaned up as the only owned child.
* **G8** ``read_regular_nofollow`` / ``is_regular_lstat`` — scan only regular
  files through descriptor-relative, no-follow reads on POSIX (no
  FIFO/socket/device hang, no symlink or swapped-ancestor traversal).

The concurrent-local ancestor-swap TOCTOU (between the lstat-walk and
``os.replace``/``os.rename``) is a documented residual: leaf writes are atomic
and static hostile ancestors are caught by the pre-write walk, but fully
closing it would need ``openat``/``dir_fd`` no-follow handles.
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

__all__ = [
    "AtomicRenameUnavailableError",
    "ContainmentError",
    "HardlinkError",
    "NonRegularFileError",
    "RenameClosureUnauthorized",
    "SafeRelPath",
    "SafetyError",
    "UnsafePathError",
    "assert_ancestors_real",
    "assert_under_root",
    "git_hardening_args",
    "is_regular_lstat",
    "owned_sandbox",
    "read_regular_nofollow",
    "readlink_nofollow",
    "refuse_unsafe_root",
    "rename_noreplace",
    "rename_noreplace_best_effort",
    "require_rename_noreplace_host_support",
    "require_rename_noreplace_support",
    "safe_mkdir",
    "safe_rename",
    "safe_write",
    "scrubbed_git_env",
    "write_control",
]


class SafetyError(Exception):
    """Base class for every containment / safe-I/O violation."""


class AtomicRenameUnavailableError(SafetyError):
    """The host or target filesystem lacks the required rename guarantee."""


class UnsafePathError(SafetyError, ValueError):
    """A relative path failed the ``SafeRelPath`` gate (G2 / G2+)."""


class ContainmentError(SafetyError, ValueError):
    """A sink would escape its root (symlink ancestor or resolves outside)."""


class HardlinkError(SafetyError, ValueError):
    """A tracked/target sink has ``st_nlink > 1`` (G3 / G3+ / G5)."""


class NonRegularFileError(SafetyError):
    """A no-follow read observed a non-regular leaf before opening it."""


class RenameClosureUnauthorized(SafetyError):  # noqa: N818 - spec-named (E2)
    """One rename-prefix closure walk carried unauthorized nodes (E2).

    Aggregates every node absent from the surface inventory and every
    uninventoried empty directory found during a single closure walk, instead
    of refusing on the first one hit. Structural refusals (a missing node, an
    unreadable directory, or an inventory-kind mismatch) and the gitlink
    pre-check are unaffected — those stay immediate raises of ``SafetyError``
    and never reach this aggregation.
    """

    code = "rename_closure_unauthorized"

    def __init__(
        self,
        source_prefix: str,
        findings: tuple[tuple[str, str], ...],
        phase: str,
    ) -> None:
        cap = 20
        total = len(findings)
        rendered = sorted(findings)[:cap]
        truncated = total > cap
        lines = [
            f"rename prefix {source_prefix!r} would carry {total} node(s) "
            f"absent from the authorized surface inventory or as an "
            f"uninventoried empty directory (phase={phase!r}):"
        ]
        lines.extend(f"  - {kind}: {path!r}" for kind, path in rendered)
        if truncated:
            lines.append(f"  … ({total - cap} more)")
        super().__init__("\n".join(lines))
        self.source_prefix = source_prefix
        self.findings = tuple(findings)
        self.total = total
        self.truncated = truncated
        self.phase = phase

    def remedy_argv(self, target: Path) -> tuple[list[str], list[str]]:
        """Literal-pathspec ``git clean`` argv to inspect/remove the prefix.

        Both scoped to ``-d`` (directories) and ``-X`` (ignored files only —
        never ``-x``, which would also sweep untracked-but-not-ignored
        content). Broader than the specific paths in ``findings``: ``git
        clean`` operates on everything ignored under ``source_prefix``, not
        just the nodes this refusal listed.
        """
        base = ["git", "--literal-pathspecs", "-C", str(target), "clean"]
        preview = [*base, "-ndX", "--", self.source_prefix]
        remove = [*base, "-fdX", "--", self.source_prefix]
        return preview, remove


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
        literal_posix_path = os.name != "nt" and not isinstance(raw, str)
        text = os.fspath(raw)
        if not isinstance(text, str):  # pragma: no cover - defensive
            raise UnsafePathError(f"path must be str-like: {raw!r}")
        if text == "":
            raise UnsafePathError("path must not be empty")
        # Normalize Windows-style separators FIRST, then validate the
        # forward-slash form. The tool's own Path constants (e.g.
        # ``press/press-receipt.toml``, ``src/demo_widget``) render via
        # os.fspath with ``\`` on Windows, so ``\`` must be treated as a path
        # separator — not rejected outright. Every escape still fires on the
        # normalized text: ``\\server\share`` -> ``//server/share`` (absolute),
        # ``C:\x`` -> ``C:/x`` (colon), ``..\x`` -> ``../x`` (dotdot),
        # ``a\.git\b`` -> ``a/.git/b`` (.git).
        if not literal_posix_path:
            text = text.replace("\\", "/")
        if not literal_posix_path and ":" in text:
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


def assert_ancestors_real(path: Path, root: Path) -> None:
    """Assert every ANCESTOR directory of ``path`` (root-inclusive down to, but
    EXCLUDING, the leaf) is real — a no-follow ``lstat`` walk that TOLERATES a
    symlink leaf.

    Unlike ``assert_under_root`` (which rejects a symlink leaf), this permits
    the leaf itself to be a symlink — moving or retargeting a token-bearing
    symlink is legitimate — while still refusing a symlinked ANCESTOR, so
    ``os.unlink`` / ``os.rename`` / ``os.symlink`` on ``path`` cannot traverse a
    symlinked ancestor out of ``root``. A root-level leaf (no ancestors under
    ``root``) always passes.
    """
    root_r = root.resolve()
    parent_r = path.parent.resolve()  # follows ancestor symlinks — an escaping
    if not _is_within(parent_r, root_r):  # ancestor lands outside the root
        raise ContainmentError(f"sink parent {parent_r} resolves outside root {root_r}")
    rel_parts = _literal_rel_parts(path, root, root_r)
    cur = root_r
    for part in rel_parts[:-1]:  # ancestors ONLY — the leaf is tolerated
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            break  # remaining (leaf-side) components do not exist yet
        if stat.S_ISLNK(st.st_mode):
            raise ContainmentError(f"symlink ancestor in sink path: {cur}")


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


def _read_descriptor(descriptor: int) -> bytes:
    data = bytearray()
    while chunk := os.read(descriptor, 1024 * 1024):
        data.extend(chunk)
    return bytes(data)


def _lstat_absolute_nofollow(path: Path) -> os.stat_result:
    """Fresh literal stat through no-follow directory descriptors."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | os.O_DIRECTORY
    parts = path.parts
    if len(parts) < 2:
        raise SafetyError(f"no-follow stat requires a leaf path: {path}")
    parent_fd = os.open(path.anchor, directory_flags)
    try:
        for part in parts[1:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        return os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def _read_regular_openat(path: Path) -> bytes:
    """Read an absolute POSIX path through no-follow directory descriptors."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | os.O_DIRECTORY
    parts = path.parts
    if len(parts) < 2:
        raise SafetyError(f"regular-file read requires a leaf path: {path}")
    parent_fd = os.open(path.anchor, directory_flags)
    try:
        for part in parts[1:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        leaf_flags = flags | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(parts[-1], leaf_flags, dir_fd=parent_fd)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise SafetyError(f"no-follow read source is not regular: {path}")
            data = _read_descriptor(descriptor)
            try:
                current = _lstat_absolute_nofollow(path)
            except OSError as exc:
                raise SafetyError(f"read source changed while reading: {path}") from exc
            if not stat.S_ISREG(current.st_mode) or not os.path.samestat(
                opened, current
            ):
                raise SafetyError(f"read source changed while reading: {path}")
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _read_regular_checked_path(path: Path) -> bytes:
    """Fallback for platforms without descriptor-relative ``open`` support.

    The handle is validated against a fresh literal ``lstat`` after bytes are
    consumed. A concurrent pathname change makes the read refuse.
    """

    _assert_absolute_ancestors_real(path)
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise NonRegularFileError(f"no-follow read source is not regular: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        data = _read_descriptor(descriptor)
        _assert_absolute_ancestors_real(path)
        after = os.lstat(path)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, after):
            raise SafetyError(f"read source changed while reading: {path}")
        return data
    finally:
        os.close(descriptor)


def _assert_absolute_ancestors_real(path: Path) -> None:
    """Refuse a symlink or non-directory in an absolute path's ancestors."""

    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current /= part
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SafetyError(f"non-real ancestor in read source: {current}")


def read_regular_nofollow(path: Path) -> bytes:
    """Read one regular file without following a leaf or ancestor symlink.

    POSIX walks from the filesystem root with ``openat``-style ``dir_fd``
    calls and ``O_NOFOLLOW`` on every component. Other platforms use a
    checked-handle fallback and refuse if the opened handle no longer matches
    the literal leaf.
    """

    absolute = path.absolute()
    if (
        os.name != "nt"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    ):
        return _read_regular_openat(absolute)
    return _read_regular_checked_path(absolute)


def _readlink_openat(path: Path) -> str:
    """Read one POSIX symlink through a no-follow parent descriptor."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | os.O_DIRECTORY
    parts = path.parts
    if len(parts) < 2:
        raise SafetyError(f"no-follow readlink requires a leaf path: {path}")
    parent_fd = os.open(path.anchor, directory_flags)
    try:
        for part in parts[1:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode):
            raise SafetyError(f"no-follow readlink source is not a symlink: {path}")
        link = os.readlink(parts[-1], dir_fd=parent_fd)
        try:
            current = _lstat_absolute_nofollow(path)
        except OSError as exc:
            raise SafetyError(f"readlink source changed while reading: {path}") from exc
        if not stat.S_ISLNK(current.st_mode) or not os.path.samestat(before, current):
            raise SafetyError(f"readlink source changed while reading: {path}")
        return link
    finally:
        os.close(parent_fd)


def _readlink_checked_path(path: Path) -> str:
    """Checked fallback for platforms without descriptor-relative readlink."""

    _assert_absolute_ancestors_real(path)
    before = os.lstat(path)
    if not stat.S_ISLNK(before.st_mode):
        raise SafetyError(f"no-follow readlink source is not a symlink: {path}")
    link = os.readlink(path)
    _assert_absolute_ancestors_real(path)
    after = os.lstat(path)
    if not stat.S_ISLNK(after.st_mode) or not os.path.samestat(before, after):
        raise SafetyError(f"readlink source changed while reading: {path}")
    return link


def readlink_nofollow(path: Path) -> str:
    """Read one symlink string without following its leaf or ancestors."""

    absolute = path.absolute()
    if (
        os.name != "nt"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.readlink in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    ):
        return _readlink_openat(absolute)
    return _readlink_checked_path(absolute)


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
    rel_sp = rel if isinstance(rel, SafeRelPath) else SafeRelPath(rel)
    root_r = root.resolve()
    path = root_r / Path(*rel_sp.parts)
    assert_under_root(path, root_r)
    if refuse_hardlink:
        _reject_hardlink(path)
    _atomic_write_bytes(path, _as_bytes(data))
    return path


def chmod_nofollow(path: Path, mode: int) -> None:
    """Restore permission bits on the just-written inode without following
    a symlink swapped in at ``path`` after the atomic replace: open
    O_NOFOLLOW and fchmod the descriptor (a swapped symlink makes the open
    itself fail loudly, aborting the press). Windows — no fchmod, trivial
    mode bits, and no O_NOFOLLOW — falls back to a plain chmod.
    """
    if not hasattr(os, "fchmod") or not hasattr(os, "O_NOFOLLOW"):
        os.chmod(path, mode)
        return
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


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
    rel_sp = rel if isinstance(rel, SafeRelPath) else SafeRelPath(rel)
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
    src_sp = src_rel if isinstance(src_rel, SafeRelPath) else SafeRelPath(src_rel)
    dst_sp = dst_rel if isinstance(dst_rel, SafeRelPath) else SafeRelPath(dst_rel)
    root_r = root.resolve()
    src = root_r / Path(*src_sp.parts)
    dst = root_r / Path(*dst_sp.parts)
    assert_under_root(src, root_r)
    assert_under_root(dst, root_r)
    os.makedirs(dst.parent, exist_ok=True)
    os.rename(src, dst)


def _rename_noreplace_unchecked(src: Path, dst: Path) -> None:
    """Invoke the host primitive without first probing its filesystem."""

    if os.name == "nt":
        # Windows os.rename already fails when the destination exists.
        os.rename(src, dst)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    src_bytes = os.fsencode(src)
    dst_bytes = os.fsencode(dst)
    if sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise AtomicRenameUnavailableError(
                f"atomic no-replace rename is unsupported on {sys.platform}"
            )
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(src_bytes, dst_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise AtomicRenameUnavailableError(
                "atomic no-replace rename is unavailable on this host"
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, src_bytes, -100, dst_bytes, 0x00000001)
    else:
        raise AtomicRenameUnavailableError(
            f"atomic no-replace rename is unsupported on {sys.platform}"
        )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(dst))


def require_rename_noreplace_host_support() -> None:
    """Check for a host primitive without touching the target filesystem."""

    if os.name == "nt":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and getattr(libc, "renamex_np", None) is not None:
        return
    if (
        sys.platform.startswith("linux")
        and getattr(libc, "renameat2", None) is not None
    ):
        return
    raise AtomicRenameUnavailableError(
        f"atomic no-replace rename is unsupported on {sys.platform}"
    )


def _probe_rename_noreplace_call(src: Path, dst: Path, source: Path) -> None:
    """Run one native probe move and classify only capability-related errors."""

    try:
        _rename_noreplace_unchecked(src, dst)
    except AtomicRenameUnavailableError:
        raise
    except FileExistsError:
        raise
    except OSError as exc:
        unsupported_errors = {
            errno.EINVAL,
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        error_type = (
            AtomicRenameUnavailableError
            if exc.errno in unsupported_errors
            else SafetyError
        )
        raise error_type(
            f"atomic no-replace rename probe failed for {source}: {exc}"
        ) from exc


def require_rename_noreplace_support(source: Path) -> None:
    """Probe atomic no-replacement rename beside ``source`` and clean up."""

    try:
        with tempfile.TemporaryDirectory(
            prefix=".press-rename-probe-", dir=source.parent
        ) as raw_probe:
            probe = Path(raw_probe)
            probe_source = probe / "source"
            probe_destination = probe / "destination"
            probe_source.write_bytes(b"source\n")
            _probe_rename_noreplace_call(probe_source, probe_destination, source)
            if (
                probe_source.exists()
                or probe_source.is_symlink()
                or read_regular_nofollow(probe_destination) != b"source\n"
            ):
                raise AtomicRenameUnavailableError(
                    f"atomic no-replace rename probe produced an invalid result "
                    f"beside {source}"
                )

            occupied_source = probe / "occupied-source"
            occupied_source.write_bytes(b"new source\n")
            try:
                _probe_rename_noreplace_call(occupied_source, probe_destination, source)
            except FileExistsError:
                pass
            else:
                raise AtomicRenameUnavailableError(
                    f"atomic no-replace rename probe replaced an occupied "
                    f"destination beside {source}"
                )
            if (
                read_regular_nofollow(occupied_source) != b"new source\n"
                or read_regular_nofollow(probe_destination) != b"source\n"
            ):
                raise AtomicRenameUnavailableError(
                    f"atomic no-replace rename probe changed protected content "
                    f"beside {source}"
                )
    except AtomicRenameUnavailableError:
        raise
    except SafetyError:
        raise
    except OSError as exc:
        raise SafetyError(
            f"atomic no-replace rename probe failed for {source}: {exc}"
        ) from exc


def rename_noreplace(src: Path, dst: Path) -> None:
    """Atomically rename ``src`` to an absent ``dst`` without replacement.

    Python's POSIX ``os.rename`` overwrites an existing destination. The
    rebrand planner treats occupancy as a refusal, so use each supported
    platform's atomic no-replace primitive and fail closed elsewhere.
    """

    _rename_noreplace_unchecked(src, dst)


def rename_noreplace_best_effort(src: Path, dst: Path) -> None:
    """Rename after an immediate occupancy check, without atomic protection.

    On POSIX, another process can create ``dst`` between ``lstat`` and
    ``os.rename``; the rename may then replace it. Callers must expose that
    risk and require an explicit safety override before using this fallback.
    """

    try:
        os.lstat(dst)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(f"rename destination already exists: {dst}")
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
    "GIT_EXEC_PATH",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
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
    for key in tuple(env):
        if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            env.pop(key, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
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


def _on_rmtree_error(
    func: Callable[..., object], path: str, exc: BaseException
) -> None:
    """``shutil.rmtree`` ``onexc`` handler: clear the read-only bit and retry.

    Git marks loose objects under ``.git/objects`` read-only; on Windows
    ``shutil.rmtree`` cannot unlink a read-only file (WinError 5 /
    ``PermissionError``) and would otherwise raise out of the sandbox teardown.
    Clearing the write bit and re-running the failing op (``func``) removes it.
    Reached ONLY for entries WITHIN the already-guarded owned tree as rmtree
    walks it, so the owned-path guard in ``_owned_rmtree`` is unaffected.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _owned_rmtree(root: Path) -> None:
    """Remove ``root`` only if it is our owned ``press-verify-*`` temp child."""
    if not root.exists():
        return
    root_r = root.resolve()
    tmp_r = Path(tempfile.gettempdir()).resolve()
    if root.name.startswith("press-verify-") and _is_within(root_r, tmp_r):
        shutil.rmtree(root, onexc=_on_rmtree_error)
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
