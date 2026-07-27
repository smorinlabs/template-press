"""Live acceptance matrix (network + real clones). Excluded by default
addopts; run explicitly: uv run pytest tests/rebrand/test_matrix.py -m live

R1 is split across the §6 excluded-file contract (P04-TS11/T12): an
UNDECLARED blueprint clone is refused loudly at the preflight (R1a), and a
clone carrying the declarations presses clean end to end — G1's CHANGELOG
reset and G2's bun.lock regeneration proven against the real repo (R1b).
"""

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, posix_only, write_answers_file

BLUEPRINT = "https://github.com/smorinlabs/py-launch-blueprint.git"

BLUEPRINT_RULES = """\
[[regenerate]]
file = "uv.lock"
command = ["uv", "lock"]

[[regenerate]]
file = "bun.lock"
command = ["scripts/regen-bun-lock.sh"]

[[reset]]
file = "CHANGELOG.md"
stub = "# Changelog\\n"
"""

# bun install alone never rewrites an existing lock's workspace name
# (bun 1.3.14) — the lock must be regenerated from scratch.
REGEN_BUN_LOCK = "#!/bin/sh\nset -e\nrm -f bun.lock\nexec bun install\n"


def clone(url: str, dest: Path) -> Path:
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "clone", "--depth=1", "-q", url, str(dest)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return dest


@pytest.mark.live
def test_r1a_undeclared_blueprint_refused_loudly(tmp_path: Path, capsys):
    """§6: tracked excluded files with no declared neutralization refuse the
    press (exit 2, nothing written) — naming every file, never silently
    letting identity survive."""
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
    assert code == 2
    err = capsys.readouterr().err
    for rel in ("uv.lock", "bun.lock", "CHANGELOG.md"):
        assert rel in err
    assert not (target / RECEIPT_REL).exists()


@pytest.mark.live
@posix_only
def test_r1b_declared_blueprint_presses_clean(tmp_path: Path):
    """The declared pipeline against the real blueprint: CHANGELOG resets to
    the stub (G1), lockfiles regenerate under the pressed identity (G2)."""
    target = clone(BLUEPRINT, tmp_path / "plb")
    press_dir = target / "press"
    press_dir.mkdir()
    (press_dir / "press-rules.toml").write_text(BLUEPRINT_RULES, encoding="utf-8")
    script = target / "scripts" / "regen-bun-lock.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text(REGEN_BUN_LOCK, encoding="utf-8")
    script.chmod(0o755)
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
    (target / "press").mkdir()
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
