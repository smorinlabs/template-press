from pathlib import Path

from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_clean_rebrand_has_no_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_content_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "notes.md").write_text(
        "demo_widget survived here\n", encoding="utf-8"
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "notes.md" and e.field == "package_name" and e.where == "content"
        for e in leaks
    )


def test_path_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "demo_widget_old.txt").write_text("x", encoding="utf-8")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(e.where == "path" for e in leaks)


def test_english_press_words_are_not_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    # README still contains Compress/express/pressure — must NOT count
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_render_leak_report_is_actionable():
    from template_press.rebrand.doctor import Leak

    text = render_leak_report(
        [Leak(path="a.md", field="app_name", value="press", where="content")]
    )
    assert "a.md" in text and "press" in text


def test_app_name_upper_path_leak_detected(src_target: Path):
    """Surviving uppercase app tokens in paths should be detected as leaks."""
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "PRESS_NOTES.md").write_text("x", encoding="utf-8")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "PRESS_NOTES.md" and e.field == "app_name_upper" and e.where == "path"
        for e in leaks
    )


def test_unreadable_file_fails_verification(src_target: Path):
    import os

    if os.name == "nt" or os.geteuid() == 0:
        import pytest

        pytest.skip("permission semantics differ on Windows/root")
    from template_press.rebrand.engine import apply
    from template_press.rebrand.rules import DEFAULT_RULES

    from .conftest import DEST, SOURCE

    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    secret = src_target / "unreadable.md"
    secret.write_text("clean content\n", encoding="utf-8")
    secret.chmod(0o000)
    try:
        leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    finally:
        secret.chmod(0o644)
    assert any(e.where == "unverifiable" for e in leaks)
