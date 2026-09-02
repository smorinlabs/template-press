# O3 — adversarial review: the declared in-place `[[edit]]`

**Verdict: APPLY MODIFIED · shape S1 (separate `[[edit]]` table) · confidence high (~0.8).** Two modifications are
load-bearing: (a) run edits as a **fixed phase before** regenerations, not in "declaration order" — TOML cannot
express that (§2.1); (b) add a **required `expect`** post-condition — dest-presence cannot distinguish "edited" from
"untouched" (§1.3).

## 1. Steelman: can design 0006 admit a sixth mechanism?

**1.1 The model is disjoint by construction, and that saves the design.** A `[[regenerate]]` output *must* be in
`exclude_files` (`rules.py:458-464`); a `[[reset]]` target *must* too (`rules.py:574-578`); both sets come from
`DEFAULT_RULES.exclude_files | extra_exclude_files` (`rules.py:797-801`). `pyproject.toml` is not a default exclusion
(`rules.py:232-233`), so an edited file is scanned by the whole-tree doctor (`cli.py:564`, run *after* every declared
command) and by hermetic verify. An edit is therefore **not** "a command that writes an unscanned file" — it writes a
**fully scanned** file: strictly *stronger* coverage than regenerate, which is why "verified, no leak" survives
(nothing new is exempted). The philosophy cost — an edit is the first mechanism whose *intent* is opaque to press — is
bounded, because the status quo is an *undeclared* `uv version` side-write hung off the `uv.lock` regenerate rule
that `_postcondition_problems` (`regen.py:622-662`) never inspects. Declaring it is the 0006-consistent move.

**1.3 What dest-presence proves, and what it misses.** Proves: the file exists, is a contained sole-linked regular
file, decodes UTF-8, carries no source identity, and was not replaced by content stripped of the pressed name. Misses:
- **No-op commands — the fatal miss.** The replace pass writes dest identity into the file *before* the command, so
  dest-presence holds whether the command edited anything or nothing. Any exit-0 command that silently fails passes,
  and the fork ships the template's `version = "2.4.2"` — the exact bug this feature exists to fix. (A uv predating
  `uv version` is the illustrative instance; whether old uv errors or ignores the argument is unverified here. The
  *class* is what matters.)
- `name = "gmail2pdf"` → `"gmail2pdf2"`: dest substring present, source absent → passes. Nothing short of diff
  semantics catches it; accept and document.
- delete-and-re-add: benign if identity returns, caught if lost. CRLF rewrite passes (still UTF-8, still dest-bearing) — not a press invariant; the target's editorconfig owns it.
- **Other files: better covered than expected.** Scanned files → doctor (`cli.py:564`); control files →
  `snapshot_control_files`/`validate_control_files` (`regen.py:779+`); other declared outputs and reset stubs →
  `final_validation_pass` (`regen.py:665-730`). Residual gap: an **undeclared excluded** file (`package-lock.json`)
  corrupted by an edit — identical to today's regenerate gap, not new.

**Modification (b): require `expect`.** `[[edit]] file, command, expect`, where `expect` is a non-empty printable
control-char-free literal that MUST be a substring of the file after the command (`expect = 'version = "0.1.0"'`). It
is the only thing making an edit's success *observable*, which every sibling already has: reset compares its stub
(`regen.py:717-728`), remove checks the file is gone, regenerate earns exemption by scan. Why `expect` and not "bytes
must differ": a re-press of a pressed fork legitimately re-runs `uv version 0.1.0` as a no-op, so bytes-changed
false-positives while `expect` passes. `expect` must be identity-free (a hardcoded dest name in committed
`press-rules.toml` breaks the next re-press) — one doc line, not a validator.

## 2. Attacking the specifics

**2.1 Ordering — "declaration order across two tables" is NOT implementable.** `tomllib` returns a dict; interleaving
between two array-of-table names is lost. Verified locally: `[[regenerate]] A / [[edit]] B / [[regenerate]] C` →
`{'regenerate': [A, C], 'edit': [B]}`. B's position between A and C is unrecoverable, so S1 as specified cannot honor
"declare the edit before `uv lock`". **This is the strongest fact in the review and it argues for S2**, where one
array preserves order free. **The rescue that keeps S1: a fixed phase — every edit runs before every regeneration.**
That is an *invariant*, not a convention: by §1.1 an edit target must NOT be excluded and a regenerate output MUST be,
so "edit after regenerate" means editing an excluded file, which the parser already refuses.
**`_validate_writer_overlaps` (`rules.py:640-724`) needs only two new rules**, not four: edit↔edit and edit↔remove
(editing a doomed file); edit↔regenerate and edit↔reset are structurally impossible by the same disjointness — comment
that, so nobody adds dead checks.

**2.2 `translate_path` under a renamed prefix.** No new work: declared paths are SOURCE coordinates, so reuse
`_translate_output_path` (`regen.py:85-97`) and re-run the sink guards (containment, real ancestors, no-follow,
`st_nlink == 1`) before each launch, exactly as `execute_regenerations` does (`regen.py:296-338`). Reuse
`stale_argv_elements` (`regen.py:159`): an edit argv naming a renamed path is the same hazard.

**2.3 Git-visibility fingerprint — edits are safe, no semantics change.** `GitVisibilityState.index_entries` is
`(path, IndexKind)` pairs only (`regen.py:734-757`), so content changes to a tracked file do not alter it. Proof from
existing behaviour: `uv lock` rewrites tracked `uv.lock` today and passes; an edit to tracked `pyproject.toml` is
identical.

**2.4 `--frozen` is load-bearing, not cosmetic.** Confirmed from `uv version --help` (uv 0.11.29): `--frozen` =
"Update the version without re-locking the project". Without it `uv version` re-locks and writes `uv.lock` — an
**undeclared side-write to another rule's declared output**, the precise sin this feature removes. Recommend `["uv",
"version", "0.1.0", "--frozen", "--no-sync"]` so the edit does no network resolution and no `.venv` write. A uv
predating `uv version` fails nonzero → press fails, no receipt (`cli.py:483-518`) — loud, but `press check-tools`
resolves `argv[0]` only, never the subcommand, so there is no version gate; `expect` is the real backstop.

**2.5-2.7 Windows argv / dry-run / receipt tolerance — three small surfaces.**
- `platforms`: reuse `_parse_platforms` verbatim (`rules.py:446-452`, shared by regenerate/reset/remove); same
  `powershell -NoProfile -File` shape as this repo's bun rules (`press/press-rules.toml`).
- Dry-run: an edit cannot be previewed — same as regenerate, acceptable for the same reason (the rendered argv *is*
  the approval artifact). New wrinkle: unlike a regenerate output, the edited file **appears in the dry-run replace
  diff** with the old `version = "2.4.2"` line intact. Render an `[edit]` plan section (argv, pinned executable, env,
  `expect`) and document the omission.
- Receipt: additive `[[press.edit]]` rows carry the **resolved** argv (pinned executable, mirroring `cli.py:587-596` /
  `receipt.py:95-105`) plus `expect`. Older readers are tolerant by construction (`removed_files_from_receipt`,
  `receipt.py:125-157`, ignores unknown keys); no read-back semantics needed, since unlike `[[remove]]` an edit's
  success destroys no precondition.

**2.8 `press verify` does NOT need to model edits — confirmed harmless.** The sandbox self-press never runs commands
(`verify_cli.py:455-500`), so its `pyproject.toml` keeps the source version; version is not an identity field, so
`scan` yields no finding. Edits must never reach `exempt_regenerated_paths` (`pathing.py:86-118`; `pyproject.toml` ∉
`REGENERATE_EXEMPTIBLE`, `pathing.py:20`) — giving a self-policing property: **an edit whose job was removing source
identity would make hermetic verify fail loud**, since the command never runs there. Do not "fix" that.

**2.9 Leak-doctor ordering — cited.** `execute_regenerations` `cli.py:483` → `final_validation_pass` `cli.py:525` →
whole-tree `find_leaks` `cli.py:564` → `write_receipt` `cli.py:581`. The doctor runs after all declared commands, so
an edited non-excluded file is scanned post-command — the load-bearing reason the mechanism is admissible at all.

## 3. S1 vs S2

| Axis | S1 `[[edit]]` | S2 `mode = "edit"` |
|---|---|---|
| Ordering | broken as specified; fixed by an edits-first **phase** (§2.1) | free — one array preserves order |
| Schema clarity | exclusion rule inverts, `scan`/`verify_exempt` meaningless — a separate table says so | one table, two opposite exclusion rules, two dead keys |
| Validation | new parser, every branch unconditional | every check becomes `if mode == …`; `rules.py:458` inverts inside one function |
| Receipt/verify | edits never reach `exempt_regenerated_paths` — **cannot be exempted** | exemption is one forgotten `if rule.mode == "edit": continue` away |
| Docs | one mechanism, clean contrast table | "regenerate, except when it isn't" |
| Maintainer risk | low | **decisive** — a shared type invites a shared exemption |

**Pick S1.** S2 wins ordering outright and I concede it; S1 wins every other axis, and its one defect has a principled
fix S2's shared type cannot even express. Exemption-by-construction beats free ordering: an edit wrongly treated as
exempt silently reopens the leak hole the design exists to close.

## 4. Minimal engine change set

- `rules.py`: `EditRule` + `_EDIT_KEYS = {file, command, expect, env, platforms}`; `_parse_edit` (reject `file` **in**
  `exclude_files` — mirror image of `:458-464`; reuse `_reject_reserved`, the argv/env control-char loops,
  `_parse_platforms`); `_ROOT_KEYS += "edit"`; `Rules.edit`; `_validate_writer_overlaps` += edit↔edit and edit↔remove
  only.
- `regen.py`: generalize `plan_regenerate_commands` and `preflight_regenerate_outputs` (`:391-445` — tracked, clean,
  sole-linked, UTF-8) over a shared rule protocol; `execute_edits` reusing the sink guards and `subprocess.run`
  contract of `:296-338`; `_edit_postconditions` = `_postcondition_problems` (`:622-662`) **plus** `expect`;
  `final_validation_pass` re-checks edits.
- `cli.py`: run edits **before** `execute_regenerations` (`:483`); change the snapshot gates at `:481-482` from `if
  regen_plans` to `if regen_plans or edit_plans` — otherwise an edits-only blueprint runs commands with no
  control-file or visibility snapshot; render the `[edit]` plan section; pass edit rows to `write_receipt`.
- `receipt.py`: `[[press.edit]]` rows (file, resolved argv, expect); `ApplyReport.edited` + count.
- `pathing.py`: unchanged, plus a comment at `:86` that edits are never exemptible. Docs: `docs/design/0006` — the six
  mechanisms and the exclusion disjointness.

**Tests that must exist**
- Parser refusals: `file` in `exclude_files`; empty command; control chars in argv/env/`expect`; missing `expect`;
  reserved control-file target; `..`/absolute path. Overlaps: edit↔edit with platform overlap; edit↔remove same file.
- Post-condition withholds the receipt: nonzero exit; `expect` absent after the command; file deleted / symlinked /
  non-UTF-8; source identity reintroduced.
- **No-op regression (the §1.3 bug):** an exit-0 command that touches nothing must FAIL via `expect` and must NOT pass
  on dest-presence alone.
- Ordering: an edits-only blueprint still snapshots/revalidates control files and Git visibility; edits observably run
  before regenerations. Edit target under a renamed identity-bearing prefix resolves post-rename.
- R3 self-press three-mirror agreement: `pyproject.toml`, `uv.lock`, `.release-please-manifest.json` all read `0.1.0`.
  Receipt `[[press.edit]]` carries the pinned executable; older receipts parse.
