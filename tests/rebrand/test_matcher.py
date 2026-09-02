"""Identifier-aware matcher for the paranoid `press verify` scanner.

Separate from identity.token_pattern (the conservative rewriter/doctor
matcher): this matcher additionally treats a lower->UPPER case transition
as a boundary, so identifier-glued variants like ``demoWidgetConfig`` are
caught even though there is no separator character. fixture app_name=
``press``, package=``demo_widget`` (mirrors conftest.SOURCE).
"""

from template_press.rebrand.matcher import classify_occurrence, find_occurrences


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


def test_repeated_separators_match_source_value():
    # A valid source value with REPEATED separators must match ITSELF: the
    # token join is zero-or-more separators (`[-_. ]*`), not at-most-one — a
    # `demo__widget`/`demo--widget` leak of the source identity must be caught.
    for s in ("demo__widget", "demo--widget", "demo..widget", "demo  widget"):
        assert find_occurrences(s, "package_name", "demo_widget", substring=False), s


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


# --- spec E9(b): whole-token vs separator-joined-prefix classification ----


def test_classify_occurrence_prefix_of_a_longer_token():
    # "demo-widget-2" (template renamed upstream): the match is immediately
    # followed by "-2" — a separator, then an alphanumeric.
    span = find_occurrences(
        "see demo-widget-2 docs", "repo_name", "demo-widget", substring=False
    )[0]
    assert classify_occurrence("see demo-widget-2 docs", span) == (
        "prefix",
        "demo-widget-2",
    )


def test_classify_occurrence_whole_token():
    for text in ("demo-widget", "demo-widget end", "demo-widget."):
        span = find_occurrences(text, "repo_name", "demo-widget", substring=False)[0]
        assert classify_occurrence(text, span) == ("whole", "")


def test_classify_occurrence_trailing_separator_with_no_continuation():
    # A separator with nothing alphanumeric after it (end of string) is not
    # a continuation — the match still stands on its own.
    assert classify_occurrence("demo-widget-", (0, 11)) == ("whole", "")


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


# --- substring mode: Unicode-safe spans + empty guard (D3) ----------------


def test_substring_ascii_case_spans_slice_back():
    text = "the PRESS release for press"
    spans = find_occurrences(text, "app_name", "press", substring=True)
    assert spans  # case-insensitive substring finds both PRESS and press
    for start, end in spans:
        assert text[start:end].lower() == "press"
    # first hit is the uppercase PRESS at index 4 — span slices it exactly
    assert text[spans[0][0] : spans[0][1]] == "PRESS"


def test_substring_unicode_case_spans_do_not_drift():
    # `İ` (U+0130) lowercases to TWO code points (i + combining dot above), so
    # a naive text.lower()/value.lower() offset drifts and slices the wrong
    # substring out of the ORIGINAL text. Spans must slice back to the match.
    text = "İ press"  # "İ press"
    spans = find_occurrences(text, "app_name", "press", substring=True)
    assert spans
    for start, end in spans:
        assert text[start:end] == "press"


def test_substring_empty_value_returns_empty():
    # An empty needle must return [] — not loop forever on find("", ...).
    assert find_occurrences("anything at all", "app_name", "", substring=True) == []
