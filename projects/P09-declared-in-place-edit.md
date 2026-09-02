# P09 — Declared in-place edit (`[[edit]]`) and command-phase snapshot gate

- **Status:** `[ ]` scoped, not started

A declared `[[edit]]` table: the file is rewritten by the replace pass, then
edited in place by a declared command with a required `expect`
post-condition; runs as a fixed phase before regenerations; not
verify-exempt; and the control-file/visibility snapshot gate fires for any
declared command (E11).

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [2026-09-01 press-improvements-g2p design spec](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E4 (`[[edit]]` with E11 folded in)
- **Review:** [O3-review.md](../docs/superpowers/specs/reviews-2026-09-01/O3-review.md)
- **Review:** [E4-review.md](../docs/superpowers/specs/reviews-2026-09-01/E4-review.md)
