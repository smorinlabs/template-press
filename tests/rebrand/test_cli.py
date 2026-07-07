import subprocess
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, SOURCE


def write_source_config(target: Path) -> None:
    (target / ".press").mkdir(exist_ok=True)
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
    p = base / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(f'{k} = "{v}"' for k, v in DEST.as_dict_prompted().items())
        + "\n",
        encoding="utf-8",
    )
    return p


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
    (src_target / ".press").mkdir()
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
