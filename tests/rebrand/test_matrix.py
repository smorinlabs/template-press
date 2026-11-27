"""Live acceptance matrix (network + real clones). Excluded by default
addopts; run explicitly: uv run pytest tests/rebrand/test_matrix.py -m live

R1 is split across the §6 excluded-file contract (P04-TS11/T12): an
UNDECLARED blueprint clone is refused loudly at the preflight (R1a), and a
clone carrying the declarations presses clean end to end — G1's CHANGELOG
reset and G2's bun.lock regeneration proven against the real repo (R1b).
"""

import dataclasses
import json
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from template_press import press_cli
from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, toml_string
from template_press.rebrand.discovery import discover
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.remove import plan_removals
from template_press.rebrand.rules import load_selected_rules
from template_press.rebrand.substitutions import check_target_keep_names
from template_press.rebrand.verify_cli import verify_command
from template_press.rebrand.verify_config import load_verify_config

from .conftest import DEST, _git, posix_only, write_answers_file

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


def declare_blueprint_languages(target: Path) -> None:
    """Declare ``languages`` in a disposable blueprint clone (upstream cannot
    yet), committing only ``press/press-rules.toml``. No-op once declared."""
    rules_path = target / "press" / "press-rules.toml"
    text = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
    if "languages" in tomllib.loads(text).get("rules", {}):
        return
    declaration = 'languages = ["python"]\n'
    table = re.search(r"^\[rules\][ \t]*\r?\n?", text, flags=re.MULTILINE)
    if table is None:
        sep = "" if not text or text.endswith("\n") else "\n"
        text = f"{text}{sep}[rules]\n{declaration}"
    else:
        end = table.end()
        lead = "" if table.group().endswith("\n") else "\n"
        text = f"{text[:end]}{lead}{declaration}{text[end:]}"
    rules_path.parent.mkdir(exist_ok=True)
    rules_path.write_text(text, encoding="utf-8", newline="")
    rel = "press/press-rules.toml"
    _git(target, "add", "--", rel)
    _git(
        target,
        "-c",
        "user.name=matrix",
        "-c",
        "user.email=matrix@example.test",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-q",
        "-m",
        "test: declare languages",
        "--",
        rel,
    )


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


def test_native_directory_declaration():
    from template_press.rebrand.rules import load_rules

    rules = load_rules(REPO_ROOT)
    assert [(r.dir, r.reason) for r in rules.remove_dirs] == [
        ("docs/research", "engine research notes")
    ]
    assert not any(r.file.startswith("docs/research/") for r in rules.remove)
    assert not any(r.file == "projects/.gitkeep" for r in rules.remove)
    assert sum(r.file.startswith("projects/") for r in rules.remove) == 13


def test_native_r3_workflows_cover_posix_and_manual_windows() -> None:
    workflow = yaml.load(
        (REPO_ROOT / ".github/workflows/rebrand-matrix.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,  # noqa: S506 - only strings/containers, no constructors.
    )

    entries = workflow["jobs"]["matrix"]["strategy"]["matrix"]["include"]
    assert any(entry["os"] == "blacksmith-4vcpu-ubuntu-2404" for entry in entries)
    assert "scripts/regen-bun-lock.ps1" in workflow["on"]["pull_request"]["paths"]

    manual = yaml.load(
        (REPO_ROOT / ".github/workflows/windows-ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,  # noqa: S506 - only strings/containers, no constructors.
    )
    assert set(manual["on"]) == {"workflow_dispatch"}
    assert manual["jobs"]["test-windows"]["runs-on"] == "blacksmith-8vcpu-windows-2025"


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [("ci.yml", "test"), ("windows-ci.yml", "test-windows")],
)
def test_ci_provisions_bun_for_native_r3(workflow_name: str, job_name: str) -> None:
    workflow = yaml.load(
        (REPO_ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,  # noqa: S506 - only strings/containers, no constructors.
    )
    steps = workflow["jobs"][job_name]["steps"]
    no_cov = next(step for step in steps if step.get("name") == "Run tests")
    no_cov_cmd = shlex.split(no_cov["run"])
    assert no_cov_cmd[:5] == [
        "uv",
        "run",
        "--no-sync",
        "python",
        "scripts/ci_run_pytest.py",
    ]
    no_cov_args = no_cov_cmd[no_cov_cmd.index("--") + 1 :]
    assert no_cov_args[no_cov_args.index("-m") + 1] == ""
    assert no_cov_args[no_cov_args.index("-n") + 1] == "auto"
    assert "--cov=template_press" not in no_cov_args
    if workflow_name == "ci.yml":
        assert no_cov.get("if") == "${{ !matrix.upload-coverage }}"
        full = next(
            step for step in steps if step.get("name") == "Run tests with coverage"
        )
        assert full.get("if") == "matrix.upload-coverage"
        command = shlex.split(full["run"])
        assert command[:5] == [
            "uv",
            "run",
            "--no-sync",
            "python",
            "scripts/ci_run_pytest.py",
        ]
        arguments = command[command.index("--") + 1 :]
        assert arguments[arguments.index("-m") + 1] == ""
        assert arguments[arguments.index("-n") + 1] == "auto"
        assert "--cov=template_press" in arguments
        assert "--cov-report=xml" in arguments
    bun = next(step for step in steps if step.get("uses") == "oven-sh/setup-bun@v2.2.0")
    assert bun["with"]["bun-version"] == "1.3.14"


def test_matrix_script_runs_live_tests_in_parallel() -> None:
    script = (REPO_ROOT / "scripts/rebrand_matrix.sh").read_text(encoding="utf-8")
    commands = [
        shlex.split(line)
        for line in script.splitlines()
        if line.startswith("uv run pytest ")
    ]
    assert len(commands) == 3
    for command in commands:
        assert command[command.index("-n") + 1] == "auto"
        # `load` would ignore xdist_group and let shared-cache tests overlap.
        assert command[command.index("--dist") + 1] == "loadgroup"


@pytest.mark.parametrize(
    "test",
    [
        pytest.param(lambda: test_r3_self_press_native, id="r3"),
        pytest.param(lambda: test_r1b_declared_blueprint_presses_clean, id="r1b"),
    ],
)
def test_regenerating_matrix_tests_share_one_worker(test) -> None:
    """Both run `uv lock` and `bun install` against the user's shared caches,
    and R1b accepts exit 1, so an overlap failure could pass unnoticed."""
    groups = [
        mark.kwargs["name"] for mark in test().pytestmark if mark.name == "xdist_group"
    ]
    assert groups == ["shared-tool-caches"]


def _keep_r3_app_name_tokens(target: Path, dest: Identity) -> None:
    """Declare kept ``app_name = "press"`` compounds in the disposable R3 clone.

    This repo is not a project template and legitimately uses ``press`` in its
    own code, tests, and docs (``press-rules``, ``press-target``,
    ``PressOutcome``, ``stray_press_dirs``). Declaring those ``app_name``
    compounds inside the disposable clone keeps checked-in
    ``press/press-rules.toml`` clean while preserving Decision 1's strict
    preflight for every other field.
    """
    found = discover(target, languages=("python",))
    assert (
        found.package_name
        and found.repo_name
        and found.app_name
        and found.author
        and found.email
        and found.owner
    )
    source = Identity(
        package_name=found.package_name,
        repo_name=found.repo_name,
        app_name=found.app_name,
        author=found.author,
        email=found.email,
        owner=found.owner,
    )
    rules = load_selected_rules(target).rules
    removal_plan = plan_removals(target, rules, source=source)
    check = check_target_keep_names(
        target,
        source,
        dest,
        rules,
        frozenset(member.current_file for member in removal_plan.members),
        ("python",),
        verify_config=load_verify_config(target),
    )
    tokens = sorted(
        {item.token for item in check.undeclared if item.field == "app_name"}
    )
    if not tokens:
        return
    rules_path = target / "press" / "press-rules.toml"
    text = rules_path.read_text(encoding="utf-8")
    keep_line = "keep_names = [" + ", ".join(toml_string(t) for t in tokens) + "]\n"
    table = re.search(r"^\[rules\][ \t]*\r?\n?", text, flags=re.MULTILINE)
    assert table is not None
    end = table.end()
    lead = "" if table.group().endswith("\n") else "\n"
    rules_path.write_text(
        f"{text[:end]}{lead}{keep_line}{text[end:]}", encoding="utf-8", newline=""
    )


@pytest.mark.live
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_r3_self_press_native(tmp_path: Path) -> None:
    """Execute the checked-in declaration selected by this native host."""

    r3_package_name = "_".join(("r3", "matrix", "fixture"))
    r3_dest = dataclasses.replace(
        DEST,
        package_name=r3_package_name,
        repo_name=r3_package_name.replace("_", "-"),
        app_name="_".join(("r3", "tool")),
        author=" ".join(("R3", "Matrix", "Fixture")),
        email="@".join(("r3-matrix", "fixture.invalid")),
        owner="-".join(("r3", "matrix", "labs")),
    )
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
    _keep_r3_app_name_tokens(target, r3_dest)
    answers = write_answers_file(tmp_path, r3_dest)

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
        if package["name"] == r3_dest.repo_name
    )
    assert manifest["."] == "0.1.0"
    assert pyproject["project"]["version"] == "0.1.0"
    assert root_package["version"] == "0.1.0"
    raw_receipt = (target / RECEIPT_REL).read_text(encoding="utf-8")
    receipt = tomllib.loads(raw_receipt)
    expected_research = {
        "docs/research/0001-skill-trigger-optimization.md",
        "docs/research/0002-dev-tooling-wishlist.md",
        "docs/research/0003-init-post-init-analysis.md",
        "docs/research/0004-py-launch-blueprint-conformance-gaps.md",
        "docs/research/0005-scaffolder-identity-variant-handling.md",
        "docs/research/README.md",
    }
    assert not (target / "docs/research").exists()
    assert (target / "projects/.gitkeep").is_file()
    (directory,) = receipt["press"]["remove_dir"]
    assert directory["dir"] == "docs/research"
    assert {row["file"] for row in directory["members"]} == expected_research
    assert expected_research <= {row["file"] for row in receipt["press"]["remove"]}
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{r3_dest.owner}/{r3_dest.repo_name}.git",
    )
    assert verify_command(["--target", str(target)]) == 0
    # E10: this repo declares its own clean paths; the native press records
    # the declaration, unrendered, and `press clean --show` previews cleanly.
    assert receipt["press"]["clean"] == [{"paths": ["src/{package_name}", "tests"]}]
    assert press_cli.main(["clean", "--target", str(target), "--show"]) == 0
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
    declare_blueprint_languages(target)
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
@pytest.mark.xdist_group(name="shared-tool-caches")
def test_r1b_declared_blueprint_presses_clean(tmp_path: Path):
    """The declared pipeline against the real blueprint: CHANGELOG resets to
    the stub (G1), lockfiles regenerate under the pressed identity (G2).

    The blueprint commits its own press/ config and regen scripts since its
    P05 conform, so the clone presses AS SHIPPED — that committed config is
    exactly what this acceptance run must prove. Its source declares
    display_name, so the answers must supply one."""
    target = clone(BLUEPRINT, tmp_path / "plb")
    declare_blueprint_languages(target)
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
    declare_blueprint_languages(target)
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
