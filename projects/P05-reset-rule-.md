# P05 — Reset rule: blank a file to a declared stub

- **Status:** `[?]` idea

First destructive op — blank CHANGELOG-style files instead of leaking their history

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
  - Refuse to reset a file git is not tracking — no tracked copy means no undo
    path, so blanking is unrecoverable. Fail loud instead.
  - Preview the before/after — **but only under a verbose flag, and the "before"
    is capped**. The motivating target is a release history that can run to
    thousands of lines; the default preview names the file and its size, and
    verbose shows a bounded excerpt.
  - Record each reset in `ApplyReport` and the receipt, alongside the existing
    replaced/renamed/regenerated counts. Closes a known gap: the embedded engine
    printed its reset list to stdout and discarded it.
  - Refuse a path that is both a reset target and a `[[replace]]` target — the
    result would depend on pass order. Inherits the embedded engine's own test-
    enforced ban.
  - **Not taken:** idempotent skip-when-already-stubbed (`ch-01-d`). The embedded
    engine had it; without it a re-press rewrites identical content and reports
    the reset each time. Harmless, but a deliberate divergence from prior art —
    revisit if the noise proves annoying.
- **D3 — §6's contract preflight folds into whichever of P04/P05 lands second.**
  (`ch-02-a`.) Roughly twenty lines, reusing that project's fixtures; as a
  standalone item it risks being orphaned once the interesting work is done.
- **D4 — A failed reset aborts the whole press.** (`ch-03-a`.) Matches press's
  existing posture on a failed lockfile regeneration (error, no receipt) rather
  than inventing a softer second rule, and avoids a half-applied state that
  neither the doctor nor an operator can reason about.
- **D5 — Validate before mutating: preflight every reset target at plan time.**
  Rather than relying on D4's abort to catch problems mid-run, check up front
  that each declared reset target is resolvable inside the target, git-tracked,
  and writable — failing at plan time (exit 2, no writes) so the destructive
  phase starts only when it can complete. Generalizes the tool's existing
  "exit 2 means nothing was written" contract to the new operation.

  *Scope note:* reset itself never executes anything — it writes a static stub
  (see prior art below); running commands is `regenerate`'s job. The same
  validate-before-mutate principle applies there and is arguably more valuable:
  P04 should check its regeneration command is actually available (e.g. `bun`
  on PATH) before a press begins, instead of discovering it after the rewrite
  phase has already run.

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

<!-- Promote with `project-refine P05`. -->
