"""Exercise production gate evaluators and bind the disposable substitutions."""

# ruff: noqa: S101 - pytest assertions in this isolated harness test file.
import copy
import importlib.util
import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = "e7d7ea2e9843bcf7328808360ec4ac53edf9c617"
ORIGINAL = "8a8de788d857e2084c506a455a7b7984802a1718"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gates = load_module("production_ci_gate_tests", ROOT / "tests/meta/test_ci_gates.py")
checks = load_module("gate_payload_checks", ROOT / ".p11a-gates/check.py")
PAYLOAD = gates.workflow("rebrand-matrix.yml")


def checked_in(commit, name):
    git = shutil.which("git")
    assert git
    return subprocess.check_output(  # noqa: S603 - fixed read-only source lookup.
        [git, "show", f"{commit}:{name}"], cwd=ROOT
    ).decode()


LEGACY = {
    name: yaml.load(
        checked_in(ORIGINAL, ".github/workflows/" + name),
        Loader=yaml.BaseLoader,  # noqa: S506 - strings/containers, no constructors.
    )
    for name in ("ci.yml", "lint.yml")
}
BAD_RESULTS = ("failure", "cancelled", "skipped", "", "unknown")
BAD_SELECTORS = (None, "", "TRUE", "FALSE", " true", "false ", "\tfalse", "no")


@pytest.mark.parametrize("event", ["pull_request", "push", "merge_group"])
@pytest.mark.parametrize("code", BAD_SELECTORS)
def test_main_selector_boundaries(tmp_path, event, code):
    context = gates.main_context("true", event)
    context["needs"]["changes"]["outputs"] = {} if code is None else {"code": code}
    step = gates.workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    assert gates.run_step(step, context, tmp_path).returncode != 0


@pytest.mark.parametrize(
    "results", list(itertools.product(("success", "skipped"), repeat=3))
)
def test_all_valid_docs_model_heavy_combinations(tmp_path, results):
    context = gates.main_context("false")
    for name, result in zip(gates.HEAVY, results, strict=True):
        context["needs"][name]["result"] = result
    step = gates.workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    assert gates.run_step(step, context, tmp_path).returncode == 0


@pytest.mark.parametrize(
    "name", ["changes", "lint", "docs", "toml-format", *gates.HEAVY]
)
@pytest.mark.parametrize("result", BAD_RESULTS)
def test_false_selector_does_not_excuse_failed_dependencies(tmp_path, name, result):
    context = gates.main_context("false")
    context["needs"][name]["result"] = result
    expected = name in gates.HEAVY and result == "skipped"
    step = gates.workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    assert (gates.run_step(step, context, tmp_path).returncode == 0) is expected


@pytest.mark.parametrize("code", ["true", "false"])
@pytest.mark.parametrize(
    "name", ["changes", "lint", "docs", "toml-format", *gates.HEAVY]
)
def test_missing_dependency_fails(tmp_path, code, name):
    context = gates.main_context(code)
    del context["needs"][name]
    step = gates.workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    assert gates.run_step(step, context, tmp_path).returncode != 0


@pytest.mark.parametrize("name", ["actionlint", "yamllint"])
@pytest.mark.parametrize("detection", ["success", *BAD_RESULTS])
@pytest.mark.parametrize("workflows", ["true", "false", *BAD_SELECTORS])
@pytest.mark.parametrize("yaml_value", ["true", "false", *BAD_SELECTORS])
def test_lint_full_selector_equivalence_table(
    tmp_path, name, detection, workflows, yaml_value
):
    outputs = {}
    if workflows is not None:
        outputs["workflows"] = workflows
    if yaml_value is not None:
        outputs["yaml"] = yaml_value
    context = {"needs": {"lint-changes": {"result": detection, "outputs": outputs}}}
    job = gates.workflow("lint.yml")["jobs"][name]
    actual = gates.lint_gate_result(job, context, tmp_path)
    valid = (
        detection == "success"
        and workflows in {"true", "false"}
        and yaml_value in {"true", "false"}
    )
    assert actual == ("success" if valid else "failure")
    if valid:
        selected = workflows if name == "actionlint" else yaml_value
        assert (tmp_path / "outputs").read_text() == f"run={selected}\n"
    else:
        assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize(
    "code,event",
    [
        ("", "pull_request"),
        ("TRUE", "pull_request"),
        ("false", "push"),
        ("false", "merge_group"),
    ],
)
def test_original_main_predicate_accepts_control_rejected_now(tmp_path, code, event):
    context = gates.main_context(code, event)
    old = LEGACY["ci.yml"]["jobs"]["ci-ok"]["steps"][0]
    current = gates.workflow("ci.yml")["jobs"]["ci-ok"]["steps"][0]
    assert gates.run_step(old, context, tmp_path).returncode == 0
    assert gates.run_step(current, context, tmp_path).returncode != 0


@pytest.mark.parametrize("name", ["actionlint", "yamllint"])
@pytest.mark.parametrize(
    "detection,value",
    [
        ("success", "TRUE"),
        ("success", "FALSE"),
        ("success", ""),
        ("failure", "true"),
        ("cancelled", "true"),
        ("skipped", "true"),
    ],
)
def test_original_lint_predicate_misses_bad_control(tmp_path, name, detection, value):
    context = {
        "needs": {
            "lint-changes": {
                "result": detection,
                "outputs": {"workflows": value, "yaml": value},
            }
        }
    }
    old = gates.lint_gate_result(LEGACY["lint.yml"]["jobs"][name], context, tmp_path)
    assert old in {"success", "skipped"}
    current = gates.workflow("lint.yml")["jobs"][name]
    assert gates.lint_gate_result(current, context, tmp_path) == "failure"


def test_production_sources_are_unchanged():
    for name in (
        ".github/workflows/ci.yml",
        ".github/workflows/lint.yml",
        "tests/meta/test_ci_gates.py",
        "pyproject.toml",
        "uv.lock",
    ):
        assert (ROOT / name).read_text() == checked_in(BASE, name)


def test_exact_main_validator_and_only_declared_event_substitution():
    original = gates.workflow("ci.yml")["jobs"]["ci-ok"]
    current = PAYLOAD["jobs"]["ci-ok"]
    for key in ("name", "needs", "if", "runs-on", "permissions"):
        assert current[key] == original[key]
    expected = copy.deepcopy(original["steps"][0])
    expected["env"]["EVENT_NAME"] = "$" + "{{ inputs.event_model }}"
    expected["timeout-minutes"] = "1"
    assert current["steps"][0] == expected
    assert current["steps"][1]["if"] == "always()"


@pytest.mark.parametrize("name", ["actionlint", "yamllint"])
def test_exact_lint_validator_and_all_selected_conditions(name):
    original = gates.workflow("lint.yml")["jobs"][name]
    current = PAYLOAD["jobs"][name]
    for key in ("name", "needs", "if", "runs-on", "permissions"):
        assert current[key] == original[key]
    expected = copy.deepcopy(original["steps"][0])
    expected["timeout-minutes"] = "1"
    assert current["steps"][0] == expected
    assert len(current["steps"]) == len(original["steps"])
    for old, new in zip(original["steps"][1:], current["steps"][1:], strict=True):
        assert old["if"] == new["if"]
        assert "uses" not in new


def test_heavy_selectors_and_selected_skip_substitution():
    original = gates.workflow("ci.yml")["jobs"]
    for name in gates.HEAVY:
        assert PAYLOAD["jobs"][name]["if"] == original[name]["if"]
    assert PAYLOAD["jobs"]["test"]["needs"] == ["changes", "lint-changes"]
    assert PAYLOAD["jobs"]["lint-changes"]["if"] == "inputs.case != 'selected-skipped'"


def test_dispatch_only_no_artifact_or_workflow_cancellation():
    assert set(PAYLOAD["on"]) == {"workflow_dispatch"}
    assert "concurrency" not in PAYLOAD
    assert PAYLOAD["permissions"] == {}
    for job in PAYLOAD["jobs"].values():
        assert 1 <= int(job["timeout-minutes"]) <= 2
        for step in job["steps"]:
            assert 1 <= int(step["timeout-minutes"]) <= 2
            assert "upload-artifact" not in step.get("uses", "")
            assert "continue-on-error" not in step
    for name in ("changes", "lint-changes"):
        target = PAYLOAD["jobs"][name]
        successor = PAYLOAD["jobs"]["cancel-" + name]
        assert target["concurrency"]["group"] == successor["concurrency"]["group"]
        assert "github.run_id" in target["concurrency"]["group"]
        assert "github.run_attempt" in target["concurrency"]["group"]
        assert target["concurrency"]["cancel-in-progress"] == "false"
        assert successor["concurrency"]["cancel-in-progress"] == "true"
        assert successor["needs"] == "arm-cancellation"
        assert successor["if"] == "needs.arm-cancellation.outputs.armed == 'true'"


@pytest.mark.parametrize("case", sorted(checks.CASES - {"cancel-detectors"}))
@pytest.mark.parametrize("name", ["changes", "lint-changes"])
def test_real_detector_witness_bodies(tmp_path, case, name):
    step = PAYLOAD["jobs"][name]["steps"][-1]
    bash = shutil.which("bash")
    assert bash
    output = tmp_path / "outputs"
    completed = subprocess.run(  # noqa: S603 - frozen witness and controlled env.
        [bash, "-c", step["run"]],
        env={
            **os.environ,
            "P11A_GATE_CASE": case,
            "OUTPUT_KEYS": step["env"]["OUTPUT_KEYS"],
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == (1 if case == "detector-failure" else 0)
    if case == "missing-output":
        assert not output.exists()
    else:
        value = (
            "false"
            if case == "valid-false"
            else "FALSE"
            if case == "uppercase-false"
            else "true"
        )
        actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert actual == dict.fromkeys(step["env"]["OUTPUT_KEYS"].split(), value)


@pytest.mark.parametrize("name", ["actionlint", "yamllint"])
@pytest.mark.parametrize(
    "case,expected", [("all-pass", 0), ("selected-tool-failure", 1)]
)
def test_real_selected_tool_witness_bodies(tmp_path, name, case, expected):
    step = PAYLOAD["jobs"][name]["steps"][-1]
    context = {"inputs": {"case": case, "event_model": "pull_request"}}
    result = gates.run_step(step, context, tmp_path)
    assert result.returncode == expected


def cancellation_context():
    results = {
        "changes": "cancelled",
        "lint-changes": "cancelled",
        "cancel-changes": "success",
        "cancel-lint-changes": "success",
        "ci-ok": "failure",
        "actionlint": "failure",
        "yamllint": "failure",
    }
    return {"needs": {name: {"result": result} for name, result in results.items()}}


def test_cancellation_proof_accepts_real_expected_conclusions(tmp_path):
    step = PAYLOAD["jobs"]["cancellation-proof"]["steps"][0]
    assert gates.run_step(step, cancellation_context(), tmp_path).returncode == 0


@pytest.mark.parametrize(
    "name,result",
    [
        ("changes", "failure"),
        ("changes", "skipped"),
        ("changes", "success"),
        ("lint-changes", "failure"),
        ("ci-ok", "success"),
        ("actionlint", "skipped"),
        ("yamllint", "success"),
        ("cancel-changes", "failure"),
    ],
)
def test_cancellation_proof_rejects_simulated_or_lost_outcomes(tmp_path, name, result):
    context = cancellation_context()
    context["needs"][name]["result"] = result
    step = PAYLOAD["jobs"]["cancellation-proof"]["steps"][0]
    assert gates.run_step(step, context, tmp_path).returncode != 0


def active_jobs():
    return {
        "total_count": 2,
        "jobs": [
            {
                "id": number,
                "name": name,
                "status": "in_progress",
                "steps": [{"name": checks.WAIT_STEP, "status": "in_progress"}],
            }
            for number, name in enumerate(sorted(checks.TARGETS), 1)
        ],
    }


def test_arm_requires_both_actual_wait_steps():
    payload = active_jobs()
    assert set(checks.ready_jobs(payload)) == checks.TARGETS
    payload["jobs"][0]["steps"][0]["status"] = "queued"
    assert checks.ready_jobs(payload) == {}
    payload["jobs"][0]["steps"][0]["status"] = "in_progress"
    payload["jobs"][1]["status"] = "completed"
    payload["jobs"][1]["conclusion"] = "cancelled"
    assert checks.ready_jobs(payload) == {}


@pytest.mark.parametrize(
    "case,event",
    [
        ("", "pull_request"),
        ("ALL-PASS", "pull_request"),
        ("bad", "pull_request"),
        ("all-pass", "workflow_dispatch"),
    ],
)
def test_unknown_case_or_event_refuses(monkeypatch, case, event):
    monkeypatch.setenv("P11A_GATE_CASE", case)
    monkeypatch.setenv("P11A_EVENT_MODEL", event)
    with pytest.raises(RuntimeError):
        checks.selected_case()


def test_source_normalization_preserves_substantive_changes(tmp_path):
    file = tmp_path / "source.py"
    file.write_bytes(b"answer = 1\n")
    initial = checks.canonical_hash(file)
    file.write_bytes(b"answer = 1\r\n")
    assert checks.canonical_hash(file) == initial
    file.write_bytes(b"answer = 2\r\n")
    assert checks.canonical_hash(file) != initial
