import subprocess
from pathlib import Path

import pytest

from .conftest import make_target


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_src_target_shape(src_target: Path):
    assert (src_target / ".git").is_dir()
    assert (src_target / "src" / "demo_widget" / "cli.py").is_file()
    assert "Compress" in (src_target / "README.md").read_text(encoding="utf-8")


def test_flat_target_shape(flat_target: Path):
    assert (flat_target / "demo_widget" / "cli.py").is_file()
    assert not (flat_target / "src").exists()


@pytest.mark.parametrize("layout", ["src", "flat"])
def test_reused_target_is_clean_and_independent(tmp_path: Path, layout: str):
    first = make_target(tmp_path / "first", layout=layout)
    tree = _git_output(first, "rev-parse", "HEAD^{tree}")
    (first / "README.md").write_text("changed\n", encoding="utf-8")
    _git_output(first, "config", "user.name", "Changed")

    second = make_target(tmp_path / "second", layout=layout)

    assert "Compress" in (second / "README.md").read_text(encoding="utf-8")
    assert _git_output(second, "rev-parse", "HEAD^{tree}") == tree
    assert _git_output(second, "status", "--porcelain") == ""
    assert _git_output(second, "diff-files", "--name-only") == ""
    assert _git_output(second, "config", "user.name") == "Test\n"
    assert _git_output(second, "remote", "get-url", "origin") == (
        "https://github.com/demolabs/demo-widget.git\n"
    )


@pytest.mark.parametrize("layout", ["src", "flat"])
def test_reused_target_only_refreshes_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
):
    make_target(tmp_path / "seed", layout=layout)
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(command, *args, **kwargs):
        calls.append(list(command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)

    make_target(tmp_path / "copy", layout=layout)

    assert len(calls) == 1
    assert "update-index" in calls[0]
