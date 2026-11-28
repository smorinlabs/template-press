"""P20: Cargo metadata target discovery, fallback, and closed P15 follow-ups.

Tests Cargo metadata target seeding, offline read-only execution, missing-cargo
fallback, and the P15 follow-ups resolved by asking Cargo which files it
compiles: P15-T12, P15-T21, P15-T23, P15-T24, P15-T25, P15-T27, P15-T28,
P15-T30, and P15-T31.

The slow tests use real Cargo as the oracle:
CARGO_BUILD_WARNINGS=deny uv run pytest -m "" tests/rebrand/test_cargo_metadata_targets.py
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand import cargo_manifest
from template_press.rebrand.cargo_manifest import (
    auto_target_sections,
    read_cargo_facts,
)
from template_press.rebrand.languages import detect_languages
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.substitutions import _compiled_rust_files

from .conftest import posix_only
from .test_cargo_source_paths import (
    CLI_DEST_NAMES,
    CLI_NAMES,
    CORE_DEST,
    CORE_NAMES,
    FIXTURE_INCLUDE,
    LIB,
    MAIN_RS,
    TEST_RS,
    _answers,
    _seed,
    _source_path_answers,
    _source_path_target,
)
from .test_cargo_split import (
    ACME,
    ZETA,
    _assert_cargo,
    _cargo,
    _package,
    _press,
    _require_cargo,
    _status,
)


def _disable_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a machine where ``cargo`` is not installed on PATH."""
    real_which = shutil.which

    def fake_which(cmd: str, *args: object, **kwargs: object) -> str | None:
        if Path(cmd).name in {"cargo", "cargo.exe"}:
            return None
        return real_which(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(shutil, "which", fake_which)


# --- P20-T02: Cargo metadata reader and fallback --------------------------------


def test_read_cargo_metadata_returns_exact_targets(tmp_path: Path) -> None:
    _require_cargo()
    manifest = (
        '[package]\nname = "acme-core"\nversion = "0.1.0"\nedition = "2021"\n'
        "autolib = false\nbuild = false\n\n"
        '[[bin]]\nname = "acme-cli"\npath = "src/cli.rs"\n\n'
        '[[test]]\nname = "foo"\npath = "tests/custom_foo.rs"\n'
    )
    (tmp_path / "Cargo.toml").write_text(manifest, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lib.rs").write_text(LIB, encoding="utf-8")
    (tmp_path / "src/cli.rs").write_text(MAIN_RS, encoding="utf-8")
    (tmp_path / "build.rs").write_text(MAIN_RS, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/foo.rs").write_text(TEST_RS, encoding="utf-8")
    (tmp_path / "tests/custom_foo.rs").write_text(TEST_RS, encoding="utf-8")

    meta = cargo_manifest.read_cargo_metadata(tmp_path)
    assert meta is not None
    assert len(meta.packages) == 1
    pkg = meta.packages[0]
    assert pkg.manifest_path == "Cargo.toml"
    assert sorted((t.kinds, t.name, t.src_path) for t in pkg.targets) == [
        (("bin",), "acme-cli", "src/cli.rs"),
        (("test",), "foo", "tests/custom_foo.rs"),
    ]

    all_files = frozenset(
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    )
    compiled = _compiled_rust_files(
        tmp_path, [("Cargo.toml", tomllib.loads(manifest))], all_files
    )
    assert compiled == frozenset({"src/cli.rs", "tests/custom_foo.rs"})


def test_read_cargo_metadata_returns_none_when_cargo_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Cargo.toml").write_text(_package("acme-core"), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lib.rs").write_text(LIB, encoding="utf-8")

    _disable_cargo(monkeypatch)
    assert cargo_manifest.read_cargo_metadata(tmp_path) is None


def test_read_cargo_metadata_rejects_outer_workspace(tmp_path: Path) -> None:
    _require_cargo()
    (tmp_path / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["other", "target-repo"]\n', encoding="utf-8"
    )
    (tmp_path / "other/src").mkdir(parents=True)
    (tmp_path / "other/Cargo.toml").write_text(_package("other"), encoding="utf-8")
    (tmp_path / "other/src/lib.rs").write_text(LIB, encoding="utf-8")

    inner = tmp_path / "target-repo"
    (inner / "src").mkdir(parents=True)
    (inner / "Cargo.toml").write_text(_package("acme-core"), encoding="utf-8")
    (inner / "src/lib.rs").write_text(LIB, encoding="utf-8")

    raw = _cargo(
        inner.resolve(),
        "metadata",
        "--format-version",
        "1",
        "--no-deps",
        "--offline",
        "--manifest-path",
        str(inner.resolve() / "Cargo.toml"),
    )
    assert raw.returncode == 0
    assert (
        Path(json.loads(raw.stdout)["workspace_root"]).resolve() == tmp_path.resolve()
    )
    assert cargo_manifest.read_cargo_metadata(inner) is None


def test_cargo_metadata_env_disables_rustup_auto_install() -> None:
    """PR #169 thread 4725610782: rustup must never auto-install a toolchain."""
    env = cargo_manifest._cargo_metadata_env()
    assert env["RUSTUP_AUTO_INSTALL"] == "0"
    assert env["CARGO_NET_OFFLINE"] == "true"


def test_read_cargo_metadata_is_offline_and_read_only(tmp_path: Path) -> None:
    _require_cargo()
    (tmp_path / "Cargo.toml").write_text(
        _package("acme-core")
        + '\n[dependencies]\nnonexistent-crate-xyz-99999 = "99.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lib.rs").write_text(LIB, encoding="utf-8")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    meta = cargo_manifest.read_cargo_metadata(tmp_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    assert meta is not None
    assert before == after


def test_read_all_cargo_metadata_includes_non_member_path_dep(tmp_path: Path) -> None:
    _require_cargo()
    (tmp_path / "Cargo.toml").write_text(
        _package("acme-core") + '\n[dependencies]\nhelper = { path = "helper" }\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lib.rs").write_text(LIB, encoding="utf-8")
    (tmp_path / "helper/src").mkdir(parents=True)
    (tmp_path / "helper/Cargo.toml").write_text(_package("helper"), encoding="utf-8")
    (tmp_path / "helper/src/lib.rs").write_text(LIB, encoding="utf-8")

    found = cargo_manifest.read_all_cargo_metadata(
        tmp_path, ("Cargo.toml", "helper/Cargo.toml")
    )
    assert set(found) == {"Cargo.toml", "helper/Cargo.toml"}
    assert [t.src_path for t in found["helper/Cargo.toml"].targets] == [
        "helper/src/lib.rs"
    ]


# --- P15-T28: overridden auto-discovered target files ---------------------------

OVERRIDDEN_AUTO_CASES = {
    "test": (
        '\n[[test]]\nname = "foo"\npath = "tests/custom_foo.rs"\n',
        "tests/custom_foo.rs",
        TEST_RS,
        "tests/foo.rs",
        f"pub const D: &str = {FIXTURE_INCLUDE};\n#[test]\nfn unused() {{}}\n",
    ),
    "bin": (
        '\n[[bin]]\nname = "foo"\npath = "src/custom_foo.rs"\n',
        "src/custom_foo.rs",
        MAIN_RS,
        "src/bin/foo.rs",
        f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
    ),
    "example": (
        '\n[[example]]\nname = "foo"\npath = "examples/custom_foo.rs"\n',
        "examples/custom_foo.rs",
        MAIN_RS,
        "examples/foo.rs",
        f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
    ),
    "bench": (
        '\n[[bench]]\nname = "foo"\npath = "benches/custom_foo.rs"\n',
        "benches/custom_foo.rs",
        MAIN_RS,
        "benches/foo.rs",
        f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
    ),
}


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
@pytest.mark.parametrize("kind", sorted(OVERRIDDEN_AUTO_CASES))
def test_overridden_auto_target_is_not_judged(
    kind: str,
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P15-T28: an explicit [[<kind>]] with another path overrides the
    auto-discovered file of the same name, so Cargo never compiles it."""
    if fallback:
        _disable_cargo(monkeypatch)
    extra, custom_path, custom_body, unused_path, unused_body = OVERRIDDEN_AUTO_CASES[
        kind
    ]
    files = {
        "Cargo.toml": _package("acme-core") + extra,
        "src/lib.rs": LIB,
        custom_path: custom_body,
        unused_path: unused_body,
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=False)

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_overridden_auto_target_presses_and_builds_with_real_cargo(
    tmp_path: Path,
) -> None:
    _require_cargo()
    extra, custom_path, custom_body, unused_path, unused_body = OVERRIDDEN_AUTO_CASES[
        "test"
    ]
    files = {
        "Cargo.toml": _package("acme-core") + extra,
        "src/lib.rs": LIB,
        custom_path: custom_body,
        unused_path: unused_body,
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=False)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "test", "--offline", "--all-targets")


# --- P15-T12: edition-2015 auto-discovery default & legacy pathless [[bin]] -----


def _ed2015_pkg(name: str, extra: str = "", *, omit_edition: bool = False) -> str:
    ed = "" if omit_edition else 'edition = "2015"\n'
    return f'[package]\nname = "{name}"\nversion = "0.1.0"\n{ed}{extra}'


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
@pytest.mark.parametrize("omit_edition", [False, True], ids=["explicit", "omitted"])
def test_edition_2015_explicit_bin_suppresses_auto_bins(
    omit_edition: bool,
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P15-T12: in edition 2015, declaring [[bin]] turns autobins off by default."""
    if fallback:
        _disable_cargo(monkeypatch)
    manifest = (
        _ed2015_pkg("acme-core", omit_edition=omit_edition)
        + '\n[[bin]]\nname = "acme-cli"\npath = "src/cli.rs"\n'
    )
    files = {
        "Cargo.toml": manifest,
        "src/lib.rs": LIB,
        "src/cli.rs": MAIN_RS,
        "src/main.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
        "src/bin/unused.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
        "data/acmelabs.txt": "x\n",
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=CLI_NAMES)

    facts = read_cargo_facts(target)
    assert facts.bins == ("acme-cli",)
    assert facts.names == ("acme-cli", "acme-core")

    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)
    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_edition_2015_workspace_inherited_edition_suppresses_auto_tests(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P15-T12: edition.workspace = true inheriting 2015 disables autotests
    when [[test]] is declared."""
    if fallback:
        _disable_cargo(monkeypatch)
    files = {
        "Cargo.toml": (
            '[workspace]\nresolver = "2"\nmembers = ["crates/acme-core"]\n'
            '[workspace.package]\nedition = "2015"\n'
        ),
        "crates/acme-core/Cargo.toml": (
            '[package]\nname = "acme-core"\nversion = "0.1.0"\n'
            "edition.workspace = true\n\n"
            '[[test]]\nname = "real"\npath = "tests/real.rs"\n'
        ),
        "crates/acme-core/src/lib.rs": LIB,
        "crates/acme-core/tests/real.rs": TEST_RS,
        "crates/acme-core/tests/unused.rs": (
            'pub const D: &str = include_str!("../../../data/acmelabs.txt");\n'
        ),
        "data/acmelabs.txt": "x\n",
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=CORE_NAMES)
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
@pytest.mark.parametrize(
    "bin_rel",
    ["src/acme-cli.rs", "src/main.rs", "src/bin/main.rs"],
)
def test_edition_2015_legacy_pathless_bin_file_is_judged(
    bin_rel: str,
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T12: edition-2015 pathless [[bin]] falls back to src/<name>.rs
    (without lib), src/main.rs, and src/bin/main.rs."""
    if fallback:
        _disable_cargo(monkeypatch)
    rel_up = "../../" if bin_rel == "src/bin/main.rs" else "../"
    files = {
        "Cargo.toml": (_ed2015_pkg("acme-core") + '\n[[bin]]\nname = "acme-cli"\n'),
        bin_rel: f'fn main() {{\n    let _ = include_str!("{rel_up}data/acmelabs.txt");\n}}\n',
        "data/acmelabs.txt": "x\n",
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=CLI_NAMES)
    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    assert f"cargo paths: {bin_rel}:2:" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_edition_2015_legacy_pathless_bin_inferred_path_split_is_refused(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T12: an owner-only rewrite of pathless [[bin]] acmelabs in edition
    2015 whose file is src/acmelabs.rs is refused before any write."""
    if fallback:
        _disable_cargo(monkeypatch)
    files = {
        "Cargo.toml": _ed2015_pkg("acme-core") + '\n[[bin]]\nname = "acmelabs"\n',
        "src/acmelabs.rs": MAIN_RS,
    }
    target = _source_path_target(tmp_path, files, table=False)

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2
    out = capsys.readouterr()
    assert "inferred path 'src/acmelabs.rs'" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_edition_2015_auto_target_sections_honors_edition_and_workspace() -> None:
    ws_2015 = {"edition": "2015"}
    ws_2021 = {"edition": "2021"}
    manifest = tomllib.loads(
        '[package]\nname = "acme-core"\nversion = "0.1.0"\nedition.workspace = true\n'
        '[[test]]\nname = "t"\npath = "tests/t.rs"\n'
    )
    sections_2015 = [
        sec for sec, *_ in auto_target_sections(manifest, workspace_package=ws_2015)
    ]
    sections_2021 = [
        sec for sec, *_ in auto_target_sections(manifest, workspace_package=ws_2021)
    ]
    assert "test" not in sections_2015
    assert "test" in sections_2021


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_edition_2015_discovery_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    files = {
        "Cargo.toml": (
            _ed2015_pkg("acme-core")
            + '\n[[bin]]\nname = "acme-cli"\npath = "src/cli.rs"\n'
        ),
        "src/lib.rs": LIB,
        "src/cli.rs": MAIN_RS,
        "src/main.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
        "data/acmelabs.txt": "x\n",
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, names=CLI_NAMES)
    _assert_cargo(target, "test", "--offline", "--all-targets")

    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)
    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()
    _assert_cargo(target, "test", "--offline", "--all-targets")


# --- P15-T23 & P15-T27: non-.rs #[path] and include! files ----------------------


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_non_rs_path_attr_module_own_paths_are_judged(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T23: Rust paths declared inside a non-.rs #[path] module are judged."""
    if fallback:
        _disable_cargo(monkeypatch)
    files = {
        "src/lib.rs": LIB + '#[path = "bridge.inc"]\npub mod bridge;\n',
        "src/bridge.inc": f"pub const T: &str = {FIXTURE_INCLUDE};\n",
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=True)

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2
    out = capsys.readouterr()
    assert "cargo paths: src/bridge.inc:1:" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_non_rs_include_macro_file_is_followed_and_judged(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T27: plain-string include!("x.inc") is followed and judged."""
    if fallback:
        _disable_cargo(monkeypatch)
    files = {
        "src/lib.rs": LIB + 'include!("frag.inc");\n',
        "src/frag.inc": f"pub const T: &str = {FIXTURE_INCLUDE};\n",
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=True)

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2
    out = capsys.readouterr()
    assert "cargo paths: src/frag.inc:1:" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_non_rs_include_str_and_bytes_still_skipped(tmp_path: Path) -> None:
    """P15-T27 control: include_str!/include_bytes! of .inc is data, not Rust."""
    files = {
        "src/lib.rs": (
            LIB
            + 'pub const S: &str = include_str!("data.inc");\n'
            + 'pub const B: &[u8] = include_bytes!("raw.inc");\n'
        ),
        "src/data.inc": "mod acmelabs;\n",
        "src/raw.inc": "mod acmelabs;\n",
    }
    target = _source_path_target(tmp_path, files, table=True)

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
@pytest.mark.parametrize(
    ("lib_extra", "inc_name"),
    [
        ('#[path = "bridge.inc"]\npub mod bridge;\n', "src/bridge.inc"),
        ('include!("frag.inc");\n', "src/frag.inc"),
    ],
    ids=["path_attr_inc", "include_macro_inc"],
)
def test_non_rs_rust_files_refusal_matches_real_cargo(
    lib_extra: str, inc_name: str, tmp_path: Path
) -> None:
    _require_cargo()
    files = {
        "src/lib.rs": LIB + lib_extra,
        inc_name: f"pub const T: &str = {FIXTURE_INCLUDE};\n",
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=True)
    _assert_cargo(target, "test", "--offline")

    assert _press(target, _source_path_answers(tmp_path, table=True)) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


# --- P15-T24: legacy [project]-table Cargo manifest -----------------------------


def _project_manifest(name: str, extra: str = "") -> str:
    return f'[project]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n{extra}'


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_legacy_project_table_manifest_is_detected_and_checked(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T24: [project] is Cargo's legacy alias for [package]."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _project_manifest(
                "acme-core", 'build = "scripts/acmelabs.rs"\n'
            ),
            "src/lib.rs": LIB,
            "scripts/acmelabs.rs": MAIN_RS,
        },
        names=CORE_NAMES,
    )

    assert [d.language for d in detect_languages(target)] == ["rust"]
    facts = read_cargo_facts(target)
    assert facts.primary == "acme-core"
    assert facts.packages == ("acme-core",)

    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(target, answers) == 2
    out = capsys.readouterr()
    assert "cargo paths:" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_legacy_project_table_autolib_and_build_false_press(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _project_manifest(
                "acme-core", "autolib = false\nbuild = false\n"
            ),
            "src/main.rs": MAIN_RS,
            "src/lib.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n",
            "build.rs": 'fn main() {\n    let _ = include_str!("data/acmelabs.txt");\n}\n',
            "data/acmelabs.txt": "x\n",
        },
        names=CORE_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_legacy_project_table_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _project_manifest(
                "acme-core", 'build = "scripts/acmelabs.rs"\n'
            ),
            "src/lib.rs": LIB,
            "scripts/acmelabs.rs": MAIN_RS,
        },
        names=CORE_NAMES,
    )
    _assert_cargo(target, "check", "--offline")

    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(target, answers) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


# --- P15-T25: conventional Cargo root renamed (src/main.rs, src/lib.rs, build.rs)


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
@pytest.mark.parametrize(
    ("pkg_name", "root_rel", "extra_files"),
    [
        ("main", "src/main.rs", {}),
        ("lib", "src/lib.rs", {}),
        ("build", "build.rs", {"src/lib.rs": LIB}),
    ],
    ids=["main_rs", "lib_rs", "build_rs"],
)
def test_conventional_cargo_root_rename_is_refused(
    pkg_name: str,
    root_rel: str,
    extra_files: dict[str, str],
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T25: renaming a crate named main/lib/build moves its conventional
    root file (src/main.rs, src/lib.rs, build.rs), leaving Cargo without it."""
    if fallback:
        _disable_cargo(monkeypatch)
    src_id = {**ACME, "package_name": pkg_name, "repo_name": f"{pkg_name}-repo"}
    dst_id = {**ZETA, "package_name": "zeta", "repo_name": "zeta-repo"}
    files = {
        "Cargo.toml": _package(pkg_name),
        root_rel: LIB if root_rel == "src/lib.rs" else MAIN_RS,
        **extra_files,
    }
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(target, files, identity=src_id, names={"core": pkg_name})
    answers = _answers(tmp_path, dst_id, {"core": "zeta"})

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    message = out.out + out.err
    assert "cargo paths:" in message
    assert root_rel in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_conventional_cargo_root_with_explicit_path_presses(tmp_path: Path) -> None:
    """P15-T25 control: an explicit [[bin]] path that renames with the file
    is healthy and presses."""
    src_id = {**ACME, "package_name": "main", "repo_name": "main-repo"}
    dst_id = {**ZETA, "package_name": "zeta", "repo_name": "zeta-repo"}
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("main")
            + '\n[[bin]]\nname = "main"\npath = "src/main.rs"\n',
            "src/main.rs": MAIN_RS,
        },
        identity=src_id,
        names={"core": "main"},
    )
    answers = _answers(tmp_path, dst_id, {"core": "zeta"})

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()
    assert (target / "src/zeta.rs").is_file()
    assert 'path = "src/zeta.rs"' in (target / "Cargo.toml").read_text(encoding="utf-8")


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_conventional_cargo_root_refusal_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    src_id = {**ACME, "package_name": "main", "repo_name": "main-repo"}
    dst_id = {**ZETA, "package_name": "zeta", "repo_name": "zeta-repo"}
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {"Cargo.toml": _package("main"), "src/main.rs": MAIN_RS},
        identity=src_id,
        names={"core": "main"},
    )
    _assert_cargo(target, "check", "--offline")

    answers = _answers(tmp_path, dst_id, {"core": "zeta"})
    assert _press(target, answers) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


# --- P15-T21: CARGO_BIN_EXE_ preflight for declared [[bin]] and src/main.rs -----


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
@pytest.mark.parametrize(
    ("manifest_extra", "bin_file", "token", "src_names", "dst_names"),
    [
        (
            '\n[[bin]]\nname = "acme-cli"\npath = "src/cli.rs"\n',
            "src/cli.rs",
            "CARGO_BIN_EXE_acme-cli",
            CLI_NAMES,
            CLI_DEST_NAMES,
        ),
        (
            "",
            "src/main.rs",
            "CARGO_BIN_EXE_acme-core",
            CORE_NAMES,
            {"core": "zeta-core"},
        ),
    ],
    ids=["declared_bin", "conventional_main"],
)
def test_bin_env_token_preflight_for_declared_bin_and_main_rs(
    manifest_extra: str,
    bin_file: str,
    token: str,
    src_names: dict[str, str],
    dst_names: dict[str, str],
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """P15-T21: an excluded CARGO_BIN_EXE_ token for a declared [[bin]] or
    src/main.rs binary is refused with exit 2 before any write."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core") + manifest_extra,
            "src/lib.rs": LIB,
            bin_file: MAIN_RS,
            "tests/cli.rs": f'#[test]\nfn t() {{\n    let _ = env!("{token}");\n}}\n',
            "press/press-rules.toml": (
                '[rules]\nextra_exclude_files = ["tests/cli.rs"]\n'
                'verify_ignore = ["tests"]\n'
            ),
        },
        names=src_names,
    )
    answers = _answers(tmp_path, CORE_DEST, dst_names)

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    assert f"tests/cli.rs: {token}" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_bin_env_token_preflight_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core"),
            "src/lib.rs": LIB,
            "src/main.rs": MAIN_RS,
            "tests/cli.rs": (
                '#[test]\nfn t() {\n    let _ = env!("CARGO_BIN_EXE_acme-core");\n}\n'
            ),
            "press/press-rules.toml": (
                '[rules]\nextra_exclude_files = ["tests/cli.rs"]\n'
                'verify_ignore = ["tests"]\n'
            ),
        },
        names=CORE_NAMES,
    )
    _assert_cargo(target, "test", "--offline")

    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(target, answers) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


# --- P15-T30: tracked symlink resolving to regular file in two-candidate check --


@posix_only
def test_tracked_symlink_candidate_causes_two_candidate_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """P15-T30: a tracked symlink resolving to a regular file counts as a
    candidate in the two-candidate collision check."""
    target = tmp_path / "target-repo"
    (target / "tests/zeta-core").mkdir(parents=True)
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core")
            + 'autotests = false\n\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
            "shared/real_test.rs": TEST_RS,
        },
        names=CORE_NAMES,
        links={"tests/zeta-core/main.rs": "../../shared/real_test.rs"},
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    message = out.out + out.err
    assert "tests/zeta-core.rs" in message
    assert "tests/zeta-core/main.rs" in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@posix_only
def test_dangling_tracked_symlink_is_not_a_two_candidate_collision(
    tmp_path: Path,
) -> None:
    """P15-T30 control: Cargo ignores a dangling symlink, so it is not refused."""
    target = tmp_path / "target-repo"
    (target / "tests/zeta-core").mkdir(parents=True)
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core")
            + 'autotests = false\n\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
        },
        names=CORE_NAMES,
        links={"tests/zeta-core/main.rs": "../../does_not_exist.rs"},
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_tracked_symlink_candidate_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    # 1) Valid symlink -> refused before write
    valid = tmp_path / "valid-repo"
    (valid / "tests/zeta-core").mkdir(parents=True)
    _seed(
        valid,
        {
            "Cargo.toml": _package("acme-core")
            + 'autotests = false\n\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
            "shared/real_test.rs": TEST_RS,
        },
        names=CORE_NAMES,
        links={"tests/zeta-core/main.rs": "../../shared/real_test.rs"},
    )
    _assert_cargo(valid, "test", "--offline", "--no-run")
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(valid, answers) == 2
    assert not (valid / RECEIPT_REL).exists()
    assert _status(valid) == ""

    # 2) Dangling symlink -> presses cleanly and compiles
    dangling = tmp_path / "dangling-repo"
    (dangling / "tests/zeta-core").mkdir(parents=True)
    _seed(
        dangling,
        {
            "Cargo.toml": _package("acme-core")
            + 'autotests = false\n\n[[test]]\nname = "acme-core"\n',
            "src/lib.rs": LIB,
            "tests/acme-core.rs": TEST_RS,
        },
        names=CORE_NAMES,
        links={"tests/zeta-core/main.rs": "../../does_not_exist.rs"},
    )
    _assert_cargo(dangling, "test", "--offline", "--no-run")
    assert _press(dangling, answers) == 0
    assert (dangling / RECEIPT_REL).is_file()
    _assert_cargo(dangling, "test", "--offline", "--no-run")


# --- P15-T31: renamed explicit target unsuppresses duplicate auto-discovered ----


def test_renamed_explicit_target_unsuppressing_duplicate_auto_files_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """P15-T31: renaming [[test]] acme-core stops suppressing unmoved
    tests/acme-core.rs and tests/acme-core/main.rs, which Cargo rejects."""
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core")
            + '\n[[test]]\nname = "acme-core"\npath = "checks/custom.rs"\n',
            "src/lib.rs": LIB,
            "checks/custom.rs": TEST_RS,
            "tests/acme-core.rs": TEST_RS,
            "tests/acme-core/main.rs": TEST_RS,
            "press/press-rules.toml": (
                '[rules]\nextra_exclude_dirs = ["tests"]\nverify_ignore = ["tests"]\n'
            ),
        },
        names=CORE_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    message = out.out + out.err
    assert "cargo paths:" in message
    assert "tests/acme-core.rs" in message
    assert "tests/acme-core/main.rs" in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_unsuppressed_duplicate_auto_files_matches_real_cargo(tmp_path: Path) -> None:
    _require_cargo()
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core")
            + '\n[[test]]\nname = "acme-core"\npath = "checks/custom.rs"\n',
            "src/lib.rs": LIB,
            "checks/custom.rs": TEST_RS,
            "tests/acme-core.rs": TEST_RS,
            "tests/acme-core/main.rs": TEST_RS,
            "press/press-rules.toml": (
                '[rules]\nextra_exclude_dirs = ["tests"]\nverify_ignore = ["tests"]\n'
            ),
        },
        names=CORE_NAMES,
    )
    _assert_cargo(target, "check", "--offline", "--all-targets")
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 2
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""
    assert _cargo(target, "check", "--offline", "--all-targets").returncode == 0


# --- PR #169 Wave 1 Codex findings ----------------------------------------------


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_flat_src_bin_main_rs_preserves_main_binary_name(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #169 thread 4725598554: flat src/bin/main.rs names binary 'main',
    not 'bin'."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _package("acme-core"),
            "src/lib.rs": LIB,
            "src/bin/main.rs": MAIN_RS,
            "tests/cli.rs": (
                '#[test]\nfn t() {\n    let _ = env!("CARGO_BIN_EXE_main");\n}\n'
            ),
        },
        names={"core": "acme-core", "bin_main": "main"},
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core", "bin_main": "main"})

    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_excluded_path_dep_own_workspace_edition_resolves_independently(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PR #169 thread 4725598545: an excluded path dependency with its own
    workspace resolves edition.workspace = true against its own workspace,
    not the target root's."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": (
                '[workspace]\nresolver = "2"\nmembers = ["crates/acme-core"]\n'
                'exclude = ["helper"]\n'
                '[workspace.package]\nedition = "2015"\n'
            ),
            "crates/acme-core/Cargo.toml": (
                '[package]\nname = "acme-core"\nversion = "0.1.0"\n'
                "edition.workspace = true\n\n"
                '[dependencies]\nhelper = { path = "../../helper" }\n'
            ),
            "crates/acme-core/src/lib.rs": LIB,
            "helper/Cargo.toml": (
                '[workspace]\nresolver = "2"\nmembers = ["."]\n'
                '[workspace.package]\nedition = "2021"\n\n'
                '[package]\nname = "helper"\nversion = "0.1.0"\n'
                "edition.workspace = true\n\n"
                '[[test]]\nname = "explicit"\npath = "tests/explicit.rs"\n'
            ),
            "helper/src/lib.rs": LIB,
            "helper/tests/explicit.rs": TEST_RS,
            "helper/tests/acme-core.rs": TEST_RS,
            "helper/tests/zeta-core/main.rs": TEST_RS,
        },
        names=CORE_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})

    assert _press(target, answers) == 2
    out = capsys.readouterr()
    message = out.out + out.err
    assert "helper/tests/zeta-core.rs" in message
    assert "helper/tests/zeta-core/main.rs" in message
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_renamed_explicit_target_activating_dormant_auto_file_is_judged(
    fallback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PR #169 thread 4725598560: renaming [[test]] acmelabs to zetalabs
    activates dormant tests/acmelabs.rs, whose broken include_str! must be
    refused before any write."""
    if fallback:
        _disable_cargo(monkeypatch)
    files = {
        "Cargo.toml": _package("acme-core")
        + '\n[[test]]\nname = "acmelabs"\npath = "checks/custom.rs"\n',
        "src/lib.rs": LIB,
        "checks/custom.rs": TEST_RS,
        "tests/acmelabs.rs": f"pub const D: &str = {FIXTURE_INCLUDE};\n{TEST_RS}",
        "data/acmelabs.txt": "x\n",
    }
    target = _source_path_target(tmp_path, files, table=False)

    assert _press(target, _source_path_answers(tmp_path, table=False)) == 2
    out = capsys.readouterr()
    assert "cargo paths: tests/acmelabs.rs:1:" in out.out + out.err
    assert _status(target) == ""
    assert not (target / RECEIPT_REL).exists()


# --- PR #169 Wave 2 CodeRabbit findings -----------------------------------------


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_edition_2015_empty_bin_list_suppresses_auto_bins(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #169 thread 4725610783: top-level `bin = []` in edition 2015
    disables autobins unless `autobins = true`."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": "bin = []\n\n" + _ed2015_pkg("acme-core"),
            "src/lib.rs": LIB,
            "src/bin/extra.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
            "data/acmelabs.txt": "x\n",
        },
        names=CORE_NAMES,
    )
    facts = read_cargo_facts(target)
    assert facts.bins == ()
    assert facts.names == ("acme-core",)

    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_edition_2015_ordinary_bin_wins_over_unused_legacy_src_file(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #169 thread 4725610789: when src/bin/<name>.rs exists, fallback
    does not queue unused legacy src/<name>.rs."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _ed2015_pkg("acme-core") + '\n[[bin]]\nname = "acme-cli"\n',
            "src/bin/acme-cli.rs": MAIN_RS,
            "src/acme-cli.rs": f"fn main() {{\n    let _ = {FIXTURE_INCLUDE};\n}}\n",
            "data/acmelabs.txt": "x\n",
        },
        names=CLI_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, CLI_DEST_NAMES)
    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()


@pytest.mark.parametrize("fallback", [False, True], ids=["cargo", "fallback"])
def test_edition_2015_pkg_main_rs_wins_over_unused_legacy_src_pkg_file(
    fallback: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #169 thread 4725610797: when [[bin]] name matches [package].name and
    src/main.rs exists, fallback does not emit an inferred pair for an excluded
    unused src/<name>.rs."""
    if fallback:
        _disable_cargo(monkeypatch)
    target = tmp_path / "target-repo"
    target.mkdir()
    _seed(
        target,
        {
            "Cargo.toml": _ed2015_pkg("acme-core") + '\n[[bin]]\nname = "acme-core"\n',
            "src/main.rs": MAIN_RS,
            "src/acme-core.rs": "fn unused() {}\n",
            "press/press-rules.toml": (
                '[rules]\nextra_exclude_files = ["src/acme-core.rs"]\n'
                'verify_ignore = ["acme-core.rs"]\n'
            ),
        },
        names=CORE_NAMES,
    )
    answers = _answers(tmp_path, CORE_DEST, {"core": "zeta-core"})
    assert _press(target, answers) == 0
    assert (target / RECEIPT_REL).is_file()
