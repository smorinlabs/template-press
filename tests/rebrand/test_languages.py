"""Parsing and validation of the ``[rules] languages`` declaration."""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.languages import KNOWN_LANGUAGES, SUPPORTED_LANGUAGES
from template_press.rebrand.rules import load_rules


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def test_language_constants() -> None:
    assert KNOWN_LANGUAGES == ("python", "node", "rust")
    assert SUPPORTED_LANGUAGES == frozenset({"python"})


def test_rules_languages_defaults_to_none(tmp_path: Path) -> None:
    target = _write_rules(tmp_path, "[rules]\n")
    assert load_rules(target).languages is None


def test_rules_languages_parsed(tmp_path: Path) -> None:
    target = _write_rules(tmp_path, '[rules]\nlanguages = ["python"]\n')
    assert load_rules(target).languages == ("python",)


@pytest.mark.parametrize(
    "value",
    ["[]", '["python", "python"]', '["perl"]', '"python"', "[1]"],
)
def test_rules_languages_rejects(tmp_path: Path, value: str) -> None:
    target = _write_rules(tmp_path, f"[rules]\nlanguages = {value}\n")
    with pytest.raises(ValidationError, match="languages"):
        load_rules(target)


@pytest.mark.parametrize("value", ['["node"]', '["python", "rust"]'])
def test_rules_languages_reserved_not_supported(tmp_path: Path, value: str) -> None:
    target = _write_rules(tmp_path, f"[rules]\nlanguages = {value}\n")
    with pytest.raises(ValidationError, match="not supported by this press version"):
        load_rules(target)
