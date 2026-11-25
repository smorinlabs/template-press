"""Fixture repositories must be stable while they are copied."""

import subprocess

from .conftest import make_target


def test_fixture_repo_disables_background_git_maintenance(tmp_path):
    repo = make_target(tmp_path)

    value = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "config", "--get", "maintenance.auto"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert value == "false"
