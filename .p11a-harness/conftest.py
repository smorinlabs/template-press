"""Controlled early exit for the disposable native diagnostic proof."""

import os

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionstart() -> None:
    if os.environ.get("P11A_CASE", "pass") == "exit7":
        pytest.exit("fixture exit7", returncode=7)
