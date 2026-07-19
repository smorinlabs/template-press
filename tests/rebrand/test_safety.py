"""Hostile-input tests for the safe-I/O + test-isolation harness (Task 0.5).

One (or more) failing-first test per Defensive-Hardening guard G1-G9. The
overriding invariant under test: nothing is written, renamed, or deleted
outside the intended root, in production OR in tests. Every decoy lives under
``tmp_path/"outside"/...`` — never a literal ``/tmp``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from template_press.rebrand.safety import (
    ContainmentError,
    HardlinkError,
    SafetyError,
    UnsafePathError,
    assert_under_root,
    git_hardening_args,
    is_regular_lstat,
    owned_sandbox,
    refuse_unsafe_root,
    safe_mkdir,
    safe_rename,
    safe_write,
    scrubbed_git_env,
    scrubbed_uv_env,
    write_control,
)

from .conftest import _can_symlink, requires_symlink

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args, **kwargs):
    # git is hardcoded; args/paths are test-controlled, not untrusted input.
    return subprocess.run(["git", *args], **kwargs)  # noqa: S603, S607


# ---------------------------------------------------------------------------
# G2 / G2+ — SafeRelPath: typed gate on every hostile path component
# ---------------------------------------------------------------------------
HOSTILE_RELPATHS = [
    "",  # empty
    ".",  # dot
    "..",  # parent
    "a/../b",  # traversal component
    "/etc/passwd",  # absolute
    "sub/dir/",  # trailing slash -> empty component
    "a//b",  # doubled separator -> empty component
    "a/./b",  # noncanonical dot component
    "C:/windows",  # drive
    "C:\\windows",  # drive + backslash
    "\\\\server\\share",  # UNC
    ".git/config",  # dotgit
    ".git",  # bare dotgit
    "sub/.GIT/x",  # casefold dotgit
    "sub/.Git/x",  # casefold dotgit
    "x/git~1/y",  # windows 8.3 shortname of .git
    "a/.git./b",  # trailing dot
    "a/.git /b",  # trailing space
]


@pytest.mark.parametrize("raw", HOSTILE_RELPATHS)
def test_saferelpath_rejects_hostile_input(raw: str) -> None:
    with pytest.raises(UnsafePathError):
        from template_press.rebrand.safety import SafeRelPath

        SafeRelPath(raw)


def test_saferelpath_accepts_clean_relative_path() -> None:
    from template_press.rebrand.safety import SafeRelPath

    sp = SafeRelPath("src/demo_widget/cli.py")
    assert sp.as_posix() == "src/demo_widget/cli.py"


def test_saferelpath_accepts_bare_git_dir_without_dot() -> None:
    # A directory literally named "git" (no leading dot) is ordinary content.
    from template_press.rebrand.safety import SafeRelPath

    assert SafeRelPath("docs/git/usage.md").as_posix() == "docs/git/usage.md"


def test_saferelpath_normalizes_windows_separators() -> None:
    # The tool's own Path constants render with "\" on Windows; a Windows-style
    # relative path is accepted and normalized to posix (the cross-platform fix).
    from template_press.rebrand.safety import SafeRelPath

    assert SafeRelPath("press\\x").as_posix() == "press/x"
    assert (
        SafeRelPath("press\\press-receipt.toml").as_posix()
        == "press/press-receipt.toml"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "\\\\server\\share",  # UNC -> //server/share -> absolute
        "C:\\x",  # drive -> C:/x -> colon
        "..\\x",  # dotdot -> ../x
        "a\\.git\\b",  # dotgit -> a/.git/b
    ],
)
def test_saferelpath_backslash_escapes_still_rejected(raw: str) -> None:
    # Normalizing "\" -> "/" opens NO hole: every backslash-encoded escape
    # still fails the same downstream check on the normalized form.
    from template_press.rebrand.safety import SafeRelPath

    with pytest.raises(UnsafePathError):
        SafeRelPath(raw)


# ---------------------------------------------------------------------------
# G3 — Containment at every I/O sink (no-follow)
# ---------------------------------------------------------------------------
def test_safe_write_writes_under_root_creating_parents(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    p = safe_write(root, "a/b/c.txt", "hello")
    assert p == root / "a" / "b" / "c.txt"
    assert p.read_text(encoding="utf-8") == "hello"


@requires_symlink
def test_safe_write_refuses_symlinked_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # root/link -> ../outside : a symlinked ancestor escaping the root.
    os.symlink(outside, root / "link", target_is_directory=True)
    with pytest.raises(ContainmentError):
        safe_write(root, "link/victim.txt", "escaped")
    assert not (outside / "victim.txt").exists()


@requires_symlink
def test_assert_under_root_rejects_symlink_ancestor_within_root(tmp_path: Path) -> None:
    # Symlink that stays *inside* the root still counts as a symlink component:
    # the lstat-walk must reject it even though parent.resolve() is contained.
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    os.symlink(root / "real", root / "link", target_is_directory=True)
    with pytest.raises(ContainmentError):
        assert_under_root(root / "link" / "f.txt", root)


def test_safe_mkdir_refuses_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        safe_mkdir(root, "../escape")


def test_safe_rename_moves_within_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "f").write_text("x", encoding="utf-8")
    safe_rename(root, "src", "dst")
    assert (root / "dst" / "f").read_text(encoding="utf-8") == "x"
    assert not (root / "src").exists()


@requires_symlink
def test_safe_rename_refuses_symlinked_destination_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "link", target_is_directory=True)
    (root / "real").mkdir()
    with pytest.raises(ContainmentError):
        safe_rename(root, "real", "link/moved")
    assert not (outside / "moved").exists()


# ---------------------------------------------------------------------------
# G3 / G3+ — hardlink safety: atomic new-inode + st_nlink>1 refusal
# ---------------------------------------------------------------------------
def test_write_control_writes_new_inode_leaving_hardlink_victim(tmp_path: Path) -> None:
    root = tmp_path / "target"
    control = root / "press" / "press-source.toml"
    control.parent.mkdir(parents=True)
    control.write_text("OLD", encoding="utf-8")
    victim = tmp_path / "outside" / "victim"
    victim.parent.mkdir(parents=True)
    os.link(control, victim)  # second hardlink to the SAME inode
    assert os.stat(control).st_ino == os.stat(victim).st_ino

    write_control(root, "press/press-source.toml", "NEW")

    assert control.read_text(encoding="utf-8") == "NEW"
    # The outside victim keeps the OLD inode + OLD content: never modified in
    # place. write_control produced a brand new inode.
    assert victim.read_text(encoding="utf-8") == "OLD"
    assert os.stat(control).st_ino != os.stat(victim).st_ino


def test_safe_write_refuses_hardlinked_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    sink = root / "tracked.txt"
    sink.write_text("OLD", encoding="utf-8")
    victim = tmp_path / "outside" / "victim"
    victim.parent.mkdir(parents=True)
    os.link(sink, victim)
    with pytest.raises(HardlinkError):
        safe_write(root, "tracked.txt", "NEW")
    assert victim.read_text(encoding="utf-8") == "OLD"
    assert sink.read_text(encoding="utf-8") == "OLD"


# ---------------------------------------------------------------------------
# G5 / G5+ — subprocess env scrub + on-target git hardening
# ---------------------------------------------------------------------------
def test_scrubbed_git_env_neutralizes_poisoned_global_config(
    tmp_path: Path, src_target: Path
) -> None:
    poison = tmp_path / "outside" / "gitconfig"
    poison.parent.mkdir(parents=True)
    poison.write_text("[core]\n\tfsmonitor = /evil/hook\n", encoding="utf-8")
    base = dict(os.environ)
    base["GIT_CONFIG_GLOBAL"] = str(poison)

    poisoned = _git(
        "-C",
        str(src_target),
        "config",
        "--get",
        "core.fsmonitor",
        env=base,
        capture_output=True,
        text=True,
    )
    assert poisoned.stdout.strip() == "/evil/hook"  # hole exists without scrub

    scrubbed = _git(
        "-C",
        str(src_target),
        "config",
        "--get",
        "core.fsmonitor",
        env=scrubbed_git_env(base),
        capture_output=True,
        text=True,
    )
    assert scrubbed.stdout.strip() == ""  # scrub silences the poisoned global


def test_scrubbed_git_env_clears_git_dir(tmp_path: Path, src_target: Path) -> None:
    base = dict(os.environ)
    base["GIT_DIR"] = str(tmp_path / "outside" / "bogus.git")
    env = scrubbed_git_env(base)
    assert "GIT_DIR" not in env
    resolved = _git(
        "-C",
        str(src_target),
        "rev-parse",
        "--absolute-git-dir",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(resolved.stdout.strip()).resolve() == (src_target / ".git").resolve()


def test_git_hardening_args_override_on_target_hookspath(src_target: Path) -> None:
    _git(
        "-C",
        str(src_target),
        "config",
        "core.hooksPath",
        "/evil/hooks",
        check=True,
        capture_output=True,
    )
    poisoned = _git(
        "-C",
        str(src_target),
        "rev-parse",
        "--git-path",
        "hooks",
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    assert "/evil/hooks" in poisoned.stdout  # target's own config is honored...

    args = git_hardening_args()
    hardened = _git(
        "-C",
        str(src_target),
        *args,
        "rev-parse",
        "--git-path",
        "hooks",
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    assert "/evil/hooks" not in hardened.stdout  # ...but hardening overrides it
    joined = " ".join(args)
    assert "core.fsmonitor=" in joined
    assert "core.hooksPath=" in joined
    assert "protocol.ext.allow=never" in joined


def test_hooks_do_not_execute_under_hardening(tmp_path: Path, src_target: Path) -> None:
    sentinel = tmp_path / "outside" / "pwned"
    sentinel.parent.mkdir(parents=True)
    hook = tmp_path / "outside" / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    _git(
        "-C",
        str(src_target),
        "config",
        "core.fsmonitor",
        str(hook),
        check=True,
        capture_output=True,
    )
    # Phase 1: prove the hole fires WITHOUT hardening (else the guard test is
    # a false green on this git build).
    _git(
        "-C",
        str(src_target),
        "status",
        "--porcelain",
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    if not sentinel.exists():
        pytest.skip("fsmonitor hook not exercised by this git build")
    sentinel.unlink()
    # Phase 2: hardening (-c core.fsmonitor=) must stop the execution.
    _git(
        "-C",
        str(src_target),
        *git_hardening_args(),
        "status",
        "--porcelain",
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    assert not sentinel.exists()


def test_scrubbed_uv_env_drops_uv_working_dir(tmp_path: Path) -> None:
    base = dict(os.environ)
    base["UV_WORKING_DIR"] = str(tmp_path / "outside" / "elsewhere")
    base["UV_CACHE_DIR"] = str(tmp_path / "outside" / "cache")
    env = scrubbed_uv_env(base)
    assert "UV_WORKING_DIR" not in env
    assert "UV_CACHE_DIR" not in env


# ---------------------------------------------------------------------------
# G6 — owned sandbox
# ---------------------------------------------------------------------------
def test_owned_sandbox_creates_0700_child_and_cleans_only_that(tmp_path: Path) -> None:
    keep = tmp_path / "outside" / "keep"
    keep.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")
    saved: Path | None = None
    with owned_sandbox() as sb:
        saved = sb
        assert sb.is_dir()
        assert sb.name.startswith("press-verify-")
        if sys.platform != "win32":
            # POSIX permission bits; os.chmod's mode is a near-no-op on Windows
            # (16895 & 511 != 448), so assert 0700 only where it is meaningful.
            assert (sb.stat().st_mode & 0o777) == 0o700
        assert sb.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        (sb / "scratch").write_text("x", encoding="utf-8")
    assert saved is not None and not saved.exists()  # owned child removed
    assert keep.read_text(encoding="utf-8") == "keep"  # nothing else touched


def test_on_rmtree_error_clears_readonly_bit_and_retries(tmp_path: Path) -> None:
    # Direct unit test of the onexc handler: a read-only file (as git marks its
    # loose objects) whose failing op is retried after the write bit is cleared.
    from template_press.rebrand.safety import _on_rmtree_error

    obj = tmp_path / "loose_object"
    obj.write_text("x", encoding="utf-8")
    os.chmod(obj, 0o444)  # read-only, exactly like a .git/objects/** entry
    _on_rmtree_error(os.unlink, os.fspath(obj), PermissionError())
    assert not obj.exists()  # handler chmodded +w and re-ran os.unlink


def test_owned_sandbox_teardown_removes_readonly_git_object(tmp_path: Path) -> None:
    # Production teardown path: a git loose object is read-only; on Windows
    # shutil.rmtree cannot unlink a read-only file (WinError 5), so the sandbox
    # cleanup raised and verify_command mapped it to exit 2. The wired onexc
    # handler must let the owned teardown remove the whole tree with no error.
    saved: Path | None = None
    with owned_sandbox() as sb:
        saved = sb
        objs = sb / "self" / ".git" / "objects" / "05"
        objs.mkdir(parents=True)
        obj = objs / "cafebabe"
        obj.write_text("loose object", encoding="utf-8")
        os.chmod(obj, 0o444)
    assert saved is not None and not saved.exists()


def test_owned_rmtree_recovers_readonly_file_that_blocks_plain_rmtree(
    monkeypatch,
) -> None:
    # Portable emulation of the Windows read-only-file case: make os.unlink
    # refuse a file whose write bit is clear (as WinError 5 does). Plain
    # shutil.rmtree then RAISES; _owned_rmtree (onexc-wired) must recover.
    from template_press.rebrand.safety import _owned_rmtree

    real_unlink = os.unlink

    def readonly_refusing_unlink(target, *args, dir_fd=None, **kwargs):
        if not (os.lstat(target, dir_fd=dir_fd).st_mode & stat.S_IWRITE):
            raise PermissionError(5, "Access is denied", os.fspath(target))
        return real_unlink(target, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "unlink", readonly_refusing_unlink)

    def _make_owned_tree() -> Path:
        root = Path(tempfile.mkdtemp(prefix="press-verify-"))
        objs = root / "self" / ".git" / "objects" / "05"
        objs.mkdir(parents=True)
        obj = objs / "deadbeef"
        obj.write_text("loose object", encoding="utf-8")
        os.chmod(obj, 0o444)
        return root

    # Without the handler, the emulated read-only unlink makes rmtree raise —
    # the exact Windows failure the fix exists to clear.
    baseline = _make_owned_tree()
    baseline_obj = baseline / "self" / ".git" / "objects" / "05" / "deadbeef"
    try:
        with pytest.raises(PermissionError):
            shutil.rmtree(baseline)
    finally:
        os.chmod(baseline_obj, 0o644)
        shutil.rmtree(baseline, ignore_errors=True)

    # With the handler wired in, the owned teardown removes the whole tree.
    owned = _make_owned_tree()
    _owned_rmtree(owned)
    assert not owned.exists()


def test_refuse_unsafe_root_rejects_dangerous_roots(tmp_path: Path) -> None:
    with pytest.raises(SafetyError):
        refuse_unsafe_root(Path(root_anchor()))
    with pytest.raises(SafetyError):
        refuse_unsafe_root(Path.home())
    with pytest.raises(SafetyError):
        refuse_unsafe_root(Path.cwd())
    with pytest.raises(SafetyError):
        refuse_unsafe_root(Path.cwd().parent)  # ancestor of cwd
    if _can_symlink(tmp_path):
        # symlinked-root branch only — creating the link is unportable
        # (Windows privilege); the other rejections above run everywhere.
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        os.symlink(real, link, target_is_directory=True)
        with pytest.raises(SafetyError):
            refuse_unsafe_root(link)  # symlinked root
    with pytest.raises(SafetyError):
        refuse_unsafe_root(tmp_path / "sb", target=tmp_path)  # not disjoint


def root_anchor() -> str:
    return os.path.abspath(os.sep)


# ---------------------------------------------------------------------------
# G7 / G8 — scanner input discipline
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo POSIX-only")
def test_is_regular_lstat_discipline(tmp_path: Path) -> None:
    reg = tmp_path / "f"
    reg.write_text("x", encoding="utf-8")
    assert is_regular_lstat(reg) is True

    d = tmp_path / "d"
    d.mkdir()
    assert is_regular_lstat(d) is False

    link = tmp_path / "l"
    os.symlink(reg, link)
    assert is_regular_lstat(link) is False  # never follow

    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert is_regular_lstat(fifo) is False  # unscannable, and lstat never hangs

    assert is_regular_lstat(tmp_path / "missing") is False


def test_gitlink_submodule_dir_is_not_a_regular_file(tmp_path: Path) -> None:
    sub = tmp_path / "target" / "vendored"
    sub.mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../.git/modules/vendored\n", encoding="utf-8")
    # A submodule/gitlink is a directory -> not a regular file, so the scanner
    # sees it by path name only and never recurses into a nested .git.
    assert is_regular_lstat(sub) is False


# ---------------------------------------------------------------------------
# G1 / G1+ — test isolation guard (autouse conftest)
# ---------------------------------------------------------------------------
def test_autouse_guard_chdir_to_tmp(tmp_path: Path) -> None:
    assert Path.cwd().resolve() == tmp_path.resolve()


def test_unpinned_git_op_fails_in_non_repo_not_checkout() -> None:
    # cwd is the per-test tmp dir (autouse chdir), which is not a repo; an
    # unpinned git op fails here instead of walking up to the real checkout.
    result = _git("status", "--porcelain", capture_output=True, text=True)
    assert result.returncode != 0


def test_interceptor_rejects_git_targeting_the_real_checkout() -> None:
    # A -C pointing at the real checkout (outside the per-test tmp sandbox) is
    # rejected by the autouse interceptor BEFORE git ever runs.
    with pytest.raises(RuntimeError):
        _git(
            "-C",
            str(REPO_ROOT),
            "status",
            "--porcelain",
            capture_output=True,
            text=True,
        )


# ---------------------------------------------------------------------------
# G9 — read-only verify: assert_target_unchanged helper
# ---------------------------------------------------------------------------
def test_assert_target_unchanged_detects_modification(
    src_target: Path, snapshot_target, assert_target_unchanged
) -> None:
    before = snapshot_target(src_target)
    assert_target_unchanged(src_target, before)  # unchanged -> passes silently
    (src_target / "README.md").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_target_unchanged(src_target, before)


def test_guarded_rmtree_refuses_outside_root(tmp_path: Path, guarded_rmtree) -> None:
    root = tmp_path / "root"
    inside = root / "sub"
    inside.mkdir(parents=True)
    guarded_rmtree(inside, root)  # contained -> allowed
    assert not inside.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SafetyError):
        guarded_rmtree(outside, root)  # outside root -> refuse
    assert outside.exists()
