# P11A CI measurement and optimization plan

Reduce avoidable CI waiting and runner consumption before the P12 value review.
Measurement, independent review and the bounded performance investigation are
complete. The owner closed further optimization, declined Windows job splitting
and authorized delivery in PR #124. The project records completion effective on
that PR's merge after final checks and review, not before. The final upload
policy keeps failure/cancellation archives and stops routine successful-job
archives. Earlier checkpoints below are dated evidence; the
[owner closeout](../../../projects/P11A-ci-speed-and-cost-optimization.md#owner-closeout-and-delivery-boundary)
records the current decision and delivery boundary. No optimization was adopted;
the worker and fixture comparisons are recorded in the
[performance report](../../reports/2026-09-09-p11a-windows-performance.md).
Revision 3 incorporates internal, Muse and Opus plan review
findings. The [review closeout](../reviews/2026-09-07-p11a-plan-review-resolution.md)
records actual provider effort and the final internal approval.

**Project:** [P11A](../../../projects/P11A-ci-speed-and-cost-optimization.md).
**Evidence:** [Measured baseline](../reviews/2026-09-07-p11a-ci-baseline.md).

## Phase 1: Baseline and independent plan review

### Milestone 1: Establish the execution contract

Tasks: P11A-TS01, P11A-T01, P11A-T02 and P11A-TS02.

The profile covers 311 unique workflow runs over roughly 47 hours and fully
paginated job records for 43 selected runs. Eleven successful full CI runs
provide descriptive comparisons across changing source revisions. They are
not a controlled before/after experiment.

| Measurement | Observed result | Consequence |
|---|---|---|
| Successful full CI | Median 6m17s; range 5m20s–8m17s | Separate workflow waiting from test execution. |
| Windows test step | Median 263s; range 234s–381s; slowest platform in all 11 runs | Profile Windows first. |
| Locked dependency sync | 1–3s on each platform | Cache tuning is low priority. |
| P10 shipping full CI | 8m07s elapsed; 11.68 cumulative runner-minutes | Waiting time and allocated runner time measure different costs. |
| P11 cancelled Windows job | 98m06s of recorded allocation; no usable Windows test logs | Bound future stalls and retain diagnostics; the cause remains unknown. |

Runner-minutes measure allocated job intervals, not dollars or proven CPU use.
Account pricing, discounts and billing records are unavailable. Do not translate
these measurements into monetary savings.

CI-only implementation may proceed in an isolated branch after this plan passes
review, using the recorded source. Before performance experiments or final
delivery, integrate accepted P11 and rebind workflow, lock, fixture and test
files. P11 owns its defects, isolated Windows validation, full CI and merge.
P11A must not absorb or bypass those gates.

Preserve these requirements and repair the explicitly identified gate gaps:

- Native Linux, macOS and Windows behavior tests, including live tests and
  committed-source self-press acceptance.
- All eight existing required contexts. Confirm exact names from the saved
  branch-protection response; do not change protection settings.
- Pull-request, main-push and merge-group validation, plus the documentation-only
  fast path. `README.md` remains a packaging input.
- Failed or cancelled dependencies must fail `ci-ok`, the aggregate merge check.
  Missing selector outputs must not create a false success.
- Per-test repositories, Git configuration isolation, containment guards and
  native filesystem controls. Never share mutable test repositories.

Two guarantees need small repairs in Milestone 3. The current aggregate accepts
successful change detection with a missing output. Required lint jobs can also
skip after their change detector fails. Separately, required `trufflehog` has
no merge-group trigger. These are source-demonstrated gaps, not evidence of an
actual bad merge or a currently enabled merge queue.

Published Blacksmith credit weights provide a separate, conditional cost model:
Linux 4 vCPU uses 2 units per minute, Windows 4 vCPU uses 4, and macOS 6 vCPU uses
20. One unit is one published x64 2-vCPU credit-minute. Applying those rates to
P10's Blacksmith jobs assigns about 54% of modeled credits to macOS and 33% to
Windows. This is not an account bill. Prioritize Windows for latency, and assess
shared test/helper improvements on macOS before claiming a cost improvement.
The [baseline supplement](../reviews/2026-09-07-p11a-ci-baseline.md#published-credit-model)
records the formula, source and exclusions.

### Milestone 2: Review and select the bounded scope

Tasks: P11A-T03 and P11A-T04.

Implement timing, recoverable diagnostics and explicit execution limits first.
Then measure one promising Windows optimization at a time. Select changes that
preserve this contract and demonstrate a repeatable benefit.

| Candidate | Recommendation | Benefit to establish | Cost or tradeoff |
|---|---|---|---|
| Timing, diagnostics and limits | Implement after plan review | Identify slow tests and cap abandoned work | Artifact/log overhead; limits need measured margins. |
| Selector and merge-group gate gaps | Repair with focused controls | Preserve meaningful required checks while optimizing | Small CI-only changes; no protection-setting changes. |
| Windows fixture or Git subprocess work | Change only a measured hot helper | Less startup with equivalent fixture behavior | Shared helpers require isolation and Git-state controls. |
| `load` versus `worksteal` scheduling | Compare if timings show worker imbalance | Keep workers busy with the same tests | More scheduling overhead; no gain if the host is saturated. |
| Worker count | Try one additional setting only if justified | Better use of the existing runner | More collection work and disk contention are possible. |
| macOS/Windows coverage instrumentation | Preserve initially; propose separately if worthwhile | Behavior tests may run faster without instrumentation | Only Linux uploads a report, but platform coverage evidence changes. |
| Repeated acceptance or edit preflight | Defer until equivalent ownership is shown | Remove repeated work | Providers, images, triggers and early failure feedback differ. |
| Cache tuning and release-push coalescing | Skip unless new evidence changes value | Small setup or cancelled-run savings | Setup is already short; extra mechanisms may cost more than they save. |

Independent internal review must try to refute the scope, evidence and validation
design. The external major-plan gate requests Muse Ultra with a 100-step maximum.
Record actual model/effort, completion and provider fallbacks. Use approved Opus
fallback when Fable is unavailable. Unavailable review is not approval. Resolve
substantive findings before implementing the reviewed scope.

Changes to platform coverage, required validation or paid runner plans need a
concrete owner decision. Equivalent optimizations and diagnostics are within the
requested CI work. Do not ask for another P10/P11 approval.

## Phase 2: Diagnostics and a controlled Windows experiment

### Milestone 3: Make failures bounded and observable

Task: P11A-T05, first implementation slice. Use locked tools without adding
`pytest-timeout` or upgrading dependencies for this work.

1. Add `--durations=25 --durations-min=1` and separate JUnit files for preflight
   and full tests, such as `--junitxml=ci-results/preflight.xml` and
   `--junitxml=ci-results/full.xml`. Jobs have separate filesystems; uploaded
   artifact names must also include platform and Python version. Preserve
   selection and coverage. Capture Python patch, Git, uv, Bun, runner image,
   actual CPU/worker counts, plugin versions and source revision.
   If the command is reflowed or its surrounding job layout changes, update
   `test_general_ci_provisions_bun_for_native_r3` in the same commit to inspect
   command semantics across whitespace, retaining its full-suite/Bun contract.
   Run that focused, non-live test against the edited workflow before pushing.
2. Request stack traces after 120 seconds in one test using locked pytest's
   fault handler with `-o faulthandler_timeout=120` on both invocations. Prove
   useful retained output on native Windows and POSIX under
   xdist, the parallel runner. A stack dump does not terminate a hung process.
   Add a small opt-in progress journal if native in-test, collection or worker
   loss probes show built-in output cannot identify the last active phase,
   worker and test. Before any test starts, evidence must explicitly identify
   collection/session setup and report that no test has started.
3. Propose a 5-minute preflight limit, a 15-minute full-test limit and a 25-minute
   enclosing test-job limit. Bound diagnostic upload to 2 minutes. The extra
   job margin accommodates setup, a slow preflight and evidence upload. Check
   margins against corrected P11 first, including total setup/preflight elapsed
   before a full-test timeout. Do not claim a guaranteed artifact if the runner
   itself stops responding. Do not add an arbitrary per-test failure deadline.
   Verify `job limit > setup + preflight limit + full-test limit + upload bound`
   with a positive measured margin. Step timeout must normally fire first.
4. The owner-selected closeout policy uploads available diagnostics on failure
   or cancellation, with unique platform names and 7-day retention. Each upload
   uses `if: failure() || cancelled()` and the existing 2-minute limit. Successful
   test jobs skip routine archive uploads; ordinary logs and bounded local
   diagnostics remain. The earlier controlled campaign used `if: always()`
   for both outcomes. Preserve that evidence and validate the final condition
   before delivery. Forced stops may prevent final JUnit output or upload;
   retain active-test evidence before the terminal limit. Preflight and full
   artifacts must not overwrite each other.
5. Preserve the owner's Windows sequence: isolate the failed remote job/family,
   reproduce it, validate the correction there, then run the full batch.
6. Make `ci-ok` require successful `changes` with exactly `true` or `false`
   output. Permit heavy-job skips only for a validated documentation-only PR.
   Selected heavy jobs and always-required jobs must succeed. Missing/invalid
   output, an unexpectedly skipped selected job, failure and cancellation fail.
7. Make required `actionlint` and `yamllint` fail when `lint-changes` fails,
   is cancelled or omits/invalidates its selectors. Preserve deliberate skips
   of lint work after valid `false` selectors and retain the exact required
   context names. GitHub string equality ignores case, so an always-run shell
   validator must reject uppercase `TRUE`/`FALSE` before conditional tool steps.
   For valid `false`, the named job may succeed with its expensive steps skipped.
8. Map all required contexts to their workflows/events before editing. The
   current source already gives `commitlint (humans)` a merge-group context;
   its lint step deliberately skips because the PR commits were checked earlier.
   Add `merge_group` to `secret-scan.yml`. Use the existing non-PR full-history
   scan of the speculative merge revision, with full checkout history and no
   equal-base/head diff. Preserve ordinary PR/main scan behavior. Do not change
   branch protection or enable the merge queue as part of this correction.

Validate behavior rather than merely compare YAML text:

- A tiny scratch harness deliberately hangs in preflight and in parallel full
  testing on native Windows and POSIX. Use short harness limits. Require
  bounded non-success, identifiable test/worker
  context, retained stack/progress evidence and a failed aggregate gate.
- Add a collection/session-setup hang and intentional xdist worker loss. Retain
  the affected phase/worker, last-started test or explicit no-test-started state,
  the interruption/restart outcome and bounded failure. These controls also
  determine whether the progress journal is necessary. Do not infer worker
  identity solely from interleaved stack output.
- Exercise step timeout and enclosing job timeout separately. Step-timeout
  artifacts are required; report whether job-timeout artifacts survive and
  retain the limitation if the provider prevents their upload.
- A passing control with the same options completes with expected test IDs,
  outcomes and useful artifacts.
- Verify production selects those validated options, and failed/cancelled
  outcomes cannot create successful `ci-ok` results.
- Exercise the actual production gate logic with successful detection plus
  empty/invalid output, selected-but-skipped jobs, failure and cancellation.
  They must fail; valid documentation-only skips and fully passing selections
  must pass. Test the equivalent failure and valid-false controls for both
  required lint contexts. Use scratch remote cases to confirm GitHub job
  conditions and outcomes, not just the local decision function.
- Map all eight required contexts to PR, main and merge-group inputs. For the
  added secret-scan trigger, bind checkout/scanning to the speculative merge
  SHA and prove passing/failing scanner outcomes retain the `trufflehog` name.
  Use the production configuration plus a bounded event/runner harness where
  a live merge-group event cannot be produced without changing owner settings;
  label that limitation rather than claiming an actual merge-queue run.
- If provider cancellation loses artifacts, record the limitation and improve
  earlier diagnostics before claiming failures are observable.

### Milestone 4: Adopt a worthwhile Windows optimization

Task: P11A-T05, performance slice, after the diagnostic gate passes.

**2026-09-09 result:** the owner later authorized a bounded performance
investigation while the remaining Milestone 3 scanner/timeout proofs were open.
Those proofs still gate production delivery. The investigation is complete
without adoption. Neither two nor eight workers improved the selected 50-test
family over four. The fixture candidate improved the first 257-test pair by
8.43%, then regressed 10.89% in reversed order. Both pairs passed evidence
checks, but the negative second pair fails the every-positive rule below.
No third run or further scheduler/shard experiment was justified. Total Windows
allocation was 929 of 1,800 runner-seconds, with 871 unspent. The disposable
remote benchmark branch was deleted; local evidence and rejected source remain
preserved. At that checkpoint the investigation closed while Milestone 3's
scanner/timeout proofs and P11A-T05 remained open. Those native proofs and the
later production execution/margins are now admitted. The owner subsequently
closed further optimization and expressly declined Windows job splitting.

Use corrected P11 native timing before another full-suite probe. Identify a
slow family/helper or worker imbalance. Measure one candidate against identical
baseline source, tests and runner allocation.

Start with one baseline/candidate screening pair on the smallest representative
family. Stop an unpromising candidate. For a promising change, complete at least
three alternating baseline/candidate pairs; a valid screening pair counts
toward those three. Keep Python patch, Git, uv, Bun, locked plugins, coverage,
runner image, actual CPU/worker count and cache state comparable. Vary only the
proposed mechanism. Blacksmith may automatically provide extra CPUs, so runner
label alone is insufficient. Run pairs without a superseding push to their
reference; exclude cancelled/incomplete runs. Record mismatches and discard
confounded pairs. Screen at most two plausible variants unless new evidence
justifies more work, and stop after one useful result.

Allocate at most 30 cumulative Windows runner-minutes to initial screening and
confirmation experiments, plus 10 minutes across other platforms to assess a
shared change. Count timed-out and discarded experiment runs against this
budget. Normal required PR validation is reported separately. Before each pair,
compare measured savings per future run with experiment allocation already
spent and report the implied number of runs to recover that cost. Stop at the
budget or when evidence no longer supports a worthwhile result; do not expand
the experiment merely to obtain a positive finding.

For measured live tests, record the actual commit and relevant input hashes of
each external blueprint clone against its test ID, from the clone that ran.
An earlier `ls-remote` query is insufficient. Different or missing clone
provenance makes a pair inconclusive. Apply this to full-suite confirmation;
ordinary live-test default-branch behavior remains unchanged. Validate the
comparison rule with matching, differing and missing external-input records.
Capture from the actual clone under the test's temporary directory using the
existing guarded Git helper. Use identical capture in both comparison arms;
never query the working checkout outside the test sandbox for this evidence.

Retain source/test hashes, test IDs, outcomes/skips, test-step elapsed time,
queue delay, allocated runner time and failure-detection behavior. Use medians
and observed ranges. Compute each paired improvement as baseline seconds minus
candidate seconds. Adopt when all three are positive and their median exceeds
the largest of the controlled baseline range, 5% of the controlled baseline
median, and 2 seconds. Results/isolation must remain equivalent. This minimum
effect avoids adopting a one-second measurement artifact in a tiny family.
Never use the historical 234–381s range
as the threshold. Report each paired delta and any allocated-time regression.
For example, controlled baselines of 100/102/101s and candidates of 85/86/86s
give improvements of 15/16/15s versus a 5.05s minimum effect. Baselines of
100/100/100s and candidates of 99/99/99s are inconclusive. This is an illustrative
decision rule, not a performed benchmark or a significance test. Treat noisy
or contradictory evidence as inconclusive.

For a helper change, first add a discriminating regression for an unsafe shortcut.
Check independent repositories, Git status/config, tracked/ignored paths and
containment refusal. Preserve real Git and native Windows evidence. For
scheduling, compare executed IDs/skips, worker crashes and retries. Do not assume
grouping modules with `loadscope` benefits function-scoped fixtures.

Confirm a selected candidate in the affected native full suite and normal
all-platform PR checks. A faster family alone does not prove a faster workflow.
Stop extra variants when a useful result is established or further experiment
cost is unjustified.

## Phase 3: Delivery and closeout before P12

### Milestone 5: Deliver the measured result

Task: P11A-T06.

Integrate accepted P11 first. Keep CI optimization separate from P11 correctness
delivery. Run setup, required local checks, workflow linting and committed-source
acceptance required by changed files. Use normal PR/review flow and CI evidence
bound to the final source revision.

Report changed behavior, baseline/candidate run links, comparable versions,
workflow waiting, test execution and cumulative runner time separately. Describe
proven stall bounds and diagnostics separately from healthy-run performance.
Record test/skip equivalence, required checks, native acceptance, limitations,
rejected candidates and why further work is not worthwhile.

A negative benchmark can close an investigation honestly. Diagnostic and timeout
changes can ship without a healthy-run speedup. Do not claim normal CI is faster
unless a full-suite comparison supports it. Complete the chosen delivery or
record an evidence-based no-change decision before the P12 review.

Milestone 4 closed without adoption. The T06 upload-policy review used observed
duration, bytes, reliability and diagnostic value. The owner then selected
failure/cancellation uploads, superseding the earlier recommendation to retain
successful-run archives. The final condition keeps the approved paths, names,
retention and bound; its final-source checks and review remain prerequisites
to merge. Seven-day expiry is not an automatic end to future failure uploads.

PR #124 carries the final tracking state, effective on its authorized merge.
Before merge, M5 delivery and T06 remain pending; after merge, the checked T05
and T06 entries record the delivered diagnostics/gate repairs and no-adoption
result. Existing CI and Fable evidence at `f71d3dd` is labeled as the source
before the final upload-condition correction. Use the PR's final commit/check
and merge records for that correction. P12 resumes with value evaluation only
after P11A delivery, without an implied implementation decision.
