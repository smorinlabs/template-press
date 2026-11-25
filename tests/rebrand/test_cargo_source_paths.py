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
from pathlib import Path

import pytest

from template_press.rebrand.receipt import RECEIPT_REL

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
            # A #[path] file is a mod.rs-like owner: its child sits beside it.
            "src/gen/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/gen/x.rs:1:",
    ),
    # Q1: #[path] inside an inline module split by a content-only row.
    "inline_path_attr_owner": (
        {
            "src/lib.rs": LIB
            + 'pub mod outer {\n    #[path = "acmelabs.rs"]\n    pub mod details;\n}\n',
            "src/outer/acmelabs.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:5:",
    ),
    # Q1 guard: an unrelated file at src/ does not satisfy #[path] inside mod outer.
    "inline_path_attr_wrong_dir_not_fooled": (
        {
            "src/lib.rs": LIB
            + 'pub mod outer {\n    #[path = "acme-core.rs"]\n    pub mod details;\n}\n',
            "src/acme-core.rs": "pub fn stray() {}\n",
        },
        "src/lib.rs:5:",
    ),
    # P15-T11 F1a: #[path] inside an inline module is reached by the compiled walk.
    "inline_path_attr_reached_include_owner": (
        {
            "src/lib.rs": LIB
            + 'pub mod outer {\n    #[path = "x.rs"]\n    pub mod x;\n}\n',
            "src/outer/x.rs": (
                'pub const T: &str = include_str!("../../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/outer/x.rs:1:",
    ),
    # P15-T11 F1b: #[path] on an inline module is followed by the compiled walk.
    "path_attr_on_inline_reached_include_owner": (
        {
            "src/lib.rs": LIB
            + '#[path = "p"]\npub mod outer {\n    pub mod inner;\n}\n',
            "src/p/inner.rs": (
                'pub const T: &str = include_str!("../../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/p/inner.rs:1:",
    ),
    # P15-T11 F1: #[cfg_attr(..., path = ...)] on an inline module is followed too.
    "cfg_attr_path_on_inline_reached_include_owner": (
        {
            "src/lib.rs": LIB
            + '#[cfg_attr(all(), path = "p")]\npub mod outer {\n    pub mod inner;\n}\n',
            "src/p/inner.rs": (
                'pub const T: &str = include_str!("../../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/p/inner.rs:1:",
    ),
    # P15-T11 F2: a renamed inline module around an unchanged child module.
    "renamed_inline_mod_unchanged_child_owner": (
        {
            "src/lib.rs": LIB + "pub mod acmelabs {\n    pub mod x;\n}\n",
            "src/acmelabs/x.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:5:",
    ),
    # P15-T11 F2: a renamed inline module around an unchanged #[path] child.
    "renamed_inline_mod_unchanged_path_attr_owner": (
        {
            "src/lib.rs": LIB
            + 'pub mod acmelabs {\n    #[path = "x.rs"]\n    pub mod y;\n}\n',
            "src/acmelabs/x.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:5:",
    ),
    # P15-T11 F3: #[path = "dir"] on an inline module split from its directory.
    "path_attr_on_inline_dir_owner": (
        {
            "src/lib.rs": LIB
            + '#[path = "acmelabs"]\npub mod outer {\n    pub mod inner;\n}\n',
            "src/acmelabs/inner.rs": "pub fn org() {}\n",
        },
        "src/lib.rs:4:",
    ),
    # P15-T11 Unicode: a Unicode inline module is tracked by the compiled walk.
    "unicode_inline_mod_reached_include_owner": (
        {
            "src/lib.rs": LIB + "pub mod café {\n    pub mod inner;\n}\n",
            "src/café/inner.rs": (
                'pub const T: &str = include_str!("../../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/café/inner.rs:1:",
    ),
    # Cycle 3 F2 control: a virtual workspace's member crate is still walked.
    "virtual_workspace_member_include_owner": (
        {
            "Cargo.toml": (
                '[workspace]\nmembers = ["crates/acme-core"]\nresolver = "2"\n'
            ),
            "crates/acme-core/Cargo.toml": _package("acme-core"),
            "crates/acme-core/src/lib.rs": LIB
            + 'pub const T: &str = include_str!("../../../data/acmelabs.txt");\n',
            "data/acmelabs.txt": "x\n",
        },
        "crates/acme-core/src/lib.rs:4:",
    ),
    # Cycle 3 F3 control: include! pastes Rust, so the walk follows it.
    "include_rs_reached_include_owner": (
        {
            "src/lib.rs": LIB + 'include!("frag.rs");\n',
            "src/frag.rs": (
                'pub const T: &str = include_str!("../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/frag.rs:1:",
    ),
    # Cycle 3 F7: a #[path] module file is Rust whatever its suffix.
    "path_attr_non_rs_bridge_owner": (
        {
            "src/lib.rs": LIB + '#[path = "bridge.inc"]\npub mod bridge;\n',
            "src/bridge.inc": '#[path = "leaf.rs"]\npub mod leaf;\n',
            "src/leaf.rs": (
                'pub const T: &str = include_str!("../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/leaf.rs:1:",
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
    # Q1: #[path] inside an inline module resolves against the inline directory.
    "inline_path_attr_renamed": {
        "src/lib.rs": LIB
        + 'pub mod outer {\n    #[path = "acme-core.rs"]\n    pub mod details;\n}\n',
        "src/outer/acme-core.rs": "pub fn d() -> u8 { 1 }\n",
    },
    "inline_path_attr_renamed_below_module_file": {
        "src/lib.rs": LIB + "pub mod top;\n",
        "src/top.rs": (
            'pub mod outer {\n    #[path = "acme-core.rs"]\n    pub mod details;\n}\n'
        ),
        "src/top/outer/acme-core.rs": "pub fn d() -> u8 { 1 }\n",
    },
    "inline_cfg_attr_path_renamed": {
        "src/lib.rs": LIB
        + 'pub mod outer {\n    #[cfg_attr(all(), path = "acme-core.rs")]\n'
        + "    pub mod details;\n}\n",
        "src/outer/acme-core.rs": "pub fn d() -> u8 { 1 }\n",
    },
    # P15-T11 F3: #[path] on an inline module with a renamed child or directory.
    "path_attr_on_inline_mod_renamed_child": {
        "src/lib.rs": LIB
        + '#[path = "p"]\npub mod outer {\n    pub mod acme_core;\n}\n',
        "src/p/acme_core.rs": "pub fn f() -> u8 { 1 }\n",
    },
    "path_attr_on_inline_mod_with_inline_path_attr_renamed": {
        "src/lib.rs": LIB
        + '#[path = "p"]\npub mod outer {\n    #[path = "acme-core.rs"]\n'
        + "    pub mod details;\n}\n",
        "src/p/acme-core.rs": "pub fn d() -> u8 { 1 }\n",
    },
    "path_attr_on_inline_mod_renamed_dir": {
        "src/lib.rs": LIB
        + '#[path = "acme_core"]\npub mod outer {\n    pub mod inner;\n}\n',
        "src/acme_core/inner.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # P15-T11 F2 healthy counterpart: renamed inline module moves with its directory.
    "renamed_inline_mod_with_its_dir": {
        "src/lib.rs": LIB + "pub mod acme_core {\n    pub mod inner;\n}\n",
        "src/acme_core/inner.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # P15-T11 F2+F3 guard: unconditional #[path] keeps the child's directory unchanged.
    "path_attr_on_renamed_inline_mod_keeps_child": {
        "src/lib.rs": LIB
        + '#[path = "p"]\npub mod acmelabs {\n    pub mod inner;\n}\n',
        "src/p/inner.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # P15-T11 Unicode: Unicode inline module around a renamed child.
    "unicode_inline_mod_renamed_child": {
        "src/lib.rs": LIB + "pub mod café {\n    pub mod acme_core;\n}\n",
        "src/café/acme_core.rs": "pub fn f() -> u8 { 1 }\n",
    },
    # Regression guard: include_str! inside an inline module still uses the file's dir.
    "inline_include_str_still_uses_file_dir": {
        "src/lib.rs": LIB
        + 'pub mod outer {\n    pub const T: &str = include_str!("acme_core.txt");\n}\n',
        "src/acme_core.txt": "x\n",
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
        "inline_path_attr_renamed",
        "inline_path_attr_renamed_below_module_file",
        "path_attr_on_inline_mod_renamed_child",
        "path_attr_on_inline_mod_renamed_dir",
        "path_attr_on_renamed_inline_mod_keeps_child",
        "renamed_inline_mod_with_its_dir",
        "unicode_inline_mod_renamed_child",
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
        "inline_path_attr_renamed",
        "path_attr_on_inline_mod_renamed_child",
    ],
)
def test_inline_path_attr_tableless_presses_and_builds(
    case: str, tmp_path: Path
) -> None:
    """Real Cargo: tableless Rust targets press and build as on base."""
    _require_cargo()
    target = _source_path_target(tmp_path, FOLLOWING_PATHS[case], table=False)
    _assert_cargo(target, "test", "--offline")

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 0

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
        "inline_path_attr_owner",
        "inline_path_attr_reached_include_owner",
        "path_attr_on_inline_reached_include_owner",
        "renamed_inline_mod_unchanged_child_owner",
        "renamed_inline_mod_unchanged_path_attr_owner",
        "unicode_inline_mod_reached_include_owner",
        "path_attr_reached_mod_owner",
        "include_rs_reached_include_owner",
        "path_attr_non_rs_bridge_owner",
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


# --- Cycle 2 F1: include macros written with ``[...]`` or ``{...}`` --------------

BRACKETED_INCLUDES = {
    "include_str_brackets": (
        {
            "src/lib.rs": LIB
            + 'pub const T: &str = include_str!["../data/acmelabs.txt"];\n',
            "data/acmelabs.txt": "x\n",
        },
        "src/lib.rs:4:",
    ),
    "include_str_braces": (
        {
            "src/lib.rs": LIB
            + 'pub const T: &str = include_str!{"../data/acmelabs.txt"};\n',
            "data/acmelabs.txt": "x\n",
        },
        "src/lib.rs:4:",
    ),
    "include_bytes_brackets": (
        {
            "src/lib.rs": LIB
            + 'pub const B: &[u8] = include_bytes!["../data/acmelabs.txt"];\n',
            "data/acmelabs.txt": "x\n",
        },
        "src/lib.rs:4:",
    ),
    # The compiled-file walk must follow a bracketed include! into its file.
    "include_rs_brackets": (
        {
            "src/lib.rs": LIB + 'include!["acmelabs_inc.rs"];\n',
            "src/acmelabs_inc.rs": (
                'pub const E: &str = include_str!("../data/acmelabs.txt");\n'
            ),
            "data/acmelabs.txt": "x\n",
        },
        "src/acmelabs_inc.rs:1:",
    ),
}


@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("case", sorted(BRACKETED_INCLUDES))
def test_bracketed_and_braced_include_paths_are_checked(
    case: str, table: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rust accepts every macro delimiter, so each include form names a path."""
    files, where = BRACKETED_INCLUDES[case]
    target = _source_path_target(tmp_path, files, table=table)

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 2

    out = capsys.readouterr()
    assert f"cargo paths: {where} the Rust path '../data/acmelabs.txt'" in (
        out.out + out.err
    )
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(BRACKETED_INCLUDES))
def test_bracketed_include_refusal_matches_real_cargo(
    case: str, tmp_path: Path
) -> None:
    """Real Cargo: the old receipt left the file behind (``0/0/yes/101``)."""
    _require_cargo()
    files, _ = BRACKETED_INCLUDES[case]
    target = _source_path_target(tmp_path, files, table=False)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2

    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    _assert_cargo(target, "test", "--offline", "--all-targets")


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


# --- Cycle 2 F3: a default crate root that Cargo does not select -----------------

MAIN_INCLUDE = f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n"
BUILD_INCLUDE = 'fn main() {{\n    let _ = include_str!("{}data/acmelabs.txt");\n}}\n'
UNUSED_ROOTS = {
    # Cycle 3 F1: ``build = false`` turns the build script off.
    "build_false_unused_build_rs": {
        "Cargo.toml": _package("acme-core") + "build = false\n",
        "src/lib.rs": LIB,
        "build.rs": BUILD_INCLUDE.format(""),
    },
    # Cycle 3 F1: a custom ``build`` path replaces the root build.rs.
    "custom_build_unused_build_rs": {
        "Cargo.toml": _package("acme-core") + 'build = "scripts/build.rs"\n',
        "src/lib.rs": LIB,
        "scripts/build.rs": "fn main() {}\n",
        "build.rs": BUILD_INCLUDE.format(""),
    },
    # Cycle 3 F2: a virtual manifest has no targets, so its src/lib.rs is a fixture.
    "virtual_workspace_root_fixture": {
        "Cargo.toml": '[workspace]\nmembers = ["crates/acme-core"]\nresolver = "2"\n',
        "crates/acme-core/Cargo.toml": _package("acme-core"),
        "crates/acme-core/src/lib.rs": LIB,
        "src/lib.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n",
    },
    # Cycle 3 F3: include_str! reads a .rs file as data; Cargo never compiles it.
    "include_str_rs_fixture": {
        "src/lib.rs": LIB + 'pub const F: &str = include_str!("fixture.rs");\n',
        "src/fixture.rs": "mod acmelabs;\n",
    },
    # Cycle 4 thread 4697845632: a comment or long whitespace keeps it data.
    "include_str_rs_fixture_comment": {
        "src/lib.rs": LIB
        + 'pub const F: &str = include_str!(/* data */ "fixture.rs");\n',
        "src/fixture.rs": "mod acmelabs;\n",
    },
    "include_str_rs_fixture_spaced": {
        "src/lib.rs": LIB
        + "pub const F: &str = include_str!("
        + " " * 80
        + '"fixture.rs");\n',
        "src/fixture.rs": "mod acmelabs;\n",
    },
    # Cycle 3 F4: an inline #[path] override with no child names no directory.
    "inline_path_override_without_children": {
        "src/lib.rs": LIB
        + '#[allow(unused_attributes)]\n#[path = "acmelabs"]\n'
        + "pub mod outer {\n    pub fn f() {}\n}\n",
    },
    # A [lib] path replaces src/lib.rs, so Cargo never compiles it.
    "lib_path_unused_srclib": {
        "Cargo.toml": _package("acme-core") + '\n[lib]\npath = "actual.rs"\n',
        "actual.rs": LIB,
        "src/lib.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n",
    },
    # autobins = false with no [[bin]]: Cargo builds no binary.
    "autobins_false_unused_main": {
        "Cargo.toml": _package("acme-core") + "autobins = false\n",
        "src/lib.rs": LIB,
        "src/main.rs": MAIN_INCLUDE,
    },
    # Cycle 5 thread 4698809971: autolib = false with no [lib] turns it off.
    "autolib_false_unused_srclib": {
        "Cargo.toml": _package("acme-core") + "autolib = false\n",
        "src/main.rs": "fn main() {}\n",
        "src/lib.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n",
    },
    # A [[bin]] with the package's name and a path replaces src/main.rs.
    "named_bin_path_unused_main": {
        "Cargo.toml": _package("acme-core")
        + '\n[[bin]]\nname = "acme-core"\npath = "actual.rs"\n',
        "actual.rs": "fn main() {}\n",
        "src/lib.rs": LIB,
        "src/main.rs": MAIN_INCLUDE,
    },
}
USED_ROOTS = {
    "autobins_false_named_main": (
        _package("acme-core")
        + 'autobins = false\n\n[[bin]]\nname = "acme-core"\npath = "src/main.rs"\n',
        "src/main.rs",
    ),
    # A pathless [[bin]] may still be inferred at src/main.rs.
    "autobins_false_pathless_bin": (
        _package("acme-core") + 'autobins = false\n\n[[bin]]\nname = "acme-core"\n',
        "src/main.rs",
    ),
    "lib_table_without_path": (
        _package("acme-core") + '\n[lib]\ncrate-type = ["rlib"]\n',
        "src/lib.rs",
    ),
    # A [lib] table keeps src/lib.rs under autolib = false.
    "autolib_false_lib_table": (
        _package("acme-core") + 'autolib = false\n\n[lib]\ncrate-type = ["rlib"]\n',
        "src/lib.rs",
    ),
    # A [[bin]] with another name leaves src/main.rs inferred.
    "other_named_bin_path": (
        _package("acme-core") + '\n[[bin]]\nname = "other"\npath = "actual.rs"\n',
        "src/main.rs",
    ),
    # Cycle 3 F1 controls: Cargo runs these build scripts.
    "build_true": (_package("acme-core") + "build = true\n", "build.rs"),
    "custom_build_script": (
        _package("acme-core") + 'build = "scripts/build.rs"\n',
        "scripts/build.rs",
    ),
}


def _used_root_files(case: str) -> dict[str, str]:
    manifest, root = USED_ROOTS[case]
    files = {"Cargo.toml": manifest, "src/lib.rs": LIB}
    if root == "src/main.rs":
        files["src/main.rs"] = MAIN_INCLUDE
        if "actual.rs" in manifest:
            files["actual.rs"] = "fn main() {}\n"
    elif root == "build.rs":
        files[root] = BUILD_INCLUDE.format("")
    elif root == "scripts/build.rs":
        files[root] = BUILD_INCLUDE.format("../")
    else:
        files["src/lib.rs"] = f"pub const D: &str = {FIXTURE_INCLUDE};\n"
    return {**files, "data/acmelabs.txt": "x\n"}


@pytest.mark.parametrize("table", [True, False], ids=["table", "tableless"])
@pytest.mark.parametrize("case", sorted(UNUSED_ROOTS))
def test_default_root_cargo_does_not_select_is_not_judged(
    case: str, table: bool, tmp_path: Path
) -> None:
    """Base ``10b4f9b`` presses these targets healthy."""
    files = {**UNUSED_ROOTS[case], "data/acmelabs.txt": "x\n"}
    target = _source_path_target(tmp_path, files, table=table)

    assert _press(target, _source_path_answers(tmp_path, table=table)) == 0

    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("case", sorted(USED_ROOTS))
def test_default_root_cargo_selects_is_still_judged(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _source_path_target(tmp_path, _used_root_files(case), table=False)

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2

    out = capsys.readouterr()
    root = USED_ROOTS[case][1]
    line = 1 if root == "src/lib.rs" else 2
    assert f"cargo paths: {root}:{line}: the Rust path" in out.out + out.err
    assert _status(target) == ""


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(UNUSED_ROOTS))
def test_default_root_cargo_does_not_select_presses_and_builds(
    case: str, tmp_path: Path
) -> None:
    """Real Cargo: the table-less form presses healthy, as on base ``10b4f9b``."""
    _require_cargo()
    files = {**UNUSED_ROOTS[case], "data/acmelabs.txt": "x\n"}
    target = _source_path_target(tmp_path, files, table=False)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 0

    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "test", "--offline", "--all-targets")


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", sorted(USED_ROOTS))
def test_default_root_cargo_selects_refusal_matches_real_cargo(
    case: str, tmp_path: Path
) -> None:
    """Real Cargo compiles the root, so the refusal guards a real build."""
    _require_cargo()
    target = _source_path_target(tmp_path, _used_root_files(case), table=False)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2

    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


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


def test_rust_source_structure_tracks_inline_paths_and_unicode() -> None:
    from template_press.rebrand.rust_text import InlineModule, rust_source_structure

    text = (
        '// mod decoy { #[path = "nope.rs"] mod bad; }\n'
        "pub const BRACE: char = '{';\n"
        '#[path = "p"]\n'
        '#[cfg_attr(unix, path = "u")]\n'
        "pub mod outer {\n"
        '    #[path = r#"x.rs"#]\n'
        "    pub mod raw_child;\n"
        '    pub const T: &str = include_str!("data.txt");\n'
        '    # [ path = "spaced.rs" ]\n'
        "    pub mod spaced;\n"
        "}\n"
        "pub mod café {\n"
        "    pub mod inner;\n"
        "}\n"
    )
    mods, paths = rust_source_structure(text)

    outer = InlineModule("outer", path="p", conditional_paths=("u",))
    cafe = InlineModule("café")
    assert [(m.name, m.attributed, m.conditional, m.inline) for m in mods] == [
        ("raw_child", True, False, (outer,)),
        ("spaced", True, False, (outer,)),
        ("inner", False, False, (cafe,)),
    ]
    assert [
        (
            p.kind,
            text[p.literal.content_start : p.literal.content_end],
            p.inline,
        )
        for p in paths
    ] == [
        ("inline_dir", "p", ()),
        ("inline_dir", "u", ()),
        ("module_path", "x.rs", (outer,)),
        ("include", "data.txt", ()),
        ("module_path", "spaced.rs", (outer,)),
    ]
