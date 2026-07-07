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
from pathlib import Path

from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.discovery import discover, mismatches
from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import ApplyReport, apply, build_plan
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.receipt import read_receipt, write_receipt
from template_press.rebrand.rules import DEFAULT_RULES, Rules, load_rules


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
            "target already has a press receipt (.press/receipt.toml); "
            "re-press with --force"
        )
    if not allow_dirty:
        status = subprocess.run(  # noqa: S603 # nosec B603 B607
            ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            return "target working tree is dirty; commit/stash or --allow-dirty"
    return None


def _resolve_source(
    target: Path, override: Path | None, accept_discovery: bool, dry_run: bool
) -> Identity | int:
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
            candidate = Identity.from_mapping({k: v for k, v in proposal.items() if v})
            candidate.validate()
        except ValidationError as exc:
            return _fail(f"discovered identity is invalid: {exc}")
        if not accept_discovery:
            print(
                f"no source-config found at {SOURCE_CONFIG_REL}.\n"
                f"Discovery proposes:\n\n{render_source_config(candidate)}\n"
                f"Save it there (and commit), or re-run with "
                f"--accept-discovery to write + use it.",
            )
            return 2
        if dry_run:
            # A preview must be side-effect free; the real run writes it.
            print(f"(dry run) would write {SOURCE_CONFIG_REL} from discovery")
        else:
            path = target / SOURCE_CONFIG_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_source_config(candidate), encoding="utf-8")
            print(f"wrote {SOURCE_CONFIG_REL} from discovery")
        source = candidate
    problems = mismatches(source, discover(target))
    if problems:
        print(
            "error: source-config does not match the target "
            "(refusing to press — this is the silent-half-rebrand guard):",
        )
        for p in problems:
            print(f"  {p}")
        return 2
    return source


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

        source = _resolve_source(
            target, args.source_config, args.accept_discovery, args.dry_run
        )
        if isinstance(source, int):
            return source

        if args.config is None:
            return _fail("--config ANSWERS.toml is required")
        dest = load_answers(args.config)

        if source == dest:
            return _fail(
                "source and destination identities are identical — nothing to press"
            )

        rules = load_rules(target)
        plan = build_plan(target, source, dest, rules)
        print(plan.render())
        if args.dry_run:
            print("(dry run — nothing applied)")
            return 0
    except (
        ValidationError,
        tomllib.TOMLDecodeError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        return _fail(str(exc))
    try:
        return _press(target, source, dest, rules)
    except (OSError, subprocess.CalledProcessError) as exc:
        # Exit 2 means "nothing applied"; a mid-apply failure is not that.
        print(
            f"error: {exc} — target may be PARTIALLY rewritten; restore with "
            f"`git -C {target} checkout . && git clean -fd`",
            file=sys.stderr,
        )
        return 1


def _regenerate_lockfiles(target: Path, rules: Rules, report: ApplyReport) -> list[str]:
    """Regenerate listed lockfiles; return the ones that FAILED to regenerate.

    A lockfile is excluded from both rewriting and the doctor scan, so a
    failed regeneration would leave source-identity content behind invisibly.
    Callers must treat failures as verification failures (no receipt).
    """
    failed: list[str] = []
    for lockfile in rules.regenerate:
        if not (target / lockfile).is_file():
            continue
        if lockfile == "uv.lock":
            result = subprocess.run(  # nosec B603 B607
                ["uv", "lock"],  # noqa: S607
                cwd=target,
                capture_output=True,
                text=True,
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


def _press(target: Path, source: Identity, dest: Identity, rules: Rules) -> int:
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
        return 1
    # Verification never honors target-side rewrite exclusions: opting a file
    # out of rewriting must not opt it out of the leak scan (EMP-01).
    doctor_rules = Rules(
        exclude_dirs=rules.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        regenerate=rules.regenerate,
    )
    leaks = find_leaks(target, source, doctor_rules)
    if leaks:
        print(render_leak_report(leaks), file=sys.stderr)
        print(report.render(), file=sys.stderr)
        return 1
    receipt_path = write_receipt(target, source, dest, report)
    source_config_path = target / SOURCE_CONFIG_REL
    source_config_path.parent.mkdir(parents=True, exist_ok=True)
    source_config_path.write_text(render_source_config(dest), encoding="utf-8")
    print(report.render())
    if report.skipped:
        print("skipped (review):")
        for entry in report.skipped:
            print(f"  {entry}")
    print(f"verified: no identity leftovers. receipt: {receipt_path}")
    print(f"updated {SOURCE_CONFIG_REL} to the new identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
