"""Cargo placeholders in `[[replace]]` patterns (P15-T10)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import load_answers
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules, render_replace_pattern
from template_press.rebrand.verify_cli import verify_command

from . import test_cargo_discovery as disc
from . import test_cargo_split as split
from .conftest import _git, posix_only

BASE = {
    "package_name": "acme_core",
    "repo_name": "acme-repo",
    "app_name": "acme",
    "author": "Demo Author",
    "email": "demo@example.test",
    "owner": "demolabs",
}


def _identity(cargo: dict[str, str]) -> Identity:
    return Identity(**BASE, cargo_names=tuple(cargo.items()))


def _rules(tmp_path: Path, pattern: str):
    (tmp_path / "press").mkdir(exist_ok=True)
    (tmp_path / "press" / "press-rules.toml").write_text(
        f'[[replace]]\npattern = "{pattern}"\nreason = "r"\n', encoding="utf-8"
    )
    return load_rules(tmp_path)


# --- parse -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "{cargo_exact_core}",
        "{cargo_ident_core}::",
        "{cargo_ident_core_upper}_HOME",
        "{cargo_ident_core2}::",
        "{cargo_exact_core_x2}",
    ],
)
def test_cargo_placeholders_parse(tmp_path: Path, pattern: str) -> None:
    assert _rules(tmp_path, pattern).replace[0].pattern == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "{cargo_exact_core_upper}",
        "{cargo_Core}",
        "{cargo_ident_}",
        "{cargo_name_core}",
        "{cargo_ident_2core}",
        "{cargo_exact_}",
        "{cargo_ident_core_upper_upper}",
    ],
)
def test_other_cargo_tokens_are_refused(tmp_path: Path, pattern: str) -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        _rules(tmp_path, pattern)


def test_clean_paths_still_refuse_cargo_placeholders(tmp_path: Path) -> None:
    (tmp_path / "press").mkdir()
    (tmp_path / "press" / "press-rules.toml").write_text(
        '[[clean]]\npaths = ["{cargo_ident_core}.txt"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="placeholder"):
        load_rules(tmp_path)


def test_role_ending_in_upper_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "answers.toml"
    path.write_text(
        '[answers]\npackage_name = "zeta"\nrepo_name = "zeta-repo"\n'
        'app_name = "zetactl"\nauthor = "Z"\nemail = "z@example.test"\n'
        'owner = "zetalabs"\n[answers.cargo_names]\nx_upper = "zeta-x"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="_upper"):
        load_answers(path)


# --- render ----------------------------------------------------------------------


def test_render_source_and_destination() -> None:
    src = _identity({"core": "acme-core"})
    dst = _identity({"core": "zeta-core"})
    for pattern, old, new in [
        ("{cargo_exact_core}", "acme-core", "zeta-core"),
        ("{cargo_ident_core}::", "acme_core::", "zeta_core::"),
        ("{cargo_ident_core_upper}_HOME", "ACME_CORE_HOME", "ZETA_CORE_HOME"),
    ]:
        assert render_replace_pattern(pattern, src) == old
        assert render_replace_pattern(pattern, dst) == new


def test_render_digit_role() -> None:
    identity = _identity({"core2": "acme-core"})
    assert render_replace_pattern("{cargo_ident_core2}", identity) == "acme_core"


def test_render_missing_role_names_the_role() -> None:
    with pytest.raises(ValidationError, match="'widget'"):
        render_replace_pattern("{cargo_ident_widget}", _identity({"core": "a-b"}))
    with pytest.raises(ValidationError, match="'widget'"):
        render_replace_pattern("{cargo_exact_widget}", _identity({}))


def test_existing_placeholders_still_render() -> None:
    assert render_replace_pattern("{app_name}-x", _identity({})) == "acme-x"


# --- end to end: the F3 shape ------------------------------------------------------

README = (
    "# acme\n\n```rust\nextern crate acme;\nuse acme as c;\n"
    'assert_eq!(c::hi(), "hello");\n```\n'
)
REPLACE_RULES = (
    '\n[[replace]]\npattern = "extern crate {cargo_ident_core};"\n'
    'files = ["crates/*/README.md"]\nreason = "doctest names the crate"\n'
    '\n[[replace]]\npattern = "use {cargo_ident_core} as c;"\n'
    'files = ["crates/*/README.md"]\nreason = "doctest imports the crate"\n'
)
F3_SPLIT = (
    '\n[[cargo_split]]\nrole = "core"\n'
    'package_files = ["README.md", "crates/acme/README.md"]\n'
    'identifier_files = ["docs/*.md"]\n'
)


def _f3_files() -> dict[str, str]:
    files = split._workspace_files()
    files["crates/acme/src/lib.rs"] = (
        '#![doc = include_str!("../README.md")]\n' + split.LIB_RS
    )
    files["crates/acme/README.md"] = README
    return files


def _f3_target(tmp_path: Path, rules: str, *, lock: bool = False) -> Path:
    target = tmp_path / "target-repo"
    target.mkdir()
    head = split.LOCK_RULES if lock else ""
    split._seed(
        target,
        _f3_files(),
        {"core": "acme", "app": "app"},
        head + F3_SPLIT + rules,
        split._identity("workspace", split.ACME),
        lock=lock,
    )
    return target


def _f3_answers(tmp_path: Path, name: str = "zeta.toml") -> Path:
    return split._answers(
        tmp_path,
        name,
        split._identity("workspace", split.ZETA),
        split.DEST_NAMES["workspace"],
    )


def test_f3_shape_is_refused_without_a_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _f3_target(tmp_path, "")
    assert split._press(target, _f3_answers(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "crates/acme/README.md:4" in err
    assert "{cargo_ident_<role>}" in err
    assert "P15-T10" not in err
    assert split._status(target) == ""


def test_f3_shape_presses_with_a_cargo_placeholder_rule(tmp_path: Path) -> None:
    target = _f3_target(tmp_path, REPLACE_RULES)
    assert split._press(target, _f3_answers(tmp_path)) == 0
    readme = (target / "crates/zeta-gadget/README.md").read_text()
    assert "extern crate zeta_gadget;" in readme
    assert "use zeta_gadget as c;" in readme
    split._set_origin(target, split.ZETA)
    assert verify_command(["--target", str(target)]) == 0


def test_second_press_rerenders_the_rule_from_the_rewritten_source(
    tmp_path: Path,
) -> None:
    target = _f3_target(tmp_path, REPLACE_RULES)
    assert split._press(target, _f3_answers(tmp_path)) == 0
    split._set_origin(target, split.ZETA)
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "first press")
    nova = split._identity("workspace", split.NOVA)
    second = split._answers(tmp_path, "nova.toml", nova, split.NOVA_NAMES["workspace"])
    assert split._press(target, second, "--force") == 0
    readme = (target / "crates/nova-gadget/README.md").read_text()
    assert "extern crate nova_gadget;" in readme
    split._set_origin(target, split.NOVA)
    assert verify_command(["--target", str(target)]) == 0


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_f3_shape_passes_real_cargo(tmp_path: Path) -> None:
    split._require_cargo()
    target = _f3_target(tmp_path, REPLACE_RULES, lock=True)
    split._assert_cargo(target, "test", "--offline")
    zeta = split._identity("workspace", split.ZETA)
    split._press_and_prove(target, _f3_answers(tmp_path), zeta)
    assert (target / RECEIPT_REL).is_file()
    source = tomllib.loads((target / "press/press-source.toml").read_text())
    assert source["identity"]["cargo_names"] == split.DEST_NAMES["workspace"]


# --- end to end: a non-split role ----------------------------------------------------


def test_upper_placeholder_presses_the_sibling_env_var(tmp_path: Path) -> None:
    rules = (
        '[[replace]]\npattern = "{cargo_ident_core_upper}_HOME"\n'
        'reason = "the crate owns this variable"\n'
    )
    target = disc._repo(
        tmp_path,
        {
            "Cargo.toml": disc._crate("acme-core"),
            "src/main.rs": 'fn main() { let _ = std::env::var("ACME_CORE_HOME"); }\n',
            "press/press-source.toml": disc._source_config(
                disc.CORE_MAP, app_name="acme"
            ),
            "press/press-rules.toml": rules,
        },
    )
    answers = disc._answers(tmp_path, disc.ZETA_MAP, app_name="zeta")
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert "ZETA_CORE_HOME" in (target / "src/main.rs").read_text()
    disc._git(
        target, "remote", "set-url", "origin", "https://github.com/zeta-org/zeta-core"
    )
    assert verify_command(["--target", str(target)]) == 0


# --- I1: a hyphenated render must not reach a .rs file ----------------------------

EXACT_IN_RS = (
    '\n[[replace]]\npattern = "{cargo_exact_core}::"\n'
    'files = ["crates/*/src/*.rs"]\nreason = "x"\n'
)


def test_exact_placeholder_into_rs_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _f3_target(tmp_path, REPLACE_RULES + EXACT_IN_RS)
    assert split._press(target, _f3_answers(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "crates/app/src/main.rs:2" in err
    assert "{cargo_exact_core}::" in err
    assert "{cargo_ident_core}" in err
    assert split._status(target) == ""
    assert not (target / RECEIPT_REL).exists()


def test_exact_placeholder_scoped_to_a_readme_still_presses(tmp_path: Path) -> None:
    rules = (
        REPLACE_RULES + '\n[[replace]]\npattern = "-p {cargo_exact_core}"\n'
        'files = ["README.md"]\nreason = "x"\n'
    )
    target = _f3_target(tmp_path, rules)
    assert split._press(target, _f3_answers(tmp_path)) == 0
    assert "cargo test -p zeta-gadget" in (target / "README.md").read_text()


@pytest.mark.slow
@posix_only
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_exact_placeholder_into_rs_file_never_breaks_real_cargo(
    tmp_path: Path,
) -> None:
    split._require_cargo()
    target = _f3_target(tmp_path, REPLACE_RULES + EXACT_IN_RS, lock=True)
    split._assert_cargo(target, "test", "--offline")
    assert split._press(target, _f3_answers(tmp_path)) == 2
    assert split._status(target) == ""
    split._assert_cargo(target, "test", "--offline")
