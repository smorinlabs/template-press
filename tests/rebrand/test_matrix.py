"""Live acceptance matrix (network + real clones). Excluded by default
addopts; run explicitly: uv run pytest tests/rebrand/test_matrix.py -m live
"""

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, write_answers_file

BLUEPRINT = "https://github.com/smorinlabs/py-launch-blueprint.git"


def clone(url: str, dest: Path) -> Path:
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "clone", "--depth=1", "-q", url, str(dest)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return dest


@pytest.mark.live
def test_r1_press_blueprint_clone_clean(tmp_path: Path):
    target = clone(BLUEPRINT, tmp_path / "plb")
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(answers),
            "--accept-discovery",
            "--allow-dirty",
        ]
    )
    assert code in (0, 1)  # 1 = leaks found: loud, actionable — never silent
    if code == 0:
        assert (target / RECEIPT_REL).is_file()
        grep = subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "grep", "-l", "py_launch_blueprint"],  # noqa: S607
            capture_output=True,
            text=True,
        )
        assert grep.stdout.strip() == ""
    else:
        assert not (target / RECEIPT_REL).exists()


@pytest.mark.live
def test_r2_mismatched_identity_fails_loudly(tmp_path: Path):
    target = clone(BLUEPRINT, tmp_path / "plb2")
    (target / ".press").mkdir()
    (target / SOURCE_CONFIG_REL).write_text(
        "[identity]\n"
        'package_name = "template_press"\n'
        'repo_name = "template-press"\n'
        'app_name = "press"\n'
        'author = "Steve Morin"\n'
        'email = "steve.morin@gmail.com"\n'
        'owner = "smorinlabs"\n',
        encoding="utf-8",
    )
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(answers),
            "--allow-dirty",
        ]
    )
    assert code == 2  # hard stop BEFORE any writes — the R2 scenario, inverted
    assert not (target / RECEIPT_REL).exists()
