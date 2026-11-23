"""Live end-to-end proof that npm, Bun, and pnpm targets press clean.

Each fixture is a small Node-only repository (no ``pyproject.toml``) with a
scoped ``npm_name``, a hyphenated ``cli_name`` backing ``bin/<cli>.js``, one
pinned ``typescript`` dev dependency, and a declared lockfile regeneration.
Package-manager subprocesses run inside ``tmp_path`` with their caches there
too; none of them touches this repository's root.

Run explicitly: uv run pytest tests/rebrand/test_node_targets.py -m live
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Literal

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import regenerate_suggestion
from template_press.rebrand.verify_cli import verify_command

from .conftest import _git, posix_only, write_answers_file

Manager = Literal["npm", "bun", "pnpm"]

TYPESCRIPT_VERSION = "5.6.3"

SOURCE = Identity(
    package_name="zeta_ledger",
    repo_name="zeta-ledger",
    app_name="zetaapp",
    author="Zeta Author",
    email="zeta@example.test",
    owner="zetalabs",
    npm_name="@zeta-org/ledger-kit",
    cli_name="ledger-cli",
)
DEST = Identity(
    package_name="omega_vault",
    repo_name="omega-vault",
    app_name="omegaapp",
    author="Omega Author",
    email="omega@example.test",
    owner="omegalabs",
    npm_name="@omega-org/vault-kit",
    cli_name="vault-cli",
)
OLD_TOKENS = (
    "zeta_ledger",
    "zeta-ledger",
    "zetaapp",
    "zetalabs",
    "zeta-org",
    "ledger-kit",
    "ledger-cli",
)

LOCKFILE = {"npm": "package-lock.json", "bun": "bun.lock", "pnpm": "pnpm-lock.yaml"}


# The Bun command is the exact block `press` suggests (rules.py), so the
# printed suggestion is what is proven end to end.
def _suggested_command(file: str) -> list[str]:
    suggestion = regenerate_suggestion(file)
    assert suggestion is not None
    return list(tomllib.loads(suggestion)["regenerate"][0]["command"])


LOCK_COMMAND = {
    "npm": ["npm", "install", "--package-lock-only", "--silent"],
    "bun": _suggested_command("bun.lock"),
    "pnpm": ["pnpm", "install", "--lockfile-only"],
}
FROZEN_COMMAND = {
    "npm": ["npm", "ci", "--no-audit", "--no-fund"],
    "bun": ["bun", "install", "--frozen-lockfile"],
    "pnpm": ["pnpm", "install", "--frozen-lockfile"],
}
RUN_COMMAND = {
    "npm": ["npm", "run", "--silent"],
    "bun": ["bun", "run"],
    "pnpm": ["pnpm", "run", "--silent"],
}
# Cache locations are redirected under tmp_path through these variables. The
# regeneration step runs under a deny-by-default environment, so each name is
# also declared in the rule's ``env`` list to reach the package manager.
CACHE_VARS = {
    "npm": "npm_config_cache",
    "bun": "BUN_INSTALL_CACHE_DIR",
    "pnpm": "npm_config_store_dir",
}


def _manager_env(manager: Manager, base: Path) -> dict[str, str]:
    cache = base / f"{manager}-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return {**os.environ, CACHE_VARS[manager]: str(cache)}


def _run(
    argv: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _require(manager: Manager) -> None:
    """Skip when the manager is absent, except npm and bun under CI."""
    if shutil.which(manager) is not None:
        return
    if manager != "pnpm" and os.environ.get("CI"):
        pytest.fail(f"{manager} is required in CI but is not on PATH")
    pytest.skip(f"{manager} is not installed")


def make_node_target(base: Path, manager: Manager) -> Path:
    """Build a committed Node-only target pressed by ``manager``."""
    target = base / SOURCE.repo_name
    for rel in ("press", "bin", "src", "test"):
        (target / rel).mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        "[identity]\n"
        + "".join(f'{k} = "{v}"\n' for k, v in SOURCE.as_dict_prompted().items()),
        encoding="utf-8",
    )
    excludes = (
        '[rules]\nextra_exclude_files = ["pnpm-lock.yaml"]\n\n'
        if manager == "pnpm"
        else ""
    )
    command = ", ".join(json.dumps(part) for part in LOCK_COMMAND[manager])
    (target / "press" / "press-rules.toml").write_text(
        f"{excludes}[[regenerate]]\n"
        f'file = "{LOCKFILE[manager]}"\n'
        f"command = [{command}]\n"
        f'env = ["{CACHE_VARS[manager]}"]\n'
        'scan = "boundary"\n',
        encoding="utf-8",
    )
    manifest = {
        "name": SOURCE.npm_name,
        "version": "0.1.0",
        "description": f"{SOURCE.app_name} by {SOURCE.owner}",
        "bin": {SOURCE.cli_name: f"./bin/{SOURCE.cli_name}.js"},
        "scripts": {
            "test": "node --test test/",
            "typecheck": "tsc --noEmit -p .",
        },
        "devDependencies": {"typescript": TYPESCRIPT_VERSION},
    }
    if manager == "pnpm":
        manifest["packageManager"] = "pnpm@10.14.0"
    (target / "package.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (target / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "strict": True,
                    "target": "es2022",
                    "module": "es2022",
                    "moduleResolution": "bundler",
                    "noEmit": True,
                    "types": [],
                },
                "include": ["src"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (target / "src" / "index.ts").write_text(
        f'export const appName: string = "{SOURCE.app_name}";\n',
        encoding="utf-8",
    )
    (target / "bin" / f"{SOURCE.cli_name}.js").write_text(
        f'#!/usr/bin/env node\nconsole.log("{SOURCE.cli_name} ready");\n',
        encoding="utf-8",
    )
    (target / "test" / "cli.test.js").write_text(
        'const test = require("node:test");\n'
        'const assert = require("node:assert");\n'
        'const { execFileSync } = require("node:child_process");\n'
        'const path = require("node:path");\n\n'
        'test("cli runs", () => {\n'
        f'  const bin = path.join(__dirname, "..", "bin", "{SOURCE.cli_name}.js");\n'
        '  const out = execFileSync(process.execPath, [bin], { encoding: "utf8" });\n'
        f'  assert.strictEqual(out.trim(), "{SOURCE.cli_name} ready");\n'
        "});\n",
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {SOURCE.repo_name}\n\nInstall {SOURCE.npm_name} and run "
        f"`{SOURCE.cli_name}`.\n",
        encoding="utf-8",
    )
    (target / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    lock = _run(LOCK_COMMAND[manager], target, _manager_env(manager, base))
    assert lock.returncode == 0, lock.stderr
    assert (target / LOCKFILE[manager]).is_file()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(
        target,
        "remote",
        "add",
        "origin",
        f"https://github.com/{SOURCE.owner}/{SOURCE.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def _press_and_prove(
    manager: Manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require(manager)
    env = _manager_env(manager, tmp_path)
    # The press reads the declared name from the operator environment.
    monkeypatch.setenv(CACHE_VARS[manager], env[CACHE_VARS[manager]])
    target = make_node_target(tmp_path, manager)
    answers = write_answers_file(tmp_path, DEST)

    press_code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert press_code == 0
    assert (target / RECEIPT_REL).is_file()

    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    assert verify_command(["--target", str(target)]) == 0

    for path in target.rglob("*"):
        if ".git" in path.relative_to(target).parts or not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == RECEIPT_REL.as_posix():  # the receipt records the source identity
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in OLD_TOKENS:
            assert token not in rel, f"{token!r} survives in path {rel}"
            assert token not in text, f"{token!r} survives in {rel}"

    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pressed["name"] == DEST.npm_name
    assert pressed["bin"] == {DEST.cli_name: f"./bin/{DEST.cli_name}.js"}
    assert (target / "bin" / f"{DEST.cli_name}.js").is_file()
    assert pressed["devDependencies"]["typescript"] == TYPESCRIPT_VERSION
    lock_text = (target / LOCKFILE[manager]).read_text(encoding="utf-8")
    assert TYPESCRIPT_VERSION in lock_text

    frozen = _run(FROZEN_COMMAND[manager], target, env)
    assert frozen.returncode == 0, frozen.stdout + frozen.stderr
    for script in ("test", "typecheck"):
        result = _run([*RUN_COMMAND[manager], script], target, env)
        assert result.returncode == 0, f"{script}: {result.stdout}{result.stderr}"


@pytest.mark.live
@posix_only
@pytest.mark.parametrize("manager", ["npm", "bun"])
def test_real_target_presses_clean(
    manager: Manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _press_and_prove(manager, tmp_path, monkeypatch)


@pytest.mark.live
@posix_only
def test_real_pnpm_target_presses_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _press_and_prove("pnpm", tmp_path, monkeypatch)


def test_ci_never_skips_required_managers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    for manager in ("npm", "bun"):
        with pytest.raises(pytest.fail.Exception):
            _require(manager)
    with pytest.raises(pytest.skip.Exception):
        _require("pnpm")
