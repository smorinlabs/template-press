"""Paths a Rust press must keep with their files, and paths it must not judge.

R38: a content-only row (``owner``, ``author``, ``email``) that rewrites a path
Rust source declares (``mod name;``, ``#[path]``, ``include_*!``) without
renaming the file is refused before any write. R39: a table-less path
dependency reached through a tracked symlinked directory presses as on base.

The slow tests use real Cargo as the oracle:
uv run pytest -m "" tests/rebrand/test_cargo_source_paths.py
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.substitutions import RenamePlan, RenameStep

from .conftest import _git, posix_only
from .test_cargo_split import (
    ACME,
    ZETA,
    _assert_cargo,
    _cargo,
    _package,
    _press,
    _require_cargo,
    _status,
    _table,
    _write,
)

CORE_SOURCE = {**ACME, "package_name": "acme_core"}
CORE_DEST = {**ZETA, "package_name": "zeta_core"}
CORE_NAMES = {"core": "acme-core"}
LIB = 'pub fn hi() -> &\'static str {\n    "hello"\n}\n'


def _seed(
    target: Path,
    files: dict[str, str],
    *,
    identity: dict[str, str] = CORE_SOURCE,
    names: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
) -> None:
    table = "" if names is None else _table("identity.cargo_names", names)
    _write(
        target,
        {
            ".gitignore": "target/\nCargo.lock\n",
            "press/press-source.toml": _table("identity", identity) + table,
            **files,
        },
    )
    for link, points_at in (links or {}).items():
        os.symlink(points_at, target / link)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    origin = f"https://github.com/{identity['owner']}/{identity['repo_name']}.git"
    _git(target, "remote", "add", "origin", origin)
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")


def _answers(
    tmp_path: Path, fields: dict[str, str], names: dict[str, str] | None
) -> Path:
    path = tmp_path / "answers.toml"
    table = "" if names is None else _table("answers.cargo_names", names)
    path.write_text(_table("answers", fields) + table, encoding="utf-8")
    return path


# --- R39 (I6): a symlinked path-dependency directory -----------------------------


def _symlinked_dependency(target: Path) -> None:
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core").replace("acme-repo", "acme-core")
            + '\n[dependencies]\nhelper = { path = "vendor/helper" }\n',
            "src/lib.rs": "pub fn hi() -> u8 { helper::one() }\n",
            "third_party/helper/Cargo.toml": (
                '[package]\nname = "helper"\nversion = "0.1.0"\nedition = "2021"\n'
            ),
            "third_party/helper/src/lib.rs": "pub fn one() -> u8 { 1 }\n",
            "NOTES.txt": "ships acmectl\n",
        },
        identity={**CORE_SOURCE, "repo_name": "acme-core"},
        links={"vendor": "third_party"},
    )


def test_symlinked_path_dependency_presses_without_a_table(tmp_path: Path) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _symlinked_dependency(target)
    answers = _answers(tmp_path, {**CORE_DEST, "repo_name": "zeta-core"}, None)

    assert _press(target, answers) == 0

    assert (target / RECEIPT_REL).is_file()
    assert 'name = "zeta-core"' in (target / "Cargo.toml").read_text()
    assert (target / "vendor").is_symlink()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_symlinked_path_dependency_still_builds(tmp_path: Path) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _symlinked_dependency(target)
    _assert_cargo(target, "check", "--offline")
    answers = _answers(tmp_path, {**CORE_DEST, "repo_name": "zeta-core"}, None)

    assert _press(target, answers) == 0

    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--offline")


def _symlinked_dependency_with_lib_path(target: Path) -> None:
    """N3: the symlink points into the tracked tree, and the press rewrites the
    dependency's manifest through its real path."""
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core").replace("acme-repo", "acme-core")
            + '\n[dependencies]\nhelper = { path = "vendor/helper" }\n',
            "src/lib.rs": "pub fn hi() -> u8 { helper::one() }\n",
            "third_party/helper/Cargo.toml": (
                '[package]\nname = "helper"\nversion = "0.1.0"\nedition = "2021"\n'
                '[lib]\npath = "src/acmelabs.rs"\n'
            ),
            "third_party/helper/src/acmelabs.rs": "pub fn one() -> u8 { 1 }\n",
            "NOTES.txt": "ships acmectl\n",
        },
        identity={**CORE_SOURCE, "repo_name": "acme-core"},
        links={"vendor": "third_party"},
    )


def test_symlinked_path_dependency_manifest_is_still_cross_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _symlinked_dependency_with_lib_path(target)
    answers = _answers(tmp_path, {**CORE_DEST, "repo_name": "zeta-core"}, None)

    assert _press(target, answers) == 2

    out = capsys.readouterr()
    assert "cargo paths: third_party/helper/Cargo.toml: [lib] path" in (
        out.out + out.err
    )
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_symlinked_path_dependency_refusal_matches_real_cargo(tmp_path: Path) -> None:
    """Real Cargo: base and the I6 skip wrote a receipt here, then ``cargo
    check`` failed on ``vendor/helper/src/zetalabs.rs``."""
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _symlinked_dependency_with_lib_path(target)
    _assert_cargo(target, "check", "--offline")
    answers = _answers(tmp_path, {**CORE_DEST, "repo_name": "zeta-core"}, None)

    assert _press(target, answers) == 2

    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    _assert_cargo(target, "check", "--offline")


# --- R38 (I5): content-only rows inside paths Rust source declares ---------------

SOURCE_PATH_CASES = {
    "mod_owner": (
        {
            "src/lib.rs": LIB + "pub mod acmelabs;\n",
            "src/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:4:",
    ),
    "include_owner": (
        {
            "src/lib.rs": LIB
            + 'pub const T: &str = include_str!("../data/acmelabs.txt");\n',
            "data/acmelabs.txt": "x\n",
        },
        "src/lib.rs:4:",
    ),
    "path_attr_owner": (
        {
            "src/lib.rs": LIB + '#[path = "acmelabs/x.rs"]\npub mod x;\n',
            "src/acmelabs/x.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:4:",
    ),
    # F1: rustfmt removes the space, but rustc accepts ``include_str ! (...)``.
    "include_spaced_bang_owner": (
        {
            "src/lib.rs": LIB
            + 'pub const T: &str = include_str ! ("../data/acmelabs.txt");\n',
            "data/acmelabs.txt": "x\n",
        },
        "src/lib.rs:4:",
    ),
    "include_bytes_owner": (
        {
            "src/lib.rs": LIB
            + 'pub const B: &[u8] = include_bytes!("acmelabs.bin");\n',
            "src/acmelabs.bin": "x\n",
        },
        "src/lib.rs:4:",
    ),
    "nested_mod_owner": (
        {
            "src/lib.rs": LIB + "pub mod outer;\n",
            "src/outer.rs": "pub mod acmelabs;\n",
            "src/outer/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/outer.rs:1:",
    ),
    # N4: the platform-module form of ``#[path]``.
    "cfg_attr_path_owner": (
        {
            "src/lib.rs": LIB
            + '#[cfg_attr(all(), path = "acmelabs_imp.rs")]\npub mod imp;\n',
            "src/acmelabs_imp.rs": "pub fn f() {}\n",
        },
        "src/lib.rs:4:",
    ),
    # N4 guards: a false ``cfg_attr`` condition leaves the name-based file.
    "cfg_attr_fallback_file_owner": (
        {
            "src/lib.rs": LIB
            + '#[cfg_attr(any(), path = "other.rs")]\npub mod acmelabs;\n',
            "src/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:5:",
    ),
    "cfg_attr_fallback_reached_owner": (
        {
            "src/lib.rs": LIB + '#[cfg_attr(any(), path = "other.rs")]\npub mod imp;\n',
            "src/imp.rs": "pub mod acmelabs;\n",
            "src/imp/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/imp.rs:1:",
    ),
    # N2 guards: files Cargo compiles are still checked.
    "test_dir_main_mod_owner": (
        {
            "src/lib.rs": LIB,
            "tests/it/main.rs": "mod acmelabs;\n",
            "tests/it/acmelabs.rs": "#[test]\nfn t() {}\n",
        },
        "tests/it/main.rs:1:",
    ),
    "declared_lib_path_mod_owner": (
        {
            "Cargo.toml": _package("acme-core") + '\n[lib]\npath = "code/root.rs"\n',
            "code/root.rs": "pub mod acmelabs;\n",
            "code/acmelabs.rs": "pub fn org() {}\n",
        },
        "code/root.rs:1:",
    ),
    "path_attr_reached_mod_owner": (
        {
            "src/lib.rs": LIB + '#[path = "gen/x.rs"]\npub mod x;\n',
            "src/gen/x.rs": "pub mod acmelabs;\n",
            "src/gen/x/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/gen/x.rs:1:",
    ),
}


def _source_path_target(tmp_path: Path, files: dict[str, str], *, table: bool) -> Path:
    target = tmp_path / "target-repo"
    target.mkdir()
    if table:
        _seed(target, {"Cargo.toml": _package("acme-core"), **files}, names=CORE_NAMES)
        return target
    # Without a table, the repo_name row is the one that rewrites the crate name.
    files = {
        "Cargo.toml": _package("acme-core"),
        **files,
    }
    files["Cargo.toml"] = files["Cargo.toml"].replace("acme-repo", "acme-core")
    _seed(
        target,
        files,
        identity={**CORE_SOURCE, "repo_name": "acme-core"},
    )
    return target


def _source_path_answers(tmp_path: Path, *, table: bool) -> Path:
    if table:
        return _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    return _answers(tmp_path, {**CORE_DEST, "repo_name": "zeta-core"}, None)


@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("case", sorted(SOURCE_PATH_CASES))
def test_content_row_inside_a_rust_source_path_is_refused(
    case: str, table: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files, where = SOURCE_PATH_CASES[case]
    target = _source_path_target(tmp_path, files, table=table)
    answers = _source_path_answers(tmp_path, table=table)

    assert _press(target, answers) == 2

    out = capsys.readouterr()
    assert f"cargo paths: {where}" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_content_row_in_a_workspace_member_module_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """N2 guard: a member crate's module tree is compiled, so it is checked."""
    files = {
        "Cargo.toml": '[workspace]\nmembers = ["crates/helper"]\n\n'
        + _package("acme-core"),
        "src/lib.rs": LIB,
        "crates/helper/Cargo.toml": (
            '[package]\nname = "helper"\nversion = "0.1.0"\nedition = "2021"\n'
        ),
        "crates/helper/src/lib.rs": "pub mod acmelabs;\n",
        "crates/helper/src/acmelabs.rs": "pub fn org() {}\n",
    }
    target = _source_path_target(tmp_path, files, table=False)

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2

    out = capsys.readouterr()
    assert "cargo paths: crates/helper/src/lib.rs:1:" in out.out + out.err
    assert _status(target) == ""


FOLLOWING_PATHS = {
    # The module file renames with the declaration: the crate name does both.
    "renamed_with_its_file": {
        "src/lib.rs": LIB + "pub mod acme_core;\n",
        "src/acme_core.rs": "",
    },
    "renamed_mod_rs": {
        "src/lib.rs": LIB + "pub mod acme_core;\n",
        "src/acme_core/mod.rs": "",
    },
    "renamed_below_a_module_file": {
        "src/lib.rs": LIB + "pub mod outer;\n",
        "src/outer.rs": "pub mod acme_core;\n",
        "src/outer/acme_core.rs": "",
    },
    "renamed_beside_a_root_file": {
        "src/lib.rs": LIB,
        "build.rs": "mod acme_core;\nfn main() {}\n",
        "acme_core.rs": "",
    },
    "renamed_include_path": {
        "src/lib.rs": LIB + 'pub const T: &str = include_str!("acme_core.txt");\n',
        "src/acme_core.txt": "x\n",
    },
    # An inline module has no file.
    "inline_module": {
        "src/lib.rs": LIB + "pub mod acmelabs {\n    pub fn org() {}\n}\n"
    },
    # N1: a module file below an enclosing inline module.
    "inline_nested_mod": {
        "src/lib.rs": LIB + "pub mod outer {\n    pub mod acme_core;\n}\n",
        "src/outer/acme_core.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # N1: brace-like character literals do not move the inline module.
    "inline_nested_mod_after_char_braces": {
        "src/lib.rs": LIB
        + "pub const OPEN: char = '{';\npub const CLOSE: u8 = b'}';\n"
        + "pub mod outer {\n    pub mod inner {\n        pub mod acme_core;\n    }\n}\n",
        "src/outer/inner/acme_core.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # N1: below a non-root file, the inline module sits under the file's stem.
    "inline_nested_mod_below_a_module_file": {
        "src/lib.rs": LIB + "pub mod outer;\n",
        "src/outer.rs": "pub mod inner {\n    pub mod acme_core;\n}\n",
        "src/outer/inner/acme_core.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # N2: Cargo never compiles a fixture below tests/, so its mod is not judged.
    "fixture_rs_owner": {
        "src/lib.rs": LIB,
        "tests/fixtures/sample.rs": "mod acmelabs;\n",
    },
    # N4: a renamed module whose only file is its cfg_attr path.
    "cfg_attr_renamed_module": {
        "src/lib.rs": LIB
        + '#[cfg_attr(all(), path = "imp/acme_core.rs")]\npub mod acme_core;\n',
        "src/imp/acme_core.rs": "pub fn f() {}\n",
    },
    # N4: a path attribute nested deeper than cfg_attr's own arguments is not
    # the module's path.
    "cfg_attr_nested_path_argument": {
        "src/lib.rs": LIB
        + "macro_rules! keep { ($($t:tt)*) => {}; }\n"
        + 'keep!(#[cfg_attr(all(), other(path = "acmelabs.rs"))] mod imp;);\n',
    },
    # A path no row changes.
    "unchanged_path": {
        "src/lib.rs": LIB + 'pub const T: &str = include_str!("t.txt");\n',
        "src/t.txt": "x\n",
    },
}


@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("case", sorted(FOLLOWING_PATHS))
def test_rust_source_paths_that_follow_their_files_press(
    case: str, table: bool, tmp_path: Path
) -> None:
    target = _source_path_target(tmp_path, FOLLOWING_PATHS[case], table=table)

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 0


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize(
    "case",
    [
        "renamed_beside_a_root_file",
        "renamed_below_a_module_file",
        "inline_nested_mod",
        "fixture_rs_owner",
    ],
)
def test_rust_source_paths_that_follow_their_files_build(
    case: str, tmp_path: Path
) -> None:
    _require_cargo()
    target = _source_path_target(tmp_path, FOLLOWING_PATHS[case], table=True)
    _assert_cargo(target, "test", "--offline")

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 0

    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "test", "--offline")


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize(
    "case",
    [
        "mod_owner",
        "include_owner",
        "include_spaced_bang_owner",
        "path_attr_owner",
        "cfg_attr_path_owner",
    ],
)
def test_rust_source_path_refusal_matches_real_cargo(case: str, tmp_path: Path) -> None:
    """Real Cargo: the crate builds before, and the press refuses the rewrite
    that the reviewer's probe showed breaks the build (``0/0/yes/101``)."""
    _require_cargo()
    files, _ = SOURCE_PATH_CASES[case]
    target = _source_path_target(tmp_path, files, table=True)
    _assert_cargo(target, "test", "--offline")
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    assert _cargo(target, "test", "--offline").returncode == 0


# --- F7: an ``auto*`` flag that turns off target discovery ----------------------

FIXTURE_INCLUDE = 'include_str!("../data/acmelabs.txt")'
AUTO_OFF_UNUSED = {
    "autotests": {"tests/fixture.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n"},
    "autoexamples": {
        "examples/fixture.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n"
    },
    "autobenches": {"benches/fixture.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n"},
    "autobins": {
        "src/bin/fixture.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n"
    },
}


def _auto_off_files(flag: str, extra: str = "") -> dict[str, str]:
    return {
        "Cargo.toml": _package("acme-core") + f"{flag} = false\n" + extra,
        "src/lib.rs": LIB,
        "data/acmelabs.txt": "x\n",
        **AUTO_OFF_UNUSED[flag],
    }


@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("flag", sorted(AUTO_OFF_UNUSED))
def test_target_file_cargo_does_not_discover_is_not_judged(
    flag: str, table: bool, tmp_path: Path
) -> None:
    """Base presses these targets healthy: Cargo never builds the file."""
    target = _source_path_target(tmp_path, _auto_off_files(flag), table=table)

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 0

    assert (target / RECEIPT_REL).is_file()


NAMED_UNDER_AUTO_OFF = {
    "file": ("tests/fixture.rs", FIXTURE_INCLUDE),
    "directory": ("tests/fixture/main.rs", FIXTURE_INCLUDE.replace("../", "../../")),
}


@pytest.mark.parametrize("shape", sorted(NAMED_UNDER_AUTO_OFF))
def test_named_target_without_a_path_is_judged_under_auto_off(
    shape: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cargo still infers the file of a ``[[test]]`` that names no path."""
    rel, include = NAMED_UNDER_AUTO_OFF[shape]
    files = {
        "Cargo.toml": _package("acme-core")
        + 'autotests = false\n\n[[test]]\nname = "fixture"\n',
        "src/lib.rs": LIB,
        "data/acmelabs.txt": "x\n",
        rel: f"pub const D: &str = {include};\n#[test]\nfn t() {{}}\n",
    }
    target = _source_path_target(tmp_path, files, table=True)

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2

    out = capsys.readouterr()
    assert f"cargo paths: {rel}:1:" in out.out + out.err
    assert _status(target) == ""


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("flag", ["autotests", "autoexamples"])
def test_target_file_cargo_does_not_discover_presses_and_builds(
    flag: str, table: bool, tmp_path: Path
) -> None:
    """Real Cargo: the tableless form is the one base ``10b4f9b`` presses."""
    _require_cargo()
    target = _source_path_target(tmp_path, _auto_off_files(flag), table=table)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 0

    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "test", "--offline", "--all-targets")


# --- F2: the legacy underscore dependency tables ----------------------------------

HELPER_MANIFEST = '[package]\nname = "helper"\nversion = "0.1.0"\nedition = "2021"\n'


def _legacy_dependency_files(section: str) -> dict[str, str]:
    files = {
        "Cargo.toml": _package("acme-core")
        + f'\n[{section}]\nhelper = {{ path = "acmelabs-helper" }}\n',
        "src/lib.rs": "pub fn hi() -> u8 { 1 }\n",
        "acmelabs-helper/Cargo.toml": HELPER_MANIFEST,
        "acmelabs-helper/src/lib.rs": "pub fn one() -> u8 { 1 }\n",
    }
    if section.startswith("build"):
        files["build.rs"] = "fn main() { let _ = helper::one(); }\n"
    else:
        files["tests/t.rs"] = "#[test]\nfn t() { assert_eq!(helper::one(), 1); }\n"
    return files


LEGACY_SECTIONS = ["dev_dependencies", "build_dependencies", "dev-dependencies"]


@pytest.mark.parametrize("section", LEGACY_SECTIONS)
def test_owner_row_in_a_legacy_dependency_table_path_is_refused(
    section: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cargo before edition 2024 reads ``[dev_dependencies]`` and
    ``[build_dependencies]`` like their hyphenated spellings."""
    target = _source_path_target(
        tmp_path, _legacy_dependency_files(section), table=True
    )

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2

    out = capsys.readouterr()
    assert "dependency 'helper' path" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("section", ["dev_dependencies", "build_dependencies"])
def test_legacy_dependency_table_refusal_matches_real_cargo(
    section: str, tmp_path: Path
) -> None:
    """Real Cargo: the old receipt left ``helper`` at a path that no longer
    existed, and ``cargo test`` failed."""
    _require_cargo()
    target = _source_path_target(
        tmp_path, _legacy_dependency_files(section), table=True
    )
    _assert_cargo(target, "test", "--offline")

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2

    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    _assert_cargo(target, "test", "--offline")


# --- M4: a binary token in a file the press does not rewrite ---------------------


def test_binary_token_in_an_excluded_file_names_the_exclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "src/lib.rs": "pub fn hi() -> u8 { 1 }\n",
        "src/bin/acme-core.rs": "fn main() {}\n",
        "third_party/x/t.rs": 'const B: &str = env!("CARGO_BIN_EXE_acme-core");\n',
        "press/press-rules.toml": '[rules]\nextra_exclude_dirs = ["third_party"]\n',
    }
    target = _source_path_target(tmp_path, files, table=True)

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2

    out = capsys.readouterr()
    message = out.out + out.err
    assert "third_party/x/t.rs: CARGO_BIN_EXE_acme-core tokens" in message
    assert "excluded from rewriting; remove the exclusion" in message
    assert "Declare a cargo_names table" not in message
    assert _status(target) == ""


# --- P15-T13: inferred/auto target renames leaving two candidate files -----------

CLI_NAMES = {"core": "acme-core", "cli": "acme-cli"}
CLI_DEST_NAMES = {"core": "zeta-core", "cli": "zeta-cli"}
MAIN_RS = "fn main() {}\n"
TEST_RS = "#[test]\nfn t() {}\n"

TWO_CANDIDATE_EXPLICIT_CASES: dict[
    str,
    tuple[dict[str, str], dict[str, str], dict[str, str], tuple[str, str]],
] = {
    "bin_file_onto_dir": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
            "src/lib.rs": LIB,
            "src/bin/acme-cli.rs": MAIN_RS,
            "src/bin/zeta-cli/main.rs": MAIN_RS,
        },
        CLI_NAMES,
        CLI_DEST_NAMES,
        ("src/bin/zeta-cli.rs", "src/bin/zeta-cli/main.rs"),
    ),
    "bin_dir_onto_file": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
            "src/lib.rs": LIB,
            "src/bin/acme-cli/main.rs": MAIN_RS,
            "src/bin/zeta-cli.rs": MAIN_RS,
        },
        CLI_NAMES,
        CLI_DEST_NAMES,
        ("src/bin/zeta-cli.rs", "src/bin/zeta-cli/main.rs"),
    ),
    "bin_main_onto_dir": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "src/main.rs": MAIN_RS,
            "src/bin/zeta-core/main.rs": MAIN_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("src/main.rs", "src/bin/zeta-core/main.rs"),
    ),
    "bin_main_onto_file": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "src/main.rs": MAIN_RS,
            "src/bin/zeta-core.rs": MAIN_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("src/main.rs", "src/bin/zeta-core.rs"),
    ),
    "test_auto_off": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autotests = false\n\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
            "tests/zeta-core/main.rs": TEST_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("tests/zeta-core.rs", "tests/zeta-core/main.rs"),
    ),
    "example_auto_off": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autoexamples = false\n\n[[example]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "examples/acme-core.rs": MAIN_RS,
            "examples/zeta-core/main.rs": MAIN_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("examples/zeta-core.rs", "examples/zeta-core/main.rs"),
    ),
    "bench_auto_off": (
        {
            "Cargo.toml": _package("acme-core")
            + 'autobenches = false\n\n[[bench]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "benches/acme-core.rs": MAIN_RS,
            "benches/zeta-core/main.rs": MAIN_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("benches/zeta-core.rs", "benches/zeta-core/main.rs"),
    ),
    "test_auto_on_explicit": (
        {
            "Cargo.toml": _package("acme-core") + '\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
            "tests/zeta-core/main.rs": TEST_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
        ("tests/zeta-core.rs", "tests/zeta-core/main.rs"),
    ),
}


@pytest.mark.parametrize("case", TWO_CANDIDATE_EXPLICIT_CASES)
def test_inferred_target_two_candidate_collision_is_refused(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files, src_names, dst_names, expected_paths = TWO_CANDIDATE_EXPLICIT_CASES[case]
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=src_names)
    answers = _answers(tmp_path, CORE_DEST, dst_names)

    assert _press(target, answers) == 2

    out = capsys.readouterr()
    message = out.out + out.err
    assert "cargo paths:" in message
    for path in expected_paths:
        assert path in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


AUTO_DISCOVERED_COLLISION_CASES: dict[str, tuple[str, str, bool, tuple[str, str]]] = {
    "tests_file_onto_dir": (
        "tests/acme-core.rs",
        "tests/zeta-core/main.rs",
        True,
        ("tests/zeta-core.rs", "tests/zeta-core/main.rs"),
    ),
    "tests_dir_onto_file": (
        "tests/acme-core/main.rs",
        "tests/zeta-core.rs",
        True,
        ("tests/zeta-core.rs", "tests/zeta-core/main.rs"),
    ),
    "examples_file_onto_dir": (
        "examples/acme-core.rs",
        "examples/zeta-core/main.rs",
        True,
        ("examples/zeta-core.rs", "examples/zeta-core/main.rs"),
    ),
    "examples_dir_onto_file": (
        "examples/acme-core/main.rs",
        "examples/zeta-core.rs",
        True,
        ("examples/zeta-core.rs", "examples/zeta-core/main.rs"),
    ),
    "benches_file_onto_dir": (
        "benches/acme-core.rs",
        "benches/zeta-core/main.rs",
        True,
        ("benches/zeta-core.rs", "benches/zeta-core/main.rs"),
    ),
    "benches_dir_onto_file": (
        "benches/acme-core/main.rs",
        "benches/zeta-core.rs",
        True,
        ("benches/zeta-core.rs", "benches/zeta-core/main.rs"),
    ),
    "bin_tableless_file_onto_dir": (
        "src/bin/acme-core.rs",
        "src/bin/zeta-core/main.rs",
        False,
        ("src/bin/zeta-core.rs", "src/bin/zeta-core/main.rs"),
    ),
    "bin_tableless_dir_onto_file": (
        "src/bin/acme-core/main.rs",
        "src/bin/zeta-core.rs",
        False,
        ("src/bin/zeta-core.rs", "src/bin/zeta-core/main.rs"),
    ),
    "bin_tableless_main_onto_file": (
        "src/main.rs",
        "src/bin/zeta-core.rs",
        False,
        ("src/main.rs", "src/bin/zeta-core.rs"),
    ),
}


@pytest.mark.parametrize("case", AUTO_DISCOVERED_COLLISION_CASES)
def test_auto_discovered_two_candidate_collision_is_refused(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, table, expected_paths = AUTO_DISCOVERED_COLLISION_CASES[case]
    body = TEST_RS if first.startswith("tests/") else MAIN_RS
    files = {"src/lib.rs": LIB, first: body, second: body}
    target = _source_path_target(tmp_path, files, table=table)

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 2

    out = capsys.readouterr()
    message = out.out + out.err
    assert "cargo paths:" in message
    for path in expected_paths:
        assert path in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_inferred_target_collision_in_renamed_workspace_member_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n',
            "crates/acme-core/Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
            "crates/acme-core/src/lib.rs": LIB,
            "crates/acme-core/src/bin/acme-cli.rs": MAIN_RS,
            "crates/acme-core/src/bin/zeta-cli/main.rs": MAIN_RS,
        },
        names=CLI_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)

    assert _press(target, answers) == 2

    out = capsys.readouterr()
    message = out.out + out.err
    assert "crates/acme-core/Cargo.toml:" in message
    assert "crates/zeta-core/src/bin/zeta-cli.rs" in message
    assert "crates/zeta-core/src/bin/zeta-cli/main.rs" in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize(
    ("files", "src_names", "dst_names"),
    [
        pytest.param(
            {
                "Cargo.toml": _package("acme-core")
                + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
                "src/lib.rs": LIB,
                "src/bin/acme-cli.rs": MAIN_RS,
                "src/bin/zeta-cli/main.rs": MAIN_RS,
                "press/press-rules.toml": (
                    '[[remove]]\nfile = "src/bin/zeta-cli/main.rs"\n'
                    'reason = "drop unused binary stub"\n'
                ),
            },
            CLI_NAMES,
            CLI_DEST_NAMES,
            id="removed_orphan_file",
        ),
        pytest.param(
            {
                "Cargo.toml": _package("acme-core")
                + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
                "src/lib.rs": LIB,
                "src/bin/acme-cli.rs": MAIN_RS,
                "src/bin/zeta-cli/main.rs": MAIN_RS,
                "press/press-rules.toml": (
                    '[[remove]]\ndir = "src/bin/zeta-cli"\n'
                    'reason = "drop unused binary directory"\n'
                ),
            },
            CLI_NAMES,
            CLI_DEST_NAMES,
            id="removed_orphan_dir",
        ),
        pytest.param(
            {
                "Cargo.toml": _package("acme-core") + "autotests = false\n",
                "src/lib.rs": LIB,
                "tests/acme-core.rs": TEST_RS,
                "tests/zeta-core/main.rs": TEST_RS,
            },
            CORE_NAMES,
            {"core": "zeta-core"},
            id="unlisted_under_auto_off",
        ),
        pytest.param(
            {
                "Cargo.toml": _package("acme-core")
                + '\n[[test]]\nname = "other"\npath = "tests/zeta-core/main.rs"\n',
                "src/lib.rs": LIB,
                "tests/acme-core.rs": TEST_RS,
                "tests/zeta-core/main.rs": TEST_RS,
            },
            CORE_NAMES,
            {"core": "zeta-core"},
            id="claimed_other_shape_under_auto_on",
        ),
    ],
)
def test_inferred_target_collision_respects_remove_auto_off_and_claimed(
    files: dict[str, str],
    src_names: dict[str, str],
    dst_names: dict[str, str],
    tmp_path: Path,
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=src_names)
    answers = _answers(tmp_path, CORE_DEST, dst_names)

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


def test_inferred_target_gitignored_orphan_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            ".gitignore": "target/\nCargo.lock\nsrc/bin/zeta-cli/\n",
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
            "src/lib.rs": LIB,
            "src/bin/acme-cli.rs": MAIN_RS,
        },
        names=CLI_NAMES,
    )
    orphan = target / "src" / "bin" / "zeta-cli" / "main.rs"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(MAIN_RS, encoding="utf-8")
    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)

    assert _press(target, answers) == 2

    out = capsys.readouterr()
    message = out.out + out.err
    assert "src/bin/zeta-cli.rs" in message
    assert "src/bin/zeta-cli/main.rs" in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_inferred_target_collision_ignores_orphan_moved_away_by_rename_plan(
    tmp_path: Path,
) -> None:
    from template_press.rebrand.substitutions import _inferred_target_collisions

    target = tmp_path / "target-repo"
    _write(
        target,
        {
            "src/bin/acme-cli.rs": MAIN_RS,
            "src/bin/zeta-cli/main.rs": MAIN_RS,
        },
    )
    before = tomllib.loads(
        _package("acme-core") + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n'
    )
    after = tomllib.loads(
        _package("zeta-core") + 'autobins = false\n\n[[bin]]\nname = "zeta-cli"\n'
    )
    plan = RenamePlan(
        steps=(
            RenameStep(
                step_id="move-orphan",
                old_prefix="src/bin/zeta-cli",
                new_prefix="src/bin/other-cli",
                pass_number=1,
                row_ids=("r1",),
                source_entries=("src/bin/zeta-cli/main.rs",),
                expected_kind="directory",
            ),
            RenameStep(
                step_id="move-bin",
                old_prefix="src/bin/acme-cli.rs",
                new_prefix="src/bin/zeta-cli.rs",
                pass_number=1,
                row_ids=("r2",),
                source_entries=("src/bin/acme-cli.rs",),
                expected_kind="file",
            ),
        )
    )
    post_files = {
        "Cargo.toml": frozenset({"Cargo.toml"}),
        "src/bin/other-cli/main.rs": frozenset({"src/bin/zeta-cli/main.rs"}),
        "src/bin/zeta-cli.rs": frozenset({"src/bin/acme-cli.rs"}),
    }
    snapshot_paths = frozenset(
        {"Cargo.toml", "src/bin/acme-cli.rs", "src/bin/zeta-cli/main.rs"}
    )

    assert (
        _inferred_target_collisions(
            target,
            "Cargo.toml",
            before,
            after,
            plan,
            post_files,
            snapshot_paths,
            frozenset(),
            (),
        )
        == []
    )


SLOW_TWO_CANDIDATE_CASES: dict[
    str, tuple[dict[str, str], dict[str, str], dict[str, str]]
] = {
    "bin_autobins_false": TWO_CANDIDATE_EXPLICIT_CASES["bin_file_onto_dir"][:3],
    "bin_main_autobins_false": TWO_CANDIDATE_EXPLICIT_CASES["bin_main_onto_dir"][:3],
    "test_autotests_false": TWO_CANDIDATE_EXPLICIT_CASES["test_auto_off"][:3],
    "example_autoexamples_false": TWO_CANDIDATE_EXPLICIT_CASES["example_auto_off"][:3],
    "bench_autobenches_false": TWO_CANDIDATE_EXPLICIT_CASES["bench_auto_off"][:3],
    "test_auto_on_unlisted": (
        {
            "Cargo.toml": _package("acme-core"),
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
            "tests/zeta-core/main.rs": TEST_RS,
        },
        CORE_NAMES,
        {"core": "zeta-core"},
    ),
}


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", SLOW_TWO_CANDIDATE_CASES)
def test_inferred_target_two_candidate_refusal_matches_real_cargo(
    case: str, tmp_path: Path
) -> None:
    _require_cargo()
    files, src_names, dst_names = SLOW_TWO_CANDIDATE_CASES[case]
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=src_names)
    _assert_cargo(target, "check", "--offline", "--all-targets")
    answers = _answers(tmp_path, CORE_DEST, dst_names)

    assert _press(target, answers) == 2

    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    assert _cargo(target, "check", "--offline", "--all-targets").returncode == 0


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_inferred_target_collision_cleared_by_remove_builds_with_real_cargo(
    tmp_path: Path,
) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core")
            + 'autobins = false\n\n[[bin]]\nname = "acme-cli"\n',
            "src/lib.rs": LIB,
            "src/bin/acme-cli.rs": MAIN_RS,
            "src/bin/zeta-cli/main.rs": MAIN_RS,
            "press/press-rules.toml": (
                '[[remove]]\nfile = "src/bin/zeta-cli/main.rs"\n'
                'reason = "drop unused binary stub"\n'
            ),
        },
        names=CLI_NAMES,
    )
    _assert_cargo(target, "check", "--offline", "--all-targets")
    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "check", "--offline", "--all-targets")
