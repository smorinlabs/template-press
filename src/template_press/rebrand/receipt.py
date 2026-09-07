"""The rebrand receipt — written into the TARGET, only after verification.

The receipt is the anti-EMP-01 artifact: it exists only when the no-leak
doctor pass succeeded, and it records what was verified, not what was
answered. Its presence also guards re-runs (require --force).
"""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from template_press.rebrand.config import toml_string
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.pathing import ROOT_CONTROL
from template_press.rebrand.removal_types import DirectoryRemoval, RemovalMember
from template_press.rebrand.rules import (
    _control_alias_key,
    _declared_rel_path,
    _reject_reserved,
)
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    assert_under_root,
    write_control,
)

RECEIPT_REL = Path("press") / "press-receipt.toml"
REMOVE_HISTORY_MAX_BYTES = 16 * 1024 * 1024
REMOVE_HISTORY_MAX_DIRS = 1024
REMOVE_HISTORY_MAX_MEMBERS = 100000
REMOVE_HISTORY_MAX_TEXT_BYTES = 4096


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


def receipt_present(target: Path) -> bool:
    """Match legacy presence checks without reading any receipt contents."""
    return (target / RECEIPT_REL).is_file()


def _read_bounded_receipt(target: Path, max_bytes: int) -> bytes | None:
    """Bound allocation with static no-follow guards and checked leaf identity."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValidationError("receipt max_bytes must be a nonnegative integer")
    path = target / RECEIPT_REL
    assert_under_root(path, target)
    assert_ancestors_real(path, target)
    if path.parent.is_junction():
        raise SafetyError("directory receipt parent is a junction")
    if not os.path.lexists(path):
        return None
    before = path.lstat()
    if path.is_junction() or not stat.S_ISREG(before.st_mode):
        raise SafetyError("directory receipt must be a regular file (no-follow check)")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise SafetyError("directory receipt changed before reading")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(max_bytes + 1)
        assert_under_root(path, target)
        assert_ancestors_real(path, target)
        if path.parent.is_junction():
            raise SafetyError("directory receipt parent is a junction")
        after = path.lstat()
        if not stat.S_ISREG(after.st_mode) or not os.path.samestat(opened, after):
            raise SafetyError("directory receipt changed while reading")
    finally:
        os.close(descriptor)
    if len(data) > max_bytes:
        raise ValidationError(f"directory receipt byte limit {max_bytes} exceeded")
    return data


def read_receipt(target: Path, *, max_bytes: int | None = None) -> str | None:
    path = target / RECEIPT_REL
    try:
        if max_bytes is not None:
            data = _read_bounded_receipt(target, max_bytes)
            return None if data is None else data.decode("utf-8")
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        if max_bytes is not None:
            raise ValidationError("directory receipt is not valid UTF-8") from exc
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
    edits: Sequence[tuple[str, Sequence[str], str]] = (),
    *,
    platform: str | None = None,
    origin: OriginDecision | None = None,
    clean: Sequence[Sequence[str]] = (),
    remove_dirs: Sequence[DirectoryRemoval] = (),
) -> Path:
    if remove_dirs:
        validate_directory_history(remove_dirs, removals)
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
        *(["remove_dirs_version = 1"] if remove_dirs else []),
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
        f"edited = {len(report.edited)}",
        f"regenerated = {len(report.regenerated)}",
        f"skipped = {len(report.skipped)}",
    ]
    # Edits precede regenerations here for the same reason they precede them
    # in the plan and in execution: the receipt reads in phase order (E4).
    # `expect` travels with the argv because it is the post-condition that
    # made this row a SUCCESS — the argv alone records only what launched.
    for file, argv, expect in edits:
        lines += [
            "",
            "[[press.edit]]",
            f"file = {toml_string(file)}",
            "argv = [" + ", ".join(toml_string(a) for a in argv) + "]",
            f"expect = {toml_string(expect)}",
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
    lines += _directory_lines(remove_dirs)
    # Declared clean paths (E10). `press clean` is a standalone verb that
    # never writes a receipt, so this row records the DECLARATION an
    # operator should run before re-pressing — never that cleaning ran.
    for paths in clean:
        lines += [
            "",
            "[[press.clean]]",
            "paths = [" + ", ".join(toml_string(p) for p in paths) + "]",
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
    text = "\n".join(lines) + "\n"
    if remove_dirs and len(text.encode("utf-8")) > REMOVE_HISTORY_MAX_BYTES:
        raise ValidationError("directory receipt byte limit 16777216 exceeded")
    return write_control(target, RECEIPT_REL, text)


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


def _history_text(value: object, context: str) -> str:
    """Check one bounded printable schema string before path/error processing."""
    if not isinstance(value, str) or not value or not value.strip():
        raise ValidationError(f"directory {context} must be a nonempty string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValidationError(f"directory {context} is not valid UTF-8") from exc
    if size > REMOVE_HISTORY_MAX_TEXT_BYTES:
        raise ValidationError("directory text byte limit 4096 exceeded")
    if any(not char.isprintable() for char in value):
        raise ValidationError(f"directory {context} must be printable")
    return value


def _history_path(value: object, context: str, *, directory: bool = False) -> str:
    text = _history_text(value, context)
    try:
        canonical = _declared_rel_path(f"directory {context}", text)
        if canonical != text:
            raise ValidationError("directory paths must use canonical POSIX spelling")
        _reject_reserved("directory history", text)
    except ValidationError as exc:
        raise ValidationError(
            f"directory {context} is not a safe canonical path"
        ) from exc
    alias = _control_alias_key(text)
    if any(part in {"", ".git"} for part in alias.split("/")):
        raise ValidationError(f"directory {context} contains an unsafe alias")
    if directory:
        if any(char in text for char in "*?["):
            raise ValidationError(
                f"directory {context} must not contain glob characters"
            )
        if any(
            control == alias or control.startswith(alias + "/")
            for control in ROOT_CONTROL
        ):
            raise ValidationError(f"directory {context} contains a press control path")
    elif alias.rsplit("/", 1)[-1] in {".gitignore", ".gitattributes", ".gitmodules"}:
        raise ValidationError(f"directory {context} names a Git visibility input")
    return text


def _directory_lines(directories: Sequence[DirectoryRemoval]) -> list[str]:
    lines: list[str] = []
    used_bytes = 0
    for directory in directories:
        header = [
            "",
            "[[press.remove_dir]]",
            f"dir = {toml_string(directory.dir)}",
            f"current_dir = {toml_string(directory.current_dir)}",
            f"reason = {toml_string(directory.reason)}",
            "complete = true",
        ]
        used_bytes += sum(len(line.encode("utf-8")) + 1 for line in header)
        used_bytes += len("members = []\n")
        rendered_members: list[str] = []
        for member in directory.members:
            if member.source_dir is None:
                raise ValidationError("directory member requires source_dir")
            rendered = (
                "{ file = "
                + toml_string(member.file)
                + ", source_dir = "
                + toml_string(member.source_dir)
                + ", current_file = "
                + toml_string(member.current_file)
                + " }"
            )
            used_bytes += len(rendered.encode("utf-8")) + (2 if rendered_members else 0)
            if used_bytes > REMOVE_HISTORY_MAX_BYTES:
                raise ValidationError("directory receipt byte limit 16777216 exceeded")
            rendered_members.append(rendered)
        if used_bytes > REMOVE_HISTORY_MAX_BYTES:
            raise ValidationError("directory receipt byte limit 16777216 exceeded")
        lines += [*header, "members = [" + ", ".join(rendered_members) + "]"]
    return lines


def _reject_root_overlaps(roots: Sequence[str]) -> None:
    """Reject overlapping canonical aliases without comparing every member pair."""
    keys = sorted(_control_alias_key(root) for root in roots)
    seen: set[str] = set()
    for key in keys:
        parts = key.split("/")
        if key in seen or any(
            "/".join(parts[:i]) in seen for i in range(1, len(parts))
        ):
            raise ValidationError("directory roots overlap or have duplicate aliases")
        seen.add(key)


def validate_directory_history(
    directories: Sequence[DirectoryRemoval],
    removals: Sequence[tuple[str, str]],
) -> None:
    """Validate frozen/output history and its raw flat rows before mutation.

    File-only callers retain legacy behavior. For directory callers this checks
    the schema and serialized history limits shared by reader and writer; the
    writer additionally bounds the entire receipt including unrelated phases.
    """
    if len(directories) > REMOVE_HISTORY_MAX_DIRS:
        raise ValidationError("directory row limit 1024 exceeded")
    if sum(len(row.members) for row in directories) > REMOVE_HISTORY_MAX_MEMBERS:
        raise ValidationError("directory member limit 100000 exceeded")
    flat: dict[str, str] = {}
    flat_aliases: set[str] = set()
    for file, reason in removals:
        file = _history_path(file, "flat file")
        reason = _history_text(reason, "flat reason")
        alias = _control_alias_key(file)
        if alias in flat_aliases:
            raise ValidationError(
                "directory receipt has duplicate or alias flat removal rows"
            )
        flat_aliases.add(alias)
        flat[file] = reason
    audit_aliases: set[str] = set()
    current_aliases: set[str] = set()
    for row in directories:
        _history_path(row.dir, "dir", directory=True)
        root = _history_path(row.current_dir, "current_dir", directory=True)
        reason = _history_text(row.reason, "reason")
        for member in row.members:
            file = _history_path(member.file, "member file")
            current = _history_path(member.current_file, "member current_file")
            source_dir = _history_path(
                member.source_dir, "member source_dir", directory=True
            )
            if not file.startswith(source_dir + "/"):
                raise ValidationError("directory member file is outside source_dir")
            if not current.startswith(root + "/"):
                raise ValidationError(
                    "directory member current_file is outside current_dir"
                )
            audit_alias = _control_alias_key(file)
            current_alias = _control_alias_key(current)
            if audit_alias in audit_aliases or current_alias in current_aliases:
                raise ValidationError("directory members have duplicate or alias paths")
            audit_aliases.add(audit_alias)
            current_aliases.add(current_alias)
            if member.reason != reason or flat.get(file) != reason:
                raise ValidationError(
                    "directory member requires one matching flat removal reason"
                )
    _reject_root_overlaps([row.dir for row in directories])
    _reject_root_overlaps([row.current_dir for row in directories])
    # Original/current coordinate overlap across distinct rows is ambiguous,
    # while a row's own old/current root may legitimately coincide or nest.
    roots_by_alias: dict[str, set[int]] = {}
    for index, row in enumerate(directories):
        for root in (row.dir, row.current_dir):
            roots_by_alias.setdefault(_control_alias_key(root), set()).add(index)
    for root, owners in roots_by_alias.items():
        parts = root.split("/")
        if len(owners) > 1 or any(
            roots_by_alias.get("/".join(parts[:i]), set()) - owners
            for i in range(1, len(parts))
        ):
            raise ValidationError(
                "directory original/current roots overlap across rows"
            )
    # Count exact history output incrementally, bounding intermediate rendering.
    used_bytes = len("[press]\nverified = true\nremove_dirs_version = 1\n")
    used_bytes += sum(
        len(line.encode("utf-8")) + 1 for line in _directory_lines(directories)
    )
    for file, reason in removals:
        rendered = f"\n[[press.remove]]\nfile = {toml_string(file)}\nreason = {toml_string(reason)}\n"
        used_bytes += len(rendered.encode("utf-8"))
        if used_bytes > REMOVE_HISTORY_MAX_BYTES:
            raise ValidationError("directory receipt byte limit 16777216 exceeded")
    if used_bytes > REMOVE_HISTORY_MAX_BYTES:
        raise ValidationError("directory receipt byte limit 16777216 exceeded")


def directory_history_from_receipt(
    text: str | None, source: Identity
) -> tuple[DirectoryRemoval, ...]:
    """Read complete identity-bound directory history, refusing ambiguous input."""
    if text is None:
        return ()
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValidationError("directory receipt is not valid UTF-8") from exc
    if size > REMOVE_HISTORY_MAX_BYTES:
        raise ValidationError("directory receipt byte limit 16777216 exceeded")
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        detail = ascii(str(exc))[:REMOVE_HISTORY_MAX_TEXT_BYTES]
        raise ValidationError(f"directory receipt TOML is invalid: {detail}") from exc
    table = parsed.get("press", {})
    if not isinstance(table, dict):
        return ()
    if "remove_dir" not in table and "remove_dirs_version" not in table:
        return ()
    version = table.get("remove_dirs_version")
    if type(version) is not int or version != 1:
        raise ValidationError("directory receipt requires remove_dirs_version = 1")
    if table.get("verified") is not True:
        raise ValidationError("directory receipt is not a verified press")
    if table.get("to") != source.as_dict_prompted():
        raise ValidationError(
            "directory receipt [press.to] does not match press-source.toml"
        )
    entries = table.get("remove_dir")
    if not isinstance(entries, list):
        raise ValidationError("directory receipt remove_dir must be an array of tables")
    if len(entries) > REMOVE_HISTORY_MAX_DIRS:
        raise ValidationError("directory row limit 1024 exceeded")
    rows: list[DirectoryRemoval] = []
    member_count = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "dir",
            "current_dir",
            "reason",
            "complete",
            "members",
        }:
            raise ValidationError("directory receipt row has missing or unknown keys")
        if entry["complete"] is not True:
            raise ValidationError("directory receipt row must be complete")
        members = entry["members"]
        if not isinstance(members, list):
            raise ValidationError("directory receipt members must be an array")
        member_count += len(members)
        if member_count > REMOVE_HISTORY_MAX_MEMBERS:
            raise ValidationError("directory member limit 100000 exceeded")
        reason = _history_text(entry["reason"], "reason")
        parsed_members: list[RemovalMember] = []
        for member in members:
            if not isinstance(member, dict) or set(member) != {
                "file",
                "source_dir",
                "current_file",
            }:
                raise ValidationError(
                    "directory receipt member has missing or unknown keys"
                )
            parsed_members.append(
                RemovalMember(
                    file=_history_path(member["file"], "member file"),
                    current_file=_history_path(
                        member["current_file"], "member current_file"
                    ),
                    source_dir=_history_path(
                        member["source_dir"], "member source_dir", directory=True
                    ),
                    reason=reason,
                    missing_ok=True,
                )
            )
        rows.append(
            DirectoryRemoval(
                dir=_history_path(entry["dir"], "dir", directory=True),
                current_dir=_history_path(
                    entry["current_dir"], "current_dir", directory=True
                ),
                reason=reason,
                members=tuple(parsed_members),
            )
        )
    flat_entries = table.get("remove", [])
    if not isinstance(flat_entries, list):
        raise ValidationError("directory receipt flat remove must be an array")
    flat: list[tuple[str, str]] = []
    for entry in flat_entries:
        if not isinstance(entry, dict) or set(entry) != {"file", "reason"}:
            raise ValidationError(
                "directory receipt flat row has missing or unknown keys"
            )
        flat.append(
            (
                _history_path(entry["file"], "flat file"),
                _history_text(entry["reason"], "flat reason"),
            )
        )
    validate_directory_history(rows, flat)
    return tuple(rows)


def selected_directory_history(
    text: str | None,
    source: Identity,
    *,
    directory_declared: bool,
) -> tuple[DirectoryRemoval, ...]:
    """Preserve tolerant legacy discovery, then strictly validate recognized history."""
    if directory_declared:
        return directory_history_from_receipt(text, source)
    table = _press_table(text)
    if "remove_dir" not in table and "remove_dirs_version" not in table:
        return ()
    return directory_history_from_receipt(text, source)
