"""press rebrand — point the press at a target repo (ARCH-01).

Pipeline: preconditions → source identity (config-first, discovery
validates) → answers → plan → [--dry-run stops here] → apply → regenerate
lockfiles → VERIFY (no-leak doctor) → receipt. Exit codes: 0 ok, 1 leaks
found after apply (no receipt), 2 precondition/config error (no writes).
"""

from __future__ import annotations

import argparse
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
from template_press.rebrand.discovery import discover, mismatches
from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import (
    RenamePreflight,
    apply,
    build_plan,
    preflight_rename_noreplace,
    stray_press_dirs,
)
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
)
from template_press.rebrand.receipt import (
    RECEIPT_REL,
    invalidate_receipt,
    read_receipt,
    write_receipt,
)
from template_press.rebrand.regen import (
    RegenerationPlan,
    execute_regenerations,
    final_validation_pass,
    plan_regenerate_commands,
    preflight_excluded_files,
    preflight_regenerate_outputs,
    render_regenerate_plan,
    restore_control_files,
    snapshot_control_files,
    validate_control_files,
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
    load_rules,
)
from template_press.rebrand.safety import (
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


def _resolve_source(
    target: Path, override: Path | None, accept_discovery: bool
) -> tuple[Identity, bool] | int:
    """Resolve the FROM identity; second element = write source-config later.

    The write is DEFERRED to main() so it happens only after every exit-2
    gate has passed — keeping "exit 2 means no writes" true by construction.
    """
    write_pending = False
    source = load_source_config(target, override)
    if source is None:
        found = discover(target)
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
    problems = mismatches(source, discover(target))
    if problems:
        print(
            "error: source-config does not match the target "
            "(refusing to press — this is the silent-half-rebrand guard):",
        )
        for p in problems:
            print(f"  {p}")
        return 2
    return source, write_pending


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

        resolved = _resolve_source(target, args.source_config, args.accept_discovery)
        if isinstance(resolved, int):
            return resolved
        source, write_pending = resolved
        if write_pending and not args.accept_discovery:
            print(
                f"no source-config found at {SOURCE_CONFIG_REL}.\n"
                f"Discovery proposes:\n\n{render_source_config(source)}\n"
                f"Save it there (and commit), or re-run with "
                f"--accept-discovery to write + use it.",
            )
            return 2

        if args.config is None:
            return _fail("--config ANSWERS.toml is required")
        dest = load_answers(args.config)

        display_problem = display_name_problem(source, dest)
        if display_problem is not None:
            return _fail(display_problem)

        if source == dest:
            return _fail(
                "source and destination identities are identical — nothing to press"
            )
        # Pipeline stability, ambiguity, and termination are validated together
        # by build_plan before any write.  Keeping the target rules here ensures
        # the adapter preserves each field's effective substring posture.
        rules = load_rules(target)
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
                "error: declared regeneration/reset cannot run — nothing written:",
                file=sys.stderr,
            )
            for problem in gate_problems:
                print(f"  {problem}", file=sys.stderr)
            return 2
        print(plan.render())
        if regen_plans:
            print(render_regenerate_plan(regen_plans))
        if reset_previews:
            print(render_reset_plan(reset_previews, verbose=args.verbose))
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
        return _fail(str(exc))
    outcome = _press(
        target,
        source,
        dest,
        rules,
        regen_plans,
        [(preview.rule, preview.stub_text) for preview in reset_previews],
        rename_preflight=rename_preflight,
        allow_unsafe_rename=args.force,
        rendered_rules=plan.rendered_rules,
        table=plan.table,
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
    rename_preflight: RenamePreflight | None = None,
    allow_unsafe_rename: bool = False,
    rendered_rules: list[tuple[ReplaceRule, str, str]] | None = None,
    table: SubstitutionTable | None = None,
) -> PressOutcome:
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
        # Declared commands run against the FINAL tree: declared paths are
        # translated through the apply-time rename report (P04 D1). The
        # press-owned control files are snapshotted before the first
        # command and revalidated after the last (D1 reservation is not
        # protection — a command can mutate arbitrary files).
        control_snapshot = snapshot_control_files(target) if regen_plans else {}
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
            restore_control_files(target, control_snapshot)
            print(
                f"error: lockfile regeneration failed for "
                f"{', '.join(failed_locks)} — the lockfile still carries the old "
                f"identity and is exempt from the doctor scan, so this rebrand "
                f"is INCOMPLETE; no receipt written. Regenerate it, then re-run "
                f"with --force.",
                file=sys.stderr,
            )
            print(report.render(), file=sys.stderr)
            return PressOutcome(
                False,
                report.renamed,
                report.regenerated,
                env_error=f"lockfile regeneration failed for {', '.join(failed_locks)}",
            )
        if regen_plans:
            # Final validation pass (D3): outputs, reset stubs, and the
            # control-file snapshot — a later command corrupting an earlier
            # result is invisible to every downstream inventory.
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
            )
            post_problems += validate_control_files(target, control_snapshot)
            if post_problems:
                restore_control_files(target, control_snapshot)
                print(
                    "error: post-regeneration validation failed — no receipt written:",
                    file=sys.stderr,
                )
                for problem in post_problems:
                    print(f"  {problem}", file=sys.stderr)
                print(report.render(), file=sys.stderr)
                return PressOutcome(
                    False,
                    report.renamed,
                    report.regenerated,
                    env_error="post-regeneration validation failed",
                )
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
        receipt_path = write_receipt(
            target,
            source,
            dest,
            report,
            regenerations=[
                (plan.rule.file, (plan.executable, *plan.rule.command[1:]))
                for plan in regen_plans
            ],
            exempt=[
                *(
                    (
                        rel,
                        "regenerated by declared command; validated by the "
                        "press's post-command scan (hermetic verify skips it)",
                    )
                    for rel in report.regenerated
                ),
                *(
                    (rel, "reset to the declared stub (scanned at plan time)")
                    for rel in report.reset
                ),
            ],
        )
        write_control(target, SOURCE_CONFIG_REL, render_source_config(dest))
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
        # Exit 2 (main's pre-_press gate) means "nothing applied"; a
        # mid-mutation failure here is not that — target may be PARTIALLY
        # rewritten.
        print(
            f"error: {exc} — target may be PARTIALLY rewritten; restore with "
            f"`git -C {target} checkout . && git clean -fd`",
            file=sys.stderr,
        )
        return PressOutcome(
            False,
            report.renamed if report else [],
            report.regenerated if report else [],
            env_error=str(exc),
        )


if __name__ == "__main__":
    raise SystemExit(main())
