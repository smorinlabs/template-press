"""Declared names that are independent of the template identity (keep_names).

A kept occurrence survives every rewrite row on content, path, and symlink
surfaces, and every leak scan ignores a match wholly inside one. This module
also finds undeclared same-prefix names before a press writes anything.

It is neutral on purpose: ``verifier.py`` derives kept spans from ``Rules``
through it, so it imports only the standard library, ``identity``, and
``matcher``. It must never import ``substitutions``, ``engine``, or ``doctor``
(design 0008, independence guardrail). Callers read the target and pass
surface text in.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    display_forms,
    token_pattern,
)
from template_press.rebrand.matcher import (
    classify_occurrence,
    find_occurrences,
    identity_pattern,
)

Span = tuple[int, int]

_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)
_REFUSED_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})
_NORMALIZED_AWAY = str.maketrans("", "", "-_. ")
_REPORT_LIMIT = 20
# The case-sensitive lower-to-upper tail of ``matcher.identity_pattern``.
_CAMEL_TAIL = re.compile(r"[a-z][A-Z]")


@dataclass(frozen=True)
class UndeclaredName:
    """A token holding a declared name inside a longer, undeclared name."""

    path: str
    where: str  # "content" | "path" | "symlink"
    field: str  # "npm_name" | "cli_name"
    token: str


@dataclass(frozen=True)
class KeepCheck:
    """The preflight result over one target's rewrite surface."""

    undeclared: tuple[UndeclaredName, ...]
    stale: tuple[str, ...]


@dataclass(frozen=True)
class RewrittenForms:
    """What the compiled rows actually rewrite on one surface subject.

    ``tokens`` are identity values, matched with name boundaries. ``literals``
    are rendered ``[[replace]]`` sources, matched exactly.
    """

    tokens: frozenset[str] = frozenset()
    literals: frozenset[str] = frozenset()


# Called with (path, where, text) for one surface row.
RewrittenLookup = Callable[[str, str, str], RewrittenForms]


def kept_spans(text: str, names: Sequence[str]) -> tuple[Span, ...]:
    """Sorted spans of each exact name, using the ``npm_name`` boundaries.

    Occurrences of one name may overlap (``a.a`` twice in ``a.a.a``). Spans of
    different names are never merged: a match is kept only when one declared
    name wholly contains it.
    """
    spans: set[Span] = set()
    for name in names:
        pattern = token_pattern("npm_name", name)
        if pattern is None:
            continue
        position = 0
        while (match := pattern.search(text, position)) is not None:
            spans.add(match.span())
            position = match.start() + 1
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


def matches_outside_kept(
    pattern: re.Pattern[str], text: str, kept: Sequence[Span]
) -> list[Span]:
    """Matches not wholly inside a kept span.

    A dropped match advances one character, so it cannot shadow an overlapping
    occurrence that is a real leak.
    """
    spans: list[Span] = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        if outside_kept((match.span(),), kept):
            spans.append(match.span())
            position = max(match.end(), match.start() + 1)
        else:
            position = match.start() + 1
    return spans


def find_outside_kept(
    text: str,
    field: str,
    value: str,
    *,
    substring: bool,
    kept: Sequence[Span],
) -> list[Span]:
    """``matcher.find_occurrences`` minus matches wholly inside a kept span."""
    if not kept:
        return find_occurrences(text, field, value, substring=substring)
    if substring:
        if not value:
            return []
        pattern = re.compile(re.escape(value), re.IGNORECASE)
    else:
        pattern = identity_pattern(field, value)
    return matches_outside_kept(pattern, text, kept)


def literal_occurs(text: str, needle: str, kept: Sequence[Span]) -> bool:
    """Whether the exact ``needle`` occurs outside every kept span."""
    if not kept:
        return needle in text
    return bool(matches_outside_kept(re.compile(re.escape(needle)), text, kept))


def disjoint_matches(
    pattern: re.Pattern[str], text: str, kept: Sequence[Span]
) -> list[Span]:
    """Rewritable matches: those sharing no character with a kept span.

    A suppressed match advances one character, so it cannot shadow a disjoint
    occurrence that overlaps it.
    """
    spans: list[Span] = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        if disjoint_from_kept(match.span(), kept):
            spans.append(match.span())
            position = match.end()
        else:
            position = match.start() + 1
    return spans


def splice_outside_kept(
    text: str,
    spans: Sequence[Span],
    replacement: str,
    kept: Sequence[Span],
) -> tuple[str, tuple[Span, ...]]:
    """Replace sorted disjoint ``spans``; return text and shifted kept spans."""
    pieces: list[str] = []
    copied = 0
    for start, end in spans:
        pieces += [text[copied:start], replacement]
        copied = end
    pieces.append(text[copied:])
    shifted = tuple(
        (low + delta, high + delta)
        for low, high in kept
        for delta in (
            sum(len(replacement) - (end - start) for start, end in spans if end <= low),
        )
    )
    return "".join(pieces), shifted


def _identity_forms(identity: Identity) -> frozenset[str]:
    forms = set(identity.as_dict().values())
    forms.add(identity.package_name.replace("_", "-"))
    if identity.display_name is not None:
        forms.update(display_forms(identity.display_name).values())
    return frozenset(forms)


def _normalized(value: str) -> str:
    return value.casefold().translate(_NORMALIZED_AWAY)


def _is_identity_spelling(name: str, forms: frozenset[str]) -> bool:
    """Exact form, or a normalized match for a name with no edge ``-`` or ``_``.

    An edge separator makes a distinct token: ``--acme-cli`` is not ``acme-cli``.
    """
    if name in forms:
        return True
    if name[0] in "-_" or name[-1] in "-_":
        return False
    return _normalized(name) in {_normalized(form) for form in forms}


def validate_keep_names(
    names: Sequence[str],
    source: Identity,
    dest: Identity,
    *,
    synthetic_dest: bool = False,
) -> None:
    """Refuse an entry that is malformed or is a spelling of an identity value.

    Entries and identity forms are compared after case-folding and removing
    ``-``, ``_``, ``.``, and spaces, unless the entry starts or ends with ``-``
    or ``_``; such an entry is refused only on exact equality. ``synthetic_dest`` is for ``press
    verify``. Its destination is generated, so the user cannot choose around
    an equality with it, and that comparison is skipped. Shape and source
    checks are identical in both commands.
    """
    source_forms = _identity_forms(source)
    dest_forms = frozenset() if synthetic_dest else _identity_forms(dest)
    for name in names:
        if not isinstance(name, str):
            raise ValidationError(f"keep_names entry must be a string: {name!r}")
        if not name.strip():
            raise ValidationError(f"keep_names entry must not be empty: {name!r}")
        if any(unicodedata.category(ch) in _REFUSED_CATEGORIES for ch in name):
            raise ValidationError(
                f"keep_names entry must not contain control characters: {name!r}"
            )
        if _is_identity_spelling(name, source_forms):
            raise ValidationError(
                f"keep_names entry {name!r} equals a source identity value; "
                f"an identity value cannot be kept"
            )
        if _is_identity_spelling(name, dest_forms):
            raise ValidationError(
                f"keep_names entry {name!r} equals a destination identity value; "
                f"an identity value cannot be kept"
            )


def _keep_line(token: str) -> str:
    return f"keep_names = {json.dumps([token])}"


def sibling_guidance(text: str, span: Span) -> str | None:
    """The ``keep_names`` line for a match that prefixes a longer name."""
    kind, _token = classify_occurrence(text, span)
    if kind != "prefix":
        return None
    start, end = span
    while end < len(text) and text[end] in _NAME_CHARS:
        end += 1
    return _keep_line(text[start:end])


def _literal_spans(text: str, literals: Iterable[str]) -> list[Span]:
    spans: list[Span] = []
    for literal in literals:
        position = text.find(literal)
        while position != -1:
            spans.append((position, position + len(literal)))
            position = text.find(literal, position + 1)
    return spans


def _joined(part: str, separator: str) -> bool:
    """Whether ``part`` holds a name part joined by its adjacent ``-`` or ``_``."""
    return separator in ("-", "_") and any(ch not in "-_" for ch in part)


def _sibling_tokens(
    text: str,
    value: str,
    identity_forms: frozenset[str],
    rewritten: RewrittenForms,
    kept: Sequence[Span],
) -> list[str]:
    """Tokens joining ``value`` to another name part, unless a row rewrites them.

    ``-``, ``_``, and a right-side lower-to-upper transition join names, so
    ``tscConfig`` is a sibling of ``tsc``. An alphanumeric glued to either side
    puts the match inside an unrelated word, so ``vite-tsconfig-paths`` is not.
    A multi-part value (holding ``-``, ``_``, or ``/``) is not word-like, so any
    name character touching it makes a sibling: ``acme-cli2``, ``xacme-cli``.
    A glued token is still reported when it is exactly an identity form that no
    row rewrites on this surface, because that form would survive the press.
    """
    tokens: list[str] = []
    occupied: list[Span] | None = None
    unrewritten = identity_forms - rewritten.tokens
    multi_part = any(separator in value for separator in "-_/")
    pattern = re.compile(re.escape(value), re.IGNORECASE)
    position = 0
    while (match := pattern.search(text, position)) is not None:
        position = match.start() + 1
        start, end = match.span()
        while start > 0 and text[start - 1] in _NAME_CHARS:
            start -= 1
        while end < len(text) and text[end] in _NAME_CHARS:
            end += 1
        if (start, end) == match.span():
            continue
        left, right = text[start : match.start()], text[match.end() : end]
        token = text[start:end]
        camel_tail = _CAMEL_TAIL.match(text, match.end() - 1) is not None
        inside_word = text[match.start() - 1 : match.start()].isalnum() or (
            text[match.end() : match.end() + 1].isalnum() and not camel_tail
        )
        is_join = _joined(left, left[-1:]) or _joined(right, right[:1]) or camel_tail
        if not (multi_part or (is_join and not inside_word) or token in unrewritten):
            continue
        if not outside_kept(((start, end),), kept):
            continue
        if occupied is None:
            occupied = [
                *kept_spans(text, tuple(rewritten.tokens)),
                *_literal_spans(text, rewritten.literals),
            ]
        if not outside_kept(((start, end),), occupied):
            continue
        tokens.append(token)
    return tokens


def check_keep_surfaces(
    surfaces: Iterable[tuple[str, str, str]],
    source: Identity,
    names: Sequence[str],
    *,
    rewritten: RewrittenLookup | None = None,
) -> KeepCheck:
    """Find undeclared names and stale entries on ``(path, where, text)`` rows.

    A token joining a declared source ``npm_name`` or ``cli_name`` to another
    name part is undeclared unless one ``keep_names`` entry wholly covers it or
    ``rewritten`` proves a row rewrites it on that exact path and surface.
    Matching ignores case because the paranoid verifier does too. An entry
    found on no surface is stale.
    """
    values = tuple(
        (field, value)
        for field, value in (
            ("npm_name", source.npm_name),
            ("cli_name", source.cli_name),
        )
        if value is not None
    )
    if not values and not names:
        return KeepCheck((), ())
    forms = _identity_forms(source)
    undeclared: dict[tuple[str, str, str], UndeclaredName] = {}
    unseen = dict.fromkeys(names)
    for path, where, text in surfaces:
        kept = kept_spans(text, names)
        for name in tuple(unseen):
            if kept_spans(text, (name,)):
                del unseen[name]
        subject = (
            rewritten(path, where, text) if rewritten is not None else RewrittenForms()
        )
        for field, value in values:
            for token in _sibling_tokens(text, value, forms, subject, kept):
                undeclared.setdefault(
                    (path, where, token), UndeclaredName(path, where, field, token)
                )
    return KeepCheck(tuple(undeclared.values()), tuple(unseen))


def render_undeclared(findings: Sequence[UndeclaredName], source: Identity) -> str:
    """The exit-1 refusal: each exact token and the line that would keep it."""
    identity = _identity_forms(source)
    lines = [
        f"error: {len(findings)} undeclared name(s) contain a declared npm_name "
        "or cli_name; nothing written, no receipt.",
    ]
    for item in findings[:_REPORT_LIMIT]:
        path = item.path if item.path.isprintable() else repr(item.path)
        lines.append(f"  [{item.where}] {path}: {item.token}")
        if _is_identity_spelling(item.token, identity):
            lines.append(
                "    this spelling is a source identity value that no row "
                "rewrites here, so it cannot be kept; rename it or change "
                "that field in the press"
            )
        else:
            lines.append(f"    {_keep_line(item.token)}")
    if len(findings) > _REPORT_LIMIT:
        lines.append(f"  and {len(findings) - _REPORT_LIMIT} more")
    lines.append(
        "hint: if a name is independent of this template, add it to [rules] "
        "keep_names in press/press-rules.toml; otherwise rename it."
    )
    return "\n".join(lines)


def render_stale(names: Sequence[str]) -> list[str]:
    """One non-fatal stderr line per entry found on no rewrite surface."""
    return [
        f"warning: keep_names entry {name!r} is stale: it occurs nowhere on the "
        "rewrite surface"
        for name in names
    ]
