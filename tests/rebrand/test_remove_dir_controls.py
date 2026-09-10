"""Discriminating controls for frozen directory-removal membership."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.engine import apply
from template_press.rebrand.remove import apply_removal_plan, plan_removals
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, _git, write_answers_file
from .test_remove_dirs import directory_repo, point_origin, rename_directory_repo


def apply_oracle(tmp_path: Path, execute) -> None:
    repo, source, destination = rename_directory_repo(tmp_path)
    rules = load_rules(repo)
    plan = plan_removals(repo, rules, source=source)
    assert [m.file for m in plan.members] == [
        "research/one.md",
        "research/two.md",
    ]
    report = apply(repo, source, destination, rules)
    assert (repo / "archive/one.md").is_file()
    # Explicit lower-level injection; this is not an alleged [[replace]] move.
    os.rename(repo / "incoming/late.md", repo / "archive/late.md")
    removed = execute(repo, plan, dict(report.renamed))
    assert set(removed) == {"archive/one.md", "archive/two.md"}
    assert not (repo / "archive/one.md").exists()
    assert not (repo / "archive/two.md").exists()
    assert (repo / "archive/late.md").read_text(encoding="utf-8") == "outside member\n"
    assert (repo / "archive").is_dir()


def reexpand_at_apply(repo, plan, renamed):
    # Deliberately broken production alternative: current filesystem widens
    # deletion authority after successful renames.
    removed = []
    for path in sorted((repo / "archive").rglob("*")):
        if path.is_file():
            path.unlink()
            removed.append(path.relative_to(repo).as_posix())
    return removed


def test_apply_membership_oracle(tmp_path):
    apply_oracle(tmp_path / "candidate", apply_removal_plan)
    with pytest.raises(AssertionError, match=r"archive/late\.md"):
        apply_oracle(tmp_path / "broken", reexpand_at_apply)


def run_verify_fixture(tmp_path: Path, capsys):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    # A tracked, excluded, identity-bearing nonmember is not rewritten. Only
    # the independent scan exposes it unless verify wrongly deletes it.
    (repo / "research/nonmember.md").write_text(
        DEST.package_name + "\n", encoding="utf-8"
    )
    rules_path = repo / "press/press-rules.toml"
    rules_path.write_text(
        '[rules]\nextra_exclude_files=["research/nonmember.md"]\n'
        + rules_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(repo, "add", "research/nonmember.md", "press/press-rules.toml")
    _git(repo, "commit", "-q", "-m", "new nonmember and exclusion only")
    capsys.readouterr()
    code = verify_command(["--target", str(repo), "--json"])
    import json

    payload = json.loads(capsys.readouterr().out)
    assert (repo / "research/nonmember.md").read_text(
        encoding="utf-8"
    ) == DEST.package_name + "\n"
    return code, payload


def assert_historical_nonmember_visible(code, payload):
    assert code == 1, "historical verify lost the nonmember finding"
    assert payload["verified"] is False
    assert any(
        row["path"] == "research/nonmember.md" and row["field"] == "package_name"
        for row in payload["surviving"]
    )


def test_verify_membership_oracle(tmp_path, monkeypatch, capsys):
    import template_press.rebrand.verify_cli as verify_module

    assert_historical_nonmember_visible(
        *run_verify_fixture(tmp_path / "candidate", capsys)
    )
    real_planner = verify_module.plan_removals

    def fresh_verify_plan(target, rules, **kwargs):
        # Deliberately broken verify: preserve receipt-based missing-file
        # handling but renew the set as though an explicit press was requested.
        return real_planner(target, rules, **{**kwargs, "mode": "press"})

    monkeypatch.setattr(verify_module, "plan_removals", fresh_verify_plan)
    code, payload = run_verify_fixture(tmp_path / "broken", capsys)
    # First prove the mutant falsely succeeds; an early refusal cannot pass.
    assert code == 0, (code, payload)
    assert payload["verified"] is True
    assert payload["surviving"] == []
    assert payload["stale_ignores"] == []
    assert payload["unavailable_submodules"] == []
    with pytest.raises(AssertionError, match="lost the nonmember finding"):
        assert_historical_nonmember_visible(code, payload)


def test_repress_refuses_ambiguous_directory_roots(tmp_path, capsys):
    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)

    declared = repo / "research/declared.md"
    recorded = repo / "archive/recorded.md"
    declared.parent.mkdir()
    recorded.parent.mkdir()
    original = destination.package_name + "\n"
    declared.write_text(original, encoding="utf-8")
    recorded.write_text(original, encoding="utf-8")
    next_identity = dataclasses.replace(destination, package_name="next_package")
    next_answers = write_answers_file(tmp_path, next_identity)

    capsys.readouterr()
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(next_answers),
                "--force",
                "--allow-dirty",
            ]
        )
        == 2
    )
    assert "conflicts with recorded current root" in capsys.readouterr().err
    assert declared.read_text(encoding="utf-8") == original
    assert recorded.read_text(encoding="utf-8") == original


def test_history_cannot_delete_outside_member(tmp_path, capsys):
    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    receipt_path = repo / "press/press-receipt.toml"
    text = receipt_path.read_text(encoding="utf-8")
    assert 'current_file = "archive/one.md"' in text
    receipt_path.write_text(
        text.replace(
            'current_file = "archive/one.md"',
            'current_file = "incoming/late.md"',
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert verify_command(["--target", str(repo)]) == 2
    assert "current_dir" in capsys.readouterr().err
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"
