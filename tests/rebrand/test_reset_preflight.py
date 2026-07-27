"""P05-TS03 — reset preflight and the two-level lines-based preview.

D5: validate before mutating — every reset target preflighted at plan time
with the NAMED write-path predicates (assert_under_root,
assert_ancestors_real, is_regular_lstat), git-tracked and clean (refused
even under --allow-dirty), UTF-8 fail-closed, under the
exit-2-nothing-written contract. D2: preview always present (path + line
count); the content excerpt sits behind the new --verbose flag, bounded at
20 lines. Wave-3 3654059289: the planned reset-path identity scan runs at
preflight — plan-time-knowable problems exit 2 before writes.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.identity import Identity
from template_press.rebrand.reset import (
    VERBOSE_PREVIEW_LINES,
    preflight_reset_targets,
    render_reset_plan,
    scan_reset_path,
)
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, load_rules

from .conftest import DEST, SOURCE, requires_symlink, write_answers_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


RESET_RULES = '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n'


def _setup_reset_target(
    target: Path,
    *,
    rules_body: str = RESET_RULES,
    changelog: str | bytes = "## v1\n## v2\n",
    commit: bool = True,
) -> None:
    (target / "press").mkdir(exist_ok=True)
    (target / "press" / "press-rules.toml").write_text(rules_body, encoding="utf-8")
    if isinstance(changelog, bytes):
        (target / "CHANGELOG.md").write_bytes(changelog)
    else:
        (target / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    if commit:
        _git(target, "add", "-A")
        _git(target, "commit", "-q", "-m", "add reset target + rules")


class TestResetPreflight:
    def test_tracked_clean_target_passes_with_preview(self, src_target: Path):
        _setup_reset_target(src_target, changelog="## v1\n## v2\n## v3\n")
        previews, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems == []
        (preview,) = previews
        assert preview.rule.file == "CHANGELOG.md"
        assert preview.line_count == 3
        assert preview.stub_text == "# Changelog\n"

    def test_untracked_target_refused(self, src_target: Path):
        _setup_reset_target(src_target, commit=False)
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems and "CHANGELOG.md" in problems[0]
        assert any("tracked" in p for p in problems)

    def test_dirty_target_refused(self, src_target: Path):
        _setup_reset_target(src_target)
        (src_target / "CHANGELOG.md").write_text("## edited\n", encoding="utf-8")
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert any("uncommitted" in p or "dirty" in p for p in problems)

    def test_missing_target_refused(self, src_target: Path):
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            RESET_RULES, encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "rules only, no changelog")
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems and "CHANGELOG.md" in problems[0]

    @requires_symlink
    def test_symlink_target_refused(self, src_target: Path):
        (src_target / "real.md").write_text("## v1\n", encoding="utf-8")
        os.symlink("real.md", src_target / "CHANGELOG.md")
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            RESET_RULES, encoding="utf-8"
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "symlink changelog")
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems and "CHANGELOG.md" in problems[0]

    @requires_symlink
    def test_symlinked_ancestor_refused(self, src_target: Path):
        outside = src_target.parent / "outside-docs"
        outside.mkdir()
        (outside / "HISTORY.md").write_text("## v1\n", encoding="utf-8")
        os.symlink(outside, src_target / "docs")
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            '[rules]\nextra_exclude_files = ["docs/HISTORY.md"]\n'
            '[[reset]]\nfile = "docs/HISTORY.md"\nstub = "# H\\n"\n',
            encoding="utf-8",
        )
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems and "docs/HISTORY.md" in problems[0]

    def test_non_utf8_target_refused(self, src_target: Path):
        _setup_reset_target(src_target, changelog=b"\xff\xfe history")
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert any("UTF-8" in p for p in problems)

    def test_stub_restoring_identity_refused(self, src_target: Path):
        _setup_reset_target(
            src_target,
            rules_body=(
                '[[reset]]\nfile = "CHANGELOG.md"\n'
                'stub = "# Changelog\\nRun press to rebuild.\\n"\n'
            ),
        )
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert any("press" in p and "stub" in p for p in problems)


class TestResetPathIdentityScan:
    """Wave-3 3654059289 / thread 3653398575: an excluded filename can
    itself carry changed identity, and downstream inventories never look at
    it — scanned at preflight on the TRANSLATED (post-rename) path."""

    SRC = Identity(
        package_name="demo_widget",
        repo_name="demo-widget",
        app_name="changelog",
        author="Demo Author",
        email="demo@example.com",
        owner="demolabs",
    )

    def test_path_carrying_changed_token_refused(self, src_target: Path):
        _setup_reset_target(src_target)
        _, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=self.SRC,
            dest=DEST,
            renames={},
        )
        assert any("CHANGELOG.md" in p and "changelog" in p for p in problems)

    def test_translated_path_is_what_gets_scanned(self, src_target: Path):
        """A reset target under an identity-bearing directory that THIS
        press renames is clean at its post-rename location — scanning the
        stale source path would false-refuse a valid config."""
        docs = src_target / "pkg_press"
        docs.mkdir()
        (docs / "HISTORY.md").write_text("## v1\n", encoding="utf-8")
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            '[rules]\nextra_exclude_files = ["pkg_press/HISTORY.md"]\n'
            '[[reset]]\nfile = "pkg_press/HISTORY.md"\nstub = "# H\\n"\n',
            encoding="utf-8",
        )
        _git(src_target, "add", "-A")
        _git(src_target, "commit", "-q", "-m", "nested reset target")
        rules = load_rules(src_target)
        # untranslated: the path still carries app_name "press" → refused
        _, problems = preflight_reset_targets(
            src_target, rules, source=SOURCE, dest=DEST, renames={}
        )
        assert any("pkg_press" in p for p in problems)
        # translated through the plan's rename map: clean → no problem
        _, problems = preflight_reset_targets(
            src_target,
            rules,
            source=SOURCE,
            dest=DEST,
            renames={"pkg_press": "pkg_potato"},
        )
        assert problems == []


class TestPreviewRendering:
    def _previews(self, src_target: Path, n_lines: int):
        body = "".join(f"## v{i}\n" for i in range(1, n_lines + 1))
        _setup_reset_target(src_target, changelog=body)
        previews, problems = preflight_reset_targets(
            src_target,
            load_rules(src_target),
            source=SOURCE,
            dest=DEST,
            renames={},
        )
        assert problems == []
        return previews

    def test_default_line_per_target_with_count(self, src_target: Path):
        previews = self._previews(src_target, 1234)
        out = render_reset_plan(previews, verbose=False)
        assert "CHANGELOG.md" in out
        assert "1,234 lines" in out
        assert "## v1" not in out  # no content excerpt without --verbose

    def test_verbose_excerpt_bounded_at_20_lines(self, src_target: Path):
        assert VERBOSE_PREVIEW_LINES == 20
        previews = self._previews(src_target, 50)
        out = render_reset_plan(previews, verbose=True)
        assert "## v1" in out
        assert "## v20" in out
        assert "## v21" not in out  # the excerpt is BOUNDED
        assert "# Changelog" in out  # the stub that would replace it


class TestCliResetGates:
    def _press_args(self, target: Path, tmp_path: Path, *extra: str) -> list[str]:
        answers = write_answers_file(tmp_path, DEST)
        return ["--target", str(target), "--config", str(answers), *extra]

    def _commit_source_config(self, target: Path) -> None:
        (target / "press").mkdir(exist_ok=True)
        (target / "press" / "press-source.toml").write_text(
            render_source_config(SOURCE), encoding="utf-8"
        )
        _git(target, "add", "-A")
        _git(target, "commit", "-q", "-m", "source config")

    def test_dirty_reset_target_exits_2_even_under_allow_dirty(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        _setup_reset_target(src_target)
        self._commit_source_config(src_target)
        (src_target / "CHANGELOG.md").write_text("## edited\n", encoding="utf-8")
        before = snapshot_target(src_target)
        code = main(self._press_args(src_target, tmp_path, "--allow-dirty"))
        assert code == 2
        assert "CHANGELOG.md" in capsys.readouterr().err
        assert snapshot_target(src_target) == before

    def test_dry_run_previews_reset_default_and_verbose(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        _setup_reset_target(src_target, changelog="## v1\n## v2\n")
        self._commit_source_config(src_target)
        code = main(self._press_args(src_target, tmp_path, "--dry-run"))
        out = capsys.readouterr().out
        assert code == 0
        assert "CHANGELOG.md" in out
        assert "2 lines" in out
        assert "## v1" not in out  # excerpt is verbose-gated

        code = main(self._press_args(src_target, tmp_path, "--dry-run", "--verbose"))
        out = capsys.readouterr().out
        assert code == 0
        assert "## v1" in out  # excerpt present under --verbose
        assert "# Changelog" in out


class TestResetPathRenderedLiteral:
    def test_rendered_path_literal_in_reset_path_fails(self):
        """Codex 3654974415 (P1): a paths-scoped rendered literal in the
        reset target's post-press path is flagged, mirroring the
        regenerated-output check — an excluded filename is invisible to
        every downstream inventory."""
        rules = dataclasses.replace(
            DEFAULT_RULES,
            replace=(
                ReplaceRule(
                    pattern="x{app_name}y",
                    reason="glued legacy name",
                    content=False,
                    paths=True,
                ),
            ),
        )
        problems = scan_reset_path(
            "xpressy.lock", "xpressy.lock", source=SOURCE, dest=DEST, rules=rules
        )
        assert problems
        assert any("xpressy" in p for p in problems)
