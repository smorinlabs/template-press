"""Compile rebrand mechanisms into one immutable substitution table."""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import stat
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from template_press.rebrand.cargo_manifest import (
    DeclaredPath,
    auto_discovered_bins,
    cargo_manifest_files,
    declared_cargo_paths,
    read_cargo_facts,
)
from template_press.rebrand.identity import (
    CARGO_BIN_ENV_TAG,
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    cargo_bin_env_pairs,
    cargo_field_values,
    cargo_name_pairs,
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
from template_press.rebrand.matcher import find_occurrences, identity_pattern
from template_press.rebrand.node_manifest import read_node_manifest
from template_press.rebrand.pathing import ROOT_CONTROL, symlink_target_posix
from template_press.rebrand.pipeline import (
    MAX_RENAME_PASSES,
    MatcherSpec,
    PipelineCandidate,
    StabilitySink,
    validate_pipeline,
)
from template_press.rebrand.rules import (
    ReplaceRule,
    Rules,
    render_replace_pattern,
)
from template_press.rebrand.safety import (
    RenameClosureUnauthorized,
    SafetyError,
    assert_ancestors_real,
    read_regular_nofollow,
    readlink_nofollow,
)

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


def _rewrite_outside_kept(
    row: RenderedSubstitution, text: str, kept: Sequence[tuple[int, int]]
) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Replace matches disjoint from ``kept``; return text and shifted spans.

    The pattern runs over the whole current text, so boundaries see true
    neighbors.
    """

    replaced: list[tuple[int, int]] = []
    if row.provenance[0].kind == "manifest_name":
        span = _project_name_span(text, row.from_value, row.to_value)
        if span is not None and disjoint_from_kept(span, kept):
            replaced.append(span)
    else:
        if row.matcher.algorithm == "literal" or row.matcher.substring:
            pattern = re.compile(re.escape(row.from_value))
        elif row.matcher.algorithm != "conservative":
            raise ValidationError(
                f"rewrite row {row.row_id} uses non-rewrite matcher "
                f"{row.matcher.algorithm!r}"
            )
        elif row.matcher.identity_field is None:
            raise ValidationError(f"rewrite row {row.row_id} has no identity field")
        else:
            pattern = token_pattern(
                row.matcher.identity_field, row.from_value
            ) or re.compile(re.escape(row.from_value))
        replaced = disjoint_matches(pattern, text, kept)
    return splice_outside_kept(text, replaced, row.to_value, kept)


def rewrite_file(
    rows: Iterable[RenderedSubstitution],
    text: str,
    keep_names: Sequence[str] = (),
) -> tuple[str, tuple[RenderedSubstitution, ...]]:
    """Apply ``rows`` in order; return the text and the rows that changed it.

    Kept spans come from the ORIGINAL text and are carried through every row.
    An earlier row can therefore neither expose a kept name to a later row by
    changing its neighbor nor create a new kept name.
    """

    kept = kept_spans(text, keep_names) if keep_names else ()
    current = text
    changed: list[RenderedSubstitution] = []
    for row in rows:
        if kept:
            updated, kept = _rewrite_outside_kept(row, current, kept)
        else:
            updated = rewrite_with_row(row, current)
        if updated != current:
            changed.append(row)
            current = updated
    return current, tuple(changed)


def rewrite_with_row(row: RenderedSubstitution, text: str) -> str:
    """Apply one row's matcher without consulting source configuration."""

    if row.provenance[0].kind == "manifest_name":
        return _rewrite_project_name(text, row.from_value, row.to_value)
    if row.matcher.algorithm == "literal" or row.matcher.substring:
        return text.replace(row.from_value, row.to_value)
    if row.matcher.algorithm != "conservative":
        raise ValidationError(
            f"rewrite row {row.row_id} uses non-rewrite matcher "
            f"{row.matcher.algorithm!r}"
        )
    field = row.matcher.identity_field
    if field is None:
        raise ValidationError(f"rewrite row {row.row_id} has no identity field")
    return replace_token(text, field, row.from_value, row.to_value)


def _hunt_pattern(row: RenderedSubstitution, matcher: MatcherSpec) -> re.Pattern[str]:
    """The regular expression equivalent of one compiled hunt matcher."""

    if matcher.algorithm == "literal":
        return re.compile(re.escape(row.from_value))
    field = matcher.identity_field
    if field is None:
        raise ValidationError(f"hunt for row {row.row_id} has no identity field")
    if matcher.algorithm == "paranoid":
        if matcher.substring:
            return re.compile(re.escape(row.from_value), re.IGNORECASE)
        return identity_pattern(field, row.from_value)
    if matcher.substring:
        return re.compile(re.escape(row.from_value))
    return token_pattern(field, row.from_value) or re.compile(re.escape(row.from_value))


def hunt_occurs(
    row: RenderedSubstitution,
    policy: HuntPolicy,
    text: str,
    kept: Sequence[tuple[int, int]] = (),
) -> bool:
    """Apply one compiled consumer hunt to text, outside ``kept`` spans."""

    matcher = policy.matcher
    if kept:
        return bool(matches_outside_kept(_hunt_pattern(row, matcher), text, kept))
    if matcher.algorithm == "literal":
        return row.from_value in text
    field = matcher.identity_field
    if field is None:
        raise ValidationError(f"hunt for row {row.row_id} has no identity field")
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


def _identity_rows(
    source: Identity, destination: Identity, rules: Rules
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
    return rows


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
    return RenderedSubstitution(
        row_id=owner.row_id,
        provenance=provenance,
        matcher=owner.matcher,
        from_value=owner.from_value,
        to_value=owner.to_value,
        rewrite_surfaces=owner.rewrite_surfaces,
        hunts=hunts,
        scope=owner.scope,
    )


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
        if provenance.kind == "identity" and not provenance.name.startswith(
            "display_name_"
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
                *_identity_rows(source, destination, rules),
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
                *_identity_rows(source, destination, rules),
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


def _rewritten_texts_with_bin_env(
    target: Path,
    rows: Sequence[RenderedSubstitution],
    rewritten: Iterable[str],
    removed: tuple[set[str], tuple[str, ...]],
    rules: Rules,
) -> tuple[tuple[str, str, str], ...]:
    """``(path, text, rewritten text)`` of kept files naming a binary by ``env!``."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(rewritten):
        if path in removed[0] or path.startswith(removed[1]):
            continue
        try:
            text = read_regular_nofollow(target / path).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "CARGO_BIN_EXE_" in text:
            scoped = (row for row in rows if row_matches_scope(row, path))
            found.append((path, text, rewrite_file(scoped, text, rules.keep_names)[0]))
    return tuple(found)


def _bin_env_splits(
    target: Path,
    manifest: str,
    data: dict[str, object],
    plan: RenamePlan,
    new_texts: Sequence[tuple[str, str, str]],
) -> list[str]:
    """``env!`` tokens the rewrite moves away from an auto-discovered binary.

    The binary's name is its file stem, so it changes only if the file renames.
    """
    base = posixpath.dirname(manifest)
    problems: list[str] = []
    for name, rel in auto_discovered_bins(target / base, data):
        moved = PurePosixPath(plan.translate(posixpath.join(base, rel)))
        new_name = moved.stem if rel.endswith(".rs") else moved.name
        old_token = re.compile(rf"CARGO_BIN_EXE_{re.escape(name)}(?![\w-])")
        new_token = re.compile(rf"CARGO_BIN_EXE_{re.escape(new_name)}(?![\w-])")
        problems.extend(
            f"{path}: CARGO_BIN_EXE_{name} would be rewritten, but the press "
            f"would name that binary {new_name!r}"
            for path, old_text, new_text in new_texts
            if len(old_token.findall(old_text)) != len(new_token.findall(new_text))
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
        target, content_rows, rewritten, removed, rules
    )
    problems: list[str] = []
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
        parsed = tomllib.loads(text)
        problems.extend(_bin_env_splits(target, manifest, parsed, plan, new_texts))
        declared = declared_cargo_paths(parsed)
        try:
            rewritten_paths = declared_cargo_paths(tomllib.loads(new_text))
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{manifest}: the rewrite breaks its TOML: {exc}")
            continue
        if len(rewritten_paths) != len(declared):
            problems.append(f"{manifest}: the rewrite changes its declared paths")
            continue
        problems.extend(
            f"{manifest}: {before.key} {before.value!r} would become "
            f"{after.value!r}, but the press would not move what it points at "
            "to match"
            for before, after in zip(declared, rewritten_paths, strict=True)
            if not _declared_path_follows(before, after, manifest, plan, directories)
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


def check_target_keep_names(
    target: Path,
    source: Identity,
    destination: Identity,
    rules: Rules,
    removed: frozenset[str],
    languages: Sequence[str],
) -> KeepCheck:
    """Run the keep-name preflight with this press's real rewrite rows."""

    rows = (
        *_declared_rows(source, destination, rules),
        *_identity_rows(source, destination, rules),
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

    return check_keep_surfaces(
        rewrite_surface_texts(
            target,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
            skip_paths=removed,
        ),
        source,
        rules.keep_names,
        rewritten=rewritten,
        dependency_names=_checked_dependency_names(target, rules, removed),
        cargo_dependency_names=_checked_cargo_dependency_names(
            target, source, removed, languages
        ),
    )


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
