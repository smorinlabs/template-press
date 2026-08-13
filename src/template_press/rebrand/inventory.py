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
    UnsafePathError,
    git_hardening_args,
    read_regular_nofollow,
    readlink_nofollow,
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


@dataclass(frozen=True)
class _NodeStamp:
    """Change token for a visibility input or traversed directory."""

    path: Path
    kind: WorktreeKind
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None
    ctime_ns: int | None


@dataclass(frozen=True)
class _VisibilityState:
    """Public fingerprints plus internal change tokens for capture bracketing."""

    inputs: tuple[VisibilityInput, ...]
    stamps: tuple[_NodeStamp, ...]


@dataclass(frozen=True)
class _ConfigSourceStamp:
    """Content and node identity for one declared config source path."""

    path: Path
    kind: WorktreeKind
    sha256: str | None
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None
    ctime_ns: int | None


@dataclass(frozen=True)
class _ConfigSourceState:
    """Config files and parent directories that make includes observable."""

    sources: tuple[_ConfigSourceStamp, ...]
    include_parents: tuple[_NodeStamp, ...]
    condition_inputs: tuple[_NodeStamp, ...]


def _run_git(
    target: Path,
    *args: str,
    check: bool = True,
    stdin: bytes | None = None,
    pin_core_excludes: bool = False,
    core_excludes: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-C", str(target), *git_hardening_args()]
    if pin_core_excludes:
        command.extend(["-c", f"core.excludesFile={core_excludes or Path(os.devnull)}"])
    command.extend(args)
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


def _git_rel_path(path_text: str) -> Path:
    """Validate Git's canonical slash-separated path without changing bytes."""

    if os.name == "nt":
        return Path(SafeRelPath(path_text).as_posix())
    if not path_text or path_text.startswith("/"):
        raise UnsafePathError(f"unsafe Git relative path: {path_text!r}")
    parts = path_text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise UnsafePathError(f"unsafe Git path component: {path_text!r}")
    if any(part == ".git" for part in parts):
        raise UnsafePathError(f"'.git' component not allowed: {path_text!r}")
    rel = Path(*parts)
    if os.fsencode(rel.as_posix()) != path_text.encode("utf-8", "surrogateescape"):
        raise UnsafePathError(f"Git path did not round trip exactly: {path_text!r}")
    return rel


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
        rel = _git_rel_path(path_text)
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


def _ignored_directories(
    target: Path, rels: list[Path], core_excludes: Path | None
) -> set[str]:
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
        pin_core_excludes=True,
        core_excludes=core_excludes,
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
    target: Path,
    entries: tuple[SurfaceEntry, ...],
    core_excludes: Path | None,
) -> tuple[set[Path], set[Path]]:
    """Find `.gitignore` leaves in directories Git can traverse.

    This filesystem walk is no-follow. Git itself decides which real child
    directories are excluded, so self-ignored `.gitignore` files remain inputs
    while `.gitignore` files below an excluded parent do not become false
    dependencies.
    """

    found: set[Path] = set()
    active_dirs: set[str] = {"."}
    gitlinks = {
        entry.rel.as_posix() for entry in entries if entry.index_kind == "gitlink"
    }
    pending: list[Path] = [Path(".")]
    while pending:
        children: list[Path] = []
        for rel_dir in pending:
            directory = target if rel_dir == Path(".") else target / rel_dir
            try:
                directory_mode = os.lstat(directory).st_mode
            except OSError as exc:
                raise SafetyError(
                    f"cannot inventory Git ignore directory {directory}: {exc}"
                ) from exc
            if not stat.S_ISDIR(directory_mode):
                raise SafetyError(
                    f"cannot inventory Git ignore directory {directory}: "
                    "node is no longer a real directory"
                )
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
                if child_rel.as_posix() in gitlinks:
                    continue
                children.append(child_rel)
        ignored = _ignored_directories(target, children, core_excludes)
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
    directories = {target if rel == "." else target / rel for rel in active_dirs}
    return found, directories


def _absolute_git_path(target: Path, *args: str) -> Path:
    result = _run_git(target, *args)
    if not result.stdout.endswith(b"\n"):
        raise SafetyError("malformed newline-terminated Git path")
    text = result.stdout[:-1].decode("utf-8", "surrogateescape")
    path = Path(text)
    return path if path.is_absolute() else target / path


def _core_excludes_path(target: Path) -> Path | None:
    result = _run_git(
        target,
        "config",
        "--includes",
        "--path",
        "--null",
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
    if not result.stdout.endswith(b"\0") or result.stdout.count(b"\0") != 1:
        raise SafetyError("malformed NUL-delimited core.excludesFile value")
    text = result.stdout[:-1].decode("utf-8", "surrogateescape")
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else target / path


def _git_exec_prefix(target: Path) -> Path:
    """Installation prefix used by Git's ``%(prefix)`` interpolation."""

    exec_path = _absolute_git_path(target, "--exec-path")
    if len(exec_path.parents) < 2:
        raise SafetyError(f"cannot derive Git installation prefix: {exec_path}")
    return exec_path.parent.parent


def _resolve_config_include_path(value: str, origin: Path, target: Path) -> Path:
    """Resolve one Git include path relative to its declaring config file."""

    if value == "%(prefix)" or value.startswith("%(prefix)/"):
        suffix = value.removeprefix("%(prefix)").removeprefix("/")
        return (_git_exec_prefix(target) / suffix).absolute()
    if value.startswith("%("):
        raise SafetyError(f"unsupported interpolated Git include path: {value!r}")
    expanded = Path(os.path.expanduser(value))
    return (expanded if expanded.is_absolute() else origin.parent / expanded).absolute()


def _config_source_paths(target: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Active file origins and every declared include target, including missing."""

    result = _run_git(
        target,
        "config",
        "--includes",
        "--show-origin",
        "--null",
        "--list",
    )
    if not result.stdout.endswith(b"\0"):
        raise SafetyError("malformed NUL-delimited Git config origins")
    records = result.stdout[:-1].split(b"\0")
    if len(records) % 2:
        raise SafetyError("malformed Git config origin/value pairs")
    origins: set[Path] = set()
    includes: set[Path] = set()
    unconditional_includes: set[Path] = set()
    for origin_raw, item_raw in zip(records[::2], records[1::2], strict=True):
        if not origin_raw.startswith(b"file:"):
            continue
        text = origin_raw[len(b"file:") :].decode("utf-8", "surrogateescape")
        origin = Path(text)
        origin = (origin if origin.is_absolute() else target / origin).absolute()
        origins.add(origin)
        key_raw, separator, value_raw = item_raw.partition(b"\n")
        if not separator:
            raise SafetyError("malformed Git config key/value record")
        key = key_raw.decode("utf-8", "surrogateescape").casefold()
        is_include = key == "include.path" or (
            key.startswith("includeif.") and key.endswith(".path")
        )
        if is_include:
            value = value_raw.decode("utf-8", "surrogateescape")
            include = _resolve_config_include_path(value, origin, target)
            includes.add(include)
            if key == "include.path":
                unconditional_includes.add(include)
    # Existing active conditional includes appear as file origins. A missing
    # conditional target cannot be distinguished from an inactive one without
    # reimplementing Git's condition language, so its parent directory is the
    # portable change token; inactive existing targets remain irrelevant.
    all_sources = origins | unconditional_includes
    return (
        tuple(sorted(all_sources, key=lambda path: path.as_posix())),
        tuple(sorted(includes, key=lambda path: path.as_posix())),
    )


def _config_source_stamp(path: Path) -> _ConfigSourceStamp:
    """Fingerprint one config source without following path components."""

    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return _ConfigSourceStamp(path, "missing", None, None, None, None, None, None)
    try:
        if not stat.S_ISREG(before.st_mode):
            raise SafetyError(f"Git config source is not a regular file: {path}")
        data = read_regular_nofollow(path)
        after = os.lstat(path)
    except OSError as exc:
        raise SafetyError(
            f"cannot fingerprint Git config source {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(after.st_mode) or not os.path.samestat(before, after):
        raise SafetyError(f"Git config source changed while reading: {path}")
    return _ConfigSourceStamp(
        path,
        "file",
        hashlib.sha256(data).hexdigest(),
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _nearest_real_parent(path: Path) -> Path:
    """Nearest existing real directory above a possibly missing include."""

    absolute = path.absolute()
    current = Path(absolute.anchor)
    nearest = current
    for part in absolute.parent.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SafetyError(f"non-real ancestor in Git config include: {current}")
        nearest = current
    return nearest


def _config_source_state(target: Path) -> _ConfigSourceState:
    sources, includes = _config_source_paths(target)
    parents = {_nearest_real_parent(path) for path in includes}
    git_dir = _absolute_git_path(
        target, "rev-parse", "--path-format=absolute", "--git-dir"
    )
    common_dir = _absolute_git_path(
        target, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    head = _absolute_git_path(
        target, "rev-parse", "--path-format=absolute", "--git-path", "HEAD"
    )
    condition_paths = {
        target,
        target / ".git",
        git_dir,
        git_dir.parent,
        common_dir,
        common_dir.parent,
        head,
        head.parent,
    }
    return _ConfigSourceState(
        tuple(_config_source_stamp(path) for path in sources),
        tuple(_node_stamp(path) for path in sorted(parents)),
        tuple(_node_stamp(path) for path in sorted(condition_paths)),
    )


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
        if origin != "gitignore":
            raise SafetyError(
                f"Git {origin} visibility input is a symbolic link: {path}"
            )
        return VisibilityInput(origin, path, "symlink", None, readlink_nofollow(path))
    if stat.S_ISDIR(mode):
        return VisibilityInput(origin, path, "directory", None, None)
    if not stat.S_ISREG(mode):
        return VisibilityInput(origin, path, "other", None, None)
    try:
        data = read_regular_nofollow(path)
    except OSError as exc:
        raise SafetyError(f"cannot read Git visibility input {path}: {exc}") from exc
    return VisibilityInput(origin, path, "file", hashlib.sha256(data).hexdigest(), None)


def _node_stamp(path: Path) -> _NodeStamp:
    path = path.absolute()
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return _NodeStamp(path, "missing", None, None, None, None, None)
    mode = info.st_mode
    if stat.S_ISREG(mode):
        kind: WorktreeKind = "file"
    elif stat.S_ISLNK(mode):
        kind = "symlink"
    elif stat.S_ISDIR(mode):
        kind = "directory"
    else:
        kind = "other"
    return _NodeStamp(
        path,
        kind,
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _visibility_inputs(
    target: Path,
    entries: tuple[SurfaceEntry, ...],
    core_excludes: Path | None,
) -> _VisibilityState:
    gitignore_paths, active_directories = _active_gitignore_paths(
        target, entries, core_excludes
    )
    items = [_fingerprint_visibility("gitignore", path) for path in gitignore_paths]
    info_exclude = _absolute_git_path(
        target, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
    )
    items.append(_fingerprint_visibility("info_exclude", info_exclude))
    if core_excludes is not None:
        items.append(_fingerprint_visibility("core_excludes_file", core_excludes))
    order = {"gitignore": 0, "info_exclude": 1, "core_excludes_file": 2}
    inputs = tuple(
        sorted(items, key=lambda item: (order[item.origin], item.path.as_posix()))
    )
    stamp_paths = active_directories | {item.path for item in inputs}
    stamps = tuple(_node_stamp(path) for path in sorted(stamp_paths))
    return _VisibilityState(inputs, stamps)


def capture_surface_snapshot(target: Path) -> SurfaceSnapshot:
    """Capture two equal candidates or refuse a changing external target."""

    target = target.absolute()
    seed_entries = _enumerate_index_entries(target)
    first = _capture_candidate(target, seed_entries)
    second = _capture_candidate(target, first.entries)
    if first != second:
        raise SafetyError("Git surface or visibility changed during capture")
    return second


def _enumerate_entries(
    target: Path, core_excludes: Path | None
) -> tuple[SurfaceEntry, ...]:
    """Enumerate raw entries under one explicitly pinned ignore policy."""

    result = _run_git(
        target,
        "ls-files",
        "-z",
        "-t",
        "--stage",
        "--cached",
        "--others",
        "--exclude-standard",
        pin_core_excludes=True,
        core_excludes=core_excludes,
    )
    return tuple(
        SurfaceEntry(rel, tracked, index_kind, _worktree_kind(target, rel))
        for rel, tracked, index_kind in parse_ls_files(result.stdout)
    )


def _enumerate_index_entries(target: Path) -> tuple[SurfaceEntry, ...]:
    """Learn tracked kinds, especially opaque gitlink directory boundaries."""

    result = _run_git(target, "ls-files", "-z", "-t", "--stage", "--cached")
    return tuple(
        SurfaceEntry(rel, tracked, index_kind, _worktree_kind(target, rel))
        for rel, tracked, index_kind in parse_ls_files(result.stdout)
    )


def _capture_candidate(
    target: Path, seed_entries: tuple[SurfaceEntry, ...]
) -> SurfaceSnapshot:
    """One coherent candidate; the public capture compares two candidates."""

    config_before = _config_source_state(target)
    core_excludes_before = _core_excludes_path(target)
    visibility_before = _visibility_inputs(target, seed_entries, core_excludes_before)
    entries = _enumerate_entries(target, core_excludes_before)
    core_excludes_after = _core_excludes_path(target)
    visibility_after = _visibility_inputs(target, entries, core_excludes_after)
    config_after = _config_source_state(target)
    if config_before != config_after or core_excludes_before != core_excludes_after:
        raise SafetyError("Git config sources changed during capture")
    if visibility_before != visibility_after:
        raise SafetyError("Git visibility changed during capture")
    return SurfaceSnapshot(entries, visibility_after.inputs)


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
    """Every present worktree entry plus every gitlink placeholder."""

    return tuple(
        entry
        for entry in snapshot.entries
        if entry.index_kind == "gitlink" or entry.worktree_kind != "missing"
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
        if entry.index_kind != "gitlink"
        and entry.worktree_kind == "file"
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
