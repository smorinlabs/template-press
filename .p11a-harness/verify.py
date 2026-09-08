"""Inspect production evidence; never add files to the upload paths."""

import hashlib
import json
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


def hashes(paths: list[Path]) -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file()
    }


def preflight_files() -> list[Path]:
    return [ROOT / "ci-results/preflight.xml", *ROOT.glob("ci-results/preflight/*")]


def frozen_source() -> None:
    freeze = json.loads((HARNESS / "freeze.json").read_text())
    expected = {entry["path"]: entry["sha256"] for entry in freeze["files"]}
    actual = hashes([ROOT / name for name in expected])
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


def verify_case(case: str) -> None:
    require(case in {"pass", "fail", "exit7", "worker-loss"}, "unknown finite case")
    if case == "pass":
        modes = ["preflight", "full"]
    else:
        modes = ["full" if case == "worker-loss" else "preflight"]
    for mode in modes:
        metadata, records = evidence(mode)
        workers = 0 if mode == "preflight" else 2
        expected = 0 if case == "pass" else 7 if case == "exit7" else 1
        require(metadata["returncode"] == expected, "native evidence condition failed")
        require(
            metadata["finished_at"] >= metadata["started_at"],
            "native evidence condition failed",
        )
        active = [row for row in records if row["phase"] == "test_call"]
        if case == "exit7":
            require(
                any(
                    row["phase"] == "session_setup"
                    and row["worker"] == "controller"
                    and row["no_test_started"]
                    and row["nodeid"] is None
                    for row in records
                ),
                "native evidence condition failed",
            )
        else:
            expected_worker = "controller" if not workers else "gw"
            require(
                any(
                    row["nodeid"].endswith("::test_probe")
                    and not row["no_test_started"]
                    and row["worker"].startswith(expected_worker)
                    for row in active
                ),
                "missing active test/process identity",
            )
            cases = ET.parse(ROOT / f"ci-results/{mode}.xml").findall(".//testcase")  # noqa: S314 - synthetic local fixture output.
            require(
                cases and any(item.attrib["name"] == "test_probe" for item in cases),
                "native evidence condition failed",
            )
            if case == "fail":
                require(
                    any(item.find("failure") is not None for item in cases),
                    "native evidence condition failed",
                )
        if case == "pass":
            require(
                any(row.get("worker_count") == workers for row in records),
                "native evidence condition failed",
            )
            require(
                any(row.get("outcome") == "passed" for row in records),
                "native evidence condition failed",
            )
        if case == "worker-loss":
            losses = [row for row in records if row["phase"] == "worker_lost"]
            require(len(losses) == 1, "native evidence condition failed")
            require(
                any(row["worker"] == losses[0]["affected_worker"] for row in active),
                "native evidence condition failed",
            )
            started = {
                row["affected_worker"]
                for row in records
                if row["phase"] == "worker_starting"
            }
            require(
                {"gw0", "gw1"} < started and len(started) == 3,
                "native evidence condition failed",
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
    if sys.argv[1] == "freeze":
        frozen_source()
    elif sys.argv[1] == "checkpoint":
        (HARNESS / "preflight-before.json").write_text(
            json.dumps(hashes(preflight_files()))
        )
    else:
        verify_case(sys.argv[1])
