"""PR review controls for directory visibility and absent-root history."""

from __future__ import annotations

import dataclasses
import os
import subprocess

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.remove import plan_removals
from template_press.rebrand.rules import load_rules
from template_press.rebrand.safety import SafetyError

from .conftest import DEST, _git, write_answers_file
from .test_remove_dirs import (
    directory_repo,
    freeze_fresh,
    point_origin,
    rename_directory_repo,
)
from .test_verify_cli import _commit


def target_bytes(repo):
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


@pytest.mark.parametrize("entrypoint", ["freeze", "dry-run", "apply"])
def test_ignored_configured_visibility_under_directory_refuses(
    tmp_path, capsys, entrypoint
):
    repo = directory_repo(tmp_path)
    with (repo / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("research/active-excludes\n")
    _commit(repo)
    excludes = repo / "research/active-excludes"
    excludes.write_text("*.cache\n", encoding="utf-8")
    # The ignored ordinary file is a permitted nonmember until configured.
    assert len(freeze_fresh(repo).members) == 2
    _git(repo, "config", "core.excludesFile", str(excludes))
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    capsys.readouterr()
    if entrypoint == "freeze":
        with pytest.raises(SafetyError, match="configured visibility input"):
            freeze_fresh(repo)
    else:
        answers = write_answers_file(tmp_path, DEST)
        args = ["--target", str(repo), "--config", str(answers)]
        if entrypoint == "dry-run":
            args.append("--dry-run")
        code = main(args)
        output = capsys.readouterr()
        assert code == 2, (code, output.out, output.err)
        assert "configured visibility input" in output.err
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    assert not (repo / RECEIPT_REL).exists()
    _git(repo, "config", "--unset", "core.excludesFile")
    assert len(freeze_fresh(repo).members) == 2


@pytest.mark.parametrize("entrypoint", ["plan", "dry-run", "apply"])
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("hidden", [False, True])
def test_missing_root_history_rejects_unrecorded_index_member(
    tmp_path, capsys, entrypoint, renamed, hidden
):
    if renamed:
        repo, _source, destination = rename_directory_repo(tmp_path)
        current_root = "archive"
    else:
        repo = directory_repo(tmp_path)
        destination = DEST
        current_root = "research"
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    rules = load_rules(repo)
    receipt_text = (repo / RECEIPT_REL).read_text(encoding="utf-8")
    # Prior recorded absences alone are still accepted without expansion.
    original = plan_removals(repo, rules, source=destination, receipt_text=receipt_text)
    assert original.directories[0].current_dir == current_root
    assert all(member.missing_ok for member in original.members)

    late_rel = f"{current_root}/unrecorded.md"
    late = repo / late_rel
    late.parent.mkdir()
    late.write_text(destination.package_name + "\n", encoding="utf-8")
    _git(repo, "add", late_rel)
    if hidden:
        _git(repo, "update-index", "--skip-worktree", late_rel)
    late.unlink()
    late.parent.rmdir()
    assert not (repo / current_root).exists()
    indexed = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "ls-files", "--", late_rel],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert indexed == [late_rel]
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    capsys.readouterr()
    if entrypoint == "plan":
        with pytest.raises(SafetyError, match="missing without validated prior"):
            plan_removals(repo, rules, source=destination, receipt_text=receipt_text)
    else:
        next_identity = dataclasses.replace(destination, package_name="next_package")
        next_answers = write_answers_file(tmp_path, next_identity)
        args = [
            "--target",
            str(repo),
            "--config",
            str(next_answers),
            "--force",
            "--allow-dirty",
        ]
        if entrypoint == "dry-run":
            args.append("--dry-run")
        code = main(args)
        output = capsys.readouterr()
        assert code == 2, (code, output.out, output.err)
        assert "missing without validated prior" in output.err
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    # Removing only the uncovered index entry restores the accepted history.
    _git(repo, "update-index", "--force-remove", late_rel)
    restored = plan_removals(repo, rules, source=destination, receipt_text=receipt_text)
    assert restored == original


@pytest.mark.parametrize("zero_device", [False, True])
def test_visibility_ancestry_does_not_equate_zero_directory_inodes(
    tmp_path, monkeypatch, zero_device
):
    repo = directory_repo(tmp_path)
    with (repo / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("research/active-excludes\n")
    _commit(repo)
    local_excludes = repo / "research/active-excludes"
    local_excludes.write_text("*.cache\n", encoding="utf-8")
    external_excludes = tmp_path / "external-excludes"
    external_excludes.write_text("*.cache\n", encoding="utf-8")
    _git(repo, "config", "core.excludesFile", str(external_excludes))
    assert len(freeze_fresh(repo).members) == 2
    real_stat = os.stat
    selected = {str(repo / "research"), str(tmp_path)}

    def zero_directory_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fsdecode(path) in selected:
            values = list(result)
            values[1] = 0
            if zero_device:
                values[2] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(os, "stat", zero_directory_stat)
    assert len(freeze_fresh(repo).members) == 2
    # Exact containment still protects a real input with unavailable identity.
    _git(repo, "config", "core.excludesFile", str(local_excludes))
    with pytest.raises(SafetyError, match="configured visibility input"):
        freeze_fresh(repo)
