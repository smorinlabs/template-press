"""Identifier-aware matcher for the paranoid `press verify` scanner.

NEW module for Phase 2 (`press verify`) — deliberately SEPARATE from
`identity.token_pattern`/`token_occurs`/`replace_token`, the conservative
matcher the rewriter/doctor use to safely rewrite content in place. That
matcher requires a full alphanumeric (or separator) boundary on both sides,
so it never fires inside a bare camelCase join like ``demoWidgetConfig`` —
the right call for a rewriter, which must never corrupt unrelated text.

`press verify` has the opposite bias: it is a paranoid, read-only scanner
whose job is to flag every place source identity might still be lurking, so
false negatives (a leftover it fails to flag) are the expensive mistake, not
false positives. This matcher therefore adds one extra boundary case beyond
a full alphanumeric boundary: a lower->UPPER case transition (as in the
"Config" of "demoWidgetConfig") counts as a boundary too, so identifier-glued
camelCase variants are still caught even though there is no separator
character on the right.

Known accepted residuals (paranoid posture, not a bug — see Task 14):
- leading camelCase (``myPressConfig``) is NOT matched: there is no
  lower->UPPER transition immediately after the token itself.
- ``PressKit`` (UPPER-then-lower directly after the token, i.e. a plain
  trailing capital letter) IS matched: a trailing capital is only excluded
  from the boundary when it's the *specific* lower->UPPER transition shape;
  a leading-capital token still satisfies `(?![A-Za-z0-9])`-adjacent letter
  boundary rules for the value's own case. This is intentional for a
  scanner that would rather over-flag than miss a real leftover.
"""

from __future__ import annotations

import re

_SEP = re.compile(r"[_\-. ]+")


def identity_pattern(field: str, value: str) -> re.Pattern[str]:
    """Build the paranoid, identifier-aware pattern for one identity field.

    ``field`` is part of the stable public API (kept for provenance and to
    leave room for future per-field variation) even though the pattern body
    is currently field-uniform — every field uses the same boundary rule.

    The pattern is IGNORECASE overall (so ``PRESS_LOG`` and ``press_log``
    both match a ``press`` token), but the boundary itself has to reject a
    plain trailing-lowercase continuation like ``pressure`` while still
    accepting a lower->UPPER camelCase join like ``demoWidgetConfig``. Under
    a global IGNORECASE, a naive `(?=[A-Z])` lookahead would be folded by
    the flag and match a lowercase letter too — silently reopening the
    ``pressure`` false-positive. `(?-i:...)` locally turns IGNORECASE back
    OFF for just that alternative, so the case-transition test stays
    case-SENSITIVE even inside the outer case-insensitive pattern.
    """
    del field  # reserved for future per-field variation; uniform today.
    # ``[-_. ]*`` (zero-OR-MORE), not ``?`` (zero-or-one): a valid source value
    # with REPEATED separators (``demo__widget``, ``demo--widget``) must match
    # ITSELF, or the paranoid scanner would miss a real leak of the source
    # identity. Zero separators still matches the glued camelCase variant.
    core = "[-_. ]*".join(re.escape(t) for t in _SEP.split(value) if t)
    tail = r"(?:(?![A-Za-z0-9])|(?-i:(?<=[a-z])(?=[A-Z])))"
    return re.compile(rf"(?<![A-Za-z0-9]){core}{tail}", re.IGNORECASE)


def find_occurrences(
    text: str, field: str, value: str, *, substring: bool
) -> list[tuple[int, int]]:
    """Return (start, end) spans where `value` occurs as identity in `text`.

    ``substring=False`` (default posture): identifier-aware — iterate
    `identity_pattern` matches, honoring boundaries (rejects ``pressure``,
    matches ``demoWidgetConfig``).

    ``substring=True``: opt-in per-field escape hatch — a plain
    case-insensitive find loop over the literal `value`, with no boundary
    check at all, so glued occurrences like ``xdemo_widgety`` are also
    caught. Non-overlapping, like `identity_pattern`'s `finditer`.
    """
    if substring:
        if not value:
            # An empty needle matches at every offset — a zero-width find loop
            # would never advance. Nothing to flag; return no spans.
            return []
        # Spans are taken on the ORIGINAL text (not a `.lower()` copy): Unicode
        # case mappings can change length (e.g. `İ` -> `i` + combining dot), so
        # lowering both sides and applying the lowered offsets to the original
        # string drifts the span. `re.IGNORECASE` handles case without a second
        # string; `finditer` is non-overlapping, matching the boundary branch.
        return [m.span() for m in re.finditer(re.escape(value), text, re.IGNORECASE)]
    pattern = identity_pattern(field, value)
    return [m.span() for m in pattern.finditer(text)]
