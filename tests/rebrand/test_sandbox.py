"""List-driven, ARG_MAX-safe, submodule-aware sandbox (Task 11).

``make_sandbox`` builds a faithful, isolated git copy of the target that
``press verify`` presses. The overriding invariant under test: every git op
and file write lands inside the owned sandbox — NEVER the real target, cwd, or
$HOME (the 152-file-wipe class). The four plan cases (a-d) plus a
one-commit/synthetic-identity/target-untouched assertion are exercised here;
all fixtures and decoys live strictly under ``tmp_path`` and every git op is
routed through ``git -C <sandbox>`` so the autouse containment guard is
satisfied.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from template_press.rebrand.safety import ContainmentError
from template_press.rebrand.sandbox import Sandbox, make_sandbox

from .conftest import make_target, requires_symlink


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.stdout


def _rev_parse_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def _committed_paths(sandbox: Path) -> set[str]:
    out = _git(sandbox, "ls-tree", "-r", "--name-only", "HEAD")
    return {line for line in out.splitlines() if line}


def _dest_root(tmp_path: Path) -> Path:
    dest = tmp_path / "dest"
    dest.mkdir()
    return dest


# ---------------------------------------------------------------------------
# (a) an untracked-but-listed file AND a symlink land in the sandbox as-is
# ---------------------------------------------------------------------------
@requires_symlink
def test_untracked_file_and_symlink_land_as_is(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    # Untracked (never `git add`ed) but non-ignored — copy_paths lists it via
    # `ls-files --others --exclude-standard`.
    (target / "notes_untracked.txt").write_text("hello demo_widget\n", encoding="utf-8")
    # A tracked symlink whose readlink target must survive verbatim.
    (target / "link_to_readme").symlink_to("README.md")
    _git(target, "add", "link_to_readme")
    _git(target, "commit", "-q", "-m", "add symlink")

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    untracked = result.path / "notes_untracked.txt"
    assert untracked.is_file()
    assert untracked.read_text(encoding="utf-8") == "hello demo_widget\n"

    link = result.path / "link_to_readme"
    assert link.is_symlink()
    assert os.readlink(link) == "README.md"

    committed = _committed_paths(result.path)
    assert "notes_untracked.txt" in committed
    assert "link_to_readme" in committed


# ---------------------------------------------------------------------------
# (b) a `git add -f` gitignored file is present in the sandbox commit
# ---------------------------------------------------------------------------
def test_force_added_gitignored_file_in_commit(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    with (target / ".gitignore").open("a", encoding="utf-8") as f:
        f.write("secret.env\n")
    (target / "secret.env").write_text("TOKEN=shh\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "add", "-f", "secret.env")
    _git(target, "commit", "-q", "-m", "force-add ignored secret")

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    assert (result.path / "secret.env").is_file()
    # The sandbox copies .gitignore too (which ignores secret.env); only a
    # forced add (`-f`) lands it in the sandbox commit.
    assert "secret.env" in _committed_paths(result.path)


# ---------------------------------------------------------------------------
# (c) a gitlink path is scannable-by-name AND recorded unavailable
# ---------------------------------------------------------------------------
def _add_gitlink(target: Path, tmp_path: Path, rel: str = "sub") -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q", "-b", "main")
    _git(inner, "config", "user.email", "test@example.com")
    _git(inner, "config", "user.name", "Test")
    (inner / "f.txt").write_text("x\n", encoding="utf-8")
    _git(inner, "add", "-A")
    _git(inner, "commit", "-q", "-m", "inner init")
    sha = _rev_parse_head(inner)
    _git(target, "update-index", "--add", "--cacheinfo", f"160000,{sha},{rel}")
    _git(target, "commit", "-q", "-m", "add gitlink")


def test_gitlink_scannable_and_recorded_unavailable(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    _add_gitlink(target, tmp_path)

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    # The gitlink NAME is scannable: the path components exist as a real dir
    # holding a tracked placeholder (submodule content is unavailable).
    placeholder = result.path / "sub" / ".press-submodule-unavailable"
    assert placeholder.is_file()
    assert "sub/.press-submodule-unavailable" in _committed_paths(result.path)
    assert "sub" in result.unavailable_submodules


# ---------------------------------------------------------------------------
# (d) a control-path symlink is rejected and NOTHING is written outside
# ---------------------------------------------------------------------------
@requires_symlink
def test_control_path_symlink_rejected_writes_nothing(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    # A symlinked control dir could redirect a control-file write out of the
    # tree — assert_control_real (Task 3) rejects it BEFORE any copy.
    (target / "press").symlink_to(outside)

    dest_root = _dest_root(tmp_path)
    with pytest.raises(ContainmentError):
        make_sandbox(target, dest_root)

    # Nothing was written into the external decoy, and the sandbox dir was
    # never even created (rejection precedes any write).
    assert list(outside.iterdir()) == []
    assert not (dest_root / "self").exists()


# ---------------------------------------------------------------------------
# exactly one commit, synthetic identity, real target untouched
# ---------------------------------------------------------------------------
def test_commit_synthetic_identity_and_target_untouched(
    tmp_path: Path,
    snapshot_target: Callable[[Path], tuple[str, str]],
    assert_target_unchanged: Callable[[Path, tuple[str, str]], None],
) -> None:
    target = make_target(tmp_path)
    before = snapshot_target(target)

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    assert isinstance(result, Sandbox)
    log = _git(result.path, "log", "--format=%an%x00%ae%x00%cn%x00%ce").splitlines()
    assert len(log) == 1
    author_name, author_email, committer_name, committer_email = log[0].split("\0")
    assert author_name == "press-verify"
    assert author_email == "verify@localhost"
    assert committer_name == "press-verify"
    assert committer_email == "verify@localhost"

    # The real target was only ever read (copy_paths + byte reads); no git op
    # or write touched it.
    assert_target_unchanged(target, before)
