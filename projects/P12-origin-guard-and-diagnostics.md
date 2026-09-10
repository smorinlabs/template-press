# P12 — Origin guard relaxation, closure diagnostics, warnings and docs

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [2026-09-01 press-improvements-g2p design spec](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E1, §E2, §E3, §E5(a)(b)(d), §E8, §E9
- **Review:** [E1-review.md](../docs/superpowers/specs/reviews-2026-09-01/E1-review.md)
- **Review:** [E1-options-review.md](../docs/superpowers/specs/reviews-2026-09-01/E1-options-review.md)
- **Review:** [E2-review.md](../docs/superpowers/specs/reviews-2026-09-01/E2-review.md)
- **Review:** [E2-codex-review.txt](../docs/superpowers/specs/reviews-2026-09-01/E2-codex-review.txt)
- **Review:** [E3-review.md](../docs/superpowers/specs/reviews-2026-09-01/E3-review.md)
- **Review:** [E8-review.md](../docs/superpowers/specs/reviews-2026-09-01/E8-review.md)
- **Review:** [2026-09-10 follow-up value evaluation](../docs/superpowers/reviews/2026-09-10-p12-value-evaluation.md)

- **Status:** `[x]` complete, 2026-09-10. Base parts 1 and 2 were delivered in
  [PR #109](https://github.com/smorinlabs/template-press/pull/109) and
  [PR #111](https://github.com/smorinlabs/template-press/pull/111). Four follow-up
  corrections merged in [PR #125](https://github.com/smorinlabs/template-press/pull/125).
  The owner declined the six remaining follow-ups without implementation.
  P12-T-defer-6 was already complete. All eleven follow-ups have a disposition.

The owner inserted [P11A — CI speed and cost optimization](P11A-ci-speed-and-cost-optimization.md)
before this value review. P09, P10, P11 and P11A are now merged. P11A closed in
[PR #124](https://github.com/smorinlabs/template-press/pull/124), and its merged
source `7ac8c1744485081d973ac6b910f13de3fb459d83` passed main-branch CI.

On 2026-09-10, the owner requested a critical evaluation of the ten then-open items:
confirm the actual behavior and likelihood, distinguish bugs from optional
improvements, compare the value with the complexity, and identify any departure
from accepted requirements. The evaluation preserved the original claims and
separated its recommendations from the subsequent owner decisions below.

The evaluation recommended fixing P12-T-defer-2 and P12-T-defer-7, narrowing
P12-T-defer-4 and P12-T-defer-5, and closing the other six without implementation.
The owner then instructed: "Solve all four." Commit `86e0885` implements those
four corrections. After their merge, the owner instructed:
"Yes close the 6 recommended to close and document the pass on those".
That decision closes P12-T-defer-1, P12-T-defer-3, P12-T-defer-8,
P12-T-defer-9, P12-T-defer-10 and P12-T-defer-11 without implementation.
The accepted limitations and conditions for reopening are recorded below.
This project and its closeout are limited to
Template Press; downstream feedback-log work is not a P12 dependency.

Task markers distinguish completed work (`[x]`) from work the owner decided
not to do (`[-]`). A declined task does not claim that its limitation was fixed.
Project completion records merged delivery and all follow-up decisions; package
publication and downstream retesting remain separate.

### Delivery and validation

PR #125 merged on 2026-09-10 at
`9b265813a4ce36da6ae3e170e914949b480a4eab`. Its final delivery commit was
`bafdfbfcaefc8b6c716e0f0561d638b6dd7752a0`.
Earlier local implementation validation passed `just check` with
2,193 tests passed and 24 skipped, followed by the two-test cleanup-hint family
after correcting its platform-specific expectation. The native self-rebrand
case passed against committed source `86e0885`. Independent internal review
found no unresolved implementation issue. The
[final shipping CI](https://github.com/smorinlabs/template-press/actions/runs/34444700728)
passed before merge, including the
[native Windows suite](https://github.com/smorinlabs/template-press/actions/runs/34444700728/job/102766912956)
with 2,123 passed and 110 skipped.
An isolated Windows proof reproduced the obsolete retry assertion before the
full-suite retry. These are implementation-delivery results, not fresh platform
tests of this documentation-only closeout.

E1 origin==destination acceptance + `--accept-origin-mismatch`; E2
aggregated closure refusal with remedy argv and `--diagnostics-json`;
E5(a)(b)(d) removal coverage warning/counts/own declarations; E8
dir-only-ignore near-miss hint; E9 prefix-only warning; E3 docs + boundary
test.

### Tests & Tasks

- [-] [P12-T-defer-1] Batch the verify/doctor ignore-hint queries. Owner declined implementation on 2026-09-10; synthetic scaling cost is accepted until a real affected workload justifies the change.
- [x] [P12-T-defer-2] Removal-coverage warning: count excluded tracked descendants carried by directory renames using the captured closure, deduplicated in original source coordinates. Rename authorization and excluded-file content remain unchanged.
- [-] [P12-T-defer-3] Count retargeted stable-name symlinks in the removal-coverage warning. Owner declined implementation on 2026-09-10; the narrow advisory omission is accepted and remains documented.
- [x] [P12-T-defer-4] Retained documentation: replace the five links into deliberately removed research with named historical references in `docs/README.md`, `docs/design/0004` and `0008`. Research removal policy is unchanged.
- [x] [P12-T-defer-5] Windows recovery presentation: show explicitly labeled JSON argument arrays for cleanup and restoration guidance, preserve preview-first and conditional cleanup instructions, and retain POSIX shell quoting. Structured refusal output is unchanged.
- [x] [P12-T-defer-6] `press verify` policy for a flag-accepted press: today verify exits 2 (unrelaxed `mismatches()`) until `origin` is repointed. Options: a matching `--accept-origin-mismatch` on verify, or record the exact accepted origin values in the receipt and accept only those. A field-name-only receipt list must not be trusted automatically (a stale receipt would waive any future value) — from the Task 10 Codex review.
      Done (Task 10b): the receipt records `origin_mismatch_accepted = { owner = "…", repo_name = "…" }` and verify waives a mismatch only when the discovered value equals the recorded one, and only from a receipt BOUND to that target (`verified = true` plus a `[press.to]` equal to its own `press-source.toml`); the 4.1 list form, a receipt describing a different identity, and a hand-written one are all not honored (fail closed); binding is by identity, not provenance.
- [x] [P12-T-defer-7] Document the existing `rmdir_paths` field in `docs/source/reference/cli.md`: sorted empty-directory paths relative to the target, complete even when prose is truncated, and empty when no empty directories were found.
- [-] [P12-T-defer-8] Move prefix-warning counts after declared replacement rows. Owner declined the proposed change on 2026-09-10; the accepted original-source policy remains, superseding the PR #109 triage promise.
- [-] [P12-T-defer-9] Add structured operational refusals to `press verify --json`. Owner declined the proposal as written on 2026-09-10; preflight refusals retain stderr, exit 2 and empty stdout.

- [-] [P12-T-defer-10] Stronger concurrent-writer protection for `press clean` was evaluated and declined on 2026-09-10. The stable-input prerequisite and existing guards remain; deletion is not atomic against arbitrary writers. Origin: [PR #122 concurrency review](https://github.com/smorinlabs/template-press/pull/122#discussion_r3946789616).

- [-] [P12-T-defer-11] Caching repeated directory-removal input identities was evaluated and declined on 2026-09-10. The measured native cost does not justify changing safety-sensitive capture. Origin: [PR #123 identity-check review](https://github.com/smorinlabs/template-press/pull/123#discussion_r3964065441).

### Closed follow-ups

**Owner decision, 2026-09-10:** pass on implementation of all six recommended
closures. The reasons below adopt the value evaluation after the four approved
corrections merged. Timing figures are historical local probe results, not new
measurements or promises about other targets.

| Task | Reason for declining implementation | Accepted limitation | Reopen when |
| --- | --- | --- | --- |
| P12-T-defer-1 | Repeated Git processes have measurable synthetic cost, but no real affected workload was identified. | Advice for 500 distinct untracked findings took 73.211 seconds for 1,000 Git processes in the evaluation. Verification results remain correct. | A representative real target repeatedly spends meaningful time building this advice; any batch preserves literal paths, ignore inputs, per-path fallback and symlink behavior. |
| P12-T-defer-3 | Improving one narrow warning would require predicting or sharing symlink-retargeting logic; this repository has no tracked symlinks. | A link such as `history/current` can correctly retarget while the history-directory warning is omitted. This accepts a known gap in E5's broad wording and does not claim the omission is fixed. | A concrete target needs this warning and a bounded design preserves link containment and retargeting safety. |
| P12-T-defer-8 | Existing behavior follows the accepted policy of examining original source content. Moving the count can add warnings as well as remove them. | A declared replacement may consume the only compound token while the original-source prefix warning still appears. Successful rewritten output is unchanged. | A real affected target motivates an explicitly approved warning policy, including when to count and when whole-token occurrences suppress a warning. |
| P12-T-defer-9 | The current stream and exit-code contract is intentional and tested; no dependent consumer requiring a new error object was identified. | Operational preflight refusals produce prose on stderr, exit 2 and empty stdout even with `--json`. Consumers must inspect the exit code before parsing a completed report. | An actual consumer needs machine-readable refusal reasons and the error codes, stream placement and compatibility contract are explicitly designed. |
| P12-T-defer-10 | Stronger coordination would expand the cleanup contract without a required concurrent workflow. Another filesystem check only moves the race. | Selected paths, ignore/configuration inputs and the index must stay stable. A concurrent replacement after the final check can still be deleted. All existing checks remain. | A required concurrent workflow justifies a coordination or platform-specific design with explicit guarantees and native validation. |
| P12-T-defer-11 | The native identity guard took 0.004808 seconds, about 0.16% of a 2.975-second directory freeze. No important real bottleneck was demonstrated. | The measured synthetic scaling cost remains. Input-identity checks continue to protect direct paths, hardlinks and aliases without a new cache. | Representative real-target timings show meaningful benefit and a design preserves missing-input, identity and concurrent-change guards at the validated snapshot boundary. |

There are no open P12 follow-up decisions or implementation tasks. Reopening
conditions identify when to reassess; they do not authorize new work or create
an ongoing performance, diagnostics or concurrency project.
