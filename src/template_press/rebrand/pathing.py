"""Neutral path coordinates shared by rewrite and independent verification."""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import ReplaceRule, Rules, rule_matches_path

ROOT_CONTROL: frozenset[str] = frozenset(
    {
        "press/press-source.toml",
        "press/press-rules.toml",
        "press/press-receipt.toml",
        "press/press-answers.toml",
    }
)
REGENERATE_EXEMPTIBLE: frozenset[str] = frozenset({"uv.lock", "bun.lock"})


def is_root_press(rel: Path, index: int) -> bool:
    """Whether one component is the protected root control directory."""

    return index == 0 and rel.parts[index] == "press"


def symlink_target_posix(rel: Path, link: str) -> str:
    """Normalize a relative link target against the link's own directory."""

    return Path(os.path.normpath(os.path.join(rel.parent.as_posix(), link))).as_posix()


def translate_path(posix: str, renames: Mapping[str, str]) -> str:
    """Translate a source path through chained shallowest-prefix moves."""

    current = posix
    for _ in range(len(renames) + 1):
        best: tuple[int, str, str] | None = None
        for old, new in renames.items():
            if current == old or current.startswith(f"{old}/"):
                depth = old.count("/")
                if best is None or depth > best[0]:
                    best = (depth, old, new)
        if best is None:
            return current
        _, old, new = best
        current = new if current == old else f"{new}{current[len(old) :]}"
    raise ValidationError(
        f"path translation did not converge for {posix!r} after "
        f"{len(renames) + 1} passes (rename map: {dict(renames)!r})"
    )


def reverse_renamed_path(posix: str, renamed: Sequence[tuple[str, str]]) -> str:
    """Map a current path back through every executed prefix move."""

    ordered = sorted(renamed, key=lambda pair: -len(pair[1]))
    for _ in range(len(ordered) + 1):
        for old, new in ordered:
            if posix == new:
                posix = old
                break
            if posix.startswith(f"{new}/"):
                posix = f"{old}{posix[len(new) :]}"
                break
        else:
            return posix
    raise ValidationError(f"reverse path translation did not converge for {posix!r}")


def rule_scope_hits(
    rule: ReplaceRule,
    posix: str,
    renamed: Sequence[tuple[str, str]],
) -> bool:
    """Match a declared scope against current and reverse-source paths."""

    return rule_matches_path(rule, posix) or rule_matches_path(
        rule,
        reverse_renamed_path(posix, renamed),
    )


def exempt_regenerated_paths(
    rules: Rules,
    renamed: Mapping[str, str] | Collection[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Translated declared outputs covered by the verifier exemption cap."""

    rename_map = dict(renamed)
    outputs: list[tuple[str, str]] = []
    for rule in rules.regenerate:
        translated = translate_path(rule.file, rename_map)
        if translated.rsplit("/", 1)[-1] in REGENERATE_EXEMPTIBLE:
            outputs.append(
                (
                    translated,
                    "declared regeneration — rebuilt and scanned by the real "
                    "press's post-command check; the hermetic sandbox never "
                    "runs commands, so verify cannot certify it",
                )
            )
    return outputs
