"""Rust source spans that a ``[[cargo_split]]`` press must spell differently.

A hyphen-free crate name in a ``.rs`` file is a Rust identifier, so it takes
the underscore spelling, except inside a string literal. A string holds a
Cargo name, a path, or prose. The press gives it a spelling only where Cargo
proves which one is right; any other string occurrence is left untouched, so
the split preflight refuses it before any write. So is every occurrence in
the arguments of ``stringify!`` or ``concat!``, which turn code into text.

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
_CHAR_LITERAL = re.compile(r"'(?:\\u\{[0-9A-Fa-f_]+\}|\\x[0-9A-Fa-f]{2}|\\.|[^\\'\n])'")
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
# Text that ends one whole operand of ``==``, or starts one. A method call,
# an index, ``?``, ``as``, or a binary operator would change the value compared.
# The end of the text is no operand end: a doc block is read in part.
_OPERAND_END = re.compile(r"\s*(?:[),;\]}{]|&&|\|\|)")
_OPERAND_START = re.compile(
    r"(?:(?:^|[(,{;\[])|(?<![=!<>])=|&&|\|\||!|\b(?:if|while|return|match))\s*$"
)
# Rust accepts every macro delimiter: ``include_str!(...)``, ``[...]``, ``{...}``.
_INCLUDE_BEFORE = re.compile(
    r"\b(?:include_str|include_bytes|include)\s*!\s*[(\[{]\s*$"
)
_OUTER_PATH_ATTR_BEFORE = re.compile(r"#(?!\!)\s*\[\s*path\s*=\s*$")
_PATH_BEFORE = re.compile(
    r"(?:\b(?:include_str|include_bytes|include)\s*!\s*[(\[{]\s*"
    r"|#!?\s*\[\s*path\s*=\s*)$"
)
# ``path = `` as a direct argument of ``cfg_attr(...)``: the platform-module
# form of ``#[path]``. A ``path`` nested deeper is another attribute's value.
_CFG_ATTR_PATH = re.compile(r"[(,]\s*path\s*=\s*$")
_CFG_ATTR_CALL = re.compile(r"\bcfg_attr\s*$")

# Macros that turn their arguments into text. A crate name there is neither an
# identifier nor a string that Cargo reads, so no spelling is provable.
_QUOTING_MACROS = frozenset({"stringify", "concat"})
_QUOTING_NAME = re.compile(r"\b(?:stringify|concat)\b")
_OPENERS = frozenset("([{")
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
_FENCE_MARK = re.compile(r"`{3,}|~{3,}")
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

    Its doc comment ends that way, or in a quoting macro's arguments, or it
    has a ``doc`` attribute that the press cannot read or that names such a
    macro. rustdoc joins the inner doc comment of the module's own
    file to that text, so the press cannot read that file's doc comment.
    """
    return _scan(text)[1]


def quoted_spans(text: str) -> tuple[Span, ...]:
    """The arguments of each ``stringify!`` and ``concat!`` call in ``text``.

    The call turns them into text, so no spelling of a crate name there is
    provable. In a doc comment that rustdoc may compile, a span runs as far as
    the call may reach.
    """
    return _scan(text)[2]


_QUOTING_RENAME = re.compile(r"\b(?:stringify|concat)\s+as\b")
_USE = re.compile(r"\buse\b")


def quoting_renames(text: str) -> tuple[int, ...]:
    """Where ``text`` renames ``stringify!`` or ``concat!``, as in ``use
    core::stringify as s;`` or ``use core::{stringify as s};``.

    A call through the new name is no quoting call the press can see, in this
    file or another. Code and doc comments count, since rustdoc may compile a
    doc comment; string literals and plain comments do not.
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith(("//", "/*"), index):
            end = _comment_end(text, index)
            piece = text[index:end]
            pieces.append(piece if _is_doc(text, index, end) else _blank(piece))
        else:
            end, literal = _token(text, index)
            pieces.append(_blank(text[index:end]) if literal else text[index:end])
        index = end
    code = "".join(pieces)
    return tuple(
        found.start()
        for found in _QUOTING_RENAME.finditer(code)
        # Only a ``use`` item renames: ``concat as usize`` casts a variable.
        if _USE.search(code, code.rfind(";", 0, found.start()) + 1, found.start())
    )


_MODULE_DECLARATION = re.compile(r"(?<!\w)(?<!r#)mod\s+(?:r#)?(?P<name>[^\W\d]\w*)\s*;")
_PATH_ATTRIBUTE = re.compile(r"#\s*\[\s*path\s*=")
_INLINE_MODULE = re.compile(r"(?<!\w)(?<!r#)mod\s+(?:r#)?(?P<name>[^\W\d]\w*)\s*\{")
_PATH_VALUE = re.compile(r"\bpath\s*=\s*(?=\"\")")

PathKind = Literal["include", "module_path", "inline_dir"]


@dataclass(frozen=True)
class InlineModule:
    """One enclosing ``mod name { ... }`` block and any plain ``#[path]`` on it."""

    name: str
    path: str | None = None
    conditional_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleDeclaration:
    """One ``mod name;`` in code.

    ``inline`` names the inline ``mod outer { ... }`` blocks around it, from
    the outermost in. ``attributed`` says whether a ``#[path = ...]``
    attribute gives its file instead. ``conditional`` says whether a
    ``#[cfg_attr(..., path = ...)]`` attribute may; when its condition is
    false, the name-based file is compiled.
    """

    offset: int
    name: str
    attributed: bool
    conditional: bool
    inline: tuple[InlineModule, ...]


@dataclass(frozen=True)
class RustPathLiteral:
    """One path-role string literal with its Rust resolution context."""

    literal: RustString
    kind: PathKind
    inline: tuple[InlineModule, ...]


def _code_view(text: str) -> tuple[str, dict[int, RustString]]:
    """``text`` with comments and chars blanked and strings reduced to ``""``.

    Preserves 1-to-1 character offsets with ``text`` and returns each string
    literal in real code keyed by its starting offset.
    """
    pieces: list[str] = []
    literals: dict[int, RustString] = {}
    index = 0
    while index < len(text):
        if text.startswith(("//", "/*"), index):
            end = _comment_end(text, index)
            pieces.append(_blank(text[index:end]))
        else:
            end, literal = _token(text, index)
            piece = text[index:end]
            if literal:
                literals[index] = literal
                # Keep the quotes, so that a ``#[path = "..."]`` stays visible.
                if len(piece) >= 2:
                    pieces.append('""')
                    pieces.append(_blank(piece)[2:])
                else:
                    pieces.append(_blank(piece))
            elif piece.startswith("'") and len(piece) > 1:
                pieces.append(_blank(piece))  # a character literal
            else:
                pieces.append(piece)
        index = end
    return "".join(pieces), literals


def rust_code_view(text: str) -> str:
    """``text`` with comments blanked, offset for offset (see ``_code_view``)."""
    return _code_view(text)[0]


def _mod_path_attributes(
    text: str,
    code: str,
    item_start: int,
    mod_start: int,
    literals: dict[int, RustString],
) -> tuple[str | None, tuple[str, ...], tuple[int, ...]]:
    """Plain-string ``#[path]`` and ``#[cfg_attr(..., path)]`` on one ``mod``."""
    attributes = code[item_start:mod_start]
    unconditional: str | None = None
    conditional: list[str] = []
    offsets: list[int] = []
    for match in _PATH_VALUE.finditer(attributes):
        lit_offset = item_start + match.end()
        literal = literals.get(lit_offset)
        if literal is None or literal.open:
            continue
        value = text[literal.content_start : literal.content_end]
        if _OUTER_PATH_ATTR_BEFORE.search(attributes, 0, match.end()):
            unconditional = value
            offsets.append(lit_offset)
        elif _cfg_attr_path(attributes, match.end()):
            conditional.append(value)
            offsets.append(lit_offset)
    return unconditional, tuple(conditional), tuple(offsets)


def _scan_modules(
    text: str,
) -> tuple[tuple[ModuleDeclaration, ...], tuple[RustPathLiteral, ...]]:
    code, literals = _code_view(text)
    inline_openers = {m.end() - 1: m for m in _INLINE_MODULE.finditer(code)}
    all_path_strings = [
        lit for lit in rust_strings(text) if string_role(text, lit, "\0") == "path"
    ]
    code_path_offsets = {lit.start for lit in all_path_strings if not lit.doc}

    events: list[tuple[int, int, str, re.Match[str] | None]] = sorted(
        [
            *((m.start(), 0, "mod", m) for m in _MODULE_DECLARATION.finditer(code)),
            *((offset, 0, "path_lit", None) for offset in code_path_offsets),
            *((b.start(), 1, "brace", None) for b in re.finditer(r"[{}]", code)),
        ],
        key=lambda event: (event[0], event[1]),
    )

    stack: list[InlineModule | None] = []
    found_mods: list[ModuleDeclaration] = []
    enclosing_at: dict[int, tuple[InlineModule, ...]] = {}
    inline_dir_offsets: set[int] = set()

    for pos, _, kind, payload in events:
        if kind == "path_lit":
            enclosing_at[pos] = tuple(m for m in stack if m is not None)
        elif kind == "brace":
            if code[pos] == "{":
                opener = inline_openers.get(pos)
                if opener is None:
                    stack.append(None)
                else:
                    item = max(code.rfind(e, 0, opener.start()) for e in ";{}")
                    path_val, cond_vals, attr_offsets = _mod_path_attributes(
                        text, code, item + 1, opener.start(), literals
                    )
                    inline_dir_offsets.update(attr_offsets)
                    stack.append(InlineModule(opener["name"], path_val, cond_vals))
            elif stack:
                stack.pop()
        elif payload is not None:
            item = max(code.rfind(e, 0, payload.start()) for e in ";{}")
            attrs = code[item + 1 : payload.start()]
            _, cond_vals, _ = _mod_path_attributes(
                text, code, item + 1, payload.start(), literals
            )
            found_mods.append(
                ModuleDeclaration(
                    payload.start(),
                    payload["name"],
                    bool(_PATH_ATTRIBUTE.search(attrs)),
                    bool(cond_vals),
                    tuple(x for x in stack if x is not None),
                )
            )

    found_paths: list[RustPathLiteral] = []
    for lit in all_path_strings:
        if lit.doc:
            line_start = lit.doc[lit.line][0]
            lit_kind: PathKind = (
                "include"
                if _INCLUDE_BEFORE.search(text, line_start, lit.start)
                else "module_path"
            )
            found_paths.append(RustPathLiteral(lit, lit_kind, ()))
        elif _INCLUDE_BEFORE.search(code, 0, lit.start):
            found_paths.append(RustPathLiteral(lit, "include", ()))
        elif lit.start in inline_dir_offsets:
            found_paths.append(
                RustPathLiteral(lit, "inline_dir", enclosing_at[lit.start])
            )
        else:
            found_paths.append(
                RustPathLiteral(lit, "module_path", enclosing_at[lit.start])
            )

    return tuple(found_mods), tuple(found_paths)


def rust_source_structure(
    text: str,
) -> tuple[tuple[ModuleDeclaration, ...], tuple[RustPathLiteral, ...]]:
    """Each ``mod name;`` and path-role string literal in ``text``."""
    return _scan_modules(text)


def module_declarations(text: str) -> tuple[ModuleDeclaration, ...]:
    """Each ``mod name;`` in code, with its enclosing inline modules.

    Comments, doc comments, string literals, and character literals are
    skipped, so a brace inside one opens no block.
    """
    return _scan_modules(text)[0]


def rust_path_literals(text: str) -> tuple[RustPathLiteral, ...]:
    """Each path-role string literal in ``text`` with its Rust resolution context."""
    return _scan_modules(text)[1]


def _blank(piece: str) -> str:
    return re.sub(r"[^\n]", " ", piece)


def span_within(spans: Sequence[Span], span: Span) -> bool:
    """Whether one of ``spans`` holds ``span``."""
    return any(low <= span[0] and span[1] <= high for low, high in spans)


def _scan(
    text: str,
) -> tuple[tuple[RustString, ...], tuple[int, ...], tuple[Span, ...]]:
    found: list[RustString] = []
    cut: list[int] = []
    quoted: list[Span] = []
    docs: dict[int, list[RustString]] = {}
    index, length = 0, len(text)
    last = ""  # the last code character, outside comments and plain attributes
    attribute_end = 0
    # Doc text the press cannot read comes before the next doc comment
    # (``unread``), or before the same item's inner doc comment (``pending``).
    unread = pending = False
    # A quoting macro's call may be open before the next doc comment
    # (``calling``), or before the same item's inner doc comment (``called``).
    calling = called = False
    # For each open bracket, whether a macro call or definition holds it. A
    # macro may add doc text around the doc comments it is given.
    macros: list[bool] = []
    # For each open bracket, whether a quoting macro opens it; how many of
    # those are open; and where the part of the outermost one being read began.
    calls: list[bool] = []
    held = segment = 0
    word = ""  # the last code token, past spaces and comments, if it is a word
    bang = False  # the code ends with ``name!``, or ``name! name``
    quoting = False  # the code ends with ``stringify!`` or ``concat!``
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
                        calling or (inner and called),
                    )
                    docs.update(cluster.literals)
                    quoted += cluster.quoted
                    pending = not inner and (cluster.hidden or cluster.cut)
                    called = not inner and cluster.calling
                    module = _MODULE_FILE.match(text, cluster.end)
                    if (cluster.cut or cluster.calling) and not inner and module:
                        cut.append(module.start())
                found.extend(docs.pop(index))
            elif held:  # a plain comment is no argument
                quoted.append((segment, index))
                segment = end
            index = end
            continue
        start = index
        if text[index] == "#" and index >= attribute_end:
            attribute_end = _attribute_end(text, index)
            if _DOC_ATTRIBUTE.search(text, index, attribute_end):
                last = "#"
                hides = _hides_doc_text(text, index, attribute_end)
                names = _names_quoting(text, index, attribute_end)
                unread, calling = unread or hides, calling or names
                if (hides or names) and text[index + 1] != "!":  # an outer attribute
                    pending, called = pending or hides, called or names
                    module = _MODULE_FILE.match(text, _item_start(text, index))
                    if module:
                        cut.append(module.start())
        index, literal = _token(text, index)
        if literal is not None:
            found.append(literal)
        char = text[start]
        if char in "{([":
            macros.append(bang or any(macros[-1:]))
            calls.append(quoting)
            if quoting and not held:
                segment = start
            held += quoting
        elif char in "})]":
            del macros[-1:]
            if calls and calls.pop():
                held -= 1
                if not held:
                    quoted.append((segment, index))
        if char == "!":
            bang = bool(word)
        elif not (char.isspace() or _IDENT_CHARS.match(char)) or literal:
            bang = False
        if not char.isspace():
            quoting = char == "!" and word in _QUOTING_MACROS
            word = text[start:index] if _IDENT_CHARS.match(char) and not literal else ""
        if start >= attribute_end and not char.isspace():
            last = text[index - 1]
            unread = calling = False
            pending = pending and last not in ";}"
            called = called and last not in ";}"
    if held:
        quoted.append((segment, length))
    return tuple(found), tuple(sorted(set(cut))), tuple(quoted)


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


def _names_quoting(text: str, start: int, end: int) -> bool:
    """Whether a string in the attribute holds a quoting macro's name.

    As doc text, that string may open a call of the macro.
    """
    index = start
    while index < end:
        if text.startswith(("//", "/*"), index):
            index = _comment_end(text, index)
            continue
        index, literal = _token(text, index)
        if literal and _QUOTING_NAME.search(
            text, literal.content_start, literal.content_end
        ):
            return True
    return False


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
    quoted: list[Span]  # where a quoting macro's arguments may hold it
    calling: bool  # it may end inside such arguments, which later text closes


def _doc_cluster(
    text: str, index: int, clean: bool, unread: bool, calling: bool
) -> _Cluster:
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
    # The first line that follows doc text which may open a quoting macro's call.
    open_from = 0 if calling else None
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
                if open_from is None and _names_quoting(text, position, end):
                    open_from = len(lines)
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
    literals, cut, quoted, open_end = _doc_literals(
        text, lines, owners, restarts, whole, sealed, unread_from, unknown
    )
    if open_from is not None and open_from < len(lines):
        quoted.append((lines[open_from][0], lines[-1][1]))
    calling = not sealed and (open_end or open_from is not None)
    return _Cluster(literals, position, hidden, cut, quoted, calling)


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
) -> tuple[dict[int, list[RustString]], bool, list[Span], bool]:
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
    returns whether the text may end inside a string or a comment, where the
    lines read as code may sit in a quoting macro's arguments, and whether
    they may end there.
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
    code = [lines[number] for number, row in lexed if row]
    breaks = [lines[number][0] for number in restarts if number]
    return found, cut, *_doc_calls(text, code, breaks)


def _doc_calls(
    text: str, lines: Sequence[Segment], breaks: Sequence[int]
) -> tuple[list[Span], bool]:
    """Where doc lines read as code may sit in a quoting macro's arguments.

    The lines are read as code from each macro name on, which is exact
    wherever the name is code. A call runs to the last line when the lines do
    not close it, or when one of the ``breaks`` is inside it: the attribute
    before that line may add a bracket. Also returns whether a call runs on
    like that.
    """
    pieces: list[str] = []
    base = position = lines[0][0] if lines else 0
    for low, high in lines:
        pieces += [re.sub(r"[^\n]", " ", text[position:low]), text[low:high]]
        position = high
    view = "".join(pieces)  # the lines, each at its place in the file
    calls: list[Span] = []
    open_end = False
    for name in _QUOTING_NAME.finditer(view):
        bang = _item_start(view, name.end())  # past spaces and comments
        opener = _item_start(view, bang + 1)
        if view[bang : bang + 1] == "!" and view[opener : opener + 1] in _OPENERS:
            end, comments = _group_end(view, opener + 1)
            if end < 0 or any(name.start() < cut - base < end for cut in breaks):
                open_end, end, comments = True, len(view), []
            start = name.start()
            for low, high in comments:  # a plain comment is no argument
                calls.append((base + start, base + low))
                start = high
            calls.append((base + start, base + end))
    return calls, open_end


def _group_end(text: str, index: int) -> tuple[int, list[Span]]:
    """Where the bracket group that is open at ``index`` closes, read as code.

    The end is -1 when the text ends first. Also returns the plain comments
    inside the group.
    """
    depth = 1
    comments: list[Span] = []
    while index < len(text) and depth:
        if text.startswith(("//", "/*"), index):
            end = _comment_end(text, index)
            if not _is_doc(text, index, end):
                comments.append((index, end))
            index = end
            continue
        depth += (text[index] in "([{") - (text[index] in ")]}")
        index = _token(text, index)[0]
    return (-1 if depth else index), comments


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


def compiled_markdown_lines(text: str) -> frozenset[int]:
    """The 1-based lines of a Markdown file that rustdoc may compile as Rust
    when the file is a crate's doc text (``#![doc = include_str!(...)]``).

    That is every line inside a fence that ``_never_compiled`` does not skip,
    and, outside fences, every line that may sit in an indented code block.
    The press does not parse Markdown further, so it fails closed.
    """
    found: set[int] = set()
    fence = ""  # the open fence's marker, if any
    compiled = False
    # After a line that starts with ``<`` (a possible HTML block), or after a
    # fence that is not at the left margin (in a block quote or a list), the
    # structure is unproven: every line after any later fence line counts.
    loose = unproven = False
    for number, line in enumerate(text.split("\n"), start=1):
        body = line.lstrip(" ")
        if unproven:
            found.add(number)
            continue
        if loose and _FENCE_MARK.search(line):
            unproven = True
            found.add(number)
            continue
        if fence:
            if len(line) - len(body) < 4 and _closes(body, fence):
                fence = ""
            elif compiled:
                found.add(number)
            continue
        opened = _FENCE.match(body) if len(line) - len(body) < 4 else None
        if opened and (opened[1][0] == "~" or "`" not in opened[2]):
            fence = opened[1]
            compiled = not _never_compiled(opened[2].strip())
        elif _FENCE_MARK.search(line):
            unproven = True  # a fence that is not at the left margin
        elif body.startswith("<"):
            loose = True
        elif _INDENTED.search(line):
            found.add(number)
    return frozenset(found)


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
        or _CFG_ATTR_PATH.search(text, line_start, literal.start)
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
    if _PATH_BEFORE.search(before) or _cfg_attr_path(text, literal.start):
        return "path"
    if content == name and _compared_with_pkg_name(text, literal):
        return "pkg_name"
    return "other"


def _cfg_attr_path(text: str, position: int) -> bool:
    """Whether the literal at ``position`` is a ``path = `` argument whose
    innermost unclosed parenthesis is a ``cfg_attr(`` call."""
    before = text[:position]
    if not _CFG_ATTR_PATH.search(before):
        return False
    depth = 0
    for index in range(position - 1, max(position - 4000, 0) - 1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if not depth:
                return bool(_CFG_ATTR_CALL.search(text[max(index - 32, 0) : index]))
            depth -= 1
        elif char in ";{}[]" and depth == 0:
            return False
    return False


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
    found = _PKG_BEFORE.search(before)
    if found:
        if re.search(r"assert_(?:eq|ne)!\(\s*" + _PKG_NAME + r"\s*,\s*$", before):
            return bool(_ARG_END.match(text, start))
        # ``env!(...) == "<name>"``: both operands must be whole.
        return bool(
            _OPERAND_START.search(before, 0, found.start())
            and _OPERAND_END.match(text, start)
        )
    after = _PKG_AFTER_CMP.match(text, start)
    if after:
        # ``"<name>" == env!(...)``: both operands must be whole.
        return bool(
            _OPERAND_START.search(before) and _OPERAND_END.match(text, after.end())
        )
    return bool(_ASSERT_BEFORE.search(before) and _PKG_AFTER_ARG.match(text, start))


def _char_literals(text: str) -> tuple[Span, ...]:
    """The span of each character literal in code, outside comments."""
    found: list[Span] = []
    index = 0
    while index < len(text):
        if text.startswith(("//", "/*"), index):
            index = _comment_end(text, index)
            continue
        end, _ = _token(text, index)
        if text[index] == "'" and end > index + 1:
            found.append((index, end))
        index = end
    return tuple(found)


def split_rust_replacements(
    text: str, spans: Sequence[Span], name: str, identifier: str, package: str
) -> list[str | None]:
    """The spelling for each matched span; ``None`` leaves it unchanged."""
    strings, _, quoted = _scan(text)
    chars = _char_literals(text)
    out: list[str | None] = []
    for span in spans:
        literal = string_at(strings, span)
        if span_within(quoted, span):
            out.append(None)
        elif span_within(chars, span):
            out.append(None)  # a char literal: neither spelling fits
        elif any(s.start <= span[0] < s.content_start for s in strings) or any(
            low == span[1] for low, _ in chars
        ):
            out.append(None)  # a literal prefix such as r#"..."#, b"..." or b'x'
        elif literal is None:
            out.append(identifier)
        elif string_role(text, literal, name) == "other":
            out.append(None)
        else:
            out.append(package)
    return out
