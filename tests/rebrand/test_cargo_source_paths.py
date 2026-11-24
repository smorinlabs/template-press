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
}


def _source_path_target(tmp_path: Path, files: dict[str, str], *, table: bool) -> Path:
    target = tmp_path / "target-repo"
    target.mkdir()
    if table:
        _seed(target, {"Cargo.toml": _package("acme-core"), **files}, names=CORE_NAMES)
        return target
    # Without a table, the repo_name row is the one that rewrites the crate name.
    manifest = _package("acme-core").replace("acme-repo", "acme-core")
    _seed(
        target,
        {"Cargo.toml": manifest, **files},
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


@pytest.mark.parametrize(
    "files",
    [
        # The module file renames with the declaration: the crate name does both.
        {"src/lib.rs": LIB + "pub mod acme_core;\n", "src/acme_core.rs": ""},
        # An inline module has no file.
        {"src/lib.rs": LIB + "pub mod acmelabs {\n    pub fn org() {}\n}\n"},
        # A path no row changes.
        {
            "src/lib.rs": LIB + 'pub const T: &str = include_str!("t.txt");\n',
            "src/t.txt": "x\n",
        },
    ],
    ids=["renamed_with_its_file", "inline_module", "unchanged_path"],
)
def test_rust_source_paths_that_follow_their_files_press(
    files: dict[str, str], tmp_path: Path
) -> None:
    target = _source_path_target(tmp_path, files, table=True)
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 0


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize("case", ["mod_owner", "include_owner", "path_attr_owner"])
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
