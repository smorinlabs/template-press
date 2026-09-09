"""Bind the disposable gate payload and arm job-scoped cancellation."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "all-pass",
    "valid-false",
    "missing-output",
    "uppercase-false",
    "selected-skipped",
    "detector-failure",
    "selected-tool-failure",
    "cancel-detectors",
}
EVENTS = {"pull_request", "push", "merge_group"}
TARGETS = {"changes", "lint-changes"}
WAIT_STEP = "Emit controlled detector outputs"


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def selected_case() -> tuple[str, str]:
    case = os.environ.get("P11A_GATE_CASE", "")
    event = os.environ.get("P11A_EVENT_MODEL", "")
    require(case in CASES, "unknown gate case")
    require(event in EVENTS, "unknown event model")
    return case, event


def git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git unavailable")
    return subprocess.check_output(  # noqa: S603 - fixed read-only arguments.
        [executable, *args], cwd=ROOT, text=True
    ).strip()


def canonical_hash(path: Path) -> str:
    """Only declared source text permits Git checkout newline conversion."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def freeze(*, working: bool = False) -> None:
    case, event = selected_case()
    manifest = json.loads((ROOT / ".p11a-gates/freeze.json").read_text())
    require(manifest["text_normalization"] == "crlf-to-lf", "unknown normalization")
    actual = {name: canonical_hash(ROOT / name) for name in manifest["source_files"]}
    require(actual == manifest["source_files"], "source or payload differs")
    git("merge-base", "--is-ancestor", manifest["source_commit"], "HEAD")
    if not working:
        changed = git(
            "diff", "--name-only", manifest["source_commit"], "HEAD"
        ).splitlines()
        require(set(changed) == set(manifest["payload_paths"]), "unexpected delta")
        git("diff", "--exit-code", "HEAD")
    print(
        json.dumps(
            {
                "source_freeze": "passed",
                "base": manifest["source_commit"],
                "checkout": git("rev-parse", "HEAD"),
                "actual_event": os.environ.get("GITHUB_EVENT_NAME", "local"),
                "modeled_event": event,
                "case": case,
                "working_only": working,
            },
            sort_keys=True,
        )
    )


def ready_jobs(payload: dict) -> dict[str, int]:
    require(payload["total_count"] <= 100, "unexpected pagination in tiny harness")
    selected = {}
    for name in sorted(TARGETS):
        matches = [job for job in payload["jobs"] if job["name"] == name]
        require(len(matches) <= 1, "ambiguous cancellation target")
        if not matches:
            return {}
        job = matches[0]
        waiting = [step for step in job.get("steps", []) if step["name"] == WAIT_STEP]
        if (
            job["status"] != "in_progress"
            or len(waiting) != 1
            or waiting[0]["status"] != "in_progress"
        ):
            return {}
        selected[name] = int(job["id"])
    return selected


def arm() -> None:
    case, _ = selected_case()
    require(case == "cancel-detectors", "arming is only for cancellation")
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None,
        "invalid repository",
    )
    require(run_id.isdigit() and attempt.isdigit(), "invalid run identity")
    api = os.environ.get("GITHUB_API_URL", "")
    require(api == "https://api.github.com", "unexpected API origin")
    url = (
        f"{api}/repos/{repository}/actions/runs/{run_id}"
        f"/attempts/{attempt}/jobs?per_page=100"
    )
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS API origin.
        url,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        with urllib.request.urlopen(  # noqa: S310 - fixed HTTPS API origin.
            request, timeout=min(5, remaining)
        ) as response:
            payload = json.load(response)
        selected = ready_jobs(payload)
        if selected:
            print(json.dumps({"armed_targets": selected, "run_attempt": attempt}))
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write("armed=true\n")
            return
        time.sleep(min(20, max(0, deadline - time.monotonic())))
    raise RuntimeError("targets were not both executing the wait fixture in 30s")


if __name__ == "__main__":
    if sys.argv[1:] == ["freeze"]:
        freeze()
    elif sys.argv[1:] == ["freeze", "--working"]:
        freeze(working=True)
    elif sys.argv[1:] == ["arm"]:
        arm()
    else:
        raise RuntimeError("unknown check command")
