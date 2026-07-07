"""No-leak verification: the gate between apply() and the receipt (EMP-01).

A rebrand that leaves ANY source-identity token behind — in file content or
in a path name — is a failed rebrand. The CLI must exit non-zero and write
no receipt. Port of init_doctor.check_no_identity_leftover, generalized to
(target, identity, rules) and extended with path-name checking.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import iter_target_files
from template_press.rebrand.identity import Identity, token_occurs
from template_press.rebrand.rules import Rules

PATH_FIELDS: tuple[str, ...] = ("package_name", "repo_name", "app_name")


@dataclass(frozen=True)
class Leak:
    path: str
    field: str
    value: str
    where: str  # "content" | "path" | "unverifiable"


def _read_for_scan(path: Path) -> str | None:
    """Content for scanning; None for binary/symlink; OSError propagates.

    Unlike the engine's lenient reader, the doctor must NOT silently skip an
    unreadable file — a file it cannot scan is a file it cannot certify.
    """
    if path.is_symlink():
        return None  # content lives outside the target; the name is scanned
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None  # binary: the rewrite pass cannot alter it either


def find_leaks(
    target: Path,
    source: Identity,
    rules: Rules,
    dest: Identity | None = None,
) -> list[Leak]:
    """Scan for surviving source-identity tokens.

    When ``dest`` is given, only fields that actually CHANGED are scanned:
    an unchanged field (same author across a rename) is not a leak — its
    token legitimately remains everywhere. Without ``dest`` all fields are
    scanned (full-rebrand semantics).
    """
    leaks: list[Leak] = []
    fields = source.as_dict()
    if dest is not None:
        dest_fields = dest.as_dict()
        fields = {k: v for k, v in fields.items() if v != dest_fields[k]}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        rel_posix = rel.as_posix()
        try:
            text = _read_for_scan(path)
        except OSError:
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            text = None
        if text is not None:
            for field_name, value in fields.items():
                if token_occurs(text, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "content"))
        for component in rel.parts:
            for field_name in PATH_FIELDS:
                value = fields.get(field_name)
                if value is not None and token_occurs(component, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
    return leaks


def render_leak_report(leaks: list[Leak], limit: int = 20) -> str:
    lines = [
        f"error: {len(leaks)} source-identity leftover(s) — rebrand is "
        f"INCOMPLETE; no receipt written."
    ]
    for leak in leaks[:limit]:
        lines.append(f"  [{leak.where}] {leak.path}: {leak.field}={leak.value!r}")
    if len(leaks) > limit:
        lines.append(f"  … and {len(leaks) - limit} more")
    lines.append(
        "hint: restore the target (git -C <target> checkout . && git clean "
        "-fd), fix the root cause (or, for content that is VALID to keep, "
        "add its directory to verify_ignore in .press/rules.toml), then "
        "press again."
    )
    return "\n".join(lines)
