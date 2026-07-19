"""`synthesize_dest` — deterministic, equality-preserving, containment-safe
synthetic TO-identity (Task 10, Decision 6).

Fixture identity mirrors conftest.SOURCE (package_name="demo_widget",
repo_name="demo-widget", app_name="press", author="Demo Author",
email="demo@example.com", owner="demolabs" — all six values pairwise
distinct in the base fixture, which is what the all-distinct test needs).

The variant builder below is INDEPENDENT of any variant-generation
synthesize.py might use internally — it is a black-box "reasonable
superset" of the separator/case/concat forms `matcher.identity_pattern`
and `identity.token_pattern` treat as identity-boundary matches, so the
containment-freedom test exercises the property against the same shapes a
real leak-scan would flag, not against the implementation's own idea of a
variant.
"""

from __future__ import annotations

import re
import signal
from contextlib import contextmanager
from dataclasses import replace

import pytest

from template_press.rebrand.identity import VALIDATORS, Identity, ValidationError
from template_press.rebrand.synthesize import synthesize_dest

from .conftest import SOURCE

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SEPARATORS = ("_", "-", ".", " ", "")


@contextmanager
def _bounded(seconds: int = 5):
    """Fail the test (not hang the suite) if the wrapped block doesn't
    return within `seconds` — belt-and-suspenders on top of synthesize.py's
    own `_MAX_ATTEMPTS` bound, using the same SIGALRM technique the
    adversarial review used to reproduce the original 100%-reproducible
    hang in `_safe_prefix`."""

    def _on_alarm(signum, frame):
        raise TimeoutError(f"did not complete within {seconds}s (hang?)")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _words(value: str) -> list[str]:
    """Split `value` into word tokens on separators and lower->UPPER
    transitions (mirrors the boundary shapes matcher.py treats as identity
    boundaries: separator-delimited AND camelCase-joined)."""
    words: list[str] = []
    for chunk in _WORD_RE.findall(value):
        start = 0
        for i in range(1, len(chunk)):
            if chunk[i - 1].islower() and chunk[i].isupper():
                words.append(chunk[start:i])
                start = i
        words.append(chunk[start:])
    return [w for w in words if w]


def _variants(value: str) -> set[str]:
    words = _words(value)
    forms = {value, value.lower(), value.upper()}
    if words:
        for sep in _SEPARATORS:
            forms.add(sep.join(words))
            forms.add(sep.join(w.lower() for w in words))
            forms.add(sep.join(w.upper() for w in words))
            forms.add(sep.join(w.capitalize() for w in words))
        forms.add(words[0].lower() + "".join(w.capitalize() for w in words[1:]))
        forms.add("".join(w.capitalize() for w in words))
    return {f for f in forms if f}


def source_variants(source: Identity) -> set[str]:
    variants: set[str] = set()
    for value in source.as_dict_prompted().values():
        variants.update(_variants(value))
    return variants


def test_equality_class_preserved():
    source = replace(SOURCE, app_name="demo_widget")
    dest = synthesize_dest(source)
    assert dest.package_name == dest.app_name


def test_all_distinct_source_yields_all_distinct_dest():
    values = SOURCE.as_dict_prompted().values()
    assert len(set(values)) == len(values)  # fixture sanity: base case
    dest = synthesize_dest(SOURCE)
    dest_values = list(dest.as_dict_prompted().values())
    assert len(set(dest_values)) == len(dest_values)


def test_deterministic():
    assert synthesize_dest(SOURCE) == synthesize_dest(SOURCE)


def test_containment_free_vs_variants():
    variants = {v.lower() for v in source_variants(SOURCE) if v}
    dest = synthesize_dest(SOURCE)
    for value in dest.as_dict_prompted().values():
        lowered = value.lower()
        for variant in variants:
            assert variant not in lowered, (variant, value)
            assert lowered not in variant, (variant, value)


def test_every_synth_value_is_valid():
    dest = synthesize_dest(SOURCE)
    dest.validate()  # must not raise
    for field, value in dest.as_dict_prompted().items():
        VALIDATORS[field](value)  # must not raise


def test_cross_shape_equality_class_is_valid_for_all_its_fields():
    # author and email have DISJOINT charsets in general (identifier-style
    # fields forbid '@'/'.', email requires them) but author is otherwise
    # unrestricted, so author == email is a realizable equality class whose
    # shared dest value must satisfy BOTH validators simultaneously.
    source = replace(SOURCE, author=SOURCE.email)
    source.validate()  # fixture sanity: this source is itself valid
    dest = synthesize_dest(source)
    assert dest.author == dest.email
    VALIDATORS["author"](dest.author)
    VALIDATORS["email"](dest.email)


# --- regression: single-character source value used to hang forever -------
#
# `_safe_prefix` used to build every candidate as a HARDCODED "z" literal
# plus a sha256-derived suffix. Any source field whose ENTIRE value was "z"
# (a valid package_name/repo_name/app_name/owner value — all four allow a
# bare single lowercase letter) made `_collides` reject EVERY candidate
# unconditionally, forever: "z" is a substring of any "z...." string
# regardless of what follows it, so the retry loop's varying suffix never
# mattered. Verified 100% reproducible via SIGALRM before the fix. The
# leading letter is now derived from the hash itself (not a fixed literal),
# so a colliding letter is resolved by simply trying the next attempt.


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM POSIX-only")
@pytest.mark.parametrize("field", ["owner", "package_name", "app_name", "repo_name"])
def test_single_char_field_does_not_hang(field):
    source = replace(SOURCE, **{field: "z"})
    source.validate()  # fixture sanity: "z" is a valid value for this field
    with _bounded(5):
        dest = synthesize_dest(source)

    dest.validate()  # property 3: still valid
    dest_values = dest.as_dict_prompted()
    # property 2: "z" appears in exactly this one source field, so its dest
    # value must still be a singleton (no accidental equality introduced).
    assert list(dest_values.values()).count(dest_values[field]) == 1

    # property 4: containment-free vs every variant of the source value "z".
    lowered = dest_values[field].lower()
    for variant in {v.lower() for v in _variants("z")}:
        assert variant not in lowered
        assert lowered not in variant


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM POSIX-only")
def test_bounded_cap_raises_instead_of_hanging():
    # Pathological (but constructible) input: email's `local@domain.tld`
    # shape ALWAYS contains a literal "." by construction. If some OTHER
    # source value is exactly ".", every producible email candidate
    # collides with it, forever, under the old unbounded `while True` loop.
    # The bounded retry now raises a clear, field-naming ValidationError
    # instead of hanging — defense-in-depth for inputs no amount of
    # hash-derived-letter cleverness can resolve (the "." is structural,
    # not a leading-character choice).
    source = replace(SOURCE, author=".")
    source.validate()  # fixture sanity: "." is a valid author value
    with _bounded(5), pytest.raises(ValidationError, match="email"):
        synthesize_dest(source)
