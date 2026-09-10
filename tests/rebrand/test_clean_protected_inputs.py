"""P10 cleanup preserves declared Git includes and press-owned inputs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from template_press import press_cli
from template_press.rebrand import clean_cli
from template_press.rebrand.inventory import capture_surface_snapshot

from .conftest import _git, posix_only, requires_symlink
from .test_cli import write_source_config

CONTROL_FILES = (
    "press/press-source.toml",
    "press/press-rules.toml",
    "press/press-receipt.toml",
    "press/press-answers.toml",
)
INCLUDE_BYTES = b"# retained config input\n"
CACHE_BYTES = b"ignored cache content\n"


def _declare(target: Path, path: str, ignored: str, *, tracked: bool = True):
    write_source_config(target)
    (target / "press/press-rules.toml").write_text(
        f'[[clean]]\npaths = ["{path}"]\n', encoding="utf-8"
    )
    (target / "press/press-receipt.toml").write_bytes(b"# retained receipt\n")
    (target / "press/press-answers.toml").write_bytes(b"# retained answers\n")
    (target / ".git/info/exclude").write_text(ignored, encoding="utf-8")
    if tracked:
        _git(target, "add", "-f", *CONTROL_FILES)
        _git(target, "commit", "-q", "-m", "track cleanup inputs")


def _include(target: Path, path: Path, *, active: bool = True):
    branch = "main" if active else "inactive-cleanup-probe"
    _git(target, "config", f"includeIf.onbranch:{branch}.path", str(path))


def _cache(target: Path, root: str = "src/demo_widget") -> Path:
    cache = target / root / "cache.tmp"
    cache.write_bytes(CACHE_BYTES)
    return cache


def _assert_refused(target, show, diagnostic, capsys, monkeypatch, *, overlap=True):
    real_execute = clean_cli.execute_clean
    clean_calls = []

    def record_clean(argv, command_target, *, stdin=None):
        if "clean" in argv:
            clean_calls.append(argv)
        return real_execute(argv, command_target, stdin=stdin)

    monkeypatch.setattr(clean_cli, "execute_clean", record_clean)
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    code = press_cli.main(args)
    output = capsys.readouterr()
    assert code == 2, output
    assert diagnostic in output.err
    if overlap:
        assert "overlaps [[clean]] path" in output.err
    assert "run:" not in output.out and "preview:" not in output.out
    assert clean_calls == []


def _assert_clean_allowed(target, show, cache):
    args = ["clean", "--target", str(target)] + (["--show"] if show else [])
    assert press_cli.main(args) == 0
    assert cache.exists() == show
    if show:
        assert cache.read_bytes() == CACHE_BYTES


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("declared", ["src/demo_widget", "src/{package_name}"])
@pytest.mark.parametrize("contents", [b"", b"# config comment\n", b"[probe]\n"])
def test_active_conditional_include_without_values_refuses_clean(
    src_target, capsys, monkeypatch, show, declared, contents
):
    _declare(src_target, declared, "*.policy\n*.tmp\n")
    policy = src_target / "src/demo_widget/extra.policy"
    policy.write_bytes(contents)
    _include(src_target, policy)
    cache = _cache(src_target)
    before = capture_surface_snapshot(src_target)
    assert all(item.path != policy for item in before.git_config_inputs)
    assert policy.relative_to(src_target) not in {item.rel for item in before.entries}

    _assert_refused(
        src_target, show, "declared Git config include", capsys, monkeypatch
    )

    assert policy.read_bytes() == contents
    assert cache.read_bytes() == CACHE_BYTES
    assert capture_surface_snapshot(src_target) == before


@pytest.mark.parametrize("show", [False, True])
def test_inactive_ignored_conditional_include_is_conservatively_preserved(
    src_target, capsys, monkeypatch, show
):
    _declare(src_target, "src/{package_name}", "*.policy\n*.tmp\n")
    policy = src_target / "src/demo_widget/extra.policy"
    contents = b"[probe]\n sentinel = inactive\n"
    policy.write_bytes(contents)
    _include(src_target, policy, active=False)
    cache = _cache(src_target)
    before = capture_surface_snapshot(src_target)
    assert all(item.path != policy for item in before.git_config_inputs)

    _assert_refused(
        src_target, show, "declared Git config include", capsys, monkeypatch
    )

    assert policy.read_bytes() == contents
    assert cache.read_bytes() == CACHE_BYTES
    assert capture_surface_snapshot(src_target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("protection", ["missing", "disjoint", "tracked", "nonignored"])
def test_safe_conditional_include_allows_clean(src_target, show, protection):
    ignored = "*.tmp\n" if protection == "nonignored" else "*.policy\n*.tmp\n"
    _declare(src_target, "src/{package_name}", ignored)
    relative = (
        "press/extra.policy"
        if protection == "disjoint"
        else "src/demo_widget/extra.policy"
    )
    policy = src_target / relative
    if protection != "missing":
        policy.write_bytes(INCLUDE_BYTES)
    if protection == "tracked":
        _git(src_target, "add", "-f", relative)
    _include(src_target, policy)
    cache = _cache(src_target)
    before = capture_surface_snapshot(src_target)

    _assert_clean_allowed(src_target, show, cache)

    if protection == "missing":
        assert not policy.exists()
    else:
        assert policy.read_bytes() == INCLUDE_BYTES
    assert capture_surface_snapshot(src_target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("declared", ["press", "{app_name}"])
@pytest.mark.parametrize("unprotected", CONTROL_FILES)
def test_each_ignored_press_control_independently_refuses_clean(
    src_target, capsys, monkeypatch, show, declared, unprotected
):
    _declare(src_target, declared, f"{unprotected}\n*.tmp\n")
    _git(src_target, "rm", "--cached", "--", unprotected)
    original = {rel: (src_target / rel).read_bytes() for rel in CONTROL_FILES}
    cache = _cache(src_target, "press")
    before = capture_surface_snapshot(src_target)
    listed = {entry.rel.as_posix() for entry in before.entries}
    assert unprotected not in listed
    assert set(CONTROL_FILES) - {unprotected} <= listed

    _assert_refused(src_target, show, "press-owned control file", capsys, monkeypatch)

    assert {rel: (src_target / rel).read_bytes() for rel in CONTROL_FILES} == original
    assert cache.read_bytes() == CACHE_BYTES
    assert capture_surface_snapshot(src_target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("protection", ["tracked", "nonignored", "missing", "disjoint"])
def test_safe_press_controls_allow_clean(src_target, show, protection):
    declared = "src/{package_name}" if protection == "disjoint" else "{app_name}"
    ignored = "*.tmp\n" if protection == "nonignored" else "press/\n*.tmp\n"
    _declare(
        src_target, declared, ignored, tracked=protection in ("tracked", "missing")
    )
    if protection == "missing":
        for relative in ("press/press-receipt.toml", "press/press-answers.toml"):
            (src_target / relative).unlink()
    existing = {
        rel: (src_target / rel).read_bytes()
        for rel in CONTROL_FILES
        if (src_target / rel).exists()
    }
    cache = _cache(
        src_target, "src/demo_widget" if protection == "disjoint" else "press"
    )
    before = capture_surface_snapshot(src_target)

    _assert_clean_allowed(src_target, show, cache)

    assert {rel: (src_target / rel).read_bytes() for rel in existing} == existing
    if protection == "missing":
        assert not (src_target / "press/press-receipt.toml").exists()
        assert not (src_target / "press/press-answers.toml").exists()
    assert capture_surface_snapshot(src_target) == before


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("tracked", [False, True])
def test_conditional_include_case_alias_uses_exact_entry_protection(
    src_target, capsys, monkeypatch, show, tracked
):
    _declare(src_target, "src/{package_name}", "*.policy\n*.tmp\n")
    policy = src_target / "src/demo_widget/extra.policy"
    policy.write_bytes(INCLUDE_BYTES)
    alias = src_target / "SRC/DEMO_WIDGET/EXTRA.POLICY"
    if not alias.exists():
        pytest.skip("requires a case-insensitive filesystem path alias")
    assert os.path.samefile(policy, alias)
    if tracked:
        _git(src_target, "add", "-f", "src/demo_widget/extra.policy")
    _include(src_target, alias)
    cache = _cache(src_target)

    if tracked:
        _assert_clean_allowed(src_target, show, cache)
    else:
        _assert_refused(
            src_target, show, "declared Git config include", capsys, monkeypatch
        )
        assert cache.read_bytes() == CACHE_BYTES
    assert policy.read_bytes() == INCLUDE_BYTES


@posix_only
@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("kind", ["include", "control"])
def test_distinct_hardlink_to_tracked_entry_does_not_protect_input(
    src_target, capsys, monkeypatch, show, kind
):
    if kind == "include":
        declared = "src/{package_name}"
        relative = "src/demo_widget/extra.policy"
    else:
        declared = "{app_name}"
        relative = "press/press-receipt.toml"
    _declare(src_target, declared, f"{relative}\n*.tmp\n")
    policy = src_target / relative
    if kind == "control":
        _git(src_target, "rm", "--cached", "--", relative)
        policy.unlink()
    tracked = src_target / "tracked-input"
    tracked.write_bytes(INCLUDE_BYTES)
    _git(src_target, "add", "tracked-input")
    os.link(tracked, policy)
    assert os.path.samefile(tracked, policy)
    if kind == "include":
        _include(src_target, policy)
    cache = _cache(src_target, "src/demo_widget" if kind == "include" else "press")

    diagnostic = (
        "declared Git config include"
        if kind == "include"
        else "press-owned control file"
    )
    _assert_refused(src_target, show, diagnostic, capsys, monkeypatch)

    assert policy.read_bytes() == INCLUDE_BYTES
    assert tracked.read_bytes() == INCLUDE_BYTES
    assert cache.read_bytes() == CACHE_BYTES


@requires_symlink
@pytest.mark.parametrize("show", [False, True])
def test_dangling_inactive_include_is_present_for_clean_guard(
    src_target, capsys, monkeypatch, show
):
    _declare(src_target, "src/{package_name}", "*.policy\n*.tmp\n")
    policy = src_target / "src/demo_widget/extra.policy"
    policy.symlink_to("missing-include")
    _include(src_target, policy, active=False)
    cache = _cache(src_target)

    _assert_refused(
        src_target, show, "declared Git config include", capsys, monkeypatch
    )

    assert policy.is_symlink()
    assert os.readlink(policy) == "missing-include"
    assert cache.read_bytes() == CACHE_BYTES


@pytest.mark.parametrize("show", [False, True])
def test_inactive_include_directory_is_present_for_clean_guard(
    src_target, capsys, monkeypatch, show
):
    _declare(src_target, "src/{package_name}", "*.policy\n*.tmp\n")
    policy = src_target / "src/demo_widget/extra.policy"
    policy.mkdir()
    child = policy / "keep.txt"
    child.write_bytes(INCLUDE_BYTES)
    _include(src_target, policy, active=False)
    cache = _cache(src_target)

    _assert_refused(
        src_target, show, "declared Git config include", capsys, monkeypatch
    )

    assert child.read_bytes() == INCLUDE_BYTES
    assert cache.read_bytes() == CACHE_BYTES


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("kind", ["include", "control"])
def test_input_presence_metadata_error_refuses_instead_of_treating_missing(
    src_target, capsys, monkeypatch, show, kind
):
    relative = (
        "src/demo_widget/extra.policy"
        if kind == "include"
        else "press/press-receipt.toml"
    )
    declared = "src/{package_name}" if kind == "include" else "{app_name}"
    _declare(src_target, declared, f"{relative}\n*.tmp\n")
    policy = src_target / relative
    if kind == "include":
        policy.write_bytes(INCLUDE_BYTES)
        _include(src_target, policy)
    else:
        _git(src_target, "rm", "--cached", "--", relative)
    original = policy.read_bytes()
    cache = _cache(src_target, "src/demo_widget" if kind == "include" else "press")
    real_capture = clean_cli.capture_surface_snapshot
    real_lstat = Path.lstat

    def deny_input_metadata(path, *args, **kwargs):
        if path == policy:
            raise PermissionError("input metadata unavailable")
        return real_lstat(path, *args, **kwargs)

    def capture_then_deny(target):
        snapshot = real_capture(target)
        monkeypatch.setattr(Path, "lstat", deny_input_metadata)
        return snapshot

    monkeypatch.setattr(clean_cli, "capture_surface_snapshot", capture_then_deny)
    _assert_refused(
        src_target,
        show,
        "input metadata unavailable",
        capsys,
        monkeypatch,
        overlap=False,
    )

    assert policy.read_bytes() == original
    assert cache.read_bytes() == CACHE_BYTES
