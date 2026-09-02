# P10 — Declared pre-press clean (`[[clean]] paths`, `press clean`)

- **Status:** `[ ]` scoped, not started

A restricted `[[clean]] paths = […]` declaration and a standalone
`press clean [--show]` subcommand that runs `git clean -fdX -- <paths>`;
ordering enforced by the closure refusal naming `press clean`; check-tools
and receipt coverage.

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [2026-09-01 press-improvements-g2p design spec](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E10 (`[[clean]]`, new mechanism, restricted v1)
- **Review:** [CLEAN-review.md](../docs/superpowers/specs/reviews-2026-09-01/CLEAN-review.md)
