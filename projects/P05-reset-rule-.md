# P05 — Reset rule: blank a file to a declared stub

- **Status:** `[?]` idea

First destructive op — blank CHANGELOG-style files instead of leaking their history

### Open questions

- Q: **Built-in default vs purely target-declared?** The register proposes both
  in different sentences and nothing since settled it. `rules.py`'s own contract
  says "the tool never carries a target's identity or file list — only generic
  rules", yet `exclude_files` already hardcodes `CHANGELOG.md`. Under the
  no-hidden-defaults preference this resolves to declared-only — confirm.
- Q: **What guards does the engine's first destructive operation need?** Nothing
  in press today discards content; every op substitutes. Candidates: refuse to
  reset an untracked file (no git undo path), dry-run preview showing the
  before/after, a `reset` count in `ApplyReport` + receipt, and capturing the
  prior content so a before/after diff is inspectable.
- Q: **§6 — the exclude-file contract preflight.** Fail loud (exit 2, distinct
  diagnostic) when an `exclude_files` entry exists, still carries identity, and
  is neither regenerated nor reset nor `verify_ignore`d. Depends on P04 and P05
  both landing. Own work item, or folded into whichever lands second?
- Q: **Atomic or best-effort?** The embedded engine made reset fatal inside
  `apply()` (aborts the press) while regeneration was best-effort (warn and
  continue). Press currently treats a failed regeneration as a hard failure with
  no receipt. Which posture does reset take?
- Q: Can a reset target also be a `[[replace]]` target? The embedded engine's
  tests forbade the overlap as "order-dependent, confusing" — inherit that ban?

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
