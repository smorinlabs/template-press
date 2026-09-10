"""Directory removals preserve active and declared Git configuration inputs."""

from __future__ import annotations

import os

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.safety import SafetyError

from .conftest import DEST, _git, write_answers_file
from .test_remove_dir_review import target_bytes
from .test_remove_dirs import directory_repo, freeze_fresh
from .test_verify_cli import _commit

POLICY_BYTES = b"[probe]\n sentinel = retained\n"


def prepare_policy(repo, *, tracked, contents=POLICY_BYTES):
    policy = repo / "research/extra.policy"
    if tracked:
        policy.write_bytes(contents)
        _commit(repo)
    else:
        with (repo / ".gitignore").open("a", encoding="utf-8") as stream:
            stream.write("research/extra.policy\n")
        _commit(repo)
        policy.write_bytes(contents)
    assert len(freeze_fresh(repo).members) == 2 + int(tracked)
    return policy


@pytest.mark.parametrize("entrypoint", ["freeze", "dry-run", "apply"])
@pytest.mark.parametrize("tracked", [False, True], ids=["ignored", "tracked"])
def test_active_git_config_input_refuses_directory_removal(
    tmp_path, capsys, entrypoint, tracked
):
    repo = directory_repo(tmp_path)
    policy = prepare_policy(repo, tracked=tracked)
    _git(repo, "config", "include.path", str(policy))
    snapshot = capture_surface_snapshot(repo)
    assert policy in {item.path for item in snapshot.git_config_inputs}
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    before_config = (repo / ".git/config").read_bytes()
    capsys.readouterr()
    if entrypoint == "freeze":
        with pytest.raises(SafetyError, match="Git config input"):
            freeze_fresh(repo)
    else:
        answers = write_answers_file(tmp_path, DEST)
        args = ["--target", str(repo), "--config", str(answers)]
        if entrypoint == "dry-run":
            args.append("--dry-run")
        code = main(args)
        output = capsys.readouterr()
        assert code == 2, (code, output.out, output.err)
        assert "Git config input" in output.err
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    assert (repo / ".git/config").read_bytes() == before_config
    assert not (repo / RECEIPT_REL).exists()
    assert capture_surface_snapshot(repo) == snapshot
    _git(repo, "config", "--unset", "include.path")
    assert len(freeze_fresh(repo).members) == 2 + int(tracked)


@pytest.mark.parametrize("include_kind", ["empty-active", "inactive"])
@pytest.mark.parametrize("tracked", [False, True], ids=["ignored", "tracked"])
def test_declared_git_include_without_active_values_refuses_directory_removal(
    tmp_path, include_kind, tracked
):
    repo = directory_repo(tmp_path)
    contents = (
        b"# configured policy\n" if include_kind == "empty-active" else POLICY_BYTES
    )
    policy = prepare_policy(repo, tracked=tracked, contents=contents)
    key = (
        "includeIf.onbranch:main.path"
        if include_kind == "empty-active"
        else "includeIf.onbranch:inactive-removal-probe.path"
    )
    _git(repo, "config", key, str(policy))
    snapshot = capture_surface_snapshot(repo)
    if include_kind == "inactive":
        assert policy not in {item.path for item in snapshot.git_config_inputs}
    assert policy in snapshot.git_config_include_paths
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    with pytest.raises(SafetyError, match=r"Git config (input|include)"):
        freeze_fresh(repo)
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    assert capture_surface_snapshot(repo) == snapshot
    _git(repo, "config", "--unset", key)
    assert len(freeze_fresh(repo).members) == 2 + int(tracked)


def test_disjoint_and_missing_git_config_includes_allow_directory_removal(tmp_path):
    repo = directory_repo(tmp_path)
    outside = tmp_path / "external.policy"
    outside.write_bytes(POLICY_BYTES)
    missing = repo / "research/missing.policy"
    _git(repo, "config", "include.path", str(outside))
    _git(repo, "config", "--add", "include.path", str(missing))
    original = freeze_fresh(repo)
    assert len(original.members) == 2
    assert not missing.exists()
    assert outside.read_bytes() == POLICY_BYTES
    _git(repo, "config", "--unset-all", "include.path")
    assert freeze_fresh(repo) == original


def test_active_git_config_hardlink_alias_refuses_directory_removal(tmp_path):
    repo = directory_repo(tmp_path)
    policy = prepare_policy(repo, tracked=True)
    outside = tmp_path / "external.policy"
    os.link(policy, outside)
    # Make the committed stat cache stale without changing the policy bytes.
    info = policy.stat()
    os.utime(policy, ns=(info.st_atime_ns, info.st_mtime_ns - 2_000_000_000))
    _git(repo, "config", "include.path", str(outside))
    before = target_bytes(repo)
    before_index = (repo / ".git/index").read_bytes()
    with pytest.raises(SafetyError, match="Git config input"):
        freeze_fresh(repo)
    assert target_bytes(repo) == before
    assert (repo / ".git/index").read_bytes() == before_index
    assert outside.read_bytes() == POLICY_BYTES
    _git(repo, "config", "--unset", "include.path")
    assert len(freeze_fresh(repo).members) == 3
