"""The rebrand receipt — written into the TARGET, only after verification.

The receipt is the anti-EMP-01 artifact: it exists only when the no-leak
doctor pass succeeded, and it records what was verified, not what was
answered. Its presence also guards re-runs (require --force).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from template_press.rebrand.config import toml_string
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity
from template_press.rebrand.safety import write_control

RECEIPT_REL = Path("press") / "press-receipt.toml"


def read_receipt(target: Path) -> str | None:
    path = target / RECEIPT_REL
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def invalidate_receipt(target: Path) -> bool:
    """Remove the prior receipt, if any; True when one was removed.

    A forced re-press consumes its predecessor's receipt after the plan
    gates pass and BEFORE the first mutation (P04-T16): a failed forced
    re-press must not leave the old receipt advertising a verified press.
    No-follow — a symlinked press dir or receipt is left alone (the press
    refuses such a layout at write time anyway).
    """
    press_dir = target / RECEIPT_REL.parent
    path = target / RECEIPT_REL
    if press_dir.is_symlink() or path.is_symlink() or not path.is_file():
        return False
    path.unlink()
    return True


def _identity_table(name: str, identity: Identity) -> list[str]:
    lines = [f"[press.{name}]"]
    lines += [f"{k} = {toml_string(v)}" for k, v in identity.as_dict_prompted().items()]
    return lines


def write_receipt(
    target: Path,
    source: Identity,
    dest: Identity,
    report: ApplyReport,
    regenerations: Sequence[tuple[str, Sequence[str]]] = (),
    resets: Sequence[str] = (),
    exempt: Sequence[tuple[str, str]] = (),
    *,
    platform: str | None = None,
) -> Path:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# press/press-receipt.toml — written by template-press AFTER the no-leak",
        "# verification pass. Presence means: this rebrand completed and was",
        "# verified. Delete it (or use --force) to press again.",
        "[press]",
        "verified = true",
        *([f"platform = {toml_string(platform)}"] if platform is not None else []),
        f'completed_at = "{stamp}"',
        "",
        *_identity_table("from", source),
        "",
        *_identity_table("to", dest),
        "",
        "[press.counts]",
        f"replaced = {len(report.replaced)}",
        f"renamed = {len(report.renamed)}",
        f"reset = {len(report.reset)}",
        f"regenerated = {len(report.regenerated)}",
        f"skipped = {len(report.skipped)}",
    ]
    # Each regeneration's RESOLVED argv (P04 D5 revision): under plan→apply
    # nothing stops a config change between two runs, so the receipt is the
    # only artifact recording what actually ran.
    for file, argv in regenerations:
        lines += [
            "",
            "[[press.regenerate]]",
            f"file = {toml_string(file)}",
            "argv = [" + ", ".join(toml_string(a) for a in argv) + "]",
        ]
    for file in resets:
        lines += [
            "",
            "[[press.reset]]",
            f"file = {toml_string(file)}",
        ]
    # Machine-readable coverage record (P04 D3): every file the ordinary
    # doctor/verify inventories skip, with the mechanism that covered it —
    # the gap stays visible and deliberate, never an unchecked free pass.
    for file, reason in exempt:
        lines += [
            "",
            "[[press.exempt]]",
            f"file = {toml_string(file)}",
            f"reason = {toml_string(reason)}",
        ]
    return write_control(target, RECEIPT_REL, "\n".join(lines) + "\n")
