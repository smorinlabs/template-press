"""P11 directory removal declarations, frozen execution, and historical integration."""

from __future__ import annotations

import dataclasses
import errno
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.engine import removal_coverage_warnings
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
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


def test_verify_fresh_directory_rules(tmp_path: Path):
    repo = directory_repo(tmp_path)
    assert verify_command(["--target", str(repo)]) == 0
    assert (repo / "research/one.md").read_text(encoding="utf-8") == "first member\n"


def test_cleanup_preserves_nonmembers(tmp_path):
    from template_press.rebrand.removal_types import RemovalPlan
    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    (repo / "research/unselected-empty").mkdir()
    (repo / "research/cache.bin").write_bytes(b"must survive")
    removed = apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {})
    assert removed == ["research/one.md", "research/sub/two.md"]
    assert not (repo / "research/sub").exists()
    assert (repo / "research/unselected-empty").is_dir()
    assert (repo / "research/cache.bin").read_bytes() == b"must survive"


def test_empty_history_round_trip(tmp_path):
    from template_press.rebrand.removal_types import RemovalPlan
    from template_press.rebrand.remove import apply_removal_plan

    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    _commit(repo)
    (repo / "research").mkdir()
    directory = freeze_fresh(repo)
    assert apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {}) == []
    assert not (repo / "research").exists()


def test_executor_validates_entire_plan_before_unlink(tmp_path):
    from dataclasses import replace

    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    bad = replace(directory.members[-1], current_file="incoming/late.md")
    directory = replace(directory, members=(directory.members[0], bad))
    with pytest.raises(ValidationError, match="current_dir"):
        apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {})
    assert (repo / "research/one.md").read_text() == "first member\n"
    assert (repo / "incoming/late.md").read_text() == "outside member\n"


def test_executor_translates_once_and_preserves_retained_history(tmp_path):
    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    (repo / "research").rename(repo / "archive")
    retained = DirectoryRemoval(
        "incoming",
        "incoming",
        "inactive",
        (
            RemovalMember(
                "incoming/late.md", "incoming/late.md", "inactive", "incoming", True
            ),
        ),
    )
    removed = apply_removal_plan(
        repo,
        RemovalPlan(directories=(directory,), retained_history=(retained,)),
        {"research": "archive"},
    )
    assert removed == ["archive/one.md", "archive/sub/two.md"]
    assert not (repo / "archive").exists()
    assert (repo / "incoming/late.md").read_text() == "outside member\n"


@pytest.mark.parametrize("missing_ok", [False, True])
def test_executor_absence_requires_member_authorization(tmp_path, missing_ok):
    from dataclasses import replace

    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    (repo / "research/one.md").unlink()
    directory = replace(
        directory,
        members=tuple(replace(m, missing_ok=missing_ok) for m in directory.members),
    )
    plan = RemovalPlan(directories=(directory,))
    if missing_ok:
        assert apply_removal_plan(repo, plan, {}) == ["research/sub/two.md"]
        assert not (repo / "research").exists()
    else:
        with pytest.raises(SafetyError, match="does not exist"):
            apply_removal_plan(repo, plan, {})
        assert (repo / "research/sub/two.md").exists()


def test_executor_history_limits_precede_any_unlink(tmp_path):
    from dataclasses import replace

    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    directory = replace(directory, reason="x" * 4097)
    with pytest.raises(
        ValidationError, match="directory text byte limit 4096 exceeded"
    ):
        apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {})
    assert (repo / "research/one.md").read_text() == "first member\n"


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_cleanup_propagates_unexpected_errors(tmp_path, monkeypatch, error):
    import template_press.rebrand.remove as module

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    actual_rmdir = module.os.rmdir

    def failing_rmdir(path, *args, **kwargs):
        if Path(path) == repo / "research/sub":
            raise OSError(error, "injected cleanup failure")
        return actual_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "rmdir", failing_rmdir)
    with pytest.raises(OSError) as exc:
        module.apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {})
    assert exc.value.errno == error
    assert not (repo / "research/one.md").exists()
    assert not (repo / "research/sub/two.md").exists()
    assert (repo / "incoming/late.md").read_text() == "outside member\n"


def test_cleanup_rejects_wrong_kind_selected_empty_root(tmp_path):
    from template_press.rebrand.remove import apply_removal_plan

    (tmp_path / "research").write_text("sentinel", encoding="utf-8")
    row = DirectoryRemoval("research", "research", "r", ())
    with pytest.raises(SafetyError, match="not a real directory"):
        apply_removal_plan(tmp_path, RemovalPlan(directories=(row,)), {})
    assert (tmp_path / "research").read_text() == "sentinel"


def test_file_only_executor_preserves_empty_parent(tmp_path):
    from template_press.rebrand.remove import apply_removal_plan

    (tmp_path / "ordinary").mkdir()
    (tmp_path / "ordinary/a.md").write_text("file", encoding="utf-8")
    plan = RemovalPlan(files=(RemovalMember("ordinary/a.md", "ordinary/a.md", "r"),))
    assert apply_removal_plan(tmp_path, plan, {}) == ["ordinary/a.md"]
    assert (tmp_path / "ordinary").is_dir()


def test_frozen_history_byte_limit_precedes_unlink(tmp_path):
    from template_press.rebrand.remove import apply_removal_plan

    (tmp_path / "research").mkdir()
    sentinel = tmp_path / "research/first"
    sentinel.write_text("preserved", encoding="utf-8")
    members = [RemovalMember("research/first", "research/first", "r", "research")]
    for index in range(2100):
        path = f"research/{index}" + "x" * 3900
        members.append(RemovalMember(path, path, "r", "research", True))
    row = DirectoryRemoval("research", "research", "r", tuple(members))
    with pytest.raises(
        ValidationError, match="directory receipt byte limit 16777216 exceeded"
    ):
        apply_removal_plan(tmp_path, RemovalPlan(directories=(row,)), {})
    assert sentinel.read_text() == "preserved"


def test_executor_refuses_junction_ancestor_before_unlink(tmp_path, monkeypatch):
    from template_press.rebrand.remove import apply_removal_plan

    (tmp_path / "research/sub").mkdir(parents=True)
    path = tmp_path / "research/sub/member"
    path.write_text("preserved", encoding="utf-8")
    member = RemovalMember(
        "research/sub/member", "research/sub/member", "r", "research"
    )
    row = DirectoryRemoval("research", "research", "r", (member,))
    actual_is_junction = Path.is_junction

    def junction_at_parent(path):
        return path == tmp_path / "research/sub" or actual_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", junction_at_parent)
    with pytest.raises(SafetyError):
        apply_removal_plan(tmp_path, RemovalPlan(directories=(row,)), {})
    assert path.read_text() == "preserved"


def rename_directory_repo(tmp_path):
    source = dataclasses.replace(SOURCE, author="research")
    destination = dataclasses.replace(DEST, author="archive")
    repo = make_pressable(tmp_path, identity=source.as_dict_prompted())
    write_dir_rules(
        repo,
        '[[replace]]\npattern="{author}"\npaths=true\ncontent=false\n'
        'files=["research/**", "archive/**"]\nreason="rename research directory"\n'
        + DIR_RULE,
    )
    (repo / "research").mkdir()
    (repo / "research/one.md").write_text("first member\n", encoding="utf-8")
    (repo / "research/two.md").write_text("second member\n", encoding="utf-8")
    (repo / "incoming").mkdir()
    (repo / "incoming/late.md").write_text("outside member\n", encoding="utf-8")
    _commit(repo)
    return repo, source, destination


def test_cli_directory_rename_receipt_verify(tmp_path, capsys):
    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    args = ["--target", str(repo), "--config", str(answers)]
    assert main([*args, "--dry-run"]) == 0
    preview = capsys.readouterr().out
    assert "research/ (2 files, dir)" in preview
    assert "research/one.md" in preview and "research/two.md" in preview
    assert (repo / "research/one.md").read_text(encoding="utf-8") == "first member\n"
    assert main(args) == 0
    point_origin(repo, destination)
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["remove"] == [
        {"file": "research/one.md", "reason": "template research"},
        {"file": "research/two.md", "reason": "template research"},
    ]
    row = receipt["press"]["remove_dir"][0]
    assert row["dir"] == "research"
    assert row["current_dir"] == "archive"
    assert [m["current_file"] for m in row["members"]] == [
        "archive/one.md",
        "archive/two.md",
    ]
    assert not (repo / "research").exists()
    assert not (repo / "archive").exists()
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"
    assert verify_command(["--target", str(repo), "--json"]) == 0


def test_renewal_keeps_tombstones(tmp_path):
    from template_press.rebrand.config import load_source_config
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    (repo / "research/new.md").write_text("new committed member\n", encoding="utf-8")
    # Commit ONLY the new member; prior successful deletions remain unstaged.
    _git(repo, "add", "research/new.md")
    _git(repo, "commit", "-q", "-m", "new member only")
    source = load_source_config(repo, None)
    assert source is not None
    plan = plan_removals(
        repo, load_rules(repo), source=source, receipt_text=read_receipt(repo)
    )
    members = {m.current_file: m for m in plan.directories[0].members}
    assert set(members) == {"research/one.md", "research/sub/two.md", "research/new.md"}
    assert members["research/one.md"].missing_ok is True
    assert members["research/sub/two.md"].missing_ok is True
    assert members["research/new.md"].missing_ok is False
    assert members["research/new.md"].file == "research/new.md"
    assert verify_command(["--target", str(repo)]) == 0
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    next_answers = write_answers_file(tmp_path, next_identity)
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
        == 0
    )
    text = (repo / RECEIPT_REL).read_text(encoding="utf-8")
    receipt = tomllib.loads(text)
    assert receipt["press"]["counts"]["removed"] == 1
    assert {row["file"] for row in receipt["press"]["remove"]} == {
        "research/one.md",
        "research/sub/two.md",
        "research/new.md",
    }


@pytest.mark.parametrize("operator_change", ["modified", "untracked"])
def test_renewal_refuses_operator_changes(tmp_path, operator_change):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    path = repo / "research/operator.md"
    path.write_text("committed\n", encoding="utf-8")
    if operator_change == "modified":
        _git(repo, "add", "research/operator.md")
        _git(repo, "commit", "-q", "-m", "operator file only")
    path.write_text("private unfinished work\n", encoding="utf-8")
    with pytest.raises(SafetyError, match=r"dirty|uncommitted|untracked"):
        plan_removals(
            repo, load_rules(repo), source=DEST, receipt_text=read_receipt(repo)
        )
    assert path.read_text(encoding="utf-8") == "private unfinished work\n"


def test_partial_directory_failure_has_no_receipt(tmp_path, monkeypatch):
    import template_press.rebrand.remove as removal

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    real_unlink = removal.os.unlink
    removed_members = []

    def fail_second(path, *args, **kwargs):
        try:
            rel = Path(path).relative_to(repo).as_posix()
        except (TypeError, ValueError):
            return real_unlink(path, *args, **kwargs)
        if rel == "research/sub/two.md":
            raise SafetyError("injected second removal failure")
        result = real_unlink(path, *args, **kwargs)
        if rel == "research/one.md":
            removed_members.append(rel)
        return result

    monkeypatch.setattr(removal.os, "unlink", fail_second)
    assert main(["--target", str(repo), "--config", str(answers)]) == 1
    assert removed_members == ["research/one.md"]
    assert (repo / "research/sub/two.md").is_file()
    assert not (repo / RECEIPT_REL).exists()


def test_resolved_history_writer_conflict(tmp_path):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    rules_path = repo / "press/press-rules.toml"
    with rules_path.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[[edit]]\nfile="archive/new.md"\ncommand=["python"]\nexpect="x"\n'
        )
    # Static declarations use research versus archive, so raw parser accepts;
    # exact recorded current-root overlap must refuse before execution.
    rules = load_rules(repo)
    with pytest.raises((SafetyError, ValidationError), match=r"overlap|conflict"):
        plan_removals(repo, rules, source=destination, receipt_text=read_receipt(repo))


def test_cli_active_directory_first_receipt_read_is_bounded(
    tmp_path, monkeypatch, capsys
):
    import template_press.rebrand.cli as cli_module
    import template_press.rebrand.receipt as receipt_module
    import template_press.rebrand.remove as remove_module

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    (repo / RECEIPT_REL).write_bytes(b"#" + b"x" * (16 * 1024 * 1024))
    original_read = receipt_module.read_receipt
    calls = []

    def bounded_read(target, *, max_bytes=None):
        assert max_bytes == 16 * 1024 * 1024, (
            "active directory reached unbounded text read"
        )
        calls.append(max_bytes)
        return original_read(target, max_bytes=max_bytes)

    for module in (cli_module, receipt_module, remove_module):
        monkeypatch.setattr(module, "read_receipt", bounded_read, raising=False)
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(answers),
            "--force",
            "--allow-dirty",
            "--dry-run",
        ]
    )
    assert code == 2
    assert "directory receipt byte limit 16777216 exceeded" in capsys.readouterr().err
    assert calls == [16 * 1024 * 1024]
    assert (repo / "research/one.md").read_text(encoding="utf-8") == "first member\n"


def test_directory_history_router_preserves_malformed_legacy():
    from template_press.rebrand.receipt import selected_directory_history

    malformed = "[press\nnot toml"
    assert selected_directory_history(malformed, SOURCE, directory_declared=False) == ()
    with pytest.raises(ValidationError, match=r"TOML|receipt"):
        selected_directory_history(malformed, SOURCE, directory_declared=True)


def test_direct_press_directory_fallback_reads_history(tmp_path):
    from template_press.rebrand.cli import _press

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    outcome = _press(repo, DEST, next_identity, load_rules(repo), [], [])
    assert outcome.env_error is None
    assert not outcome.leaked
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert len(receipt["press"]["remove"]) == 2
    assert len({row["file"] for row in receipt["press"]["remove"]}) == 2
    assert receipt["press"]["counts"]["removed"] == 0


def test_partial_repress_invalidates_previous_receipt(tmp_path, monkeypatch, capsys):
    import template_press.rebrand.remove as removal

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    prior_receipt = (repo / RECEIPT_REL).read_bytes()
    assert b"verified = true" in prior_receipt
    (repo / "research/sub").mkdir(parents=True)
    (repo / "research/one.md").write_text("restored first\n", encoding="utf-8")
    (repo / "research/sub/two.md").write_text("restored second\n", encoding="utf-8")
    _git(repo, "add", "research/one.md", "research/sub/two.md")
    _git(repo, "commit", "-q", "-m", "restore only removal members")
    assert (repo / RECEIPT_REL).read_bytes() == prior_receipt
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    next_answers = write_answers_file(tmp_path, next_identity)
    original_unlink = removal.os.unlink
    removed = []

    def fail_second(path, *args, **kwargs):
        try:
            rel = Path(path).relative_to(repo).as_posix()
        except (TypeError, ValueError):
            return original_unlink(path, *args, **kwargs)
        if rel == "research/sub/two.md":
            raise SafetyError("injected second removal failure")
        result = original_unlink(path, *args, **kwargs)
        if rel == "research/one.md":
            removed.append(rel)
        return result

    monkeypatch.setattr(removal.os, "unlink", fail_second)
    capsys.readouterr()
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(next_answers),
            "--force",
            "--allow-dirty",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "injected second removal failure" in captured.err
    assert "prior receipt invalidated" in captured.out
    assert removed == ["research/one.md"]
    assert (repo / "research/sub/two.md").read_text(
        encoding="utf-8"
    ) == "restored second\n"
    assert not (repo / RECEIPT_REL).exists()


def test_historical_ancestor_translation():
    from template_press.rebrand.removal_types import (
        DirectoryRemoval,
        RemovalMember,
        RemovalPlan,
    )
    from template_press.rebrand.remove import translate_removal_plan

    row = DirectoryRemoval(
        dir="old/research",
        current_dir="old/archive",
        reason="r",
        members=(
            RemovalMember(
                file="old/research/demo.md",
                source_dir="old/research",
                current_file="old/archive/renamed.md",
                reason="r",
                missing_ok=True,
            ),
        ),
    )
    updated = translate_removal_plan(RemovalPlan(directories=(row,)), {"old": "new"})
    assert updated.directories[0].current_dir == "new/archive"
    member = updated.directories[0].members[0]
    assert (member.file, member.source_dir, member.current_file) == (
        "old/research/demo.md",
        "old/research",
        "new/archive/renamed.md",
    )
    assert member.missing_ok


def point_origin(repo, identity):
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{identity.owner}/{identity.repo_name}.git",
    )


@pytest.mark.parametrize("direct", [False, True])
def test_cli_directory_internal_filename_translation(tmp_path, direct):
    from template_press.rebrand.cli import _press

    repo, source, destination = rename_directory_repo(tmp_path)
    with (repo / "press/press-rules.toml").open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[[replace]]\npattern="{app_name}.md"\npaths=true\ncontent=false\nfiles=["research/**", "archive/**"]\nreason="rename member"\n'
        )
    (repo / "research/press.md").write_text("third member\n", encoding="utf-8")
    _commit(repo)
    if direct:
        outcome = _press(repo, source, destination, load_rules(repo), [], [])
        assert outcome.env_error is None
        assert not outcome.leaked
    else:
        answers = write_answers_file(tmp_path, destination)
        assert main(["--target", str(repo), "--config", str(answers)]) == 0
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    member = next(
        m
        for m in receipt["press"]["remove_dir"][0]["members"]
        if m["file"] == "research/press.md"
    )
    assert member["current_file"] == "archive/potato.md"
    point_origin(repo, destination)
    assert verify_command(["--target", str(repo), "--json"]) == 0


@pytest.mark.parametrize("supply_table", [False, True])
def test_direct_press_dirty_directory_before_mutation(tmp_path, supply_table):
    from template_press.rebrand.cli import _press
    from template_press.rebrand.engine import build_plan

    repo = directory_repo(tmp_path)
    rules = load_rules(repo)
    (repo / "research/one.md").write_text("private unfinished work\n", encoding="utf-8")
    before = (repo / "pyproject.toml").read_bytes()
    table = build_plan(repo, SOURCE, DEST, rules).table if supply_table else None
    outcome = _press(repo, SOURCE, DEST, rules, [], [], table=table)
    assert outcome.env_error is not None
    assert "dirty" in outcome.env_error
    assert (repo / "research/one.md").read_text(
        encoding="utf-8"
    ) == "private unfinished work\n"
    assert (repo / "pyproject.toml").read_bytes() == before
    assert not (repo / RECEIPT_REL).exists()


def test_renewal_restored_members_keep_audit_coordinates(tmp_path):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    (repo / "archive").mkdir()
    (repo / "archive/one.md").write_text("restored first\n", encoding="utf-8")
    _git(repo, "add", "archive/one.md")
    _git(repo, "commit", "-q", "-m", "restore only recorded member")
    plan = plan_removals(
        repo, load_rules(repo), source=destination, receipt_text=read_receipt(repo)
    )
    restored = next(m for m in plan.members if m.current_file == "archive/one.md")
    assert (restored.file, restored.source_dir, restored.missing_ok) == (
        "research/one.md",
        "research",
        False,
    )


def test_verify_history_does_not_expand_membership(tmp_path):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    new_member = repo / "research/operator.md"
    new_member.write_text("operator unfinished work\n", encoding="utf-8")
    plan = plan_removals(
        repo,
        load_rules(repo),
        source=DEST,
        receipt_text=read_receipt(repo),
        mode="verify",
    )
    assert [m.current_file for m in plan.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]
    assert verify_command(["--target", str(repo), "--json"]) == 0
    assert new_member.read_text(encoding="utf-8") == "operator unfinished work\n"


def test_cli_inactive_history_preserved_without_execution(tmp_path):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    restored = repo / "research/one.md"
    restored.write_text("operator restored content\n", encoding="utf-8")
    write_dir_rules(repo, "")
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    next_answers = write_answers_file(tmp_path, next_identity)
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
        == 0
    )
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["counts"]["removed"] == 0
    assert len(receipt["press"]["remove_dir"][0]["members"]) == 2
    assert len(receipt["press"]["remove"]) == 2
    assert restored.read_text(encoding="utf-8") == "operator restored content\n"


@pytest.mark.parametrize("alias", ["RESEARCH", "research/sub", "archive"])
def test_renewal_history_alias_refused_before_lookup(tmp_path, alias):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo, _source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    write_dir_rules(repo, f'[[remove]]\ndir="{alias}"\nreason="r"\n')
    with pytest.raises(SafetyError, match=r"conflict|alias"):
        plan_removals(
            repo, load_rules(repo), source=destination, receipt_text=read_receipt(repo)
        )


def test_verify_history_wrong_kind_refuses_before_sandbox(tmp_path, capsys):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research/one.md").mkdir(parents=True)
    capsys.readouterr()
    assert verify_command(["--target", str(repo), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "preflight failed" in captured.err
    assert (repo / "research/one.md").is_dir()


@pytest.mark.parametrize("explicit", [False, True])
def test_direct_directory_legacy_mapping_precedence(tmp_path, explicit):
    from template_press.rebrand.cli import _press

    repo = directory_repo(tmp_path)
    with (repo / "press/press-rules.toml").open("a", encoding="utf-8") as stream:
        stream.write('[[remove]]\nfile="old.md"\nreason="legacy"\n')
    (repo / "old.md").write_text("legacy file\n", encoding="utf-8")
    _commit(repo)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    mapping = {"old.md": "legacy"} if explicit else {}
    outcome = _press(
        repo, DEST, next_identity, load_rules(repo), [], [], previously_removed=mapping
    )
    if explicit:
        assert outcome.env_error is None
        assert not outcome.leaked
    else:
        assert outcome.env_error is not None
        assert "old.md" in outcome.env_error and "does not exist" in outcome.env_error


def test_direct_press_invalid_history_precedes_reset(tmp_path):
    from template_press.rebrand.cli import _press
    from template_press.rebrand.rules import ResetRule

    repo = directory_repo(tmp_path)
    bad = RemovalPlan(
        directories=(DirectoryRemoval("research", "research", "x" * 4097, ()),)
    )
    before = (repo / "README.md").read_bytes()
    outcome = _press(
        repo,
        SOURCE,
        DEST,
        load_rules(repo),
        [],
        [(ResetRule(file="README.md", stub="reset\n"), "reset\n")],
        removal_plan=bad,
    )
    assert outcome.env_error is not None
    assert (repo / "README.md").read_bytes() == before
    assert (repo / "research/one.md").exists()
    assert not (repo / RECEIPT_REL).exists()


@pytest.mark.parametrize("supply_table", [False, True])
def test_direct_press_projected_history_limit_precedes_reset(tmp_path, supply_table):
    from template_press.rebrand.cli import _press
    from template_press.rebrand.engine import build_plan
    from template_press.rebrand.remove import plan_removals
    from template_press.rebrand.rules import ResetRule

    repo = directory_repo(tmp_path)
    rules = load_rules(repo)
    plan = plan_removals(repo, rules, source=SOURCE)
    prefix = "src/demo_widget/" + "a/" * 2035
    current_file = prefix + "x" * (4095 - len(prefix))
    row = DirectoryRemoval(
        dir="retired",
        current_dir=prefix.rstrip("/"),
        reason="history",
        members=(
            RemovalMember(
                file="retired/x",
                source_dir="retired",
                current_file=current_file,
                reason="history",
                missing_ok=True,
            ),
        ),
    )
    plan = dataclasses.replace(plan, retained_history=(row,))
    table = build_plan(repo, SOURCE, DEST, rules).table if supply_table else None
    before = (repo / "README.md").read_bytes()
    outcome = _press(
        repo,
        SOURCE,
        DEST,
        rules,
        [],
        [(ResetRule(file="README.md", stub="reset\n"), "reset\n")],
        table=table,
        removal_plan=plan,
    )
    assert outcome.env_error is not None
    assert "4096" in outcome.env_error
    assert (repo / "README.md").read_bytes() == before
    assert (repo / "research/one.md").exists()
    assert not (repo / RECEIPT_REL).exists()


def test_resolved_directory_writer_overlap_precedes_cli_mutation(tmp_path, capsys):
    repo, _source, destination = rename_directory_repo(tmp_path)
    with (repo / "press/press-rules.toml").open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[[edit]]\nfile="archive/new.md"\ncommand=["python"]\nexpect="x"\n'
        )
    _commit(repo)
    answers = write_answers_file(tmp_path, destination)
    before = (repo / "pyproject.toml").read_bytes()
    assert main(["--target", str(repo), "--config", str(answers)]) == 2
    assert "overlap" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_bytes() == before
    assert (repo / "research/one.md").exists()
    assert not (repo / RECEIPT_REL).exists()


def test_active_file_cannot_alias_retained_directory_member(tmp_path):
    from template_press.rebrand.remove import validate_removal_conflicts
    from template_press.rebrand.rules import DEFAULT_RULES

    row = DirectoryRemoval(
        dir="old",
        current_dir="archive",
        reason="history",
        members=(
            RemovalMember(
                file="old/one.md",
                source_dir="old",
                current_file="archive/one.md",
                reason="history",
                missing_ok=True,
            ),
        ),
    )
    plan = RemovalPlan(
        files=(RemovalMember("archive/ONE.md", "archive/ONE.md", "active"),),
        retained_history=(row,),
    )
    with pytest.raises((SafetyError, ValidationError), match=r"alias|overlap"):
        validate_removal_conflicts(DEFAULT_RULES, plan, {})


@pytest.mark.parametrize("entry", ["verify", "private", "private_table"])
def test_active_directory_receipt_limit_at_consumer_entry(tmp_path, entry, capsys):
    from template_press.rebrand.cli import _press
    from template_press.rebrand.engine import build_plan

    repo = directory_repo(tmp_path)
    rules = load_rules(repo)
    table = (
        build_plan(repo, SOURCE, DEST, rules).table
        if entry == "private_table"
        else None
    )
    (repo / RECEIPT_REL).write_bytes(b"#" + b"x" * (16 * 1024 * 1024))
    before = (repo / "pyproject.toml").read_bytes()
    if entry == "verify":
        assert verify_command(["--target", str(repo), "--json"]) == 2
        assert "preflight failed" in capsys.readouterr().err
    else:
        outcome = _press(repo, SOURCE, DEST, rules, [], [], table=table)
        assert outcome.env_error is not None
        assert "directory receipt byte limit 16777216 exceeded" in outcome.env_error
    assert (repo / "pyproject.toml").read_bytes() == before
    assert (repo / "research/one.md").exists()


def test_direct_file_only_press_keeps_no_receipt_read(tmp_path, monkeypatch):
    import template_press.rebrand.remove as remove_module
    from template_press.rebrand.cli import _press

    repo = directory_repo(tmp_path)
    write_dir_rules(repo, '[[remove]]\nfile="research/one.md"\nreason="one file"\n')
    _commit(repo)

    def unexpected_read(*args, **kwargs):
        pytest.fail("direct file-only press added a receipt read")

    monkeypatch.setattr(remove_module, "read_receipt", unexpected_read)
    outcome = _press(repo, SOURCE, DEST, load_rules(repo), [], [])
    assert outcome.env_error is None
    assert not outcome.leaked
    assert not (repo / "research/one.md").exists()
    assert (repo / "research/sub/two.md").exists()


@pytest.mark.parametrize("state", ["dirty", "untracked"])
def test_verify_file_only_regular_members_keep_legacy_policy(tmp_path, state):
    repo = directory_repo(tmp_path)
    write_dir_rules(repo, '[[remove]]\nfile="research/one.md"\nreason="one file"\n')
    _commit(repo)
    if state == "untracked":
        _git(repo, "rm", "--cached", "research/one.md")
        _git(repo, "commit", "-q", "-m", "untrack one member")
    (repo / "research/one.md").write_text("private changed content\n", encoding="utf-8")
    assert verify_command(["--target", str(repo), "--json"]) == 0
    assert (repo / "research/one.md").read_text(
        encoding="utf-8"
    ) == "private changed content\n"


def carried_legacy_repo(
    tmp_path, *, file="RESEARCH/one.md", reason="legacy removal", directories=True
):
    repo = directory_repo(tmp_path)
    removal = (
        DIR_RULE
        if directories
        else '[[remove]]\nfile="research/one.md"\nreason="one file"\n'
    )
    write_dir_rules(
        repo,
        '[rules]\nextra_exclude_files=["state.txt"]\n'
        + removal
        + '[[reset]]\nfile="state.txt"\nstub="reset state\\n"\n',
    )
    (repo / "state.txt").write_text("original state\n", encoding="utf-8")
    _commit(repo)
    # This is deliberately the permissive historical file-only schema.
    import json

    text = (
        "[press]\nverified=true\n[[press.remove]]\n"
        + f"file={json.dumps(file)}\nreason={json.dumps(reason)}\n"
    )
    (repo / RECEIPT_REL).write_text(text, encoding="utf-8")
    return repo, {file: reason}


def press_with_legacy_entry(repo, tmp_path, entry, legacy):
    from template_press.rebrand.cli import _press
    from template_press.rebrand.engine import build_plan
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    if entry == "main":
        answers = write_answers_file(tmp_path, DEST)
        return main(
            [
                "--target",
                str(repo),
                "--config",
                str(answers),
                "--force",
                "--allow-dirty",
            ]
        )
    rules = load_rules(repo)
    plan = (
        plan_removals(
            repo,
            rules,
            source=SOURCE,
            receipt_text=read_receipt(repo),
            legacy_removed=legacy,
        )
        if "plan" in entry
        else None
    )
    table = build_plan(repo, SOURCE, DEST, rules).table if "table" in entry else None
    return _press(
        repo,
        SOURCE,
        DEST,
        rules,
        [],
        [(rules.reset[0], "reset state\n")],
        previously_removed=legacy,
        removal_plan=plan,
        table=table,
    )


@pytest.mark.parametrize(
    "entry", ["main", "private", "private_plan", "private_table", "private_plan_table"]
)
@pytest.mark.parametrize("bad_row", ["alias", "reason_limit"])
def test_carried_legacy_refused_before_any_mutation(tmp_path, entry, bad_row, capsys):
    file = "RESEARCH/one.md" if bad_row == "alias" else "retired.md"
    reason = "legacy removal" if bad_row == "alias" else "x" * 4097
    repo, legacy = carried_legacy_repo(tmp_path, file=file, reason=reason)
    before = {
        path: (repo / path).read_bytes()
        for path in (
            "README.md",
            "pyproject.toml",
            "state.txt",
            "research/one.md",
            "research/sub/two.md",
            "press/press-source.toml",
            RECEIPT_REL,
        )
    }
    result = press_with_legacy_entry(repo, tmp_path, entry, legacy)
    # These observations prove the known writer refusal precedes real mutation.
    assert (repo / "research/one.md").is_file()
    assert {path: (repo / path).read_bytes() for path in before} == before
    if entry == "main":
        assert result == 2
    else:
        assert result.env_error is not None
        assert result.renamed == []
    err = capsys.readouterr().err
    assert ("alias" if bad_row == "alias" else "4096") in err


@pytest.mark.parametrize(
    "entry", ["main", "private", "private_plan", "private_table", "private_plan_table"]
)
def test_nonconflicting_carried_legacy_emitted_once(tmp_path, entry):
    repo, legacy = carried_legacy_repo(tmp_path, file="retired.md")
    result = press_with_legacy_entry(repo, tmp_path, entry, legacy)
    assert (
        result == 0
        if entry == "main"
        else result.env_error is None and not result.leaked
    )
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["remove"] == [
        {"file": "research/one.md", "reason": "template research"},
        {"file": "research/sub/two.md", "reason": "template research"},
        {"file": "retired.md", "reason": "legacy removal"},
    ]
    assert receipt["press"]["counts"]["removed"] == 2
    assert (repo / "state.txt").read_text(encoding="utf-8") == "reset state\n"
    assert not (repo / "research").exists()


@pytest.mark.parametrize("entry", ["main", "private", "private_plan_table"])
def test_no_directory_legacy_alias_policy_is_unchanged(tmp_path, entry):
    repo, legacy = carried_legacy_repo(tmp_path, directories=False)
    result = press_with_legacy_entry(repo, tmp_path, entry, legacy)
    assert (
        result == 0
        if entry == "main"
        else result.env_error is None and not result.leaked
    )
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["remove"] == [
        {"file": "research/one.md", "reason": "one file"},
        {"file": "RESEARCH/one.md", "reason": "legacy removal"},
    ]
    assert "remove_dir" not in receipt["press"]
    assert (repo / "research/sub/two.md").is_file()


@pytest.mark.parametrize("active_directory", [False, True])
@pytest.mark.parametrize(
    "receipt_kind",
    ["valid", "non_utf8", "oversized", "malformed_toml", "inactive_history"],
)
def test_existing_receipt_refusal_uses_routed_read(
    tmp_path, active_directory, receipt_kind, monkeypatch, capsys
):
    import template_press.rebrand.remove as removal

    repo = directory_repo(tmp_path)
    if not active_directory:
        write_dir_rules(repo, "")
        _commit(repo)
    payloads = {
        "valid": b"[press]\nverified=true\n",
        "inactive_history": b"[press]\nremove_dirs_version=99\nremove_dir=[]\n",
        "non_utf8": b"[press]\n\xff\xfe",
        "oversized": b"#" + b"x" * (16 * 1024 * 1024),
        "malformed_toml": b"[press\nmalformed legacy receipt",
    }
    payload = payloads[receipt_kind]
    (repo / RECEIPT_REL).write_bytes(payload)
    original_read = removal.read_receipt
    bounds = []

    def checked_read(target, *, max_bytes=None):
        bounds.append(max_bytes)
        return original_read(target, max_bytes=max_bytes)

    monkeypatch.setattr(removal, "read_receipt", checked_read)
    answers = write_answers_file(tmp_path, DEST)
    before = (repo / "pyproject.toml").read_bytes()
    assert main(["--target", str(repo), "--config", str(answers)]) == 2
    captured = capsys.readouterr()
    expected = "--force"
    if receipt_kind == "non_utf8":
        expected = "UTF-8"
    elif receipt_kind == "oversized" and active_directory:
        expected = "directory receipt byte limit 16777216 exceeded"
    assert expected in captured.err
    assert captured.out == ""
    assert bounds == [16 * 1024 * 1024 if active_directory else None]
    assert (repo / RECEIPT_REL).read_bytes() == payload
    assert (repo / "pyproject.toml").read_bytes() == before
    assert (repo / "research/one.md").is_file()


@pytest.mark.parametrize("refusal", ["missing", "not_git", "dirty"])
def test_unrelated_precondition_refusal_does_not_load_rules(
    tmp_path, refusal, monkeypatch, capsys
):
    import template_press.rebrand.cli as cli_module

    if refusal == "dirty":
        repo = directory_repo(tmp_path)
        (repo / "research/one.md").write_text("unfinished\n", encoding="utf-8")
    else:
        repo = tmp_path / "target"
        if refusal == "not_git":
            repo.mkdir()

    def unexpected_rules(*args, **kwargs):
        pytest.fail("unrelated precondition refusal loaded rules")

    monkeypatch.setattr(cli_module, "load_selected_rules", unexpected_rules)
    monkeypatch.setattr(cli_module, "removal_receipt_text", unexpected_rules)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 2
    expected = {
        "missing": "does not exist",
        "not_git": "not a git repository",
        "dirty": "working tree is dirty",
    }
    assert expected[refusal] in capsys.readouterr().err


@pytest.mark.parametrize("active_directory", [False, True])
def test_force_receipt_selects_and_reads_once(tmp_path, active_directory, monkeypatch):
    import template_press.rebrand.cli as cli_module
    import template_press.rebrand.remove as removal

    repo, _legacy = carried_legacy_repo(
        tmp_path, file="retired.md", directories=active_directory
    )
    original_select = cli_module.load_selected_rules
    original_read = removal.read_receipt
    selections = []
    bounds = []

    def select_once(target):
        selections.append(target)
        return original_select(target)

    def read_once(target, *, max_bytes=None):
        bounds.append(max_bytes)
        return original_read(target, max_bytes=max_bytes)

    monkeypatch.setattr(cli_module, "load_selected_rules", select_once)
    monkeypatch.setattr(removal, "read_receipt", read_once)
    answers = write_answers_file(tmp_path, DEST)
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(answers),
                "--force",
                "--allow-dirty",
            ]
        )
        == 0
    )
    assert selections == [repo.resolve()]
    assert bounds == [16 * 1024 * 1024 if active_directory else None]
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert {"file": "retired.md", "reason": "legacy removal"} in receipt["press"][
        "remove"
    ]
