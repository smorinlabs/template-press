# P05 — Reset rule: blank a file to a declared stub

- **Status:** `[~]` in progress

First destructive op — blank CHANGELOG-style files instead of leaking their history

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Research:** [0004 — py-launch-blueprint conformance gaps, §G1](../docs/research/0004-py-launch-blueprint-conformance-gaps.md)
  — the 86% measurement (678 of 784 findings; re-verified at 678 of 791 on
  v3.3.0, see Notes)
- **Ticket:** issue #54 (the G1/G2 dogfood gaps)
- **PRs:** #56 (the decision record) · #57 (the revisions that touched it:
  supersession alignment, stub-content scan)
- **Prior art:** py-launch-blueprint's embedded engine — researched
  2026-07-25, recorded under Notes below
- **Sibling:** [P04 — regenerate](P04-regenerate-bun-lock.md) — ships
  together per P04 D5

### Scope

The `[[reset]]` mechanism per D1–D6, plus two joint rules recorded in P04
(the reset/regenerate overlap ban and stub mode preservation): declared
only, no built-in changelog
behavior; stub content from an inline string or a contained local
`stub_file`, both scanned so a stub cannot restore the identity its reset
removes; the guards — target must be git-tracked and clean (refused even
under `--allow-dirty`), always-on two-level lines-based preview, every reset
recorded in `ApplyReport` and the receipt, overlap bans with `[[replace]]`
and `[[regenerate]]`; plan-time preflight with the named safety predicates;
reset runs first, in source coordinates; a failed reset aborts the press;
the stub write preserves the target's original file mode. Ships as one
change with P04 — the §6 preflight needs both mechanisms to exist.

### Out of scope

- `stub_url` (remote fetch) — deferred; see D6 for the sketched semantics.
- Idempotent skip-when-already-stubbed — deliberately not taken (D2);
  revisit only if re-press noise proves annoying.
- Anything that executes commands — that is P04's mechanism.
- P06 substitution-set refactor (issue #42).

### Open questions

None — the five codesign answers are recorded (2026-07-25), D6 decided
2026-07-26, and `stub_url` is a recorded deferral, not an open fork.

### Decisions

All five open questions settled 2026-07-25 (codesign export
`The reset rule — three design decisions`, sections sec-01/sec-02/sec-03).

- **D1 — Declared only; no built-in default.** A target declares every
  `[[reset]]` entry in its own `press-rules.toml`. The tool ships no default
  entry for `CHANGELOG.md` or anything else. Follows the standing preference
  that everything be declared with no hidden defaults, and keeps `rules.py`'s
  "the tool never carries a target's file list" contract intact for the new
  mechanism even though `exclude_files` predates it.
- **D2 — Guards: refuse-if-untracked, dry-run preview, receipt record, and an
  overlap ban.** (`ch-01-a`, `ch-01-b`, `ch-01-c`, `ch-01-e`.)
  - Refuse to reset a file git is not tracking **or that has uncommitted
    changes**. The guard's purpose is an undo path, and `git checkout` restores
    only the committed content — a tracked file carrying unstaged work has no
    recoverable copy of that work either. Since `--allow-dirty` exists
    (`cli.py:233`) this is reachable, not theoretical: refuse a dirty reset
    target even under that flag.
  - Preview at two levels, both always present, both measured in **lines**:
    - **default** — one line per reset target: its path and current line count
      (`reset CHANGELOG.md (1,234 lines → stub)`).
    - **verbose** — additionally the first N lines of the current content plus
      the stub that would replace it, where N is the same unit as the count
      above. The motivating target is a release history running to thousands of
      lines, so the excerpt is bounded rather than complete. (Decided
      2026-07-26: the excerpt is gated behind a new `--verbose` flag on
      `press rebrand` — no such flag exists today — and N is fixed at 20
      lines.)

    Normal mode is never silent about a reset; only the content excerpt is
    verbose-gated.
  - Record each reset in `ApplyReport` and the receipt, mirroring the existing
    shapes exactly: `ApplyReport.reset: list[str]` holds the reset paths (as
    `replaced`/`renamed` already do), and the receipt's `[press.counts]` gains a
    `reset = <n>` line beside `replaced`/`renamed`/`regenerated`/`skipped`
    (counts only, as that table already is). Closes a known gap: the embedded
    engine printed its reset list to stdout and discarded it.
  - Refuse a path that is both a reset target and a `[[replace]]` target — the
    result would depend on pass order. Inherits the embedded engine's own test-
    enforced ban.
  - **Not taken:** idempotent skip-when-already-stubbed (`ch-01-d`). The embedded
    engine had it; without it a re-press rewrites identical content and reports
    the reset each time. Harmless, but a deliberate divergence from prior art —
    revisit if the noise proves annoying.
- **D3 — §6's contract preflight folds into whichever of P04/P05 lands second.**
  **SUPERSEDED 2026-07-25 by P04 D5 — the preflight ships with P04 and P05
  TOGETHER, as one change with one migration.** ("With the first of the two"
  was the intermediate ruling; re-verification showed it is not implementable
  either — `CHANGELOG.md` is a built-in exclusion whose only cure is P05's
  reset, so a preflight landing with P04 alone would reject this repo's own R3
  self-press. See P04 D5.) An
  adversarial review showed "second" leaves a live hole in the interval: once
  the `uv.lock` regeneration default is removed, an excluded file with no
  declared neutralization is never rebuilt and never scanned (the doctor gets
  all of `exclude_files` and `iter_target_files` omits them), so source identity
  survives under a clean receipt — and R3 runs only a real `rebrand`, with no
  independent check able to catch it. The preflight is that check. Original
  reasoning below, kept for the record.

  (`ch-02-a`.) Roughly twenty lines, reusing that project's fixtures; as a
  standalone item it risks being orphaned once the interesting work is done.
- **D4 — A failed reset aborts the whole press.** (`ch-03-a`.) Matches press's
  existing posture on a failed lockfile regeneration (error, no receipt) rather
  than inventing a softer second rule.

  **This is not an atomicity guarantee, and must not be implemented or tested as
  one.** `apply` writes incrementally and has no rollback — its own failure path
  says "target may be PARTIALLY rewritten; restore with `git checkout . && git
  clean -fd`" (`cli.py:442`). Aborting stops *further* damage and withholds the
  success receipt; git remains the undo button. D5 is what actually keeps the
  destructive phase from starting in a state it cannot finish.
- **D5 — Validate before mutating: preflight every reset target at plan time.**
  Rather than relying on D4's abort to catch problems mid-run, check up front
  that each declared reset target is resolvable inside the target, git-tracked,
  clean, and passes the write-path guards — failing at plan time (exit 2, no
  writes). Generalizes the tool's existing "exit 2 means nothing was written"
  contract to the new operation.

  **This rejects known-invalid targets; it is not a completion guarantee.** A
  preflight cannot promise that later I/O succeeds — a filesystem can change
  between plan and apply, and D4 already records that `apply` is incremental
  with no rollback. The pairing is: D5 removes the failure modes that are
  knowable in advance, D4 bounds the damage from the ones that are not.

  **The preflight applies the same predicates the write path applies**, named
  explicitly so plan-time and apply-time cannot drift:
  - `safety.assert_under_root` — the target resolves inside the press root.
  - `safety.assert_ancestors_real` — no symlinked ancestor could redirect the
    write outside the tree.
  - `safety.is_regular_lstat` — the sink is a regular file, no-follow; this is
    what rejects a symlink sink that a bare `os.access` probe would pass.
  - `safety.safe_write(..., refuse_hardlink=False)` performs the write itself,
    matching `_apply_replacements`: its atomic temp-plus-rename creates a new
    inode, so an external hardlink keeps the pre-reset content rather than
    being blanked through.
  - The declared stub content itself passes the changed-only paranoid
    identity and rendered-`[[replace]]`-literal scan (P04 D3's evidence
    standard): a stub may not restore the identity its reset exists to
    remove, and equality checks downstream prove only that nothing altered
    the stub afterwards.

  **Ordering: reset runs first, before every other pass.** `apply`'s order today
  is replace → retarget-symlinks → rename (`engine.py`); reset takes position
  zero. Two reasons, and only the first is load-bearing: (1) declared paths are
  written against the repo's current layout, so they must be consumed before the
  rename pass moves anything — placing reset last, as the embedded engine did,
  makes a declared path stale, and because the prior-art implementation creates
  the file when absent, a stale path would silently *create* a spurious file
  rather than fail (the embedded engine never hit this because its only target
  was a root `CHANGELOG.md` that never moves); (2) the replace pass then sees a
  stub with no identity left to rewrite — though D2's overlap ban already makes
  reset and replace targets disjoint, so this is a consequence, not a reason.

  *Scope note:* reset itself never executes anything — it writes a static stub
  (see prior art below); running commands is `regenerate`'s job. The same
  validate-before-mutate principle applies there and is arguably more valuable:
  P04 should check its regeneration command is actually available (e.g. `bun`
  on PATH) before a press begins, instead of discovering it after the rewrite
  phase has already run.

- **D6 — Stub content comes from exactly one of two declared forms (decided
  2026-07-26).** Either an inline string (`stub = "# Changelog\n"`, the prior-
  art form) or a local file reference (`stub_file = "press/stubs/CHANGELOG.md"`)
  whose path is validated with the same containment predicates as every other
  declared path (inside the target, no traversal, no-follow regular file) and
  whose content passes the same stub scan D5 applies to inline stubs — a stub
  may not restore the identity its reset exists to remove, whatever its
  source. Declaring both forms on one entry is a config-load error.

  **The target key is `file` (decided 2026-07-26)** — the same key
  `[[regenerate]]` uses, one vocabulary across `press-rules.toml`. The prior
  art used `path`; consistency inside this tool's own config wins over
  matching the embedded engine. And **reset reads bytes as text, fail
  closed**: the target's current content and any `stub_file` must decode as
  UTF-8 at plan time — the line count, the verbose excerpt, and the stub
  scan all interpret text — and undecodable bytes refuse the press (exit 2),
  mirroring P04's rule for regeneration outputs.

  **`stub_url` (remote fetch) considered and DEFERRED.** It would be the
  tool's first network dependency — press is pure stdlib, offline, and
  deterministic by design — to serve content that can equally be committed as
  a `stub_file`. If a real template ever needs it, the sketched semantics:
  fetched once at plan time so the preview shows the actual content; an
  unreachable URL is a plan-time refusal (exit 2, nothing written).

### Tests & Tasks

- [x] [P05-TS01] Failing tests: `[[reset]]` schema — the target declared as
      `file` (the `[[regenerate]]` key, not prior art's `path`); `stub` XOR
      `stub_file` (both or neither is a config-load error); `stub_file`
      containment predicates; `ROOT_CONTROL` paths rejected as reset
      targets; non-UTF-8 target or `stub_file` refused at plan time;
      stub-content scan refuses changed tokens and rendered FROM literals
      from either source; the reset/replace overlap ban (reset⊗regenerate
      lands in P04-TS11)
- [x] [P05-T02] Implement the `[[reset]]` schema + config-load validation
- [x] [P05-TS03] Failing tests: preflight — untracked or dirty target
      refused even under `--allow-dirty`; the named predicates
      (`assert_under_root`, `assert_ancestors_real`, `is_regular_lstat`);
      exit 2 = nothing written; two-level lines-based preview always present,
      the excerpt behind the new `--verbose` flag with its fixed 20-line
      bound
- [x] [P05-T04] Implement the preflight + preview
- [x] [P05-TS05] Failing tests: apply — reset runs first (position zero,
      source coordinates); `safe_write` with original-mode preservation;
      `ApplyReport.reset` + receipt `reset = <n>` count; a failed reset
      aborts with no receipt; translated reset-target path components pass
      the same paranoid scan as regeneration output paths
      (`app_name = "changelog"` → `CHANGELOG.md`, thread 3653398575)
- [x] [P05-T06] Implement the reset operation + reporting
- [ ] [P05-T07] Joint acceptance: the R3 self-press with the migrated rules
      yields a stub `CHANGELOG.md`, regenerated lockfiles, and a clean
      verify (§6 preflight is P04-TS11/T12; the migration itself is P04-T15)

### Notes

Gap **G1** from the dogfood register
([research 0004 §G1](../docs/research/0004-py-launch-blueprint-conformance-gaps.md)),
tracked under issue #54. The dominant leak by a wide margin: re-verified
2026-07-25 against v3.3.0 — 678 findings in `CHANGELOG.md` alone, 86% of the
791 total, unchanged from the v3.2.0 run.

**Prior art (researched 2026-07-25, do not re-derive).** The embedded engine in
py-launch-blueprint had exactly this feature:

- Schema is exactly two keys — `path` and `stub` (`init/common.py:208-221`);
  one instance ever: `CHANGELOG.md` → `"# Changelog\n"` (`init/manifest.toml:579-582`).
- **Static content only — it never ran a shell command.** Running commands is a
  *separate* mechanism there (`RegenerateOp` carries an argv). Worth stating
  plainly because the two are easy to conflate.
- Exact path, not globbed; creates the file if absent; no tracked/untracked
  check; idempotent (skips when content already equals the stub)
  (`init/_engine.py:190-196`).
- Ran inside the main rewrite phase in order `remove → replace → rename → reset`,
  fatal on failure — deliberately unlike regeneration, which was skippable and
  best-effort.
- **Not recorded** in the post-rebrand marker; the reset list was printed to
  stdout and discarded.

Ordering constraint from the register: a reset must be applied *before* the
verify scan reads the file, so a reset file contributes zero findings.

Not blocked by P06 — reset removes content rather than adding a substitution, so
it adds no cell to the matrix P06 exists to eliminate.

