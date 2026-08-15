import dataclasses
import errno
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import template_press.rebrand.engine as engine_module
from template_press.rebrand.engine import (
    RenamePreflight,
    _rename_candidates,
    apply,
    build_plan,
    preflight_rename_noreplace,
    translate_path,
)
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
from template_press.rebrand.safety import (
    ContainmentError,
    SafetyError,
    UnsafePathError,
)

from .conftest import DEST, SOURCE, requires_symlink


def _git_add(repo: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _rules_with(**overrides):
    return dataclasses.replace(DEFAULT_RULES, **overrides)


def _identity(**overrides):
    base = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    base.update(overrides)
    return Identity(**base)


def _diverged_symlink_ancestor_repo(tmp_path: Path, leaf: str) -> tuple[Path, Path]:
    """A committed target whose real dir ``a/`` (holding ``a/<leaf>``) is, in a
    dirty working tree, swapped to a symlink pointing at an EXTERNAL dir.

    ``git ls-files`` still reports ``a/<leaf>`` from the INDEX, so any op on
    ``tgt/a/<leaf>`` that fails to validate ancestors traverses the ``a``
    symlink and mutates the external tree. Both dirs live under ``tmp_path``.
    """
    tgt = tmp_path / "tgt"
    ext = tmp_path / "ext"
    tgt.mkdir()
    ext.mkdir()
    _git(tgt, "init", "-q")
    _git(tgt, "config", "user.email", "a@b.c")
    _git(tgt, "config", "user.name", "x")
    (tgt / "a").mkdir()
    if leaf == "leaf":
        # token-bearing relative symlink (retarget candidate)
        os.symlink("../tgt/demo_widget/thing", tgt / "a" / "leaf")
    else:
        # token-bearing regular file (rename candidate)
        (tgt / "a" / leaf).write_text("in-repo content\n", encoding="utf-8")
    (tgt / "keep.txt").write_text("hi\n", encoding="utf-8")
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-q", "-m", "init")
    # DIVERGE: replace the real dir a/ with a symlink to the external dir.
    shutil.rmtree(tgt / "a")
    os.symlink(str(ext), tgt / "a")
    return tgt, ext


def test_package_dir_renamed_src_layout(src_target: Path):
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "src" / "potato_launcher" / "cli.py").is_file()
    assert not (src_target / "src" / "demo_widget").exists()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


def test_package_dir_renamed_flat_layout(flat_target: Path):
    apply(flat_target, SOURCE, DEST, DEFAULT_RULES)
    assert (flat_target / "potato_launcher" / "cli.py").is_file()
    assert not (flat_target / "demo_widget").exists()


def test_app_token_filename_renamed(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "potato_config.toml").is_file()
    assert not (src_target / "press_config.toml").exists()


@pytest.mark.skipif(os.name == "nt", reason="simulates another POSIX platform")
def test_preflight_refuses_unsupported_posix_when_rename_required(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    monkeypatch.setattr(safety.sys, "platform", "freebsd14")
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)

    with pytest.raises(
        SafetyError, match="atomic no-replace rename is unsupported on freebsd14"
    ):
        preflight_rename_noreplace(src_target, plan.renames)


def test_preflight_rejects_hostile_rename_source_before_probe(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engine_module,
        "require_rename_noreplace_support",
        lambda _source: pytest.fail("unsafe source reached probe"),
    )

    with pytest.raises(UnsafePathError):
        preflight_rename_noreplace(
            src_target,
            {"../outside/demo_widget": "potato_launcher"},
            allow_unsafe=True,
        )


@pytest.mark.skipif(os.name == "nt", reason="simulates another POSIX platform")
def test_apply_refuses_unsupported_posix_before_writes(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    ordinary = src_target / "ordinary.txt"
    ordinary.write_text("demo_widget content\n", encoding="utf-8")
    _git_add(src_target)
    source_path = src_target / "src" / "demo_widget"
    destination_path = src_target / "src" / "potato_launcher"
    monkeypatch.setattr(safety.sys, "platform", "freebsd14")

    with pytest.raises(
        SafetyError, match="atomic no-replace rename is unsupported on freebsd14"
    ):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert ordinary.read_text(encoding="utf-8") == "demo_widget content\n"
    assert source_path.is_dir()
    assert not destination_path.exists()


@pytest.mark.parametrize("error", [errno.ENOSYS, errno.ENOTSUP, errno.EINVAL])
def test_apply_refuses_unsupported_rename_filesystem_before_writes(
    error: int, src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    ordinary = src_target / "ordinary.txt"
    ordinary.write_text("demo_widget content\n", encoding="utf-8")
    _git_add(src_target)
    source_path = src_target / "src" / "demo_widget"
    destination_path = src_target / "src" / "potato_launcher"

    def reject_atomic_rename(_source: Path, _destination: Path) -> None:
        raise OSError(error, os.strerror(error))

    monkeypatch.setattr(safety, "_rename_noreplace_unchecked", reject_atomic_rename)

    with pytest.raises(SafetyError, match="atomic no-replace rename probe failed"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert ordinary.read_text(encoding="utf-8") == "demo_widget content\n"
    assert source_path.is_dir()
    assert not destination_path.exists()
    assert not list(src_target.rglob(".press-rename-probe-*"))


def test_apply_force_uses_best_effort_rename_when_atomic_support_is_unavailable(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    ordinary = src_target / "ordinary.txt"
    ordinary.write_text("demo_widget content\n", encoding="utf-8")
    _git_add(src_target)
    source_path = src_target / "src" / "demo_widget"
    destination_path = src_target / "src" / "potato_launcher"

    def reject_atomic_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))

    monkeypatch.setattr(safety, "_rename_noreplace_unchecked", reject_atomic_rename)

    report = apply(
        src_target,
        SOURCE,
        DEST,
        DEFAULT_RULES,
        allow_unsafe_rename=True,
    )

    assert ordinary.read_text(encoding="utf-8") == "potato_launcher content\n"
    assert not source_path.exists()
    assert destination_path.is_dir()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


def test_apply_force_does_not_override_probe_permission_failure(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    before = (src_target / "README.md").read_bytes()

    def reject_atomic_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    monkeypatch.setattr(safety, "_rename_noreplace_unchecked", reject_atomic_rename)

    with pytest.raises(SafetyError, match="atomic no-replace rename probe failed"):
        apply(
            src_target,
            SOURCE,
            DEST,
            DEFAULT_RULES,
            allow_unsafe_rename=True,
        )

    assert (src_target / "README.md").read_bytes() == before


def test_apply_force_does_not_override_probe_setup_failure(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    before = (src_target / "README.md").read_bytes()

    def reject_probe_setup(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EINVAL, "injected probe setup failure")

    monkeypatch.setattr(safety.tempfile, "TemporaryDirectory", reject_probe_setup)

    with pytest.raises(SafetyError, match="injected probe setup failure"):
        apply(
            src_target,
            SOURCE,
            DEST,
            DEFAULT_RULES,
            allow_unsafe_rename=True,
        )

    assert (src_target / "README.md").read_bytes() == before


def test_apply_rejects_preflight_policy_from_an_unrecognized_filesystem(
    src_target: Path,
) -> None:
    before = (src_target / "README.md").read_bytes()
    stale_preflight = RenamePreflight(
        checked_devices=frozenset({-1}),
        unsafe_devices=frozenset({-1}),
    )

    with pytest.raises(
        SafetyError, match="rename filesystem changed after capability preflight"
    ):
        apply(
            src_target,
            SOURCE,
            DEST,
            DEFAULT_RULES,
            allow_unsafe_rename=True,
            rename_preflight=stale_preflight,
        )

    assert (src_target / "README.md").read_bytes() == before


def test_apply_force_keeps_atomic_rename_on_supported_filesystem(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = engine_module.rename_noreplace
    atomic_calls: list[tuple[Path, Path]] = []

    def record_atomic_rename(source: Path, destination: Path) -> None:
        atomic_calls.append((source, destination))
        real_rename(source, destination)

    monkeypatch.setattr(engine_module, "rename_noreplace", record_atomic_rename)

    apply(
        src_target,
        SOURCE,
        DEST,
        DEFAULT_RULES,
        allow_unsafe_rename=True,
    )

    assert atomic_calls


def test_apply_skips_rename_preflight_for_content_only_rebrand(
    src_target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from template_press.rebrand import safety

    monkeypatch.setattr(
        safety,
        "_rename_noreplace_unchecked",
        lambda _source, _destination: pytest.fail("unexpected rename probe"),
    )
    content_only_dest = dataclasses.replace(SOURCE, author="Potato Farmer")

    report = apply(src_target, SOURCE, content_only_dest, DEFAULT_RULES)

    assert report.renamed == []


def test_nested_token_bearing_paths_rename_fully(src_target: Path):
    extra = src_target / "src" / "demo_widget" / "demo_widget_extra.py"
    extra.write_text('"""demo_widget extra."""\n', encoding="utf-8")
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    moved = src_target / "src" / "potato_launcher" / "potato_launcher_extra.py"
    assert moved.is_file()
    assert not (src_target / "src" / "demo_widget").exists()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


def test_blocked_parent_rename_gates_later_intermediate_step(
    src_target: Path,
) -> None:
    nested = src_target / "nested"
    source = nested / "demo_widget"
    source.mkdir(parents=True)
    (source / "demo_widget.txt").write_text("source\n", encoding="utf-8")
    occupied = nested / "potato_launcher"
    occupied.mkdir()
    unrelated = occupied / "demo_widget.txt"
    unrelated.write_text("unrelated\n", encoding="utf-8")
    rules = _rules_with(
        exclude_files=DEFAULT_RULES.exclude_files
        | frozenset({"nested/potato_launcher/demo_widget.txt"})
    )
    _git_add(src_target)

    report = apply(src_target, SOURCE, DEST, rules)

    assert unrelated.read_text(encoding="utf-8") == "unrelated\n"
    assert not (occupied / "potato_launcher.txt").exists()
    assert any("destination exists" in item for item in report.skipped)
    assert any("predecessor did not execute" in item for item in report.skipped)


def test_blocked_deep_rename_gates_step_after_successful_ancestor(
    src_target: Path,
) -> None:
    source_file = src_target / "aa" / "mn" / "file.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source\n", encoding="utf-8")
    carrier = src_target / "aa" / "carrier.txt"
    carrier.write_text("carrier\n", encoding="utf-8")
    occupied = src_target / "aa" / "zz" / "file.txt"
    occupied.parent.mkdir()
    occupied.write_text("unrelated\n", encoding="utf-8")
    source = _identity(package_name="file", author="mn", owner="aa")
    destination = _identity(package_name="renamed", author="zz", owner="bb")
    rules = _rules_with(
        exclude_files=DEFAULT_RULES.exclude_files | frozenset({"aa/zz/file.txt"}),
        replace=(
            ReplaceRule(
                pattern="{author}",
                reason="move the nested directory",
                files=("aa/mn/file.txt",),
                paths=True,
                content=False,
            ),
            ReplaceRule(
                pattern="{owner}",
                reason="move the ancestor directory",
                files=("aa/carrier.txt",),
                paths=True,
                content=False,
            ),
        ),
    )
    _git_add(src_target)

    report = apply(src_target, source, destination, rules)

    carried_occupied = src_target / "bb" / "zz" / "file.txt"
    assert carried_occupied.read_text(encoding="utf-8") == "unrelated\n"
    assert not (src_target / "bb" / "zz" / "renamed.txt").exists()
    assert any("destination exists" in item for item in report.skipped)
    assert any("predecessor did not execute" in item for item in report.skipped)


@requires_symlink
def test_apply_rewrites_in_repo_relative_symlink_target(src_target: Path):
    """An in-repo relative symlink target embedding identity is retargeted so a
    pressed fork's links don't dangle — only the link STRING changes."""
    link = src_target / "link"
    os.symlink("demo_widget/thing", link)  # in-repo, relative, does not exist
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "potato_launcher/thing"
    # The pointed-to file was never created or followed.
    assert not (src_target / "potato_launcher" / "thing").exists()
    assert not (src_target / "demo_widget" / "thing").exists()


@requires_symlink
def test_apply_leaves_escaping_symlink_target_untouched(src_target: Path):
    """A symlink whose (token-bearing) target escapes the root is NEVER
    rewritten — containment refuses it, the link string is left intact."""
    link = src_target / "link"
    os.symlink("../../outside/demo_widget", link)  # escapes root
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "../../outside/demo_widget"  # unchanged


@requires_symlink
def test_apply_leaves_absolute_symlink_target_untouched(src_target: Path):
    """An absolute symlink target is never rewritten or followed (isabs skip)."""
    link = src_target / "link"
    os.symlink("/srv/demo_widget/thing", link)  # absolute link STRING only
    _git_add(src_target)
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert link.is_symlink()
    assert os.readlink(link) == "/srv/demo_widget/thing"  # unchanged


@requires_symlink
def test_retarget_symlink_uses_substring_mode_for_opted_in_field(src_target: Path):
    """A field in substring_rewrite_fields must retarget symlinks via plain
    substring replace, not the boundary-guarded token pattern — mirroring
    _apply_replacements' dispatch (Fix 1). "plbpOwned" is glued (no boundary
    on the right side), so the default boundary match would leave it alone;
    substring mode must still catch it."""
    link = src_target / "link"
    os.symlink("targets/plbpOwned", link)
    _git_add(src_target)
    rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
    apply(src_target, _identity(), _identity(app_name="acme"), rules)
    assert os.readlink(link) == "targets/acmeOwned"


@requires_symlink
def test_retarget_excludes_display_form_pairs_dangling_link_guard(src_target: Path):
    """Display-form pairs rewrite symlink TEXT but display forms never rename
    paths (not in RENAME_FIELDS) — the target directory keeps its original
    name, so a display pair must not touch the link string either, or the
    link dangles (Fix 2)."""
    link = src_target / "link"
    os.symlink("PyLaunchBlueprint/data", link)
    _git_add(src_target)
    src = _identity(display_name="Py Launch Blueprint")
    dst = _identity(app_name="acme", display_name="Acme Widget")
    apply(src_target, src, dst, DEFAULT_RULES)
    assert os.readlink(link) == "PyLaunchBlueprint/data"


@requires_symlink
def test_existing_link_target_is_not_retargeted_for_non_path_identity(
    src_target: Path,
) -> None:
    target_dir = src_target / "Steve Morin"
    target_dir.mkdir()
    (target_dir / "profile.txt").write_text("profile\n", encoding="utf-8")
    link = src_target / "profile-link"
    os.symlink("Steve Morin/profile.txt", link)
    _git_add(src_target)
    destination = dataclasses.replace(SOURCE, author="Potato Farmer")

    apply(src_target, SOURCE, destination, DEFAULT_RULES)

    assert os.readlink(link) == "Steve Morin/profile.txt"
    assert (target_dir / "profile.txt").read_text(encoding="utf-8") == "profile\n"
    assert not (src_target / "Potato Farmer").exists()


def test_app_name_upper_renamed(src_target: Path):
    """Uppercased app token in filenames should be renamed."""
    (src_target / "PRESS_GUIDE.md").write_text("# Press Guide\n", encoding="utf-8")
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "POTATO_GUIDE.md").is_file()
    assert not (src_target / "PRESS_GUIDE.md").exists()


@requires_symlink
def test_retarget_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """PoC mirror (C1): a token-bearing symlink whose ANCESTOR dir is (dirty
    state) a symlink to an external tree must NOT be retargeted through that
    ancestor. ``apply`` must fail closed (ContainmentError) and the external
    object's inode must be unchanged (nothing unlinked/recreated outside)."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="leaf")
    # External sink the escape would delete + recreate.
    os.symlink("../tgt/demo_widget/thing", ext / "leaf")
    ext_inode_before = os.lstat(ext / "leaf").st_ino
    ext_link_before = os.readlink(ext / "leaf")

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external object is byte-for-byte untouched: same inode, same target.
    assert (ext / "leaf").is_symlink()
    assert os.lstat(ext / "leaf").st_ino == ext_inode_before
    assert os.readlink(ext / "leaf") == ext_link_before


@requires_symlink
def test_rename_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """Same-class hole (I1) in the rename pass: a token-bearing path whose
    ANCESTOR dir is a symlink to an external tree must NOT be renamed through
    that ancestor. ``apply`` fails closed and the external file is untouched."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="demo_widget.txt")
    # External content the rename would move through the symlinked ancestor.
    (ext / "demo_widget.txt").write_text("external\n", encoding="utf-8")
    ext_inode_before = os.lstat(ext / "demo_widget.txt").st_ino

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external file was neither moved nor recreated.
    assert (ext / "demo_widget.txt").is_file()
    assert os.lstat(ext / "demo_widget.txt").st_ino == ext_inode_before
    assert not (ext / "potato_launcher.txt").exists()


@requires_symlink
def test_replace_refuses_symlinked_ancestor_no_external_write(tmp_path: Path):
    """Same-class hole in the CONTENT replace pass: a token-free-named regular
    file whose ANCESTOR dir is a symlink to an external tree, where the external
    file's CONTENT carries a source token, must NOT be rewritten through that
    ancestor. ``apply`` fails closed; the external file's inode + content are
    untouched (no write-through)."""
    tgt, ext = _diverged_symlink_ancestor_repo(tmp_path, leaf="file.txt")
    # External file content embeds the source token — a write-through would
    # rewrite demo_widget -> potato_launcher in a file OUTSIDE the target.
    (ext / "file.txt").write_text("mentions demo_widget here\n", encoding="utf-8")
    ext_inode_before = os.lstat(ext / "file.txt").st_ino
    ext_content_before = (ext / "file.txt").read_text(encoding="utf-8")

    with pytest.raises(ContainmentError):
        apply(tgt, SOURCE, DEST, DEFAULT_RULES)

    # The external file was neither rewritten nor recreated.
    assert (ext / "file.txt").is_file()
    assert os.lstat(ext / "file.txt").st_ino == ext_inode_before
    assert (ext / "file.txt").read_text(encoding="utf-8") == ext_content_before


@requires_symlink
def test_rename_ignores_other_entries_under_excluded_directory(tmp_path: Path):
    """Containment validation applies only to paths the rename pass may touch."""

    target, _external = _diverged_symlink_ancestor_repo(tmp_path, leaf="file.txt")
    rules = _rules_with(exclude_dirs=DEFAULT_RULES.exclude_dirs | {"a"})

    candidates = _rename_candidates(target, rules)

    assert target / "keep.txt" in candidates
    assert not any(path.relative_to(target).parts[0] == "a" for path in candidates)


def test_build_plan_refuses_tracked_file_replaced_by_directory(
    src_target: Path,
) -> None:
    replaced = src_target / "README.md"
    replaced.unlink()
    replaced.mkdir()

    with pytest.raises(SafetyError, match="unscannable worktree entry"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo POSIX-only")
def test_build_plan_refuses_visible_fifo(src_target: Path) -> None:
    fifo = src_target / "events.pipe"
    fifo.write_text("tracked\n", encoding="utf-8")
    _git_add(src_target)
    fifo.unlink()
    os.mkfifo(fifo)

    with pytest.raises(SafetyError, match="unscannable worktree entry"):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo POSIX-only")
def test_apply_refuses_visible_fifo_before_rewriting_other_files(
    src_target: Path,
) -> None:
    ordinary = src_target / "ordinary.txt"
    ordinary.write_text("demo_widget stays\n", encoding="utf-8")
    fifo = src_target / "events.pipe"
    fifo.write_text("tracked\n", encoding="utf-8")
    _git_add(src_target)
    fifo.unlink()
    os.mkfifo(fifo)

    with pytest.raises(SafetyError, match="unscannable worktree entry"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert ordinary.read_text(encoding="utf-8") == "demo_widget stays\n"


def test_apply_refuses_embedded_repository_before_rewriting_other_files(
    src_target: Path,
) -> None:
    ordinary = src_target / "ordinary.txt"
    ordinary.write_text("demo_widget stays\n", encoding="utf-8")
    nested = src_target / "nested"
    nested.mkdir()
    _git(nested, "init", "-q")

    with pytest.raises(SafetyError, match="unscannable worktree entry"):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES)

    assert ordinary.read_text(encoding="utf-8") == "demo_widget stays\n"


@pytest.mark.parametrize("replacement_kind", ["missing", "directory"])
def test_rename_pass_refuses_source_changed_after_capture(
    src_target: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    source = src_target / "demo_widget.txt"
    source.write_text("clean\n", encoding="utf-8")
    _git_add(src_target)
    real_entries = engine_module._rename_candidate_entries
    changed = False

    def change_after_capture(target: Path, rules):
        nonlocal changed
        entries = real_entries(target, rules)
        if not changed:
            source.unlink()
            if replacement_kind == "directory":
                source.mkdir()
            changed = True
        return entries

    monkeypatch.setattr(
        engine_module,
        "_rename_candidate_entries",
        change_after_capture,
    )
    report = engine_module.ApplyReport()

    with pytest.raises(SafetyError, match="rename source changed after capture"):
        engine_module._rename_pass_once(
            src_target,
            [("package_name", "demo_widget", "potato_launcher")],
            DEFAULT_RULES,
            report,
            [],
        )

    assert report.skipped == []


def test_rename_pass_refuses_source_kind_swap_after_destination_checks(
    src_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = src_target / "demo_widget.txt"
    source.write_text("source\n", encoding="utf-8")
    _git_add(src_target)
    destination = src_target / "potato_launcher.txt"
    displaced = src_target / "displaced.txt"
    real_assert = engine_module.assert_ancestors_real
    swapped = False

    def swap_during_destination_check(path: Path, root: Path) -> None:
        nonlocal swapped
        real_assert(path, root)
        if path == destination and not swapped:
            source.rename(displaced)
            source.mkdir()
            (source / "child.txt").write_text("unauthorized\n", encoding="utf-8")
            swapped = True

    monkeypatch.setattr(
        engine_module,
        "assert_ancestors_real",
        swap_during_destination_check,
    )

    with pytest.raises(SafetyError, match="rename source changed after capture"):
        engine_module._rename_pass_once(
            src_target,
            [("package_name", "demo_widget", "potato_launcher")],
            DEFAULT_RULES,
            engine_module.ApplyReport(),
            [],
        )

    assert source.is_dir()
    assert not destination.exists()


def test_rename_pass_atomically_refuses_destination_created_after_checks(
    src_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = src_target / "demo_widget.txt"
    source.write_text("source\n", encoding="utf-8")
    _git_add(src_target)
    destination = src_target / "potato_launcher.txt"
    real_assert = engine_module.assert_ancestors_real
    occupied = False

    def occupy_before_move(path: Path, root: Path) -> None:
        nonlocal occupied
        real_assert(path, root)
        if path == source and not occupied:
            destination.write_text("do not overwrite\n", encoding="utf-8")
            occupied = True

    monkeypatch.setattr(
        engine_module,
        "assert_ancestors_real",
        occupy_before_move,
    )

    with pytest.raises(SafetyError, match="destination appeared"):
        engine_module._rename_pass_once(
            src_target,
            [("package_name", "demo_widget", "potato_launcher")],
            DEFAULT_RULES,
            engine_module.ApplyReport(),
            [],
        )

    assert source.read_text(encoding="utf-8") == "source\n"
    assert destination.read_text(encoding="utf-8") == "do not overwrite\n"


@requires_symlink
@pytest.mark.skipif(os.name == "nt", reason="descriptor-relative POSIX read")
def test_read_text_refuses_regular_file_replaced_by_symlink_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-read type change is not the stable-symlink compatibility case."""

    import template_press.rebrand.safety as safety_module

    source = tmp_path / "source.txt"
    source.write_text("captured bytes\n", encoding="utf-8")
    displaced = tmp_path / "displaced.txt"
    real_read = safety_module._read_descriptor

    def replace_with_symlink(descriptor: int) -> bytes:
        data = real_read(descriptor)
        source.rename(displaced)
        source.symlink_to("missing-target")
        return data

    monkeypatch.setattr(safety_module, "_read_descriptor", replace_with_symlink)

    with pytest.raises(SafetyError, match="changed while reading"):
        engine_module._read_text(source)


@requires_symlink
def test_build_plan_refuses_ancestor_swap_after_inventory(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A selected file must not be read after its ancestor becomes a link."""
    tracked = src_target / "race" / "file.txt"
    tracked.parent.mkdir()
    tracked.write_text("mentions demo_widget\n", encoding="utf-8")
    _git_add(src_target)
    external = tmp_path / "external-plan"
    external.mkdir()
    (external / "file.txt").write_text("external demo_widget\n", encoding="utf-8")
    real_candidates = engine_module.select_content_rewrite_entries

    def swap_after_inventory(snapshot, **kwargs):
        paths = real_candidates(snapshot, **kwargs)
        shutil.rmtree(src_target / "race")
        os.symlink(external, src_target / "race")
        return paths

    monkeypatch.setattr(
        engine_module, "select_content_rewrite_entries", swap_after_inventory
    )

    with pytest.raises(ContainmentError):
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)


@requires_symlink
def test_apply_refuses_ancestor_swap_after_inventory(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The content pass rechecks ancestors immediately before reading."""
    tracked = src_target / "race" / "file.txt"
    tracked.parent.mkdir()
    tracked.write_text("mentions demo_widget\n", encoding="utf-8")
    _git_add(src_target)
    external = tmp_path / "external-apply"
    external.mkdir()
    outside = external / "file.txt"
    outside.write_text("external demo_widget\n", encoding="utf-8")
    outside_before = outside.read_bytes()
    real_iter = engine_module.select_content_rewrite_entries

    def swap_after_inventory(snapshot, **kwargs):
        paths = real_iter(snapshot, **kwargs)
        shutil.rmtree(src_target / "race")
        os.symlink(external, src_target / "race")
        return paths

    monkeypatch.setattr(
        engine_module, "select_content_rewrite_entries", swap_after_inventory
    )

    with pytest.raises(ContainmentError):
        apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert outside.read_bytes() == outside_before


@requires_symlink
@pytest.mark.parametrize("operation", ["plan", "apply"])
def test_content_pass_refuses_file_replaced_by_symlink_before_open(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    tracked = src_target / "leaf.txt"
    tracked.write_text("mentions demo_widget\n", encoding="utf-8")
    _git_add(src_target)
    displaced = tmp_path / f"displaced-{operation}.txt"
    real_read = engine_module.read_regular_nofollow
    swapped = False

    def swap_before_open(path: Path) -> bytes:
        nonlocal swapped
        if path == tracked and not swapped:
            swapped = True
            tracked.rename(displaced)
            tracked.symlink_to("missing-target")
        return real_read(path)

    monkeypatch.setattr(engine_module, "read_regular_nofollow", swap_before_open)

    with pytest.raises(SafetyError, match="selected regular file changed"):
        if operation == "plan":
            build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
        else:
            apply(src_target, SOURCE, DEST, DEFAULT_RULES)


class TestRulePathRenames:
    def test_paths_rule_renames_doc_filename(self, src_target: Path):
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "0001-plbp-cli-conventions.md").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="-{app_name}-",
                    reason="doc filename token",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-acme-cli-conventions.md").exists()
        assert not (docs / "0001-plbp-cli-conventions.md").exists()

    def test_paths_false_rule_never_renames(self, src_target: Path):
        (src_target / "plbp-web.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(ReplaceRule(pattern="{app_name}-web", reason="content only"),)
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (src_target / "plbp-web.txt").exists()

    def test_empty_component_fails_loud_at_plan_time(self, src_target: Path):
        (src_target / "plbp").mkdir()
        (src_target / "plbp" / "keep.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}",
                    reason="degenerate",
                    paths=True,
                    content=False,
                ),
            )
        )
        # A paths rule whose TO renders empty would collapse "plbp/" into its
        # parent — build a dest whose app_name yields an empty TO is not
        # constructible (validators forbid empty), so simulate the guard via
        # a rule that strips the whole component: FROM == component text.
        # Direct unit check on _renamed_rel:
        from template_press.rebrand.engine import _renamed_rel

        with pytest.raises(ValidationError):
            _renamed_rel(
                Path("plbp/keep.txt"),
                [],
                rendered=[(rules.replace[0], "plbp", "")],
            )

    def test_dest_component_collapsing_to_dotdot_raises_at_build_plan(
        self, src_target: Path
    ):
        (src_target / "sub").mkdir()
        (src_target / "sub" / "keep.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{author}",
                    reason="author-named dir (path-collapse guard)",
                    paths=True,
                    content=False,
                ),
            )
        )
        source = _identity(author="sub")
        dest = _identity(author="..")
        with pytest.raises(ValidationError):
            build_plan(src_target, source, dest, rules)


class TestSelfReapplyingPathsRule:
    """F2(a): a paths=true [[replace]] rule whose rendered TO still
    contains its rendered FROM re-matches its own output on every rename
    pass (a.txt -> ax.txt -> axx.txt -> ... for pattern "{app_name}x" with
    app_name a -> ax) — 32 destructive passes for nothing. Rejected loud at
    plan time, mirroring the substring self-embedding collision guard."""

    def test_self_reapplying_rule_raises_at_build_plan(self, src_target: Path):
        (src_target / "a.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}x",
                    reason="self-reapplying repro (a -> ax)",
                    paths=True,
                    content=False,
                ),
            )
        )
        source = _identity(app_name="a")
        dest = _identity(app_name="ax")
        with pytest.raises(ValidationError):
            build_plan(src_target, source, dest, rules)


class TestRenameFixpointExhaustion:
    """F2(b): _apply_renames must fail LOUD, never silently return, when 32
    passes still haven't reached a fixpoint.

    Fix (a) above rejects every [[replace]]-rule shape that could drive
    this (rendered FROM in rendered TO, checked at plan time in
    ``rendered_replace_rules``) — but that guard inspects rule literals
    ONLY. A plain identity field pair opted into substring rewrite mode
    (``rules.substring_rewrite_fields``) is applied with the same
    no-boundary ``str.replace`` and so can re-embed itself exactly like a
    rule can (app_name "ax" -> "axx": ax.txt -> axx.txt -> axxx.txt -> ...),
    entirely independent of any [[replace]] rule — this is the
    independently-constructible exhaustion case fix (a) does not (and
    cannot, being rule-scoped) cover.
    """

    def test_substring_field_self_reapply_raises(self, src_target: Path):
        (src_target / "ax.txt").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        source = _identity(app_name="ax")
        dest = _identity(app_name="axx")
        # P06 validates path-pipeline termination before any target write.
        with pytest.raises(ValidationError, match="stale-source emission"):
            apply(src_target, source, dest, rules)


class TestSubstringRenames:
    def test_doc_filename_renamed_with_substring_mode(self, src_target: Path):
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "0001-app-short-name-plbp.md").write_text("x\n", encoding="utf-8")
        _git_add(src_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-app-short-name-acme.md").exists()


class TestRenameDestinationSymlinkHardening:
    @requires_symlink
    def test_rename_skips_dangling_symlink_destination(self, src_target: Path):
        """F1: `dst.exists()` FOLLOWS symlinks, so a dangling symlink sitting
        at the rename destination reads as absent and POSIX rename() would
        silently replace it (in-tree destructive overwrite). The rename must
        be skipped instead, leaving both the source file and the dangling
        symlink exactly as they were."""
        source_file = src_target / "plbp-web.txt"
        source_file.write_text("original content\n", encoding="utf-8")
        dangling = src_target / "acme-web.txt"
        os.symlink("nonexistent-target", dangling)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="collision with a dangling symlink destination",
                    paths=True,
                    content=False,
                ),
            )
        )
        report = apply(src_target, _identity(), _identity(app_name="acme"), rules)
        # The rename was skipped: source untouched, symlink still dangling.
        assert source_file.is_file()
        assert source_file.read_text(encoding="utf-8") == "original content\n"
        assert dangling.is_symlink()
        assert not dangling.exists()  # still dangling — never replaced
        assert os.readlink(dangling) == "nonexistent-target"
        assert any(
            "plbp-web.txt" in entry and "symlink" in entry for entry in report.skipped
        )


class TestRetargetSymlinksFollowsPathsRules:
    @requires_symlink
    def test_paths_rule_dir_rename_retargets_symlink_text(self, src_target: Path):
        """F2: a paths=true [[replace]] rule renames plbp-web/ -> acme-web/,
        but `_retarget_symlinks` previously only saw plain field token pairs
        — a relative symlink pointing into the renamed dir would keep
        pointing at the now-gone old path. The rule must retarget the link
        text too, mirroring exactly what the rename pass moved."""
        webdir = src_target / "plbp-web"
        webdir.mkdir()
        (webdir / "data").write_text("x\n", encoding="utf-8")
        link = src_target / "link"
        os.symlink("plbp-web/data", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="dir rename retarget",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "acme-web/data"

    @requires_symlink
    def test_paths_rule_scope_matches_link_target_not_link_location(
        self, src_target: Path
    ):
        """F3: a `files` scope selects which TARGET paths a paths=true rule
        renames — `_retarget_symlinks` must match that scope against the
        symlink's TARGET (what actually got renamed), not the symlink's own
        location. A root-level link into docs/ must still be retargeted by a
        files=["docs/**"] rule even though the link itself lives at the
        repo root (outside that scope)."""
        docs = src_target / "docs"
        docs.mkdir()
        (docs / "plbp-guide.md").write_text("x\n", encoding="utf-8")
        link = src_target / "guide"
        os.symlink("docs/plbp-guide.md", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-guide.md",
                    reason="doc rename retarget",
                    files=["docs/**"],
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "docs/acme-guide.md"


class TestRetargetOnlyWhenTargetMoves:
    """Commit 1: `_retarget_symlinks` must only rewrite a symlink's target
    TEXT when something under that target actually moves — never on
    candidate MEMBERSHIP alone, since `git ls-files` lists FILES, never
    directories. `TestRetargetSymlinksFollowsPathsRules`'s existing test
    points the link at a FILE INSIDE the renamed dir (`plbp-web/data`),
    which is itself a candidate either way — it cannot distinguish a
    membership-only check from the prefix-aware one this fix requires. These
    pin the two shapes a membership-only implementation gets wrong."""

    @requires_symlink
    def test_symlink_to_tracked_directory_still_retargets(self, src_target: Path):
        """The link points AT the directory itself (not a file inside it) —
        the directory is never itself a `_rename_candidates` member (git
        lists files only), but a file inside it is, so the prefix check
        (`cand.startswith(target_posix + "/")`) must still recognize the
        target as movable."""
        webdir = src_target / "plbp-web"
        webdir.mkdir()
        (webdir / "readme.md").write_text("x\n", encoding="utf-8")
        link = src_target / "link"
        os.symlink("plbp-web", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="dir rename retarget (dir target, not a file inside it)",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "acme-web"
        assert (src_target / "acme-web" / "readme.md").is_file()
        assert not webdir.exists()

    @requires_symlink
    @pytest.mark.parametrize("referring_target", ["plbp-guide", "plbp-guide/child"])
    def test_link_to_dangling_symlink_path_stays_put_when_rename_is_skipped(
        self, src_target: Path, referring_target: str
    ) -> None:
        source_link = src_target / "plbp-guide"
        os.symlink("missing-target", source_link)
        referring_link = src_target / "link"
        os.symlink(referring_target, referring_link)
        _git_add(src_target)
        with (src_target / ".git" / "info" / "exclude").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write("\nacme-guide\n")
        occupied_destination = src_target / "acme-guide"
        occupied_destination.write_text("operator data\n", encoding="utf-8")
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-guide",
                    reason="occupied dangling-symlink rename destination",
                    paths=True,
                    content=False,
                ),
            )
        )

        report = apply(src_target, _identity(), _identity(app_name="acme"), rules)

        assert source_link.is_symlink()
        assert os.readlink(source_link) == "missing-target"
        assert os.readlink(referring_link) == referring_target
        assert occupied_destination.read_text(encoding="utf-8") == "operator data\n"
        assert any(
            "rename plbp-guide (destination exists)" in item for item in report.skipped
        )

    @requires_symlink
    def test_missing_suffix_below_unrelated_dangling_symlink_retargets(
        self, src_target: Path
    ) -> None:
        alias = src_target / "alias"
        os.symlink("missing-dir", alias)
        referring_link = src_target / "link"
        os.symlink("alias/plbp-guide", referring_link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-guide",
                    reason="missing suffix below unchanged dangling symlink",
                    paths=True,
                    content=False,
                ),
            )
        )

        apply(src_target, _identity(), _identity(app_name="acme"), rules)

        assert os.readlink(alias) == "missing-dir"
        assert os.readlink(referring_link) == "alias/acme-guide"

    @requires_symlink
    def test_dangling_rule_target_still_retargets(self, src_target: Path):
        """The target never exists anywhere — nothing can break by
        rebranding the link text, so the dangling fallback
        (`not (target / target_posix).exists()`) must still retarget it."""
        link = src_target / "link"
        os.symlink("plbp-guide", link)  # never exists anywhere in the repo
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-guide",
                    reason="dangling target still rebrands",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        assert os.readlink(link) == "acme-guide"
        assert not (src_target / "acme-guide").exists()  # still dangling


class TestRenameSeesSymlinkNames:
    """F2: retarget rewrites a symlink's TEXT only — the rename pass must
    ALSO see the symlink's own NAME as a candidate, or a token-bearing
    directory/dangling symlink's stale name survives every press forever
    (the doctor's dangling-symlink path scan then flags it permanently:
    `iter_target_files`'s `is_file()` FOLLOWS the link, so a symlink to a
    directory or to nothing drops out of both `_rename_pass_once` and
    `build_plan`'s rename-planning loop before this fix)."""

    @requires_symlink
    def test_dangling_symlink_name_renamed(self, src_target: Path):
        link = src_target / "plbp-link"
        os.symlink("nowhere", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dangling symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        report = apply(src_target, _identity(), _identity(app_name="acme"), rules)
        new_link = src_target / "acme-link"
        assert new_link.is_symlink()
        assert not new_link.exists()  # still dangling — target untouched
        assert os.readlink(new_link) == "nowhere"
        assert not link.is_symlink() and not link.exists()
        assert ("plbp-link", "acme-link") in report.renamed

    @requires_symlink
    def test_build_plan_lists_the_dangling_symlink_rename(self, src_target: Path):
        """Plan/apply parity: `build_plan` must see the same candidate
        `_rename_pass_once` does, or a dry-run silently under-reports what
        apply() will actually do."""
        link = src_target / "plbp-link"
        os.symlink("nowhere", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dangling symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        plan = build_plan(src_target, _identity(), _identity(app_name="acme"), rules)
        assert any(
            item.kind == "rename" and item.path == "plbp-link" for item in plan.items
        )

    @requires_symlink
    def test_build_plan_accepts_stable_symlink_with_checked_read_fallback(
        self, src_target: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The non-openat reader must retain stable symlink compatibility."""

        import template_press.rebrand.safety as safety_module

        link = src_target / "plbp-link"
        os.symlink("nowhere", link)
        _git_add(src_target)
        monkeypatch.setattr(safety_module.os, "supports_dir_fd", frozenset())
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="checked-path symlink compatibility",
                    paths=True,
                    content=False,
                ),
            )
        )

        plan = build_plan(
            src_target,
            _identity(),
            _identity(app_name="acme"),
            rules,
        )

        assert any(
            item.kind == "rename" and item.path == "plbp-link" for item in plan.items
        )

    @requires_symlink
    def test_directory_symlink_name_renamed(self, src_target: Path):
        """Cheap directory-symlink variant: the link's NAME renames, its
        target string is untouched, and it still resolves through."""
        real_dir = src_target / "realtarget"
        real_dir.mkdir()
        (real_dir / "f.txt").write_text("x\n", encoding="utf-8")
        link = src_target / "plbp-link"
        os.symlink("realtarget", link)
        _git_add(src_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-link",
                    reason="dir symlink name token",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(src_target, _identity(), _identity(app_name="acme"), rules)
        new_link = src_target / "acme-link"
        assert new_link.is_symlink()
        assert os.readlink(new_link) == "realtarget"  # target string untouched
        assert (new_link / "f.txt").is_file()  # still resolves through
        assert not link.is_symlink()

    def test_gitlink_never_a_rename_candidate(self, src_target: Path, tmp_path: Path):
        """Gitlink exclusion: a submodule pointer must never be renamed by
        this pass, even when its own path carries an identity token.

        Not independently exercisable end-to-end via `apply()`: a real
        gitlink is a plain DIRECTORY when checked out (excluded already by
        the `is_file()`/`is_symlink()` filter — it is neither) and has no
        working-tree entry at all when not checked out (same exclusion, for
        the same reason) — a symlinked or regular-file gitlink is not a
        shape git produces. So this pins `_rename_candidates` directly
        (belt-and-suspenders defense-in-depth, mirroring `copy_paths`'
        established gitlink handling) rather than through a rename that
        could ever actually fire.
        """
        inner = tmp_path / "inner"
        inner.mkdir()
        _git(inner, "init", "-q", "-b", "main")
        _git(inner, "config", "user.email", "test@example.com")
        _git(inner, "config", "user.name", "Test")
        (inner / "f.txt").write_text("x\n", encoding="utf-8")
        _git_add(inner)
        _git(inner, "commit", "-q", "-m", "inner init")
        sha = subprocess.run(  # noqa: S603
            ["git", "-C", str(inner), "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
        _git(
            src_target, "update-index", "--add", "--cacheinfo", f"160000,{sha},plbp-sub"
        )
        _git(src_target, "commit", "-q", "-m", "add gitlink")
        candidates = {
            p.relative_to(src_target).as_posix()
            for p in _rename_candidates(src_target, DEFAULT_RULES)
        }
        assert "plbp-sub" not in candidates


class TestTranslatePath:
    """Copilot thread 3654632264: ApplyReport.renamed carries later-pass
    pairs in INTERMEDIATE coordinates (see ignores.build_forward_map), so
    forward translation must chain to a fixpoint, not stop at first match."""

    def test_single_prefix_translation(self):
        assert (
            translate_path("pkg_press/HISTORY.md", {"pkg_press": "pkg_potato"})
            == "pkg_potato/HISTORY.md"
        )

    def test_unrenamed_path_passes_through(self):
        assert translate_path("docs/README.md", {"pkg_press": "pkg_potato"}) == (
            "docs/README.md"
        )

    def test_intermediate_coordinate_chain_reaches_fixpoint(self):
        renames = {
            "src/demo_widget": "src/potato_launcher",
            "src/potato_launcher/demo_widget.lock": (
                "src/potato_launcher/potato_launcher.lock"
            ),
        }
        assert (
            translate_path("src/demo_widget/demo_widget.lock", renames)
            == "src/potato_launcher/potato_launcher.lock"
        )

    def test_cyclic_map_raises_instead_of_hanging(self):
        with pytest.raises(ValidationError):
            translate_path("a/x", {"a": "b", "b": "a"})
