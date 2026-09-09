# P11 — Directory removals (`[[remove]] dir`) and removal phase

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Directory membership and history contract](../docs/superpowers/specs/2026-09-06-p11-directory-removals-design.md)
- **Design:** [Original press improvements specification](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md), E5(c)
- **Plan:** [Six implementation tasks](../docs/superpowers/plans/2026-09-06-p11-directory-removals.md)
- **Depends on:** P10
- **Review:** [Original removal review](../docs/superpowers/specs/reviews-2026-09-01/E5-review.md)
- **Discussion:** [Merged implementation PR 123](https://github.com/smorinlabs/template-press/pull/123)

- **Status:** `[x]` done — Group 3C merged through PR 123 on 2026-09-09 at
  03:45:20 UTC, September 8 in Pacific time. Shipping source
  `b2737a0cf77bd300a4a66d7fac7c52b1b837ca9d` passed independent review, isolated
  Windows validation, full platform CI and native acceptance. Merge commit
  `6079a22b3fb3069b965ee1061765bc67a95349b4` has the same reviewed tree.

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
- [x] [P11-T07] Delivery: final independent review, PR checks and thread resolution, authorized merge, then project closeout.

### Verification

The following task checkpoints are historical. The completed delivery and
current evidence are recorded under **Delivery closeout** below.

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
completed after Fable was unavailable. Those local results closed P11-T06.
At that checkpoint, P11-T07 and the trunk remained in progress pending remote
checks, review threads and the authorized merge. Their completion follows below.

### Delivery closeout

The native Windows mechanism proof confirmed that the oversized pytest test ID
exceeded Windows' environment-variable limit. Short explicit parameter IDs
preserve the original test payloads and assertions. The proof does not establish
the sole cause of the earlier 98-minute stalled run with unavailable logs.

Final review corrections protect active and declared Git configuration inputs,
reject changed indexed blobs or modes when recorded members are absent, and
apply the same protection during historical verification. Read-only Git status
queries preserve index bytes before a hardlink refusal. Discriminating parent
failures and corrected positive/inverse controls established these defects and
their fixes. The combined independent review returned SPEC PASS / QUALITY PASS.

The final local `just check` passed with 2,095 tests and 24 skips. Committed
R1/R2/R3 acceptance passed all four cases. The
[final isolated Windows safety run](https://github.com/smorinlabs/template-press/actions/runs/34306959880)
passed all 50 tests with four workers and coverage in 68.51 seconds before the
shipping correction was pushed. Its diagnostic source matched all 98 relevant
shipping source, test and dependency files.

[Full CI](https://github.com/smorinlabs/template-press/actions/runs/34307256114)
passed on the final shipping source. Each platform collected 2,123 cases:

| Platform | Passed | Skipped | Pytest seconds |
|---|---:|---:|---:|
| Linux | 2,064 | 59 | 110.09 |
| macOS | 2,099 | 24 | 175.34 |
| Windows | 2,015 | 108 | 552.96 |

The separate [native acceptance run](https://github.com/smorinlabs/template-press/actions/runs/34307256146)
passed four POSIX cases and one Windows case. The Windows full-test job interval
was 593 seconds; its test step took 554 seconds. These are timing observations,
not billing or optimization claims.

All eight required contexts were satisfied; `actionlint` and `yamllint` validly
skipped. The final pre-merge inventory contained
40 acceptable check runs and 22 completed acceptable workflow runs. All seven
review threads were resolved. The optional current-head Codex review was still
running at merge, completed five seconds later, and produced no additional
finding in the post-merge inventory. No diagnostic workflow was merged.

Repeated input-identity stat calls remain a value-evaluation candidate under
`P12-T-defer-11`, not unfinished P11 correctness work. P11A still needs its own
native diagnostic validation, optimization assessment and delivery. P12 remains
paused until that follow-up closes.
