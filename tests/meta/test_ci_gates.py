"""Execute production gate scripts with controlled GitHub dependency results."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HEAVY = ("typecheck", "test", "build-smoke")


def workflow(name):
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 - only strings/containers, no constructors.
    )


def lookup(context, reference):
    value = context
    for key in reference.split("."):
        value = value.get(key, "") if isinstance(value, dict) else ""
    return value


def step_env(step, context):
    result = {}
    for key, value in step.get("env", {}).items():
        expression = value.removeprefix("${{").removesuffix("}}").strip()
        if expression == "join(needs.*.result, ' ')":
            result[key] = " ".join(
                job.get("result", "") for job in context["needs"].values()
            )
        else:
            result[key] = str(lookup(context, expression))
    return result


def run_step(step, context, tmp_path):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("production Bash gate requires Bash")
    return subprocess.run(  # noqa: S603 - checked-in script and controlled env.
        [bash, "-c", step["run"]],
        env={
            **os.environ,
            **step_env(step, context),
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )


def main_context(code="true", event="pull_request"):
    needs = {
        name: {"result": "success"}
        for name in workflow("ci.yml")["jobs"]["ci-ok"]["needs"]
    }
    needs["changes"] = {"result": "success", "outputs": {"code": code}}
    if code == "false":
        for name in HEAVY:
            needs[name]["result"] = "skipped"
    return {"needs": needs, "github": {"event_name": event}}


MAIN_CASES = [
    ("true", "pull_request", None, None, True),
    ("false", "pull_request", None, None, True),
    ("true", "push", None, None, True),
    ("true", "merge_group", None, None, True),
    ("false", "push", None, None, False),
    ("false", "merge_group", None, None, False),
    *[
        (value, "pull_request", None, None, False)
        for value in ("", "TRUE", "FALSE", "no")
    ],
    *[
        ("true", "pull_request", job, result, False)
        for job in workflow("ci.yml")["jobs"]["ci-ok"]["needs"]
        for result in ("failure", "cancelled", "skipped", "", "unknown")
    ],
]


@pytest.mark.parametrize(("code", "event", "job", "result", "passes"), MAIN_CASES)
def test_main_gate_rejects_unsafe_dependencies(
    tmp_path, code, event, job, result, passes
):
    context = main_context(code, event)
    if job:
        context["needs"][job]["result"] = result
    step = workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    completed = run_step(step, context, tmp_path)
    assert (completed.returncode == 0) is passes, completed.stdout + completed.stderr


def lint_gate_result(job, context, tmp_path):
    """Model scheduling only; execute the actual validator when scheduled.

    GitHub treats expression string equality as case-insensitive. The baseline
    uses a single selector comparison; the repaired jobs use always(). Remote
    controls separately establish the provider's scheduling/failure behavior.
    """
    condition = job["if"]
    if condition != "always()":
        reference, expected = re.fullmatch(
            r"([\w.-]+) == '([^']*)'", condition
        ).groups()
        detector = context["needs"]["lint-changes"]["result"]
        if (
            detector != "success"
            or lookup(context, reference).lower() != expected.lower()
        ):
            return "skipped"
    validator = next(
        (step for step in job["steps"] if step.get("id") == "validate"), None
    )
    if validator is None:
        return "success"
    completed = run_step(validator, context, tmp_path)
    return "success" if completed.returncode == 0 else "failure"


@pytest.mark.parametrize("name", ["actionlint", "yamllint"])
@pytest.mark.parametrize(
    ("detection", "selector", "other", "expected"),
    [
        ("success", "true", "true", "success"),
        ("success", "true", "false", "success"),
        ("success", "false", "false", "skip"),
        ("success", "false", "true", "skip"),
        *[
            (result, "false", "false", "failure")
            for result in ("failure", "cancelled", "skipped", "")
        ],
        *[
            ("success", value, "false", "failure")
            for value in ("", "TRUE", "FALSE", "no")
        ],
        *[
            ("success", "false", value, "failure")
            for value in ("", "TRUE", "FALSE", "no")
        ],
    ],
)
def test_required_lint_contexts_validate_selectors(
    tmp_path, name, detection, selector, other, expected
):
    outputs = {"workflows": selector, "yaml": other}
    if name == "yamllint":
        outputs = {"yaml": selector, "workflows": other}
    context = {
        "needs": {"lint-changes": {"result": detection, "outputs": outputs}},
        "github": {"event_name": "pull_request"},
    }
    job = workflow("lint.yml")["jobs"][name]
    outcome = lint_gate_result(job, context, tmp_path)
    if expected == "skip":
        assert outcome in {"success", "skipped"}
        output = tmp_path / "outputs"
        if output.exists():
            assert output.read_text() == "run=false\n"
    else:
        assert outcome == expected
        if expected == "success":
            assert (tmp_path / "outputs").read_text() == "run=true\n"
