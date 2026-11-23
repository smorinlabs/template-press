"""Keep `just check` failing fast on its near-instant static checks."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def test_static_checks_run_before_the_test_suite() -> None:
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")
    recipe = re.search(r"^@check: (.+)$", justfile, flags=re.MULTILINE)
    assert recipe is not None
    dependencies = recipe.group(1)
    tests_at = dependencies.index('(test "-n" "auto")')
    for check in (
        "lint",
        "typecheck",
        "check-yaml",
        "check-spelling",
        "check-editorconfig",
    ):
        assert dependencies.index(check) < tests_at
