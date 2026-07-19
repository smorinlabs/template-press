"""End-to-end `press verify` — the hermetic sandbox self-press leak check (Task 12).

`verify_command` ties every prior module together: preflight against the REAL
target (discover/mismatches + a presence check), then — inside an owned,
torn-down sandbox — a faithful copy, a HERMETIC `engine.apply` toward a
synthetic equality-preserving identity, a paranoid `verifier.scan`, and
source-anchored `apply_ignores`. Exit codes: 2 config/env/unverifiable (never
mutating the real target), 1 a real finding/stale ignore/equal-fields
collision/unavailable submodule, 0 verified-clean.

All fixtures/decoys live strictly under ``tmp_path``; every git op is routed
through ``git -C <tmp>`` so the autouse containment guard (tests/conftest.py)
is satisfied.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from template_press.rebrand.verify_cli import verify_command

from .conftest import requires_symlink

# The pressable target's committed FROM identity (discoverable + consistent).
DEFAULT_IDENTITY: dict[str, str] = {
    "package_name": "demo_widget",
    "repo_name": "demo-widget",
    "app_name": "press",
    "author": "Demo Author",
    "email": "demo@example.com",
    "owner": "demolabs",
}


def _git(repo: Path, *args: str) -> None:
    # git binary is hardcoded and the repo path is a test-owned tmp target; the
    # -C pin keeps the op under tmp_path so the autouse guard is satisfied.
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def _render_source(identity: dict[str, str]) -> str:
    lines = ["[identity]"]
    lines += [f'{k} = "{v}"' for k, v in identity.items()]
    return "\n".join(lines) + "\n"


def make_pressable(
    tmp_path: Path,
    *,
    identity: dict[str, str] | None = None,
    scripts: bool = True,
    source_identity: dict[str, str] | None = None,
) -> Path:
    """A minimal-but-real pressable target: pyproject with ``[project.scripts]``,
    a ``src/<pkg>`` package, a README with English-word traps, and a committed
    ``press/press-source.toml`` FROM identity. Git is init'd with an ``origin``
    remote (so owner/repo are discoverable) but NOT committed — the caller runs
    ``_commit`` after adding any decoy files.
    """
    ident = {**DEFAULT_IDENTITY, **(identity or {})}
    repo = tmp_path / "target"
    pkg = repo / "src" / ident["package_name"]
    pkg.mkdir(parents=True)

    scripts_block = (
        f"\n[project.scripts]\n{ident['app_name']} = "
        f'"{ident["package_name"]}.cli:main"\n'
        if scripts
        else ""
    )
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{ident["package_name"]}"\nversion = "0.1.0"\n'
        f'authors = [{{ name = "{ident["author"]}", '
        f'email = "{ident["email"]}" }}]\n'
        f'requires-python = ">=3.12"\n{scripts_block}',
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        f"# {ident['repo_name']}\n\n"
        "Compress the archive before express delivery; "
        "do not let the pressure rise.\n"
        f"Run `{ident['app_name']} --help`. Repo: "
        f"https://github.com/{ident['owner']}/{ident['repo_name']}\n"
        f"Maintained by {ident['author']} <{ident['email']}>.\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text(
        f'"""{ident["package_name"]} package."""\n', encoding="utf-8"
    )
    (pkg / "cli.py").write_text(
        f'"""{ident["package_name"]} cli."""\n\n\ndef main() -> int:\n    return 0\n',
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")

    (repo / "press").mkdir()
    src_ident = source_identity if source_identity is not None else ident
    (repo / "press" / "press-source.toml").write_text(
        _render_source(src_ident), encoding="utf-8"
    )

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        f"https://github.com/{ident['owner']}/{ident['repo_name']}.git",
    )
    return repo


def _commit(repo: Path, message: str = "snapshot") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)


def _tree(repo: Path) -> dict[str, tuple[str, str]]:
    """A ``{relpath: (kind, hash|linktarget)}`` snapshot of the working tree
    (``.git`` excluded) — for proving a run wrote NOTHING to the real target."""
    root = repo.resolve()
    out: dict[str, tuple[str, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                out[rel] = ("L", os.readlink(path))
            else:
                out[rel] = ("F", hashlib.sha256(path.read_bytes()).hexdigest())
    return out


# ---------------------------------------------------------------------------
# 12.1 — the plan's failing-tests list, verbatim
# ---------------------------------------------------------------------------
def test_clean_template_exits_0(tmp_path: Path) -> None:
    # incl. compress/press English traps in README + a regenerable uv.lock
    # (exempt from the scan, so its old package_name is NOT a leak).
    repo = make_pressable(tmp_path)
    (repo / "uv.lock").write_text('name = "demo_widget"\n', encoding="utf-8")
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 0


def test_bun_lock_leak_exits_1(tmp_path: Path) -> None:
    # bun.lock is a DEFAULT exclude (never rewritten) but NOT regenerable, so it
    # IS scanned — a surviving package_name is a leak.
    repo = make_pressable(tmp_path)
    (repo / "bun.lock").write_text('"name":"demo_widget"\n', encoding="utf-8")
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 1


def test_hyphen_token_leak_exits_1(tmp_path: Path) -> None:
    # package-lock.json is excluded from rewrite but scanned; the hyphen-form
    # repo_name survives and must be flagged.
    repo = make_pressable(tmp_path)
    (repo / "package-lock.json").write_text(
        '{"name": "demo-widget"}\n', encoding="utf-8"
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 1


def test_missing_source_config_exits_2_no_write(tmp_path: Path) -> None:
    repo = make_pressable(tmp_path)
    (repo / "press" / "press-source.toml").unlink()
    _commit(repo)
    before = _tree(repo)
    assert verify_command(["--target", str(repo)]) == 2
    # verify NEVER mutates the real target — exit 2 wrote nothing.
    assert _tree(repo) == before


def test_declared_app_absent_exits_2(tmp_path: Path) -> None:
    # Drop [project.scripts] so discovery cannot see app_name, and declare a
    # phantom app_name in the source-config that appears NOWHERE in the target:
    # undiscoverable AND absent -> presence fails -> 2.
    repo = make_pressable(tmp_path)
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        pyproject.split("[project.scripts]")[0], encoding="utf-8"
    )
    (repo / "press" / "press-source.toml").write_text(
        _render_source({**DEFAULT_IDENTITY, "app_name": "ghost"}), encoding="utf-8"
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 2


@requires_symlink
def test_control_path_symlink_rejected_exits_2(tmp_path: Path) -> None:
    repo = make_pressable(tmp_path)
    shutil.rmtree(repo / "press")
    outside = tmp_path / "outside"
    outside.mkdir()
    # A symlinked control dir could redirect a control-file read/write out of
    # the tree — assert_control_real rejects it at load time -> 2.
    (repo / "press").symlink_to(outside, target_is_directory=True)
    assert verify_command(["--target", str(repo)]) == 2
    # Nothing was written into the external decoy.
    assert list(outside.iterdir()) == []


def test_ignore_suppresses_then_drifts(tmp_path: Path) -> None:
    repo = make_pressable(tmp_path)
    # A real leftover: an unregenerable lockfile carrying the old owner token.
    # owner ("demolabs") is used because — unlike package_name/repo_name, whose
    # separator-normalized forms collide — no other identity field matches it,
    # so the leftover yields exactly one finding to suppress.
    (repo / "bun.lock").write_text('"name": "demolabs"\n', encoding="utf-8")
    rules = repo / "press" / "press-rules.toml"
    rules.write_text(
        "[[verify.ignore]]\n"
        'file = "bun.lock"\n'
        'field = "owner"\n'
        'value = "demolabs"\n'
        'anchor = "name"\n'
        'reason = "vendored lockfile, intentional"\n',
        encoding="utf-8",
    )
    _commit(repo)
    # The ignore suppresses the leftover -> clean.
    assert verify_command(["--target", str(repo)]) == 0

    # Break the anchor: it no longer matches the source line, so the leftover
    # resurfaces AND the ignore is stale -> 1.
    rules.write_text(
        "[[verify.ignore]]\n"
        'file = "bun.lock"\n'
        'field = "owner"\n'
        'value = "demolabs"\n'
        'anchor = "does-not-appear-on-that-line"\n'
        'reason = "broken anchor"\n',
        encoding="utf-8",
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 1


def test_equal_fields_warns_exits_0(tmp_path: Path, capsys) -> None:
    # package_name == app_name == repo_name (all "widget"): equality is
    # preserved by synthesis, so a clean press still verifies -> 0 with a WARN.
    repo = make_pressable(
        tmp_path,
        identity={
            "package_name": "widget",
            "app_name": "widget",
            "repo_name": "widget",
        },
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 0
    assert "equal" in capsys.readouterr().err.lower()

    # equal_fields = "error" turns the same equality into a hard failure -> 1.
    (repo / "press" / "press-rules.toml").write_text(
        '[verify]\nequal_fields = "error"\n', encoding="utf-8"
    )
    _commit(repo)
    assert verify_command(["--target", str(repo)]) == 1


def test_env_regen_absent_is_2(monkeypatch, tmp_path: Path) -> None:
    # A tool/env failure during the sandbox press is an env error -> 2 (NOT a
    # leak's 1): the press could not complete, so verify cannot claim clean.
    repo = make_pressable(tmp_path)
    _commit(repo)

    def boom(*_a, **_k):
        raise OSError("simulated tool/env failure during press")

    monkeypatch.setattr("template_press.rebrand.verify_cli.apply", boom)
    assert verify_command(["--target", str(repo)]) == 2


# ---------------------------------------------------------------------------
# Regression: a gitignored + `git add -f`'d BINARY whose bytes embed a source
# value and whose path carries a rename token must NOT read as clean. Root
# cause of the fixed bug: a plain `git add -A` re-stage respects .gitignore, so
# after apply renames the file to a still-ignored path the file dropped out of
# the sandbox index and scan never saw the surviving bytes (apply cannot
# rewrite binary) -> FALSE CLEAN. The re-stage now force-adds (`-A -f`).
# ---------------------------------------------------------------------------
def _add_leaky_binary(repo: Path, *, gitignore_assets: bool) -> None:
    """A binary under a token-bearing path whose bytes embed ``demo_widget``."""
    if gitignore_assets:
        with (repo / ".gitignore").open("a", encoding="utf-8") as fh:
            fh.write("assets/\n")
    (repo / "assets").mkdir(exist_ok=True)
    (repo / "assets" / "demo_widget.bin").write_bytes(
        b"\x00\x01demo_widget\xff\xfe binary blob\x00"
    )
    _git(repo, "add", "-A")
    _git(repo, "add", "-f", "assets/demo_widget.bin")


def test_gitignored_forceadded_binary_leak_exits_1(tmp_path: Path) -> None:
    # The PoC: `assets/` is gitignored, the binary is force-added. apply renames
    # assets/demo_widget.bin -> assets/<synth>.bin (still under ignored assets/)
    # and cannot rewrite the embedded bytes; the force-add re-stage keeps it in
    # the sandbox index so scan catches the surviving `demo_widget` bytes.
    repo = make_pressable(tmp_path)
    _add_leaky_binary(repo, gitignore_assets=True)
    _git(repo, "commit", "-q", "-m", "force-add ignored leaky binary")
    assert verify_command(["--target", str(repo)]) == 1


def test_nongitignored_binary_leak_exits_1(tmp_path: Path) -> None:
    # Control for the PoC: the identical binary that is NOT gitignored also -> 1,
    # so the gitignored test above proves the .gitignore path specifically is
    # now covered (both reach the scanner, not just the tracked one).
    repo = make_pressable(tmp_path)
    _add_leaky_binary(repo, gitignore_assets=False)
    _git(repo, "commit", "-q", "-m", "add leaky binary")
    assert verify_command(["--target", str(repo)]) == 1


# ---------------------------------------------------------------------------
# M1 coverage: a target with a real gitlink/submodule -> 1 (a submodule the
# sandbox could not fully verify is never a silent pass — non-empty
# `unavailable_submodules` forces exit 1).
# ---------------------------------------------------------------------------
def test_gitlink_submodule_exits_1(tmp_path: Path) -> None:
    repo = make_pressable(tmp_path)
    # Build a throwaway inner repo and register it as a gitlink in the target's
    # index (no working-tree checkout needed).
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q", "-b", "main")
    _git(inner, "config", "user.email", "test@example.com")
    _git(inner, "config", "user.name", "Test")
    (inner / "f.txt").write_text("x\n", encoding="utf-8")
    _git(inner, "add", "-A")
    _git(inner, "commit", "-q", "-m", "inner init")
    sha = subprocess.run(  # noqa: S603
        ["git", "-C", str(inner), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _commit(repo)
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendored")
    _git(repo, "commit", "-q", "-m", "add gitlink")
    assert verify_command(["--target", str(repo)]) == 1


# ---------------------------------------------------------------------------
# I2: a surviving finding must be REPORTED in SOURCE coordinates, never the
# sandbox synthetic path — and this holds through the forward-map fixpoint for
# a DOUBLY-renamed path (both the package dir and the file carry the token).
# ---------------------------------------------------------------------------
def test_json_report_maps_surviving_path_to_source_coords(
    tmp_path: Path, capsys
) -> None:
    repo = make_pressable(tmp_path)
    # A binary leak inside the package dir: apply renames src/demo_widget ->
    # src/<synth> (pass 1) then src/<synth>/demo_widget.bin ->
    # src/<synth>/<synth>.bin (pass 2) but cannot rewrite the embedded bytes, so
    # the finding survives at the doubly-renamed SANDBOX path. The report must
    # translate it back to src/demo_widget/demo_widget.bin.
    leak = repo / "src" / "demo_widget" / "demo_widget.bin"
    leak.write_bytes(b"\x00\x01demo_widget\xff\xfe binary blob\x00")
    _commit(repo)

    assert verify_command(["--target", str(repo), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["verified"] is False
    paths = [f["path"] for f in out["surviving"]]
    assert "src/demo_widget/demo_widget.bin" in paths
    # Every reported path is a SOURCE coordinate — it exists in the real target
    # (a raw sandbox synth path such as src/<hash>/<hash>.bin would not).
    for p in paths:
        assert (repo / p).exists(), f"reported path {p!r} is not a source path"


# ---------------------------------------------------------------------------
# G9 (plan headline): a full verify_command run must leave the REAL target
# byte-identical — on BOTH the clean (exit 0) and the leak (exit 1) paths. Each
# reaches the sandbox copy/apply/scan; verify must never write to the target.
# ---------------------------------------------------------------------------
def test_verify_never_mutates_real_target_exit_0_and_1(tmp_path: Path) -> None:
    # exit-0: a clean template (regenerable uv.lock is scan-exempt).
    clean = make_pressable(tmp_path / "clean")
    (clean / "uv.lock").write_text('name = "demo_widget"\n', encoding="utf-8")
    _commit(clean)
    before_clean = _tree(clean)
    assert verify_command(["--target", str(clean)]) == 0
    assert _tree(clean) == before_clean

    # exit-1: a real leftover (owner token in an unregenerable lockfile).
    leak = make_pressable(tmp_path / "leak")
    (leak / "bun.lock").write_text('"name": "demolabs"\n', encoding="utf-8")
    _commit(leak)
    before_leak = _tree(leak)
    assert verify_command(["--target", str(leak)]) == 1
    assert _tree(leak) == before_leak
