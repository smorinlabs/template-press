"""P06-TS01 -- raw surface and Git-visibility inventory contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from template_press.rebrand import inventory
from template_press.rebrand.engine import copy_paths, iter_target_files, scan_paths
from template_press.rebrand.inventory import (
    SurfaceEntry,
    SurfaceSnapshot,
    capture_surface_snapshot,
    gitlink_path_strings,
    listed_paths,
    parse_ls_files,
    select_content_rewrite_entries,
    select_copy_entries,
    select_inline_doctor_entries,
    select_rename_entries,
    select_symlink_entries,
    select_verifier_entries,
    tracked_path_strings,
)
from template_press.rebrand.rules import DEFAULT_RULES
from template_press.rebrand.safety import SafetyError

from .conftest import _git, posix_only, requires_symlink


def _entries(target: Path) -> dict[str, SurfaceEntry]:
    snapshot = capture_surface_snapshot(target)
    return {entry.rel.as_posix(): entry for entry in snapshot.entries}


def test_snapshot_classifies_tracked_visible_untracked_and_ignored(
    src_target: Path,
) -> None:
    with (src_target / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("ignored.txt\n")
    (src_target / "visible.txt").write_text("visible\n", encoding="utf-8")
    (src_target / "ignored.txt").write_text("ignored\n", encoding="utf-8")

    snapshot = capture_surface_snapshot(src_target)
    entries = {entry.rel.as_posix(): entry for entry in snapshot.entries}

    assert entries["README.md"] == SurfaceEntry(
        rel=Path("README.md"),
        tracked=True,
        index_kind="file",
        worktree_kind="file",
    )
    assert entries["visible.txt"] == SurfaceEntry(
        rel=Path("visible.txt"),
        tracked=False,
        index_kind=None,
        worktree_kind="file",
    )
    assert "ignored.txt" not in entries
    assert tuple(entry.rel.as_posix() for entry in snapshot.entries) == tuple(
        sorted(entries)
    )


def test_snapshot_separates_index_and_missing_worktree_state(src_target: Path) -> None:
    tracked = src_target / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "tracked.txt")
    _git(src_target, "commit", "-q", "-m", "add tracked file")
    tracked.unlink()

    assert _entries(src_target)["tracked.txt"] == SurfaceEntry(
        rel=Path("tracked.txt"),
        tracked=True,
        index_kind="file",
        worktree_kind="missing",
    )


def test_snapshot_separates_index_file_from_worktree_directory(
    src_target: Path,
) -> None:
    tracked = src_target / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "tracked.txt")
    _git(src_target, "commit", "-q", "-m", "add tracked file")
    tracked.unlink()
    tracked.mkdir()

    assert _entries(src_target)["tracked.txt"] == SurfaceEntry(
        rel=Path("tracked.txt"),
        tracked=True,
        index_kind="file",
        worktree_kind="directory",
    )


@requires_symlink
def test_snapshot_classifies_index_and_worktree_symlink_without_following(
    src_target: Path,
) -> None:
    link = src_target / "linked"
    link.symlink_to("README.md")
    _git(src_target, "add", "linked")
    _git(src_target, "commit", "-q", "-m", "add symlink")

    assert _entries(src_target)["linked"] == SurfaceEntry(
        rel=Path("linked"),
        tracked=True,
        index_kind="symlink",
        worktree_kind="symlink",
    )


def test_snapshot_classifies_uninitialized_gitlink_from_index(
    src_target: Path, tmp_path: Path
) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q", "-b", "main")
    _git(inner, "config", "user.email", "test@example.com")
    _git(inner, "config", "user.name", "Test")
    (inner / "file.txt").write_text("content\n", encoding="utf-8")
    _git(inner, "add", "file.txt")
    _git(inner, "commit", "-q", "-m", "inner")
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(inner), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    _git(src_target, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")

    assert _entries(src_target)["sub"] == SurfaceEntry(
        rel=Path("sub"),
        tracked=True,
        index_kind="gitlink",
        worktree_kind="missing",
    )

    (src_target / "sub").mkdir()
    assert _entries(src_target)["sub"] == SurfaceEntry(
        rel=Path("sub"),
        tracked=True,
        index_kind="gitlink",
        worktree_kind="directory",
    )


@requires_symlink
def test_snapshot_keeps_index_symlink_when_worktree_replaced_by_file(
    src_target: Path,
) -> None:
    path = src_target / "swapped"
    path.symlink_to("README.md")
    _git(src_target, "add", "swapped")
    _git(src_target, "commit", "-q", "-m", "add tracked symlink")
    path.unlink()
    path.write_text("ordinary file\n", encoding="utf-8")

    assert _entries(src_target)["swapped"] == SurfaceEntry(
        rel=Path("swapped"),
        tracked=True,
        index_kind="symlink",
        worktree_kind="file",
    )


@requires_symlink
def test_snapshot_keeps_index_file_when_worktree_replaced_by_symlink(
    src_target: Path,
) -> None:
    path = src_target / "swapped"
    path.write_text("ordinary file\n", encoding="utf-8")
    _git(src_target, "add", "swapped")
    _git(src_target, "commit", "-q", "-m", "add tracked file")
    path.unlink()
    path.symlink_to("README.md")

    assert _entries(src_target)["swapped"] == SurfaceEntry(
        rel=Path("swapped"),
        tracked=True,
        index_kind="file",
        worktree_kind="symlink",
    )


@requires_symlink
def test_snapshot_never_traverses_symlink_ancestor_for_worktree_kind(
    src_target: Path, tmp_path: Path
) -> None:
    nested = src_target / "a"
    nested.mkdir()
    leaf = nested / "leaf.txt"
    leaf.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "a/leaf.txt")
    _git(src_target, "commit", "-q", "-m", "add nested file")
    leaf.unlink()
    nested.rmdir()
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    (outside / "leaf.txt").write_text("external\n", encoding="utf-8")
    nested.symlink_to(outside, target_is_directory=True)

    assert _entries(src_target)["a/leaf.txt"] == SurfaceEntry(
        rel=Path("a/leaf.txt"),
        tracked=True,
        index_kind="file",
        worktree_kind="other",
    )


@posix_only
def test_snapshot_classifies_visible_fifo_as_other(src_target: Path) -> None:
    fifo = src_target / "events.pipe"
    fifo.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "events.pipe")
    _git(src_target, "commit", "-q", "-m", "add tracked file")
    fifo.unlink()
    os.mkfifo(fifo)

    assert _entries(src_target)["events.pipe"] == SurfaceEntry(
        rel=Path("events.pipe"),
        tracked=True,
        index_kind="file",
        worktree_kind="other",
    )


def test_ls_files_parser_round_trips_non_utf8_and_combined_record_shapes() -> None:
    raw = (
        b"? visible\xff.txt\0"
        b"H 100644 " + b"0" * 40 + b" 0\ttracked.txt\0"
        b"H 120000 " + b"1" * 40 + b" 0\tlinked\0"
        b"H 160000 " + b"2" * 40 + b" 0\tsub\0"
    )

    parsed = parse_ls_files(raw)
    by_path = {item[0].as_posix(): item[1:] for item in parsed}

    visible = next(item for item in parsed if not item[1])
    assert (
        visible[0].as_posix().encode("utf-8", "surrogateescape") == b"visible\xff.txt"
    )
    assert by_path == {
        "linked": (True, "symlink"),
        "sub": (True, "gitlink"),
        "tracked.txt": (True, "file"),
        visible[0].as_posix(): (False, None),
    }
    assert [item[0].as_posix() for item in parsed] == sorted(by_path)


@pytest.mark.parametrize("unsafe", [b"../outside", b".git/config", b".GIT/config"])
def test_ls_files_parser_rejects_unsafe_git_paths(unsafe: bytes) -> None:
    with pytest.raises(ValueError):
        parse_ls_files(b"? " + unsafe + b"\0")


def test_ls_files_parser_refuses_unmerged_index_stages() -> None:
    raw = b"M 100644 " + b"0" * 40 + b" 2\tconflicted.txt\0"

    with pytest.raises(SafetyError, match="unmerged"):
        parse_ls_files(raw)


@posix_only
def test_snapshot_preserves_legal_posix_backslash_and_colon_names(
    src_target: Path,
) -> None:
    names = ("a\\b.txt", "a:b.txt")
    for name in names:
        (src_target / name).write_text("content\n", encoding="utf-8")
    _git(src_target, "add", "--", *names)
    _git(src_target, "commit", "-q", "-m", "add punctuation names")

    entries = _entries(src_target)

    for name in names:
        assert name in entries
        assert entries[name].worktree_kind == "file"
        assert os.fsencode(entries[name].rel.as_posix()) == os.fsencode(name)


def test_visibility_inventory_captures_gitignore_info_and_local_core_excludes(
    src_target: Path,
) -> None:
    info_exclude = src_target / ".git" / "info" / "exclude"
    info_exclude.write_text("info-secret.txt\n", encoding="utf-8")
    core_excludes = src_target / "press-core-excludes"
    core_excludes.write_text("core-secret.txt\n", encoding="utf-8")
    _git(src_target, "config", "--local", "core.excludesFile", str(core_excludes))

    snapshot = capture_surface_snapshot(src_target)
    inputs = {item.origin: item for item in snapshot.visibility_inputs}

    assert set(inputs) == {"gitignore", "info_exclude", "core_excludes_file"}
    assert inputs["gitignore"].path == src_target / ".gitignore"
    assert inputs["gitignore"].kind == "file"
    assert inputs["gitignore"].sha256 is not None
    assert inputs["gitignore"].link_text is None
    assert inputs["info_exclude"].path == info_exclude
    assert inputs["info_exclude"].kind == "file"
    assert inputs["info_exclude"].sha256 is not None
    assert inputs["core_excludes_file"].path == core_excludes
    assert inputs["core_excludes_file"].kind == "file"
    assert inputs["core_excludes_file"].sha256 is not None


def test_visibility_inventory_resolves_relative_local_core_excludes(
    src_target: Path,
) -> None:
    config_dir = src_target / "config"
    config_dir.mkdir()
    excludes = config_dir / "ignore"
    excludes.write_text("core-hidden.txt\n", encoding="utf-8")
    (src_target / "core-hidden.txt").write_text("hidden\n", encoding="utf-8")
    _git(src_target, "config", "--local", "core.excludesFile", "config/ignore")

    snapshot = capture_surface_snapshot(src_target)
    core = next(
        item
        for item in snapshot.visibility_inputs
        if item.origin == "core_excludes_file"
    )

    assert core.path == excludes
    assert core.kind == "file"
    assert "core-hidden.txt" not in {entry.rel.as_posix() for entry in snapshot.entries}


def test_visibility_inventory_preserves_whitespace_in_core_excludes_path(
    src_target: Path,
) -> None:
    excludes = src_target / " odd "
    excludes.write_text("hidden-by-spaces.txt\n", encoding="utf-8")
    (src_target / "hidden-by-spaces.txt").write_text("hidden\n", encoding="utf-8")
    _git(src_target, "config", "--local", "core.excludesFile", " odd ")

    snapshot = capture_surface_snapshot(src_target)
    core = next(
        item
        for item in snapshot.visibility_inputs
        if item.origin == "core_excludes_file"
    )

    assert core.path == excludes
    assert core.kind == "file"
    assert "hidden-by-spaces.txt" not in {
        entry.rel.as_posix() for entry in snapshot.entries
    }


def test_visibility_inventory_uses_effective_worktree_core_excludes(
    src_target: Path, tmp_path: Path
) -> None:
    _git(src_target, "config", "extensions.worktreeConfig", "true")
    linked = tmp_path / "linked-with-config"
    _git(src_target, "worktree", "add", "--detach", str(linked), "HEAD")
    excludes = linked / "wt-ignore"
    excludes.write_text("hidden-by-worktree.txt\n", encoding="utf-8")
    (linked / "hidden-by-worktree.txt").write_text("hidden\n", encoding="utf-8")
    _git(linked, "config", "--worktree", "core.excludesFile", "wt-ignore")

    snapshot = capture_surface_snapshot(linked)
    core = next(
        item
        for item in snapshot.visibility_inputs
        if item.origin == "core_excludes_file"
    )

    assert core.path == excludes
    assert core.kind == "file"
    assert "hidden-by-worktree.txt" not in {
        entry.rel.as_posix() for entry in snapshot.entries
    }


def test_visibility_inventory_uses_core_excludes_from_local_include(
    src_target: Path,
) -> None:
    included = src_target / "included-config"
    excludes = src_target / "included-ignore"
    excludes.write_text("hidden-by-include.txt\n", encoding="utf-8")
    included.write_text(
        f"[core]\n\texcludesFile = {excludes.as_posix()}\n", encoding="utf-8"
    )
    (src_target / "hidden-by-include.txt").write_text("hidden\n", encoding="utf-8")
    _git(src_target, "config", "--local", "include.path", str(included))

    snapshot = capture_surface_snapshot(src_target)
    core = next(
        item
        for item in snapshot.visibility_inputs
        if item.origin == "core_excludes_file"
    )

    assert core.path == excludes
    assert "hidden-by-include.txt" not in {
        entry.rel.as_posix() for entry in snapshot.entries
    }


def test_visibility_inventory_expands_prefix_include_path(
    src_target: Path, tmp_path: Path
) -> None:
    included = tmp_path / "prefix-included-config"
    excludes = src_target / "prefix-included-ignore"
    excludes.write_text("hidden-by-prefix.txt\n", encoding="utf-8")
    included.write_text(
        f"[core]\n\texcludesFile = {excludes.as_posix()}\n", encoding="utf-8"
    )
    (src_target / "hidden-by-prefix.txt").write_text("hidden\n", encoding="utf-8")
    prefix = inventory._git_exec_prefix(src_target)
    relative = os.path.relpath(included, prefix)
    _git(src_target, "config", "--local", "include.path", f"%(prefix)/{relative}")

    snapshot = capture_surface_snapshot(src_target)

    assert "hidden-by-prefix.txt" not in {
        entry.rel.as_posix() for entry in snapshot.entries
    }


def test_visibility_inventory_allows_missing_prefix_include(
    src_target: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-prefix-include"
    prefix = inventory._git_exec_prefix(src_target)
    relative = os.path.relpath(missing, prefix)
    _git(src_target, "config", "--local", "include.path", f"%(prefix)/{relative}")

    snapshot = capture_surface_snapshot(src_target)

    assert snapshot.entries
    assert not missing.exists()


def test_inventory_ignores_ambient_xdg_and_command_scope_excludes(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    ambient_ignore = xdg / "git" / "ignore"
    ambient_ignore.write_text("ambient-hidden.txt\n", encoding="utf-8")
    (src_target / "ambient-hidden.txt").write_text(
        "must stay visible\n", encoding="utf-8"
    )
    injected_ignore = tmp_path / "injected-ignore"
    injected_ignore.write_text("injected-hidden.txt\n", encoding="utf-8")
    (src_target / "injected-hidden.txt").write_text(
        "must stay visible\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(injected_ignore))

    snapshot = capture_surface_snapshot(src_target)
    rels = {entry.rel.as_posix() for entry in snapshot.entries}

    assert "ambient-hidden.txt" in rels
    assert "injected-hidden.txt" in rels
    assert not any(
        item.path in {ambient_ignore, injected_ignore}
        for item in snapshot.visibility_inputs
    )


def test_visibility_inventory_includes_active_self_ignored_gitignore_files(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    _git(src_target, "rm", "--cached", ".gitignore")
    gitignore.write_text(".gitignore\n*.secret\n", encoding="utf-8")
    nested = src_target / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("*.private\n", encoding="utf-8")
    (nested / "hidden.private").write_text("hidden\n", encoding="utf-8")

    snapshot = capture_surface_snapshot(src_target)
    gitignores = {
        item.path for item in snapshot.visibility_inputs if item.origin == "gitignore"
    }

    assert gitignore in gitignores
    assert nested / ".gitignore" in gitignores
    assert ".gitignore" not in {entry.rel.as_posix() for entry in snapshot.entries}
    assert "nested/.gitignore" not in {
        entry.rel.as_posix() for entry in snapshot.entries
    }


def test_visibility_inventory_resolves_linked_worktree_info_exclude(
    src_target: Path, tmp_path: Path
) -> None:
    linked = tmp_path / "linked"
    _git(src_target, "worktree", "add", "--detach", str(linked), "HEAD")

    snapshot = capture_surface_snapshot(linked)
    info = next(
        item for item in snapshot.visibility_inputs if item.origin == "info_exclude"
    )

    assert info.path == src_target / ".git" / "info" / "exclude"
    assert info.kind == "file"
    assert info.sha256 is not None


@requires_symlink
def test_visibility_inventory_preserves_whitespace_in_resolved_info_exclude(
    src_target: Path,
) -> None:
    info_exclude = src_target / ".git" / "info" / "exclude"
    backing = src_target / " info backing "
    backing.write_text("hidden-by-info.txt\n", encoding="utf-8")
    info_exclude.unlink()
    info_exclude.symlink_to(backing)
    (src_target / "hidden-by-info.txt").write_text("hidden\n", encoding="utf-8")

    first = capture_surface_snapshot(src_target)
    info_first = next(
        item for item in first.visibility_inputs if item.origin == "info_exclude"
    )
    backing.write_text("different.txt\n", encoding="utf-8")
    second = capture_surface_snapshot(src_target)
    info_second = next(
        item for item in second.visibility_inputs if item.origin == "info_exclude"
    )

    assert info_first.path == backing
    assert info_first.kind == "file"
    assert info_first.sha256 is not None
    assert info_first != info_second


def test_visibility_inputs_keep_missing_and_multiple_gitignores_in_stable_order(
    src_target: Path,
) -> None:
    root_ignore = src_target / ".gitignore"
    root_bytes = root_ignore.read_bytes()
    root_ignore.unlink()
    for name in ("alpha", "beta"):
        directory = src_target / name
        directory.mkdir()
        (directory / ".gitignore").write_text("*.secret\n", encoding="utf-8")

    first = capture_surface_snapshot(src_target)
    second = capture_surface_snapshot(src_target)
    gitignores = [
        item for item in first.visibility_inputs if item.origin == "gitignore"
    ]

    assert first == second
    assert {item.path for item in gitignores} == {
        root_ignore,
        src_target / "alpha" / ".gitignore",
        src_target / "beta" / ".gitignore",
    }
    assert next(item for item in gitignores if item.path == root_ignore).kind == (
        "missing"
    )
    order = {"gitignore": 0, "info_exclude": 1, "core_excludes_file": 2}
    keys = [
        (order[item.origin], item.path.as_posix()) for item in first.visibility_inputs
    ]
    assert keys == sorted(keys)

    root_ignore.write_bytes(root_bytes)
    recreated = capture_surface_snapshot(src_target)
    assert first.visibility_inputs != recreated.visibility_inputs
    restored = next(
        item
        for item in recreated.visibility_inputs
        if item.origin == "gitignore" and item.path == root_ignore
    )
    assert restored.kind == "file"


@requires_symlink
def test_visibility_inventory_refuses_core_excludes_beneath_symlink_ancestor(
    src_target: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "excludes").write_text("*.secret\n", encoding="utf-8")
    linked_dir = src_target / "linked-config"
    linked_dir.symlink_to(outside, target_is_directory=True)
    _git(
        src_target,
        "config",
        "--local",
        "core.excludesFile",
        str(linked_dir / "excludes"),
    )

    with pytest.raises(SafetyError, match="symlink"):
        capture_surface_snapshot(src_target)


@requires_symlink
def test_visibility_inventory_refuses_symlink_core_excludes_leaf(
    src_target: Path,
) -> None:
    backing = src_target / "real-excludes"
    backing.write_text("hidden.txt\n", encoding="utf-8")
    linked = src_target / "linked-excludes"
    linked.symlink_to(backing.name)
    _git(src_target, "config", "--local", "core.excludesFile", linked.name)

    with pytest.raises(SafetyError, match="symbolic link"):
        capture_surface_snapshot(src_target)


@requires_symlink
def test_visibility_inventory_distinguishes_regular_gitignore_from_symlink(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    original = gitignore.read_bytes()
    snapshot_regular = capture_surface_snapshot(src_target)
    regular = next(
        item for item in snapshot_regular.visibility_inputs if item.path == gitignore
    )

    backing = src_target / "gitignore-backing"
    backing.write_bytes(original)
    gitignore.unlink()
    gitignore.symlink_to(backing.name)
    snapshot_symlink = capture_surface_snapshot(src_target)
    symlink = next(
        item for item in snapshot_symlink.visibility_inputs if item.path == gitignore
    )

    assert regular.kind == "file"
    assert regular.sha256 is not None
    assert regular.link_text is None
    assert symlink.kind == "symlink"
    assert symlink.sha256 is None
    assert symlink.link_text == backing.name
    assert regular != symlink


def test_every_inventory_git_call_uses_target_hardening(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict]] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append((list(cmd), kwargs))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(inventory.subprocess, "run", spy)

    capture_surface_snapshot(src_target)

    assert calls
    # One seed learns opaque gitlink boundaries; two bracketed candidates
    # must then agree before the public snapshot is accepted.
    assert sum("ls-files" in cmd for cmd, _kwargs in calls) == 3
    for cmd, kwargs in calls:
        assert cmd[0] == "git"
        assert "core.fsmonitor=" in cmd
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == os.devnull
        assert kwargs["env"]["GIT_CONFIG_SYSTEM"] == os.devnull


def test_capture_refuses_ignore_policy_changed_during_enumeration(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("old-only.txt\n", encoding="utf-8")
    (src_target / "leak.txt").write_text("visible before change\n", encoding="utf-8")
    real_run_git = inventory._run_git
    changed = False

    def mutate_after_listing(target: Path, *args: str, **kwargs):
        nonlocal changed
        result = real_run_git(target, *args, **kwargs)
        if "ls-files" in args and "--others" in args and not changed:
            changed = True
            gitignore.write_text("leak.txt\n", encoding="utf-8")
        return result

    monkeypatch.setattr(inventory, "_run_git", mutate_after_listing)

    with pytest.raises(SafetyError, match="visibility changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_refuses_transient_ignore_policy_during_every_enumeration(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = src_target / "transient"
    nested.mkdir()
    leak = nested / "leak.txt"
    leak.write_text("must remain visible\n", encoding="utf-8")
    gitignore = nested / ".gitignore"
    real_run_git = inventory._run_git

    def transient_ignore(target: Path, *args: str, **kwargs):
        if "ls-files" in args:
            gitignore.write_text(".gitignore\nleak.txt\n", encoding="utf-8")
            result = real_run_git(target, *args, **kwargs)
            gitignore.unlink()
            return result
        return real_run_git(target, *args, **kwargs)

    monkeypatch.setattr(inventory, "_run_git", transient_ignore)

    with pytest.raises(SafetyError, match="changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_refuses_same_ignore_transition_during_every_enumeration(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("old-only.txt\n", encoding="utf-8")
    (src_target / "leak.txt").write_text("visible under old policy\n", encoding="utf-8")
    real_run_git = inventory._run_git

    def repeat_transition(target: Path, *args: str, **kwargs):
        if "ls-files" not in args:
            return real_run_git(target, *args, **kwargs)
        gitignore.write_text("old-only.txt\n", encoding="utf-8")
        result = real_run_git(target, *args, **kwargs)
        gitignore.write_text("leak.txt\n", encoding="utf-8")
        return result

    monkeypatch.setattr(inventory, "_run_git", repeat_transition)

    with pytest.raises(SafetyError, match="changed during capture"):
        capture_surface_snapshot(src_target)


def test_inventory_preserves_effective_case_insensitive_ignore_matching(
    src_target: Path,
) -> None:
    (src_target / ".gitignore").write_text("FOO\n", encoding="utf-8")
    (src_target / "foo").write_text("must remain visible\n", encoding="utf-8")
    _git(src_target, "config", "core.ignoreCase", "true")

    rels = {
        entry.rel.as_posix() for entry in capture_surface_snapshot(src_target).entries
    }

    assert "foo" not in rels


def test_capture_refuses_repeated_core_excludes_config_transition(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ignore_a = src_target / "ignore-a"
    ignore_b = src_target / "ignore-b"
    ignore_a.write_text("hide-a\n", encoding="utf-8")
    ignore_b.write_text("hide-b\n", encoding="utf-8")
    (src_target / "hide-a").write_text("visible under B\n", encoding="utf-8")
    (src_target / "hide-b").write_text("hidden under B\n", encoding="utf-8")
    _git(src_target, "config", "core.excludesFile", ignore_b.name)
    real_resolver = inventory._core_excludes_path

    def repeat_transition(target: Path) -> Path | None:
        _git(target, "config", "core.excludesFile", ignore_a.name)
        resolved = real_resolver(target)
        _git(target, "config", "core.excludesFile", ignore_b.name)
        return resolved

    monkeypatch.setattr(inventory, "_core_excludes_path", repeat_transition)

    with pytest.raises(SafetyError, match=r"config.*changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_refuses_temporary_missing_config_include(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    include_parent = tmp_path / "include-parent"
    include_parent.mkdir()
    included = include_parent / "optional-config"
    ignore_a = src_target / "ignore-a"
    ignore_a.write_text("hide-a\n", encoding="utf-8")
    (src_target / "hide-a").write_text("visible without include\n", encoding="utf-8")
    _git(src_target, "config", "include.path", str(included))
    real_resolver = inventory._core_excludes_path

    def temporary_include(target: Path) -> Path | None:
        included.write_text(f"[core]\n\texcludesFile = {ignore_a}\n", encoding="utf-8")
        try:
            return real_resolver(target)
        finally:
            included.unlink()

    monkeypatch.setattr(inventory, "_core_excludes_path", temporary_include)

    with pytest.raises(SafetyError, match=r"config.*changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_refuses_temporary_onbranch_include_activation(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    included = src_target / "conditional-config"
    ignore_a = src_target / "ignore-a"
    included.write_text(f"[core]\n\texcludesFile = {ignore_a}\n", encoding="utf-8")
    ignore_a.write_text("hide-a\n", encoding="utf-8")
    (src_target / "hide-a").write_text("visible on main\n", encoding="utf-8")
    _git(src_target, "branch", "feature")
    _git(
        src_target,
        "config",
        "includeIf.onbranch:feature.path",
        str(included),
    )
    head = src_target / ".git" / "HEAD"
    main_head = head.read_bytes()
    real_resolver = inventory._core_excludes_path

    def temporary_feature_branch(target: Path) -> Path | None:
        head.write_text("ref: refs/heads/feature\n", encoding="utf-8")
        try:
            return real_resolver(target)
        finally:
            head.write_bytes(main_head)

    monkeypatch.setattr(inventory, "_core_excludes_path", temporary_feature_branch)

    with pytest.raises(SafetyError, match=r"config.*changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_refuses_temporary_linked_worktree_gitdir_redirect(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = tmp_path / "linked-redirect"
    _git(src_target, "worktree", "add", "--detach", str(linked), "HEAD")
    git_pointer = linked / ".git"
    original_pointer = git_pointer.read_bytes()

    other = tmp_path / "other-repo"
    other.mkdir()
    _git(other, "init", "-q")
    ignore_a = linked / "ignore-a"
    ignore_a.write_text("hide-a\n", encoding="utf-8")
    (linked / "hide-a").write_text("visible in linked worktree\n", encoding="utf-8")
    _git(other, "config", "core.excludesFile", str(ignore_a))
    other_pointer = f"gitdir: {(other / '.git').as_posix()}\n"
    real_resolver = inventory._core_excludes_path

    def temporary_other_repo(target: Path) -> Path | None:
        git_pointer.write_text(other_pointer, encoding="utf-8")
        try:
            return real_resolver(target)
        finally:
            git_pointer.write_bytes(original_pointer)

    monkeypatch.setattr(inventory, "_core_excludes_path", temporary_other_repo)

    with pytest.raises(SafetyError, match=r"config.*changed during capture"):
        capture_surface_snapshot(linked)


def test_capture_refuses_temporary_alternate_git_index(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = src_target / "secret.txt"
    secret.write_text("tracked and ignored\n", encoding="utf-8")
    (src_target / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _git(src_target, "add", "-f", secret.name)
    _git(src_target, "add", ".gitignore")
    _git(src_target, "commit", "-q", "-m", "track ignored secret")

    index = src_target / ".git" / "index"
    original_index = index.read_bytes()
    alternate_index = tmp_path / "alternate-index"
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(alternate_index)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "read-tree", "HEAD^"],  # noqa: S607
        check=True,
        capture_output=True,
        env=env,
    )
    alternate_bytes = alternate_index.read_bytes()
    real_run_git = inventory._run_git

    def temporary_index(target: Path, *args: str, **kwargs):
        if "ls-files" not in args:
            return real_run_git(target, *args, **kwargs)
        index.write_bytes(alternate_bytes)
        try:
            return real_run_git(target, *args, **kwargs)
        finally:
            index.write_bytes(original_index)

    monkeypatch.setattr(inventory, "_run_git", temporary_index)

    with pytest.raises(SafetyError, match="changed during capture"):
        capture_surface_snapshot(src_target)


def test_capture_accepts_stable_split_index(src_target: Path) -> None:
    _git(src_target, "update-index", "--split-index")

    first = capture_surface_snapshot(src_target)
    second = capture_surface_snapshot(src_target)

    assert first == second
    assert "README.md" in {entry.rel.as_posix() for entry in first.entries}


@posix_only
@requires_symlink
def test_visibility_read_refuses_ancestor_swap_at_descriptor_open(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    configured = src_target / "config"
    configured.mkdir()
    excludes = configured / "excludes"
    excludes.write_text("inside-only.txt\n", encoding="utf-8")
    _git(src_target, "config", "core.excludesFile", "config/excludes")
    external = tmp_path / "external-config"
    external.mkdir()
    (external / "excludes").write_text("outside-only.txt\n", encoding="utf-8")
    original = tmp_path / "original-config"
    real_read = safety._read_regular_openat
    swapped = False

    def swap_ancestor_before_open(path: Path) -> bytes:
        nonlocal swapped
        if path == excludes and not swapped:
            configured.rename(original)
            configured.symlink_to(external, target_is_directory=True)
            swapped = True
        return real_read(path)

    monkeypatch.setattr(safety, "_read_regular_openat", swap_ancestor_before_open)

    with pytest.raises(SafetyError, match="visibility input"):
        capture_surface_snapshot(src_target)


def test_copy_adapter_marks_present_unmaterializable_nodes(
    src_target: Path,
) -> None:
    missing = src_target / "tracked-missing.txt"
    missing.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", missing.name)
    _git(src_target, "commit", "-q", "-m", "add tracked missing")
    missing.unlink()
    occupied = src_target / "occupied"
    occupied.write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", occupied.name)
    _git(src_target, "commit", "-q", "-m", "add tracked occupied")
    occupied.unlink()
    occupied.mkdir()

    entries = {entry.rel.as_posix(): entry.kind for entry in copy_paths(src_target)}

    assert missing.name not in entries
    assert entries[occupied.name] == "unscannable"


def test_dirty_gitlink_file_replacement_is_scannable_worktree_content(
    src_target: Path,
) -> None:
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(
        src_target,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{head},sub",
    )
    (src_target / "sub").write_text("demo_widget survives\n", encoding="utf-8")

    copied = {entry.rel.as_posix(): entry.kind for entry in copy_paths(src_target)}
    scanned = {
        entry.rel.as_posix(): entry.kind
        for entry in scan_paths(src_target, DEFAULT_RULES)
    }

    assert copied["sub"] == "file"
    assert scanned["sub"] == "file"


@requires_symlink
def test_dirty_gitlink_symlink_replacement_is_scannable_link_text(
    src_target: Path,
) -> None:
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(
        src_target,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{head},sub",
    )
    (src_target / "sub").symlink_to("missing/demo_widget")

    copied = {entry.rel.as_posix(): entry.kind for entry in copy_paths(src_target)}
    scanned = {
        entry.rel.as_posix(): entry.kind
        for entry in scan_paths(src_target, DEFAULT_RULES)
    }

    assert copied["sub"] == "symlink"
    assert scanned["sub"] == "symlink"


@requires_symlink
def test_adapters_do_not_follow_symlink_ancestor_outside_target(
    src_target: Path, tmp_path: Path
) -> None:
    tracked = src_target / "ancestor" / "leaf.txt"
    tracked.parent.mkdir()
    tracked.write_text("inside\n", encoding="utf-8")
    _git(src_target, "add", "ancestor/leaf.txt")
    _git(src_target, "commit", "-q", "-m", "add nested tracked file")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaf.txt").write_text("demo_widget outside\n", encoding="utf-8")
    tracked.unlink()
    tracked.parent.rmdir()
    tracked.parent.symlink_to(outside, target_is_directory=True)

    assert tracked not in iter_target_files(src_target, DEFAULT_RULES)
    selected = {
        entry.rel.as_posix(): entry.kind
        for entry in scan_paths(src_target, DEFAULT_RULES)
    }
    assert selected["ancestor/leaf.txt"] == "unscannable"


def test_visibility_walk_does_not_descend_into_checked_out_gitlink(
    src_target: Path,
) -> None:
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(
        src_target,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{head},sub",
    )
    sub = src_target / "sub"
    sub.mkdir()
    inner_ignore = sub / ".gitignore"
    inner_ignore.write_text("hidden.txt\n", encoding="utf-8")

    snapshot = capture_surface_snapshot(src_target)

    assert inner_ignore not in {item.path for item in snapshot.visibility_inputs}


@requires_symlink
def test_visibility_walk_refuses_directory_swapped_to_symlink(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = src_target / "nested"
    nested.mkdir()
    external = tmp_path / "external-ignore-tree"
    external.mkdir()
    (external / ".gitignore").write_text("hidden.txt\n", encoding="utf-8")
    original = tmp_path / "original-nested"
    real_ignored_directories = inventory._ignored_directories
    real_scandir = inventory.os.scandir
    swapped = False

    def swap_after_child_selection(target, rels, core_excludes):
        nonlocal swapped
        result = real_ignored_directories(target, rels, core_excludes)
        if not swapped and Path("nested") in rels:
            nested.rename(original)
            nested.symlink_to(external, target_is_directory=True)
            swapped = True
        return result

    def refuse_external_scandir(path):
        if Path(path) == nested and nested.is_symlink():
            pytest.fail("visibility walk followed a swapped symlink directory")
        return real_scandir(path)

    monkeypatch.setattr(inventory, "_ignored_directories", swap_after_child_selection)
    monkeypatch.setattr(inventory.os, "scandir", refuse_external_scandir)

    with pytest.raises(SafetyError, match="ignore directory"):
        capture_surface_snapshot(src_target)


def test_consumer_selectors_keep_their_distinct_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def entry(
        rel: str,
        *,
        tracked: bool = True,
        index_kind: str | None = "file",
        worktree_kind: str = "file",
    ) -> SurfaceEntry:
        return SurfaceEntry(  # type: ignore[arg-type]
            Path(rel), tracked, index_kind, worktree_kind
        )

    snapshot = SurfaceSnapshot(
        tuple(
            sorted(
                (
                    entry("README.md"),
                    entry("link", index_kind="symlink", worktree_kind="symlink"),
                    entry("sub", index_kind="gitlink", worktree_kind="missing"),
                    entry("missing", worktree_kind="missing"),
                    entry("occupied", worktree_kind="directory"),
                    entry("press/press-source.toml"),
                    entry("uv.lock"),
                    entry("bun.lock"),
                    entry("package-lock.json"),
                    entry("node_modules/forced.js"),
                    entry("custom.skip"),
                    entry("vendor/forced.txt"),
                    entry("legacy/history.txt"),
                ),
                key=lambda item: item.rel.as_posix(),
            )
        ),
        (),
    )
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("pure selector invoked Git"),
    )

    def rels(entries) -> set[str]:
        return {item.rel.as_posix() for item in entries}

    root_control = frozenset({"press/press-source.toml"})
    built_in_files = frozenset(
        {"uv.lock", "bun.lock", "package-lock.json", "CHANGELOG.md"}
    )
    built_in_dirs = frozenset({"node_modules", ".git"})

    assert rels(select_copy_entries(snapshot)) == {
        "README.md",
        "link",
        "sub",
        "occupied",
        "press/press-source.toml",
        "uv.lock",
        "bun.lock",
        "package-lock.json",
        "node_modules/forced.js",
        "custom.skip",
        "vendor/forced.txt",
        "legacy/history.txt",
    }
    assert rels(
        select_content_rewrite_entries(
            snapshot,
            exclude_files=built_in_files | {"custom.skip"},
            exclude_dirs=built_in_dirs | {"vendor"},
            root_control=root_control,
        )
    ) == {"README.md", "legacy/history.txt"}
    assert rels(
        select_rename_entries(
            snapshot,
            exclude_files=built_in_files | {"custom.skip"},
            exclude_dirs=built_in_dirs | {"vendor"},
            root_control=root_control,
        )
    ) == {"README.md", "link", "legacy/history.txt"}
    assert rels(
        select_inline_doctor_entries(
            snapshot,
            built_in_exclude_files=built_in_files,
            built_in_exclude_dirs=built_in_dirs,
            verify_ignore=frozenset({"legacy"}),
            root_control=root_control,
        )
    ) == {
        "README.md",
        "link",
        "sub",
        "missing",
        "occupied",
        "custom.skip",
        "vendor/forced.txt",
    }
    assert rels(
        select_verifier_entries(
            snapshot,
            verify_ignore=frozenset({"legacy"}),
            root_control=root_control,
            exempt_paths=frozenset({"bun.lock"}),
        )
    ) == {
        "README.md",
        "link",
        "sub",
        "missing",
        "occupied",
        "uv.lock",
        "package-lock.json",
        "node_modules/forced.js",
        "custom.skip",
        "vendor/forced.txt",
    }
    assert rels(select_symlink_entries(snapshot)) == {"link"}
    assert tracked_path_strings(snapshot) == frozenset(
        item.rel.as_posix() for item in snapshot.entries
    )
    assert gitlink_path_strings(snapshot) == frozenset({"sub"})
    assert listed_paths(snapshot) == tuple(item.rel for item in snapshot.entries)
