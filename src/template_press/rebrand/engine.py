"""Rebrand engine: enumerate, plan, and apply identity rewrites on a target.

Scan-based (ARCH-03): no per-target file lists. Every tracked text file is a
replace candidate; every path component containing an identity token is a
rename candidate. Failure mode: any op raising propagates — git in the
TARGET is the undo button (`git checkout . && git clean -fd`).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    replace_token,
)
from template_press.rebrand.inventory import (
    SurfaceEntry,
    SurfaceSnapshot,
    WorktreeKind,
    capture_surface_snapshot,
    gitlink_path_strings,
    listed_paths,
    select_content_rewrite_entries,
    select_copy_entries,
    select_rename_entries,
    select_verifier_entries,
    tracked_path_strings,
)
from template_press.rebrand.pathing import (
    REGENERATE_EXEMPTIBLE as REGENERATE_EXEMPTIBLE,
)
from template_press.rebrand.pathing import (
    ROOT_CONTROL,
    exempt_regenerated_paths,
    symlink_target_posix,
    translate_path,
)
from template_press.rebrand.pathing import (
    is_root_press as _is_root_press,
)
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
    rule_matches_path,
)
from template_press.rebrand.safety import (
    AtomicRenameUnavailableError,
    ContainmentError,
    NonRegularFileError,
    SafeRelPath,
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    chmod_nofollow,
    read_regular_nofollow,
    readlink_nofollow,
    rename_noreplace,
    rename_noreplace_best_effort,
    require_rename_noreplace_host_support,
    require_rename_noreplace_support,
    safe_write,
)
from template_press.rebrand.substitutions import (
    RenamePlan,
    SubstitutionTable,
    compile_substitution_table,
    declared_rule_triples,
    revalidate_substitution_table,
    rewrite_with_row,
    row_matches_scope,
)

RENAME_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "app_name_upper",
)

# Marker files that identify a press/ directory as THIS tool's control dir
# (one legitimately carries SOURCE identity). These feed ONLY the
# `stray_press_dirs` warning (via `_control_press_dirs`) — they do NOT drive the
# rewrite/scan exemption. The exact-artifact exemption is `ROOT_CONTROL` below
# (Decision D3): only the literal root-level control files are exempt from
# iteration, never a whole press/ subtree keyed on these markers.
CONTROL_MARKERS: tuple[str, ...] = (
    "press-source.toml",
    "press-rules.toml",
    "press-receipt.toml",
)


@dataclass(frozen=True)
class PathEntry:
    """A ``copy_paths``/``scan_paths`` entry: a relative path plus its kind.

    ``kind`` is ``"file" | "symlink" | "gitlink" | "unscannable"``,
    determined without following links.
    """

    rel: Path
    kind: str


@dataclass
class PlanItem:
    kind: str  # "replace" | "rename"
    path: str
    detail: str

    def render(self) -> str:
        return f"  [{self.kind:<7}] {self.path}  —  {self.detail}"


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    # The shallowest-prefix rename map (source → destination POSIX rel
    # paths) this plan implies — structured data for plan-time consumers
    # (stale-argv membership, reset-path translation), so nothing parses it
    # back out of rendered PlanItem strings.
    renames: dict[str, str] = field(default_factory=dict)
    rendered_rules: list[tuple[ReplaceRule, str, str]] = field(default_factory=list)
    table: SubstitutionTable | None = None
    # Plan-time, non-fatal E5(a) advisories (declared-removal coverage) —
    # populated by build_plan from the SAME snapshot the plan itself was
    # built from, so the printed plan and the warnings can never disagree.
    removal_warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.items:
            return "(plan is empty — nothing to do)"
        return "\n".join(["Plan:", *(i.render() for i in self.items)])

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"replace": 0, "rename": 0}
        for i in self.items:
            out[i.kind] = out.get(i.kind, 0) + 1
        return out


@dataclass(frozen=True)
class RenamePreflight:
    """Result of checking the planned rename filesystems."""

    checked_devices: frozenset[int] = frozenset()
    unsafe_devices: frozenset[int] = frozenset()
    problems: tuple[str, ...] = ()
    operational: bool = True

    @property
    def atomic(self) -> bool:
        """Whether every planned rename filesystem passed the probe."""

        return not self.unsafe_devices


def _is_excluded(rel: Path, rules: Rules) -> bool:
    if rel.as_posix() in rules.exclude_files:
        return True
    return any(part in rules.exclude_dirs for part in rel.parts)


def _git_listed(target: Path) -> list[Path]:
    """Compatibility adapter over the one raw surface inventory."""

    return list(listed_paths(capture_surface_snapshot(target)))


def _press_dirs(files: list[Path]) -> set[str]:
    """POSIX paths of every directory component literally named 'press'."""
    dirs: set[str] = set()
    for rel in files:
        parts = rel.parts
        for i in range(len(parts) - 1):  # directory components only
            if parts[i] == "press":
                dirs.add(Path(*parts[: i + 1]).as_posix())
    return dirs


def _control_press_dirs(target: Path, files: list[Path]) -> frozenset[str]:
    """press/ dirs that ARE this tool's control dir (hold a CONTROL_MARKER).

    Content-keyed, not name- or depth-keyed: a press/ directory is exempt
    only when it carries a control file that legitimately holds SOURCE
    identity. Every other press/ dir is ordinary target content.
    """
    return frozenset(
        d
        for d in _press_dirs(files)
        if any((target / d / m).is_file() for m in CONTROL_MARKERS)
    )


def stray_press_dirs(target: Path) -> list[str]:
    """press/ dirs that are NOT the control dir (no control marker).

    They are treated as ordinary content — rewritten AND leak-scanned — so
    surviving source tokens under them cannot yield a false 'verified'. The
    CLI warns about them so a human can confirm the rewrite was intended.
    """
    files = _git_listed(target)
    return sorted(_press_dirs(files) - _control_press_dirs(target, files))


def _content_candidate_entries(target: Path, rules: Rules) -> tuple[SurfaceEntry, ...]:
    """Snapshot-backed regular-file and symlink rewrite candidates."""

    snapshot = capture_surface_snapshot(target)
    entries = select_content_rewrite_entries(
        snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    # Preserve the compatibility adapter's observable symlink skip reporting
    # without recovering membership through ``Path.is_file()``, which would
    # follow the link or one of its ancestors. All symlink leaves are safe for
    # ``_read_text``: it refuses them before reading bytes.
    symlinks = tuple(
        entry
        for entry in select_rename_entries(
            snapshot,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
        )
        if entry.worktree_kind == "symlink"
    )
    return tuple(sorted((*entries, *symlinks), key=lambda item: item.rel.as_posix()))


def iter_target_files(target: Path, rules: Rules) -> list[Path]:
    """All non-excluded tracked+untracked files under target, sorted.

    Excludes rules.exclude_files / exclude_dirs and the exact root control
    artifacts in ROOT_CONTROL. Everything else under a press/ dir — root or
    nested — is ordinary content: scanned and rewritten like any file.
    """
    return [target / entry.rel for entry in _content_candidate_entries(target, rules)]


def _gitlink_rels(target: Path) -> frozenset[str]:
    """Compatibility adapter for gitlink index paths."""

    return gitlink_path_strings(capture_surface_snapshot(target))


def _validate_rewrite_snapshot(
    target: Path,
    snapshot: SurfaceSnapshot,
    rules: Rules,
) -> None:
    """Refuse selected entries that the rewrite and doctor cannot inspect."""

    for entry in snapshot.entries:
        if entry.rel.as_posix() in ROOT_CONTROL or _is_excluded(entry.rel, rules):
            continue
        unscannable = entry.worktree_kind == "other" or (
            entry.worktree_kind == "directory" and entry.index_kind != "gitlink"
        )
        if not unscannable:
            continue
        if entry.worktree_kind == "other" and entry.index_kind != "gitlink":
            assert_ancestors_real(target / entry.rel, target)
        raise SafetyError(
            f"unscannable worktree entry must be resolved before rebrand: "
            f"{entry.rel.as_posix()} ({entry.worktree_kind})"
        )


def _rename_candidate_entries(target: Path, rules: Rules) -> tuple[SurfaceEntry, ...]:
    """Snapshot-backed rename candidates, with their expected leaf kinds.

    Mirrors ``iter_target_files``'s exclusion filtering (``_is_excluded`` +
    ``ROOT_CONTROL``), but enumerates by no-follow ``is_symlink()`` in
    addition to ``is_file()`` (Fix F2) — retarget rewrites a symlink's TEXT
    only, so a directory or dangling symlink whose NAME carries an identity
    token still needs its own name renamed. ``is_file()`` alone FOLLOWS the
    link: it reads True for a symlink-to-file (already covered), but False
    for a symlink-to-dir or a dangling symlink, which then silently drops
    out of both the rename pass and ``build_plan``'s rename-planning loop —
    the link's stale NAME survives the press and the doctor's dangling-
    symlink path scan flags it forever. A gitlink (submodule pointer) is
    excluded outright: a submodule mount point must never be renamed by
    this pass.
    """
    snapshot = capture_surface_snapshot(target)
    # Refuse any selected, present node that the later doctor cannot scan.
    # A tracked file replaced by a directory and any FIFO/socket/other leaf
    # would otherwise be omitted from this plan, allow unrelated writes, and
    # then make the post-mutation doctor fail.  A normal checked-out gitlink
    # directory remains opaque; an untracked embedded repository is a
    # directory record and must be refused because the doctor cannot verify it.
    _validate_rewrite_snapshot(target, snapshot, rules)
    entries = select_rename_entries(
        snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    return entries


def _rename_candidates(target: Path, rules: Rules) -> list[Path]:
    """Rename-pass candidate paths; compatibility view over raw entries."""

    return [target / entry.rel for entry in _rename_candidate_entries(target, rules)]


def copy_paths(target: Path) -> list[PathEntry]:
    """Present Git-listed nodes plus opaque gitlink placeholders.

    RETAINS symlinks and gitlinks — never filters on ``is_file()``, which
    would drop a symlink-to-dir/dangling symlink and hide gitlinks. ``kind``
    is determined without following links: a gitlink is detected via the
    index mode (``_gitlink_rels``); otherwise an ``lstat``-based
    snapshot kind decides ``file``/``symlink``/``gitlink``/``unscannable``.
    Sorted, deterministic. The sandbox refuses ``unscannable`` rather than
    silently certifying an incomplete copy.
    """
    entries: list[PathEntry] = []
    snapshot = capture_surface_snapshot(target)
    for entry in select_copy_entries(snapshot):
        rel = entry.rel
        if ".git" in rel.parts:
            continue
        if entry.worktree_kind == "symlink":
            kind = "symlink"
        elif entry.worktree_kind == "file":
            kind = "file"
        elif entry.index_kind == "gitlink" and entry.worktree_kind in (
            "directory",
            "missing",
        ):
            kind = "gitlink"
        else:
            kind = "unscannable"
        entries.append(PathEntry(rel, kind))
    return sorted(entries, key=lambda e: e.rel.as_posix())


def rewrite_paths(target: Path, rules: Rules) -> list[Path]:
    """Files eligible for content/path rewrite — a thin named wrapper.

    ``iter_target_files`` already excludes lockfiles (``exclude_files``),
    ``exclude_dirs``, and ``ROOT_CONTROL`` (Task 2); kept symmetric with
    ``copy_paths``/``scan_paths`` rather than reimplemented.
    """
    return iter_target_files(target, rules)


def scan_paths(
    target: Path,
    rules: Rules,
    renamed: Mapping[str, str] | Collection[tuple[str, str]] = (),
) -> list[PathEntry]:
    """``copy_paths`` minus ``ROOT_CONTROL``, regenerable lockfiles, and
    ``verify_ignore`` dirs — the no-leak scan's candidate set.

    A lockfile is scan-exempt only when it is regenerated FRESH after apply,
    which requires it to be in BOTH:

    - the TARGET's effective ``rules.regenerate`` declarations — press
      actually regenerates it for THIS target (no declaration → no rebuild →
      a stale token must be scanned; keying on a tool-side list ALONE would
      FALSE-CLEAN it); AND
    - the tool's OWN ``REGENERATE_EXEMPTIBLE`` constant — the explicit cap on
      what a target can exempt (EMP-01/F5: a target's ``press-rules.toml``
      must not be able to hide arbitrary content from the scan by declaring a
      regeneration for it). Deliberately its own constant, never derived
      from ``exclude_files`` — that would wrongly exempt ``CHANGELOG.md``-
      class artifacts (P04 D3).

    Everything else stays: non-exemptible lockfiles (``package-lock.json``),
    a force-added gitignored file, and symlink/gitlink entries (type-tagged,
    for Task 7).

    ``renamed`` (the press's rename map/report) translates declared
    source-coordinate outputs to their post-rename locations before the
    exact-path comparison — basename alone matches a nested
    ``packages/demo_widget/bun.lock``, but the path half would fail forever
    without the translation (P04 D3).
    """
    exempt_lockfiles = {p for p, _ in exempt_regenerated_paths(rules, renamed)}
    snapshot = capture_surface_snapshot(target)
    selected = select_verifier_entries(
        snapshot,
        verify_ignore=rules.verify_ignore,
        root_control=ROOT_CONTROL,
        exempt_paths=frozenset(exempt_lockfiles),
    )
    out: list[PathEntry] = []
    for entry in selected:
        if entry.worktree_kind == "symlink":
            kind = "symlink"
        elif entry.worktree_kind == "file":
            kind = "file"
        elif entry.index_kind == "gitlink" and entry.worktree_kind in (
            "directory",
            "missing",
        ):
            kind = "gitlink"
        else:
            kind = "unscannable"
        out.append(PathEntry(entry.rel, kind))
    return out


def _raw_replacement_pairs(
    source: Identity,
    dest: Identity,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[tuple[str, str, str]]:
    """(field, current, replacement) triples, longest current first.

    display_name is expanded into one pair per enabled exact form
    (display_name_spaced/…_pascal/…_camel) — generic-boundary tags, never in
    RENAME_FIELDS, so display forms rewrite content but never paths. The
    `k in dst` guard keeps a half-specified display name (source has it,
    dest doesn't) out of the pair list entirely — the CLI gates that case.

    Two entries can legitimately share the same `cur` literal (e.g. a
    one-word display_name equal to app_name's value) — harmless as long as
    both map to the SAME `repl`, in which case the duplicate is dropped
    silently. When they map to DIFFERENT `repl` values the occurrence is
    genuinely ambiguous — the engine cannot know which identity it
    represents, and applying one while starving the other (stable sort order
    picking a "winner") would corrupt the press — so this raises instead.

    WITHIN the display-form family alone, that same-`cur`-different-`repl`
    shape is NOT an ambiguity: a one-word display name renders identically
    across forms (source "NumPy": spaced == pascal == "NumPy") while the
    destination is multi-word ("Acme Widget" vs "AcmeWidget") — one source
    literal, one field, just two forms that happen to collapse to the same
    text. Raising here would reject the DEFAULT configuration for any
    one-word display name. So these are coalesced first, deterministically:
    keep the FIRST pair per `display_form_names` order (spaced first by
    default — the verbatim display name wins) and drop the rest silently.
    This coalescing is scoped to the display_name_* family ONLY — a `cur`
    shared between a display form and a DIFFERENT field (e.g. app_name) is
    still routed to the ambiguity guard below.
    """
    src, dst = source.as_dict(), dest.as_dict()
    pairs = [
        (k, src[k], dst[k])
        for k in src
        if k != "display_name" and k in dst and src[k] != dst[k]
    ]
    if "display_name" in src and "display_name" in dst:
        sf = display_forms(src["display_name"])
        df = display_forms(dst["display_name"])
        for form in display_form_names:
            if sf[form] != df[form]:
                pairs.append((f"display_name_{form}", sf[form], df[form]))
    display_seen: set[str] = set()
    coalesced: list[tuple[str, str, str]] = []
    for tag, cur, repl in pairs:
        if tag.startswith("display_name_"):
            if cur in display_seen:
                continue  # same-family duplicate — drop, keep the first form
            display_seen.add(cur)
        coalesced.append((tag, cur, repl))
    pairs = coalesced

    deduped: list[tuple[str, str, str]] = []
    seen: dict[str, tuple[str, str]] = {}  # cur -> (tag, repl)
    for tag, cur, repl in pairs:
        if cur in seen:
            _other_tag, other_repl = seen[cur]
            if other_repl == repl:
                # Keep the declaration until the shared-validator adapter can
                # merge its field provenance onto the first executable row.
                deduped.append((tag, cur, repl))
                continue
            # Preserve the ambiguity for the one shared validator.  Keeping
            # both candidates is what lets it report both field provenances.
            deduped.append((tag, cur, repl))
            continue
        seen[cur] = (tag, repl)
        deduped.append((tag, cur, repl))
    deduped.sort(key=lambda t: -len(t[1]))
    return deduped


def _rendered_replace_declarations(
    rules: Rules, source: Identity, dest: Identity
) -> list[tuple[int, ReplaceRule, str, str]]:
    """(rule, FROM, TO) with both sides rendered; identical sides dropped.

    Rendering raises ValidationError when a pattern references a field this
    identity pair doesn't declare (optional display_name) — surfacing at
    plan time, before any write.

    A ``paths = true`` rule whose rendered FROM or TO contains a path
    separator (``/`` or ``\\`` — either can split a component on the
    platforms this tool targets) also raises: the FROM side can never match
    a single path COMPONENT (the unit `_renamed_rel` operates on), and a TO
    side that splits into nested parts corrupts the component-wise rename
    (the strict ``zip`` in the rename-collapse loop crashes or silently
    mis-renames). Content-only rules are NOT restricted — a content pattern
    like ``{owner}/{repo_name}`` is legitimate prose.

    A ``paths = true`` rule whose rendered TO still CONTAINS its rendered
    FROM (Fix F2a) also raises: a rename pass applies the rule via plain
    ``str.replace`` (no boundary guard), so the rule's own output re-matches
    on the very next pass (pattern ``"{app_name}x"`` with app_name ``a`` ->
    ``ax``: FROM ``"ax"`` is a substring of TO ``"axx"``, so ``a.txt`` ->
    ``ax.txt`` -> ``axx.txt`` -> ... never converges). Caught here at plan
    time through the shared validator, before any mutation.

    A rule's rendered TO is checked for STABILITY against later rows by the
    shared pipeline validator: ``[[replace]]`` rules run BEFORE the token pass
    (``_apply_replacements``/``_renamed_rel``), so a rule's rendered output
    is itself subject to that later pass. The check inspects the FULL
    rendered TO — not just its static (non-placeholder) segments — because a
    CHANGING field's SOURCE value can appear at the SEAM between static text
    and a DIFFERENT placeholder's rendered value: pattern
    ``"f{repo_name}_Owned"`` with repo_name rendering to ``"oo"`` composes TO
    ``"foo_Owned"``, which boundary-matches the CHANGING app_name value
    ``"foo"`` even though neither static segment (``"f"``, ``"_Owned"``)
    contains it alone. The token pass would then re-rewrite that composed
    occurrence right back out from under the rule, silently corrupting the
    output. Checked against every field's SOURCE value using that field's
    own matcher (boundary ``token_occurs``, or plain containment for a field
    in ``substring_rewrite_fields``) via the shared ``identity.occurs``
    dispatch — the same dispatch the doctor's leak scan uses.

    This eliminates every mutation of a rendered TO that lies wholly WITHIN
    the TO. A match that STRADDLES the boundary between surrounding file
    content and the inserted TO (e.g. context ``"x"`` + TO ``"bar_data"``
    forming ``"xbar"``, which matches a changed ``package_name`` ``"xbar"``
    -> ``"qq"``) is content-dependent and not checkable at plan time — a
    known, documented limitation (see
    docs/design/0008-identity-variants-and-replace-rules.md), not a claim of
    impossibility.

    Two DISTINCT rules can render the SAME FROM with DIFFERENT TOs (e.g.
    ``"{app_name}"`` and ``"f{package_name}"`` both rendering FROM
    ``"foo"``); every rewrite pass applies rules in order via plain
    ``str.replace``, so the FIRST one silently wins and the second never
    applies. This raises when that happens AND the two rules' surfaces
    overlap (both act on content, or both act on paths) — rules on DISJOINT
    surfaces (content-only vs paths-only) provably never contend, so
    rejecting those would be a false rejection.

    Exact duplicates are deduped first, keyed on the WHOLE ``ReplaceRule``
    — never on ``(FROM, TO)`` alone: the rendered triples drive
    ``_apply_replacements``, ``_renamed_rel``, AND the doctor/verifier
    rule-literal scans, so two rules that render identically but differ in
    ``files``/``paths``/``content`` are NOT redundant — a ``(FROM, TO)``-
    keyed dedupe would silently drop the second rule's SCOPE from both the
    rewrite and the scan (a missed rewrite plus a false-clean receipt).
    """
    out: list[tuple[int, ReplaceRule, str, str]] = []
    for declaration_index, rule in enumerate(rules.replace, start=1):
        frm = render_replace_pattern(rule.pattern, source)
        to = render_replace_pattern(rule.pattern, dest)
        if frm == to:
            continue
        out.append((declaration_index, rule, frm, to))
    return out


def _pipeline_inputs(
    source: Identity,
    dest: Identity,
    rules: Rules,
) -> tuple[
    tuple[PipelineCandidate, ...],
    dict[str, tuple[str, str, str]],
    dict[str, tuple[ReplaceRule, str, str]],
]:
    """Adapt current identity/rule tuples to the pure validator contract."""

    pair_by_id: dict[str, tuple[str, str, str]] = {}
    rule_by_id: dict[str, tuple[ReplaceRule, str, str]] = {}
    candidates: list[PipelineCandidate] = []

    rendered = _rendered_replace_declarations(rules, source, dest)
    for declaration_index, rule, frm, to in rendered:
        row_id = f"replace:{declaration_index}"
        rule_by_id[row_id] = (rule, frm, to)
        surfaces = frozenset(
            surface
            for surface, enabled in (
                ("content", rule.content),
                ("path", rule.paths),
                ("symlink", rule.paths),
            )
            if enabled
        )
        candidates.append(
            PipelineCandidate(
                row_id=row_id,
                from_value=frm,
                to_value=to,
                rewrite_surfaces=surfaces,
                matcher=MatcherSpec("literal", None, False),
                files=tuple(rule.files),
                provenance=(
                    f"replace[{declaration_index}] pattern={rule.pattern!r} "
                    f"reason={rule.reason!r}",
                ),
            )
        )

    raw_pairs = _raw_replacement_pairs(source, dest, rules.display_forms)
    provenance_by_values: dict[tuple[str, str], list[str]] = {}
    for tag, cur, repl in raw_pairs:
        provenance_by_values.setdefault((cur, repl), []).append(f"identity:{tag}")
    for index, pair in enumerate(raw_pairs, start=1):
        tag, cur, repl = pair
        row_id = f"identity:{index}:{tag}"
        pair_by_id[row_id] = pair
        identity_surfaces = {"content"}
        if tag in RENAME_FIELDS:
            identity_surfaces.add("path")
        if not tag.startswith("display_name_"):
            identity_surfaces.add("symlink")
        candidates.append(
            PipelineCandidate(
                row_id=row_id,
                from_value=cur,
                to_value=repl,
                rewrite_surfaces=frozenset(identity_surfaces),
                matcher=MatcherSpec(
                    "conservative", tag, tag in rules.substring_rewrite_fields
                ),
                provenance=tuple(provenance_by_values[(cur, repl)]),
                ambiguity_family=(
                    "display_name" if tag.startswith("display_name_") else None
                ),
            )
        )
    return tuple(candidates), pair_by_id, rule_by_id


def _validated_replacements(
    source: Identity,
    dest: Identity,
    rules: Rules,
    *,
    initial_paths: tuple[str, ...] | None = None,
    initial_symlink_paths: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, str, str]], list[tuple[ReplaceRule, str, str]]]:
    candidates, pair_by_id, rule_by_id = _pipeline_inputs(source, dest, rules)
    destination_values = dest.as_dict()
    if dest.display_name is not None:
        destination_values.pop("display_name")
        rendered_display_forms = display_forms(dest.display_name)
        destination_values.update(
            {
                f"display_name_{form}": rendered_display_forms[form]
                for form in rules.display_forms
            }
        )
    stability_sinks = tuple(
        StabilitySink(
            sink_id=f"destination:{field}",
            value=value,
            provenance=(f"destination identity field:{field}",),
        )
        for field, value in destination_values.items()
    )
    normalized = validate_pipeline(
        candidates,
        initial_paths=initial_paths,
        initial_symlink_paths=initial_symlink_paths,
        stability_sinks=stability_sinks,
    )
    pairs = [
        pair_by_id[item.row_id] for item in normalized if item.row_id in pair_by_id
    ]
    rendered = [
        rule_by_id[item.row_id] for item in normalized if item.row_id in rule_by_id
    ]
    return pairs, rendered


def replacement_pairs(
    source: Identity,
    dest: Identity,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[tuple[str, str, str]]:
    """Return normalized identity triples after shared pipeline validation."""

    # The compatibility API has no declared rules or target paths.  Construct
    # a rules view that changes only the enabled display forms.
    from template_press.rebrand.rules import DEFAULT_RULES

    rules = Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        replace=(),
        regenerate=(),
        reset=(),
        substring_rewrite_fields=frozenset(),
        display_forms=display_form_names,
        verify_ignore=frozenset(),
    )
    pairs, _rendered = _validated_replacements(source, dest, rules)
    # Preserve the compatibility API's historical one-row representation for
    # equal executable values. Internal build/apply paths consume
    # _validated_replacements directly and retain semantically distinct rows.
    deduped: list[tuple[str, str, str]] = []
    seen_values: set[tuple[str, str]] = set()
    for pair in pairs:
        values = pair[1:]
        if values in seen_values:
            continue
        seen_values.add(values)
        deduped.append(pair)
    return deduped


def rendered_replace_rules(
    rules: Rules, source: Identity, dest: Identity
) -> list[tuple[ReplaceRule, str, str]]:
    """Return normalized declared-rule triples after shared validation."""

    _pairs, rendered = _validated_replacements(source, dest, rules)
    return rendered


def _read_text(path: Path, *, expected_kind: WorktreeKind | None = None) -> str | None:
    if expected_kind == "symlink":
        # A stable selected symlink remains a non-content candidate. If the
        # pathname changed to any other kind, the no-follow readlink refuses.
        readlink_nofollow(path)
        return None
    try:
        return read_regular_nofollow(path).decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary — never a rewrite candidate
    except OSError as exc:
        if expected_kind == "file":
            raise SafetyError(
                f"selected regular file changed before read: {path}"
            ) from exc
        return None  # compatibility path for an unclassified unreadable leaf
    except NonRegularFileError as exc:
        if expected_kind == "file":
            raise SafetyError(
                f"selected regular file changed before read: {path}"
            ) from exc
        # The checked-path fallback reports an initially non-regular leaf with
        # this dedicated exception, whereas POSIX O_NOFOLLOW reports a symlink
        # as an OSError above. Preserve the cross-platform skip contract only
        # after a second no-follow operation proves that the leaf is still a
        # symlink. Every change-detection safety refusal remains fail-closed.
        readlink_nofollow(path)
        return None


def _renamed_rel(
    rel: Path,
    pairs: list[tuple[str, str, str]],
    rendered: list[tuple[ReplaceRule, str, str]] | None = None,
    substring_fields: Collection[str] = frozenset(),
) -> Path:
    rendered = rendered or []
    posix = rel.as_posix()
    parts = []
    for i, component in enumerate(rel.parts):
        if _is_root_press(rel, i):
            # The protected root control dir literally 'press' is never
            # renamed (it holds ROOT_CONTROL) — but its DESCENDANTS still are,
            # so a token-bearing child (press/press_notes.md) renames to
            # press/potato_notes.md instead of being abandoned.
            parts.append(component)
            continue
        new = component
        # [[replace]] rules run BEFORE the token pass here too: a rule's
        # rendered FROM may embed an identity token (e.g. "{package_name}-extra");
        # the token pass would rewrite that token out from under the rule.
        for rule, frm, to in rendered:
            if rule.paths and rule_matches_path(rule, posix):
                new = new.replace(frm, to)
        for f, cur, repl in pairs:
            if f in RENAME_FIELDS:
                if f in substring_fields:
                    new = new.replace(cur, repl)
                else:
                    new = replace_token(new, f, cur, repl)
        if component and not new:
            # A substitution that empties a path segment would collapse the
            # path into its parent (cookiecutter #1518's corruption class).
            raise ValidationError(
                f"rename would empty a path component of {posix!r} — refusing"
            )
        if new in (".", ".."):
            # A substituted component rendering to exactly "." or ".."
            # would collapse the path into itself/its parent or escape the
            # tree entirely — the same corruption class as the empty-
            # component guard above, just via a different degenerate value.
            raise ValidationError(
                f"rename would collapse a path component of {posix!r} to "
                f"{new!r} — refusing"
            )
        parts.append(new)
    return Path(*parts)


def _rename_prefix_map(
    entries: Collection[SurfaceEntry],
    pairs: list[tuple[str, str, str]],
    rendered: list[tuple[ReplaceRule, str, str]],
    substring_fields: Collection[str],
) -> dict[str, str]:
    """Collapse selected path rewrites to their shallowest rename prefixes."""

    rename_map: dict[str, str] = {}
    for entry in entries:
        rel = entry.rel
        new_rel = _renamed_rel(rel, pairs, rendered, substring_fields)
        if new_rel == rel:
            continue
        for i, (old_part, new_part) in enumerate(
            zip(rel.parts, new_rel.parts, strict=True)
        ):
            if old_part != new_part:
                old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                rename_map.setdefault(old_prefix, new_prefix)
                break
    return rename_map


def build_plan(target: Path, source: Identity, dest: Identity, rules: Rules) -> Plan:
    """Resolve what apply() would do; executes nothing."""
    source.validate()
    dest.validate()
    snapshot = capture_surface_snapshot(target)
    _validate_rewrite_snapshot(target, snapshot, rules)
    table = compile_substitution_table(
        source,
        dest,
        rules,
        snapshot,
        target=target,
        pipeline_validator=validate_pipeline,
    )
    plan = Plan(table=table)
    plan.rendered_rules = declared_rule_triples(table)
    content_entries = select_content_rewrite_entries(
        snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    for entry in content_entries:
        path = target / entry.rel
        rel = entry.rel
        assert_ancestors_real(path, target)
        text = _read_text(path, expected_kind=entry.worktree_kind)
        if text is not None:
            preview = text
            for row in table.rows:
                if "content" not in row.rewrite_surfaces or not row_matches_scope(
                    row, rel.as_posix()
                ):
                    continue
                rewritten = rewrite_with_row(row, preview)
                if rewritten == preview:
                    continue
                provenance = row.provenance[0]
                detail = (
                    f"rule {row.from_value!r} -> {row.to_value!r}"
                    if provenance.kind == "replace_rule"
                    else f"fields={[provenance.name]}"
                )
                plan.items.append(PlanItem("replace", rel.as_posix(), detail))
                preview = rewritten
    for step in table.rename_plan.steps:
        plan.items.append(PlanItem("rename", step.old_prefix, f"→ {step.new_prefix}"))
    plan.renames.update(table.rename_plan.as_mapping())
    tracked = tracked_path_strings(snapshot)
    rename_prefixes = [step.old_prefix for step in table.rename_plan.steps]
    rewrite_paths = {item.path for item in plan.items if item.kind == "replace"} | {
        path
        for path in tracked
        if any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in rename_prefixes
        )
    }
    plan.removal_warnings = removal_coverage_warnings(
        rules, source, rewrite_paths, tracked
    )
    return plan


def removal_coverage_warnings(
    rules: Rules,
    source: Identity,
    rewrite_paths: Collection[str],
    tracked_paths: Collection[str],
) -> list[str]:
    """Plan-time, non-fatal advisory (spec E5a): flag a top-level directory
    that LOOKS like undeclared template history because the press is about
    to rewrite every tracked file under it and no rule says what should
    happen to it.

    Depth 1 only for v1 (POSIX rel path's first component) — deeper
    directories are out of scope until a real need for them shows up.
    Grouping by TOP-LEVEL directory, not by every directory level, keeps
    the signal coarse and cheap to reason about: one line per top-level
    dir, not a warning per nested history folder.

    A directory triggers the warning only when EVERY one of its tracked
    files is a rewrite candidate — ``rewrite_paths`` is the union of (a)
    every file with a content substitution hit (``PlanItem(kind="replace")``
    from ``build_plan``) and (b) every tracked file whose PATH falls under
    a planned rename prefix (SOURCE coordinates), since a rename-only file
    (identity in its name, not its body — e.g. a logo PNG or a directory
    named after the package) is just as much "rewritten to the new
    identity" as a content hit. A directory with even one untouched tracked
    file is not, by this heuristic, template history — it is ordinary
    content that happens to sit next to rewritten files.

    A directory is silently skipped (never warned on) when:
    - its name is ``"src"`` or ``"tests"`` — conventional Python layout
      dirs where full-directory rewrite is the ordinary, expected case
      (the whole package/test tree legitimately mentions the identity); or
    - its name equals ``source.package_name`` — the flat-layout package
      root (the src-layout case is already covered by the ``"src"``
      exclusion above, since the package then sits at depth 2); or
    - any ``[[remove]]`` or ``[[reset]]`` rule targets a path under it — a
      human has already declared what happens to this directory, whether
      or not that declaration covers every file in it; or
    - the directory's name is in ``[rules] verify_ignore`` — the
      deliberate, committed exemption (matched by name, like
      ``verify_ignore`` elsewhere: this is a top-level dir name, so no
      component-at-any-depth scan is needed here).
    """

    tracked_set = set(tracked_paths)
    rewrite_set = set(rewrite_paths)
    by_dir: dict[str, list[str]] = {}
    for path in tracked_set:
        head, sep, _ = path.partition("/")
        if sep:
            by_dir.setdefault(head, []).append(path)
    declared_dirs = {
        rule.file.split("/", 1)[0]
        for rule in (*rules.remove, *rules.reset)
        if "/" in rule.file
    }
    warnings: list[str] = []
    for dirname in sorted(by_dir):
        if dirname in ("src", "tests", source.package_name):
            continue
        if dirname in declared_dirs:
            continue
        if dirname in rules.verify_ignore:
            continue
        files = by_dir[dirname]
        if all(f in rewrite_set for f in files):
            warnings.append(
                f"warning: {len(files)} tracked files under {dirname}/ will "
                "be rewritten to the new identity and no rule removes or "
                "resets them — declare [[remove]] or [rules] verify_ignore "
                "if this is template history"
            )
    return warnings


def _preflight_source_prefixes(
    renames: Mapping[str, str] | RenamePlan,
) -> list[str]:
    if isinstance(renames, RenamePlan):
        source_prefixes: list[str] = []
        prior_steps: list[tuple[str, str]] = []
        for step in renames.steps:
            source_prefix = step.old_prefix
            for old, new in reversed(prior_steps):
                if source_prefix == new:
                    source_prefix = old
                elif source_prefix.startswith(f"{new}/"):
                    source_prefix = f"{old}{source_prefix[len(new) :]}"
            source_prefixes.append(source_prefix)
            prior_steps.append((step.old_prefix, step.new_prefix))
    else:
        reverse = {new: old for old, new in renames.items()}
        source_prefixes = [translate_path(old, reverse) for old in sorted(renames)]
    return source_prefixes


def preflight_rename_noreplace(
    target: Path,
    renames: Mapping[str, str] | RenamePlan,
    *,
    allow_unsafe: bool = False,
    operational: bool = True,
) -> RenamePreflight:
    """Check planned rename filesystems; optionally permit a risky fallback."""

    checked_devices: set[int] = set()
    unsafe_devices: set[int] = set()
    problems: list[str] = []
    source_prefixes = _preflight_source_prefixes(renames)
    for old in source_prefixes:
        safe_old = SafeRelPath(old)
        source = target / Path(*safe_old.parts)
        assert_ancestors_real(source, target)
        device = os.lstat(source.parent).st_dev
        if device in checked_devices:
            continue
        checked_devices.add(device)
        try:
            if operational:
                require_rename_noreplace_support(source)
            else:
                require_rename_noreplace_host_support()
        except AtomicRenameUnavailableError as exc:
            if not allow_unsafe:
                raise
            unsafe_devices.add(device)
            problems.append(str(exc))
    return RenamePreflight(
        checked_devices=frozenset(checked_devices),
        unsafe_devices=frozenset(unsafe_devices),
        problems=tuple(problems),
        operational=operational,
    )


@dataclass
class ApplyReport:
    replaced: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    regenerated: list[str] = field(default_factory=list)
    reset: list[str] = field(default_factory=list)  # declared stubs written
    removed: list[str] = field(default_factory=list)  # declared deletions
    executed_rename_step_ids: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (
            f"Applied: {len(self.replaced)} replaced, "
            f"{len(self.renamed)} renamed, "
            f"{len(self.reset)} reset, "
            f"{len(self.removed)} removed, "
            f"{len(self.regenerated)} regenerated, "
            f"{len(self.skipped)} skipped."
        )


def _apply_replacements(
    target: Path,
    table: SubstitutionTable,
    rules: Rules,
    report: ApplyReport,
) -> None:
    snapshot = SurfaceSnapshot(
        table.rename_plan.source_entries,
        table.rename_plan.visibility_inputs,
    )
    entries = select_content_rewrite_entries(
        snapshot,
        exclude_files=rules.exclude_files,
        exclude_dirs=rules.exclude_dirs,
        root_control=ROOT_CONTROL,
    )
    symlink_entries = tuple(
        entry
        for entry in select_rename_entries(
            snapshot,
            exclude_files=rules.exclude_files,
            exclude_dirs=rules.exclude_dirs,
            root_control=ROOT_CONTROL,
        )
        if entry.worktree_kind == "symlink"
    )
    for entry in sorted(
        (*entries, *symlink_entries),
        key=lambda item: item.rel.as_posix(),
    ):
        path = target / entry.rel
        rel = entry.rel.as_posix()
        assert_ancestors_real(path, target)
        text = _read_text(path, expected_kind=entry.worktree_kind)
        if text is None:
            kind = "symlink" if path.is_symlink() else "binary"
            report.skipped.append(f"replace {rel} ({kind})")
            continue
        new_text = text
        for row in table.rows:
            if "content" in row.rewrite_surfaces and row_matches_scope(row, rel):
                new_text = rewrite_with_row(row, new_text)
        if new_text != text:
            # Route through safe_write: its assert_under_root closes the
            # ancestor-symlink hole (a symlinked ancestor would write OUTSIDE
            # the target), and its atomic temp + os.replace makes the write
            # hardlink-SAFE (a new inode). refuse_hardlink=False because that
            # atomicity already protects an external hardlink WITHOUT falsely
            # refusing a legitimate in-repo hardlinked file. A symlink LEAF
            # never reaches here — _read_text returns None for it upstream.
            # The fresh inode starts from mkstemp's 0600, so the original
            # permission bits are restored afterwards — a rewritten 0755
            # helper must not come out non-executable (P04 D1).
            mode = stat.S_IMODE(os.lstat(path).st_mode)
            safe_write(
                target,
                path.relative_to(target),
                new_text,
                refuse_hardlink=False,
            )
            chmod_nofollow(path, mode)
            report.replaced.append(rel)


def _retarget_symlinks(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]] | None = None,
    substring_fields: Collection[str] = frozenset(),
) -> None:
    """Rewrite in-repo RELATIVE symlink targets carrying identity tokens.

    Only the link STRING is rewritten — the pointed-to file is never read,
    written, or followed. Candidates come from ``_git_listed`` filtered by a
    no-follow ``is_symlink`` lstat (NOT ``iter_target_files``, which follows
    links). A symlink is left untouched when its target is absolute, carries
    no token, or would escape the root after rewriting (containment via the
    reused ``assert_under_root`` on the resolved sink). The link is recreated
    with unlink + symlink, guarded by an immediate ``is_symlink`` re-check to
    refuse a TOCTOU swap.

    A link is retargeted ONLY when its (un-rewritten) TARGET is *movable* —
    something the rename pass will actually do something to. Rewriting the
    link's text otherwise silently repoints it at a DIFFERENT, unrelated
    file that happens to already sit at the rendered TO (a gitignored
    ``bar-guide`` next to a gitignored ``foo-guide``): the doctor never scans
    ignored content, so this corruption goes undetected and a receipt gets
    written over it. ``target_posix`` is movable when it (a) IS itself a
    rename candidate, (b) is a DIRECTORY holding one (git lists FILES only,
    never directories, so a link to a tracked dir is never itself a
    candidate — the check must be prefix-aware, not membership-only, or a
    link to a tracked directory is wrongly refused and left dangling), or
    (c) doesn't exist at all (dangling — nothing there to break, so
    rebranding the link text is safe). The candidate set is computed ONCE
    per call (it shells out to git) since it does not depend on the
    individual link being examined.

    The same movable gate also applies to the plain identity-field PAIR
    loop below, not just the rule loop: the identical silent-redirect shape
    is constructible through an ordinary field pair alone (no [[replace]]
    rule involved) and predates this branch — fixing only the rule twin
    while leaving the pair twin unguarded would still permit the exact same
    corruption via a different mechanism.

    Dispatch per field mirrors ``_apply_replacements``: a field in
    ``substring_fields`` uses plain substring replacement (glued-token
    coverage, codesign sec-02 secondary); every other field uses the
    boundary-guarded ``replace_token``.

    A ``paths = true`` [[replace]] rule (Fix F2) is also applied to the link
    text, mirroring ``_renamed_rel``/the rename pass exactly: symlink text
    follows exactly what the rename pass moves, so a rule renaming
    ``plbp-web/`` -> ``acme-web/`` must retarget ``link -> plbp-web/data``
    too, or the link keeps pointing at a path the rename pass just moved
    away from under it. A ``content``-only rule (``paths=False``) must NOT
    touch link text — mirror-image of the display-pair exclusion below.
    Rules run BEFORE the field-pair pass (same order as
    ``_apply_replacements``/``_renamed_rel``).

    A rule's ``files`` scope selects which TARGET paths get renamed — so the
    scope match here (Fix F3) is against the link's TARGET, normalized to an
    in-tree rel posix path (``rel.parent`` joined with the un-rewritten link
    text), NOT the symlink's own location: a rule with ``files=["docs/**"]``
    must still retarget a root-level link pointing INTO ``docs/``, even
    though the link itself lives outside that scope. A target that
    normalizes outside the tree (a relative ``../`` escape) never matches any
    rule's scope here — the containment guard below (on the fully-rewritten
    sink) is what actually polices an escaping link.
    """
    rendered = rendered or []
    target_r = target.resolve()
    cands = {
        p.relative_to(target).as_posix() for p in _rename_candidates(target, rules)
    }
    snapshot = capture_surface_snapshot(target)
    for entry in snapshot.entries:
        if entry.worktree_kind != "symlink":
            continue
        rel = entry.rel
        path = target / rel
        link = readlink_nofollow(path)
        if os.path.isabs(link):
            continue  # never rewrite or follow an absolute target
        new_link = link
        target_posix = symlink_target_posix(rel, link)
        scope_escapes = target_posix == ".." or target_posix.startswith("../")
        movable = (
            target_posix in cands
            or any(c.startswith(target_posix + "/") for c in cands)
            or not (target / target_posix).exists()
        )
        if movable:
            for rule, frm, to in rendered:
                if (
                    rule.paths
                    and not scope_escapes
                    and rule_matches_path(rule, target_posix)
                ):
                    new_link = new_link.replace(frm, to)
            for f, cur, repl in pairs:
                if f in substring_fields:
                    new_link = new_link.replace(cur, repl)
                else:
                    new_link = replace_token(new_link, f, cur, repl)
        if new_link == link:
            continue
        sink = (path.parent / new_link).resolve()
        try:
            assert_under_root(sink, target_r)
        except ContainmentError:
            report.skipped.append(f"retarget {rel.as_posix()} (escaping target)")
            continue
        if not path.is_symlink():  # TOCTOU: refuse a swapped-in non-symlink
            report.skipped.append(f"retarget {rel.as_posix()} (no longer a symlink)")
            continue
        # Validate the LINK LOCATION's ancestors (not just the sink): a
        # symlinked ancestor of `path` would land unlink/symlink OUTSIDE the
        # target. Fail closed (propagate) on a hostile ancestor — never
        # silently skip a containment violation.
        assert_ancestors_real(path, target)
        # Windows distinguishes file and directory symlinks: a directory link
        # must be removed with rmdir (unlink raises WinError 5) and recreated
        # with target_is_directory, or it comes back as a broken file link.
        # `is_dir()` follows the link, which is exactly the question here (is
        # the SINK a directory), and must be asked before the link is removed.
        # POSIX ignores target_is_directory, so one code path serves both.
        links_to_dir = path.is_dir()
        if links_to_dir and os.name == "nt":
            os.rmdir(path)
        else:
            os.unlink(path)
        os.symlink(new_link, path, target_is_directory=links_to_dir)
        report.replaced.append(rel.as_posix())


def _apply_planned_renames(
    target: Path,
    plan: RenamePlan,
    report: ApplyReport,
    *,
    rename_preflight: RenamePreflight,
) -> None:
    """Execute the compiled steps, gating each on its predecessors."""

    executed: set[str] = set()
    for step in plan.steps:
        missing_predecessors = [
            predecessor
            for predecessor in step.predecessor_step_ids
            if predecessor not in executed
        ]
        if missing_predecessors:
            report.skipped.append(
                f"rename {step.old_prefix} (predecessor did not execute: "
                f"{', '.join(missing_predecessors)})"
            )
            continue
        old, new = step.old_prefix, step.new_prefix
        src, dst = target / old, target / new
        if os.path.lexists(dst):
            kind = "symlink" if dst.is_symlink() else "exists"
            report.skipped.append(f"rename {old} (destination {kind})")
            continue
        assert_ancestors_real(dst, target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        assert_ancestors_real(src, target)
        try:
            current = os.lstat(src)
        except OSError as exc:
            raise SafetyError(
                f"rename source changed after capture: {old} "
                f"(expected {step.expected_kind})"
            ) from exc
        if stat.S_ISREG(current.st_mode):
            current_kind: WorktreeKind = "file"
        elif stat.S_ISLNK(current.st_mode):
            current_kind = "symlink"
        elif stat.S_ISDIR(current.st_mode):
            current_kind = "directory"
        else:
            current_kind = "other"
        if current_kind != step.expected_kind:
            raise SafetyError(
                f"rename source changed after capture: {old} "
                f"(expected {step.expected_kind}, found {current_kind})"
            )
        device = os.lstat(src.parent).st_dev
        if device not in rename_preflight.checked_devices:
            raise SafetyError("rename filesystem changed after capability preflight")
        try:
            if device in rename_preflight.unsafe_devices:
                rename_noreplace_best_effort(src, dst)
            else:
                rename_noreplace(src, dst)
        except FileExistsError as exc:
            raise SafetyError(
                f"rename destination appeared after validation: {new}"
            ) from exc
        report.renamed.append((old, new))
        report.executed_rename_step_ids.append(step.step_id)
        executed.add(step.step_id)


def _retarget_planned_symlinks(
    target: Path,
    table: SubstitutionTable,
    report: ApplyReport,
) -> None:
    """Retarget links from executed moves or validated dangling translations."""

    plan = table.rename_plan
    executed = frozenset(report.executed_rename_step_ids)
    virtual = {
        (link_source, target_source): target_destination
        for link_source, target_source, target_destination in (
            plan.virtual_translations
        )
    }
    expected_links = dict(plan.symlink_inputs)
    target_root = target.resolve()
    for entry in plan.source_entries:
        if entry.worktree_kind != "symlink":
            continue
        source_rel = entry.rel.as_posix()
        current_rel = plan.translate(source_rel, executed_step_ids=executed)
        path = target / current_rel
        assert_ancestors_real(path, target)
        try:
            link = readlink_nofollow(path)
        except OSError as exc:
            raise SafetyError(f"symlink changed after capture: {source_rel}") from exc
        expected_link = expected_links.get(source_rel)
        if expected_link is None:
            raise SafetyError(f"symlink was not captured during planning: {source_rel}")
        if link != expected_link:
            raise SafetyError(
                f"symlink changed after capture: {source_rel} "
                f"(expected {expected_link!r}, found {link!r})"
            )
        if os.path.isabs(link):
            continue
        source_target = symlink_target_posix(entry.rel, link)
        if source_target == ".." or source_target.startswith("../"):
            continue
        executed_target = plan.translate(
            source_target,
            executed_step_ids=executed,
        )
        if executed_target != source_target:
            final_target = executed_target
        else:
            final_target = virtual.get((source_rel, source_target))
            if final_target is None:
                continue
        new_link = os.path.relpath(
            final_target,
            start=Path(current_rel).parent.as_posix(),
        ).replace(os.sep, "/")
        if new_link == link:
            continue
        sink = (path.parent / new_link).resolve()
        try:
            assert_under_root(sink, target_root)
        except ContainmentError:
            report.skipped.append(f"retarget {current_rel} (escaping target)")
            continue
        if not path.is_symlink():
            report.skipped.append(f"retarget {current_rel} (no longer a symlink)")
            continue
        links_to_dir = path.is_dir()
        if links_to_dir and os.name == "nt":
            os.rmdir(path)
        else:
            os.unlink(path)
        os.symlink(new_link, path, target_is_directory=links_to_dir)
        report.replaced.append(current_rel)


def apply(
    target: Path,
    source: Identity,
    dest: Identity,
    rules: Rules,
    *,
    allow_unsafe_rename: bool = False,
    rename_preflight: RenamePreflight | None = None,
    table: SubstitutionTable | None = None,
) -> ApplyReport:
    """Execute content rows, the compiled rename plan, then link retargets."""
    source.validate()
    dest.validate()
    if table is None:
        snapshot = capture_surface_snapshot(target)
        _validate_rewrite_snapshot(target, snapshot, rules)
        table = compile_substitution_table(
            source,
            dest,
            rules,
            snapshot,
            target=target,
            pipeline_validator=validate_pipeline,
        )
    else:
        _validate_rewrite_snapshot(
            target,
            SurfaceSnapshot(
                table.rename_plan.source_entries,
                table.rename_plan.visibility_inputs,
            ),
            rules,
        )
    revalidate_substitution_table(target, table)
    # Direct callers bypass the CLI preflight, so probe each source filesystem
    # before replacements can partially rewrite the target.
    if rename_preflight is None:
        rename_preflight = preflight_rename_noreplace(
            target,
            table.rename_plan,
            allow_unsafe=allow_unsafe_rename,
        )
    elif not rename_preflight.operational:
        raise SafetyError("rename execution requires an operational preflight")
    elif not rename_preflight.atomic and not allow_unsafe_rename:
        raise SafetyError(
            "non-atomic rename fallback requires allow_unsafe_rename=True"
        )
    current_devices = frozenset(
        os.lstat((target / Path(*SafeRelPath(old).parts)).parent).st_dev
        for old in _preflight_source_prefixes(table.rename_plan)
    )
    if not current_devices <= rename_preflight.checked_devices:
        raise SafetyError("rename filesystem changed after capability preflight")
    report = ApplyReport()
    _apply_replacements(target, table, rules, report)
    _apply_planned_renames(
        target,
        table.rename_plan,
        report,
        rename_preflight=rename_preflight,
    )
    _retarget_planned_symlinks(target, table, report)
    return report


def _rename_pass_once(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]],
    *,
    rename_preflight: RenamePreflight | None = None,
) -> bool:
    """Run one shallowest-prefix rename pass; return True if any rename ran.

    Rescans `_rename_candidates` fresh so each pass sees the previous pass's
    moves, then collapses each differing path to only its shallowest
    renamed ancestor (one path level per pass) and executes deepest-first
    to keep parents valid. `_rename_candidates` (Fix F2), not
    `iter_target_files`: retarget rewrites a symlink's TEXT only, so a
    directory or dangling symlink whose NAME carries an identity token would
    otherwise never reach this pass at all (`iter_target_files`'s
    `is_file()` filter follows the link and drops it).
    """
    rename_map: dict[str, tuple[str, WorktreeKind]] = {}
    for entry in _rename_candidate_entries(target, rules):
        rel = entry.rel
        new_rel = _renamed_rel(rel, pairs, rendered, rules.substring_rewrite_fields)
        if new_rel == rel:
            continue
        for i, (old_part, new_part) in enumerate(
            zip(rel.parts, new_rel.parts, strict=True)
        ):
            if old_part != new_part:
                # The root 'press' component never differs (protected in
                # _renamed_rel), so the first diff is always a renamable
                # component — no root-press guard is needed here.
                old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                expected_kind: WorktreeKind = (
                    entry.worktree_kind if i == len(rel.parts) - 1 else "directory"
                )
                rename_map.setdefault(old_prefix, (new_prefix, expected_kind))
                break
    performed = False
    for old in sorted(rename_map, key=lambda p: -len(Path(p).parts)):
        new, expected_kind = rename_map[old]
        src, dst = target / old, target / new
        if dst.exists():
            report.skipped.append(f"rename {old} (destination exists)")
            continue
        if dst.is_symlink():
            # `Path.exists()` FOLLOWS symlinks — a DANGLING symlink at dst
            # reads as absent there, so without this lstat-based check
            # POSIX rename() would silently replace the symlink itself
            # (a destructive in-tree overwrite the destination-occupied
            # check was meant to prevent).
            report.skipped.append(f"rename {old} (destination is a symlink)")
            continue
        # A symlinked ancestor on either endpoint would move CONTENT through a
        # symlink out of the target. Tolerates a token-bearing symlink LEAF
        # (renaming a symlink is legitimate); fails closed (propagates) on a
        # symlinked ancestor.
        assert_ancestors_real(dst, target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # All destination preparation is complete. Revalidate the captured
        # source kind as the final userspace check before the atomic move.
        assert_ancestors_real(src, target)
        try:
            current = os.lstat(src)
        except OSError as exc:
            raise SafetyError(
                f"rename source changed after capture: {old} (expected {expected_kind})"
            ) from exc
        current_kind: WorktreeKind
        if stat.S_ISREG(current.st_mode):
            current_kind = "file"
        elif stat.S_ISLNK(current.st_mode):
            current_kind = "symlink"
        elif stat.S_ISDIR(current.st_mode):
            current_kind = "directory"
        else:
            current_kind = "other"
        if current_kind != expected_kind:
            raise SafetyError(
                f"rename source changed after capture: {old} "
                f"(expected {expected_kind}, found {current_kind})"
            )
        try:
            device = os.lstat(src.parent).st_dev
            if rename_preflight is not None and device not in (
                rename_preflight.checked_devices
            ):
                raise SafetyError(
                    "rename filesystem changed after capability preflight"
                )
            if rename_preflight is not None and device in (
                rename_preflight.unsafe_devices
            ):
                rename_noreplace_best_effort(src, dst)
            else:
                rename_noreplace(src, dst)
        except FileExistsError as exc:
            raise SafetyError(
                f"rename destination appeared after validation: {new}"
            ) from exc
        report.renamed.append((old, new))
        performed = True
    return performed


def _apply_renames(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]],
    *,
    rename_preflight: RenamePreflight,
) -> None:
    """Rename tracked paths whose components carry identity tokens.

    Runs `_rename_pass_once` to a fixpoint: each pass renames only the
    shallowest differing path level (e.g. src/demo_widget →
    src/potato_launcher) and re-scans the target before the next pass, so a
    token-bearing file nested inside a token-bearing dir gets its dir moved
    on one pass and its (now-relocated) file renamed on the next, instead of
    colliding mid-move. Bounded to 32 passes (depth bound); stops as soon as
    a pass performs no renames.

    Fix F2b: falling out of this loop with the LAST pass still having
    performed renames means 32 passes never reached a fixpoint — e.g. a
    substring-mode identity field pair that re-embeds itself the same way a
    self-reapplying [[replace]] rule would (fix F2a catches that shape at
    plan time; this is the belt-and-suspenders catch-all for any other path
    that drives non-convergence, plan-time or not). Silently returning here
    would leave the target 32 passes into a destructive, non-terminating
    rename with no signal anything went wrong. Raises ``SafetyError``
    (rather than ``ValidationError``): this fires MID-APPLY, after writes
    have already happened, and the CLI's ``_press`` partial-rewrite error
    path (which prints the "target may be PARTIALLY rewritten" restore
    message) only catches ``SafetyError`` — not ``ValidationError``, which
    would otherwise propagate past ``_press`` as an uncaught traceback.
    """
    for _ in range(MAX_RENAME_PASSES):
        if not _rename_pass_once(
            target,
            pairs,
            rules,
            report,
            rendered,
            rename_preflight=rename_preflight,
        ):
            return
    raise SafetyError(
        f"rename passes did not reach a fixpoint after {MAX_RENAME_PASSES} "
        "iterations — a "
        "path component keeps changing on every pass (a self-reapplying "
        "[[replace]] rule or substring-mode identity field); the target is "
        "PARTIALLY rewritten"
    )
