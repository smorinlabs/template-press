"""P10-TS01 — ``[[clean]]`` schema and config-load validation (E10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    CleanRule,
    load_rules,
    load_selected_rules,
)


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


CLEAN_SRC_TESTS = '[[clean]]\npaths = ["src/{package_name}", "tests"]\n'


def test_valid_entry_parses_unrendered(tmp_path: Path):
    target = _write_rules(tmp_path, CLEAN_SRC_TESTS)
    (rule,) = load_rules(target).clean
    assert isinstance(rule, CleanRule)
    assert rule.paths == ("src/{package_name}", "tests")


def test_absent_table_and_defaults_yield_no_rules(tmp_path: Path):
    assert DEFAULT_RULES.clean == ()
    target = _write_rules(tmp_path, "[rules]\n")
    assert load_rules(target).clean == ()


def test_unknown_root_table_still_fails_loud(tmp_path: Path):
    target = _write_rules(tmp_path, '[[cleanup]]\npaths = ["x"]\n')
    with pytest.raises(ValidationError, match="unknown root-level table"):
        load_rules(target)


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ('clean = "src"\n', "must be an array of tables"),
        ("[[clean]]\n", "paths must be a non-empty list of strings"),
        ("[[clean]]\npaths = []\n", "paths must be a non-empty list of strings"),
        ('[[clean]]\npaths = "src"\n', "paths must be a non-empty list of strings"),
        (
            '[[clean]]\npaths = ["src", 3]\n',
            "paths must be a non-empty list of strings",
        ),
        ('[[clean]]\npaths = ["src"]\nreason = "x"\n', "unknown key"),
        ('[[clean]]\npaths = ["/abs"]\n', "paths"),
        ('[[clean]]\npaths = ["../up"]\n', "paths"),
        ('[[clean]]\npaths = ["src\\u001b"]\n', "control characters"),
        ('[[clean]]\npaths = ["src/{nope}"]\n', "unknown placeholder"),
        ('[[clean]]\npaths = ["src/{App_Name}"]\n', "unknown placeholder"),
        ('[[clean]]\npaths = ["src/{package_name"]\n', "unbalanced or nested brace"),
        ('[[clean]]\npaths = ["src/package_name}"]\n', "unbalanced or nested brace"),
        (
            '[[clean]]\npaths = ["src/{a{package_name}}"]\n',
            "unbalanced or nested brace",
        ),
        ('[[clean]]\npaths = ["src", "src"]\n', "duplicate"),
        ('[[clean]]\npaths = ["src"]\nplatforms = []\n', "platforms must be"),
        ('[[clean]]\npaths = ["src"]\nplatforms = ["plan9"]\n', "platforms values"),
    ],
)
def test_malformed_entries_refuse(tmp_path: Path, body: str, fragment: str):
    target = _write_rules(tmp_path, body)
    with pytest.raises(ValidationError, match=fragment):
        load_rules(target)


def test_platform_selection_makes_a_foreign_rule_inert(tmp_path: Path):
    target = _write_rules(
        tmp_path,
        '[[clean]]\npaths = ["build"]\nplatforms = ["win32"]\n'
        '[[clean]]\npaths = ["dist"]\n',
    )
    darwin = load_selected_rules(target, platform="darwin").rules.clean
    win32 = load_selected_rules(target, platform="win32").rules.clean
    assert [rule.paths for rule in darwin] == [("dist",)]
    assert [rule.paths for rule in win32] == [("build",), ("dist",)]


def test_clean_coexists_with_every_other_mechanism(tmp_path: Path):
    target = _write_rules(
        tmp_path,
        CLEAN_SRC_TESTS
        + '[[edit]]\nfile = "pyproject.toml"\ncommand = ["uv", "version", "0.1.0"]\n'
        "expect = 'version = \"0.1.0\"'\n"
        '[[remove]]\nfile = "docs/old.md"\nreason = "history"\n',
    )
    rules = load_rules(target)
    assert rules.clean[0].paths == ("src/{package_name}", "tests")
    assert rules.edit[0].file == "pyproject.toml"
    assert rules.remove[0].file == "docs/old.md"
