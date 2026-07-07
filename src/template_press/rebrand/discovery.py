"""Discover a target repo's identity — the VALIDATOR, never the authority.

Per OQ3 (decision log 2026-06-15): the committed source-config is the
authoritative FROM identity; discovery cross-checks it against the target
(pyproject [project].name / authors, the [project.scripts] key, git origin,
src-vs-flat layout) and the CLI fails loudly on any mismatch. This replaces
the silent half-rebrand failure mode (EMPIRICAL R2) with a hard stop.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 — reads git origin of the target
import tomllib
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.identity import Identity

_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class Discovered:
    package_name: str | None
    app_name: str | None
    owner: str | None
    repo_name: str | None
    author: str | None
    email: str | None
    layout: str | None  # "src" | "flat" | None


def _origin(target: Path) -> tuple[str | None, str | None]:
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        ["git", "-C", str(target), "remote", "get-url", "origin"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, None
    m = _ORIGIN_RE.match(result.stdout.strip())
    return (m["owner"], m["repo"]) if m else (None, None)


def discover(target: Path) -> Discovered:
    package_name = app_name = author = email = None
    pyproject_path = target / "pyproject.toml"
    if pyproject_path.is_file():
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        raw_name = project.get("name")
        if isinstance(raw_name, str):
            package_name = raw_name.replace("-", "_")
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            app_name = str(next(iter(scripts)))
        authors = project.get("authors", [])
        if authors and isinstance(authors[0], dict):
            author = authors[0].get("name")
            email = authors[0].get("email")
    owner, repo_name = _origin(target)
    layout: str | None = None
    if package_name is not None:
        if (target / "src" / package_name).is_dir():
            layout = "src"
        elif (target / package_name).is_dir():
            layout = "flat"
    return Discovered(
        package_name=package_name,
        app_name=app_name,
        owner=owner,
        repo_name=repo_name,
        author=author,
        email=email,
        layout=layout,
    )


def mismatches(source: Identity, found: Discovered) -> list[str]:
    """Non-empty means the source-config does NOT describe this target."""
    out: list[str] = []
    checks: tuple[tuple[str, str | None], ...] = (
        ("package_name", found.package_name),
        ("app_name", found.app_name),
        ("owner", found.owner),
        ("repo_name", found.repo_name),
        ("author", found.author),
        ("email", found.email),
    )
    declared = source.as_dict()
    for field_name, discovered_value in checks:
        if discovered_value is None:
            continue  # undiscoverable field — config stands unchallenged
        if discovered_value != declared[field_name]:
            out.append(
                f"{field_name}: source-config says "
                f"{declared[field_name]!r} but target shows "
                f"{discovered_value!r}"
            )
    return out
