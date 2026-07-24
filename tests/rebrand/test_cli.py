import os
import subprocess
import sys
from pathlib import Path

import pytest

from template_press.rebrand.cli import display_name_problem, main
from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, SOURCE, requires_symlink, write_answers_file


def write_source_config(target: Path) -> None:
    (target / "press").mkdir(exist_ok=True)
    (target / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "commit", "-q", "-m", "add source config"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def write_answers(base: Path) -> Path:
    return write_answers_file(base, DEST)


def test_missing_target_dir_exits_2(tmp_path: Path):
    answers = write_answers(tmp_path)
    code = main(["--target", str(tmp_path / "nope"), "--config", str(answers)])
    assert code == 2


def test_dirty_target_exits_2(src_target: Path, tmp_path: Path):
    write_source_config(src_target)
    (src_target / "dirty.txt").write_text("x", encoding="utf-8")
    answers = write_answers(tmp_path)
    assert main(["--target", str(src_target), "--config", str(answers)]) == 2


def test_missing_source_config_prints_proposal_and_exits_2(
    src_target: Path, tmp_path: Path, capsys
):
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2
    out = capsys.readouterr().out
    assert "[identity]" in out and 'package_name = "demo_widget"' in out
    assert "--accept-discovery" in out


def test_mismatched_source_config_fails_loudly_no_writes(
    src_target: Path, tmp_path: Path, capsys
):
    """The R2 regression: wrong identity must be a hard stop, not a half-run."""
    wrong = SOURCE.__class__(
        **{**SOURCE.as_dict_prompted(), "package_name": "other_pkg"}
    )
    (src_target / "press").mkdir()
    (src_target / SOURCE_CONFIG_REL).write_text(
        render_source_config(wrong), encoding="utf-8"
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "cfg"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    before = (src_target / "README.md").read_text(encoding="utf-8")
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2
    assert "package_name" in capsys.readouterr().out
    assert (src_target / "README.md").read_text(encoding="utf-8") == before
    assert not (src_target / RECEIPT_REL).exists()


def test_dry_run_prints_plan_and_writes_nothing(
    src_target: Path, tmp_path: Path, capsys
):
    write_source_config(src_target)
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
    assert code == 0
    assert "README.md" in capsys.readouterr().out
    assert "demo-widget" in (src_target / "README.md").read_text(encoding="utf-8")


def test_happy_path_presses_verifies_and_writes_receipt(
    src_target: Path, tmp_path: Path
):
    write_source_config(src_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert (src_target / RECEIPT_REL).is_file()
    assert (src_target / "src" / "potato_launcher" / "cli.py").is_file()
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "demo" not in readme and "Compress" in readme


def test_success_updates_source_config_to_new_identity(
    src_target: Path, tmp_path: Path
):
    write_source_config(src_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert load_source_config(src_target, override=None) == DEST


def test_leak_after_apply_exits_1_and_writes_no_receipt(
    src_target: Path, tmp_path: Path
):
    """EMP-01 regression: a partial rebrand must fail loudly, no receipt."""
    write_source_config(src_target)
    # Excluded from rewriting but NOT from the doctor scan → guaranteed leak.
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(
        '[rules]\nextra_exclude_files = ["notes.md"]\n', encoding="utf-8"
    )
    (src_target / "notes.md").write_text(
        "demo_widget must survive rewriting\n", encoding="utf-8"
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert not (src_target / RECEIPT_REL).exists()


def test_malformed_source_config_exits_2(src_target: Path, tmp_path: Path):
    (src_target / "press").mkdir()
    (src_target / SOURCE_CONFIG_REL).write_text("not [ valid toml", encoding="utf-8")
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2


def test_accept_discovery_never_writes_invalid_identity(tmp_path: Path):
    import subprocess as sp

    repo = tmp_path / "hyphen"
    pkg = repo / "src" / "hyphen_app"
    pkg.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "hyphen_app"\nversion = "0.1.0"\n'
        'authors = [{ name = "A B", email = "a@b.co" }]\n'
        "[project.scripts]\n"
        '"my-app" = "hyphen_app.cli:main"\n',
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@e.co"],
        ["config", "user.name", "T"],
        ["remote", "add", "origin", "https://github.com/ab/hyphen-app.git"],
        ["add", "-A"],
        ["commit", "-q", "-m", "x"],
    ):
        sp.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)  # noqa: S603, S607
    answers = write_answers(tmp_path)
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(answers),
            "--accept-discovery",
            "--allow-dirty",
        ]
    )
    assert code == 2
    assert not (repo / SOURCE_CONFIG_REL).exists()


def test_identical_identity_press_exits_2(src_target: Path, tmp_path: Path):
    write_source_config(src_target)
    answers = tmp_path / "same.toml"
    answers.write_text(
        "[answers]\n"
        + "\n".join(f'{k} = "{v}"' for k, v in SOURCE.as_dict_prompted().items())
        + "\n",
        encoding="utf-8",
    )
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="read-only-dir fault injection is POSIX-only (Windows ignores POSIX "
    "dir perms); the mid-apply OSError->exit-1 path is covered portably by "
    "test_press_outcome_env_error_on_apply_ioerror",
)
def test_mid_apply_oserror_exits_1_with_partial_warning(
    src_target: Path, tmp_path: Path, capsys
):
    write_source_config(src_target)
    # A token-bearing file in a read-only DIRECTORY. safe_write is atomic
    # (temp file in the parent dir + os.replace), so a read-only *leaf file* is
    # no longer a fault surface — os.replace swaps the dir entry regardless of
    # the file's own mode. A non-writable *parent* makes safe_write's temp
    # creation raise PermissionError (OSError) mid-apply. The dir sorts last
    # (zz_), so earlier files are rewritten first — proving the partial path.
    rodir = src_target / "zz_readonly"
    rodir.mkdir()
    readonly = rodir / "note.md"
    readonly.write_text("demo_widget survives here\n", encoding="utf-8")
    rodir.chmod(0o555)
    answers = write_answers(tmp_path)
    try:
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
        )
    finally:
        rodir.chmod(0o755)  # let pytest clean the tmp dir
    assert code == 1
    assert "PARTIALLY rewritten" in capsys.readouterr().err
    assert not (src_target / RECEIPT_REL).exists()


def test_failed_lock_regeneration_exits_1_no_receipt(
    src_target: Path, tmp_path: Path, monkeypatch, capsys
):
    """Greptile PR#15: a stale lockfile must never get a verified receipt."""
    import subprocess as sp

    from template_press.rebrand import cli as cli_mod

    write_source_config(src_target)
    (src_target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")
    real_run = sp.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "lock"]:
            return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert "lockfile regeneration failed" in capsys.readouterr().err
    assert not (src_target / RECEIPT_REL).exists()


@requires_symlink
def test_regen_refuses_symlinked_lockfile_no_external_write(
    tmp_path: Path, monkeypatch
):
    """M1: a symlinked uv.lock must be refused, never written through.

    `uv.lock` -> external file under tmp_path. `_regenerate_lockfiles` must
    reject it on the leaf is_symlink() check BEFORE ever invoking `uv lock`,
    so the external file is never touched.
    """
    import subprocess as sp

    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.engine import ApplyReport
    from template_press.rebrand.rules import DEFAULT_RULES

    target = tmp_path / "target"
    target.mkdir()
    external = tmp_path / "external.lock"
    external_content = "external-untouched==1.0.0\n"
    external.write_text(external_content, encoding="utf-8")
    external_inode = external.stat().st_ino

    (target / "uv.lock").symlink_to(external)

    uv_lock_calls = []

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "lock"]:
            uv_lock_calls.append(cmd)
            # Simulates what a real `uv lock` does: write the relative
            # lockfile path in cwd. If the symlink guard is bypassed, this
            # follows the symlink and mutates the external file.
            (Path(kwargs["cwd"]) / "uv.lock").write_text(
                "mutated-by-uv-lock\n", encoding="utf-8"
            )
            return sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    report = ApplyReport()
    failed = cli_mod._regenerate_lockfiles(target, DEFAULT_RULES, report)

    assert uv_lock_calls == []  # uv lock must never run against a symlink
    assert failed == ["uv.lock"]
    assert any("symlink" in s for s in report.skipped)
    assert external.read_text(encoding="utf-8") == external_content
    assert external.stat().st_ino == external_inode


def test_uv_lock_regen_uses_scrubbed_uv_env(tmp_path: Path, monkeypatch) -> None:
    """G5: `uv lock` regeneration must run with a SCRUBBED UV_* environment.

    A poisoned ``UV_*`` override (cache/index/working-dir) could steer the one
    external-tool write the press performs off the target. `_regenerate_lockfiles`
    must pass ``env=scrubbed_uv_env()`` — an explicit env carrying no ``UV_*``.
    """
    import subprocess as sp

    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.engine import ApplyReport
    from template_press.rebrand.rules import DEFAULT_RULES

    target = tmp_path / "target"
    target.mkdir()
    (target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")

    monkeypatch.setenv("UV_CACHE_DIR", "/tmp/evil-cache")  # noqa: S108
    monkeypatch.setenv("UV_INDEX_URL", "https://evil.example/simple")

    captured: dict[str, object] = {}

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "lock"]:
            captured["env"] = kwargs.get("env")
            return sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    report = ApplyReport()
    failed = cli_mod._regenerate_lockfiles(target, DEFAULT_RULES, report)

    assert failed == []
    assert report.regenerated == ["uv.lock"]
    env = captured["env"]
    # An explicit env was passed (not the ambient environment) ...
    assert env is not None
    # ... and it carries NO UV_* overrides (the poison was scrubbed).
    assert not any(k.startswith("UV_") for k in env)


def test_dry_run_with_accept_discovery_writes_nothing(
    src_target: Path, tmp_path: Path, capsys
):
    answers = write_answers(tmp_path)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--accept-discovery",
            "--dry-run",
        ]
    )
    assert code == 0
    assert not (src_target / SOURCE_CONFIG_REL).exists()
    assert "would write" in capsys.readouterr().out


def test_chained_identity_collision_exits_2(src_target: Path, tmp_path: Path):
    """Sweep F2: dest package == source app must refuse, not double-press."""
    wrong_src = SOURCE.__class__(
        **{**SOURCE.as_dict_prompted(), "package_name": "alpha", "app_name": "beta"}
    )
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / SOURCE_CONFIG_REL).write_text(
        render_source_config(wrong_src), encoding="utf-8"
    )
    # collision check runs before mismatch would matter — craft answers only
    dest = {
        **DEST.as_dict_prompted(),
        "package_name": "beta",
        "app_name": "gamma",
    }
    answers = tmp_path / "coll.toml"
    answers.write_text(
        "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
        encoding="utf-8",
    )
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2


def test_embedding_old_app_name_exits_2_with_guidance(
    src_target: Path, tmp_path: Path, capsys
):
    """Sweep F4: press -> press_two would deadlock the verifier; refuse."""
    write_source_config(src_target)
    dest = {**DEST.as_dict_prompted(), "app_name": "press_two"}
    answers = tmp_path / "embed.toml"
    answers.write_text(
        "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
        encoding="utf-8",
    )
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2
    assert "intermediate identity" in capsys.readouterr().err


def test_display_name_ambiguous_replacement_source_exits_2(
    src_target: Path, tmp_path: Path
):
    """F2: source display_name equals source app_name's value ("press") but
    the two fields map to DIFFERENT destinations — build_plan's
    replacement_pairs must refuse (ValidationError -> exit 2) rather than
    silently applying one pair and starving the other."""
    src = Identity(**{**SOURCE.as_dict_prompted(), "display_name": "press"})
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / SOURCE_CONFIG_REL).write_text(
        render_source_config(src), encoding="utf-8"
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add source config"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    dest = {**DEST.as_dict_prompted(), "app_name": "tool", "display_name": "Tool Pro"}
    answers = tmp_path / "ambiguous.toml"
    answers.write_text(
        "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
        encoding="utf-8",
    )
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2


def test_extra_exclude_dirs_no_longer_hides_leaks(src_target: Path, tmp_path: Path):
    """Sweep F3: rewrite dir-excludes must not blind the doctor."""
    write_source_config(src_target)
    legacy = src_target / "legacy"
    legacy.mkdir()
    (legacy / "old.txt").write_text("demo_widget stays\n", encoding="utf-8")
    (src_target / "press" / "press-rules.toml").write_text(
        '[rules]\nextra_exclude_dirs = ["legacy"]\n', encoding="utf-8"
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert not (src_target / RECEIPT_REL).exists()


def test_verify_ignore_is_the_sanctioned_ignore_set(src_target: Path, tmp_path: Path):
    write_source_config(src_target)
    legacy = src_target / "legacy"
    legacy.mkdir()
    (legacy / "old.txt").write_text("demo_widget stays on purpose\n", encoding="utf-8")
    (src_target / "press" / "press-rules.toml").write_text(
        '[rules]\nextra_exclude_dirs = ["legacy"]\nverify_ignore = ["legacy"]\n',
        encoding="utf-8",
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert (src_target / RECEIPT_REL).is_file()
    text = (legacy / "old.txt").read_text(encoding="utf-8")
    assert "demo_widget" in text  # deliberately preserved


def test_rule_scope_migrated_by_ancestor_rename_exits_1_no_receipt(
    src_target: Path, tmp_path: Path
):
    """F1 e2e: a paths=true [[replace]] rule scoped `files=["press_docs/**"]`
    guards a filename under a directory the ORDINARY token-rename pass ALSO
    renames (press_docs/ -> potato_docs/). `_rename_pass_once` collapses
    each pass to its shallowest differing ancestor, so the directory rename
    lands on pass 1 and the rule's own `files` scope no longer matches by
    the time the SAME rule gets to re-evaluate against the file on pass 2 —
    the rule never fires and the file keeps its stale name (0008's
    documented rewrite-side scope-migration limitation, not fixed here).
    The doctor must catch that leftover instead of certifying a false
    receipt (a receipt/verify contradiction)."""
    write_source_config(src_target)
    docs = src_target / "press_docs"
    docs.mkdir()
    (docs / "_press_guide.md").write_text("x\n", encoding="utf-8")
    (src_target / "press" / "press-rules.toml").write_text(
        "[[replace]]\n"
        'pattern = "_{app_name}_guide.md"\n'
        'files   = ["press_docs/**"]\n'
        "paths   = true\n"
        "content = false\n"
        'reason  = "doc filename scoped to its own dir"\n',
        encoding="utf-8",
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert not (src_target / RECEIPT_REL).exists()
    # the exact leftover shape: dir renamed, file inside kept its stale name
    assert (src_target / "potato_docs" / "_press_guide.md").exists()


def test_rule_scope_stable_dir_no_ancestor_rename_still_receipts(
    src_target: Path, tmp_path: Path
):
    """Negative control: the identical rule shape, scoped to a directory
    that is never itself renamed (no app_name token in its own name), must
    still press clean end-to-end — `renamed` threading must not manufacture
    a false positive when there is no ancestor shift to reverse-map."""
    write_source_config(src_target)
    docs = src_target / "docs"
    docs.mkdir()
    (docs / "_press_guide.md").write_text("x\n", encoding="utf-8")
    (src_target / "press" / "press-rules.toml").write_text(
        "[[replace]]\n"
        'pattern = "_{app_name}_guide.md"\n'
        'files   = ["docs/**"]\n'
        "paths   = true\n"
        "content = false\n"
        'reason  = "doc filename scoped to a stable dir"\n',
        encoding="utf-8",
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert (src_target / RECEIPT_REL).is_file()
    assert (docs / "_potato_guide.md").exists()
    assert not (docs / "_press_guide.md").exists()


def test_partial_rebrand_keeping_author_verifies(src_target: Path, tmp_path: Path):
    """Fable sweep finding: unchanged fields are not leaks."""
    write_source_config(src_target)
    dest = {
        **DEST.as_dict_prompted(),
        "author": SOURCE.author,
        "email": SOURCE.email,
    }
    answers = tmp_path / "partial.toml"
    answers.write_text(
        "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
        encoding="utf-8",
    )
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert (src_target / RECEIPT_REL).is_file()


def test_accept_discovery_mismatch_leaves_no_source_config(tmp_path: Path):
    """Docs sweep W1: exit 2 must mean no writes, even with --accept-discovery."""
    import subprocess as sp

    repo = tmp_path / "nolayout"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "ghost_pkg"\nversion = "0.1.0"\n'
        'authors = [{ name = "G Host", email = "g@h.co" }]\n'
        "[project.scripts]\n"
        'ghost = "ghost_pkg.cli:main"\n',
        encoding="utf-8",
    )
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@e.co"],
        ["config", "user.name", "T"],
        ["remote", "add", "origin", "https://github.com/gh/ghost-pkg.git"],
        ["add", "-A"],
        ["commit", "-q", "-m", "x"],
    ):
        sp.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)  # noqa: S603, S607
    answers = write_answers(tmp_path)
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(answers),
            "--accept-discovery",
            "--allow-dirty",
        ]
    )
    assert code == 2  # layout mismatch: no package dir exists
    assert not (repo / SOURCE_CONFIG_REL).exists()


@requires_symlink
def test_rebrand_symlinked_control_dir_exits_2_no_write(
    src_target: Path, tmp_path: Path
):
    """D8: a symlinked press/ control dir is a hard exit-2 precondition error;
    nothing is written through the link (the external decoy stays empty)."""
    decoy = tmp_path / "outside" / "decoy"
    decoy.mkdir(parents=True)
    os.symlink(decoy, src_target / "press", target_is_directory=True)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2
    assert list(decoy.iterdir()) == []  # nothing written through the symlink


def test_accept_discovery_bad_rules_toml_leaves_no_source_config(
    src_target: Path, tmp_path: Path
):
    """Fable final review: rules/plan failures after the deferred write must
    not leave a source-config behind on an exit-2 path."""
    (src_target / "press").mkdir()
    (src_target / "press" / "press-rules.toml").write_text(
        "not [ valid toml", encoding="utf-8"
    )
    answers = write_answers(tmp_path)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--accept-discovery",
            "--allow-dirty",
        ]
    )
    assert code == 2
    assert not (src_target / SOURCE_CONFIG_REL).exists()


def test_press_outcome_env_error_on_regen_failure(tmp_path: Path, monkeypatch):
    """B5/C-7/C-11: nonzero regen surfaces as PressOutcome.env_error, not a leak."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    monkeypatch.setattr(cli_mod, "_regenerate_lockfiles", lambda *a, **k: ["uv.lock"])

    direct_target = make_target(tmp_path / "direct", layout="src")
    write_source_config(direct_target)
    rules = load_rules(direct_target)
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules)
    assert outcome.env_error is not None
    assert outcome.leaked is False

    main_target = make_target(tmp_path / "main", layout="src")
    write_source_config(main_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(main_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1


def test_press_outcome_env_error_on_missing_tool(tmp_path: Path, monkeypatch):
    """A missing regen tool (FileNotFoundError) normalizes into env_error."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("uv: command not found")

    monkeypatch.setattr(cli_mod, "_regenerate_lockfiles", boom)

    target = make_target(tmp_path / "direct", layout="src")
    write_source_config(target)
    rules = load_rules(target)
    outcome = cli_mod._press(target, SOURCE, DEST, rules)
    assert outcome.env_error is not None


def test_press_outcome_env_error_on_apply_ioerror(tmp_path: Path, monkeypatch):
    """A mid-apply OSError means `report` never comes into existence."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli_mod, "apply", boom)

    direct_target = make_target(tmp_path / "direct", layout="src")
    write_source_config(direct_target)
    rules = load_rules(direct_target)
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules)
    assert outcome.env_error is not None
    assert outcome.renamed == []

    main_target = make_target(tmp_path / "main", layout="src")
    write_source_config(main_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(main_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1


def test_press_outcome_env_error_on_receipt_write_failure(tmp_path: Path, monkeypatch):
    """A post-verification receipt-write failure is still an env failure."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    def boom(*_args, **_kwargs):
        raise OSError("cannot write receipt")

    monkeypatch.setattr(cli_mod, "write_receipt", boom)

    direct_target = make_target(tmp_path / "direct", layout="src")
    write_source_config(direct_target)
    rules = load_rules(direct_target)
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules)
    assert outcome.env_error is not None

    main_target = make_target(tmp_path / "main", layout="src")
    write_source_config(main_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(main_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1


def test_press_outcome_success_no_env_error(tmp_path: Path):
    """A clean press yields a PressOutcome with no env_error and no leak."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    direct_target = make_target(tmp_path / "direct", layout="src")
    write_source_config(direct_target)
    rules = load_rules(direct_target)
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules)
    assert isinstance(outcome, cli_mod.PressOutcome)
    assert outcome.env_error is None
    assert outcome.leaked is False
    assert outcome.renamed  # package dir renamed demo_widget -> potato_launcher
    assert outcome.regenerated == []  # no uv.lock in the fixture

    main_target = make_target(tmp_path / "main", layout="src")
    write_source_config(main_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(main_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0


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


class TestDisplayNameGate:
    def test_half_specified_is_a_problem(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme")
        msg = display_name_problem(src, dst)
        assert msg is not None and "display_name" in msg

    def test_reverse_direction_is_fine(self):
        src = _identity()
        dst = _identity(app_name="acme", display_name="Acme Widget")
        assert display_name_problem(src, dst) is None

    def test_both_or_neither_is_fine(self):
        assert display_name_problem(_identity(), _identity(app_name="acme")) is None
        assert (
            display_name_problem(
                _identity(display_name="Py Launch Blueprint"),
                _identity(display_name="Acme Widget"),
            )
            is None
        )


class TestCollisionsCoverDerivedDisplayForms:
    """F3: `_collisions` compared raw identity values, but replacement uses
    derived display forms — a destination display name whose derived form
    embeds a changed source token slipped through. Repro: source app_name
    "plbp" + source display "Py Launch Blueprint" + dest display "Plbp" ->
    camel("Plbp") == "plbp", the very (changed) source app_name token."""

    def test_derived_camel_form_embedding_changed_app_name_is_a_collision(self):
        from template_press.rebrand.cli import _collisions

        source = _identity(display_name="Py Launch Blueprint")
        dest = _identity(app_name="acme", display_name="Plbp")
        assert _collisions(source, dest) != []

    def test_end_to_end_main_exits_2(self, tmp_path: Path):
        target = tmp_path / "plbp-repo"
        (target / "press").mkdir(parents=True)
        (target / "press" / "press-source.toml").write_text(
            "[identity]\n"
            'package_name = "py_launch_blueprint"\n'
            'repo_name    = "py-launch-blueprint"\n'
            'app_name     = "plbp"\n'
            'author       = "Steve Morin"\n'
            'email        = "steve.morin@gmail.com"\n'
            'owner        = "smorinlabs"\n'
            'display_name = "Py Launch Blueprint"\n',
            encoding="utf-8",
        )
        (target / "pyproject.toml").write_text(
            "[project]\n"
            'name = "py-launch-blueprint"\n'
            'version = "0.1.0"\n'
            'authors = [{name = "Steve Morin", email = "steve.morin@gmail.com"}]\n'
            "[project.scripts]\n"
            'plbp = "py_launch_blueprint.cli:main"\n',
            encoding="utf-8",
        )
        (target / "src" / "py_launch_blueprint").mkdir(parents=True)
        (target / "src" / "py_launch_blueprint" / "__init__.py").write_text(
            '"""Py Launch Blueprint."""\n', encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)  # noqa: S607
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "config", "user.email", "t@example.com"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "config", "user.name", "t"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(target),
                "remote",
                "add",
                "origin",
                "https://github.com/smorinlabs/py-launch-blueprint.git",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "add", "-A"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "commit", "-q", "-m", "seed"],  # noqa: S607
            check=True,
            capture_output=True,
        )
        answers = tmp_path / "answers.toml"
        answers.write_text(
            "[answers]\n"
            'package_name = "acme_widget"\n'
            'repo_name    = "acme-widget"\n'
            'app_name     = "acme"\n'
            'author       = "Ada Lovelace"\n'
            'email        = "ada@example.com"\n'
            'owner        = "acmelabs"\n'
            'display_name = "Plbp"\n',
            encoding="utf-8",
        )
        code = main(["--target", str(target), "--config", str(answers)])
        assert code == 2


class TestSubstringAwareCollisionPreflight:
    """F4: with a field opted into ``[rules] substring_rewrite_fields``, the
    engine rewrites that field SUBSTRING-wide — so ``_collisions`` must catch
    a destination value that embeds the source token WITHOUT a word boundary
    too, not just the boundary-guarded default posture."""

    def test_substring_field_embedded_without_boundary_is_a_collision(self):
        from template_press.rebrand.cli import _collisions

        source = _identity(app_name="press")
        dest = _identity(app_name="tool", repo_name="mypress-tools")
        # Boundary mode: "press" preceded by alnum "y" in "mypress-tools" is
        # NOT a token match — no collision without substring mode.
        assert _collisions(source, dest) == []
        # Substring mode for app_name: the embedded literal IS a collision.
        assert _collisions(source, dest, substring_fields=frozenset({"app_name"})) != []

    def test_end_to_end_substring_collision_exits_2(
        self, src_target: Path, tmp_path: Path, capsys
    ):
        """Repro: pressing app_name press->potato with dest repo_name
        embedding the old app_name as a glued substring — without the
        preflight fix, the repo pair writes it and the substring app pass
        would corrupt it afterward (receipt records the wrong repo name)."""
        write_source_config(src_target)
        (src_target / "press" / "press-rules.toml").write_text(
            '[rules]\nsubstring_rewrite_fields = ["app_name"]\n', encoding="utf-8"
        )
        dest = {**DEST.as_dict_prompted(), "repo_name": "mypress-tools"}
        answers = tmp_path / "substring-collision.toml"
        answers.write_text(
            "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
            encoding="utf-8",
        )
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
        )
        assert code == 2
        err = capsys.readouterr().err
        assert "repo_name" in err and "app_name" in err

    def test_same_identities_without_substring_mode_no_collision(
        self, src_target: Path, tmp_path: Path
    ):
        """Control: the IDENTICAL destination without substring mode declared
        is not a collision — the boundary-guarded default posture is
        unchanged by this fix."""
        write_source_config(src_target)
        dest = {**DEST.as_dict_prompted(), "repo_name": "mypress-tools"}
        answers = tmp_path / "no-substring.toml"
        answers.write_text(
            "[answers]\n" + "\n".join(f'{k} = "{v}"' for k, v in dest.items()) + "\n",
            encoding="utf-8",
        )
        code = main(
            ["--target", str(src_target), "--config", str(answers), "--dry-run"]
        )
        assert code == 0
