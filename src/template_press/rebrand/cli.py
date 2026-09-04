"""press rebrand — point the press at a target repo (ARCH-01).

Pipeline: preconditions → answers → source identity (config-first,
discovery validates) → plan → [--dry-run stops here] → apply → regenerate
lockfiles → VERIFY (no-leak doctor) → receipt. Exit codes: 0 ok, 1 leaks
found after apply (no receipt), 2 precondition/config error (no writes).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess  # nosec B404 — invokes git/uv on user-supplied targets
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.discovery import Discovered, discover, mismatches
from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import (
    RenamePreflight,
    apply,
    build_plan,
    preflight_rename_noreplace,
    stray_press_dirs,
    translate_path,
)
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
)
from template_press.rebrand.receipt import (
    RECEIPT_REL,
    OriginDecision,
    invalidate_receipt,
    read_receipt,
    removed_files_from_receipt,
    write_receipt,
)
from template_press.rebrand.regen import (
    EditPlan,
    RegenerationPlan,
    execute_edits,
    execute_regenerations,
    final_validation_pass,
    plan_edits,
    plan_regenerate_commands,
    preflight_edit_targets,
    preflight_excluded_files,
    preflight_regenerate_outputs,
    render_edit_plan,
    render_regenerate_plan,
    restore_control_files,
    snapshot_control_files,
    snapshot_visibility_state,
    validate_control_files,
    validate_visibility_state,
)
from template_press.rebrand.remove import (
    apply_removals,
    preflight_remove_targets,
    remove_regen_conflicts,
    render_remove_plan,
)
from template_press.rebrand.reset import (
    apply_resets,
    preflight_reset_targets,
    render_reset_plan,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    ReplaceRule,
    ResetRule,
    Rules,
    load_selected_rules,
)
from template_press.rebrand.safety import (
    RenameClosureUnauthorized,
    SafetyError,
    git_hardening_args,
    scrubbed_git_env,
    write_control,
)
from template_press.rebrand.substitutions import (
    SubstitutionTable,
    declared_rule_triples,
    revalidate_substitution_table,
    validate_reset_visibility,
)


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _shell_join(argv: list[str]) -> str:
    """Render `argv` as a copy-pasteable shell command for this platform."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _partial_rewrite_restore_hint(target: Path) -> str:
    """Shared restoration guidance for a mid-mutation `_press()` failure.

    Used by both the generic catch-all message and the
    `RenameClosureUnauthorized` branch, which prints its own aggregated
    findings + remedy first and then appends this same hint.
    """
    checkout = _shell_join(["git", "-C", str(target), "checkout", "--", "."])
    clean = _shell_join(["git", "-C", str(target), "clean", "-fd"])
    return f"target may be PARTIALLY rewritten; restore with `{checkout} && {clean}`"


def _report_control_restore_problems(problems: list[str]) -> None:
    """Report best-effort recovery failures without masking the root failure."""
    if not problems:
        return
    print(
        "error: press-owned control-file restoration incomplete:",
        file=sys.stderr,
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)


def _empty_dir_paths(exc: RenameClosureUnauthorized) -> list[str]:
    """Sorted ``empty-dir`` finding paths from `exc` (E2).

    ``git clean -fdX`` (the remedy `remedy_argv` prints) cannot remove these:
    ``-X`` only removes IGNORED paths, and an uninventoried empty directory
    is by definition unignored (nothing in it for `.gitignore` to match) —
    so each needs its own `rmdir`.

    Stays repo-relative here: the `--diagnostics-json` payload's
    ``rmdir_paths`` renders this return value as-is (a machine consumer
    joins it with its own known target root), while the prose remedy
    (`_print_closure_refusal_prose`) renders each path through `target /
    path` so the printed `rmdir` command works from any caller cwd.
    """
    return sorted(path for kind, path in exc.findings if kind == "empty-dir")


def _print_closure_refusal_prose(
    exc: RenameClosureUnauthorized, target: Path, rules: Rules
) -> None:
    """Print the E2 aggregated findings + remedy argv as prose (stdout).

    Shared by both catch sites: the plan-time refusal (exit 2, "nothing
    written") and the apply-time revalidation refusal (exit 1, "partially
    rewritten") — the message and remedy are identical; only the exit code
    and surrounding context differ by call site.
    """
    preview, remove = exc.remedy_argv(target)
    print(str(exc))
    print(f"preview: {_shell_join(preview)}")
    print(f"remove:  {_shell_join(remove)}")
    print(
        "(destructive, and broader than the paths listed — run only if "
        "the preview shows nothing you keep)"
    )
    empty_dirs = _empty_dir_paths(exc)
    if empty_dirs:
        cap = 20
        prefix_abs = target / exc.source_prefix
        for path in empty_dirs[:cap]:
            leaf = target / path
            if sys.platform == "win32":
                argv = ["rmdir", str(leaf)]
            else:
                argv = ["rmdir", "--", str(leaf)]
            print(_shell_join(argv))
            print(f"  # then rmdir each newly-empty parent up to {prefix_abs}")
        if len(empty_dirs) > cap:
            print(f"  … ({len(empty_dirs) - cap} more)")
    if getattr(rules, "clean", ()):
        print(f"declared clean rules exist — run: press clean --target {target}")


def _report_closure_refusal(
    exc: RenameClosureUnauthorized, target: Path, rules: Rules, diagnostics_json: bool
) -> int:
    """Print the E2 remedy (or `--diagnostics-json` payload) and return 2.

    Plan-time only (see docstring on `_print_closure_refusal_prose` for the
    apply-time counterpart, which never emits JSON and returns 1).
    """
    if diagnostics_json:
        preview, remove = exc.remedy_argv(target)
        payload = {
            "schema": 1,
            "code": exc.code,
            "source_prefix": exc.source_prefix,
            "findings": [{"kind": kind, "path": path} for kind, path in exc.findings],
            "total": exc.total,
            "truncated": exc.truncated,
            "phase": exc.phase,
            "preview_argv": preview,
            "remove_argv": remove,
            "rmdir_paths": _empty_dir_paths(exc),
        }
        print(json.dumps(payload, ensure_ascii=True))
        return 2
    _print_closure_refusal_prose(exc, target, rules)
    return 2


def check_preconditions(target: Path, force: bool, allow_dirty: bool) -> str | None:
    """Return an error message, or None when the target is pressable."""
    if not target.is_dir():
        return f"target does not exist or is not a directory: {target}"
    if not (target / ".git").exists():
        return f"target is not a git repository: {target}"
    if read_receipt(target) is not None and not force:
        return (
            "target already has a press receipt (press/press-receipt.toml); "
            "re-press with --force"
        )
    if not allow_dirty:
        # A working-tree read on an untrusted target: hardening args
        # neutralize fsmonitor/hooksPath/ext-transport, but a repo-local
        # clean/smudge FILTER definition is a documented residual
        # (git_hardening_args' docstring) that `-c` cannot disable by name —
        # accepted here, not solved.
        status = subprocess.run(  # noqa: S603 # nosec B603 B607
            [  # noqa: S607
                "git",
                "-C",
                str(target),
                *git_hardening_args(),
                "status",
                "--porcelain",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=scrubbed_git_env(),
        )
        if status.stdout.strip():
            return "target working tree is dirty; commit/stash or --allow-dirty"
    return None


def _relax_origin_guard(
    source: Identity,
    found: Discovered,
    dest: Identity | None,
    problems: list[str],
    accept_origin_mismatch: bool,
) -> tuple[list[str], OriginDecision]:
    """Relax the source-identity guard for the `origin` remote (E1).

    Two passes, in this order, over `owner` and `repo_name` only — never
    over the pyproject-derived fields, which still exit 2 whatever the
    operator asked for:

    1. **Origin already names the DESTINATION.** A discovered value that
       disagrees with the source-config is accepted iff it equals the
       destination's value for that SAME field — the gh-created clone whose
       origin was repointed before the press ran. Comparison is exact, so a
       case-different origin falls through to pass 2.
    2. **`--accept-origin-mismatch`.** Whatever still disagrees (origin
       names neither identity) is accepted only when the operator passed
       the flag.

    Destination-equality is tried first, so a field lands in at most one of
    the decision's two lists. Without the flag, an origin naming neither
    identity still exits 2.

    The decision is only RECORDED here; `_render_origin_notices` and
    `_render_origin_mismatch_warnings` announce it once the run is past
    every plan-time gate. Announcing it here would put a `notice:`/
    `warning:` line on stdout ahead of a later refusal — including the
    `--diagnostics-json` payload, whose contract is that the JSON object is
    the whole of stdout.
    """
    if dest is None or not problems:
        return problems, OriginDecision()
    declared = source.as_dict()
    relaxed: list[str] = []
    accepted: list[tuple[str, str]] = []
    for field_name in ("owner", "repo_name"):
        discovered_value = getattr(found, field_name)
        if discovered_value is None or discovered_value == declared[field_name]:
            continue
        if discovered_value == getattr(dest, field_name):
            relaxed.append(field_name)
        elif accept_origin_mismatch:
            # The EXACT value, not just the field name: it is what the
            # receipt records and what lets `press verify` waive this one
            # acceptance without waiving whatever `origin` says next.
            accepted.append((field_name, discovered_value))
        else:
            continue
        problems = [p for p in problems if not p.startswith(f"{field_name}: ")]
    return problems, OriginDecision(
        named_destination=tuple(sorted(relaxed)),
        mismatch_accepted=tuple(sorted(accepted)),
    )


def _render_origin_notices(
    origin: OriginDecision, source: Identity, dest: Identity
) -> list[str]:
    """One notice line per field the origin guard relaxed (E1).

    The origin value is the destination's value for that field — equality
    with it is what the relaxation tested — so the line is reconstructible
    from the two identities alone.
    """
    return [
        f"notice: {field_name}: origin already names the destination "
        f"({getattr(dest, field_name)!r}); source-config says "
        f"{getattr(source, field_name)!r} — accepted"
        for field_name in origin.named_destination
    ]


def _render_origin_mismatch_warnings(
    origin: OriginDecision, source: Identity, dest: Identity, found: Discovered
) -> list[str]:
    """One warning line per field accepted under `--accept-origin-mismatch`.

    The repository's value is a third value — equal to neither identity —
    so it is read from the discovery result rather than reconstructed. It is
    also the one value here that was never validated (it comes straight from
    `.git/config`), so it is rendered with `repr`, which escapes control
    characters and leaves an ordinary value quoted exactly as before.
    """
    return [
        f"warning: {field_name}: source-config "
        f"{getattr(source, field_name)!r}, repository "
        f"{getattr(found, field_name)!r}, destination "
        f"{getattr(dest, field_name)!r} — proceeding on --accept-origin-mismatch"
        for field_name, _ in origin.mismatch_accepted
    ]


def _resolve_source(
    target: Path,
    override: Path | None,
    accept_discovery: bool,
    dest: Identity | None,
    accept_origin_mismatch: bool,
) -> tuple[Identity, bool, OriginDecision, Discovered] | int:
    """Resolve the FROM identity; second element = write source-config later.

    The write is DEFERRED to main() so it happens only after every exit-2
    gate has passed — keeping "exit 2 means no writes" true by construction.
    The discovery result is returned so the origin warnings can name the
    repository's own value.
    """
    write_pending = False
    source = load_source_config(target, override)
    found = discover(target)
    if source is None:
        proposal = {
            "package_name": found.package_name,
            "repo_name": found.repo_name,
            "app_name": found.app_name,
            "author": found.author,
            "email": found.email,
            "owner": found.owner,
        }
        unresolved = [k for k, v in proposal.items() if v is None]
        if unresolved:
            return _fail(
                f"no source-config at {SOURCE_CONFIG_REL} and discovery "
                f"could not resolve: {', '.join(unresolved)}. Write the "
                f"source-config by hand."
            )
        try:
            candidate = Identity.from_mapping(
                {k: v for k, v in proposal.items() if v is not None}
            )
            candidate.validate()
        except ValidationError as exc:
            return _fail(f"discovered identity is invalid: {exc}")
        source = candidate
        write_pending = True
    problems, origin = _relax_origin_guard(
        source, found, dest, mismatches(source, found), accept_origin_mismatch
    )
    if problems:
        print(
            "error: source-config does not match the target "
            "(refusing to press — this is the silent-half-rebrand guard):",
        )
        for p in problems:
            print(f"  {p}")
        return 2
    return source, write_pending, origin, found


def display_name_problem(source: Identity, dest: Identity) -> str | None:
    """Half-specified display identity is refused (codesign sec-06).

    The press knows what to erase but not what to write — proceeding would
    ship a half-rebrand where every prose mention keeps the old product
    name. The reverse direction is harmless: nothing to rewrite, and the
    post-apply source-config write records the new display name.
    """
    if source.display_name is not None and dest.display_name is None:
        return (
            f"source-config declares display_name "
            f"({source.display_name!r}) but the answers file does not — "
            f"add display_name to [answers]; press cannot know the new "
            f"display name"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press rebrand", description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="answers TOML (TO identity)")
    parser.add_argument("--source-config", type=Path, dest="source_config")
    parser.add_argument("--accept-discovery", action="store_true")
    parser.add_argument(
        "--accept-origin-mismatch",
        action="store_true",
        dest="accept_origin_mismatch",
        help=(
            "proceed when origin's owner/repo_name match neither the "
            "source-config nor the destination; prints each mismatch and "
            "records it in the receipt. Never covers pyproject-derived fields."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "override safety guards, including an existing receipt or "
            "unavailable atomic rename support"
        ),
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--diagnostics-json",
        action="store_true",
        help=(
            "on a structured refusal, print a JSON diagnostic instead of "
            "prose; exit code unchanged"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show the bounded reset content excerpts in the plan",
    )
    args = parser.parse_args(argv)

    target = args.target.resolve()
    try:
        problem = check_preconditions(target, args.force, args.allow_dirty)
        if problem is not None:
            return _fail(problem)

        # The answers file is read BEFORE the guard so the guard can ask
        # whether origin already names the destination (E1). It is a pure
        # read: the only write in this function stays deferred behind every
        # exit-2 gate, so "exit 2 means no writes" is unaffected. A malformed
        # answers file now reports before the guard does.
        dest = load_answers(args.config) if args.config is not None else None

        resolved = _resolve_source(
            target,
            args.source_config,
            args.accept_discovery,
            dest,
            args.accept_origin_mismatch,
        )
        if isinstance(resolved, int):
            return resolved
        source, write_pending, origin, found = resolved
        if write_pending and not args.accept_discovery:
            print(
                f"no source-config found at {SOURCE_CONFIG_REL}.\n"
                f"Discovery proposes:\n\n{render_source_config(source)}\n"
                f"Save it there (and commit), or re-run with "
                f"--accept-discovery to write + use it.",
            )
            return 2

        if dest is None:
            return _fail("--config ANSWERS.toml is required")

        display_problem = display_name_problem(source, dest)
        if display_problem is not None:
            return _fail(display_problem)

        if source == dest:
            message = (
                "source and destination identities are identical — nothing to press"
            )
            if read_receipt(target) is None:
                # A press that rewrote press-source.toml but died before its
                # receipt landed leaves exactly this state: the target already
                # declares the DESTINATION while nothing records a completed
                # press, so a plain retry stops here with nothing to do. Name
                # the restore path rather than leaving the operator to infer
                # it from a message about identical identities.
                message += (
                    f"\nno receipt either: an interrupted press may have left "
                    f"this state — {_partial_rewrite_restore_hint(target)}, "
                    f"then press again"
                )
            return _fail(message)
        # Pipeline stability, ambiguity, and termination are validated together
        # by build_plan before any write.  Keeping the target rules here ensures
        # the adapter preserves each field's effective substring posture.
        selected = load_selected_rules(target)
        rules = selected.rules
        plan = build_plan(target, source, dest, rules)
        rename_preflight = preflight_rename_noreplace(
            target,
            plan.table.rename_plan if plan.table is not None else plan.renames,
            allow_unsafe=True,
            operational=not args.dry_run,
        )
        if not rename_preflight.atomic:
            print(
                "warning: planned path renames cannot use atomic "
                "no-replacement protection",
                file=sys.stderr,
            )
            for problem in rename_preflight.problems:
                print(f"  {problem}", file=sys.stderr)
            if args.dry_run:
                print(
                    "warning: dry-run remains read-only; a real apply requires "
                    "--force to accept the overwrite risk",
                    file=sys.stderr,
                )
            elif args.force:
                print(
                    "warning: proceeding because --force permits a guarded "
                    "non-atomic fallback; a destination created during the "
                    "final race window may be overwritten",
                    file=sys.stderr,
                )
            else:
                return _fail(
                    "refusing a non-atomic rename; re-run with --force only "
                    "if you accept the risk that a concurrently created "
                    "destination may be overwritten"
                )
        # Plan-time gates for both declared mechanisms (P04 D1/D2/D5, P05
        # D5): output/target state, stale path-bearing argv against THIS
        # plan's rename set, executable resolution under the deny-by-default
        # env, stub scans, and the translated reset-path identity scan — all
        # before any write, under the exit-2-nothing-written contract
        # (dry-run included).
        gate_problems = preflight_excluded_files(target, rules)
        # Edit problems are collected BEFORE regeneration problems so a
        # refusal listing both reads in the order the phases actually run
        # (E4): every edit precedes every regeneration. Edits are planned
        # with the SAME machinery and feed the SAME gate — a missing edit
        # tool or an unpressable edit target refuses at exit 2 with nothing
        # written, before the rewrite pass the edit would have amended.
        gate_problems += preflight_edit_targets(target, rules)
        edit_plans, edit_problems = plan_edits(
            target, rules.edit, renamed=frozenset(plan.renames)
        )
        gate_problems += edit_problems
        gate_problems += preflight_regenerate_outputs(target, rules)
        regen_plans, plan_problems = plan_regenerate_commands(
            target, rules.regenerate, renamed=frozenset(plan.renames)
        )
        gate_problems += plan_problems
        reset_previews, reset_problems = preflight_reset_targets(
            target,
            rules,
            source=source,
            dest=dest,
            renames=plan.renames,
            rendered_rules=plan.rendered_rules,
            table=plan.table,
        )
        gate_problems += reset_problems
        prior_removed = removed_files_from_receipt(read_receipt(target))
        gate_problems += preflight_remove_targets(
            target, rules, previously_removed=frozenset(prior_removed)
        )
        gate_problems += remove_regen_conflicts(rules)
        if plan.table is not None:
            try:
                validate_reset_visibility(
                    target,
                    plan.table.rename_plan,
                    tuple(
                        (preview.rule.file, preview.stub_text)
                        for preview in reset_previews
                    ),
                )
            except SafetyError as exc:
                gate_problems.append(str(exc))
        if gate_problems:
            print(
                "error: declared edit/regeneration/reset/removal cannot run — "
                "nothing written:",
                file=sys.stderr,
            )
            for problem in gate_problems:
                print(f"  {problem}", file=sys.stderr)
            return 2
        # Announced only now: every plan-time gate (including the closure
        # refusal that owns stdout under --diagnostics-json) is behind us,
        # so a notice or warning can no longer precede a refusal on the same
        # stream.
        for notice in _render_origin_notices(origin, source, dest):
            print(notice)
        for warning in _render_origin_mismatch_warnings(origin, source, dest, found):
            print(warning)
        print(f"Platform: {selected.platform}")
        print(plan.render())
        # Phase order (E4): every edit runs before every regeneration, so the
        # plan the operator approves reads in the order execution will take.
        if edit_plans:
            print(render_edit_plan(edit_plans))
        if regen_plans:
            print(render_regenerate_plan(regen_plans))
        if reset_previews:
            print(render_reset_plan(reset_previews, verbose=args.verbose))
        if rules.remove:
            print(render_remove_plan(rules))
        for warning in plan.removal_warnings:
            print(warning)
        for warning in plan.prefix_warnings:
            print(warning)
        strays = stray_press_dirs(target)
        if strays:
            print(
                "warning: these press/ director(ies) are NOT this tool's "
                "control dir (no press-*.toml marker); their contents are "
                "rewritten and leak-scanned as ordinary content — review:",
                file=sys.stderr,
            )
            for stray in strays:
                print(f"  {stray}", file=sys.stderr)
        if args.dry_run:
            if write_pending:
                print(f"(dry run) would write {SOURCE_CONFIG_REL} from discovery")
            print("(dry run — nothing applied)")
            return 0
        # LAST gate before apply: every exit-2 path (rules/plan included) is
        # behind us, so the deferred source-config write can no longer be
        # followed by a "no writes" exit code.
        if args.force and invalidate_receipt(target):
            # Before the first mutation (P04-T16): a failed forced re-press
            # must not leave the old receipt advertising a verified press.
            print(f"prior receipt invalidated ({RECEIPT_REL})")
        if write_pending:
            write_control(target, SOURCE_CONFIG_REL, render_source_config(source))
            print(f"wrote {SOURCE_CONFIG_REL} from discovery")
    except (
        ValidationError,
        tomllib.TOMLDecodeError,
        OSError,
        subprocess.CalledProcessError,
        SafetyError,
    ) as exc:
        if isinstance(exc, RenameClosureUnauthorized):
            return _report_closure_refusal(exc, target, rules, args.diagnostics_json)
        return _fail(str(exc))
    outcome = _press(
        target,
        source,
        dest,
        rules,
        regen_plans,
        [(preview.rule, preview.stub_text) for preview in reset_previews],
        edit_plans=edit_plans,
        previously_removed=prior_removed,
        platform=selected.platform,
        rename_preflight=rename_preflight,
        allow_unsafe_rename=args.force,
        rendered_rules=plan.rendered_rules,
        table=plan.table,
        origin=origin,
    )
    return 1 if (outcome.env_error is not None or outcome.leaked) else 0


@dataclass
class PressOutcome:
    """Structurally distinguishes an env/tool failure from a doctor leak.

    `renamed`/`regenerated` carry `ApplyReport` provenance through to callers
    even on failure (empty when `apply` itself never completed).
    """

    leaked: bool
    renamed: list[tuple[str, str]]
    regenerated: list[str]
    env_error: str | None


def _press(
    target: Path,
    source: Identity,
    dest: Identity,
    rules: Rules,
    regen_plans: list[RegenerationPlan],
    resets: list[tuple[ResetRule, str]],
    *,
    edit_plans: list[EditPlan] | None = None,
    previously_removed: dict[str, str] | None = None,
    platform: str | None = None,
    rename_preflight: RenamePreflight | None = None,
    allow_unsafe_rename: bool = False,
    rendered_rules: list[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
    origin: OriginDecision | None = None,
) -> PressOutcome:
    if previously_removed is None:
        previously_removed = {}
    if edit_plans is None:
        edit_plans = []
    try:
        if table is None:
            fallback_plan = build_plan(target, source, dest, rules)
            rendered_rules = fallback_plan.rendered_rules
            table = fallback_plan.table
        elif rendered_rules is None:
            rendered_rules = declared_rule_triples(table)
    except (
        ValidationError,
        OSError,
        subprocess.CalledProcessError,
        SafetyError,
    ) as exc:
        print(f"error: {exc} — nothing applied", file=sys.stderr)
        return PressOutcome(False, [], [], env_error=str(exc))
    report = None
    control_snapshot: dict[str, bytes | None] = {}
    restore_controls_on_exception = False
    try:
        if table is None:
            raise SafetyError("substitution table is unavailable at mutation boundary")
        revalidate_substitution_table(target, table)
        validate_reset_visibility(
            target,
            table.rename_plan,
            tuple((rule.file, stub) for rule, stub in resets),
        )
        # Reset takes position ZERO (P05 D5): declared paths are consumed in
        # SOURCE coordinates before the rename pass moves anything. A raise
        # here aborts the press (no receipt) — git is the undo button.
        reset_done = apply_resets(target, resets)
        report = apply(
            target,
            source,
            dest,
            rules,
            allow_unsafe_rename=allow_unsafe_rename,
            rename_preflight=rename_preflight,
            table=table,
        )
        report.reset.extend(reset_done)
        # Declared removals run right after the rewrite/rename passes, at
        # their post-rename locations (P08 T2) — before any declared command
        # so a regeneration never observes a doomed file.
        removed_rels = apply_removals(
            target,
            rules,
            dict(report.renamed),
            previously_removed=frozenset(previously_removed),
        )
        report.removed.extend(removed_rels)
        # Declared commands run against the FINAL tree: declared paths are
        # translated through the apply-time rename report (P04 D1). The
        # Press-owned control files and Git visibility inputs are snapshotted
        # before the first command and revalidated after the last. Reservation
        # alone is not protection because a command can mutate arbitrary files.
        # E11: gated on ANY declared command, not on regenerations alone. An
        # edits-only target runs commands too, and a command is a command —
        # one that rewrites press-rules.toml or changes Git's ignore policy
        # mid-press is exactly as unsafe whether or not a [[regenerate]]
        # happens to be declared beside it.
        any_command = bool(edit_plans) or bool(regen_plans)
        control_snapshot = snapshot_control_files(target) if any_command else {}
        visibility_snapshot = snapshot_visibility_state(target) if any_command else None
        # A pinned executable can disappear between planning and launch (for
        # example, an earlier declared command can delete a later
        # target-relative executable). subprocess.run then raises instead of
        # returning a nonzero status, so the explicit failed_edits/failed_locks
        # branches below never run. From this point onward, every exceptional
        # exit must restore the same control snapshot those branches restore.
        restore_controls_on_exception = any_command
        # Phase order (E4): EVERY edit runs after the renames and before EVERY
        # regeneration, in declaration order — so a regeneration observes the
        # edited tree, which is the composition targets actually need
        # (bump the version, then rebuild the lockfile from it).
        failed_edits = execute_edits(
            target,
            edit_plans,
            dict(report.renamed),
            report,
            source=source,
            dest=dest,
            rules=rules,
            rendered_rules=rendered_rules,
            table=table,
        )
        if failed_edits:
            # Regeneration-equivalent failure handling: restore what a failed
            # command may have tampered with, withhold the receipt, exit 1.
            # The wording differs because an edit receives no command-based
            # exemption: the incompleteness is in its own declared postcondition,
            # regardless of whether target-wide verify_ignore later omits it from
            # doctor and hermetic-verify inventories.
            restore_problems = restore_control_files(target, control_snapshot)
            print(
                f"error: declared edit failed for {', '.join(failed_edits)} — the "
                f"file did not reach the state its [[edit]] declaration promised, "
                f"so this rebrand is INCOMPLETE; no receipt written. Fix the "
                f"command or the declaration, then re-run with --force.",
                file=sys.stderr,
            )
            _report_control_restore_problems(restore_problems)
            if report.skipped:
                print("skipped (review):", file=sys.stderr)
                for entry in report.skipped:
                    print(f"  {entry}", file=sys.stderr)
            print(report.render(), file=sys.stderr)
            return PressOutcome(
                False,
                report.renamed,
                report.regenerated,
                env_error=f"declared edit failed for {', '.join(failed_edits)}",
            )
        failed_locks = execute_regenerations(
            target,
            regen_plans,
            dict(report.renamed),
            report,
            source=source,
            dest=dest,
            rules=rules,
            rendered_rules=rendered_rules,
            table=table,
        )
        if failed_locks:
            # A failed command must not leave a tampered/planted control
            # file behind (codex 3654736777) — restore the snapshot before
            # reporting; {} when no commands ran.
            restore_problems = restore_control_files(target, control_snapshot)
            print(
                f"error: lockfile regeneration failed for "
                f"{', '.join(failed_locks)} — the lockfile still carries the old "
                f"identity and is exempt from the doctor scan, so this rebrand "
                f"is INCOMPLETE; no receipt written. Regenerate it, then re-run "
                f"with --force.",
                file=sys.stderr,
            )
            _report_control_restore_problems(restore_problems)
            # The per-file reason lives in report.skipped; without it the
            # failure is undiagnosable from the output (dogfood run 4
            # PROBLEM-23 — the reason was only printed on the success path).
            if report.skipped:
                print("skipped (review):", file=sys.stderr)
                for entry in report.skipped:
                    print(f"  {entry}", file=sys.stderr)
            print(report.render(), file=sys.stderr)
            return PressOutcome(
                False,
                report.renamed,
                report.regenerated,
                env_error=f"lockfile regeneration failed for {', '.join(failed_locks)}",
            )
        if any_command:
            # Final validation pass (D3): edits, outputs, reset stubs, and the
            # control-file snapshot — a later command corrupting an earlier
            # result is invisible to every downstream inventory. Edits are
            # rechecked here (expect included) because they run FIRST: a
            # regeneration is the one thing positioned to undo one.
            post_problems = final_validation_pass(
                target,
                regen_plans,
                resets,
                dict(report.renamed),
                source=source,
                dest=dest,
                rules=rules,
                rendered_rules=rendered_rules,
                table=table,
                edits=edit_plans,
            )
            post_problems += validate_control_files(target, control_snapshot)
            if visibility_snapshot is not None:
                post_problems += validate_visibility_state(target, visibility_snapshot)
            if post_problems:
                restore_problems = restore_control_files(target, control_snapshot)
                print(
                    "error: post-regeneration validation failed — no receipt written:",
                    file=sys.stderr,
                )
                for problem in post_problems:
                    print(f"  {problem}", file=sys.stderr)
                _report_control_restore_problems(restore_problems)
                print(report.render(), file=sys.stderr)
                return PressOutcome(
                    False,
                    report.renamed,
                    report.regenerated,
                    env_error="post-regeneration validation failed",
                )
            # Every command-owned effect on ROOT_CONTROL has now been
            # revalidated. Past this boundary, source-config and receipt
            # writes are the press's own successful output; a later reporting
            # error must not roll them back to the pre-command snapshot.
            restore_controls_on_exception = False
        # Verification never honors target-side REWRITE exclusions (EMP-01):
        # neither extra_exclude_files nor extra_exclude_dirs can hide content
        # from the doctor. The only sanctioned exemption is the explicit,
        # committed verify_ignore list — the deliberate ignore set.
        doctor_rules = Rules(
            exclude_dirs=DEFAULT_RULES.exclude_dirs | rules.verify_ignore,
            exclude_files=DEFAULT_RULES.exclude_files,
            regenerate=rules.regenerate,
            verify_ignore=rules.verify_ignore,
        )
        leaks = find_leaks(
            target,
            source,
            doctor_rules,
            dest=dest,
            display_form_names=rules.display_forms,
            substring_fields=rules.substring_rewrite_fields,
            rendered_rules=rendered_rules,
            renamed=report.renamed,
            table=table,
        )
        if leaks:
            print(render_leak_report(leaks), file=sys.stderr)
            print(report.render(), file=sys.stderr)
            return PressOutcome(
                True, report.renamed, report.regenerated, env_error=None
            )
        write_control(target, SOURCE_CONFIG_REL, render_source_config(dest))
        # The receipt is the LAST write of a successful press (P12 fix
        # round 1): it means "this rebrand completed and was verified" and it
        # guards re-runs, so it must not survive a failure of the
        # source-config write ABOVE. Ordered this way, an OSError there leaves
        # no receipt and the press can be re-run without --force. Nothing
        # between the two writes reads the receipt.
        receipt_path = write_receipt(
            target,
            source,
            dest,
            report,
            platform=platform,
            origin=origin,
            edits=[
                # Every PLANNED edit, unconditionally: a failed edit withholds
                # the receipt entirely, so reaching this write means each one
                # ran and held its post-condition.
                (
                    plan.rule.file,
                    (plan.executable, *plan.rule.command[1:]),
                    plan.rule.expect,
                )
                for plan in edit_plans
            ],
            regenerations=[
                (plan.rule.file, (plan.executable, *plan.rule.command[1:]))
                for plan in regen_plans
                if plan.rule.file in report.regenerated
            ],
            resets=report.reset,
            removals=[
                # Recorded in DECLARED (source) coordinates, matching
                # [[press.regenerate]] — that is the coordinate every later
                # consumer (re-press preflight, verify tri-state) compares
                # against, and press-rules.toml is never rewritten. A target
                # satisfied by a PRIOR press carries forward, so the
                # satisfied-chain survives any number of re-presses.
                (rule.file, rule.reason)
                for rule in rules.remove
                if translate_path(rule.file, dict(report.renamed)) in report.removed
                or rule.file in previously_removed
            ]
            + [
                # Prior records with no active declaration on THIS platform
                # (or whose declaration was retired) carry forward with
                # their recorded reasons: a cross-platform re-press must
                # not drop another platform's satisfied removals.
                (file, reason)
                for file, reason in previously_removed.items()
                if file not in {rule.file for rule in rules.remove}
            ],
            exempt=[
                # A declared verify_exempt reason travels VERBATIM into the
                # receipt's exempt record (issue #81); the generic mechanism
                # note covers the rest.
                *(
                    (
                        rel,
                        next(
                            (
                                plan.rule.reason
                                for plan in regen_plans
                                if plan.rule.file == rel and plan.rule.verify_exempt
                            ),
                            "regenerated by declared command; validated by the "
                            "press's post-command scan (hermetic verify skips "
                            "it)",
                        ),
                    )
                    for rel in report.regenerated
                ),
                *(
                    (rel, "reset to the declared stub (scanned at plan time)")
                    for rel in report.reset
                ),
            ],
        )
        print(report.render())
        if report.skipped:
            print("skipped (review):")
            for entry in report.skipped:
                print(f"  {entry}")
        print(f"verified: no identity leftovers. receipt: {receipt_path}")
        print(f"updated {SOURCE_CONFIG_REL} to the new identity")
        return PressOutcome(False, report.renamed, report.regenerated, env_error=None)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        SafetyError,
        ValidationError,
    ) as exc:
        restore_problems: list[str] = []
        if restore_controls_on_exception:
            restore_problems = restore_control_files(target, control_snapshot)
        # Exit 2 (main's pre-_press gate) means "nothing applied"; a
        # mid-mutation failure here is not that — target may be PARTIALLY
        # rewritten.
        if isinstance(exc, RenameClosureUnauthorized):
            # The tree changed between planning and apply (e.g. a new
            # ignored file appeared under a renamed prefix): print the same
            # aggregated findings + remedy argv as the plan-time refusal,
            # never JSON here (the plan already printed to stdout), THEN the
            # same restoration guidance the generic branch below prints —
            # without changing this site's exit-1 partial-rewrite contract.
            _print_closure_refusal_prose(exc, target, rules)
            print(_partial_rewrite_restore_hint(target), file=sys.stderr)
        else:
            print(
                f"error: {exc} — {_partial_rewrite_restore_hint(target)}",
                file=sys.stderr,
            )
        _report_control_restore_problems(restore_problems)
        return PressOutcome(
            False,
            report.renamed if report else [],
            report.regenerated if report else [],
            env_error=str(exc),
        )
    except BaseException:
        # KeyboardInterrupt and SystemExit are deliberately re-raised, but an
        # interruption during the armed command phase must not leave a forged
        # receipt or altered rules behind, and the target's broader partial
        # rewrite still needs the same operator recovery guidance as an
        # ordinary exception.
        restore_problems = []
        if restore_controls_on_exception:
            restore_problems = restore_control_files(target, control_snapshot)
            print(_partial_rewrite_restore_hint(target), file=sys.stderr)
        _report_control_restore_problems(restore_problems)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
