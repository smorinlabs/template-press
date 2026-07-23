"""No-leak verification: the gate between apply() and the receipt (EMP-01).

A rebrand that leaves ANY source-identity token behind — in file content or
in a path name — is a failed rebrand. The CLI must exit non-zero and write
no receipt. Port of init_doctor.check_no_identity_leftover, generalized to
(target, identity, rules) and extended with path-name checking.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import (
    _git_listed,
    _is_root_press,
    iter_target_files,
)
from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    display_forms,
    token_occurs,
)
from template_press.rebrand.rules import Rules

PATH_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "app_name_upper",
)


@dataclass(frozen=True)
class Leak:
    path: str
    field: str
    value: str
    where: str  # "content" | "path" | "symlink" | "unverifiable"


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
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[Leak]:
    """Scan for surviving source-identity tokens.

    When ``dest`` is given, only fields that actually CHANGED are scanned:
    an unchanged field (same author across a rename) is not a leak — its
    token legitimately remains everywhere. Without ``dest`` all fields are
    scanned (full-rebrand semantics).
    """
    leaks: list[Leak] = []
    fields = source.as_dict()
    if "display_name" in fields:
        # Expand into the exact per-form values so a surviving glued form
        # (PyLaunchBlueprint) is a leak, not just the spaced original.
        sf = display_forms(fields.pop("display_name"))
        for form in display_form_names:
            fields[f"display_name_{form}"] = sf[form]
    if dest is not None:
        dest_fields = dest.as_dict()
        if "display_name" in dest_fields:
            df = display_forms(dest_fields.pop("display_name"))
            for form in display_form_names:
                dest_fields[f"display_name_{form}"] = df[form]
        fields = {k: v for k, v in fields.items() if dest_fields.get(k) != v}
    covered_symlinks: set[str] = set()
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
        if path.is_symlink():
            # A symlink's bytes are its target string, not file content — an
            # identity token embedded there would dangle/leak in a pressed fork.
            covered_symlinks.add(rel_posix)
            link = os.readlink(path)
            for field_name, value in fields.items():
                if token_occurs(link, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "symlink"))
        for i, component in enumerate(rel.parts):
            if _is_root_press(rel, i):
                continue
            for field_name in PATH_FIELDS:
                value = fields.get(field_name)
                if value is not None and token_occurs(component, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
    # DIRECTORY and DANGLING symlinks never reach the loop above:
    # `iter_target_files` keeps only `is_file()` paths, and `is_file()` FOLLOWS
    # the link — so a symlink to a dir (or to nothing) is dropped, and a source
    # token embedded in its link string would slip the gate. Scan every
    # git-listed symlink's `readlink` STRING here (never the destination),
    # deduping the symlink-to-file links the loop already covered.
    for rel in _git_listed(target):
        rel_posix = rel.as_posix()
        if rel_posix in covered_symlinks:
            continue
        path = target / rel
        if not path.is_symlink():
            continue
        # The NAME of a dir/dangling symlink is never scanned by the main loop
        # (iter_target_files drops non-is_file paths), so scan its path
        # components here exactly as Pass 1 does — a source token in the link's
        # OWN name would otherwise slip the gate. (symlink-to-file names are
        # already covered above via covered_symlinks.)
        for i, component in enumerate(rel.parts):
            if _is_root_press(rel, i):
                continue
            for field_name in PATH_FIELDS:
                value = fields.get(field_name)
                if value is not None and token_occurs(component, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
        try:
            link = os.readlink(path)
        except OSError:
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        for field_name, value in fields.items():
            if token_occurs(link, field_name, value):
                leaks.append(Leak(rel_posix, field_name, value, "symlink"))
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
        "add its directory to BOTH extra_exclude_dirs and verify_ignore in "
        "<target>/press/press-rules.toml — the first skips rewriting, the second skips "
        "this scan), then press again."
    )
    return "\n".join(lines)
