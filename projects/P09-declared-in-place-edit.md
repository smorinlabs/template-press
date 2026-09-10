# P09 — Declared in-place edit (`[[edit]]`) and command-phase snapshot gate

- **Status:** `[x]` completed
- **Closeout:** [PR #116](https://github.com/smorinlabs/template-press/pull/116)
  merged on 2026-09-05 at `f8b74a4554c7227d056c11a360f3cb614185341c`.
  The declared edit mechanism and command-phase snapshot gate are included in
  the Group 3B baseline. Tracking reconciled against the merged PR on 2026-09-06.

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
