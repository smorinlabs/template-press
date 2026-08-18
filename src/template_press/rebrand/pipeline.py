"""Pure validation for the ordered rebrand substitution pipeline.

The validator knows nothing about repositories or configuration parsing.  Its
inputs are already-rendered source-to-destination candidates plus the target's
initial POSIX relative paths.  This keeps every stability and termination rule
in one place while adapters remain responsible only for preserving provenance,
matcher semantics, surfaces, and scope.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from typing import Literal

from template_press.rebrand.identity import (
    ValidationError,
    occurs,
    replace_token,
)

MatcherKind = Literal["conservative", "literal", "paranoid"]

# Runtime and pre-write validation must use the same termination budget.  The
# runtime loop needs one final no-op call to prove that the rename reached a
# fixpoint, so 31 mutating calls are the largest accepted pipeline.
MAX_RENAME_PASSES = 32


@dataclass(frozen=True)
class MatcherSpec:
    """All inputs that determine whether one candidate matches text."""

    algorithm: MatcherKind
    identity_field: str | None
    substring: bool


@dataclass(frozen=True)
class PipelineCandidate:
    """One rendered rewrite candidate accepted by the stability validator."""

    row_id: str
    from_value: str
    to_value: str
    rewrite_surfaces: frozenset[str]
    matcher: MatcherSpec
    files: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    ambiguity_family: str | None = None


@dataclass(frozen=True)
class StabilitySink:
    """A destination value that no changing candidate may rewrite."""

    sink_id: str
    value: str
    provenance: tuple[str, ...] = ()


def _describe(candidate: PipelineCandidate) -> str:
    provenance = ", ".join(candidate.provenance) or "unknown provenance"
    return f"{candidate.row_id} [{provenance}]"


def _describe_sink(sink: StabilitySink) -> str:
    provenance = ", ".join(sink.provenance) or "unknown provenance"
    return f"{sink.sink_id} [{provenance}]"


def _matches(candidate: PipelineCandidate, text: str) -> bool:
    spec = candidate.matcher
    if spec.algorithm == "literal":
        return candidate.from_value in text
    if spec.identity_field is None:
        raise ValidationError(
            f"candidate {_describe(candidate)} has {spec.algorithm} matcher "
            "without an identity field"
        )
    return occurs(
        text,
        spec.identity_field,
        candidate.from_value,
        frozenset({spec.identity_field}) if spec.substring else frozenset(),
    )


def _replace(candidate: PipelineCandidate, text: str) -> str:
    spec = candidate.matcher
    if spec.algorithm == "literal" or spec.substring:
        return text.replace(candidate.from_value, candidate.to_value)
    if spec.identity_field is None:
        raise ValidationError(
            f"candidate {_describe(candidate)} has {spec.algorithm} matcher "
            "without an identity field"
        )
    return replace_token(
        text, spec.identity_field, candidate.from_value, candidate.to_value
    )


def _is_exact_scope(files: tuple[str, ...]) -> bool:
    return bool(files) and all(
        not any(char in item for char in "*?[") for item in files
    )


def _rewrite_scopes_overlap(left: PipelineCandidate, right: PipelineCandidate) -> bool:
    if not left.files or not right.files:
        return True
    if not (_is_exact_scope(left.files) and _is_exact_scope(right.files)):
        return True
    return not set(left.files).isdisjoint(right.files)


def _scope_matches(candidate: PipelineCandidate, path: str) -> bool:
    return not candidate.files or any(
        fnmatch.fnmatchcase(path, pattern) for pattern in candidate.files
    )


def _shared_surfaces(
    left: PipelineCandidate, right: PipelineCandidate
) -> frozenset[str]:
    return left.rewrite_surfaces & right.rewrite_surfaces


def _normalize(
    candidates: tuple[PipelineCandidate, ...],
) -> tuple[PipelineCandidate, ...]:
    active = tuple(item for item in candidates if item.from_value != item.to_value)
    for item in active:
        if "path" not in item.rewrite_surfaces:
            continue
        if any(separator in item.from_value for separator in ("/", "\\")):
            raise ValidationError(
                f"path component source is structurally unsafe for "
                f"{_describe(item)}: {item.from_value!r}"
            )
        if (
            not item.to_value
            or item.to_value in (".", "..")
            or any(separator in item.to_value for separator in ("/", "\\"))
        ):
            raise ValidationError(
                f"path component destination is structurally unsafe for "
                f"{_describe(item)}: {item.to_value!r}"
            )

    normalized: list[PipelineCandidate] = []
    for item in active:
        display_winner = next(
            (
                prior
                for prior in normalized
                if item.ambiguity_family is not None
                and prior.ambiguity_family == item.ambiguity_family
                and prior.from_value == item.from_value
                and prior.to_value != item.to_value
            ),
            None,
        )
        if display_winner is not None:
            continue
        duplicate_index = next(
            (
                index
                for index, prior in enumerate(normalized)
                if (
                    prior.from_value,
                    prior.to_value,
                    prior.rewrite_surfaces,
                    prior.matcher,
                    prior.files,
                    prior.ambiguity_family,
                )
                == (
                    item.from_value,
                    item.to_value,
                    item.rewrite_surfaces,
                    item.matcher,
                    item.files,
                    item.ambiguity_family,
                )
            ),
            None,
        )
        if duplicate_index is None:
            normalized.append(item)
            continue
        prior = normalized[duplicate_index]
        normalized[duplicate_index] = replace(
            prior,
            provenance=tuple(dict.fromkeys((*prior.provenance, *item.provenance))),
        )
    return tuple(normalized)


def _validate_ambiguity(
    candidates: tuple[PipelineCandidate, ...], *, target_paths_known: bool
) -> None:
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            shared = _shared_surfaces(left, right)
            if (
                not shared
                or left.from_value != right.from_value
                or left.to_value == right.to_value
            ):
                continue
            # Declared rules execute before identity rows.  A scoped literal
            # rule may intentionally consume a source that the later global
            # identity row maps differently; issue #45 permits that stable,
            # deterministic shape.  Same-family ambiguity remains invalid.
            if left.row_id.startswith("replace:") != right.row_id.startswith(
                "replace:"
            ):
                continue
            if shared == frozenset({"content"}) and not _rewrite_scopes_overlap(
                left, right
            ):
                continue
            if "path" in shared and target_paths_known:
                # Exact target paths provide the stronger shared-prefix and
                # reachability proof below.  Defer scoped path candidates so
                # disjoint leaves are not rejected from glob syntax alone.
                if (
                    _is_exact_scope(left.files)
                    and _is_exact_scope(right.files)
                    and set(left.files).isdisjoint(right.files)
                ):
                    continue
            raise ValidationError(
                f"same source {left.from_value!r} has different destinations "
                f"for {_describe(left)} ({left.to_value!r}) and "
                f"{_describe(right)} ({right.to_value!r})"
            )


def _path_graph(
    candidates: tuple[PipelineCandidate, ...], *, target_paths_known: bool
) -> dict[int, set[int]]:
    graph = {index: set() for index in range(len(candidates))}
    for producer_index, producer in enumerate(candidates):
        if "path" not in producer.rewrite_surfaces:
            continue
        for receiver_index, receiver in enumerate(candidates):
            if "path" not in receiver.rewrite_surfaces:
                continue
            if (
                target_paths_known
                and _is_exact_scope(producer.files)
                and _is_exact_scope(receiver.files)
                and set(producer.files).isdisjoint(receiver.files)
            ):
                continue
            if _matches(receiver, producer.to_value):
                graph[producer_index].add(receiver_index)
    return graph


def _find_cycle(graph: dict[int, set[int]]) -> tuple[int, ...] | None:
    visited: set[int] = set()
    stack: list[int] = []
    active: set[int] = set()

    def visit(node: int) -> tuple[int, ...] | None:
        visited.add(node)
        stack.append(node)
        active.add(node)
        for neighbor in graph[node]:
            if neighbor == node:
                continue
            if neighbor not in visited:
                cycle = visit(neighbor)
                if cycle is not None:
                    return cycle
            elif neighbor in active:
                start = stack.index(neighbor)
                return tuple(stack[start:])
        active.remove(node)
        stack.pop()
        return None

    for node in graph:
        if node not in visited:
            cycle = visit(node)
            if cycle is not None:
                return cycle
    return None


def _validate_dependencies(
    candidates: tuple[PipelineCandidate, ...], *, target_paths_known: bool
) -> None:
    """Reject every ordered pair of content rows whose EXECUTION order could
    corrupt one another, for four distinct relationships:

    - a row emitting its own source (stale-source emission, self-pair);
    - an earlier row's rendered TO consumed by a later row (ordered content
      dependency);
    - a later row's rendered TO matching an earlier row's now-stale source
      (stale-source emission, cross-pair);
    - an earlier row's rendered FROM matching INSIDE a later row's rendered
      FROM (issue #44, "nested rendered source"): the earlier row runs
      first and has no notion of the later row's boundaries, so it can
      consume/corrupt the exact text the later row needs intact — e.g. a
      declared `[[replace]]` rule rendering `app_name` runs before every
      identity row, so if `app_name`'s value is a plain substring of
      `package_name`'s value (the ordinary shape of a real Python repo —
      `app_name="demo"`, `package_name="demo_widget"`), the rule's literal
      pass mangles `demo_widget` into `spud_widget` before the
      `package_name` row ever gets a chance to match the intact token. This
      is NOT the TO-vs-FROM relationship the other three checks cover — it
      is FROM-vs-FROM — and previously went undetected: the press exited 0
      with an internally inconsistent target (content mismatched the
      renamed package directory), silently.

    Identity rows are length-sorted (longest FROM first) before this
    validator ever sees them, so identity-vs-identity nesting — a shorter
    identity value being a substring of a longer one, e.g. `app_name` inside
    `package_name` — is already safe by construction and this check stays
    silent for it (a longer FROM can never be found inside a shorter one).
    It fires only when EXECUTION order and LENGTH order disagree, which is
    exactly the declared-rule-before-identity-row shape above. Scoped by
    the same `_rewrite_scopes_overlap` exemption #45 established, so two
    rules provably scoped to disjoint files are not falsely rejected here
    either. Explicitly excludes `producer.from_value == receiver.from_value`
    (a string trivially "contains" itself): two rows sharing the EXACT SAME
    rendered FROM is the SAME-FROM ambiguity/coexistence question, already
    governed by `_validate_ambiguity`'s own #45 carve-out — this guard is
    strictly about a PROPER substring relationship between two DIFFERENT
    FROM values.

    It also excludes the COMPATIBLE nesting shape: when applying the earlier
    row to the later row's rendered FROM already yields exactly the later
    row's rendered TO (`demo -> spud` ahead of `demo_widget ->
    spud_widget`), the earlier pass produces the later row's own intended
    text, so the later row has nothing left to do and the pipeline is
    stable rather than corrupt. Only an INCOMPATIBLE result (`demo_widget`
    becoming `spud_widget` where the later row wanted `potato_launcher`) is
    the silent corruption #44 is about. This mirrors the engine's existing
    treatment of a duplicated substitution pair, which is dropped silently
    when both entries map to the same replacement and raised on only when
    the replacements differ (`_raw_replacement_pairs` in `engine.py`).

    Beyond these content-surface pair relationships, this function also
    owns the PATH-surface dependency proof: after the pair loop it builds
    `_path_graph` and rejects both dependency cycles (`_find_cycle`) and
    any path row whose rendered TO is consumed by another path row.
    """
    for producer_index, producer in enumerate(candidates):
        if "content" not in producer.rewrite_surfaces:
            continue
        if _matches(producer, producer.to_value):
            raise ValidationError(
                f"stale-source emission: {_describe(producer)} emits its own "
                f"source in {producer.to_value!r}; press in two steps via an "
                "intermediate identity"
            )
        for receiver_index, receiver in enumerate(candidates):
            if (
                receiver_index == producer_index
                or "content" not in receiver.rewrite_surfaces
            ):
                continue
            if not _rewrite_scopes_overlap(producer, receiver):
                continue
            if (
                producer_index < receiver_index
                and producer.from_value != receiver.from_value
                and _matches(producer, receiver.from_value)
                and _replace(producer, receiver.from_value) != receiver.to_value
            ):
                raise ValidationError(
                    f"nested rendered source: {_describe(producer)}'s source "
                    f"{producer.from_value!r} matches inside {_describe(receiver)}'s "
                    f"source {receiver.from_value!r}, and {_describe(producer)} runs "
                    f"first — {_describe(receiver)} would never see an intact "
                    "occurrence to rewrite; press in two steps via an intermediate "
                    "identity"
                )
            if producer_index < receiver_index and _matches(
                receiver, producer.to_value
            ):
                raise ValidationError(
                    f"ordered content dependency: {_describe(producer)} emits "
                    f"{producer.to_value!r}, which is consumed by "
                    f"{_describe(receiver)}"
                )
            if producer_index > receiver_index and _matches(
                receiver, producer.to_value
            ):
                raise ValidationError(
                    f"stale-source emission: {_describe(producer)} emits the "
                    f"earlier source of {_describe(receiver)} in "
                    f"{producer.to_value!r}; press in two steps via an "
                    "intermediate identity"
                )

    graph = _path_graph(candidates, target_paths_known=target_paths_known)
    cycle = _find_cycle(graph)
    if cycle is not None:
        details = " -> ".join(_describe(candidates[index]) for index in cycle)
        raise ValidationError(f"path dependency cycle: {details}")
    for producer_index, receivers in graph.items():
        if not receivers:
            continue
        receiver_index = min(receivers)
        raise ValidationError(
            f"path dependency: {_describe(candidates[producer_index])} emits "
            f"{candidates[producer_index].to_value!r}, which is consumed by "
            f"{_describe(candidates[receiver_index])}"
        )


def _validate_symlink_dependencies(
    candidates: tuple[PipelineCandidate, ...],
) -> None:
    """Reject ordered dependencies in relative symlink target text."""

    # Relative symlink targets are a third ordered rewrite surface. Runtime
    # applies paths=true declared rules first, then every non-display identity
    # row to the same link text. Model that order independently from content
    # and pathname-component rewriting so those rows cannot silently consume
    # one another's output. Pathname diagnostics stay first for configurations
    # already refused by the pre-existing path model.
    for producer_index, producer in enumerate(candidates):
        if "symlink" not in producer.rewrite_surfaces:
            continue
        for receiver_index, receiver in enumerate(candidates):
            if (
                receiver_index == producer_index
                or "symlink" not in receiver.rewrite_surfaces
            ):
                continue
            if not _rewrite_scopes_overlap(producer, receiver):
                continue
            # Issue #44's twin, for symlink target text: an earlier row's
            # rendered FROM matching inside a later row's rendered FROM
            # would let the earlier row corrupt the later row's occurrence
            # before it ever gets an intact link-text match to rewrite. See
            # `_validate_dependencies`'s docstring for the full mechanism —
            # the equality exclusion applies here for the identical reason
            # (same-FROM is `_validate_ambiguity`'s question, not this one),
            # and so does the compatible-outcome exclusion (an earlier pass
            # that already yields the later row's own rendered TO leaves
            # correct link text, not corruption).
            if (
                producer_index < receiver_index
                and producer.from_value != receiver.from_value
                and _matches(producer, receiver.from_value)
                and _replace(producer, receiver.from_value) != receiver.to_value
            ):
                raise ValidationError(
                    f"nested rendered source in symlink targets: "
                    f"{_describe(producer)}'s source {producer.from_value!r} "
                    f"matches inside {_describe(receiver)}'s source "
                    f"{receiver.from_value!r}, and {_describe(producer)} runs "
                    f"first — {_describe(receiver)} would never see an intact "
                    "occurrence to rewrite; press in two steps via an "
                    "intermediate identity"
                )
            if producer_index < receiver_index and _matches(
                receiver, producer.to_value
            ):
                raise ValidationError(
                    f"ordered symlink dependency: {_describe(producer)} emits "
                    f"{producer.to_value!r}, which is consumed by "
                    f"{_describe(receiver)}"
                )
            if producer_index > receiver_index and _matches(
                receiver, producer.to_value
            ):
                raise ValidationError(
                    f"stale-source emission in symlink targets: "
                    f"{_describe(producer)} emits the earlier source of "
                    f"{_describe(receiver)} in {producer.to_value!r}; press "
                    "in two steps via an intermediate identity"
                )


def _validate_stability_sinks(
    candidates: tuple[PipelineCandidate, ...], sinks: tuple[StabilitySink, ...]
) -> None:
    """Preserve destination fields that are not themselves rewrite rows."""

    for candidate in candidates:
        if not candidate.row_id.startswith("identity:"):
            continue
        for sink in sinks:
            if _matches(candidate, sink.value):
                raise ValidationError(
                    f"destination stability conflict: {_describe(candidate)} "
                    f"would rewrite {_describe_sink(sink)} value {sink.value!r}; "
                    "press in two steps via an intermediate identity"
                )


def _validate_target_paths(
    candidates: tuple[PipelineCandidate, ...],
    initial_paths: tuple[str, ...],
    initial_symlink_paths: frozenset[str],
) -> None:
    path_rows = tuple(item for item in candidates if "path" in item.rewrite_surfaces)
    if not path_rows:
        return
    assignments: dict[str, tuple[str, PipelineCandidate]] = {}
    current_by_initial = {initial: initial for initial in initial_paths}
    initially_active = {
        initial: {row.row_id for row in path_rows if _scope_matches(row, initial)}
        for initial in initial_paths
    }
    movers_by_initial: dict[str, list[PipelineCandidate]] = {
        initial: [] for initial in initial_paths
    }
    seen_states = {tuple(sorted(current_by_initial.values()))}

    for _pass_index in range(MAX_RENAME_PASSES):
        pass_moves: dict[str, tuple[str, list[PipelineCandidate]]] = {}
        pass_destinations: dict[str, tuple[str, PipelineCandidate]] = {}
        deferred_by_initial: dict[str, list[PipelineCandidate]] = {}

        for initial, current in sorted(
            current_by_initial.items(), key=lambda item: item[1]
        ):
            active_rows = tuple(
                row for row in path_rows if _scope_matches(row, current)
            )
            original_parts = current.split("/")
            parts = list(original_parts)
            change_rows: dict[int, list[PipelineCandidate]] = {}
            for row in active_rows:
                for component_index, component in enumerate(parts):
                    # The engine protects the literal root control directory
                    # while still renaming identity-bearing descendants.
                    if component_index == 0 and component == "press":
                        continue
                    rewritten = _replace(row, component)
                    if rewritten == component:
                        continue
                    change_rows.setdefault(component_index, []).append(row)
                    parts[component_index] = rewritten

            changing_rows: list[PipelineCandidate] = []
            for rows in change_rows.values():
                for row in rows:
                    if all(item.row_id != row.row_id for item in changing_rows):
                        changing_rows.append(row)
            for row in changing_rows:
                if row.row_id in initially_active[initial]:
                    continue
                moved_by = ", ".join(
                    _describe(item) for item in movers_by_initial[initial]
                )
                raise ValidationError(
                    f"path dependency: {moved_by} moves {initial!r} "
                    f"into the scope of {_describe(row)}"
                )

            differing = [
                index
                for index, (before, after) in enumerate(
                    zip(original_parts, parts, strict=True)
                )
                if before != after
            ]
            if not differing:
                continue
            shallowest = min(differing)
            source_prefix = "/".join(original_parts[: shallowest + 1])
            destination_prefix = "/".join(
                (*original_parts[:shallowest], parts[shallowest])
            )
            applied_rows = change_rows[shallowest]

            prior_source = pass_destinations.get(destination_prefix)
            if prior_source is not None and prior_source[0] != source_prefix:
                other_source, other_candidate = prior_source
                raise ValidationError(
                    f"converging path prefixes {other_source!r} from "
                    f"{_describe(other_candidate)} and {source_prefix!r} from "
                    f"{_describe(applied_rows[0])} both target "
                    f"{destination_prefix!r} in one rename pass"
                )
            pass_destinations[destination_prefix] = (
                source_prefix,
                applied_rows[0],
            )

            prior_assignment = assignments.get(source_prefix)
            if (
                prior_assignment is not None
                and prior_assignment[0] != destination_prefix
            ):
                prior_destination, prior_candidate = prior_assignment
                raise ValidationError(
                    f"shared prefix {source_prefix!r} has conflicting "
                    f"destinations {prior_destination!r} from "
                    f"{_describe(prior_candidate)} and "
                    f"{destination_prefix!r} from {_describe(applied_rows[0])}"
                )
            assignments[source_prefix] = (destination_prefix, applied_rows[0])

            prior_move = pass_moves.get(source_prefix)
            if prior_move is not None and prior_move[0] != destination_prefix:
                prior_destination, prior_rows = prior_move
                raise ValidationError(
                    f"shared prefix {source_prefix!r} has conflicting "
                    f"destinations {prior_destination!r} from "
                    f"{_describe(prior_rows[0])} and {destination_prefix!r} "
                    f"from {_describe(applied_rows[0])}"
                )
            if prior_move is None:
                pass_moves[source_prefix] = (destination_prefix, list(applied_rows))
            else:
                for row in applied_rows:
                    if all(item.row_id != row.row_id for item in prior_move[1]):
                        prior_move[1].append(row)

            deferred_by_initial[initial] = [
                row
                for component_index in differing
                if component_index != shallowest
                for row in change_rows[component_index]
            ]

        if not pass_moves:
            return

        for source_prefix in sorted(
            pass_moves, key=lambda value: -len(value.split("/"))
        ):
            destination_prefix, move_rows = pass_moves[source_prefix]
            for initial, current in current_by_initial.items():
                if current != source_prefix and not current.startswith(
                    f"{source_prefix}/"
                ):
                    continue
                suffix = current[len(source_prefix) :]
                current_by_initial[initial] = f"{destination_prefix}{suffix}"
                for row in move_rows:
                    if all(
                        item.row_id != row.row_id for item in movers_by_initial[initial]
                    ):
                        movers_by_initial[initial].append(row)

        destination_initial_by_path: dict[str, str] = {}
        for initial, current in current_by_initial.items():
            prior_initial = destination_initial_by_path.setdefault(current, initial)
            if prior_initial != initial:
                stationary_symlink = (
                    prior_initial == current and prior_initial in initial_symlink_paths
                ) or (initial == current and initial in initial_symlink_paths)
                if stationary_symlink:
                    continue
                raise ValidationError(
                    f"converging target paths {prior_initial!r} and "
                    f"{initial!r} both target {current!r}"
                )

        for initial, deferred_rows in deferred_by_initial.items():
            current = current_by_initial[initial]
            for deferred in deferred_rows:
                if _scope_matches(deferred, current):
                    continue
                moved_by = ", ".join(
                    _describe(item) for item in movers_by_initial[initial]
                )
                raise ValidationError(
                    f"path dependency: {moved_by} moves {initial!r} out of "
                    f"the scope of {_describe(deferred)} before its deeper "
                    "rename can run"
                )

        state = tuple(sorted(current_by_initial.values()))
        if state in seen_states:
            raise ValidationError(
                "path dependency cycle for complete target path state: "
                + ", ".join(_describe(item) for item in path_rows)
            )
        seen_states.add(state)
    raise ValidationError(
        "path dependency did not terminate for complete target path state: "
        + ", ".join(_describe(item) for item in path_rows)
    )


def validate_pipeline(
    candidates: tuple[PipelineCandidate, ...],
    *,
    initial_paths: tuple[str, ...] | None = None,
    initial_symlink_paths: frozenset[str] = frozenset(),
    stability_sinks: tuple[StabilitySink, ...] = (),
) -> tuple[PipelineCandidate, ...]:
    """Normalize candidates and reject every unstable ordered pipeline.

    ``None`` means no target-path evidence is available, so path-scope
    relationships fail closed. An explicit tuple, including an empty tuple,
    is an authoritative target inventory and enables target-aware proofs.
    ``initial_symlink_paths`` identifies occupied symlink destinations that
    the runtime deliberately preserves by skipping the corresponding move.
    """

    normalized = _normalize(candidates)
    target_paths_known = initial_paths is not None
    target_paths = initial_paths or ()
    _validate_ambiguity(normalized, target_paths_known=target_paths_known)
    _validate_dependencies(normalized, target_paths_known=target_paths_known)
    _validate_stability_sinks(normalized, stability_sinks)
    _validate_target_paths(normalized, target_paths, initial_symlink_paths)
    _validate_symlink_dependencies(normalized)
    return normalized
