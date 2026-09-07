"""Standalone declared cleanup: exact ignored files and bounded Git directories.

File previews describe engine actions; directory previews run Git. Cleanup
never runs inside rebrand and never writes a receipt.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess  # nosec B404 — engine-owned hardened Git invocations
import sys
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.config import SOURCE_CONFIG_REL, load_source_config
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.inventory import (
    SurfaceSnapshot,
    _git_rel_path,
    _ignored_directories,
    capture_surface_snapshot,
    listed_paths,
)
from template_press.rebrand.pathing import ROOT_CONTROL
from template_press.rebrand.regen import command_env, resolve_executable
from template_press.rebrand.rules import RULES_REL, load_selected_rules
from template_press.rebrand.safety import (
    SafetyError,
    git_hardening_args,
    read_regular_nofollow,
)

# The configuration exception set every entry point normalizes to exit 2,
# plus safety and checked-Git failures from source/config/snapshot preflight;
# all refuse before a clean command runs.
_CONFIG_ERRORS = (
    ValidationError,
    SafetyError,
    subprocess.CalledProcessError,
    tomllib.TOMLDecodeError,
    UnicodeDecodeError,
    OSError,
)


def _decode_git_path(raw: bytes) -> str:
    """Decode Git path bytes consistently with the surface inventory."""
    return raw.decode("utf-8", "surrogateescape")


def _remove_git_line_ending(raw: bytes) -> bytes:
    """Remove one LF or CRLF metadata terminator without stripping path bytes."""
    if raw.endswith(b"\r\n"):
        return raw[:-2]
    return raw.removesuffix(b"\n")


def _clean_excludes_path(git: Path, target: Path) -> Path | None:
    """Match inventory's configured excludes; never inherit Git's default file."""
    query = [
        str(git),
        "-C",
        str(target),
        f"--work-tree={target}",
        *git_hardening_args(),
        "config",
        "--includes",
        "--path",
        "--null",
        "--get",
        "core.excludesFile",
    ]
    result = execute_clean(query, target)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValidationError("cannot resolve configured core.excludesFile")
    if not result.stdout.endswith(b"\0") or result.stdout.count(b"\0") != 1:
        raise ValidationError("malformed NUL-delimited core.excludesFile value")
    raw = result.stdout[:-1]
    if not raw:
        return None
    path = Path(_decode_git_path(raw))
    if path == Path(os.devnull):
        return None
    if not path.is_absolute():
        path = target / path
    try:
        read_regular_nofollow(path)
    except FileNotFoundError:
        # Git permits an absent configured excludes file.
        pass
    return path


def _paths_are_same(left: Path, right: Path) -> bool:
    """Compare normalized spelling, then existing filesystem-node identity."""
    normalized_left = Path(os.path.normcase(os.path.abspath(left)))
    normalized_right = Path(os.path.normcase(os.path.abspath(right)))
    if normalized_left == normalized_right:
        return True
    try:
        return os.path.samefile(normalized_left, normalized_right)
    except OSError:
        return False


def _paths_are_same_entry(left: Path, right: Path) -> bool:
    """Match one entry across case/Unicode filesystem aliases, not hardlinks."""
    absolute_left = Path(os.path.abspath(left))
    absolute_right = Path(os.path.abspath(right))
    if os.fspath(absolute_left) == os.fspath(absolute_right):
        return True
    try:
        if not os.path.samefile(absolute_left.parent, absolute_right.parent):
            return False
        if not os.path.samefile(absolute_left, absolute_right):
            return False
    except OSError:
        return False
    if absolute_left.name == absolute_right.name:
        return True
    # Case folding alone does not equate composed and decomposed Unicode.
    # Normalize comparison keys only: actual path and stored-name bytes stay
    # literal, including the hardlink-entry distinction below.
    left_key = unicodedata.normalize("NFC", absolute_left.name.casefold())
    right_key = unicodedata.normalize("NFC", absolute_right.name.casefold())
    if left_key != right_key:
        return False
    # Unavailable alias evidence must refuse cleanup, not authorize unlink.
    stored_names = {entry.name for entry in os.scandir(absolute_left.parent)}
    # A filesystem alias has one stored name. If both literal spellings are
    # stored, they are distinct hardlink entries and both can be removed alone.
    return not (
        absolute_left.name in stored_names and absolute_right.name in stored_names
    )


def _path_is_same_or_descendant(path: Path, root: Path) -> bool:
    """Compare the lexical relation, then existing ancestor identities."""
    candidate = Path(os.path.normcase(os.path.abspath(path)))
    normalized_root = Path(os.path.normcase(os.path.abspath(root)))
    if candidate.is_relative_to(normalized_root):
        return True
    # POSIX normcase is a no-op, including on case-insensitive macOS volumes.
    # Match an existing candidate ancestor by identity so alternate case
    # spellings cannot bypass containment checks.
    for ancestor in (candidate, *candidate.parents):
        if _paths_are_same(ancestor, normalized_root):
            return True
    return False


def _validate_clean_excludes_disjoint(
    target: Path, paths: tuple[str, ...], core_excludes: Path | None
) -> None:
    """Refuse when Git's configured excludes path is cleanable."""
    if core_excludes is None:
        return
    for relative in paths:
        if _path_is_same_or_descendant(core_excludes, target / relative):
            raise ValidationError(
                f"configured core.excludesFile {core_excludes} overlaps "
                f"[[clean]] path {relative!r}"
            )


def _validate_clean_preserves_active_inputs(
    target: Path, paths: tuple[str, ...]
) -> SurfaceSnapshot:
    """Preserve Git and press inputs, returning the validated snapshot."""
    snapshot = capture_surface_snapshot(target)
    protected = tuple(target / relative for relative in listed_paths(snapshot))
    active_inputs = (*snapshot.visibility_inputs, *snapshot.git_config_inputs)
    for active_input in active_inputs:
        if active_input.kind == "missing" or any(
            _paths_are_same_entry(active_input.path, protected_path)
            for protected_path in protected
        ):
            continue
        for relative in paths:
            if _path_is_same_or_descendant(active_input.path, target / relative):
                raise ValidationError(
                    f"active Git input {active_input.path} overlaps "
                    f"[[clean]] path {relative!r} but is absent from protected "
                    "surface entries"
                )

    declared_inputs = (
        ("declared Git config include", snapshot.git_config_include_paths),
        (
            "press-owned control file",
            tuple(target / relative for relative in sorted(ROOT_CONTROL)),
        ),
    )
    for origin, candidates in declared_inputs:
        for path in candidates:
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            if any(
                _paths_are_same_entry(path, protected_path)
                for protected_path in protected
            ):
                continue
            for relative in paths:
                if _path_is_same_or_descendant(path, target / relative):
                    raise ValidationError(
                        f"{origin} {path} overlaps [[clean]] path {relative!r} "
                        "but is absent from protected surface entries"
                    )
    return snapshot


def _validate_git_metadata(git: Path, target: Path) -> None:
    """Bind Git discovery to this ordinary directory or linked worktree.

    Invalid ordinary markers must not let Git discover an ancestor repo.

    Do not pin --work-tree on this read-only query. Neither the reported
    top-level directory nor membership in worktree list binds the selected
    index: a target can point at another linked worktree in the same repo.
    Git's per-worktree gitdir backlink must name this exact .git marker.
    """
    query = [
        str(git),
        "-C",
        str(target),
        *git_hardening_args(),
        "rev-parse",
        "--absolute-git-dir",
    ]
    result = execute_clean(query, target)
    # Git stdout adds LF; a preceding CR can be part of a POSIX path.
    raw = result.stdout.removesuffix(b"\n")
    if result.returncode != 0 or not raw or b"\x00" in raw:
        raise ValidationError("cannot resolve .git gitfile")
    git_dir = Path(_decode_git_path(raw))
    if not git_dir.is_absolute():
        raise ValidationError("Git returned a relative Git directory")
    if (target / ".git").is_dir():
        if git_dir.resolve() != target / ".git":
            raise ValidationError(".git directory discovery escaped the target")
        return
    backlink_raw = _remove_git_line_ending(read_regular_nofollow(git_dir / "gitdir"))
    if not backlink_raw or b"\x00" in backlink_raw:
        raise ValidationError("invalid linked-worktree gitdir backlink")
    backlink = Path(_decode_git_path(backlink_raw))
    if not backlink.is_absolute():
        backlink = git_dir / backlink
    if not _paths_are_same_entry(backlink.resolve(), target / ".git"):
        raise ValidationError(".git gitfile does not belong to this linked worktree")

    # A normal foreign Git directory can forge the backlink above. A linked
    # worktree must also occupy a registered slot in its common repository.
    common_raw = _remove_git_line_ending(read_regular_nofollow(git_dir / "commondir"))
    if not common_raw or b"\x00" in common_raw:
        raise ValidationError("invalid linked-worktree commondir")
    common_dir = Path(_decode_git_path(common_raw))
    if not common_dir.is_absolute():
        common_dir = git_dir / common_dir
    if not _paths_are_same_entry(
        git_dir.resolve().parent, common_dir.resolve() / "worktrees"
    ):
        raise ValidationError(".git gitfile is not registered linked-worktree metadata")


@dataclass(frozen=True)
class _ExactFile:
    relative: str
    metadata: os.stat_result
    parents: tuple[tuple[Path, os.stat_result], ...]


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _check_repository_boundary(path: Path) -> None:
    if _present(path / ".git"):
        raise ValidationError(f"nested repository boundary: {path}")
    if (
        _present(path / "HEAD")
        and (_present(path / "objects") or _present(path / "commondir"))
        and any(_present(path / name) for name in ("refs", "packed-refs", "commondir"))
    ):
        raise ValidationError(f"repository metadata-shaped boundary: {path}")


def _inspect_clean_path(
    target: Path, relative: str
) -> tuple[os.stat_result | None, tuple[tuple[Path, os.stat_result], ...]]:
    """Inspect only the selected finite chain, never following a boundary."""
    current = target
    parents: list[tuple[Path, os.stat_result]] = []
    parts = Path(relative).parts
    for index in range(len(parts) + 1):
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return None, tuple(parents)
        if current.is_junction():
            raise ValidationError(f"junction in [[clean]] selection: {current}")
        leaf = index == len(parts)
        if not leaf:
            if stat.S_ISLNK(metadata.st_mode):
                raise ValidationError(f"symlink ancestor in [[clean]] path: {current}")
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValidationError(f"non-directory [[clean]] ancestor: {current}")
        if stat.S_ISDIR(metadata.st_mode) and current != target:
            _check_repository_boundary(current)
        if leaf:
            return metadata, tuple(parents)
        parents.append((current, metadata))
        current /= parts[index]
    raise ValidationError(f"cannot inspect [[clean]] path {relative!r}")


def _clean_query_argv(
    git: Path, target: Path, core_excludes: Path | None, *arguments: str
) -> list[str]:
    return [
        str(git),
        "-C",
        str(target),
        f"--work-tree={target}",
        *git_hardening_args(),
        "-c",
        f"core.excludesFile={core_excludes or Path(os.devnull)}",
        *arguments,
    ]


def _ignored_clean_files(
    git: Path, target: Path, core_excludes: Path | None, paths: tuple[str, ...]
) -> set[str]:
    if not paths:
        return set()
    command = _clean_query_argv(
        git, target, core_excludes, "check-ignore", "-z", "--stdin"
    )
    payload = b"".join(
        path.encode("utf-8", "surrogateescape") + b"\0" for path in paths
    )
    result = execute_clean(command, target, stdin=payload)
    if result.returncode == 1 and not result.stdout:
        return set()
    if result.returncode != 0 or not result.stdout or not result.stdout.endswith(b"\0"):
        raise ValidationError("invalid exact-file git check-ignore result")
    records = _decode_git_path(result.stdout[:-1]).split("\0")
    if len(records) != len(set(records)) or not set(records).issubset(paths):
        raise ValidationError("malformed exact-file git check-ignore paths")
    return set(records)


def _current_tracked_paths(
    git: Path, target: Path, core_excludes: Path | None
) -> tuple[Path, ...]:
    command = _clean_query_argv(
        git, target, core_excludes, "ls-files", "-z", "--cached"
    )
    result = execute_clean(command, target)
    if result.returncode != 0 or (result.stdout and not result.stdout.endswith(b"\0")):
        raise ValidationError("invalid exact-file git ls-files result")
    if not result.stdout:
        return ()
    return tuple(
        target / _git_rel_path(record)
        for record in dict.fromkeys(_decode_git_path(result.stdout[:-1]).split("\0"))
    )


def _plan_clean(
    git: Path,
    target: Path,
    paths: tuple[str, ...],
    core_excludes: Path | None,
    snapshot: SurfaceSnapshot,
) -> tuple[tuple[_ExactFile, ...], tuple[str, ...]]:
    protected = tuple(target / rel for rel in listed_paths(snapshot))
    tracked = tuple(target / entry.rel for entry in snapshot.entries if entry.tracked)
    files: list[_ExactFile] = []
    directories: list[str] = []
    seen: list[Path] = []
    for relative in paths:
        metadata, parents = _inspect_clean_path(target, relative)
        if metadata is None:
            continue
        path = target / relative
        # Inspection precedes duplicate/coverage pruning: an unsafe original
        # declaration cannot disappear merely because a parent was selected.
        if any(_paths_are_same_entry(path, prior) for prior in seen):
            continue
        seen.append(path)
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(relative)
        elif stat.S_ISREG(metadata.st_mode):
            if not any(_paths_are_same_entry(path, entry) for entry in protected):
                files.append(_ExactFile(relative, metadata, parents))
        elif not any(_paths_are_same_entry(path, entry) for entry in tracked):
            raise ValidationError(
                f"unsupported non-regular [[clean]] file: {relative!r}"
            )
    roots = tuple(
        relative
        for relative in directories
        if not any(
            other != relative
            and _path_is_same_or_descendant(target / relative, target / other)
            for other in directories
        )
    )
    files = [
        item
        for item in files
        if not any(
            _path_is_same_or_descendant(target / item.relative, target / root)
            for root in roots
        )
    ]
    ancestors = list(
        dict.fromkeys(
            parent
            for relative in roots
            for parent in Path(relative).parents
            if parent != Path(".")
        )
    )
    ignored_ancestors = _ignored_directories(target, ancestors, core_excludes)
    if ignored_ancestors:
        raise ValidationError(
            "ignored proper ancestor of [[clean]] directory: "
            + ", ".join(repr(path) for path in sorted(ignored_ancestors))
        )
    ignored = _ignored_clean_files(
        git, target, core_excludes, tuple(item.relative for item in files)
    )
    return tuple(item for item in files if item.relative in ignored), roots


def _same_identity(before: os.stat_result, after: os.stat_result) -> bool:
    return all(
        not left or not right or left == right
        for left, right in (
            (before.st_dev, after.st_dev),
            (before.st_ino, after.st_ino),
        )
    )


def _revalidate_clean_file(
    git: Path,
    target: Path,
    core_excludes: Path | None,
    item: _ExactFile,
    *,
    writable: bool = False,
) -> None:
    metadata, parents = _inspect_clean_path(target, item.relative)
    expected = item.metadata
    if metadata is None or not stat.S_ISREG(metadata.st_mode):
        raise ValidationError(
            f"selected file changed or disappeared: {item.relative!r}"
        )
    write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    mode_matches = (
        metadata.st_mode & ~write_bits == expected.st_mode & ~write_bits
        and bool(metadata.st_mode & stat.S_IWRITE)
        if writable
        else metadata.st_mode == expected.st_mode
    )
    if (
        not _same_identity(expected, metadata)
        or not mode_matches
        or metadata.st_size != expected.st_size
        or metadata.st_mtime_ns != expected.st_mtime_ns
        or len(parents) != len(item.parents)
        or any(
            path != old_path
            or not _same_identity(old, new)
            or old.st_mode != new.st_mode
            for (path, new), (old_path, old) in zip(parents, item.parents, strict=True)
        )
    ):
        raise ValidationError(f"selected file or parent changed: {item.relative!r}")
    if item.relative not in _ignored_clean_files(
        git, target, core_excludes, (item.relative,)
    ):
        raise ValidationError(
            f"selected file is no longer ignored and untracked: {item.relative!r}"
        )
    if any(
        _paths_are_same_entry(target / item.relative, path)
        for path in _current_tracked_paths(git, target, core_excludes)
    ):
        raise ValidationError(f"selected file is now tracked: {item.relative!r}")


def _unlink_clean_file(
    git: Path, target: Path, core_excludes: Path | None, item: _ExactFile
) -> None:
    path = target / item.relative
    try:
        path.unlink()
    except PermissionError:
        if os.name != "nt":
            raise
        current = path.lstat()
        if not getattr(current, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY:
            raise
        _revalidate_clean_file(git, target, core_excludes, item)
        path.chmod(current.st_mode | stat.S_IWRITE)
        _revalidate_clean_file(git, target, core_excludes, item, writable=True)
        path.unlink()


def clean_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press clean", description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--show",
        action="store_true",
        help="preview exact files and git clean -ndX directories; remove nothing",
    )
    args = parser.parse_args(argv)

    target = args.target.resolve()
    if not target.is_dir():
        print(f"error: target {target} is not a directory", file=sys.stderr)
        return 2
    marker = target / ".git"
    if marker.is_symlink():
        # A symlinked .git would make git classify "tracked" and "ignored"
        # from a FOREIGN repository's index and excludes, so -X could delete
        # a file this target tracks. Refuse before anything runs (the same
        # no-follow rule the surface inventory applies to git markers).
        print(f"error: target {target}: .git is a symlink", file=sys.stderr)
        return 2
    if marker.is_junction():
        print(f"error: target {target}: .git is a junction", file=sys.stderr)
        return 2
    if not (marker.is_dir() or marker.is_file()):
        # No clean command ran, so this is a precondition refusal.
        print(f"error: target {target} is not a git repository", file=sys.stderr)
        return 2
    try:
        rules = load_selected_rules(target).rules
        if not rules.clean:
            print(
                f"error: no [[clean]] rules declared in {RULES_REL.as_posix()}",
                file=sys.stderr,
            )
            return 2
        source = load_source_config(target, None)
        if source is None:
            print(
                f"error: {SOURCE_CONFIG_REL.as_posix()} is required to render "
                f"[[clean]] paths",
                file=sys.stderr,
            )
            return 2
        paths = render_clean_paths(rules.clean, source)
    except _CONFIG_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    git = resolve_executable(target, "git", command_env(()))
    if git is None:
        print("error: git — missing (press clean needs it)", file=sys.stderr)
        return 2

    try:
        _validate_git_metadata(git, target)
        core_excludes = _clean_excludes_path(git, target)
        _validate_clean_excludes_disjoint(target, paths, core_excludes)
        snapshot = _validate_clean_preserves_active_inputs(target, paths)
        files, directories = _plan_clean(git, target, paths, core_excludes, snapshot)
        command = (
            clean_argv(
                git, target, directories, show=args.show, core_excludes=core_excludes
            )
            if directories
            else None
        )
    except _CONFIG_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    started = False
    try:
        for item in files:
            if args.show:
                print(f"would remove file: {item.relative!r}")
                continue
            _revalidate_clean_file(git, target, core_excludes, item)
            started = True
            _unlink_clean_file(git, target, core_excludes, item)
            print(f"removed file: {item.relative!r}")
        if command is not None:
            print(f"{'preview' if args.show else 'run'}: {shell_join(command)}")
            result = execute_clean(command, target)
            started = True
            sys.stdout.write(result.stdout.decode("utf-8", "replace"))
            sys.stderr.write(result.stderr.decode("utf-8", "replace"))
            if result.returncode != 0:
                raise ValidationError(f"git clean exited {result.returncode}")
    except _CONFIG_ERRORS as exc:
        suffix = "; earlier cleanup may have completed" if started else ""
        print(f"error: {exc}{suffix}", file=sys.stderr)
        return 1 if started else 2
    return 0
