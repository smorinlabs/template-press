"""Load/render the two per-run identity configs (OQ3 two-file model).

source-config (FROM, committed in the target at press/press-source.toml) — the
authoritative identity being replaced. answers (TO) — the identity being
pressed in, from an [answers] TOML at a caller-supplied path
(conventionally named press-answers.toml, but any path works).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from template_press.rebrand.engine import ROOT_CONTROL
from template_press.rebrand.identity import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    Identity,
    ValidationError,
)
from template_press.rebrand.safety import ContainmentError, assert_under_root

SOURCE_CONFIG_REL = Path("press") / "press-source.toml"


def assert_control_real(target: Path) -> None:
    """Reject a control dir / artifact that is (or hides behind) a symlink (D8).

    The control location is tool-managed and must be REAL: a symlinked
    ``press/`` (or a symlinked control artifact inside it) could redirect a
    control-file WRITE out of the target tree, or make a control-file READ
    trust external content. Called once at the top of the shared load path
    (``load_source_config``) so both rebrand's resolve/write-from-discovery
    and (later) verify's preflight are guarded. Raises ``ContainmentError``
    (a ``SafetyError``/``ValueError``) → the CLI maps it to exit 2.
    """
    control = target / "press"
    # No symlinked ancestor and the leaf itself is not a symlink (no-follow
    # lstat walk); the belt-and-suspenders is_symlink covers the present-leaf
    # case explicitly.
    assert_under_root(control, target)
    if control.is_symlink():
        raise ContainmentError(f"control dir is a symlink: {control}")
    for rel in ROOT_CONTROL:
        artifact = target / rel
        if artifact.is_symlink():
            raise ContainmentError(f"control artifact is a symlink: {artifact}")


def toml_string(value: str) -> str:
    """Render a str as a TOML basic-string literal (quoted, escaped)."""
    out = []
    for ch in value:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def load_identity_toml(path: Path, table: str) -> Identity:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    section = data.get(table)
    if not isinstance(section, dict):
        raise ValidationError(f"{path}: missing [{table}] table")
    # F3: an unknown key (typo'd optional field, e.g. `display_nam`) must
    # fail loud — the dict-comprehension below silently drops any key it
    # doesn't recognize, so a typo would otherwise pass through as if the
    # field were simply absent, and press proceeds none the wiser.
    known = frozenset(REQUIRED_FIELDS) | frozenset(OPTIONAL_FIELDS)
    unknown = set(section) - known
    if unknown:
        raise ValidationError(
            f"{path}: [{table}] unknown key(s): {', '.join(sorted(unknown))}"
        )
    for key in (*REQUIRED_FIELDS, *OPTIONAL_FIELDS):
        if key in section and not isinstance(section[key], str):
            raise ValidationError(
                f"{path}: [{table}] {key} must be a string, got "
                f"{type(section[key]).__name__}"
            )
    identity = Identity.from_mapping(
        {k: v for k, v in section.items() if isinstance(v, str)}
    )
    identity.validate()
    return identity


def load_source_config(target: Path, override: Path | None) -> Identity | None:
    assert_control_real(target)
    path = override if override is not None else target / SOURCE_CONFIG_REL
    if not path.is_file():
        return None
    return load_identity_toml(path, "identity")


def render_source_config(identity: Identity) -> str:
    lines = [
        "# press/press-source.toml — this repo's CURRENT identity (the FROM side",
        "# of a rebrand). Authoritative: press validates it against the repo",
        "# and refuses to run on mismatch. Commit this file.",
        "[identity]",
    ]
    lines += [f"{k} = {toml_string(v)}" for k, v in identity.as_dict_prompted().items()]
    return "\n".join(lines) + "\n"


def load_answers(path: Path) -> Identity:
    return load_identity_toml(path, "answers")
