"""``[verify]`` configuration for `press verify` (Task 9).

Holds the scan-scope knobs the no-leak gate reads: which identity fields to
scan, which fields use substring (not boundary-safe) matching, the
source-anchored ignore list (Task 8's `ignores.Ignore`), and whether a
still-equal source/dest field pair is a warning or a hard error.
Dependency-neutral: imports only `identity` (the known field-name set) and
`ignores` (the `Ignore` dataclass) — never engine/verifier/rules.

`parse_verify_config` is PURE: it takes the already-loaded `[verify]` TOML
mapping and returns a `VerifyConfig`. A thin file-reading loader (Task 12)
is the only I/O boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from template_press.rebrand.identity import REQUIRED_FIELDS, ValidationError
from template_press.rebrand.ignores import Ignore

# Every identity field `press verify` may scan for: the six REQUIRED_FIELDS
# plus the derived `app_name_upper` (present in `Identity.as_dict()` but not
# independently required/validated).
KNOWN_FIELDS: frozenset[str] = frozenset(REQUIRED_FIELDS) | {"app_name_upper"}

# NOTE: no `app_name_upper` (the matcher is case-insensitive, so scanning
# `app_name` already covers the uppercased form — including it would
# double-count) and no `email` (deliberately skipped; opt in via
# `extra_fields`).
DEFAULT_FIELDS: tuple[str, ...] = ("app_name", "package_name", "repo_name", "owner")

_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"extra_fields", "substring_fields", "equal_fields", "ignore"}
)


def _parse_ignore(entry: dict) -> Ignore:
    """One ``[[verify.ignore]]`` table -> ``Ignore``; missing optionals ->
    ``None``/``False``/``""`` (``Ignore.__post_init__`` rejects field & value
    both ``None``)."""
    return Ignore(
        field=entry.get("field"),
        value=entry.get("value"),
        file=entry.get("file", ""),
        anchor=entry.get("anchor", ""),
        line=entry.get("line"),
        ordinal=entry.get("ordinal"),
        force=entry.get("force", False),
        reason=entry.get("reason", ""),
    )


@dataclass(frozen=True)
class VerifyConfig:
    """Parsed ``[verify]`` configuration."""

    fields: tuple[str, ...]
    substring_fields: frozenset[str]
    ignores: tuple[Ignore, ...]
    equal_fields: str  # "warn" | "error"


def parse_verify_config(table: dict | None) -> VerifyConfig:
    """Parse the ``[verify]`` TOML mapping into a ``VerifyConfig``.

    PURE — takes the already-loaded mapping (or ``None`` when the table is
    absent); performs no file I/O.
    """
    if table is None:
        table = {}

    unknown = set(table) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValidationError(f"[verify] unknown key(s): {', '.join(sorted(unknown))}")

    fields = list(DEFAULT_FIELDS)
    for name in table.get("extra_fields", []):
        if name not in KNOWN_FIELDS:
            raise ValidationError(f"[verify] extra_fields: unknown field {name!r}")
        if name not in fields:
            fields.append(name)

    substring_fields = frozenset(table.get("substring_fields", []))
    unknown_substring = substring_fields - set(fields)
    if unknown_substring:
        raise ValidationError(
            f"[verify] substring_fields not in fields: "
            f"{', '.join(sorted(unknown_substring))}"
        )

    equal_fields = table.get("equal_fields", "warn")
    if equal_fields not in ("warn", "error"):
        raise ValidationError(
            f"[verify] equal_fields must be 'warn' or 'error': {equal_fields!r}"
        )

    ignores = tuple(_parse_ignore(entry) for entry in table.get("ignore", []))

    return VerifyConfig(
        fields=tuple(fields),
        substring_fields=substring_fields,
        ignores=ignores,
        equal_fields=equal_fields,
    )
