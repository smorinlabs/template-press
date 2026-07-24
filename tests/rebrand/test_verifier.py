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
from pathlib import Path

from template_press.rebrand.identity import Identity
from template_press.rebrand.rules import DEFAULT_RULES
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

    monkeypatch.setattr(verifier_mod.os, "readlink", _boom)

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
