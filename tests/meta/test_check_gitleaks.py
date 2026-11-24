"""The pre-push secret scan must cover a branch's first push."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-gitleaks.sh"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text("content\n")
    git(repo, "add", name)
    git(repo, "commit", "--no-verify", "-m", f"add {name}")


@pytest.fixture
def fake_gitleaks(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Put a gitleaks stub on PATH that records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "gitleaks-args"
    stub = bin_dir / "gitleaks"
    stub.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\nexit "${{FAKE_RC:-0}}"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return env, record


def run_range(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--range"],  # noqa: S607
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def repo_with_origin(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-b", "main", str(repo))
    commit(repo, "base.txt")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return repo


def test_first_push_scans_commits_missing_from_default_branch(tmp_path, fake_gitleaks):
    env, record = fake_gitleaks
    repo = repo_with_origin(tmp_path)
    git(repo, "switch", "-c", "feature", "--no-track")
    commit(repo, "feature.txt")

    result = run_range(repo, env)

    assert result.returncode == 0, result.stderr
    assert "--log-opts=origin/main..HEAD" in record.read_text().splitlines()


def test_first_push_fails_when_scan_finds_a_secret(tmp_path, fake_gitleaks):
    env, _ = fake_gitleaks
    repo = repo_with_origin(tmp_path)
    git(repo, "switch", "-c", "feature", "--no-track")
    commit(repo, "feature.txt")

    result = run_range(repo, {**env, "FAKE_RC": "1"})

    assert result.returncode == 1


def test_repo_without_remote_scans_all_commits(tmp_path, fake_gitleaks):
    env, record = fake_gitleaks
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-b", "main", str(repo))
    commit(repo, "base.txt")

    result = run_range(repo, env)

    assert result.returncode == 0, result.stderr
    assert "--log-opts=HEAD" in record.read_text().splitlines()


def test_tracked_branch_still_scans_from_its_upstream(tmp_path, fake_gitleaks):
    env, record = fake_gitleaks
    repo = repo_with_origin(tmp_path)
    commit(repo, "next.txt")

    result = run_range(repo, env)

    assert result.returncode == 0, result.stderr
    assert "--log-opts=@{u}..HEAD" in record.read_text().splitlines()
