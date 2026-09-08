"""Real pytest/xdist controls for CI evidence, without product test changes."""

import hashlib
import importlib
import io
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/ci_run_pytest.py"


def probe(tmp_path, body, workers=0, conftest=""):
    source = tmp_path / "test_probe.py"
    source.write_text(body)
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    if conftest:
        (tmp_path / "conftest.py").write_text(conftest)
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    args = [
        "-c",
        str(config),
        str(source),
        "-n",
        str(workers),
        "--durations=25",
        "--durations-min=0.01",
        "-o",
        "faulthandler_timeout=0.2",
        f"--junitxml={result_dir / 'tests.xml'}",
    ]
    if RUNNER.exists():
        command = [sys.executable, str(RUNNER), str(result_dir), "--", *args]
    else:
        # RED control uses locked pytest's built-in diagnostics directly.
        command = [sys.executable, "-m", "pytest", *args]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
    ):
        env.pop(key, None)
    completed = subprocess.run(  # noqa: S603 - test-owned source, fixed executable.
        command,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=30,
    )
    records = [
        json.loads(line)
        for path in result_dir.glob("progress-*.jsonl")
        for line in path.read_text().splitlines()
    ]
    return completed, records, result_dir


@pytest.mark.slow
@pytest.mark.parametrize("workers", [0, 2])
def test_delayed_body_retains_worker_test_and_stack(tmp_path, workers):
    completed, records, result_dir = probe(
        tmp_path,
        "import time\ndef test_delayed_body():\n"
        "    time.sleep(0.7)\n    assert False, 'controlled body failure'\n",
        workers,
    )
    assert completed.returncode == 1
    active = [row for row in records if row["phase"] == "test_call"]
    assert active and active[0]["nodeid"].endswith("::test_delayed_body")
    assert active[0]["no_test_started"] is False
    if workers == 0:
        assert active[0]["worker"] == "controller"
    else:
        assert active[0]["worker"].startswith("gw")
    retained = b"".join(path.read_bytes() for path in result_dir.glob("output-*.log"))
    assert b"Timeout (" in retained and b"test_delayed_body" in retained


@pytest.mark.slow
@pytest.mark.parametrize("workers", [0, 2])
def test_collection_failure_retains_explicit_no_test_state(tmp_path, workers):
    completed, records, _ = probe(
        tmp_path,
        "import time\ntime.sleep(0.7)\n"
        "raise RuntimeError('controlled collection failure')\n",
        workers,
    )
    assert completed.returncode != 0
    collecting = [row for row in records if row["phase"] == "collection"]
    assert collecting
    assert all(row["no_test_started"] and row["nodeid"] is None for row in collecting)
    if workers:
        assert {row["worker"] for row in collecting} >= {"gw0", "gw1"}


@pytest.mark.slow
def test_worker_loss_preserves_last_test_and_restart_outcome(tmp_path):
    completed, records, _ = probe(
        tmp_path,
        "import os\ndef test_worker_loss():\n    os._exit(3)\n"
        "def test_passing_control():\n    assert True\n",
        2,
    )
    assert completed.returncode == 1
    losses = [row for row in records if row["phase"] == "worker_lost"]
    assert losses
    lost_worker = losses[0]["affected_worker"]
    assert any(
        row["worker"] == lost_worker
        and row["phase"] == "test_call"
        and row["nodeid"].endswith("::test_worker_loss")
        for row in records
    )
    assert any(
        row["phase"] == "worker_starting"
        and row["affected_worker"] not in {"gw0", "gw1"}
        for row in records
    )


@pytest.mark.slow
@pytest.mark.parametrize("workers", [0, 2])
def test_passing_control_keeps_junit_and_runtime_metadata(tmp_path, workers):
    completed, records, result_dir = probe(
        tmp_path, "def test_passing_control():\n    assert True\n", workers
    )
    assert completed.returncode == 0, completed.stdout.decode(errors="replace")
    cases = ET.parse(result_dir / "tests.xml").findall(".//testcase")  # noqa: S314 - test-owned XML.
    assert [case.attrib["name"] for case in cases] == ["test_passing_control"]
    assert records and any(row["phase"] == "session_finished" for row in records)
    metadata = json.loads((result_dir / "runtime.json").read_text())
    assert metadata["python"] == sys.version
    assert metadata["cpu_count"]
    assert {plugin["name"] for plugin in metadata["plugins"]} >= {"xdist", "pytest_cov"}
    if workers:
        assert any(row.get("worker_count") == workers for row in records)
    else:
        assert any(row.get("worker_count") == 0 for row in records)


@pytest.mark.slow
def test_early_session_failure_has_no_test_state(tmp_path):
    completed, records, _ = probe(
        tmp_path,
        "def test_unused():\n    pass\n",
        conftest="import time\ntime.sleep(0.3)\nraise RuntimeError('session setup probe')\n",
    )
    assert completed.returncode != 0
    assert any(
        row["phase"] == "session_setup"
        and row["no_test_started"]
        and row["nodeid"] is None
        for row in records
    )


@pytest.mark.slow
def test_runner_preserves_custom_pytest_exit_code(tmp_path):
    completed, records, _ = probe(
        tmp_path,
        "def test_unused():\n    pass\n",
        conftest="import pytest\ndef pytest_sessionstart():\n    pytest.exit('controlled exit', returncode=7)\n",
    )
    assert completed.returncode == 7
    assert records


@pytest.mark.slow
def test_nested_probe_preserves_parent_temporary_directory(tmp_path, monkeypatch):
    parent_temp = tmp_path / "parent-temp"
    parent_temp.mkdir()
    sentinel = parent_temp / "parent-owned.txt"
    sentinel.write_text("parent state")
    monkeypatch.setenv("PYTEST_ADDOPTS", f"--basetemp={parent_temp}")
    completed, _, _ = probe(
        tmp_path, "def test_nested(tmp_path):\n    assert tmp_path.is_dir()\n"
    )
    assert completed.returncode == 0
    assert sentinel.read_text() == "parent state"


def test_rotating_journal_keeps_whole_recent_records(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    logs = importlib.import_module("ci_logs")
    log = logs.BoundedLog(tmp_path, "progress", 80, ".jsonl")
    for sequence in range(12):
        log.write_record(
            (json.dumps({"sequence": sequence, "phase": "test_call"}) + "\n").encode()
        )
    log.close()
    index = json.loads((tmp_path / "progress-index.json").read_text())
    paths = [tmp_path / name for name in index["parts"]]
    retained = [
        json.loads(line) for path in paths for line in path.read_text().splitlines()
    ]
    assert retained[-1] == {"sequence": 11, "phase": "test_call"}
    assert len(paths) == 2 and all(path.stat().st_size <= 80 for path in paths)


def test_bounded_output_keeps_recent_bytes_and_limits_provider_log(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    logs = importlib.import_module("ci_logs")
    log = logs.BoundedLog(tmp_path, "output", 80)
    stream = io.BytesIO()
    console = logs.BoundedConsole(stream, 30, 20)
    output = b"start-" + b"a" * 1000 + b"-last failure context"
    for offset in range(0, len(output), 37):
        log.write(output[offset : offset + 37])
        console.write(output[offset : offset + 37])
    console.finish()
    log.close()
    index = json.loads((tmp_path / "output-index.json").read_text())
    retained = b"".join((tmp_path / name).read_bytes() for name in index["parts"])
    assert len(retained) <= 160 and output.endswith(retained)
    assert retained.endswith(b"-last failure context")
    assert stream.getvalue().startswith(output[:30])
    assert stream.getvalue().endswith(output[-20:] + b"\n")
    assert stream.getvalue().count(b"CI console limit reached") == 1
    assert len(stream.getvalue()) < 200


def test_journal_bounds_large_names_without_losing_identity(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    plugin = importlib.import_module("ci_pytest")
    journal = plugin.Journal(tmp_path)
    nodes = ["test_example[" + "x" * (1024 * 1024) + suffix for suffix in ("a]", "b]")]
    for node in nodes:
        journal.start_test(node)
        journal.write("test_call")
    journal.log.close()
    rows = [
        json.loads(line)
        for path in tmp_path.glob("progress-*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert rows[0]["nodeid"] == rows[1]["nodeid"]
    assert len(rows[0]["nodeid"]) <= 512
    assert [row["nodeid_sha256"] for row in rows] == [
        hashlib.sha256(node.encode()).hexdigest() for node in nodes
    ]
    assert all(
        row["nodeid_chars"] == len(node) for row, node in zip(rows, nodes, strict=True)
    )
    assert sum(path.stat().st_size for path in tmp_path.glob("progress-*.jsonl")) < 4096
