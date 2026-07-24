"""No-leak verification: the gate between apply() and the receipt (EMP-01).

A rebrand that leaves ANY source-identity token behind — in file content or
in a path name — is a failed rebrand. The CLI must exit non-zero and write
no receipt. Port of init_doctor.check_no_identity_leftover, generalized to
(target, identity, rules) and extended with path-name checking.
"""

from __future__ import annotations

import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import (
    _git_listed,
    _is_root_press,
    iter_target_files,
    symlink_target_posix,
)
from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    display_forms,
    token_occurs,
)
from template_press.rebrand.rules import ReplaceRule, Rules, rule_matches_path

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


def _occurs(
    text: str, field_name: str, value: str, substring_fields: Collection[str]
) -> bool:
    """Dispatch to plain substring membership for an opted-in field.

    Mirrors the engine's own dispatch (``_apply_replacements``,
    ``_renamed_rel``): when ``substring_rewrite_fields`` promises glued-token
    coverage for a field, the doctor's scan must use the same plain-substring
    posture — the boundary-guarded ``token_occurs`` would miss a glued
    leftover (``plbpOwned``) that the substring rewrite is meant to close.
    """
    if field_name in substring_fields:
        return value in text
    return token_occurs(text, field_name, value)


def _reverse_renamed_posix(posix: str, renamed: list[tuple[str, str]]) -> str:
    """Undo every prefix rename recorded in ``renamed`` (new -> old), longest
    new-prefix first, applied iteratively until no further substitution
    fires (Fix F1).

    A rename entry's NEW prefix substitutes back to its OLD prefix when
    ``posix`` equals it exactly or starts with it plus ``"/"`` — mirroring
    how ``_rename_pass_once``/``build_plan`` record ``(old_prefix,
    new_prefix)`` collapsed to the shallowest differing ancestor per pass. A
    path may have crossed several such ancestors across SEPARATE passes, so
    this keeps substituting (bounded to ``len(renamed) + 1`` rounds — more
    than enough for any chain of disjoint renames) rather than doing it once.
    """
    ordered = sorted(renamed, key=lambda pair: -len(pair[1]))
    for _ in range(len(ordered) + 1):
        for old, new in ordered:
            if posix == new:
                posix = old
                break
            if posix.startswith(new + "/"):
                posix = old + posix[len(new) :]
                break
        else:
            break
    return posix


def _rule_scope_hits(
    rule: ReplaceRule, posix: str, renamed: list[tuple[str, str]]
) -> bool:
    """Rule-literal scope match against BOTH the CURRENT path and its
    PRE-rename original (Fix F1).

    A token-rename pass can move a file's ancestor out from under a
    ``files`` scope written against the source layout before the SAME
    [[replace]] rule ever gets a chance to re-evaluate against it (the
    rewrite-side scope migration is a documented 0008 limitation, left
    unfixed there) — so scoping the doctor's rule-literal scan against the
    current path alone would silently certify the missed rename. Over-flags
    rather than misses: a hit on EITHER path counts.
    """
    return rule_matches_path(rule, posix) or rule_matches_path(
        rule, _reverse_renamed_posix(posix, renamed)
    )


def find_leaks(
    target: Path,
    source: Identity,
    rules: Rules,
    dest: Identity | None = None,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
    substring_fields: Collection[str] = frozenset(),
    rendered_rules: list[tuple[ReplaceRule, str, str]] | None = None,
    renamed: list[tuple[str, str]] | None = None,
) -> list[Leak]:
    """Scan for surviving source-identity tokens.

    When ``dest`` is given, only fields that actually CHANGED are scanned:
    an unchanged field (same author across a rename) is not a leak — its
    token legitimately remains everywhere. Without ``dest`` all fields are
    scanned (full-rebrand semantics).

    ``rendered_rules`` (rule, FROM, TO) triples from
    ``engine.rendered_replace_rules`` — when a ``[[replace]]`` rule is the
    ONLY matcher for a boundary-unmatched rendered form (e.g. an
    underscore-glued ``_{app_name}_owned``), the ordinary field-based token
    scan can miss a surviving FROM literal entirely (a containment-skipped
    symlink retarget, or any other rewrite the engine could not perform).
    Each rule is scanned scoped by what it was supposed to touch:
    ``rule.content`` against file CONTENT (glob-scoped via
    ``rule_matches_path`` against the file's own rel posix), and
    ``rule.paths`` against PATH COMPONENTS (glob-scoped the same way,
    mirroring ``_renamed_rel``) and SYMLINK text (scoped against the link
    TARGET's normalized rel path, mirroring ``_retarget_symlinks``).

    ``renamed`` (Fix F1) — ``ApplyReport.renamed`` (old_prefix, new_prefix)
    pairs from every rename ``apply()`` actually executed — lets each
    rule-literal scope check (``_rule_scope_hits``) recover a scanned
    path/symlink-target's PRE-rename original before testing ``rule.files``:
    a token-rename pass can move a rule-scoped path's ancestor out from under
    its own ``files`` glob before that same rule ever gets to re-evaluate
    against it, leaving a stale FROM literal that a current-path-only scope
    check would miss entirely (a receipt/verify contradiction). Omitted
    (``None``/empty), this degrades to the prior current-path-only behavior.
    """
    rendered_rules = rendered_rules or []
    renamed = renamed or []
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
    # Path-component scans must cover display-form fields too (Fix 2): the
    # doctor already expands display_name into its exact forms for the
    # content/symlink scans above, but a leftover PyLaunchBlueprint/ dir
    # would otherwise pass the path-component loops below, which iterated
    # PATH_FIELDS only.
    path_fields = (
        *PATH_FIELDS,
        *(f"display_name_{form}" for form in display_form_names),
    )
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
                if _occurs(text, field_name, value, substring_fields):
                    leaks.append(Leak(rel_posix, field_name, value, "content"))
            for rule, frm, _to in rendered_rules:
                if (
                    rule.content
                    and _rule_scope_hits(rule, rel_posix, renamed)
                    and frm in text
                ):
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "content"))
        if path.is_symlink():
            # A symlink's bytes are its target string, not file content — an
            # identity token embedded there would dangle/leak in a pressed fork.
            covered_symlinks.add(rel_posix)
            link = os.readlink(path)
            for field_name, value in fields.items():
                if _occurs(link, field_name, value, substring_fields):
                    leaks.append(Leak(rel_posix, field_name, value, "symlink"))
            # Rule scope for symlink text is the link's TARGET, normalized —
            # mirroring _retarget_symlinks — never the link's own location.
            link_target_posix = symlink_target_posix(rel, link)
            for rule, frm, _to in rendered_rules:
                if (
                    rule.paths
                    and _rule_scope_hits(rule, link_target_posix, renamed)
                    and frm in link
                ):
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "symlink"))
        path_rules = [
            (rule, frm)
            for rule, frm, _to in rendered_rules
            if rule.paths and _rule_scope_hits(rule, rel_posix, renamed)
        ]
        for i, component in enumerate(rel.parts):
            if _is_root_press(rel, i):
                continue
            for field_name in path_fields:
                value = fields.get(field_name)
                if value is not None and _occurs(
                    component, field_name, value, substring_fields
                ):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
            for _rule, frm in path_rules:
                if frm in component:
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "path"))
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
        path_rules = [
            (rule, frm)
            for rule, frm, _to in rendered_rules
            if rule.paths and _rule_scope_hits(rule, rel_posix, renamed)
        ]
        for i, component in enumerate(rel.parts):
            if _is_root_press(rel, i):
                continue
            for field_name in path_fields:
                value = fields.get(field_name)
                if value is not None and _occurs(
                    component, field_name, value, substring_fields
                ):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
            for _rule, frm in path_rules:
                if frm in component:
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "path"))
        try:
            link = os.readlink(path)
        except OSError:
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        for field_name, value in fields.items():
            if _occurs(link, field_name, value, substring_fields):
                leaks.append(Leak(rel_posix, field_name, value, "symlink"))
        link_target_posix = symlink_target_posix(rel, link)
        for rule, frm, _to in rendered_rules:
            if (
                rule.paths
                and _rule_scope_hits(rule, link_target_posix, renamed)
                and frm in link
            ):
                leaks.append(Leak(rel_posix, "replace_rule", frm, "symlink"))
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
