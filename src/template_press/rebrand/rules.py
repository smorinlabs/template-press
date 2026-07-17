"""Scan rules the tool carries + per-target overrides (OQ4 hybrid model).

The tool never carries a target's identity or file list — only generic
rules: what to skip and which lockfiles to regenerate after a rebrand.
A target may extend them via <target>/press/press-rules.toml.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.identity import ValidationError

RULES_REL = Path("press") / "press-rules.toml"


@dataclass(frozen=True)
class Rules:
    exclude_dirs: frozenset[str]
    exclude_files: frozenset[str]  # POSIX paths relative to the target root
    regenerate: tuple[str, ...]  # lockfiles regenerated (not rewritten)
    # The deliberate, committed ignore set: directories whose surviving
    # source-identity content is VALID (vendored trees, historical docs).
    # Exempts them from the doctor's leak scan only — never from rewriting.
    # Matched like exclude_dirs: by single path COMPONENT at any depth
    # ("legacy" ignores every dir named legacy; "docs/old" never matches).
    verify_ignore: frozenset[str] = frozenset()


DEFAULT_RULES = Rules(
    exclude_dirs=frozenset(
        {
            # NB: the control "press/" dir is NOT excluded here — the engine
            # exempts it content-keyed (only when it holds a press-*.toml
            # marker), so an unrelated press/ dir in a target is still
            # rewritten and leak-scanned. See engine.CONTROL_MARKERS.
            ".git",
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


_COMPONENT_KEYS = frozenset({"extra_exclude_dirs", "verify_ignore"})


def _str_list(table: dict, key: str, default: list[str]) -> list[str]:
    value = table.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{RULES_REL}: [rules] {key} must be a list of strings")
    if key in _COMPONENT_KEYS:
        nested = [v for v in value if "/" in v or "\\" in v]
        if nested:
            raise ValidationError(
                f"{RULES_REL}: [rules] {key} entries are single directory "
                f"NAMES matched at any depth, not paths — invalid: {nested}"
            )
    return value


def load_rules(target: Path) -> Rules:
    """DEFAULT_RULES, extended by the target's press/press-rules.toml if present."""
    override_path = target / RULES_REL
    if not override_path.is_file():
        return DEFAULT_RULES
    data = tomllib.loads(override_path.read_text(encoding="utf-8"))
    table = data.get("rules", {})
    if not isinstance(table, dict):
        raise ValidationError(f"{RULES_REL}: [rules] must be a table")
    return Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs
        | frozenset(_str_list(table, "extra_exclude_dirs", [])),
        exclude_files=DEFAULT_RULES.exclude_files
        | frozenset(_str_list(table, "extra_exclude_files", [])),
        regenerate=tuple(
            _str_list(table, "regenerate", list(DEFAULT_RULES.regenerate))
        ),
        verify_ignore=frozenset(_str_list(table, "verify_ignore", [])),
    )
