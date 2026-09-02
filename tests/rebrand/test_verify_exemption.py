"""P04-TS09 — hermetic-verify exemption semantics.

D3: the exemption requires BOTH the tool-side cap (basename on the explicit
REGENERATE_EXEMPTIBLE constant — never derived from exclude_files) AND the
target's declaration for that exact path, TRANSLATED through the sandbox
press's renames (declared source-coordinate outputs have moved by scan
time). The exemption is a coverage gap and verify must say so: exempt files
are listed as not-verified in the report (human and --json), exit 0 keeps
meaning "clean over the SCANNED set", and the press receipt records each
skipped file with its reason.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.engine import (
    REGENERATE_EXEMPTIBLE,
    build_plan,
    scan_paths,
)
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, SOURCE, write_answers_file
from .test_verify_cli import _commit, make_pressable

PY = sys.executable


def test_exemptible_cap_is_the_explicit_constant():
    """Never derived from exclude_files (CHANGELOG.md-class artifacts must
    not be exemptible) nor from any rules default (removed with D1)."""
    assert REGENERATE_EXEMPTIBLE == frozenset({"uv.lock", "bun.lock"})
    assert "CHANGELOG.md" not in REGENERATE_EXEMPTIBLE
    assert "package-lock.json" not in REGENERATE_EXEMPTIBLE


class TestScanPathsTranslation:
    def test_nested_declared_output_exempt_at_translated_path(self, tmp_path: Path):
        """Basename-on-cap matches a nested bun.lock, and the declared
        exact path is translated through the renames before comparison —
        without the translation the path half would fail forever."""
        target = tmp_path / "target"
        moved = target / "packages" / "potato_launcher"
        moved.mkdir(parents=True)
        (moved / "bun.lock").write_text("lock\n", encoding="utf-8")
        press = target / "press"
        press.mkdir()
        (press / "press-rules.toml").write_text(
            "[rules]\n"
            'extra_exclude_files = ["packages/demo_widget/bun.lock"]\n'
            "[[regenerate]]\n"
            'file = "packages/demo_widget/bun.lock"\n'
            'command = ["bun", "install"]\n',
            encoding="utf-8",
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "init", "-q", "-b", "main"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        rules = load_rules(target)
        renames = {"packages/demo_widget": "packages/potato_launcher"}
        rels = {e.rel.as_posix() for e in scan_paths(target, rules, renamed=renames)}
        assert "packages/potato_launcher/bun.lock" not in rels  # exempt
        # without the rename map the declared path matches nothing → scanned
        rels_untranslated = {e.rel.as_posix() for e in scan_paths(target, rules)}
        assert "packages/potato_launcher/bun.lock" in rels_untranslated


class TestVerifyExemption:
    def test_nested_declared_output_verifies_clean(self, tmp_path: Path) -> None:
        """End-to-end: a nested declared bun.lock carrying source identity
        is exempt in the sandbox (where no command ever runs) — the real
        press's post-command scan is what certifies it instead."""
        repo = make_pressable(tmp_path)
        pkg_dir = repo / "packages" / "demo_widget"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "index.js").write_text("// demo_widget module\n", encoding="utf-8")
        (pkg_dir / "bun.lock").write_text('{"name": "demo_widget"}\n', encoding="utf-8")
        (repo / "press" / "press-rules.toml").write_text(
            "[rules]\n"
            'extra_exclude_files = ["packages/demo_widget/bun.lock"]\n'
            "[[regenerate]]\n"
            'file = "packages/demo_widget/bun.lock"\n'
            'command = ["bun", "install"]\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 0

    def test_changelog_declaration_cannot_buy_exemption(self, tmp_path: Path) -> None:
        """A declared regeneration for CHANGELOG.md (validly excluded) must
        NOT exempt it — its basename is off the tool cap, so surviving
        identity in it still fails verify."""
        repo = make_pressable(tmp_path)
        (repo / "CHANGELOG.md").write_text(
            "## demo_widget release notes\n", encoding="utf-8"
        )
        (repo / "press" / "press-rules.toml").write_text(
            "[[regenerate]]\n"
            'file = "CHANGELOG.md"\n'
            'command = ["some-changelog-tool"]\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 1

    def test_exempt_files_listed_in_json_report(self, tmp_path: Path, capsys):
        repo = make_pressable(tmp_path)
        (repo / "uv.lock").write_text('name = "demo_widget"\n', encoding="utf-8")
        (repo / "press" / "press-rules.toml").write_text(
            '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["verified"] is True
        (entry,) = payload["exempt"]
        assert entry["file"] == "uv.lock"
        assert entry["reason"]  # each skipped file carries WHY it was skipped

    def test_exempt_files_listed_in_human_output(self, tmp_path: Path, capsys):
        """Not-verified rather than omitted: a clean result must read as
        'clean over the scanned set', with the gap visible."""
        repo = make_pressable(tmp_path)
        (repo / "uv.lock").write_text('name = "demo_widget"\n', encoding="utf-8")
        (repo / "press" / "press-rules.toml").write_text(
            '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "uv.lock" in out
        assert "exempt" in out or "not verified" in out


class TestReceiptExempt:
    def test_receipt_records_skipped_files_with_reasons(
        self, src_target: Path, tmp_path: Path
    ):
        from template_press.rebrand.config import render_source_config

        (src_target / "bun.lock").write_text("lockdata\n", encoding="utf-8")
        (src_target / "HISTORY.md").write_text("old history\n", encoding="utf-8")
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            "[rules]\n"
            'extra_exclude_files = ["HISTORY.md"]\n'
            "[[regenerate]]\n"
            'file = "bun.lock"\n'
            f"command = ['{PY}', '-c', "
            '\'import pathlib; pathlib.Path("bun.lock").write_text("clean")\']\n'
            "[[reset]]\n"
            'file = "HISTORY.md"\nstub = "# History\\n"\n',
            encoding="utf-8",
        )
        (src_target / "press" / "press-source.toml").write_text(
            render_source_config(SOURCE), encoding="utf-8"
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "commit", "-q", "-m", "setup"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        receipt = (src_target / RECEIPT_REL).read_text(encoding="utf-8")
        assert "[[press.exempt]]" in receipt
        assert "bun.lock" in receipt
        assert "HISTORY.md" in receipt


class TestVerifyModelsDeclaredResets:
    def test_declared_reset_target_verifies_clean(self, tmp_path: Path) -> None:
        """Codex thread 3654657444 (P1): the real press replaces a declared
        reset target with its validated stub at position zero, so the
        hermetic sandbox must model the same reset before scanning —
        otherwise verify exits 1 for a target the real press handles."""
        repo = make_pressable(tmp_path)
        (repo / "CHANGELOG.md").write_text(
            "## demo_widget 1.0 — by Demo Author\n", encoding="utf-8", newline=""
        )
        (repo / "press" / "press-rules.toml").write_text(
            '[[reset]]\nfile = "CHANGELOG.md"\nstub = "# Changelog\\n"\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 0

    def test_stub_file_under_renamed_directory(self, tmp_path: Path) -> None:
        """Codex 3654853355: stub contents are captured BEFORE the sandbox
        press — apply() renames identity-bearing directories, so a
        stub_file beneath one no longer resolves afterwards."""
        repo = make_pressable(tmp_path)
        stub_dir = repo / "packages" / "demo_widget"
        stub_dir.mkdir(parents=True)
        (stub_dir / "stub.md").write_text("# Changelog\n", encoding="utf-8", newline="")
        (repo / "CHANGELOG.md").write_text(
            "## demo_widget 1.0\n", encoding="utf-8", newline=""
        )
        (repo / "press" / "press-rules.toml").write_text(
            '[[reset]]\nfile = "CHANGELOG.md"\n'
            'stub_file = "packages/demo_widget/stub.md"\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo)]) == 0

    def test_exempt_paths_reported_in_source_coordinates(
        self, tmp_path: Path, capsys
    ) -> None:
        """Codex thread 3654657451: findings are mapped back to source
        coordinates before reporting; the exempt list must be too — the
        synthetic sandbox path does not exist in the user's repo."""
        repo = make_pressable(tmp_path)
        pkg = repo / "packages" / "demo_widget"
        pkg.mkdir(parents=True)
        (pkg / "index.js").write_text("// demo_widget\n", encoding="utf-8")
        (pkg / "bun.lock").write_text('{"name": "demo_widget"}\n', encoding="utf-8")
        (repo / "press" / "press-rules.toml").write_text(
            "[rules]\n"
            'extra_exclude_files = ["packages/demo_widget/bun.lock"]\n'
            "[[regenerate]]\n"
            'file = "packages/demo_widget/bun.lock"\n'
            'command = ["bun", "install"]\n',
            encoding="utf-8",
        )
        _commit(repo)
        assert verify_command(["--target", str(repo), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        (entry,) = payload["exempt"]
        assert entry["file"] == "packages/demo_widget/bun.lock"


class TestDeclaredExemption:
    """P08-T01/TS01 (issue #81): the tool cap stays the silent default; a
    target buys an exemption for any OTHER regenerated output only loudly —
    ``verify_exempt = true`` plus a required ``reason`` on the
    ``[[regenerate]]`` entry, committed where reviewers see it."""

    RULES_EXEMPT = (
        "[rules]\n"
        'extra_exclude_files = ["docs/generated-api.md"]\n'
        "[[regenerate]]\n"
        'file = "docs/generated-api.md"\n'
        'command = ["true"]\n'
        "verify_exempt = true\n"
        'reason = "rendered from source at build time; press cannot rewrite it"\n'
    )
    RULES_PLAIN = (
        "[rules]\n"
        'extra_exclude_files = ["docs/generated-api.md"]\n'
        "[[regenerate]]\n"
        'file = "docs/generated-api.md"\n'
        'command = ["true"]\n'
    )

    def _repo(self, tmp_path: Path, rules_body: str) -> Path:
        repo = make_pressable(tmp_path)
        gen = repo / "docs" / "generated-api.md"
        gen.parent.mkdir(exist_ok=True)
        gen.write_text("# demo_widget API\n", encoding="utf-8")
        (repo / "press" / "press-rules.toml").write_text(rules_body, encoding="utf-8")
        _commit(repo)
        return repo

    def test_declared_exemption_verifies_clean_with_reason_shown(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = self._repo(tmp_path, self.RULES_EXEMPT)
        assert verify_command(["--target", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "docs/generated-api.md" in out
        assert "rendered from source at build time" in out

    def test_without_declaration_the_output_still_fails_verify(
        self, tmp_path: Path
    ) -> None:
        """Pins the cap as the default: a non-lockfile declared regen
        without verify_exempt is scanned and leaks (dogfood PROBLEM-28)."""
        repo = self._repo(tmp_path, self.RULES_PLAIN)
        assert verify_command(["--target", str(repo)]) == 1

    def test_verify_exempt_requires_reason(self, tmp_path: Path) -> None:
        repo = self._repo(
            tmp_path,
            self.RULES_EXEMPT.replace(
                'reason = "rendered from source at build time; press cannot rewrite it"\n',
                "",
            ),
        )
        with pytest.raises(ValidationError):
            load_rules(repo)

    def test_reason_without_verify_exempt_is_rejected(self, tmp_path: Path) -> None:
        repo = self._repo(
            tmp_path,
            self.RULES_EXEMPT.replace("verify_exempt = true\n", ""),
        )
        with pytest.raises(ValidationError):
            load_rules(repo)

    def test_control_characters_in_reason_rejected(self, tmp_path: Path) -> None:
        repo = self._repo(
            tmp_path,
            self.RULES_EXEMPT.replace(
                'reason = "rendered from source at build time; press cannot rewrite it"\n',
                'reason = "line one\\u001b[31mforged report line"\n',
            ),
        )
        with pytest.raises(ValidationError):
            load_rules(repo)

    def test_explicitly_empty_reason_without_exempt_rejected(
        self, tmp_path: Path
    ) -> None:
        """`reason = ""` with no verify_exempt is dead config, not a pass."""
        repo = self._repo(
            tmp_path,
            self.RULES_PLAIN + 'reason = ""\n',
        )
        with pytest.raises(ValidationError):
            load_rules(repo)

    def test_real_press_receipt_carries_declared_reason_verbatim(
        self, tmp_path: Path
    ) -> None:
        repo = make_pressable(tmp_path)
        gen = repo / "docs" / "generated-api.md"
        gen.parent.mkdir(exist_ok=True)
        gen.write_text("# API reference\n", encoding="utf-8")  # identity-free
        (repo / "press" / "press-rules.toml").write_text(
            self.RULES_EXEMPT, encoding="utf-8"
        )
        _commit(repo)
        answers = write_answers_file(tmp_path, DEST)
        assert main(["--target", str(repo), "--config", str(answers)]) == 0
        receipt = (repo / RECEIPT_REL).read_text(encoding="utf-8")
        assert (
            'reason = "rendered from source at build time; '
            'press cannot rewrite it"' in receipt
        )


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


def test_regenerate_on_excluded_identity_bearing_source_fails_after_apply_without_receipt(
    src_target: Path, capsys: pytest.CaptureFixture
) -> None:
    """E3 — regression PIN, not TDD (see E3-review.md §4's "one test that
    must exist").

    This is an AFTER-APPLY leak failure, not a plan-time refusal ("refusal"
    in this CLI means exit 2, nothing written — see `preflight_*` gates).
    Neither `load_rules` nor `build_plan` rejects a `[[regenerate]]`
    declared against a normal, identity-bearing source file once that file
    is added to `extra_exclude_files` (confirmed empirically: both succeed
    for this exact rules body — the file-in-exclude_files check at parse
    time and the excluded-file preflight are satisfied because a
    `[[regenerate]]` declaration for the file exists, regardless of what
    its command actually does). What fails is later and functional, not an
    exception: `apply()` rewrites the rest of the tree first, then
    `execute_regenerations`' post-command leak scan (`regen.py`) finds the
    excluded file still carrying source identity — the `[[replace]]` pass
    never touched it — and `main()` reports `PressOutcome(success=False)`,
    printing to stderr and returning exit code 1 with NO receipt written.
    This is the same "leaks found, no receipt, target already rewritten —
    restore it first" contract every other leak failure uses
    (`press-target` SKILL.md step 5): `git checkout -- .` restores the
    excluded file's pre-press bytes exactly, which this test also pins.

    The declared command is `["true"]`, not a real formatter — the pin
    exercises the excluded-file leak boundary, not a specific tool, so it
    must not depend on PATH.
    """
    cli_py = src_target / "src" / "demo_widget" / "cli.py"
    pre_press_bytes = cli_py.read_bytes()
    _write_rules(
        src_target,
        '[rules]\nextra_exclude_files = ["src/demo_widget/cli.py"]\n'
        "[[regenerate]]\n"
        'file = "src/demo_widget/cli.py"\n'
        'command = ["true"]\n',
    )
    _commit(src_target)

    # Pin: neither load-time nor plan-time raises for this rules body.
    rules = load_rules(src_target)
    build_plan(src_target, SOURCE, DEST, rules)

    answers = write_answers_file(src_target.parent, DEST)
    rc = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--accept-discovery",
        ]
    )
    err = capsys.readouterr().err

    assert rc == 1
    assert not (src_target / RECEIPT_REL).exists()
    assert "src/demo_widget/cli.py" in err
    assert "still carries source" in err

    # Documented recovery path (press-target SKILL.md step 5): git restores
    # the excluded file's pre-press bytes exactly.
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "checkout", "--", "."],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    assert cli_py.read_bytes() == pre_press_bytes
