# P10 — Declared pre-press clean (`[[clean]] paths`, `press clean`)

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Approved exact-file cleanup amendment](../docs/superpowers/specs/2026-09-07-p10-exact-file-clean-amendment.md)
- **Design:** [Original press improvements specification](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md), E10
- **Design:** [Standalone clean decision](../docs/adr/0018-declared-pre-press-clean.md)
- **Plan:** [Original six implementation tasks](../docs/superpowers/plans/2026-09-05-p10-declared-pre-press-clean.md)
- **Discussion:** [PR #122](https://github.com/smorinlabs/template-press/pull/122)
- **Review:** [Original clean review](../docs/superpowers/specs/reviews-2026-09-01/CLEAN-review.md)

- **Status:** `[x]` complete — Group 3B. Declared cleanup, input protections
  and exact individual-file selections shipped in [PR #122](https://github.com/smorinlabs/template-press/pull/122),
  merged on 2026-09-07 as `3f8c9fa8adc34aad8dc7dc7c776660070ad93c43`.

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
- [x] [P10-TS02] Prove input preservation, exact-file sibling preservation, alias safety, native Windows behavior, and partial failures with independent controls.
- [x] [P10-T07] Approved correction: protect declared config includes and press controls; prevent ignored-parent scope widening while supporting exact regular-file selections.
- [x] [P10-T08] Amend output, error, and safety documentation; run complete corrected-code checks and final independent review.
- [x] [P10-T06] Task 6: resolve PR findings, pass current CI and committed-head acceptance, merge under existing authorization, and close out tracking.

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

Those local skips included native Windows cases and did not establish Windows
acceptance. The subsequent isolated native short-name runs and shipping platform
checks passed, as recorded in the delivery closeout below.


### Delivery closeout

Shipping commit `34d95817e0dd4044c9f1ed9544cb76b5b6beac7e` passed isolated
native Windows validation before the full shipping suite. The baseline run
[34163206247](https://github.com/smorinlabs/template-press/actions/runs/34163206247)
produced six expected failures and six passes. The corrected run
[34163419361](https://github.com/smorinlabs/template-press/actions/runs/34163419361)
passed the same twelve tests, with no skips in either run. Independent hardlink
controls passed on both revisions. The diagnostic workflow stayed separate
from shipping source.

[Full CI](https://github.com/smorinlabs/template-press/actions/runs/34163591598)
passed on Linux (1,775 passed, 57 skipped), macOS (1,809 passed, 23 skipped) and
Windows (1,728 passed, 104 skipped). The separate
[acceptance run](https://github.com/smorinlabs/template-press/actions/runs/34163591589)
passed all four POSIX cases and native Windows R3. All ten review threads were
resolved with evidence before the normal merge. The two final concurrent-writer
findings were reproduced in disposable fixtures and remain the already approved
P12-T-defer-10 value evaluation. No stronger coordination mechanism is promised
by this closeout. No release or tag is included in P10 delivery.
