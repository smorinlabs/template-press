"""keep_names across every scan and report, plus the undeclared-name preflight."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand import verifier as verifier_module
from template_press.rebrand.cli import main
from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.engine import build_plan
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    token_pattern,
)
from template_press.rebrand.keep_names import (
    RewrittenForms,
    check_keep_surfaces,
    find_outside_kept,
    kept_spans,
    sibling_guidance,
    validate_keep_names,
)
from template_press.rebrand.pipeline import (
    MatcherSpec,
    PipelineCandidate,
    validate_pipeline,
)
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.regen import scan_regenerated_output
from template_press.rebrand.reset import scan_reset_path, scan_stub_text
from template_press.rebrand.rules import load_rules
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verifier import scan
from template_press.rebrand.verify_cli import verify_command

from .conftest import requires_symlink
from .test_keep_names import (
    DEST,
    KEPT,
    LANGUAGES,
    SOURCE,
    _answers,
    _git,
    _keep_rules,
    _make_target,
    _toml_identity,
)

SCAN_FIELDS = ("app_name", "package_name", "repo_name", "owner", "npm_name", "cli_name")


def _press(target: Path, answers: Path, *extra: str) -> int:
    return main(["--target", str(target), "--config", str(answers), *extra])


def _verify(target: Path, *extra: str) -> int:
    return verify_command(["--target", str(target), *extra])


def _status(target: Path) -> str:
    return _git(target, "status", "--porcelain")


def _assert_refused_clean(target: Path, code: int) -> None:
    assert code == 1
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


def _table(target: Path, source: Identity = SOURCE, dest: Identity = DEST):
    return build_plan(target, source, dest, load_rules(target)).table


# Undeclared-name preflight


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("uses @acme/widget-extra here", "@acme/widget-extra"),
        ("run acme-cli-helper now", "acme-cli-helper"),
        ("run pre-acme-cli now", "pre-acme-cli"),
        ("see x-@acme/widget here", "x-@acme/widget"),
        ("end @acme/widget-extra.", "@acme/widget-extra"),
    ],
)
def test_undeclared_sibling_exit_1_no_receipt(tmp_path, capsys, text, token):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": text})
    code = _press(target, _answers(tmp_path))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    assert token in err
    assert f"keep_names = {json.dumps([token])}" in err


def test_undeclared_sibling_error_suggests_keep_names(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": f"{KEPT}\n"})
    assert _press(target, _answers(tmp_path), "--dry-run") == 1
    assert 'keep_names = ["@acme/widget-extra"]' in capsys.readouterr().err
    assert _status(target) == ""


def test_verify_runs_the_same_preflight(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": "pre-acme-cli\n"})
    assert _verify(target) == 1
    assert 'keep_names = ["pre-acme-cli"]' in capsys.readouterr().err
    assert _status(target) == ""


def test_verify_json_reports_refusal_as_one_object(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": "pre-acme-cli\n"})
    assert _verify(target, "--json") == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["verified"] is False
    assert report["undeclared_names"] == [
        {
            "path": "docs/a.md",
            "where": "content",
            "field": "cli_name",
            "token": "pre-acme-cli",
        }
    ]
    assert "pre-acme-cli" in captured.err


@pytest.mark.parametrize("owner", ["acme", "zetalabs"])
def test_cli_sibling_is_refused_for_either_owner(tmp_path, capsys, owner):
    source = replace(SOURCE, owner=owner)
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": "run pre-acme-cli now\n"})
    (target / "press" / "press-source.toml").write_text(
        _toml_identity(source, "identity"), encoding="utf-8"
    )
    _git(target, "remote", "set-url", "origin", f"https://github.com/{owner}/acme-repo")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "--allow-empty", "-m", "owner")
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "pre-acme-cli" in capsys.readouterr().err


def test_scoped_sibling_with_owner_row_is_refused(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": "@acme/widget-api-extra"})
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "@acme/widget-api-extra" in capsys.readouterr().err


def test_sibling_in_a_scoped_path_is_refused(tmp_path, capsys):
    target = _make_target(
        tmp_path, LANGUAGES, {"packages/@acme/widget-api/index.js": "x\n"}
    )
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert 'keep_names = ["@acme/widget-api"]' in capsys.readouterr().err


@requires_symlink
def test_sibling_in_a_symlink_target_is_refused(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES)
    os.symlink("acme-cli-helper/run", target / "link")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "link")
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "acme-cli-helper" in capsys.readouterr().err


def test_printed_token_round_trips_through_keep_names(tmp_path, capsys):
    text = "pre-acme-cli and x-@acme/widget and @acme/widget-extra\n"
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": text})
    assert _press(target, _answers(tmp_path), "--dry-run") == 1
    capsys.readouterr()
    tokens = ["pre-acme-cli", "x-@acme/widget", "@acme/widget-extra"]
    (target / "press" / "press-rules.toml").write_text(
        _keep_rules(tokens), encoding="utf-8"
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "keep")
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == text


def test_excluded_and_control_files_are_outside_the_preflight(tmp_path):
    rules = f'{LANGUAGES}extra_exclude_dirs = ["vendor"]\nverify_ignore = ["vendor"]\n'
    target = _make_target(tmp_path, rules, {"vendor/a.md": "pre-acme-cli\n"})
    assert _press(target, _answers(tmp_path), "--dry-run") == 0


def test_longer_declared_identity_value_is_not_a_sibling():
    source = replace(SOURCE, repo_name="acme-cli-core")
    check = check_keep_surfaces(
        [("README.md", "content", "see acme-cli-core and acme-cli\n")],
        source,
        (),
        rewritten=lambda *_: RewrittenForms(frozenset({"acme-cli-core"})),
    )
    assert check.undeclared == ()


def test_value_inside_another_identity_occurrence_is_not_a_sibling():
    source = replace(SOURCE, npm_name="@acme/widget-api", cli_name="widget")
    check = check_keep_surfaces(
        [("README.md", "content", "install @acme/widget-api\n")],
        source,
        (),
        rewritten=lambda *_: RewrittenForms(frozenset({"@acme/widget-api"})),
    )
    assert check.undeclared == ()


def test_sibling_of_a_longer_identity_value_is_still_refused():
    source = replace(SOURCE, repo_name="acme-cli-core")
    check = check_keep_surfaces(
        [("README.md", "content", "see acme-cli-core-extra\n")], source, ()
    )
    assert [item.token for item in check.undeclared] == ["acme-cli-core-extra"]


def test_case_variant_sibling_is_refused():
    check = check_keep_surfaces(
        [("README.md", "content", "ACME-CLI-HELPER\n")], SOURCE, ()
    )
    assert [item.token for item in check.undeclared] == ["ACME-CLI-HELPER"]


def test_partial_keep_does_not_cover_a_longer_token():
    check = check_keep_surfaces(
        [("a.md", "content", "x-@acme/widget-extra\n")], SOURCE, [KEPT]
    )
    assert [item.token for item in check.undeclared] == ["x-@acme/widget-extra"]


def test_identity_without_npm_or_cli_has_no_preflight_findings():
    source = replace(SOURCE, npm_name=None, cli_name=None)
    check = check_keep_surfaces(
        [("a.md", "content", "pre-acme-cli @acme/widget-extra\n")], source, ()
    )
    assert check.undeclared == ()


# Normalized refusal


@pytest.mark.parametrize("entry", ["ACME-REPO", "acme_repo", "AcmeRepo", "acme.repo"])
def test_normalized_source_value_is_refused(entry):
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST)


@pytest.mark.parametrize(
    "entry", ["ACME_CORE", "acme-core", "acmewidget", "ACME WIDGET"]
)
def test_normalized_package_and_display_forms_are_refused(entry):
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST)


@pytest.mark.parametrize("entry", ["OTHER-REPO", "other_repo", "OtherThing"])
def test_normalized_destination_value_is_refused(entry):
    with pytest.raises(ValidationError, match="destination identity"):
        validate_keep_names([entry], SOURCE, DEST)


def test_synthetic_destination_skips_normalized_destination_check():
    validate_keep_names(["OTHER-REPO"], SOURCE, DEST, synthetic_dest=True)


@pytest.mark.parametrize(
    "entry", ["a\x85b", f"a{chr(0x2028)}b", f"a{chr(0x2029)}b", "a\x9fb"]
)
def test_line_breaking_unicode_is_refused(entry):
    with pytest.raises(ValidationError, match="control"):
        validate_keep_names([entry], SOURCE, DEST)


def test_true_sibling_survives_beside_rewritten_repo_name(tmp_path):
    text = "acme-repo and acme-repo-extra\n"
    target = _make_target(
        tmp_path, _keep_rules(["acme-repo-extra"]), {"docs/a.md": text}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == (
        "other-repo and acme-repo-extra\n"
    )


# Overlapping spans


def test_kept_spans_finds_overlapping_occurrences():
    assert kept_spans("a.a.a", ["a.a"]) == ((0, 3), (2, 5))


def test_overlapping_match_stays_a_leak():
    text = "x.acme.cli"
    kept = kept_spans(text, ["x.acme"])
    assert find_outside_kept(
        text, "cli_name", "acme-cli", substring=False, kept=kept
    ) == [(2, 10)]


def test_match_hidden_behind_a_kept_match_is_found():
    text = "a.a.a"
    kept = ((0, 3),)
    assert find_outside_kept(text, "owner", "a.a", substring=True, kept=kept) == [
        (2, 5)
    ]


# End-to-end survival


def test_declared_sibling_survives_press_and_verify(tmp_path):
    target = _make_target(
        tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT} @acme/widget\n"}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == f"{KEPT} @new/x\n"


def test_declared_sibling_in_package_json_survives(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]))
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["dependencies"] = {KEPT: "1.0.0"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "dep")
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pressed["name"] == DEST.npm_name
    assert KEPT in pressed["dependencies"]


def test_near_miss_still_fails(tmp_path, capsys):
    target = _make_target(
        tmp_path, _keep_rules([KEPT]), {"docs/a.md": "@acme/widget-extra-2\n"}
    )
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "@acme/widget-extra-2" in capsys.readouterr().err
    assert _verify(target) == 1


@requires_symlink
def test_kept_name_in_filename_and_symlink_survives(tmp_path):
    target = _make_target(
        tmp_path,
        _keep_rules(["acme-repo-extra"]),
        {"acme-repo-extra/a.txt": "x\n", "tools/acme-repo-extra.sh": "y\n"},
    )
    os.symlink("acme-repo-extra/a.txt", target / "live-link")
    os.symlink("missing/acme-repo-extra", target / "dangling-link")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "paths")
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "acme-repo-extra" / "a.txt").is_file()
    assert (target / "tools" / "acme-repo-extra.sh").is_file()
    assert os.readlink(target / "live-link") == "acme-repo-extra/a.txt"
    assert os.readlink(target / "dangling-link") == "missing/acme-repo-extra"


def test_scoped_kept_name_across_path_components_survives(tmp_path):
    target = _make_target(
        tmp_path,
        _keep_rules(["@tools/acme-repo"]),
        {"packages/@tools/acme-repo/x.js": "x\n", "other/acme-repo/y.js": "y\n"},
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "packages" / "@tools" / "acme-repo" / "x.js").is_file()
    assert (target / "other" / "other-repo" / "y.js").is_file()


def test_rename_plan_leaves_kept_component_alone(tmp_path):
    target = _make_target(
        tmp_path,
        _keep_rules(["acme-repo-extra"]),
        {"acme-repo-extra/a.txt": "x\n", "acme-repo/b.txt": "y\n"},
    )
    plan = build_plan(target, SOURCE, DEST, load_rules(target))
    assert plan.renames["acme-repo"] == "other-repo"
    assert "acme-repo-extra" not in plan.renames


def test_pipeline_does_not_refuse_a_kept_path_collision(tmp_path):
    target = _make_target(
        tmp_path,
        _keep_rules(["acme-repo-extra"]),
        {"acme-repo-extra/a.txt": "x\n", "other-repo-extra/a.txt": "y\n"},
    )
    assert _press(target, _answers(tmp_path), "--dry-run") == 0
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "acme-repo-extra" / "a.txt").read_text(encoding="utf-8") == "x\n"
    assert (target / "other-repo-extra" / "a.txt").read_text(encoding="utf-8") == "y\n"


def test_pipeline_still_refuses_an_unkept_path_collision():
    row = PipelineCandidate(
        row_id="identity:repo_name",
        from_value="acme-repo",
        to_value="other-repo",
        rewrite_surfaces=frozenset({"path"}),
        matcher=MatcherSpec("conservative", "repo_name", False),
    )
    paths = ("acme-repo-extra/a", "other-repo-extra/a")
    validate_pipeline((row,), initial_paths=paths, keep_names=("acme-repo-extra",))
    with pytest.raises(ValidationError, match="converging"):
        validate_pipeline((row,), initial_paths=paths)


def test_repeat_press_keeps_list_valid(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    assert _press(target, _answers(tmp_path)) == 0
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    assert _verify(target) == 0
    third = replace(
        DEST,
        package_name="third_core",
        repo_name="third-repo",
        app_name="thirdapp",
        owner="third-owner",
        display_name="Third Thing",
        npm_name="@third/y",
        cli_name="third-cli",
    )
    answers = tmp_path / "third.toml"
    answers.write_text(_toml_identity(third, "answers"), encoding="utf-8")
    assert _press(target, answers, "--force") == 0
    assert KEPT in (target / "docs" / "a.md").read_text(encoding="utf-8")
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{third.owner}/{third.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed again")
    assert _verify(target) == 0


def test_dry_run_and_receipt_list_kept_names(tmp_path, capsys):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    assert _press(target, _answers(tmp_path), "--dry-run") == 0
    assert KEPT in capsys.readouterr().out
    assert _press(target, _answers(tmp_path)) == 0
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["keep_names"] == [KEPT]


def test_receipt_omits_keep_names_when_empty(tmp_path):
    target = _make_target(tmp_path, LANGUAGES)
    assert _press(target, _answers(tmp_path)) == 0
    assert "keep_names" not in (target / RECEIPT_REL).read_text(encoding="utf-8")


def test_stale_keep_name_warns_on_stderr_only(tmp_path, capsys):
    target = _make_target(tmp_path, _keep_rules(["@zeta/not-here"]))
    code = _verify(target, "--json")
    captured = capsys.readouterr()
    assert code == 0
    assert "keep_names" in captured.err
    assert "@zeta/not-here" in captured.err
    assert json.loads(captured.out)["verified"] is True


def test_stale_keep_name_warns_on_press(tmp_path, capsys):
    target = _make_target(tmp_path, _keep_rules(["@zeta/not-here"]))
    assert _press(target, _answers(tmp_path), "--dry-run") == 0
    captured = capsys.readouterr()
    assert "@zeta/not-here" in captured.err
    assert "stale" in captured.err


def test_path_only_keep_name_is_not_stale():
    check = check_keep_surfaces(
        [(f"packages/{KEPT}/a.js", "path", f"packages/{KEPT}/a.js")],
        SOURCE,
        [KEPT],
    )
    assert check.stale == ()


def test_sibling_guidance_names_the_longer_token():
    text = "see @acme/widget-extra."
    guidance = sibling_guidance(text, (4, 16))
    assert guidance is not None
    assert 'keep_names = ["@acme/widget-extra"]' in guidance
    assert sibling_guidance("see @acme/widget.", (4, 16)) is None


# Every scan subtracts kept spans


@pytest.mark.parametrize(
    "value", ["@acme/widget-extra", "pre-acme-cli", "acme-cli-helper"]
)
def test_doctor_ignores_kept_content(tmp_path, value):
    target = _make_target(tmp_path, _keep_rules([value]), {"docs/a.md": f"{value}\n"})
    table = _table(target)
    target.joinpath("README.md").write_text("# Other Thing\n", encoding="utf-8")
    target.joinpath("package.json").write_text("{}", encoding="utf-8")
    target.joinpath("pyproject.toml").write_text("", encoding="utf-8")
    leaks = find_leaks(target, SOURCE, load_rules(target), dest=DEST, table=table)
    assert [leak for leak in leaks if leak.path == "docs/a.md"] == []


def test_doctor_reports_text_outside_the_kept_span(tmp_path):
    target = _make_target(
        tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT} @acme/widget\n"}
    )
    table = _table(target)
    leaks = find_leaks(target, SOURCE, load_rules(target), dest=DEST, table=table)
    assert any(leak.path == "docs/a.md" for leak in leaks)


def test_doctor_legacy_path_honors_rules_keep_names(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    leaks = find_leaks(target, SOURCE, load_rules(target), dest=DEST)
    assert [leak for leak in leaks if leak.path == "docs/a.md"] == []


@pytest.mark.parametrize(
    ("keep", "text", "field"),
    [
        (KEPT, f"lock {KEPT}\n", "npm_name"),
        ("pre-acme-cli", "lock pre-acme-cli\n", "cli_name"),
    ],
)
def test_declared_sibling_survives_regeneration_scan(tmp_path, keep, text, field):
    target = _make_target(tmp_path, _keep_rules([keep]), {"docs/a.md": text})
    rules = load_rules(target)
    table = _table(target)
    assert (
        scan_regenerated_output(
            text,
            "bun.lock",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            renames={},
            table=table,
        )
        == []
    )
    leaked = f"{text}{getattr(SOURCE, field)}\n"
    problems = scan_regenerated_output(
        leaked,
        "bun.lock",
        source=SOURCE,
        dest=DEST,
        rules=rules,
        renames={},
        table=table,
    )
    assert any(field in problem for problem in problems)
    assert any("(1 occurrence(s))" in p for p in problems if field in p)


def test_regeneration_scan_boundary_mode_honors_kept(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    assert (
        scan_regenerated_output(
            f"{KEPT}\n",
            "bun.lock",
            source=SOURCE,
            dest=DEST,
            rules=load_rules(target),
            renames={},
            table=_table(target),
            scan_mode="boundary",
        )
        == []
    )


def test_regeneration_scan_legacy_path_honors_kept(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    assert (
        scan_regenerated_output(
            f"{KEPT}\n",
            f"packages/{KEPT}/bun.lock",
            source=SOURCE,
            dest=DEST,
            rules=load_rules(target),
            renames={},
        )
        == []
    )


@pytest.mark.parametrize("with_table", [True, False])
def test_reset_scans_honor_kept(tmp_path, with_table):
    target = _make_target(tmp_path, _keep_rules([KEPT]), {"docs/a.md": f"{KEPT}\n"})
    rules = load_rules(target)
    table = _table(target) if with_table else None
    assert (
        scan_stub_text(
            f"{KEPT}\n",
            rel="CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            table=table,
        )
        == []
    )
    assert (
        scan_reset_path(
            f"packages/{KEPT}/CHANGELOG.md",
            f"packages/{KEPT}/CHANGELOG.md",
            source=SOURCE,
            dest=DEST,
            rules=rules,
            table=table,
        )
        == []
    )
    problems = scan_stub_text(
        f"{KEPT} @acme/widget\n",
        rel="CHANGELOG.md",
        source=SOURCE,
        dest=DEST,
        rules=rules,
        table=table,
    )
    assert any("npm_name" in problem for problem in problems)


def _verifier_findings(target: Path):
    return scan(
        target,
        SOURCE,
        synthesize_dest(SOURCE),
        fields=SCAN_FIELDS,
        substring_fields=frozenset(),
        rules=load_rules(target),
    )


def test_verifier_subtracts_kept_content_and_paths(tmp_path):
    target = _make_target(
        tmp_path, _keep_rules([KEPT]), {f"packages/{KEPT}/a.md": f"{KEPT}\n"}
    )
    findings = _verifier_findings(target)
    assert [f for f in findings if f.path.startswith("packages/")] == []


def test_verifier_keeps_overlapping_match(tmp_path):
    target = _make_target(
        tmp_path, _keep_rules(["x.acme"]), {"docs/a.md": "x.acme.cli\n"}
    )
    findings = [f for f in _verifier_findings(target) if f.path == "docs/a.md"]
    assert any(f.field == "cli_name" for f in findings)


def test_verifier_subtracts_kept_from_binary(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]))
    (target / "blob.bin").write_bytes(b"\xff" + KEPT.encode() + b"\x00")
    (target / "leak.bin").write_bytes(b"\xff@acme/widget\x00")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "binary")
    findings = _verifier_findings(target)
    assert [f for f in findings if f.path == "blob.bin"] == []
    assert any(f.path == "leak.bin" for f in findings)


@requires_symlink
def test_verifier_subtracts_kept_symlink_text(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]))
    os.symlink(f"packages/{KEPT}/a", target / "link")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "link")
    findings = [f for f in _verifier_findings(target) if f.path == "link"]
    assert findings == []


def test_kept_replace_rule_literal_survives_press_and_verify(tmp_path):
    rules = _keep_rules(
        ["acme-repo.extra"],
        '\n[[replace]]\npattern = "{repo_name}.extra"\nreason = "doc"\n',
    )
    target = _make_target(tmp_path, rules, {"docs/a.md": "acme-repo.extra\n"})
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == "acme-repo.extra\n"


def test_prefix_warning_ignores_kept_names(tmp_path, capsys):
    target = _make_target(
        tmp_path, _keep_rules(["acme-repo-extra"]), {"docs/a.md": "acme-repo-extra\n"}
    )
    (target / "README.md").write_text("# Acme Widget\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "--allow-empty", "-m", "readme")
    assert _press(target, _answers(tmp_path), "--dry-run") == 0
    assert "occurs only as a prefix" not in capsys.readouterr().out


def test_verifier_derives_kept_spans_from_rules():
    source = Path(verifier_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "keep_names" in imports
    assert not {"substitutions", "engine", "doctor"} & imports
    assert "rules.keep_names" in source
    scan_def = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "scan"
    )
    params = {arg.arg for arg in scan_def.args.kwonlyargs}
    assert "keep_names" not in params


# Proposal gap


def _bin_target(tmp_path: Path, bins: dict[str, str]) -> Path:
    target = _make_target(tmp_path, LANGUAGES)
    (target / "press" / "press-source.toml").unlink()
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["name"] = SOURCE.npm_name
    manifest["bin"] = bins
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bins")
    return target


def test_distinct_bin_is_proposed_as_cli_name(tmp_path, capsys):
    target = _bin_target(tmp_path, {"web-cli": "./bin/web.js"})
    assert main(["--target", str(target)]) == 2
    assert 'cli_name = "web-cli"' in capsys.readouterr().out


def test_bin_equal_to_app_name_is_not_proposed(tmp_path, capsys):
    target = _bin_target(tmp_path, {SOURCE.app_name: "./bin/app.js"})
    assert main(["--target", str(target)]) == 2
    assert "cli_name" not in capsys.readouterr().out


def test_proposed_cli_name_cannot_leave_bin_unchanged(tmp_path, capsys):
    target = _bin_target(tmp_path, {"web-cli": "./bin/web.js"})
    answers = _answers(tmp_path, replace(DEST, cli_name="new-web"))
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0
    capsys.readouterr()
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert "new-web" in pressed["bin"]
    assert "web-cli" not in pressed["bin"]


def test_string_bin_is_not_proposed_and_verify_passes_after_press(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES)
    (target / "press" / "press-source.toml").unlink()
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["bin"] = "./cli.js"
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "string bin")
    answers = _answers(tmp_path, replace(DEST, cli_name=None, display_name=None))
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0, capsys.readouterr().err
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    assert _verify(target) == 0


def test_receipt_key_is_accepted_with_directory_removal(tmp_path):
    rules = _keep_rules(
        [KEPT],
        '\n[[remove]]\ndir = "history"\nreason = "template history"\n',
    )
    target = _make_target(
        tmp_path, rules, {"docs/a.md": f"{KEPT}\n", "history/old.md": "old\n"}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    receipt = tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["keep_names"] == [KEPT]
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    assert _verify(target) == 0
    third = replace(
        DEST,
        package_name="third_core",
        repo_name="third-repo",
        app_name="thirdapp",
        owner="third-owner",
        display_name="Third Thing",
        npm_name="@third/y",
        cli_name="third-cli",
    )
    answers = tmp_path / "third.toml"
    answers.write_text(_toml_identity(third, "answers"), encoding="utf-8")
    assert _press(target, answers, "--force") == 0


def test_kept_name_in_excluded_verify_ignored_lockfile_is_accepted(tmp_path):
    rules = _keep_rules(
        [KEPT],
        'extra_exclude_files = ["vendor.lock"]\nverify_ignore = ["vendor.lock"]\n',
    )
    target = _make_target(tmp_path, rules, {"vendor.lock": f"{KEPT}\n"})
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "vendor.lock").read_text(encoding="utf-8") == f"{KEPT}\n"


# Review regressions: exemptions, join rule, removals, several bins


def _with_source(
    tmp_path: Path, source: Identity, rules: str, files: dict[str, str]
) -> Path:
    target = _make_target(tmp_path, rules, files)
    (target / "press" / "press-source.toml").write_text(
        _toml_identity(source, "identity"), encoding="utf-8"
    )
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{source.owner}/{source.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "--allow-empty", "-m", "source")
    return target


def test_owner_form_has_no_path_row_so_path_is_refused(tmp_path, capsys):
    source = replace(SOURCE, owner="acme-cli-labs")
    target = _with_source(
        tmp_path, source, LANGUAGES, {"tools/acme-cli-labs/run.sh": "x\n"}
    )
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "acme-cli-labs" in capsys.readouterr().err


def test_disabled_display_form_is_refused(tmp_path, capsys):
    source = replace(SOURCE, display_name="acme-cli Tool")
    rules = f'{LANGUAGES}display_forms = ["spaced"]\n'
    target = _with_source(
        tmp_path,
        source,
        rules,
        {"README.md": "# acme-cli Tool\n", "docs/a.md": "see acme-cliTool here\n"},
    )
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "acme-cliTool" in capsys.readouterr().err


def test_unchanged_field_form_is_refused(tmp_path, capsys):
    source = replace(SOURCE, repo_name="pre-acme-cli", owner="zetalabs")
    dest = replace(DEST, repo_name="pre-acme-cli")
    target = _with_source(
        tmp_path, source, LANGUAGES, {"docs/a.md": "run pre-acme-cli now\n"}
    )
    code = _press(target, _answers(tmp_path, dest))
    _assert_refused_clean(target, code)
    err = capsys.readouterr().err
    assert "pre-acme-cli" in err
    assert "cannot be kept" in err
    assert 'keep_names = ["pre-acme-cli"]' not in err


def test_changed_longer_identity_value_still_presses(tmp_path):
    source = replace(SOURCE, repo_name="acme-cli-core")
    target = _with_source(
        tmp_path, source, LANGUAGES, {"acme-cli-core/a.md": "acme-cli-core\n"}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "other-repo" / "a.md").read_text(encoding="utf-8") == (
        "other-repo\n"
    )


@pytest.mark.parametrize(
    ("cli_name", "rel", "text"),
    [
        ("tsc", "tsconfig.json", "{}\n"),
        ("serve", "docs/a.md", "the server observes reserved ports\n"),
        ("acme-cli", "bin/acme-cli.js", "// acme-cli.js\n"),
    ],
)
def test_glued_and_dotted_names_are_not_siblings(tmp_path, cli_name, rel, text):
    source = replace(SOURCE, cli_name=cli_name)
    target = _with_source(tmp_path, source, LANGUAGES, {rel: text})
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["bin"] = {cli_name: "./bin/run.js"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bin")
    assert _press(target, _answers(tmp_path), "--dry-run") == 0


def test_bare_separator_touching_a_single_token_value_is_a_sibling():
    source = replace(SOURCE, cli_name="tsc")
    check = check_keep_surfaces(
        [("a.md", "content", "pass --tsc or tsc-\n")], source, ()
    )
    assert [item.token for item in check.undeclared] == ["--tsc", "tsc-"]


def test_bare_separator_touching_a_multi_part_value_is_a_sibling():
    check = check_keep_surfaces(
        [("a.md", "content", "pass --acme-cli or acme-cli-\n")], SOURCE, ()
    )
    assert [item.token for item in check.undeclared] == ["--acme-cli", "acme-cli-"]


@pytest.mark.parametrize(
    ("files", "token"),
    [
        ({"docs/a.md": "see x-@acme/widget-api here\n"}, "x-@acme/widget-api"),
        ({"packages/@acme/widget-api-extra/a.js": "x\n"}, "@acme/widget-api-extra"),
    ],
)
def test_exact_controller_cases_with_owner_zetalabs(tmp_path, capsys, files, token):
    source = replace(SOURCE, owner="zetalabs", npm_name="@acme/widget-api")
    target = _with_source(tmp_path, source, LANGUAGES, files)
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["name"] = "@acme/widget-api"
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "name")
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert f"keep_names = {json.dumps([token])}" in capsys.readouterr().err


@pytest.mark.parametrize(
    "rule",
    [
        '[[remove]]\nfile = "docs/old.md"\nreason = "history"\n',
        '[[remove]]\ndir = "docs"\nreason = "history"\n',
    ],
)
def test_planned_removal_is_outside_the_preflight(tmp_path, rule):
    target = _make_target(
        tmp_path, f"{LANGUAGES}\n{rule}", {"docs/old.md": "pre-acme-cli\n"}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert not (target / "docs" / "old.md").exists()


def _no_source_target(tmp_path: Path, rules: str, *, python: bool) -> Path:
    target = _make_target(tmp_path, rules)
    (target / "press" / "press-source.toml").unlink()
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest.update(
        author="Acme Author <author@example.test>",
        bin={"web-cli": "./a.js", "api-cli": "./b.js"},
    )
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    if not python:
        (target / "pyproject.toml").unlink()
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bins")
    return target


@pytest.mark.parametrize(
    ("rules", "python"), [("", False), (LANGUAGES, True)], ids=["node", "python+node"]
)
def test_several_distinct_bins_exit_2_before_writes(tmp_path, capsys, rules, python):
    target = _no_source_target(tmp_path, rules, python=python)
    answers = _answers(tmp_path)
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "web-cli" in err
    assert "api-cli" in err
    assert "keep_names" in err
    assert not (target / "press" / "press-source.toml").exists()
    assert _status(target) == ""


def _replace_rule(extra: str = "") -> str:
    return (
        f"{LANGUAGES}\n[[replace]]\n"
        'pattern = "{cli_name}-helper"\nreason = "companion tool"\n'
        f"{extra}"
    )


def test_applying_replace_rule_exempts_and_rewrites_token(tmp_path):
    target = _make_target(
        tmp_path, _replace_rule(), {"docs/a.md": "run acme-cli-helper now\n"}
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == (
        "run new-cli-helper now\n"
    )


def test_applying_path_rule_exempts_and_renames_token(tmp_path):
    target = _make_target(
        tmp_path,
        _replace_rule("paths = true\n"),
        {"tools/acme-cli-helper/a.sh": "x\n"},
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "tools" / "new-cli-helper" / "a.sh").is_file()


@pytest.mark.parametrize(
    ("extra", "files"),
    [
        ('files = ["docs/other.md"]\n', {"docs/a.md": "acme-cli-helper\n"}),
        ("content = false\npaths = true\n", {"docs/a.md": "acme-cli-helper\n"}),
        ("", {"tools/acme-cli-helper/a.sh": "x\n"}),
    ],
    ids=["other-file", "content-disabled", "paths-disabled"],
)
def test_non_applying_replace_rule_still_refuses(tmp_path, capsys, extra, files):
    target = _make_target(
        tmp_path, _replace_rule(extra), {"docs/other.md": "x\n", **files}
    )
    code = _press(target, _answers(tmp_path))
    _assert_refused_clean(target, code)
    assert "acme-cli-helper" in capsys.readouterr().err


def _cli_target(tmp_path: Path, cli_name: str, rules: str, text: str) -> Path:
    source = replace(SOURCE, cli_name=cli_name)
    target = _with_source(tmp_path, source, rules, {"docs/a.md": text})
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["bin"] = {cli_name: "./bin/run.js"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bin")
    return target


@pytest.mark.parametrize(
    ("cli_name", "token"), [("acme-cli", "acme-cliFoo"), ("tsc", "tscConfig")]
)
def test_camel_case_tail_is_a_sibling(tmp_path, capsys, cli_name, token):
    target = _cli_target(tmp_path, cli_name, LANGUAGES, f"see {token} here\n")
    code = _press(target, _answers(tmp_path))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    assert token in err
    assert f"keep_names = {json.dumps([token])}" in err
    assert _verify(target) == 1


@pytest.mark.parametrize(
    ("cli_name", "token"), [("acme-cli", "acme-cliFoo"), ("tsc", "tscConfig")]
)
def test_declared_camel_case_token_survives(tmp_path, cli_name, token):
    text = f"see {token} here\n"
    target = _cli_target(tmp_path, cli_name, _keep_rules([token]), text)
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "text",
    ["tsconfig.json\n", "TSConfig\n", "TSCONFIG\n", "preTsc\n"],
)
def test_non_transition_glue_is_not_a_sibling(text):
    source = replace(SOURCE, cli_name="tsc")
    check = check_keep_surfaces([("a.md", "content", text)], source, ())
    assert check.undeclared == ()


def test_server_is_still_not_a_sibling_of_serve():
    source = replace(SOURCE, cli_name="serve")
    check = check_keep_surfaces([("a.md", "content", "the server\n")], source, ())
    assert check.undeclared == ()


@pytest.mark.parametrize(
    ("cli_name", "text"),
    [
        ("serve", "a web-server here\n"),
        ("serve", "observe-mode\n"),
        ("tsc", "vite-tsconfig-paths\n"),
        ("tsc", "tsconfig\n"),
        ("serve", "server\n"),
        ("acme-cli", "bin/acme-cli.js\n"),
        ("tsc", "x-Atsc-y\n"),
        ("tsc", "x-tsc9-y\n"),
    ],
)
def test_match_inside_an_unrelated_word_is_not_a_sibling(cli_name, text):
    source = replace(SOURCE, cli_name=cli_name)
    check = check_keep_surfaces([("a.md", "content", text)], source, ())
    assert check.undeclared == ()


@pytest.mark.parametrize(
    ("cli_name", "text"),
    [
        ("serve", "a web-server here\n"),
        ("serve", "observe-mode\n"),
        ("tsc", "vite-tsconfig-paths\n"),
    ],
)
def test_unrelated_hyphenated_words_pass_press_and_verify(tmp_path, cli_name, text):
    target = _cli_target(tmp_path, cli_name, LANGUAGES, text)
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    ("npm_name", "cli_name", "text", "token"),
    [
        ("@acme/widget", "acme-cli", "acme-cli-helper", "acme-cli-helper"),
        ("@acme/widget", "acme-cli", "pre-acme-cli", "pre-acme-cli"),
        ("@acme/widget-api", "acme-cli", "x-@acme/widget-api", "x-@acme/widget-api"),
        ("@acme/widget", "acme-cli", "@acme/widget-extra", "@acme/widget-extra"),
        (
            "@acme/widget-api",
            "acme-cli",
            "packages/@acme/widget-api-extra/",
            "@acme/widget-api-extra",
        ),
        ("@acme/widget", "acme-cli", "acme-cliFoo", "acme-cliFoo"),
        ("@acme/widget", "tsc", "tscConfig", "tscConfig"),
    ],
)
def test_required_siblings_stay_refused(npm_name, cli_name, text, token):
    source = replace(SOURCE, npm_name=npm_name, cli_name=cli_name)
    check = check_keep_surfaces([("a.md", "content", f"{text}\n")], source, ())
    assert [item.token for item in check.undeclared] == [token]


def _pure_node_target(tmp_path: Path, name: str, bins: dict[str, str]) -> Path:
    target = _make_target(tmp_path, "", {"README.md": "run web-cli now\n"})
    (target / "press" / "press-source.toml").unlink()
    (target / "pyproject.toml").unlink()
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest.update(name=name, author="Acme Author <author@example.test>", bin=bins)
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "node")
    return target


@pytest.mark.parametrize(
    ("name", "bins"),
    [
        ("acme-repo", {"acme_repo": "./a.js", "web-cli": "./b.js"}),
        ("@acme/tool", {"tool": "./a.js", "web-cli": "./b.js"}),
    ],
    ids=["unscoped", "scoped"],
)
def test_pure_node_uncovered_bin_exits_2(tmp_path, capsys, name, bins):
    target = _pure_node_target(tmp_path, name, bins)
    answers = _answers(tmp_path, replace(DEST, display_name=None, cli_name=None))
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "web-cli" in err
    assert "keep_names" in err
    assert not (target / RECEIPT_REL).exists()
    assert not (target / "press" / "press-source.toml").exists()
    assert _status(target) == ""


def test_pure_node_single_covered_bin_still_proposes(tmp_path, capsys):
    target = _pure_node_target(tmp_path, "acme-repo", {"acme-repo": "./a.js"})
    assert main(["--target", str(target)]) == 2
    captured = capsys.readouterr()
    assert 'app_name = "acme_repo"' in captured.out.replace("  ", " ")


def test_python_node_second_bin_becomes_cli_name(tmp_path, capsys):
    target = _make_target(tmp_path, LANGUAGES, {"README.md": "run web-cli now\n"})
    (target / "press" / "press-source.toml").unlink()
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["bin"] = {SOURCE.package_name: "./a.js", "web-cli": "./b.js"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bins")
    answers = _answers(tmp_path, replace(DEST, display_name=None))
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0, capsys.readouterr().err
    pressed = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert "web-cli" not in pressed["bin"]
    assert (target / "README.md").read_text(encoding="utf-8") == "run new-cli now\n"


@pytest.mark.parametrize(
    ("npm_name", "text", "token"),
    [
        ("@acme/widget", "acme-cli2", "acme-cli2"),
        ("@acme/widget", "acme-clients", "acme-clients"),
        ("@acme/widget", "xacme-cli", "xacme-cli"),
        ("@acme/widget", "@acme/widget2", "@acme/widget2"),
    ],
)
def test_glued_text_on_a_multi_part_value_is_a_sibling(npm_name, text, token):
    source = replace(SOURCE, npm_name=npm_name)
    check = check_keep_surfaces([("a.md", "content", f"{text}\n")], source, ())
    assert [item.token for item in check.undeclared] == [token]


@pytest.mark.parametrize(
    "text", ["tsconfig", "web-server", "observe-mode", "vite-tsconfig-paths"]
)
def test_single_token_values_keep_the_both_sides_rule(text):
    for cli_name in ("tsc", "serve"):
        source = replace(SOURCE, cli_name=cli_name)
        check = check_keep_surfaces([("a.md", "content", f"{text}\n")], source, ())
        assert check.undeclared == ()


@pytest.mark.parametrize("token", ["tscConfig", "tsc-helper"])
def test_single_token_siblings_stay_refused(token):
    source = replace(SOURCE, cli_name="tsc")
    check = check_keep_surfaces([("a.md", "content", f"{token}\n")], source, ())
    assert [item.token for item in check.undeclared] == [token]


def test_glued_multi_part_name_full_press(tmp_path, capsys):
    text = "run acme-cli2 now\n"
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": text})
    code = _press(target, _answers(tmp_path))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    assert 'keep_names = ["acme-cli2"]' in err
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == text
    (target / "press" / "press-rules.toml").write_text(
        _keep_rules(["acme-cli2"]), encoding="utf-8"
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "keep")
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "entry", ["--acme-cli", "acme-cli-", "_acme-cli_", "@acme/widget-"]
)
def test_edge_separator_entry_may_be_declared(entry):
    validate_keep_names([entry], SOURCE, DEST)
    validate_keep_names([entry], SOURCE, DEST, synthetic_dest=True)


@pytest.mark.parametrize(
    "entry", ["acme-cli", "acme_cli", "Acme.CLI", "ACME-CLI", "AcmeCli"]
)
def test_real_identity_spellings_stay_refused(entry):
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST)


def test_exact_identity_value_with_edge_separator_stays_refused():
    source = replace(SOURCE, npm_name="-acme-tool")
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names(["-acme-tool"], source, DEST)


@pytest.mark.parametrize(
    ("text", "entry", "spans"),
    [
        ("pass --acme-cli now", "--acme-cli", ((5, 15),)),
        ("--acme-cli", "--acme-cli", ((0, 10),)),
        ("x--acme-cli now", "--acme-cli", ()),
        ("--acme-cli-extra", "--acme-cli", ()),
        ("run acme-cli- now", "acme-cli-", ((4, 13),)),
        ("run acme-cli-x now", "acme-cli-", ()),
        ("run acme-cli-- now", "acme-cli-", ()),
    ],
)
def test_kept_spans_with_edge_separators(text, entry, spans):
    assert kept_spans(text, [entry]) == spans


@pytest.mark.parametrize("token", ["--acme-cli", "acme-cli-", "_acme-cli_"])
def test_edge_separator_refusal_prints_keep_line(tmp_path, capsys, token):
    target = _make_target(tmp_path, LANGUAGES, {"docs/a.md": f"pass {token} now\n"})
    code = _press(target, _answers(tmp_path))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    assert f"keep_names = {json.dumps([token])}" in err
    assert "cannot be kept" not in err


@pytest.mark.parametrize("token", ["--acme-cli", "acme-cli-"])
def test_declared_edge_separator_token_survives(tmp_path, token):
    assert SOURCE.owner == "acme"
    target = _make_target(
        tmp_path,
        _keep_rules([token]),
        {"docs/a.md": f"pass {token} now\nrun acme-cli here\n"},
    )
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path)) == 0
    assert (target / "docs" / "a.md").read_text(encoding="utf-8") == (
        f"pass {token} now\nrun new-cli here\n"
    )


def test_declared_edge_separator_does_not_cover_a_longer_token(tmp_path, capsys):
    target = _make_target(
        tmp_path,
        _keep_rules(["--acme-cli"]),
        {"docs/a.md": "pass --acme-cli and --acme-cli-extra\n"},
    )
    code = _press(target, _answers(tmp_path))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    assert 'keep_names = ["--acme-cli-extra"]' in err
    assert _verify(target) == 1


# Single-token values touching a bare separator

BARE_TOKENS = ("__ledgerkit__", "_ledgerkit_", "--zcli", "_zcli_", "_zcli", "zcli_")
BARE_TEXT = (
    "Use __ledgerkit__ and _ledgerkit_ daily.\n"
    "Flag --zcli and _zcli_ and _zcli and zcli_ here.\n"
    "Plain ledgerkit and zcli.\n"
)
SINGLE_SOURCE = replace(SOURCE, npm_name="ledgerkit", cli_name="zcli")
SINGLE_DEST = replace(DEST, npm_name="vaultkit", cli_name="ocli")


def _single_token_target(tmp_path: Path, rules: str) -> Path:
    target = _with_source(tmp_path, SINGLE_SOURCE, rules, {"docs/guide.md": BARE_TEXT})
    manifest = {"name": "ledgerkit", "version": "0.1.0", "bin": {"zcli": "./run.js"}}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "single-token manifest")
    return target


def test_bare_separator_tokens_refuse_press_and_verify(tmp_path, capsys):
    target = _single_token_target(tmp_path, LANGUAGES)
    assert _verify(target) == 1
    capsys.readouterr()
    code = _press(target, _answers(tmp_path, SINGLE_DEST))
    err = capsys.readouterr().err
    _assert_refused_clean(target, code)
    for token in BARE_TOKENS:
        assert f"keep_names = {json.dumps([token])}" in err


def test_declared_bare_separator_tokens_pass_and_survive(tmp_path, capsys):
    target = _single_token_target(tmp_path, _keep_rules(list(BARE_TOKENS)))
    assert _verify(target) == 0
    assert _press(target, _answers(tmp_path, SINGLE_DEST)) == 0
    capsys.readouterr()
    text = (target / "docs" / "guide.md").read_text(encoding="utf-8")
    assert text == BARE_TEXT.replace(
        "Plain ledgerkit and zcli.", "Plain vaultkit and ocli."
    )
    assert (target / RECEIPT_REL).exists()


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("tsc", "tsconfig.json"),
        ("serve", "server"),
        ("serve", "web-server"),
        ("serve", "observe-mode"),
        ("tsc", "vite-tsconfig-paths"),
    ],
)
def test_single_token_inside_an_unrelated_word_is_allowed(value, text):
    source = replace(SOURCE, cli_name=value)
    check = check_keep_surfaces([("a.md", "content", f"{text}\n")], source, ())
    assert check.undeclared == ()


@pytest.mark.parametrize("token", ["tscConfig", "tsc-helper"])
def test_single_token_joined_to_a_name_part_stays_refused(token):
    source = replace(SOURCE, cli_name="tsc")
    check = check_keep_surfaces([("a.md", "content", f"{token}\n")], source, ())
    assert [item.token for item in check.undeclared] == [token]


def test_bare_separator_token_rewritten_by_another_row_is_not_refused(tmp_path):
    source = replace(SOURCE, cli_name="zcli", repo_name="zcli")
    dest = replace(DEST, cli_name="ocli", repo_name="ocli")
    target = _with_source(
        tmp_path, source, LANGUAGES, {"docs/a.md": "see _zcli_ here\n"}
    )
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["bin"] = {"zcli": "./run.js"}
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "bin")
    assert _press(target, _answers(tmp_path, dest)) == 0
    text = (target / "docs" / "a.md").read_text(encoding="utf-8")
    assert text == "see _ocli_ here\n"


def test_exemption_needs_the_row_to_match_that_occurrence():
    source = replace(SOURCE, cli_name="zcli", app_name="zcli")
    forms = RewrittenForms(
        tokens=frozenset({"zcli"}),
        patterns=(token_pattern("app_name", "zcli"),),
    )
    check = check_keep_surfaces(
        [("a.md", "content", "zcli_ and _zcli\n")],
        source,
        (),
        rewritten=lambda _path, _where, _text: forms,
    )
    assert [item.token for item in check.undeclared] == ["_zcli"]


def test_equal_npm_and_repo_bare_token_refuses_before_writing(tmp_path, capsys):
    source = replace(SOURCE, npm_name="ledgerkit", repo_name="ledgerkit")
    dest = replace(DEST, npm_name="vaultkit", repo_name="vaultkit")
    target = _with_source(
        tmp_path, source, LANGUAGES, {"docs/a.md": "see _ledgerkit_ here\n"}
    )
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["name"] = "ledgerkit"
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "name")
    code = _press(target, _answers(tmp_path, dest))
    _assert_refused_clean(target, code)
    assert 'keep_names = ["_ledgerkit_"]' in capsys.readouterr().err


# String-form bin on a pure-Node target


def test_pure_node_string_bin_is_not_proposed_and_verify_passes(tmp_path, capsys):
    target = _make_target(tmp_path, "[rules]\n")
    (target / "press" / "press-source.toml").unlink()
    (target / "pyproject.toml").unlink()
    (target / "src" / SOURCE.package_name / "__init__.py").unlink()
    manifest = {
        "name": "@zeta-org/ledger-kit",
        "version": "0.1.0",
        "bin": "./cli.js",
        "author": f"{SOURCE.author} <{SOURCE.email}>",
    }
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "cli.js").write_text("// ledger_kit entry point\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pure node string bin")
    assert main(["--target", str(target)]) == 2
    assert "cli_name" not in capsys.readouterr().out
    dest = replace(DEST, app_name=DEST.package_name, cli_name=None, display_name=None)
    answers = _answers(tmp_path, dest)
    code = main(
        ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    )
    assert code == 0, capsys.readouterr().err
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    assert _verify(target) == 0


# Punctuation wrapped around an identity value


@pytest.mark.parametrize(
    "entry",
    [
        '"acme-cli"',
        "`acme-cli",
        "`acme-cli`",
        "'acme-repo'",
        "(@acme/widget)",
        "acme-cli.",
    ],
)
def test_punctuation_wrapped_identity_value_is_refused(entry):
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST)
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST, synthetic_dest=True)


def test_punctuation_wrapped_destination_value_is_refused():
    with pytest.raises(ValidationError, match="destination identity"):
        validate_keep_names(['"other-repo"'], SOURCE, DEST)


def test_wrapped_identity_exits_2_before_writes(tmp_path, capsys):
    rules = _keep_rules(['"acme-cli"', "`acme-cli"])
    text = 'run "acme-cli" or `acme-cli --help`\n'
    target = _make_target(tmp_path, rules, {"docs/a.md": text})
    assert _verify(target) == 2
    assert _press(target, _answers(tmp_path)) == 2
    capsys.readouterr()
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


def test_identity_form_ending_in_punctuation_stays_refused():
    source = replace(SOURCE, display_name="Acme!")
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names(["Acme!"], source, DEST)


@pytest.mark.parametrize("entry", ["...", '""', "``"])
def test_punctuation_only_entry_does_not_crash_validation(entry):
    validate_keep_names([entry], SOURCE, DEST)


_VALIDATE_LONG_ENTRY = """
from template_press.rebrand.identity import Identity
from template_press.rebrand.keep_names import validate_keep_names
source = Identity("a_core", "a-repo", "aapp", "A", "a@example.test", "aorg")
dest = Identity("b_core", "b-repo", "bapp", "B", "b@example.test", "borg")
validate_keep_names(["x" + "!" * 200_000 + "x"], source, dest)
"""


def test_long_punctuation_entry_validates_in_bounded_time():
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _VALIDATE_LONG_ENTRY],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert done.returncode == 0, done.stderr


# Edge slash and at-sign around an identity value


@pytest.mark.parametrize(
    "entry",
    [
        "/acme-cli",
        "acme-cli/",
        "@acme-cli",
        "/acme-cli/",
        "@acme",
        "@acme/",
        "/@acme",
        "@acme/widget/",
        "/@acme/widget",
        "@@acme/widget",
        '"@acme-cli"',
    ],
)
def test_slash_or_at_wrapped_identity_value_is_refused(entry):
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST)
    with pytest.raises(ValidationError, match="source identity"):
        validate_keep_names([entry], SOURCE, DEST, synthetic_dest=True)


@pytest.mark.parametrize("entry", ["/acme-cli", "acme-cli/", "@acme-cli", "@acme"])
def test_slash_or_at_wrapped_identity_exits_2_before_writes(tmp_path, capsys, entry):
    target = _make_target(
        tmp_path, _keep_rules([entry]), {"docs/a.md": f"run {entry} now\n"}
    )
    assert _verify(target) == 2
    assert _press(target, _answers(tmp_path)) == 2
    capsys.readouterr()
    assert not (target / RECEIPT_REL).exists()
    assert _status(target) == ""


@pytest.mark.parametrize(
    "entry",
    ["--acme-cli", "acme-cli-", "_acme-cli_", "@acme/widget-", "@acme/widget-extra"],
)
def test_edge_separator_and_true_sibling_stay_keepable(entry):
    validate_keep_names([entry], SOURCE, DEST)
    validate_keep_names([entry], SOURCE, DEST, synthetic_dest=True)


@pytest.mark.parametrize("entry", ["@acme/widget", "acme/widget", "@widget/acme"])
def test_scoped_entry_is_not_reduced_to_an_unrelated_identity_value(entry):
    source = replace(SOURCE, owner="widget", npm_name="@zeta/core", display_name=None)
    dest = replace(DEST, display_name=None)
    validate_keep_names([entry], source, dest)


def test_long_slash_entry_validates_in_bounded_time():
    code = _VALIDATE_LONG_ENTRY.replace('"!" * 200_000', '"/" * 200_000')
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert done.returncode == 0, done.stderr
