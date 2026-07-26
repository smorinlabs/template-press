# P04 — Regenerate bun.lock during a press

- **Status:** `[?]` idea

Neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks

### Decisions

All three open questions settled 2026-07-25 (walkthrough in chat).

- **D1 — Regeneration commands are fully target-declared.** A target declares
  both the file and the argv that rebuilds it, e.g.
  `{ file = "bun.lock", command = ["bun", "install"] }`. Nothing is inferred
  from a filename, so there is no hidden filename-to-command mapping.

  **This deliberately reverses a documented guarantee** and must be recorded as
  such rather than discovered later: today `regenerate` is a list of filenames
  and the only argv press ever runs is a literal `["uv", "lock"]` baked into
  `cli.py`, so a pressed repo's config cannot make press execute a program of
  its choosing (design 0007 D3/D5, EMP-01). After D1 it can. The threat model
  that makes this acceptable: pressing a repo already means running that repo's
  build tooling — `uv lock` itself executes arbitrary build backends — so the
  config is not a new trust boundary, only a more explicit one. Whoever
  implements this should carry that reasoning into the design doc, and D3 below
  is what keeps the change from also weakening leak detection.

- **D2 — Resolve every declared command at plan time; missing tool exits 2.**
  Before any write, check each command's executable resolves on PATH. A missing
  tool becomes a clean refusal with nothing written instead of a failure
  discovered after the rewrite pass has already mutated the repo. Consistent
  with P05 D5 (validate before mutating) and with the existing "exit 2 means
  nothing was written" contract. Considered and not taken: also recording the
  resolved binary path in the receipt for reproducibility across machines —
  worth revisiting, but not required for correctness.

- **D3 — Scan-exemption is earned by result, not by declaration.** Two parts,
  because the two contexts differ:
  - **Real press** (`cli._press`): after regeneration runs, SCAN what the command
    produced. A no-op command (`["true"]`) leaves source identity in the file and
    fails the press. This is newly possible because regeneration happens before
    the doctor scan — note it also requires the doctor to look at regenerated
    files at all, which it does not today (`iter_target_files` skips everything
    in `exclude_files`).
  - **Hermetic verify** (`verify_cli`): keeps an exemption, keyed on **press's own
    list of exemptible filenames** rather than on the target's declaration, so a
    target cannot widen it. Verified 2026-07-25: `_regenerate_lockfiles` is
    called only from `cli.py:379` and never from the verify path, so the sandbox
    copy of a lockfile still carries source identity and would flag forever
    without an exemption.

  Together these preserve EMP-01's actual purpose — a target must not be able to
  blind the scanner to a file that still carries old identity — under a model
  where "does press have a regenerator for this file" has become vacuously true.

### Notes

Gap **G2** from the dogfood register
([research 0004 §G2](../docs/research/0004-py-launch-blueprint-conformance-gaps.md)),
tracked under issue #54 alongside P05.

`bun.lock` sits in `DEFAULT_RULES.exclude_files` (never rewritten) but, unlike
`uv.lock`, is absent from `regenerate` — so stale identity survives and the
verify scanner flags it. Small in code (a `bun install` branch in
`cli._regenerate_lockfiles` plus the regenerate entry); the open questions above
are the real content. Re-verified 2026-07-25 against v3.3.0: still reproduces.

Recommended first of the three captured today — it settles the declared-vs-default
policy on a two-line change rather than on the destructive one (P05).

<!-- Promote with `project-refine P04`. -->
