"""The rebrand receipt — written into the TARGET, only after verification.

The receipt is the anti-EMP-01 artifact: it exists only when the no-leak
doctor pass succeeded, and it records what was verified, not what was
answered. Its presence also guards re-runs (require --force).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from template_press.rebrand.config import toml_string
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity

RECEIPT_REL = Path("press") / "press-receipt.toml"


def read_receipt(target: Path) -> str | None:
    path = target / RECEIPT_REL
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _identity_table(name: str, identity: Identity) -> list[str]:
    lines = [f"[press.{name}]"]
    lines += [f"{k} = {toml_string(v)}" for k, v in identity.as_dict_prompted().items()]
    return lines


def write_receipt(
    target: Path, source: Identity, dest: Identity, report: ApplyReport
) -> Path:
    path = target / RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# press/press-receipt.toml — written by template-press AFTER the no-leak",
        "# verification pass. Presence means: this rebrand completed and was",
        "# verified. Delete it (or use --force) to press again.",
        "[press]",
        "verified = true",
        f'completed_at = "{stamp}"',
        "",
        *_identity_table("from", source),
        "",
        *_identity_table("to", dest),
        "",
        "[press.counts]",
        f"replaced = {len(report.replaced)}",
        f"renamed = {len(report.renamed)}",
        f"regenerated = {len(report.regenerated)}",
        f"skipped = {len(report.skipped)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
