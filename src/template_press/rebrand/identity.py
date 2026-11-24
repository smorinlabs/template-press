"""Identity model and boundary-safe token matching for the rebrand press.

Ported from the proven init/ engine (branch feat/init-rebrand-robustness):
validators from init/common.py:133-197, boundary patterns from
init/common.py:102-130 — generalized from a module-global BLUEPRINT_IDENTITY
to per-run values so any target's identity can be pressed (ARCH-03).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

PYTHON_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REPO_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
GITHUB_OWNER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$")
NPM_NAME_MAX_LENGTH = 214
CLI_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# A role may not end in "_upper": {cargo_ident_<role>_upper} would otherwise be
# ambiguous between role "x" uppercased and a role literally named "x_upper".
CARGO_ROLE_RE = re.compile(r"^(?!.*_upper$)[a-z][a-z0-9_]*$")
# A leading underscore is allowed (maturin library names); a bare "_" is not.
CARGO_NAME_RE = re.compile(r"^(?=.*[A-Za-z0-9])[A-Za-z_][A-Za-z0-9_-]*$")
CARGO_EXACT_PREFIX = "cargo_exact_"
CARGO_IDENT_PREFIX = "cargo_ident_"
CARGO_BIN_ENV_TAG = "cargo_binenv_"
# Cargo defines this prefix exactly for integration tests of each binary.
CARGO_BIN_EXE_PREFIX = "CARGO_BIN_EXE_"

# Whole values that are filesystem path traversal segments rather than names.
# Only the free-form fields (author, display_name) can hold them — every other
# field's charset already excludes ".". A rule rendering one of these into a
# path component or a symlink target would repoint the link at its own or its
# parent directory; rejecting the value is the root-cause fix, and it leaves
# ordinary dotted names ("Node.js", "J. R. R. Tolkien") untouched.
_PATH_DOT_SEGMENTS: frozenset[str] = frozenset({".", ".."})


class ValidationError(ValueError):
    """Raised when an identity field fails its validator."""


def validate_package_name(name: str) -> str:
    if not PYTHON_IDENTIFIER_RE.fullmatch(name):
        raise ValidationError(
            f"package name must be a valid lowercase Python identifier "
            f"(matching {PYTHON_IDENTIFIER_RE.pattern}): {name!r}"
        )
    return name


def validate_repo_name(name: str) -> str:
    if not REPO_NAME_RE.fullmatch(name):
        raise ValidationError(
            f"repo name must be lowercase alphanumeric + hyphens "
            f"(matching {REPO_NAME_RE.pattern}): {name!r}"
        )
    return name


def validate_owner(name: str) -> str:
    if not GITHUB_OWNER_RE.fullmatch(name):
        raise ValidationError(
            f"GitHub owner must be 1-39 chars, alphanumeric + hyphens, "
            f"not starting/ending with hyphen: {name!r}"
        )
    return name


def validate_email(value: str) -> str:
    if not EMAIL_RE.fullmatch(value):
        raise ValidationError(f"email must look like local@domain.tld: {value!r}")
    return value


def validate_author(value: str) -> str:
    # No charset restriction (names are worldwide), but a degenerate value
    # is catastrophic: an empty token compiles to a zero-width match-anywhere
    # pattern and control chars break the rendered TOML/receipts.
    if not value.strip():
        raise ValidationError("author must not be empty")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
        raise ValidationError(f"author must not contain control characters: {value!r}")
    if value in _PATH_DOT_SEGMENTS:
        raise ValidationError(f"author must not be a path dot segment: {value!r}")
    return value


def validate_app_name(name: str) -> str:
    # The app short name becomes the CLI command, file name prefixes
    # (<app>_config.toml), and — uppercased — the env-var prefix, so it must
    # be identifier-safe (no hyphens: ACME-X is not a valid env var).
    if not PYTHON_IDENTIFIER_RE.fullmatch(name):
        raise ValidationError(
            f"app name must be a valid lowercase Python identifier "
            f"(matching {PYTHON_IDENTIFIER_RE.pattern}): {name!r}"
        )
    return name


def validate_display_name(value: str) -> str:
    # The humanized product name ("Py Launch Blueprint"). Same posture as
    # author: worldwide charset, but empty/control values are catastrophic
    # (empty compiles to a match-anywhere pattern; control chars break TOML).
    if not value.strip():
        raise ValidationError("display name must not be empty")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
        raise ValidationError(
            f"display name must not contain control characters: {value!r}"
        )
    if value in _PATH_DOT_SEGMENTS:
        raise ValidationError(f"display name must not be a path dot segment: {value!r}")
    return value


def validate_npm_name(name: str) -> str:
    # The exact root package.json "name": optionally scoped, lowercase, at most
    # 214 characters (npm's own limit, scope included).
    if len(name) > NPM_NAME_MAX_LENGTH or not NPM_NAME_RE.fullmatch(name):
        raise ValidationError(
            f"npm name must be an optionally scoped lowercase npm package name "
            f"of at most {NPM_NAME_MAX_LENGTH} characters "
            f"(matching {NPM_NAME_RE.pattern}): {name!r}"
        )
    return name


def validate_cli_name(name: str) -> str:
    # The exact package.json "bin" key. The charset starts with an
    # alphanumeric, so the dot segments "." and ".." are already excluded.
    if not CLI_NAME_RE.fullmatch(name) or name in _PATH_DOT_SEGMENTS:
        raise ValidationError(
            f"cli name must be lowercase alphanumeric plus . _ - and not a dot "
            f"segment (matching {CLI_NAME_RE.pattern}): {name!r}"
        )
    return name


def validate_cargo_role(role: str) -> str:
    if role.endswith("_upper"):
        raise ValidationError(
            f"cargo_names role may not end in '_upper' (that suffix selects the "
            f"uppercase form in [[replace]] placeholders): {role!r}"
        )
    if not CARGO_ROLE_RE.fullmatch(role):
        raise ValidationError(
            f"cargo_names role must be lowercase letters, digits, and "
            f"underscores, starting with a letter "
            f"(matching {CARGO_ROLE_RE.pattern}): {role!r}"
        )
    return role


def validate_cargo_name(name: str) -> str:
    if not CARGO_NAME_RE.fullmatch(name):
        raise ValidationError(
            f"cargo_names name must start with a letter or underscore, use "
            f"letters, digits, hyphens, and underscores, and contain at "
            f"least one letter or digit "
            f"(matching {CARGO_NAME_RE.pattern}): {name!r}"
        )
    return name


VALIDATORS = {
    "package_name": validate_package_name,
    "repo_name": validate_repo_name,
    "app_name": validate_app_name,
    "author": validate_author,
    "owner": validate_owner,
    "email": validate_email,
    "display_name": validate_display_name,
    "npm_name": validate_npm_name,
    "cli_name": validate_cli_name,
}

REQUIRED_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "author",
    "email",
    "owner",
)

# Optional identity fields: absent means the feature is off — existing
# 6-field press-source.toml files stay valid (codesign sec-01/sec-06).
OPTIONAL_FIELDS: tuple[str, ...] = ("display_name", "npm_name", "cli_name")

# Fields whose value is one path component, so a press renames paths with it.
# `field_renames_paths` adds cli_name and an unscoped npm_name.
RENAME_FIELDS: frozenset[str] = frozenset(
    {"package_name", "repo_name", "app_name", "app_name_upper"}
)

# The closed set of exact display-name rewrite forms (codesign sec-04).
DISPLAY_FORM_NAMES: tuple[str, ...] = ("spaced", "pascal", "camel")


@dataclass(frozen=True)
class Identity:
    """One repo identity — either the source (FROM) or destination (TO)."""

    package_name: str
    repo_name: str
    app_name: str
    author: str
    email: str
    owner: str
    display_name: str | None = None
    npm_name: str | None = None
    cli_name: str | None = None
    # Role -> exact Cargo name, sorted by role. Kept out of as_dict(), whose
    # values are all strings; control_mapping() adds it for the receipt.
    cargo_names: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cargo_names", tuple(sorted(self.cargo_names)))

    @property
    def app_name_upper(self) -> str:
        return self.app_name.upper()

    def as_dict(self) -> dict[str, str]:
        d = {
            "package_name": self.package_name,
            "repo_name": self.repo_name,
            "app_name": self.app_name,
            "app_name_upper": self.app_name_upper,
            "author": self.author,
            "email": self.email,
            "owner": self.owner,
        }
        if self.display_name is not None:
            d["display_name"] = self.display_name
        if self.npm_name is not None:
            d["npm_name"] = self.npm_name
        if self.cli_name is not None:
            d["cli_name"] = self.cli_name
        return d

    def as_dict_prompted(self) -> dict[str, str]:
        d = self.as_dict()
        d.pop("app_name_upper")
        return d

    def control_mapping(self) -> dict[str, str | dict[str, str]]:
        """The mapping written to the source config and the receipt tables.

        Equal to ``as_dict_prompted()`` plus ``cargo_names`` only when the
        table is non-empty, so an identity without one is unchanged.
        """
        mapping: dict[str, str | dict[str, str]] = dict(self.as_dict_prompted())
        if self.cargo_names:
            mapping["cargo_names"] = dict(self.cargo_names)
        return mapping

    def validate(self) -> None:
        for field_name, value in self.as_dict().items():
            validator = VALIDATORS.get(field_name)
            if validator is not None:
                validator(value)
        for role, name in self.cargo_names:
            validate_cargo_role(role)
            validate_cargo_name(name)

    @classmethod
    def from_mapping(
        cls, data: dict[str, str], cargo_names: Mapping[str, str] | None = None
    ) -> Identity:
        missing = [k for k in REQUIRED_FIELDS if k not in data]
        if missing:
            raise ValidationError(f"identity is missing fields: {', '.join(missing)}")
        fields = {k: data[k] for k in REQUIRED_FIELDS}
        for opt in OPTIONAL_FIELDS:
            if data.get(opt) is not None:
                fields[opt] = data[opt]
        return cls(**fields, cargo_names=tuple((cargo_names or {}).items()))


def token_pattern(field: str, value: str) -> re.Pattern[str] | None:
    """Boundary matcher — boundary-safe replacement is the default (OQ12).

    An app token like ``press`` is an English word inside unrelated prose
    (compress, expression, pressure). Match it as a standalone token or a
    filename/env prefix, never inside another word. Underscore counts as a
    separator on the RIGHT of app_name (press_config.toml) and on the LEFT
    of app_name_upper (_PRESS_COMPLETE); digits are allowed AFTER
    app_name_upper so identity-prefixed constants (PRESS000 error codes)
    are rewritten. Every other field uses alphanumeric boundaries: short
    values (owner ``go``, author ``Ann``) must not rewrite the inside of
    unrelated words (ongoing, Announcement), while ``_``/``-``/``.``/``/``
    remain separators so compound forms (demo_widget_extra) still match.
    """
    if not value:
        # A zero-width pattern matches everywhere and would splice the
        # replacement between every token of every file. Validators reject
        # empty values upstream; this guard makes the invariant local.
        raise ValidationError(f"identity field {field!r} must not be empty")
    if field == "app_name":
        return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9-])")
    if field == "app_name_upper":
        return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z-])")
    if field in ("npm_name", "cli_name") or is_cargo_field(field):
        # Exact names: a same-prefix sibling (@acme/widget-extra) is a different
        # package, while a subpath (@acme/widget/sub) still rewrites its prefix.
        return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9_-])")
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])")


def distinct_hyphen_form(source: Identity, dest: Identity) -> str | None:
    """The hyphenated package name, when no other identity value claims it.

    ``None`` means there is nothing separate to rewrite or hunt: the name has
    no underscore, the package is unchanged, or the spelling is another
    source or destination value (commonly ``repo_name``).
    """
    hyphen = source.package_name.replace("_", "-")
    if hyphen == source.package_name or source.package_name == dest.package_name:
        return None
    claimed = {
        value
        for identity in (source, dest)
        for field, value in identity.as_dict().items()
        if field != "package_name"
    }
    claimed.update(
        name for identity in (source, dest) for _role, name in identity.cargo_names
    )
    return None if hyphen in claimed else hyphen


def field_renames_paths(field: str, value: str) -> bool:
    """True when ``value`` of ``field`` is one renameable path component.

    A scoped ``npm_name`` contains ``/``, so it can never be one component.
    """
    if field == "npm_name":
        return "/" not in value
    if field.startswith(CARGO_BIN_ENV_TAG):
        return False  # an environment variable name, never a path component
    return field == "cli_name" or field in RENAME_FIELDS or is_cargo_field(field)


def pair_renames_paths(field: str, current: str, replacement: str) -> bool:
    """True when a rewrite may rename paths: both sides must be one component.

    An unscoped source pressed to a scoped destination is content-only. The
    doctor and verifier still hunt the source value in paths, so a file that
    keeps the old name is reported as a leak.
    """
    return field_renames_paths(field, current) and field_renames_paths(
        field, replacement
    )


def token_occurs(text: str, field: str, value: str) -> bool:
    pattern = token_pattern(field, value)
    if pattern is not None:
        return pattern.search(text) is not None
    return value in text


def occurs(
    text: str, field: str, value: str, substring_fields: Collection[str] = frozenset()
) -> bool:
    """Dispatch to plain substring membership for an opted-in field.

    Shared by every OCCURRENCE check across the engine/doctor/rules modules
    (the engine's own replacement dispatch in ``_apply_replacements``/
    ``_renamed_rel`` mirrors this same split): when ``substring_fields``
    promises glued-token coverage for a field, the check must use the same
    plain-substring posture — the boundary-guarded ``token_occurs`` would
    miss a glued occurrence (``plbpOwned``) that substring mode is meant to
    rewrite/catch.
    """
    if field in substring_fields:
        return value in text
    return token_occurs(text, field, value)


def replace_token(text: str, field: str, current: str, replacement: str) -> str:
    pattern = token_pattern(field, current)
    if pattern is not None:
        # Function replacement: the destination value is LITERAL text, never
        # a re template (a backslash in an author name must not become a
        # group reference or crash re.sub).
        return pattern.sub(lambda _: replacement, text)
    return text.replace(current, replacement)


def display_forms(value: str) -> dict[str, str]:
    """The closed set of exact display-name forms, keyed by DISPLAY_FORM_NAMES.

    spaced is the value verbatim; pascal capitalizes each space-separated
    word's first letter and joins (inner casing preserved: "NumPy" stays
    "NumPy"); camel is pascal with its first character lowercased. A closed,
    enumerable set — never an elastic pattern (codesign sec-04).
    """
    words = value.split()
    pascal = "".join(w[:1].upper() + w[1:] for w in words)
    camel = pascal[:1].lower() + pascal[1:]
    return {"spaced": value, "pascal": pascal, "camel": camel}


def cargo_ident(name: str) -> str:
    """The Rust identifier spelling of a Cargo name (hyphens become underscores)."""
    return name.replace("-", "_")


def is_cargo_field(field: str) -> bool:
    return field.startswith((CARGO_EXACT_PREFIX, CARGO_IDENT_PREFIX, CARGO_BIN_ENV_TAG))


def exact_name_rank(field: str) -> int:
    """Equal-length tie order: Cargo names, then ``npm_name``, then the rest."""
    if is_cargo_field(field):
        return 0
    return 1 if field == "npm_name" else 2


def cargo_field_values(identity: Identity) -> dict[str, str]:
    """Each Cargo spelling by row tag; an identical underscore form is omitted."""
    values: dict[str, str] = {}
    for role, name in identity.cargo_names:
        values[f"{CARGO_EXACT_PREFIX}{role}"] = name
        if cargo_ident(name) != name:
            values[f"{CARGO_IDENT_PREFIX}{role}"] = cargo_ident(name)
    return values


def cargo_name_pairs(source: Identity, dest: Identity) -> list[tuple[str, str, str]]:
    """``(tag, from, to)`` rewrite pairs for the Cargo name table.

    Each role gives an exact-name pair (``cargo_exact_<role>``) and an
    underscore pair (``cargo_ident_<role>``). An underscore pair equal to its
    exact pair, and any pair whose two sides match, is dropped. Longest source
    first; an exact pair wins an equal-length tie.
    """
    dest_names = dict(dest.cargo_names)
    pairs: list[tuple[str, str, str]] = []
    for role, old in source.cargo_names:
        new = dest_names.get(role)
        if new is None:
            continue
        exact = (f"{CARGO_EXACT_PREFIX}{role}", old, new)
        ident = (f"{CARGO_IDENT_PREFIX}{role}", cargo_ident(old), cargo_ident(new))
        if exact[1] != exact[2]:
            pairs.append(exact)
        # A hyphen-free source spells both forms identically, so its one text
        # gets one unscoped pair; only a [[cargo_split]] press splits it.
        if ident[1] != exact[1] and ident[1] != ident[2]:
            pairs.append(ident)
    pairs.sort(
        key=lambda p: (-len(p[1]), not p[0].startswith(CARGO_EXACT_PREFIX), p[0])
    )
    return pairs


def cargo_bin_env_pairs(source: Identity, dest: Identity) -> list[tuple[str, str, str]]:
    """``(tag, from, to)`` pairs for ``CARGO_BIN_EXE_<name>`` of each changed name.

    The Cargo row's left boundary excludes ``_``, so it cannot reach this token.
    """
    return [
        (
            f"{CARGO_BIN_ENV_TAG}{tag}",
            f"{CARGO_BIN_EXE_PREFIX}{old}",
            f"{CARGO_BIN_EXE_PREFIX}{new}",
        )
        for tag, old, new in cargo_name_pairs(source, dest)
    ]


def _cargo_forms(name: str) -> set[str]:
    return {name, cargo_ident(name)}


def cargo_split_roles(
    source: Identity, dest: Identity, roles: Iterable[str]
) -> frozenset[str]:
    """The declared ``[[cargo_split]]`` roles this press really splits.

    A role splits when its source name has no hyphen and its destination has
    one, so one source text needs two destination spellings.
    """
    src_map, dst_map = dict(source.cargo_names), dict(dest.cargo_names)
    return frozenset(
        role
        for role in roles
        if role in src_map
        and role in dst_map
        and src_map[role] == cargo_ident(src_map[role])
        and dst_map[role] != cargo_ident(dst_map[role])
    )


def cargo_split_problems(
    source: Identity, dest: Identity, roles: Sequence[str], *, pressed: bool
) -> tuple[list[str], list[str]]:
    """``(refusals, warnings)`` for the declared ``[[cargo_split]]`` roles.

    After a press the source already has a hyphen, so a block left in place
    is inert and warned about. Before any press it is refused as unnecessary.
    """
    src_map, dst_map = dict(source.cargo_names), dict(dest.cargo_names)
    problems: list[str] = []
    warnings: list[str] = []
    for role in roles:
        where = f"[[cargo_split]] role {role!r}"
        if role not in src_map or role not in dst_map:
            problems.append(
                f"{where} is not a cargo_names role in both the source config "
                "and the answers file"
            )
            continue
        old, new = src_map[role], dst_map[role]
        if old != cargo_ident(old):
            if pressed:
                warnings.append(
                    f"warning: {where} is inert: source name {old!r} already "
                    "has a hyphen, so a previous press split it. Remove the "
                    "block from press/press-rules.toml"
                )
                continue
            problems.append(
                f"{where} is unnecessary: source name {old!r} has a hyphen, so "
                "its package and identifier spellings already differ. Remove "
                "the block"
            )
        elif new == cargo_ident(new):
            problems.append(
                f"{where} is unnecessary: destination {new!r} has no hyphen, so "
                "both spellings stay identical. Remove the block"
            )
    return problems, warnings


def cargo_identity_problem(
    source: Identity, dest: Identity, *, split_roles: Collection[str] = ()
) -> str | None:
    """Why this source and destination Cargo name tables cannot be pressed.

    ``None`` means they can, or neither side declares a table. A role in
    ``split_roles`` may take a hyphen-free source to a hyphenated destination.
    """
    if not source.cargo_names and not dest.cargo_names:
        return None
    if not source.cargo_names or not dest.cargo_names:
        return (
            "cargo_names must be declared on both the source config and the "
            "answers file, or on neither"
        )
    src_map, dst_map = dict(source.cargo_names), dict(dest.cargo_names)
    if src_map.keys() != dst_map.keys():
        return (
            "cargo_names role sets differ: source has "
            f"{sorted(src_map)}, destination has {sorted(dst_map)}"
        )
    for side, mapping in (("source", src_map), ("destination", dst_map)):
        seen: dict[str, str] = {}
        for role, name in sorted(mapping.items()):
            key = cargo_ident(name)
            if key in seen:
                return (
                    f"cargo_names roles {seen[key]!r} and {role!r} have the "
                    f"same underscore-normalized {side} name {key!r}"
                )
            seen[key] = role
    for role, new in dst_map.items():
        for other, old in src_map.items():
            if other != role and _cargo_forms(new) & _cargo_forms(old):
                return (
                    f"cargo_names destination {new!r} for role {role!r} equals "
                    f"source name {old!r} of role {other!r}; sequential "
                    "rewrites would chain"
                )
    for role, old in src_map.items():
        new = dst_map[role]
        if old == cargo_ident(old) and new != cargo_ident(new):
            if role in split_roles:
                continue
            return (
                f"cargo_names role {role!r} maps {old!r}, which has no hyphen, to "
                f"{new!r}, which has one. Text alone cannot tell the package "
                f"spelling of {old!r} from its Rust identifier, so the press "
                f"cannot tell whether to write {new!r} or {cargo_ident(new)!r}; "
                f"use {cargo_ident(new)!r} as the destination, rename the "
                "source crate to a hyphenated name first, or declare "
                f'[[cargo_split]] role = "{role}" in press/press-rules.toml to '
                "do this rename in one press"
            )
    role = next(
        (r for r, n in src_map.items() if cargo_ident(n) == source.package_name),
        None,
    )
    if role is None:
        return (
            f"package_name {source.package_name!r} is not the underscore form "
            "of any source cargo_names value"
        )
    if dest.package_name != cargo_ident(dst_map[role]):
        return (
            f"destination package_name {dest.package_name!r} is not the "
            f"underscore form of cargo_names role {role!r} destination "
            f"{dst_map[role]!r}"
        )
    return None
