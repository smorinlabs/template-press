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
    cargo_field_values,
    cargo_ident,
    display_forms,
    is_cargo_field,
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
_ASCII_ALNUM = _NAME_CHARS - {"_", "-"}
_SCOPE_CHARS = _NAME_CHARS | {"."}


@dataclass(frozen=True)
class UndeclaredName:
    """A token holding a declared name inside a longer, undeclared name."""

    path: str
    where: str  # "content" | "path" | "symlink"
    field: str  # "npm_name" | "cli_name" | a ``cargo_*`` row tag
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
    are rendered ``[[replace]]`` sources, matched exactly. ``patterns`` are the
    compiled identity rows' own matchers, which prove that one occurrence
    touching a bare ``-`` or ``_`` is really rewritten.
    """

    tokens: frozenset[str] = frozenset()
    literals: frozenset[str] = frozenset()
    patterns: tuple[re.Pattern[str], ...] = ()


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


def loses_kept_name(before: str, after: str, names: Sequence[str]) -> bool:
    """Whether a path move leaves fewer occurrences of any kept name."""
    return any(
        len(kept_spans(after, (name,))) < len(kept_spans(before, (name,)))
        for name in names
    )


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
    forms.update(cargo_field_values(identity).values())
    return frozenset(forms)


def _normalized(value: str) -> str:
    return value.casefold().translate(_NORMALIZED_AWAY)


def _identity_core(name: str) -> str:
    """``name`` without edge characters outside ``[A-Za-z0-9_-]``, in linear time.

    A scoped name keeps one ``@``: ``/"@acme/widget"`` reduces to ``@acme/widget``,
    never to ``acme/widget``, so a scope cannot be mistaken for another value.
    """
    start = 0
    end = len(name)
    while start < end and name[start] not in _NAME_CHARS:
        start += 1
    while end > start and name[end - 1] not in _NAME_CHARS:
        end -= 1
    core = name[start:end]
    return f"@{core}" if "/" in core and "@" in name[:start] else core


def _is_identity_spelling(name: str, forms: frozenset[str]) -> bool:
    """Exact form, or a normalized match for a name with no edge ``-`` or ``_``.

    Surrounding punctuation and edge ``/`` or ``@`` are ignored first, because
    a kept span containing ``"acme-cli"`` or ``@acme`` would shield the identity
    value inside it. An edge separator makes a distinct token: ``--acme-cli`` is
    not ``acme-cli``.
    """
    if name in forms:
        return True
    core = _identity_core(name)
    if not core:
        return False
    if core in forms:
        return True
    if core[0] in "-_" or core[-1] in "-_":
        return False
    return _normalized(core) in {_normalized(form) for form in forms}


def _complete_name_pattern(field: str, value: str) -> re.Pattern[str]:
    """Where ``value`` stands as a complete name inside a ``keep_names`` entry.

    A scoped value starts at its ``@``, so a glued alphanumeric does not extend
    it: ``widget-extra@acme/widget`` holds ``@acme/widget``. A touching ``-`` or
    ``_`` is still an edge separator, as in ``x-@acme/widget``. A ``.`` or ``~``
    followed by a name character continues an npm name, so ``acme-cli.extra``
    does not hold ``acme-cli``.
    """
    left = r"(?<![_-])" if value.startswith("@") else r"(?<![A-Za-z0-9_-])"
    return re.compile(
        rf"{left}{re.escape(value)}(?![A-Za-z0-9_-])(?![.~][A-Za-z0-9_-])"
    )


def _contained_source_name(name: str, source: Identity) -> tuple[str, str] | None:
    """The source ``npm_name``, ``cli_name``, or Cargo name inside ``name``, if any.

    An unscoped value that is the basename of ``@scope/value`` is not contained:
    that spelling names a different package and may be kept.
    """
    candidates = (
        *((field, getattr(source, field)) for field in ("npm_name", "cli_name")),
        *cargo_field_values(source).items(),
    )
    for field, value in candidates:
        if value is None:
            continue
        for match in _complete_name_pattern(field, value).finditer(name):
            if "/" in value or _scoped_start(name, *match.span()) is None:
                return field, value
    return None


def validate_keep_names(
    names: Sequence[str],
    source: Identity,
    dest: Identity,
    *,
    synthetic_dest: bool = False,
) -> None:
    """Refuse an entry that is malformed or is a spelling of an identity value.

    Leading and trailing characters outside ``[A-Za-z0-9_-]`` are ignored,
    keeping the ``@`` of a scoped name. Entries and identity forms are then
    compared after case-folding and removing ``-``, ``_``, ``.``, and spaces,
    unless the entry starts or ends with ``-`` or ``_``; such an entry is
    refused only on exact equality. ``synthetic_dest`` is for ``press verify``.
    Its destination is generated, so the user cannot choose around an equality
    with it, and that comparison is skipped. An entry holding a complete source
    ``npm_name`` or ``cli_name`` is also refused. Shape and source
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
        contained = _contained_source_name(name, source)
        if contained is not None:
            raise ValidationError(
                f"keep_names entry {name!r} contains the source {contained[0]} "
                f"{contained[1]!r} as a complete name, so it cannot be kept; "
                "rename it"
            )


def _keep_line(token: str) -> str:
    return f"keep_names = {json.dumps([token])}"


def sibling_guidance(
    text: str, span: Span, source: Identity | None = None
) -> str | None:
    """The ``keep_names`` line for a match that prefixes a longer name.

    With ``source``, a token that validation would refuse gets no line.
    """
    kind, _token = classify_occurrence(text, span)
    if kind != "prefix":
        return None
    start, end = span
    while end < len(text) and text[end] in _NAME_CHARS:
        end += 1
    token = text[start:end]
    if source is not None and (
        _is_identity_spelling(token, _identity_forms(source))
        or _contained_source_name(token, source) is not None
    ):
        return None
    return _keep_line(token)


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


def _row_rewrites(patterns: Iterable[re.Pattern[str]], text: str, span: Span) -> bool:
    """Whether one row's matcher replaces exactly this occurrence."""
    for pattern in patterns:
        found = pattern.match(text, span[0])
        if found is not None and found.end() == span[1]:
            return True
    return False


def _scoped_start(text: str, start: int, end: int) -> int | None:
    """Where ``@scope/`` begins when ``text[start:end]`` is that scope's basename."""
    if text[start - 1 : start] != "/" or text[end : end + 1] in _NAME_CHARS:
        return None
    at = start - 1
    while at > 0 and text[at - 1] in _SCOPE_CHARS:
        at -= 1
    if at == start - 1 or text[at - 1 : at] != "@":
        return None
    at -= 1
    if text[at - 1 : at] in _ASCII_ALNUM:
        return None
    while at > 0 and text[at - 1] in _NAME_CHARS:
        at -= 1
    return at


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
    Any other directly touching ``-`` or ``_`` is a sibling, even with no name
    part after it (``--tsc``, ``_tsc_``), because the exact-name rewrite skips
    it. Such a bare spelling is exempt only when a row rewrites that occurrence.
    A multi-part value (holding ``-``, ``_``, or ``/``) is not word-like, so any
    name character touching it makes a sibling: ``acme-cli2``, ``xacme-cli``.
    A glued token is still reported when it is exactly an identity form that no
    row rewrites on this surface, because that form would survive the press.
    An unscoped value that is the basename of ``@scope/value`` is a sibling too:
    it names a different package.
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
        scoped = None if "/" in value else _scoped_start(text, start, end)
        if scoped is not None:
            start = scoped
        else:
            while start > 0 and text[start - 1] in _NAME_CHARS:
                start -= 1
            while end < len(text) and text[end] in _NAME_CHARS:
                end += 1
            if (start, end) == match.span():
                continue
            left, right = text[start : match.start()], text[match.end() : end]
            camel_tail = _CAMEL_TAIL.match(text, match.end() - 1) is not None
            # ASCII only, matching the boundaries in ``identity.token_pattern``.
            inside_word = text[match.start() - 1 : match.start()] in _ASCII_ALNUM or (
                text[match.end() : match.end() + 1] in _ASCII_ALNUM and not camel_tail
            )
            is_join = (
                _joined(left, left[-1:]) or _joined(right, right[:1]) or camel_tail
            )
            if not (multi_part or not inside_word or text[start:end] in unrewritten):
                continue
            if (
                not multi_part
                and not is_join
                and not inside_word
                and _row_rewrites(rewritten.patterns, text, match.span())
            ):
                continue
        token = text[start:end]
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


def _extended_dependencies(
    dependencies: Iterable[str],
    values: Sequence[tuple[str, str]],
    names: Sequence[str],
    subject: RewrittenForms,
) -> Iterable[UndeclaredName]:
    """Manifest dependency keys extending a declared name with ``.`` or ``~``."""
    for dependency in dependencies:
        if dependency in subject.tokens or dependency in subject.literals:
            continue
        kept = kept_spans(dependency, names)
        for field, value in values:
            if (
                dependency.startswith(value)
                and dependency[len(value) : len(value) + 1] in (".", "~")
                and outside_kept(((0, len(value)),), kept)
            ):
                yield UndeclaredName("package.json", "content", field, dependency)


def _extended_cargo_dependencies(
    dependencies: Iterable[str],
    source: Identity,
    names: Sequence[str],
    subject: RewrittenForms,
) -> Iterable[UndeclaredName]:
    """Cargo dependencies whose name extends a declared Cargo name with a separator.

    Compared in underscore form, because Cargo treats ``-`` and ``_`` alike.
    """
    values = cargo_field_values(source)
    for dependency in dependencies:
        if dependency in subject.tokens or dependency in subject.literals:
            continue
        ident = cargo_ident(dependency)
        kept = kept_spans(dependency, names)
        for field, value in values.items():
            base = cargo_ident(value)
            if (
                ident.startswith(base)
                and ident[len(base) : len(base) + 1] == "_"
                and outside_kept(((0, len(base)),), kept)
            ):
                yield UndeclaredName("Cargo.toml", "content", field, dependency)
                break


def check_keep_surfaces(
    surfaces: Iterable[tuple[str, str, str]],
    source: Identity,
    names: Sequence[str],
    *,
    rewritten: RewrittenLookup | None = None,
    dependency_names: Sequence[str] = (),
    cargo_dependency_names: Sequence[str] = (),
) -> KeepCheck:
    """Find undeclared names and stale entries on ``(path, where, text)`` rows.

    A token joining a declared source ``npm_name`` or ``cli_name`` to another
    name part is undeclared unless one ``keep_names`` entry wholly covers it or
    ``rewritten`` proves a row rewrites it on that exact path and surface.
    Matching ignores case because the paranoid verifier does too. An entry
    found on no surface is stale. ``dependency_names`` are the root manifest's
    dependency keys: only that evidence separates the package ``name.extra``
    from an ordinary file such as ``name.js``. ``cargo_dependency_names`` are
    the non-local Cargo dependencies; one extending a declared Cargo name is
    reported even when its manifest is outside the rewrite surface.
    """
    values = (
        *(
            (field, value)
            for field, value in (
                ("npm_name", source.npm_name),
                ("cli_name", source.cli_name),
            )
            if value is not None
        ),
        *cargo_field_values(source).items(),
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
    manifest_subject = (
        rewritten("package.json", "content", "")
        if rewritten is not None and dependency_names
        else RewrittenForms()
    )
    node_values = tuple(item for item in values if not is_cargo_field(item[0]))
    for item in _extended_dependencies(
        dependency_names, node_values, names, manifest_subject
    ):
        undeclared.setdefault((item.path, item.where, item.token), item)
    cargo_subject = (
        rewritten("Cargo.toml", "content", "")
        if rewritten is not None and cargo_dependency_names
        else RewrittenForms()
    )
    reported = {item.token for item in undeclared.values()}
    for item in _extended_cargo_dependencies(
        cargo_dependency_names, source, names, cargo_subject
    ):
        if item.token not in reported:
            undeclared.setdefault((item.path, item.where, item.token), item)
    return KeepCheck(tuple(undeclared.values()), tuple(unseen))


def render_undeclared(findings: Sequence[UndeclaredName], source: Identity) -> str:
    """The exit-1 refusal: each exact token and the line that would keep it."""
    identity = _identity_forms(source)
    declared = (
        "npm_name, cli_name, or Cargo name"
        if any(is_cargo_field(item.field) for item in findings)
        else "npm_name or cli_name"
    )
    lines = [
        f"error: {len(findings)} undeclared name(s) contain a declared "
        f"{declared}; nothing written, no receipt.",
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
        elif (contained := _contained_source_name(item.token, source)) is not None:
            lines.append(
                f"    this token contains the source {contained[0]} "
                f"{contained[1]!r}, so it cannot be kept; rename it"
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
