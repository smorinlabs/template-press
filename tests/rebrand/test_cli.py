import os
import subprocess
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, SOURCE, write_answers_file


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


def test_mid_apply_oserror_exits_1_with_partial_warning(
    src_target: Path, tmp_path: Path, capsys
):
    write_source_config(src_target)
    # Sorts after README.md etc., so earlier files are rewritten first.
    readonly = src_target / "zz_readonly.md"
    readonly.write_text("demo_widget survives here\n", encoding="utf-8")
    readonly.chmod(0o444)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    readonly.chmod(0o644)  # let pytest clean the tmp dir
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
