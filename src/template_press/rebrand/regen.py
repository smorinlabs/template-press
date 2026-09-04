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
    EditRule,
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


@dataclass(frozen=True)
class EditPlan:
    """One declared in-place edit, resolved exactly as a regeneration is (E4).

    Same three resolved facts, same guarantees: the pinned executable is what
    will launch, and the declared env names are split by whether the
    operator's environment actually carries them.
    """

    rule: EditRule
    executable: str  # the pinned absolute path that will actually launch
    env_present: tuple[str, ...]  # declared names that WILL apply
    env_absent: tuple[str, ...]  # declared names absent from the operator env


@dataclass(frozen=True)
class _CommandResolution:
    """The plan-time facts shared by every declared-command mechanism."""

    executable: str
    env_present: tuple[str, ...]
    env_absent: tuple[str, ...]


def _resolve_declared_command(
    target: Path,
    *,
    kind: str,
    file: str,
    command: Sequence[str],
    env: Sequence[str],
    renamed: Collection[str],
    ambient: Mapping[str, str],
) -> _CommandResolution | str:
    """Resolve one declaration, or return the problem text that refuses it.

    Shared verbatim by [[regenerate]] and [[edit]] so the two mechanisms
    cannot drift in what they pin, what they refuse, or how they say so;
    ``kind`` is the only difference the operator sees.
    """
    stale = stale_argv_elements(command, renamed)
    if stale:
        return (
            f"{kind} {file}: argv element(s) "
            f"{', '.join(repr(s) for s in stale)} name path(s) this press "
            f"renames — they would go stale mid-press; write the command "
            f"rename-independent (it runs from the target root, so cwd "
            f"carries the location)"
        )
    effective = command_env(env, base_env=ambient)
    resolved = resolve_executable(target, command[0], effective)
    if resolved is None:
        where = (
            "relative to the target root"
            if "/" in command[0].replace("\\", "/")
            else "on PATH under the deny-by-default environment"
        )
        return (
            f"{kind} {file}: executable {command[0]!r} not "
            f"found {where} — install it or fix the declaration "
            f"(`press check-tools` reports every declared tool)"
        )
    return _CommandResolution(
        executable=str(resolved),
        env_present=tuple(n for n in env if n in ambient),
        env_absent=tuple(n for n in env if n not in ambient),
    )


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
        resolution = _resolve_declared_command(
            target,
            kind="regenerate",
            file=rule.file,
            command=rule.command,
            env=rule.env,
            renamed=renamed,
            ambient=ambient,
        )
        if isinstance(resolution, str):
            problems.append(resolution)
            continue
        plans.append(
            RegenerationPlan(
                rule=rule,
                executable=resolution.executable,
                env_present=resolution.env_present,
                env_absent=resolution.env_absent,
            )
        )
    return plans, problems


def plan_edits(
    target: Path,
    edit: Sequence[EditRule],
    *,
    renamed: Collection[str],
    base_env: Mapping[str, str] | None = None,
) -> tuple[list[EditPlan], list[str]]:
    """Resolve every declared in-place edit at plan time (E4); problems refuse.

    The regeneration planner's contract, unchanged: a missing tool or a
    stale path-bearing argv refuses with exit 2 and nothing written, before
    the rewrite pass the edit would have amended.
    """
    ambient = os.environ if base_env is None else base_env
    plans: list[EditPlan] = []
    problems: list[str] = []
    for rule in edit:
        resolution = _resolve_declared_command(
            target,
            kind="edit",
            file=rule.file,
            command=rule.command,
            env=rule.env,
            renamed=renamed,
            ambient=ambient,
        )
        if isinstance(resolution, str):
            problems.append(resolution)
            continue
        plans.append(
            EditPlan(
                rule=rule,
                executable=resolution.executable,
                env_present=resolution.env_present,
                env_absent=resolution.env_absent,
            )
        )
    return plans, problems


def _run_declared(
    target: Path,
    plan: RegenerationPlan | EditPlan,
    *,
    kind: str,
    renames: Mapping[str, str],
    report: ApplyReport,
    source: Identity,
    dest: Identity,
    rules: Rules,
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None,
    table: SubstitutionTable | None,
    scan_mode: str,
    expect: str | None,
) -> bool:
    """Run ONE declared command under the full contract; True when it held.

    Shared verbatim by [[regenerate]] and [[edit]] — the execution contract is
    the part neither mechanism may drift on. ``kind`` is the only difference
    the operator sees in ``report.skipped``; ``scan_mode`` and ``expect`` are
    the only behavioral knobs.
    """
    rule = plan.rule
    out_rel = _translate_output_path(rule.file, renames, table)
    out_path = target / out_rel
    try:
        assert_under_root(out_path, target)
        assert_ancestors_real(out_path, target)
    except SafetyError as exc:
        report.skipped.append(f"{kind} {rule.file} (sink guard: {exc})")
        return False
    if not is_regular_lstat(out_path):
        report.skipped.append(
            f"{kind} {rule.file} (sink guard: {out_rel} is not a "
            f"regular file — no-follow check)"
        )
        return False
    if os.lstat(out_path).st_nlink > 1:
        report.skipped.append(
            f"{kind} {rule.file} (sink guard: {out_rel} is hardlinked)"
        )
        return False
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
            f"{kind} {rule.file} (command exited {result.returncode})"
        )
        return False
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
        scan_mode=scan_mode,
        expect=expect,
    )
    if problems:
        report.skipped.extend(f"{kind} {rule.file} ({problem})" for problem in problems)
        return False
    return True


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
        if _run_declared(
            target,
            plan,
            kind="regenerate",
            renames=renames,
            report=report,
            source=source,
            dest=dest,
            rules=rules,
            rendered_rules=rendered_rules,
            table=table,
            scan_mode=plan.rule.scan,
            expect=None,
        ):
            report.regenerated.append(plan.rule.file)
        else:
            failed.append(plan.rule.file)
    return failed


def execute_edits(
    target: Path,
    plans: Sequence[EditPlan],
    renamed: Mapping[str, str],
    report: ApplyReport,
    *,
    source: Identity,
    dest: Identity,
    rules: Rules,
    rendered_rules: Sequence[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
) -> list[str]:
    """Run every declared in-place edit (E4); return the FAILED files.

    The regeneration executor's contract in full — same cwd, same absent
    shell, same deny-by-default env, same pinned executable, same sink
    guards before each launch — with two differences that follow from what
    an edit IS. It amends a file the replace pass has already rewritten, so
    the scan is always ``strict`` (there is no ``scan`` key to relax it and
    no exemption to buy); and it must leave the declaration's ``expect``
    substring behind, which is the only thing that catches a command that
    exits 0 and does nothing.

    Success is deliberately NOT recorded in ``report.regenerated``: that
    list drives the receipt's ``[[press.exempt]]`` rows, and an edited file
    stays wholly inside the doctor's and ``press verify``'s scan surface.
    """
    failed: list[str] = []
    renames = dict(renamed)
    for plan in plans:
        if not _run_declared(
            target,
            plan,
            kind="edit",
            renames=renames,
            report=report,
            source=source,
            dest=dest,
            rules=rules,
            rendered_rules=rendered_rules,
            table=table,
            scan_mode="strict",
            expect=plan.rule.expect,
        ):
            failed.append(plan.rule.file)
    return failed


def _render_command_section(
    heading: str,
    tag: str,
    plans: Sequence[RegenerationPlan | EditPlan],
) -> str:
    """One declared-command plan section: verbatim argv, pinned executable,
    and the declared env names (marking which would actually apply) — plan
    visibility is the approval guard, so this must show what will launch.

    ``tag`` is the seven-character row label ("regen  " / "edit   ") that
    keeps every row of every section aligned under one another.
    """
    lines = [heading]
    for plan in plans:
        lines.append(f"  [{tag}] {plan.rule.file}  —  {shlex.join(plan.rule.command)}")
        lines.append(f"            executable: {plan.executable}")
        if plan.rule.env:
            marks = [
                name if name in plan.env_present else f"{name} (absent)"
                for name in plan.rule.env
            ]
            lines.append(f"            env: {', '.join(marks)}")
    return "\n".join(lines)


def render_regenerate_plan(plans: Sequence[RegenerationPlan]) -> str:
    """The plan's regeneration section (rendered AFTER the edit section, the
    order the two phases actually run in)."""
    return _render_command_section(
        "Regenerate (declared commands, run after apply):", "regen  ", plans
    )


def render_edit_plan(plans: Sequence[EditPlan]) -> str:
    """The plan's in-place-edit section (E4). The heading names the phase
    slot explicitly: edits amend what apply() wrote, and every edit runs
    before every regeneration."""
    return _render_command_section(
        "Edit (declared in-place edits, run after apply, before regenerations):",
        "edit   ",
        plans,
    )


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


def preflight_edit_targets(target: Path, rules: Rules) -> list[str]:
    """Problems that make a declared [[edit]] target unpressable (E4).

    The regeneration preflight's state gate, applied to edit targets:
    containment, git-tracked, clean, no-follow regular file, sole link.
    Every one of those reasons holds identically here — the declared command
    rewrites the file in place, and git restores only committed content, so
    an untracked or dirty target has no recoverable copy, and an in-place
    truncating editor on a hardlinked target would corrupt the external
    inode. Refused even under ``--allow-dirty``; this function takes no such
    flag at all, so the refusal is structural.

    The ONE regeneration check deliberately absent is the UTF-8 pre-state
    gate: that one exists to stop a file the text scan cannot read from
    buying the verify exemption, and an edit target never buys it — it stays
    in the doctor's and ``press verify``'s surface either way. The edit
    target is also NOT excluded from the rewrite pass, so unlike a
    regeneration output it is rewritten first and edited second.
    """
    if not rules.edit:
        return []
    problems: list[str] = []
    tracked = tracked_paths(target)
    for rule in rules.edit:
        prefix = f"edit target {rule.file}: "
        path = target / rule.file
        try:
            assert_under_root(path, target)
        except SafetyError as exc:
            problems.append(prefix + str(exc))
            continue
        if rule.file not in tracked:
            problems.append(
                prefix + "not git-tracked (edit targets must be committed so "
                "git provides the undo path)"
            )
            continue
        if not is_regular_lstat(path):
            problems.append(prefix + "not a regular file (no-follow check)")
            continue
        st = os.lstat(path)
        if st.st_nlink > 1:
            problems.append(
                prefix + f"hardlinked (st_nlink={st.st_nlink}) — an in-place "
                f"editor would corrupt the external inode"
            )
            continue
        if has_uncommitted_changes(target, rule.file):
            problems.append(
                prefix + "has uncommitted changes — refused even under "
                "--allow-dirty (git restores only committed content)"
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
    expect: str | None = None,
) -> list[str]:
    """Existence, type, containment, UTF-8, and the paranoid scan — what a
    command must leave behind to have regenerated anything at all (D3).

    ``expect`` adds [[edit]]'s extra post-condition (E4): the declared literal
    substring must be present in the decoded text. It is collected ALONGSIDE
    the identity scan rather than short-circuiting it, so one failed edit
    reports every reason it failed instead of only the first.
    """
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
    problems: list[str] = []
    if expect is not None and expect not in text:
        problems.append(
            f"{translated_rel} does not contain the declared expect string "
            f"{expect!r} after the command — the command exited 0 but left "
            f"the file unchanged in the way the declaration promised"
        )
    return problems + scan_regenerated_output(
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
    edits: Sequence[EditPlan] = (),
) -> list[str]:
    """After the LAST declared command: re-validate EVERY output, edit, and
    reset stub (D3). Per-command postconditions are not enough once a target
    declares multiple commands — a later command can delete, replace,
    or reintroduce source identity into an earlier output, or modify a
    reset stub, after that output's own checks passed, and these files stay
    excluded from the ordinary doctor and hermetic-verify inventories.

    Edits are rechecked with their ``expect`` (E4): edits run before every
    regeneration, so a later regeneration undoing an earlier edit is exactly
    the ordering this pass exists to catch. An edited file IS in the doctor's
    surface, but the doctor knows nothing of ``expect``.
    """
    problems: list[str] = []
    for edit in edits:
        translated = _translate_output_path(edit.rule.file, renames, table)
        for problem in _postcondition_problems(
            target,
            translated,
            source=source,
            dest=dest,
            rules=rules,
            renames=renames,
            rendered_rules=rendered_rules,
            table=table,
            expect=edit.rule.expect,
        ):
            problems.append(f"final pass: edit {edit.rule.file}: {problem}")
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
        + _visibility_delta(target, snapshot, current)
    ]


def _visibility_delta(
    target: Path, before: GitVisibilityState, after: GitVisibilityState
) -> str:
    """The ``; changed: …`` clause naming what actually moved, or "".

    Without it the refusal is undiagnosable: an operator told only that
    "visibility changed" has to bisect the declared commands to learn which
    of three surfaces (ignore policy, repository config, index) one of them
    touched, and which file inside it.
    """
    changed: list[str] = []
    ignore_before = {i.path: i for i in before.exclusion_inputs}
    ignore_after = {i.path: i for i in after.exclusion_inputs}
    changed += [
        repr(_relative_to(target, path))
        for path in sorted(set(ignore_before) | set(ignore_after))
        if ignore_before.get(path) != ignore_after.get(path)
    ]
    config_before = {c.path: c for c in before.config_inputs}
    config_after = {c.path: c for c in after.config_inputs}
    changed += [
        repr(_relative_to(target, path))
        for path in sorted(set(config_before) | set(config_after))
        if config_before.get(path) != config_after.get(path)
    ]
    if before.config_effective_sha256 != after.config_effective_sha256:
        changed.append("effective git config")
    if before.index_entries != after.index_entries:
        changed.append("the git index")
    return f"; changed: {', '.join(changed)}" if changed else ""


def _relative_to(target: Path, path: Path) -> str:
    """A target-relative POSIX spelling when the path is inside it."""
    try:
        return path.relative_to(target).as_posix()
    except ValueError:
        return str(path)


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


def restore_control_files(
    target: Path, snapshot: Mapping[str, bytes | None]
) -> list[str]:
    """Put every press-owned control file back to its pre-command state —
    including REMOVING one a failed command created: a planted
    press-receipt.toml surviving a failed press would advertise a verified
    target the press never certified.

    Recovery is best-effort per entry and never raises: a hostile command can
    replace one absent control path with a directory or otherwise make that
    path unrestorable. That failure must not mask the command failure that
    triggered recovery, and it must not prevent later entries from being
    restored. Returned problems make every incomplete recovery explicit.
    """
    problems: list[str] = []
    for rel, data in snapshot.items():
        path = target / rel
        try:
            # Never traverse a symlinked control dir during recovery
            # (codex 3654974418): a command that swapped press/ for a
            # symlink must not turn restoration into an outside deletion.
            assert_under_root(path, target)
            assert_ancestors_real(path, target)
            if data is None:
                path.unlink(missing_ok=True)
            elif not is_regular_lstat(path) or path.read_bytes() != data:
                safe_write(target, rel, data, refuse_hardlink=False)
        except (OSError, SafetyError) as exc:
            problems.append(f"control file {rel} could not be restored: {exc!r}")
    return problems


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
