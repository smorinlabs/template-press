"""Inspect production evidence; never add files to the upload paths."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path.cwd()
HARNESS = ROOT / ".p11a-harness"
sys.path.insert(0, str(ROOT / "scripts"))

from ci_pytest import JOURNAL_PART_BYTES, NODEID_PREFIX_CHARS  # noqa: E402
from ci_run_pytest import LOG_PART_BYTES  # noqa: E402


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is missing from the native runner PATH")
    # Fixed read-only Git operations on the harness checkout.
    return subprocess.check_output([executable, *args], text=True).strip()  # noqa: S603


def hashes(paths: list[Path], *, normalize_crlf: bool = False) -> dict[str, str]:
    result = {}
    for path in sorted(paths):
        if path.is_file():
            data = path.read_bytes()
            if normalize_crlf:
                data = data.replace(b"\r\n", b"\n")
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
    return result


def preflight_files() -> list[Path]:
    return [ROOT / "ci-results/preflight.xml", *ROOT.glob("ci-results/preflight/*")]


def frozen_source() -> None:
    freeze = json.loads((HARNESS / "freeze.json").read_text())
    require(freeze["text_normalization"] == "crlf-to-lf", "unknown normalization")
    expected = {entry["path"]: entry["sha256"] for entry in freeze["files"]}
    # Only the manifest's declared source text files permit checkout newlines.
    # Generated evidence and preflight checkpoints remain byte-exact.
    actual = hashes([ROOT / name for name in expected], normalize_crlf=True)
    require(actual == expected, "source or harness bytes differ from freeze")
    git("merge-base", "--is-ancestor", freeze["source_commit"], "HEAD")
    changed = git("diff", "--name-only", freeze["source_commit"], "HEAD").splitlines()
    require(set(changed) == set(freeze["payload_paths"]), "unexpected source delta")
    git("diff", "--exit-code", "HEAD")
    revision = git("rev-parse", "HEAD")
    print(
        f"Source freeze passed: baseline={freeze['source_commit']} checkout={revision}"
    )


def evidence(mode: str) -> tuple[dict, list[dict]]:
    directory = ROOT / "ci-results" / mode
    metadata = json.loads((directory / "runtime.json").read_text())
    records = []
    for index in directory.glob("progress-*-index.json"):
        names = json.loads(index.read_text())["parts"]
        require(1 <= len(names) <= 2, "native evidence condition failed")
        previous = 0
        for name in names:
            require(Path(name).name == name, "native evidence condition failed")
            part = (directory / name).read_bytes()
            require(len(part) <= JOURNAL_PART_BYTES, "native evidence condition failed")
            for line in part.splitlines():
                row = json.loads(line)
                require(row["sequence"] > previous, "native evidence condition failed")
                previous = row["sequence"]
                require(
                    row["pid"] > 0 and row["worker"], "native evidence condition failed"
                )
                require(
                    len(row.get("nodeid") or "") <= NODEID_PREFIX_CHARS,
                    "native evidence condition failed",
                )
                records.append(row)
    names = json.loads((directory / "output-index.json").read_text())["parts"]
    require(1 <= len(names) <= 2, "native evidence condition failed")
    for name in names:
        require(Path(name).name == name, "native evidence condition failed")
        require(
            (directory / name).stat().st_size <= LOG_PART_BYTES,
            "native evidence condition failed",
        )
    require(records, "no production progress records")
    require(
        metadata["cpu_count"] and metadata["process_cpu_count"],
        "native evidence condition failed",
    )
    require(
        {item["name"] for item in metadata["plugins"]} >= {"xdist", "pytest_cov"},
        "native evidence condition failed",
    )
    revision = git("rev-parse", "HEAD")
    require(
        metadata["source_revision"] == {"returncode": 0, "output": revision},
        "native evidence condition failed",
    )
    return metadata, records


NODE = "test_probe.py::test_probe"


def verify_junit(mode: str, case: str) -> None:
    path = ROOT / f"ci-results/{mode}.xml"
    if case == "exit7" and not path.exists():
        return
    root = ET.parse(path).getroot()  # noqa: S314 - synthetic fixture output.
    tests = root.findall(".//testcase")
    suites = root.findall(".//testsuite")
    if case == "exit7":
        require(not tests, "exit7 JUnit reports test execution")
        require(
            all(int(suite.attrib["tests"]) == 0 for suite in suites),
            "exit7 JUnit test count is nonzero",
        )
        return
    require(
        len(tests) == 1 and tests[0].attrib["name"] == "test_probe",
        "JUnit must report exactly the fixture test",
    )
    require(
        len(suites) == 1 and int(suites[0].attrib["tests"]) == 1,
        "JUnit fixture count differs",
    )
    counts = {
        name: len(tests[0].findall(tag))
        for name, tag in [
            ("failures", "failure"),
            ("errors", "error"),
            ("skipped", "skipped"),
        ]
    }
    require(
        all(int(suites[0].attrib[name]) == count for name, count in counts.items()),
        "JUnit totals contradict fixture outcome",
    )
    if case == "pass":
        require(not any(counts.values()), "passing fixture has failure, error or skip")
    elif case == "fail":
        require(
            counts == {"failures": 1, "errors": 0, "skipped": 0},
            "assertion fixture did not fail",
        )
    else:
        require(
            counts["failures"] + counts["errors"] == 1 and counts["skipped"] == 0,
            "worker crash is absent from JUnit",
        )


def same_test(row: dict, active: dict) -> bool:
    return all(row.get(key) == active[key] for key in ("worker", "pid", "nodeid"))


def verify_completed_test(records: list[dict], active: dict, case: str) -> None:
    results = [row for row in records if row["phase"] == "test_result"]
    expected = {
        ("setup", "passed"),
        ("call", "passed" if case == "pass" else "failed"),
        ("teardown", "passed"),
    }
    require(
        len(results) == 3 and all(same_test(row, active) for row in results),
        "fixture results lack matching process/test identity",
    )
    require(
        {(row["when"], row["outcome"]) for row in results} == expected,
        "fixture call outcome or phase is wrong",
    )
    finished = [row for row in records if row["phase"] == "test_finished"]
    require(
        len(finished) == 1 and same_test(finished[0], active),
        "fixture protocol did not finish",
    )


def verify_case(case: str) -> None:
    require(case in {"pass", "fail", "exit7", "worker-loss"}, "unknown finite case")
    modes = (
        ["preflight", "full"]
        if case == "pass"
        else ["full" if case == "worker-loss" else "preflight"]
    )
    for mode in modes:
        metadata, records = evidence(mode)
        workers = 0 if mode == "preflight" else 2
        expected_exit = 0 if case == "pass" else 7 if case == "exit7" else 1
        require(metadata["returncode"] == expected_exit, "runtime exit differs")
        require(
            metadata["finished_at"] >= metadata["started_at"], "runtime did not finish"
        )
        verify_junit(mode, case)
        active = [row for row in records if row["phase"] == "test_call"]
        if case == "exit7":
            require(
                any(row["phase"] == "session_setup" for row in records),
                "exit7 has no session evidence",
            )
            require(
                all(
                    row["worker"] == "controller"
                    and row["no_test_started"]
                    and row["nodeid"] is None
                    and not row["phase"].startswith("test_")
                    for row in records
                ),
                "exit7 contains test execution",
            )
        else:
            allowed = {"controller"} if not workers else {"gw0", "gw1"}
            require(
                len(active) == 1
                and active[0]["worker"] in allowed
                and active[0]["nodeid"] == NODE
                and not active[0]["no_test_started"],
                "missing exact fixture/process identity",
            )
            require(
                active[0]["nodeid_sha256"] == hashlib.sha256(NODE.encode()).hexdigest()
                and active[0]["nodeid_chars"] == len(NODE),
                "fixture node hash or length differs",
            )
        if case in {"pass", "fail"}:
            verify_completed_test(records, active[0], case)
            expected_sessions = {"controller": expected_exit}
            if workers:
                expected_sessions.update(gw0=0, gw1=0)
            finished = [row for row in records if row["phase"] == "session_finished"]
            require(
                len(finished) == len(expected_sessions)
                and {row["worker"]: row["exitstatus"] for row in finished}
                == expected_sessions,
                "session completion or exit differs",
            )
        if case == "pass":
            require(
                any(row.get("worker_count") == workers for row in records),
                "worker count differs",
            )
            ready = [row for row in records if row["phase"] == "worker_ready"]
            expected_ready = {"gw0", "gw1"} if workers else set()
            require(
                len(ready) == workers
                and {row["affected_worker"] for row in ready} == expected_ready
                and all(row["worker"] == "controller" for row in ready),
                "worker readiness differs",
            )
        if case == "worker-loss":
            losses = [row for row in records if row["phase"] == "worker_lost"]
            require(
                len(losses) == 1
                and losses[0]["worker"] == "controller"
                and active[0]["worker"] == losses[0]["affected_worker"],
                "worker loss does not match active fixture",
            )
            started = {
                row["affected_worker"]
                for row in records
                if row["phase"] == "worker_starting"
            }
            require(
                {"gw0", "gw1"} < started and len(started) == 3,
                "replacement worker identity differs",
            )
        print(
            f"Production evidence passed: case={case} mode={mode} rows={len(records)}"
        )
    if case == "pass":
        checkpoint = json.loads((HARNESS / "preflight-before.json").read_text())
        require(
            hashes(preflight_files()) == checkpoint,
            "full run changed preflight evidence",
        )


if __name__ == "__main__":
    if len(sys.argv) == 1:
        verify_case(os.environ.get("P11A_CASE", ""))
    elif sys.argv[1:] == ["freeze"]:
        frozen_source()
    elif sys.argv[1:] == ["checkpoint"]:
        (HARNESS / "preflight-before.json").write_text(
            json.dumps(hashes(preflight_files()))
        )
    else:
        raise RuntimeError("unknown verification command")
