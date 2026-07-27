"""P04-TS07 — post-command postconditions, scans, and the final pass.

D3: scan-exemption is EARNED BY RESULT — after each command, the output
must exist (a deleting command is a failed regeneration), pass the full
containment/type recheck (a symlink swapped in by the command must not be
followed), decode as UTF-8 (fail closed, both ends of the two-point gate),
and pass the PARANOID changed-fields scan (matcher.find_occurrences, not
the doctor's conservative matcher) including rendered [[replace]] FROM
literals with reverse-mapped scopes and the translated output path's own
components. After the LAST command, a final pass re-validates every output,
every reset stub, and the press-owned control files (snapshot/revalidate).
The receipt records each regeneration's resolved argv (D5 revision).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL, write_receipt
from template_press.rebrand.regen import (
    RegenerationPlan,
    execute_regenerations,
    final_validation_pass,
    preflight_regenerate_outputs,
    snapshot_control_files,
    validate_control_files,
)
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    RegenerateRule,
    ResetRule,
    load_rules,
)

from .conftest import DEST, SOURCE, requires_symlink

PY = sys.executable


def _plan(file: str, *args: str) -> RegenerationPlan:
    rule = RegenerateRule(file=file, command=(PY, *args))
    return RegenerationPlan(rule=rule, executable=PY, env_present=(), env_absent=())


def _write_cmd(rel: str, content: str) -> tuple[str, str]:
    return (
        "-c",
        f"import pathlib; pathlib.Path({rel!r}).write_text({content!r})",
    )


def _target(tmp_path: Path, **files: str) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    for rel, content in files.items():
        path = target / rel.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return target


def _run(
    target: Path,
    plans: list[RegenerationPlan],
    renamed: dict[str, str] | None = None,
    rules=DEFAULT_RULES,
) -> tuple[list[str], ApplyReport]:
    report = ApplyReport()
    failed = execute_regenerations(
        target,
        plans,
        renamed or {},
        report,
        source=SOURCE,
        dest=DEST,
        rules=rules,
    )
    return failed, report


class TestPostCommandScan:
    def test_noop_command_leaving_identity_fails(self, tmp_path: Path):
        """The no-op regenerator case (D3): exit 0 with source identity
        still in the file must fail the press, not earn the exemption."""
        target = _target(tmp_path, **{"bun.lock": '{"name": "demo_widget"}\n'})
        failed, report = _run(target, [_plan("bun.lock", "-c", "pass")])
        assert failed == ["bun.lock"]
        assert report.regenerated == []
        assert any("demo_widget" in s for s in report.skipped)

    def test_glued_camel_variant_caught_by_paranoid_matcher(self, tmp_path: Path):
        """The evidence must be as strong as what it buys: the doctor's
        conservative matcher misses demoWidgetConfig; the paranoid one
        (matcher.find_occurrences) must catch it."""
        target = _target(tmp_path, **{"bun.lock": "demoWidgetConfig=1\n"})
        failed, _ = _run(target, [_plan("bun.lock", "-c", "pass")])
        assert failed == ["bun.lock"]

    def test_unchanged_field_not_flagged(self, tmp_path: Path):
        """Changed-fields only: a retained author in a correct, freshly
        regenerated lockfile is not a leak."""
        same_author_dest = Identity(
            package_name=DEST.package_name,
            repo_name=DEST.repo_name,
            app_name=DEST.app_name,
            author=SOURCE.author,
            email=DEST.email,
            owner=DEST.owner,
        )
        target = _target(tmp_path, **{"bun.lock": f"author: {SOURCE.author}\n"})
        report = ApplyReport()
        failed = execute_regenerations(
            target,
            [_plan("bun.lock", "-c", "pass")],
            {},
            report,
            source=SOURCE,
            dest=same_author_dest,
            rules=DEFAULT_RULES,
        )
        assert failed == []
        assert report.regenerated == ["bun.lock"]

    def test_rendered_from_literal_in_output_fails(self, tmp_path: Path):
        # "xpressy" is invisible to the boundary-honoring identity matcher
        # (glued on both sides), so only the rendered-literal scan can flag
        # it — the same coverage doctor.find_leaks and verifier.scan have.
        target = _target(tmp_path, **{"bun.lock": "tag: xpressy\n"})
        rules = load_rules(
            _rules_target(
                tmp_path,
                '[[replace]]\npattern = "x{app_name}y"\nreason = "legacy tag"\n',
            )
        )
        report = ApplyReport()
        failed = execute_regenerations(
            target,
            [_plan("bun.lock", "-c", "pass")],
            {},
            report,
            source=SOURCE,
            dest=DEST,
            rules=rules,
        )
        assert failed == ["bun.lock"]
        assert any("xpressy" in s for s in report.skipped)

    def test_rule_scope_reverse_mapped_through_renames(self, tmp_path: Path):
        """A rule scoped packages/demo_widget/** must still hit the moved
        output at packages/potato_launcher/ — scopes are written in SOURCE
        coordinates and the scan runs at the destination. The literal
        (xpressy) is identity-invisible, so ONLY a correctly reverse-mapped
        scope can produce the failure."""
        target = _target(
            tmp_path,
            **{"packages__potato_launcher__bun.lock": "tag: xpressy\n"},
        )
        rules = load_rules(
            _rules_target(
                tmp_path,
                '[[replace]]\npattern = "x{app_name}y"\nreason = "legacy"\n'
                'files = ["packages/demo_widget/**"]\n',
            )
        )
        report = ApplyReport()
        failed = execute_regenerations(
            target,
            [_plan("packages/demo_widget/bun.lock", "-c", "pass")],
            {"packages/demo_widget": "packages/potato_launcher"},
            report,
            source=SOURCE,
            dest=DEST,
            rules=rules,
        )
        assert failed == ["packages/demo_widget/bun.lock"]

    def test_translated_path_component_carrying_identity_fails(self, tmp_path: Path):
        """D3's path refinement: an identity token that doubles as the
        lockfile's own name survives in the FILENAME precisely because the
        output is excluded from the rename pass."""
        bun_source = Identity(
            package_name="demo_widget",
            repo_name="demo-widget",
            app_name="bun",
            author="Demo Author",
            email="demo@example.com",
            owner="demolabs",
        )
        target = _target(tmp_path, **{"bun.lock": "clean content\n"})
        report = ApplyReport()
        failed = execute_regenerations(
            target,
            [_plan("bun.lock", "-c", "pass")],
            {},
            report,
            source=bun_source,
            dest=DEST,
            rules=DEFAULT_RULES,
        )
        assert failed == ["bun.lock"]
        assert any("bun.lock" in s and "path" in s for s in report.skipped)

    def test_clean_rewrite_passes_and_is_recorded(self, tmp_path: Path):
        target = _target(tmp_path, **{"bun.lock": "stale demo_widget\n"})
        failed, report = _run(
            target,
            [_plan("bun.lock", *_write_cmd("bun.lock", "potato_launcher lock\n"))],
        )
        assert failed == []
        assert report.regenerated == ["bun.lock"]


class TestPostconditionShape:
    def test_deleted_output_fails(self, tmp_path: Path):
        target = _target(tmp_path, **{"bun.lock": "lockdata\n"})
        plan = _plan(
            "bun.lock", "-c", "import pathlib; pathlib.Path('bun.lock').unlink()"
        )
        failed, report = _run(target, [plan])
        assert failed == ["bun.lock"]
        assert report.regenerated == []

    @requires_symlink
    def test_output_replaced_by_symlink_fails_not_followed(self, tmp_path: Path):
        target = _target(
            tmp_path, **{"bun.lock": "lockdata\n", "clean.txt": "all clean\n"}
        )
        plan = _plan(
            "bun.lock",
            "-c",
            "import pathlib; p = pathlib.Path('bun.lock'); p.unlink(); "
            "p.symlink_to('clean.txt')",
        )
        failed, _ = _run(target, [plan])
        assert failed == ["bun.lock"]

    def test_non_utf8_output_fails_closed(self, tmp_path: Path):
        target = _target(tmp_path, **{"bun.lock": "lockdata\n"})
        plan = _plan(
            "bun.lock",
            "-c",
            "import pathlib; "
            "pathlib.Path('bun.lock').write_bytes(b'\\xff\\xfe binary')",
        )
        failed, report = _run(target, [plan])
        assert failed == ["bun.lock"]
        assert any("UTF-8" in s for s in report.skipped)

    def test_plan_time_pre_state_must_decode(self, src_target: Path):
        """The other end of the two-point gate: an undecodable tracked
        pre-state refuses at plan time (outputs are tracked and clean, so
        there is a pre-state to check)."""
        (src_target / "bun.lock").write_bytes(b"\xff\xfe binary lock")
        (src_target / "press").mkdir(exist_ok=True)
        (src_target / "press" / "press-rules.toml").write_text(
            '[[regenerate]]\nfile = "bun.lock"\ncommand = ["true"]\n',
            encoding="utf-8",
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "commit", "-q", "-m", "binary lock"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        problems = preflight_regenerate_outputs(src_target, load_rules(src_target))
        assert any("UTF-8" in p for p in problems)


class TestFinalPass:
    def test_later_command_corrupting_earlier_output_caught(self, tmp_path: Path):
        """Per-command scans pass for each command's OWN output; only the
        final pass sees a later command reintroducing identity into an
        earlier one."""
        target = _target(
            tmp_path, **{"a.lock": "stale demo_widget\n", "b.lock": "stale\n"}
        )
        plans = [
            _plan("a.lock", *_write_cmd("a.lock", "clean a\n")),
            _plan(
                "b.lock",
                "-c",
                "import pathlib; "
                "pathlib.Path('b.lock').write_text('clean b'); "
                "pathlib.Path('a.lock').write_text('demo_widget is back')",
            ),
        ]
        failed, _ = _run(target, plans)
        assert failed == []  # each command's own postcondition passed
        problems = final_validation_pass(
            target,
            plans,
            resets=[],
            renames={},
            source=SOURCE,
            dest=DEST,
            rules=DEFAULT_RULES,
        )
        assert any("a.lock" in p and "demo_widget" in p for p in problems)

    def test_later_command_modifying_reset_stub_caught(self, tmp_path: Path):
        target = _target(
            tmp_path,
            **{"bun.lock": "stale\n", "CHANGELOG.md": "# Changelog\n"},
        )
        plans = [
            _plan(
                "bun.lock",
                "-c",
                "import pathlib; "
                "pathlib.Path('bun.lock').write_text('clean'); "
                "pathlib.Path('CHANGELOG.md').write_text('demo_widget history')",
            ),
        ]
        failed, _ = _run(target, plans)
        assert failed == []
        problems = final_validation_pass(
            target,
            plans,
            resets=[
                (ResetRule(file="CHANGELOG.md", stub="# Changelog\n"), "# Changelog\n")
            ],
            renames={},
            source=SOURCE,
            dest=DEST,
            rules=DEFAULT_RULES,
        )
        assert any("CHANGELOG.md" in p for p in problems)

    @requires_symlink
    def test_stub_replaced_by_symlink_caught_before_content_compare(
        self, tmp_path: Path
    ):
        """Stub equality alone would follow a symlink a later command
        planted and accept matching OUTSIDE content — the full guard set
        runs before the compare."""
        target = _target(tmp_path, **{"bun.lock": "clean\n"})
        outside = tmp_path / "outside-stub.md"
        outside.write_text("# Changelog\n", encoding="utf-8")  # content MATCHES
        os.symlink(outside, target / "CHANGELOG.md")
        problems = final_validation_pass(
            target,
            [_plan("bun.lock", "-c", "pass")],
            resets=[
                (ResetRule(file="CHANGELOG.md", stub="# Changelog\n"), "# Changelog\n")
            ],
            renames={},
            source=SOURCE,
            dest=DEST,
            rules=DEFAULT_RULES,
        )
        assert any("CHANGELOG.md" in p for p in problems)

    def test_reset_stub_validated_at_translated_path(self, tmp_path: Path):
        """Reset paths are consumed in SOURCE coordinates before the rename
        pass, but this check runs AFTER it — validating the declared source
        path would report a validly moved stub as missing."""
        target = _target(
            tmp_path,
            **{
                "bun.lock": "clean\n",
                "pkg_potato__HISTORY.md": "# History\n",
            },
        )
        problems = final_validation_pass(
            target,
            [_plan("bun.lock", "-c", "pass")],
            resets=[
                (
                    ResetRule(file="pkg_press/HISTORY.md", stub="# History\n"),
                    "# History\n",
                )
            ],
            renames={"pkg_press": "pkg_potato"},
            source=SOURCE,
            dest=DEST,
            rules=DEFAULT_RULES,
        )
        assert problems == []


class TestControlFileGuard:
    def test_command_modifying_control_file_aborts(self, tmp_path: Path):
        target = _target(
            tmp_path,
            **{
                "bun.lock": "stale\n",
                "press__press-source.toml": '[identity]\napp_name = "press"\n',
            },
        )
        snapshot = snapshot_control_files(target)
        plans = [
            _plan(
                "bun.lock",
                "-c",
                "import pathlib; "
                "pathlib.Path('bun.lock').write_text('clean'); "
                "pathlib.Path('press/press-source.toml').write_text('tampered')",
            ),
        ]
        failed, _ = _run(target, plans)
        assert failed == []
        problems = validate_control_files(target, snapshot)
        assert any("press-source.toml" in p for p in problems)

    def test_command_creating_control_file_aborts(self, tmp_path: Path):
        target = _target(tmp_path, **{"bun.lock": "stale\n"})
        snapshot = snapshot_control_files(target)
        (target / "press").mkdir()
        (target / "press" / "press-receipt.toml").write_text(
            "[press]\nverified = true\n", encoding="utf-8"
        )
        problems = validate_control_files(target, snapshot)
        assert any("press-receipt.toml" in p for p in problems)

    def test_untouched_control_files_pass(self, tmp_path: Path):
        target = _target(
            tmp_path,
            **{"press__press-source.toml": '[identity]\napp_name = "press"\n'},
        )
        snapshot = snapshot_control_files(target)
        assert validate_control_files(target, snapshot) == []


class TestReceiptResolvedArgv:
    def test_receipt_records_each_regenerations_resolved_argv(self, tmp_path: Path):
        target = tmp_path / "target"
        (target / "press").mkdir(parents=True)
        report = ApplyReport()
        report.regenerated.append("bun.lock")
        write_receipt(
            target,
            SOURCE,
            DEST,
            report,
            regenerations=[("bun.lock", ("/opt/tools/bin/bun", "install"))],
        )
        receipt = (target / RECEIPT_REL).read_text(encoding="utf-8")
        assert "bun.lock" in receipt
        assert "/opt/tools/bin/bun" in receipt  # the RESOLVED argv, pinned path


def _rules_target(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "rules-holder" / "press"
    d.mkdir(parents=True, exist_ok=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path / "rules-holder"
