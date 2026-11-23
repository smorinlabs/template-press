"""Declared names that are independent of the template identity (keep_names).

A kept occurrence survives every rewrite row. This module is neutral on
purpose: ``verifier.py`` derives kept spans from ``Rules`` through it, so it
must never import ``substitutions``, ``engine``, or ``doctor`` (design 0008,
independence guardrail).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    display_forms,
    token_pattern,
)

Span = tuple[int, int]


def kept_spans(text: str, names: Sequence[str]) -> tuple[Span, ...]:
    """Sorted spans of each exact name, using the ``npm_name`` boundaries.

    Spans of different names are never merged: a match is kept only when one
    declared name wholly contains it.
    """
    spans: set[Span] = set()
    for name in names:
        pattern = token_pattern("npm_name", name)
        if pattern is not None:
            spans.update(match.span() for match in pattern.finditer(text))
    return tuple(sorted(spans))


def outside_kept(spans: Iterable[Span], kept: Sequence[Span]) -> list[Span]:
    """Drop only spans wholly inside one kept span; an overlap is still a leak."""
    return [
        (start, end)
        for start, end in spans
        if not any(low <= start and end <= high for low, high in kept)
    ]


def disjoint_from_kept(span: Span, kept: Sequence[Span]) -> bool:
    """True when the half-open ``span`` shares no character with any kept span."""
    start, end = span
    return all(end <= low or start >= high for low, high in kept)


def component_kept_spans(
    parts: Sequence[str], index: int, names: Sequence[str]
) -> tuple[Span, ...]:
    """Kept spans of ``parts[index]``, in that component's own coordinates.

    Names are matched over the joined path, so a scoped name that spans two
    components is found and each component's boundaries see true neighbors.
    """
    offset = sum(len(part) + 1 for part in parts[:index])
    length = len(parts[index])
    clipped = {
        (max(start - offset, 0), min(end - offset, length))
        for start, end in kept_spans("/".join(parts), names)
        if start < offset + length and end > offset
    }
    return tuple(sorted(clipped))


def _identity_forms(identity: Identity) -> frozenset[str]:
    forms = set(identity.as_dict().values())
    forms.add(identity.package_name.replace("_", "-"))
    if identity.display_name is not None:
        forms.update(display_forms(identity.display_name).values())
    return frozenset(forms)


def validate_keep_names(
    names: Sequence[str],
    source: Identity,
    dest: Identity,
    *,
    synthetic_dest: bool = False,
) -> None:
    """Refuse an entry that is malformed or is itself an identity value.

    ``synthetic_dest`` is for ``press verify``. Its destination is generated,
    so the user cannot choose around an equality with it, and that comparison
    is skipped. Shape and source checks are identical in both commands.
    """
    source_forms = _identity_forms(source)
    dest_forms = frozenset() if synthetic_dest else _identity_forms(dest)
    for name in names:
        if not isinstance(name, str):
            raise ValidationError(f"keep_names entry must be a string: {name!r}")
        if not name.strip():
            raise ValidationError(f"keep_names entry must not be empty: {name!r}")
        if any(ord(ch) < 0x20 or ch == "\x7f" for ch in name):
            raise ValidationError(
                f"keep_names entry must not contain control characters: {name!r}"
            )
        if name in source_forms:
            raise ValidationError(
                f"keep_names entry {name!r} equals a source identity value; "
                f"an identity value cannot be kept"
            )
        if name in dest_forms:
            raise ValidationError(
                f"keep_names entry {name!r} equals a destination identity value; "
                f"an identity value cannot be kept"
            )
