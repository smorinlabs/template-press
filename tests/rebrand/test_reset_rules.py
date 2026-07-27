"""P05-TS01 — [[reset]] schema + config-load validation + stub handling.

D1/D6: declared only, target key is `file` (not prior art's `path`), stub
content from exactly one of `stub` (inline) or `stub_file` (contained local
path), UTF-8 fail-closed, and a stub may not restore the identity its reset
exists to remove (changed-only paranoid scan + rendered FROM literals).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.reset import (
    load_stub_content,
    read_reset_target_text,
    scan_stub_text,
)
from template_press.rebrand.rules import ResetRule, load_rules

from .conftest import DEST, SOURCE, requires_symlink


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


RESET_CHANGELOG = '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n'


# ---------------------------------------------------------------------------
# Schema — shape, types, and config-load validation
# ---------------------------------------------------------------------------
class TestResetSchema:
    def test_valid_inline_stub_parses(self, tmp_path: Path):
        target = _write_rules(tmp_path, RESET_CHANGELOG)
        (rule,) = load_rules(target).reset
        assert isinstance(rule, ResetRule)
        assert rule.file == "CHANGELOG.md"
        assert rule.stub == "# Changelog\n"
        assert rule.stub_file is None

    def test_valid_stub_file_parses(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[reset]]\nfile = "CHANGELOG.md"\n'
            'stub_file = "press/stubs/CHANGELOG.md"\n',
        )
        (rule,) = load_rules(target).reset
        assert rule.stub is None
        assert rule.stub_file == "press/stubs/CHANGELOG.md"

    def test_empty_inline_stub_allowed(self, tmp_path: Path):
        target = _write_rules(tmp_path, '[[reset]]\nfile = "CHANGELOG.md"\nstub = ""\n')
        (rule,) = load_rules(target).reset
        assert rule.stub == ""

    def test_stub_and_stub_file_together_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# C\\n"\n'
            'stub_file = "press/stubs/CHANGELOG.md"\n',
        )
        with pytest.raises(ValidationError, match="stub"):
            load_rules(target)

    def test_neither_stub_nor_stub_file_rejected(self, tmp_path: Path):
        target = _write_rules(tmp_path, '[[reset]]\nfile = "CHANGELOG.md"\n')
        with pytest.raises(ValidationError, match="stub"):
            load_rules(target)

    def test_prior_art_path_key_rejected(self, tmp_path: Path):
        """The target key is `file` — the [[regenerate]] key, one vocabulary
        across press-rules.toml; prior art's `path` must fail loud."""
        target = _write_rules(
            tmp_path, '[[reset]]\npath = "CHANGELOG.md"\nstub = "# C\\n"\n'
        )
        with pytest.raises(ValidationError, match="path"):
            load_rules(target)

    def test_unknown_key_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# C\\n"\nmode = "w"\n',
        )
        with pytest.raises(ValidationError, match="mode"):
            load_rules(target)

    @pytest.mark.parametrize(
        "file_toml",
        [
            'file = "/etc/passwd"',
            'file = "../outside.md"',
            'file = ".git/config"',
            'file = ""',
            "file = 3",
            "",  # missing
        ],
    )
    def test_unsafe_file_rejected(self, tmp_path: Path, file_toml: str):
        target = _write_rules(tmp_path, f'[[reset]]\n{file_toml}\nstub = "x"\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    @pytest.mark.parametrize(
        "reserved",
        ["press/press-receipt.toml", "press/press-source.toml"],
    )
    def test_root_control_rejected(self, tmp_path: Path, reserved: str):
        target = _write_rules(
            tmp_path,
            f'[[reset]]\nfile = "{reserved}"\nstub = "x"\n'
            f"[rules]\n"
            f'extra_exclude_files = ["{reserved}"]\n',
        )
        with pytest.raises(ValidationError, match="control"):
            load_rules(target)

    def test_duplicate_targets_rejected(self, tmp_path: Path):
        """Wave-3 3654059282/3654059283: two [[reset]] entries for one file
        would write twice with an order-dependent survivor — config error."""
        target = _write_rules(
            tmp_path,
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# A\\n"\n'
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# B\\n"\n',
        )
        with pytest.raises(ValidationError, match="duplicate"):
            load_rules(target)

    def test_target_not_in_exclude_files_rejected(self, tmp_path: Path):
        """The reset⊗replace overlap ban: a non-excluded reset target is
        also rewritten by the replace pass, so the result would depend on
        pass order — refuse at config load."""
        target = _write_rules(
            tmp_path, '[[reset]]\nfile = "README.md"\nstub = "# R\\n"\n'
        )
        with pytest.raises(ValidationError, match="exclude_files"):
            load_rules(target)

    def test_target_in_extra_exclude_files_accepted(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["HISTORY.md"]\n'
            '[[reset]]\nfile = "HISTORY.md"\nstub = "# H\\n"\n',
        )
        (rule,) = load_rules(target).reset
        assert rule.file == "HISTORY.md"

    @pytest.mark.parametrize(
        "stub_toml",
        [
            "stub = 3",  # non-string stub
            'stub_file = ""',  # empty stub_file
            'stub_file = "/abs/stub.md"',  # absolute
            'stub_file = "../stub.md"',  # traversal
            "stub_file = 3",  # non-string
        ],
    )
    def test_malformed_stub_sources_rejected(self, tmp_path: Path, stub_toml: str):
        target = _write_rules(
            tmp_path, f'[[reset]]\nfile = "CHANGELOG.md"\n{stub_toml}\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)


# ---------------------------------------------------------------------------
# Plan-time stub loading — containment, no-follow, UTF-8 fail-closed
# ---------------------------------------------------------------------------
class TestStubLoading:
    def test_inline_stub_returned_verbatim(self, tmp_path: Path):
        rule = ResetRule(file="CHANGELOG.md", stub="# Changelog\n")
        assert load_stub_content(tmp_path, rule) == "# Changelog\n"

    def test_stub_file_content_read(self, tmp_path: Path):
        stubs = tmp_path / "press" / "stubs"
        stubs.mkdir(parents=True)
        (stubs / "CHANGELOG.md").write_text("# Fresh\n", encoding="utf-8")
        rule = ResetRule(file="CHANGELOG.md", stub_file="press/stubs/CHANGELOG.md")
        assert load_stub_content(tmp_path, rule) == "# Fresh\n"

    def test_missing_stub_file_refused(self, tmp_path: Path):
        rule = ResetRule(file="CHANGELOG.md", stub_file="press/stubs/missing.md")
        with pytest.raises(ValidationError):
            load_stub_content(tmp_path, rule)

    @requires_symlink
    def test_symlink_stub_file_refused(self, tmp_path: Path):
        outside = tmp_path.parent / "outside-stub.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        stubs = tmp_path / "press" / "stubs"
        stubs.mkdir(parents=True)
        os.symlink(outside, stubs / "CHANGELOG.md")
        rule = ResetRule(file="CHANGELOG.md", stub_file="press/stubs/CHANGELOG.md")
        with pytest.raises((ValidationError, ValueError)):
            load_stub_content(tmp_path, rule)

    def test_non_utf8_stub_file_refused(self, tmp_path: Path):
        stubs = tmp_path / "press" / "stubs"
        stubs.mkdir(parents=True)
        (stubs / "CHANGELOG.md").write_bytes(b"\xff\xfe broken")
        rule = ResetRule(file="CHANGELOG.md", stub_file="press/stubs/CHANGELOG.md")
        with pytest.raises(ValidationError, match="UTF-8"):
            load_stub_content(tmp_path, rule)

    def test_non_utf8_reset_target_refused(self, tmp_path: Path):
        """Reset reads bytes as text, fail closed: an undecodable target
        refuses at plan time (the line count / preview interpret text)."""
        (tmp_path / "CHANGELOG.md").write_bytes(b"\xff\xfe history")
        rule = ResetRule(file="CHANGELOG.md", stub="# C\n")
        with pytest.raises(ValidationError, match="UTF-8"):
            read_reset_target_text(tmp_path, rule)

    def test_reset_target_text_read(self, tmp_path: Path):
        (tmp_path / "CHANGELOG.md").write_text("## v1\n## v2\n", encoding="utf-8")
        rule = ResetRule(file="CHANGELOG.md", stub="# C\n")
        assert read_reset_target_text(tmp_path, rule) == "## v1\n## v2\n"


# ---------------------------------------------------------------------------
# Stub-content scan — a stub may not restore old identity
# ---------------------------------------------------------------------------
def _rules_with(tmp_path: Path, body: str):
    return load_rules(_write_rules(tmp_path, body))


class TestStubScan:
    def test_changed_token_flagged(self, tmp_path: Path):
        """SOURCE app_name "press" changes to "potato" — a stub carrying
        `press` as an identity token would neutralize the exclusion while
        keeping old identity in the tree."""
        rules = _rules_with(tmp_path, RESET_CHANGELOG)
        problems = scan_stub_text(
            "# Changelog\nRun press to rebuild.\n",
            rel="CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
        )
        assert problems and any("press" in p for p in problems)

    def test_boundary_safe_word_not_flagged(self, tmp_path: Path):
        """`compress` must not fire the app_name=press matcher — the paranoid
        matcher still honors the leading alphanumeric boundary."""
        rules = _rules_with(tmp_path, RESET_CHANGELOG)
        assert (
            scan_stub_text(
                "# Changelog\nCompress the archive before delivery.\n",
                rel="CHANGELOG.md",
                source=SOURCE,
                dest=DEST,
                rules=rules,
            )
            == []
        )

    def test_unchanged_field_not_flagged(self, tmp_path: Path):
        """Changed-only: an author kept across the press legitimately
        remains — flagging it would fail every partial rebrand."""
        rules = _rules_with(tmp_path, RESET_CHANGELOG)
        same_author_dest = Identity(
            package_name=DEST.package_name,
            repo_name=DEST.repo_name,
            app_name=DEST.app_name,
            author=SOURCE.author,
            email=DEST.email,
            owner=DEST.owner,
        )
        assert (
            scan_stub_text(
                f"# Changelog\nMaintained by {SOURCE.author}.\n",
                rel="CHANGELOG.md",
                source=SOURCE,
                dest=same_author_dest,
                rules=rules,
            )
            == []
        )

    def test_rendered_from_literal_flagged(self, tmp_path: Path):
        rules = _rules_with(
            tmp_path,
            RESET_CHANGELOG
            + '[[replace]]\npattern = "v1-{app_name}"\nreason = "legacy tag"\n',
        )
        problems = scan_stub_text(
            "# Changelog\nSee the v1-press notes.\n",
            rel="CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
        )
        assert any("v1-press" in p for p in problems)

    def test_clean_stub_passes(self, tmp_path: Path):
        rules = _rules_with(tmp_path, RESET_CHANGELOG)
        assert (
            scan_stub_text(
                "# Changelog\n",
                rel="CHANGELOG.md",
                source=SOURCE,
                dest=DEST,
                rules=rules,
            )
            == []
        )
