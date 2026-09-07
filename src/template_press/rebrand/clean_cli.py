"""`press clean` — remove ignored entries under declared [[clean]] paths (E10).

A standalone verb: it renders the declared paths from press/press-source.toml,
echoes the exact git argv, runs ``git clean -fdX -- <paths>`` (``-ndX`` under
``--show``), and prints git's own output. It never runs inside
``press rebrand`` and never writes a receipt.
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 — engine-owned hardened Git invocations
import sys
import tomllib
from pathlib import Path

from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.config import SOURCE_CONFIG_REL, load_source_config
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.inventory import capture_surface_snapshot, listed_paths
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
    """Match one directory entry across filesystem case aliases, not hardlinks."""
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
    if absolute_left.name.casefold() != absolute_right.name.casefold():
        return False
    try:
        stored_names = {entry.name for entry in os.scandir(absolute_left.parent)}
    except OSError:
        return False
    # A case-insensitive alias has one stored name. If both spellings are
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
) -> None:
    """Refuse a clean path that can delete a present active Git input."""
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
    raw = _remove_git_line_ending(result.stdout)
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


def clean_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press clean", description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--show",
        action="store_true",
        help="preview with git clean -ndX and remove nothing",
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
        _validate_clean_preserves_active_inputs(target, paths)
    except _CONFIG_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    command = clean_argv(
        git, target, paths, show=args.show, core_excludes=core_excludes
    )
    print(f"{'preview' if args.show else 'run'}: {shell_join(command)}")
    try:
        result = execute_clean(command, target)
    except OSError as exc:
        # The process could not start, so no clean command ran.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(result.stdout.decode("utf-8", "replace"))
    sys.stderr.write(result.stderr.decode("utf-8", "replace"))
    if result.returncode != 0:
        print(f"error: git clean exited {result.returncode}", file=sys.stderr)
        return 1
    return 0
