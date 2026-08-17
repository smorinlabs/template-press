"""Declared-command regeneration — plan-time state preflight (P04 D1/D5).

Regeneration outputs must be git-tracked and clean at plan time, refused
even under ``--allow-dirty`` (the functions here take no such flag at all):
the declared command overwrites the file wholesale, and git restores only
committed content, so uncommitted edits to a declared output have no
recoverable copy. The sink predicates (containment, no-follow regular file,
``st_nlink == 1``) run here too — an in-place-truncating regenerator on a
hardlinked output would corrupt the external inode, and unlike reset, no
``safe_write`` new-inode guarantee applies.
"""

from __future__ import annotations

import os
import posixpath
import shlex
import shutil
import subprocess  # nosec B404 — git state reads on the target
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import (
    ROOT_CONTROL,
    ApplyReport,
    rendered_replace_rules,
    translate_path,
)
from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    display_forms,
)
from template_press.rebrand.inventory import (
    GitConfigInput,
    IndexKind,
    VisibilityInput,
    capture_surface_snapshot,
    tracked_path_strings,
)
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.rules import (
    RegenerateRule,
    ReplaceRule,
    ResetRule,
    Rules,
    rule_matches_path,
)
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    git_hardening_args,
    is_regular_lstat,
    safe_write,
    scrubbed_git_env,
)
from template_press.rebrand.substitutions import (
    SubstitutionTable,
    matching_hunts,
)

# The deny-by-default child environment's fixed base (P04 D1, decided
# 2026-07-26): a minimal, PLATFORM-SPECIFIC set — the Unix base is wrong on
# Windows, where process loading and tool discovery need SystemRoot/PATHEXT/
# USERPROFILE/TEMP/TMP while HOME and TMPDIR may not exist at all. Everything
# else reaches a declared command only via its declared ``env`` NAMES.
COMMAND_ENV_BASE: tuple[str, ...] = (
    ("PATH", "SystemRoot", "PATHEXT", "USERPROFILE", "TEMP", "TMP")
    if os.name == "nt"
    else ("PATH", "HOME", "LANG", "TMPDIR")
)


def _executed_step_ids(
    table: SubstitutionTable,
    renames: Mapping[str, str],
) -> frozenset[str]:
    """Resolve an apply report's executed pairs to the table's step IDs."""

    return table.rename_plan.executed_ids_for(tuple(renames.items()))


def _translate_output_path(
    rel: str,
    renames: Mapping[str, str],
    table: SubstitutionTable | None,
) -> str:
    """Translate a declared source path through the executed lifecycle view."""

    if table is None:
        return translate_path(rel, renames)
    return table.rename_plan.translate(
        rel,
        executed_step_ids=_executed_step_ids(table, renames),
    )


def _reverse_output_path(
    rel: str,
    renames: Mapping[str, str],
    table: SubstitutionTable | None,
) -> str:
    """Recover a declared source coordinate from the executed lifecycle view."""

    if table is None:
        reverse = {new: old for old, new in renames.items()}
        return translate_path(rel, reverse)
    return table.rename_plan.reverse_translate(
        rel,
        executed_step_ids=_executed_step_ids(table, renames),
    )


def command_env(
    declared: Sequence[str],
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The deny-by-default effective environment for one declared command.

    Copies ONLY the platform base plus the declaration's named variables
    from the operator's environment; a declared name absent there is simply
    omitted (the declaration is permission, not a requirement). Stray
    ``UV_INDEX_URL``-class settings and CI tokens never arrive.
    """
    ambient = os.environ if base_env is None else base_env
    env: dict[str, str] = {}
    for name in (*COMMAND_ENV_BASE, *declared):
        if name in ambient:
            env[name] = ambient[name]
    return env


def resolve_executable(target: Path, argv0: str, env: Mapping[str, str]) -> Path | None:
    """Resolve ``argv0`` exactly as execution will (D2), or None.

    Path-qualified (anything containing a separator) resolves against the
    TARGET root — the mandatory execution cwd — and never via PATH; an
    absolute argv0 pins itself. Bare names resolve on the EFFECTIVE env's
    PATH (the deny-by-default base), never the operator's ambient PATH, so
    a command cannot pass planning under an env it will not launch under.
    """
    text = argv0.replace("\\", "/")
    if "/" in text:
        if os.path.isabs(argv0):
            candidate = argv0
        else:
            candidate = os.path.normpath(os.path.join(str(target), text))
        found = shutil.which(candidate)
        return Path(os.path.abspath(found)) if found else None
    # Absolute at resolution time: a relative PATH entry yields a relative
    # which() result anchored to the CALLER's cwd, but execution launches
    # with cwd=target — the pin must freeze the binary planning verified.
    found = shutil.which(argv0, path=env.get("PATH", ""))
    return Path(os.path.abspath(found)) if found else None


def stale_argv_elements(command: Sequence[str], renamed: Collection[str]) -> list[str]:
    """argv elements that name a path in the plan's rename set (D1).

    Prefix-aware (an element equal to OR beneath a renamed path goes just
    as stale) and normalized before comparison — separators unified,
    ``.``/``..`` segments collapsed — so spellings like
    ``./packages/demo_widget`` cannot slip past. Best-effort over
    recognized shapes: an attached-option payload (``--config=path``)
    cannot be seen without guessing argv semantics; the command then fails
    loudly mid-press and the abort withholds the receipt.
    """
    renamed_set = {r.rstrip("/") for r in renamed}
    if not renamed_set:
        return []
    stale: list[str] = []
    for element in command:
        norm = posixpath.normpath(element.replace("\\", "/"))
        if norm.startswith(("/", "../")) or norm == ".." or ":" in norm:
            continue  # not a target-relative path shape
        if norm in renamed_set or any(
            norm.startswith(prefix + "/") for prefix in renamed_set
        ):
            stale.append(element)
    return stale


@dataclass(frozen=True)
class RegenerationPlan:
    """One declared command, fully resolved for the plan (and the plan is
    the approval guard, so this carries exactly what will launch)."""

    rule: RegenerateRule
    executable: str  # the pinned absolute path that will actually launch
    env_present: tuple[str, ...]  # declared names that WILL apply
    env_absent: tuple[str, ...]  # declared names absent from the operator env


def plan_regenerate_commands(
    target: Path,
    regenerate: Sequence[RegenerateRule],
    *,
    renamed: Collection[str],
    base_env: Mapping[str, str] | None = None,
) -> tuple[list[RegenerationPlan], list[str]]:
    """Resolve every declared command at plan time (D2); problems refuse.

    A missing tool or a stale path-bearing argv is a clean exit-2 refusal
    with nothing written, instead of a failure discovered after the rewrite
    pass has already mutated the repo.
    """
    ambient = os.environ if base_env is None else base_env
    plans: list[RegenerationPlan] = []
    problems: list[str] = []
    for rule in regenerate:
        stale = stale_argv_elements(rule.command, renamed)
        if stale:
            problems.append(
                f"regenerate {rule.file}: argv element(s) "
                f"{', '.join(repr(s) for s in stale)} name path(s) this press "
                f"renames — they would go stale mid-press; write the command "
                f"rename-independent (it runs from the target root, so cwd "
                f"carries the location)"
            )
            continue
        env = command_env(rule.env, base_env=ambient)
        resolved = resolve_executable(target, rule.command[0], env)
        if resolved is None:
            where = (
                "relative to the target root"
                if "/" in rule.command[0].replace("\\", "/")
                else "on PATH under the deny-by-default environment"
            )
            problems.append(
                f"regenerate {rule.file}: executable {rule.command[0]!r} not "
                f"found {where} — install it or fix the declaration "
                f"(`press check-tools` reports every declared tool)"
            )
            continue
        plans.append(
            RegenerationPlan(
                rule=rule,
                executable=str(resolved),
                env_present=tuple(n for n in rule.env if n in ambient),
                env_absent=tuple(n for n in rule.env if n not in ambient),
            )
        )
    return plans, problems


def execute_regenerations(
    target: Path,
    plans: Sequence[RegenerationPlan],
    renamed: Mapping[str, str],
    report: ApplyReport,
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
) -> list[str]:
    """Run each declared command (D1's execution contract); return FAILED files.

    cwd = the target root (a relative-path-resolving tool must mutate THIS
    checkout, never the press caller's); NO shell (argv is a list precisely
    so there is no shell to inject into); deny-by-default env; and the
    PINNED plan-time executable launches — no second runtime PATH lookup
    exists to diverge from what was planned and shown.

    Declared paths are SOURCE coordinates translated through the rename
    report (apply() has already moved identity-bearing directories). The
    full sink-guard set — containment, real ancestors, no-follow regular
    file, ``st_nlink == 1`` — re-runs immediately before EACH launch: an
    earlier command can plant a symlink or hardlink at a later output's
    path (D3). A nonzero exit fails the press regardless of how the output
    scans afterwards (wave-3 3654059287).
    """
    failed: list[str] = []
    renames = dict(renamed)
    for plan in plans:
        rule = plan.rule
        out_rel = _translate_output_path(rule.file, renames, table)
        out_path = target / out_rel
        try:
            assert_under_root(out_path, target)
            assert_ancestors_real(out_path, target)
        except SafetyError as exc:
            report.skipped.append(f"regenerate {rule.file} (sink guard: {exc})")
            failed.append(rule.file)
            continue
        if not is_regular_lstat(out_path):
            report.skipped.append(
                f"regenerate {rule.file} (sink guard: {out_rel} is not a "
                f"regular file — no-follow check)"
            )
            failed.append(rule.file)
            continue
        if os.lstat(out_path).st_nlink > 1:
            report.skipped.append(
                f"regenerate {rule.file} (sink guard: {out_rel} is hardlinked)"
            )
            failed.append(rule.file)
            continue
        # Bytes capture: only the exit code is consumed, and a declared
        # command may legitimately emit non-UTF-8 — a strict text decode
        # would crash mid-press with the target partially mutated.
        result = subprocess.run(  # noqa: S603 # nosec B603
            [plan.executable, *rule.command[1:]],
            cwd=target,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=command_env(rule.env),
        )
        if result.returncode != 0:
            report.skipped.append(
                f"regenerate {rule.file} (command exited {result.returncode})"
            )
            failed.append(rule.file)
            continue
        # Postconditions (D3): the exemption is earned by RESULT — the
        # produced output must exist, still be a contained regular file,
        # decode as UTF-8, and pass the paranoid changed-fields scan.
        problems = _postcondition_problems(
            target,
            out_rel,
            source=source,
            dest=dest,
            rules=rules,
            renames=renames,
            rendered_rules=rendered_rules,
            table=table,
            scan_mode=rule.scan,
        )
        if problems:
            report.skipped.extend(
                f"regenerate {rule.file} ({problem})" for problem in problems
            )
            failed.append(rule.file)
        else:
            report.regenerated.append(rule.file)
    return failed


def render_regenerate_plan(plans: Sequence[RegenerationPlan]) -> str:
    """The plan's regeneration section: verbatim argv, pinned executable,
    and the declared env names (with which would actually apply) — plan
    visibility is the approval guard, so this must show what will launch."""
    lines = ["Regenerate (declared commands, run after apply):"]
    for plan in plans:
        lines.append(
            f"  [regen  ] {plan.rule.file}  —  {shlex.join(plan.rule.command)}"
        )
        lines.append(f"            executable: {plan.executable}")
        if plan.rule.env:
            marks = [
                name if name in plan.env_present else f"{name} (absent)"
                for name in plan.rule.env
            ]
            lines.append(f"            env: {', '.join(marks)}")
    return "\n".join(lines)


def _git_stdout(target: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        ["git", "-C", str(target), *git_hardening_args(), *args],  # noqa: S607
        check=True,
        capture_output=True,
        env=scrubbed_git_env(),
    )
    # Bytes + surrogateescape, matching engine._git_listed: a git path is
    # any byte except NUL, so a strict text decode would crash every
    # preflight on a single non-UTF-8 filename.
    return result.stdout.decode("utf-8", "surrogateescape")


def tracked_paths(target: Path) -> frozenset[str]:
    """Compatibility adapter for every path present in the target index."""

    return tracked_path_strings(capture_surface_snapshot(target))


def has_uncommitted_changes(target: Path, rel: str) -> bool:
    """Staged or unstaged changes for one path — including edits the
    assume-unchanged / skip-worktree bits hide from `status --porcelain`
    (lowercase or S first column in `ls-files -v`): the guard's promise is
    refusing to destroy hidden work, which is precisely that case."""
    if _git_stdout(target, "status", "--porcelain", "--", rel).strip():
        return True
    flags = _git_stdout(target, "ls-files", "-v", "--", rel)
    return any(line[:1].islower() or line[:1] == "S" for line in flags.splitlines())


def preflight_regenerate_outputs(target: Path, rules: Rules) -> list[str]:
    """Problems that make a declared regeneration output unpressable.

    Empty list = every declared output is contained, a regular file
    (no-follow), sole-linked, git-tracked, and clean. Runs at plan time in
    SOURCE coordinates (before the rename pass moves anything), under the
    exit-2-nothing-written contract.
    """
    if not rules.regenerate:
        return []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.regenerate:
        prefix = f"regenerate output {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (outputs must be committed so git "
                "provides the undo path)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        st = os.lstat(path)
        if st.st_nlink > 1:
            problems.append(
                prefix + f"hardlinked (st_nlink={st.st_nlink}) — an in-place-"
                f"truncating regenerator would corrupt the external inode"
            )
            continue
        if has_uncommitted_changes(target, rule.file):
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (git restores only committed content)"
            )
            continue
        # Plan-time half of the UTF-8 two-point gate (D3): the exemption is
        # bought with the post-command TEXT scan, so an undecodable
        # pre-state can never earn it — fail closed, route such files
        # through verify_ignore instead.
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problems.append(
                prefix + "tracked pre-state is not valid UTF-8 — a file the "
                "text scan cannot read cannot earn the exemption (fail "
                "closed; use verify_ignore for deliberate binaries)"
            )
    return problems


def preflight_excluded_files(target: Path, rules: Rules) -> list[str]:
    """The §6 excluded-file contract preflight (P04 D5, shared with P05).

    An excluded file is never rewritten; with the hidden regeneration
    default removed, one with no declared neutralization is also never
    rebuilt and never scanned — source identity would survive under a
    clean receipt, and the R3 harness (a real rebrand, no independent
    grep) cannot catch it. So every TRACKED excluded file must carry
    exactly one of the three: a [[regenerate]] command, a [[reset]] stub,
    or a deliberate [rules] verify_ignore entry. Exit 2, nothing written.
    """
    regenerated = {r.file for r in rules.regenerate}
    reset_files = {r.file for r in rules.reset}
    removed_files = {r.file for r in rules.remove}
    problems: list[str] = []
    for rel in sorted(tracked_paths(target)):
        if rel not in rules.exclude_files:
            continue
        if rel in regenerated or rel in reset_files or rel in removed_files:
            continue
        if any(part in rules.verify_ignore for part in rel.split("/")):
            continue
        if not os.path.lexists(target / rel):
            continue  # tracked but absent from the worktree — nothing survives
        problems.append(
            f"excluded file {rel} is neither regenerated, reset, removed, "
            f"nor ignored — it would survive the press unrewritten AND "
            f"unscanned; declare a [[regenerate]] command, a [[reset]] stub, "
            f"or a [[remove]] in press/press-rules.toml, or list it under "
            f"[rules] verify_ignore (the deliberate, committed exemption)"
        )
    return problems


def changed_identity_pairs(source: Identity, dest: Identity) -> list[tuple[str, str]]:
    """(field, source_value) for fields present on both sides that differ —
    an unchanged field legitimately remains everywhere (changed-only, the
    verifier's rule; feeding the full source identity would turn a retained
    author in a correct fresh lockfile into a false leak)."""
    src, dst = _expanded_fields(source), _expanded_fields(dest)
    return [(f, src[f]) for f in src if f in dst and dst[f] != src[f]]


def _expanded_fields(identity: Identity) -> dict[str, str]:
    """as_dict() with a raw display_name replaced by its DERIVED forms —
    the rewriter and doctor both operate on the per-form tags, so the
    changed-fields scan must see the same universe (a glued source
    PascalCase form is invisible to the raw spaced value)."""
    values = identity.as_dict()
    if "display_name" not in values:
        return values
    expanded = {k: v for k, v in values.items() if k != "display_name"}
    forms = display_forms(values["display_name"])
    for form in DISPLAY_FORM_NAMES:
        expanded[f"display_name_{form}"] = forms[form]
    return expanded


def scan_regenerated_output(
    text: str,
    translated_rel: str,
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
    renames: Mapping[str, str],
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
    scan_mode: str = "strict",
) -> list[str]:
    """Paranoid changed-fields scan of one produced output (D3).

    The exemption being earned is exemption from VERIFY, whose reason for
    existing is a stricter matcher than the doctor's — so the evidence uses
    ``matcher.find_occurrences`` (case/separator-glued forms included),
    covers rendered ``[[replace]]`` FROM literals (scopes are in SOURCE
    coordinates, so the file's destination path is reverse-mapped through
    the renames before the glob check), and covers every component of the
    TRANSLATED output path (an identity token that doubles as the
    lockfile's own name survives in the filename precisely because the
    output is excluded from the rename pass).
    """
    problems: list[str] = []
    source_scope = _reverse_output_path(translated_rel, renames, table)
    if table is not None:
        # scan = "boundary" swaps the CONTENT hunt's matcher inside
        # matching_hunts: hash noise (substring hit, no boundary hit) drops
        # out, while separator/case variants the boundary matcher sees stay
        # caught (PROBLEM-22, plbp dogfood run 4).
        for row, policy in matching_hunts(
            table,
            consumer="regeneration",
            surface="content",
            text=text,
            source_scope_path=source_scope,
            boundary_identity=scan_mode == "boundary",
        ):
            if row.provenance[0].kind == "replace_rule":
                problems.append(
                    f"output contains rendered [[replace]] literal "
                    f"{row.from_value!r} ({row.provenance[0].reason})"
                )
            else:
                field = policy.matcher.identity_field or row.provenance[0].name
                substring = policy.matcher.substring and scan_mode != "boundary"
                spans = find_occurrences(
                    text,
                    field,
                    row.from_value,
                    substring=substring,
                )
                if not spans:
                    continue
                problems.append(
                    f"output still carries source {field} {row.from_value!r} "
                    f"({len(spans)} occurrence(s))"
                )
        for row, policy in matching_hunts(
            table,
            consumer="regeneration",
            surface="path",
            text=translated_rel,
            source_scope_path=source_scope,
        ):
            if row.provenance[0].kind == "replace_rule":
                problems.append(
                    f"its path ({translated_rel}) carries rendered [[replace]] "
                    f"literal {row.from_value!r} ({row.provenance[0].reason})"
                )
            else:
                field = policy.matcher.identity_field or row.provenance[0].name
                problems.append(
                    f"its path ({translated_rel}) carries source {field} "
                    f"{row.from_value!r} — downstream inventories never look "
                    f"at an excluded filename"
                )
        return problems
    for field, value in changed_identity_pairs(source, dest):
        substring = field in rules.substring_rewrite_fields
        content_substring = substring and scan_mode != "boundary"
        spans = find_occurrences(text, field, value, substring=content_substring)
        if spans:
            problems.append(
                f"output still carries source {field} {value!r} "
                f"({len(spans)} occurrence(s))"
            )
        if find_occurrences(translated_rel, field, value, substring=substring):
            problems.append(
                f"its path ({translated_rel}) carries source {field} "
                f"{value!r} — downstream inventories never look at an "
                f"excluded filename"
            )
    effective_rules = (
        rendered_replace_rules(rules, source, dest)
        if rendered_rules is None
        else rendered_rules
    )
    for rule, frm, _to in effective_rules:
        if rule.content and rule_matches_path(rule, source_scope) and frm in text:
            problems.append(
                f"output contains rendered [[replace]] literal {frm!r} ({rule.reason})"
            )
        if (
            rule.paths
            and rule_matches_path(rule, source_scope)
            and frm in translated_rel
        ):
            problems.append(
                f"its path ({translated_rel}) carries rendered [[replace]] "
                f"literal {frm!r} ({rule.reason})"
            )
    return problems


def _postcondition_problems(
    target: Path,
    translated_rel: str,
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
    renames: Mapping[str, str],
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
    scan_mode: str = "strict",
) -> list[str]:
    """Existence, type, containment, UTF-8, and the paranoid scan — what a
    command must leave behind to have regenerated anything at all (D3)."""
    path = target / translated_rel
    try:
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
    except SafetyError as exc:
        return [str(exc)]
    if not is_regular_lstat(path):
        return [
            f"{translated_rel} is not a regular file after the command "
            f"(deleted, symlink, or special — a declared regeneration that "
            f"does not leave its file behind is a failed regeneration)"
        ]
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [
            f"{translated_rel} is not valid UTF-8 after the command — the "
            f"exemption is bought with the text scan, fail closed"
        ]
    return scan_regenerated_output(
        text,
        translated_rel,
        source=source,
        dest=dest,
        rules=rules,
        renames=renames,
        rendered_rules=rendered_rules,
        table=table,
        scan_mode=scan_mode,
    )


def final_validation_pass(
    target: Path,
    plans: Sequence[RegenerationPlan],
    resets: Sequence[tuple[ResetRule, str]],
    renames: Mapping[str, str],
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
) -> list[str]:
    """After the LAST declared command: re-validate EVERY output and reset
    stub (D3). Per-command postconditions are not enough once a target
    declares multiple regenerations — a later command can delete, replace,
    or reintroduce source identity into an earlier output, or modify a
    reset stub, after that output's own checks passed, and these files stay
    excluded from the ordinary doctor and hermetic-verify inventories.
    """
    problems: list[str] = []
    for plan in plans:
        translated = _translate_output_path(plan.rule.file, renames, table)
        for problem in _postcondition_problems(
            target,
            translated,
            source=source,
            dest=dest,
            rules=rules,
            renames=renames,
            rendered_rules=rendered_rules,
            table=table,
            scan_mode=plan.rule.scan,
        ):
            problems.append(f"final pass: {plan.rule.file}: {problem}")
    for rule, stub in resets:
        # Reset paths were consumed in SOURCE coordinates before the rename
        # pass; this check runs after it, so translate — validating the
        # declared path would report a validly moved stub as missing. The
        # full guard set runs BEFORE the content compare: stub equality
        # alone would follow a symlink a later command planted and accept
        # matching outside content.
        translated = _translate_output_path(rule.file, renames, table)
        path = target / translated
        prefix = f"final pass: reset {rule.file}: "
        try:
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if not is_regular_lstat(path):
            problems.append(
                prefix + f"{translated} is not a regular file after the "
                f"declared commands (no-follow check)"
            )
            continue
        if path.read_bytes() != stub.encode("utf-8"):
            problems.append(
                prefix + f"stub content at {translated} was modified after "
                f"the reset — a later command altered it"
            )
    return problems


@dataclass(frozen=True)
class GitVisibilityState:
    """Git policy and index facts that determine the doctor's scan surface."""

    exclusion_inputs: tuple[VisibilityInput, ...]
    config_inputs: tuple[GitConfigInput, ...]
    config_effective_sha256: str
    index_entries: tuple[tuple[Path, IndexKind], ...]


def snapshot_visibility_state(target: Path) -> GitVisibilityState:
    """Fingerprint effective Git visibility before the first command runs."""

    snapshot = capture_surface_snapshot(target)
    index_entries = tuple(
        (entry.rel, entry.index_kind)
        for entry in snapshot.entries
        if entry.tracked and entry.index_kind is not None
    )
    return GitVisibilityState(
        snapshot.visibility_inputs,
        snapshot.git_config_inputs,
        snapshot.git_config_effective_sha256,
        index_entries,
    )


def validate_visibility_state(target: Path, snapshot: GitVisibilityState) -> list[str]:
    """Refuse command-phase changes to the Git visibility state."""

    try:
        current = snapshot_visibility_state(target)
    except (OSError, subprocess.CalledProcessError, SafetyError) as exc:
        return [
            "effective Git visibility could not be revalidated after declared "
            f"commands: {exc}"
        ]
    if current == snapshot:
        return []
    return [
        "effective Git visibility changed during declared commands — restore the "
        "target's ignore policy, repository config, and index before re-running. "
        "Make intentional Git visibility changes in a separate commit"
    ]


def snapshot_control_files(target: Path) -> dict[str, bytes | None]:
    """Presence + content of every press-owned control file (ROOT_CONTROL),
    taken before the FIRST declared command runs.

    Reservation alone is not protection (D1): a declared command can mutate
    arbitrary files, and ROOT_CONTROL is omitted from the downstream doctor
    and verifier inventories — so press snapshots what it owns and
    revalidates after the last command.
    """
    snapshot: dict[str, bytes | None] = {}
    for rel in sorted(ROOT_CONTROL):
        path = target / rel
        snapshot[rel] = path.read_bytes() if is_regular_lstat(path) else None
    return snapshot


def restore_control_files(target: Path, snapshot: Mapping[str, bytes | None]) -> None:
    """Put every press-owned control file back to its pre-command state —
    including REMOVING one a failed command created: a planted
    press-receipt.toml surviving a failed press would advertise a verified
    target the press never certified.
    """
    for rel, data in snapshot.items():
        path = target / rel
        try:
            # Never traverse a symlinked control dir during recovery
            # (codex 3654974418): a command that swapped press/ for a
            # symlink must not turn restoration into an outside deletion.
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
        except SafetyError:
            continue  # best-effort recovery; validation already reported
        if data is None:
            path.unlink(missing_ok=True)
        elif not is_regular_lstat(path) or path.read_bytes() != data:
            safe_write(target, rel, data, refuse_hardlink=False)


def validate_control_files(
    target: Path, snapshot: Mapping[str, bytes | None]
) -> list[str]:
    """Type, containment, and content revalidation against the snapshot —
    a mismatch aborts the press: the rules that ran are no longer the rules
    that were planned and validated (D1)."""
    problems: list[str] = []
    for rel, before in snapshot.items():
        path = target / rel
        try:
            assert_under_root(path, target)
        except SafetyError as exc:
            problems.append(f"control file {rel}: {exc}")
            continue
        if os.path.lexists(path) and not is_regular_lstat(path):
            problems.append(
                f"control file {rel} is no longer a regular file — a "
                f"declared command replaced it"
            )
            continue
        now = path.read_bytes() if is_regular_lstat(path) else None
        if now != before:
            problems.append(
                f"control file {rel} changed during regeneration — the "
                f"rules that ran are no longer the rules that were planned "
                f"and validated"
            )
    return problems
