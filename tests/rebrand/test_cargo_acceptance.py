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


def _commit_unmapped(
    target: Path, files: dict[str, str], identity: dict[str, str]
) -> None:
    _write(
        target,
        {
            **files,
            ".gitignore": "target/\nCargo.lock\n",
            "press/press-source.toml": _table("identity", identity),
        },
    )
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    url = f"https://github.com/{identity['owner']}/{identity['repo_name']}.git"
    _git(target, "remote", "add", "origin", url)
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")


def _prefix_workspace() -> dict[str, str]:
    package = '[package]\nname = "{}"\nversion = "0.1.0"\nedition = "2021"\n'
    return {
        "Cargo.toml": '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n',
        "crates/acme/Cargo.toml": package.format("acme")
        + '[dependencies]\nacme-core = { path = "../acme-core" }\n',
        "crates/acme/src/main.rs": "fn main() {\n    acme_core::hi();\n}\n",
        "crates/acme-core/Cargo.toml": package.format("acme-core"),
        "crates/acme-core/src/lib.rs": "pub fn hi() {}\n",
    }


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize(
    ("source", "dest"),
    [
        (
            {"package_name": "acme", "repo_name": "acme", "app_name": "acme"},
            {"package_name": "zeta", "repo_name": "zeta", "app_name": "zeta"},
        ),
        (
            {"package_name": "other_pkg", "repo_name": "acme", "app_name": "other"},
            {"package_name": "zeta_pkg", "repo_name": "zeta", "app_name": "zother"},
        ),
    ],
    ids=["all_fields_prefix", "repo_only_prefix"],
)
def test_tableless_prefix_workspace_builds_after_press(
    source: dict[str, str], dest: dict[str, str], tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    identity = {**ACME, **source}
    destination = {**ZETA, **dest}
    readme = f"{identity['package_name']} {identity['app_name']}\n"
    _commit_unmapped(target, {**_prefix_workspace(), "README.md": readme}, identity)
    answers = tmp_path / "answers.toml"
    answers.write_text(_table("answers", destination), encoding="utf-8")

    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--offline")
    _set_origin(target, destination)
    assert verify_command(["--target", str(target)]) == 0
    _assert_tokens_absent(target, ("acme",))


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_bin_env_token_compiles_after_press(tmp_path: Path, cargo_or_skip) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    files = {
        "Cargo.toml": (
            '[package]\nname = "acme-core"\nversion = "0.1.0"\n'
            f'edition = "2021"\n{AUTHOR_LINE}repository = "{REPOSITORY}"\n\n'
            '[[bin]]\nname = "acme-cli"\npath = "src/main.rs"\n'
        ),
        "src/main.rs": 'fn main() {\n    println!("hello");\n}\n',
        "tests/cli.rs": (
            "#[test]\nfn runs_the_binary() {\n"
            '    let bin = env!("CARGO_BIN_EXE_acme-cli");\n'
            "    let done = std::process::Command::new(bin).output().unwrap();\n"
            "    assert!(done.status.success());\n}\n"
        ),
    }
    _commit_fixture(target, files, {"cli": "acme-cli", "core": "acme-core"})
    answers = _answers(
        tmp_path, "zeta.toml", ZETA, {"cli": "zeta-cli", "core": "zeta-core"}
    )

    _press_and_verify(target, answers, ZETA)

    assert "CARGO_BIN_EXE_zeta-cli" in (target / "tests/cli.rs").read_text()
    _assert_tokens_absent(target, ("acme", "Acme"))


# --- P15-T08: declared paths, with real Cargo as the oracle ----------------------

OWNER_ONLY = {
    **ACME,
    "package_name": "other_pkg",
    "repo_name": "other-repo",
    "app_name": "tool_app",
    "author": "Dev Author",
    "email": "dev@example.test",
    "owner": "acme",
}
PACKAGE = '[package]\nname = "{}"\nversion = "0.1.0"\nedition = "2021"\n'
SPLIT_SHAPES = {
    "lib": {
        "Cargo.toml": PACKAGE.format("acme-core") + '\n[lib]\npath = "lib/acme-x.rs"\n',
        "lib/acme-x.rs": "pub fn hi() {}\n",
    },
    "bin": {
        "Cargo.toml": PACKAGE.format("acme-core")
        + '\n[[bin]]\nname = "tool"\npath = "tools/acme-x.rs"\n',
        "tools/acme-x.rs": "fn main() {}\n",
    },
    "build": {
        "Cargo.toml": PACKAGE.format("acme-core") + 'build = "tools/acme-build.rs"\n',
        "tools/acme-build.rs": "fn main() {}\n",
        "src/lib.rs": "pub fn hi() {}\n",
    },
    "inferred_bin": {
        "Cargo.toml": PACKAGE.format("tool-pkg") + '\n[[bin]]\nname = "acme-cli"\n',
        "src/bin/acme-cli.rs": "fn main() {}\n",
    },
    "inferred_example": {
        "Cargo.toml": PACKAGE.format("tool-pkg")
        + '\n[[example]]\nname = "acme-demo"\n',
        "src/lib.rs": "pub fn hi() {}\n",
        "examples/acme-demo.rs": "fn main() {}\n",
    },
    "inferred_test": {
        "Cargo.toml": PACKAGE.format("tool-pkg") + '\n[[test]]\nname = "acme-it"\n',
        "src/lib.rs": "pub fn hi() {}\n",
        "tests/acme-it.rs": "#[test]\nfn runs() {}\n",
    },
    "inferred_bench": {
        "Cargo.toml": PACKAGE.format("tool-pkg")
        + '\n[[bench]]\nname = "acme-speed"\nharness = false\n',
        "src/lib.rs": "pub fn hi() {}\n",
        "benches/acme-speed.rs": "fn main() {}\n",
    },
    "package_workspace": {
        "Cargo.toml": PACKAGE.format("tool-pkg") + 'workspace = "acme-ws"\n',
        "src/lib.rs": "pub fn hi() {}\n",
        "acme-ws/Cargo.toml": '[workspace]\nresolver = "2"\nmembers = [".."]\n',
    },
    "unrelated_dependency": {
        "Cargo.toml": '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n',
        "crates/app/Cargo.toml": PACKAGE.format("tool-app")
        + '\n[dependencies]\nhelper = { path = "../acme-x" }\n',
        "crates/app/src/main.rs": "fn main() {\n    helper::hi();\n}\n",
        "crates/acme-x/Cargo.toml": PACKAGE.format("helper"),
        "crates/acme-x/src/lib.rs": "pub fn hi() {}\n",
    },
}
HEALTHY_SHAPES = {
    "auto_discovered_bin": {
        "Cargo.toml": PACKAGE.format("tool-pkg"),
        "src/lib.rs": "pub fn hi() {}\n",
        "src/bin/acme-cli.rs": "fn main() {}\n",
        "press/press-rules.toml": '[rules]\nkeep_names = ["acme-cli"]\n',
    },
    "unreferenced_manifest": {
        "Cargo.toml": PACKAGE.format("tool-pkg"),
        "src/lib.rs": "pub fn hi() {}\n",
        "testdata/acme-sample/Cargo.toml": PACKAGE.format("acme-sample"),
        "testdata/acme-sample/src/lib.rs": "pub fn hi() {}\n",
        "press/press-rules.toml": '[rules]\nkeep_names = ["acme-sample"]\n',
    },
}


def _owner_answers(tmp_path: Path) -> Path:
    answers = tmp_path / "answers.toml"
    answers.write_text(
        _table("answers", {**OWNER_ONLY, "owner": "zeta"}), encoding="utf-8"
    )
    return answers


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", sorted(SPLIT_SHAPES))
def test_split_declared_path_is_refused_and_still_builds(
    shape: str, tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _commit_unmapped(target, SPLIT_SHAPES[shape], OWNER_ONLY)
    _assert_cargo(target, "check", "--offline", "--all-targets")

    assert (
        main(["--target", str(target), "--config", str(_owner_answers(tmp_path))]) == 2
    )

    assert not (target / RECEIPT_REL).exists()
    status = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""
    _assert_cargo(target, "check", "--offline")


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", sorted(HEALTHY_SHAPES))
def test_undeclared_path_presses_and_builds(
    shape: str, tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _commit_unmapped(target, HEALTHY_SHAPES[shape], OWNER_ONLY)
    _assert_cargo(target, "check", "--offline")

    assert (
        main(["--target", str(target), "--config", str(_owner_answers(tmp_path))]) == 0
    )

    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--offline")


def _consistent_workspace(members: str) -> dict[str, str]:
    return {
        "Cargo.toml": f'[workspace]\nresolver = "2"\nmembers = ["{members}"]\n',
        "crates/acme-app/Cargo.toml": PACKAGE.format("acme-app")
        + 'build = "tools/acme-build.rs"\n'
        + '\n[lib]\npath = "lib/acme-app.rs"\n'
        + '\n[[bin]]\nname = "acme-tool"\npath = "tools/acme-tool.rs"\n'
        + '\n[[example]]\nname = "acme-demo"\n'
        + '\n[dependencies]\nacme-core = { path = "../acme-core" }\n',
        "crates/acme-app/examples/acme-demo.rs": "fn main() {}\n",
        "crates/acme-app/tools/acme-build.rs": "fn main() {}\n",
        "crates/acme-app/lib/acme-app.rs": "pub use acme_core::hi;\n",
        "crates/acme-app/tools/acme-tool.rs": "fn main() {\n    acme_app::hi();\n}\n",
        "crates/acme-core/Cargo.toml": PACKAGE.format("acme-core"),
        "crates/acme-core/src/lib.rs": "pub fn hi() {}\n",
    }


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("members", ["crates/*", "crates/acme-*"])
def test_declared_paths_moved_with_their_files_press_and_build(
    members: str, tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    identity = {**ACME, "package_name": "acme", "repo_name": "acme", "app_name": "acme"}
    destination = {
        **ZETA,
        "package_name": "zeta",
        "repo_name": "zeta",
        "app_name": "zeta",
    }
    _commit_unmapped(target, _consistent_workspace(members), identity)
    _assert_cargo(target, "check", "--offline")
    answers = tmp_path / "answers.toml"
    answers.write_text(_table("answers", destination), encoding="utf-8")

    assert main(["--target", str(target), "--config", str(answers)]) == 0

    assert (target / RECEIPT_REL).is_file()
    assert (target / "crates/zeta-app/lib/zeta-app.rs").is_file()
    _assert_cargo(target, "check", "--offline")
    _set_origin(target, destination)
    assert verify_command(["--target", str(target)]) == 0
    _assert_tokens_absent(target, ("acme",))


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_bin_env_token_moves_with_an_auto_discovered_bin(
    tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    identity = {**ACME, "package_name": "acme", "repo_name": "acme", "app_name": "acme"}
    destination = {
        **ZETA,
        "package_name": "zeta",
        "repo_name": "zeta",
        "app_name": "zeta",
    }
    files = {
        "Cargo.toml": PACKAGE.format("acme"),
        "src/lib.rs": "pub fn hi() {}\n",
        "src/bin/acme-cli.rs": "fn main() {}\n",
        "tests/cli.rs": (
            "#[test]\nfn names_the_binary() {\n"
            '    assert!(!env!("CARGO_BIN_EXE_acme-cli").is_empty());\n}\n'
        ),
    }
    _commit_unmapped(target, files, identity)
    _assert_cargo(target, "test", "--offline")
    answers = tmp_path / "answers.toml"
    answers.write_text(_table("answers", destination), encoding="utf-8")

    assert main(["--target", str(target), "--config", str(answers)]) == 0

    assert (target / "src/bin/zeta-cli.rs").is_file()
    _assert_cargo(target, "test", "--offline")


EXCLUDED = "crates/acme-x/Cargo.toml"


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_excluded_crate_split_is_refused_and_still_builds(
    tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    files = {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\nmembers = ["crates/app"]\n'
            'exclude = ["crates/acme-x"]\n'
        ),
        "crates/app/Cargo.toml": PACKAGE.format("tool-app"),
        "crates/app/src/lib.rs": "pub fn hi() {}\n",
        "crates/acme-x/Cargo.toml": PACKAGE.format("helper"),
        "crates/acme-x/src/lib.rs": "pub fn hi() {}\n",
    }
    _commit_unmapped(target, files, OWNER_ONLY)
    _assert_cargo(target, "check", "--offline", "--manifest-path", EXCLUDED)

    assert (
        main(["--target", str(target), "--config", str(_owner_answers(tmp_path))]) == 2
    )

    assert not (target / RECEIPT_REL).exists()
    _assert_cargo(target, "check", "--offline", "--manifest-path", EXCLUDED)


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_bin_env_token_in_an_excluded_file_is_refused(
    tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    identity = {**OWNER_ONLY, "app_name": "acme", "owner": "other-org"}
    files = {
        "Cargo.toml": PACKAGE.format("tool-pkg"),
        "src/lib.rs": "pub fn hi() {}\n",
        "src/bin/acme.rs": "fn main() {}\n",
        "tests/cli.rs": (
            "#[test]\nfn names_the_binary() {\n"
            '    assert!(!env!("CARGO_BIN_EXE_acme").is_empty());\n}\n'
        ),
        "press/press-rules.toml": '[rules]\nextra_exclude_dirs = ["tests"]\n',
    }
    _commit_unmapped(target, files, identity)
    _assert_cargo(target, "test", "--offline")
    answers = tmp_path / "answers.toml"
    answers.write_text(
        _table("answers", {**identity, "app_name": "zeta"}), encoding="utf-8"
    )

    assert main(["--target", str(target), "--config", str(answers)]) == 2

    assert not (target / RECEIPT_REL).exists()
    _assert_cargo(target, "test", "--offline")


MATURIN_ACME = {**ACME, "package_name": "acme_widget", "app_name": "acme_widget"}
MATURIN_ZETA = {**ZETA, "package_name": "zeta_widget", "app_name": "zeta_widget"}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_maturin_leading_underscore_lib_presses_builds_and_verifies(
    tmp_path: Path, cargo_or_skip
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    names = {"widget": "acme-widget", "py": "_acme_widget"}
    _write(
        target,
        {
            "Cargo.toml": (
                '[package]\nname = "acme-widget"\nversion = "0.1.0"\n'
                f'edition = "2021"\n{AUTHOR_LINE}repository = "{REPOSITORY}"\n\n'
                '[lib]\nname = "_acme_widget"\npath = "src/lib.rs"\n'
            ),
            "pyproject.toml": '[project]\nname = "acme-widget"\nversion = "0.1.0"\n',
            "src/acme_widget/__init__.py": "",
            "src/lib.rs": (
                'pub const MODULE: &str = "_acme_widget";\n'
                'pub const PACKAGE: &str = "acme_widget";\n'
            ),
            "tests/smoke.rs": (
                "#[test]\nfn links_library() {\n"
                '    assert_eq!(_acme_widget::MODULE, "_acme_widget");\n}\n'
            ),
            ".gitignore": "target/\n",
            "press/press-source.toml": _table("identity", MATURIN_ACME)
            + _table("identity.cargo_names", names),
            "press/press-rules.toml": LOCK_RULES.replace(
                "[rules]\n", '[rules]\nlanguages = ["python", "rust"]\n', 1
            ),
        },
    )
    _assert_cargo(target, "generate-lockfile", "--offline")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(target, "remote", "add", "origin", f"{REPOSITORY}.git")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    answers = _answers(
        tmp_path,
        "zeta.toml",
        MATURIN_ZETA,
        {"widget": "zeta-widget", "py": "_zeta_widget"},
    )

    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert (target / RECEIPT_REL).is_file()
    lib = (target / "src/lib.rs").read_text(encoding="utf-8")
    assert '"_zeta_widget"' in lib
    assert '"zeta_widget"' in lib
    assert "__zeta" not in lib
    _assert_cargo(target, "check", "--offline")
    _set_origin(target, MATURIN_ZETA)
    assert verify_command(["--target", str(target)]) == 0
    _assert_tokens_absent(target, ("acme", "Acme"))
