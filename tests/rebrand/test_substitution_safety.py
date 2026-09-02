"""P06-TS09: frozen-plan closure and Git-visibility safety gates."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.engine import (
    ApplyReport,
    _retarget_planned_symlinks,
    apply,
    build_plan,
)
from template_press.rebrand.inventory import SurfaceEntry
from template_press.rebrand.reset import preflight_reset_targets
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule, ResetRule
from template_press.rebrand.safety import RenameClosureUnauthorized, SafetyError
from template_press.rebrand.substitutions import (
    RenamePlan,
    SubstitutionTable,
    validate_reset_visibility,
)

from .conftest import DEST, SOURCE, posix_only, requires_symlink


def _git(target: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(target), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _exclude_without_identity(target: Path, pattern: str) -> None:
    info_exclude = target / ".git" / "info" / "exclude"
    with info_exclude.open("a", encoding="utf-8") as stream:
        stream.write(f"\n{pattern}\n")


@requires_symlink
def test_retarget_refuses_symlink_missing_from_planning_inputs(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = target / "link"
    link.symlink_to("destination")
    table = SubstitutionTable(
        rows=(),
        rename_plan=RenamePlan(
            source_entries=(
                SurfaceEntry(
                    rel=Path("link"),
                    tracked=True,
                    index_kind="symlink",
                    worktree_kind="symlink",
                ),
            ),
        ),
    )

    with pytest.raises(SafetyError, match="not captured during planning"):
        _retarget_planned_symlinks(target, table, ApplyReport())


def test_prefix_closure_refuses_ignored_untracked_descendant(
    src_target: Path,
) -> None:
    _exclude_without_identity(src_target, "src/*/ignored.txt")
    ignored = src_target / "src" / "demo_widget" / "ignored.txt"
    ignored.write_text("operator data\n", encoding="utf-8")
    assert _git(src_target, "check-ignore", ignored.relative_to(src_target).as_posix())

    with pytest.raises(SafetyError, match="absent from the authorized surface"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_prefix_closure_error_lists_every_ignored_descendant(src_target: Path) -> None:
    _exclude_without_identity(src_target, "src/*/ignored*.txt")
    pkg = src_target / "src" / "demo_widget"
    (pkg / "ignored-a.txt").write_text("a\n", encoding="utf-8")
    (pkg / "ignored-b.txt").write_text("b\n", encoding="utf-8")
    (pkg / "empty").mkdir()
    with pytest.raises(
        RenameClosureUnauthorized, match="absent from the authorized surface"
    ) as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    exc = info.value
    assert exc.code == "rename_closure_unauthorized"
    assert exc.source_prefix == "src/demo_widget"
    assert {p for _, p in exc.findings} == {
        "src/demo_widget/ignored-a.txt",
        "src/demo_widget/ignored-b.txt",
        "src/demo_widget/empty",
    }
    assert exc.total == 3 and exc.truncated is False
    assert {k for k, _ in exc.findings} == {"absent", "empty-dir"}
    assert exc.phase == "plan"


def test_prefix_closure_gitlink_wins_over_ignored_leaves(src_target: Path) -> None:
    _exclude_without_identity(src_target, "src/*/ignored*.txt")
    pkg = src_target / "src" / "demo_widget"
    (pkg / "ignored-a.txt").write_text("a\n", encoding="utf-8")
    (pkg / "ignored-b.txt").write_text("b\n", encoding="utf-8")
    sha = _git(src_target, "rev-parse", "HEAD")
    rel = "src/demo_widget/submodule"
    _git(src_target, "update-index", "--add", "--cacheinfo", f"160000,{sha},{rel}")

    with pytest.raises(SafetyError, match="would carry gitlink"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_prefix_closure_structural_refusal_is_immediate(
    src_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structural refusal wins even with authorization findings already
    collected: ``0empty`` and ``0ignored.txt`` sort before ``cli.py`` in the
    directory walk, so both an empty-dir and an absent finding are appended to
    the in-progress ``findings`` list before the forced-missing ``cli.py``
    node is reached and immediately raises — proving the plain ``SafetyError``
    wins over aggregation rather than being folded into a
    ``RenameClosureUnauthorized``.
    """
    from template_press.rebrand import substitutions as substitutions_module

    _exclude_without_identity(src_target, "src/*/0ignored.txt")
    pkg = src_target / "src" / "demo_widget"
    (pkg / "0ignored.txt").write_text("a\n", encoding="utf-8")
    (pkg / "0empty").mkdir()

    real_node_kind = substitutions_module._node_kind
    missing_child = pkg / "cli.py"

    def fake_node_kind(path: Path) -> object:
        if path == missing_child:
            return "missing"
        return real_node_kind(path)

    monkeypatch.setattr(substitutions_module, "_node_kind", fake_node_kind)

    with pytest.raises(SafetyError, match="closure changed during planning") as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert type(info.value) is SafetyError


def test_prefix_closure_nested_empty_directory_does_not_cascade(
    src_target: Path,
) -> None:
    """An empty directory returns 1 to its own parent's ``child_count``, so
    only the innermost empty directory is reported — the parent that merely
    CONTAINS it is not spuriously reported as empty too."""
    outer = src_target / "src" / "demo_widget" / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)

    with pytest.raises(
        RenameClosureUnauthorized, match="uninventoried empty directory"
    ) as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    exc = info.value
    assert exc.findings == (("empty-dir", "src/demo_widget/outer/inner"),)
    assert exc.total == 1
    assert exc.truncated is False


def test_prefix_closure_truncates_rendered_list_past_cap(src_target: Path) -> None:
    _exclude_without_identity(src_target, "src/*/absent-*.txt")
    pkg = src_target / "src" / "demo_widget"
    absent_paths = set()
    for i in range(15):
        name = f"absent-{i:02d}.txt"
        (pkg / name).write_text("x\n", encoding="utf-8")
        absent_paths.add(f"src/demo_widget/{name}")
    empty_paths = set()
    for i in range(10):
        name = f"empty-{i:02d}"
        (pkg / name).mkdir()
        empty_paths.add(f"src/demo_widget/{name}")

    with pytest.raises(
        RenameClosureUnauthorized, match="absent from the authorized surface"
    ) as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    exc = info.value
    assert exc.total == 25
    assert exc.truncated is True
    assert {p for _, p in exc.findings} == absent_paths | empty_paths
    message = str(exc)
    assert message.count("\n  - ") == 20
    assert "… (5 more)" in message


@posix_only
def test_prefix_closure_renders_hostile_filenames_safely(src_target: Path) -> None:
    _exclude_without_identity(src_target, "src/*/hostile-*")
    pkg = src_target / "src" / "demo_widget"
    newline_name = "hostile-new\nline.txt"
    control_name = "hostile-control-\x01\x1b.txt"
    (pkg / newline_name).write_text("a\n", encoding="utf-8")
    (pkg / control_name).write_text("b\n", encoding="utf-8")

    with pytest.raises(
        RenameClosureUnauthorized, match="absent from the authorized surface"
    ) as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    exc = info.value
    expected = {
        f"src/demo_widget/{newline_name}",
        f"src/demo_widget/{control_name}",
    }
    assert {p for _, p in exc.findings} == expected
    message = str(exc)
    assert repr(f"src/demo_widget/{newline_name}") in message
    assert repr(f"src/demo_widget/{control_name}") in message
    # repr() escapes the raw control bytes — none survive verbatim in the
    # rendered message.
    assert "\x01" not in message
    assert "\x1b" not in message


@posix_only
def test_prefix_closure_renders_non_utf8_filename_or_skips(src_target: Path) -> None:
    """Lossless, safe rendering of a filename that is not valid UTF-8
    (created via a raw byte path, POSIX ``surrogateescape`` round-trip).
    Skipped with an explicit marker on a filesystem that refuses to create
    such a name (e.g. macOS APFS, which normalizes/validates UTF-8)."""
    _exclude_without_identity(src_target, "src/*/hostile-bytes-*")
    pkg = src_target / "src" / "demo_widget"
    raw_name = b"hostile-bytes-\xff\xfe.txt"
    raw_path = os.fsencode(str(pkg)) + b"/" + raw_name
    try:
        fd = os.open(raw_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o644)
        os.close(fd)
    except OSError as exc:
        pytest.skip(f"filesystem refuses non-UTF-8 filenames: {exc}")

    name = os.fsdecode(raw_name)
    with pytest.raises(
        RenameClosureUnauthorized, match="absent from the authorized surface"
    ) as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    result = info.value
    expected_rel = f"src/demo_widget/{name}"
    assert {p for _, p in result.findings} == {expected_rel}
    assert repr(expected_rel) in str(result)


def test_prefix_closure_unauthorized_phase_is_apply_after_planning(
    src_target: Path,
) -> None:
    _exclude_without_identity(src_target, "src/*/late-ignored.txt")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    late = src_target / "src" / "demo_widget" / "late-ignored.txt"
    late.write_text("late operator data\n", encoding="utf-8")

    with pytest.raises(
        RenameClosureUnauthorized, match="absent from the authorized surface"
    ) as info:
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)
    exc = info.value
    assert exc.code == "rename_closure_unauthorized"
    assert exc.phase == "apply"
    assert {p for _, p in exc.findings} == {"src/demo_widget/late-ignored.txt"}
    assert readme.read_bytes() == before


def test_prefix_closure_refuses_uninventoried_empty_directory(
    src_target: Path,
) -> None:
    (src_target / "src" / "demo_widget" / "empty").mkdir()

    with pytest.raises(SafetyError, match="uninventoried empty directory"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


@pytest.mark.parametrize("checked_out", [False, True])
def test_prefix_closure_refuses_missing_and_checked_out_gitlink(
    src_target: Path,
    checked_out: bool,
) -> None:
    sha = _git(src_target, "rev-parse", "HEAD")
    rel = "src/demo_widget/submodule"
    _git(src_target, "update-index", "--add", "--cacheinfo", f"160000,{sha},{rel}")
    if checked_out:
        path = src_target / rel
        path.mkdir()
        (path / "worktree.txt").write_text("opaque\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="would carry gitlink"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_apply_refuses_live_prefix_closure_divergence_before_content_write(
    src_target: Path,
) -> None:
    _exclude_without_identity(src_target, "src/*/late-secret.txt")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    late = src_target / "src" / "demo_widget" / "late-secret.txt"
    late.write_text("late operator data\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="absent from the authorized surface"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before


def test_apply_refuses_destination_state_divergence_before_content_write(
    src_target: Path,
) -> None:
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    destination = src_target / "src" / "potato_launcher"
    destination.mkdir()

    with pytest.raises(SafetyError, match="rename destination changed"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before


def test_content_rewrite_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    (src_target / ".gitignore").write_text(
        "demo_widget-secret\n",
        encoding="utf-8",
    )
    (src_target / "demo_widget-secret").write_text("ignored\n", encoding="utf-8")

    with pytest.raises(SafetyError, match=r"content rewrite.*Git visibility input"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_ancestor_rename_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    directory = src_target / "demo_widget_ignore"
    directory.mkdir()
    (directory / ".gitignore").write_text("secret\n", encoding="utf-8")
    (directory / "keep.txt").write_text("tracked\n", encoding="utf-8")
    _git(src_target, "add", "-A")

    with pytest.raises(SafetyError, match=r"Git visibility input.*would move"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


def test_direct_rename_of_gitignore_is_refused_during_planning(
    src_target: Path,
) -> None:
    source = replace(SOURCE, app_name="ignore")
    destination = replace(source, app_name="safe")
    rules = replace(
        DEFAULT_RULES,
        replace=(
            ReplaceRule(
                pattern=".git{app_name}",
                reason="direct visibility-input rename fixture",
                paths=True,
                content=False,
            ),
        ),
    )

    with pytest.raises(SafetyError, match=r"Git visibility input.*would move"):
        build_plan(src_target, source, destination, rules)


def test_position_zero_reset_of_gitignore_is_refused(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("secret\n", encoding="utf-8")
    _git(src_target, "add", ".gitignore")
    _git(src_target, "commit", "-q", "-m", "track ignore policy")
    rules = replace(
        DEFAULT_RULES,
        reset=(ResetRule(file=".gitignore", stub="other\n"),),
    )
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None
    previews, problems = preflight_reset_targets(
        src_target,
        rules,
        source=SOURCE,
        dest=DEST,
        renames=plan.renames,
        table=plan.table,
    )
    assert not problems

    with pytest.raises(SafetyError, match="reset would change Git visibility"):
        validate_reset_visibility(
            src_target,
            plan.table.rename_plan,
            tuple((preview.rule.file, preview.stub_text) for preview in previews),
        )


def test_apply_refuses_live_visibility_input_change_before_content_write(
    src_target: Path,
) -> None:
    gitignore = src_target / ".gitignore"
    gitignore.write_text("secret\n", encoding="utf-8")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert plan.table is not None
    readme = src_target / "README.md"
    before = readme.read_bytes()
    gitignore.write_text("other\n", encoding="utf-8")

    with pytest.raises(SafetyError, match="Git visibility inputs changed"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES, table=plan.table)

    assert readme.read_bytes() == before
