# P11 — Directory removals (`[[remove]] dir`) and removal phase

- **Status:** `[ ]` scoped, not started

`[[remove]] dir = …` with frozen plan-time expansion, per-directory clean
check, gitlink/symlink refusal, `rmdir`, per-path receipt rows, verify
parity; decides whether removals move before the rewrite pass.

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [2026-09-01 press-improvements-g2p design spec](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E5(c) (multi-file removals — `[[remove]] dir`)
- **Review:** [E5-review.md](../docs/superpowers/specs/reviews-2026-09-01/E5-review.md)
