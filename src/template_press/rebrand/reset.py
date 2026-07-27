"""The [[reset]] mechanism — stub loading and the stub-content scan (P05).

Reset reads bytes as text, FAIL CLOSED (D6): the target's current content
and any ``stub_file`` must decode as UTF-8 at plan time — the line count,
the verbose excerpt, and the stub scan all interpret text — and undecodable
bytes refuse the press. And a stub may not itself restore the identity its
reset exists to remove: stub content passes the same changed-only paranoid
identity and rendered-``[[replace]]``-literal scan the post-command check
uses (P04 D3's evidence standard), whatever its source.
"""

from __future__ import annotations

from pathlib import Path

from template_press.rebrand.engine import rendered_replace_rules
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.rules import ResetRule, Rules, rule_matches_path
from template_press.rebrand.safety import (
    SafetyError,
    assert_under_root,
    is_regular_lstat,
)


def _read_utf8(path: Path, what: str) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"{what}: cannot read: {exc}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{what} is not valid UTF-8 — reset reads bytes as text, fail "
            f"closed ({exc})"
        ) from exc


def _contained_regular(target: Path, rel: str, what: str) -> Path:
    path = target / rel
    try:
        assert_under_root(path, target)
    except SafetyError as exc:
        raise ValidationError(f"{what}: {exc}") from exc
    if not is_regular_lstat(path):
        raise ValidationError(
            f"{what} is not a regular file (missing, symlink, or special — "
            f"no-follow check)"
        )
    return path


def load_stub_content(target: Path, rule: ResetRule) -> str:
    """The stub text that will replace ``rule.file`` — UTF-8 fail-closed.

    Inline ``stub`` is returned verbatim (an empty string legitimately
    blanks the file); ``stub_file`` is read under the same containment
    predicates as every other declared path.
    """
    if rule.stub is not None:
        return rule.stub
    if rule.stub_file is None:  # config-load enforces the XOR; fail loud
        raise ValidationError(
            f"[[reset]] {rule.file}: neither stub nor stub_file present"
        )
    what = f"[[reset]] {rule.file}: stub_file {rule.stub_file}"
    path = _contained_regular(target, rule.stub_file, what)
    return _read_utf8(path, what)


def read_reset_target_text(target: Path, rule: ResetRule) -> str:
    """The reset target's CURRENT text (plan-time read, UTF-8 fail-closed)."""
    what = f"[[reset]] target {rule.file}"
    path = _contained_regular(target, rule.file, what)
    return _read_utf8(path, what)


def scan_stub_text(
    text: str,
    *,
    rel: str,
    source: Identity,
    dest: Identity,
    rules: Rules,
) -> list[str]:
    """Problems where the stub would RESTORE identity its reset removes.

    Changed-only (an unchanged field legitimately remains — flagging it
    would fail every partial rebrand), with the paranoid matcher for
    identity fields and exact literals for rendered ``[[replace]]`` FROM
    sides (``rendered_replace_rules`` already drops FROM == TO pairs).
    """
    problems: list[str] = []
    src, dst = source.as_dict(), dest.as_dict()
    for field in src:
        value = src[field]
        if field not in dst or dst[field] == value:
            continue
        spans = find_occurrences(
            text, field, value, substring=field in rules.substring_rewrite_fields
        )
        if spans:
            problems.append(
                f"stub for {rel} contains source {field} {value!r} "
                f"({len(spans)} occurrence(s)) — a stub may not restore the "
                f"identity its reset removes"
            )
    for replace_rule, frm, _to in rendered_replace_rules(rules, source, dest):
        if not replace_rule.content:
            continue
        if not rule_matches_path(replace_rule, rel):
            continue
        if frm in text:
            problems.append(
                f"stub for {rel} contains rendered [[replace]] literal "
                f"{frm!r} ({replace_rule.reason})"
            )
    return problems
