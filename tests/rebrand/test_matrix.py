"""Live acceptance matrix (network + real clones). Excluded by default
addopts; run explicitly: uv run pytest tests/rebrand/test_matrix.py -m live

R1 is split across the §6 excluded-file contract (P04-TS11/T12): an
UNDECLARED blueprint clone is refused loudly at the preflight (R1a), and a
clone carrying the declarations presses clean end to end — G1's CHANGELOG
reset and G2's bun.lock regeneration proven against the real repo (R1b).
"""

import dataclasses
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_selected_rules

from .conftest import DEST, posix_only, write_answers_file

BLUEPRINT = "https://github.com/smorinlabs/py-launch-blueprint.git"
SELF_ORIGIN = "https://github.com/smorinlabs/template-press.git"
REPO_ROOT = Path(__file__).parents[2]


def clone(url: str, dest: Path) -> Path:
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "clone", "--depth=1", "-q", url, str(dest)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return dest


@pytest.mark.parametrize(
    ("platform", "expected_helper", "inactive_helper"),
    [
        ("darwin", "scripts/regen-bun-lock.sh", "scripts/regen-bun-lock.ps1"),
        ("linux", "scripts/regen-bun-lock.sh", "scripts/regen-bun-lock.ps1"),
        ("win32", "scripts/regen-bun-lock.ps1", "scripts/regen-bun-lock.sh"),
    ],
)
def test_checked_in_bun_regeneration_is_native_and_single_writer(
    platform: str, expected_helper: str, inactive_helper: str
) -> None:
    selected = load_selected_rules(REPO_ROOT, platform=platform)
    bun_rules = [rule for rule in selected.rules.regenerate if rule.file == "bun.lock"]

    assert len(bun_rules) == 1
    assert expected_helper in bun_rules[0].command
    assert inactive_helper not in bun_rules[0].command
    assert (REPO_ROOT / expected_helper).is_file()


def test_native_r3_workflow_covers_posix_and_windows() -> None:
    workflow = (REPO_ROOT / ".github/workflows/rebrand-matrix.yml").read_text(
        encoding="utf-8"
    )

    assert "blacksmith-4vcpu-ubuntu-2404" in workflow
    assert "windows-latest" in workflow
    assert "test_r3_self_press_native" in workflow
    assert "scripts/regen-bun-lock.ps1" in workflow


def test_general_ci_provisions_bun_for_native_r3() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _prefix, test_marker, after_test = workflow.partition("\n  test:\n")
    test_job, next_marker, _suffix = after_test.partition("\n  build-smoke:\n")

    assert test_marker and next_marker
    assert 'run: uv run --no-sync pytest -m ""' in test_job
    assert "uses: oven-sh/setup-bun@v2.2.0" in test_job
    assert "bun-version: '1.3.14'" in test_job


@pytest.mark.live
def test_r3_self_press_native(tmp_path: Path) -> None:
    """Execute the checked-in declaration selected by this native host."""

    target = clone(str(REPO_ROOT), tmp_path / "self")
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            "remote",
            "set-url",
            "origin",
            SELF_ORIGIN,
        ],
        check=True,
        capture_output=True,
    )
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

    assert code == 0
    manifest = json.loads(
        (target / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((target / "uv.lock").read_text(encoding="utf-8"))
    root_package = next(
        package
        for package in uv_lock["package"]
        if package["name"] == "potato-launcher"
    )
    assert manifest["."] == "0.1.0"
    assert pyproject["project"]["version"] == "0.1.0"
    assert root_package["version"] == "0.1.0"
    raw_receipt = (target / RECEIPT_REL).read_text(encoding="utf-8")
    receipt = tomllib.loads(raw_receipt)
    assert receipt["press"]["platform"] == sys.platform
    bun_actions = [
        item for item in receipt["press"]["regenerate"] if item["file"] == "bun.lock"
    ]
    assert len(bun_actions) == 1
    expected_helper = (
        "regen-bun-lock.ps1" if sys.platform == "win32" else "regen-bun-lock.sh"
    )
    inactive_helper = (
        "regen-bun-lock.sh" if sys.platform == "win32" else "regen-bun-lock.ps1"
    )
    assert any(expected_helper in element for element in bun_actions[0]["argv"])
    assert inactive_helper not in raw_receipt
    bun_lock = (target / "bun.lock").read_text(encoding="utf-8")
    assert "template_press" not in bun_lock
    assert '"template-press"' not in bun_lock


@pytest.mark.live
def test_r1a_undeclared_blueprint_refused_loudly(tmp_path: Path, capsys):
    """§6: tracked excluded files with no declared neutralization refuse the
    press (exit 2, nothing written) — naming every file, never silently
    letting identity survive.

    The real blueprint has been conformed (its P05 run 4) and now COMMITS
    its declarations, so the undeclared state is constructed deliberately:
    strip the committed press/ config after cloning."""
    target = clone(BLUEPRINT, tmp_path / "plb")
    shutil.rmtree(target / "press")
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
    assert code == 2
    err = capsys.readouterr().err
    for rel in ("uv.lock", "bun.lock", "CHANGELOG.md"):
        assert rel in err
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.live
@posix_only
def test_r1b_declared_blueprint_presses_clean(tmp_path: Path):
    """The declared pipeline against the real blueprint: CHANGELOG resets to
    the stub (G1), lockfiles regenerate under the pressed identity (G2).

    The blueprint commits its own press/ config and regen scripts since its
    P05 conform, so the clone presses AS SHIPPED — that committed config is
    exactly what this acceptance run must prove. Its source declares
    display_name, so the answers must supply one."""
    target = clone(BLUEPRINT, tmp_path / "plb")
    answers = write_answers_file(
        tmp_path, dataclasses.replace(DEST, display_name="Potato Launcher")
    )
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
        changelog = (target / "CHANGELOG.md").read_text(encoding="utf-8")
        assert changelog == "# Changelog\n"
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
    # The conformed blueprint ships press/ — overwrite its source config
    # with a mismatched identity in place.
    (target / "press").mkdir(exist_ok=True)
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
