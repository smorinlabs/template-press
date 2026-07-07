# P03 — External-target rebrand press (clean-core rebuild)

Rebuild as standalone press: rebrand → provision, verify-then-mark

### Open questions

- R3 self-press allowlist — which identity-bearing files (design doc 0006,
  the press-target/rebrand-matrix skills) get excluded vs accepted?

### Notes

- Plan: [docs/superpowers/plans/2026-06-23-rebrand-core.md](../docs/superpowers/plans/2026-06-23-rebrand-core.md)
  covers M0–M3 (rebrand core); M4 (shed residue), M5 (publish 0.1.0), and
  M6 (provision feature modules) are successor plans with decisions locked
  in the plan's program map.
- Salvage branch `feat/init-rebrand-robustness` holds the audit docs
  (BUGS.md, EMPIRICAL_BUGS.md, EMPIRICAL_ARCH.md, OPEN_QUESTIONS.md) and
  the port sources (proven engine + boundary matcher + doctor).
- PyPI name `template-press` is already reserved.
- CI usage (to scope in refine): template-press must be usable in CI as a
  drift guard — a configuration declaring keywords that must be completely
  eliminated from the target repo, testable ("is anything still there?"),
  plus an ignore set for valid instances of prior identity (legitimate
  references to the source repo) that should not count as drift.

<!-- Idea stub — run `project-refine P03` to scope/promote. -->
