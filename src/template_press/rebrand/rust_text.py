"""Rust source spans that a ``[[cargo_split]]`` press must spell differently.

A hyphen-free crate name in a ``.rs`` file is a Rust identifier, so it takes
the underscore spelling, except inside a string literal. A string holds a
Cargo name, a path, or prose. The press gives it a spelling only where Cargo
proves which one is right; any other string occurrence is left untouched, so
the split preflight refuses it before any write.

A doc comment is Rust code wherever rustdoc compiles it as a doctest. The
press does not parse Markdown, so it reads doc text as code from every line
where a code block may start, and keeps a literal only when every reading
agrees on it. Doc text is prose only where no code block can hold it.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

Span = tuple[int, int]
Segment = tuple[int, int]
StringRole = Literal["feature", "path", "pkg_name", "other"]
# The lexer between two doc lines: in code, in a string, in a raw string with
# that many hashes, or in a block comment nested that deep.
_State = tuple[Literal["code", "string", "raw", "comment"], int]
# Where a code block may start: the line, and whether it can outlast prose.
_Start = tuple[int, bool]
# One way to read a doc line: the state it begins in, and every such start.
_Reading = tuple[_State, list[_Start]]
_CODE: _State = ("code", 0)

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

_ATTRIBUTE = re.compile(r"#!?\s*\[")
# An attribute that adds doc text the press cannot read: ``doc = ...`` in any
# form, or a macro variable that may expand to one.
_DOC_ATTRIBUTE = re.compile(r"\bdoc\s*=|\$")
_DOC_VALUE = re.compile(r"\bdoc\s*=\s*")
_PLAIN_VALUE = re.compile(r'"[^"\\]*"')
# After an item's doc comments: a module whose own file may continue them.
_MODULE_FILE = re.compile(r"(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+\w+\s*;")
# The code character before an item's first doc comment.
_ITEM_EDGES = frozenset({"", "{", "}", ";", ",", "("})
_FENCE = re.compile(r"(`{3,}|~{3,})(.*)")
# A line that can sit in an indented code block: it holds a tab or four spaces
# in a row. Markdown counts the indent after any list, task, or quote marker,
# so the run may follow one.
_INDENTED = re.compile(r"\t| {4}")
_ODD_SPACE = re.compile(r"[^\S ]")
_FENCE_TAG = re.compile(r"[A-Za-z0-9_-]+")
# Fence tags that name another language. rustdoc compiles a fence unless a tag
# it does not know comes before any Rust tag, so only known names count: a
# misspelt Rust tag is not one, and a later rustdoc may learn new Rust tags.
NOT_RUST_TAGS = frozenset(
    {"text", "txt", "plain", "plaintext", "console", "sh", "shell", "bash"}
    | {"toml", "json", "yaml", "yml", "ini", "xml", "html", "css", "sql", "diff"}
    | {"c", "cpp", "python", "javascript", "typescript", "markdown", "md"}
    | {"makefile", "dockerfile", "asm", "notrust"}
)
# How many lines around a doc literal its code block is read for its role. A
# shorter block can only lose a role, which refuses the literal.
_LINES_BEFORE = 40
# The most hashes of a raw string, and levels of a block comment, that the
# press follows from doc text it cannot read. Beyond that, it reads nothing.
_MAX_OPEN = 6
_MAX_STATES = 2 * _MAX_OPEN + 2  # a string, each raw string, each comment
_LINES_AFTER = 8


@dataclass(frozen=True)
class RustString:
    """One string literal: its whole span and its content span."""

    start: int
    content_start: int
    content_end: int
    end: int
    # Cut short by the end of its text, or read differently by two readings of
    # its doc comment: never provable.
    open: bool = False
    # For a literal in a doc comment: every line of the comment, the literal's
    # line, and each line where the code block that holds it may start.
    doc: tuple[Segment, ...] = ()
    line: int = 0
    starts: tuple[int, ...] = ()
    # A whole doc line that follows doc text the press cannot read.
    unread: bool = False


# One doc line read as code: its literals, its comment spans, its end state.
_Lexed = tuple[list[RustString], list[Span], _State]


def rust_strings(text: str) -> tuple[RustString, ...]:
    """Every string literal in ``text``, skipping comments and char literals.

    A doc comment yields the literals that rustdoc may compile.
    """
    return _scan(text)[0]


def cut_module_docs(text: str) -> tuple[int, ...]:
    """Where a ``mod name;`` has doc text that may end inside a string or comment.

    Its doc comment ends that way, or it has a ``doc`` attribute that the
    press cannot read. rustdoc joins the inner doc comment of the module's own
    file to that text, so the press cannot read that file's doc comment.
    """
    return _scan(text)[1]


def _scan(text: str) -> tuple[tuple[RustString, ...], tuple[int, ...]]:
    found: list[RustString] = []
    cut: list[int] = []
    docs: dict[int, list[RustString]] = {}
    index, length = 0, len(text)
    last = ""  # the last code character, outside comments and plain attributes
    attribute_end = 0
    # Doc text the press cannot read comes before the next doc comment
    # (``unread``), or before the same item's inner doc comment (``pending``).
    unread = pending = False
    # For each open bracket, whether a macro call or definition holds it. A
    # macro may add doc text around the doc comments it is given.
    macros: list[bool] = []
    bang = False  # the code ends with ``name!``, or ``name! name``
    while index < length:
        if text.startswith(("//", "/*"), index):
            end = _comment_end(text, index)
            if _is_doc(text, index, end):
                if index not in docs:
                    inner = text[index + 2] == "!"
                    cluster = _doc_cluster(
                        text,
                        index,
                        last in _ITEM_EDGES and not any(macros[-1:]),
                        unread or (inner and pending),
                    )
                    docs.update(cluster.literals)
                    pending = not inner and (cluster.hidden or cluster.cut)
                    module = _MODULE_FILE.match(text, cluster.end)
                    if cluster.cut and not inner and module:
                        cut.append(module.start())
                found.extend(docs.pop(index))
            index = end
            continue
        start = index
        if text[index] == "#" and index >= attribute_end:
            attribute_end = _attribute_end(text, index)
            if _DOC_ATTRIBUTE.search(text, index, attribute_end):
                last = "#"
                if _hides_doc_text(text, index, attribute_end):
                    unread = True
                    if text[index + 1] != "!":  # an outer attribute
                        pending = True
                        module = _MODULE_FILE.match(text, _item_start(text, index))
                        if module:
                            cut.append(module.start())
        index, literal = _token(text, index)
        if literal is not None:
            found.append(literal)
        char = text[start]
        if char in "{([":
            macros.append(bang or any(macros[-1:]))
        elif char in "})]":
            del macros[-1:]
        if char == "!":
            bang = bool(_IDENT_CHARS.match(text[start - 1 : start]))
        elif not (char.isspace() or _IDENT_CHARS.match(char)) or literal:
            bang = False
        if start >= attribute_end and not char.isspace():
            last = text[index - 1]
            unread = False
            pending = pending and last not in ";}"
    return tuple(found), tuple(sorted(set(cut)))


def _item_start(text: str, position: int) -> int:
    """Where the item's code begins, past its attributes and comments."""
    while position < len(text):
        if text[position].isspace():
            position += 1
        elif text.startswith(("//", "/*"), position):
            position = _comment_end(text, position)
        elif (end := _attribute_end(text, position)) > position:
            position = end
        else:
            break
    return position


def _hides_doc_text(text: str, start: int, end: int) -> bool:
    """Whether a doc attribute may add part of a Rust string or comment.

    A plain string value without a quote, a backslash, or a block-comment
    marker cannot. Any other value, such as ``include_str!(...)``, may.
    """
    attribute = text[start:end]
    values = [
        _PLAIN_VALUE.match(attribute, found.end())
        for found in _DOC_VALUE.finditer(attribute)
    ]
    return any(
        value is None or "/*" in value[0] or "*/" in value[0] for value in values
    )


def _token(text: str, index: int) -> tuple[int, RustString | None]:
    """Where the literal, lifetime, word, or character at ``index`` ends."""
    char = text[index]
    if char == '"':
        literal = _quoted(text, index, index)
        return literal.end, literal
    if char == "'":
        match = _CHAR_LITERAL.match(text, index)
        return (match.end() if match else index + 1), None  # else a lifetime
    if not _IDENT_CHARS.match(char):
        return index + 1, None
    word_end = index
    while word_end < len(text) and _IDENT_CHARS.match(text[word_end]):
        word_end += 1
    word = text[index:word_end]
    if word not in _STRING_PREFIXES:
        return word_end, None
    literal = _prefixed(text, index, word_end, word)
    return (word_end if literal is None else literal.end), literal


def _comment_end(text: str, start: int) -> int:
    if text.startswith("/*", start):
        return _block_comment(text, start)[0]
    newline = text.find("\n", start)
    return len(text) if newline == -1 else newline


def _block_comment(text: str, start: int, depth: int = 0) -> tuple[int, int]:
    """Where the block comment ends, and how deep it is if ``text`` ends first."""
    index = start
    while index < len(text):
        if text.startswith("/*", index):
            depth, index = depth + 1, index + 2
        elif text.startswith("*/", index):
            depth, index = depth - 1, index + 2
            if depth == 0:
                return index, 0
        else:
            index += 1
    return len(text), depth


def _is_doc(text: str, start: int, end: int) -> bool:
    """``///`` or ``//!`` (``/**`` or ``/*!``); not ``////``, ``/***``, ``/**/``."""
    mark, third = text[start + 1], text[start + 2 : start + 3]
    if mark == "*" and end - start < 5:
        return False
    return third == "!" or (third == mark and text[start + 3 : start + 4] != mark)


def _attribute_end(text: str, start: int) -> int:
    """Where the attribute at ``start`` ends, or ``start`` when none begins."""
    match = _ATTRIBUTE.match(text, start)
    if match is None:
        return start
    depth, index = 1, match.end()
    while index < len(text) and depth:
        if text.startswith(("//", "/*"), index):
            index = _comment_end(text, index)
            continue
        depth += (text[index] == "[") - (text[index] == "]")
        index = _token(text, index)[0]
    return index


@dataclass(frozen=True)
class _Cluster:
    """The doc comments rustdoc joins, read as one text."""

    literals: dict[int, list[RustString]]  # by the offset of each doc comment
    end: int  # where the item's code begins
    hidden: bool  # it holds doc text the press cannot read
    cut: bool  # it may end inside a string or a comment that later text closes


def _doc_cluster(text: str, index: int, clean: bool, unread: bool) -> _Cluster:
    """The literals of each doc comment that rustdoc joins with the one here.

    rustdoc joins an item's doc comments, across blank lines, plain comments,
    and attributes, into one Markdown text, and then compiles its code blocks.
    Only ``///`` comments that open an item, with no ``doc`` attribute beside
    them, are sure to start that text: an inner comment follows the item's
    outer one, and a block comment has its own indentation rules. Only inner
    comments are sure to end it.
    """
    inner = text[index + 2] == "!"
    lines: list[Segment] = []
    owners: list[int] = []
    restarts = {0}  # lines after an attribute, which may add doc text
    whole, sealed = clean and not inner, inner
    hidden = after_hidden = unread  # unread doc text comes before the next line
    unknown: set[int] = set()  # the lines such text comes before
    position, after_attribute = index, False
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        end = _attribute_end(text, position)
        if end > position:
            if _DOC_ATTRIBUTE.search(text, position, end):
                whole = False
                sealed = sealed and "$" not in text[position:end]
                if _hides_doc_text(text, position, end):
                    hidden = after_hidden = True
            after_attribute = True
        elif not text.startswith(("//", "/*"), position):
            break
        else:
            end = _comment_end(text, position)
            if _is_doc(text, position, end):
                if (text[position + 2] == "!") != inner:
                    break
                block = text[position + 1] == "*"
                whole = whole and not block
                if after_attribute:
                    restarts.add(len(lines))
                    after_attribute = False
                if after_hidden:
                    unknown.add(len(lines))
                    after_hidden = False
                body = _doc_lines(text, position + 3, end - 2 if block else end)
                lines += body
                owners += [position] * len(body)
        position = end
    # An inner comment ends the item's doc text, unless unread text follows it.
    # Then, and in an outer comment, a string from unread text may never close,
    # so nothing after that text can be read.
    sealed = sealed and not after_hidden
    unread_from = len(lines) if sealed or not unknown else min(unknown)
    literals, cut = _doc_literals(
        text, lines, owners, restarts, whole, sealed, unread_from, unknown
    )
    return _Cluster(literals, position, hidden, cut)


def _doc_lines(text: str, start: int, end: int) -> list[Segment]:
    lines: list[Segment] = []
    while True:
        newline = text.find("\n", start, end)
        if newline == -1:
            return [*lines, (start, end)]
        lines.append((start, newline))
        start = newline + 1


def _doc_literals(
    text: str,
    lines: Sequence[Segment],
    owners: Sequence[int],
    restarts: set[int],
    proven: bool,
    sealed: bool,
    unread_from: int,
    unknown: set[int],
) -> tuple[dict[int, list[RustString]], bool]:
    """Read the joined doc lines as code wherever a code block may hold them.

    While the Markdown structure is ``proven``, the press knows where each
    fence opens and closes: a non-Rust fence and plain prose hold no code, and
    a Rust fence is read from its first line. Anything that puts the structure
    in doubt ends that for the rest of the text. From then on a code block may
    start after any fence marker and at any indented line.

    A reading binds a line only if it is back in code at the end of that line
    or a later one, because a doctest that ends inside a string or a comment
    does not compile. The text ends with the last line only when ``sealed``.

    From line ``unread_from`` on, the text follows doc text the press cannot
    read, so each of those lines is unread as a whole. Before that, such text
    leaves only the lexer state of an ``unknown`` line in doubt: one more
    reading starts there in each state that the later text can close. Also
    returns whether the text may end inside a string or a comment.
    """
    bodies = [text[low:high] for low, high in lines]
    widths = [len(body) - len(body.lstrip(" ")) for body in bodies if body.strip()]
    # rustdoc strips the common indent. Unseen doc text can only lower it, so a
    # line's real indent lies between its width less the margin and its width.
    margin = min(widths, default=0)
    proven = proven and margin <= 3 and not any(map(_ODD_SPACE.search, bodies))
    unseen = not proven  # doc text the press cannot read may precede a restart
    readings: list[_Reading] = []
    lexed: list[tuple[int, list[tuple[_Lexed, list[_Start]]]]] = []
    closed: dict[_Start, int] = {}  # each start: the last line it left in code
    fence, skipped = "", False
    for number, body in enumerate(bodies):
        if number in unknown and number < unread_from:
            # The blocks so far run on into the unread text, which may close
            # them. After it, a block is in code or in a state from that text.
            for _, starts in readings:
                closed.update(dict.fromkeys(starts, number - 1))
            states = _open_states("\n".join(bodies[number:]))
            if states is None:
                unread_from = number
            else:  # a start below zero: the block began in unread text
                readings = [
                    (state, [(-1 - number * _MAX_STATES - n, True)])
                    for n, state in enumerate(states)
                ]
        if number >= unread_from:
            break
        width = len(body) - len(body.lstrip(" "))
        marked = "```" in body or "~~~" in body
        prose = bool(body.strip()) and not _INDENTED.search(body)
        inside = bool(fence)
        if fence and _closes(body, fence) and width - margin < 4:
            fence, inside = "", False
            if width <= 3:
                readings = []
                continue
            proven = False  # a closing fence at some indents only
        if inside:
            if skipped:
                continue
        elif proven:
            opener = _FENCE.fullmatch(body, margin) if width == margin else None
            if opener and (opener[1][0] == "~" or "`" not in opener[2]):
                fence, skipped = opener[1], _never_compiled(opener[2])
                readings = [] if skipped else [(_CODE, [(number + 1, True)])]
                continue
            if marked or body.lstrip(" ").startswith("<"):
                proven = False  # a fence in a list or quote, or an HTML block
            elif prose:
                readings = []  # no code block holds this line
                continue
        if not inside:
            if prose:
                readings = _lasting(readings)
            if unseen and number in restarts:
                readings = _merged([*readings, (_CODE, [(number, True)])])
            if _INDENTED.search(body):
                readings = _merged([*readings, (_CODE, [(number, False)])])
        row = [(_lex_line(body, state), starts) for state, starts in readings]
        lexed.append((number, row))
        readings = []
        for (_, _, state), starts in row:
            if state == _CODE:
                closed.update(dict.fromkeys(starts, number))
                # Back in code, a block from the unread text reads on like one
                # that starts at the next line.
                starts = [(number + 1, True) if s[0] < 0 else s for s in starts]
            readings.append((state, starts))
        if marked and not proven:
            readings.append((_CODE, [(number + 1, True)]))
        readings = _merged(readings)
    cut = not sealed and any(state != _CODE for state, _ in readings)
    if not sealed:
        for _, starts in readings:
            closed.update(dict.fromkeys(starts, len(bodies)))
    doc = tuple(lines)
    found: dict[int, list[RustString]] = {owner: [] for owner in owners}
    for number in range(unread_from, len(bodies)):
        low, high = lines[number]
        found[owners[number]].append(
            RustString(low, low, high, high, True, doc, number, unread=True)
        )
    for number, row in lexed:
        binding = [
            (
                literals,
                comments,
                [start for start in starts if closed.get(start, -1) >= number],
            )
            for (literals, comments, _), starts in row
        ]
        found[owners[number]] += _agreed(
            [reading for reading in binding if reading[2]], doc, number
        )
    return found, cut


def _open_states(doc: str) -> list[_State] | None:
    """The states a string or comment from earlier text can be in, if few.

    Only a state that ``doc`` can close matters: a string closes at a quote, a
    raw string at a quote and its hashes, a comment at ``*/``.
    """
    hashes = max((len(found[1]) for found in re.finditer(r'"(#*)', doc)), default=-1)
    depth = doc.count("*/")
    if max(hashes, depth) > _MAX_OPEN:
        return None
    strings: list[_State] = [("string", 0)] if hashes >= 0 else []
    raws: list[_State] = [("raw", count) for count in range(hashes + 1)]
    comments: list[_State] = [("comment", count + 1) for count in range(depth)]
    return strings + raws + comments


def _closes(body: str, fence: str) -> bool:
    run = body.strip(" ")
    return len(run) >= len(fence) and not run.strip(fence[0])


def _never_compiled(info: str) -> bool:
    """Whether rustdoc never compiles a fence with this info string.

    That is ``ignore`` without an ``ignore-<target>`` tag, or a fence whose
    every tag names another language. Real ``cargo test`` proves each one in
    the test suite.
    """
    tags = [tag for tag in re.split(r"[,\s]+", info) if tag]
    if not all(_FENCE_TAG.fullmatch(tag) for tag in tags):
        return False
    if "ignore" in tags:
        return not any(tag.startswith("ignore-") for tag in tags)
    return bool(tags) and all(tag in NOT_RUST_TAGS for tag in tags)


def _lasting(readings: Sequence[_Reading]) -> list[_Reading]:
    """Drop the indented code blocks, which a prose line ends."""
    kept = [
        (state, [start for start in starts if start[1]]) for state, starts in readings
    ]
    return [reading for reading in kept if reading[1]]


def _merged(readings: Sequence[_Reading]) -> list[_Reading]:
    """Join the readings that share a state: they read every later line alike."""
    by_state: dict[_State, dict[_Start, None]] = {}
    for state, starts in readings:
        by_state.setdefault(state, {}).update(dict.fromkeys(starts))
    return [(state, list(starts)) for state, starts in by_state.items()]


def _lex_line(line: str, state: _State) -> _Lexed:
    """Lex one doc line as Rust code that begins in ``state``.

    Returns the line's string literals, its comment spans, and the state at
    its end. A literal that the line's start or end cuts is ``open``.
    """
    literals: list[RustString] = []
    comments: list[Span] = []
    index = 0
    kind, count = state
    if kind == "comment":
        index, count = _block_comment(line, 0, count)
        comments.append((0, index))
        if count:
            return literals, comments, ("comment", count)
    elif kind != "code":
        if kind == "string":
            rest = _quoted(line, 0, -1)
        else:
            rest = _raw(line, 0, 0, '"' + "#" * count)
        literals.append(replace(rest, open=True))
        if rest.end == rest.content_end:
            return literals, comments, state
        index = rest.end
    while index < len(line):
        if line.startswith("//", index):
            comments.append((index, len(line)))
            break
        if line.startswith("/*", index):
            end, depth = _block_comment(line, index)
            comments.append((index, end))
            if depth:
                return literals, comments, ("comment", depth)
            index = end
            continue
        index, literal = _token(line, index)
        if literal is None:
            continue
        if literal.end > literal.content_end:
            literals.append(literal)
            continue
        literals.append(replace(literal, open=True))
        opener = line[literal.start : literal.content_start]
        return (
            literals,
            comments,
            (("raw", opener.count("#")) if "r" in opener else ("string", 0)),
        )
    return literals, comments, _CODE


def _agreed(
    readings: Sequence[tuple[list[RustString], list[Span], list[_Start]]],
    doc: tuple[Segment, ...],
    number: int,
) -> list[RustString]:
    """The literals of one doc line, placed in the file.

    A literal counts when every reading has it, or has a comment around it,
    which makes its spelling harmless. The other literals come back ``open``.
    """
    base = doc[number][0]
    sure: dict[RustString, set[int]] = {}
    doubted: list[Span] = []
    for literals, _, _ in readings:
        for literal in literals:
            holders: set[int] = set()
            agreed = not literal.open
            for others, comments, starts in readings:
                if literal in others:
                    holders.update(line for line, _ in starts)
                elif not any(
                    low <= literal.start and literal.end <= high
                    for low, high in comments
                ):
                    agreed = False
            if agreed:
                sure[literal] = holders
            else:
                doubted.append((literal.start, literal.end))
    found = [
        RustString(
            literal.start + base,
            literal.content_start + base,
            literal.content_end + base,
            literal.end + base,
            doc=doc,
            line=number,
            starts=tuple(sorted(holders)),
        )
        for literal, holders in sure.items()
    ]
    spans: list[Span] = []
    for low, high in sorted(doubted):
        if spans and low <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], high))
        else:
            spans.append((low, high))
    found += [
        RustString(low + base, low + base, high + base, high + base, True, doc, number)
        for low, high in spans
    ]
    return sorted(found, key=lambda literal: literal.start)


def _quoted(text: str, start: int, quote: int) -> RustString:
    index = quote + 1
    while index < len(text) and text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    end = min(index + 1, len(text))
    return RustString(start, quote + 1, min(index, len(text)), end)


def _raw(text: str, start: int, content_start: int, closing: str) -> RustString:
    close = text.find(closing, content_start)
    close = len(text) if close == -1 else close
    return RustString(start, content_start, close, min(close + len(closing), len(text)))


def _prefixed(text: str, start: int, word_end: int, word: str) -> RustString | None:
    if "r" in word:
        hashes = word_end
        while hashes < len(text) and text[hashes] == "#":
            hashes += 1
        if hashes >= len(text) or text[hashes] != '"':
            return None
        return _raw(text, start, hashes + 1, '"' + "#" * (hashes - word_end))
    if word_end < len(text) and text[word_end] == '"':
        return _quoted(text, start, word_end)
    return None  # a word, or a byte char literal, which holds no name


def string_at(strings: Sequence[RustString], span: Span) -> RustString | None:
    """The literal whose content holds ``span``, if any."""
    index = bisect_right(strings, span[0], key=lambda literal: literal.content_start)
    literal = strings[index - 1] if index else None
    if literal is not None and span[1] <= literal.content_end:
        return literal
    return None


def string_role(text: str, literal: RustString, name: str) -> StringRole:
    """What Cargo makes of a literal that holds the crate name.

    ``feature``: the whole literal is a ``feature = "<name>"`` value inside
    ``cfg``. ``path``: an ``include_*!`` or ``#[path]`` argument.
    ``pkg_name``: the whole literal is the other side of a ``CARGO_PKG_NAME``
    comparison. A doc-comment literal has a role only when it has that role
    wherever its code block may start.
    """
    if literal.open:
        return "other"
    if not literal.doc:
        return _role(text, literal, name)
    if min(literal.starts) < 0:
        return "other"  # one block began in doc text the press cannot read
    line_start = literal.doc[literal.line][0]
    if text[literal.content_start : literal.content_end] != name and not (
        _PATH_BEFORE.search(text, line_start, literal.start)
    ):
        return "other"  # no role fits: skip building the code blocks
    first = literal.line - _LINES_BEFORE
    roles = {
        _role(*_block_view(text, literal, start), name)
        for start in {max(start, first) for start in literal.starts}
    }
    return roles.pop() if len(roles) == 1 else "other"


def _block_view(text: str, literal: RustString, start: int) -> tuple[str, RustString]:
    """The code block from line ``start``, and the literal's place in it."""
    lines = literal.doc[start : literal.line + 1 + _LINES_AFTER]
    before = sum(high - low + 1 for low, high in lines[: literal.line - start])
    shift = before - literal.doc[literal.line][0]
    return "\n".join(text[low:high] for low, high in lines), RustString(
        literal.start + shift,
        literal.content_start + shift,
        literal.content_end + shift,
        literal.end + shift,
    )


@lru_cache(maxsize=8)
def _without_comments(text: str) -> str:
    """``text`` with each comment blanked, so that its words fit no role."""
    pieces: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith(("//", "/*"), index):
            end = _comment_end(text, index)
            pieces.append(re.sub(r"[^\n]", " ", text[index:end]))
        else:
            end = _token(text, index)[0]
            pieces.append(text[index:end])
        index = end
    return "".join(pieces)


def _role(text: str, literal: RustString, name: str) -> StringRole:
    text = _without_comments(text)
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
