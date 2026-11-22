"""Target-language names a target may declare in ``[rules] languages``."""

from __future__ import annotations

KNOWN_LANGUAGES: tuple[str, ...] = ("python", "node", "rust")

# Languages this press version can rebrand; the rest are reserved names.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"python"})
