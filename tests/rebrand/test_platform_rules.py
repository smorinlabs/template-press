"""P07-TS01 — platform selector parsing, selection, and overlap validation."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from template_press.rebrand import rules as rules_module
from template_press.rebrand.identity import ValidationError

SUPPORTED = frozenset({"darwin", "linux", "win32"})


def _write_rules(target: Path, body: str) -> Path:
    press = target / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def _load_selected(target: Path, platform: str):
    return rules_module.load_selected_rules(target, platform=platform)


def _regenerate(file: str, command: str, platforms: str | None = None) -> str:
    selector = "" if platforms is None else f"platforms = {platforms}\n"
    return f'[[regenerate]]\nfile = "{file}"\ncommand = ["{command}"]\n{selector}'


def _reset(file: str, stub: str, platforms: str | None = None) -> str:
    selector = "" if platforms is None else f"platforms = {platforms}\n"
    return f'[[reset]]\nfile = "{file}"\nstub = "{stub}"\n{selector}'


def test_supported_platform_vocabulary_is_exact() -> None:
    assert rules_module.SUPPORTED_PLATFORMS == SUPPORTED


@pytest.mark.parametrize("platform", sorted(SUPPORTED))
def test_exact_platform_value_selects_matching_declaration(
    tmp_path: Path, platform: str
) -> None:
    body = "".join(
        _regenerate("bun.lock", candidate, f'["{candidate}"]')
        for candidate in ("darwin", "linux", "win32")
    )

    selected = _load_selected(_write_rules(tmp_path, body), platform)

    assert selected.platform == platform
    assert [rule.command for rule in selected.rules.regenerate] == [(platform,)]
    assert not hasattr(selected.rules.regenerate[0], "platforms")


@pytest.mark.parametrize("platform", sorted(SUPPORTED))
def test_omitted_selector_is_active_on_all_supported_platforms(
    tmp_path: Path, platform: str
) -> None:
    target = _write_rules(
        tmp_path,
        _regenerate("bun.lock", "regen") + _reset("CHANGELOG.md", "# Changelog\\n"),
    )

    selected = _load_selected(target, platform)

    assert [rule.file for rule in selected.rules.regenerate] == ["bun.lock"]
    assert [rule.file for rule in selected.rules.reset] == ["CHANGELOG.md"]


@pytest.mark.parametrize("kind", ["regenerate", "reset"])
@pytest.mark.parametrize(
    "selector",
    [
        "[]",
        '"darwin"',
        "[3]",
        "[true]",
        '["darwin", 3]',
        '["darwin", true]',
        '["darwin", "darwin"]',
        '["freebsd14"]',
        '["Darwin"]',
        '[" darwin"]',
        '["darwin "]',
    ],
)
def test_malformed_selector_is_rejected_before_selection(
    tmp_path: Path, kind: str, selector: str
) -> None:
    body = (
        _regenerate("bun.lock", "regen", selector)
        if kind == "regenerate"
        else _reset("CHANGELOG.md", "clean", selector)
    )

    with pytest.raises(ValidationError, match="platforms"):
        _load_selected(_write_rules(tmp_path, body), "darwin")


def test_inactive_regenerate_schema_is_still_validated(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path,
        _regenerate("bun.lock", "valid", '["darwin"]') + "[[regenerate]]\n"
        'file = "uv.lock"\n'
        'command = "powershell script.ps1"\n'
        'platforms = ["win32"]\n',
    )

    with pytest.raises(ValidationError, match="command"):
        _load_selected(target, "darwin")


def test_inactive_reset_schema_is_still_validated(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path,
        _reset("CHANGELOG.md", "clean", '["darwin"]') + "[[reset]]\n"
        'file = "bun.lock"\n'
        "stub = 3\n"
        'platforms = ["win32"]\n',
    )

    with pytest.raises(ValidationError, match="stub"):
        _load_selected(target, "darwin")


def test_disjoint_same_file_regenerations_are_selected_in_place(
    tmp_path: Path,
) -> None:
    target = _write_rules(
        tmp_path,
        _regenerate("bun.lock", "posix", '["darwin", "linux"]')
        + _regenerate("bun.lock", "windows", '["win32"]'),
    )

    assert _load_selected(target, "linux").rules.regenerate[0].command == ("posix",)
    assert _load_selected(target, "win32").rules.regenerate[0].command == ("windows",)


def test_disjoint_same_file_resets_are_allowed(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path,
        _reset("CHANGELOG.md", "posix", '["darwin", "linux"]')
        + _reset("CHANGELOG.md", "windows", '["win32"]'),
    )

    assert _load_selected(target, "darwin").rules.reset[0].stub == "posix"
    assert _load_selected(target, "win32").rules.reset[0].stub == "windows"


def test_disjoint_reset_and_regenerate_for_same_file_are_allowed(
    tmp_path: Path,
) -> None:
    target = _write_rules(
        tmp_path,
        _reset("bun.lock", "posix", '["darwin", "linux"]')
        + _regenerate("bun.lock", "windows", '["win32"]'),
    )

    assert [rule.file for rule in _load_selected(target, "linux").rules.reset] == [
        "bun.lock"
    ]
    assert [rule.file for rule in _load_selected(target, "win32").rules.regenerate] == [
        "bun.lock"
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            _regenerate("bun.lock", "first", '["darwin", "linux"]'),
            _regenerate("bun.lock", "second", '["linux", "win32"]'),
        ),
        (
            _reset("CHANGELOG.md", "first", '["darwin", "linux"]'),
            _reset("CHANGELOG.md", "second", '["linux", "win32"]'),
        ),
        (
            _reset("bun.lock", "reset", '["darwin", "linux"]'),
            _regenerate("bun.lock", "regen", '["linux", "win32"]'),
        ),
        (
            _regenerate("bun.lock", "all"),
            _reset("bun.lock", "windows", '["win32"]'),
        ),
    ],
)
def test_overlapping_writers_are_rejected_globally(
    tmp_path: Path, first: str, second: str
) -> None:
    with pytest.raises(ValidationError, match="overlap"):
        _load_selected(_write_rules(tmp_path, first + second), "darwin")


def test_active_declarations_preserve_source_order(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path,
        '[rules]\nextra_exclude_files = ["z.lock", "a.lock"]\n'
        + _regenerate("z.lock", "z", '["darwin"]')
        + _regenerate("a.lock", "a", '["darwin"]')
        + _reset("CHANGELOG.md", "first", '["darwin"]')
        + _reset("bun.lock", "second", '["darwin"]'),
    )

    rules = _load_selected(target, "darwin").rules

    assert [rule.file for rule in rules.regenerate] == ["z.lock", "a.lock"]
    assert [rule.file for rule in rules.reset] == ["CHANGELOG.md", "bun.lock"]


def test_configuration_without_selectors_keeps_existing_rules_view(
    tmp_path: Path,
) -> None:
    target = _write_rules(
        tmp_path,
        _regenerate("bun.lock", "regen") + _reset("CHANGELOG.md", "clean"),
    )

    selected = _load_selected(target, "darwin")

    assert selected.rules == rules_module.load_rules(target)


def test_selected_rules_is_immutable(tmp_path: Path) -> None:
    selected = _load_selected(tmp_path, "darwin")

    with pytest.raises(dataclasses.FrozenInstanceError):
        selected.platform = "linux"


def test_unsupported_runtime_is_rejected_before_selection(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match=r"unsupported.*freebsd14"):
        _load_selected(tmp_path, "freebsd14")


def test_schema_error_precedes_unsupported_runtime_error(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path,
        _regenerate("bun.lock", "regen", '["not-a-platform"]'),
    )

    with pytest.raises(ValidationError, match="platforms"):
        _load_selected(target, "freebsd14")
