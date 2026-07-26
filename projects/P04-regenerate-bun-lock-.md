# P04 — Regenerate bun.lock during a press

- **Status:** `[?]` idea

Neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks

### Open questions

- Q: Should regenerate commands be **target-declared** (no hidden defaults, per
  the stated preference) or stay **tool-hardcoded**? Today `regenerate` is a
  list of *filenames* and the only argv press ever runs is a literal
  `["uv", "lock"]` baked into `cli.py` — a target cannot make press execute an
  arbitrary program. Letting a target declare the command reverses that
  guarantee. This is the cheapest place to settle the policy, before P05 has to
  answer the same question about a destructive operation.
- Q: Scan-exemption keying (EMP-01, design 0007 D3/D5) requires a lockfile to be
  in BOTH the target's `regenerate` AND the tool's own `DEFAULT_RULES.regenerate`
  — deliberately, so a target cannot blind the scanner by declaring a lockfile
  press has no regenerator for. Does a fully-declared model preserve that
  protection, and if so how?

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
