"""Rebrand engine: enumerate, plan, and apply identity rewrites on a target.

Scan-based (ARCH-03): no per-target file lists. Every tracked text file is a
replace candidate; every path component containing an identity token is a
rename candidate. Failure mode: any op raising propagates — git in the
TARGET is the undo button (`git checkout . && git clean -fd`).
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — git ls-files enumerates the target
from dataclasses import dataclass, field
from pathlib import Path

from template_press.rebrand.identity import Identity, replace_token, token_occurs
from template_press.rebrand.rules import Rules
from template_press.rebrand.safety import ContainmentError, assert_under_root

RENAME_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "app_name_upper",
)

# A press/ directory is THIS tool's control dir — exempt from rewriting and
# the no-leak scan — only when it holds one of these files (which legitimately
# carry SOURCE identity). Any other press/ dir is ordinary target content.
CONTROL_MARKERS: tuple[str, ...] = (
    "press-source.toml",
    "press-rules.toml",
    "press-receipt.toml",
)

# Exact-root-artifact exemption (plan Decision D3: exempt an exact artifact,
# never a location). Only these literal root-level control files are exempt
# from iteration — never a whole press/ subtree. rel.as_posix() membership.
ROOT_CONTROL: frozenset[str] = frozenset(
    {
        "press/press-source.toml",
        "press/press-rules.toml",
        "press/press-receipt.toml",
        "press/press-answers.toml",
    }
)


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


def _git_listed(target: Path) -> list[Path]:
    """Relative paths git reports (tracked+untracked), honoring .gitignore.

    Uses `git ls-files --cached --others --exclude-standard`.
    """
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        # git emits UTF-8 path bytes; text=True would decode with the locale
        # codepage on Windows (cp1252) and mojibake non-ASCII filenames.
        encoding="utf-8",
    )
    return [Path(line) for line in result.stdout.split("\0") if line]


def _press_dirs(files: list[Path]) -> set[str]:
    """POSIX paths of every directory component literally named 'press'."""
    dirs: set[str] = set()
    for rel in files:
        parts = rel.parts
        for i in range(len(parts) - 1):  # directory components only
            if parts[i] == "press":
                dirs.add(Path(*parts[: i + 1]).as_posix())
    return dirs


def _control_press_dirs(target: Path, files: list[Path]) -> frozenset[str]:
    """press/ dirs that ARE this tool's control dir (hold a CONTROL_MARKER).

    Content-keyed, not name- or depth-keyed: a press/ directory is exempt
    only when it carries a control file that legitimately holds SOURCE
    identity. Every other press/ dir is ordinary target content.
    """
    return frozenset(
        d
        for d in _press_dirs(files)
        if any((target / d / m).is_file() for m in CONTROL_MARKERS)
    )


def _is_root_press(rel: Path, i: int) -> bool:
    """Component i of rel is the protected root control dir literally 'press'.

    The root press/ dir holds ROOT_CONTROL; renaming or path-flagging it
    would break control-file exemption when app_name == 'press'.
    """
    return i == 0 and rel.parts[i] == "press"


def stray_press_dirs(target: Path) -> list[str]:
    """press/ dirs that are NOT the control dir (no control marker).

    They are treated as ordinary content — rewritten AND leak-scanned — so
    surviving source tokens under them cannot yield a false 'verified'. The
    CLI warns about them so a human can confirm the rewrite was intended.
    """
    files = _git_listed(target)
    return sorted(_press_dirs(files) - _control_press_dirs(target, files))


def iter_target_files(target: Path, rules: Rules) -> list[Path]:
    """All non-excluded tracked+untracked files under target, sorted.

    Excludes rules.exclude_files / exclude_dirs and the exact root control
    artifacts in ROOT_CONTROL. Everything else under a press/ dir — root or
    nested — is ordinary content: scanned and rewritten like any file.
    """
    files = _git_listed(target)
    out: list[Path] = []
    for rel in files:
        if _is_excluded(rel, rules):
            continue
        if rel.as_posix() in ROOT_CONTROL:
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
    if path.is_symlink():
        return None  # never follow a link: writes must stay inside the target
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
                    if _is_root_press(rel, i):
                        break
                    old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                    new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                    rename_map.setdefault(old_prefix, new_prefix)
                    break
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
            kind = "symlink" if path.is_symlink() else "binary"
            report.skipped.append(f"replace {rel} ({kind})")
            continue
        new_text = text
        for f, cur, repl in pairs:
            new_text = replace_token(new_text, f, cur, repl)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            report.replaced.append(rel)


def _retarget_symlinks(
    target: Path,
    pairs: list[tuple[str, str, str]],
    report: ApplyReport,
) -> None:
    """Rewrite in-repo RELATIVE symlink targets carrying identity tokens.

    Only the link STRING is rewritten — the pointed-to file is never read,
    written, or followed. Candidates come from ``_git_listed`` filtered by a
    no-follow ``is_symlink`` lstat (NOT ``iter_target_files``, which follows
    links). A symlink is left untouched when its target is absolute, carries
    no token, or would escape the root after rewriting (containment via the
    reused ``assert_under_root`` on the resolved sink). The link is recreated
    with unlink + symlink, guarded by an immediate ``is_symlink`` re-check to
    refuse a TOCTOU swap.
    """
    target_r = target.resolve()
    for rel in _git_listed(target):
        path = target / rel
        if not path.is_symlink():
            continue
        link = os.readlink(path)
        if os.path.isabs(link):
            continue  # never rewrite or follow an absolute target
        new_link = link
        for f, cur, repl in pairs:
            new_link = replace_token(new_link, f, cur, repl)
        if new_link == link:
            continue
        sink = (path.parent / new_link).resolve()
        try:
            assert_under_root(sink, target_r)
        except ContainmentError:
            report.skipped.append(f"retarget {rel.as_posix()} (escaping target)")
            continue
        if not path.is_symlink():  # TOCTOU: refuse a swapped-in non-symlink
            report.skipped.append(f"retarget {rel.as_posix()} (no longer a symlink)")
            continue
        os.unlink(path)
        os.symlink(new_link, path)
        report.replaced.append(rel.as_posix())


def apply(target: Path, source: Identity, dest: Identity, rules: Rules) -> ApplyReport:
    """Execute the rebrand: replace pass, symlink-retarget pass, rename pass."""
    source.validate()
    dest.validate()
    report = ApplyReport()
    pairs = replacement_pairs(source, dest)
    _apply_replacements(target, pairs, rules, report)
    _retarget_symlinks(target, pairs, report)
    _apply_renames(target, pairs, rules, report)
    return report


def _rename_pass_once(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> bool:
    """Run one shallowest-prefix rename pass; return True if any rename ran.

    Rescans `iter_target_files` fresh so each pass sees the previous pass's
    moves, then collapses each differing path to only its shallowest
    renamed ancestor (one path level per pass) and executes deepest-first
    to keep parents valid.
    """
    rename_map: dict[str, str] = {}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        new_rel = _renamed_rel(rel, pairs)
        if new_rel == rel:
            continue
        for i, (old_part, new_part) in enumerate(
            zip(rel.parts, new_rel.parts, strict=True)
        ):
            if old_part != new_part:
                if _is_root_press(rel, i):
                    break
                old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                rename_map.setdefault(old_prefix, new_prefix)
                break
    performed = False
    for old in sorted(rename_map, key=lambda p: -len(Path(p).parts)):
        src, dst = target / old, target / rename_map[old]
        if not src.exists():
            report.skipped.append(f"rename {old} (missing)")
            continue
        if dst.exists():
            report.skipped.append(f"rename {old} (destination exists)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        report.renamed.append((old, rename_map[old]))
        performed = True
    return performed


def _apply_renames(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    """Rename tracked paths whose components carry identity tokens.

    Runs `_rename_pass_once` to a fixpoint: each pass renames only the
    shallowest differing path level (e.g. src/demo_widget →
    src/potato_launcher) and re-scans the target before the next pass, so a
    token-bearing file nested inside a token-bearing dir gets its dir moved
    on one pass and its (now-relocated) file renamed on the next, instead of
    colliding mid-move. Bounded to 32 passes (depth bound); stops as soon as
    a pass performs no renames.
    """
    for _ in range(32):
        if not _rename_pass_once(target, pairs, rules, report):
            return
