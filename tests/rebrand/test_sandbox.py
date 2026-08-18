"""List-driven, ARG_MAX-safe, submodule-aware sandbox (Task 11).

``make_sandbox`` builds a faithful, isolated git copy of the target that
``press verify`` presses. The overriding invariant under test: every git op
and file write lands inside the owned sandbox — NEVER the real target, cwd, or
$HOME (the 152-file-wipe class). The four plan cases (a-d) plus a
one-commit/synthetic-identity/target-untouched assertion are exercised here;
all fixtures and decoys live strictly under ``tmp_path`` and every git op is
routed through ``git -C <sandbox>`` so the autouse containment guard is
satisfied.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from template_press.rebrand.safety import ContainmentError, SafetyError
from template_press.rebrand.sandbox import Sandbox, make_sandbox

from .conftest import make_target, posix_only, requires_symlink


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.stdout


def _rev_parse_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def _committed_paths(sandbox: Path) -> set[str]:
    out = _git(sandbox, "ls-tree", "-r", "--name-only", "HEAD")
    return {line for line in out.splitlines() if line}


def _dest_root(tmp_path: Path) -> Path:
    dest = tmp_path / "dest"
    dest.mkdir()
    return dest


# ---------------------------------------------------------------------------
# (a) an untracked-but-listed file AND a symlink land in the sandbox as-is
# ---------------------------------------------------------------------------
@requires_symlink
def test_untracked_file_and_symlink_land_as_is(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    # Untracked (never `git add`ed) but non-ignored — copy_paths lists it via
    # `ls-files --others --exclude-standard`.
    (target / "notes_untracked.txt").write_text("hello demo_widget\n", encoding="utf-8")
    # A tracked symlink whose readlink target must survive verbatim.
    (target / "link_to_readme").symlink_to("README.md")
    _git(target, "add", "link_to_readme")
    _git(target, "commit", "-q", "-m", "add symlink")

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    untracked = result.path / "notes_untracked.txt"
    assert untracked.is_file()
    assert untracked.read_text(encoding="utf-8") == "hello demo_widget\n"

    link = result.path / "link_to_readme"
    assert link.is_symlink()
    assert os.readlink(link) == "README.md"

    committed = _committed_paths(result.path)
    assert "notes_untracked.txt" in committed
    assert "link_to_readme" in committed


# ---------------------------------------------------------------------------
# (b) a `git add -f` gitignored file is present in the sandbox commit
# ---------------------------------------------------------------------------
def test_force_added_gitignored_file_in_commit(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    with (target / ".gitignore").open("a", encoding="utf-8") as f:
        f.write("secret.env\n")
    (target / "secret.env").write_text("TOKEN=shh\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "add", "-f", "secret.env")
    _git(target, "commit", "-q", "-m", "force-add ignored secret")

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    assert (result.path / "secret.env").is_file()
    # The sandbox copies .gitignore too (which ignores secret.env); only a
    # forced add (`-f`) lands it in the sandbox commit.
    assert "secret.env" in _committed_paths(result.path)


def test_present_unmaterializable_node_refuses_sandbox(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    occupied = target / "occupied"
    occupied.write_text("tracked file\n", encoding="utf-8")
    _git(target, "add", occupied.name)
    _git(target, "commit", "-q", "-m", "add occupied")
    occupied.unlink()
    occupied.mkdir()

    with pytest.raises(SafetyError, match="cannot materialize"):
        make_sandbox(target, _dest_root(tmp_path))


def test_file_changed_to_directory_after_copy_inventory_refuses_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import template_press.rebrand.sandbox as sandbox_mod

    target = make_target(tmp_path)
    source = target / "source.txt"
    source.write_text("tracked file\n", encoding="utf-8")
    _git(target, "add", source.name)
    _git(target, "commit", "-q", "-m", "add source")
    displaced = target / "displaced.txt"
    real_copy_paths = sandbox_mod.copy_paths

    def capture_then_replace(repo: Path):
        entries = real_copy_paths(repo)
        source.rename(displaced)
        source.mkdir()
        return entries

    monkeypatch.setattr(sandbox_mod, "copy_paths", capture_then_replace)

    with pytest.raises(SafetyError, match="not regular"):
        make_sandbox(target, _dest_root(tmp_path))


@posix_only
def test_sandbox_preserves_legal_posix_punctuation_names(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    names = ("colon:name.txt", "back\\slash.txt")
    for name in names:
        (target / name).write_text("content\n", encoding="utf-8")
    _git(target, "add", "--", *names)
    _git(target, "commit", "-q", "-m", "add punctuation names")

    result = make_sandbox(target, _dest_root(tmp_path))

    for name in names:
        assert (result.path / name).read_text(encoding="utf-8") == "content\n"
    assert not (result.path / "back" / "slash.txt").exists()


# ---------------------------------------------------------------------------
# (b2) a recreated symlink passes target_is_directory matching what it points
# at (Windows needs it on a directory-target link, per the sibling fix in
# engine._retarget_symlinks); asserted via the CALL ARGUMENT rather than
# actual broken/working link behavior, since only a Windows runner can
# observe that directly. Containment is computed ONLY on Windows -- POSIX
# ignores the flag entirely and always passes False, spending zero
# filesystem I/O proving it (a POSIX-side containment walk would itself be a
# probe of every path component, including a possible in-tree mount point).
# The Windows path is exercised on ANY host by patching `os.name` to "nt";
# `os.symlink`'s OWN handling of the flag is unaffected by that patch (POSIX
# accepts and ignores it either way), so the real symlink still gets created
# correctly underneath the patch.
# ---------------------------------------------------------------------------
@requires_symlink
def test_posix_symlink_to_directory_target_always_passes_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = make_target(tmp_path)
    (target / "realdir").mkdir()
    (target / "realdir" / "f.txt").write_text("x\n", encoding="utf-8")
    (target / "link_to_dir").symlink_to("realdir", target_is_directory=True)
    _git(target, "add", "realdir/f.txt", "link_to_dir")
    _git(target, "commit", "-q", "-m", "add dir symlink")

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name == "link_to_dir":
            calls.append((src, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    make_sandbox(target, _dest_root(tmp_path))

    assert calls == [("realdir", False)]


@requires_symlink
def test_windows_symlink_to_directory_target_passes_target_is_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import template_press.rebrand.sandbox as sandbox_mod

    target = make_target(tmp_path)
    (target / "realdir").mkdir()
    (target / "realdir" / "f.txt").write_text("x\n", encoding="utf-8")
    (target / "link_to_dir").symlink_to("realdir", target_is_directory=True)
    _git(target, "add", "realdir/f.txt", "link_to_dir")
    _git(target, "commit", "-q", "-m", "add dir symlink")

    # Patches the module's OWN flag, not the real `os.name` -- Python 3.13's
    # pathlib consults `os.name` internally to pick WindowsPath/PosixPath,
    # so patching it globally breaks Path operations mid-test on a POSIX host.
    monkeypatch.setattr(sandbox_mod, "_IS_WINDOWS", True)

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name == "link_to_dir":
            calls.append((src, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    make_sandbox(target, _dest_root(tmp_path))

    assert calls == [("realdir", True)]


@requires_symlink
def test_symlink_to_file_target_passes_target_is_directory_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = make_target(tmp_path)
    (target / "realfile.txt").write_text("x\n", encoding="utf-8")
    (target / "link_to_file").symlink_to("realfile.txt")
    _git(target, "add", "realfile.txt", "link_to_file")
    _git(target, "commit", "-q", "-m", "add file symlink")

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name == "link_to_file":
            calls.append((src, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    make_sandbox(target, _dest_root(tmp_path))

    assert calls == [("realfile.txt", False)]


@requires_symlink
def test_escaping_symlink_target_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tracked symlink whose target resolves OUTSIDE the target repo (here,
    # a directory that genuinely exists and IS a directory) must never be
    # followed to determine target_is_directory -- doing so would mean
    # stat-ing an arbitrary external path (a UNC share, an automount,
    # anything that could hang or trigger network I/O) during a supposedly
    # hermetic sandbox build. Proven two ways: target_is_directory comes
    # through False despite the real external target being a directory, AND
    # Path.is_dir is never even CALLED for this link's path -- not just
    # "returns a safe answer", but "never touches the filesystem at all".
    target = make_target(tmp_path)
    outside_dir = tmp_path / "outside_real_dir"
    outside_dir.mkdir()
    (target / "escaping_link").symlink_to("../outside_real_dir")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "add escaping symlink")

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name == "escaping_link":
            calls.append((src, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    real_is_dir = Path.is_dir
    is_dir_calls: list[Path] = []

    def recording_is_dir(self: Path, *args, **kwargs) -> bool:
        is_dir_calls.append(self)
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", recording_is_dir)

    make_sandbox(target, _dest_root(tmp_path))

    assert calls == [("../outside_real_dir", False)]
    escaping_src = target / "escaping_link"
    assert escaping_src not in is_dir_calls


@requires_symlink
def test_pivot_symlink_target_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `link -> pivot/dir` looks lexically contained (symlink_target_posix
    # sees only the string "pivot/dir") -- but `pivot` is ITSELF a tracked
    # symlink whose OWN target is outside the target tree. A naive follow of
    # `link`'s target would cross `pivot` to reach outside. Proven exactly
    # like the escaping-target case: target_is_directory stays False despite
    # the real chained target being a directory, and Path.is_dir is never
    # called with a path that would cross the pivot.
    target = make_target(tmp_path)
    outside_dir = tmp_path / "outside_pivot_dir"
    outside_dir.mkdir()
    (target / "pivot").symlink_to("../outside_pivot_dir", target_is_directory=True)
    (target / "pivot_link").symlink_to("pivot/nonexistent")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "add pivot symlink chain")

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name in ("pivot", "pivot_link"):
            calls.append((Path(dst).name, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    real_is_dir = Path.is_dir
    is_dir_calls: list[Path] = []

    def recording_is_dir(self: Path, *args, **kwargs) -> bool:
        is_dir_calls.append(self)
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", recording_is_dir)

    make_sandbox(target, _dest_root(tmp_path))

    pivot_link_call = next(c for c in calls if c[0] == "pivot_link")
    assert pivot_link_call == ("pivot_link", False)
    pivot_link_src = target / "pivot_link"
    assert pivot_link_src not in is_dir_calls


@requires_symlink
def test_single_component_pivot_symlink_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `link -> pivot` (a SINGLE-component target, no further path segment
    # under it) is the direct-destination case the ancestor-only walk used
    # to skip entirely: `"pivot".split("/")[:-1]` is `[]`, zero iterations,
    # vacuously "safely contained". `pivot` itself — the direct
    # destination — must be checked too, not just its ancestors.
    target = make_target(tmp_path)
    outside_dir = tmp_path / "outside_single_pivot_dir"
    outside_dir.mkdir()
    (target / "pivot").symlink_to(
        "../outside_single_pivot_dir", target_is_directory=True
    )
    (target / "direct_link").symlink_to("pivot")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "add single-component pivot chain")

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name in ("pivot", "direct_link"):
            calls.append((Path(dst).name, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    real_is_dir = Path.is_dir
    is_dir_calls: list[Path] = []

    def recording_is_dir(self: Path, *args, **kwargs) -> bool:
        is_dir_calls.append(self)
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", recording_is_dir)

    make_sandbox(target, _dest_root(tmp_path))

    direct_link_call = next(c for c in calls if c[0] == "direct_link")
    assert direct_link_call == ("direct_link", False)
    direct_link_src = target / "direct_link"
    assert direct_link_src not in is_dir_calls


@requires_symlink
def test_dotdot_erasing_pivot_component_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `link -> "pivot/../real_dir"` normalizes (os.path.normpath) to
    # `"real_dir"`, LEXICALLY erasing "pivot" from the string the
    # containment walk would otherwise check — even though the real
    # filesystem walk a naive follow performs still steps through the
    # tracked `pivot` symlink on its way to `real_dir`. `real_dir` itself
    # is a genuine in-tree directory, so this is not caught by any other
    # check; only rejecting any raw `..` component up front closes it.
    target = make_target(tmp_path)
    outside_dir = tmp_path / "outside_dotdot_pivot_dir"
    outside_dir.mkdir()
    (target / "pivot").symlink_to(
        "../outside_dotdot_pivot_dir", target_is_directory=True
    )
    (target / "real_dir").mkdir()
    (target / "real_dir" / ".gitkeep").write_text("", encoding="utf-8")
    (target / "dotdot_link").symlink_to("pivot/../real_dir")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "add dotdot-erasing pivot chain")

    real_is_dir = Path.is_dir
    is_dir_calls: list[Path] = []

    def recording_is_dir(self: Path, *args, **kwargs) -> bool:
        is_dir_calls.append(self)
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", recording_is_dir)

    real_symlink = os.symlink
    calls: list[tuple[str, bool]] = []

    def recording_symlink(src, dst, target_is_directory=False):
        if Path(dst).name == "dotdot_link":
            calls.append((src, target_is_directory))
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    make_sandbox(target, _dest_root(tmp_path))

    assert calls == [("pivot/../real_dir", False)]
    dotdot_link_src = target / "dotdot_link"
    assert dotdot_link_src not in is_dir_calls


@requires_symlink
def test_windows_anchor_link_text_is_rejected_on_any_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `os.path.isabs()` does not recognize Windows root- or drive-relative
    # target text ("\external", "C:external") when evaluated with POSIX
    # semantics — these are rejected directly on the raw link characters
    # instead, so the guard holds regardless of which host runs it. POSIX
    # permits a backslash or colon literally in a symlink target, so both
    # links below are creatable and followable on this host — proving the
    # rejection is a deliberate policy choice, not a filesystem error.
    target = make_target(tmp_path)
    (target / "backslash_link").symlink_to("\\external")
    (target / "drive_link").symlink_to("C:external")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "add windows-anchor-text symlinks")

    real_symlink = os.symlink
    calls: dict[str, tuple[str, bool]] = {}

    def recording_symlink(src, dst, target_is_directory=False):
        name = Path(dst).name
        if name in ("backslash_link", "drive_link"):
            calls[name] = (src, target_is_directory)
        real_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(os, "symlink", recording_symlink)

    real_is_dir = Path.is_dir
    is_dir_calls: list[Path] = []

    def recording_is_dir(self: Path, *args, **kwargs) -> bool:
        is_dir_calls.append(self)
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", recording_is_dir)

    make_sandbox(target, _dest_root(tmp_path))

    # `target_is_directory` is the property under test on every host; the
    # exact `src` text is NOT pinned for "C:external" because Windows
    # itself resolves a drive-relative symlink target to an extended-length
    # absolute form (`\\?\C:\...\external`) on readback -- a real, benign
    # platform quirk in what `readlink` returns, not a rewrite performed by
    # this code (which never rewrites link text) and not a containment
    # weakening (the resolved form still contains `:` and is rejected the
    # same way).
    assert calls["backslash_link"][1] is False
    assert calls["drive_link"][1] is False
    # Proves the False came from a REJECTION, not from `.is_dir()` merely
    # returning False for a target that happens not to exist on this host.
    assert target / "backslash_link" not in is_dir_calls
    assert target / "drive_link" not in is_dir_calls


# ---------------------------------------------------------------------------
# (c) a gitlink path is scannable-by-name AND recorded unavailable
# ---------------------------------------------------------------------------
def _add_gitlink(target: Path, tmp_path: Path, rel: str = "sub") -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q", "-b", "main")
    _git(inner, "config", "user.email", "test@example.com")
    _git(inner, "config", "user.name", "Test")
    (inner / "f.txt").write_text("x\n", encoding="utf-8")
    _git(inner, "add", "-A")
    _git(inner, "commit", "-q", "-m", "inner init")
    sha = _rev_parse_head(inner)
    _git(target, "update-index", "--add", "--cacheinfo", f"160000,{sha},{rel}")
    _git(target, "commit", "-q", "-m", "add gitlink")


def test_gitlink_scannable_and_recorded_unavailable(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    _add_gitlink(target, tmp_path)

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    # The gitlink NAME is scannable: the path components exist as a real dir
    # holding a tracked placeholder (submodule content is unavailable).
    placeholder = result.path / "sub" / ".press-submodule-unavailable"
    assert placeholder.is_file()
    assert "sub/.press-submodule-unavailable" in _committed_paths(result.path)
    assert "sub" in result.unavailable_submodules


@posix_only
def test_dirty_gitlink_fifo_refuses_sandbox(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    _add_gitlink(target, tmp_path)
    os.mkfifo(target / "sub")

    with pytest.raises(SafetyError, match="cannot materialize"):
        make_sandbox(target, _dest_root(tmp_path))


# ---------------------------------------------------------------------------
# (d) a control-path symlink is rejected and NOTHING is written outside
# ---------------------------------------------------------------------------
@requires_symlink
def test_control_path_symlink_rejected_writes_nothing(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    # A symlinked control dir could redirect a control-file write out of the
    # tree — assert_control_real (Task 3) rejects it BEFORE any copy.
    (target / "press").symlink_to(outside)

    dest_root = _dest_root(tmp_path)
    with pytest.raises(ContainmentError):
        make_sandbox(target, dest_root)

    # Nothing was written into the external decoy, and the sandbox dir was
    # never even created (rejection precedes any write).
    assert list(outside.iterdir()) == []
    assert not (dest_root / "self").exists()


# ---------------------------------------------------------------------------
# G3 (crash): a tracked path carrying a non-UTF-8 byte (surfaced by copy_paths
# via surrogateescape) must round-trip through make_sandbox's NUL pathspec
# stdin without raising UnicodeEncodeError. A non-UTF-8 filename cannot be
# created on APFS, so copy_paths + the contained writes are stubbed and the git
# ops captured; the assertion is that the add-list stdin encodes with
# surrogateescape and decodes back to the ORIGINAL bytes.
# ---------------------------------------------------------------------------
def test_non_utf8_pathspec_encodes_without_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    import template_press.rebrand.sandbox as sandbox_mod
    from template_press.rebrand.engine import PathEntry

    target = make_target(tmp_path)
    dest_root = _dest_root(tmp_path)

    bad_bytes = b"vendored/asset\xe9"
    bad_rel = Path(bad_bytes.decode("utf-8", "surrogateescape"))

    # A gitlink entry appends its rel to the add-list WITHOUT reading the
    # (non-creatable) source path; the writes are stubbed so nothing touches disk.
    monkeypatch.setattr(
        sandbox_mod, "copy_paths", lambda _t: [PathEntry(rel=bad_rel, kind="gitlink")]
    )
    monkeypatch.setattr(sandbox_mod, "safe_mkdir", lambda root, rel: Path(root) / rel)
    monkeypatch.setattr(sandbox_mod, "safe_write", lambda root, rel, data: None)

    captured: dict[str, bytes | None] = {}

    def fake_run_git(sandbox, env, *args, stdin=None):
        if args and args[0] == "add":
            captured["stdin"] = stdin

    monkeypatch.setattr(sandbox_mod, "_run_git", fake_run_git)

    # Before the fix this raises UnicodeEncodeError on the surrogate byte.
    result = make_sandbox(target, dest_root)

    assert captured.get("stdin") is not None
    assert bad_bytes in captured["stdin"]  # round-tripped to the original bytes
    assert bad_rel.as_posix() in result.unavailable_submodules


# ---------------------------------------------------------------------------
# exactly one commit, synthetic identity, real target untouched
# ---------------------------------------------------------------------------
def test_commit_synthetic_identity_and_target_untouched(
    tmp_path: Path,
    snapshot_target: Callable[[Path], tuple[str, str]],
    assert_target_unchanged: Callable[[Path, tuple[str, str]], None],
) -> None:
    target = make_target(tmp_path)
    before = snapshot_target(target)

    dest_root = _dest_root(tmp_path)
    result = make_sandbox(target, dest_root)

    assert isinstance(result, Sandbox)
    log = _git(result.path, "log", "--format=%an%x00%ae%x00%cn%x00%ce").splitlines()
    assert len(log) == 1
    author_name, author_email, committer_name, committer_email = log[0].split("\0")
    assert author_name == "press-verify"
    assert author_email == "verify@localhost"
    assert committer_name == "press-verify"
    assert committer_email == "verify@localhost"

    # The real target was only ever read (copy_paths + byte reads); no git op
    # or write touched it.
    assert_target_unchanged(target, before)
