"""Immutable records shared by directory-removal planning and execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemovalMember:
    file: str
    current_file: str
    reason: str
    source_dir: str | None = None
    missing_ok: bool = False


@dataclass(frozen=True)
class DirectoryRemoval:
    dir: str
    current_dir: str
    reason: str
    members: tuple[RemovalMember, ...]


@dataclass(frozen=True)
class RemovalPlan:
    files: tuple[RemovalMember, ...] = ()
    directories: tuple[DirectoryRemoval, ...] = ()
    retained_history: tuple[DirectoryRemoval, ...] = ()

    @property
    def members(self) -> tuple[RemovalMember, ...]:
        return self.files + tuple(
            member for directory in self.directories for member in directory.members
        )
