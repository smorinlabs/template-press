"""Rebrand engine: enumerate, plan, and apply identity rewrites on a target.

Scan-based (ARCH-03): no per-target file lists. Every tracked text file is a
replace candidate; every path component containing an identity token is a
rename candidate. Failure mode: any op raising propagates — git in the
TARGET is the undo button (`git checkout . && git clean -fd`).
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — git ls-files enumerates the target
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    replace_token,
    token_occurs,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    ReplaceRule,
    Rules,
    render_replace_pattern,
    rule_matches_path,
)
from template_press.rebrand.safety import (
    ContainmentError,
    assert_ancestors_real,
    assert_under_root,
    git_hardening_args,
    safe_write,
    scrubbed_git_env,
)

RENAME_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "app_name_upper",
)

# Marker files that identify a press/ directory as THIS tool's control dir
# (one legitimately carries SOURCE identity). These feed ONLY the
# `stray_press_dirs` warning (via `_control_press_dirs`) — they do NOT drive the
# rewrite/scan exemption. The exact-artifact exemption is `ROOT_CONTROL` below
# (Decision D3): only the literal root-level control files are exempt from
# iteration, never a whole press/ subtree keyed on these markers.
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


@dataclass(frozen=True)
class PathEntry:
    """A ``copy_paths``/``scan_paths`` entry: a relative path plus its kind.

    ``kind`` is ``"file" | "symlink" | "gitlink"``, determined without
    following links — this is the interface Task 7's scanner consumes.
    """

    rel: Path
    kind: str


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

    Uses `git ls-files --cached --others --exclude-standard`. This is a
    working-tree-scanning read on an untrusted target (a hostile
    `.git/config` is attacker input), so it is scrubbed-env + hardening-args
    protected (G5+) exactly like the sandbox's on-target git calls: no
    identity is needed for a read.
    """
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            *git_hardening_args(),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        # Capture raw BYTES (no encoding=): a git path is any byte except NUL,
        # so a non-UTF-8 filename would raise UnicodeDecodeError under a strict
        # text decode and crash enumeration. Decode UTF-8 with surrogateescape
        # so arbitrary bytes round-trip to str (and back, via os.fsencode) —
        # this also avoids the Windows locale-codepage mojibake text=True gives.
        env=scrubbed_git_env(),
    )
    stdout = result.stdout.decode("utf-8", "surrogateescape")
    return [Path(line) for line in stdout.split("\0") if line]


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


def _gitlink_rels(target: Path) -> frozenset[str]:
    """POSIX rel paths of index entries whose mode is a gitlink (160000).

    Reads the index directly (``git ls-files --stage``), so a submodule
    that isn't checked out is still correctly identified — no working-tree
    directory needs to exist. Scrubbed-env + hardening-args protected (G5+):
    the target's own ``.git/config`` is attacker input.
    """
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            *git_hardening_args(),
            "ls-files",
            "--stage",
            "-z",
        ],
        check=True,
        capture_output=True,
        # Raw bytes + surrogateescape decode (see _git_listed): a gitlink whose
        # path carries a non-UTF-8 byte must not crash enumeration.
        env=scrubbed_git_env(),
    )
    stdout = result.stdout.decode("utf-8", "surrogateescape")
    rels: set[str] = set()
    for entry in stdout.split("\0"):
        if not entry:
            continue
        meta, _, rel = entry.partition("\t")
        mode = meta.split(" ", 1)[0]
        if mode == "160000":
            rels.add(rel)
    return frozenset(rels)


def copy_paths(target: Path) -> list[PathEntry]:
    """Everything git lists (tracked + non-ignored untracked), minus ``.git``.

    RETAINS symlinks and gitlinks — never filters on ``is_file()``, which
    would drop a symlink-to-dir/dangling symlink and hide gitlinks. ``kind``
    is determined without following links: a gitlink is detected via the
    index mode (``_gitlink_rels``); otherwise an ``lstat``-based
    ``is_symlink()`` check on the (possibly not-checked-out) path decides
    "symlink" vs "file". Sorted, deterministic.
    """
    gitlinks = _gitlink_rels(target)
    entries: list[PathEntry] = []
    for rel in _git_listed(target):
        if ".git" in rel.parts:
            continue
        posix = rel.as_posix()
        if posix in gitlinks:
            kind = "gitlink"
        elif (target / rel).is_symlink():
            kind = "symlink"
        else:
            kind = "file"
        entries.append(PathEntry(rel, kind))
    return sorted(entries, key=lambda e: e.rel.as_posix())


def rewrite_paths(target: Path, rules: Rules) -> list[Path]:
    """Files eligible for content/path rewrite — a thin named wrapper.

    ``iter_target_files`` already excludes lockfiles (``exclude_files``),
    ``exclude_dirs``, and ``ROOT_CONTROL`` (Task 2); kept symmetric with
    ``copy_paths``/``scan_paths`` rather than reimplemented.
    """
    return iter_target_files(target, rules)


def scan_paths(target: Path, rules: Rules) -> list[PathEntry]:
    """``copy_paths`` minus ``ROOT_CONTROL``, regenerable lockfiles, and
    ``verify_ignore`` dirs — the no-leak scan's candidate set.

    A lockfile is scan-exempt only when it is regenerated FRESH after apply,
    which requires it to be in BOTH:

    - the TARGET's effective ``rules.regenerate`` — press actually regenerates
      it for THIS target (so ``regenerate = []`` re-includes uv.lock: press
      neither rewrites it, since it is in ``exclude_files``, nor regenerates
      it, so a stale token must be scanned — keying on ``DEFAULT_RULES`` ALONE
      would FALSE-CLEAN it); AND
    - the tool's OWN ``DEFAULT_RULES.regenerate`` ∩ ``DEFAULT_RULES.exclude_files``
      — the tool has a real regenerator for it (EMP-01/F5: a target's
      ``press-rules.toml`` must not be able to hide content from the scan by
      declaring ``regenerate = ["bun.lock"]`` for a lockfile press never
      regenerates).

    Everything else stays: non-regenerable lockfiles (``bun.lock``,
    ``package-lock.json``), a force-added gitignored file, and symlink/
    gitlink entries (type-tagged, for Task 7).
    """
    exempt_lockfiles = (
        set(rules.regenerate)
        & set(DEFAULT_RULES.regenerate)
        & DEFAULT_RULES.exclude_files
    )
    out: list[PathEntry] = []
    for entry in copy_paths(target):
        posix = entry.rel.as_posix()
        if posix in ROOT_CONTROL:
            continue
        if posix in exempt_lockfiles:
            continue
        if any(part in rules.verify_ignore for part in entry.rel.parts):
            continue
        out.append(entry)
    return out


def replacement_pairs(
    source: Identity,
    dest: Identity,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[tuple[str, str, str]]:
    """(field, current, replacement) triples, longest current first.

    display_name is expanded into one pair per enabled exact form
    (display_name_spaced/…_pascal/…_camel) — generic-boundary tags, never in
    RENAME_FIELDS, so display forms rewrite content but never paths. The
    `k in dst` guard keeps a half-specified display name (source has it,
    dest doesn't) out of the pair list entirely — the CLI gates that case.
    """
    src, dst = source.as_dict(), dest.as_dict()
    pairs = [
        (k, src[k], dst[k])
        for k in src
        if k != "display_name" and k in dst and src[k] != dst[k]
    ]
    if "display_name" in src and "display_name" in dst:
        sf = display_forms(src["display_name"])
        df = display_forms(dst["display_name"])
        for form in display_form_names:
            if sf[form] != df[form]:
                pairs.append((f"display_name_{form}", sf[form], df[form]))
    pairs.sort(key=lambda t: -len(t[1]))
    return pairs


def rendered_replace_rules(
    rules: Rules, source: Identity, dest: Identity
) -> list[tuple[ReplaceRule, str, str]]:
    """(rule, FROM, TO) with both sides rendered; identical sides dropped.

    Rendering raises ValidationError when a pattern references a field this
    identity pair doesn't declare (optional display_name) — surfacing at
    plan time, before any write.

    A ``paths = true`` rule whose rendered FROM or TO contains a path
    separator (``/`` or ``\\`` — either can split a component on the
    platforms this tool targets) also raises: the FROM side can never match
    a single path COMPONENT (the unit `_renamed_rel` operates on), and a TO
    side that splits into nested parts corrupts the component-wise rename
    (the strict ``zip`` in the rename-collapse loop crashes or silently
    mis-renames). Content-only rules are NOT restricted — a content pattern
    like ``{owner}/{repo_name}`` is legitimate prose.
    """
    out: list[tuple[ReplaceRule, str, str]] = []
    for rule in rules.replace:
        frm = render_replace_pattern(rule.pattern, source)
        to = render_replace_pattern(rule.pattern, dest)
        if frm == to:
            continue
        if rule.paths and any(sep in frm or sep in to for sep in ("/", "\\")):
            raise ValidationError(
                f"[[replace]] pattern {rule.pattern!r} has paths=true but its "
                f"rendered value contains a path separator ('/' or '\\'), "
                f"which can never match (or would corrupt) a single path "
                f"component: FROM {frm!r} TO {to!r}"
            )
        out.append((rule, frm, to))
    return out


def _read_text(path: Path) -> str | None:
    if path.is_symlink():
        return None  # never follow a link: writes must stay inside the target
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable — never a rewrite candidate


def _renamed_rel(
    rel: Path,
    pairs: list[tuple[str, str, str]],
    rendered: list[tuple[ReplaceRule, str, str]] | None = None,
    substring_fields: Collection[str] = frozenset(),
) -> Path:
    rendered = rendered or []
    posix = rel.as_posix()
    parts = []
    for i, component in enumerate(rel.parts):
        if _is_root_press(rel, i):
            # The protected root control dir literally 'press' is never
            # renamed (it holds ROOT_CONTROL) — but its DESCENDANTS still are,
            # so a token-bearing child (press/press_notes.md) renames to
            # press/potato_notes.md instead of being abandoned.
            parts.append(component)
            continue
        new = component
        # [[replace]] rules run BEFORE the token pass here too: a rule's
        # rendered FROM may embed an identity token (e.g. "{package_name}-extra");
        # the token pass would rewrite that token out from under the rule.
        for rule, frm, to in rendered:
            if rule.paths and rule_matches_path(rule, posix):
                new = new.replace(frm, to)
        for f, cur, repl in pairs:
            if f in RENAME_FIELDS:
                if f in substring_fields:
                    new = new.replace(cur, repl)
                else:
                    new = replace_token(new, f, cur, repl)
        if component and not new:
            # A substitution that empties a path segment would collapse the
            # path into its parent (cookiecutter #1518's corruption class).
            raise ValidationError(
                f"rename would empty a path component of {posix!r} — refusing"
            )
        if new in (".", ".."):
            # A substituted component rendering to exactly "." or ".."
            # would collapse the path into itself/its parent or escape the
            # tree entirely — the same corruption class as the empty-
            # component guard above, just via a different degenerate value.
            raise ValidationError(
                f"rename would collapse a path component of {posix!r} to "
                f"{new!r} — refusing"
            )
        parts.append(new)
    return Path(*parts)


def build_plan(target: Path, source: Identity, dest: Identity, rules: Rules) -> Plan:
    """Resolve what apply() would do; executes nothing."""
    source.validate()
    dest.validate()
    plan = Plan()
    pairs = replacement_pairs(source, dest, rules.display_forms)
    rendered = rendered_replace_rules(rules, source, dest)
    rename_map: dict[str, str] = {}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        text = _read_text(path)
        if text is not None:
            for rule, frm, to in rendered:
                if rule.content and rule_matches_path(rule, rel.as_posix()):
                    if frm in text:
                        plan.items.append(
                            PlanItem(
                                "replace", rel.as_posix(), f"rule {frm!r} -> {to!r}"
                            )
                        )
            hit_fields = [
                f
                for f, cur, _ in pairs
                if (
                    (cur in text)
                    if f in rules.substring_rewrite_fields
                    else token_occurs(text, f, cur)
                )
            ]
            if hit_fields:
                plan.items.append(
                    PlanItem("replace", rel.as_posix(), f"fields={hit_fields}")
                )
        new_rel = _renamed_rel(rel, pairs, rendered, rules.substring_rewrite_fields)
        if new_rel != rel:
            # collapse to the shallowest differing ancestor (dir rename)
            for i, (old_part, new_part) in enumerate(
                zip(rel.parts, new_rel.parts, strict=True)
            ):
                if old_part != new_part:
                    # The root 'press' component never differs (protected in
                    # _renamed_rel), so the first diff is always a renamable
                    # component — no root-press guard is needed here.
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
    rendered: list[tuple[ReplaceRule, str, str]],
) -> None:
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target).as_posix()
        text = _read_text(path)
        if text is None:
            kind = "symlink" if path.is_symlink() else "binary"
            report.skipped.append(f"replace {rel} ({kind})")
            continue
        new_text = text
        # [[replace]] rules run BEFORE the token pass: a rule's rendered
        # FROM may embed an identity token (e.g. "{package_name}-extra");
        # the token pass would rewrite that token out from under the rule.
        for rule, frm, to in rendered:
            if rule.content and rule_matches_path(rule, rel):
                new_text = new_text.replace(frm, to)
        for f, cur, repl in pairs:
            if f in rules.substring_rewrite_fields:
                # Opt-in per-field substring mode (codesign sec-02 secondary):
                # plain replacement, no boundary guard — gated on the target
                # declaring the token word-disjoint in press-rules.toml.
                new_text = new_text.replace(cur, repl)
            else:
                new_text = replace_token(new_text, f, cur, repl)
        if new_text != text:
            # Route through safe_write: its assert_under_root closes the
            # ancestor-symlink hole (a symlinked ancestor would write OUTSIDE
            # the target), and its atomic temp + os.replace makes the write
            # hardlink-SAFE (a new inode). refuse_hardlink=False because that
            # atomicity already protects an external hardlink WITHOUT falsely
            # refusing a legitimate in-repo hardlinked file. A symlink LEAF
            # never reaches here — _read_text returns None for it upstream.
            safe_write(target, rel, new_text, refuse_hardlink=False)
            report.replaced.append(rel)


def _retarget_symlinks(
    target: Path,
    pairs: list[tuple[str, str, str]],
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]] | None = None,
    substring_fields: Collection[str] = frozenset(),
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

    Dispatch per field mirrors ``_apply_replacements``: a field in
    ``substring_fields`` uses plain substring replacement (glued-token
    coverage, codesign sec-02 secondary); every other field uses the
    boundary-guarded ``replace_token``.

    A ``paths = true`` [[replace]] rule (Fix F2) is also applied to the link
    text, mirroring ``_renamed_rel``/the rename pass exactly: symlink text
    follows exactly what the rename pass moves, so a rule renaming
    ``plbp-web/`` -> ``acme-web/`` must retarget ``link -> plbp-web/data``
    too, or the link keeps pointing at a path the rename pass just moved
    away from under it. A ``content``-only rule (``paths=False``) must NOT
    touch link text — mirror-image of the display-pair exclusion below.
    Rules run BEFORE the field-pair pass (same order as
    ``_apply_replacements``/``_renamed_rel``), scoped by the SYMLINK's own
    rel posix — consistent with how the rename pass scopes by the renamed
    file's path.
    """
    rendered = rendered or []
    target_r = target.resolve()
    for rel in _git_listed(target):
        path = target / rel
        if not path.is_symlink():
            continue
        link = os.readlink(path)
        if os.path.isabs(link):
            continue  # never rewrite or follow an absolute target
        new_link = link
        posix = rel.as_posix()
        for rule, frm, to in rendered:
            if rule.paths and rule_matches_path(rule, posix):
                new_link = new_link.replace(frm, to)
        for f, cur, repl in pairs:
            if f in substring_fields:
                new_link = new_link.replace(cur, repl)
            else:
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
        # Validate the LINK LOCATION's ancestors (not just the sink): a
        # symlinked ancestor of `path` would land unlink/symlink OUTSIDE the
        # target. Fail closed (propagate) on a hostile ancestor — never
        # silently skip a containment violation.
        assert_ancestors_real(path, target)
        os.unlink(path)
        os.symlink(new_link, path)
        report.replaced.append(rel.as_posix())


def apply(target: Path, source: Identity, dest: Identity, rules: Rules) -> ApplyReport:
    """Execute the rebrand: replace pass, symlink-retarget pass, rename pass."""
    source.validate()
    dest.validate()
    report = ApplyReport()
    pairs = replacement_pairs(source, dest, rules.display_forms)
    rendered = rendered_replace_rules(rules, source, dest)
    _apply_replacements(target, pairs, rules, report, rendered)
    # Symlink text must only be rewritten where the rename pass would move
    # the target — display forms never rename paths (not in RENAME_FIELDS),
    # so a display pair would rewrite a link's text out from under a
    # directory that keeps its original name (dangling link). Drop them
    # before retargeting. `rendered` IS passed through in full (Fix F2): a
    # paths=true rule (any field) is exactly what moves a path, so retarget
    # must follow every such rule the same way the rename pass does.
    symlink_pairs = [p for p in pairs if not p[0].startswith("display_name_")]
    _retarget_symlinks(
        target, symlink_pairs, report, rendered, rules.substring_rewrite_fields
    )
    _apply_renames(target, pairs, rules, report, rendered)
    return report


def _rename_pass_once(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]],
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
        new_rel = _renamed_rel(rel, pairs, rendered, rules.substring_rewrite_fields)
        if new_rel == rel:
            continue
        for i, (old_part, new_part) in enumerate(
            zip(rel.parts, new_rel.parts, strict=True)
        ):
            if old_part != new_part:
                # The root 'press' component never differs (protected in
                # _renamed_rel), so the first diff is always a renamable
                # component — no root-press guard is needed here.
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
        if dst.is_symlink():
            # `Path.exists()` FOLLOWS symlinks — a DANGLING symlink at dst
            # reads as absent there, so without this lstat-based check
            # POSIX rename() would silently replace the symlink itself
            # (a destructive in-tree overwrite the destination-occupied
            # check was meant to prevent).
            report.skipped.append(f"rename {old} (destination is a symlink)")
            continue
        # A symlinked ancestor on either endpoint would move CONTENT through a
        # symlink out of the target. Tolerates a token-bearing symlink LEAF
        # (renaming a symlink is legitimate); fails closed (propagates) on a
        # symlinked ancestor.
        assert_ancestors_real(src, target)
        assert_ancestors_real(dst, target)
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
    rendered: list[tuple[ReplaceRule, str, str]],
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
        if not _rename_pass_once(target, pairs, rules, report, rendered):
            return
