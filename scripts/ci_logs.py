"""Two-part, size-bounded CI logs that retain recent output after a forced stop."""

import json
from pathlib import Path
from typing import BinaryIO


class BoundedLog:
    """Keep at most two parts; the index lists them in chronological order."""

    def __init__(
        self, directory: Path, prefix: str, part_bytes: int, suffix: str = ".log"
    ) -> None:
        if part_bytes < 1:
            raise ValueError("log part size must be positive")
        self.directory = directory
        self.prefix = prefix
        self.part_bytes = part_bytes
        self.suffix = suffix
        self.part = 0
        self.written = 0
        self.names: list[str] = []
        directory.mkdir(parents=True, exist_ok=True)
        self.file = self._open_part()

    def _open_part(self) -> BinaryIO:
        name = f"{self.prefix}-{self.part}{self.suffix}"
        self.names = [entry for entry in self.names if entry != name] + [name]
        stream = (self.directory / name).open("wb")
        index = self.directory / f"{self.prefix}-index.json"
        temporary = index.with_suffix(".tmp")
        temporary.write_text(json.dumps({"parts": self.names}) + "\n", encoding="utf-8")
        temporary.replace(index)
        return stream

    def _rotate(self) -> None:
        self.file.close()
        self.part = 1 - self.part
        self.written = 0
        self.file = self._open_part()

    def write_record(self, data: bytes) -> None:
        """Keep JSONL records whole when the oldest part is discarded."""
        if len(data) > self.part_bytes:
            raise ValueError("record exceeds log part size")
        if self.written + len(data) > self.part_bytes:
            self._rotate()
        self.write(data)

    def write(self, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            if self.written == self.part_bytes:
                self._rotate()
            count = min(len(remaining), self.part_bytes - self.written)
            self.file.write(remaining[:count])
            self.file.flush()
            self.written += count
            remaining = remaining[count:]

    def close(self) -> None:
        self.file.close()


class BoundedConsole:
    """Limit provider log volume while retaining the final failure context."""

    def __init__(self, stream: BinaryIO, limit_bytes: int, tail_bytes: int) -> None:
        self.stream = stream
        self.limit_bytes = limit_bytes
        self.tail_bytes = tail_bytes
        self.forwarded = 0
        self.truncated = False
        self.tail = b""

    def write(self, data: bytes) -> None:
        self.tail = (self.tail + data[-self.tail_bytes :])[-self.tail_bytes :]
        available = self.limit_bytes - self.forwarded
        prefix = data[:available]
        self.stream.write(prefix)
        self.forwarded += len(prefix)
        if len(data) > available and not self.truncated:
            self.truncated = True
            self.stream.write(
                b"\nCI console limit reached; recent output remains in bounded diagnostic logs.\n"
            )
        self.stream.flush()

    def finish(self) -> None:
        if self.truncated:
            self.stream.write(b"\nFinal retained pytest output:\n" + self.tail + b"\n")
            self.stream.flush()
