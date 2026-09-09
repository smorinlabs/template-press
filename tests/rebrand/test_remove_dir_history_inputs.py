"""History-backed directory plans retain index and Git-input safety checks."""

from __future__ import annotations

import dataclasses
import subprocess

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.remove import plan_removals
from template_press.rebrand.rules import load_rules
from template_press.rebrand.safety import SafetyError
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, _git, write_answers_file
from .test_remove_dir_review import target_bytes
from .test_remove_dirs import directory_repo, point_origin


def prepared_history(tmp_path):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    rules = load_rules(repo)
    receipt = (repo / RECEIPT_REL).read_text(encoding="utf-8")
    return repo, rules, receipt


@pytest.mark.parametrize("entrypoint", ["plan", "dry-run", "apply"])
@pytest.mark.parametrize("replacement", ["blob", "symlink-mode"])
@pytest.mark.parametrize("hidden", [False, True], ids=["visible", "skip-worktree"])
def test_missing_root_history_rejects_modified_indexed_member(
    tmp_path, capsys, entrypoint, replacement, hidden
):
    repo, rules, receipt = prepared_history(tmp_path)
    original = plan_removals(repo, rules, source=DEST, receipt_text=receipt)
    relative = "research/one.md"
    original_entry = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "ls-files", "--stage", "--", relative],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    original_mode, original_oid = original_entry[:2]
    payload = (DEST.package_name + " unrecorded replacement\n").encode()
    new_oid = (
        subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],  # noqa: S607
            check=True,
            input=payload,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    mode = "120000" if replacement == "symlink-mode" else original_mode
    _git(repo, "update-index", "--cacheinfo", f"{mode},{new_oid},{relative}")
    if hidden:
        _git(repo, "update-index", "--skip-worktree", relative)
    assert not (repo / "research").exists()
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    capsys.readouterr()
    if entrypoint == "plan":
        with pytest.raises(SafetyError, match="dirty path"):
            plan_removals(repo, rules, source=DEST, receipt_text=receipt)
    else:
        destination = dataclasses.replace(DEST, package_name="next_package")
        answers = write_answers_file(tmp_path, destination)
        args = [
            "--target",
            str(repo),
            "--config",
            str(answers),
            "--force",
            "--allow-dirty",
        ]
        if entrypoint == "dry-run":
            args.append("--dry-run")
        code = main(args)
        output = capsys.readouterr()
        assert code == 2, (code, output.out, output.err)
        assert "dirty path" in output.err
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    _git(
        repo,
        "update-index",
        "--cacheinfo",
        f"{original_mode},{original_oid},{relative}",
    )
    if hidden:
        _git(repo, "update-index", "--skip-worktree", relative)
    assert plan_removals(repo, rules, source=DEST, receipt_text=receipt) == original


@pytest.mark.parametrize("entrypoint", ["plan", "human", "json"])
@pytest.mark.parametrize("input_kind", ["visibility", "config", "inactive-include"])
def test_history_verification_protects_restored_git_inputs(
    tmp_path, capsys, entrypoint, input_kind
):
    repo, rules, receipt = prepared_history(tmp_path)
    original = plan_removals(
        repo, rules, source=DEST, receipt_text=receipt, mode="verify"
    )
    restored = repo / "research/one.md"
    restored.parent.mkdir()
    restored.write_text("[probe]\n sentinel = retained\n", encoding="utf-8")
    key = {
        "visibility": "core.excludesFile",
        "config": "include.path",
        "inactive-include": "includeIf.onbranch:inactive-removal-probe.path",
    }[input_kind]
    diagnostic = (
        "configured visibility input" if input_kind == "visibility" else "Git config"
    )
    _git(repo, "config", key, str(restored))
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    before_config = (repo / ".git/config").read_bytes()
    capsys.readouterr()
    if entrypoint == "plan":
        with pytest.raises(SafetyError, match=diagnostic):
            plan_removals(repo, rules, source=DEST, receipt_text=receipt, mode="verify")
    else:
        args = ["--target", str(repo)] + (["--json"] if entrypoint == "json" else [])
        code = verify_command(args)
        output = capsys.readouterr()
        assert code == 2, (code, output.out, output.err)
        assert diagnostic in output.err
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    assert (repo / ".git/config").read_bytes() == before_config
    _git(repo, "config", "--unset", key)
    # Restored ordinary recorded files remain valid historical removals.
    assert (
        plan_removals(repo, rules, source=DEST, receipt_text=receipt, mode="verify")
        == original
    )
    args = ["--target", str(repo)] + (["--json"] if entrypoint == "json" else [])
    assert verify_command(args) == 0
