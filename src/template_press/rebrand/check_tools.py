"""press check-tools — declared-tool availability report (P04 D4).

Resolves ``argv[0]`` of every declared ``[[regenerate]]`` command plus
``git`` — the only tool press itself contributes after D1 — exactly as
execution would (D2): path-qualified names against the TARGET root, bare
names on the deny-by-default effective PATH. Reads config, writes
nothing, executes nothing. Exit 0 all found, 1 any missing, 2
config/usage error.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from template_press.rebrand.regen import command_env, resolve_executable
from template_press.rebrand.rules import ValidationError, load_rules


def check_tools_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press check-tools", description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)

    target = args.target.resolve()
    if not target.is_dir():
        print(f"error: target {target} is not a directory", file=sys.stderr)
        return 2
    try:
        rules = load_rules(target)
    except (
        ValidationError,
        tomllib.TOMLDecodeError,
        UnicodeDecodeError,
        OSError,
    ) as exc:
        # The same configuration exception set the rebrand and verify entry
        # points normalize to exit 2 — never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    missing = 0
    reports: list[str] = []
    git = resolve_executable(target, "git", command_env(()))
    if git is None:
        missing += 1
        reports.append("git — missing (press itself needs it)")
    else:
        reports.append(f"git — {git}")
    for rule in rules.regenerate:
        argv0 = rule.command[0]
        found = resolve_executable(target, argv0, command_env(rule.env))
        if found is None:
            missing += 1
            reports.append(f"{argv0} — missing (declared to regenerate {rule.file})")
        else:
            reports.append(f"{argv0} — {found} (regenerates {rule.file})")
    print("\n".join(reports))
    return 1 if missing else 0
