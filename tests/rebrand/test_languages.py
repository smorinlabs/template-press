"""Parsing and validation of the ``[rules] languages`` declaration."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.languages import (
    KNOWN_LANGUAGES,
    SUPPORTED_LANGUAGES,
    DetectedLanguage,
    LanguageDecision,
    check_target_languages,
    detect_languages,
    render_ignored_languages,
)
from template_press.rebrand.rules import load_rules

from .conftest import posix_only


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


# --- Detection and resolution ------------------------------------------------


def _write(target: Path, name: str, body: str | bytes) -> None:
    path = target / name
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body, encoding="utf-8")


def test_detect_counts_identity_manifests_only(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "a"\n')
    _write(tmp_path, "package.json", '{"name": "a"}')
    _write(tmp_path, "Cargo.toml", '[package]\nname = "a"\n')
    assert detect_languages(tmp_path) == (
        DetectedLanguage("python", "pyproject.toml"),
        DetectedLanguage("node", "package.json"),
        DetectedLanguage("rust", "Cargo.toml"),
    )


def test_detect_rust_workspace_counts(tmp_path: Path) -> None:
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["a"]\n')
    assert detect_languages(tmp_path) == (DetectedLanguage("rust", "Cargo.toml"),)


def test_detect_ignores_non_identity_manifests(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.x]\ny = 1\n")
    _write(tmp_path, "package.json", '{"scripts": {}}')
    _write(tmp_path, "Cargo.toml", "[dependencies]\n")
    assert detect_languages(tmp_path) == ()


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", "[project\n"),
        ("pyproject.toml", b"\xff\xfe\x00bad"),
        ("pyproject.toml", "project = 1\n"),
        ("Cargo.toml", "[package\n"),
        ("Cargo.toml", "package = 1\n"),
        ("Cargo.toml", "workspace = []\n"),
        ("package.json", "{not json"),
        ("package.json", b"\xff\xfe\x00bad"),
        ("package.json", "[]"),
        ("package.json", '{"name": 1}'),
        ("package.json", '{"name": ""}'),
        ("package.json", "[" * 100000),
        ("pyproject.toml", "a = " + "[" * 100000),
    ],
)
def test_detect_refuses_malformed(tmp_path: Path, name: str, body: str | bytes) -> None:
    _write(tmp_path, name, body)
    with pytest.raises(ValidationError, match=re.escape(name)):
        detect_languages(tmp_path)


@posix_only
def test_detect_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.toml"
    real.write_text('[project]\nname = "a"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").symlink_to(real)
    with pytest.raises(ValidationError, match=r"pyproject\.toml"):
        detect_languages(tmp_path)


def test_detect_refuses_directory_manifest(tmp_path: Path) -> None:
    (tmp_path / "package.json").mkdir()
    with pytest.raises(ValidationError, match=r"package\.json"):
        detect_languages(tmp_path)


def _py_and_node(target: Path) -> None:
    _write(target, "pyproject.toml", '[project]\nname = "a"\n')
    _write(target, "package.json", '{"name": "a"}')


def test_undeclared_multi_language_refused(tmp_path: Path) -> None:
    _py_and_node(tmp_path)
    with pytest.raises(ValidationError) as exc:
        check_target_languages(tmp_path, None, [])
    message = str(exc.value)
    assert "pyproject.toml" in message
    assert "package.json" in message
    assert 'languages = ["python"]' in message


def test_undeclared_multi_language_unsupported_has_no_paste_line(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", '{"name": "a"}')
    _write(tmp_path, "Cargo.toml", '[package]\nname = "a"\n')
    with pytest.raises(ValidationError) as exc:
        check_target_languages(tmp_path, None, [])
    message = str(exc.value)
    assert "package.json" in message
    assert "Cargo.toml" in message
    assert "only python" in message
    assert "languages = [" not in message


def test_single_language_undeclared_continues(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "a"\n')
    decision = check_target_languages(tmp_path, None, [])
    assert decision.checked == ("python",)
    assert decision.ignored == ()


def test_no_manifest_continues(tmp_path: Path) -> None:
    decision = check_target_languages(tmp_path, None, [])
    assert decision == LanguageDecision(checked=(), ignored=())


def test_declared_subset_ignores_rest(tmp_path: Path) -> None:
    _py_and_node(tmp_path)
    decision = check_target_languages(tmp_path, ("python",), [])
    assert decision.checked == ("python",)
    assert decision.ignored == (DetectedLanguage("node", "package.json"),)
    assert render_ignored_languages(decision) == [
        "ignored node (package.json): not declared in [rules] languages"
    ]


def test_render_ignored_languages_empty() -> None:
    assert render_ignored_languages(LanguageDecision(("python",), ())) == []


def test_declared_without_manifest_refused(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name": "a"}')
    with pytest.raises(ValidationError, match=r"python.*pyproject\.toml"):
        check_target_languages(tmp_path, ("python",), [])


@pytest.mark.parametrize(
    "removed", ["pyproject.toml", "PYPROJECT.TOML", "pyproject.toml. "]
)
def test_declared_manifest_removed_refused(tmp_path: Path, removed: str) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "a"\n')
    with pytest.raises(ValidationError, match=r"python.*pyproject\.toml"):
        check_target_languages(tmp_path, ("python",), [removed])
