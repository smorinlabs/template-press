"""P11 Tasks 1-2: typed directory removal declarations and frozen expansion."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.engine import removal_coverage_warnings
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.removal_types import (
    DirectoryRemoval,
    RemovalMember,
    RemovalPlan,
)
from template_press.rebrand.remove import (
    frozen_remove_command_conflicts,
    render_frozen_remove_plan,
)
from template_press.rebrand.rules import load_rules, load_selected_rules
from template_press.rebrand.safety import SafetyError
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, SOURCE, _git, requires_symlink, write_answers_file
from .test_verify_cli import _commit, make_pressable

DIR_RULE = '[[remove]]\ndir = "research"\nreason = "template research"\n'


def write_dir_rules(repo: Path, body: str = DIR_RULE) -> None:
    (repo / "press").mkdir(parents=True, exist_ok=True)
    (repo / "press/press-rules.toml").write_text(body, encoding="utf-8")


def directory_repo(tmp_path: Path, body: str = DIR_RULE) -> Path:
    repo = make_pressable(tmp_path)
    write_dir_rules(repo, body)
    (repo / "research/sub").mkdir(parents=True)
    (repo / "research/one.md").write_text("first member\n", encoding="utf-8")
    (repo / "research/sub/two.md").write_text("second member\n", encoding="utf-8")
    (repo / "incoming").mkdir()
    (repo / "incoming/late.md").write_text("outside member\n", encoding="utf-8")
    _commit(repo)
    return repo


def test_directory_schema(tmp_path: Path):
    write_dir_rules(tmp_path)
    rules = load_rules(tmp_path)
    assert rules.remove == ()
    assert [(r.dir, r.reason) for r in rules.remove_dirs] == [
        ("research", "template research")
    ]


@pytest.mark.parametrize(
    "body",
    [
        '[[remove]]\nfile="x"\ndir="research"\nreason="r"\n',
        '[[remove]]\nreason="r"\n',
        '[[remove]]\ndir="research"\n',
        '[[remove]]\ndir="research"\nreason=" "\n',
        '[[remove]]\ndir="research/*"\nreason="r"\n',
        '[[remove]]\ndir="../research"\nreason="r"\n',
        '[[remove]]\ndir="."\nreason="r"\n',
        '[[remove]]\ndir="PRESS."\nreason="r"\n',
        '[[remove]]\ndir=".git"\nreason="r"\n',
        '[[remove]]\ndir="research"\nexclude=[".gitkeep"]\nreason="r"\n',
    ],
)
def test_directory_invalid(tmp_path: Path, body: str):
    write_dir_rules(tmp_path, body)
    with pytest.raises(ValidationError):
        load_rules(tmp_path)


@pytest.mark.parametrize(
    "other",
    [
        '[[remove]]\nfile="research/one.md"\nreason="r"\n',
        '[[remove]]\ndir="research/sub"\nreason="r"\n',
        '[[edit]]\nfile="RESEARCH./one.md"\ncommand=["python"]\nexpect="x"\n',
        '[[reset]]\nfile="out.md"\nstub_file="research/one.md"\n',
        '[[regenerate]]\nfile="research/one.md"\ncommand=["python"]\n',
    ],
)
def test_directory_writer_overlap(tmp_path: Path, other: str):
    write_dir_rules(tmp_path, DIR_RULE + other)
    with pytest.raises(ValidationError, match=r"overlap|stub_file"):
        load_rules(tmp_path)


def test_directory_platform_selection(tmp_path: Path):
    write_dir_rules(tmp_path, DIR_RULE + 'platforms=["win32"]\n')
    assert load_selected_rules(tmp_path, platform="linux").rules.remove_dirs == ()
    assert len(load_selected_rules(tmp_path, platform="win32").rules.remove_dirs) == 1


def test_directory_disjoint_platforms(tmp_path: Path):
    write_dir_rules(
        tmp_path,
        '[rules]\nextra_exclude_files=["out.txt"]\n'
        + DIR_RULE
        + 'platforms=["win32"]\n'
        + '[[remove]]\nfile="research/one.md"\nreason="r"\n'
        + 'platforms=["linux", "darwin"]\n',
    )
    assert len(load_selected_rules(tmp_path, platform="linux").rules.remove) == 1


def freeze_fresh(repo: Path, prior: DirectoryRemoval | None = None):
    from template_press.rebrand.remove import _freeze_directory

    (declaration,) = load_rules(repo).remove_dirs
    return _freeze_directory(
        repo, declaration, current_dir=declaration.dir, prior=prior
    )


def test_freeze_exact_members(tmp_path: Path):
    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    assert [m.file for m in directory.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]
    assert [m.current_file for m in directory.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]
    assert all(m.source_dir == "research" for m in directory.members)
    assert all(not m.missing_ok for m in directory.members)


@pytest.mark.parametrize("change", ["modified", "staged", "untracked", "hidden"])
def test_directory_dirty_refuses(tmp_path: Path, change: str):
    repo = directory_repo(tmp_path)
    path = repo / "research/one.md"
    if change == "untracked":
        path = repo / "research/operator note.md"
    if change == "hidden":
        _git(repo, "update-index", "--assume-unchanged", "research/one.md")
    path.write_text("operator work\n", encoding="utf-8")
    if change == "staged":
        _git(repo, "add", "research/one.md")
    with pytest.raises(SafetyError, match=r"uncommitted|dirty|untracked"):
        freeze_fresh(repo)


def test_ignored_file_is_not_member(tmp_path: Path):
    repo = directory_repo(tmp_path)
    with (repo / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("research/cache.bin\n")
    _commit(repo)
    (repo / "research/cache.bin").write_bytes(b"operator cache")
    directory = freeze_fresh(repo)
    assert {m.file for m in directory.members} == {
        "research/one.md",
        "research/sub/two.md",
    }


@pytest.mark.parametrize("kind", ["gitlink", "visibility"])
def test_directory_unsafe_nodes_refuse(tmp_path: Path, kind: str):
    repo = directory_repo(tmp_path)
    if kind == "gitlink":
        head = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{head},research/submodule",
        )
        _git(repo, "commit", "-q", "-m", "gitlink fixture")
    else:
        (repo / "research/.gitignore").write_text("cache/\n", encoding="utf-8")
        _commit(repo)
    with pytest.raises((SafetyError, ValidationError), match=kind):
        freeze_fresh(repo)


@requires_symlink
def test_directory_symlink_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    (repo / "research/link").symlink_to("../incoming/late.md")
    with pytest.raises(SafetyError, match="symlink"):
        freeze_fresh(repo)


@pytest.mark.parametrize("flag", ["assume-unchanged", "skip-worktree"])
def test_directory_hidden_flags_have_paired_control(tmp_path: Path, flag: str):
    repo = directory_repo(tmp_path)
    assert len(freeze_fresh(repo).members) == 2
    _git(repo, "update-index", "--" + flag, "research/one.md")
    with pytest.raises(SafetyError, match=r"assume-unchanged/skip-worktree"):
        freeze_fresh(repo)
    _git(repo, "update-index", "--no-" + flag, "research/one.md")
    assert len(freeze_fresh(repo).members) == 2


def test_empty_and_stale_directory(tmp_path: Path):
    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    _commit(repo)
    with pytest.raises(SafetyError, match=r"does not exist|stale"):
        freeze_fresh(repo)
    (repo / "research").mkdir()
    assert freeze_fresh(repo).members == ()


def test_directory_status_pins_real_worktree(tmp_path: Path):
    repo = directory_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(repo, "config", "core.worktree", str(other))
    assert len(freeze_fresh(repo).members) == 2
    (repo / "research/one.md").write_text("unfinished\n", encoding="utf-8")
    with pytest.raises(SafetyError, match=r"dirty path.*research/one.md"):
        freeze_fresh(repo)


def test_configured_visibility_input_refuses_with_inverse_control(tmp_path: Path):
    repo = directory_repo(tmp_path)
    assert len(freeze_fresh(repo).members) == 2
    _git(repo, "config", "core.excludesFile", str(repo / "research/one.md"))
    with pytest.raises(SafetyError, match="configured visibility input"):
        freeze_fresh(repo)


def test_configured_visibility_hardlink_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    excludes = tmp_path / "external-excludes"
    os.link(repo / "research/one.md", excludes)
    _git(repo, "config", "core.excludesFile", str(excludes))
    with pytest.raises(SafetyError, match="configured visibility input"):
        freeze_fresh(repo)


def test_distinct_visibility_zero_identity_does_not_refuse(tmp_path: Path, monkeypatch):
    repo = directory_repo(tmp_path)
    excludes = tmp_path / "external-excludes"
    excludes.write_text("*.cache\n", encoding="utf-8")
    _git(repo, "config", "core.excludesFile", str(excludes))
    real_stat = os.stat
    selected_paths = {str(repo / "research/one.md"), str(excludes)}

    def zero_inode_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fsdecode(path) in selected_paths:
            values = list(result)
            values[1] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(os, "stat", zero_inode_stat)
    assert len(freeze_fresh(repo).members) == 2


def test_directory_status_problem_bound_reports_omitted_total(tmp_path: Path):
    repo = directory_repo(tmp_path)
    for index in range(25):
        (repo / f"research/operator-{index}.txt").write_text(
            "dirty\n", encoding="utf-8"
        )
    with pytest.raises(SafetyError, match=r"5 additional path\(s\) omitted"):
        freeze_fresh(repo)


@requires_symlink
def test_directory_symlink_ancestor_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "research").mkdir(parents=True)
    (repo / "container").symlink_to(outside, target_is_directory=True)
    write_dir_rules(repo, '[[remove]]\ndir = "container/research"\nreason = "r"\n')
    with pytest.raises(SafetyError):
        freeze_fresh(repo)
    assert outside.joinpath("research").is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows junction control")
def test_directory_junction_refuses_on_native_windows(tmp_path: Path):
    repo = directory_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "cmd",
            "/c",
            "mklink",
            "/J",
            str(repo / "research/junction"),
            str(outside),
        ],
        check=True,
        capture_output=True,
    )
    (outside / "survivor.txt").write_text("survive\n", encoding="utf-8")
    with pytest.raises(SafetyError, match="junction"):
        freeze_fresh(repo)
    assert (outside / "survivor.txt").read_text(encoding="utf-8") == "survive\n"


def test_directory_root_gitlink_refuses(tmp_path: Path):
    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    (repo / "research").mkdir()
    _commit(repo)
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{head},research",
    )
    _git(repo, "commit", "-q", "-m", "root gitlink fixture")
    with pytest.raises(SafetyError, match="root gitlink"):
        freeze_fresh(repo)


def test_directory_control_character_member_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    (repo / "research/line\nbreak.md").write_text("bad\n", encoding="utf-8")
    _commit(repo)
    with pytest.raises(SafetyError, match="unsafe member path"):
        freeze_fresh(repo)


def test_directory_alias_member_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    (repo / "research/one.md.").write_text("alias\n", encoding="utf-8")
    _commit(repo)
    with pytest.raises(SafetyError, match="alias-colliding"):
        freeze_fresh(repo)


def test_directory_audit_key_collision_with_history_refuses(tmp_path: Path):
    repo = directory_repo(tmp_path)
    prior = DirectoryRemoval(
        "research",
        "research",
        "r",
        (
            RemovalMember(
                "research/one.md",
                "research/old-current.md",
                "r",
                "research",
                True,
            ),
        ),
    )
    with pytest.raises(SafetyError, match="audit members"):
        freeze_fresh(repo, prior=prior)


def test_missing_prior_member_is_retained_once(tmp_path: Path):
    repo = directory_repo(tmp_path)
    prior = freeze_fresh(repo)
    (repo / "research/one.md").unlink()
    current = freeze_fresh(repo, prior=prior)
    matches = [
        member for member in current.members if member.current_file == "research/one.md"
    ]
    assert len(matches) == 1
    assert matches[0].missing_ok is True


@pytest.mark.parametrize("flag", ["assume-unchanged", "skip-worktree"])
def test_missing_history_hidden_flag_is_ignored(tmp_path: Path, flag: str):
    repo = directory_repo(tmp_path)
    prior = freeze_fresh(repo)
    (repo / "research/one.md").unlink()
    _git(repo, "update-index", "--" + flag, "research/one.md")
    current = freeze_fresh(repo, prior=prior)
    assert [member.current_file for member in current.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]


@pytest.mark.parametrize("flag", ["assume-unchanged", "skip-worktree"])
def test_missing_without_history_refuses_even_when_hidden(tmp_path: Path, flag: str):
    repo = directory_repo(tmp_path)
    (repo / "research/one.md").unlink()
    _git(repo, "update-index", "--" + flag, "research/one.md")
    with pytest.raises(SafetyError, match="missing without validated prior"):
        freeze_fresh(repo)


def test_missing_empty_history_is_valid(tmp_path: Path):
    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    (repo / "research").mkdir()
    _commit(repo)
    prior = DirectoryRemoval("research", "research", "r", ())
    (repo / "research").rmdir()
    assert freeze_fresh(repo, prior=prior).members == ()


def test_frozen_command_conflicts_include_directory_descendants(tmp_path: Path):
    write_dir_rules(
        tmp_path,
        '[rules]\nextra_exclude_files = ["out.txt"]\n'
        + DIR_RULE
        + '[[regenerate]]\nfile="out.txt"\ncommand=["research/new.txt"]\n',
    )
    rules = load_rules(tmp_path)
    plan = RemovalPlan(directories=(DirectoryRemoval("research", "research", "r", ()),))
    assert frozen_remove_command_conflicts(rules, plan, {})
    assert frozen_remove_command_conflicts(rules, plan, {"research": "archive"})


def test_frozen_render_preserves_file_summary_and_audit_path():
    plan = RemovalPlan(
        files=(RemovalMember("research/one.md", "archive/one.md", "r"),),
        directories=(DirectoryRemoval("research", "archive", "r", ()),),
    )
    rendered = render_frozen_remove_plan(plan)
    assert "research/one.md → archive/one.md" in rendered
    assert "removing 1 file under research/" in rendered
    assert "archive/ (0 files, dir)" in rendered


def test_directory_removal_suppresses_history_warning(tmp_path: Path):
    repo = directory_repo(tmp_path)
    rules = load_rules(repo)
    warnings = removal_coverage_warnings(
        rules,
        SOURCE,
        ["research/one.md", "research/sub/two.md"],
        ["research/one.md", "research/sub/two.md"],
    )
    assert warnings == []


def test_rebrand_refuses_directory_rules_until_executor_exists(tmp_path: Path, capsys):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    from template_press.rebrand.cli import main as rebrand_main

    assert rebrand_main(["--target", str(repo), "--config", str(answers)]) == 2
    assert "complete P11 executor and history integration" in capsys.readouterr().err


def test_verify_refuses_directory_rules_until_executor_exists(tmp_path: Path, capsys):
    repo = directory_repo(tmp_path)
    assert verify_command(["--target", str(repo)]) == 2
    assert "complete P11 executor and history integration" in capsys.readouterr().err
