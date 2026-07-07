"""Identity model and boundary-safe token matching for the rebrand press.

Ported from the proven init/ engine (branch feat/init-rebrand-robustness):
validators from init/common.py:133-197, boundary patterns from
init/common.py:102-130 — generalized from a module-global BLUEPRINT_IDENTITY
to per-run values so any target's identity can be pressed (ARCH-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PYTHON_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REPO_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
GITHUB_OWNER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


VALIDATORS = {
    "package_name": validate_package_name,
    "repo_name": validate_repo_name,
    "app_name": validate_app_name,
    "owner": validate_owner,
    "email": validate_email,
}

REQUIRED_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "author",
    "email",
    "owner",
)


@dataclass(frozen=True)
class Identity:
    """One repo identity — either the source (FROM) or destination (TO)."""

    package_name: str
    repo_name: str
    app_name: str
    author: str
    email: str
    owner: str

    @property
    def app_name_upper(self) -> str:
        return self.app_name.upper()

    def as_dict(self) -> dict[str, str]:
        return {
            "package_name": self.package_name,
            "repo_name": self.repo_name,
            "app_name": self.app_name,
            "app_name_upper": self.app_name_upper,
            "author": self.author,
            "email": self.email,
            "owner": self.owner,
        }

    def as_dict_prompted(self) -> dict[str, str]:
        d = self.as_dict()
        d.pop("app_name_upper")
        return d

    def validate(self) -> None:
        for field_name, value in self.as_dict().items():
            validator = VALIDATORS.get(field_name)
            if validator is not None:
                validator(value)

    @classmethod
    def from_mapping(cls, data: dict[str, str]) -> Identity:
        missing = [k for k in REQUIRED_FIELDS if k not in data]
        if missing:
            raise ValidationError(f"identity is missing fields: {', '.join(missing)}")
        return cls(**{k: data[k] for k in REQUIRED_FIELDS})


def token_pattern(field: str, value: str) -> re.Pattern[str] | None:
    """Boundary matcher for fields whose values are unsafe as raw substrings.

    An app token like ``press`` is an English word inside unrelated prose
    (compress, expression, pressure). Match it as a standalone token or a
    filename/env prefix, never inside another word. Underscore counts as a
    separator on the RIGHT of app_name (press_config.toml) and on the LEFT
    of app_name_upper (_PRESS_COMPLETE) — mirroring the proven matcher.
    Long compound tokens (package/repo names) return None: plain substring
    replacement, longest-first, is exact for them.
    """
    if field == "app_name":
        return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9-])")
    if field == "app_name_upper":
        return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z0-9-])")
    return None


def token_occurs(text: str, field: str, value: str) -> bool:
    pattern = token_pattern(field, value)
    if pattern is not None:
        return pattern.search(text) is not None
    return value in text


def replace_token(text: str, field: str, current: str, replacement: str) -> str:
    pattern = token_pattern(field, current)
    if pattern is not None:
        return pattern.sub(replacement, text)
    return text.replace(current, replacement)
