"""Declared file and frozen directory removal (P08 T2 and P11).

Template-only files — maintenance CI workflows, dogfood history docs —
must not ship to pressed forks, and the legacy embedded engines deleted
them via their own manifests. ``[[remove]]`` is the press's declared
equivalent. Contract:

- Plan-time preflight applies the NAMED write-path predicates
  (``assert_under_root``, ``assert_ancestors_real``, ``is_regular_lstat``)
  plus git-tracked and clean (refused even under ``--allow-dirty`` — git
  restores only committed content, so deleting uncommitted edits would
  lose data). A declared target that does not exist fails loud: a stale
  ``[[remove]]`` is config drift, never a silent no-op.
- Removal executes AFTER ``apply()`` with the declared SOURCE-coordinate
  path translated through the rename report — the regeneration pattern,
  not position zero: ``apply()`` revalidates the tree against its
  plan-time snapshot, so deleting files before it would break the
  mutation boundary.
- Hermetic verify performs the same removals inside its sandbox. No
  command is needed, so unlike regeneration there is no exemption and no
  coverage gap: a removed file simply vanishes from the scan.
"""

from __future__ import annotations

import errno
import os
import posixpath
import stat
import subprocess
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from template_press.rebrand.identity import Identity
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.pathing import translate_path
from template_press.rebrand.receipt import (
    REMOVE_HISTORY_MAX_BYTES,
    read_receipt,
    removed_files_from_receipt,
    selected_directory_history,
    validate_directory_history,
)
from template_press.rebrand.regen import has_uncommitted_changes, tracked_paths
from template_press.rebrand.removal_types import (
    DirectoryRemoval,
    RemovalMember,
    RemovalPlan,
)
from template_press.rebrand.rules import (
    RemoveDirRule,
    RemoveRule,
    Rules,
    _control_alias_key,
    _reject_reserved,
)
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    git_hardening_args,
    is_regular_lstat,
    scrubbed_git_env,
)


def _directory_git_bytes(target: Path, *args: str) -> bytes:
    """Run one hardened, target-pinned Git query for directory preflight."""
    command = [
        "git",
        "--literal-pathspecs",
        "-C",
        str(target),
        f"--work-tree={target.absolute()}",
        *git_hardening_args(),
        *args,
    ]
    return subprocess.run(  # noqa: S603 # nosec B603
        command,
        check=True,
        capture_output=True,
        env=scrubbed_git_env(),
    ).stdout


def _directory_status_problems(
    target: Path,
    root: str,
    missing_recorded: frozenset[str],
    present_members: frozenset[str],
) -> list[str]:
    """Return dirty or hidden-index paths beneath one frozen directory root."""
    problems: list[str] = []
    raw_status = _directory_git_bytes(
        target,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        root,
    )
    records = raw_status.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise SafetyError("malformed directory status record")
        code = record[:2]
        rel = record[3:].decode("utf-8", "surrogateescape")
        has_second_path = b"R" in code or b"C" in code
        if has_second_path:
            if index >= len(records) or not records[index]:
                raise SafetyError("malformed directory rename status record")
            index += 1
        missing_history = (
            not has_second_path
            and code in (b" D", b"D ")
            and rel in missing_recorded
            and not os.path.lexists(target / rel)
        )
        if not missing_history:
            problems.append(f"remove directory {root!r}: dirty path {rel!r}")
    raw_flags = _directory_git_bytes(target, "ls-files", "-v", "-z", "--", root)
    for record in raw_flags.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise SafetyError("malformed directory index-flag record")
        tag = record[:1]
        rel = record[2:].decode("utf-8", "surrogateescape")
        if rel in present_members and (tag.islower() or tag == b"S"):
            problems.append(
                f"remove directory {root!r}: {rel!r} has uncommitted changes "
                "(assume-unchanged/skip-worktree) — refused even under "
                "--allow-dirty"
            )
    return problems


def _require_exact_stored_directory_spelling(target: Path, current_dir: str) -> None:
    """Refuse filesystem aliases of a directory's stored component names."""
    parent = target
    for component in PurePosixPath(current_dir).parts:
        with os.scandir(parent) as entries:
            stored = [(entry.name, Path(entry.path)) for entry in entries]
        if any(name == component for name, _path in stored):
            parent /= component
            continue
        candidate = parent / component
        stored_alias = next(
            (
                name
                for name, stored_path in stored
                if _same_existing_directory(stored_path, candidate)
            ),
            None,
        )
        detail = (
            f" {stored_alias!r}" if stored_alias is not None else " on the filesystem"
        )
        raise SafetyError(
            f"remove directory {current_dir!r}: component {component!r} does not "
            f"use exact stored spelling{detail}"
        )


def _same_existing_directory(left: Path, right: Path) -> bool:
    """Compare real directory entries without following symlink-like nodes."""
    try:
        if (
            not stat.S_ISDIR(left.lstat().st_mode)
            or left.is_junction()
            or not stat.S_ISDIR(right.lstat().st_mode)
            or right.is_junction()
        ):
            return False
        return os.path.samefile(left, right)
    except OSError:
        return False


def _freeze_directory(
    target: Path,
    declaration: RemoveDirRule,
    *,
    current_dir: str,
    prior: DirectoryRemoval | None = None,
) -> DirectoryRemoval:
    """Freeze tracked regular members and reject all directory dirtiness."""
    root = target / current_dir
    try:
        assert_under_root(root, target)
        assert_ancestors_real(root, target)
    except SafetyError:
        raise
    if root.is_junction():
        raise SafetyError(f"remove directory {current_dir!r} is a junction")
    if not os.path.lexists(root):
        if prior is not None:
            retained = tuple(
                RemovalMember(
                    file=member.file,
                    current_file=member.current_file,
                    reason=declaration.reason,
                    source_dir=member.source_dir,
                    missing_ok=True,
                )
                for member in prior.members
            )
            return DirectoryRemoval(
                dir=declaration.dir,
                current_dir=current_dir,
                reason=declaration.reason,
                members=retained,
            )
        raise SafetyError(
            f"remove directory {current_dir!r} does not exist — stale declaration"
        )
    if not root.is_dir() or root.is_symlink():
        raise SafetyError(f"remove directory {current_dir!r} is not a real directory")
    _require_exact_stored_directory_spelling(target, current_dir)

    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                relative = entry_path.relative_to(target).as_posix()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise SafetyError(
                        f"remove directory {current_dir!r}: symlink {relative!r}"
                    )
                if entry.name == ".git":
                    raise SafetyError(
                        f"remove directory {current_dir!r}: embedded git boundary {relative!r}"
                    )
                if stat.S_ISDIR(info.st_mode):
                    if entry_path.is_junction():
                        raise SafetyError(
                            f"remove directory {current_dir!r}: junction {relative!r}"
                        )
                    stack.append(entry_path)
                elif not stat.S_ISREG(info.st_mode):
                    raise SafetyError(
                        f"remove directory {current_dir!r}: unsafe node {relative!r}"
                    )
                if entry.name in {".gitignore", ".gitattributes", ".gitmodules"}:
                    raise SafetyError(
                        f"remove directory {current_dir!r}: Git visibility input {relative!r}"
                    )

    snapshot = capture_surface_snapshot(target)
    prefix = current_dir + "/"
    root_parts = PurePosixPath(current_dir).parts
    for entry in snapshot.entries:
        relative = entry.rel.as_posix()
        if (
            not entry.tracked
            or relative == current_dir
            or relative.startswith(prefix)
            or len(entry.rel.parts) < len(root_parts)
        ):
            continue
        indexed_root = target.joinpath(*entry.rel.parts[: len(root_parts)])
        if _same_existing_directory(indexed_root, root):
            raise SafetyError(
                f"remove directory {current_dir!r}: tracked path {relative!r} does "
                "not use the exact directory root spelling"
            )
    present = {
        entry.rel.as_posix()
        for entry in snapshot.entries
        if entry.tracked
        and entry.rel.as_posix().startswith(prefix)
        and entry.index_kind == "file"
        and os.path.lexists(target / entry.rel)
        and is_regular_lstat(target / entry.rel)
    }
    selected_tracked = {
        entry.rel.as_posix()
        for entry in snapshot.entries
        if entry.tracked
        and entry.rel.as_posix().startswith(prefix)
        and entry.index_kind == "file"
    }
    unsafe = [
        f"{entry.rel.as_posix()} ({entry.index_kind})"
        for entry in snapshot.entries
        if entry.tracked
        and entry.rel.as_posix().startswith(prefix)
        and entry.index_kind != "file"
    ]
    if unsafe:
        raise SafetyError(
            f"remove directory {current_dir!r}: unsafe tracked node {unsafe[0]!r}"
        )
    prior_missing = frozenset(
        member.current_file
        for member in (prior.members if prior is not None else ())
        if not os.path.lexists(target / member.current_file)
    )
    unauthorized_missing = selected_tracked - present - prior_missing
    if unauthorized_missing:
        missing = sorted(unauthorized_missing)[0]
        raise SafetyError(
            f"remove directory {current_dir!r}: tracked member {missing!r} is "
            "missing without validated prior absence history"
        )
    problems = _directory_status_problems(
        target, current_dir, prior_missing, frozenset(present)
    )
    if problems:
        omitted = len(problems) - min(len(problems), 20)
        suffix = f"; {omitted} additional path(s) omitted" if omitted else ""
        raise SafetyError("; ".join(problems[:20]) + suffix)
    retained = tuple(
        RemovalMember(
            file=member.file,
            current_file=member.current_file,
            reason=declaration.reason,
            source_dir=member.source_dir,
            missing_ok=True,
        )
        for member in (prior.members if prior is not None else ())
        if member.current_file in prior_missing
    )
    members = tuple(
        RemovalMember(
            file=rel,
            current_file=rel,
            reason=declaration.reason,
            source_dir=current_dir,
        )
        for rel in sorted(present)
    )
    root_entry = next(
        (entry for entry in snapshot.entries if entry.rel.as_posix() == current_dir),
        None,
    )
    if root_entry is not None and root_entry.index_kind == "gitlink":
        raise SafetyError(f"remove directory {current_dir!r}: root gitlink")
    seen_current: dict[str, str] = {}
    seen_audit: dict[str, str] = {}
    for member in members + retained:
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in member.file):
            raise SafetyError(
                f"remove directory {current_dir!r}: unsafe member path {member.file!r}"
            )
        _reject_reserved("[[remove]] directory member", member.file)
        if member.file.rsplit("/", 1)[-1] in {
            ".gitignore",
            ".gitattributes",
            ".gitmodules",
        }:
            raise SafetyError(
                f"remove directory {current_dir!r}: Git visibility input {member.file!r}"
            )
        alias = _control_alias_key(member.current_file)
        if alias in seen_current:
            raise SafetyError(
                f"remove directory {current_dir!r}: alias-colliding members "
                f"{seen_current[alias]!r} and {member.current_file!r}"
            )
        seen_current[alias] = member.current_file
        audit_alias = _control_alias_key(member.file)
        if audit_alias in seen_audit:
            raise SafetyError(
                f"remove directory {current_dir!r}: alias-colliding audit members "
                f"{seen_audit[audit_alias]!r} and {member.file!r}"
            )
        seen_audit[audit_alias] = member.file
        member_path = target / member.current_file
        if os.path.lexists(member_path):
            for visibility in snapshot.visibility_inputs:
                if not os.path.lexists(visibility.path):
                    continue
                try:
                    member_stat = os.stat(member_path)
                    visibility_stat = os.stat(visibility.path)
                except OSError:
                    continue
                same_resolved_path = member_path.resolve(
                    strict=False
                ) == visibility.path.resolve(strict=False)
                if same_resolved_path or (
                    member_stat.st_dev == visibility_stat.st_dev
                    and member_stat.st_ino == visibility_stat.st_ino
                    and member_stat.st_dev != 0
                    and member_stat.st_ino != 0
                ):
                    raise SafetyError(
                        f"remove directory {current_dir!r}: configured visibility "
                        f"input {member.file!r}"
                    )
    return DirectoryRemoval(
        dir=declaration.dir,
        current_dir=current_dir,
        reason=declaration.reason,
        members=tuple(
            sorted(
                members + retained,
                key=lambda member: (member.file, member.current_file),
            )
        ),
    )


def _paths_overlap(left: str, right: str) -> bool:
    """Compare exact paths and ancestors using all-platform filesystem aliases."""
    left_key = _control_alias_key(left)
    right_key = _control_alias_key(right)
    return (
        left_key == right_key
        or left_key.startswith(right_key + "/")
        or right_key.startswith(left_key + "/")
    )


def validate_removal_conflicts(
    rules: Rules, plan: RemovalPlan, renamed: Mapping[str, str]
) -> None:
    """Refuse resolved active removal overlaps before reset or rewrite."""
    translated = translate_removal_plan(plan, renamed)
    validate_removal_plan(translated)
    history = translated.directories + translated.retained_history
    if history:
        seen_current: set[str] = set()
        for member in (
            *translated.files,
            *(member for directory in history for member in directory.members),
        ):
            alias = _control_alias_key(member.current_file)
            if alias in seen_current:
                raise SafetyError("removal plan has duplicate or alias current paths")
            seen_current.add(alias)
    writers = [
        (kind, translate_path(rule.file, renamed))
        for kind, declarations in (
            ("edit", rules.edit),
            ("regenerate", rules.regenerate),
            ("reset", rules.reset),
        )
        for rule in declarations
    ]
    stubs = [
        translate_path(rule.stub_file, renamed)
        for rule in rules.reset
        if rule.stub_file is not None
    ]
    for directory in translated.directories:
        for kind, path in writers:
            if _paths_overlap(directory.current_dir, path):
                raise SafetyError(
                    f"remove directory {directory.current_dir!r} has "
                    f"resolved {kind} writer overlap at {path!r}"
                )
        for path in stubs:
            if _paths_overlap(directory.current_dir, path):
                raise SafetyError(
                    f"remove directory {directory.current_dir!r} has "
                    f"resolved stub_file overlap at {path!r}"
                )
        for member in translated.files:
            if _paths_overlap(directory.current_dir, member.current_file):
                raise SafetyError("resolved file/directory removal overlap")


def _guard_directory_history(target: Path, prior: DirectoryRemoval) -> None:
    """Check recorded roots and members without enumerating or reading status."""
    root = target / prior.current_dir
    _guard_frozen_remove_path(root, target)
    if os.path.lexists(root) and (
        root.is_junction() or not stat.S_ISDIR(root.lstat().st_mode)
    ):
        raise SafetyError(
            f"remove directory {prior.current_dir!r} is not a real directory"
        )
    for member in prior.members:
        path = target / member.current_file
        _guard_frozen_remove_path(path, target)
        if os.path.lexists(path) and (path.is_junction() or not is_regular_lstat(path)):
            raise SafetyError(
                f"remove target {member.current_file!r} is not a regular file"
            )


def plan_removals(
    target: Path,
    rules: Rules,
    *,
    source: Identity,
    receipt_text: str | None = None,
    mode: Literal["press", "verify"] = "press",
    legacy_removed: Mapping[str, str] | None = None,
) -> RemovalPlan:
    """Freeze active deletions and carry validated inactive directory history."""
    history = selected_directory_history(
        receipt_text, source, directory_declared=bool(rules.remove_dirs)
    )
    history_by_dir = {row.dir: row for row in history}
    directories: list[DirectoryRemoval] = []
    for declaration in rules.remove_dirs:
        for row in history:
            if declaration.dir != row.dir and any(
                _paths_overlap(declaration.dir, root)
                for root in (row.dir, row.current_dir)
            ):
                raise SafetyError(
                    "directory declaration conflicts with recorded history aliases"
                )
        prior = history_by_dir.get(declaration.dir)
        if prior is not None:
            prior = replace(
                prior,
                reason=declaration.reason,
                members=tuple(
                    replace(m, reason=declaration.reason) for m in prior.members
                ),
            )
            _guard_directory_history(target, prior)
        if mode == "verify" and prior is not None:
            directories.append(prior)
            continue
        current_dir = declaration.dir
        if prior is not None and prior.current_dir != declaration.dir:
            declared_path = target / declaration.dir
            _guard_frozen_remove_path(declared_path, target)
            if os.path.lexists(declared_path):
                raise SafetyError(
                    f"remove directory {declaration.dir!r} conflicts with recorded "
                    f"current root {prior.current_dir!r}; restore a coherent root"
                )
            current_dir = prior.current_dir
        if prior is not None and not os.path.lexists(target / current_dir):
            directories.append(prior)
            continue
        directories.append(
            _freeze_directory(target, declaration, current_dir=current_dir, prior=prior)
        )
    legacy = (
        removed_files_from_receipt(receipt_text)
        if legacy_removed is None
        else legacy_removed
    )
    file_members = tuple(
        RemovalMember(
            file=rule.file,
            current_file=rule.file,
            reason=rule.reason,
            missing_ok=rule.file in legacy,
        )
        for rule in rules.remove
    )
    declared = {rule.dir for rule in rules.remove_dirs}
    plan = RemovalPlan(
        files=file_members,
        directories=tuple(directories),
        retained_history=tuple(row for row in history if row.dir not in declared),
    )
    validate_removal_plan(plan)
    validate_removal_conflicts(rules, plan, {})
    return plan


def removal_rules_view(rules: Rules, plan: RemovalPlan) -> Rules:
    """Expose frozen members to legacy file-oriented plan gates."""
    files = tuple(
        RemoveRule(file=member.current_file, reason=member.reason)
        for member in plan.members
    )
    dirs = tuple(
        RemoveDirRule(dir=directory.current_dir, reason=directory.reason)
        for directory in plan.directories
    )
    if files == rules.remove and dirs == rules.remove_dirs:
        return rules
    return replace(rules, remove=files, remove_dirs=dirs)


def render_frozen_remove_plan(plan: RemovalPlan) -> str:
    """Render every frozen file and directory member before mutation."""
    lines = ["Remove (frozen declared deletions, applied after the rewrite pass):"]
    counts: dict[str, int] = {}
    for member in plan.files:
        location = (
            f" → {member.current_file}" if member.file != member.current_file else ""
        )
        lines.append(f"  [remove ] {member.file}{location}  —  {member.reason}")
        head, separator, _ = member.file.partition("/")
        if separator:
            counts[head] = counts.get(head, 0) + 1
    for directory in plan.directories:
        count = len(directory.members)
        noun = "file" if count == 1 else "files"
        lines.append(
            f"  [remove ] {directory.current_dir}/ ({count} {noun}, dir) "
            f"— {directory.reason}"
        )
        for member in directory.members:
            location = (
                f" → {member.current_file}"
                if member.file != member.current_file
                else ""
            )
            lines.append(f"    member {member.file}{location}")
    for dirname in sorted(counts):
        count = counts[dirname]
        noun = "file" if count == 1 else "files"
        lines.append(f"  removing {count} {noun} under {dirname}/")
    return "\n".join(lines)


def frozen_remove_command_conflicts(
    rules: Rules, plan: RemovalPlan, renamed: Mapping[str, str]
) -> list[str]:
    """Find command argv paths removed by the frozen plan."""
    if not plan.directories:
        return remove_command_conflicts(removal_rules_view(rules, plan), renamed)
    removed: dict[str, str] = {}
    for member in plan.members:
        current = translate_path(member.current_file, renamed)
        removed[_control_alias_key(member.current_file)] = member.current_file
        removed[_control_alias_key(current)] = member.current_file
    directory_roots: list[tuple[str, str]] = []
    for directory in plan.directories:
        current_dir = translate_path(directory.current_dir, renamed)
        directory_roots.extend(
            (
                (directory.current_dir, directory.current_dir),
                (current_dir, directory.current_dir),
            )
        )
        removed[_control_alias_key(directory.current_dir)] = directory.current_dir
        removed[_control_alias_key(current_dir)] = directory.current_dir
    problems: list[str] = []
    for kind, declarations in (("edit", rules.edit), ("regenerate", rules.regenerate)):
        for declaration in declarations:
            for element in declaration.command:
                normalized = posixpath.normpath(element.replace("\\", "/"))
                alias = _control_alias_key(normalized)
                matching_root = next(
                    (
                        declared
                        for root, declared in directory_roots
                        if alias == _control_alias_key(root)
                        or alias.startswith(_control_alias_key(root) + "/")
                    ),
                    None,
                )
                if alias not in removed and matching_root is None:
                    continue
                problems.append(
                    f"frozen removal {(removed.get(alias) or matching_root)!r}: "
                    f"argv element {element!r} in the [[{kind}]] command for "
                    f"{declaration.file!r} names a removed path"
                )
    return problems


@dataclass(frozen=True)
class RemovePreview:
    """One planned removal: the SOURCE-coordinate path and its reason."""

    rel: str
    reason: str


def preflight_remove_targets(
    target: Path,
    rules: Rules,
    *,
    previously_removed: frozenset[str] = frozenset(),
) -> list[str]:
    """Problems that make a declared removal unpressable (exit 2, nothing
    written). Empty list = every declared target is contained, tracked,
    a clean regular file (no-follow) — or already removed by a prior press
    (``previously_removed``, the prior receipt's ``[[press.remove]]`` set:
    a removal deletes its own precondition, so a forced re-press must not
    refuse over its predecessor's success)."""

    if not rules.remove:
        return []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.remove:
        prefix = f"remove target {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if not os.path.lexists(path):
            if rule.file in previously_removed:
                continue  # satisfied by the prior press (receipt-recorded)
            problems.append(
                prefix + "does not exist — a stale [[remove]] is config "
                "drift, never a silent no-op; delete the declaration or "
                "restore the file"
            )
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (targets must be committed so git "
                "provides the undo path)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        if has_uncommitted_changes(target, rule.file):
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (git restores only committed content)"
            )
    return problems


def render_remove_plan(rules: Rules) -> str:
    """The plan's removal section — every deletion visible before approval.

    Ends with a per-directory summary (spec E5b): one ``removing N file(s)
    under <dir>/`` line (singular for ``N == 1``) per top-level directory
    (the removal's SOURCE-path first component) that holds at least one
    declared removal — a quick count check against the per-file lines
    above it, not a replacement for them. A removal at the target root
    (no directory component) has nothing to group under and contributes
    no summary line.
    """

    lines = ["Remove (declared deletions, applied after the rewrite pass):"]
    for rule in rules.remove:
        lines.append(f"  [remove ] {rule.file}  —  {rule.reason}")
    counts: dict[str, int] = {}
    for rule in rules.remove:
        head, sep, _ = rule.file.partition("/")
        if sep:
            counts[head] = counts.get(head, 0) + 1
    for dirname in sorted(counts):
        count = counts[dirname]
        noun = "file" if count == 1 else "files"
        lines.append(f"  removing {count} {noun} under {dirname}/")
    return "\n".join(lines)


def remove_command_conflicts(rules: Rules, renamed: Mapping[str, str]) -> list[str]:
    """Refuse standalone target-relative argv paths an active removal deletes.

    Removals run before edits and regenerations. Without this plan-time gate,
    dry-run succeeds but apply deletes the argv path before the command can
    launch. Compare original and final paths, normalizing path syntax and
    filesystem aliases. Like ``stale_argv_elements``, this is best-effort:
    absolute paths, attached options, and command-language strings are not
    interpreted as target-relative paths.
    """

    removed = {
        _control_alias_key(path): r.file
        for r in rules.remove
        for path in (r.file, translate_path(r.file, renamed))
    }
    if not removed:
        return []
    problems: list[str] = []
    for kind, declarations in (
        ("edit", rules.edit),
        ("regenerate", rules.regenerate),
    ):
        for declaration in declarations:
            for element in declaration.command:
                norm = posixpath.normpath(element.replace("\\", "/"))
                removed_file = removed.get(_control_alias_key(norm))
                if removed_file is None:
                    continue
                problems.append(
                    f"remove target {removed_file!r}: argv element {element!r} "
                    f"in the [[{kind}]] command for {declaration.file!r} names "
                    f"its original or renamed location (including filesystem "
                    f"aliases) — the removal would delete it before the command "
                    f"runs; drop one declaration"
                )
    return problems


def apply_removals(
    target: Path,
    rules: Rules,
    renamed: dict[str, str],
    *,
    previously_removed: frozenset[str] = frozenset(),
) -> list[str]:
    """Delete every declared target at its post-rename location; return the
    removed rels (CURRENT coordinates) for the report and receipt. The
    write-path predicates re-run immediately before each unlink — the
    rewrite pass has run since the preflight. A target already removed by
    a prior press (receipt-recorded) is skipped, matching the preflight."""

    removed: list[str] = []
    for rule in rules.remove:
        rel = translate_path(rule.file, renamed)
        path = target / rel
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
        if not os.path.lexists(path):
            if rule.file in previously_removed:
                continue  # satisfied by the prior press
            raise SafetyError(f"remove target {rel} does not exist at apply time")
        if not is_regular_lstat(path):
            raise SafetyError(
                f"remove target {rel} is not a regular file at apply time "
                f"(no-follow check)"
            )
        os.unlink(path)
        removed.append(rel)
    return removed


def removal_receipt_text(target: Path, rules: Rules) -> str | None:
    """Bound active-directory receipt allocation before its first content read."""
    return read_receipt(
        target, max_bytes=REMOVE_HISTORY_MAX_BYTES if rules.remove_dirs else None
    )


def translate_removal_plan(
    plan: RemovalPlan, renamed: Mapping[str, str]
) -> RemovalPlan:
    """Translate exact current locations while preserving source audit coordinates."""

    def member_at_current(member: RemovalMember) -> RemovalMember:
        return replace(
            member, current_file=translate_path(member.current_file, renamed)
        )

    def directory_at_current(directory: DirectoryRemoval) -> DirectoryRemoval:
        return replace(
            directory,
            current_dir=translate_path(directory.current_dir, renamed),
            members=tuple(member_at_current(m) for m in directory.members),
        )

    return RemovalPlan(
        files=tuple(member_at_current(m) for m in plan.files),
        directories=tuple(directory_at_current(d) for d in plan.directories),
        retained_history=tuple(directory_at_current(d) for d in plan.retained_history),
    )


def removal_receipt_metadata(
    plan: RemovalPlan,
    legacy_removed: Mapping[str, str],
    *,
    removed: Collection[str] | None = None,
) -> tuple[list[tuple[str, str]], tuple[DirectoryRemoval, ...]]:
    """Build and validate known removal metadata before mutation and at output.

    Preflight omits ``removed``: every planned file must be unlinked or have
    licensed absence for execution to succeed. At output, actual unlinks select
    the emitted file rows. Directory rows always retain their frozen history.
    File-only legacy receipts deliberately keep their tolerant schema.
    """
    directories = (*plan.directories, *plan.retained_history)
    file_rows = [
        (member.file, member.reason)
        for member in plan.files
        if removed is None or member.current_file in removed or member.missing_ok
    ]
    directory_rows = [
        (member.file, member.reason)
        for directory in directories
        for member in directory.members
    ]
    emitted = {file for file, _ in (*file_rows, *directory_rows)}
    removals = [
        *file_rows,
        *directory_rows,
        *(
            (file, reason)
            for file, reason in legacy_removed.items()
            if file not in emitted
        ),
    ]
    if directories:
        validate_directory_history(directories, removals)
    return removals, directories


def validate_removal_plan(plan: RemovalPlan) -> None:
    """Validate all frozen history before the caller's first target mutation.

    Planning callers must invoke this before reset/rewrite, including on the
    projected translated plan. The executor repeats it before any unlink.
    """
    history = plan.directories + plan.retained_history
    if not history:
        return
    rows = [(member.file, member.reason) for member in plan.files]
    rows += [
        (member.file, member.reason)
        for directory in history
        for member in directory.members
    ]
    validate_directory_history(history, rows)


def _guard_frozen_remove_path(path: Path, target: Path) -> None:
    """Repeat static containment and junction guards for each exact operation."""
    assert_under_root(path, target)
    assert_ancestors_real(path, target)
    for ancestor in path.relative_to(target).parents:
        if (target / ancestor).is_junction():
            raise SafetyError("remove path has a junction ancestor")


def apply_removal_plan(
    target: Path, plan: RemovalPlan, renamed: Mapping[str, str]
) -> list[str]:
    """Unlink frozen members, then remove only their empty bounded ancestors."""
    translated = translate_removal_plan(plan, renamed)
    validate_removal_plan(translated)
    cleanup: set[str] = set()
    for directory in translated.directories:
        cleanup.add(directory.current_dir)
        root = PurePosixPath(directory.current_dir)
        for member in directory.members:
            for parent in PurePosixPath(member.current_file).parents:
                if parent == root:
                    break
                if root not in parent.parents:
                    raise SafetyError(
                        "directory member escaped its recorded current root"
                    )
                cleanup.add(parent.as_posix())
    removed: list[str] = []
    for member in translated.members:
        rel = member.current_file
        path = target / rel
        _guard_frozen_remove_path(path, target)
        if not os.path.lexists(path):
            if member.missing_ok:
                continue
            raise SafetyError(f"remove target {rel!r} does not exist at apply time")
        if path.is_junction() or not is_regular_lstat(path):
            raise SafetyError(
                f"remove target {rel!r} is not a regular file at apply time (no-follow check)"
            )
        os.unlink(path)
        removed.append(rel)
    for rel in sorted(cleanup, key=lambda value: (-value.count("/"), value)):
        path = target / rel
        _guard_frozen_remove_path(path, target)
        if not os.path.lexists(path):
            continue
        if (
            path.is_symlink()
            or path.is_junction()
            or not stat.S_ISDIR(path.lstat().st_mode)
        ):
            raise SafetyError(f"remove directory {rel!r} is not a real directory")
        try:
            os.rmdir(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
    return removed
