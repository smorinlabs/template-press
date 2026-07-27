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

from template_press.rebrand.engine import ApplyReport, translate_path
from template_press.rebrand.rules import RegenerateRule, Rules
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    git_hardening_args,
    is_regular_lstat,
    scrubbed_git_env,
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
        return Path(found) if found else None
    found = shutil.which(argv0, path=env.get("PATH", ""))
    return Path(found) if found else None


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
        out_rel = translate_path(rule.file, renames)
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
        result = subprocess.run(  # noqa: S603 # nosec B603
            [plan.executable, *rule.command[1:]],
            cwd=target,
            capture_output=True,
            text=True,
            env=command_env(rule.env),
        )
        if result.returncode != 0:
            report.skipped.append(
                f"regenerate {rule.file} (command exited {result.returncode})"
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
        text=True,
        env=scrubbed_git_env(),
    )
    return result.stdout


def tracked_paths(target: Path) -> frozenset[str]:
    """POSIX rel paths git tracks — an index read (no clean/smudge filters)."""
    out = _git_stdout(target, "ls-files", "-z")
    return frozenset(p for p in out.split("\0") if p)


def has_uncommitted_changes(target: Path, rel: str) -> bool:
    """Staged or unstaged changes for one path (porcelain output non-empty)."""
    return bool(_git_stdout(target, "status", "--porcelain", "--", rel).strip())


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
    return problems
