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
KNOWN_FIELDS: frozenset[str] = frozenset(REQUIRED_FIELDS) | {
    "app_name_upper",
    "display_name",
}

# NOTE: no `app_name_upper` (the matcher is case-insensitive, so scanning
# `app_name` already covers the uppercased form — including it would
# double-count) and no `email` (deliberately skipped; opt in via
# `extra_fields`).
DEFAULT_FIELDS: tuple[str, ...] = ("app_name", "package_name", "repo_name", "owner")

_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"extra_fields", "substring_fields", "equal_fields", "ignore"}
)

_IGNORE_KEYS: frozenset[str] = frozenset(
    {"field", "value", "file", "anchor", "line", "ordinal", "force", "reason"}
)


def _str_list(table: dict, key: str) -> list[str]:
    """``table[key]`` (default ``[]``) as a list of str — fail closed on any
    other shape (mirrors ``rules.py:_str_list``'s isinstance guard)."""
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"[verify] {key} must be a list of strings: {value!r}")
    return value


def _parse_ignore(entry: dict) -> Ignore:
    """One ``[[verify.ignore]]`` table -> ``Ignore``; missing optionals ->
    ``None``/``False``/``""`` (``Ignore.__post_init__`` rejects field & value
    both ``None``). Fails closed on a non-table entry or an unknown key
    (e.g. a misspelled ``reason``) rather than silently defaulting."""
    if not isinstance(entry, dict):
        raise ValidationError(f"[verify.ignore] entry must be a table: {entry!r}")
    unknown = set(entry) - _IGNORE_KEYS
    if unknown:
        raise ValidationError(
            f"[verify.ignore] unknown key(s): {', '.join(sorted(unknown))}"
        )
    # Fail-closed value-type validation. A mistyped `force = "true"` (string)
    # is truthy in Python, so `not ignore.force` would SILENTLY disable the
    # staleness check — exactly the drift this module exists to catch. TOML
    # `true` parses as a Python bool, so legit configs are unaffected.
    for key in ("field", "value", "file", "anchor", "reason"):
        if key in entry and not isinstance(entry[key], str):
            raise ValidationError(
                f"[verify.ignore] {key} must be a string: {entry[key]!r}"
            )
    for key in ("line", "ordinal"):
        if key in entry and (
            not isinstance(entry[key], int) or isinstance(entry[key], bool)
        ):
            raise ValidationError(
                f"[verify.ignore] {key} must be an integer: {entry[key]!r}"
            )
    if "force" in entry and not isinstance(entry["force"], bool):
        raise ValidationError(
            f"[verify.ignore] force must be a boolean: {entry['force']!r}"
        )
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
    if not isinstance(table, dict):
        raise ValidationError(f"[verify] must be a table, got {type(table).__name__}")

    unknown = set(table) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValidationError(f"[verify] unknown key(s): {', '.join(sorted(unknown))}")

    fields = list(DEFAULT_FIELDS)
    for name in _str_list(table, "extra_fields"):
        if name not in KNOWN_FIELDS:
            raise ValidationError(f"[verify] extra_fields: unknown field {name!r}")
        if name not in fields:
            fields.append(name)

    substring_fields = frozenset(_str_list(table, "substring_fields"))
    unknown_substring = substring_fields - set(fields)
    if unknown_substring:
        raise ValidationError(
            f"[verify] substring_fields not in fields: "
            f"{', '.join(sorted(unknown_substring))}"
        )

    equal_fields = table.get("equal_fields", "warn")
    if not isinstance(equal_fields, str) or equal_fields not in ("warn", "error"):
        raise ValidationError(
            f"[verify] equal_fields must be 'warn' or 'error': {equal_fields!r}"
        )

    raw_ignores = table.get("ignore", [])
    if not isinstance(raw_ignores, list):
        raise ValidationError(
            f"[verify] ignore must be a list of tables: {raw_ignores!r}"
        )
    ignores = tuple(_parse_ignore(entry) for entry in raw_ignores)

    return VerifyConfig(
        fields=tuple(fields),
        substring_fields=substring_fields,
        ignores=ignores,
        equal_fields=equal_fields,
    )
