"""Run locked pytest with portable bounded logs; GitHub owns execution limits."""

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from ci_logs import BoundedConsole, BoundedLog

LOG_PART_BYTES = 4 * 1024 * 1024
CONSOLE_LIMIT_BYTES = 1024 * 1024
CONSOLE_TAIL_BYTES = 64 * 1024


def command_output(*args: str) -> dict[str, object]:
    try:
        result = subprocess.run(  # noqa: S603 - fixed metadata commands below.
            args, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error": str(error)[:1024]}
    return {"returncode": result.returncode, "output": result.stdout.strip()[:1024]}


def write_metadata(directory: Path, data: dict[str, object]) -> None:
    target = directory / "runtime.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def run(directory: Path, args: list[str]) -> int:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", "-p", "ci_pytest", *args]
    metadata: dict[str, object] = {
        "started_at": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "process_cpu_count": os.process_cpu_count(),
        "git": command_output("git", "--version"),
        "uv": command_output("uv", "--version"),
        "bun": command_output("bun", "--version"),
        "source_revision": command_output("git", "rev-parse", "HEAD"),
        "runner": {
            key: os.environ.get(key)
            for key in (
                "RUNNER_OS",
                "RUNNER_ARCH",
                "ImageOS",
                "ImageVersion",
                "GITHUB_SHA",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
            )
        },
        "plugins": [
            {
                "name": entry.name,
                "distribution": entry.dist.name,
                "version": entry.dist.version,
            }
            for entry in importlib.metadata.entry_points(group="pytest11")
            if entry.dist is not None
        ],
        "pytest_version": importlib.metadata.version("pytest"),
        "command": command,
    }
    write_metadata(directory, metadata)
    env = dict(os.environ)
    env["PRESS_CI_DIAGNOSTICS_DIR"] = str(directory)
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(Path(__file__).resolve().parent), env.get("PYTHONPATH", ""))
        if part
    )
    env["PYTHONUNBUFFERED"] = "1"
    output = BoundedLog(directory, "output", LOG_PART_BYTES)
    console = BoundedConsole(sys.stdout.buffer, CONSOLE_LIMIT_BYTES, CONSOLE_TAIL_BYTES)
    try:
        with subprocess.Popen(  # noqa: S603 - current interpreter, explicit pytest arguments.
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        ) as process:
            if process.stdout is None:
                raise RuntimeError("pytest output pipe was not created")
            while True:
                try:
                    chunk = process.stdout.read(64 * 1024)
                    if not chunk:
                        result = process.wait()
                        break
                    output.write(chunk)
                    console.write(chunk)
                except KeyboardInterrupt:
                    # Keep the pipe open for the child's interrupt diagnostics.
                    # GitHub still owns termination if the child does not exit.
                    metadata["interrupted"] = True
    finally:
        output.close()
        console.finish()
    metadata.update(returncode=result, finished_at=time.time())
    write_metadata(directory, metadata)
    return result


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 3 or args[1] != "--":
        print(
            "usage: ci_run_pytest.py OUTPUT_DIRECTORY -- PYTEST_ARGUMENTS",
            file=sys.stderr,
        )
        return 2
    return run(Path(args[0]), args[2:])


if __name__ == "__main__":
    raise SystemExit(main())
