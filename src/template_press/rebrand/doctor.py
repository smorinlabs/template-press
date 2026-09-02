"""No-leak verification: the gate between apply() and the receipt (EMP-01).

A rebrand that leaves ANY source-identity token behind — in file content or
in a path name — is a failed rebrand. The CLI must exit non-zero and write
no receipt. Port of init_doctor.check_no_identity_leftover, generalized to
(target, identity, rules) and extended with path-name checking.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import (
    ROOT_CONTROL,
    _is_root_press,
    symlink_target_posix,
)
from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    display_forms,
    occurs,
)
from template_press.rebrand.inventory import (
    capture_surface_snapshot,
    select_inline_doctor_entries,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    ReplaceRule,
    Rules,
    rule_matches_path,
)
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    read_regular_nofollow,
    readlink_nofollow,
)
from template_press.rebrand.substitutions import (
    HuntPolicy,
    RenderedSubstitution,
    SubstitutionTable,
    hunt_occurs,
    row_matches_scope,
)
from template_press.rebrand.verifier import ignore_near_miss

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
    # E8: populated only when this leak's entry is UNTRACKED and a
    # directory-only `.gitignore` pattern near-misses it — see
    # `verifier.ignore_near_miss`. Diagnostic only; never affects pass/fail.
    note: str | None = None


def _attach_ignore_hints(
    target: Path, leaks: list[Leak], untracked: frozenset[str]
) -> list[Leak]:
    """Doctor-side counterpart of `verifier.attach_ignore_hints` (E8) — same
    cached-per-path near-miss probe, over `Leak` instead of `Finding`."""
    if not untracked:
        return leaks
    cache: dict[str, str | None] = {}
    out: list[Leak] = []
    for leak in leaks:
        if leak.path in untracked:
            if leak.path not in cache:
                cache[leak.path] = ignore_near_miss(target, Path(leak.path))
            note = cache[leak.path]
            if note is not None:
                leak = dataclasses.replace(leak, note=note)
        out.append(leak)
    return out


def _read_for_scan(path: Path) -> str | None:
    """Content for scanning; None for binary/symlink; OSError propagates.

    Unlike the engine's lenient reader, the doctor must NOT silently skip an
    unreadable file — a file it cannot scan is a file it cannot certify.
    """
    try:
        return read_regular_nofollow(path).decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary: the rewrite pass cannot alter it either


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


def _table_scope_hits(
    row: RenderedSubstitution,
    current: str,
    table: SubstitutionTable,
    executed: frozenset[str],
) -> bool:
    source = table.rename_plan.reverse_translate(
        current,
        executed_step_ids=executed,
    )
    return row_matches_scope(row, current) or row_matches_scope(row, source)


def _table_symlink_scope_hits(
    row: RenderedSubstitution,
    current_target: str,
    table: SubstitutionTable,
    executed: frozenset[str],
) -> bool:
    if _table_scope_hits(row, current_target, table, executed):
        return True
    source_target = table.rename_plan.reverse_translate(
        current_target,
        executed_step_ids=executed,
    )
    for step in table.rename_plan.steps:
        if step.step_id not in executed or row.row_id not in step.row_ids:
            continue
        if (
            source_target == step.old_prefix
            or source_target.startswith(f"{step.old_prefix}/")
            or current_target == step.new_prefix
            or current_target.startswith(f"{step.new_prefix}/")
        ):
            return True
    return False


def _leak_field(row: RenderedSubstitution, policy: HuntPolicy) -> str:
    if row.provenance[0].kind == "replace_rule":
        return "replace_rule"
    return policy.matcher.identity_field or row.provenance[0].name


def _find_table_leaks(
    target: Path,
    rules: Rules,
    table: SubstitutionTable,
    renamed: list[tuple[str, str]],
) -> list[Leak]:
    """Scan inline-doctor surfaces from compiled doctor hunt policies."""

    executed = table.rename_plan.executed_ids_for(renamed)
    doctor_hunts = tuple(
        (row, policy)
        for row in table.rows
        for policy in row.hunts
        if policy.consumer == "doctor"
    )
    snapshot = capture_surface_snapshot(target)
    entries = select_inline_doctor_entries(
        snapshot,
        built_in_exclude_files=DEFAULT_RULES.exclude_files,
        built_in_exclude_dirs=DEFAULT_RULES.exclude_dirs,
        verify_ignore=rules.verify_ignore,
        root_control=ROOT_CONTROL,
    )
    untracked = frozenset(e.rel.as_posix() for e in entries if not e.tracked)
    leaks: list[Leak] = []
    for entry in entries:
        if entry.worktree_kind == "missing" and entry.index_kind != "gitlink":
            continue
        rel = entry.rel
        posix = rel.as_posix()
        path = target / rel
        source_posix = table.rename_plan.reverse_translate(
            posix,
            executed_step_ids=executed,
        )
        scoped_hunts = tuple(
            (row, policy)
            for row, policy in doctor_hunts
            if row_matches_scope(row, posix) or row_matches_scope(row, source_posix)
        )
        for index, component in enumerate(rel.parts):
            if _is_root_press(rel, index):
                continue
            for row, policy in scoped_hunts:
                if "path" in policy.surfaces and hunt_occurs(row, policy, component):
                    leaks.append(
                        Leak(
                            posix,
                            _leak_field(row, policy),
                            row.from_value,
                            "path",
                        )
                    )
        if entry.index_kind == "gitlink" and entry.worktree_kind in (
            "directory",
            "missing",
        ):
            continue
        if entry.worktree_kind == "other":
            leaks.append(Leak(posix, "io", "unreadable", "unverifiable"))
            continue
        try:
            assert_ancestors_real(path, target)
        except SafetyError:
            leaks.append(Leak(posix, "io", "unreadable", "unverifiable"))
            continue
        if entry.worktree_kind == "symlink":
            try:
                link = readlink_nofollow(path)
            except (OSError, SafetyError):
                leaks.append(Leak(posix, "io", "unreadable", "unverifiable"))
                continue
            link_target = symlink_target_posix(rel, link)
            for row, policy in doctor_hunts:
                if (
                    "symlink" in policy.surfaces
                    and _table_symlink_scope_hits(row, link_target, table, executed)
                    and hunt_occurs(row, policy, link)
                ):
                    leaks.append(
                        Leak(
                            posix,
                            _leak_field(row, policy),
                            row.from_value,
                            "symlink",
                        )
                    )
            continue
        if entry.worktree_kind != "file":
            leaks.append(Leak(posix, "io", "unreadable", "unverifiable"))
            continue
        try:
            text = _read_for_scan(path)
        except (OSError, SafetyError):
            leaks.append(Leak(posix, "io", "unreadable", "unverifiable"))
            continue
        if text is None:
            continue
        for row, policy in scoped_hunts:
            if "content" in policy.surfaces and hunt_occurs(row, policy, text):
                leaks.append(
                    Leak(
                        posix,
                        _leak_field(row, policy),
                        row.from_value,
                        "content",
                    )
                )
    return _attach_ignore_hints(target, leaks, untracked)


def find_leaks(
    target: Path,
    source: Identity,
    rules: Rules,
    dest: Identity | None = None,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
    substring_fields: Collection[str] = frozenset(),
    rendered_rules: list[tuple[ReplaceRule, str, str]] | None = None,
    renamed: list[tuple[str, str]] | None = None,
    table: SubstitutionTable | None = None,
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

    One shared surface snapshot drives every node kind. Gitlinks contribute
    path components only; symlink leaves contribute path components and link
    text; regular files additionally contribute content.
    """
    renamed = renamed or []
    if table is not None:
        return _find_table_leaks(target, rules, table, renamed)
    rendered_rules = rendered_rules or []
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
    snapshot = capture_surface_snapshot(target)
    entries = select_inline_doctor_entries(
        snapshot,
        built_in_exclude_files=DEFAULT_RULES.exclude_files,
        built_in_exclude_dirs=DEFAULT_RULES.exclude_dirs,
        verify_ignore=rules.verify_ignore,
        root_control=ROOT_CONTROL,
    )
    untracked = frozenset(e.rel.as_posix() for e in entries if not e.tracked)
    for entry in entries:
        if entry.worktree_kind == "missing" and entry.index_kind != "gitlink":
            # Apply renames the worktree before updating Git's index. The old
            # tracked source coordinate is therefore expected to be listed as
            # missing; no node survives there to scan.
            continue
        rel = entry.rel
        rel_posix = rel.as_posix()
        path = target / rel
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
                if value is not None and occurs(
                    component, field_name, value, substring_fields
                ):
                    leaks.append(Leak(rel_posix, field_name, value, "path"))
            for _rule, frm in path_rules:
                if frm in component:
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "path"))
        if entry.index_kind == "gitlink" and entry.worktree_kind in (
            "directory",
            "missing",
        ):
            continue
        if entry.worktree_kind == "other":
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        try:
            assert_ancestors_real(path, target)
        except SafetyError:
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        if entry.worktree_kind == "symlink":
            try:
                link = readlink_nofollow(path)
            except (OSError, SafetyError):
                leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
                continue
            for field_name, value in fields.items():
                if occurs(link, field_name, value, substring_fields):
                    leaks.append(Leak(rel_posix, field_name, value, "symlink"))
            link_target_posix = symlink_target_posix(rel, link)
            for rule, frm, _to in rendered_rules:
                if (
                    rule.paths
                    and _rule_scope_hits(rule, link_target_posix, renamed)
                    and frm in link
                ):
                    leaks.append(Leak(rel_posix, "replace_rule", frm, "symlink"))
            continue
        if entry.worktree_kind != "file":
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        if path.is_symlink():
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        try:
            text = _read_for_scan(path)
        except (OSError, SafetyError):
            leaks.append(Leak(rel_posix, "io", "unreadable", "unverifiable"))
            continue
        if text is None:
            continue
        for field_name, value in fields.items():
            if occurs(text, field_name, value, substring_fields):
                leaks.append(Leak(rel_posix, field_name, value, "content"))
        for rule, frm, _to in rendered_rules:
            if (
                rule.content
                and _rule_scope_hits(rule, rel_posix, renamed)
                and frm in text
            ):
                leaks.append(Leak(rel_posix, "replace_rule", frm, "content"))
    return _attach_ignore_hints(target, leaks, untracked)


def render_leak_report(leaks: list[Leak], limit: int = 20) -> str:
    lines = [
        f"error: {len(leaks)} source-identity leftover(s) — rebrand is "
        f"INCOMPLETE; no receipt written."
    ]
    for leak in leaks[:limit]:
        lines.append(f"  [{leak.where}] {leak.path}: {leak.field}={leak.value!r}")
        if leak.note is not None:
            lines.append(f"    note: {leak.note}")
    if len(leaks) > limit:
        lines.append(f"  … and {len(leaks) - limit} more")
    lines.append(
        "hint: restore the target (git -C <target> checkout . && git clean "
        "-fd), fix the root cause (or, for content that is VALID to keep, "
        "add its directory to BOTH extra_exclude_dirs and verify_ignore in "
        "<target>/press/press-rules.toml — the first skips rewriting, the "
        "second skips this scan; a [symlink] leak is keyed on the link's "
        "OWN name, not its target's directory, so also add the link's own "
        "name to verify_ignore), then press again."
    )
    return "\n".join(lines)
