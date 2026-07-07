"""Fixture targets: minimal-but-real repos the press is aimed at in tests.

app_name deliberately = "press" so English-word traps (compress, express,
pressure) exercise boundary safety — the empirically proven danger case.
DEST mirrors the potato identity used by the EMPIRICAL_BUGS.md live matrix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.identity import Identity

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
    subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def make_target(base: Path, layout: str = "src") -> Path:
    """Build a committed mini target repo. layout: 'src' or 'flat'."""
    repo = base / "target"
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
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/demolabs/demo-widget.git",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init fixture")
    return repo


@pytest.fixture
def src_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="src")


@pytest.fixture
def flat_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="flat")
