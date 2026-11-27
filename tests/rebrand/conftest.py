"""Fixture targets: minimal-but-real repos the press is aimed at in tests.

app_name deliberately = "press" so English-word traps (compress, express,
pressure) exercise boundary safety — the empirically proven danger case.
DEST mirrors the potato identity used by the EMPIRICAL_BUGS.md live matrix.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from template_press.rebrand.identity import Identity


def _can_symlink(base: Path | None = None) -> bool:
    """Whether ``os.symlink`` actually works here.

    Probes by creating (and removing) a symlink under ``base`` (a throwaway
    temp dir when omitted); returns False when the OS refuses. Windows CI
    runners lack the create-symbolic-link privilege, so ``os.symlink`` raises
    ``OSError`` there. A runtime probe (not a blanket ``os.name == "nt"``
    check) so symlink tests still run on a Windows host that DOES grant the
    privilege, and always on POSIX. Only the test's link CREATION is
    unportable — the production symlink-safety code is unchanged.
    """
    made_tmp = base is None
    probe_dir = Path(tempfile.mkdtemp()) if made_tmp else base
    probe = probe_dir / ".symlink-probe"
    try:
        os.symlink("symlink-probe-target", probe)
    except (OSError, NotImplementedError):
        ok = False
    else:
        ok = True
        try:
            probe.unlink()
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
    if made_tmp:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return ok


# Applied to tests that must CREATE a symlink to exercise a guard; skips them
# where the runner cannot make one (Windows without privilege) while keeping
# them live on POSIX and privileged Windows.
requires_symlink = pytest.mark.skipif(
    not _can_symlink(),
    reason="symlink creation requires privilege (skipped on Windows CI)",
)

# Applied to tests whose MECHANISM is POSIX-only — sh scripts as declared
# executables, exec bits, permission-mode assertions, or filenames illegal
# on Win32 (colons, control characters, non-UTF-8 bytes). The engine
# behavior they exercise stays correct on Windows (an unresolvable tool is
# reported missing); only the fixture apparatus cannot exist there.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only test mechanism (sh scripts / permission bits / "
    "filenames illegal on Win32)",
)

SOURCE = Identity(
    package_name="demo_widget",
    repo_name="demo-widget",
    app_name="press",
    author="Demo Author",
    email="demo@example.com",
    owner="demolabs",
)

DEST = Identity(
    package_name="potato_launcher",
    repo_name="potato-launcher",
    app_name="potato",
    author="Potato Farmer",
    email="potato@example.com",
    owner="potatolabs",
)

PYPROJECT = """\
[project]
name = "demo_widget"
version = "0.1.0"
description = "Demo widget by Demo Author"
authors = [{ name = "Demo Author", email = "demo@example.com" }]
requires-python = ">=3.12"

[project.scripts]
press = "demo_widget.cli:main"
"""

README = """\
# demo-widget

Compress the archive before express delivery; do not let the pressure rise.
Run `press --help`. Repo: https://github.com/demolabs/demo-widget
Maintained by Demo Author <demo@example.com>.
"""

CLI_PY = '''\
"""demo_widget CLI (env prefix PRESS_*)."""

import os


def main() -> int:
    level = os.environ.get("PRESS_LOG_LEVEL", "info")
    complete = os.environ.get("_PRESS_COMPLETE")
    print(f"demo_widget cli level={level} complete={complete}")
    return 0
'''


def _git(repo: Path, *args: str) -> None:
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


_TARGET_TEMPLATE_ROOT: Path | None = None
_TARGET_TEMPLATES: dict[str, Path] = {}
_EMPTY_GIT_TEMPLATE: Path | None = None
_SEEDED_TEMPLATES: dict[
    tuple[str | None, str, str | None, tuple[str, ...]],
    tuple[Path, dict[str, str]],
] = {}


def _template_root() -> Path:
    global _TARGET_TEMPLATE_ROOT
    if _TARGET_TEMPLATE_ROOT is None:
        _TARGET_TEMPLATE_ROOT = Path(tempfile.mkdtemp(prefix="press-target-templates-"))
        atexit.register(shutil.rmtree, _TARGET_TEMPLATE_ROOT, ignore_errors=True)
    return _TARGET_TEMPLATE_ROOT


def init_git_repo(
    repo: Path,
    *,
    origin: str | None = None,
    commit_message: str | None = "seed",
    allow_empty: bool = False,
) -> None:
    """Initialize ``repo`` from the per-worker empty ``.git`` template.

    Replaces up to four git subprocesses (``init``, ``config`` x2, ``remote add``)
    with a local ``.git`` copy and optional origin stanza append. The first call
    per worker runs ``git init`` inside ``repo`` (under ``tmp_path``) and caches
    a pristine copy of its ``.git`` directory for later tests on that worker.
    """
    global _EMPTY_GIT_TEMPLATE
    git_dir = repo / ".git"
    if _EMPTY_GIT_TEMPLATE is None:
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "maintenance.auto", "false")
        template = _template_root() / "_empty_git"
        shutil.copytree(git_dir, template, symlinks=True)
        _EMPTY_GIT_TEMPLATE = template
    else:
        shutil.copytree(_EMPTY_GIT_TEMPLATE, git_dir, symlinks=True)
    if origin is not None:
        with (git_dir / "config").open("a", encoding="utf-8") as fh:
            fh.write(
                f'\n[remote "origin"]\n'
                f"\turl = {origin}\n"
                f"\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
            )
    if commit_message is not None:
        _git(repo, "add", "-A")
        args = ["commit", "-q", "-m", commit_message]
        if allow_empty:
            args.append("--allow-empty")
        _git(repo, *args)


def _store_target_template(repo: Path, layout: str) -> None:
    """Keep one pristine repo per layout for this pytest process."""
    template = _template_root() / layout
    shutil.copytree(repo, template, symlinks=True)
    _TARGET_TEMPLATES[layout] = template


def copy_cached_repo(
    repo: Path,
    cache_key: str,
    populate: Callable[[Path], None],
) -> Path:
    """Copy a per-worker cached committed repo, building it in ``repo`` on miss.

    ``populate(repo)`` must create and commit ``repo`` inside the caller's
    ``tmp_path`` sandbox (satisfying ``UncontainedGitError``). Later calls with
    the same ``cache_key`` copy the cached repo and refresh its index.
    """
    template = _TARGET_TEMPLATES.get(cache_key)
    if template is not None:
        shutil.copytree(template, repo, symlinks=True, dirs_exist_ok=True)
        _git(repo, "update-index", "-q", "--refresh")
        return repo
    populate(repo)
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    template = _template_root() / f"repo-{digest}-{len(_TARGET_TEMPLATES)}"
    shutil.copytree(repo, template, symlinks=True)
    _TARGET_TEMPLATES[cache_key] = template
    return repo


def seed_cached_git_repo(
    repo: Path,
    files: Mapping[str, str],
    *,
    origin: str | None = None,
    commit_message: str = "seed",
    newline: str | None = None,
) -> Path:
    """Populate and commit ``repo`` using a per-worker pre-committed template.

    Caches one committed repo per ``(origin, commit_message, newline, paths)``
    shape per pytest worker. Exact repeats copy the cached repo and refresh its
    index (1 git spawn); same-shape variants overwrite only modified tracked
    files and run ``git commit -q -a --amend --no-edit`` (1 git spawn) instead
    of ``git add`` + ``git commit``.
    """
    file_map = dict(files)
    shape_key = (origin, commit_message, newline, tuple(sorted(file_map)))
    cached = _SEEDED_TEMPLATES.get(shape_key)
    if cached is not None:
        template, template_files = cached
        shutil.copytree(template, repo, symlinks=True, dirs_exist_ok=True)
        changed = [
            rel for rel, content in file_map.items() if template_files[rel] != content
        ]
        if changed:
            for rel in changed:
                (repo / rel).write_text(
                    file_map[rel], encoding="utf-8", newline=newline
                )
            _git(repo, "commit", "-q", "-a", "--amend", "--no-edit")
        else:
            _git(repo, "update-index", "-q", "--refresh")
        return repo

    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in file_map.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline=newline)
    init_git_repo(repo, origin=origin, commit_message=commit_message)
    digest = hashlib.sha256(repr(shape_key).encode("utf-8")).hexdigest()[:16]
    template = _template_root() / f"seeded-{digest}-{len(_SEEDED_TEMPLATES)}"
    shutil.copytree(repo, template, symlinks=True)
    _SEEDED_TEMPLATES[shape_key] = (template, file_map)
    return repo


def make_target(base: Path, layout: str = "src") -> Path:
    """Build a committed mini target repo. layout: 'src' or 'flat'."""
    repo = base / "target"
    template = _TARGET_TEMPLATES.get(layout)
    if template is not None:
        shutil.copytree(template, repo, symlinks=True, dirs_exist_ok=True)
        # A copy has new inodes and ctimes, so refresh the index stat data.
        _git(repo, "update-index", "-q", "--refresh")
        return repo
    pkg_root = repo / "src" if layout == "src" else repo
    pkg = pkg_root / "demo_widget"
    pkg.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "README.md").write_text(README, encoding="utf-8")
    (repo / "press_config.toml").write_text(
        '# press config for demo_widget\ntheme = "dark"\n', encoding="utf-8"
    )
    (pkg / "__init__.py").write_text('"""demo_widget package."""\n', encoding="utf-8")
    (pkg / "cli.py").write_text(CLI_PY, encoding="utf-8")
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Background maintenance can change .git while the template is copied.
    _git(repo, "config", "maintenance.auto", "false")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/demolabs/demo-widget.git",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init fixture")
    _store_target_template(repo, layout)
    return repo


@pytest.fixture
def src_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="src")


@pytest.fixture
def flat_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="flat")


def write_answers_file(base: Path, identity: Identity) -> Path:
    p = base / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(f'{k} = "{v}"' for k, v in identity.as_dict_prompted().items())
        + "\n",
        encoding="utf-8",
    )
    return p
