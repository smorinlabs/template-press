"""Read the identity-bearing keys of a target's root ``package.json``.

The manifest is attacker-controlled input (it ships inside the target), so
every key is optional and type-checked: anything absent or malformed is
undiscoverable and is never guessed. Only the root manifest is read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
# npm's "Name <email> (url)" author string; every part after the name is optional.
_AUTHOR_RE = re.compile(
    r"^\s*(?P<name>[^<(]*?)\s*(?:<(?P<email>[^>]*)>)?\s*(?:\([^)]*\))?\s*$"
)


@dataclass(frozen=True)
class NodeManifest:
    name: str | None
    author: str | None
    email: str | None
    bins: tuple[str, ...]
    owner: str | None
    repo_name: str | None
    # Object-form bin keys only. A string-form bin has no key: its command name
    # follows the package name, so it is not a separate identity value.
    named_bins: tuple[str, ...] = ()


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def unscoped(name: str) -> str:
    """``@scope/pkg`` -> ``pkg``; an unscoped name is returned unchanged."""
    return name.split("/", 1)[1] if name.startswith("@") and "/" in name else name


def _author(raw: object) -> tuple[str | None, str | None]:
    if isinstance(raw, dict):
        return _text(raw.get("name")), _text(raw.get("email"))
    if isinstance(raw, str):
        m = _AUTHOR_RE.match(raw)
        if m:
            return _text(m["name"]), _text(m["email"])
    return None, None


def _bins(raw: object, name: str | None) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (unscoped(name),) if name else ()
    if isinstance(raw, dict):
        return tuple(k for k in raw if isinstance(k, str) and k)
    return ()


def _repository(raw: object) -> tuple[str | None, str | None]:
    url = raw.get("url") if isinstance(raw, dict) else raw
    text = _text(url)
    if text is None:
        return None, None
    text = text.removeprefix("git+")
    m = _ORIGIN_RE.match(text)
    return (m["owner"], m["repo"]) if m else (None, None)


def read_node_manifest(target: Path) -> NodeManifest | None:
    """The root ``package.json`` identity keys, or ``None`` when unreadable."""
    path = target / "package.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    name = _text(data.get("name"))
    author, email = _author(data.get("author"))
    owner, repo_name = _repository(data.get("repository"))
    raw_bin = data.get("bin")
    return NodeManifest(
        name=name,
        author=author,
        email=email,
        bins=_bins(raw_bin, name),
        owner=owner,
        repo_name=repo_name,
        named_bins=_bins(raw_bin, None) if isinstance(raw_bin, dict) else (),
    )
