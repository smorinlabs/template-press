"""Rebrand engine: enumerate, plan, and apply identity rewrites on a target.

Scan-based (ARCH-03): no per-target file lists. Every tracked text file is a
replace candidate; every path component containing an identity token is a
rename candidate. Failure mode: any op raising propagates — git in the
TARGET is the undo button (`git checkout . && git clean -fd`).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from template_press.rebrand.identity import Identity, replace_token, token_occurs
from template_press.rebrand.rules import Rules

RENAME_FIELDS: tuple[str, ...] = ("package_name", "repo_name", "app_name")


@dataclass
class PlanItem:
    kind: str  # "replace" | "rename"
    path: str
    detail: str

    def render(self) -> str:
        return f"  [{self.kind:<7}] {self.path}  —  {self.detail}"


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)

    def render(self) -> str:
        if not self.items:
            return "(plan is empty — nothing to do)"
        return "\n".join(["Plan:", *(i.render() for i in self.items)])

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"replace": 0, "rename": 0}
        for i in self.items:
            out[i.kind] = out.get(i.kind, 0) + 1
        return out


def _is_excluded(rel: Path, rules: Rules) -> bool:
    if rel.as_posix() in rules.exclude_files:
        return True
    return any(part in rules.exclude_dirs for part in rel.parts)


def iter_target_files(target: Path, rules: Rules) -> list[Path]:
    """All non-excluded tracked+untracked files under target, sorted.

    Uses `git ls-files --cached --others --exclude-standard` so the scan
    respects the target's .gitignore.
    """
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    out: list[Path] = []
    for line in result.stdout.splitlines():
        rel = Path(line)
        if _is_excluded(rel, rules):
            continue
        path = target / rel
        if path.is_file():
            out.append(path)
    return sorted(out)


def replacement_pairs(source: Identity, dest: Identity) -> list[tuple[str, str, str]]:
    """(field, current, replacement) triples, longest current first."""
    src, dst = source.as_dict(), dest.as_dict()
    pairs = [(k, src[k], dst[k]) for k in src if src[k] != dst[k]]
    pairs.sort(key=lambda t: -len(t[1]))
    return pairs


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable — never a rewrite candidate


def _renamed_rel(rel: Path, pairs: list[tuple[str, str, str]]) -> Path:
    parts = []
    for component in rel.parts:
        new = component
        for f, cur, repl in pairs:
            if f in RENAME_FIELDS:
                new = replace_token(new, f, cur, repl)
        parts.append(new)
    return Path(*parts)


def build_plan(target: Path, source: Identity, dest: Identity, rules: Rules) -> Plan:
    """Resolve what apply() would do; executes nothing."""
    source.validate()
    dest.validate()
    plan = Plan()
    pairs = replacement_pairs(source, dest)
    rename_map: dict[str, str] = {}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        text = _read_text(path)
        if text is not None:
            hit_fields = [f for f, cur, _ in pairs if token_occurs(text, f, cur)]
            if hit_fields:
                plan.items.append(
                    PlanItem("replace", rel.as_posix(), f"fields={hit_fields}")
                )
        new_rel = _renamed_rel(rel, pairs)
        if new_rel != rel:
            # collapse to the shallowest differing ancestor (dir rename)
            for i, (old_part, new_part) in enumerate(
                zip(rel.parts, new_rel.parts, strict=True)
            ):
                if old_part != new_part:
                    old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                    new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                    rename_map.setdefault(old_prefix, new_prefix)
    for old, new in sorted(rename_map.items()):
        plan.items.append(PlanItem("rename", old, f"→ {new}"))
    return plan


@dataclass
class ApplyReport:
    replaced: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    regenerated: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (
            f"Applied: {len(self.replaced)} replaced, "
            f"{len(self.renamed)} renamed, "
            f"{len(self.regenerated)} regenerated, "
            f"{len(self.skipped)} skipped."
        )


def _apply_replacements(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target).as_posix()
        text = _read_text(path)
        if text is None:
            report.skipped.append(f"replace {rel} (binary)")
            continue
        new_text = text
        for f, cur, repl in pairs:
            new_text = replace_token(new_text, f, cur, repl)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            report.replaced.append(rel)


def apply(target: Path, source: Identity, dest: Identity, rules: Rules) -> ApplyReport:
    """Execute the rebrand: replace pass, then rename pass."""
    source.validate()
    dest.validate()
    report = ApplyReport()
    pairs = replacement_pairs(source, dest)
    _apply_replacements(target, pairs, rules, report)
    _apply_renames(target, pairs, rules, report)
    return report


def _apply_renames(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    raise NotImplementedError  # implemented in the rename-pass task
