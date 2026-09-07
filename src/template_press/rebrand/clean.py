"""Declared cleanup rendering, directory Git argv and hardened subprocess I/O.

The filesystem planner and exact-file executor live in clean_cli.py. Cleanup
is a standalone verb, never a phase of press rebrand.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess  # nosec B404 — engine-owned hardened Git invocations
import sys
from pathlib import Path

from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import CleanRule
from template_press.rebrand.safety import (
    SafeRelPath,
    UnsafePathError,
    git_hardening_args,
    scrubbed_git_env,
)

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _render_one(pattern: str, values: dict[str, str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValidationError(
                f"[[clean]] path {pattern!r} references {{{name}}} but "
                "press/press-source.toml does not declare it"
            )
        return values[name]

    return _PLACEHOLDER_RE.sub(_sub, pattern)


def render_clean_paths(
    rules: tuple[CleanRule, ...], source: Identity
) -> tuple[str, ...]:
    """Render and independently validate every declared clean path in order."""
    values = source.as_dict()
    rendered: list[str] = []
    for rule in rules:
        for pattern in rule.paths:
            path = _render_one(pattern, values)
            if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
                raise ValidationError(
                    "[[clean]] rendered path must not contain control "
                    f"characters: {path!r}"
                )
            try:
                rendered.append(SafeRelPath(path).as_posix())
            except UnsafePathError as exc:
                raise ValidationError(
                    f"[[clean]] rendered path {path!r}: {exc}"
                ) from exc
    return tuple(rendered)


def clean_argv(
    git: Path,
    target: Path,
    paths: tuple[str, ...],
    *,
    show: bool,
    core_excludes: Path | None = None,
) -> list[str]:
    """Build the exact hardened Git invocation for declared clean paths."""
    mode = "-ndX" if show else "-fdX"
    return [
        str(git),
        "-C",
        str(target),
        f"--work-tree={target.absolute()}",
        *git_hardening_args(),
        "-c",
        f"core.excludesFile={core_excludes or Path(os.devnull)}",
        "--literal-pathspecs",
        "clean",
        mode,
        "--",
        *paths,
    ]


def shell_join(argv: list[str]) -> str:
    """Render argv for display; the scrubbed environment is not represented."""
    joined = (
        subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)
    )
    return repr(joined) if any(not char.isprintable() for char in joined) else joined


def execute_clean(
    argv: list[str], target: Path, *, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run argv under the scrubbed Git environment and return all exit codes."""
    return subprocess.run(  # noqa: S603 # nosec B603
        argv,
        cwd=target,
        capture_output=True,
        input=stdin,
        env=scrubbed_git_env(),
        check=False,
    )
