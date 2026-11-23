"""End-to-end proof that real Cargo targets press, build, test, and verify.

Each fixture is a committed Cargo repository that uses only the Rust standard
library and path dependencies, so no test needs a registry or the network. The
locked-dependency test adds a local directory source for the same reason.

Direct ``cargo`` commands keep ``CARGO_HOME`` inside ``tmp_path``. The press's
declared ``cargo update`` cannot: its command environment passes ``HOME`` but
not ``CARGO_HOME``, so it uses the default Cargo home. Every test that presses
therefore shares the ``shared-tool-caches`` xdist group.

Run explicitly: uv run pytest -m "" tests/rebrand/test_cargo_acceptance.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.verify_cli import verify_command

from .conftest import _git, posix_only

ACME = {
    "package_name": "acme_core",
    "repo_name": "acme-repo",
    "app_name": "acme",
    "author": "Acme Author",
    "email": "acme@example.test",
    "owner": "acmelabs",
}
ZETA = {
    "package_name": "zeta_core",
    "repo_name": "zeta-repo",
    "app_name": "zeta",
    "author": "Zeta Author",
    "email": "zeta@example.test",
    "owner": "zetalabs",
}
NOVA = {
    "package_name": "nova_core",
    "repo_name": "nova-repo",
    "app_name": "nova",
    "author": "Nova Author",
    "email": "nova@example.test",
    "owner": "novalabs",
}
ACME_NAMES = {
    "single_crate": {"core": "acme-core", "engine": "acme_engine"},
    "workspace": {
        "core": "acme-core",
        "engine": "acme_engine",
        "widget": "acme-widget",
    },
}
ZETA_NAMES = {
    "single_crate": {"core": "zeta-core", "engine": "zeta_engine"},
    "workspace": {
        "core": "zeta-core",
        "engine": "zeta_engine",
        "widget": "zeta-gadget",
    },
}
NOVA_NAMES = {
    "single_crate": {"core": "nova-core", "engine": "nova_engine"},
    "workspace": {
        "core": "nova-core",
        "engine": "nova_engine",
        "widget": "nova-tool",
    },
}
LOCK_RULES = (
    '[rules]\nextra_exclude_files = ["Cargo.lock"]\n\n'
    '[[regenerate]]\nfile = "Cargo.lock"\n'
    'command = ["cargo", "update", "--workspace", "--offline"]\n'
)
LIB_RS = (
    'pub fn hi() -> &\'static str {\n    "hello"\n}\n\n'
    "#[cfg(test)]\nmod tests {\n    #[test]\n    fn says_hello() {\n"
    '        assert_eq!(super::hi(), "hello");\n    }\n}\n'
)
AUTHOR_LINE = 'authors = ["Acme Author <acme@example.test>"]\n'
REPOSITORY = "https://github.com/acmelabs/acme-repo"


def _require_cargo() -> None:
    if shutil.which("cargo") is not None:
        return
    if os.environ.get("CI"):
        pytest.fail("cargo is required in CI but is not on PATH")
    pytest.skip("cargo is not installed")


@pytest.fixture
def cargo_or_skip() -> None:
    _require_cargo()


def test_ci_never_skips_missing_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setenv("CI", "1")
    with pytest.raises(pytest.fail.Exception):
        _require_cargo()
    monkeypatch.delenv("CI")
    with pytest.raises(pytest.skip.Exception):
        _require_cargo()


def _cargo(target: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    home = target.parent / "cargo-home"
    home.mkdir(exist_ok=True)
    return subprocess.run(  # noqa: S603
        ["cargo", *argv],  # noqa: S607
        cwd=target,
        env={**os.environ, "CARGO_HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _assert_cargo(target: Path, *argv: str) -> None:
    done = _cargo(target, *argv)
    assert done.returncode == 0, f"cargo {argv}: {done.stdout}{done.stderr}"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _table(header: str, values: dict[str, str]) -> str:
    return f"[{header}]\n" + "".join(f'{k} = "{v}"\n' for k, v in values.items())


def _single_crate_files() -> dict[str, str]:
    return {
        "Cargo.toml": (
            '[package]\nname = "acme-core"\nversion = "0.1.0"\n'
            f'edition = "2021"\n{AUTHOR_LINE}repository = "{REPOSITORY}"\n\n'
            '[lib]\nname = "acme_engine"\npath = "src/lib.rs"\n'
        ),
        "src/lib.rs": LIB_RS,
        "src/main.rs": 'fn main() {\n    println!("{}", acme_engine::hi());\n}\n',
        "tests/smoke.rs": (
            '#[test]\nfn links_library() {\n    assert_eq!(acme_engine::hi(), "hello");'
            "\n}\n"
        ),
        "README.md": "# acme-repo\n\nRun `acme-core`, built on `acme_engine`.\n",
    }


def _workspace_files() -> dict[str, str]:
    return {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\n'
            'members = ["crates/acme-core", "crates/acme-widget"]\n\n'
            '[workspace.package]\nversion = "0.1.0"\nedition = "2021"\n'
            f'{AUTHOR_LINE}repository = "{REPOSITORY}"\n'
        ),
        "crates/acme-core/Cargo.toml": (
            '[package]\nname = "acme-core"\nversion.workspace = true\n'
            "edition.workspace = true\nauthors.workspace = true\n"
            'repository.workspace = true\n\n[lib]\nname = "acme_engine"\n'
            'path = "src/lib.rs"\n'
        ),
        "crates/acme-core/src/lib.rs": LIB_RS,
        "crates/acme-widget/Cargo.toml": (
            '[package]\nname = "acme-widget"\nversion.workspace = true\n'
            "edition.workspace = true\nauthors.workspace = true\n"
            "repository.workspace = true\n\n[dependencies]\n"
            'core = { package = "acme-core", path = "../acme-core" }\n'
        ),
        "crates/acme-widget/src/main.rs": (
            'fn main() {\n    println!("{}", core::hi());\n}\n\n'
            "#[cfg(test)]\nmod tests {\n    #[test]\n    fn uses_alias() {\n"
            '        assert_eq!(core::hi(), "hello");\n    }\n}\n'
        ),
        "README.md": (
            "# acme-repo\n\nCrates `acme-core` (`acme_engine`) and `acme-widget`.\n"
        ),
    }


def _commit_fixture(target: Path, files: dict[str, str], names: dict[str, str]) -> None:
    _write(
        target,
        {
            **files,
            ".gitignore": "target/\n",
            "press/press-source.toml": _table("identity", ACME)
            + _table("identity.cargo_names", names),
            "press/press-rules.toml": LOCK_RULES,
        },
    )
    _assert_cargo(target, "generate-lockfile", "--offline")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(target, "remote", "add", "origin", f"{REPOSITORY}.git")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")


def _build_fixture(shape: str, base: Path) -> Path:
    target = base / "target-repo"
    target.mkdir()
    files = _single_crate_files() if shape == "single_crate" else _workspace_files()
    _commit_fixture(target, files, ACME_NAMES[shape])
    return target


def _answers(
    base: Path, name: str, fields: dict[str, str], names: dict[str, str]
) -> Path:
    path = base / name
    path.write_text(
        _table("answers", fields) + _table("answers.cargo_names", names),
        encoding="utf-8",
    )
    return path


def _set_origin(target: Path, identity: dict[str, str]) -> None:
    url = f"https://github.com/{identity['owner']}/{identity['repo_name']}.git"
    _git(target, "remote", "set-url", "origin", url)


def _press_and_verify(
    target: Path, answers: Path, identity: dict[str, str], *flags: str
) -> None:
    assert main(["--target", str(target), "--config", str(answers), *flags]) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--locked", "--offline")
    _assert_cargo(target, "test", "--offline")
    _set_origin(target, identity)
    assert verify_command(["--target", str(target)]) == 0


def _assert_tokens_absent(target: Path, tokens: tuple[str, ...]) -> None:
    for path in target.rglob("*"):
        parts = path.relative_to(target).parts
        if ".git" in parts or "target" in parts or not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == RECEIPT_REL.as_posix():  # the receipt records the source identity
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in tokens:
            assert token not in rel, f"{token!r} survives in path {rel}"
            assert token not in text, f"{token!r} survives in {rel}"


def _locked_packages(target: Path) -> dict[str, str]:
    lock = tomllib.loads((target / "Cargo.lock").read_text(encoding="utf-8"))
    return {entry["name"]: entry["version"] for entry in lock["package"]}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", ["single_crate", "workspace"])
def test_unpressed_fixture_builds(shape: str, tmp_path: Path, cargo_or_skip) -> None:
    target = _build_fixture(shape, tmp_path)
    _assert_cargo(target, "check", "--locked", "--offline")
    _assert_cargo(target, "test", "--offline")


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", ["single_crate", "workspace"])
def test_press_check_test_verify(shape: str, tmp_path: Path, cargo_or_skip) -> None:
    target = _build_fixture(shape, tmp_path)
    answers = _answers(tmp_path, "zeta.toml", ZETA, ZETA_NAMES[shape])

    _press_and_verify(target, answers, ZETA)

    _assert_tokens_absent(target, ("acme", "Acme"))
    assert set(_locked_packages(target)) == {
        name for role, name in ZETA_NAMES[shape].items() if role != "engine"
    }
    if shape == "workspace":
        widget = target / "crates/zeta-gadget/Cargo.toml"
        manifest = tomllib.loads(widget.read_text(encoding="utf-8"))
        # The local alias stays; only the package and path values change.
        assert manifest["dependencies"]["core"] == {
            "package": "zeta-core",
            "path": "../zeta-core",
        }


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", ["single_crate", "workspace"])
def test_second_press_from_refreshed_source(
    shape: str, tmp_path: Path, cargo_or_skip
) -> None:
    target = _build_fixture(shape, tmp_path)
    first = _answers(tmp_path, "zeta.toml", ZETA, ZETA_NAMES[shape])
    _press_and_verify(target, first, ZETA)

    refreshed = tomllib.loads(
        (target / "press/press-source.toml").read_text(encoding="utf-8")
    )
    assert refreshed["identity"]["cargo_names"] == ZETA_NAMES[shape]
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "first press")

    second = _answers(tmp_path, "nova.toml", NOVA, NOVA_NAMES[shape])
    _press_and_verify(target, second, NOVA, "--force")

    _assert_tokens_absent(target, ("acme", "Acme", "zeta", "Zeta"))
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    press = receipt["press"]
    assert press["from"]["cargo_names"] == ZETA_NAMES[shape]
    assert press["to"]["cargo_names"] == NOVA_NAMES[shape]


def _vendor(root: Path, version: str) -> None:
    _write(
        root / "vendor" / f"padkit-{version}",
        {
            "Cargo.toml": (
                f'[package]\nname = "padkit"\nversion = "{version}"\nedition = "2021"\n'
            ),
            "src/lib.rs": "pub fn pad() -> u8 {\n    1\n}\n",
            ".cargo-checksum.json": '{"files":{},"package":null}',
        },
    )


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_press_keeps_locked_third_party_version(tmp_path: Path, cargo_or_skip) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    files = _workspace_files()
    files["crates/acme-core/Cargo.toml"] += '\n[dependencies]\npadkit = "1"\n'
    files["crates/acme-core/src/lib.rs"] += (
        "\npub fn pad() -> u8 {\n    padkit::pad()\n}\n"
    )
    files[".cargo/config.toml"] = (
        '[source.crates-io]\nreplace-with = "vendored"\n\n'
        '[source.vendored]\ndirectory = "vendor"\n'
    )
    _vendor(target, "1.0.0")
    _commit_fixture(target, files, ACME_NAMES["workspace"])
    assert _locked_packages(target)["padkit"] == "1.0.0"
    _vendor(target, "1.1.0")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "vendor a newer release")

    answers = _answers(tmp_path, "zeta.toml", ZETA, ZETA_NAMES["workspace"])
    _press_and_verify(target, answers, ZETA)

    locked = _locked_packages(target)
    assert locked["padkit"] == "1.0.0"
    assert {"zeta-core", "zeta-gadget"} <= set(locked)
    assert not {"acme-core", "acme-widget"} & set(locked)
