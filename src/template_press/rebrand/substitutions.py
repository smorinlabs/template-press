"""Compile rebrand mechanisms into one immutable substitution table."""

from __future__ import annotations

import fnmatch
import functools
import os
import posixpath
import re
import stat
import tomllib
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from template_press.rebrand.cargo_manifest import (
    CargoPackageMetadata,
    DeclaredPath,
    Table,
    auto_discovered_bins,
    auto_discovery_enabled,
    auto_target_sections,
    cargo_manifest_files,
    declared_cargo_paths,
    declared_target_names,
    inferred_target_candidates,
    inferred_target_paths,
    named_target_files,
    package_table,
    read_all_cargo_metadata,
    read_cargo_facts,
)
from template_press.rebrand.identity import (
    CARGO_BIN_ENV_TAG,
    CARGO_EXACT_PREFIX,
    CARGO_IDENT_PREFIX,
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    cargo_bin_env_pairs,
    cargo_field_values,
    cargo_ident,
    cargo_name_pairs,
    cargo_split_roles,
    display_forms,
    distinct_hyphen_form,
    exact_name_rank,
    field_renames_paths,
    is_cargo_field,
    occurs,
    pair_renames_paths,
    replace_token,
    token_pattern,
)
from template_press.rebrand.ignores import apply_ignores
from template_press.rebrand.inventory import (
    SurfaceEntry,
    SurfaceSnapshot,
    VisibilityInput,
    WorktreeKind,
    capture_surface_snapshot,
    rewrite_surface_texts,
    select_content_rewrite_entries,
    select_rename_entries,
    select_symlink_entries,
)
from template_press.rebrand.keep_names import (
    KeepCheck,
    RewrittenForms,
    UndeclaredName,
    check_keep_surfaces,
    component_kept_spans,
    disjoint_from_kept,
    disjoint_matches,
    find_outside_kept,
    kept_spans,
    loses_kept_name,
    matches_outside_kept,
    splice_outside_kept,
)
from template_press.rebrand.matcher import (
    find_occurrences,
    identity_pattern,
    substring_pattern,
)
from template_press.rebrand.node_manifest import read_node_manifest
from template_press.rebrand.pathing import (
    ROOT_CONTROL,
    regenerate_dir_prefixes,
    symlink_target_posix,
)
from template_press.rebrand.pipeline import (
    MAX_RENAME_PASSES,
    MatcherSpec,
    PipelineCandidate,
    StabilitySink,
    validate_pipeline,
)
from template_press.rebrand.rules import (
    CargoSplit,
    ReplaceRule,
    Rules,
    render_replace_pattern,
    rule_matches_path,
)
from template_press.rebrand.rust_text import (
    InlineModule,
    compiled_markdown_lines,
    cut_module_docs,
    quoted_spans,
    quoting_renames,
    rust_code_view,
    rust_path_literals,
    rust_source_structure,
    rust_strings,
    span_within,
    split_rust_replacements,
    string_at,
)
from template_press.rebrand.safety import (
    RenameClosureUnauthorized,
    SafeRelPath,
    SafetyError,
    assert_ancestors_real,
    is_regular_lstat,
    read_regular_nofollow,
    readlink_nofollow,
)
from template_press.rebrand.verifier import Finding, changed_verify_fields
from template_press.rebrand.verify_config import VerifyConfig, effective_verify_fields

Surface = Literal["content", "path", "symlink"]
HuntConsumer = Literal["doctor", "reset_stub", "reset_path", "regeneration"]
ScopeCoordinates = Literal["source", "current_or_source"]
ProvenanceKind = Literal["identity", "display_form", "replace_rule", "manifest_name"]


@dataclass(frozen=True)
class Provenance:
    """One identity field, display form, or declaration behind a row."""

    kind: ProvenanceKind
    name: str
    declaration_index: int | None = None
    pattern: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Scope:
    """Declared POSIX path globs; empty means every path."""

    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class HuntPolicy:
    """How one consumer searches for a surviving source value."""

    consumer: HuntConsumer
    matcher: MatcherSpec
    surfaces: frozenset[Surface]
    scope_coordinates: ScopeCoordinates


@dataclass(frozen=True)
class RenderedSubstitution:
    """One normalized, rendered source-to-destination substitution."""

    row_id: str
    provenance: tuple[Provenance, ...]
    matcher: MatcherSpec
    from_value: str
    to_value: str
    rewrite_surfaces: frozenset[Surface]
    hunts: tuple[HuntPolicy, ...]
    scope: Scope
    # Set only on a [[cargo_split]] row for ``.rs`` files: the package spelling
    # that a provable string literal takes instead of ``to_value``.
    package_value: str | None = None


@dataclass(frozen=True)
class RenameStep:
    """One executable shallowest-prefix move in a fixed-point rename plan."""

    step_id: str
    old_prefix: str
    new_prefix: str
    pass_number: int
    row_ids: tuple[str, ...]
    source_entries: tuple[str, ...]
    expected_kind: WorktreeKind
    predecessor_step_ids: tuple[str, ...] = ()
    closure: tuple[tuple[str, WorktreeKind], ...] = ()
    destination_kind: WorktreeKind | None = None


@dataclass(frozen=True)
class RenamePlan:
    """Ordered target-specific path moves compiled from one surface snapshot."""

    steps: tuple[RenameStep, ...] = ()
    visibility_inputs: tuple[VisibilityInput, ...] = ()
    virtual_translations: tuple[tuple[str, str, str], ...] = ()
    source_entries: tuple[SurfaceEntry, ...] = ()
    symlink_inputs: tuple[tuple[str, str], ...] = ()

    def as_mapping(self) -> dict[str, str]:
        """Compatibility view of every ordered old-to-new prefix step."""

        return {step.old_prefix: step.new_prefix for step in self.steps}

    def translate(
        self,
        posix: str,
        *,
        executed_step_ids: frozenset[str] | None = None,
    ) -> str:
        """Translate a source coordinate through planned or executed steps."""

        current = posix
        for step in self.steps:
            if executed_step_ids is not None and step.step_id not in executed_step_ids:
                continue
            if current == step.old_prefix:
                current = step.new_prefix
            elif current.startswith(f"{step.old_prefix}/"):
                current = f"{step.new_prefix}{current[len(step.old_prefix) :]}"
        return current

    def reverse_translate(
        self,
        posix: str,
        *,
        executed_step_ids: frozenset[str] | None = None,
    ) -> str:
        """Translate a current coordinate back through plan steps."""

        current = posix
        for step in reversed(self.steps):
            if executed_step_ids is not None and step.step_id not in executed_step_ids:
                continue
            if current == step.new_prefix:
                current = step.old_prefix
            elif current.startswith(f"{step.new_prefix}/"):
                current = f"{step.old_prefix}{current[len(step.new_prefix) :]}"
        return current

    def executed_ids_for(
        self, renamed: tuple[tuple[str, str], ...] | list[tuple[str, str]]
    ) -> frozenset[str]:
        """Resolve legacy executed prefix pairs to stable step identifiers."""

        executed_pairs = set(renamed)
        return frozenset(
            step.step_id
            for step in self.steps
            if (step.old_prefix, step.new_prefix) in executed_pairs
        )


@dataclass(frozen=True)
class SubstitutionTable:
    """Ordered rendered rows plus their target-specific rename plan."""

    rows: tuple[RenderedSubstitution, ...]
    rename_plan: RenamePlan
    keep_names: tuple[str, ...] = ()


def row_matches_scope(row: RenderedSubstitution, posix: str) -> bool:
    """Whether a rendered row's declared scope includes one POSIX path."""

    return _scope_matches(row.scope, posix)


def _project_name(text: str) -> object:
    try:
        return tomllib.loads(text).get("project", {}).get("name")
    except (tomllib.TOMLDecodeError, AttributeError):
        return None


def _project_name_span(
    text: str, from_value: str, to_value: str
) -> tuple[int, int] | None:
    """The occurrence of ``from_value`` that TOML resolves to ``[project].name``."""

    before = _project_name(text)
    for match in re.finditer(re.escape(from_value), text):
        candidate = text[: match.start()] + to_value + text[match.end() :]
        if _project_name(candidate) != before:
            return match.span()
    return None


def _rewrite_project_name(text: str, from_value: str, to_value: str) -> str:
    """Replace only the assignment that TOML resolves to ``[project].name``."""

    span = _project_name_span(text, from_value, to_value)
    if span is None:
        return text
    return text[: span[0]] + to_value + text[span[1] :]


@functools.lru_cache(maxsize=4096)
def _literal_pattern(value: str) -> re.Pattern[str]:
    return re.compile(re.escape(value))


def _validate_rewrite_row(row: RenderedSubstitution) -> None:
    if (
        row.provenance[0].kind == "manifest_name"
        or row.package_value is not None
        or row.matcher.algorithm == "literal"
        or row.matcher.substring
    ):
        return
    if row.matcher.algorithm != "conservative":
        raise ValidationError(
            f"rewrite row {row.row_id} uses non-rewrite matcher "
            f"{row.matcher.algorithm!r}"
        )
    if row.matcher.identity_field is None:
        raise ValidationError(f"rewrite row {row.row_id} has no identity field")


def _rewrite_outside_kept(
    row: RenderedSubstitution, text: str, kept: Sequence[tuple[int, int]]
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Replace matches disjoint from ``kept``; return text and shifted spans.

    The pattern runs over the whole current text, so boundaries see true
    neighbors.
    """

    _validate_rewrite_row(row)
    if row.from_value and row.from_value not in text:
        return text, tuple(kept)
    if row.package_value is not None:
        return _rewrite_rust_split(row, text, kept)
    replaced: list[tuple[int, int]] = []
    if row.provenance[0].kind == "manifest_name":
        span = _project_name_span(text, row.from_value, row.to_value)
        if span is not None and disjoint_from_kept(span, kept):
            replaced.append(span)
    else:
        if row.matcher.algorithm == "literal" or row.matcher.substring:
            pattern = _literal_pattern(row.from_value)
        else:
            field = row.matcher.identity_field
            if field is None:
                raise ValidationError(f"rewrite row {row.row_id} has no identity field")
            pattern = token_pattern(field, row.from_value) or _literal_pattern(
                row.from_value
            )
        replaced = disjoint_matches(pattern, text, kept)
    return splice_outside_kept(text, replaced, row.to_value, kept)


def _rewrite_rust_split(
    row: RenderedSubstitution, text: str, kept: Sequence[tuple[int, int]]
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Identifier spelling in Rust code, package spelling in provable strings.

    A string occurrence with no provable spelling stays as it is, so the split
    preflight reports it before any write.
    """
    if row.from_value and row.from_value not in text:
        return text, tuple(kept)
    field = row.matcher.identity_field or ""
    pattern = token_pattern(field, row.from_value) or _literal_pattern(row.from_value)
    spans = disjoint_matches(pattern, text, kept)
    if not spans:
        return text, tuple(kept)
    choices = split_rust_replacements(
        text, spans, row.from_value, row.to_value, row.package_value or ""
    )
    pieces: list[str] = []
    copied = 0
    shifts: list[tuple[int, int]] = []
    for (start, end), choice in zip(spans, choices, strict=True):
        if choice is None:
            continue
        pieces.append(text[copied:start])
        pieces.append(choice)
        copied = end
        shifts.append((end, len(choice) - (end - start)))
    if not shifts:
        return text, tuple(kept)
    pieces.append(text[copied:])
    if not kept:
        return "".join(pieces), ()
    n_shifts = len(shifts)
    shifted: list[tuple[int, int]] = []
    delta = 0
    shift_idx = 0
    prev_low = -1
    for low, high in kept:
        if low < prev_low:
            delta = 0
            shift_idx = 0
        while shift_idx < n_shifts and shifts[shift_idx][0] <= low:
            delta += shifts[shift_idx][1]
            shift_idx += 1
        prev_low = low
        shifted.append((low + delta, high + delta))
    return "".join(pieces), tuple(shifted)


def rewrite_file(
    rows: Iterable[RenderedSubstitution],
    text: str,
    keep_names: Sequence[str] = (),
    *,
    kept: Sequence[tuple[int, int]] | None = None,
) -> tuple[str, tuple[RenderedSubstitution, ...]]:
    """Apply ``rows`` in order; return the text and the rows that changed it.

    Kept spans come from the ORIGINAL text and are carried through every row.
    An earlier row can therefore neither expose a kept name to a later row by
    changing its neighbor nor create a new kept name.
    """

    active_kept: tuple[tuple[int, int], ...] | None = (
        tuple(kept) if kept is not None else (None if keep_names else ())
    )
    current = text
    changed: list[RenderedSubstitution] = []
    for row in rows:
        _validate_rewrite_row(row)
        if row.from_value and row.from_value not in current:
            continue
        if active_kept is None:
            active_kept = kept_spans(text, keep_names)
        if active_kept:
            updated, active_kept = _rewrite_outside_kept(row, current, active_kept)
        else:
            updated = rewrite_with_row(row, current)
        if updated != current:
            changed.append(row)
            current = updated
    return current, tuple(changed)


def rewrite_with_row(row: RenderedSubstitution, text: str) -> str:
    """Apply one row's matcher without consulting source configuration."""

    _validate_rewrite_row(row)
    if row.from_value and row.from_value not in text:
        return text
    if row.provenance[0].kind == "manifest_name":
        return _rewrite_project_name(text, row.from_value, row.to_value)
    if row.package_value is not None:
        return _rewrite_rust_split(row, text, ())[0]
    if row.matcher.algorithm == "literal" or row.matcher.substring:
        return text.replace(row.from_value, row.to_value)
    field = row.matcher.identity_field
    if field is None:
        raise ValidationError(f"rewrite row {row.row_id} has no identity field")
    return replace_token(text, field, row.from_value, row.to_value)


def _hunt_pattern(row: RenderedSubstitution, matcher: MatcherSpec) -> re.Pattern[str]:
    """The regular expression equivalent of one compiled hunt matcher."""

    if matcher.algorithm == "literal":
        return _literal_pattern(row.from_value)
    field = matcher.identity_field
    if field is None:
        raise ValidationError(f"hunt for row {row.row_id} has no identity field")
    if matcher.algorithm == "paranoid":
        if matcher.substring:
            return substring_pattern(row.from_value)
        return identity_pattern(field, row.from_value)
    if matcher.substring:
        return _literal_pattern(row.from_value)
    return token_pattern(field, row.from_value) or _literal_pattern(row.from_value)


def hunt_occurs(
    row: RenderedSubstitution,
    policy: HuntPolicy,
    text: str,
    kept: Sequence[tuple[int, int]] = (),
) -> bool:
    """Apply one compiled consumer hunt to text, outside ``kept`` spans."""

    matcher = policy.matcher
    if matcher.algorithm == "literal":
        if row.from_value and row.from_value not in text:
            return False
        if not kept:
            return row.from_value in text
        return bool(matches_outside_kept(_hunt_pattern(row, matcher), text, kept))
    field = matcher.identity_field
    if field is None:
        raise ValidationError(f"hunt for row {row.row_id} has no identity field")
    if (
        matcher.algorithm != "paranoid"
        and row.from_value
        and row.from_value not in text
    ):
        return False
    if kept:
        return bool(matches_outside_kept(_hunt_pattern(row, matcher), text, kept))
    if matcher.algorithm == "paranoid":
        return bool(
            find_occurrences(
                text,
                field,
                row.from_value,
                substring=matcher.substring,
            )
        )
    return occurs(
        text,
        field,
        row.from_value,
        frozenset({field}) if matcher.substring else frozenset(),
    )


def matching_hunts(
    table: SubstitutionTable,
    *,
    consumer: HuntConsumer,
    surface: Surface,
    text: str,
    source_scope_path: str,
    boundary_identity: bool = False,
) -> tuple[tuple[RenderedSubstitution, HuntPolicy], ...]:
    """Return compiled consumer hunts that match one scoped subject.

    ``boundary_identity`` swaps paranoid substring identity hunts for
    boundary-safe matching (regen ``scan = "boundary"``). The swap happens
    INSIDE the hunt: a post-filter over substring-prefiltered results would
    drop hash noise but also lose the boundary matcher's separator/case
    variant catches — ``demo-widget`` is invisible to the literal substring
    matcher yet a real leak of ``demo_widget``.
    """

    kept = kept_spans(text, table.keep_names)
    matches: list[tuple[RenderedSubstitution, HuntPolicy]] = []
    for row in table.rows:
        if not row_matches_scope(row, source_scope_path):
            continue
        for policy in row.hunts:
            if policy.consumer != consumer or surface not in policy.surfaces:
                continue
            if (
                boundary_identity
                and policy.matcher.algorithm == "paranoid"
                and policy.matcher.substring
                and policy.matcher.identity_field is not None
            ):
                occurs_here = bool(
                    find_outside_kept(
                        text,
                        policy.matcher.identity_field,
                        row.from_value,
                        substring=False,
                        kept=kept,
                    )
                )
            else:
                occurs_here = hunt_occurs(row, policy, text, kept)
            if occurs_here:
                matches.append((row, policy))
    return tuple(matches)


def declared_rule_triples(
    table: SubstitutionTable,
) -> list[tuple[ReplaceRule, str, str]]:
    """Compatibility view for callers not yet converted to hunt policies."""

    triples: list[tuple[ReplaceRule, str, str]] = []
    for row in table.rows:
        provenance = row.provenance[0]
        if provenance.kind != "replace_rule":
            continue
        if provenance.pattern is None or provenance.reason is None:
            raise ValidationError(
                f"declared row {row.row_id} is missing pattern or reason provenance"
            )
        triples.append(
            (
                ReplaceRule(
                    pattern=provenance.pattern,
                    reason=provenance.reason,
                    files=row.scope.files,
                    paths="path" in row.rewrite_surfaces,
                    content="content" in row.rewrite_surfaces,
                ),
                row.from_value,
                row.to_value,
            )
        )
    return triples


def _scope_matches(scope: Scope, posix: str) -> bool:
    return not scope.files or any(
        fnmatch.fnmatchcase(posix, pattern) for pattern in scope.files
    )


def _rewrite_component(row: RenderedSubstitution, component: str) -> str:
    if row.matcher.algorithm == "literal":
        return component.replace(row.from_value, row.to_value)
    if row.matcher.algorithm != "conservative":
        raise ValidationError(
            f"rename row {row.row_id} uses non-rewrite matcher "
            f"{row.matcher.algorithm!r}"
        )
    field = row.matcher.identity_field
    if field is None:
        raise ValidationError(f"rename row {row.row_id} has no identity field")
    if row.matcher.substring:
        return component.replace(row.from_value, row.to_value)
    return replace_token(component, field, row.from_value, row.to_value)


def _rewritten_path(
    posix: str,
    path_rows: tuple[RenderedSubstitution, ...],
    keep_names: Sequence[str] = (),
) -> tuple[str, dict[int, tuple[str, ...]]]:
    rel = Path(posix)
    parts: list[str] = []
    row_ids_by_component: dict[int, list[str]] = {}
    for component_index, component in enumerate(rel.parts):
        if component_index == 0 and component == "press":
            parts.append(component)
            continue
        rewritten = component
        kept = component_kept_spans(rel.parts, component_index, keep_names)
        for row in path_rows:
            if not _scope_matches(row.scope, posix):
                continue
            if kept:
                updated, kept = _rewrite_outside_kept(row, rewritten, kept)
            else:
                updated = _rewrite_component(row, rewritten)
            if updated != rewritten:
                row_ids_by_component.setdefault(component_index, []).append(row.row_id)
                rewritten = updated
        if component and not rewritten:
            raise ValidationError(
                f"rename would empty a path component of {posix!r} — refusing"
            )
        if rewritten in (".", ".."):
            raise ValidationError(
                f"rename would collapse a path component of {posix!r} to "
                f"{rewritten!r} — refusing"
            )
        parts.append(rewritten)
    return Path(*parts).as_posix(), {
        index: tuple(dict.fromkeys(row_ids))
        for index, row_ids in row_ids_by_component.items()
    }


def _compile_rename_plan(
    rows: tuple[RenderedSubstitution, ...],
    snapshot: SurfaceSnapshot,
    keep_names: Sequence[str] = (),
) -> RenamePlan:
    path_rows = tuple(row for row in rows if "path" in row.rewrite_surfaces)
    current_by_source = {
        entry.rel.as_posix(): entry.rel.as_posix() for entry in snapshot.entries
    }
    kind_by_source = {
        entry.rel.as_posix(): entry.worktree_kind for entry in snapshot.entries
    }
    prior_step_ids_by_source: dict[str, list[str]] = {}
    steps: list[RenameStep] = []

    for pass_number in range(1, MAX_RENAME_PASSES + 1):
        grouped: dict[str, tuple[str, set[str], set[str]]] = {}
        for source, current in current_by_source.items():
            rewritten, row_ids_by_component = _rewritten_path(
                current, path_rows, keep_names
            )
            if rewritten == current:
                continue
            current_parts = Path(current).parts
            rewritten_parts = Path(rewritten).parts
            shallowest = next(
                index
                for index, (before, after) in enumerate(
                    zip(current_parts, rewritten_parts, strict=True)
                )
                if before != after
            )
            old_prefix = Path(*current_parts[: shallowest + 1]).as_posix()
            new_prefix = Path(*rewritten_parts[: shallowest + 1]).as_posix()
            row_ids = set(row_ids_by_component[shallowest])
            existing = grouped.get(old_prefix)
            if existing is None:
                grouped[old_prefix] = (new_prefix, row_ids, {source})
                continue
            existing_destination, existing_rows, existing_sources = existing
            if existing_destination != new_prefix:
                raise ValidationError(
                    f"shared prefix {old_prefix!r} has conflicting destinations "
                    f"{existing_destination!r} and {new_prefix!r}"
                )
            existing_rows.update(row_ids)
            existing_sources.add(source)

        if not grouped:
            return RenamePlan(tuple(steps), snapshot.visibility_inputs)

        pass_steps: list[RenameStep] = []
        ordered_groups = sorted(
            grouped.items(),
            key=lambda item: (-len(Path(item[0]).parts), item[0]),
        )
        for step_index, (old_prefix, group) in enumerate(ordered_groups, start=1):
            new_prefix, row_ids, source_entries = group
            predecessors = tuple(
                dict.fromkeys(
                    step_id
                    for source in sorted(source_entries)
                    for step_id in prior_step_ids_by_source.get(source, ())
                )
            )
            exact_sources = [
                source
                for source in source_entries
                if current_by_source[source] == old_prefix
            ]
            expected_kind: WorktreeKind = (
                kind_by_source[exact_sources[0]] if exact_sources else "directory"
            )
            pass_steps.append(
                RenameStep(
                    step_id=f"rename:{pass_number}:{step_index}",
                    old_prefix=old_prefix,
                    new_prefix=new_prefix,
                    pass_number=pass_number,
                    row_ids=tuple(
                        row.row_id for row in path_rows if row.row_id in row_ids
                    ),
                    source_entries=tuple(sorted(source_entries)),
                    expected_kind=expected_kind,
                    predecessor_step_ids=predecessors,
                )
            )

        for step in pass_steps:
            for source, current in current_by_source.items():
                if current != step.old_prefix and not current.startswith(
                    f"{step.old_prefix}/"
                ):
                    continue
                suffix = current[len(step.old_prefix) :]
                moved = f"{step.new_prefix}{suffix}"
                if loses_kept_name(current, moved, keep_names):
                    raise ValidationError(
                        f"keep_names: moving {step.old_prefix!r} to "
                        f"{step.new_prefix!r} would change a kept name in "
                        f"{current!r}"
                    )
                current_by_source[source] = moved
                prior_step_ids_by_source.setdefault(source, []).append(step.step_id)
        steps.extend(pass_steps)

    raise ValidationError(
        f"rename plan did not reach a fixpoint after {MAX_RENAME_PASSES} passes"
    )


def _node_kind(path: Path) -> WorktreeKind:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    return "other"


def _source_prefix_for_step(
    step: RenameStep,
    prior_steps: tuple[RenameStep, ...],
) -> str:
    source_prefix = step.old_prefix
    for prior in reversed(prior_steps):
        if source_prefix == prior.new_prefix:
            source_prefix = prior.old_prefix
        elif source_prefix.startswith(f"{prior.new_prefix}/"):
            source_prefix = (
                f"{prior.old_prefix}{source_prefix[len(prior.new_prefix) :]}"
            )
    return source_prefix


def _prefix_closure(
    target: Path,
    source_prefix: str,
    snapshot: SurfaceSnapshot,
    phase: str,
) -> tuple[tuple[str, WorktreeKind], ...]:
    """Capture and authorize every no-follow node carried by one move.

    Structural refusals — a node that vanished mid-walk, a directory that
    cannot be read, or a worktree/inventory kind mismatch — stay immediate
    ``SafetyError`` raises: those indicate the closure changed underneath the
    planner, not an authorization gap. Authorization findings (a node absent
    from the surface inventory, or an uninventoried empty directory) are
    instead collected across the whole walk and reported together as one
    ``RenameClosureUnauthorized`` (E2), so an operator sees every offending
    path in one refusal instead of fixing them one at a time.
    """

    indexed = {entry.rel.as_posix(): entry for entry in snapshot.entries}
    covered_gitlinks = [
        posix
        for posix, entry in indexed.items()
        if entry.index_kind == "gitlink"
        and (posix == source_prefix or posix.startswith(f"{source_prefix}/"))
    ]
    if covered_gitlinks:
        raise SafetyError(
            f"rename prefix {source_prefix!r} would carry gitlink "
            f"{covered_gitlinks[0]!r} — submodule boundaries are immovable"
        )

    root = target / source_prefix
    assert_ancestors_real(root, target)
    closure: list[tuple[str, WorktreeKind]] = []
    findings: list[tuple[str, str]] = []

    def walk(path: Path) -> int:
        rel = path.relative_to(target).as_posix()
        kind = _node_kind(path)
        if kind == "missing":
            raise SafetyError(
                f"rename prefix closure changed during planning: {rel!r} is missing"
            )
        closure.append((rel, kind))
        if kind == "directory":
            child_count = 0
            try:
                with os.scandir(path) as iterator:
                    children = sorted(iterator, key=lambda item: item.name)
            except OSError as exc:
                raise SafetyError(
                    f"cannot inspect rename prefix closure {rel!r}: {exc}"
                ) from exc
            for child in children:
                child_count += walk(Path(child.path))
            if child_count == 0:
                # Collected, not raised immediately (E2) — return 1 so this
                # directory still counts as one node toward its own parent's
                # child_count, the same as it would have counted had it not
                # been empty. Otherwise an uninventoried empty directory
                # would make its parent look empty too, cascading a single
                # finding into a spurious chain of empty-dir findings.
                findings.append(("empty-dir", rel))
                return 1
            return child_count + 1
        entry = indexed.get(rel)
        if entry is None:
            # Collected, not raised immediately (E2).
            findings.append(("absent", rel))
            return 1
        if kind == "other" or entry.worktree_kind != kind:
            raise SafetyError(
                f"rename prefix closure kind mismatch for {rel!r}: "
                f"inventory={entry.worktree_kind}, worktree={kind}"
            )
        return 1

    walk(root)
    if findings:
        raise RenameClosureUnauthorized(source_prefix, tuple(findings), phase)
    return tuple(sorted(closure))


def _enrich_rename_plan(
    target: Path | None,
    plan: RenamePlan,
    snapshot: SurfaceSnapshot,
) -> RenamePlan:
    if target is None:
        return plan
    enriched: list[RenameStep] = []
    for step in plan.steps:
        source_prefix = _source_prefix_for_step(step, tuple(enriched))
        enriched.append(
            replace(
                step,
                closure=_prefix_closure(target, source_prefix, snapshot, "plan"),
                destination_kind=_node_kind(target / step.new_prefix),
            )
        )
    return replace(plan, steps=tuple(enriched))


def revalidate_rename_plan(target: Path, plan: RenamePlan) -> None:
    """Refuse live closure or destination drift before the first mutation."""

    snapshot = SurfaceSnapshot(plan.source_entries, plan.visibility_inputs)
    prior: list[RenameStep] = []
    for step in plan.steps:
        source_prefix = _source_prefix_for_step(step, tuple(prior))
        current_closure = _prefix_closure(target, source_prefix, snapshot, "apply")
        if current_closure != step.closure:
            raise SafetyError(
                f"rename prefix closure changed after planning: {source_prefix!r}"
            )
        current_destination = _node_kind(target / step.new_prefix)
        if current_destination != step.destination_kind:
            raise SafetyError(
                f"rename destination changed after planning: {step.new_prefix!r} "
                f"(expected {step.destination_kind}, found {current_destination})"
            )
        prior.append(step)


def _virtual_path_translation(
    posix: str,
    path_rows: tuple[RenderedSubstitution, ...],
    keep_names: Sequence[str] = (),
) -> str:
    current = posix
    for _ in range(MAX_RENAME_PASSES):
        rewritten, _row_ids = _rewritten_path(current, path_rows, keep_names)
        if rewritten == current:
            return current
        current = rewritten
    raise ValidationError(
        f"virtual path translation did not reach a fixpoint after "
        f"{MAX_RENAME_PASSES} passes for {posix!r}"
    )


def _path_occupant_nofollow(target: Path, posix: str) -> tuple[str, bool] | None:
    """Return an occupied coordinate prefix and whether it is a symlink."""

    parts = Path(posix).parts
    current = target
    prefix_parts: list[str] = []
    for index, part in enumerate(parts):
        prefix_parts.append(part)
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return None
        if index < len(parts) - 1 and stat.S_ISDIR(mode):
            continue
        return "/".join(prefix_parts), stat.S_ISLNK(mode)
    return posix, False


def _compile_virtual_translations(
    target: Path | None,
    rows: tuple[RenderedSubstitution, ...],
    snapshot: SurfaceSnapshot,
    keep_names: Sequence[str] = (),
) -> tuple[tuple[str, str, str], ...]:
    if target is None:
        return ()
    path_rows = tuple(row for row in rows if "path" in row.rewrite_surfaces)
    translations: list[tuple[str, str, str]] = []
    for entry in select_symlink_entries(snapshot):
        link = readlink_nofollow(target / entry.rel)
        if os.path.isabs(link):
            continue
        target_posix = Path(
            os.path.normpath(os.path.join(entry.rel.parent.as_posix(), link))
        ).as_posix()
        if target_posix == ".." or target_posix.startswith("../"):
            continue
        if os.path.lexists(target / target_posix):
            continue
        occupant = _path_occupant_nofollow(target, target_posix)
        if occupant is not None:
            occupied_prefix, is_symlink = occupant
            if (
                occupied_prefix == target_posix
                or not is_symlink
                or _virtual_path_translation(occupied_prefix, path_rows, keep_names)
                != occupied_prefix
            ):
                continue
        translated = _virtual_path_translation(target_posix, path_rows, keep_names)
        if translated != target_posix:
            translations.append((entry.rel.as_posix(), target_posix, translated))
    return tuple(translations)


def _compile_symlink_inputs(
    target: Path | None,
    snapshot: SurfaceSnapshot,
) -> tuple[tuple[str, str], ...]:
    if target is None:
        return ()
    return tuple(
        (entry.rel.as_posix(), readlink_nofollow(target / entry.rel))
        for entry in select_symlink_entries(snapshot)
    )


def _target_relative_visibility_path(
    target: Path,
    visibility: VisibilityInput,
) -> str | None:
    try:
        return visibility.path.absolute().relative_to(target.absolute()).as_posix()
    except ValueError:
        return None


def _validate_visibility_projection(
    target: Path | None,
    rows: tuple[RenderedSubstitution, ...],
    plan: RenamePlan,
    snapshot: SurfaceSnapshot,
    rules: Rules,
) -> None:
    if target is None:
        return
    rewrite_entries = select_rename_entries(
        snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    rewrite_paths = {
        entry.rel.as_posix()
        for entry in rewrite_entries
        if entry.worktree_kind == "file"
    }
    virtual = {
        (link_source, source_target): destination_target
        for link_source, source_target, destination_target in (
            plan.virtual_translations
        )
    }
    for visibility in plan.visibility_inputs:
        rel = _target_relative_visibility_path(target, visibility)
        if rel is None:
            continue
        translated = plan.translate(rel)
        if translated != rel:
            raise SafetyError(
                f"Git visibility input {rel!r} would move to {translated!r}; "
                f"the shared surface plan would become stale"
            )
        if visibility.kind == "file" and rel in rewrite_paths:
            try:
                text = read_regular_nofollow(target / rel).decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                projected, _ = rewrite_file(
                    (
                        row
                        for row in rows
                        if "content" in row.rewrite_surfaces
                        and row_matches_scope(row, rel)
                    ),
                    text,
                    rules.keep_names,
                )
                if projected != text:
                    raise SafetyError(
                        f"content rewrite would change Git visibility input "
                        f"{rel!r}; change and commit ignore policy separately"
                    )
        if visibility.kind != "symlink":
            continue
        link = visibility.link_text
        if link is None or os.path.isabs(link):
            continue
        source_target = Path(
            os.path.normpath(os.path.join(Path(rel).parent.as_posix(), link))
        ).as_posix()
        projected_target = plan.translate(source_target)
        if projected_target == source_target:
            projected_target = virtual.get((rel, source_target), source_target)
        if projected_target != source_target:
            raise SafetyError(
                f"symlink retarget would change Git visibility input {rel!r}; "
                f"change and commit ignore policy separately"
            )


def revalidate_visibility_inputs(target: Path, plan: RenamePlan) -> None:
    """Recapture Git visibility fingerprints before any authorized mutation."""

    current = capture_surface_snapshot(target).visibility_inputs
    if current != plan.visibility_inputs:
        raise SafetyError(
            "Git visibility inputs changed after planning; nothing was written"
        )


def validate_reset_visibility(
    target: Path,
    plan: RenamePlan,
    resets: tuple[tuple[str, str], ...],
) -> None:
    """Refuse a position-zero reset that would mutate an ignore input."""

    visibility_by_rel = {
        rel: item
        for item in plan.visibility_inputs
        if (rel := _target_relative_visibility_path(target, item)) is not None
    }
    for rel, stub in resets:
        visibility = visibility_by_rel.get(rel)
        if visibility is None:
            continue
        if visibility.kind != "file" or read_regular_nofollow(
            target / rel
        ) != stub.encode("utf-8"):
            raise SafetyError(
                f"reset would change Git visibility input {rel!r}; change and "
                f"commit ignore policy separately"
            )


def revalidate_substitution_table(target: Path, table: SubstitutionTable) -> None:
    """Revalidate all frozen-plan filesystem facts before mutation."""

    revalidate_visibility_inputs(target, table.rename_plan)
    revalidate_rename_plan(target, table.rename_plan)
    for rel, expected_link in table.rename_plan.symlink_inputs:
        try:
            current_link = readlink_nofollow(target / rel)
        except OSError as exc:
            raise SafetyError(f"symlink changed after planning: {rel!r}") from exc
        if current_link != expected_link:
            raise SafetyError(
                f"symlink changed after planning: {rel!r} "
                f"(expected {expected_link!r}, found {current_link!r})"
            )


def _policy(
    consumer: HuntConsumer,
    matcher: MatcherSpec,
    surfaces: frozenset[Surface],
    coordinates: ScopeCoordinates,
) -> HuntPolicy:
    return HuntPolicy(consumer, matcher, surfaces, coordinates)


def _identity_hunts(
    field: str,
    matcher: MatcherSpec,
    *,
    renames_paths: bool,
    enabled_display_form: bool = False,
    disabled_display_form: bool = False,
) -> tuple[HuntPolicy, ...]:
    paranoid = MatcherSpec("paranoid", field, matcher.substring)
    hunts: list[HuntPolicy] = []
    if not disabled_display_form:
        doctor_surfaces: set[Surface] = {"content", "symlink"}
        # A scoped npm_name is never rewritten in paths, but the doctor still
        # hunts it across the whole relative path.
        if renames_paths or enabled_display_form or field == "npm_name":
            doctor_surfaces.add("path")
        hunts.append(
            _policy(
                "doctor",
                matcher,
                frozenset(doctor_surfaces),
                "current_or_source",
            )
        )
    hunts.extend(
        (
            _policy("reset_stub", paranoid, frozenset({"content"}), "source"),
            _policy("reset_path", paranoid, frozenset({"path"}), "source"),
            _policy(
                "regeneration",
                paranoid,
                frozenset({"content", "path"}),
                "source",
            ),
        )
    )
    return tuple(hunts)


def _declared_hunts(rule: ReplaceRule) -> tuple[HuntPolicy, ...]:
    literal = MatcherSpec("literal", None, False)
    hunts: list[HuntPolicy] = []
    doctor_surfaces: set[Surface] = set()
    if rule.content:
        doctor_surfaces.add("content")
    if rule.paths:
        doctor_surfaces.update(("path", "symlink"))
    if doctor_surfaces:
        hunts.append(
            _policy(
                "doctor",
                literal,
                frozenset(doctor_surfaces),
                "current_or_source",
            )
        )
    if rule.content:
        hunts.append(_policy("reset_stub", literal, frozenset({"content"}), "source"))
    if rule.paths:
        hunts.append(_policy("reset_path", literal, frozenset({"path"}), "source"))
    regeneration_surfaces = frozenset(
        surface
        for surface, enabled in (("content", rule.content), ("path", rule.paths))
        if enabled
    )
    if regeneration_surfaces:
        hunts.append(
            _policy(
                "regeneration",
                literal,
                regeneration_surfaces,
                "source",
            )
        )
    return tuple(hunts)


def _declared_rows(
    source: Identity, destination: Identity, rules: Rules
) -> list[RenderedSubstitution]:
    rows: list[RenderedSubstitution] = []
    for index, rule in enumerate(rules.replace, start=1):
        from_value = render_replace_pattern(rule.pattern, source)
        to_value = render_replace_pattern(rule.pattern, destination)
        if from_value == to_value:
            continue
        rewrite_surfaces = frozenset(
            surface
            for surface, enabled in (("content", rule.content), ("path", rule.paths))
            if enabled
        )
        rows.append(
            RenderedSubstitution(
                row_id=f"replace:{index}",
                provenance=(
                    Provenance(
                        kind="replace_rule",
                        name=f"replace[{index}]",
                        declaration_index=index,
                        pattern=rule.pattern,
                        reason=rule.reason,
                    ),
                ),
                matcher=MatcherSpec("literal", None, False),
                from_value=from_value,
                to_value=to_value,
                rewrite_surfaces=rewrite_surfaces,
                hunts=_declared_hunts(rule),
                scope=Scope(tuple(rule.files)),
            )
        )
    return rows


SplitSpelling = Literal["package", "identifier", "both"]
# The path-only row of a [[cargo_split]] role carries this row_id suffix.
SPLIT_PATH_ROW_SUFFIX = ":path"
# The ``.rs`` content row of a [[cargo_split]] role carries this suffix.
SPLIT_RUST_ROW_SUFFIX = ":rust"


def split_spelling(split: CargoSplit, posix: str) -> SplitSpelling | None:
    """Which spelling a ``[[cargo_split]]`` press writes into one file.

    Cargo manifests and ``.rs`` files are classified by structure, which takes
    precedence over the declared glob lists.
    """
    if posixpath.basename(posix) == "Cargo.toml":
        return "package"
    if posix.endswith(".rs"):
        return "identifier"
    package = any(fnmatch.fnmatchcase(posix, glob) for glob in split.package_files)
    ident = any(fnmatch.fnmatchcase(posix, glob) for glob in split.identifier_files)
    if package and ident:
        return "both"
    if package:
        return "package"
    return "identifier" if ident else None


def active_cargo_splits(
    source: Identity, destination: Identity, rules: Rules
) -> tuple[CargoSplit, ...]:
    """The declared splits whose role this press really splits."""
    roles = cargo_split_roles(
        source, destination, (split.role for split in rules.cargo_split)
    )
    return tuple(split for split in rules.cargo_split if split.role in roles)


def _content_surface_paths(target: Path, rules: Rules) -> tuple[str, ...]:
    snapshot = capture_surface_snapshot(target)
    return tuple(
        entry.rel.as_posix()
        for entry in select_content_rewrite_entries(
            snapshot,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
        )
    )


def _split_rows(
    row: RenderedSubstitution,
    split: CargoSplit,
    destination_name: str,
    paths: Sequence[str],
) -> list[RenderedSubstitution]:
    """Replace one unscoped exact row with the rows a split press runs.

    Content rows take exact file scopes, so the shared validator can prove
    they never meet. The package spelling alone renames paths.
    """
    scoped = {
        spelling: tuple(
            path for path in paths if split_spelling(split, path) == spelling
        )
        for spelling in ("package", "identifier")
    }
    rust = tuple(path for path in scoped["identifier"] if path.endswith(".rs"))
    declared = tuple(path for path in scoped["identifier"] if path not in rust)
    field = f"{CARGO_IDENT_PREFIX}{split.role}"
    ident_matcher = MatcherSpec("conservative", field, row.matcher.substring)
    rows: list[RenderedSubstitution] = []
    if scoped["package"]:
        rows.append(
            replace(
                row,
                rewrite_surfaces=frozenset({"content"}),
                scope=Scope(scoped["package"]),
            )
        )
    for files, suffix, package_value in (
        (rust, SPLIT_RUST_ROW_SUFFIX, destination_name),
        (declared, "", None),
    ):
        if not files:
            continue
        rows.append(
            RenderedSubstitution(
                row_id=f"identity:{field}{suffix}",
                provenance=(Provenance(kind="identity", name=field),),
                matcher=ident_matcher,
                from_value=row.from_value,
                to_value=cargo_ident(destination_name),
                rewrite_surfaces=frozenset({"content"}),
                hunts=_identity_hunts(field, ident_matcher, renames_paths=False),
                scope=Scope(files),
                package_value=package_value,
            )
        )
    if "path" in row.rewrite_surfaces:
        rows.append(
            replace(
                row,
                row_id=f"{row.row_id}{SPLIT_PATH_ROW_SUFFIX}",
                rewrite_surfaces=frozenset({"path"}),
            )
        )
    return rows


def _identity_rows(
    source: Identity,
    destination: Identity,
    rules: Rules,
    target: Path | None = None,
) -> list[RenderedSubstitution]:
    source_values = source.as_dict()
    destination_values = destination.as_dict()
    values: list[tuple[str, str, str, bool, bool]] = []
    for field, from_value in source_values.items():
        if field == "display_name" or field not in destination_values:
            continue
        to_value = destination_values[field]
        if from_value != to_value:
            values.append((field, from_value, to_value, False, False))

    if source.display_name is not None and destination.display_name is not None:
        source_forms = display_forms(source.display_name)
        destination_forms = display_forms(destination.display_name)
        enabled_forms = frozenset(rules.display_forms)
        for form in DISPLAY_FORM_NAMES:
            from_value = source_forms[form]
            to_value = destination_forms[form]
            if from_value == to_value:
                continue
            enabled = form in enabled_forms
            values.append(
                (
                    f"display_name_{form}",
                    from_value,
                    to_value,
                    enabled,
                    not enabled,
                )
            )

    values.extend(
        (tag, from_value, to_value, False, False)
        for tag, from_value, to_value in (
            *cargo_name_pairs(source, destination),
            *cargo_bin_env_pairs(source, destination),
        )
    )
    values.sort(key=lambda item: (-len(item[1]), exact_name_rank(item[0])))
    rows: list[RenderedSubstitution] = []
    for field, from_value, to_value, enabled_display, disabled_display in values:
        display = field.startswith("display_name_")
        substring = field in rules.substring_rewrite_fields
        matcher = MatcherSpec("conservative", field, substring)
        rewrite_surfaces: set[Surface] = set()
        if not disabled_display:
            rewrite_surfaces.add("content")
            if pair_renames_paths(field, from_value, to_value):
                rewrite_surfaces.add("path")
        kind: ProvenanceKind = "display_form" if display else "identity"
        rows.append(
            RenderedSubstitution(
                row_id=f"identity:{field}",
                provenance=(Provenance(kind=kind, name=field),),
                matcher=matcher,
                from_value=from_value,
                to_value=to_value,
                rewrite_surfaces=frozenset(rewrite_surfaces),
                hunts=_identity_hunts(
                    field,
                    matcher,
                    renames_paths=field_renames_paths(field, from_value),
                    enabled_display_form=enabled_display,
                    disabled_display_form=disabled_display,
                ),
                scope=Scope(),
            )
        )
    splits = active_cargo_splits(source, destination, rules)
    if not splits:
        return rows
    paths = _content_surface_paths(target, rules) if target is not None else ()
    wanted = dict(destination.cargo_names)
    by_field = {f"{CARGO_EXACT_PREFIX}{split.role}": split for split in splits}
    split_rows: list[RenderedSubstitution] = []
    for row in rows:
        split = by_field.get(row.provenance[0].name)
        if split is None:
            split_rows.append(row)
        else:
            split_rows.extend(_split_rows(row, split, wanted[split.role], paths))
    return split_rows


def _manifest_text(target: Path | None, rules: Rules) -> tuple[str, str] | None:
    """The root manifest's text and literal ``[project].name``, if readable.

    A declaration that excludes python leaves ``pyproject.toml`` unread.
    """

    if target is None or (
        rules.languages is not None and "python" not in rules.languages
    ):
        return None
    try:
        text = read_regular_nofollow(target / "pyproject.toml").decode("utf-8")
        name = tomllib.loads(text).get("project", {}).get("name")
    except (OSError, SafetyError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return (text, name) if isinstance(name, str) else None


def _hyphen_rows(
    source: Identity,
    destination: Identity,
    target: Path | None,
    rules: Rules,
) -> list[RenderedSubstitution]:
    """Rewrite a manifest-proven hyphen name; otherwise only hunt for it."""

    hyphen = distinct_hyphen_form(source, destination)
    if hyphen is None:
        return []
    field = "package_name_hyphen"
    manifest = _manifest_text(target, rules)
    proven = manifest is not None and manifest[1] == hyphen
    matcher = MatcherSpec("conservative", field, False)
    return [
        RenderedSubstitution(
            row_id=f"identity:{field}",
            provenance=(Provenance(kind="identity", name=field),),
            matcher=matcher,
            from_value=hyphen,
            to_value=destination.package_name.replace("_", "-"),
            rewrite_surfaces=(
                frozenset({"content", "path"}) if proven else frozenset()
            ),
            hunts=(
                _policy(
                    "doctor",
                    matcher,
                    frozenset({"content", "path", "symlink"}),
                    "current_or_source",
                ),
            ),
            scope=Scope(),
        )
    ]


def _manifest_name_rows(
    source: Identity, destination: Identity, target: Path | None, rules: Rules
) -> list[RenderedSubstitution]:
    """Keep ``[project].name`` on package_name when another field owns it."""

    hyphen = source.package_name.replace("_", "-")
    to_value = destination.package_name.replace("_", "-")
    if (
        hyphen == source.package_name
        or hyphen == to_value
        or distinct_hyphen_form(source, destination) is not None
    ):
        return []
    manifest = _manifest_text(target, rules)
    if manifest is None or manifest[1] != hyphen:
        return []
    source_values = source.as_dict()
    destination_values = destination.as_dict()
    owners = [
        name
        for name, value in source_values.items()
        if name != "package_name" and value == hyphen
    ]
    if owners and all(destination_values.get(name) == to_value for name in owners):
        return []
    text = manifest[0]
    assignment = re.compile(
        rf"(?m)^[ \t]*name[ \t]*=[ \t]*([\"']){re.escape(hyphen)}\1"
    )
    for line in assignment.finditer(text):
        from_value = line.group(0).lstrip()
        rewritten = from_value.replace(hyphen, to_value)
        if _rewrite_project_name(text, from_value, rewritten) == text:
            continue
        return [
            RenderedSubstitution(
                row_id="manifest:name",
                provenance=(Provenance(kind="manifest_name", name="package_name"),),
                matcher=MatcherSpec("literal", None, False),
                from_value=from_value,
                to_value=rewritten,
                rewrite_surfaces=frozenset({"content"}),
                hunts=(),
                scope=Scope(("pyproject.toml",)),
            )
        ]
    return []


def _merge_row_metadata(
    owner: RenderedSubstitution,
    additions: tuple[RenderedSubstitution, ...],
) -> RenderedSubstitution:
    """Retain the owner's rewrite semantics while joining audit metadata."""

    provenance = tuple(
        dict.fromkeys(item for row in (owner, *additions) for item in row.provenance)
    )
    hunts = tuple(
        dict.fromkeys(item for row in (owner, *additions) for item in row.hunts)
    )
    return replace(owner, provenance=provenance, hunts=hunts)


def _collapse_display_rows(
    rows: list[RenderedSubstitution], rules: Rules
) -> list[RenderedSubstitution]:
    """Choose one owner when derived forms share the same source literal."""

    groups: dict[str, list[RenderedSubstitution]] = {}
    for row in rows:
        if row.provenance[0].kind == "display_form":
            groups.setdefault(row.from_value, []).append(row)

    enabled_order = {
        f"display_name_{form}": index for index, form in enumerate(rules.display_forms)
    }
    canonical_order = {
        f"display_name_{form}": index for index, form in enumerate(DISPLAY_FORM_NAMES)
    }
    collapsed_by_source: dict[str, RenderedSubstitution] = {}
    for from_value, group in groups.items():
        if len(group) == 1:
            collapsed_by_source[from_value] = group[0]
            continue
        enabled = [row for row in group if row.provenance[0].name in enabled_order]
        if enabled:
            owner = min(
                enabled,
                key=lambda row: enabled_order[row.provenance[0].name],
            )
        else:
            owner = min(
                group,
                key=lambda row: canonical_order[row.provenance[0].name],
            )
        additions = tuple(row for row in group if row is not owner)
        collapsed_by_source[from_value] = _merge_row_metadata(owner, additions)

    result: list[RenderedSubstitution] = []
    emitted: set[str] = set()
    for row in rows:
        if row.provenance[0].kind != "display_form":
            result.append(row)
            continue
        if row.from_value in emitted:
            continue
        result.append(collapsed_by_source[row.from_value])
        emitted.add(row.from_value)
    return result


def _normalize_rows(
    declared: list[RenderedSubstitution],
    identity: list[RenderedSubstitution],
    rules: Rules,
) -> tuple[RenderedSubstitution, ...]:
    """Normalize rendered rows without expanding a later rewrite mechanism."""

    collapsed_identity = _collapse_display_rows(identity, rules)
    identity_owners: list[RenderedSubstitution] = []
    for row in collapsed_identity:
        duplicate_index = next(
            (
                index
                for index, prior in enumerate(identity_owners)
                if (prior.from_value, prior.to_value) == (row.from_value, row.to_value)
            ),
            None,
        )
        # A cli_name or npm_name equal to a content-only field (owner, author)
        # keeps its own row, or merging would drop its path rename. A substring
        # field keeps its own row beside a stricter Cargo owner, or merging
        # would drop its glued matches at table level. A real press rewrites
        # such a match only for a single-part value; the keep-names preflight
        # refuses a glued token around a multi-part value.
        if (
            duplicate_index is None
            or (
                row.provenance[0].name in ("npm_name", "cli_name")
                and "path" in row.rewrite_surfaces
                and "path" not in identity_owners[duplicate_index].rewrite_surfaces
            )
            or (
                row.matcher.substring
                and is_cargo_field(identity_owners[duplicate_index].provenance[0].name)
            )
            # A [[cargo_split]] path row keeps the path surface its scoped
            # content row lacks, and each scoped split row keeps its own files.
            or row.row_id.endswith(SPLIT_PATH_ROW_SUFFIX)
            or (
                bool(row.scope.files)
                and row.scope != identity_owners[duplicate_index].scope
            )
        ):
            identity_owners.append(row)
            continue
        identity_owners[duplicate_index] = _merge_row_metadata(
            identity_owners[duplicate_index], (row,)
        )

    normalized: list[RenderedSubstitution] = []
    for row in (*declared, *identity_owners):
        duplicate_index = next(
            (
                index
                for index, prior in enumerate(normalized)
                if (
                    prior.matcher,
                    prior.from_value,
                    prior.to_value,
                    prior.rewrite_surfaces,
                    prior.hunts,
                    prior.scope,
                )
                == (
                    row.matcher,
                    row.from_value,
                    row.to_value,
                    row.rewrite_surfaces,
                    row.hunts,
                    row.scope,
                )
            ),
            None,
        )
        if duplicate_index is None:
            normalized.append(row)
            continue
        normalized[duplicate_index] = _merge_row_metadata(
            normalized[duplicate_index], (row,)
        )
    return tuple(normalized)


def _validate_rows(
    rows: tuple[RenderedSubstitution, ...],
    destination: Identity,
    rules: Rules,
    snapshot: SurfaceSnapshot,
    pipeline_validator: Callable[..., tuple[PipelineCandidate, ...]],
    dangling_target_paths: tuple[str, ...] = (),
) -> None:
    candidates: list[PipelineCandidate] = []
    for row in rows:
        if not row.rewrite_surfaces:
            continue
        validator_surfaces = set(row.rewrite_surfaces)
        provenance = row.provenance[0]
        if provenance.kind == "replace_rule" and "path" in row.rewrite_surfaces:
            validator_surfaces.add("symlink")
        # A scoped identity row is a [[cargo_split]] content row; its path
        # row alone models symlink text.
        if (
            provenance.kind == "identity"
            and not provenance.name.startswith("display_name_")
            and not row.scope.files
        ):
            validator_surfaces.add("symlink")
        candidates.append(
            PipelineCandidate(
                row_id=row.row_id,
                from_value=row.from_value,
                to_value=row.to_value,
                rewrite_surfaces=frozenset(validator_surfaces),
                matcher=row.matcher,
                files=row.scope.files,
                provenance=tuple(
                    (
                        f"{item.name} pattern={item.pattern!r} reason={item.reason!r}"
                        if item.kind == "replace_rule"
                        else item.name
                    )
                    for item in row.provenance
                ),
                ambiguity_family=(
                    "display_name" if provenance.kind == "display_form" else None
                ),
            )
        )

    destination_sinks = destination.as_dict()
    if destination.display_name is not None:
        destination_sinks.pop("display_name")
        rendered_forms = display_forms(destination.display_name)
        destination_sinks.update(
            {
                f"display_name_{form}": rendered_forms[form]
                for form in rules.display_forms
            }
        )
    destination_sinks.update(cargo_field_values(destination))
    keep_arguments = {"keep_names": rules.keep_names} if rules.keep_names else {}
    pipeline_validator(
        tuple(candidates),
        **keep_arguments,
        initial_paths=tuple(
            dict.fromkeys(
                (
                    *(entry.rel.as_posix() for entry in snapshot.entries),
                    *dangling_target_paths,
                )
            )
        ),
        initial_symlink_paths=frozenset(
            entry.rel.as_posix()
            for entry in snapshot.entries
            if entry.worktree_kind == "symlink"
        ),
        stability_sinks=tuple(
            StabilitySink(
                sink_id=f"destination:{field}",
                value=value,
                provenance=(f"destination identity field:{field}",),
            )
            for field, value in destination_sinks.items()
        ),
    )


def _stale_emission(row: RenderedSubstitution, output: str) -> ValidationError:
    return ValidationError(
        f"stale-source emission: {row.row_id} source {row.from_value!r} is still "
        f"found in destination value {output!r}; press in two steps via an "
        "intermediate identity"
    )


def _refuse_cargo_owner_stale_output(
    rows: tuple[RenderedSubstitution, ...], destination: Identity
) -> None:
    """Refuse output that a field merged into a Cargo row would report as a leak.

    A merged field keeps its looser doctor hunt, so ``acme_core_next`` would be
    written by the Cargo row and then fail on ``package_name`` ``acme_core``.

    The regeneration and reset hunts are paranoid, so ``-`` and ``_`` count as
    boundaries. A destination Cargo name that extends a source name
    (``acme-widget-next``) would land in a regenerated ``Cargo.lock`` and fail
    that scan after the writes, so every hunt is checked against the
    destination Cargo names. Other fields' outputs stay doctor-only: they do
    not reach a lockfile, and a kept word in an email domain is legitimate.
    """

    cargo_outputs = set(cargo_field_values(destination).values())
    outputs = {
        row.to_value
        for row in rows
        if row.rewrite_surfaces
        and not row.provenance[0].name.startswith(CARGO_BIN_ENV_TAG)
    } | cargo_outputs
    for row in rows:
        if not is_cargo_field(row.provenance[0].name):
            continue
        for policy in row.hunts:
            candidates = outputs if policy.consumer == "doctor" else cargo_outputs
            for output in sorted(candidates):
                if hunt_occurs(row, policy, output):
                    raise _stale_emission(row, output)


def _refuse_regenerated_cargo_leak(
    rows: tuple[RenderedSubstitution, ...], destination: Identity, rules: Rules
) -> None:
    """Refuse a destination Cargo name that holds another field's source value.

    A Cargo name lands in a regenerated ``Cargo.lock``, so ``acmerepo`` would
    fail the paranoid ``repo_name`` ``acme-repo`` hunt after the writes. Runs
    after pipeline validation, whose stability refusals are more specific.
    """

    cargo_outputs = sorted(set(cargo_field_values(destination).values()))
    if not cargo_outputs:
        return
    regenerated = tuple(rule.file for rule in rules.regenerate) or ("Cargo.lock",)
    for row in rows:
        if is_cargo_field(row.provenance[0].name) or not any(
            row_matches_scope(row, path) for path in regenerated
        ):
            continue
        for policy in row.hunts:
            if policy.consumer != "regeneration":
                continue
            for output in cargo_outputs:
                if hunt_occurs(
                    row, policy, output, kept_spans(output, rules.keep_names)
                ):
                    raise _stale_emission(row, output)


def _compiled_rows(
    source: Identity, destination: Identity, target: Path | None, rules: Rules
) -> tuple[RenderedSubstitution, ...]:
    """The normalized rewrite rows, shared by the table and the keep preflight."""

    return _normalize_rows(
        [
            *_manifest_name_rows(source, destination, target, rules),
            *_declared_rows(source, destination, rules),
        ],
        sorted(
            [
                *_identity_rows(source, destination, rules, target),
                *_hyphen_rows(source, destination, target, rules),
            ],
            key=lambda row: -len(row.from_value),
        ),
        rules,
    )


def identity_row_rewriter(
    source: Identity, destination: Identity, target: Path | None, rules: Rules
) -> Callable[[str], str]:
    """Apply the identity rows a press would really run on content, in order."""

    rows = _normalize_rows(
        [],
        sorted(
            [
                *_identity_rows(source, destination, rules, target),
                *_hyphen_rows(source, destination, target, rules),
            ],
            key=lambda row: -len(row.from_value),
        ),
        rules,
    )
    active = tuple(row for row in rows if "content" in row.rewrite_surfaces)

    def rewrite(text: str) -> str:
        for row in active:
            text = rewrite_with_row(row, text)
        return text

    return rewrite


def _declared_path_follows(
    before: DeclaredPath,
    after: DeclaredPath,
    manifest: str,
    plan: RenamePlan,
    directories: frozenset[str],
) -> bool:
    """Whether the rewritten string still names what the old string named."""
    old = posixpath.normpath(posixpath.join(posixpath.dirname(manifest), before.value))
    new = posixpath.normpath(
        posixpath.join(posixpath.dirname(plan.translate(manifest)), after.value)
    )
    if not before.is_glob:
        return plan.translate(old) == new
    if old == os.pardir or old.startswith(f"{os.pardir}/") or old.startswith("/"):
        return before.value == after.value  # the press renames nothing out there
    matched = {
        plan.translate(path)
        for path in directories
        if PurePosixPath(path).full_match(old)
    }
    moved = {plan.translate(path) for path in directories}
    return matched == {path for path in moved if PurePosixPath(path).full_match(new)}


def _package_name(data: Table) -> str | None:
    package = package_table(data)
    name = package.get("name")
    return name.strip() or None if isinstance(name, str) else None


def _join_posix(directory: str, rel: str) -> str:
    return posixpath.normpath(posixpath.join(directory, rel))


def _post_press_file_exists(
    target: Path,
    posix_path: str,
    post_files: Mapping[str, frozenset[str]],
    snapshot_paths: frozenset[str],
    removed_files: frozenset[str],
    removed_dirs: tuple[str, ...],
) -> bool:
    """Whether a regular file will sit at ``posix_path`` after the press."""
    if posix_path in post_files:
        return True
    if posix_path in snapshot_paths:
        # Was in the Git inventory and either moved elsewhere or removed.
        return False
    if posix_path in removed_files or posix_path.startswith(removed_dirs):
        return False
    # Fallback for Git-ignored regular files on disk (Cargo ignores .gitignore).
    # Validate containment strictly because target names come from untrusted TOML.
    try:
        safe = SafeRelPath(posix_path)
        candidate = target / safe.as_posix()
        assert_ancestors_real(candidate, target)
    except SafetyError:
        return False
    return is_regular_lstat(candidate)


def _post_press_target_files(
    target: Path,
    snapshot: SurfaceSnapshot,
    plan: RenamePlan,
    post_files: Mapping[str, frozenset[str]],
    snapshot_paths: frozenset[str],
    removed_files: frozenset[str],
    removed_dirs: tuple[str, ...],
) -> dict[str, frozenset[str]]:
    """Post-press regular files plus tracked symlinks resolving to regular files.

    Cargo counts a symlink as a target candidate when it resolves to a regular
    file and ignores dangling symlinks.
    """
    post_symlinks: dict[str, tuple[str, str]] = {}
    for entry in snapshot.entries:
        if entry.worktree_kind != "symlink":
            continue
        rel = entry.rel.as_posix()
        if rel in removed_files or rel.startswith(removed_dirs):
            continue
        try:
            raw_target = os.readlink(target / rel)
        except OSError:
            continue
        post_symlinks[plan.translate(rel)] = (rel, raw_target)
    if not post_symlinks:
        return dict(post_files)

    def resolves_to_regular_file(start_dest: str) -> bool:
        current = start_dest
        seen: set[str] = set()
        for _ in range(16):
            if current in seen:
                return False
            seen.add(current)
            link_info = post_symlinks.get(current)
            if link_info is None:
                return _post_press_file_exists(
                    target,
                    current,
                    post_files,
                    snapshot_paths,
                    removed_files,
                    removed_dirs,
                )
            old_rel, raw_target = link_info
            if os.path.isabs(raw_target):
                return (target / old_rel).is_file()
            resolved_old = symlink_target_posix(Path(old_rel), raw_target)
            if resolved_old == ".." or resolved_old.startswith("../"):
                return (target / old_rel).is_file()
            current = plan.translate(resolved_old)
        return False

    combined: dict[str, set[str]] = {
        dest: set(srcs) for dest, srcs in post_files.items()
    }
    for dest_link, (old_rel, _raw) in post_symlinks.items():
        if resolves_to_regular_file(dest_link):
            combined.setdefault(dest_link, set()).add(old_rel)
    return {dest: frozenset(srcs) for dest, srcs in combined.items()}


def _inferred_target_collisions(
    target: Path,
    manifest: str,
    before: Table,
    after: Table,
    plan: RenamePlan,
    post_files: Mapping[str, frozenset[str]],
    snapshot_paths: frozenset[str],
    removed_files: frozenset[str],
    removed_dirs: tuple[str, ...],
    *,
    workspace_package: Table | None = None,
) -> list[str]:
    """Target names that would have multiple candidate files after the press."""
    old_dir = posixpath.dirname(manifest)
    new_dir = posixpath.dirname(plan.translate(manifest))
    old_pkg = _package_name(before)
    new_pkg = _package_name(after)
    problems: list[str] = []

    # --- Pass 1: Explicit pathless [[bin]], [[test]], [[example]], [[bench]] ---
    # Cargo resolves these even when auto* = false.
    old_targets = inferred_target_candidates(before)
    new_targets = inferred_target_candidates(after)

    for (_sec, old_name, _old_cands), (section, new_name, new_cands) in zip(
        old_targets, new_targets, strict=True
    ):
        present: list[str] = []
        touched = old_name != new_name
        for crate_rel in new_cands:
            dest_posix = _join_posix(new_dir, crate_rel)
            if not _post_press_file_exists(
                target,
                dest_posix,
                post_files,
                snapshot_paths,
                removed_files,
                removed_dirs,
            ):
                continue
            present.append(dest_posix)
            expected_old = _join_posix(old_dir, crate_rel)
            sources = post_files.get(dest_posix)
            if sources is not None and any(src != expected_old for src in sources):
                touched = True
            if section == "bin" and crate_rel == "src/main.rs" and old_pkg != new_pkg:
                touched = True
        if len(present) > 1 and touched:
            joined = ", ".join(repr(p) for p in present)
            problems.append(
                f"{manifest}: [[{section}]] {new_name!r} would have multiple "
                f"candidate target files after the press ({joined}), so Cargo "
                f"could not infer its path. Declare an explicit path on "
                f"[[{section}]], remove the extra file, or choose another name"
            )

    # --- Pass 2: Auto-discovered targets when auto* is enabled ---
    # Catches tests/, examples/, benches/, and table-less src/bin/ collisions
    # where Cargo rejects duplicate auto-discovered target names.
    # Cargo suppresses auto-discovered targets whose name is declared by any
    # explicit target table (pathed or pathless) and ignores leading-dot names.
    before_explicit = declared_target_names(before)
    explicit_targets = declared_target_names(after)
    unsuppressed_targets = before_explicit - explicit_targets
    for section, base, auto_flag, claimed, pkg_name in auto_target_sections(
        after, workspace_package=workspace_package
    ):
        prefix = f"{new_dir}/{base}/" if new_dir else f"{base}/"
        by_stem: dict[str, dict[str, bool]] = {}

        for dest_posix, sources in post_files.items():
            if not dest_posix.startswith(prefix):
                continue
            rest = dest_posix[len(prefix) :]
            parts = rest.split("/")
            if len(parts) == 1 and rest.endswith(".rs"):
                stem = rest[:-3]
            elif len(parts) == 2 and parts[1] == "main.rs":
                stem = parts[0]
            else:
                continue
            if not stem or stem.startswith("."):
                continue
            crate_rel = f"{base}/{rest}"
            if crate_rel in claimed:
                continue
            moved = any(src != _join_posix(old_dir, crate_rel) for src in sources)
            by_stem.setdefault(stem, {})[crate_rel] = moved

        if section == "bin" and pkg_name is not None and "src/main.rs" not in claimed:
            main_dest = _join_posix(new_dir, "src/main.rs")
            if _post_press_file_exists(
                target,
                main_dest,
                post_files,
                snapshot_paths,
                removed_files,
                removed_dirs,
            ):
                main_moved = (old_pkg != new_pkg) or any(
                    src != _join_posix(old_dir, "src/main.rs")
                    for src in post_files.get(main_dest, ())
                )
                by_stem.setdefault(pkg_name, {})["src/main.rs"] = main_moved

        # An explicit target renamed away stops suppressing auto-discovered
        # files with its old name, even if those files themselves do not move.
        for unsup_sec, unsup_stem in sorted(unsuppressed_targets):
            if unsup_sec == section and unsup_stem and not unsup_stem.startswith("."):
                by_stem.setdefault(unsup_stem, {})

        for stem, entries in sorted(by_stem.items()):
            if (section, stem) in explicit_targets:
                continue  # pathless checked in Pass 1; pathed overrides auto name
            unsuppressed = (section, stem) in unsuppressed_targets
            if not any(entries.values()) and not unsuppressed:
                continue  # untouched pre-existing files; do not blame the press
            # Also probe opposite shape(s) on disk for Git-ignored orphans.
            for shape in ("{}.rs", "{}/main.rs"):
                other_rel = f"{base}/{shape.format(stem)}"
                if other_rel in entries or other_rel in claimed:
                    continue
                if _post_press_file_exists(
                    target,
                    _join_posix(new_dir, other_rel),
                    post_files,
                    snapshot_paths,
                    removed_files,
                    removed_dirs,
                ):
                    entries[other_rel] = False
            if len(entries) > 1:
                present = sorted(_join_posix(new_dir, rel) for rel in entries)
                joined = ", ".join(repr(p) for p in present)
                problems.append(
                    f"{manifest}: auto-discovered {section} target {stem!r} "
                    f"would have multiple candidate files after the press "
                    f"({joined}), which Cargo rejects as duplicate targets. "
                    f"Remove or rename the extra file, declare an explicit path, "
                    f"or set {auto_flag} = false"
                )

    return problems


def _rewritten_texts_with_bin_env(
    target: Path,
    rows: Sequence[RenderedSubstitution],
    snapshot: SurfaceSnapshot,
    rewritten: Collection[str],
    removed: tuple[set[str], tuple[str, ...]],
    rules: Rules,
) -> tuple[tuple[str, str, str], ...]:
    """``(path, text, text after the press)`` of kept files naming a binary.

    Every tracked file counts; one excluded from rewriting keeps its text.
    """
    found: list[tuple[str, str, str]] = []
    for entry in snapshot.entries:
        path = entry.rel.as_posix()
        if (
            not entry.tracked
            or entry.worktree_kind != "file"
            or path in removed[0]
            or path.startswith(removed[1])
        ):
            continue
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "CARGO_BIN_EXE_" not in text:
            continue
        new_text = text
        if path in rewritten:
            scoped = (row for row in rows if row_matches_scope(row, path))
            new_text = rewrite_file(scoped, text, rules.keep_names)[0]
        found.append((path, text, new_text))
    return tuple(found)


def _conventional_root_splits(
    manifest: str,
    before: Table,
    plan: RenamePlan,
    files: frozenset[str],
    removed_files: frozenset[str],
    removed_dirs: tuple[str, ...],
    *,
    pkg_meta: CargoPackageMetadata | None = None,
    workspace_package: Table | None = None,
) -> list[str]:
    """Refuse a rename that moves an implicit conventional Cargo root file.

    Cargo fixes the filenames of implicit ``src/lib.rs``, ``src/main.rs``,
    ``build.rs``, and edition-2015 ``src/bin/main.rs`` relative to the crate
    directory. A crate named ``main``, ``lib``, or ``build`` would move its
    conventional root to ``src/<new>.rs`` or ``<new>.rs``, leaving Cargo
    without that target.
    """
    package = package_table(before)
    if not package:
        return []
    old_dir = posixpath.dirname(manifest)
    new_dir = posixpath.dirname(plan.translate(manifest))
    explicit_paths = {
        posixpath.normpath(d.value.replace("\\", "/"))
        for d in declared_cargo_paths(before)
        if d.kind in {"target", "build"}
    }
    conventional = frozenset(
        {"src/lib.rs", "src/main.rs", "build.rs", "src/bin/main.rs"}
    )
    active: list[str] = []
    if pkg_meta is not None:
        for t in pkg_meta.targets:
            crate_rel = (
                posixpath.relpath(t.src_path, old_dir) if old_dir else t.src_path
            )
            if crate_rel in conventional and crate_rel not in explicit_paths:
                active.append(crate_rel)
    else:
        build = package.get("build")
        if build is not False and not isinstance(build, str):
            active.append("build.rs")
        lib = before.get("lib")
        if not (isinstance(lib, dict) and isinstance(lib.get("path"), str)) and (
            isinstance(lib, dict) or package.get("autolib") is not False
        ):
            active.append("src/lib.rs")
        raw_bins = before.get("bin")
        if "src/main.rs" not in explicit_paths and (
            auto_discovery_enabled(before, "bin", workspace_package)
            or (
                isinstance(raw_bins, list)
                and any(isinstance(b, dict) and "path" not in b for b in raw_bins)
            )
        ):
            active.append("src/main.rs")

    problems: list[str] = []
    for crate_rel in dict.fromkeys(active):
        old_posix = _join_posix(old_dir, crate_rel)
        if (
            old_posix not in files
            or old_posix in removed_files
            or old_posix.startswith(removed_dirs)
        ):
            continue
        expected_posix = _join_posix(new_dir, crate_rel)
        moved_posix = plan.translate(old_posix)
        if moved_posix != expected_posix:
            problems.append(
                f"{manifest}: conventional Cargo root {old_posix!r} would move "
                f"to {moved_posix!r}, leaving {expected_posix!r} missing. "
                "Declare an explicit path in Cargo.toml, add the name to "
                "keep_names, or choose another name"
            )
    return problems


def _bin_env_splits(
    target: Path,
    manifest: str,
    before: Table,
    after: Table | None,
    plan: RenamePlan,
    new_texts: Sequence[tuple[str, str, str]],
    rewritten: frozenset[str] | set[str],
    *,
    pkg_meta: CargoPackageMetadata | None = None,
    workspace_package: Table | None = None,
) -> list[str]:
    """``env!`` tokens the rewrite moves away from any Cargo binary target.

    Covers auto-discovered ``src/bin/`` binaries (whose name follows the file
    stem), conventional ``src/main.rs`` (whose name follows ``[package].name``),
    and explicit ``[[bin]]`` targets (whose name follows ``[[bin]].name``).
    """
    base = posixpath.dirname(manifest)
    pairs: list[tuple[str, str, bool]] = []  # (old_name, new_name, from_file)
    raw_before_bins = before.get("bin")
    explicit_before = [
        e
        for e in (raw_before_bins if isinstance(raw_before_bins, list) else [])
        if isinstance(e, dict) and isinstance(e.get("name"), str)
    ]
    explicit_names = {str(e["name"]) for e in explicit_before}
    if after is not None:
        raw_after_bins = after.get("bin")
        explicit_after = [
            e
            for e in (raw_after_bins if isinstance(raw_after_bins, list) else [])
            if isinstance(e, dict) and isinstance(e.get("name"), str)
        ]
        if len(explicit_before) == len(explicit_after):
            for old_entry, new_entry in zip(
                explicit_before, explicit_after, strict=True
            ):
                pairs.append((str(old_entry["name"]), str(new_entry["name"]), False))

    old_pkg = _package_name(before)
    new_pkg = _package_name(after) if after is not None else old_pkg
    if pkg_meta is not None:
        for t in pkg_meta.targets:
            if "bin" not in t.kinds or t.name in explicit_names:
                continue
            crate_rel = posixpath.relpath(t.src_path, base) if base else t.src_path
            if crate_rel == "src/main.rs":
                if old_pkg is not None and new_pkg is not None:
                    pairs.append((t.name, new_pkg, False))
            else:
                moved = PurePosixPath(plan.translate(t.src_path))
                new_name = (
                    moved.parent.name if crate_rel.endswith("/main.rs") else moved.stem
                )
                pairs.append((t.name, new_name, True))
    else:
        claimed_bins = {
            posixpath.normpath(str(e["path"]).replace("\\", "/"))
            for e in explicit_before
            if isinstance(e.get("path"), str)
        }
        if (
            old_pkg is not None
            and new_pkg is not None
            and auto_discovery_enabled(before, "bin", workspace_package)
            and "src/main.rs" not in claimed_bins
            and (target / base / "src" / "main.rs").is_file()
        ):
            pairs.append((old_pkg, new_pkg, False))
        for name, rel in auto_discovered_bins(
            target / base, before, workspace_package=workspace_package
        ):
            moved = PurePosixPath(plan.translate(posixpath.join(base, rel)))
            new_name = moved.stem if rel.endswith(".rs") else moved.name
            pairs.append((name, new_name, True))

    problems: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    for name, new_name, from_file in pairs:
        if (name, new_name) in seen_pairs:
            continue
        seen_pairs.add((name, new_name))
        old_token = re.compile(rf"CARGO_BIN_EXE_{re.escape(name)}(?![\w-])")
        new_token = re.compile(rf"CARGO_BIN_EXE_{re.escape(new_name)}(?![\w-])")
        where_desc = (
            f"which its file would name {new_name!r}"
            if from_file
            else f"which Cargo would name {new_name!r}"
        )
        for path, old_text, new_text in new_texts:
            old_count = len(old_token.findall(old_text))
            if old_count == 0:
                continue
            if name == new_name:
                matched = len(old_token.findall(new_text)) == old_count
            else:
                matched = (
                    len(old_token.findall(new_text)) == 0
                    and len(new_token.findall(new_text))
                    - len(new_token.findall(old_text))
                    == old_count
                )
            if matched:
                continue
            problems.append(
                f"{path}: CARGO_BIN_EXE_{name} tokens would not match the "
                f"binary, {where_desc}. "
                + (
                    "Declare a cargo_names table that names this binary, so the "
                    "press rewrites the binary and its tokens together"
                    if path in rewritten
                    else "The file is excluded from rewriting; remove the exclusion "
                    "or edit the token by hand"
                )
            )
    return problems


def cargo_path_splits(
    target: Path, source: Identity, destination: Identity, rules: Rules
) -> list[str]:
    """Declared Cargo paths this press would separate from their files.

    Both halves come from what the press really runs: the whole-manifest content
    rewrite and the rename plan. A table or plan that cannot compile is left for
    the plan step, which reports it.
    """
    snapshot = capture_surface_snapshot(target)
    selection = {
        "exclude_files": rules.exclude_files,
        "exclude_dirs": rules.exclude_dirs,
        "root_control": ROOT_CONTROL,
    }
    try:
        rows = _compiled_rows(source, destination, target, rules)
        plan = _compile_rename_plan(
            rows,
            SurfaceSnapshot(
                entries=select_rename_entries(snapshot, **selection),
                visibility_inputs=snapshot.visibility_inputs,
            ),
            rules.keep_names,
        )
    except ValidationError:
        return []
    rewritten = {
        entry.rel.as_posix()
        for entry in select_content_rewrite_entries(snapshot, **selection)
    }
    removed_files = {str(rule.file) for rule in rules.remove}
    removed_dirs = tuple(f"{rule.dir}/" for rule in rules.remove_dirs)
    directories = frozenset(
        parent.as_posix()
        for entry in snapshot.entries
        for parent in entry.rel.parents
        if parent != Path()
    )
    removed = (removed_files, removed_dirs)
    content_rows = tuple(row for row in rows if "content" in row.rewrite_surfaces)
    new_texts = _rewritten_texts_with_bin_env(
        target, content_rows, snapshot, rewritten, removed, rules
    )
    files = frozenset(
        entry.rel.as_posix()
        for entry in snapshot.entries
        if entry.worktree_kind == "file"
    )
    snapshot_paths = frozenset(entry.rel.as_posix() for entry in snapshot.entries)
    removed_files_set = frozenset(removed_files)
    post_by_dest: dict[str, set[str]] = {}
    for rel in files:
        if rel in removed_files_set or rel.startswith(removed_dirs):
            continue
        post_by_dest.setdefault(plan.translate(rel), set()).add(rel)
    post_files = {dest: frozenset(srcs) for dest, srcs in post_by_dest.items()}
    post_target_files = _post_press_target_files(
        target,
        snapshot,
        plan,
        post_files,
        snapshot_paths,
        removed_files_set,
        removed_dirs,
    )
    manifest_entries: list[tuple[str, Table, str]] = []
    for manifest in cargo_manifest_files(target):
        if manifest in removed_files or manifest.startswith(removed_dirs):
            continue
        text = read_regular_nofollow(target / manifest).decode("utf-8")
        new_text = text
        if manifest in rewritten:
            new_text, _ = rewrite_file(
                (row for row in content_rows if row_matches_scope(row, manifest)),
                text,
                rules.keep_names,
            )
        manifest_entries.append((manifest, tomllib.loads(text), new_text))

    crates = [(manifest, parsed) for manifest, parsed, _ in manifest_entries]
    root_parsed = next(
        (parsed for manifest, parsed in crates if manifest == "Cargo.toml"), {}
    )
    ws_table = root_parsed.get("workspace")
    ws_pkg_raw = ws_table.get("package") if isinstance(ws_table, dict) else None
    workspace_package: Table = ws_pkg_raw if isinstance(ws_pkg_raw, dict) else {}
    pkg_metadata = read_all_cargo_metadata(target, [manifest for manifest, _ in crates])

    problems: list[str] = []
    for manifest, parsed, new_text in manifest_entries:
        pkg_meta = pkg_metadata.get(manifest)
        problems.extend(
            _conventional_root_splits(
                manifest,
                parsed,
                plan,
                files,
                removed_files_set,
                removed_dirs,
                pkg_meta=pkg_meta,
                workspace_package=workspace_package,
            )
        )
        declared = declared_cargo_paths(parsed)
        try:
            new_parsed = tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            problems.extend(
                _bin_env_splits(
                    target,
                    manifest,
                    parsed,
                    None,
                    plan,
                    new_texts,
                    rewritten,
                    pkg_meta=pkg_meta,
                    workspace_package=workspace_package,
                )
            )
            problems.append(f"{manifest}: the rewrite breaks its TOML: {exc}")
            continue
        problems.extend(
            _bin_env_splits(
                target,
                manifest,
                parsed,
                new_parsed,
                plan,
                new_texts,
                rewritten,
                pkg_meta=pkg_meta,
                workspace_package=workspace_package,
            )
        )
        rewritten_paths = declared_cargo_paths(new_parsed)
        inferred = inferred_target_paths(
            parsed,
            new_parsed,
            target / posixpath.dirname(manifest),
            pkg_meta=pkg_meta,
            workspace_package=workspace_package,
        )
        if len(rewritten_paths) != len(declared) or inferred is None:
            problems.append(f"{manifest}: the rewrite changes its declared paths")
            continue
        problems.extend(
            f"{manifest}: {before.key} {before.value!r} would become "
            f"{after.value!r}, but the press would not move what it points at "
            "to match. Rename the path so a press moves it, or add the shared "
            "name to keep_names"
            for before, after in (
                *zip(declared, rewritten_paths, strict=True),
                *inferred,
            )
            if not _declared_path_follows(before, after, manifest, plan, directories)
        )
        problems.extend(
            _inferred_target_collisions(
                target,
                manifest,
                parsed,
                new_parsed,
                plan,
                post_target_files,
                snapshot_paths,
                removed_files_set,
                removed_dirs,
                workspace_package=workspace_package,
            )
        )
    split_tokens = _split_tokens(source, destination, rules)
    # Only files Cargo compiles can break the build; a fixture can't. Checking
    # the compiled set also covers non-.rs Rust files reached via #[path] or
    # include! (such as bridge.inc / frag.inc).
    compiled = _compiled_rust_files(
        target,
        crates,
        files,
        metadata=pkg_metadata,
        workspace_package=workspace_package,
    )
    for path in sorted(rewritten & compiled):
        if path in removed_files or path.startswith(removed_dirs):
            continue
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text, _ = rewrite_file(
            (row for row in content_rows if row_matches_scope(row, path)),
            text,
            rules.keep_names,
        )
        if new_text != text:
            problems.extend(
                _rust_source_path_splits(
                    path, text, new_text, plan, files, directories, split_tokens
                )
            )
    return problems


_MODULE_SHAPES = ("{}.rs", "{}/mod.rs")
# Directories whose ``*.rs`` and ``*/main.rs`` files Cargo makes targets, each
# with the ``[package]`` flag that turns that discovery off.
_TARGET_DIRS = {
    "src/bin": "bin",
    "tests": "test",
    "benches": "bench",
    "examples": "example",
}


def _inline_dirs(path: str, inline: Sequence[InlineModule]) -> tuple[str, ...]:
    """Candidate directories for a non-empty chain of enclosing inline modules.

    The outermost inline module's ``#[path]`` / ``#[cfg_attr(..., path)]``
    anchors at ``dirname(path)`` even in a non-mod-rs file. Its fallback name
    uses both ``base`` (mod-rs) and ``base/<stem>`` (non-mod-rs). Each nested
    inline module extends every parent directory by its own path override(s)
    and, when it has no unconditional ``#[path]``, by its name.
    """
    base = posixpath.dirname(path)
    stem = PurePosixPath(path).stem
    first, *rest = inline
    explicit = (
        (first.path, *first.conditional_paths)
        if first.path is not None
        else first.conditional_paths
    )
    dirs = [posixpath.normpath(posixpath.join(base, value)) for value in explicit]
    if first.path is None:
        dirs.append(posixpath.normpath(posixpath.join(base, first.name)))
        dirs.append(posixpath.normpath(posixpath.join(base, stem, first.name)))
    for mod in rest:
        steps = (
            (mod.path, *mod.conditional_paths)
            if mod.path is not None
            else (*mod.conditional_paths, mod.name)
        )
        dirs = [
            posixpath.normpath(posixpath.join(parent, step))
            for parent in dirs
            for step in steps
        ]
    return tuple(dirs)


def _module_places(path: str, inline: Sequence[InlineModule]) -> tuple[str, ...]:
    """The directories a ``mod name;`` in ``path`` may name a file in.

    A crate root or ``mod.rs`` keeps its modules beside it, and any other file
    keeps them below its stem. Enclosing inline modules follow Rust's path
    rules, including any ``#[path]`` or ``#[cfg_attr(..., path)]`` overrides.
    """
    if inline:
        return _inline_dirs(path, inline)
    base = posixpath.dirname(path)
    return (base, posixpath.join(base, PurePosixPath(path).stem))


def _path_attr_dirs(path: str, inline: Sequence[InlineModule]) -> tuple[str, ...]:
    """The directories a ``#[path]`` attribute in ``path`` resolves against.

    Outside any inline module, ``#[path]`` resolves against ``dirname(path)``
    even in a non-mod-rs file. Inside inline modules, it follows their chain.
    """
    if inline:
        return _inline_dirs(path, inline)
    return (posixpath.dirname(path),)


def _effective_inline(
    inline: Sequence[InlineModule],
) -> tuple[tuple[str, ...], ...]:
    """Effective directory steps of each enclosing inline module."""
    return tuple(
        (mod.path, *mod.conditional_paths)
        if mod.path is not None
        else (*mod.conditional_paths, mod.name)
        for mod in inline
    )


def _fallback_target_roots(
    manifest: str,
    parsed: Table,
    files: frozenset[str],
    workspace_package: Table | None,
) -> list[str]:
    """Hand-written target-root seeding used only when ``cargo metadata`` is
    unavailable or fails for ``manifest``."""
    package = package_table(parsed)
    if not package:
        return []  # a virtual manifest has no targets of its own
    directory = posixpath.dirname(manifest)
    lib, bins = parsed.get("lib"), parsed.get("bin")
    build = package.get("build")
    roots = [] if build is False or isinstance(build, str) else ["build.rs"]
    if not (isinstance(lib, dict) and isinstance(lib.get("path"), str)) and (
        isinstance(lib, dict) or package.get("autolib") is not False
    ):
        roots.append("src/lib.rs")
    claimed = (
        isinstance(bins, list)
        and "name" in package
        and any(
            isinstance(b, dict) and b.get("name") == package.get("name") and "path" in b
            for b in bins
        )
    )
    if (auto_discovery_enabled(parsed, "bin", workspace_package) and not claimed) or (
        isinstance(bins, list)
        and any(isinstance(b, dict) and "path" not in b for b in bins)
    ):
        roots.append("src/main.rs")
    seeded = [posixpath.normpath(posixpath.join(directory, root)) for root in roots]
    seeded.extend(
        posixpath.normpath(posixpath.join(directory, declared.value))
        for declared in declared_cargo_paths(parsed)
        if declared.kind in {"target", "build"}
    )
    seeded.extend(
        posixpath.normpath(posixpath.join(directory, file))
        for file in named_target_files(parsed, workspace_package=workspace_package)
    )
    declared_names = declared_target_names(parsed)
    for sub, section in _TARGET_DIRS.items():
        if not auto_discovery_enabled(parsed, section, workspace_package):
            continue
        prefix = posixpath.join(directory, sub) + "/"
        for file in files:
            rest = file[len(prefix) :] if file.startswith(prefix) else ""
            parts = rest.split("/")
            if len(parts) == 1 and rest.endswith(".rs"):
                stem = rest[:-3]
            elif len(parts) == 2 and parts[1] == "main.rs":
                stem = parts[0]
            else:
                continue
            if not stem or stem.startswith(".") or (section, stem) in declared_names:
                continue
            seeded.append(file)
    return seeded


def _compiled_rust_files(
    target: Path,
    crates: Sequence[tuple[str, Table]],
    files: frozenset[str],
    *,
    metadata: Mapping[str, CargoPackageMetadata] | None = None,
    workspace_package: Table | None = None,
) -> frozenset[str]:
    """Files Cargo compiles: target roots from ``cargo metadata`` (falling back
    to manifest rules when Cargo is unavailable), and every file those reach
    through ``mod``, ``#[path]``, ``#[cfg_attr(..., path)]``, or ``include!``."""
    resolved_meta = (
        read_all_cargo_metadata(target, [manifest for manifest, _ in crates])
        if metadata is None
        else metadata
    )
    if workspace_package is None:
        root_parsed = next(
            (parsed for manifest, parsed in crates if manifest == "Cargo.toml"), {}
        )
        ws_table = root_parsed.get("workspace")
        ws_pkg_raw = ws_table.get("package") if isinstance(ws_table, dict) else None
        workspace_package = ws_pkg_raw if isinstance(ws_pkg_raw, dict) else {}

    queue: list[str] = []
    for manifest, parsed in crates:
        pkg_meta = resolved_meta.get(manifest)
        if pkg_meta is not None:
            queue.extend(t.src_path for t in pkg_meta.targets)
        else:
            queue.extend(
                _fallback_target_roots(manifest, parsed, files, workspace_package)
            )
    reached: set[str] = set()
    while queue:
        path = queue.pop()
        if path in reached or path not in files:
            continue
        reached.add(path)
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        mods, path_literals = rust_source_structure(text)
        code = rust_code_view(text)
        for module in mods:
            if not module.attributed:
                queue.extend(
                    posixpath.normpath(posixpath.join(place, shape.format(module.name)))
                    for place in _module_places(path, module.inline)
                    for shape in _MODULE_SHAPES
                )
        base = posixpath.dirname(path)
        for item in path_literals:
            if item.kind == "inline_dir":
                continue  # directory override; child mods/paths carry it in item.inline
            value = text[item.literal.content_start : item.literal.content_end]
            if item.kind == "include" and _opens_with(
                _DATA_INCLUDE, code, item.literal.start
            ):
                continue  # include_str!/include_bytes! read data, not Rust
            places = (
                (base,)
                if item.kind == "include"
                else _path_attr_dirs(path, item.inline)
            )
            queue.extend(
                posixpath.normpath(posixpath.join(place, value)) for place in places
            )
    return frozenset(reached)


def _split_tokens(
    source: Identity, destination: Identity, rules: Rules
) -> tuple[re.Pattern[str], ...]:
    """The crate names a ``[[cargo_split]]`` press checks with its own rules."""
    names = dict(source.cargo_names)
    return tuple(
        token_pattern(f"{CARGO_EXACT_PREFIX}{split.role}", names[split.role])
        or re.compile(re.escape(names[split.role]))
        for split in active_cargo_splits(source, destination, rules)
    )


def _rust_source_path_splits(
    path: str,
    text: str,
    new_text: str,
    plan: RenamePlan,
    files: frozenset[str],
    directories: frozenset[str],
    split_tokens: Sequence[re.Pattern[str]],
) -> list[str]:
    """Paths Rust source declares that the rewrite would separate from their files.

    These are the file of a ``mod name;``, a ``#[path]`` value, and an
    ``include_str!``, ``include_bytes!``, or ``include!`` argument. Each is
    judged when the rewrite changes it or its effective enclosing inline-module
    directories: it must still name the file or directory it named, at that
    target's planned new path. A crate name that a ``[[cargo_split]]`` role
    splits is left to the split preflight.
    """

    def split_owned(value: str) -> bool:
        return any(token.search(value) for token in split_tokens)

    problems: list[str] = []
    new_path = plan.translate(path)
    base, new_base = posixpath.dirname(path), posixpath.dirname(new_path)
    old_mods, old_paths = rust_source_structure(text)
    new_mods, new_paths = rust_source_structure(new_text)
    if len(old_paths) != len(new_paths) or len(old_mods) != len(new_mods):
        return [f"{path}: the rewrite changes which Rust paths the file declares"]
    for old_item, new_item in zip(old_paths, new_paths, strict=True):
        if old_item.kind != new_item.kind:
            return [f"{path}: the rewrite changes which Rust paths the file declares"]
        value = text[old_item.literal.content_start : old_item.literal.content_end]
        new_value = new_text[
            new_item.literal.content_start : new_item.literal.content_end
        ]
        inline_changed = old_item.kind != "include" and _effective_inline(
            old_item.inline
        ) != _effective_inline(new_item.inline)
        if value == new_value and not inline_changed:
            continue
        if split_owned(value):
            continue  # checked by _rust_path_problems with the same inline rules
        old_dirs = (
            (base,)
            if old_item.kind == "include"
            else _path_attr_dirs(path, old_item.inline)
        )
        new_dirs = (
            (new_base,)
            if new_item.kind == "include"
            else _path_attr_dirs(new_path, new_item.inline)
        )
        if len(old_dirs) != len(new_dirs):
            return [f"{path}: the rewrite changes which Rust paths the file declares"]
        targets = directories if old_item.kind == "inline_dir" else files
        found = [
            (
                posixpath.normpath(posixpath.join(old_dir, value)),
                posixpath.normpath(posixpath.join(new_dir, new_value)),
            )
            for old_dir, new_dir in zip(old_dirs, new_dirs, strict=True)
            if posixpath.normpath(posixpath.join(old_dir, value)) in targets
        ]
        if found and all(
            plan.translate(resolved) == moved for resolved, moved in found
        ):
            continue
        if not found and old_item.kind == "inline_dir":
            continue  # no child resolves against it; each child is judged itself
        if value != new_value:
            problems.append(
                f"{path}:{_line_of(text, old_item.literal.start)}: the Rust path "
                f"{value!r} would become {new_value!r}, but the press would not move "
                "the file it names to match. Rename the file so a press moves it, add "
                "the shared name to keep_names, or edit the path by hand before "
                "pressing"
            )
        else:
            problems.append(
                f"{path}:{_line_of(text, old_item.literal.start)}: the Rust path "
                f"{value!r} sits inside a renamed inline module, but the press would "
                "not move the file it names to match. Rename the directory so a press "
                "moves it, add the shared name to keep_names, or edit the module by "
                "hand before pressing"
            )
    join = posixpath.join
    for old_mod, new_mod in zip(old_mods, new_mods, strict=True):
        name, new_name = old_mod.name, new_mod.name
        inline_changed = _effective_inline(old_mod.inline) != _effective_inline(
            new_mod.inline
        )
        if (name == new_name and not inline_changed) or old_mod.attributed:
            continue
        if name != new_name and split_owned(name) and not inline_changed:
            continue
        old_dirs = _module_places(path, old_mod.inline)
        new_dirs = _module_places(new_path, new_mod.inline)
        if len(old_dirs) != len(new_dirs):
            return [f"{path}: the rewrite changes which Rust paths the file declares"]
        found_mods = [
            (posixpath.normpath(join(old_dir, shape.format(name))), new_dir, shape)
            for old_dir, new_dir in zip(old_dirs, new_dirs, strict=True)
            for shape in _MODULE_SHAPES
            if posixpath.normpath(join(old_dir, shape.format(name))) in files
        ]
        if (found_mods or old_mod.conditional) and all(
            plan.translate(file)
            == posixpath.normpath(join(new_dir, shape.format(new_name)))
            for file, new_dir, shape in found_mods
        ):
            # A ``cfg_attr`` path with no name-based file leaves nothing to move.
            continue
        if name != new_name:
            problems.append(
                f"{path}:{_line_of(text, old_mod.offset)}: `mod {name};` would become "
                f"`mod {new_name};`, but the press would not rename the module's "
                "file to match. Rename the file so a press moves it, add the shared "
                "name to keep_names, or edit the module by hand before pressing"
            )
        else:
            problems.append(
                f"{path}:{_line_of(text, old_mod.offset)}: `mod {name};` sits inside "
                "a renamed inline module, but the press would not move the module's "
                "file to match. Rename the directory so a press moves it, add the "
                "shared name to keep_names, or edit the module by hand before pressing"
            )
    return problems


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _module_rename_problem(
    step: RenameStep, old_name: str, new_name: str, mod_declared: bool
) -> str | None:
    """A rename that would give a Rust module path the package spelling.

    ``src/bin/<name>`` names a binary, which may hold a hyphen; any other
    renamed component below ``src/`` is a module that ``mod <name>;`` names.
    Anywhere else, such as ``tests/<name>/mod.rs``, a component is a module
    when some ``.rs`` file declares ``mod <name>;``.
    """
    parts = PurePosixPath(step.old_prefix).parts
    parents = parts[:-1]
    leaf = parts[-1]
    named = leaf == old_name or leaf == f"{old_name}.rs"
    problem = (
        f"{step.old_prefix}: renaming it to {step.new_prefix!r} gives a Rust "
        f"module path the package spelling {new_name!r}, which `mod` cannot "
        "name. Rename the module first"
    )
    if mod_declared and named:
        return problem
    if "src" not in parents:
        return None
    below = parents[len(parents) - parents[::-1].index("src") :]
    return None if below == ("bin",) else problem


_LOG_LEVELS = "error|warn|info|debug|trace|off"
_RUST_LOG = re.compile(r"RUST_LOG=[\"']?([^\s\"']*)")


def _identifier_contexts(text: str, name: str) -> list[int]:
    """Offsets where ``name`` sits in a position only a Rust identifier fits.

    These are a path (``name::``), ``extern crate name``, ``use name``, and a
    log filter target (``name=debug`` or a ``RUST_LOG`` directive).
    """
    token = re.escape(name)
    edge = r"(?![A-Za-z0-9_-])"
    patterns = (
        rf"(?<![A-Za-z0-9_-]){token}::",
        rf"\bextern\s+crate\s+(?P<n>{token}){edge}",
        rf"\buse\s+(?P<n>{token}){edge}",
        rf"(?<![A-Za-z0-9_-]){token}=(?:{_LOG_LEVELS})\b",
    )
    offsets = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE if "=" in pattern else 0):
            offsets.add(match.start("n") if "?P<n>" in pattern else match.start())
    for match in _RUST_LOG.finditer(text):
        position = match.start(1)
        for directive in match.group(1).split(","):
            target = directive.split("=", 1)[0]
            if target == name or target.startswith(f"{name}::"):
                offsets.add(position)
            position += len(directive) + 1
    return sorted(offsets)


_INCLUDE_STR = re.compile(r"\binclude_str\s*!\s*[(\[{]\s*$")
_DATA_INCLUDE = re.compile(r"\binclude_(?:str|bytes)\s*!\s*[(\[{]\s*$")


def _opens_with(macro: re.Pattern[str], code: str, start: int) -> bool:
    """Whether ``macro``'s call opens right before ``start`` in ``code``,
    past any whitespace and blanked comments."""
    end = start
    while end and code[end - 1].isspace():
        end -= 1
    return macro.search(code, max(end - 64, 0), end) is not None


def _doc_included_files(target: Path, paths: Sequence[str]) -> dict[str, str]:
    """Files a ``.rs`` file reads with ``include_str!``, each with that
    ``file:line``. rustdoc compiles such a file's code blocks when the string
    is doc text, as in ``#![doc = include_str!("../README.md")]``.
    """
    found: dict[str, str] = {}
    for path in paths:
        if not path.endswith(".rs"):
            continue
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "include_str" not in text:
            continue
        code = rust_code_view(text)
        for literal in rust_strings(text):
            if literal.doc or not _opens_with(_INCLUDE_STR, code, literal.start):
                continue
            value = text[literal.content_start : literal.content_end]
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(path), value)
            )
            found.setdefault(resolved, f"{path}:{_line_of(text, literal.start)}")
    return found


def _doc_included_problems(
    path: str, text: str, new_text: str, new: str, role: str, where: str
) -> list[str]:
    """Package spellings the press would write where rustdoc compiles Rust.

    In a doc-included ``package_files`` file, that is any line of a code block
    rustdoc may compile, and any position only a Rust identifier fits.
    """
    old_lines, new_lines = text.split("\n"), new_text.split("\n")
    if len(old_lines) != len(new_lines):
        return [f"{path}: the rewrite changes its line count; edit it by hand"]
    lines = {
        number
        for number in compiled_markdown_lines(text)
        if new_lines[number - 1].count(new) > old_lines[number - 1].count(new)
    }
    if len(_identifier_contexts(new_text, new)) > len(_identifier_contexts(text, new)):
        lines.update(
            _line_of(new_text, offset) for offset in _identifier_contexts(new_text, new)
        )
    return [
        f"{path}:{line}: {new!r} would sit in a code block that rustdoc compiles "
        f"as Rust, or where only a Rust identifier fits, because {where} includes "
        "this file with include_str!, but package_files gives it the package "
        "spelling. List the file in identifier_files instead, and cover each "
        "span that needs the package spelling, such as a `cargo add` line, with "
        f'an exact [[replace]] rule such as "cargo add {{cargo_exact_{role}}}"'
        for line in sorted(lines)
    ]


def _rule_hyphen_problems(
    path: str,
    text: str,
    new: str,
    role: str,
    rules: Rules,
    source: Identity,
    destination: Identity,
) -> list[str]:
    """A ``[[replace]]`` rule must not write a split role's hyphenated name into
    a ``.rs`` file: ``{cargo_exact_<role>}`` never fits a Rust identifier."""
    found: list[str] = []
    for rule in rules.replace:
        if not rule.content or not rule_matches_path(rule, path):
            continue
        to_value = render_replace_pattern(rule.pattern, destination)
        from_value = render_replace_pattern(rule.pattern, source)
        if new not in to_value or from_value == to_value or from_value not in text:
            continue
        found.append(
            f"{path}:{_line_of(text, text.index(from_value))}: [[replace]] rule "
            f"{rule.pattern!r} would write {new!r}, the hyphenated name of "
            f"[[cargo_split]] role {role!r}, into a Rust file, where only an "
            f"identifier fits. Use {{cargo_ident_{role}}} in the pattern, or "
            "scope the rule away from .rs files"
        )
    return found


def cargo_split_target_problems(
    target: Path, source: Identity, destination: Identity, rules: Rules
) -> list[str]:
    """Why this target's ``[[cargo_split]]`` press cannot choose every spelling.

    Each check reads what the press really runs: every occurrence the ordered
    rows leave behind is a file nobody declared, listed by ``file:line``.
    """
    splits = active_cargo_splits(source, destination, rules)
    if not splits:
        return []
    old_names, new_names = dict(source.cargo_names), dict(destination.cargo_names)
    removed = frozenset(rule.file for rule in rules.remove)
    removed_dirs = tuple(f"{rule.dir}/" for rule in rules.remove_dirs)
    problems: list[str] = []
    paths = [
        path
        for path in _content_surface_paths(target, rules)
        if path not in removed and not path.startswith(removed_dirs)
    ]
    for split in splits:
        problems.extend(
            f"{path}: matches both package_files and identifier_files of "
            f"[[cargo_split]] role {split.role!r}; a file takes one spelling"
            for path in paths
            if split_spelling(split, path) == "both"
        )
    if problems:
        return problems
    rows = _compiled_rows(source, destination, target, rules)
    rename_snapshot = capture_surface_snapshot(target)
    try:
        plan: RenamePlan | None = _compile_rename_plan(
            rows,
            SurfaceSnapshot(
                entries=select_rename_entries(
                    rename_snapshot,
                    exclude_files=rules.exclude_files,
                    exclude_dirs=rules.exclude_dirs,
                    root_control=ROOT_CONTROL,
                ),
                visibility_inputs=rename_snapshot.visibility_inputs,
            ),
            rules.keep_names,
        )
    except ValidationError:
        plan = None  # the plan step reports an uncompilable plan
    surface = frozenset(entry.rel.as_posix() for entry in rename_snapshot.entries)
    directories = frozenset(
        parent.as_posix()
        for entry in rename_snapshot.entries
        for parent in entry.rel.parents
        if parent != Path()
    )
    content_rows = tuple(row for row in rows if "content" in row.rewrite_surfaces)
    mod_declared: set[str] = set()
    included = _doc_included_files(target, paths)
    for path in paths:
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except UnicodeDecodeError:
            continue
        new_text, _ = rewrite_file(
            (row for row in content_rows if row_matches_scope(row, path)),
            text,
            rules.keep_names,
        )
        kept = kept_spans(new_text, rules.keep_names)
        strings = rust_strings(new_text) if path.endswith(".rs") else ()
        quoted = quoted_spans(new_text) if path.endswith(".rs") else ()
        if path.endswith(".rs"):
            problems.extend(
                f"{path}:{_line_of(text, offset)}: the documentation above this "
                "`mod` declaration may end inside a Rust string literal, a block "
                "comment, or the arguments of a `stringify!` or `concat!` call: "
                "its doc comment ends that way, or a `#[doc = ...]` attribute "
                "there is not a plain string or names one of those macros. rustdoc "
                "joins the doc comment of the module's own file to it, so the "
                "press cannot read that file's doc comment. Close the string or "
                "comment, or move the attribute into the module's file, below "
                "its doc comment"
                for offset in cut_module_docs(text)
            )
            problems.extend(
                f"{path}:{_line_of(text, offset)}: renames `stringify!` or "
                "`concat!`. A call through the new name, in this file or another, "
                "turns its arguments into text that the press cannot see, so it "
                "cannot choose a spelling there. Call the macro by its own name "
                "before pressing"
                for offset in quoting_renames(text)
            )
        for split in splits:
            old, new = old_names[split.role], new_names[split.role]
            role = f"[[cargo_split]] role {split.role!r}"
            if path.endswith(".rs") and re.search(
                rf"(?<![A-Za-z0-9_])mod\s+{re.escape(old)}\s*;", text
            ):
                mod_declared.add(split.role)
            if path.endswith(".rs") and "-" in new:
                problems.extend(
                    _rule_hyphen_problems(
                        path, text, new, split.role, rules, source, destination
                    )
                )
            for start, end in disjoint_matches(
                token_pattern(f"{CARGO_EXACT_PREFIX}{split.role}", old)
                or re.compile(re.escape(old)),
                new_text,
                kept,
            ):
                where = f"{path}:{_line_of(new_text, start)}"
                literal = string_at(strings, (start, end))
                unread = literal is not None and literal.unread
                if span_within(quoted, (start, end)) and not unread:
                    problems.append(
                        f"{where}: {old!r} is in the arguments of a `stringify!` "
                        "or `concat!` call, which turns them into text, so the "
                        f"press cannot choose {new!r} or {cargo_ident(new)!r}. In "
                        "a doc comment, a call that the press cannot find the end "
                        "of holds the rest of the item's doc comments. Edit the "
                        "call by hand before pressing"
                    )
                    continue
                if literal is not None:
                    place, remedy = (
                        "inside a Rust string literal",
                        "Edit the string by hand before pressing",
                    )
                    if literal.unread:
                        problems.append(
                            f"{where}: {old!r} is in a doc comment that follows a "
                            "`#[doc = ...]` attribute the press cannot read: its "
                            "value is not a plain string, or holds a quote, a "
                            "backslash, or a block-comment marker. A string or a "
                            "comment from that text may still be open here, so "
                            f"the press cannot choose {new!r} or "
                            f"{cargo_ident(new)!r}. Move the attribute below the "
                            "doc comment, or edit the comment by hand before "
                            "pressing"
                        )
                        continue
                    if literal.doc:
                        place = (
                            "in a doc comment that rustdoc may compile as a "
                            "doctest, where it would sit in a Rust string literal"
                        )
                        remedy = (
                            "Edit the comment by hand before pressing: prose that "
                            "names the crate in backticks, without double quotes, "
                            f"takes {cargo_ident(new)!r}"
                        )
                    problems.append(
                        f"{where}: {old!r} is {place} that the press cannot prove "
                        "is a Cargo feature name, a path to a file it renames, or "
                        "a CARGO_PKG_NAME comparison, so it cannot choose "
                        f"{new!r} or {cargo_ident(new)!r}. {remedy}"
                    )
                    continue
                problems.append(
                    f"{where}: {old!r} is in no {role} list, so the press cannot "
                    f"tell whether to write {new!r} or {cargo_ident(new)!r}. Add "
                    "the file to package_files or identifier_files"
                )
            if path.endswith(".rs") and plan is not None:
                problems.extend(
                    _rust_path_problems(
                        path, text, new_text, old, plan, surface, directories
                    )
                )
            if split_spelling(split, path) != "package" or path.endswith("Cargo.toml"):
                continue
            if path in included:
                problems.extend(
                    _doc_included_problems(
                        path, text, new_text, new, split.role, included[path]
                    )
                )
                continue
            written = _identifier_contexts(new_text, new)
            if len(written) <= len(_identifier_contexts(text, new)):
                continue  # the press wrote none of them
            problems.extend(
                f"{path}:{_line_of(new_text, offset)}: {new!r} would sit where "
                "only a Rust identifier fits (a `::` path, `extern crate`, "
                "`use`, or a log filter such as RUST_LOG), but package_files "
                f"gives it the package spelling. List the file in "
                "identifier_files, or cover the span with an exact [[replace]] "
                "rule scoped to the file, with a pattern such as "
                '"{cargo_ident_<role>}::" or "extern crate {cargo_ident_<role>};" '
                "(or {package_name} when "
                f"{old!r} is the package_name crate)"
                for offset in written
            )
    for manifest in cargo_manifest_files(target):
        if manifest in removed or manifest.startswith(removed_dirs):
            continue
        data = tomllib.loads(read_regular_nofollow(target / manifest).decode("utf-8"))
        lib = data.get("lib")
        lib_name = lib.get("name") if isinstance(lib, dict) else None
        for split in splits:
            if lib_name == old_names[split.role]:
                problems.append(
                    f"{manifest}: [lib] name {lib_name!r} would take the package "
                    f"spelling {new_names[split.role]!r}, and Cargo refuses a "
                    "hyphen in a library name. Remove the explicit [lib] name, "
                    "which defaults to the package name's underscore form"
                )
    if plan is None:
        return problems
    split_path_rows = {
        f"identity:{CARGO_EXACT_PREFIX}{split.role}{SPLIT_PATH_ROW_SUFFIX}": split
        for split in splits
    }
    for step in plan.steps:
        for row_id in step.row_ids:
            split = split_path_rows.get(row_id)
            if split is None:
                continue
            problem = _module_rename_problem(
                step,
                old_names[split.role],
                new_names[split.role],
                split.role in mod_declared,
            )
            if problem is not None:
                problems.append(problem)
    return problems


def _rust_path_problems(
    path: str,
    text: str,
    new_text: str,
    old: str,
    plan: RenamePlan,
    surface: frozenset[str],
    directories: frozenset[str],
) -> list[str]:
    """Rewritten path strings that no longer name the file they named.

    ``include_*!`` resolves against the source file's directory; ``#[path]``
    resolves against any enclosing inline-module directories. The string is
    provable only when it named a file or directory on the surface and its
    rewrite names that target's planned new path from the file's new location.
    """
    token = token_pattern(f"{CARGO_EXACT_PREFIX}x", old) or re.compile(re.escape(old))
    old_items = rust_path_literals(text)
    new_items = rust_path_literals(new_text)
    if len(old_items) != len(new_items):
        return [f"{path}: the rewrite changes which Rust paths the file declares"]
    new_path = plan.translate(path)
    base, new_base = posixpath.dirname(path), posixpath.dirname(new_path)
    problems: list[str] = []
    for old_item, new_item in zip(old_items, new_items, strict=True):
        if not token.search(
            text, old_item.literal.content_start, old_item.literal.content_end
        ):
            continue
        if old_item.kind != new_item.kind:
            return [f"{path}: the rewrite changes which Rust paths the file declares"]
        value = text[old_item.literal.content_start : old_item.literal.content_end]
        new_value = new_text[
            new_item.literal.content_start : new_item.literal.content_end
        ]
        old_dirs = (
            (base,)
            if old_item.kind == "include"
            else _path_attr_dirs(path, old_item.inline)
        )
        new_dirs = (
            (new_base,)
            if new_item.kind == "include"
            else _path_attr_dirs(new_path, new_item.inline)
        )
        if len(old_dirs) != len(new_dirs):
            return [f"{path}: the rewrite changes which Rust paths the file declares"]
        targets = directories if old_item.kind == "inline_dir" else surface
        found = [
            (
                posixpath.normpath(posixpath.join(old_dir, value)),
                posixpath.normpath(posixpath.join(new_dir, new_value)),
            )
            for old_dir, new_dir in zip(old_dirs, new_dirs, strict=True)
            if posixpath.normpath(posixpath.join(old_dir, value)) in targets
        ]
        if found and all(
            plan.translate(resolved) == moved for resolved, moved in found
        ):
            continue
        line = _line_of(text, old_item.literal.start)
        problems.append(
            f"{path}:{line}: the path string {value!r} names "
            + (
                "no file the press keeps"
                if not found
                else "a file whose rename the rewritten string would not follow"
            )
            + ", so the press cannot prove its spelling. Edit the string by hand "
            "before pressing"
        )
    return problems


def _identity_row_pattern(row: RenderedSubstitution) -> re.Pattern[str]:
    """The matcher one compiled identity row rewrites with."""

    field = row.matcher.identity_field
    if row.matcher.substring or field is None:
        return re.compile(re.escape(row.from_value))
    return token_pattern(field, row.from_value) or re.compile(re.escape(row.from_value))


def _checked_dependency_names(
    target: Path, rules: Rules, removed: frozenset[str]
) -> tuple[str, ...]:
    """Root ``package.json`` dependency keys, when node is a checked language."""

    if "package.json" in removed or (
        rules.languages is not None and "node" not in rules.languages
    ):
        return ()
    manifest = read_node_manifest(target)
    return () if manifest is None else manifest.dependency_names


def _checked_cargo_dependency_names(
    target: Path,
    source: Identity,
    removed: frozenset[str],
    languages: Sequence[str],
) -> tuple[str, ...]:
    """Non-local Cargo dependencies, when a Cargo table meets a checked manifest."""

    if (
        not source.cargo_names
        or "Cargo.toml" in removed
        or "rust" not in languages
        or not os.path.lexists(target / "Cargo.toml")
    ):
        return ()
    return read_cargo_facts(target).external_dependencies


def _source_line_reader(target: Path) -> Callable[[str, int], str | None]:
    """Cached ``(src_path, 1-based line) -> str | None`` reader over ``target``."""
    cache: dict[str, list[str] | None] = {}

    def reader(src_path: str, line: int) -> str | None:
        if src_path not in cache:
            path = target / src_path
            if is_regular_lstat(path):
                try:
                    cache[src_path] = (
                        read_regular_nofollow(path).decode("utf-8").splitlines()
                    )
                except (OSError, SafetyError, UnicodeDecodeError):
                    cache[src_path] = None
            else:
                cache[src_path] = None
        lines = cache[src_path]
        if lines is None or line < 1 or line > len(lines):
            return None
        return lines[line - 1]

    return reader


def check_target_keep_names(
    target: Path,
    source: Identity,
    destination: Identity,
    rules: Rules,
    removed: frozenset[str],
    languages: Sequence[str],
    *,
    verify_config: VerifyConfig | None = None,
    snapshot: SurfaceSnapshot | None = None,
) -> KeepCheck:
    """Run the keep-name preflight with this press's real rewrite rows."""

    rows = (
        *_declared_rows(source, destination, rules),
        *_identity_rows(source, destination, rules, target),
        *_hyphen_rows(source, destination, target, rules),
    )
    # Equal-valued fields collapse to one owner row, so only the compiled rows
    # prove which matcher really rewrites an occurrence.
    compiled = _compiled_rows(source, destination, target, rules)

    def rewritten(path: str, where: str, text: str) -> RewrittenForms:
        scope_path = path
        surface: Surface = "content" if where == "content" else "path"
        if where == "symlink":
            # Only an in-tree relative link follows a rename.
            scope_path = symlink_target_posix(Path(path), text)
            if os.path.isabs(text) or scope_path.split("/", 1)[0] == "..":
                return RewrittenForms()
        applying = [
            row
            for row in rows
            if surface in row.rewrite_surfaces and row_matches_scope(row, scope_path)
        ]
        return RewrittenForms(
            tokens=frozenset(
                row.from_value
                for row in applying
                if row.provenance[0].kind != "replace_rule"
            ),
            literals=frozenset(
                row.from_value
                for row in applying
                if row.provenance[0].kind == "replace_rule"
            ),
            patterns=tuple(
                _identity_row_pattern(row)
                for row in compiled
                if row.provenance[0].kind not in ("replace_rule", "manifest_name")
                and surface in row.rewrite_surfaces
                and row_matches_scope(row, scope_path)
            ),
        )

    glued_fields: Sequence[tuple[str, str]] = ()
    glued_substring: frozenset[str] = frozenset()
    if verify_config is not None:
        scan_fields, glued_substring = effective_verify_fields(
            source, verify_config, rules.substring_rewrite_fields
        )
        glued_fields = changed_verify_fields(
            source, destination, scan_fields, glued_substring
        )

    raw = check_keep_surfaces(
        rewrite_surface_texts(
            target,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
            skip_paths=removed,
            exclude_prefixes=regenerate_dir_prefixes(rules),
            snapshot=snapshot,
        ),
        source,
        rules.keep_names,
        rewritten=rewritten,
        dependency_names=_checked_dependency_names(target, rules, removed),
        cargo_dependency_names=_checked_cargo_dependency_names(
            target, source, removed, languages
        ),
        glued_fields=glued_fields,
        glued_substring_fields=glued_substring,
        glued_skip_dir_components=rules.verify_ignore,
    )
    if verify_config is None:
        return raw
    exact_items = [item for item in raw.undeclared if item.kind != "glued"]
    glued_items = [item for item in raw.undeclared if item.kind == "glued"]
    if glued_items and verify_config.ignores:
        findings = [
            Finding(
                item.path,
                item.field,
                item.value,
                item.where,
                item.line,
                item.col,
                "",
            )
            for item in glued_items
        ]
        surviving, _stale = apply_ignores(
            findings,
            list(verify_config.ignores),
            forward_map=lambda p: p,
            source_line=_source_line_reader(target),
        )
        surviving_keys = {
            (f.path, f.field, f.value, f.where, f.line, f.col) for f in surviving
        }
        glued_items = [
            item
            for item in glued_items
            if (item.path, item.field, item.value, item.where, item.line, item.col)
            in surviving_keys
        ]
    exact_keys = {(item.path, item.where, item.token) for item in exact_items}
    deduped_glued: dict[tuple[str, str, str], UndeclaredName] = {}
    for item in glued_items:
        key = (item.path, item.where, item.token)
        if key in exact_keys:
            continue
        deduped_glued.setdefault(key, item)
    return KeepCheck((*exact_items, *deduped_glued.values()), raw.stale)


def compile_substitution_table(
    source: Identity,
    destination: Identity,
    rules: Rules,
    snapshot: SurfaceSnapshot,
    *,
    target: Path | None = None,
    pipeline_validator: Callable[
        ..., tuple[PipelineCandidate, ...]
    ] = validate_pipeline,
) -> SubstitutionTable:
    """Render, validate, and compile all rebrand mechanisms for one target."""

    source.validate()
    destination.validate()
    rows = _compiled_rows(source, destination, target, rules)
    _refuse_cargo_owner_stale_output(rows, destination)
    rename_snapshot = SurfaceSnapshot(
        entries=select_rename_entries(
            snapshot,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
            exclude_prefixes=regenerate_dir_prefixes(rules),
        ),
        visibility_inputs=snapshot.visibility_inputs,
    )
    virtual_translations = _compile_virtual_translations(
        target, rows, snapshot, rules.keep_names
    )
    _validate_rows(
        rows,
        destination,
        rules,
        rename_snapshot,
        pipeline_validator,
        tuple(source for _link, source, _destination in virtual_translations),
    )
    _refuse_regenerated_cargo_leak(rows, destination, rules)
    rename_plan = _compile_rename_plan(rows, rename_snapshot, rules.keep_names)
    rename_plan = replace(
        rename_plan,
        virtual_translations=virtual_translations,
        source_entries=snapshot.entries,
        symlink_inputs=_compile_symlink_inputs(target, snapshot),
    )
    rename_plan = _enrich_rename_plan(target, rename_plan, snapshot)
    _validate_visibility_projection(
        target,
        rows,
        rename_plan,
        snapshot,
        rules,
    )
    return SubstitutionTable(
        rows=rows,
        rename_plan=rename_plan,
        keep_names=rules.keep_names,
    )
