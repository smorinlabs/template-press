import errno
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


def test_non_utf8_receipt_exits_2_not_unicode_decode_error(
    src_target: Path, tmp_path: Path, capsys
):
    """Issue #86: a corrupted or hand-edited receipt (non-UTF-8 bytes) must
    fail clean at the precondition check, not crash with UnicodeDecodeError."""
    write_source_config(src_target)
    (src_target / RECEIPT_REL).write_bytes(b"[press]\nverified = true\n\xff\xfe")
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2
    assert "UTF-8" in capsys.readouterr().err


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


def test_dry_run_refuses_reset_that_changes_git_visibility_input(
    src_target: Path, tmp_path: Path, capsys
) -> None:
    write_source_config(src_target)
    (src_target / "press" / "press-rules.toml").write_text(
        '[rules]\nextra_exclude_files = [".gitignore"]\n'
        '[[reset]]\nfile = ".gitignore"\nstub = "other\\n"\n',
        encoding="utf-8",
    )
    _commit_all(src_target, "add visibility reset")
    answers = write_answers(tmp_path)
    before = (src_target / ".gitignore").read_bytes()

    code = main(["--target", str(src_target), "--config", str(answers), "--dry-run"])

    assert code == 2
    assert "reset would change Git visibility input '.gitignore'" in (
        capsys.readouterr().err
    )
    assert (src_target / ".gitignore").read_bytes() == before
    assert not (src_target / RECEIPT_REL).exists()


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

    # Files written BEFORE write_source_config so its `git add -A` + commit
    # covers them: the plan-time output preflight requires uv.lock tracked
    # and clean, and this test's subject is the MID-PRESS failure path.
    (src_target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
        encoding="utf-8",
    )
    write_source_config(src_target)
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
    err = capsys.readouterr().err
    assert "lockfile regeneration failed" in err
    # The per-file reason must reach the operator on the FAILURE path too
    # (dogfood run 4 PROBLEM-23).
    assert "skipped (review):" in err
    assert "command exited" in err
    assert not (src_target / RECEIPT_REL).exists()


@pytest.mark.parametrize(
    "visibility_mutation",
    [
        "gitignore",
        "info_exclude",
        "core_excludes_file",
        "core_ignore_case",
        "conditional_config_activation",
        "index_membership",
    ],
)
def test_declared_command_cannot_change_git_visibility_before_doctor(
    src_target: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
    visibility_mutation: str,
) -> None:
    """Issue #71: a command must not hide a leak from the final doctor."""
    import subprocess as sp

    from template_press.rebrand import cli as cli_mod

    (src_target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
        encoding="utf-8",
    )
    if visibility_mutation == "core_excludes_file":
        config_dir = src_target / "config"
        config_dir.mkdir()
        (config_dir / "excludes").write_text("# baseline\n", encoding="utf-8")
        sp.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(src_target),
                "config",
                "--local",
                "core.excludesFile",
                "config/excludes",
            ],
            check=True,
            capture_output=True,
        )
    elif visibility_mutation in {"core_ignore_case", "conditional_config_activation"}:
        (src_target / ".gitignore").write_text("HIDDEN/\n", encoding="utf-8")
        if visibility_mutation == "core_ignore_case":
            sp.run(  # noqa: S603
                [  # noqa: S607
                    "git",
                    "-C",
                    str(src_target),
                    "config",
                    "--local",
                    "core.ignoreCase",
                    "false",
                ],
                check=True,
                capture_output=True,
            )
    elif visibility_mutation == "index_membership":
        (src_target / ".gitignore").write_text("hidden/\n", encoding="utf-8")
    write_source_config(src_target)
    if visibility_mutation == "conditional_config_activation":
        (src_target / ".git" / "visibility.config").write_text(
            "[core]\nignoreCase = true\n", encoding="utf-8"
        )
        with (src_target / ".git" / "config").open("a", encoding="utf-8") as fh:
            fh.write(
                '\n[includeIf "onbranch:visibility-before"]\n'
                "path = visibility.config\n"
                "[core]\nignoreCase = false\n"
                '[includeIf "onbranch:visibility-after"]\n'
                "path = visibility.config\n"
            )
        for branch in ("visibility-before", "visibility-after"):
            sp.run(  # noqa: S603
                ["git", "-C", str(src_target), "branch", branch],  # noqa: S607
                check=True,
                capture_output=True,
            )
        sp.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(src_target),
                "checkout",
                "-q",
                "visibility-before",
            ],
            check=True,
            capture_output=True,
        )
    elif visibility_mutation == "index_membership":
        hidden = src_target / "hidden"
        hidden.mkdir()
        (hidden / "generated.txt").write_text("demo_widget\n", encoding="utf-8")
        sp.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(src_target),
                "add",
                "-f",
                "hidden/generated.txt",
            ],
            check=True,
            capture_output=True,
        )
        sp.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(src_target),
                "commit",
                "-q",
                "-m",
                "add tracked ignored fixture",
            ],
            check=True,
            capture_output=True,
        )
    real_run = sp.run

    def hide_leak_and_succeed(cmd, *args, **kwargs):
        if Path(cmd[0]).stem == "uv" and cmd[1:] == ["lock"]:
            (src_target / "uv.lock").write_text(
                "potato_launcher==1.0.0\n", encoding="utf-8"
            )
            hidden = src_target / "hidden"
            hidden.mkdir(exist_ok=True)
            (hidden / "generated.txt").write_text("demo_widget\n", encoding="utf-8")
            if visibility_mutation == "gitignore":
                with (src_target / ".gitignore").open("a", encoding="utf-8") as fh:
                    fh.write("hidden/\n")
            elif visibility_mutation == "info_exclude":
                with (src_target / ".git" / "info" / "exclude").open(
                    "a", encoding="utf-8"
                ) as fh:
                    fh.write("hidden/\n")
            elif visibility_mutation == "core_excludes_file":
                changed = src_target / "config" / "command-excludes"
                changed.write_text("hidden/\n", encoding="utf-8")
                real_run(
                    [
                        "git",
                        "-C",
                        str(src_target),
                        "config",
                        "--local",
                        "core.excludesFile",
                        "config/command-excludes",
                    ],
                    check=True,
                    capture_output=True,
                )
            elif visibility_mutation == "core_ignore_case":
                real_run(
                    [
                        "git",
                        "-C",
                        str(src_target),
                        "config",
                        "--local",
                        "core.ignoreCase",
                        "true",
                    ],
                    check=True,
                    capture_output=True,
                )
            elif visibility_mutation == "conditional_config_activation":
                real_run(
                    [
                        "git",
                        "-C",
                        str(src_target),
                        "symbolic-ref",
                        "HEAD",
                        "refs/heads/visibility-after",
                    ],
                    check=True,
                    capture_output=True,
                )
            elif visibility_mutation == "index_membership":
                real_run(
                    [
                        "git",
                        "-C",
                        str(src_target),
                        "rm",
                        "--cached",
                        "-q",
                        "hidden/generated.txt",
                    ],
                    check=True,
                    capture_output=True,
                )
            return sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", hide_leak_and_succeed)
    answers = write_answers(tmp_path)

    code = main(["--target", str(src_target), "--config", str(answers)])

    assert code == 1
    assert "effective Git visibility changed during declared commands" in (
        capsys.readouterr().err
    )
    assert not (src_target / RECEIPT_REL).exists()
    assert (src_target / "hidden" / "generated.txt").read_text(
        encoding="utf-8"
    ) == "demo_widget\n"
    ignored = real_run(
        [
            "git",
            "-C",
            str(src_target),
            "check-ignore",
            "hidden/generated.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 0


def _commit_all(target: Path, message: str = "post-press") -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "commit", "-q", "-m", message],  # noqa: S607
        check=True,
        capture_output=True,
    )


DEST2 = Identity(
    package_name="tomato_thrower",
    repo_name="tomato-thrower",
    app_name="tomato",
    author="Tomato Farmer",
    email="tomato@example.com",
    owner="tomatolabs",
)


def _pressed_target_with_receipt(src_target: Path, tmp_path: Path, monkeypatch) -> None:
    """One verified press with a declared uv.lock regeneration, committed.

    The regeneration is faked to succeed (the fixture pyproject has no
    build-system, so a real `uv lock` fails) — the fake matches the PINNED
    executable the executor actually launches, and writes output that
    passes the postcondition scan.
    """
    import subprocess as sp

    (src_target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
        encoding="utf-8",
    )
    write_source_config(src_target)
    real_run = sp.run

    def regen_succeeds(cmd, *args, **kwargs):
        if Path(cmd[0]).stem == "uv" and cmd[1:] == ["lock"]:
            (src_target / "uv.lock").write_text(
                "tuber_toolkit==1.0.0\n", encoding="utf-8"
            )
            return sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", regen_succeeds)
    answers = write_answers(tmp_path)
    assert main(["--target", str(src_target), "--config", str(answers)]) == 0
    assert (src_target / RECEIPT_REL).is_file()
    monkeypatch.setattr(subprocess, "run", real_run)
    _commit_all(src_target)
    # The press rewrites files, not git config: discovery would still see
    # the old origin and refuse the re-press (EMP-01). Point it at the new
    # identity, as a genuinely re-pressed repo would be.
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(src_target),
            "remote",
            "set-url",
            "origin",
            "https://github.com/potatolabs/potato-launcher.git",
        ],
        check=True,
        capture_output=True,
    )


def test_failed_forced_repress_removes_stale_receipt(
    src_target: Path, tmp_path: Path, monkeypatch, capsys
):
    """P04-T16 (PR #56 thread 3651682614): a failed forced re-press must not
    leave the prior receipt advertising a verified press — it is invalidated
    after the plan gates pass and before the first mutation.
    """
    import subprocess as sp

    _pressed_target_with_receipt(src_target, tmp_path, monkeypatch)
    real_run = sp.run

    def regen_fails(cmd, *args, **kwargs):
        if Path(cmd[0]).stem == "uv" and cmd[1:] == ["lock"]:
            return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", regen_fails)
    second = tmp_path / "second"
    second.mkdir()
    answers2 = write_answers_file(second, DEST2)
    code = main(["--target", str(src_target), "--config", str(answers2), "--force"])
    assert code == 1
    assert "lockfile regeneration failed" in capsys.readouterr().err
    assert not (src_target / RECEIPT_REL).exists()


def test_failed_command_cannot_plant_a_receipt(
    src_target: Path, tmp_path: Path, monkeypatch, capsys
):
    """Codex 3654736777 (P1): a declared command that creates
    press/press-receipt.toml and then fails must not leave it behind
    advertising a verified press — the control snapshot is restored on
    every post-command failure exit."""
    import subprocess as sp

    (src_target / "uv.lock").write_text("demo_widget==0.1.0\n", encoding="utf-8")
    (src_target / "press").mkdir(exist_ok=True)
    (src_target / "press" / "press-rules.toml").write_text(
        '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n',
        encoding="utf-8",
    )
    write_source_config(src_target)
    real_run = sp.run

    def plant_and_fail(cmd, *args, **kwargs):
        if Path(cmd[0]).stem == "uv" and cmd[1:] == ["lock"]:
            (src_target / RECEIPT_REL).write_text(
                "[press]\nverified = true\n", encoding="utf-8"
            )
            return sp.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", plant_and_fail)
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 1
    assert "lockfile regeneration failed" in capsys.readouterr().err
    assert not (src_target / RECEIPT_REL).exists()


def test_forced_repress_blocked_at_plan_gate_keeps_receipt(
    src_target: Path, tmp_path: Path, monkeypatch
):
    """Invalidation runs AFTER the plan gates: a forced re-press refused at
    exit 2 (nothing written) must leave the prior receipt untouched.
    """
    _pressed_target_with_receipt(src_target, tmp_path, monkeypatch)
    # Dirty the declared output: the output preflight refuses (exit 2) even
    # under --allow-dirty, before any write.
    with (src_target / "uv.lock").open("a", encoding="utf-8") as fh:
        fh.write("# uncommitted\n")
    second = tmp_path / "second"
    second.mkdir()
    answers2 = write_answers_file(second, DEST2)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers2),
            "--force",
            "--allow-dirty",
        ]
    )
    assert code == 2
    assert (src_target / RECEIPT_REL).is_file()


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


def test_rule_scope_migrated_by_ancestor_rename_exits_2_no_receipt(
    src_target: Path, tmp_path: Path
):
    """F1 e2e: a paths=true [[replace]] rule scoped `files=["press_docs/**"]`
    guards a filename under a directory the ORDINARY token-rename pass ALSO
    renames (press_docs/ -> potato_docs/). `_rename_pass_once` collapses
    each pass to its shallowest differing ancestor, so the directory rename
    lands on pass 1 and the rule's own `files` scope no longer matches by
    the time the SAME rule gets to re-evaluate against the file on pass 2 —
    the rule never fires and the file keeps its stale name (0008's
    former rewrite-side scope-migration limitation). P06's shared validator
    now refuses that order-dependent pipeline before any target write."""
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
    assert code == 2
    assert not (src_target / RECEIPT_REL).exists()
    # The new refusal is pre-write: both source coordinates remain intact.
    assert (src_target / "press_docs" / "_press_guide.md").exists()
    assert not (src_target / "potato_docs").exists()


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


@requires_symlink
def test_symlink_to_ignored_existing_rule_target_not_silently_redirected(
    src_target: Path, tmp_path: Path
):
    """Commit 1 e2e (rule-based retarget): `press-guide` and `potato-guide`
    both already exist on disk but are gitignored — git never lists their
    content, so the doctor cannot scan either path. A `paths=true`
    [[replace]] rule renders FROM `press-guide` TO `potato-guide`; without a
    target-actually-moves gate, `_retarget_symlinks` would rewrite
    `link -> press-guide` to `link -> potato-guide` — a DIFFERENT,
    pre-existing file the rename pass never touched — and both the doctor
    and a naive scan would see nothing wrong (the source token is gone).
    The fix must leave the link text UNCHANGED; the doctor's ordinary
    replace_rule/symlink scan then flags the surviving source literal
    loudly (exit 1), never a silent redirect (exit 0)."""
    write_source_config(src_target)
    (src_target / "press" / "press-rules.toml").write_text(
        "[[replace]]\n"
        'pattern = "{app_name}-guide"\n'
        "paths   = true\n"
        "content = false\n"
        'reason  = "guide dir rename"\n',
        encoding="utf-8",
    )
    (src_target / ".gitignore").write_text(
        "press-guide\npotato-guide\n", encoding="utf-8"
    )
    (src_target / "press-guide").mkdir()
    (src_target / "potato-guide").mkdir()
    os.symlink("press-guide", src_target / "link")
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert not (src_target / RECEIPT_REL).exists()
    assert os.readlink(src_target / "link") == "press-guide"  # unchanged


@requires_symlink
def test_symlink_to_ignored_existing_pair_target_not_silently_redirected(
    src_target: Path, tmp_path: Path
):
    """Commit 1 scope addition: the identical silent-redirect shape through
    a plain identity-FIELD pair (no [[replace]] rule involved at all)
    predates this branch — `link -> press_guide` boundary-matches app_name
    "press" exactly like any ordinary token (underscore is a separator on
    its right). P06 now refuses earlier because that same substitution would
    mutate `.gitignore` and invalidate the frozen inventory; the link must
    remain unchanged and no receipt may be written."""
    write_source_config(src_target)
    (src_target / ".gitignore").write_text(
        "press_guide\npotato_guide\n", encoding="utf-8"
    )
    (src_target / "press_guide").mkdir()
    (src_target / "potato_guide").mkdir()
    os.symlink("press_guide", src_target / "link")
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2
    assert not (src_target / RECEIPT_REL).exists()
    assert os.readlink(src_target / "link") == "press_guide"  # unchanged


def test_rule_static_text_colliding_with_changed_token_exits_2_no_writes(
    src_target: Path, tmp_path: Path
):
    """F2 e2e: `pattern = "press_{app_name}Owned"` renders TO
    `"press_potatoOwned"` — its static "press_" prefix boundary-matches the
    SOURCE app_name value ("press", underscore-terminated) exactly like the
    ordinary token pass would, so the token pass that runs right after the
    rule pass would re-rewrite the rule's own static text, silently
    corrupting the output. `rendered_replace_rules` must reject this at
    build-plan time — before any write — never producing a
    wrong-but-plausible receipt."""
    write_source_config(src_target)
    (src_target / "press" / "press-rules.toml").write_text(
        "[[replace]]\n"
        'pattern = "press_{app_name}Owned"\n'
        'reason  = "static-text collision repro (F2)"\n',
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "commit", "-q", "-m", "add colliding rule"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 2
    assert not (src_target / RECEIPT_REL).exists()


def test_composed_boundary_collision_exits_2_no_writes(tmp_path: Path):
    """Commit 2 e2e: `pattern = "f{repo_name}_Owned"` renders TO
    `"foo_Owned"` (static "f" + repo_name TO "oo") — this literal collides
    with the CHANGING app_name value "foo" only once the static text and
    the (different) placeholder's rendered value are composed together, a
    seam `pattern_static_segments` (static text only) never sees. The
    rendered-TO stability check must reject this at build-plan time — before
    any write — never producing a wrong-but-plausible receipt.

    A custom minimal target (not the `src_target` fixture) is built here so
    its discoverable pyproject/git-origin content actually matches the
    purpose-built `app_name`/`repo_name` values the composed repro needs —
    reusing `src_target`'s fixed "press"/"demo-widget" identity would trip
    the unrelated source-config-mismatch guard first."""
    source = Identity(
        package_name="oldrepo",
        repo_name="oldrepo",
        app_name="foo",
        author="Demo Author",
        email="demo@example.com",
        owner="demolabs",
    )
    repo = tmp_path / "target"
    pkg = repo / "src" / source.package_name
    pkg.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{source.package_name}"\nversion = "0.1.0"\n'
        f'authors = [{{ name = "{source.author}", email = "{source.email}" }}]\n'
        f'requires-python = ">=3.12"\n\n'
        f'[project.scripts]\n{source.app_name} = "{source.package_name}.cli:main"\n',
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text('"""pkg."""\n', encoding="utf-8")
    for git_args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
        [
            "remote",
            "add",
            "origin",
            f"https://github.com/{source.owner}/{source.repo_name}.git",
        ],
    ):
        subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), *git_args],  # noqa: S607
            check=True,
            capture_output=True,
        )
    (repo / "press").mkdir()
    (repo / SOURCE_CONFIG_REL).write_text(
        render_source_config(source), encoding="utf-8"
    )
    (repo / "press" / "press-rules.toml").write_text(
        "[[replace]]\n"
        'pattern = "f{repo_name}_Owned"\n'
        'reason  = "composed-boundary repro (commit 2)"\n',
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    dest = Identity(
        package_name="oo",
        repo_name="oo",
        app_name="bar",
        author="Potato Farmer",
        email="potato@example.com",
        owner="potatolabs",
    )
    answers = write_answers_file(tmp_path, dest)
    code = main(["--target", str(repo), "--config", str(answers)])
    assert code == 2
    assert not (repo / RECEIPT_REL).exists()


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


def test_accept_discovery_rename_preflight_failure_leaves_no_writes(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from template_press.rebrand import safety

    before = (src_target / "README.md").read_bytes()

    def reject_atomic_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))

    monkeypatch.setattr(safety, "_rename_noreplace_unchecked", reject_atomic_rename)
    answers = write_answers(tmp_path)

    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--accept-discovery",
        ]
    )

    assert code == 2
    assert (src_target / "README.md").read_bytes() == before
    assert not (src_target / SOURCE_CONFIG_REL).exists()
    assert not list(src_target.rglob(".press-rename-probe-*"))
    stderr = capsys.readouterr().err
    assert "warning: planned path renames cannot use atomic" in stderr
    assert "re-run with --force" in stderr


def test_force_warns_and_uses_nonatomic_rename_fallback(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from template_press.rebrand import safety

    def reject_atomic_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))

    monkeypatch.setattr(safety, "_rename_noreplace_unchecked", reject_atomic_rename)
    answers = write_answers(tmp_path)

    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--accept-discovery",
            "--force",
        ]
    )

    assert code == 0
    assert not (src_target / "src" / "demo_widget").exists()
    assert (src_target / "src" / "potato_launcher").is_dir()
    stderr = capsys.readouterr().err
    assert "proceeding because --force" in stderr
    assert "destination created during the final race window may be overwritten" in (
        stderr
    )


@pytest.mark.skipif(os.name == "nt", reason="simulates another POSIX platform")
def test_dry_run_warns_but_does_not_require_force_for_nonatomic_rename(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from template_press.rebrand import engine as engine_module
    from template_press.rebrand import safety

    monkeypatch.setattr(safety.sys, "platform", "linux")

    def reject_host_support() -> None:
        raise safety.AtomicRenameUnavailableError(
            "atomic no-replace rename is unavailable on this supported host"
        )

    monkeypatch.setattr(
        engine_module, "require_rename_noreplace_host_support", reject_host_support
    )
    monkeypatch.setattr(
        safety,
        "_rename_noreplace_unchecked",
        lambda _source, _destination: pytest.fail(
            "dry-run executed the target-filesystem probe"
        ),
    )
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
    assert (src_target / "src" / "demo_widget").is_dir()
    assert not (src_target / "src" / "potato_launcher").exists()
    captured = capsys.readouterr()
    assert "(dry run — nothing applied)" in captured.out
    assert "a real apply requires --force" in captured.err


def test_press_outcome_env_error_on_regen_failure(tmp_path: Path, monkeypatch):
    """B5/C-7/C-11: nonzero regen surfaces as PressOutcome.env_error, not a leak."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    monkeypatch.setattr(cli_mod, "execute_regenerations", lambda *a, **k: ["uv.lock"])

    direct_target = make_target(tmp_path / "direct", layout="src")
    write_source_config(direct_target)
    rules = load_rules(direct_target)
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules, [], [])
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

    monkeypatch.setattr(cli_mod, "execute_regenerations", boom)

    target = make_target(tmp_path / "direct", layout="src")
    write_source_config(target)
    rules = load_rules(target)
    outcome = cli_mod._press(target, SOURCE, DEST, rules, [], [])
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
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules, [], [])
    assert outcome.env_error is not None
    assert outcome.renamed == []

    main_target = make_target(tmp_path / "main", layout="src")
    write_source_config(main_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(main_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1


def test_press_outcome_env_error_on_declared_rule_compilation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A supplied table's rendered-rule validation stays inside the CLI guard."""
    from template_press.rebrand import cli as cli_mod
    from template_press.rebrand.identity import ValidationError
    from template_press.rebrand.rules import load_rules

    from .conftest import make_target

    target = make_target(tmp_path / "direct", layout="src")
    write_source_config(target)
    rules = load_rules(target)
    plan = cli_mod.build_plan(target, SOURCE, DEST, rules)
    assert plan.table is not None

    def reject(_table):
        raise ValidationError("invalid rendered rule")

    monkeypatch.setattr(cli_mod, "declared_rule_triples", reject)

    outcome = cli_mod._press(
        target,
        SOURCE,
        DEST,
        rules,
        [],
        [],
        table=plan.table,
    )

    assert outcome.env_error == "invalid rendered rule"
    assert outcome.renamed == []


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
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules, [], [])
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
    outcome = cli_mod._press(direct_target, SOURCE, DEST, rules, [], [])
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
    """Destination stability includes enabled derived display forms."""

    def test_derived_camel_form_embedding_changed_app_name_is_a_collision(
        self, src_target: Path
    ):
        from template_press.rebrand.engine import build_plan
        from template_press.rebrand.identity import ValidationError
        from template_press.rebrand.rules import DEFAULT_RULES

        source = _identity(display_name="Py Launch Blueprint")
        dest = _identity(app_name="acme", display_name="Plbp")
        with pytest.raises(ValidationError, match="ordered content dependency"):
            build_plan(src_target, source, dest, DEFAULT_RULES)

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
    """Destination stability uses each field's configured matcher."""

    def test_substring_field_embedded_without_boundary_is_a_collision(
        self, src_target: Path
    ):
        from dataclasses import replace

        from template_press.rebrand.engine import build_plan
        from template_press.rebrand.identity import ValidationError
        from template_press.rebrand.rules import DEFAULT_RULES

        source = _identity(app_name="press")
        dest = _identity(app_name="tool", repo_name="mypress-tools")
        # Boundary mode: "press" preceded by alnum "y" in "mypress-tools" is
        # NOT a token match — no collision without substring mode.
        build_plan(src_target, source, dest, DEFAULT_RULES)
        # Substring mode for app_name: the embedded literal IS a collision.
        rules = replace(
            DEFAULT_RULES,
            substring_rewrite_fields=frozenset({"app_name"}),
        )
        with pytest.raises(ValidationError, match="ordered content dependency"):
            build_plan(src_target, source, dest, rules)

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
