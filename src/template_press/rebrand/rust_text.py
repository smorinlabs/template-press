"""Rust source spans that a ``[[cargo_split]]`` press must spell differently.

A hyphen-free crate name in a ``.rs`` file is a Rust identifier, so it takes
the underscore spelling, except inside a string literal. A string holds a
Cargo name, a path, or prose. The press gives it a spelling only where Cargo
proves which one is right; any other string occurrence is left untouched, so
the split preflight refuses it before any write.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Span = tuple[int, int]
StringRole = Literal["feature", "path", "pkg_name", "other"]

_IDENT_CHARS = re.compile(r"[A-Za-z0-9_]")
_STRING_PREFIXES = frozenset({"r", "b", "br", "c", "cr"})
_CHAR_LITERAL = re.compile(r"'(?:\\u\{[0-9A-Fa-f]{1,6}\}|\\.|[^\\'\n])'")
# Text right before a literal that makes it a Cargo feature name or a path the
# compiler resolves against the source file's directory.
_FEATURE_BEFORE = re.compile(r"\bfeature\s*=\s*$")
_CFG_CALL = re.compile(r"\b(?:cfg!?|cfg_attr)\s*$")
_PKG_NAME = r'env!\(\s*"CARGO_PKG_NAME"\s*\)'
_PKG_BEFORE = re.compile(
    rf"(?:{_PKG_NAME}\s*(?:==|!=)\s*|\bassert_(?:eq|ne)!\(\s*{_PKG_NAME}\s*,\s*)$"
)
_PKG_AFTER_CMP = re.compile(rf"\s*(?:==|!=)\s*{_PKG_NAME}")
_ASSERT_BEFORE = re.compile(r"\bassert_(?:eq|ne)!\(\s*$")
_PKG_AFTER_ARG = re.compile(rf"\s*,\s*{_PKG_NAME}\s*[,)]")
_ARG_END = re.compile(r"\s*[,)]")
_PATH_BEFORE = re.compile(
    r"(?:\b(?:include_str|include_bytes|include)!\s*\(\s*|#!?\[\s*path\s*=\s*)$"
)


@dataclass(frozen=True)
class RustString:
    """One string literal: its whole span and its content span."""

    start: int
    content_start: int
    content_end: int
    end: int
    # Still open where its doc comment or code block ends: never provable.
    open: bool = False


def rust_strings(text: str) -> tuple[RustString, ...]:
    """Every string literal in ``text``, skipping comments and char literals."""
    found: list[RustString] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if text.startswith("//", index):
            newline = text.find("\n", index)
            end = length if newline == -1 else newline
            if _is_doc(text, index, "/"):
                segments, end = _doc_line_segments(text, index)
                found.extend(_doc_strings(text, segments))
            index = end + 1
        elif text.startswith("/*", index):
            end = _block_comment_end(text, index)
            if _is_doc(text, index, "*") and end - index >= 5:
                found.extend(_doc_strings(text, _doc_block_segments(text, index, end)))
            index = end
        elif char == '"':
            found.append(_quoted(text, index, index))
            index = found[-1].end
        elif char == "'":
            match = _CHAR_LITERAL.match(text, index)
            index = match.end() if match else index + 1  # else a lifetime
        elif _IDENT_CHARS.match(char):
            word_end = index
            while word_end < length and _IDENT_CHARS.match(text[word_end]):
                word_end += 1
            word = text[index:word_end]
            literal = (
                _prefixed(text, index, word_end, word)
                if word in _STRING_PREFIXES
                else None
            )
            if literal is None:
                index = word_end
            else:
                found.append(literal)
                index = literal.end
        else:
            index += 1
    return tuple(found)


def _is_doc(text: str, start: int, mark: str) -> bool:
    """``///`` or ``//!`` (``/**`` or ``/*!``), but not ``////`` or ``/***``."""
    third = text[start + 2 : start + 3]
    return third == "!" or (third == mark and text[start + 3 : start + 4] != mark)


Segment = tuple[int, int]
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
# Info-string tokens rustdoc compiles; ``ignore``, ``text``, and every other
# language tag mean the block is not Rust.
_COMPILED_TAGS = frozenset(
    {"rust", "should_panic", "no_run", "compile_fail", "test_harness"}
    | {"standalone_crate", "allow_fail"}
)
_EDITION_TAG = re.compile(r"edition\d{4}|E\d{4}")


def _doc_line_segments(text: str, start: int) -> tuple[list[Segment], int]:
    """Bodies of consecutive ``///`` (or ``//!``) lines, and where they end."""
    prefix = text[start : start + 3]
    segments: list[Segment] = []
    position = start
    while True:
        newline = text.find("\n", position)
        end = len(text) if newline == -1 else newline
        segments.append((position + 3, end))
        following = end + 1
        lead = following
        while lead < len(text) and text[lead] in " \t":
            lead += 1
        if (
            following >= len(text)
            or not text.startswith(prefix, lead)
            or not _is_doc(text, lead, "/")
        ):
            return segments, end
        position = lead


def _doc_block_segments(text: str, start: int, end: int) -> list[Segment]:
    """Lines of a ``/** */`` body, each without its leading `` * ``."""
    segments: list[Segment] = []
    position = start + 3
    body_end = end - 2
    while position <= body_end:
        newline = text.find("\n", position, body_end)
        line_end = body_end if newline == -1 else newline
        lead = position
        while lead < line_end and text[lead] in " \t":
            lead += 1
        if lead < line_end and text[lead] == "*":
            lead += 1
        segments.append((lead, line_end))
        position = line_end + 1
    return segments


def _compiled_fence(info: str) -> bool:
    tokens = [token for token in re.split(r"[\s,]+", info.strip()) if token]
    return all(
        token in _COMPILED_TAGS or _EDITION_TAG.fullmatch(token) for token in tokens
    )


def _doc_strings(text: str, segments: Sequence[Segment]) -> list[RustString]:
    """String literals in the doc comment's fenced blocks that rustdoc compiles.

    Each block is read across its lines without their comment prefix, so a
    string may span lines. Prose and other fences hold no Rust strings.
    """
    found: list[RustString] = []
    code: list[Segment] = []
    fence: str | None = None
    compiled = False
    for segment in segments:
        line = text[segment[0] : segment[1]]
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence, compiled, code = (
                    match.group(1),
                    _compiled_fence(match.group(2)),
                    [],
                )
            continue
        if (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
            and not match.group(2).strip()
        ):
            if compiled:
                found.extend(_code_strings(text, code))
            fence = None
            continue
        code.append(segment)
    if fence is not None and compiled:
        found.extend(_code_strings(text, code))  # an unclosed fence runs to the end
    return found


def _code_strings(text: str, lines: Sequence[Segment]) -> list[RustString]:
    """Lex the joined code lines, then map each literal back into ``text``."""
    if not lines:
        return []
    joined = "\n".join(text[start:end] for start, end in lines)
    starts: list[int] = []
    offset = 0
    for start, end in lines:
        starts.append(offset)
        offset += end - start + 1

    def real(virtual: int) -> int:
        index = max(i for i, value in enumerate(starts) if value <= virtual)
        start, end = lines[index]
        return min(start + virtual - starts[index], end)

    return [
        RustString(
            real(literal.start),
            real(literal.content_start),
            real(literal.content_end),
            real(literal.end),
            open=literal.end <= literal.content_end or literal.open,
        )
        for literal in rust_strings(joined)
    ]


def _block_comment_end(text: str, start: int) -> int:
    depth, index = 0, start
    while index < len(text):
        if text.startswith("/*", index):
            depth, index = depth + 1, index + 2
        elif text.startswith("*/", index):
            depth, index = depth - 1, index + 2
            if depth == 0:
                return index
        else:
            index += 1
    return len(text)


def _quoted(text: str, start: int, quote: int) -> RustString:
    index = quote + 1
    while index < len(text) and text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    end = min(index + 1, len(text))
    return RustString(start, quote + 1, min(index, len(text)), end)


def _prefixed(text: str, start: int, word_end: int, word: str) -> RustString | None:
    if "r" in word:
        hashes = word_end
        while hashes < len(text) and text[hashes] == "#":
            hashes += 1
        if hashes >= len(text) or text[hashes] != '"':
            return None
        closing = '"' + "#" * (hashes - word_end)
        close = text.find(closing, hashes + 1)
        close = len(text) if close == -1 else close
        return RustString(
            start, hashes + 1, close, min(close + len(closing), len(text))
        )
    if word_end < len(text) and text[word_end] == '"':
        return _quoted(text, start, word_end)
    if word == "b" and word_end < len(text) and text[word_end] == "'":
        return None  # a byte char literal holds no name
    return None


def string_at(strings: Sequence[RustString], span: Span) -> RustString | None:
    """The literal whose content holds ``span``, if any."""
    for literal in strings:
        if literal.content_start <= span[0] and span[1] <= literal.content_end:
            return literal
        if literal.start > span[0]:
            break
    return None


def string_role(text: str, literal: RustString, name: str) -> StringRole:
    """What Cargo makes of a literal that holds the crate name.

    ``feature``: the whole literal is a ``feature = "<name>"`` value. ``path``:
    an ``include_*!`` or ``#[path]`` argument. ``pkg_name``: the whole literal
    is compared on a line that reads ``CARGO_PKG_NAME``.
    """
    if literal.open:
        return "other"
    before = text[: literal.start]
    content = text[literal.content_start : literal.content_end]
    if _FEATURE_BEFORE.search(before) and content == name:
        return "feature" if _inside_cfg(text, literal.start) else "other"
    if _PATH_BEFORE.search(before):
        return "path"
    if content == name and _compared_with_pkg_name(text, literal):
        return "pkg_name"
    return "other"


def _inside_cfg(text: str, position: int) -> bool:
    """Whether an unclosed ``cfg(``, ``cfg!(`` or ``cfg_attr(`` encloses it.

    The scan walks outward through unclosed parentheses and stops at the end
    of the enclosing statement or block.
    """
    depth = 0
    for index in range(position - 1, max(position - 4000, 0) - 1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth:
                depth -= 1
            elif _CFG_CALL.search(text[max(index - 32, 0) : index]):
                return True
        elif char in ";{}" and depth == 0:
            return False
    return False


def _compared_with_pkg_name(text: str, literal: RustString) -> bool:
    """Whether the literal is the other side of an ``env!("CARGO_PKG_NAME")``
    comparison: ``==``, ``!=``, or an ``assert_eq!``/``assert_ne!`` argument.
    """
    before, start = text[: literal.start], literal.end
    if _PKG_BEFORE.search(before):
        return bool(_ARG_END.match(text, start)) or not re.search(
            r"assert_(?:eq|ne)!\(\s*" + _PKG_NAME + r"\s*,\s*$", before
        )
    if _PKG_AFTER_CMP.match(text, start):
        return True
    return bool(_ASSERT_BEFORE.search(before) and _PKG_AFTER_ARG.match(text, start))


def split_rust_replacements(
    text: str, spans: Sequence[Span], name: str, identifier: str, package: str
) -> list[str | None]:
    """The spelling for each matched span; ``None`` leaves it unchanged."""
    strings = rust_strings(text)
    out: list[str | None] = []
    for span in spans:
        literal = string_at(strings, span)
        if literal is None:
            out.append(identifier)
        elif string_role(text, literal, name) == "other":
            out.append(None)
        else:
            out.append(package)
    return out
