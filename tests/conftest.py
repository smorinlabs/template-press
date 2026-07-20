"""Top-level test isolation guard (Task 0.5, guards G1 / G1+).

This autouse fixture closes the "152-file-wipe" class of test-harness escape:
a mis-directed git op or raw filesystem write hitting the real checkout
instead of a throwaway sandbox. For EVERY test it:

* ``chdir`` into the per-test ``tmp_path`` so an unpinned git op runs in a
  non-repo instead of walking up to the checkout;
* sets ``GIT_CEILING_DIRECTORIES`` to the checkout's parent and neutralizes
  global/system git config so test git is hermetic;
* installs a ``subprocess.run`` / ``subprocess.Popen`` interceptor that
  REJECTS any git call whose ``-C`` / ``cwd=`` points outside the per-test
  ``tmp_path`` (or an owned ``press-verify-*`` sandbox) — enforced, not
  advisory.

It also exposes the guarded test helpers ``guarded_rmtree`` (containment before
``shutil.rmtree``), ``snapshot_target`` and ``assert_target_unchanged`` (G9:
prove a target is byte-identical before/after a read-only op).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from template_press.rebrand.safety import (
    SafetyError,
    git_hardening_args,
    is_regular_lstat,
    scrubbed_git_env,
)

_ORIG_RUN = subprocess.run
_ORIG_POPEN = subprocess.Popen

CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_PARENT = CHECKOUT_ROOT.parent

# Set per-test by the autouse fixture; the interceptor reads it to decide
# whether a git ``-C`` / ``cwd`` is contained. Tests run sequentially, so a
# module global is safe (xdist workers each have their own process).
_ALLOWED_TMP: Path | None = None


class UncontainedGitError(RuntimeError):
    """A git subprocess targets a path outside the per-test tmp sandbox."""


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _under_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover - defensive
        return False
    if _ALLOWED_TMP is not None and _is_within(resolved, _ALLOWED_TMP):
        return True
    tmp_root = Path(tempfile.gettempdir()).resolve()
    return _is_within(resolved, tmp_root) and any(
        part.startswith("press-verify-") for part in resolved.parts
    )


def _command(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    return kwargs.get("args")


def _is_git_command(cmd: Any) -> bool:
    if isinstance(cmd, (str, bytes)):
        text = cmd.decode() if isinstance(cmd, bytes) else cmd
        tokens = text.split()
        exe = tokens[0] if tokens else ""
    elif isinstance(cmd, Sequence):
        if not cmd:
            return False
        exe = os.fspath(cmd[0])
    else:  # pragma: no cover - defensive
        return False
    return os.path.basename(exe) == "git"


def _git_dash_c_path(cmd: Any) -> str | None:
    if not isinstance(cmd, Sequence) or isinstance(cmd, (str, bytes)):
        return None
    tokens = [os.fspath(t) for t in cmd]
    for i, token in enumerate(tokens[:-1]):
        if token == "-C":
            return tokens[i + 1]
    return None


def _guard_git(cmd: Any, cwd: Any) -> None:
    if not _is_git_command(cmd):
        return
    pin = _git_dash_c_path(cmd)
    if pin is None and cwd is not None:
        pin = os.fspath(cwd)
    if pin is None:
        # Unpinned: relies on the process cwd, which the autouse chdir has
        # pointed at a non-repo tmp dir. Let it run and fail there instead of
        # escaping to the checkout.
        return
    if not _under_allowed(Path(pin)):
        raise UncontainedGitError(
            f"git op targets {pin!r} outside the per-test tmp sandbox "
            f"(pin it with -C/cwd under tmp_path)"
        )


def _guarded_run(*args: Any, **kwargs: Any) -> Any:
    _guard_git(_command(args, kwargs), kwargs.get("cwd"))
    return _ORIG_RUN(*args, **kwargs)


def _guarded_popen(*args: Any, **kwargs: Any) -> Any:
    _guard_git(_command(args, kwargs), kwargs.get("cwd"))
    return _ORIG_POPEN(*args, **kwargs)


@pytest.fixture(autouse=True)
def _press_test_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    global _ALLOWED_TMP
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(CHECKOUT_PARENT))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(subprocess, "run", _guarded_run)
    monkeypatch.setattr(subprocess, "Popen", _guarded_popen)
    _ALLOWED_TMP = tmp_path.resolve()
    try:
        yield
    finally:
        _ALLOWED_TMP = None


# ---------------------------------------------------------------------------
# Guarded test helpers
# ---------------------------------------------------------------------------
def _guarded_rmtree(path: Path, root: Path) -> None:
    if not _is_within(path.resolve(), root.resolve()):
        raise SafetyError(f"refusing to rmtree {path} outside {root}")
    shutil.rmtree(path)


@pytest.fixture
def guarded_rmtree() -> Callable[[Path, Path], None]:
    """Return a ``shutil.rmtree`` that first asserts ``path`` is under ``root``."""
    return _guarded_rmtree


def _run_git_ro(repo: Path, *args: str) -> str:
    # git is hardcoded and the repo path is a test-owned tmp target, not
    # untrusted input; the call is hardened + env-scrubbed (G5/G5+).
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *git_hardening_args(), *args],  # noqa: S607
        check=True,
        capture_output=True,
        encoding="utf-8",
        env=scrubbed_git_env(),
    )
    return result.stdout


def _hash_tree(repo: Path) -> str:
    root = repo.resolve()
    entries: list[tuple[str, str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if os.path.islink(path):
                entries.append((rel, "L", os.readlink(path)))
            elif is_regular_lstat(path):
                entries.append(
                    (rel, "F", hashlib.sha256(path.read_bytes()).hexdigest())
                )
            else:
                entries.append((rel, "?", ""))
    digest = hashlib.sha256()
    for rel, kind, value in sorted(entries):
        digest.update(f"{rel}\0{kind}\0{value}\0".encode())
    return digest.hexdigest()


def _snapshot_target(repo: Path) -> tuple[str, str]:
    """A read-only ``(git-status, content-hash)`` snapshot of a target (G9)."""
    return (_run_git_ro(repo, "status", "--porcelain", "-uall"), _hash_tree(repo))


def _assert_target_unchanged(repo: Path, before: tuple[str, str]) -> None:
    after = _snapshot_target(repo)
    assert after == before, (
        f"target {repo} changed during a read-only op:\nbefore={before}\nafter ={after}"
    )


@pytest.fixture
def snapshot_target() -> Callable[[Path], tuple[str, str]]:
    return _snapshot_target


@pytest.fixture
def assert_target_unchanged() -> Callable[[Path, tuple[str, str]], None]:
    return _assert_target_unchanged
