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
    ApplyReport,
    apply,
    build_plan,
    rendered_replace_rules,
    stray_press_dirs,
)
from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    token_occurs,
)
from template_press.rebrand.receipt import read_receipt, write_receipt
from template_press.rebrand.rules import DEFAULT_RULES, Rules, load_rules
from template_press.rebrand.safety import (
    SafetyError,
    git_hardening_args,
    scrubbed_git_env,
    scrubbed_uv_env,
    write_control,
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


def _expand_display_forms(values: dict[str, str]) -> dict[str, str]:
    """Replace a raw ``display_name`` entry with its per-form expansions.

    Mirrors ``replacement_pairs``' display-form handling (engine.py):
    runtime pair tags are ``display_name_spaced/pascal/camel``, never bare
    ``display_name``, so comparing raw dict values alone can miss a derived
    form that embeds a changed source token. Uses the full
    ``DISPLAY_FORM_NAMES`` set (not a rules-configured subset) — a subset
    only narrows what gets REWRITTEN; this preflight stays conservative and
    checks every form regardless.
    """
    if "display_name" not in values:
        return values
    expanded = {k: v for k, v in values.items() if k != "display_name"}
    forms = display_forms(values["display_name"])
    for form in DISPLAY_FORM_NAMES:
        expanded[f"display_name_{form}"] = forms[form]
    return expanded


def _collisions(
    source: Identity,
    dest: Identity,
    substring_fields: frozenset[str] = frozenset(),
) -> list[str]:
    """Destination values that embed a CHANGED source token.

    Sequential substitution would re-rewrite such output (old app name
    becoming the new package name chains two replacements), and the doctor
    would flag correct output as a leak (press → press_two). Refusing up
    front with guidance beats either silent corruption or a permanent
    verification failure.

    Both identities are expanded the same way ``replacement_pairs`` expands
    them (Fix F3): a raw ``display_name`` entry is replaced by its exact
    per-form values, so a destination display name whose DERIVED form (e.g.
    the camel form of "Plbp" is "plbp") embeds a changed source token is
    caught even though the raw display name never contains it verbatim.

    ``substring_fields`` (Fix F4) — the target's ``[rules]
    substring_rewrite_fields`` — mirrors what the engine will actually do to
    a changed field opted into substring mode: it rewrites that field
    SUBSTRING-wide, with no word-boundary guard, so a destination value that
    embeds the source token WITHOUT a boundary (e.g. dest repo_name
    "myfoo-tools" embedding source app_name "foo") is just as much a
    collision as a boundary-guarded one — checked via plain ``in`` instead of
    the boundary-guarded ``token_occurs``.
    """
    out: list[str] = []
    src = _expand_display_forms(source.as_dict())
    dst = _expand_display_forms(dest.as_dict())
    changed = {f: v for f, v in src.items() if v != dst.get(f)}
    for dest_field, dest_value in dst.items():
        for src_field, src_value in changed.items():
            hit = (
                src_value in dest_value
                if src_field in substring_fields
                else token_occurs(dest_value, src_field, src_value)
            )
            if hit:
                out.append(
                    f"destination {dest_field}={dest_value!r} contains the "
                    f"source {src_field} token {src_value!r}"
                )
    return out


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
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
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
        # Loaded before the collision preflight (Fix F4): substring_rewrite_fields
        # changes what counts as a collision (a boundary-free embedded token is
        # only a problem for a field the engine will actually rewrite
        # substring-wide) — pure reading, no side effect, so moving it earlier
        # is safe.
        rules = load_rules(target)
        collisions = _collisions(
            source, dest, substring_fields=rules.substring_rewrite_fields
        )
        if collisions:
            print(
                "error: destination identity embeds source tokens — a single "
                "press cannot produce a verifiable result; press in two steps "
                "via an intermediate identity:",
                file=sys.stderr,
            )
            for c in collisions:
                print(f"  {c}", file=sys.stderr)
            return 2

        plan = build_plan(target, source, dest, rules)
        print(plan.render())
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
    outcome = _press(target, source, dest, rules)
    return 1 if (outcome.env_error is not None or outcome.leaked) else 0


def _regenerate_lockfiles(target: Path, rules: Rules, report: ApplyReport) -> list[str]:
    """Regenerate listed lockfiles; return the ones that FAILED to regenerate.

    A lockfile is excluded from both rewriting and the doctor scan, so a
    failed regeneration would leave source-identity content behind invisibly.
    Callers must treat failures as verification failures (no receipt).
    """
    failed: list[str] = []
    for lockfile in rules.regenerate:
        lockpath = target / lockfile
        if lockpath.is_symlink():  # lstat-based, no-follow — check first
            report.skipped.append(
                f"regenerate {lockfile} (symlink — refusing to write through)"
            )
            failed.append(lockfile)
            continue
        if not lockpath.is_file():
            continue
        if lockfile == "uv.lock":
            result = subprocess.run(  # nosec B603 B607
                ["uv", "lock"],  # noqa: S607
                cwd=target,
                capture_output=True,
                text=True,
                env=scrubbed_uv_env(),  # G5: no UV_* override can steer the write
            )
            if result.returncode == 0:
                report.regenerated.append(lockfile)
            else:
                report.skipped.append(f"regenerate {lockfile} (uv lock failed)")
                failed.append(lockfile)
        else:
            report.skipped.append(f"regenerate {lockfile} (no regenerator)")
            failed.append(lockfile)
    return failed


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
    target: Path, source: Identity, dest: Identity, rules: Rules
) -> PressOutcome:
    report = None
    try:
        report = apply(target, source, dest, rules)
        failed_locks = _regenerate_lockfiles(target, rules, report)
        if failed_locks:
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
            rendered_rules=rendered_replace_rules(rules, source, dest),
        )
        if leaks:
            print(render_leak_report(leaks), file=sys.stderr)
            print(report.render(), file=sys.stderr)
            return PressOutcome(
                True, report.renamed, report.regenerated, env_error=None
            )
        receipt_path = write_receipt(target, source, dest, report)
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
