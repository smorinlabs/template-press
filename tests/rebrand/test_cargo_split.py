"""P15-T09: one-press rename of a hyphen-free crate to a hyphenated name.

``[[cargo_split]]`` in ``press/press-rules.toml`` lets ``acme`` become
``zeta-gadget`` in one press. Cargo manifests take the package spelling,
``.rs`` files the identifier spelling, and two glob lists name the other files.
Every other occurrence is refused before any write.

The slow tests use real Cargo as the oracle:
uv run pytest -m "" tests/rebrand/test_cargo_split.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    cargo_identity_problem,
    cargo_name_pairs,
    cargo_split_problems,
    cargo_split_roles,
)
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import CargoSplit, load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import _git, posix_only

ACME = {
    "package_name": "acme",
    "repo_name": "acme-repo",
    "app_name": "acmectl",
    "author": "Acme Author",
    "email": "acme@example.test",
    "owner": "acmelabs",
}
ZETA = {
    "package_name": "zeta_gadget",
    "repo_name": "zeta-repo",
    "app_name": "zetactl",
    "author": "Zeta Author",
    "email": "zeta@example.test",
    "owner": "zetalabs",
}
NOVA = {
    "package_name": "nova_gadget",
    "repo_name": "nova-repo",
    "app_name": "novactl",
    "author": "Nova Author",
    "email": "nova@example.test",
    "owner": "novalabs",
}
REPOSITORY = "https://github.com/acmelabs/acme-repo"
AUTHOR_LINE = 'authors = ["Acme Author <acme@example.test>"]\n'
LIB_RS = (
    'pub fn hi() -> &\'static str {\n    "hello"\n}\n\n'
    "#[cfg(test)]\nmod tests {\n    #[test]\n    fn says_hello() {\n"
    '        assert_eq!(super::hi(), "hello");\n    }\n}\n'
)
LOCK_RULES = (
    '[rules]\nextra_exclude_files = ["Cargo.lock"]\n\n'
    '[[regenerate]]\nfile = "Cargo.lock"\n'
    'command = ["cargo", "update", "--workspace", "--offline"]\n'
)
SINGLE_SPLIT = (
    '\n[[cargo_split]]\nrole = "core"\n'
    'package_files = ["README.md", "scripts/release.sh"]\n'
    'identifier_files = ["docs/api.md"]\n\n'
    '[[replace]]\npattern = "{package_name}::hi"\nfiles = ["README.md"]\n'
    'reason = "the README names the crate both ways"\n'
)
WORKSPACE_SPLIT = (
    '\n[[cargo_split]]\nrole = "core"\npackage_files = ["README.md"]\n'
    'identifier_files = ["docs/*.md"]\n'
)


def _table(header: str, values: dict[str, str]) -> str:
    return f"[{header}]\n" + "".join(f'{k} = "{v}"\n' for k, v in values.items())


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _package(name: str, *, workspace: bool = False) -> str:
    if workspace:
        return (
            f'[package]\nname = "{name}"\nversion.workspace = true\n'
            "edition.workspace = true\nauthors.workspace = true\n"
            "repository.workspace = true\n"
        )
    return (
        f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n'
        f'{AUTHOR_LINE}repository = "{REPOSITORY}"\n'
    )


def _single_crate_files() -> dict[str, str]:
    return {
        "Cargo.toml": _package("acme"),
        "src/lib.rs": LIB_RS,
        "src/main.rs": 'fn main() {\n    println!("{}", acme::hi());\n}\n',
        "tests/cli.rs": (
            "#[test]\nfn runs_the_binary() {\n"
            '    let bin = env!("CARGO_BIN_EXE_acme");\n'
            "    let done = std::process::Command::new(bin).output().unwrap();\n"
            "    assert!(done.status.success());\n"
            '    assert_eq!(acme::hi(), "hello");\n}\n'
        ),
        "README.md": "# acme-repo\n\nRun `cargo run -p acme`, then call `acme::hi()`.\n",
        "scripts/release.sh": "# ships acmectl\ncargo publish -p acme\n",
        "docs/api.md": "`acme::hi` returns hello.\n",
    }


def _workspace_files() -> dict[str, str]:
    return {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\nmembers = ["crates/acme", "crates/app"]\n\n'
            '[workspace.package]\nversion = "0.1.0"\nedition = "2021"\n'
            f'{AUTHOR_LINE}repository = "{REPOSITORY}"\n'
        ),
        "crates/acme/Cargo.toml": _package("acme", workspace=True),
        "crates/acme/src/lib.rs": LIB_RS,
        "crates/app/Cargo.toml": _package("app", workspace=True)
        + '\n[dependencies]\nacme = { path = "../acme" }\n',
        "crates/app/src/main.rs": (
            'fn main() {\n    println!("{}", acme::hi());\n}\n\n'
            "#[cfg(test)]\nmod tests {\n    #[test]\n    fn calls_core() {\n"
            '        assert_eq!(acme::hi(), "hello");\n    }\n}\n'
        ),
        "README.md": "# acme-repo\n\nTest the core with `cargo test -p acme`.\n",
        "docs/api.md": "Call `acme::hi()` from `app` or `acmectl`.\n",
    }


SHAPES = {
    "single_crate": (_single_crate_files, {"core": "acme"}, SINGLE_SPLIT),
    "workspace": (_workspace_files, {"core": "acme", "app": "app"}, WORKSPACE_SPLIT),
}
DEST_NAMES = {
    "single_crate": {"core": "zeta-gadget"},
    "workspace": {"core": "zeta-gadget", "app": "app"},
}
NOVA_NAMES = {
    "single_crate": {"core": "nova-gadget"},
    "workspace": {"core": "nova-gadget", "app": "app"},
}


def _identity(shape: str, values: dict[str, str]) -> dict[str, str]:
    return {**values, "package_name": "app"} if shape == "workspace" else values


def _seed(
    target: Path,
    files: dict[str, str],
    names: dict[str, str],
    rules: str,
    identity: dict[str, str],
    *,
    lock: bool,
) -> None:
    _write(
        target,
        {
            **files,
            ".gitignore": "target/\n" if lock else "target/\nCargo.lock\n",
            "press/press-source.toml": _table("identity", identity)
            + _table("identity.cargo_names", names),
            "press/press-rules.toml": rules,
        },
    )
    if lock:
        _assert_cargo(target, "generate-lockfile", "--offline")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(target, "remote", "add", "origin", f"{REPOSITORY}.git")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")


def _answers(
    base: Path, name: str, fields: dict[str, str], names: dict[str, str]
) -> Path:
    path = base / name
    path.write_text(
        _table("answers", fields) + _table("answers.cargo_names", names),
        encoding="utf-8",
    )
    return path


def _status(target: Path) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def _press(target: Path, answers: Path, *flags: str) -> int:
    return main(["--target", str(target), "--config", str(answers), *flags])


# --- real Cargo as the oracle ----------------------------------------------------


def _require_cargo() -> None:
    if shutil.which("cargo") is not None:
        return
    if os.environ.get("CI"):
        pytest.fail("cargo is required in CI but is not on PATH")
    pytest.skip("cargo is not installed")


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


def _set_origin(target: Path, identity: dict[str, str]) -> None:
    url = f"https://github.com/{identity['owner']}/{identity['repo_name']}.git"
    _git(target, "remote", "set-url", "origin", url)


def _press_and_prove(
    target: Path, answers: Path, identity: dict[str, str], *flags: str
) -> None:
    assert _press(target, answers, *flags) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--locked", "--offline")
    _assert_cargo(target, "test", "--offline")
    _set_origin(target, identity)
    assert verify_command(["--target", str(target)]) == 0


def _assert_absent(target: Path, tokens: tuple[str, ...]) -> None:
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


def _locked_names(target: Path) -> set[str]:
    lock = tomllib.loads((target / "Cargo.lock").read_text(encoding="utf-8"))
    return {entry["name"] for entry in lock["package"]}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("shape", ["single_crate", "workspace"])
def test_split_press_builds_verifies_and_presses_again(
    shape: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    files, names, split = SHAPES[shape]
    _seed(
        target,
        files(),
        names,
        LOCK_RULES + split,
        _identity(shape, ACME),
        lock=True,
    )
    _assert_cargo(target, "test", "--offline")
    zeta = _identity(shape, ZETA)
    first = _answers(tmp_path, "zeta.toml", zeta, DEST_NAMES[shape])

    _press_and_prove(target, first, zeta)

    _assert_absent(target, ("acme", "Acme"))
    assert "zeta-gadget" in _locked_names(target)
    if shape == "single_crate":
        assert (target / "README.md").read_text() == (
            "# zeta-repo\n\nRun `cargo run -p zeta-gadget`, then call "
            "`zeta_gadget::hi()`.\n"
        )
        assert (target / "scripts/release.sh").read_text() == (
            "# ships zetactl\ncargo publish -p zeta-gadget\n"
        )
        assert (
            target / "docs/api.md"
        ).read_text() == "`zeta_gadget::hi` returns hello.\n"
        cli = (target / "tests/cli.rs").read_text()
        assert 'env!("CARGO_BIN_EXE_zeta-gadget")' in cli
        assert "zeta_gadget::hi()" in cli
    else:
        app = tomllib.loads((target / "crates/app/Cargo.toml").read_text())
        assert app["dependencies"] == {"zeta-gadget": {"path": "../zeta-gadget"}}
        assert (target / "crates/zeta-gadget/Cargo.toml").is_file()
        assert "zeta_gadget::hi()" in (target / "crates/app/src/main.rs").read_text()
        assert "cargo test -p zeta-gadget" in (target / "README.md").read_text()
        assert "zeta_gadget::hi()" in (target / "docs/api.md").read_text()
    refreshed = tomllib.loads((target / "press/press-source.toml").read_text())
    assert refreshed["identity"]["cargo_names"] == DEST_NAMES[shape]
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["from"]["cargo_names"] == names
    assert receipt["press"]["to"]["cargo_names"] == DEST_NAMES[shape]
    # The block stays in place; the next press reads it as inert.
    assert "[[cargo_split]]" in (target / "press/press-rules.toml").read_text()
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "first press")
    capsys.readouterr()

    nova = _identity(shape, NOVA)
    second = _answers(tmp_path, "nova.toml", nova, NOVA_NAMES[shape])
    _press_and_prove(target, second, nova, "--force")

    assert "[[cargo_split]] role 'core' is inert" in capsys.readouterr().err
    _assert_absent(target, ("acme", "Acme", "zeta", "Zeta"))
    assert "nova-gadget" in _locked_names(target)
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["from"]["cargo_names"] == DEST_NAMES[shape]
    assert receipt["press"]["to"]["cargo_names"] == NOVA_NAMES[shape]


# --- fast end-to-end checks without Cargo ----------------------------------------


def _fast_target(
    tmp_path: Path,
    files: dict[str, str] | None = None,
    split: str = SINGLE_SPLIT,
    rules_head: str = "",
) -> Path:
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        _single_crate_files() if files is None else files,
        {"core": "acme"},
        rules_head + split,
        ACME,
        lock=False,
    )
    return target


def _zeta(tmp_path: Path) -> Path:
    return _answers(tmp_path, "zeta.toml", ZETA, {"core": "zeta-gadget"})


def test_split_press_rewrites_each_spelling(tmp_path: Path) -> None:
    target = _fast_target(tmp_path)
    assert _press(target, _zeta(tmp_path)) == 0
    assert 'name = "zeta-gadget"' in (target / "Cargo.toml").read_text()
    assert "zeta_gadget::hi()" in (target / "src/main.rs").read_text()
    assert (target / "README.md").read_text() == (
        "# zeta-repo\n\nRun `cargo run -p zeta-gadget`, then call "
        "`zeta_gadget::hi()`.\n"
    )
    assert (target / "docs/api.md").read_text() == "`zeta_gadget::hi` returns hello.\n"
    _set_origin(target, ZETA)
    assert verify_command(["--target", str(target)]) == 0


def test_without_block_the_refusal_names_cargo_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _fast_target(tmp_path, split="")
    assert _press(target, _zeta(tmp_path)) == 2
    assert "[[cargo_split]]" in capsys.readouterr().err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_undeclared_file_is_refused_with_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {**_single_crate_files(), "NOTES.md": "intro\nsee acme here\n"}
    target = _fast_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "NOTES.md:2: 'acme' is in no [[cargo_split]] role 'core' list" in err
    assert "nothing written" in err
    assert _status(target) == ""


def test_longer_rows_consume_their_own_spans_first(tmp_path: Path) -> None:
    # The email row owns acme@example.test, so NOTES.md needs no declaration.
    files = {**_single_crate_files(), "NOTES.md": "mail acme@example.test\n"}
    target = _fast_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 0
    assert (target / "NOTES.md").read_text() == "mail zeta@example.test\n"


def test_mixed_file_without_replace_rule_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    split = (
        '\n[[cargo_split]]\nrole = "core"\n'
        'package_files = ["README.md", "scripts/release.sh"]\n'
        'identifier_files = ["docs/api.md"]\n'
    )
    target = _fast_target(tmp_path, split=split)
    assert _press(target, _zeta(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "README.md:3: 'zeta-gadget' would sit where only a Rust" in err
    assert _status(target) == ""


def test_file_in_both_lists_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    split = (
        '\n[[cargo_split]]\nrole = "core"\npackage_files = ["docs/*"]\n'
        'identifier_files = ["docs/api.md"]\n'
    )
    files = {**_single_crate_files(), "README.md": "# acme-repo\n"}
    files.pop("scripts/release.sh")
    target = _fast_target(tmp_path, files, split=split)
    assert _press(target, _zeta(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "docs/api.md: matches both package_files and identifier_files" in err
    assert _status(target) == ""


def test_explicit_lib_name_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        **_single_crate_files(),
        "Cargo.toml": _package("acme") + '\n[lib]\nname = "acme"\n',
    }
    target = _fast_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 2
    assert "Cargo.toml: [lib] name 'acme'" in capsys.readouterr().err
    assert _status(target) == ""


def test_module_file_rename_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        **_single_crate_files(),
        "src/lib.rs": "pub mod acme;\n" + LIB_RS,
        "src/acme.rs": "pub fn inner() {}\n",
    }
    target = _fast_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 2
    assert "src/acme.rs: renaming it to 'src/zeta-gadget.rs'" in (
        capsys.readouterr().err
    )
    assert _status(target) == ""


def test_binary_file_under_src_bin_may_rename(tmp_path: Path) -> None:
    files = {**_single_crate_files(), "src/bin/acme.rs": "fn main() {}\n"}
    files.pop("src/main.rs")
    target = _fast_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 0
    assert (target / "src/bin/zeta-gadget.rs").is_file()


def test_python_checked_target_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        **_single_crate_files(),
        "pyproject.toml": '[project]\nname = "acme"\nversion = "0.1.0"\n',
        "src/acme/__init__.py": "",
    }
    target = _fast_target(
        tmp_path, files, rules_head='[rules]\nlanguages = ["python", "rust"]\n'
    )
    assert _press(target, _zeta(tmp_path)) == 2
    assert "supports Rust-only targets" in capsys.readouterr().err
    assert _status(target) == ""


def test_hyphenated_source_block_is_refused_before_any_press(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        **_single_crate_files(),
        "Cargo.toml": _package("acme-core"),
        "src/main.rs": 'fn main() {\n    println!("{}", acme_core::hi());\n}\n',
        "README.md": "# acme-repo\n",
        "tests/cli.rs": "#[test]\nfn noop() {}\n",
        "docs/api.md": "`acme_core::hi`\n",
        "scripts/release.sh": "# ships acmectl\ncargo publish -p acme-core\n",
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        files,
        {"core": "acme-core"},
        SINGLE_SPLIT,
        {**ACME, "package_name": "acme_core"},
        lock=False,
    )
    answers = _answers(
        tmp_path,
        "zeta.toml",
        {**ZETA, "package_name": "zeta_core"},
        {"core": "zeta-core"},
    )
    assert _press(target, answers) == 2
    assert "is unnecessary: source name 'acme-core' has a hyphen" in (
        capsys.readouterr().err
    )
    assert _status(target) == ""


# --- fix round 1: text in .rs strings, module paths, identifier contexts ---------

PLAIN_SPLIT = '\n[[cargo_split]]\nrole = "core"\n'
PLAIN_LIB = 'pub fn hi() -> &\'static str {\n    "hello"\n}\n'


def _round_target(
    tmp_path: Path,
    files: dict[str, str],
    *,
    names: dict[str, str] | None = None,
    split: str = PLAIN_SPLIT,
    identity: dict[str, str] = ACME,
    lock: bool = False,
) -> Path:
    target = tmp_path / "target-repo"
    target.mkdir()
    rules = (LOCK_RULES if lock else "") + split
    _seed(target, files, names or {"core": "acme"}, rules, identity, lock=lock)
    return target


def _feature_workspace() -> dict[str, str]:
    return {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\nmembers = ["crates/acme", "crates/app"]\n'
        ),
        "crates/acme/Cargo.toml": _package("acme"),
        "crates/acme/src/lib.rs": PLAIN_LIB,
        "crates/app/Cargo.toml": _package("app")
        + '\n[dependencies]\nacme = { path = "../acme", optional = true }\n\n'
        '[features]\ndefault = ["acme"]\n',
        "crates/app/src/main.rs": (
            'fn main() {\n    #[cfg(feature = "acme")]\n    println!("{}", acme::hi());\n'
            "}\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn feature_on() {\n"
            '        assert!(cfg!(feature = "acme"));\n    }\n}\n'
        ),
        "README.md": "# acme-repo, by acmectl\n",
    }


def _include_crate() -> dict[str, str]:
    return {
        "Cargo.toml": _package("acme"),
        "src/lib.rs": (
            "pub fn hi() -> &'static str {\n"
            '    include_str!("../assets/acme.txt")\n}\n\n'
            "#[cfg(test)]\nmod tests {\n    #[test]\n    fn reads_asset() {\n"
            '        assert_eq!(super::hi(), "hello\\n");\n    }\n}\n'
        ),
        "assets/acme.txt": "hello\n",
        "src/main.rs": 'fn main() {\n    println!("{} acmectl", acme::hi());\n}\n',
    }


def _pkg_name_crate() -> dict[str, str]:
    return {
        "Cargo.toml": _package("acme"),
        "src/lib.rs": PLAIN_LIB
        + '\n#[test]\nfn name() {\n    assert_eq!(env!("CARGO_PKG_NAME"), "acme");\n}\n',
        "README.md": "# acme-repo, by acmectl\n",
    }


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", ["feature_cfg", "include_str", "pkg_name_env"])
def test_split_string_spans_that_are_provable_build(case: str, tmp_path: Path) -> None:
    _require_cargo()
    files, names, identity, dest_names, dest = {
        "feature_cfg": (
            _feature_workspace(),
            {"core": "acme", "app": "app"},
            {**ACME, "package_name": "app"},
            {"core": "zeta-gadget", "app": "app"},
            {**ZETA, "package_name": "app"},
        ),
        "include_str": (
            _include_crate(),
            {"core": "acme"},
            ACME,
            {"core": "zeta-gadget"},
            ZETA,
        ),
        "pkg_name_env": (
            _pkg_name_crate(),
            {"core": "acme"},
            ACME,
            {"core": "zeta-gadget"},
            ZETA,
        ),
    }[case]
    target = _round_target(tmp_path, files, names=names, identity=identity, lock=True)
    _assert_cargo(target, "test", "--offline")
    answers = _answers(tmp_path, "zeta.toml", dest, dest_names)

    _press_and_prove(target, answers, dest)

    _assert_absent(target, ("acme", "Acme"))
    if case == "feature_cfg":
        main_rs = (target / "crates/app/src/main.rs").read_text()
        assert main_rs.count('feature = "zeta-gadget"') == 2
        assert "zeta_gadget::hi()" in main_rs
    elif case == "include_str":
        assert (target / "assets/zeta-gadget.txt").is_file()
        lib = (target / "src/lib.rs").read_text()
        assert 'include_str!("../assets/zeta-gadget.txt")' in lib
    else:
        lib = (target / "src/lib.rs").read_text()
        assert '"zeta-gadget");' in lib


def _refusal(
    tmp_path: Path,
    files: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    split: str = PLAIN_SPLIT,
) -> str:
    target = _round_target(tmp_path, files, split=split)
    assert _press(target, _zeta(tmp_path)) == 2
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()
    return capsys.readouterr().err


def _lib_crate(**extra: str) -> dict[str, str]:
    return {
        "Cargo.toml": _package("acme"),
        "src/lib.rs": PLAIN_LIB,
        "README.md": "# acme-repo, by acmectl\n",
        **extra,
    }


def test_unprovable_rust_string_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _lib_crate(
        **{"src/main.rs": 'fn main() {\n    println!("run acme now");\n}\n'}
    )
    err = _refusal(tmp_path, files, capsys)
    assert "src/main.rs:2:" in err
    assert "Rust string literal" in err


def test_rust_attribute_string_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _lib_crate(**{"src/main.rs": '#[doc(alias = "acme")]\nfn main() {}\n'})
    assert "src/main.rs:1:" in _refusal(tmp_path, files, capsys)


def test_path_string_to_an_unrenamed_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The string names a path no file occupies, so the press cannot prove it.
    files = _lib_crate(
        **{
            "src/main.rs": (
                'fn main() {\n    let _ = include_bytes!("../missing/acme.bin");\n}\n'
            )
        }
    )
    assert "src/main.rs:2:" in _refusal(tmp_path, files, capsys)


def test_tests_module_directory_rename_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _lib_crate(
        **{
            "tests/it.rs": "mod acme;\n",
            "tests/acme/mod.rs": (
                '#[test]\nfn t() {\n    assert_eq!(::acme::hi(), "hello");\n}\n'
            ),
        }
    )
    err = _refusal(tmp_path, files, capsys)
    assert "tests/acme" in err
    assert "mod" in err


def test_test_target_file_may_rename(tmp_path: Path) -> None:
    files = _lib_crate(
        **{
            "tests/acme.rs": '#[test]\nfn t() {\n    assert_eq!(acme::hi(), "hello");\n}\n',
            "examples/acme.rs": 'fn main() {\n    println!("{}", acme::hi());\n}\n',
        }
    )
    target = _round_target(tmp_path, files)
    assert _press(target, _zeta(tmp_path)) == 0
    assert (target / "tests/zeta-gadget.rs").is_file()
    assert (target / "examples/zeta-gadget.rs").is_file()


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("Run `cargo run -p acme`.\n\n```rust\nextern crate acme;\n```\n", 4),
        ("Run `cargo run -p acme`.\n\n```rust\nuse acme as c;\n```\n", 4),
        (
            "Run `cargo run -p acme`.\n\n```rust\n#[macro_use]\nextern crate acme;\n```\n",
            5,
        ),
        ("Debug with `RUST_LOG=acme=debug cargo run -p acme`.\n", 1),
        ("Set the filter to `acme=info`.\n", 1),
        ("Call `acme::hi()` after `cargo add acme`.\n", 1),
    ],
)
def test_identifier_context_in_package_file_is_refused(
    text: str, line: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    split = PLAIN_SPLIT + 'package_files = ["GUIDE.md"]\n'
    err = _refusal(tmp_path, _lib_crate(**{"GUIDE.md": text}), capsys, split)
    assert f"GUIDE.md:{line}:" in err
    assert "identifier_files" in err
    assert "[[replace]]" in err


def test_rust_log_in_package_script_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    split = PLAIN_SPLIT + 'package_files = ["scripts/*.sh"]\n'
    files = _lib_crate(
        **{"scripts/run.sh": "#!/bin/sh\nRUST_LOG=acme=debug cargo run -q\n"}
    )
    assert "scripts/run.sh:2:" in _refusal(tmp_path, files, capsys, split)


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_rust_log_oracle_needs_the_identifier_spelling(tmp_path: Path) -> None:
    """Real env_logger matches the module path, never the package spelling.

    Skips without a cached registry, because env_logger is a registry crate.
    """
    _require_cargo()
    target = tmp_path / "crate"
    _write(
        target,
        {
            "Cargo.toml": (
                '[package]\nname = "zeta-gadget"\nversion = "0.1.0"\n'
                'edition = "2021"\n\n[dependencies]\nlog = "0.4"\n'
                'env_logger = "0.11"\n'
            ),
            "src/main.rs": (
                'fn main() {\n    env_logger::init();\n    log::debug!("VISIBLE");\n}\n'
            ),
        },
    )
    home = Path.home() / ".cargo"
    env = {**os.environ, "CARGO_HOME": str(home)}

    def run(filter_: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["cargo", "run", "-q", "--offline"],  # noqa: S607
            cwd=target,
            env={**env, "RUST_LOG": filter_},
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    first = run("zeta_gadget=debug")
    if first.returncode != 0:
        pytest.skip(f"log and env_logger are not cached offline: {first.stderr[-300:]}")
    assert "VISIBLE" in first.stderr
    assert "VISIBLE" not in run("zeta-gadget=debug").stderr


# --- fix round 2: doc-comment strings, cfg-only features, real comparisons -------

FEATURE_PKG = _package("acme") + '\n[features]\ndefault = ["acme"]\nacme = []\n'
DOC_CASES = {
    "doc_pkgname": (
        '/// ```\n/// assert_eq!(env!("CARGO_PKG_NAME"), "acme");\n/// ```\n',
        '/// assert_eq!(env!("CARGO_PKG_NAME"), "zeta-gadget");',
    ),
    "doc_feature": (
        '/// ```\n/// assert!(cfg!(feature = "acme"));\n/// ```\n',
        '/// assert!(cfg!(feature = "zeta-gadget"));',
    ),
    "doc_inner_reversed": (
        '//! ```\n//! assert_eq!("acme", env!("CARGO_PKG_NAME"));\n//! ```\n',
        '//! assert_eq!("zeta-gadget", env!("CARGO_PKG_NAME"));',
    ),
    "cmp_eq": (
        '#[test]\nfn name() {\n    assert!(env!("CARGO_PKG_NAME") == "acme");\n}\n',
        'assert!(env!("CARGO_PKG_NAME") == "zeta-gadget");',
    ),
}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(DOC_CASES))
def test_doc_and_comparison_strings_build(case: str, tmp_path: Path) -> None:
    _require_cargo()
    lead, written = DOC_CASES[case]
    files = {
        "Cargo.toml": FEATURE_PKG,
        "src/lib.rs": lead + PLAIN_LIB,
        "README.md": "# acme-repo, by acmectl\n",
    }
    target = _round_target(tmp_path, files, lock=True)
    _assert_cargo(target, "test", "--offline")

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    assert written in (target / "src/lib.rs").read_text()
    _assert_absent(target, ("acme", "Acme"))


@pytest.mark.parametrize(
    ("lib", "line"),
    [
        # N2: a feature-shaped assignment outside cfg is an ordinary string.
        ('#[test]\nfn t() {\n    let feature = "acme";\n    let _ = feature;\n}\n', 3),
        # N3: the literal is not the other side of the CARGO_PKG_NAME comparison.
        (
            '#[test]\nfn t() {\n    let _n = env!("CARGO_PKG_NAME"); '
            'assert_eq!(module_path!(), "acme");\n}\n',
            3,
        ),
        # N1: a doc comment's string with no provable spelling is refused.
        ('/// ```\n/// assert_eq!(module_path!(), "acme");\n/// ```\n', 2),
        ('/** ```\n let s = "acme";\n``` */\npub fn x() {}\n', 2),
    ],
)
def test_round_two_unprovable_strings_are_refused(
    lib: str, line: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _lib_crate(**{"src/lib.rs": lib + PLAIN_LIB})
    files["Cargo.toml"] = FEATURE_PKG
    err = _refusal(tmp_path, files, capsys)
    assert f"src/lib.rs:{line}:" in err
    assert "Rust string literal" in err


# --- fix round 3: only compiled doctest fences take the string rules -----------

DOC_PRESS_CASES = {
    # Prose outside a fence is not compiled: it keeps the identifier spelling.
    "prose_quote": (
        '/// The "acme" crate says hello.\n',
        '/// The "zeta_gadget" crate says hello.',
    ),
    # Fences that rustdoc does not compile are prose too.
    "text_fence": (
        '/// ```text\n/// say "acme"\n/// ```\n',
        '/// say "zeta_gadget"',
    ),
    "ignore_fence": (
        '/// ```ignore\n/// let s = "acme";\n/// ```\n',
        '/// let s = "zeta_gadget";',
    ),
    # A compiled block read across its doc lines, with a provable string.
    "block_star_feature": (
        '/**\n * ```\n * assert!(cfg!(feature = "acme"));\n * ```\n */\n',
        ' * assert!(cfg!(feature = "zeta-gadget"));',
    ),
}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(DOC_PRESS_CASES))
def test_doc_fences_follow_rustdoc(case: str, tmp_path: Path) -> None:
    _require_cargo()
    lead, written = DOC_PRESS_CASES[case]
    files = {
        "Cargo.toml": FEATURE_PKG,
        "src/lib.rs": lead + PLAIN_LIB,
        "README.md": "# acme-repo, by acmectl\n",
    }
    target = _round_target(tmp_path, files, lock=True)
    _assert_cargo(target, "test", "--offline")

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    assert written in (target / "src/lib.rs").read_text()


@pytest.mark.parametrize(
    ("lib", "line"),
    [
        # R1: a doctest string spanning two doc lines is lexed as one string.
        (
            '/// ```\n/// let s = "acme\n/// tail";\n'
            '/// assert!(s.starts_with(env!("CARGO_PKG_NAME")));\n/// ```\n',
            2,
        ),
        # A string still open when the doc comment ends is refused.
        ('/// ```\n/// let s = "acme\n', 2),
        # Tagged fences that rustdoc compiles.
        ('/// ```rust,no_run\n/// println!("acme");\n/// ```\n', 2),
        ('/// ```should_panic\n/// panic!("acme");\n/// ```\n', 2),
        ('//! ```compile_fail\n//! let x: i32 = "acme";\n//! ```\n', 2),
    ],
)
def test_compiled_doc_fence_strings_are_refused(
    lib: str, line: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _lib_crate(**{"src/lib.rs": lib + PLAIN_LIB})
    files["Cargo.toml"] = FEATURE_PKG
    err = _refusal(tmp_path, files, capsys)
    assert f"src/lib.rs:{line}:" in err
    assert "Rust string literal" in err


# --- fix round 4: doc text is code unless rustdoc provably skips it ---------------

# One line of doctest code. Cargo proves the first; nothing proves the second.
PKG_ASSERT = 'assert_eq!(env!("CARGO_PKG_NAME"), "acme");'
PKG_PRESSED = 'assert_eq!(env!("CARGO_PKG_NAME"), "zeta-gadget");'
UNPROVEN = 'let name = "acme"; assert_eq!(name, env!("CARGO_PKG_NAME"));'
UNPROVEN_AS_PROSE = (
    'let name = "zeta_gadget"; assert_eq!(name, env!("CARGO_PKG_NAME"));'
)

# Each snippet is one documented item. CODE is the doctest line and ITEM is the
# item's name. S1: rustdoc compiles every one of these, whatever it looks like.
S1_LAYOUTS = {
    "indented_block": "/// Example:\n///\n///     CODE\npub fn ITEM() {}\n",
    "tag_rust_ignore_target": "/// ```rust,ignore-x\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_ignore_target": "/// ```ignore-x\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_class_attribute": "/// ```{.rust}\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_rust_then_unknown": "/// ```rust,foo\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "split_by_doc_attribute": (
        '/// ```\n#[doc = "let _x = 1;"]\n/// CODE\n/// ```\npub fn ITEM() {}\n'
    ),
    "split_by_plain_comment": (
        "/// ```\n// plain comment\n/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
    "fence_indented_four": "///     ```\n///     CODE\n///     ```\npub fn ITEM() {}\n",
}
# More doc text that rustdoc compiles. Several hide the code block behind text
# that looks like a `text` fence or like prose.
COMPILED_LAYOUTS = {
    **S1_LAYOUTS,
    "tag_text_then_rust": "/// ```text,rust\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_class_text": "/// ```{.text}\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_ignore_and_ignore_target": (
        "/// ```ignore,ignore-x\n/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
    "tag_edition": "/// ```edition2021\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tilde_fence": "/// ~~~\n/// CODE\n/// ~~~\npub fn ITEM() {}\n",
    "hidden_line": "/// ```\n/// # CODE\n/// ```\npub fn ITEM() {}\n",
    "list_item_block": "/// -     CODE\npub fn ITEM() {}\n",
    "quote_block": "/// >     CODE\npub fn ITEM() {}\n",
    # After a task marker, four spaces are enough to indent a code block.
    "task_item_block": "/// - [ ]     CODE\npub fn ITEM() {}\n",
    "task_item_block_four_spaces": "/// - [x]    CODE\npub fn ITEM() {}\n",
    "block_after_heading": "/// # Example\n///     CODE\npub fn ITEM() {}\n",
    "block_after_odd_quote_prose": (
        '/// A 5" disk.\n///\n///     CODE\npub fn ITEM() {}\n'
    ),
    "multi_line_assert": (
        '/// ```\n/// assert_eq!(\n///     env!("CARGO_PKG_NAME"),\n'
        '///     "acme",\n/// );\n/// CODE\n/// ```\npub fn ITEM() {}\n'
    ),
    "inner_doc_fence": "pub mod ITEM {\n    //! ```\n    //! CODE\n    //! ```\n}\n",
    # Plain `doc` attributes supply the fence line, as crates do per feature.
    "fence_from_doc_attributes": (
        '#[cfg_attr(all(), doc = "```")]\n#[cfg_attr(any(), doc = "```ignore")]\n'
        "/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
    "block_doc_indented": "/**\n * Example:\n *\n *     CODE\n */\npub fn ITEM() {}\n",
    # An HTML block swallows the `text` fence line, so the block below is code.
    "html_block_hides_text_fence": (
        "/// <div>\n/// ```text\n///\n///     CODE\n///\n/// <div>\n/// ```\n"
        "pub fn ITEM() {}\n"
    ),
    # The list item ends at `para`, and its `text` fence ends with it.
    "list_item_ends_text_fence": (
        "/// - item\n///   ```text\n///   inside\n/// para\n///\n///     CODE\n"
        "///\n/// ```text\n/// ```\npub fn ITEM() {}\n"
    ),
    # The outer comment's fence stays open, so the inner comment is code.
    "inner_doc_continues_outer_fence": (
        "/// ```\n/// let _x = 1;\npub mod ITEM {\n    //! CODE\n    //! ```\n}\n"
    ),
    # `//!x` lowers the common indent, so the indented fence does not close.
    "inner_doc_changes_outer_indent": (
        "/// ```\n/// /*\n///    ```\n/// ```text\n/// */ CODE\n/// ```\n"
        "pub mod ITEM {\n//!x\n}\n"
    ),
}
# Doc text that rustdoc provably never compiles: prose and non-Rust fences in
# a `///` comment. CODE keeps the identifier spelling, as prose does.
SKIPPED_LAYOUTS = {
    "prose": "/// CODE\npub fn ITEM() {}\n",
    "prose_three_spaces": "///   CODE\npub fn ITEM() {}\n",
    "prose_in_list_item": "/// - CODE\npub fn ITEM() {}\n",
    "prose_after_code_fence": (
        "/// ```\n/// let _x = 1;\n/// ```\n/// CODE\npub fn ITEM() {}\n"
    ),
    "text_fence": "/// ```text\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "ignore_fence": "/// ```ignore\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "ignore_rust_fence": "/// ```ignore,rust\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "two_language_fence": "/// ```text,toml\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tilde_text_fence": "/// ~~~text\n/// ```\n/// CODE\n/// ~~~\npub fn ITEM() {}\n",
    "long_text_fence": (
        "/// ````text\n/// ```\n/// CODE\n/// ```\n/// ````\npub fn ITEM() {}\n"
    ),
    "text_fence_after_derive": (
        "#[derive(Debug)]\n/// ```text\n/// CODE\n/// ```\npub struct ITEM;\n"
    ),
    "text_fence_split_by_plain_comment": (
        "/// ```text\n// plain comment\n/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
}
# Doc text the press cannot prove rustdoc skips. An unproven string is refused.
UNPROVABLE_LAYOUTS = {
    **COMPILED_LAYOUTS,
    # rustdoc skips these today, but the tag is a misspelt Rust tag or unknown.
    "tag_should_dash_panic": "/// ```should-panic\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_capital_rust": "/// ```Rust\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_unknown_language": "/// ```klingon\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_text_no_run": "/// ```text,no_run\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    "tag_with_punctuation": "/// ```c++\n/// CODE\n/// ```\npub fn ITEM() {}\n",
    # Another doc fragment of the same item may precede these comments.
    "inner_doc_prose": "pub mod ITEM {\n    //! CODE\n}\n",
    "inner_doc_text_fence": (
        "pub mod ITEM {\n    //! ```text\n    //! CODE\n    //! ```\n}\n"
    ),
    "block_doc_prose": "/** CODE */\npub fn ITEM() {}\n",
    # Read after `include_str!` text: no reading that starts inside a string
    # or a comment of that text can end in code here.
    "inner_doc_around_included_doc": (
        '//! Intro.\n#![doc = include_str!("../README.md")]\n//! CODE\n'
    ),
    "inner_doc_after_included_doc": (
        '#[doc = include_str!("../README.md")]\npub mod ITEM {\n    //! CODE\n}\n'
    ),
    # The crate's `#![doc = ...]` does not come before a later item's docs, so
    # this comment is read, and refused only for its unproven string.
    "inner_doc_of_item_after_crate_doc_attribute": (
        '#![doc = include_str!("../README.md")]\npub mod ITEM {\n    //! CODE\n}\n'
    ),
    "prose_after_doc_attribute": '#[doc = "Intro."]\n/// CODE\npub fn ITEM() {}\n',
    "prose_before_doc_attribute": '/// CODE\n#[doc = "Outro."]\npub fn ITEM() {}\n',
    "prose_after_macro_attribute": (
        "macro_rules! ITEM {\n    ($(#[$m:meta])*) => {\n        $(#[$m])*\n"
        "        /// CODE\n        pub fn made() {}\n    };\n}\n"
    ),
    # The layout leaves the Markdown structure in doubt.
    "prose_four_spaces": "///     CODE\npub fn ITEM() {}\n",
    "prose_after_tab": "///\tCODE\npub fn ITEM() {}\n",
    "text_fence_after_html": (
        "/// <div>\n///\n/// ```text\n/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
    "text_fence_not_flush": (
        "///intro\n///  ```text\n///  CODE\n///  ```\npub fn ITEM() {}\n"
    ),
    "text_fence_in_list_item": (
        "/// - item\n///   ```text\n///   CODE\n///   ```\npub fn ITEM() {}\n"
    ),
    "text_fence_after_doubtful_closer": (
        "/// ```text\n///    ```\n/// CODE\n/// ```\npub fn ITEM() {}\n"
    ),
}


# `///` comments below a doc attribute the press cannot read. A string from that
# text may never close in sight, so even a name in code position is refused.
UNREAD_LAYOUTS = {
    "after_included_doc": (
        '#[doc = include_str!("../README.md")]\n/// CODE\npub fn ITEM() {}\n'
    ),
    "after_doc_attribute_that_opens_a_string": (
        '/// ```\n#[doc = "let s = \\""]\n/// "; CODE\n/// ```\npub fn ITEM() {}\n'
    ),
    "after_concat_doc_attribute": (
        '/// ```\n#[doc = concat!("let s = ", "\\"")]\n/// "; CODE\n/// ```\n'
        "pub fn ITEM() {}\n"
    ),
}


# An inner doc comment after doc text the press cannot read. The comment ends
# the text, so only the lexer state at its first line is unknown: the press
# also reads it as the rest of a string or comment that the earlier text opened.
OPEN_START_LAYOUTS = {
    "outer_doc_opens_a_string": (
        '/// ```\n/// let s = "\npub mod ITEM {\n    //! "; CODE\n    //! ```\n}\n'
    ),
    "outer_doc_opens_a_comment": (
        "/// ```\n/// /*\npub mod ITEM {\n    //! ```text\n    //! */ CODE\n"
        "    //! ```\n}\n"
    ),
}


def _doc_lib(layout: str, code: str, name: str = "documented") -> str:
    return layout.replace("ITEM", name).replace("CODE", code)


def _code_line(layout: str) -> int:
    return layout.split("CODE")[0].count("\n") + 1


def _press_lib(tmp_path: Path, lib: str) -> tuple[int, str]:
    tmp_path.mkdir(exist_ok=True)
    target = _round_target(tmp_path, _lib_crate(**{"src/lib.rs": lib + PLAIN_LIB}))
    code = _press(target, _zeta(tmp_path))
    assert (code == 0) == (target / RECEIPT_REL).exists()
    if code:
        assert _status(target) == ""
    return code, (target / "src/lib.rs").read_text()


@pytest.mark.parametrize("case", sorted(COMPILED_LAYOUTS))
def test_doc_text_rustdoc_compiles_takes_the_string_rules(
    case: str, tmp_path: Path
) -> None:
    code, lib = _press_lib(tmp_path, _doc_lib(COMPILED_LAYOUTS[case], PKG_ASSERT))
    assert code == 0
    assert PKG_PRESSED in lib
    assert '"zeta_gadget"' not in lib


@pytest.mark.parametrize("case", sorted(UNPROVABLE_LAYOUTS))
def test_doc_text_rustdoc_may_compile_refuses_unproven_strings(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = UNPROVABLE_LAYOUTS[case]
    code, _ = _press_lib(tmp_path, _doc_lib(layout, UNPROVEN))
    err = capsys.readouterr().err
    assert code == 2
    assert f"src/lib.rs:{_code_line(layout)}: 'acme' is in a doc comment" in err
    assert "Rust string literal" in err
    assert "in backticks, without double quotes, takes 'zeta_gadget'" in err


@pytest.mark.parametrize("case", sorted(UNREAD_LAYOUTS))
@pytest.mark.parametrize("code", [PKG_ASSERT, "acme::hi();"])
def test_doc_text_after_unreadable_doc_text_is_refused(
    case: str, code: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = UNREAD_LAYOUTS[case]
    exit_code, _ = _press_lib(tmp_path, _doc_lib(layout, code))
    err = capsys.readouterr().err
    assert exit_code == 2
    assert (
        f"src/lib.rs:{_code_line(layout)}: 'acme' is in a doc comment that "
        "follows a `#[doc = ...]` attribute the press cannot read"
    ) in err


@pytest.mark.parametrize("case", sorted(OPEN_START_LAYOUTS))
def test_inner_doc_after_an_open_outer_doc_is_read_from_that_state(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = OPEN_START_LAYOUTS[case]
    # Code that follows the closing quote or `*/` is code in every reading.
    code, lib = _press_lib(tmp_path / "plain", _doc_lib(layout, "acme::hi();"))
    assert code == 0
    assert "zeta_gadget::hi();" in lib
    # A string there has no provable role: its block began in the outer comment.
    code, _ = _press_lib(tmp_path / "string", _doc_lib(layout, PKG_ASSERT))
    assert code == 2
    assert f"src/lib.rs:{_code_line(layout)}: 'acme' is in a doc comment" in (
        capsys.readouterr().err
    )


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(OPEN_START_LAYOUTS))
def test_inner_doc_after_an_open_outer_doc_passes_real_cargo(
    case: str, tmp_path: Path
) -> None:
    _require_cargo()
    target = _doc_crate(tmp_path, _doc_lib(OPEN_START_LAYOUTS[case], "acme::hi();"))
    assert "1 passed; 0 failed" in _cargo(target, "test", "--doc", "--offline").stdout

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    assert "zeta_gadget::hi();" in (target / "src/lib.rs").read_text()


def test_module_doc_cut_inside_a_string_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # rustdoc joins `src/m.rs`'s inner doc comment to the outer one here, so
    # the string that opens on line 2 closes in the other file.
    files = _lib_crate(
        **{
            "src/lib.rs": '/// ```\n/// let s = "\npub mod m;\n' + PLAIN_LIB,
            "src/m.rs": f'//! "; {PKG_ASSERT}\n//! ```\n',
        }
    )
    err = _refusal(tmp_path, files, capsys)
    assert "src/lib.rs:3: the doc comment above this `mod` declaration ends" in err


@pytest.mark.parametrize("case", sorted(SKIPPED_LAYOUTS))
def test_doc_text_rustdoc_never_compiles_reads_as_prose(
    case: str, tmp_path: Path
) -> None:
    code, lib = _press_lib(tmp_path, _doc_lib(SKIPPED_LAYOUTS[case], UNPROVEN))
    assert code == 0
    assert UNPROVEN_AS_PROSE in lib


def test_every_non_rust_fence_tag_reads_as_prose(tmp_path: Path) -> None:
    from template_press.rebrand.rust_text import NOT_RUST_TAGS

    lib = "".join(
        _doc_lib(SKIPPED_LAYOUTS["text_fence"].replace("text", tag), UNPROVEN, f"f{n}")
        for n, tag in enumerate(sorted(NOT_RUST_TAGS))
    )
    code, pressed = _press_lib(tmp_path, lib)
    assert code == 0
    assert pressed.count(UNPROVEN_AS_PROSE) == len(NOT_RUST_TAGS)


def test_inner_doc_readings_that_disagree_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A code block may start at line 1 or at line 3. Read from line 1, the
    # quote on line 1 closes on line 3, so the two readings disagree there.
    lib = f'//! He said "hi\n//!\n//!     {PKG_ASSERT} // "\n'
    code, _ = _press_lib(tmp_path, lib)
    assert code == 2
    assert "src/lib.rs:3:" in capsys.readouterr().err


def test_inner_doc_reading_that_never_closes_its_string_does_not_bind(
    tmp_path: Path,
) -> None:
    # Read from line 1, the quote on line 1 is still open when the comment
    # ends. A doctest that ends inside a string does not compile, so only the
    # block that starts at line 3 counts.
    code, lib = _press_lib(tmp_path, f'//! He said "hi\n//!\n//!     {PKG_ASSERT}\n')
    assert code == 0
    assert PKG_PRESSED in lib


def _doc_crate(tmp_path: Path, lib: str) -> Path:
    files = {
        "Cargo.toml": _package("acme"),
        "src/lib.rs": lib + PLAIN_LIB,
        "README.md": "# acme-repo, by acmectl\n",
    }
    target = _round_target(tmp_path, files, lock=True)
    _assert_cargo(target, "test", "--offline")
    return target


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(S1_LAYOUTS))
def test_s1_doctests_pass_real_cargo_after_the_press(case: str, tmp_path: Path) -> None:
    _require_cargo()
    target = _doc_crate(tmp_path, _doc_lib(S1_LAYOUTS[case], PKG_ASSERT))

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    assert PKG_PRESSED in (target / "src/lib.rs").read_text()
    _assert_absent(target, ("acme", "Acme"))


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_compiled_doc_layouts_pass_real_cargo_after_the_press(tmp_path: Path) -> None:
    """Real ``cargo test`` runs every layout's doctest, before and after."""
    _require_cargo()
    lib = "".join(
        _doc_lib(layout, PKG_ASSERT, f"item_{case}")
        for case, layout in sorted(COMPILED_LAYOUTS.items())
    )
    target = _doc_crate(tmp_path, lib)
    listed = _cargo(target, "test", "--doc", "--offline").stdout
    counted = re.search(r"(\d+) passed; 0 failed; (\d+) ignored", listed)
    assert counted is not None, listed
    passed, ignored = int(counted[1]), int(counted[2])
    # `ignore-x` skips a doctest on a host whose target triple holds an `x`.
    host_skipped = sum("ignore-x" in layout for layout in COMPILED_LAYOUTS.values())
    assert passed + ignored == len(COMPILED_LAYOUTS)
    assert ignored in (0, host_skipped)

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    pressed = (target / "src/lib.rs").read_text()
    assert pressed.count(PKG_PRESSED) == len(COMPILED_LAYOUTS)
    _assert_absent(target, ("acme", "Acme"))


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_skipped_doc_layouts_are_never_compiled_by_real_cargo(tmp_path: Path) -> None:
    """The oracle for every exemption: prose, and each non-Rust fence tag.

    The press writes the identifier spelling into each block. That text would
    fail as a doctest, so ``cargo test`` passes only if rustdoc compiles none.
    """
    _require_cargo()
    from template_press.rebrand.rust_text import NOT_RUST_TAGS

    layouts = {
        **SKIPPED_LAYOUTS,
        **{
            f"tag_{tag}": SKIPPED_LAYOUTS["text_fence"].replace("text", tag)
            for tag in NOT_RUST_TAGS
        },
    }
    lib = "".join(
        _doc_lib(layout, UNPROVEN, f"item_{case}".replace("-", "_"))
        for case, layout in sorted(layouts.items())
    )
    target = _doc_crate(tmp_path, lib)

    _press_and_prove(target, _zeta(tmp_path), ZETA)

    pressed = (target / "src/lib.rs").read_text()
    assert pressed.count(UNPROVEN_AS_PROSE) == len(layouts)
    after = _cargo(target, "test", "--doc", "--offline").stdout
    # The one test that runs is the Rust fence in `prose_after_code_fence`, which
    # holds no name. The two `ignore` fences are listed and never compiled.
    assert "test result: ok. 1 passed; 0 failed; 2 ignored" in after


# --- identity and rules units ----------------------------------------------------


def _ident(names: dict[str, str], **values: str) -> Identity:
    return Identity.from_mapping({**ACME, **values}, names)


def test_hyphen_free_source_gets_one_unscoped_pair() -> None:
    source = _ident({"core": "acme"})
    dest = Identity.from_mapping(ZETA, {"core": "zeta-gadget"})
    assert cargo_name_pairs(source, dest) == [
        ("cargo_exact_core", "acme", "zeta-gadget")
    ]


def test_split_roles_need_a_hyphen_free_source_and_hyphenated_destination() -> None:
    source = _ident({"core": "acme", "app": "acme-app"})
    dest = Identity.from_mapping(ZETA, {"core": "zeta-gadget", "app": "zeta-app"})
    assert cargo_split_roles(source, dest, ["core", "app", "ghost"]) == {"core"}


def test_identity_problem_allows_only_split_roles() -> None:
    source = _ident({"core": "acme"})
    dest = Identity.from_mapping(ZETA, {"core": "zeta-gadget"})
    problem = cargo_identity_problem(source, dest)
    assert problem is not None
    assert '[[cargo_split]] role = "core"' in problem
    assert cargo_identity_problem(source, dest, split_roles={"core"}) is None


@pytest.mark.parametrize(
    ("names", "dest_names", "pressed", "problem", "warning"),
    [
        ({"core": "acme"}, {"core": "zeta-gadget"}, False, None, None),
        ({"core": "acme"}, {"core": "zeta"}, False, "destination 'zeta' has no", None),
        ({"core": "acme-x"}, {"core": "zeta-x"}, False, "source name 'acme-x'", None),
        ({"core": "acme-x"}, {"core": "zeta-x"}, True, None, "is inert"),
        ({"app": "acme"}, {"app": "zeta-gadget"}, False, "is not a cargo_names", None),
    ],
)
def test_split_problems(names, dest_names, pressed, problem, warning) -> None:
    source = _ident(names, package_name=next(iter(names.values())).replace("-", "_"))
    dest = Identity.from_mapping(ZETA, dest_names)
    problems, warnings = cargo_split_problems(source, dest, ["core"], pressed=pressed)
    assert [p for p in problems if problem and problem in p] == (
        problems if problem else []
    )
    assert bool(problems) == bool(problem)
    assert bool(warnings) == bool(warning)
    if warning:
        assert warning in warnings[0]


def _rules(tmp_path: Path, text: str):
    (tmp_path / "press").mkdir(exist_ok=True)
    (tmp_path / "press" / "press-rules.toml").write_text(text, encoding="utf-8")
    return load_rules(tmp_path)


def test_rules_parse_cargo_split(tmp_path: Path) -> None:
    rules = _rules(tmp_path, SINGLE_SPLIT)
    assert rules.cargo_split == (
        CargoSplit("core", ("README.md", "scripts/release.sh"), ("docs/api.md",)),
    )
    assert _rules(tmp_path, '[[cargo_split]]\nrole = "core"\n').cargo_split == (
        CargoSplit("core"),
    )


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ('role = "core"\nfiles = ["a"]\n', "unknown key(s): files"),
        ("package_files = []\n", "role must be a cargo_names role string"),
        ('role = "Core"\n', "cargo_names role must be"),
        ('role = "core"\npackage_files = "README.md"\n', "must be a list"),
        ('role = "core"\nidentifier_files = [1]\n', "must be a list"),
        ('role = "core"\npackage_files = [""]\n', "must be a list"),
        (
            'role = "core"\npackage_files = ["a.md"]\nidentifier_files = ["a.md"]\n',
            "in both package_files and identifier_files",
        ),
    ],
)
def test_rules_refuse_bad_cargo_split(tmp_path: Path, block: str, message: str) -> None:
    with pytest.raises(ValidationError, match=r".*") as caught:
        _rules(tmp_path, f"[[cargo_split]]\n{block}")
    assert message in str(caught.value)


def test_rules_refuse_duplicate_role(tmp_path: Path) -> None:
    block = '[[cargo_split]]\nrole = "core"\n'
    with pytest.raises(ValidationError, match="declared twice"):
        _rules(tmp_path, block + block)


def test_rules_refuse_non_table_cargo_split(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="array of tables"):
        _rules(tmp_path, 'cargo_split = ["core"]\n')


def test_rust_strings_skip_comments_lifetimes_and_chars() -> None:
    from template_press.rebrand.rust_text import rust_strings

    text = (
        '// "acme" in a comment\n/* "x" /* nested */ */\n'
        "fn f<'a>(c: char) -> &'a str { let _ = 'q'; r#\"raw \"acme\"\"# }\n"
        'const B: &[u8] = b"acme";\n'
    )
    contents = [text[s.content_start : s.content_end] for s in rust_strings(text)]
    assert contents == ['raw "acme"', "acme"]
