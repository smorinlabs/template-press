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
from dataclasses import replace

from template_press.rebrand.identity import VALIDATORS, Identity
from template_press.rebrand.synthesize import synthesize_dest

from .conftest import SOURCE

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SEPARATORS = ("_", "-", ".", " ", "")


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
