"""``press verify`` — the hermetic sandbox self-press leak check (Task 12).

The architectural KEYSTONE of `press verify`: it ties every prior module
together and, crucially, presses via the HERMETIC ``engine.apply`` — NOT the
rebrand ``_press`` path. There is no doctor, no receipt, no lockfile
regeneration: verify must be a pure, repeatable observation, never a mutation.

Flow (Decisions 2-6):

1. Load the target's committed FROM identity (``press/press-source.toml``). A
   missing config, a malformed one, or a control-path symlink -> **2** with NO
   writes to the real target.
2. Preflight against the REAL target (never the sandbox, never ``_resolve_source``):
   ``mismatches(source, discover(target))`` plus a PRESENCE check — for every
   field discovery could not confirm, the declared value must occur at least
   once in the target's ``scan_paths`` corpus. A wholly-undiscoverable-and-absent
   identity is ``unverifiable``. Any problem -> **2**.
3. Load the ``[verify]`` config (shared file with ``[rules]``). Any two SOURCE
   fields equal -> WARN; with ``equal_fields == "error"`` the equality is
   remembered to force **1**.
4-8. Inside ``safety.owned_sandbox`` (so the sandbox is torn down): build a
   faithful copy (``make_sandbox``), press it toward a synthetic
   equality-preserving TO-identity (``synthesize_dest`` + hermetic ``apply``),
   re-stage the sandbox index so ``scan`` sees the pressed worktree (not stale
   renamed paths), ``verifier.scan`` for surviving SOURCE identity, then apply
   the source-anchored ignores.

Exit: **2** for config/env/unverifiable; else **1** if any surviving finding,
stale ignore, ``equal_fields == "error"`` collision, or unavailable submodule;
else **0**. An env/tool error raised by the press is **2** (not **1**): the
press could not complete, so verify cannot claim clean.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess  # nosec B404 — re-stages the OWNED sandbox git index only
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from template_press.rebrand.config import SOURCE_CONFIG_REL, load_source_config
from template_press.rebrand.discovery import Discovered, discover, mismatches
from template_press.rebrand.engine import apply, scan_paths
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.ignores import Ignore, apply_ignores, build_forward_map
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.rules import RULES_REL, Rules, load_rules
from template_press.rebrand.safety import (
    SafetyError,
    git_hardening_args,
    is_regular_lstat,
    owned_sandbox,
    scrubbed_git_env,
)
from template_press.rebrand.sandbox import make_sandbox
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verifier import Finding, scan
from template_press.rebrand.verify_config import VerifyConfig, parse_verify_config

# The re-stage of the sandbox index after apply is authored by a synthetic
# identity — never the user's git config — mirroring make_sandbox.
_SANDBOX_GIT_IDENTITY: dict[str, str] = {
    "GIT_AUTHOR_NAME": "press-verify",
    "GIT_AUTHOR_EMAIL": "verify@localhost",
    "GIT_COMMITTER_NAME": "press-verify",
    "GIT_COMMITTER_EMAIL": "verify@localhost",
}

# Config/env failures anywhere on the pre-sandbox and sandbox-setup paths all
# map to exit 2 (no target mutation is possible from any of them).
_CONFIG_ERRORS: tuple[type[Exception], ...] = (
    SafetyError,
    ValidationError,
    tomllib.TOMLDecodeError,
    OSError,
    subprocess.CalledProcessError,
)

# A failure raised BY the press (apply / re-stage) — an env/tool error, not a
# leak — is exit 2, distinct from a surviving finding's exit 1.
_PRESS_ENV_ERRORS: tuple[type[Exception], ...] = (
    FileNotFoundError,
    OSError,
    subprocess.CalledProcessError,
    SafetyError,
)


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _discovered_map(found: Discovered) -> dict[str, str | None]:
    """Discovery's per-field result keyed by the identity field name."""
    return {
        "package_name": found.package_name,
        "repo_name": found.repo_name,
        "app_name": found.app_name,
        "author": found.author,
        "email": found.email,
        "owner": found.owner,
    }


def _target_text_corpus(target: Path, rules: Rules) -> list[str]:
    """Every scannable string of the REAL target: each ``scan_paths`` entry's
    POSIX path plus its symlink readlink text or decoded file content.

    ``scan_paths`` already excludes ``ROOT_CONTROL`` — so the source-config's
    OWN declaration of a value is not in the corpus, which is what makes the
    presence check meaningful (it looks for the value in real content, never in
    the config that declares it).
    """
    corpus: list[str] = []
    for entry in scan_paths(target, rules):
        corpus.append(entry.rel.as_posix())
        path = target / entry.rel
        if entry.kind == "symlink":
            try:
                corpus.append(os.readlink(path))
            except OSError:
                continue
        elif entry.kind == "file" and is_regular_lstat(path):
            try:
                # UTF-8-only by design: a non-UTF-8 (binary) file is skipped
                # here, which only makes a value HARDER to confirm present —
                # the presence check fails CLOSED to exit 2 (unverifiable), so
                # a skipped binary can never cause a false CLEAN.
                corpus.append(path.read_bytes().decode("utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    return corpus


def _value_present(field: str, value: str, corpus: list[str]) -> bool:
    return any(find_occurrences(text, field, value, substring=False) for text in corpus)


def _preflight(
    target: Path, source: Identity, rules: Rules, scan_fields: Sequence[str]
) -> list[str]:
    """Consistency + presence check against the REAL target; problems -> 2.

    Presence is required only for the fields ``verify`` will actually scan
    (``scan_fields``, the effective ``[verify]`` scope) — requiring presence for
    a field verify won't scan (e.g. ``author``/``email`` under the default
    scope) falsely rejects a target whose identity is consistent for everything
    that IS scanned. Only discovery-confirmed fields are exempt; the
    wholly-undiscoverable-AND-absent ``unverifiable`` verdict is scoped to the
    scanned set. ``mismatches`` (the consistency check) is unchanged — a
    discoverable field that DISAGREES with the config still fails regardless of
    scope.
    """
    found = discover(target)
    problems = list(mismatches(source, found))
    discovered = _discovered_map(found)
    declared = source.as_dict()
    # Only scanned fields that discovery can confirm (skip derived forms like
    # ``app_name_upper`` that are not independently discoverable).
    scanned = [f for f in scan_fields if f in discovered]
    undiscoverable = [f for f in scanned if discovered[f] is None]
    if not undiscoverable:
        return problems
    corpus = _target_text_corpus(target, rules)
    absent = [f for f in undiscoverable if not _value_present(f, declared[f], corpus)]
    if len(undiscoverable) == len(scanned) and len(absent) == len(undiscoverable):
        problems.append(
            "unverifiable: the declared identity is WHOLLY undiscoverable and "
            "absent from the target — refusing to pass on historical prose"
        )
    else:
        problems.extend(
            f"{f}: declared {declared[f]!r} is neither discoverable nor present "
            f"anywhere in the target (undiscoverable and absent)"
            for f in absent
        )
    return problems


def _equal_pair(source: Identity) -> tuple[str, str] | None:
    """The first pair of SOURCE fields sharing the same value, or None."""
    items = list(source.as_dict_prompted().items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][1] == items[j][1]:
                return items[i][0], items[j][0]
    return None


def _load_verify_config(target: Path) -> VerifyConfig:
    """Parse the ``[verify]`` table from ``press/press-rules.toml`` (the same
    file that carries ``[rules]``); absent file/table -> defaults."""
    path = target / RULES_REL
    table = None
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        table = data.get("verify")
    return parse_verify_config(table)


def _make_source_line(target: Path) -> Callable[[str, int], str | None]:
    """A cached ``(src_path, 1-based line) -> str | None`` reader over the
    ORIGINAL target. Fails CLOSED (None) on any unreadable/absent file/line —
    ``apply_ignores`` treats None as "anchor not present"."""
    cache: dict[str, list[str] | None] = {}

    def source_line(src_path: str, line: int) -> str | None:
        if src_path not in cache:
            path = target / src_path
            if is_regular_lstat(path):
                try:
                    cache[src_path] = path.read_bytes().decode("utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    cache[src_path] = None
            else:
                cache[src_path] = None
        lines = cache[src_path]
        if lines is None or line < 1 or line > len(lines):
            return None
        return lines[line - 1]

    return source_line


def _restage_sandbox(sandbox: Path) -> None:
    """``git add -A -f`` on the OWNED sandbox so ``git ls-files`` reflects the
    pressed worktree — apply's renames leave the old paths in the index but
    absent from the worktree, which would otherwise scan as false leaks. This
    reconciles the index; it is NOT lockfile regeneration (verify stays
    hermetic). Scrubbed + hardened + synthetic-identity, ``-C`` pinned.

    ``-f`` is REQUIRED, not optional: without it, a plain ``add -A`` respects
    ``.gitignore``, so after apply renames a force-added-ignored file to a
    still-ignored path, ``-A`` stages the deletion but REFUSES to re-add the
    ignored path — the file (e.g. a binary whose bytes embed a source value and
    apply cannot rewrite) drops out of the sandbox index and ``scan`` never sees
    the surviving leak → a FALSE CLEAN. Force-adding is correct and faithful
    here because ``make_sandbox`` copied ONLY the ``copy_paths`` set into the
    sandbox worktree — there are no extraneous ignored files for ``-f`` to
    over-add, so ``-A -f`` re-stages exactly the pressed tree (force-added
    ignored files included) and stages the renamed-away deletions.
    """
    cmd = ["git", "-C", str(sandbox), *git_hardening_args(), "add", "-A", "-f"]
    subprocess.run(  # noqa: S603 # nosec B603 B607
        cmd,
        check=True,
        capture_output=True,
        env=scrubbed_git_env(extra=_SANDBOX_GIT_IDENTITY),
    )


def _report(
    surviving: list[Finding],
    stale: list[Ignore],
    unavailable: tuple[str, ...],
    equal_collision: tuple[str, str] | None,
) -> None:
    """Human, grouped-by-file failure report to stderr."""
    print(
        "verify FAILED — source identity survived the hermetic self-press:",
        file=sys.stderr,
    )
    by_file: dict[str, list[Finding]] = {}
    for finding in surviving:
        by_file.setdefault(finding.path, []).append(finding)
    for path in sorted(by_file):
        print(f"  {path}", file=sys.stderr)
        for f in by_file[path]:
            where = f.where if f.line is None else f"{f.where} L{f.line}:C{f.col}"
            print(f"    [{where}] {f.field}={f.value!r}", file=sys.stderr)
    for ignore in stale:
        print(
            f"  stale ignore (suppressed nothing): file={ignore.file!r} "
            f"anchor={ignore.anchor!r}",
            file=sys.stderr,
        )
    for sub in unavailable:
        print(f"  unavailable submodule (could not verify): {sub}", file=sys.stderr)
    if equal_collision is not None:
        print(
            f"  equal_fields=error: {equal_collision[0]} and "
            f"{equal_collision[1]} share a value",
            file=sys.stderr,
        )


def verify_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press verify", description=__doc__)
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    target = args.target.resolve()

    # Step 1 — source-config (control-symlink / missing / malformed -> 2; the
    # real target is never mutated on any exit-2 path).
    try:
        source = load_source_config(target, None)
    except _CONFIG_ERRORS as exc:
        return _fail(f"cannot load source-config: {exc}")
    if source is None:
        return _fail(
            f"no source-config at {SOURCE_CONFIG_REL}; verify needs the "
            f"target's committed FROM identity"
        )

    # Steps 2-3 — preflight + [verify] config, against the REAL target.
    try:
        rules = load_rules(target)
        cfg = _load_verify_config(target)
        scan_fields: tuple[str, ...] = cfg.fields
        if source.display_name is not None and "display_name" not in scan_fields:
            # codesign sec-05: a declared display name is scanned as its own
            # field — the only coverage when its words diverge from the slug.
            scan_fields = (*scan_fields, "display_name")
        problems = _preflight(target, source, rules, scan_fields)
    except _CONFIG_ERRORS as exc:
        return _fail(f"preflight failed: {exc}")
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2

    equal_pair = _equal_pair(source)
    if equal_pair is not None:
        print(
            f"warning: source fields {equal_pair[0]} and {equal_pair[1]} are "
            f"equal — the press preserves the equality (not itself a failure)",
            file=sys.stderr,
        )
    equal_collision = equal_pair if cfg.equal_fields == "error" else None

    # Steps 4-8 — press + scan inside an owned, torn-down sandbox.
    surviving: list[Finding] = []
    stale: list[Ignore] = []
    unavailable: tuple[str, ...] = ()
    try:
        synth = synthesize_dest(source)
        with owned_sandbox(target) as dest_root:
            sandbox = make_sandbox(target, dest_root)
            try:
                report = apply(sandbox.path, source, synth, rules)
                _restage_sandbox(sandbox.path)
            except _PRESS_ENV_ERRORS as exc:
                return _fail(
                    f"press failed in the sandbox (env/tool error, not a leak): {exc}"
                )
            findings = scan(
                sandbox.path,
                source,
                synth,
                fields=scan_fields,
                substring_fields=cfg.substring_fields,
                rules=rules,
            )
            forward_map = build_forward_map(report.renamed)
            surviving, stale = apply_ignores(
                findings,
                list(cfg.ignores),
                forward_map=forward_map,
                source_line=_make_source_line(target),
            )
            # Report/JSON in SOURCE coordinates (Design §3): the sandbox path is
            # a synthetic press artifact that does not exist in the user's repo.
            # line/col already index the source via the newline invariant.
            surviving = [
                dataclasses.replace(f, path=forward_map(f.path)) for f in surviving
            ]
            unavailable = sandbox.unavailable_submodules
    except _CONFIG_ERRORS as exc:
        return _fail(f"sandbox verify failed: {exc}")

    failed = bool(surviving or stale or unavailable or equal_collision)
    if args.as_json:
        print(
            json.dumps(
                {
                    "verified": not failed,
                    "surviving": [dataclasses.asdict(f) for f in surviving],
                    "stale_ignores": [dataclasses.asdict(i) for i in stale],
                    "unavailable_submodules": list(unavailable),
                    "equal_fields_collision": (
                        list(equal_collision) if equal_collision else None
                    ),
                }
            )
        )
    if failed:
        if not args.as_json:
            _report(surviving, stale, unavailable, equal_collision)
        return 1
    if not args.as_json:
        print("verified: no identity leftovers survived the hermetic self-press.")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify_command())
