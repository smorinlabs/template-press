# P11 — Directory removals (`[[remove]] dir`) and removal phase

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Directory membership and history contract](../docs/superpowers/specs/2026-09-06-p11-directory-removals-design.md)
- **Design:** [Original press improvements specification](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md), E5(c)
- **Plan:** [Six implementation tasks](../docs/superpowers/plans/2026-09-06-p11-directory-removals.md)
- **Depends on:** P10
- **Review:** [Original removal review](../docs/superpowers/specs/reviews-2026-09-01/E5-review.md)

- **Status:** `[~]` in progress — Group 3C. Declaration parsing, frozen
  directory selection, exact deletion, complete receipt history, and public
  press/verifier integration are implemented and reviewed. Discriminating
  membership controls also pass independent review. The native migration,
  documentation, final corrections and committed-head acceptance are complete.
  Native Windows CI, PR review closure and merge remain delivery gates.

### Scope

`[[remove]] dir` selects tracked regular files before mutation. The press removes
only those selected members after rewriting and renaming, records their complete
source and current paths, and uses that recorded membership during verification.
Directory safety checks preserve untracked work and refuse unsafe nodes or Git
visibility inputs. The approved acceptance amendment pairs a supported production
rename with a separate injected nonmember and broken-executor control.

### Tests & Tasks

- [x] [P11-TS01] Establish parser and frozen-selection refusal controls; 51 focused tests passed with one Windows-only skip before the first implementation commit.
- [x] [P11-T01] Task 1: typed directory declarations, static overlap checks, and temporary public execution gate.
- [x] [P11-T02] Task 2: immutable membership, directory safety/status checks, compatibility view, rendering, and command-conflict checks.
- [x] [P11-TS02] Establish executor/history, CLI/verify, renewal, and discriminating membership controls; implementation tests include recorded RED results, and Task 5 rejects deliberately broken alternatives.
- [x] [P11-T03] Task 3: exact deletion, safe empty-directory pruning, and complete bounded receipt history.
- [x] [P11-T04] Task 4: real press, historical verification, and explicit membership renewal.
- [x] [P11-T05] Task 5: prove production preserves nonmembers and deliberately broken alternatives fail the same oracles.
- [x] [P11-T06] Task 6: migrate research declarations, preserve project scaffolding, document behavior, and validate committed-head acceptance.
- [ ] [P11-T07] Delivery: final independent review, PR checks and thread resolution, authorized merge, then project closeout.

### Verification

Tasks 1–2 passed independent specification and quality review. The first batch
passed `just check` with 1,594 tests and three skips, root formatting, and the
four-case acceptance matrix. Native Windows execution of the new junction test
remains a remote CI gate. These results do not certify the unfinished tasks.

Task 3 passed independent specification and quality review, `just check` with
1,651 tests and three skips, root formatting, and all four acceptance tests.
The receipt reader enforces complete bounded history; the executor deletes exact
frozen members and preserves unselected contents.


Task 4 passed independent specification and quality review after correcting
known receipt-metadata preflight and file-only compatibility regressions.
The final `just check` passed with 1,718 tests and three skips. Root formatting
and all four acceptance tests passed. Public directory execution, historical
verification, and explicit membership renewal now share the frozen removal
plan. The deliberately broken alternatives, native declaration migration, and
remote Windows validation remain separate gates.


Task 5 passed independent specification and quality review with no findings.
All four focused controls passed. Production preserves nonmembers, while both
deliberately broken alternatives fail the same independent assertions. These
are inverse controls, not production failures. The final `just check` passed
with 1,722 tests and three skips. Root formatting and all four acceptance tests
passed. No production changes were needed.


Task 6 passed independent specification and quality review with no findings.
The native declaration test first failed against the six file declarations,
then passed with the directory declaration. All twelve explicit project-history
removals and `projects/.gitkeep` remain. The final `just check` passed with
1,723 tests and three skips; root formatting passed. The native R3 assertions
require acceptance after the declaration commit and are not yet certified by
this targeted or full default-suite result.


Final local closeout is bound to implementation commit
`e53e5333cffef7522b885bd559013811cda88a8b`, tree
`46df63f16f926f1a989f9879f7afe1cb0d747905`. The combined `just check` passed
with 2,045 tests and 24 platform/marker skips; all 188 Python files passed root
formatting. The committed-head R1/R2/R3 matrix passed all four cases with six
deselections. Native R3 verifies the research directory history and retained
project scaffolding after cloning that commit.

Final review corrections preserve renewed audit history, reject directory
spelling aliases, retain file-only diagnostics, and preflight complete receipt
bytes and translated field limits before writes. Stable-input occupied-rename
regressions first failed, then passed alongside exact-limit success controls.
Independent internal and Muse correction reviews both approved the final tree.
Muse requested Ultra with a 100-step maximum but reported an `xhigh` fallback;
the maximum is not an observed step count. The earlier whole-branch Opus review
completed after Fable was unavailable. These local results close P11-T06.
P11-T07 and the trunk remain in progress until remote checks, all review
threads and the authorized merge are complete. P12 remains evaluation-only.

### Delivery progress on 2026-09-08

[PR 123](https://github.com/smorinlabs/template-press/pull/123) remains open at
`6304a5d5c090d06272c744f9651e2520d53ce16d`. Two review corrections are committed
locally in `80be8e356da235eaa30d4fa4cbf98e8542e7b4c0`: reject a configured Git
visibility input below a removal directory, and detect newly indexed nonmembers
when reusing history for a directory absent from the worktree. The correction
passed `just check` with 2,062 tests and 24 skips, committed R1/R2/R3 acceptance
with four passes, and 17 isolated native Windows review controls in
[run 34172523362](https://github.com/smorinlabs/template-press/actions/runs/34172523362).
The two PR threads remain unresolved until the correction is published.

Windows isolation narrowed the remaining stall to the 44-case receipt test
family. One autogenerated test ID contains 16,777,306 characters. The local
metadata-only correction `3242c2d0112926f54facaf5c3a12b07f0975b149` supplies short
explicit parameter IDs while preserving all cases, byte payloads and assertions.
The local size control failed before the correction and passed afterward; the
44-case family passed locally with four workers and coverage in 31.68 seconds.
The exact native Windows mechanism proof and corrected family run are pending.
This evidence does not yet establish the sole cause of the stalled remote job.

P11-T07 remains open. Automatic approval review blocked the prepared diagnostic
push and dispatch; the specific approval request is pending. After that boundary
is cleared, validate the isolated native family first, publish the two shipping
commits, complete full CI and fresh review closure, then perform the already
authorized merge. P11A CI work proceeds in parallel, with P12 still paused.
