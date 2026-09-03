"""``press verify`` — the hermetic sandbox self-press leak check (Task 12).

The architectural KEYSTONE of `press verify`: it ties every prior module
together and, crucially, presses via the HERMETIC ``engine.apply`` — NOT the
rebrand ``_press`` path. There is no doctor, no receipt, no lockfile
regeneration: verify must be a pure, repeatable observation, never a mutation.

Flow (Decisions 2-6):

1. Load the target's committed FROM identity (``press/press-source.toml``). A
   missing config, a malformed one, or a control-path symlink -> **2** with NO
   writes to the real target.
2. Preflight against the REAL target (never the sandbox, never ``_resolve_source``):
   ``mismatches(source, discover(target))`` plus a PRESENCE check — for every
   field discovery could not confirm, the declared value must occur at least
   once in the target's ``scan_paths`` corpus. A wholly-undiscoverable-and-absent
   identity is ``unverifiable``. An ``owner``/``repo_name`` mismatch whose
   discovered value is the EXACT one a prior ``--accept-origin-mismatch`` press
   recorded in the receipt is waived (a ``note:``) — but only when that receipt
   is BOUND to this target (``verified = true`` and a ``[press.to]`` EQUAL to
   the target's own source-config identity — same keys, same values); any other
   value, and any unbound receipt, still refuses. Any remaining problem -> **2**.
3. Load the ``[verify]`` config (shared file with ``[rules]``). Any two SOURCE
   fields equal -> WARN; with ``equal_fields == "error"`` the equality is
   remembered to force **1**.
4-8. Inside ``safety.owned_sandbox`` (so the sandbox is torn down): build a
   faithful copy (``make_sandbox``), press it toward a synthetic
   equality-preserving TO-identity (``synthesize_dest`` + hermetic ``apply``),
   re-stage the sandbox index so ``scan`` sees the pressed worktree (not stale
   renamed paths), ``verifier.scan`` for surviving SOURCE identity, then apply
   the source-anchored ignores.

Exit: **2** for config/env/unverifiable; else **1** if any surviving finding,
stale ignore, ``equal_fields == "error"`` collision, or unavailable submodule;
else **0**. An env/tool error raised by the press is **2** (not **1**): the
press could not complete, so verify cannot claim clean.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess  # nosec B404 — re-stages the OWNED sandbox git index only
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from template_press.rebrand.config import SOURCE_CONFIG_REL, load_source_config
from template_press.rebrand.discovery import Discovered, discover, mismatches
from template_press.rebrand.engine import (
    apply,
    exempt_regenerated_paths,
    scan_paths,
    translate_path,
)
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.ignores import Ignore, apply_ignores, build_forward_map
from template_press.rebrand.inventory import (
    capture_surface_snapshot,
    core_excludes_from_snapshot,
)
from template_press.rebrand.matcher import find_occurrences
from template_press.rebrand.receipt import (
    accepted_origin_from_receipt,
    read_receipt,
    receipt_binding_problem,
    removed_files_from_receipt,
)
from template_press.rebrand.reset import load_stub_content
from template_press.rebrand.rules import RULES_REL, Rules, load_selected_rules
from template_press.rebrand.safety import (
    SafetyError,
    assert_ancestors_real,
    git_hardening_args,
    is_regular_lstat,
    owned_sandbox,
    read_regular_nofollow,
    readlink_nofollow,
    safe_write,
    scrubbed_git_env,
)
from template_press.rebrand.sandbox import make_sandbox
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verifier import Finding, attach_ignore_hints, scan
from template_press.rebrand.verify_config import (
    KNOWN_FIELDS,
    VerifyConfig,
    parse_verify_config,
)

# The re-stage of the sandbox index after apply is authored by a synthetic
# identity — never the user's git config — mirroring make_sandbox.
_SANDBOX_GIT_IDENTITY: dict[str, str] = {
    "GIT_AUTHOR_NAME": "press-verify",
    "GIT_AUTHOR_EMAIL": "verify@localhost",
    "GIT_COMMITTER_NAME": "press-verify",
    "GIT_COMMITTER_EMAIL": "verify@localhost",
}

# Config/env failures anywhere on the pre-sandbox and sandbox-setup paths all
# map to exit 2 (no target mutation is possible from any of them).
_CONFIG_ERRORS: tuple[type[Exception], ...] = (
    SafetyError,
    ValidationError,
    tomllib.TOMLDecodeError,
    OSError,
    subprocess.CalledProcessError,
)

# A failure raised BY the press (apply / re-stage) — an env/tool error, not a
# leak — is exit 2, distinct from a surviving finding's exit 1.
_PRESS_ENV_ERRORS: tuple[type[Exception], ...] = (
    FileNotFoundError,
    OSError,
    subprocess.CalledProcessError,
    SafetyError,
)


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _discovered_map(found: Discovered) -> dict[str, str | None]:
    """Discovery's per-field result keyed by the identity field name."""
    return {
        "package_name": found.package_name,
        "repo_name": found.repo_name,
        "app_name": found.app_name,
        "author": found.author,
        "email": found.email,
        "owner": found.owner,
    }


def _target_text_corpus(target: Path, rules: Rules) -> list[str]:
    """Every scannable string of the REAL target: each ``scan_paths`` entry's
    POSIX path plus its symlink readlink text or decoded file content.

    ``scan_paths`` already excludes ``ROOT_CONTROL`` — so the source-config's
    OWN declaration of a value is not in the corpus, which is what makes the
    presence check meaningful (it looks for the value in real content, never in
    the config that declares it).
    """
    corpus: list[str] = []
    for entry in scan_paths(target, rules):
        corpus.append(entry.rel.as_posix())
        path = target / entry.rel
        if entry.kind == "symlink":
            try:
                corpus.append(readlink_nofollow(path))
            except (OSError, SafetyError):
                continue
        elif entry.kind == "file" and is_regular_lstat(path):
            try:
                # UTF-8-only by design: a non-UTF-8 (binary) file is skipped
                # here, which only makes a value HARDER to confirm present —
                # the presence check fails CLOSED to exit 2 (unverifiable), so
                # a skipped binary can never cause a false CLEAN.
                corpus.append(read_regular_nofollow(path).decode("utf-8"))
            except (OSError, SafetyError, UnicodeDecodeError):
                continue
    return corpus


def _value_present(
    field: str, value: str, corpus: list[str], substring_fields: frozenset[str]
) -> bool:
    """Whether ``value`` occurs as identity anywhere in the corpus.

    The matcher mode is the field's OWN effective mode, not a fixed boundary
    match (#47). ``substring_fields`` is the SCAN's effective substring set —
    ``[verify] substring_fields`` (a scan-scope opt-in that says nothing about
    rewriting) unioned with ``[rules] substring_rewrite_fields`` (the press's
    boundary-free rewrite set) — the same set ``verifier.scan`` receives.
    Either declaration asserts the same thing about presence: this field's
    occurrences need not carry a boundary. A target opts in precisely because
    the value appears GLUED (``xdemolabsy``), so asking the boundary matcher
    reports it absent, and preflight then rejects the target with a false
    exit 2 for the very property the declaration exists to state.
    """
    substring = field in substring_fields
    return any(
        find_occurrences(text, field, value, substring=substring) for text in corpus
    )


def _effective_scan_fields(
    fields: Sequence[str], substring_rewrite_fields: frozenset[str]
) -> tuple[str, ...]:
    """Union ``[rules] substring_rewrite_fields`` into the scan's field set.

    A field the sandbox press rewrites substring-wide but that is absent
    from ``fields`` (e.g. ``app_name_upper``, not in ``DEFAULT_FIELDS``) is
    never scanned at all — ``scan_substring`` only controls HOW a field
    already in ``fields`` is matched, not WHETHER it is scanned. Filtered to
    ``KNOWN_FIELDS`` defensively: ``rules.load_selected_rules`` already rejects any
    other value at parse time, so this is defense in depth, not a reachable
    path through normal config loading.
    """
    extra = [
        f for f in substring_rewrite_fields if f in KNOWN_FIELDS and f not in fields
    ]
    return (*fields, *extra)


def _honor_accepted_origin(
    problems: list[str], found: Discovered, accepted: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Drop the `owner`/`repo_name` mismatches a prior press already accepted.

    The press never touches git remotes, so a target pressed with
    `--accept-origin-mismatch` keeps an `origin` naming a third repository
    while its source-config names the destination — and the unrelaxed
    `mismatches()` would refuse it forever. The receipt records the EXACT
    value that was accepted, so a mismatch is dropped only when the value
    discovered NOW equals the recorded one: repoint `origin` at yet another
    repository and verify refuses again.

    `mismatches()` itself is untouched — this filters its output by the same
    `"{field}: "` prefix the press-side guard uses. Returns the surviving
    problems and the fields actually honored (a field whose origin already
    agrees raises no problem and so is never "honored").

    `accepted` arrives already bound to this target by the caller (see
    `receipt.receipt_binding_problem`); an unbound receipt reaches here as an
    empty mapping and waives nothing.
    """
    honored: dict[str, str] = {}
    for field_name in ("owner", "repo_name"):
        recorded = accepted.get(field_name)
        if recorded is None or getattr(found, field_name) != recorded:
            continue
        remaining = [p for p in problems if not p.startswith(f"{field_name}: ")]
        if remaining != problems:
            honored[field_name] = recorded
            problems = remaining
    return problems, honored


def _preflight(
    target: Path,
    source: Identity,
    rules: Rules,
    scan_fields: Sequence[str],
    substring_fields: frozenset[str],
    accepted_origin: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Consistency + presence check against the REAL target; problems -> 2.

    Presence is required only for the fields ``verify`` will actually scan
    (``scan_fields``, the effective ``[verify]`` scope) — requiring presence for
    a field verify won't scan (e.g. ``author``/``email`` under the default
    scope) falsely rejects a target whose identity is consistent for everything
    that IS scanned. Only discovery-confirmed fields are exempt; the
    wholly-undiscoverable-AND-absent ``unverifiable`` verdict is scoped to the
    scanned set. ``mismatches`` (the consistency check) is unchanged — a
    discoverable field that DISAGREES with the config still fails regardless of
    scope.

    ``substring_fields`` is the same effective set the scan uses
    (``[verify] substring_fields`` unioned with ``[rules]
    substring_rewrite_fields``), so presence is decided by each field's own
    matcher mode rather than a fixed boundary match — see ``_value_present``.

    ``accepted_origin`` is the target's own receipt record of an
    ``--accept-origin-mismatch`` press; the second return value names the
    fields whose mismatch it waived (see ``_honor_accepted_origin``).
    """
    found = discover(target)
    problems, honored = _honor_accepted_origin(
        list(mismatches(source, found)), found, accepted_origin
    )
    discovered = _discovered_map(found)
    declared = source.as_dict()
    # Only scanned fields that discovery can confirm (skip derived forms like
    # ``app_name_upper`` that are not independently discoverable).
    scanned = [f for f in scan_fields if f in discovered]
    undiscoverable = [f for f in scanned if discovered[f] is None]
    # ``display_name`` has NO discovery entry at all (Fix F1) — it can never
    # land in ``discovered``/``scanned``/``undiscoverable`` above, so without
    # this it would sail through preflight with zero reality check: a stale
    # or typo'd declaration would only surface once a real press has already
    # half-rewritten the target's prose. When the source declares one and
    # it's in ``scan_fields``, require its presence directly.
    check_display_name = (
        source.display_name is not None and "display_name" in scan_fields
    )
    if not undiscoverable and not check_display_name:
        return problems, honored
    corpus = _target_text_corpus(target, rules)
    if check_display_name and not _value_present(
        "display_name", source.display_name, corpus, substring_fields
    ):
        problems.append(
            f"declared display_name {source.display_name!r} not found in "
            "target — stale or mistyped?"
        )
    if not undiscoverable:
        return problems, honored
    absent = [
        f
        for f in undiscoverable
        if not _value_present(f, declared[f], corpus, substring_fields)
    ]
    if len(undiscoverable) == len(scanned) and len(absent) == len(undiscoverable):
        problems.append(
            "unverifiable: the declared identity is WHOLLY undiscoverable and "
            "absent from the target — refusing to pass on historical prose"
        )
    else:
        problems.extend(
            f"{f}: declared {declared[f]!r} is neither discoverable nor present "
            f"anywhere in the target (undiscoverable and absent)"
            for f in absent
        )
    return problems, honored


def _equal_pair(source: Identity) -> tuple[str, str] | None:
    """The first pair of SOURCE fields sharing the same value, or None."""
    items = list(source.as_dict_prompted().items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][1] == items[j][1]:
                return items[i][0], items[j][0]
    return None


def _load_verify_config(target: Path) -> VerifyConfig:
    """Parse the ``[verify]`` table from ``press/press-rules.toml`` (the same
    file that carries ``[rules]``); absent file/table -> defaults."""
    path = target / RULES_REL
    table = None
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        table = data.get("verify")
    return parse_verify_config(table)


def _make_source_line(target: Path) -> Callable[[str, int], str | None]:
    """A cached ``(src_path, 1-based line) -> str | None`` reader over the
    ORIGINAL target. Fails CLOSED (None) on any unreadable/absent file/line —
    ``apply_ignores`` treats None as "anchor not present"."""
    cache: dict[str, list[str] | None] = {}

    def source_line(src_path: str, line: int) -> str | None:
        if src_path not in cache:
            path = target / src_path
            if is_regular_lstat(path):
                try:
                    cache[src_path] = path.read_bytes().decode("utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    cache[src_path] = None
            else:
                cache[src_path] = None
        lines = cache[src_path]
        if lines is None or line < 1 or line > len(lines):
            return None
        return lines[line - 1]

    return source_line


def _restage_sandbox(sandbox: Path) -> None:
    """``git add -A -f`` on the OWNED sandbox so ``git ls-files`` reflects the
    pressed worktree — apply's renames leave the old paths in the index but
    absent from the worktree, which would otherwise scan as false leaks. This
    reconciles the index; it is NOT lockfile regeneration (verify stays
    hermetic). Scrubbed + hardened + synthetic-identity, ``-C`` pinned.

    ``-f`` is REQUIRED, not optional: without it, a plain ``add -A`` respects
    ``.gitignore``, so after apply renames a force-added-ignored file to a
    still-ignored path, ``-A`` stages the deletion but REFUSES to re-add the
    ignored path — the file (e.g. a binary whose bytes embed a source value and
    apply cannot rewrite) drops out of the sandbox index and ``scan`` never sees
    the surviving leak → a FALSE CLEAN. Force-adding is correct and faithful
    here because ``make_sandbox`` copied ONLY the ``copy_paths`` set into the
    sandbox worktree — there are no extraneous ignored files for ``-f`` to
    over-add, so ``-A -f`` re-stages exactly the pressed tree (force-added
    ignored files included) and stages the renamed-away deletions.
    """
    cmd = ["git", "-C", str(sandbox), *git_hardening_args(), "add", "-A", "-f"]
    subprocess.run(  # noqa: S603 # nosec B603 B607
        cmd,
        check=True,
        capture_output=True,
        env=scrubbed_git_env(extra=_SANDBOX_GIT_IDENTITY),
    )


def _finding_json(finding: Finding) -> dict[str, object]:
    """`Finding` as a JSON-ready dict with `note` OMITTED when ``None``
    (Codex fix-round-1 P3) — `note` is a new (E8) field, so `note: null` on
    every ordinary finding would be a schema change for every existing
    consumer of `press verify --json`; only a finding that actually carries
    a near-miss hint gets the key at all.
    """
    data = dataclasses.asdict(finding)
    if data["note"] is None:
        del data["note"]
    return data


def _report(
    surviving: list[Finding],
    stale: list[Ignore],
    unavailable: tuple[str, ...],
    equal_collision: tuple[str, str] | None,
) -> None:
    """Human, grouped-by-file failure report to stderr."""
    print(
        "verify FAILED — source identity survived the hermetic self-press:",
        file=sys.stderr,
    )
    by_file: dict[str, list[Finding]] = {}
    for finding in surviving:
        by_file.setdefault(finding.path, []).append(finding)
    for path in sorted(by_file):
        print(f"  {path}", file=sys.stderr)
        for f in by_file[path]:
            where = f.where if f.line is None else f"{f.where} L{f.line}:C{f.col}"
            print(f"    [{where}] {f.field}={f.value!r}", file=sys.stderr)
            if f.note is not None:
                print(f"      note: {f.note}", file=sys.stderr)
    for ignore in stale:
        print(
            f"  stale ignore (suppressed nothing): file={ignore.file!r} "
            f"anchor={ignore.anchor!r}",
            file=sys.stderr,
        )
    for sub in unavailable:
        print(f"  unavailable submodule (could not verify): {sub}", file=sys.stderr)
    if equal_collision is not None:
        print(
            f"  equal_fields=error: {equal_collision[0]} and "
            f"{equal_collision[1]} share a value",
            file=sys.stderr,
        )


def verify_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press verify", description=__doc__)
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    target = args.target.resolve()

    # Step 1 — source-config (control-symlink / missing / malformed -> 2; the
    # real target is never mutated on any exit-2 path).
    try:
        source = load_source_config(target, None)
    except _CONFIG_ERRORS as exc:
        return _fail(f"cannot load source-config: {exc}")
    if source is None:
        return _fail(
            f"no source-config at {SOURCE_CONFIG_REL}; verify needs the "
            f"target's committed FROM identity"
        )

    # Steps 2-3 — preflight + [verify] config, against the REAL target.
    try:
        selected = load_selected_rules(target)
        rules = selected.rules
        cfg = _load_verify_config(target)
        scan_fields: tuple[str, ...] = cfg.fields
        if source.display_name is not None and "display_name" not in scan_fields:
            # codesign sec-05: a declared display name is scanned as its own
            # field — the only coverage when its words diverge from the slug.
            scan_fields = (*scan_fields, "display_name")
        # A field the SANDBOX PRESS rewrites substring-wide (`[rules]
        # substring_rewrite_fields`) must be SCANNED at all (Fix F2) — a field
        # absent from DEFAULT_FIELDS (e.g. app_name_upper) is otherwise never
        # scanned regardless of substring mode — AND substring-wide (a
        # containment-skipped symlink target, or any other rewrite the
        # hermetic apply cannot perform, can leave a glued, boundary-free
        # occurrence of that field's source value behind; the boundary-only
        # `[verify] substring_fields` scope alone would never flag it).
        scan_fields = _effective_scan_fields(
            scan_fields, rules.substring_rewrite_fields
        )
        scan_substring = cfg.substring_fields | rules.substring_rewrite_fields
        # The target's OWN receipt (not the sandbox copy's): a prior
        # `--accept-origin-mismatch` press records the exact origin values it
        # accepted, and preflight waives precisely those.
        #
        # A receipt describes one identity's press, so it is honored only
        # when it is BOUND to this target: a completed, verified press whose
        # `[press.to]` equals this target's current source-config identity.
        # A hand-written `[press]` table asserting an acceptance, or a
        # receipt describing a different identity, is refused — and the
        # refusal says which condition failed, because "verify still exits 2"
        # is otherwise indistinguishable from "the flag never worked".
        receipt_text = read_receipt(target)
        recorded = accepted_origin_from_receipt(receipt_text)
        unbound = receipt_binding_problem(receipt_text, source)
        accepted_origin = {} if unbound is not None else recorded
        recorded_but_unbound = unbound is not None and bool(recorded)
        problems, honored_origin = _preflight(
            target, source, rules, scan_fields, scan_substring, accepted_origin
        )
    except _CONFIG_ERRORS as exc:
        return _fail(f"preflight failed: {exc}")
    if problems:
        # Printed alongside the refusal it explains, in BOTH modes: it is a
        # stderr diagnostic, and the one-JSON-object contract is about stdout,
        # so `--json` gets the same explanation prose does. Gated on a
        # recorded acceptance that binding rejected — on a run that passes
        # anyway (origin agrees now) the receipt's binding is not what the
        # operator is asking about.
        if recorded_but_unbound:
            print(f"error: press receipt not honored: {unbound}", file=sys.stderr)
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2
    # Announced only once preflight has cleared, and never under --json (whose
    # contract is that the JSON object is the whole of stdout): a "note:
    # accepted" line printed alongside a refusal would read as a contradiction,
    # exactly as on the press side.
    if not args.as_json:
        for field_name, value in honored_origin.items():
            print(
                f"note: {field_name}: origin {value!r} accepted by the press "
                f"receipt (--accept-origin-mismatch)"
            )

    equal_pair = _equal_pair(source)
    if equal_pair is not None:
        print(
            f"warning: source fields {equal_pair[0]} and {equal_pair[1]} are "
            f"equal — the press preserves the equality (not itself a failure)",
            file=sys.stderr,
        )
    equal_collision = equal_pair if cfg.equal_fields == "error" else None

    # Steps 4-8 — press + scan inside an owned, torn-down sandbox.
    surviving: list[Finding] = []
    stale: list[Ignore] = []
    unavailable: tuple[str, ...] = ()
    exempt: list[tuple[str, str]] = []
    try:
        synth = synthesize_dest(source)
        with owned_sandbox(target) as dest_root:
            sandbox = make_sandbox(target, dest_root)
            try:
                # Model declared resets (codex 3654657444, P1): the real
                # press writes the validated stub at position zero, so the
                # hermetic scan must see the stub — not the history the
                # reset exists to remove. Stub CONTENTS are captured before
                # the press (codex 3654853355): apply() renames
                # identity-bearing dirs, so a stub_file path beneath one
                # would no longer resolve afterwards.
                prior_removed = removed_files_from_receipt(read_receipt(sandbox.path))
                reset_stubs = [
                    (rule, load_stub_content(sandbox.path, rule))
                    for rule in rules.reset
                ]
                source_snapshot = capture_surface_snapshot(sandbox.path)
                report = apply(sandbox.path, source, synth, rules)
                for reset_rule, stub in reset_stubs:
                    rel = translate_path(reset_rule.file, dict(report.renamed))
                    safe_write(sandbox.path, rel, stub, refuse_hardlink=False)
                # Model declared removals (P08 T2): unlike regeneration, a
                # removal needs no command, so verify performs it for real —
                # the file vanishes from the scan with no exemption and no
                # coverage gap. Tri-state, mirroring the press preflight: a
                # missing target recorded in the target's own receipt was
                # removed by a prior press (a pressed fork's normal state);
                # a missing target with NO record is stale config and must
                # fail loud, never silently scan clean.
                for remove_rule in rules.remove:
                    rel = translate_path(remove_rule.file, dict(report.renamed))
                    removed_path = sandbox.path / rel
                    # The unlink must not travel through a symlinked
                    # ancestor — an absolute link in the copied tree could
                    # point OUTSIDE the sandbox (same guard as the real
                    # press's apply_removals).
                    assert_ancestors_real(removed_path, sandbox.path)
                    if os.path.lexists(removed_path):
                        if not is_regular_lstat(removed_path):
                            raise SafetyError(
                                f"remove target {rel} is not a regular file "
                                f"(no-follow check)"
                            )
                        os.unlink(removed_path)
                    elif remove_rule.file not in prior_removed:
                        return _fail(
                            f"[[remove]] target {remove_rule.file} does not "
                            f"exist and no receipt records its removal — a "
                            f"stale declaration is config drift; delete it "
                            f"or restore the file"
                        )
                _restage_sandbox(sandbox.path)
            except _PRESS_ENV_ERRORS as exc:
                return _fail(
                    f"press failed in the sandbox (env/tool error, not a leak): {exc}"
                )
            findings = scan(
                sandbox.path,
                source,
                synth,
                fields=scan_fields,
                substring_fields=scan_substring,
                rules=rules,
                source_snapshot=source_snapshot,
                # `report.renamed` (Fix F1) is available right here — thread
                # it through so a rule-literal scope check can recover a
                # scanned path/symlink-target's PRE-rename original before
                # testing `rule.files`, mirroring
                # `doctor.find_leaks`'s `renamed` parameter exactly (9d9d0c5).
                renamed=report.renamed,
            )
            # The exemption is a COVERAGE GAP and verify must say so (P04
            # D3): declaring a regeneration does not prove the command
            # rebuilds anything — only the real press's post-command scan
            # can certify these files, so they are listed as not-verified
            # rather than silently omitted.
            exempt = exempt_regenerated_paths(rules, report.renamed)
            forward_map = build_forward_map(report.renamed)
            # Exempt paths back to SOURCE coordinates (codex 3654657451),
            # exactly like the findings below — the synthetic sandbox path
            # does not exist in the user's repo.
            exempt = [(forward_map(file), reason) for file, reason in exempt]
            surviving, stale = apply_ignores(
                findings,
                list(cfg.ignores),
                forward_map=forward_map,
                source_line=_make_source_line(target),
            )
            # Report/JSON in SOURCE coordinates (Design §3): the sandbox path is
            # a synthetic press artifact that does not exist in the user's repo.
            # line/col already index the source via the newline invariant.
            surviving = [
                dataclasses.replace(f, path=forward_map(f.path)) for f in surviving
            ]
            # E8: the sandbox `scan()` above can never see "untracked" — Fix
            # F1's own `_restage_sandbox` (and `make_sandbox` itself) `git
            # add -f` every copied path, so the sandbox's OWN index marks
            # everything tracked regardless of the REAL target's git state.
            # A near-miss note is only meaningful against the REAL target
            # (the note literally says what `git add -A` would do THERE), so
            # it is attached here, in SOURCE coordinates, against `target`
            # directly — never against the sandbox. Best-effort: any failure
            # reading the real target's surface just skips the hint, exactly
            # like `ignore_near_miss`'s own "no note, no error" contract.
            if surviving:
                try:
                    real_snapshot = capture_surface_snapshot(target)
                except _CONFIG_ERRORS:
                    real_snapshot = None
                if real_snapshot is not None:
                    real_untracked = frozenset(
                        e.rel.as_posix() for e in real_snapshot.entries if not e.tracked
                    )
                    real_core_excludes = core_excludes_from_snapshot(real_snapshot)
                    surviving = attach_ignore_hints(
                        target, surviving, real_untracked, real_core_excludes
                    )
            unavailable = sandbox.unavailable_submodules
    except _CONFIG_ERRORS as exc:
        return _fail(f"sandbox verify failed: {exc}")

    failed = bool(surviving or stale or unavailable or equal_collision)
    if args.as_json:
        print(
            json.dumps(
                {
                    "verified": not failed,
                    "surviving": [_finding_json(f) for f in surviving],
                    "stale_ignores": [dataclasses.asdict(i) for i in stale],
                    "unavailable_submodules": list(unavailable),
                    "equal_fields_collision": (
                        list(equal_collision) if equal_collision else None
                    ),
                    # Machine-readable coverage gap: every skipped file and
                    # why (exit 0 means clean over the SCANNED set).
                    "exempt": [
                        {"file": file, "reason": reason} for file, reason in exempt
                    ],
                }
            )
        )
    else:
        for file, reason in exempt:
            print(f"not verified (exempt): {file} — {reason}")
    if failed:
        if not args.as_json:
            _report(surviving, stale, unavailable, equal_collision)
        return 1
    if not args.as_json:
        print(
            "verified: no identity leftovers survived the hermetic "
            "self-press (clean over the scanned set"
            + (", exemptions listed above)." if exempt else ").")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(verify_command())
