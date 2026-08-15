"""Compile rebrand mechanisms into one immutable substitution table."""

from __future__ import annotations

import fnmatch
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    occurs,
    replace_token,
)
from template_press.rebrand.inventory import (
    SurfaceEntry,
    SurfaceSnapshot,
    VisibilityInput,
    WorktreeKind,
    capture_surface_snapshot,
    select_rename_entries,
    select_symlink_entries,
)
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.pathing import ROOT_CONTROL
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
    SafetyError,
    assert_ancestors_real,
    read_regular_nofollow,
    readlink_nofollow,
)

Surface = Literal["content", "path", "symlink"]
HuntConsumer = Literal["doctor", "reset_stub", "reset_path", "regeneration"]
ScopeCoordinates = Literal["source", "current_or_source"]
ProvenanceKind = Literal["identity", "display_form", "replace_rule"]

RENAME_FIELDS: frozenset[str] = frozenset(
    {"package_name", "repo_name", "app_name", "app_name_upper"}
)


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


def row_matches_scope(row: RenderedSubstitution, posix: str) -> bool:
    """Whether a rendered row's declared scope includes one POSIX path."""

    return _scope_matches(row.scope, posix)


def rewrite_with_row(row: RenderedSubstitution, text: str) -> str:
    """Apply one row's matcher without consulting source configuration."""

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


def hunt_occurs(
    row: RenderedSubstitution,
    policy: HuntPolicy,
    text: str,
) -> bool:
    """Apply one compiled consumer hunt to text."""

    matcher = policy.matcher
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
) -> tuple[tuple[RenderedSubstitution, HuntPolicy], ...]:
    """Return compiled consumer hunts that match one scoped subject."""

    matches: list[tuple[RenderedSubstitution, HuntPolicy]] = []
    for row in table.rows:
        if not row_matches_scope(row, source_scope_path):
            continue
        for policy in row.hunts:
            if (
                policy.consumer == consumer
                and surface in policy.surfaces
                and hunt_occurs(row, policy, text)
            ):
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
    posix: str, path_rows: tuple[RenderedSubstitution, ...]
) -> tuple[str, dict[int, tuple[str, ...]]]:
    rel = Path(posix)
    parts: list[str] = []
    row_ids_by_component: dict[int, list[str]] = {}
    for component_index, component in enumerate(rel.parts):
        if component_index == 0 and component == "press":
            parts.append(component)
            continue
        rewritten = component
        for row in path_rows:
            if not _scope_matches(row.scope, posix):
                continue
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
    rows: tuple[RenderedSubstitution, ...], snapshot: SurfaceSnapshot
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
            rewritten, row_ids_by_component = _rewritten_path(current, path_rows)
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
                current_by_source[source] = f"{step.new_prefix}{suffix}"
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
) -> tuple[tuple[str, WorktreeKind], ...]:
    """Capture and authorize every no-follow node carried by one move."""

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
                raise SafetyError(
                    f"rename prefix {source_prefix!r} would carry uninventoried "
                    f"empty directory {rel!r} — Git cannot restore it"
                )
            return child_count + 1
        entry = indexed.get(rel)
        if entry is None:
            raise SafetyError(
                f"rename prefix {source_prefix!r} would carry {rel!r}, which is "
                f"absent from the authorized surface inventory"
            )
        if kind == "other" or entry.worktree_kind != kind:
            raise SafetyError(
                f"rename prefix closure kind mismatch for {rel!r}: "
                f"inventory={entry.worktree_kind}, worktree={kind}"
            )
        return 1

    walk(root)
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
                closure=_prefix_closure(target, source_prefix, snapshot),
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
        current_closure = _prefix_closure(target, source_prefix, snapshot)
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
) -> str:
    current = posix
    for _ in range(MAX_RENAME_PASSES):
        rewritten, _row_ids = _rewritten_path(current, path_rows)
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
                or _virtual_path_translation(occupied_prefix, path_rows)
                != occupied_prefix
            ):
                continue
        translated = _virtual_path_translation(target_posix, path_rows)
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
                projected = text
                for row in rows:
                    if "content" in row.rewrite_surfaces and row_matches_scope(
                        row, rel
                    ):
                        projected = rewrite_with_row(row, projected)
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
    enabled_display_form: bool = False,
    disabled_display_form: bool = False,
) -> tuple[HuntPolicy, ...]:
    paranoid = MatcherSpec("paranoid", field, matcher.substring)
    hunts: list[HuntPolicy] = []
    if not disabled_display_form:
        doctor_surfaces: set[Surface] = {"content", "symlink"}
        if field in RENAME_FIELDS or enabled_display_form:
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

    values.sort(key=lambda item: -len(item[1]))
    rows: list[RenderedSubstitution] = []
    for field, from_value, to_value, enabled_display, disabled_display in values:
        display = field.startswith("display_name_")
        substring = field in rules.substring_rewrite_fields
        matcher = MatcherSpec("conservative", field, substring)
        rewrite_surfaces: set[Surface] = set()
        if not disabled_display:
            rewrite_surfaces.add("content")
            if field in RENAME_FIELDS:
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
                    enabled_display_form=enabled_display,
                    disabled_display_form=disabled_display,
                ),
                scope=Scope(),
            )
        )
    return rows


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
        if duplicate_index is None:
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
    pipeline_validator(
        tuple(candidates),
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
    rows = _normalize_rows(
        _declared_rows(source, destination, rules),
        _identity_rows(source, destination, rules),
        rules,
    )
    rename_snapshot = SurfaceSnapshot(
        entries=select_rename_entries(
            snapshot,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
        ),
        visibility_inputs=snapshot.visibility_inputs,
    )
    virtual_translations = _compile_virtual_translations(target, rows, snapshot)
    _validate_rows(
        rows,
        destination,
        rules,
        rename_snapshot,
        pipeline_validator,
        tuple(source for _link, source, _destination in virtual_translations),
    )
    rename_plan = _compile_rename_plan(rows, rename_snapshot)
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
    )
