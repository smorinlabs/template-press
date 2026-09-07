# P10 — Declared pre-press clean (`[[clean]] paths`, `press clean`)

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Approved exact-file cleanup amendment](../docs/superpowers/specs/2026-09-07-p10-exact-file-clean-amendment.md)
- **Design:** [Original press improvements specification](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md), E10
- **Design:** [Standalone clean decision](../docs/adr/0018-declared-pre-press-clean.md)
- **Plan:** [Original six implementation tasks](../docs/superpowers/plans/2026-09-05-p10-declared-pre-press-clean.md)
- **Discussion:** [PR #122](https://github.com/smorinlabs/template-press/pull/122)
- **Review:** [Original clean review](../docs/superpowers/specs/reviews-2026-09-01/CLEAN-review.md)

- **Status:** `[~]` in progress — Group 3B. Approved input protections and
  exact individual-file cleanup are implemented and reviewed. Native Windows
  validation, current PR checks, acceptance, and merge remain delivery gates
  for PR #122.

### Scope

`[[clean]] paths` declares ignored content eligible for the standalone
`press clean [--show]` command. A regular-file declaration removes only that
file's directory entry, preserving siblings and its parent. Directory
selections use hardened Git cleanup with guards against widening beyond the
selected root. Missing, tracked, and nonignored file declarations are no-ops.
Cleanup preserves its Git and press inputs, runs before an operator's separate
press invocation, and writes no success receipt.

### Tests & Tasks

Original plan Tasks 1–5 are implemented and reviewed. The owner-approved
corrections below precede the original Task 6 delivery gate.

- [x] [P10-TS01] Baseline parser, CLI, tool/receipt, refusal, and native acceptance tests established before their implementations.
- [x] [P10-T01] Task 1: parse restricted `[[clean]]` declarations.
- [x] [P10-T02] Task 2: render SOURCE paths and construct/execute hardened Git argv.
- [x] [P10-T03] Task 3: standalone command, dispatcher, and closure remedy hint.
- [x] [P10-T04] Task 4: tool availability and declaration receipt coverage.
- [x] [P10-T05] Task 5: initial docs, decision record, runbook, and native declaration.
- [ ] [P10-TS02] Prove input preservation, exact-file sibling preservation, alias safety, native Windows behavior, and partial failures with independent controls.
- [x] [P10-T07] Approved correction: protect declared config includes and press controls; prevent ignored-parent scope widening while supporting exact regular-file selections.
- [x] [P10-T08] Amend output, error, and safety documentation; run complete corrected-code checks and final independent review.
- [ ] [P10-T06] Task 6: resolve PR findings, pass current CI and committed-head acceptance, merge under existing authorization, and close out tracking.

### Remaining limitation

Git inputs, index state, and selected paths must stay stable during cleanup.
Immediate per-file checks detect some changes but do not make deletion atomic.
Stronger concurrent-writer protection is a separate value evaluation in
[P12-T-defer-10](P12-origin-guard-and-diagnostics.md).


### Corrected implementation validation

The complete corrected local `just check` passed with 1,805 tests and 23
platform or filesystem skips. Root-wide formatting passed. Independent Muse
and Opus reviews approved specification compliance and quality. Their final
Windows short-name and stale-plan findings received a scoped correction and
independent internal approval. Muse was requested at Ultra with a maximum of
100 model steps; the provider used xhigh. Fable was unavailable before
inference, so the approved Opus fallback was used.

The local skips include native Windows cases. They do not establish Windows
acceptance. Isolated native short-name regression/correction runs and the
shipping PR's platform checks remain required before delivery can close.
