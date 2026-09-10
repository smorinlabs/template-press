"""Opt-in pytest progress journal; no changes to selection, results or deadlines."""

import hashlib
import json
import os
import re
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from ci_logs import BoundedLog

JOURNAL_PART_BYTES = 1024 * 1024
NODEID_PREFIX_CHARS = 512


class Journal:
    def __init__(self, directory: Path) -> None:
        self.worker = os.environ.get("PYTEST_XDIST_WORKER", "controller")
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", self.worker)[:32]
        self.log = BoundedLog(
            directory, f"progress-{name}-{os.getpid()}", JOURNAL_PART_BYTES, ".jsonl"
        )
        self.node: dict[str, object] = {"nodeid": None}
        self.started = False
        self.sequence = 0

    def start_test(self, nodeid: str) -> None:
        self.started = True
        self.node = {
            "nodeid": nodeid[:NODEID_PREFIX_CHARS],
            "nodeid_sha256": hashlib.sha256(
                nodeid.encode("utf-8", errors="surrogatepass")
            ).hexdigest(),
            "nodeid_chars": len(nodeid),
        }

    def write(self, phase: str, **details: object) -> None:
        self.sequence += 1
        row = {
            "phase": phase,
            "worker": self.worker,
            "pid": os.getpid(),
            "sequence": self.sequence,
            "time": time.time(),
            "no_test_started": not self.started,
            **self.node,
            **details,
        }
        self.log.write_record(
            (json.dumps(row, ensure_ascii=True) + "\n").encode("utf-8")
        )


_journal: Journal | None = None


def journal() -> Journal | None:
    global _journal
    directory = os.environ.get("PRESS_CI_DIAGNOSTICS_DIR")
    if _journal is None and directory:
        _journal = Journal(Path(directory))
    return _journal


def record(phase: str, **details: object) -> None:
    if active := journal():
        active.write(phase, **details)


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests() -> None:
    record("session_setup")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart() -> None:
    record(
        "session_setup",
        worker_count=int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "0")),
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collectstart(collector: pytest.Collector) -> None:
    record("collection", collector=collector.nodeid[:512])


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    if active := journal():
        active.start_test(item.nodeid)
        active.write("test_protocol")
    try:
        return (yield)
    finally:
        record("test_finished")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup() -> None:
    record("test_setup")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call() -> None:
    record("test_call")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown() -> None:
    record("test_teardown")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport() -> Generator[
    None, pytest.TestReport, pytest.TestReport
]:
    report = yield
    record("test_result", when=report.when, outcome=report.outcome)
    return report


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_setupnodes(specs: list[object]) -> None:
    record("workers_starting", worker_count=len(specs))


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: Any) -> None:
    record("worker_starting", affected_worker=node.gateway.id)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodeready(node: Any) -> None:
    record("worker_ready", affected_worker=node.gateway.id)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: object | None) -> None:
    record(
        "worker_lost" if error is not None else "worker_finished",
        affected_worker=node.gateway.id,
        error=None if error is None else str(error)[:512],
    )


def pytest_sessionfinish(exitstatus: int) -> None:
    record("session_finished", exitstatus=int(exitstatus))


def pytest_unconfigure() -> None:
    global _journal
    if _journal is not None:
        _journal.log.close()
        _journal = None
