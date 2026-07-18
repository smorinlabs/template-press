"""Identifier-aware matcher for the paranoid `press verify` scanner.

Separate from identity.token_pattern (the conservative rewriter/doctor
matcher): this matcher additionally treats a lower->UPPER case transition
as a boundary, so identifier-glued variants like ``demoWidgetConfig`` are
caught even though there is no separator character. fixture app_name=
``press``, package=``demo_widget`` (mirrors conftest.SOURCE).
"""

from template_press.rebrand.matcher import find_occurrences


def test_word_traps_not_matched():
    for w in ("compress", "express", "pressure", "Pressure", "PRESSURE"):
        assert find_occurrences(w, "app_name", "press", substring=False) == []


def test_variants_matched():
    for s in ("0001-x-press.md", "PRESS_LOG", "demo-widget_x", "demoWidgetConfig"):
        assert find_occurrences(
            s,
            "package_name" if "widget" in s.lower() else "app_name",
            "demo_widget" if "widget" in s.lower() else "press",
            substring=False,
        )


def test_glued_only_with_substring():
    assert (
        find_occurrences(
            "xdemo_widgety", "package_name", "demo_widget", substring=False
        )
        == []
    )
    assert find_occurrences(
        "xdemo_widgety", "package_name", "demo_widget", substring=True
    )


# --- 5.5 property test: no false positives over an unrelated wordlist -----
#
# Deterministic (no `random`/time): a fixed, modest wordlist of plain English
# words plus a few code-like tokens, none of which are the identity values
# ("press", "demo_widget") or any separator variant of them — those SHOULD
# match, so including them here would make this a contradiction, not a
# property test. The word-trap set doubles down on the specific English
# words that legitimately contain "press" as a substring (compress, express,
# pressure, impression, ...), since those are exactly the boundary-safety
# regressions this matcher exists to keep closed.
_UNRELATED_WORDS = (
    # plain English words unrelated to either identity value
    "banana",
    "keyboard",
    "umbrella",
    "wardrobe",
    "sunlight",
    "gravity",
    "mountain",
    "octopus",
    "calendar",
    "telephone",
    # English words that contain "press" as a substring (the classic traps)
    "compress",
    "compressed",
    "compressor",
    "express",
    "expression",
    "impression",
    "impressive",
    "pressure",
    "pressurize",
    "depression",
    "repress",
    "suppress",
    "espresso",
    # code-like tokens unrelated to "demo_widget"
    "widget_demo",  # reversed token order, not the identity value
    "widgetDemo",  # reversed camelCase order, not the identity value
    "gizmo_gadget",
    "acme_toolkit",
    "sample_module",
    "config_loader",
)


def test_wordlist_has_no_false_positives():
    for word in _UNRELATED_WORDS:
        assert find_occurrences(word, "app_name", "press", substring=False) == [], word
        assert (
            find_occurrences(word, "package_name", "demo_widget", substring=False) == []
        ), word
