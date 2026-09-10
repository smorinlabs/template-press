"""Exact [[clean]] file selection: real Git and CLI preservation oracles."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from template_press import press_cli

from .conftest import _git, posix_only, requires_symlink
from .test_cli import write_source_config

PATHSPEC_MODES = (
    "GIT_GLOB_PATHSPECS",
    "GIT_ICASE_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
    "GIT_LITERAL_PATHSPECS",
)


def _declare(target: Path, paths: tuple[str, ...], ignored: str = "build/\n"):
    # The source helper stages the whole tree. Install ignore policy first so
    # owned ignored fixture nodes cannot accidentally become tracked inputs.
    (target / ".gitignore").write_text(ignored, encoding="utf-8")
    write_source_config(target)
    (target / "press/press-rules.toml").write_text(
        "".join("[[clean]]\npaths = " + json.dumps([path]) + "\n" for path in paths),
        encoding="utf-8",
    )
    _git(target, "add", "-f", ".gitignore", "press")


def _put(target: Path, relative: str, content: bytes):
    path = target / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _run(target: Path, show: bool, capsys):
    code = press_cli.main(
        ["clean", "--target", str(target)] + (["--show"] if show else [])
    )
    output = capsys.readouterr()
    return code, output


@pytest.fixture
def clean_processes(monkeypatch):
    """Observe real subprocesses without replacing their filesystem behavior."""
    calls = []
    real_run = subprocess.run

    def record(argv, *args, **kwargs):
        if "clean" in argv:
            calls.append(tuple(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    return calls


def _preserved_pair(target: Path):
    assert (target / "build/two.txt").read_bytes() == b"unselected sibling\n"
    assert (target / "build").is_dir()


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    ("selected", "ignored"),
    [
        ("build/one.txt", "build/\n"),
        ("build/one.txt", "build/*.txt\n"),
        ("build/deep/one.txt", "build/\n"),
        ("build/deep/one.txt", "build/deep/\n"),
        ("build/{repo_name}.txt", "build/\n"),
        ("build/a [b] # !.txt", "build/\n"),
        ("build/-leading.txt", "build/\n"),
        ("build/café.txt", "build/\n"),
    ],
)
def test_exact_file_preserves_sibling_and_parent(
    src_target, capsys, clean_processes, show, selected, ignored
):
    _declare(src_target, (selected,), ignored)
    rendered = selected.replace("{repo_name}", "demo-widget")
    chosen = _put(src_target, rendered, b"selected file\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    _put(src_target, "elsewhere/keep.txt", b"outside declaration\n")
    parent = chosen.parent

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert parent.is_dir()
    assert (src_target / "elsewhere/keep.txt").read_bytes() == b"outside declaration\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"selected file\n"
        assert rendered in output.out
    assert clean_processes == [], "regular files must never be sent to git clean"


@posix_only
@pytest.mark.parametrize("show", [False, True])
def test_literal_wildcard_file_is_not_a_pattern(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/a*?.txt",))
    chosen = _put(src_target, "build/a*?.txt", b"literal wildcard filename\n")
    sibling = _put(src_target, "build/abc.txt", b"pattern-matching sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert sibling.read_bytes() == b"pattern-matching sibling\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"literal wildcard filename\n"
    assert (src_target / "build").is_dir()
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "kind", ["missing-leaf", "missing-parent", "tracked", "visible"]
)
def test_file_noops_never_delegate_empty_or_missing_pathspecs(
    src_target, capsys, clean_processes, show, kind
):
    selected = "build/absent/one.txt" if kind == "missing-parent" else "build/one.txt"
    _declare(
        src_target, (selected,), "build/*.tmp\n" if kind == "visible" else "build/\n"
    )
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    outside = _put(src_target, "unrelated.tmp", b"ignored outside declaration\n")
    (src_target / ".git/info/exclude").write_bytes(b"*.tmp\n")
    chosen = src_target / selected
    if kind in ("tracked", "visible"):
        chosen.write_bytes(b"selected but protected\n")
    if kind == "tracked":
        _git(src_target, "add", "-f", selected)

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert outside.read_bytes() == b"ignored outside declaration\n"
    if kind in ("tracked", "visible"):
        assert chosen.read_bytes() == b"selected but protected\n"
    else:
        assert not chosen.exists()
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_multiple_files_duplicates_and_disjoint_directory(
    src_target, capsys, clean_processes, show, mixed
):
    paths = ("build/one.txt", "cache/one.txt", "build/one.txt")
    if mixed:
        paths += ("discard", "discard/child", "discard")
    _declare(src_target, paths, "build/\ncache/\ndiscard/\n")
    chosen = _put(src_target, "build/one.txt", b"first selection\n")
    second = _put(src_target, "cache/one.txt", b"second selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    cache_sibling = _put(src_target, "cache/two.txt", b"second unselected sibling\n")
    directory_child = _put(
        src_target, "discard/child/one.txt", b"directory selection\n"
    )

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert cache_sibling.read_bytes() == b"second unselected sibling\n"
    assert (src_target / "cache").is_dir()
    assert chosen.exists() == show
    assert second.exists() == show
    if show:
        assert chosen.read_bytes() == b"first selection\n"
        assert second.read_bytes() == b"second selection\n"
    if mixed:
        assert directory_child.exists() == show
        assert len(clean_processes) == 1
        command = clean_processes[0]
        assert command[command.index("--") + 1 :] == ("discard",)
    else:
        assert directory_child.read_bytes() == b"directory selection\n"
        assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
def test_selected_directory_explicitly_authorizes_its_selected_file(
    src_target, capsys, clean_processes, monkeypatch, show
):
    _declare(src_target, ("build/one.txt", "build", "build/deep"))
    chosen = _put(src_target, "build/one.txt", b"selected descendant\n")
    sibling = _put(src_target, "build/two.txt", b"authorized by parent declaration\n")
    _put(src_target, "build/deep/three.txt", b"redundant descendant directory\n")

    unlinks = []
    real_unlink = os.unlink

    def observe_unlink(path, *args, **kwargs):
        unlinks.append(path)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", observe_unlink)
    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert unlinks == [], "selected parent must cover the separate file action"
    assert chosen.exists() == show
    assert sibling.exists() == show
    if show:
        assert chosen.read_bytes() == b"selected descendant\n"
        assert sibling.read_bytes() == b"authorized by parent declaration\n"
    assert len(clean_processes) == 1
    command = clean_processes[0]
    assert command[command.index("--") + 1 :] == ("build",)


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("variable", PATHSPEC_MODES)
def test_inherited_pathspec_modes_cannot_break_file_and_directory_selection(
    src_target, capsys, clean_processes, monkeypatch, show, variable
):
    _declare(src_target, ("build/a[b].txt", "discard"), "build/\ndiscard/\n")
    chosen = _put(src_target, "build/a[b].txt", b"literal brackets\n")
    sibling = _put(src_target, "build/ab.txt", b"glob-matching sibling\n")
    directory_child = _put(src_target, "discard/one.txt", b"directory contents\n")
    monkeypatch.setenv(variable, "1")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert sibling.read_bytes() == b"glob-matching sibling\n"
    assert chosen.exists() == show
    assert directory_child.exists() == show
    if show:
        assert chosen.read_bytes() == b"literal brackets\n"
        assert directory_child.read_bytes() == b"directory contents\n"
    assert len(clean_processes) == 1
    command = clean_processes[0]
    assert command[command.index("--") + 1 :] == ("discard",)


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("tracked", [False, True])
def test_case_aliases_deduplicate_one_entry_and_preserve_tracked_file(
    src_target, capsys, clean_processes, show, tracked
):
    _declare(src_target, ("build/one.txt", "BUILD/ONE.TXT"))
    chosen = _put(src_target, "build/one.txt", b"same filesystem entry\n")
    alias = src_target / "BUILD/ONE.TXT"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem path alias")
    assert os.path.samefile(chosen, alias)
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    _git(src_target, "config", "core.ignoreCase", "true")
    if tracked:
        _git(src_target, "add", "-f", "build/one.txt")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert chosen.exists() == (show or tracked)
    if show or tracked:
        assert chosen.read_bytes() == b"same filesystem entry\n"
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("location", ["relative", "absolute", "info"])
def test_file_eligibility_uses_configured_git_excludes(
    src_target, tmp_path, capsys, clean_processes, show, location
):
    _declare(src_target, ("build/one.txt",), "")
    if location == "info":
        (src_target / ".git/info/exclude").write_bytes(b"build/\n")
    else:
        policy = (
            src_target / "policy.exclude"
            if location == "relative"
            else tmp_path / "outside.exclude"
        )
        policy.write_bytes(b"build/\n")
        _git(
            src_target,
            "config",
            "core.excludesFile",
            policy.name if location == "relative" else str(policy),
        )
    chosen = _put(src_target, "build/one.txt", b"ignored by configured policy\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"ignored by configured policy\n"
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("kind", ["include", "control", "excludes", "missing-excludes"])
def test_exact_file_input_guards_refuse_entire_batch_before_cleanup(
    src_target, capsys, clean_processes, show, kind
):
    relative = "press/press-receipt.toml" if kind == "control" else "build/policy"
    _declare(
        src_target, ("build/one.txt", relative), "build/\npress/press-receipt.toml\n"
    )
    chosen = _put(src_target, "build/one.txt", b"valid earlier selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    policy = src_target / relative
    if kind != "missing-excludes":
        policy.write_bytes(b"# protected input\n")
    if kind == "include":
        _git(src_target, "config", "includeIf.onbranch:inactive.path", str(policy))
    elif kind in ("excludes", "missing-excludes"):
        _git(src_target, "config", "core.excludesFile", str(policy))

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert "overlaps [[clean]] path" in output.err
    assert "run:" not in output.out and "preview:" not in output.out
    assert chosen.read_bytes() == b"valid earlier selection\n"
    _preserved_pair(src_target)
    if kind != "missing-excludes":
        assert policy.read_bytes() == b"# protected input\n"
    else:
        assert not policy.exists()
    assert clean_processes == []


@pytest.mark.parametrize("selected", ["build/one.txt", "build/missing.txt"])
def test_legacy_root_git_inverse_control_breaks_sibling_preservation(
    src_target, selected
):
    """The production preservation oracle rejects the previous Git-only route."""
    _declare(src_target, (selected,))
    _put(src_target, "build/one.txt", b"selected file\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    _preserved_pair(src_target)

    _git(src_target, "--literal-pathspecs", "clean", "-fdX", "--", selected)

    assert not (src_target / "build").exists()
    with pytest.raises((AssertionError, FileNotFoundError)):
        _preserved_pair(src_target)


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "relative",
    [
        "press/press-source.toml",
        "press/press-rules.toml",
        "press/press-receipt.toml",
        "press/press-answers.toml",
    ],
)
def test_every_exact_press_control_refuses_when_ignored_untracked(
    src_target, capsys, clean_processes, show, relative
):
    _declare(src_target, ("build/one.txt", relative), f"build/\n{relative}\n")
    if not (src_target / relative).exists():
        (src_target / relative).write_bytes(b"# protected control\n")
    else:
        _git(src_target, "rm", "--cached", "--", relative)
    original = (src_target / relative).read_bytes()
    chosen = _put(src_target, "build/one.txt", b"valid earlier selection\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert "press-owned control file" in output.err
    assert "run:" not in output.out and "preview:" not in output.out
    assert chosen.read_bytes() == b"valid earlier selection\n"
    assert (src_target / relative).read_bytes() == original
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("kind", ["include", "control"])
@pytest.mark.parametrize("protection", ["tracked", "nonignored", "disjoint"])
def test_exact_file_cleanup_conjoins_positive_input_guards(
    src_target, capsys, clean_processes, show, kind, protection
):
    relative = "press/press-receipt.toml" if kind == "control" else "policy.include"
    paths = (
        ("build/one.txt",) if protection == "disjoint" else ("build/one.txt", relative)
    )
    ignored = "build/\n" + ("" if protection == "nonignored" else f"{relative}\n")
    _declare(src_target, paths, ignored)
    policy = _put(src_target, relative, b"# retained input\n")
    if protection == "tracked":
        _git(src_target, "add", "-f", relative)
    if kind == "include":
        _git(src_target, "config", "includeIf.onbranch:main.path", str(policy))
    chosen = _put(src_target, "build/one.txt", b"selected file\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert policy.read_bytes() == b"# retained input\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"selected file\n"
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
def test_later_directory_with_ignored_ancestor_refuses_before_exact_file_removal(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("cache/one.txt", "build/deep"), "build/\ncache/\n")
    chosen = _put(src_target, "cache/one.txt", b"valid first selection\n")
    nested = _put(src_target, "build/deep/one.txt", b"unsafe directory selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert "run:" not in output.out and "preview:" not in output.out
    assert chosen.read_bytes() == b"valid first selection\n"
    assert nested.read_bytes() == b"unsafe directory selection\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@posix_only
@pytest.mark.parametrize("show", [False, True])
def test_exact_file_hardlink_name_is_independent_of_tracked_name(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/one.txt",))
    tracked = _put(src_target, "tracked.txt", b"hardlinked bytes retained\n")
    _git(src_target, "add", "tracked.txt")
    chosen = src_target / "build/one.txt"
    chosen.parent.mkdir()
    os.link(tracked, chosen)
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    _preserved_pair(src_target)
    assert tracked.read_bytes() == b"hardlinked bytes retained\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"hardlinked bytes retained\n"
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "relative", ["build/one.txt", 'build/a "quote".txt', "build/a 'quote'.txt"]
)
def test_exact_file_action_output_is_literal_and_truthful(
    src_target, capsys, clean_processes, show, relative
):
    if os.name == "nt" and '"' in relative:
        pytest.skip("Win32 does not permit double quotes in filenames")
    _declare(src_target, (relative,))
    chosen = _put(src_target, relative, b"selected output fixture\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    verb = "would remove file" if show else "removed file"
    assert output.out == f"{verb}: {relative!r}\n"
    assert output.err == ""
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"selected output fixture\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
def test_missing_only_batch_has_empty_stdout(src_target, capsys, clean_processes, show):
    _declare(src_target, ("build/missing.txt",))
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert output.out == ""
    assert output.err == ""
    _preserved_pair(src_target)
    assert clean_processes == []


@requires_symlink
@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "selection", ["file", "directory", "missing", "covered-directory", "leaf"]
)
def test_every_declaration_refuses_symlink_traversal_before_any_cleanup(
    src_target, tmp_path, capsys, clean_processes, show, selection
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "one.txt").write_bytes(b"outside symlink target\n")
    (outside / "directory").mkdir()
    (outside / "directory/keep.txt").write_bytes(b"outside nested sentinel\n")
    (src_target / "build").mkdir()
    link = src_target / "build/link"
    link.symlink_to(outside, target_is_directory=True)
    suffix = {
        "file": "/one.txt",
        "directory": "/directory",
        "missing": "/missing",
        "covered-directory": "/directory",
        "leaf": "",
    }[selection]
    paths = ("cache/one.txt", "build/link" + suffix)
    if selection == "covered-directory":
        paths += ("build",)
    _declare(src_target, paths, "build/\ncache/\n")
    first = _put(src_target, "cache/one.txt", b"earlier valid selection\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert output.out == ""
    assert first.read_bytes() == b"earlier valid selection\n"
    assert (outside / "one.txt").read_bytes() == b"outside symlink target\n"
    assert (outside / "directory/keep.txt").read_bytes() == b"outside nested sentinel\n"
    assert link.is_symlink()
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize(
    "selection", ["file", "directory", "missing", "covered-directory"]
)
def test_every_declaration_refuses_nested_repository_traversal(
    src_target, capsys, clean_processes, show, selection
):
    nested = src_target / "build/nested"
    nested.mkdir(parents=True)
    _git(nested, "init", "-q", "-b", "main")
    (nested / "one.txt").write_bytes(b"nested repository file\n")
    (nested / "directory").mkdir()
    (nested / "directory/keep.txt").write_bytes(b"nested repository child\n")
    suffix = {
        "file": "/one.txt",
        "directory": "/directory",
        "missing": "/missing",
        "covered-directory": "/directory",
    }[selection]
    paths = ("cache/one.txt", "build/nested" + suffix)
    if selection == "covered-directory":
        paths += ("build",)
    _declare(src_target, paths, "build/\ncache/\n")
    first = _put(src_target, "cache/one.txt", b"earlier valid selection\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert output.out == ""
    assert first.read_bytes() == b"earlier valid selection\n"
    assert (nested / "one.txt").read_bytes() == b"nested repository file\n"
    assert (nested / "directory/keep.txt").read_bytes() == b"nested repository child\n"
    assert (nested / ".git").is_dir()
    assert clean_processes == []


@pytest.mark.skipif(os.name != "nt", reason="native Windows junction behavior")
@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("selection", ["leaf", "file", "directory"])
def test_windows_junction_leaf_and_ancestors_refuse_before_cleanup(
    src_target, tmp_path, capsys, clean_processes, show, selection
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "one.txt").write_bytes(b"outside junction target\n")
    (outside / "directory").mkdir()
    (outside / "directory/keep.txt").write_bytes(b"outside junction child\n")
    junction = src_target / "vendor"
    # Fixed Windows command with exclusively owned temporary paths.
    subprocess.run(  # noqa: S603
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        assert junction.is_junction()
        suffix = {"leaf": "", "file": "/one.txt", "directory": "/directory"}[selection]
        _declare(src_target, ("cache/one.txt", "vendor" + suffix), "vendor/\ncache/\n")
        first = _put(src_target, "cache/one.txt", b"earlier valid selection\n")

        code, output = _run(src_target, show, capsys)

        assert code == 2, output
        assert output.out == ""
        assert first.read_bytes() == b"earlier valid selection\n"
        assert (outside / "one.txt").read_bytes() == b"outside junction target\n"
        assert (
            outside / "directory/keep.txt"
        ).read_bytes() == b"outside junction child\n"
        assert junction.is_junction()
        assert clean_processes == []
    finally:
        if junction.is_junction():
            junction.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="native Windows read-only unlink behavior")
@pytest.mark.parametrize("show", [False, True])
def test_windows_readonly_exact_file_preserves_writable_sibling(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/one.txt",))
    chosen = _put(src_target, "build/one.txt", b"read-only selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    chosen.chmod(stat.S_IREAD)
    try:
        assert chosen.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY

        code, output = _run(src_target, show, capsys)

        assert code == 0, output
        _preserved_pair(src_target)
        assert chosen.exists() == show
        if show:
            assert chosen.read_bytes() == b"read-only selection\n"
            assert chosen.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        assert clean_processes == []
    finally:
        if chosen.exists():
            chosen.chmod(stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="native Windows read-only retry behavior")
def test_windows_readonly_retry_failure_stops_remaining_cleanup(
    src_target, capsys, clean_processes, monkeypatch
):
    _declare(
        src_target,
        ("build/one.txt", "cache/one.txt", "discard"),
        "build/\ncache/\ndiscard/\n",
    )
    chosen = _put(src_target, "build/one.txt", b"retry fails selection\n")
    second = _put(src_target, "cache/one.txt", b"later exact selection\n")
    directory = _put(src_target, "discard/one.txt", b"later directory selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    chosen.chmod(stat.S_IREAD)
    real_unlink = os.unlink
    attempts = []

    def fail_retry(path, *args, **kwargs):
        if Path(path) == chosen:
            attempts.append(path)
            if len(attempts) == 2:
                raise PermissionError("controlled second unlink refusal")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_retry)
    try:
        code, output = _run(src_target, False, capsys)

        assert code == 1, output
        assert len(attempts) == 2
        assert "controlled second unlink refusal" in output.err
        assert "earlier cleanup may have completed" in output.err
        assert "removed file:" not in output.out
        assert chosen.read_bytes() == b"retry fails selection\n"
        assert second.read_bytes() == b"later exact selection\n"
        assert directory.read_bytes() == b"later directory selection\n"
        _preserved_pair(src_target)
        assert clean_processes == []
    finally:
        if chosen.exists():
            chosen.chmod(stat.S_IWRITE)


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("ignore_case", ["true", "false"])
def test_initial_tracked_uppercase_only_alias_is_a_silent_noop(
    src_target, capsys, clean_processes, show, ignore_case
):
    _declare(src_target, ("build/ONE.TXT",))
    chosen = _put(src_target, "build/one.txt", b"tracked original spelling\n")
    alias = src_target / "build/ONE.TXT"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem path alias")
    assert os.path.samefile(chosen, alias)
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    _git(src_target, "config", "core.ignoreCase", ignore_case)
    _git(src_target, "add", "-f", "build/one.txt")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert output.out == ""
    assert chosen.read_bytes() == b"tracked original spelling\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
def test_nondirectory_ancestor_refuses_before_any_cleanup(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/one.txt", "build/regular/child"))
    chosen = _put(src_target, "build/one.txt", b"earlier valid selection\n")
    ancestor = _put(
        src_target, "build/regular", b"regular ancestor cannot be traversed\n"
    )
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert output.out == ""
    assert chosen.read_bytes() == b"earlier valid selection\n"
    assert ancestor.read_bytes() == b"regular ancestor cannot be traversed\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("ignore_case", ["true", "false"])
@pytest.mark.parametrize("prior_unlink", [False, True])
def test_late_tracking_under_case_alias_preserves_newly_tracked_entry(
    src_target, capsys, clean_processes, monkeypatch, ignore_case, prior_unlink
):
    paths = ("build/ONE.TXT",)
    if prior_unlink:
        paths = ("cache/one.txt", *paths)
    _declare(src_target, paths, "build/\ncache/\n")
    chosen = _put(src_target, "build/one.txt", b"newly tracked original spelling\n")
    alias = src_target / "build/ONE.TXT"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem path alias")
    assert os.path.samefile(chosen, alias)
    first = _put(src_target, "cache/one.txt", b"earlier exact selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    _git(src_target, "config", "core.ignoreCase", ignore_case)
    real_run = subprocess.run
    real_unlink = os.unlink
    tracked_late = []

    def track_now():
        _git(src_target, "add", "-f", "build/one.txt")
        tracked_late.append(True)

    def classify_then_track(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if (
            not prior_unlink
            and not tracked_late
            and "check-ignore" in argv
            and "--no-index" not in argv
            and b"build/ONE.TXT\0" in kwargs.get("input", b"")
        ):
            track_now()
        return result

    def unlink_then_track(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if prior_unlink and Path(path) == first:
            track_now()
        return result

    monkeypatch.setattr(subprocess, "run", classify_then_track)
    monkeypatch.setattr(os, "unlink", unlink_then_track)

    code, output = _run(src_target, False, capsys)

    assert tracked_late == [True], "controlled late tracking boundary must execute"
    assert code == (1 if prior_unlink else 2), output
    assert chosen.read_bytes() == b"newly tracked original spelling\n"
    _preserved_pair(src_target)
    assert first.exists() != prior_unlink
    if not prior_unlink:
        assert first.read_bytes() == b"earlier exact selection\n"
        assert output.out == ""
    else:
        assert "earlier cleanup may have completed" in output.err
    assert clean_processes == []


def test_git_launch_failure_after_exact_unlink_reports_partial_cleanup(
    src_target, capsys, monkeypatch
):
    _declare(src_target, ("build/one.txt", "discard"), "build/\ndiscard/\n")
    chosen = _put(src_target, "build/one.txt", b"successful earlier selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    directory_child = _put(src_target, "discard/one.txt", b"not reached by Git\n")
    real_run = subprocess.run

    def refuse_git_clean_launch(argv, *args, **kwargs):
        if "clean" in argv:
            raise FileNotFoundError("controlled Git launch failure")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", refuse_git_clean_launch)

    code, output = _run(src_target, False, capsys)

    assert code == 1, output
    assert not chosen.exists()
    _preserved_pair(src_target)
    assert directory_child.read_bytes() == b"not reached by Git\n"
    assert "controlled Git launch failure" in output.err
    assert "earlier cleanup may have completed" in output.err
    assert "removed file: 'build/one.txt'\n" in output.out


def test_first_exact_unlink_failure_stops_remaining_cleanup(
    src_target, capsys, clean_processes, monkeypatch
):
    _declare(
        src_target,
        ("build/one.txt", "cache/one.txt", "discard"),
        "build/\ncache/\ndiscard/\n",
    )
    chosen = _put(src_target, "build/one.txt", b"first unlink refused\n")
    second = _put(src_target, "cache/one.txt", b"later exact selection\n")
    directory = _put(src_target, "discard/one.txt", b"later directory selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_unlink = os.unlink
    attempts = []

    def refuse_first_unlink(path, *args, **kwargs):
        if Path(path) == chosen:
            attempts.append(path)
            raise PermissionError("controlled unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refuse_first_unlink)

    code, output = _run(src_target, False, capsys)

    assert code == 1, output
    assert len(attempts) == 1
    assert "controlled unlink failure" in output.err
    assert "earlier cleanup may have completed" in output.err
    assert "removed file:" not in output.out
    assert chosen.read_bytes() == b"first unlink refused\n"
    assert second.read_bytes() == b"later exact selection\n"
    assert directory.read_bytes() == b"later directory selection\n"
    _preserved_pair(src_target)
    assert clean_processes == []


def test_execute_clean_forwards_literal_stdin_to_real_child(src_target):
    from template_press.rebrand.clean import execute_clean

    payload = b"path with spaces\0literal[*?]\0"
    result = execute_clean(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ],
        src_target,
        stdin=payload,
    )
    assert result.returncode == 0
    assert result.stdout == b"path with spaces\0literal[*?]\0"
    assert result.stderr == b""


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (0, b""),
        (0, b"build/one.txt"),
        (0, b"build/one.txt\0build/one.txt\0"),
        (0, b"unselected.txt\0"),
        (1, b"build/one.txt\0"),
        (128, b""),
    ],
)
@pytest.mark.parametrize("show", [False, True])
def test_malformed_ignore_classification_refuses_before_cleanup(
    src_target, capsys, clean_processes, monkeypatch, returncode, stdout, show
):
    _declare(src_target, ("build/one.txt",))
    chosen = _put(src_target, "build/one.txt", b"selected file\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    queries = []

    def corrupt_classification(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if "check-ignore" in argv and "--no-index" not in argv:
            queries.append(kwargs["input"])
            return subprocess.CompletedProcess(
                argv, returncode, stdout=stdout, stderr=b""
            )
        return result

    monkeypatch.setattr(subprocess, "run", corrupt_classification)

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert queries == [b"build/one.txt\0"]
    assert output.out == ""
    assert chosen.read_bytes() == b"selected file\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [(128, b""), (0, b"README.md"), (0, b"../outside\0"), (0, b"\0")],
)
def test_malformed_live_index_refuses_before_first_unlink(
    src_target, capsys, clean_processes, monkeypatch, returncode, stdout
):
    _declare(src_target, ("build/one.txt",))
    chosen = _put(src_target, "build/one.txt", b"selected file\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    queries = []

    def corrupt_live_index(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if "ls-files" in argv and "--cached" in argv and "--others" not in argv:
            queries.append(argv)
            return subprocess.CompletedProcess(
                argv, returncode, stdout=stdout, stderr=b""
            )
        return result

    monkeypatch.setattr(subprocess, "run", corrupt_live_index)

    code, output = _run(src_target, False, capsys)

    assert code == 2, output
    assert len(queries) == 1
    assert output.out == ""
    assert chosen.read_bytes() == b"selected file\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize(
    "change", ["contents", "entry", "directory", "parent", "metadata-error"]
)
def test_changed_frozen_file_or_parent_refuses_before_first_unlink(
    src_target, capsys, clean_processes, monkeypatch, change
):
    _declare(src_target, ("build/one.txt",))
    chosen = _put(src_target, "build/one.txt", b"original selected bytes\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    real_lstat = Path.lstat
    changed = []

    def denied_metadata(path, *args, **kwargs):
        if path == chosen:
            raise PermissionError("controlled selected metadata error")
        return real_lstat(path, *args, **kwargs)

    def mutate_after_plan_query(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if not changed and "check-ignore" in argv and "--no-index" not in argv:
            changed.append(True)
            if change == "contents":
                chosen.write_bytes(b"replacement selected bytes with different size\n")
            elif change == "entry":
                chosen.rename(src_target / "build/original.txt")
                chosen.write_bytes(b"replacement entry\n")
            elif change == "directory":
                chosen.unlink()
                chosen.mkdir()
                (chosen / "keep.txt").write_bytes(b"replacement directory child\n")
            elif change == "parent":
                chosen.parent.rename(src_target / "saved-build")
                chosen.parent.mkdir()
                chosen.write_bytes(b"replacement parent child\n")
            else:
                monkeypatch.setattr(Path, "lstat", denied_metadata)
        return result

    monkeypatch.setattr(subprocess, "run", mutate_after_plan_query)

    code, output = _run(src_target, False, capsys)

    assert changed == [True]
    assert code == 2, output
    assert output.out == ""
    if change == "directory":
        assert (chosen / "keep.txt").read_bytes() == b"replacement directory child\n"
    elif change == "contents":
        assert (
            chosen.read_bytes() == b"replacement selected bytes with different size\n"
        )
    elif change == "entry":
        assert chosen.read_bytes() == b"replacement entry\n"
        assert (
            src_target / "build/original.txt"
        ).read_bytes() == b"original selected bytes\n"
    elif change == "parent":
        assert chosen.read_bytes() == b"replacement parent child\n"
        assert (
            src_target / "saved-build/one.txt"
        ).read_bytes() == b"original selected bytes\n"
        assert (
            src_target / "saved-build/two.txt"
        ).read_bytes() == b"unselected sibling\n"
    else:
        assert chosen.read_bytes() == b"original selected bytes\n"
    if change != "parent":
        _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("prior_unlink", [False, True])
def test_live_ignore_change_stops_and_preserves_newly_visible_file(
    src_target, capsys, clean_processes, monkeypatch, prior_unlink
):
    paths = ("build/one.txt",)
    if prior_unlink:
        paths = ("cache/one.txt", *paths)
    _declare(src_target, paths, "build/\ncache/\n")
    chosen = _put(src_target, "build/one.txt", b"newly visible selected file\n")
    first = _put(src_target, "cache/one.txt", b"earlier exact selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    real_unlink = os.unlink
    changed = []

    def change_policy():
        (src_target / ".gitignore").write_bytes(b"# all fixture files now visible\n")
        changed.append(True)

    def query_then_change(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if (
            not prior_unlink
            and not changed
            and "check-ignore" in argv
            and "--no-index" not in argv
        ):
            change_policy()
        return result

    def unlink_then_change(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if prior_unlink and Path(path) == first:
            change_policy()
        return result

    monkeypatch.setattr(subprocess, "run", query_then_change)
    monkeypatch.setattr(os, "unlink", unlink_then_change)

    code, output = _run(src_target, False, capsys)

    assert changed == [True]
    assert code == (1 if prior_unlink else 2), output
    assert chosen.read_bytes() == b"newly visible selected file\n"
    _preserved_pair(src_target)
    assert first.exists() != prior_unlink
    if prior_unlink:
        assert "earlier cleanup may have completed" in output.err
    else:
        assert first.read_bytes() == b"earlier exact selection\n"
        assert output.out == ""
    assert clean_processes == []


@posix_only
@pytest.mark.parametrize("show", [False, True])
def test_two_selected_hardlink_names_survive_each_others_metadata_changes(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/one.txt", "build/second.txt"))
    chosen = _put(src_target, "build/one.txt", b"shared selected bytes\n")
    second = src_target / "build/second.txt"
    os.link(chosen, second)
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert chosen.exists() == show
    assert second.exists() == show
    if show:
        assert chosen.read_bytes() == b"shared selected bytes\n"
        assert second.read_bytes() == b"shared selected bytes\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@requires_symlink
@pytest.mark.parametrize("tracked", [False, True])
def test_symlink_leaf_is_noop_only_when_tracked(
    src_target, capsys, clean_processes, tracked
):
    _declare(src_target, ("build/link",))
    destination = _put(
        src_target, "destination.txt", b"symlink destination preserved\n"
    )
    (src_target / "build").mkdir()
    link = src_target / "build/link"
    link.symlink_to(destination)
    if tracked:
        _git(src_target, "add", "-f", "build/link")

    code, output = _run(src_target, False, capsys)

    assert code == (0 if tracked else 2), output
    assert output.out == ""
    assert destination.read_bytes() == b"symlink destination preserved\n"
    assert link.is_symlink()
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
def test_default_global_ignore_does_not_authorize_exact_file_cleanup(
    src_target, tmp_path, capsys, clean_processes, monkeypatch, show
):
    _declare(
        src_target,
        ("build/global.tmp", "build/repository.tmp"),
        "build/repository.tmp\n",
    )
    config = tmp_path / "xdg/git"
    config.mkdir(parents=True)
    (config / "ignore").write_bytes(b"build/global.tmp\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    global_only = _put(
        src_target, "build/global.tmp", b"global-default-only ignored file\n"
    )
    chosen = _put(src_target, "build/repository.tmp", b"repository ignored selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert global_only.read_bytes() == b"global-default-only ignored file\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"repository ignored selection\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@posix_only
@pytest.mark.parametrize("show", [False, True])
def test_untracked_fifo_selection_refuses_before_any_cleanup(
    src_target, capsys, clean_processes, show
):
    _declare(src_target, ("build/one.txt", "build/pipe"))
    chosen = _put(src_target, "build/one.txt", b"earlier valid selection\n")
    fifo = src_target / "build/pipe"
    os.mkfifo(fifo)
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert output.out == ""
    assert chosen.read_bytes() == b"earlier valid selection\n"
    assert stat.S_ISFIFO(fifo.lstat().st_mode)
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("marker", ["gitfile", "bare", "common"])
def test_exact_file_refuses_finite_repository_metadata_boundary(
    src_target, capsys, clean_processes, show, marker
):
    _declare(
        src_target, ("cache/one.txt", "build/repository/one.txt"), "build/\ncache/\n"
    )
    chosen = _put(src_target, "build/repository/one.txt", b"nested selected bytes\n")
    first = _put(src_target, "cache/one.txt", b"earlier valid selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    repository = chosen.parent
    if marker == "gitfile":
        (repository / ".git").write_bytes(b"gitdir: never-open-this-child\n")
    else:
        (repository / "HEAD").write_bytes(b"ref: refs/heads/main\n")
        if marker == "bare":
            (repository / "objects").mkdir()
            (repository / "refs").mkdir()
        else:
            (repository / "commondir").write_bytes(b"never-open-this-common-dir\n")

    code, output = _run(src_target, show, capsys)

    assert code == 2, output
    assert output.out == ""
    assert chosen.read_bytes() == b"nested selected bytes\n"
    assert first.read_bytes() == b"earlier valid selection\n"
    _preserved_pair(src_target)
    assert clean_processes == []


UNICODE_ALIASES = ("build/cafe\u0301.txt", "build/CAFE\u0301.TXT")


def _require_unicode_alias(target: Path, selected: str) -> Path:
    stored = _put(
        target,
        "build/caf\u00e9.txt",  # codespell:ignore caf
        b"normalization alias bytes\n",
    )
    alias = target / selected
    if not alias.exists():
        pytest.skip("requires actual Unicode-normalization filesystem aliases")
    assert os.path.samefile(stored, alias)
    assert len(list(stored.parent.iterdir())) == 1
    return stored


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("selected", UNICODE_ALIASES)
def test_unicode_normalization_tracked_alias_is_silent_noop(
    src_target, capsys, clean_processes, show, selected
):
    _declare(src_target, (selected,))
    stored = _require_unicode_alias(src_target, selected)
    _git(src_target, "add", "-f", "build/caf\u00e9.txt")  # codespell:ignore caf
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.read_bytes() == b"normalization alias bytes\n"
    _preserved_pair(src_target)
    assert output.out == ""
    assert output.err == ""
    assert clean_processes == []


@pytest.mark.parametrize("selected", UNICODE_ALIASES)
@pytest.mark.parametrize("prior_unlink", [False, True])
def test_unicode_normalization_late_tracking_refuses_before_alias_unlink(
    src_target, capsys, clean_processes, monkeypatch, selected, prior_unlink
):
    paths = ("cache/one.txt", selected) if prior_unlink else (selected,)
    _declare(src_target, paths, "build/\ncache/\n")
    stored = _require_unicode_alias(src_target, selected)
    first = _put(src_target, "cache/one.txt", b"earlier exact selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    real_unlink = os.unlink
    tracked_late = []

    def track_now():
        _git(src_target, "add", "-f", "build/caf\u00e9.txt")  # codespell:ignore caf
        tracked_late.append(True)

    def query_then_track(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if (
            not prior_unlink
            and not tracked_late
            and "check-ignore" in argv
            and "--no-index" not in argv
            and selected.encode("utf-8") + b"\0" in kwargs.get("input", b"")
        ):
            track_now()
        return result

    def unlink_then_track(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if prior_unlink and Path(path) == first:
            track_now()
        return result

    monkeypatch.setattr(subprocess, "run", query_then_track)
    monkeypatch.setattr(os, "unlink", unlink_then_track)

    code, output = _run(src_target, False, capsys)

    assert tracked_late == [True]
    assert code == (1 if prior_unlink else 2), output
    assert stored.read_bytes() == b"normalization alias bytes\n"
    _preserved_pair(src_target)
    assert first.exists() != prior_unlink
    if prior_unlink:
        assert "earlier cleanup may have completed" in output.err
    else:
        assert first.read_bytes() == b"earlier exact selection\n"
        assert output.out == ""
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("selected", UNICODE_ALIASES)
def test_unicode_normalization_duplicate_alias_has_one_exact_action(
    src_target, capsys, clean_processes, show, selected
):
    _declare(src_target, (selected, "build/caf\u00e9.txt"))  # codespell:ignore caf
    stored = _require_unicode_alias(src_target, selected)
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.exists() == show
    if show:
        assert stored.read_bytes() == b"normalization alias bytes\n"
    verb = "would remove file" if show else "removed file"
    assert output.out == f"{verb}: {selected!r}\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("selected", UNICODE_ALIASES)
def test_unicode_normalization_distinct_stored_hardlinks_remain_independent(
    src_target, capsys, clean_processes, show, selected
):
    _declare(src_target, (selected,))
    stored = _put(
        src_target,
        "build/caf\u00e9.txt",  # codespell:ignore caf
        b"independent hardlink bytes\n",
    )
    chosen = src_target / selected
    if chosen.exists():
        pytest.skip("filesystem aliases these spellings instead of storing two entries")
    os.link(stored, chosen)
    assert os.path.samefile(stored, chosen)
    assert {entry.name for entry in stored.parent.iterdir()} == {
        stored.name,
        chosen.name,
    }
    _git(src_target, "add", "-f", "build/caf\u00e9.txt")  # codespell:ignore caf
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.read_bytes() == b"independent hardlink bytes\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"independent hardlink bytes\n"
    _preserved_pair(src_target)
    assert clean_processes == []


def _require_directory_read_denied(path: Path):
    path.chmod(0o300)
    try:
        with os.scandir(path) as entries:
            list(entries)
    except PermissionError:
        return
    pytest.skip("filesystem or process privileges do not enforce directory read denial")


@posix_only
@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("kind", ["alias", "same-spelling", "independent-hardlink"])
def test_unreadable_alias_parent_refuses_with_exact_and_hardlink_controls(
    src_target, capsys, clean_processes, show, kind
):
    selected = {
        "alias": "build/ONE.TXT",
        "same-spelling": "build/one.txt",
        "independent-hardlink": "build/second.txt",
    }[kind]
    paths = ("cache/one.txt", selected) if kind == "alias" else (selected,)
    _declare(src_target, paths, "build/\ncache/\n")
    earlier = _put(src_target, "cache/one.txt", b"earlier valid batch selection\n")
    stored = _put(
        src_target, "build/one.txt", b"tracked bytes under unreadable parent\n"
    )
    chosen = src_target / selected
    if kind == "alias" and not chosen.exists():
        pytest.skip("requires an actual case-insensitive filesystem alias")
    if kind == "independent-hardlink":
        os.link(stored, chosen)
    assert os.path.samefile(stored, chosen)
    _git(src_target, "add", "-f", "build/one.txt")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    parent = stored.parent
    original_mode = stat.S_IMODE(parent.stat().st_mode)
    try:
        _require_directory_read_denied(parent)

        code, output = _run(src_target, show, capsys)

        assert code == (0 if kind == "same-spelling" else 2), output
        assert stored.read_bytes() == b"tracked bytes under unreadable parent\n"
        _preserved_pair(src_target)
        assert chosen.read_bytes() == b"tracked bytes under unreadable parent\n"
        assert output.out == ""
        if kind != "same-spelling":
            assert "Permission denied" in output.err
        if kind == "alias":
            assert earlier.read_bytes() == b"earlier valid batch selection\n"
        assert clean_processes == []
    finally:
        parent.chmod(original_mode)


@posix_only
@pytest.mark.parametrize("prior_unlink", [False, True])
def test_unreadable_alias_parent_late_tracking_stops_at_correct_exit_boundary(
    src_target, capsys, clean_processes, monkeypatch, prior_unlink
):
    selected = "build/ONE.TXT"
    paths = ("cache/one.txt", selected) if prior_unlink else (selected,)
    paths += ("later/one.txt",)
    _declare(src_target, paths, "build/\ncache/\nlater/\n")
    later = _put(src_target, "later/one.txt", b"later selected bytes survive refusal\n")
    stored = _put(
        src_target, "build/one.txt", b"late tracked unreadable-parent bytes\n"
    )
    alias = src_target / selected
    if not alias.exists():
        pytest.skip("requires an actual case-insensitive filesystem alias")
    assert os.path.samefile(stored, alias)
    first = _put(src_target, "cache/one.txt", b"earlier exact selection\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    # Hash the owned file while readable. Updating cacheinfo later changes
    # the real index without requiring Git to enumerate the unreadable parent.
    blob = (
        subprocess.run(  # noqa: S603
            ["git", "-C", str(src_target), "hash-object", "-w", "--", "build/one.txt"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    real_run = subprocess.run
    real_unlink = os.unlink
    tracked_late = []

    def track_now():
        _git(
            src_target,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},build/one.txt",
        )
        cached = real_run(
            ["git", "-C", str(src_target), "ls-files", "-z", "--cached"],
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        assert b"build/one.txt" in cached
        tracked_late.append(True)

    def query_then_track(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if (
            not prior_unlink
            and not tracked_late
            and "check-ignore" in argv
            and "--no-index" not in argv
        ):
            track_now()
        return result

    def unlink_then_track(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if prior_unlink and Path(path) == first:
            track_now()
        return result

    monkeypatch.setattr(subprocess, "run", query_then_track)
    monkeypatch.setattr(os, "unlink", unlink_then_track)
    parent = stored.parent
    original_mode = stat.S_IMODE(parent.stat().st_mode)
    try:
        # Keep this mode stable from planning onward: refusal must come from
        # unavailable alias evidence, not from the parent-mode change guard.
        _require_directory_read_denied(parent)

        code, output = _run(src_target, False, capsys)

        assert tracked_late == [True]
        assert code == (1 if prior_unlink else 2), output
        assert stored.read_bytes() == b"late tracked unreadable-parent bytes\n"
        _preserved_pair(src_target)
        assert first.exists() != prior_unlink
        assert later.read_bytes() == b"later selected bytes survive refusal\n"
        assert "Permission denied" in output.err
        if prior_unlink:
            assert "earlier cleanup may have completed" in output.err
        else:
            assert first.read_bytes() == b"earlier exact selection\n"
            assert output.out == ""
        assert clean_processes == []
    finally:
        parent.chmod(original_mode)


def _windows_shortname_for_owned_file(path: Path) -> str:
    import ctypes
    from ctypes import wintypes
    from shutil import which

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short = kernel32.GetShortPathNameW
    get_short.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_short.restype = wintypes.DWORD

    def query_leaf():
        required = get_short(str(path), None, 0)
        if not required:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(required)
        written = get_short(str(path), buffer, required)
        if not written or written >= required:
            raise OSError("GetShortPathNameW did not return a complete stable path")
        return Path(buffer.value).name

    short_name = query_leaf()
    if short_name.casefold() == path.name.casefold():
        executable = which("fsutil")
        if executable is None:
            pytest.skip("no existing 8.3 alias and no per-file fsutil setter")
        # This changes only the owned file's alias, never volume/system policy.
        result = subprocess.run(  # noqa: S603
            [executable, "file", "setshortname", str(path), "P10ALIAS.TXT"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip(
                "no existing 8.3 alias; per-file setshortname unavailable: "
                + result.stderr.decode("utf-8", "replace").strip()
            )
        short_name = query_leaf()
    if short_name.casefold() == path.name.casefold():
        pytest.skip("filesystem did not provide a distinct short-name leaf")
    alias = path.parent / short_name
    assert alias.exists()
    assert os.path.samefile(path, alias)
    stored_names = {entry.name for entry in path.parent.iterdir()}
    assert path.name in stored_names
    assert short_name not in stored_names
    return short_name


@pytest.mark.skipif(os.name != "nt", reason="native Windows 8.3 filesystem aliases")
@pytest.mark.parametrize("show", [False, True])
def test_windows_shortname_tracked_file_is_silent_noop(
    src_target, capsys, clean_processes, show
):
    stored = _put(
        src_target,
        "build/longfilename-for-clean-probe.txt",
        b"tracked long-name bytes\n",
    )
    short_name = _windows_shortname_for_owned_file(stored)
    _declare(src_target, (f"build/{short_name}",))
    _git(src_target, "add", "-f", "build/longfilename-for-clean-probe.txt")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.read_bytes() == b"tracked long-name bytes\n"
    assert output.out == ""
    assert output.err == ""
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.skipif(os.name != "nt", reason="native Windows 8.3 filesystem aliases")
@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("duplicate", [False, True])
def test_windows_shortname_exact_selection_preserves_sibling_and_deduplicates(
    src_target, capsys, clean_processes, show, duplicate
):
    stored = _put(
        src_target,
        "build/longfilename-for-clean-probe.txt",
        b"selected long-name bytes\n",
    )
    short_name = _windows_shortname_for_owned_file(stored)
    selected = f"build/{short_name}"
    paths = (
        (selected, "build/longfilename-for-clean-probe.txt")
        if duplicate
        else (selected,)
    )
    _declare(src_target, paths)
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.exists() == show
    if show:
        assert stored.read_bytes() == b"selected long-name bytes\n"
    verb = "would remove file" if show else "removed file"
    assert output.out == f"{verb}: {selected!r}\n"
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.skipif(os.name != "nt", reason="native Windows 8.3 filesystem aliases")
@pytest.mark.parametrize("prior_unlink", [False, True])
def test_windows_shortname_late_tracking_stops_before_tracked_alias_unlink(
    src_target, capsys, clean_processes, monkeypatch, prior_unlink
):
    stored = _put(
        src_target,
        "build/longfilename-for-clean-probe.txt",
        b"newly tracked long-name bytes\n",
    )
    short_name = _windows_shortname_for_owned_file(stored)
    selected = f"build/{short_name}"
    paths = ("cache/one.txt", selected) if prior_unlink else (selected,)
    paths += ("later/one.txt",)
    _declare(src_target, paths, "build/\ncache/\nlater/\n")
    first = _put(src_target, "cache/one.txt", b"earlier exact selection\n")
    later = _put(src_target, "later/one.txt", b"later selected bytes survive refusal\n")
    _put(src_target, "build/two.txt", b"unselected sibling\n")
    real_run = subprocess.run
    real_unlink = os.unlink
    tracked_late = []

    def track_now():
        _git(src_target, "add", "-f", "build/longfilename-for-clean-probe.txt")
        cached = real_run(
            ["git", "-C", str(src_target), "ls-files", "-z", "--cached"],
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        assert b"build/longfilename-for-clean-probe.txt" in cached
        tracked_late.append(True)

    def query_then_track(argv, *args, **kwargs):
        result = real_run(argv, *args, **kwargs)
        if (
            not prior_unlink
            and not tracked_late
            and "check-ignore" in argv
            and "--no-index" not in argv
        ):
            track_now()
        return result

    def unlink_then_track(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if prior_unlink and Path(path) == first:
            track_now()
        return result

    monkeypatch.setattr(subprocess, "run", query_then_track)
    monkeypatch.setattr(os, "unlink", unlink_then_track)

    code, output = _run(src_target, False, capsys)

    assert tracked_late == [True]
    assert code == (1 if prior_unlink else 2), output
    assert stored.read_bytes() == b"newly tracked long-name bytes\n"
    assert first.exists() != prior_unlink
    assert later.read_bytes() == b"later selected bytes survive refusal\n"
    if prior_unlink:
        assert "earlier cleanup may have completed" in output.err
    else:
        assert first.read_bytes() == b"earlier exact selection\n"
        assert output.out == ""
    _preserved_pair(src_target)
    assert clean_processes == []


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("selected", ["build/BACKUP~1.TXT", "build/ALIAS.TXT"])
def test_literal_shortname_hardlink_entries_remain_independent(
    src_target, capsys, clean_processes, show, selected
):
    _declare(src_target, (selected,))
    stored = _put(
        src_target,
        "build/longfilename-for-clean-probe.txt",
        b"independent stored hardlink bytes\n",
    )
    chosen = src_target / selected
    os.link(stored, chosen)
    assert os.path.samefile(stored, chosen)
    assert {entry.name for entry in stored.parent.iterdir()} == {
        stored.name,
        chosen.name,
    }
    _git(src_target, "add", "-f", "build/longfilename-for-clean-probe.txt")
    _put(src_target, "build/two.txt", b"unselected sibling\n")

    code, output = _run(src_target, show, capsys)

    assert code == 0, output
    assert stored.read_bytes() == b"independent stored hardlink bytes\n"
    assert chosen.exists() == show
    if show:
        assert chosen.read_bytes() == b"independent stored hardlink bytes\n"
    _preserved_pair(src_target)
    assert clean_processes == []
