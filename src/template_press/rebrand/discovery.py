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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from template_press.rebrand.identity import PYTHON_IDENTIFIER_RE, Identity
from template_press.rebrand.languages import KNOWN_LANGUAGES, SUPPORTED_LANGUAGES
from template_press.rebrand.node_manifest import (
    NodeManifest,
    read_node_manifest,
    unscoped,
)
from template_press.rebrand.safety import git_hardening_args, scrubbed_git_env

_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class Discovered:
    package_name: str | None
    app_name: str | None  # FIRST [project.scripts] key, for display/back-compat
    owner: str | None
    repo_name: str | None
    author: str | None
    email: str | None
    layout: str | None  # "src" | "flat" | None
    app_names: tuple[str, ...] = ()  # ALL [project.scripts] keys, insertion order
    # The first checked language in KNOWN_LANGUAGES order, or None. It selects
    # the source-config proposal. When python is not checked, the fatal-check
    # fields above stay None.
    source_kind: str | None = None
    # package.json was checked: the manifest values below feed the two
    # declared-field checks and the non-fatal warnings.
    node_checked: bool = False
    npm_name: str | None = None
    cli_names: tuple[str, ...] = ()  # package.json bin keys, manifest order
    manifest_package_name: str | None = None  # derived from npm_name
    manifest_author: str | None = None
    manifest_email: str | None = None
    manifest_owner: str | None = None  # package.json repository, never origin
    manifest_repo_name: str | None = None
    named_cli_names: tuple[str, ...] = ()  # object-form bin keys only


def _origin(target: Path) -> tuple[str | None, str | None]:
    # A config read on an untrusted target (its .git/config is attacker
    # input) — scrubbed env blocks a poisoned global config from redirecting
    # this; hardening args are cheap insurance even though this is not a
    # working-tree read.
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        [  # noqa: S607
            "git",
            "-C",
            str(target),
            *git_hardening_args(),
            "remote",
            "get-url",
            "origin",
        ],
        capture_output=True,
        text=True,
        env=scrubbed_git_env(),
    )
    if result.returncode != 0:
        return None, None
    m = _ORIGIN_RE.match(result.stdout.strip())
    return (m["owner"], m["repo"]) if m else (None, None)


def _python_project(target: Path) -> dict[str, Any] | None:
    """The ``[project]`` table of the root ``pyproject.toml``, if it has one."""
    pyproject_path = target / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get("project")
    return project if isinstance(project, dict) else None


def discover(target: Path, languages: Sequence[str] | None = None) -> Discovered:
    """Read identity from the manifests of ``languages``.

    The CLI passes the language guard's ``LanguageDecision.checked``. When it
    selects no supported language, every readable manifest is read, so a
    ``package.json`` without ``name`` keeps its declared-field checks.
    """
    package_name = app_name = author = email = None
    app_names: tuple[str, ...] = ()
    selected = SUPPORTED_LANGUAGES.intersection(languages or ())
    project = _python_project(target) if not selected or "python" in selected else None
    manifest = (
        read_node_manifest(target) if not selected or "node" in selected else None
    )
    checked = selected or {
        language
        for language, value in (("python", project), ("node", manifest))
        if value is not None
    }
    source_kind = next((name for name in KNOWN_LANGUAGES if name in checked), None)
    if project is not None:
        raw_name = project.get("name")
        if isinstance(raw_name, str):
            package_name = raw_name.replace("-", "_")
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            app_names = tuple(str(k) for k in scripts)
            app_name = app_names[0]  # first key — display/back-compat
        authors = project.get("authors", [])
        if isinstance(authors, list) and authors and isinstance(authors[0], dict):
            author = authors[0].get("name")
            email = authors[0].get("email")
    owner, repo_name = _origin(target)
    layout: str | None = None
    if package_name is not None:
        if (target / "src" / package_name).is_dir():
            layout = "src"
        elif (target / package_name).is_dir():
            layout = "flat"
    found = Discovered(
        package_name=package_name,
        app_name=app_name,
        owner=owner,
        repo_name=repo_name,
        author=author,
        email=email,
        layout=layout,
        app_names=app_names,
        source_kind=source_kind,
    )
    if manifest is None:
        return found
    return replace(
        found,
        node_checked=True,
        npm_name=manifest.name,
        cli_names=manifest.bins,
        named_cli_names=manifest.named_bins,
        manifest_package_name=(
            unscoped(manifest.name).replace("-", "_") if manifest.name else None
        ),
        manifest_author=manifest.author,
        manifest_email=manifest.email,
        manifest_owner=manifest.owner,
        manifest_repo_name=manifest.repo_name,
    )


def node_proposal(
    manifest: NodeManifest, owner: str | None, repo_name: str | None
) -> dict[str, str | None]:
    """Propose source-config values from ``package.json``; gaps stay ``None``.

    ``owner`` and ``repo_name`` arrive already resolved (git origin first, the
    manifest ``repository`` only as a fallback). Nothing absent is guessed.
    """
    name = manifest.name
    package_name = unscoped(name).replace("-", "_") if name else None
    app_name: str | None = None
    cli_name: str | None = None
    if manifest.bins:
        first = manifest.bins[0]
        if PYTHON_IDENTIFIER_RE.fullmatch(first):
            app_name = first
        elif "-" in first:
            app_name = first.replace("-", "_")
            # A string-form bin has no key: its command follows the package name.
            cli_name = first if first in manifest.named_bins else None
        else:
            app_name = first  # not derivable: validation rejects it cleanly
    return {
        "package_name": package_name,
        "repo_name": repo_name,
        "app_name": app_name,
        "author": manifest.author,
        "email": manifest.email,
        "owner": owner,
        "npm_name": name if name not in (None, repo_name, package_name) else None,
        "cli_name": cli_name,
    }


def mismatches(source: Identity, found: Discovered) -> list[str]:
    """Non-empty means the source-config does NOT describe this target."""
    out: list[str] = []
    checks: tuple[tuple[str, str | None], ...] = (
        ("package_name", found.package_name),
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
    # app_name matches when it is ANY [project.scripts] key (membership),
    # not just the first (F3/D2) — a target may expose several scripts and
    # commit a non-first one. Empty app_names -> undiscoverable, unchallenged.
    if found.app_names and declared["app_name"] not in found.app_names:
        out.append(
            f"app_name: source-config says {declared['app_name']!r} but "
            f"target [project.scripts] exposes {list(found.app_names)!r}"
        )
    if found.node_checked:
        out.extend(_node_mismatches(declared, found))
    if found.package_name is not None and found.layout is None:
        out.append(
            f"layout: pyproject declares {found.package_name!r} but neither "
            f"src/{found.package_name}/ nor {found.package_name}/ exists"
        )
    return out


def _node_mismatches(declared: dict[str, str], found: Discovered) -> list[str]:
    """The only fatal manifest checks: a DECLARED npm_name or cli_name."""
    out: list[str] = []
    npm_name = declared.get("npm_name")
    if npm_name is not None and found.npm_name not in (None, npm_name):
        out.append(
            f"npm_name: source-config says {npm_name!r} but package.json "
            f"name is {found.npm_name!r}"
        )
    cli_name = declared.get("cli_name")
    if cli_name is not None and found.cli_names and cli_name not in found.cli_names:
        out.append(
            f"cli_name: source-config says {cli_name!r} but package.json "
            f"bin exposes {list(found.cli_names)!r}"
        )
    return out


def manifest_warnings(source: Identity, found: Discovered) -> list[str]:
    """Non-fatal package.json disagreements, one stderr line each."""
    if not found.node_checked:
        return []
    declared = source.as_dict()
    out: list[str] = []

    def warn(field_name: str, expected: str, actual: str | None, where: str) -> None:
        if actual is not None and actual != expected:
            out.append(
                f"warning: {field_name}: source-config says {expected!r} "
                f"but {where} shows {actual!r}"
            )

    warn(
        "package_name",
        source.package_name,
        found.manifest_package_name,
        "package.json name",
    )
    warn("author", source.author, found.manifest_author, "package.json author")
    warn("email", source.email, found.manifest_email, "package.json author")
    if found.cli_names and declared.get("cli_name") is None:
        if source.app_name not in found.cli_names:
            out.append(
                f"warning: app_name: source-config says {source.app_name!r} "
                f"but package.json bin exposes {list(found.cli_names)!r}"
            )
    # The repository value is compared with origin when origin exists, else
    # with the source-config; it never feeds a fatal check.
    owner = found.owner if found.owner is not None else source.owner
    repo = found.repo_name if found.repo_name is not None else source.repo_name
    warn("owner", owner, found.manifest_owner, "package.json repository")
    warn("repo_name", repo, found.manifest_repo_name, "package.json repository")
    return out
