"""The rebrand receipt — written into the TARGET, only after verification.

The receipt is the anti-EMP-01 artifact: it exists only when the no-leak
doctor pass succeeded, and it records what was verified, not what was
answered. Its presence also guards re-runs (require --force).
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from template_press.rebrand.config import toml_string
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.safety import write_control

RECEIPT_REL = Path("press") / "press-receipt.toml"


@dataclass(frozen=True)
class OriginDecision:
    """What the origin-remote guard decided about `git remote origin` (E1).

    `named_destination` lists the fields (`owner`/`repo_name`) whose
    discovered value disagreed with the source-config but matched the
    DESTINATION identity, so the guard accepted them instead of refusing.
    It is recorded in the receipt so the relaxation stays auditable after
    the press. `mismatch_accepted` pairs each field whose discovered value
    matched NEITHER identity — accepted only because the operator passed
    `--accept-origin-mismatch` — with that discovered value. A field appears
    in at most one of the two: destination-equality is tried first.

    `named_destination` needs no value (it equals the destination's, which
    the press writes into the source-config, so `press verify` never sees it
    as a mismatch). `mismatch_accepted` carries its value because that is
    the only thing that lets `press verify` waive the acceptance safely: a
    field-name-only record would waive whatever `origin` says NEXT.
    """

    named_destination: tuple[str, ...] = ()
    mismatch_accepted: tuple[tuple[str, str], ...] = ()


def read_receipt(target: Path) -> str | None:
    path = target / RECEIPT_REL
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{RECEIPT_REL}: receipt is not valid UTF-8 ({path}): {exc}"
        ) from exc


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
    removals: Sequence[tuple[str, str]] = (),
    exempt: Sequence[tuple[str, str]] = (),
    *,
    platform: str | None = None,
    origin: OriginDecision | None = None,
) -> Path:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    # Each key is written only when that relaxation actually fired (E1): a
    # receipt without them means the guard relaxed nothing — origin agreed
    # with the source-config, or had no discoverable value (no remote, or a
    # non-GitHub one) — so every reader must tolerate their absence.
    named = origin.named_destination if origin is not None else ()
    accepted = origin.mismatch_accepted if origin is not None else ()
    origin_lines = []
    if named:
        origin_lines.append(
            "origin_named_destination = ["
            + ", ".join(toml_string(f) for f in sorted(named))
            + "]"
        )
    if accepted:
        # An inline table of field -> the EXACT origin value accepted, keys
        # sorted. `press verify` waives a mismatch only when the value it
        # discovers equals the one recorded here; a name-only list (the 4.1
        # shape) would waive any future value, so it is not honored.
        origin_lines.append(
            "origin_mismatch_accepted = { "
            + ", ".join(f"{f} = {toml_string(v)}" for f, v in sorted(accepted))
            + " }"
        )
    lines = [
        "# press/press-receipt.toml — written by template-press AFTER the no-leak",
        "# verification pass. Presence means: this rebrand completed and was",
        "# verified. Delete it (or use --force) to press again.",
        "[press]",
        "verified = true",
        *([f"platform = {toml_string(platform)}"] if platform is not None else []),
        f'completed_at = "{stamp}"',
        *origin_lines,
        "",
        *_identity_table("from", source),
        "",
        *_identity_table("to", dest),
        "",
        "[press.counts]",
        f"replaced = {len(report.replaced)}",
        f"renamed = {len(report.renamed)}",
        f"reset = {len(report.reset)}",
        f"removed = {len(report.removed)}",
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
    # Each removal with its declared reason (P08 T2): a deletion is a
    # deliberate, documented decision, and the receipt is where it stays
    # auditable after the file is gone.
    for file, reason in removals:
        lines += [
            "",
            "[[press.remove]]",
            f"file = {toml_string(file)}",
            f"reason = {toml_string(reason)}",
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


def _press_table(text: str | None) -> dict[str, object]:
    """The receipt's ``[press]`` table; an empty mapping for no receipt,
    unparsable TOML, or a ``press`` key that is not a table."""
    if not text:
        return {}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    table = data.get("press", {})
    return table if isinstance(table, dict) else {}


def receipt_binding_problem(text: str | None, source: Identity) -> str | None:
    """Why this receipt does not describe a completed press OF THIS target —
    ``None`` when it does.

    A receipt describes one identity's press, so a reader that TRUSTS its
    contents (see `accepted_origin_from_receipt`) must first check that it
    describes THIS target. Two conditions do that:

    1. ``verified = true`` — the receipt is written only after the no-leak
       pass, so anything else is not a completed, verified press.
    2. ``[press.to]`` is EQUAL to the target's current source-config
       identity — the same key set and the same value for every key. The
       press writes the same ``Identity.as_dict_prompted()`` mapping into
       both ``[press.to]`` and ``press/press-source.toml``, so a genuine
       receipt matches its own target exactly, while a hand-written table
       asserting an acceptance does not.

       Whole-mapping equality, not one-way containment (fix round 2):
       checking only the fields the source-config declares would ignore an
       EXTRA field in the receipt, so deleting an optional field (say
       ``display_name``) from ``press-source.toml`` would leave the stale
       receipt — which still carries it — honored against an identity it no
       longer describes.

       The binding is by IDENTITY, not by provenance: two targets that
       declare the same identity are indistinguishable here, and a receipt
       moved between them is honored by design. What the check excludes is
       a receipt describing a DIFFERENT identity than the target's own.
    """
    press_table = _press_table(text)
    if press_table.get("verified") is not True:
        return "receipt is not a verified press"
    if press_table.get("to") != source.as_dict_prompted():
        return "[press.to] does not match press-source.toml"
    return None


def accepted_origin_from_receipt(text: str | None) -> dict[str, str]:
    """The exact `origin` values a prior `--accept-origin-mismatch` press
    accepted, as ``{field: value}``.

    The press never touches git remotes, so a flag-accepted target keeps an
    ``origin`` naming a third repository while its source-config names the
    destination. `press verify` honors that acceptance by dropping a
    mismatch whose DISCOVERED value equals the one recorded here — never by
    field name alone, which would waive whatever the remote says next.

    This is a pure parser: it says what the receipt CLAIMS, not whether the
    receipt may be trusted. The caller must pair it with
    `receipt_binding_problem`, or a receipt copied in from another
    repository would waive this target's mismatch.

    Tolerant reader, like `removed_files_from_receipt`: no receipt,
    unparsable TOML, an absent key, the 4.1 list-of-field-names shape, or a
    non-string value all yield nothing for that entry. Failing closed here
    means verify refuses exactly as it did before the receipt was honored —
    it can never waive more than the receipt actually proves.
    """
    accepted = _press_table(text).get("origin_mismatch_accepted", {})
    if not isinstance(accepted, dict):
        return {}
    return {k: v for k, v in accepted.items() if isinstance(v, str)}


def removed_files_from_receipt(text: str | None) -> dict[str, str]:
    """The ``[[press.remove]]`` file set recorded by a prior press.

    A successful removal deletes its own precondition: the declaration
    stays in press-rules.toml while the file is gone, so a forced re-press
    (and a pressed fork's ``press verify``) must treat a missing target
    RECORDED here as satisfied — and a missing target NOT recorded as
    stale config. Tolerant reader: no receipt, unparsable TOML, or absent
    keys mean an empty mapping (the strict path then reports the target as
    stale, which fails loud — never silently clean).
    """
    if not text:
        return {}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    press_table = data.get("press", {})
    if not isinstance(press_table, dict):
        return {}
    entries = press_table.get("remove", [])
    if not isinstance(entries, list):
        return {}
    return {
        e["file"]: (
            e["reason"]
            if isinstance(e.get("reason"), str)
            else "recorded by a prior press"
        )
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("file"), str)
    }
