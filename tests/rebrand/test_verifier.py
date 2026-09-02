"""Occurrence-level scan — `verifier.scan` (Task 7).

The paranoid scanner at the heart of `press verify`: unlike
`doctor.find_leaks` (presence/absence only), `verifier.scan` returns one
`Finding` per OCCURRENCE, with line/column for content matches. Composes
`matcher.find_occurrences`, `engine.scan_paths`/`PathEntry`/`_is_root_press`,
and `safety.is_regular_lstat` — see verifier.py's module docstring.

Fixture identity mirrors conftest: SOURCE app_name="press",
package_name="demo_widget"; DEST app_name="potato",
package_name="potato_launcher" — so English word-traps (compress, express,
pressure) and separator-normalized (hyphen/underscore) forms are exercised.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

from template_press.rebrand.identity import Identity
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
from template_press.rebrand.verifier import Finding, scan

from .conftest import DEST, SOURCE, requires_symlink

FIELDS: tuple[str, ...] = tuple(SOURCE.as_dict().keys())
NO_SUBSTRING: frozenset[str] = frozenset()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _git_add_all(repo: Path) -> None:
    _git(repo, "add", "-A")


def _identity(**overrides):
    base = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    base.update(overrides)
    return Identity(**base)


def test_hyphen_filename_found(src_target: Path):
    (src_target / "demo-widget_x.md").write_text("notes\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add hyphen filename")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    assert any(
        f.path == "demo-widget_x.md" and f.where == "filename" and f.line is None
        for f in findings
    )


def test_compress_in_readme_not_found(src_target: Path):
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    trap_line = (
        "Compress the archive before express delivery; do not let the pressure rise."
    )
    # The English-word trap line must produce NO findings at all (boundary
    # safety inherited from matcher.find_occurrences).
    assert not any(f.context == trap_line for f in findings)
    # Positive control: the legitimate standalone `press` token IS found.
    assert any(
        f.where == "content" and f.field == "app_name" and "press --help" in f.context
        for f in findings
    )


def test_two_leaks_one_line_distinct_columns(src_target: Path):
    (src_target / "leak.txt").write_text("press press\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add same-line double leak")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [
        f
        for f in findings
        if f.path == "leak.txt" and f.where == "content" and f.field == "app_name"
    ]
    assert len(hits) == 2
    cols = sorted(f.col for f in hits)
    assert cols == [0, 6]
    assert all(f.line == 1 for f in hits)


def test_png_binary_embedding_matches_where_binary(src_target: Path):
    marker = b"demo_widget"
    fake_png = (
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + marker + b"\x00\x01\x02\x03"
    )
    (src_target / "asset.png").write_bytes(fake_png)
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add fake png embedding demo_widget")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "asset.png"]
    assert len(hits) == 1
    hit = hits[0]
    assert hit.where == "binary"
    assert hit.line is None
    assert hit.field == "package_name"
    assert hit.col == fake_png.find(marker)


def test_binary_variant_matches_where_binary(src_target: Path):
    # G2 (false clean): a binary embedding a SEPARATOR/CASE variant of a source
    # value that NO field's exact byte form matches — camelCase `demoWidget` for
    # package_name `demo_widget` (repo_name is `demo-widget`, so neither exact
    # form is present). apply() cannot rewrite binary content, so the variant
    # survives; the OLD exact-only byte scan missed it -> false clean. The scan
    # must now be variant-aware (identifier-boundary matcher on the latin-1
    # bytes), consistent with text.
    marker = b"demoWidget"
    fake = b"\x89PNG\r\n\x1a\n\x00\x00" + marker + b"\x00\x01\x02"
    (src_target / "camel.png").write_bytes(fake)
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "camelcase variant in binary")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "camel.png"]
    assert hits, "camelCase variant in a binary must be flagged (was a false clean)"
    assert all(h.where == "binary" and h.line is None for h in hits)
    # char span == byte offset (latin-1 is 1:1), so col is the byte offset.
    assert all(h.col == fake.find(marker) for h in hits)
    assert any(h.field == "package_name" for h in hits)
    # The README word-traps (compress/express/pressure) must STILL produce no
    # content finding — variant awareness must not reopen the word-trap.
    trap = "Compress the archive before express delivery; do not let the pressure rise."
    assert not any(f.context == trap for f in findings)


def test_unreadable_file_is_unscannable(src_target: Path):
    if os.name == "nt" or os.geteuid() == 0:
        import pytest

        pytest.skip("permission semantics differ on Windows/root")
    secret = src_target / "secret.md"
    secret.write_text("demo_widget leak\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add file to later lock down")
    secret.chmod(0o000)
    try:
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=DEFAULT_RULES,
        )
    finally:
        secret.chmod(0o644)
    hits = [f for f in findings if f.path == "secret.md"]
    assert hits and all(
        f.where == "unscannable" and f.field == "io" and f.value == "unreadable"
        for f in hits
    )


def test_lstat_guard_failure_on_absent_file_is_unscannable_io(src_target: Path):
    """Defense-in-depth TOCTOU coverage: a path git's index still lists as a
    plain file (so `scan_paths` tags it `kind="file"`) but that is ABSENT
    from the working tree by read time — `is_regular_lstat` returns False
    (`os.lstat` raises `FileNotFoundError`) for it, so `_scan_file`'s guard
    fires and must flag it `unscannable`/`io`/`unreadable` rather than
    silently skip it.
    """
    ghost = src_target / "ghost.md"
    ghost.write_text("demo_widget leak\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add file to later remove from worktree")
    ghost.unlink()  # still tracked in the index; gone from the working tree
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "ghost.md"]
    assert len(hits) == 1
    hit = hits[0]
    assert hit.where == "unscannable"
    assert hit.field == "io"
    assert hit.value == "unreadable"
    assert hit.line is None
    assert hit.col is None


@requires_symlink
def test_scan_does_not_read_through_ancestor_swapped_after_inventory(
    src_target: Path, tmp_path: Path, monkeypatch
):
    nested = src_target / "swap" / "leaf.txt"
    nested.parent.mkdir()
    nested.write_text("clean\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "swap/leaf.txt"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaf.txt").write_text("demo_widget outside\n", encoding="utf-8")
    from template_press.rebrand import verifier

    real_select = verifier.select_verifier_entries

    def inventory_then_swap(snapshot, **kwargs):
        entries = real_select(snapshot, **kwargs)
        nested.unlink()
        nested.parent.rmdir()
        nested.parent.symlink_to(outside, target_is_directory=True)
        return entries

    monkeypatch.setattr(verifier, "select_verifier_entries", inventory_then_swap)

    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=("package_name",),
        substring_fields=frozenset(),
        rules=DEFAULT_RULES,
    )

    assert not any(
        finding.path == "swap/leaf.txt" and finding.field == "package_name"
        for finding in findings
    )
    assert any(
        finding.path == "swap/leaf.txt" and finding.where == "unscannable"
        for finding in findings
    )


@requires_symlink
def test_scan_does_not_read_leaf_swapped_after_lstat(
    src_target: Path, tmp_path: Path, monkeypatch
):
    leaf = src_target / "leaf-race.txt"
    leaf.write_text("clean\n", encoding="utf-8")
    _git(src_target, "add", leaf.name)
    _git(src_target, "commit", "-q", "-m", "add leaf race")
    outside = tmp_path / "outside-verifier.txt"
    outside.write_text("demo_widget outside\n", encoding="utf-8")
    from template_press.rebrand import verifier

    real_guard = verifier.is_regular_lstat
    swapped = False

    def guard_then_swap(path: Path) -> bool:
        nonlocal swapped
        result = real_guard(path)
        if path == leaf and result and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(outside)
        return result

    monkeypatch.setattr(verifier, "is_regular_lstat", guard_then_swap)

    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=("package_name",),
        substring_fields=frozenset(),
        rules=DEFAULT_RULES,
    )

    assert not any(
        finding.path == leaf.name and finding.field == "package_name"
        for finding in findings
    )
    assert any(
        finding.path == leaf.name and finding.where == "unscannable"
        for finding in findings
    )


@requires_symlink
def test_dangling_symlink_readlink_leak_is_i2_closure(src_target: Path):
    """I2 closure: a DANGLING symlink whose readlink text embeds a changed
    value must still produce a `where="symlink"` finding — the destination
    does not exist and is NEVER read; only the link string itself is
    scanned.
    """
    link = src_target / "link_to_backup"
    link_text = "nonexistent/demo_widget_backup"
    os.symlink(link_text, link)
    assert not link.resolve().exists()  # genuinely dangling
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add dangling symlink")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "link_to_backup"]
    assert any(
        f.where == "symlink"
        and f.field == "package_name"
        and f.context == link_text
        and f.line is None
        and f.col is None
        for f in hits
    )


def test_scan_binary_empty_needle_returns_empty_no_hang():
    """`_scan_binary` must not loop forever on an empty needle: `data.find(b"",
    start)` returns `start`, so an unguarded scan advances zero bytes each
    iteration. An empty value yields no findings (fast, bounded)."""
    from template_press.rebrand.verifier import _scan_binary

    assert (
        _scan_binary(b"some binary data", "asset.png", [("app_name", "")], frozenset())
        == []
    )


@requires_symlink
def test_symlink_readlink_oserror_is_unscannable(src_target: Path, monkeypatch):
    """A transient `os.readlink` failure on a listed `symlink` entry (stale
    TOCTOU tag / removed between lstat and read) must yield ONE
    `where="unscannable"` finding, not crash `scan()` — mirroring the
    `_scan_file` OSError convention (`field="io", value="unreadable"`)."""
    link = src_target / "link_to_x"
    os.symlink("nonexistent/demo_widget_backup", link)
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "add symlink")

    import template_press.rebrand.verifier as verifier_mod

    def _boom(_path, *a, **k):
        raise OSError("stale symlink")

    monkeypatch.setattr(verifier_mod, "readlink_nofollow", _boom)

    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "link_to_x"]
    assert len(hits) == 1
    hit = hits[0]
    assert hit.where == "unscannable"
    assert hit.field == "io"
    assert hit.value == "unreadable"
    assert hit.line is None
    assert hit.col is None


@requires_symlink
def test_untracked_symlink_matching_dir_only_ignore_pattern_is_scanned(
    src_target: Path, tmp_path: Path
):
    """E8: `node_modules/` is a DIRECTORY-only ignore pattern — an untracked
    SYMLINK named `node_modules` is not a directory to git, so it is not
    ignored, IS enumerated, IS scanned, and its finding must explain the
    near-miss (the operator incident this locks in as regression coverage)."""
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\nnode_modules/\n", encoding="utf-8"
    )
    _git(src_target, "commit", "-qam", "ignore")
    outside = tmp_path / "press" / "node_modules"  # link text embeds app_name
    outside.mkdir(parents=True)
    (src_target / "node_modules").symlink_to(outside)
    snapshot = capture_surface_snapshot(src_target)
    assert any(e.rel.as_posix() == "node_modules" for e in snapshot.entries)
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    f = next(x for x in findings if x.where == "symlink" and x.field == "app_name")
    assert f.note is not None
    assert "matches directories only" in f.note
    assert "node_modules/" in f.note
    assert "git add -A" in f.note


def test_untracked_file_matching_dir_only_ignore_pattern_gets_note(src_target: Path):
    """The same near-miss note applies to a plain untracked FILE (not just a
    symlink) whose name matches a directory-only pattern."""
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\nnode_modules/\n", encoding="utf-8"
    )
    _git(src_target, "commit", "-qam", "ignore")
    (src_target / "node_modules").write_text("press\n", encoding="utf-8")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "node_modules"]
    assert hits
    assert all(
        f.note is not None and "matches directories only" in f.note for f in hits
    )


@requires_symlink
def test_tracked_symlink_matching_dir_only_ignore_pattern_gets_no_note(
    src_target: Path, tmp_path: Path
):
    """A TRACKED symlink is force-addable by design (EMP-01) — the near-miss
    note only ever applies to an UNTRACKED entry, never a tracked one."""
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\nnode_modules/\n", encoding="utf-8"
    )
    outside = tmp_path / "press" / "node_modules"
    outside.mkdir(parents=True)
    (src_target / "node_modules").symlink_to(outside)
    _git(src_target, "add", "-A", "-f")
    _git(src_target, "commit", "-qm", "track the symlink anyway")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "node_modules"]
    assert hits
    assert all(f.note is None for f in hits)


def test_genuinely_unignorable_untracked_path_gets_no_note(src_target: Path):
    """An untracked entry with no near-miss pattern at all (nothing in
    `.gitignore` even resembles its name) gets no note — the probe must not
    invent one."""
    (src_target / "totally_unrelated_press_file.txt").write_text(
        "press\n", encoding="utf-8"
    )
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "totally_unrelated_press_file.txt"]
    assert hits
    assert all(f.note is None for f in hits)


# ---------------------------------------------------------------------------
# Fix round 1 (Sonnet + Codex adversarial review): pathspec-magic-safe
# probing, pinned core.excludesFile, note-source rendering.
# ---------------------------------------------------------------------------
def test_untracked_entry_with_leading_colon_name_gets_correct_note(src_target: Path):
    """[P1] A name STARTING WITH `:` is `check-ignore` pathspec-magic
    territory (a leading colon triggers magic-signature parsing) — verified
    empirically to silently match the WRONG pattern under the naive
    ``-- <path>/`` query shape. The `./`-prefixed, `-c
    core.literalPathspecs=true`, stdin-fed probe must still name the
    CORRECT pattern for a colon-led name, not silently misfire."""
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\n:oddname/\n", encoding="utf-8"
    )
    _git(src_target, "commit", "-qam", "ignore")
    (src_target / ":oddname").write_text("press\n", encoding="utf-8")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == ":oddname"]
    assert hits
    assert all(
        f.note is not None and "matches directories only" in f.note for f in hits
    )
    assert all(":oddname/" in (f.note or "") for f in hits)


def test_untracked_entry_with_bracket_in_name_gets_correct_note(src_target: Path):
    """[P1] A name containing `[`/`]` is `check-ignore` pathspec GLOB-magic
    territory (character-class wildcarding) unless neutralized. Must not
    crash and, when git resolves the query correctly (as verified
    empirically here), must still name the correct escaped pattern —
    the brief's own fallback ("or ... yields no note and no error") is the
    floor, not the target."""
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\ndemo\\[x\\]/\n", encoding="utf-8"
    )
    _git(src_target, "commit", "-qam", "ignore")
    (src_target / "demo[x]").write_text("press\n", encoding="utf-8")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "demo[x]"]
    assert hits
    # Either a correct note, or a clean no-note — never a crash (the
    # brief's own accepted floor for a pathspec git may still refuse).
    for f in hits:
        if f.note is not None:
            assert "matches directories only" in f.note


def test_note_source_for_out_of_tree_core_excludes_file_is_placeholder(
    src_target: Path, tmp_path: Path
):
    """[P2] `core.excludesFile` is resolved from the SAME snapshot the
    untracked-set came from (never re-queried ambiently), and an
    OUT-OF-TREE excludes path is never printed verbatim in the note — only
    the literal placeholder `<core.excludesFile>`."""
    excludes = tmp_path / "global-ignore"
    excludes.write_text("outside_lib/\n", encoding="utf-8")
    _git(src_target, "config", "core.excludesFile", str(excludes))
    (src_target / "outside_lib").write_text("press\n", encoding="utf-8")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "outside_lib"]
    assert hits
    note = hits[0].note
    assert note is not None
    assert "<core.excludesFile>:1" in note
    assert str(excludes) not in note


def test_note_source_for_in_tree_core_excludes_file_is_repo_relative(
    src_target: Path,
):
    """[P2] An excludes file INSIDE the target is rendered as a repo-relative
    path, never an absolute filesystem path."""
    (src_target / "team-ignore.txt").write_text("inside_lib/\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-qm", "add in-tree excludes file")
    _git(src_target, "config", "core.excludesFile", "team-ignore.txt")
    (src_target / "inside_lib").write_text("press\n", encoding="utf-8")
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=FIELDS,
        substring_fields=NO_SUBSTRING,
        rules=DEFAULT_RULES,
    )
    hits = [f for f in findings if f.path == "inside_lib"]
    assert hits
    note = hits[0].note
    assert note is not None
    assert "team-ignore.txt:1" in note
    assert str(src_target) not in note


def test_finding_dataclass_shape():
    f = Finding(
        path="a",
        field="app_name",
        value="press",
        where="content",
        line=1,
        col=0,
        context="press",
    )
    assert f.path == "a"
    assert f.where == "content"


class TestDisplayNameScan:
    def test_scan_flags_glued_display_variant(self, src_target: Path):
        (src_target / "README.md").write_text(
            "# PyLaunchBlueprint intro\n", encoding="utf-8"
        )
        _git_add_all(src_target)
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        findings = scan(
            src_target,
            src,
            dst,
            fields=("display_name",),
            substring_fields=NO_SUBSTRING,
            rules=DEFAULT_RULES,
        )
        assert any(f.field == "display_name" and f.where == "content" for f in findings)

    def test_sparse_identity_does_not_crash(self, src_target: Path):
        _git_add_all(src_target)
        findings = scan(
            src_target,
            _identity(),  # no display_name
            _identity(app_name="acme"),
            fields=("app_name", "display_name"),
            substring_fields=NO_SUBSTRING,
            rules=DEFAULT_RULES,
        )
        assert not any(f.field == "display_name" for f in findings)


class TestRenderedRuleFindings:
    """F1: `scan` must also hunt surviving rendered `[[replace]]` FROM
    literals — mirroring `doctor.find_leaks`'s `rendered_rules` scan, but
    emitting occurrence-level `Finding`s (``field="replace_rule",
    value=frm``) instead of presence-only `Leak`s. Fixture identity: SOURCE
    app_name="press" (conftest). Note `verifier.scan`'s own field-based
    matcher (`matcher.identity_pattern`) is deliberately MORE permissive
    than `identity.token_occurs` (it treats `_`/`-` as boundary-safe, not
    just alnum) — an underscore-glued form like doctor's `_press_owned` is
    ALREADY caught by the ordinary field scan here, so the genuinely
    rule-only-visible shape needs pure alnum glue on both sides:
    `pattern = "x{app_name}owned"` renders `xpressowned`, which even the
    paranoid matcher can't see (an `x` immediately precedes `press`,
    blocking its left boundary)."""

    def test_glued_content_leak_via_rule_only(self, src_target: Path):
        rule = ReplaceRule(pattern="x{app_name}owned", reason="test")
        (src_target / "conftest_extra.py").write_text("xpressowned\n", encoding="utf-8")
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        hits = [
            f
            for f in findings
            if f.path == "conftest_extra.py" and f.field == "replace_rule"
        ]
        assert hits and hits[0].value == "xpressowned" and hits[0].where == "content"
        assert hits[0].line == 1
        # The ordinary app_name field scan must NOT have caught it on its
        # own — proving the hit came from rule-aware scanning.
        assert not any(
            f.path == "conftest_extra.py" and f.field == "app_name" for f in findings
        )

    def test_duplicate_behavioral_rules_emit_one_finding(self, src_target: Path):
        rules = (
            ReplaceRule(pattern="x{app_name}owned", reason="first declaration"),
            ReplaceRule(pattern="x{app_name}owned", reason="second declaration"),
        )
        (src_target / "conftest_extra.py").write_text("xpressowned\n", encoding="utf-8")
        _git_add_all(src_target)

        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=rules),
        )

        assert [
            finding
            for finding in findings
            if finding.path == "conftest_extra.py" and finding.field == "replace_rule"
        ] == [
            Finding(
                "conftest_extra.py",
                "replace_rule",
                "xpressowned",
                "content",
                1,
                0,
                "xpressowned",
            )
        ]

    def test_content_rule_scoped_by_files_glob(self, src_target: Path):
        rule = ReplaceRule(
            pattern="x{app_name}owned", reason="test", files=("docs/**",)
        )
        (src_target / "conftest_extra.py").write_text("xpressowned\n", encoding="utf-8")
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        assert not any(f.field == "replace_rule" for f in findings)

    def test_path_component_leak_via_rule_only(self, src_target: Path):
        rule = ReplaceRule(
            pattern="-{app_name}.md", reason="test", paths=True, content=False
        )
        (src_target / "0001-press.md").write_text("x\n", encoding="utf-8")
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        hits = [
            f
            for f in findings
            if f.path == "0001-press.md" and f.field == "replace_rule"
        ]
        assert hits and hits[0].value == "-press.md" and hits[0].where == "filename"

    def test_no_false_positive_after_rule_actually_applied(self, src_target: Path):
        """Negative control: once the rule's rendered FROM is genuinely
        gone (a normal rewrite ran), passing rendered_rules must not
        manufacture a leak — `to` is never itself scanned for."""
        rule = ReplaceRule(
            pattern="-{app_name}.md", reason="test", paths=True, content=False
        )
        (src_target / "0001-potato.md").write_text("x\n", encoding="utf-8")
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        assert not any(f.field == "replace_rule" for f in findings)

    @requires_symlink
    def test_escaping_symlink_text_leak_via_rule_only(self, src_target: Path):
        """The exact F1 repro (paths rule `x{app_name}owned`, escaping
        symlink target `xpressowned`): the retarget pass refuses to rewrite
        an escaping symlink's target (containment), and the identity
        variant matcher can't see `press` inside the alnum glue on either
        side. Only the rule-aware symlink scan, scoped against the link's
        normalized TARGET path, catches it."""
        rule = ReplaceRule(
            pattern="x{app_name}owned", reason="test", paths=True, content=False
        )
        link = src_target / "escaping-link"
        os.symlink("../../outside/xpressowned", link)
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        hits = [f for f in findings if f.path == "escaping-link"]
        assert any(
            f.field == "replace_rule"
            and f.value == "xpressowned"
            and f.where == "symlink"
            for f in hits
        )
        assert not any(f.field == "app_name" for f in hits)

    def test_renamed_threading_recovers_pre_rename_scope(self, src_target: Path):
        """The independent verifier can still diagnose a legacy residual.

        P06 refuses this order-dependent path pipeline before any write, so
        seed the former post-rename shape directly. The index is re-staged
        after the move (mirroring `verify_cli._restage_sandbox`'s
        `git add -A -f`) so `scan_paths` reflects only the POST-rename tree.
        Without a re-stage, git's cached OLD path would itself satisfy the
        rule's `files` glob and mask whether `renamed` is load-bearing.
        """
        docs = src_target / "press_docs"
        docs.mkdir()
        (docs / "_press_guide.md").write_text("x\n", encoding="utf-8")
        _git_add_all(src_target)
        rule = ReplaceRule(
            pattern="_{app_name}_guide.md",
            reason="doc filename scoped to its own dir",
            files=("press_docs/**",),
            paths=True,
            content=False,
        )
        docs.rename(src_target / "potato_docs")
        assert (src_target / "potato_docs" / "_press_guide.md").exists()
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
            renamed=[("press_docs", "potato_docs")],
        )
        hits = [
            f
            for f in findings
            if f.path == "potato_docs/_press_guide.md" and f.field == "replace_rule"
        ]
        assert (
            hits
            and hits[0].value == "_press_guide.md"
            and hits[0].where == ("filename")
        )

    def test_renamed_omitted_misses_the_same_leak_red_evidence(self, src_target: Path):
        """RED: the same seeded residual is invisible without `renamed`."""
        docs = src_target / "press_docs"
        docs.mkdir()
        (docs / "_press_guide.md").write_text("x\n", encoding="utf-8")
        _git_add_all(src_target)
        rule = ReplaceRule(
            pattern="_{app_name}_guide.md",
            reason="doc filename scoped to its own dir",
            files=("press_docs/**",),
            paths=True,
            content=False,
        )
        docs.rename(src_target / "potato_docs")
        _git_add_all(src_target)
        findings = scan(
            src_target,
            SOURCE,
            DEST,
            fields=FIELDS,
            substring_fields=NO_SUBSTRING,
            rules=replace(DEFAULT_RULES, replace=(rule,)),
        )
        assert not any(f.field == "replace_rule" for f in findings)
