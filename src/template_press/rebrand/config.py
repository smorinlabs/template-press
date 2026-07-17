"""Load/render the two per-run identity configs (OQ3 two-file model).

source-config (FROM, committed in the target at press/press-source.toml) — the
authoritative identity being replaced. answers (TO) — the identity being
pressed in, from an [answers] TOML (same shape as the repo's answers.toml).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from template_press.rebrand.identity import Identity, ValidationError

SOURCE_CONFIG_REL = Path("press") / "press-source.toml"


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
    identity = Identity.from_mapping(
        {k: v for k, v in section.items() if isinstance(v, str)}
    )
    identity.validate()
    return identity


def load_source_config(target: Path, override: Path | None) -> Identity | None:
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
