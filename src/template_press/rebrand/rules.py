"""Scan rules the tool carries + per-target overrides (OQ4 hybrid model).

The tool never carries a target's identity or file list — only generic
rules: what to skip and which lockfiles to regenerate after a rebrand.
A target may extend them via <target>/.press/rules.toml.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

RULES_REL = Path(".press") / "rules.toml"


@dataclass(frozen=True)
class Rules:
    exclude_dirs: frozenset[str]
    exclude_files: frozenset[str]  # POSIX paths relative to the target root
    regenerate: tuple[str, ...]  # lockfiles regenerated (not rewritten)


DEFAULT_RULES = Rules(
    exclude_dirs=frozenset(
        {
            ".git",
            ".press",
            "node_modules",
            ".venv",
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
        }
    ),
    exclude_files=frozenset(
        {"uv.lock", "bun.lock", "package-lock.json", "CHANGELOG.md"}
    ),
    regenerate=("uv.lock",),
)


def load_rules(target: Path) -> Rules:
    """DEFAULT_RULES, extended by the target's .press/rules.toml if present."""
    override_path = target / RULES_REL
    if not override_path.is_file():
        return DEFAULT_RULES
    data = tomllib.loads(override_path.read_text(encoding="utf-8"))
    table = data.get("rules", {})
    return Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs
        | frozenset(table.get("extra_exclude_dirs", [])),
        exclude_files=DEFAULT_RULES.exclude_files
        | frozenset(table.get("extra_exclude_files", [])),
        regenerate=tuple(table.get("regenerate", DEFAULT_RULES.regenerate)),
    )
