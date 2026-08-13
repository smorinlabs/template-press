"""One Git-backed, kind-tagged inventory of an external target tree.

The inventory records raw path facts. Copy, rewrite, rename, doctor, verifier,
and preflight coverage remain explicit selectors above those facts so one
consumer cannot silently change another consumer's policy.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess  # nosec B404 -- hardened Git reads of an untrusted target
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from template_press.rebrand.safety import (
    SafeRelPath,
    SafetyError,
    git_hardening_args,
    scrubbed_git_env,
)

IndexKind = Literal["file", "symlink", "gitlink"]
WorktreeKind = Literal["file", "symlink", "directory", "missing", "other"]
VisibilityOrigin = Literal["gitignore", "info_exclude", "core_excludes_file"]


@dataclass(frozen=True)
class SurfaceEntry:
    """One Git-listed relative path with independent index/worktree facts."""

    rel: Path
    tracked: bool
    index_kind: IndexKind | None
    worktree_kind: WorktreeKind


@dataclass(frozen=True)
class VisibilityInput:
    """No-follow fingerprint of one input to Git's standard exclusions."""

    origin: VisibilityOrigin
    path: Path
    kind: WorktreeKind
    sha256: str | None
    link_text: str | None


@dataclass(frozen=True)
class SurfaceSnapshot:
    """Sorted raw target entries plus the ignore inputs that selected them."""

    entries: tuple[SurfaceEntry, ...]
    visibility_inputs: tuple[VisibilityInput, ...]


def _run_git(
    target: Path,
    *args: str,
    check: bool = True,
    stdin: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-C", str(target), *git_hardening_args(), *args]
    return subprocess.run(  # noqa: S603 # nosec B603 B607
        command,
        check=check,
        capture_output=True,
        env=scrubbed_git_env(),
        input=stdin,
    )


def _index_kind(mode: str) -> IndexKind:
    if mode.startswith("100"):
        return "file"
    if mode == "120000":
        return "symlink"
    if mode == "160000":
        return "gitlink"
    raise SafetyError(f"unsupported Git index mode {mode!r} in surface inventory")


def parse_ls_files(raw: bytes) -> list[tuple[Path, bool, IndexKind | None]]:
    """Parse tagged, staged ``git ls-files -z`` output without losing bytes.

    The capture command combines cached and non-ignored untracked entries.
    ``-t`` makes the two record shapes unambiguous: ``? path`` is untracked;
    every cached record carries a tag plus ``mode object stage<TAB>path``.
    Unmerged stages and duplicate paths fail closed because a single
    ``index_kind`` cannot represent them honestly.
    """

    parsed: dict[str, tuple[Path, bool, IndexKind | None]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise SafetyError(f"malformed git ls-files record: {record!r}")
        tag = record[:1]
        body = record[2:]
        if tag == b"?":
            path_raw = body
            tracked = False
            kind: IndexKind | None = None
        else:
            meta, separator, path_raw = body.partition(b"\t")
            fields = meta.split(b" ")
            if separator != b"\t" or len(fields) != 3:
                raise SafetyError(f"malformed staged git record: {record!r}")
            mode_raw, _object_id, stage_raw = fields
            try:
                mode = mode_raw.decode("ascii")
                stage = int(stage_raw)
            except (UnicodeDecodeError, ValueError) as exc:
                raise SafetyError(f"malformed staged git metadata: {record!r}") from exc
            if stage != 0:
                raise SafetyError(
                    f"unmerged Git index stage {stage} cannot be inventoried safely"
                )
            tracked = True
            kind = _index_kind(mode)
        path_text = path_raw.decode("utf-8", "surrogateescape")
        rel = Path(SafeRelPath(path_text).as_posix())
        posix = rel.as_posix()
        if posix in parsed:
            raise SafetyError(f"duplicate Git inventory path {posix!r}")
        parsed[posix] = (rel, tracked, kind)
    return [parsed[posix] for posix in sorted(parsed)]


def _worktree_kind(target: Path, rel: Path) -> WorktreeKind:
    """Classify ``target / rel`` without traversing a symlink ancestor."""

    current = target
    for part in rel.parts[:-1]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return "missing"
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            return "other"
    path = target / rel
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    return "other"


def _ignored_directories(target: Path, rels: list[Path]) -> set[str]:
    if not rels:
        return set()
    payload = b"".join(
        rel.as_posix().encode("utf-8", "surrogateescape") + b"/\0" for rel in rels
    )
    result = _run_git(
        target,
        "check-ignore",
        "--no-index",
        "-z",
        "--stdin",
        check=False,
        stdin=payload,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return {
        item.rstrip("/")
        for item in result.stdout.decode("utf-8", "surrogateescape").split("\0")
        if item
    }


def _active_gitignore_paths(
    target: Path, entries: tuple[SurfaceEntry, ...]
) -> set[Path]:
    """Find `.gitignore` leaves in directories Git can traverse.

    This filesystem walk is no-follow. Git itself decides which real child
    directories are excluded, so self-ignored `.gitignore` files remain inputs
    while `.gitignore` files below an excluded parent do not become false
    dependencies.
    """

    found: set[Path] = set()
    active_dirs: set[str] = {"."}
    pending: list[Path] = [Path(".")]
    while pending:
        children: list[Path] = []
        for rel_dir in pending:
            directory = target if rel_dir == Path(".") else target / rel_dir
            ignore_path = directory / ".gitignore"
            if os.path.lexists(ignore_path):
                found.add(ignore_path)
            try:
                scandir_entries = list(os.scandir(directory))
            except OSError as exc:
                raise SafetyError(
                    f"cannot inventory Git ignore directory {directory}: {exc}"
                ) from exc
            for child in scandir_entries:
                if child.name == ".git" or not child.is_dir(follow_symlinks=False):
                    continue
                child_rel = (
                    Path(child.name) if rel_dir == Path(".") else rel_dir / child.name
                )
                children.append(child_rel)
        ignored = _ignored_directories(target, children)
        pending = []
        for child in sorted(children, key=lambda path: path.as_posix()):
            if child.as_posix() in ignored:
                continue
            active_dirs.add(child.as_posix())
            pending.append(child)

    for entry in entries:
        if entry.rel.name != ".gitignore" or entry.worktree_kind != "missing":
            continue
        parent = entry.rel.parent.as_posix()
        if parent in active_dirs:
            found.add(target / entry.rel)
    return found


def _absolute_git_path(target: Path, *args: str) -> Path:
    result = _run_git(target, *args)
    text = result.stdout.decode("utf-8", "surrogateescape").strip()
    path = Path(text)
    return path if path.is_absolute() else target / path


def _core_excludes_path(target: Path) -> Path | None:
    result = _run_git(
        target,
        "config",
        "--local",
        "--path",
        "--get",
        "core.excludesFile",
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    text = result.stdout.decode("utf-8", "surrogateescape").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else target / path


def _assert_real_ancestors(path: Path) -> bool:
    """Return False for a missing ancestor; raise for a symlink/non-directory."""

    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(mode):
            raise SafetyError(f"symlink ancestor in Git visibility input: {current}")
        if not stat.S_ISDIR(mode):
            raise SafetyError(
                f"non-directory ancestor in Git visibility input: {current}"
            )
    return True


def _fingerprint_visibility(origin: VisibilityOrigin, path: Path) -> VisibilityInput:
    path = path.absolute()
    if not _assert_real_ancestors(path):
        return VisibilityInput(origin, path, "missing", None, None)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return VisibilityInput(origin, path, "missing", None, None)
    if stat.S_ISLNK(mode):
        return VisibilityInput(origin, path, "symlink", None, os.readlink(path))
    if stat.S_ISDIR(mode):
        return VisibilityInput(origin, path, "directory", None, None)
    if not stat.S_ISREG(mode):
        return VisibilityInput(origin, path, "other", None, None)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise SafetyError(
                f"Git visibility input changed type while opening: {path}"
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return VisibilityInput(origin, path, "file", digest.hexdigest(), None)


def _visibility_inputs(
    target: Path, entries: tuple[SurfaceEntry, ...]
) -> tuple[VisibilityInput, ...]:
    items = [
        _fingerprint_visibility("gitignore", path)
        for path in _active_gitignore_paths(target, entries)
    ]
    info_exclude = _absolute_git_path(
        target, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
    )
    items.append(_fingerprint_visibility("info_exclude", info_exclude))
    core_excludes = _core_excludes_path(target)
    if core_excludes is not None:
        items.append(_fingerprint_visibility("core_excludes_file", core_excludes))
    order = {"gitignore": 0, "info_exclude": 1, "core_excludes_file": 2}
    return tuple(
        sorted(items, key=lambda item: (order[item.origin], item.path.as_posix()))
    )


def capture_surface_snapshot(target: Path) -> SurfaceSnapshot:
    """Capture one sorted raw surface snapshot from an external target."""

    target = target.absolute()
    result = _run_git(
        target,
        "ls-files",
        "-z",
        "-t",
        "--stage",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    entries = tuple(
        SurfaceEntry(rel, tracked, index_kind, _worktree_kind(target, rel))
        for rel, tracked, index_kind in parse_ls_files(result.stdout)
    )
    return SurfaceSnapshot(entries, _visibility_inputs(target, entries))


def listed_paths(snapshot: SurfaceSnapshot) -> tuple[Path, ...]:
    """Every Git-listed relative path, including tracked missing entries."""

    return tuple(entry.rel for entry in snapshot.entries)


def tracked_path_strings(snapshot: SurfaceSnapshot) -> frozenset[str]:
    """Every index path in canonical POSIX form."""

    return frozenset(
        entry.rel.as_posix() for entry in snapshot.entries if entry.tracked
    )


def gitlink_path_strings(snapshot: SurfaceSnapshot) -> frozenset[str]:
    """Every gitlink index path, regardless of checkout state."""

    return frozenset(
        entry.rel.as_posix()
        for entry in snapshot.entries
        if entry.index_kind == "gitlink"
    )


def _excluded(
    entry: SurfaceEntry,
    *,
    exclude_files: frozenset[str],
    exclude_dirs: frozenset[str],
    root_control: frozenset[str],
) -> bool:
    posix = entry.rel.as_posix()
    return (
        posix in root_control
        or posix in exclude_files
        or any(part in exclude_dirs for part in entry.rel.parts)
    )


def select_copy_entries(snapshot: SurfaceSnapshot) -> tuple[SurfaceEntry, ...]:
    """Materializable sandbox entries plus every gitlink placeholder."""

    return tuple(
        entry
        for entry in snapshot.entries
        if entry.index_kind == "gitlink" or entry.worktree_kind in ("file", "symlink")
    )


def select_content_rewrite_entries(
    snapshot: SurfaceSnapshot,
    *,
    exclude_files: frozenset[str],
    exclude_dirs: frozenset[str],
    root_control: frozenset[str],
) -> tuple[SurfaceEntry, ...]:
    """No-follow regular files eligible for conservative content rewriting."""

    return tuple(
        entry
        for entry in snapshot.entries
        if entry.worktree_kind == "file"
        and not _excluded(
            entry,
            exclude_files=exclude_files,
            exclude_dirs=exclude_dirs,
            root_control=root_control,
        )
    )


def select_rename_entries(
    snapshot: SurfaceSnapshot,
    *,
    exclude_files: frozenset[str],
    exclude_dirs: frozenset[str],
    root_control: frozenset[str],
) -> tuple[SurfaceEntry, ...]:
    """Rewrite-eligible regular files and symlink leaves, never gitlinks."""

    return tuple(
        entry
        for entry in snapshot.entries
        if entry.index_kind != "gitlink"
        and entry.worktree_kind in ("file", "symlink")
        and not _excluded(
            entry,
            exclude_files=exclude_files,
            exclude_dirs=exclude_dirs,
            root_control=root_control,
        )
    )


def select_inline_doctor_entries(
    snapshot: SurfaceSnapshot,
    *,
    built_in_exclude_files: frozenset[str],
    built_in_exclude_dirs: frozenset[str],
    verify_ignore: frozenset[str],
    root_control: frozenset[str],
) -> tuple[SurfaceEntry, ...]:
    """Doctor coverage: built-in exclusions plus committed verify ignores."""

    excluded_dirs = built_in_exclude_dirs | verify_ignore
    return tuple(
        entry
        for entry in snapshot.entries
        if not _excluded(
            entry,
            exclude_files=built_in_exclude_files,
            exclude_dirs=excluded_dirs,
            root_control=root_control,
        )
    )


def select_verifier_entries(
    snapshot: SurfaceSnapshot,
    *,
    verify_ignore: frozenset[str],
    root_control: frozenset[str],
    exempt_paths: frozenset[str],
) -> tuple[SurfaceEntry, ...]:
    """Standalone verifier coverage over all kinds that are not exempt."""

    return tuple(
        entry
        for entry in snapshot.entries
        if entry.rel.as_posix() not in root_control
        and entry.rel.as_posix() not in exempt_paths
        and not any(part in verify_ignore for part in entry.rel.parts)
    )


def select_symlink_entries(snapshot: SurfaceSnapshot) -> tuple[SurfaceEntry, ...]:
    """Every Git-listed symlink leaf, without following its target."""

    return tuple(
        entry for entry in snapshot.entries if entry.worktree_kind == "symlink"
    )
