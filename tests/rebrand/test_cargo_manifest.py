"""Cargo manifest reader: names, workspace members, identity, dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.cargo_manifest import read_cargo_facts
from template_press.rebrand.identity import ValidationError


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _pkg(name: str, extra: str = "") -> str:
    return f'[package]\nname = "{name}"\nversion = "0.1.0"\n{extra}'


def test_single_crate_auto_bin_and_lib_name(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _pkg("acme-widget") + '[lib]\nname = "acme_lib"\n')
    _write(tmp_path / "src" / "main.rs", "fn main() {}\n")
    facts = read_cargo_facts(tmp_path)
    assert facts.primary == "acme-widget"
    assert facts.packages == ("acme-widget",)
    assert facts.bins == ("acme-widget",)
    assert facts.names == ("acme-widget", "acme_lib")


def test_autobins_false_ignores_src_main_and_src_bin(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _pkg("acme-widget", "autobins = false\n"))
    _write(tmp_path / "src" / "main.rs", "fn main() {}\n")
    _write(tmp_path / "src" / "bin" / "extra.rs", "fn main() {}\n")
    _write(
        tmp_path / "Cargo.toml",
        _pkg("acme-widget", "autobins = false\n")
        + '[[bin]]\nname = "declared"\npath = "src/x.rs"\n',
    )
    facts = read_cargo_facts(tmp_path)
    assert facts.bins == ("declared",)
    assert facts.names == ("acme-widget", "declared")


def test_src_bin_file_and_directory_stems(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _pkg("acme-widget"))
    _write(tmp_path / "src" / "bin" / "one.rs", "fn main() {}\n")
    _write(tmp_path / "src" / "bin" / "two" / "main.rs", "fn main() {}\n")
    _write(tmp_path / "src" / "bin" / "empty-dir" / "other.rs", "")
    _write(tmp_path / "src" / "bin" / "notes.txt", "")
    facts = read_cargo_facts(tmp_path)
    assert facts.bins == ("one", "two")


def test_virtual_workspace_glob_with_exclude(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/skipped"]\n',
    )
    _write(tmp_path / "crates" / "one" / "Cargo.toml", _pkg("acme-one"))
    _write(tmp_path / "crates" / "two" / "Cargo.toml", _pkg("acme-two"))
    # Excluded before reading: a broken manifest there is not an error.
    _write(tmp_path / "crates" / "skipped" / "Cargo.toml", "not = [valid")
    _write(tmp_path / "crates" / "plain-file", "")
    facts = read_cargo_facts(tmp_path)
    assert facts.primary is None
    assert facts.packages == ("acme-one", "acme-two")
    assert facts.names == ("acme-one", "acme-two")


def test_glob_directory_without_manifest_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
    (tmp_path / "crates" / "bare").mkdir(parents=True)
    with pytest.raises(ValidationError):
        read_cargo_facts(tmp_path)


def test_root_package_and_members_are_both_read(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        _pkg("acme-root") + '[workspace]\nmembers = [".", "member"]\n',
    )
    _write(tmp_path / "member" / "Cargo.toml", _pkg("acme-member"))
    facts = read_cargo_facts(tmp_path)
    assert facts.primary == "acme-root"
    assert facts.packages == ("acme-root", "acme-member")
    assert facts.names == ("acme-member", "acme-root")


def test_authors_and_repository_inherit_from_workspace(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        '[workspace]\nmembers = ["m"]\n'
        "[workspace.package]\n"
        'authors = ["Example Person <person@example.test>", "Other"]\n'
        'repository = "https://github.com/example-org/acme-repo"\n',
    )
    _write(
        tmp_path / "m" / "Cargo.toml",
        _pkg("acme-m", "authors.workspace = true\nrepository.workspace = true\n"),
    )
    facts = read_cargo_facts(tmp_path)
    assert facts.author == "Example Person"
    assert facts.email == "person@example.test"
    assert facts.repository == "https://github.com/example-org/acme-repo"


def test_direct_authors_name_only(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _pkg("acme-x", 'authors = ["Solo Name"]\n'))
    facts = read_cargo_facts(tmp_path)
    assert (facts.author, facts.email) == ("Solo Name", None)
    assert facts.repository is None


def test_member_outside_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root / "Cargo.toml", '[workspace]\nmembers = ["../outside"]\n')
    _write(tmp_path / "outside" / "Cargo.toml", _pkg("acme-out"))
    with pytest.raises(ValidationError):
        read_cargo_facts(root)


def test_absolute_member_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(tmp_path / "outside" / "Cargo.toml", _pkg("acme-out"))
    _write(
        root / "Cargo.toml",
        f'[workspace]\nmembers = ["{(tmp_path / "outside").as_posix()}"]\n',
    )
    with pytest.raises(ValidationError):
        read_cargo_facts(root)


def test_symlinked_member_leaving_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(tmp_path / "outside" / "Cargo.toml", _pkg("acme-out"))
    _write(root / "Cargo.toml", '[workspace]\nmembers = ["link"]\n')
    (root / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValidationError):
        read_cargo_facts(root)


def test_symlinked_member_manifest_is_refused(tmp_path: Path) -> None:
    real = _write(tmp_path / "real.toml", _pkg("acme-real"))
    _write(tmp_path / "Cargo.toml", '[workspace]\nmembers = ["m"]\n')
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "Cargo.toml").symlink_to(real)
    with pytest.raises(ValidationError):
        read_cargo_facts(tmp_path)


def test_malformed_manifest_raises_validation_error(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", "[package\nname =")
    with pytest.raises(ValidationError):
        read_cargo_facts(tmp_path)


def test_malformed_member_raises_validation_error(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", '[workspace]\nmembers = ["m"]\n')
    _write(tmp_path / "m" / "Cargo.toml", "[package\nname =")
    with pytest.raises(ValidationError):
        read_cargo_facts(tmp_path)


def test_external_dependency_honors_package_key_and_target_tables(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "Cargo.toml",
        _pkg("acme-widget")
        + '[dependencies]\nserde = "1"\nrenamed = { package = "real-name", '
        'version = "1" }\n'
        '[dev-dependencies]\ndev-only = { version = "1" }\n'
        '[build-dependencies]\nbuilder = { git = "https://example.test/b.git" }\n'
        "[target.'cfg(unix)'.dependencies]\nunix-only = \"1\"\n"
        '[target.x86_64-pc-windows-gnu.build-dependencies]\nwin-build = "1"\n'
        '[workspace]\nmembers = []\n[workspace.dependencies]\nshared = "2"\n',
    )
    facts = read_cargo_facts(tmp_path)
    assert facts.external_dependencies == (
        "builder",
        "dev-only",
        "real-name",
        "serde",
        "shared",
        "unix-only",
        "win-build",
    )


def test_path_and_workspace_dependencies_are_local(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        '[workspace]\nmembers = ["m"]\n'
        "[workspace.dependencies]\n"
        'acme-m = { path = "m" }\n'
        'ext = { package = "ext-real", version = "1" }\n',
    )
    _write(
        tmp_path / "m" / "Cargo.toml",
        _pkg("acme-m")
        + '[dependencies]\nlocal = { path = "../local", version = "1" }\n'
        "acme-m = { workspace = true }\next = { workspace = true }\n",
    )
    facts = read_cargo_facts(tmp_path)
    assert facts.external_dependencies == ("ext-real",)


def test_examples_tests_and_benches_are_not_names(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        _pkg("acme-widget")
        + "[features]\nacme-feature = []\n"
        + '[[example]]\nname = "ex"\n[[test]]\nname = "tt"\n[[bench]]\nname = "bb"\n',
    )
    facts = read_cargo_facts(tmp_path)
    assert facts.names == ("acme-widget",)
    assert facts.bins == ()


def test_symlinked_root_manifest_raises_validation_error(tmp_path: Path) -> None:
    real = _write(tmp_path / "elsewhere.toml", _pkg("acme-widget"))
    (tmp_path / "Cargo.toml").symlink_to(real)
    with pytest.raises(ValidationError):
        read_cargo_facts(tmp_path)


# --- Final review: agreement with `cargo metadata --no-deps --offline` -------

_WS = '[workspace]\nresolver = "2"\nmembers = ["crates/a"]\n'


def _crates(root: Path, manifests: dict[str, str]) -> None:
    for rel, text in manifests.items():
        _write(root / rel / "Cargo.toml", text)
        _write(root / rel / "src" / "lib.rs", "pub fn hi() {}\n")


def test_path_dependency_under_root_is_a_member(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _WS)
    _crates(
        tmp_path,
        {
            "crates/a": _pkg("a", '[dependencies]\nb = { path = "../b" }\n'),
            "crates/b": _pkg("b", '[dev-dependencies]\nc = { path = "../c" }\n'),
            "crates/c": _pkg(
                "c",
                "[target.'cfg(unix)'.build-dependencies]\nd = { path = \"../d\" }\n",
            ),
            "crates/d": _pkg("d"),
        },
    )
    assert read_cargo_facts(tmp_path).names == ("a", "b", "c", "d")


def test_inherited_path_dependency_is_a_member_only_when_used(tmp_path: Path) -> None:
    root = _WS + '[workspace.dependencies]\nb = { path = "crates/b" }\n'
    _write(tmp_path / "Cargo.toml", root)
    _crates(tmp_path, {"crates/a": _pkg("a"), "crates/b": _pkg("b")})
    assert read_cargo_facts(tmp_path).names == ("a",)
    _write(
        tmp_path / "crates/a/Cargo.toml",
        _pkg("a", "[dependencies]\nb = { workspace = true }\n"),
    )
    assert read_cargo_facts(tmp_path).names == ("a", "b")


def test_path_dependency_needs_a_workspace_root(tmp_path: Path) -> None:
    _write(
        tmp_path / "Cargo.toml",
        _pkg("root", '[dependencies]\nb = { path = "crates/b" }\n'),
    )
    _crates(tmp_path, {"crates/b": _pkg("b")})
    assert read_cargo_facts(tmp_path).names == ("root",)


def test_path_dependency_outside_root_is_skipped_not_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _write(root / "Cargo.toml", _WS)
    _crates(
        root, {"crates/a": _pkg("a", '[dependencies]\nz = { path = "../../../z" }\n')}
    )
    _crates(tmp_path, {"z": _pkg("z")})
    assert read_cargo_facts(root).names == ("a",)


def test_excluded_path_dependency_is_not_a_member(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _WS + 'exclude = ["crates/b"]\n')
    _crates(
        tmp_path,
        {
            "crates/a": _pkg("a", '[dependencies]\nb = { path = "../b" }\n'),
            "crates/b": _pkg("b"),
        },
    )
    assert read_cargo_facts(tmp_path).names == ("a",)


def test_path_dependency_symlink_leaving_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _write(root / "Cargo.toml", _WS)
    _crates(root, {"crates/a": _pkg("a", '[dependencies]\nb = { path = "../b" }\n')})
    _crates(tmp_path, {"outside": _pkg("outside")})
    (root / "crates" / "b").symlink_to(tmp_path / "outside")
    with pytest.raises(ValidationError):
        read_cargo_facts(root)


@pytest.mark.parametrize(
    ("members", "exclude", "expected"),
    [
        ("tools/*", "tools/x*", ("xtask", "y")),
        ("tools/*", "tools/xtask", ("y",)),
        ("tools/*", "tools", ()),
        ("tools/xtask", "tools/xtask", ("xtask",)),
    ],
)
def test_exclude_matches_cargo(tmp_path: Path, members, exclude, expected) -> None:
    _write(
        tmp_path / "Cargo.toml",
        f'[workspace]\nresolver = "2"\nmembers = ["{members}"]\n'
        f'exclude = ["{exclude}"]\n',
    )
    _crates(tmp_path, {"tools/xtask": _pkg("xtask"), "tools/y": _pkg("y")})
    assert read_cargo_facts(tmp_path).names == expected


@pytest.mark.parametrize(
    ("path", "rel"),
    [
        ("src/bin/tool.rs", "src/bin/tool.rs"),
        ("./src/bin/tool.rs", "src/bin/tool.rs"),
        ("src/bin/tool/main.rs", "src/bin/tool/main.rs"),
        ("src/main.rs", "src/main.rs"),
    ],
)
def test_file_claimed_by_a_bin_is_not_auto_discovered(
    tmp_path: Path, path: str, rel: str
) -> None:
    _write(
        tmp_path / "Cargo.toml",
        _pkg("pkg", f'[[bin]]\nname = "acme"\npath = "{path}"\n'),
    )
    _write(tmp_path / rel, "fn main() {}\n")
    facts = read_cargo_facts(tmp_path)
    assert facts.bins == ("acme",)
    assert facts.names == ("acme", "pkg")
