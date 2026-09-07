# P11A CI measurement and optimization plan

Reduce avoidable CI waiting and runner consumption before the P12 value review.
Measurement is complete; this implementation plan awaits independent review.
No optimization or controlled performance comparison has run yet.

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

Bind relevant workflow, lock, fixture and test files to accepted P11 before
implementation. P11 owns its defects, isolated Windows validation, full CI and
merge. P11A must not absorb or bypass those gates.

Preserve these requirements:

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

### Milestone 2: Review and select the bounded scope

Tasks: P11A-T03 and P11A-T04.

Implement timing, recoverable diagnostics and explicit execution limits first.
Then measure one promising Windows optimization at a time. Select changes that
preserve this contract and demonstrate a repeatable benefit.

| Candidate | Recommendation | Benefit to establish | Cost or tradeoff |
|---|---|---|---|
| Timing, diagnostics and limits | Implement after plan review | Identify slow tests and cap abandoned work | Artifact/log overhead; limits need measured margins. |
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

Task: P11A-T05, first implementation slice.

1. Report the slowest 25 test phases above one second and produce one JUnit
   result file per platform. Preserve full test selection and coverage. Capture
   Python patch, Git, uv, runner image, plugin versions, worker count and source.
2. Request stack traces after 120 seconds in one test using locked pytest's
   fault handler. Prove useful retained output on native Windows and POSIX under
   xdist, the parallel runner. A stack dump does not terminate a hung process.
   Add a small opt-in progress journal only if native probes show built-in
   output cannot identify and retain the active worker/test.
3. Propose a 15-minute full-test step limit inside a 20-minute test-job limit.
   Bound the short visibility preflight separately; leave time for diagnostics
   upload. Check margins against corrected P11 native timings first. Do not add
   an arbitrary per-test failure deadline.
4. Upload available diagnostics on success and failure, with unique platform
   names and short retention. Forced stops may prevent final JUnit output;
   retain active-test evidence before the terminal limit.
5. Preserve the owner's Windows sequence: isolate the failed remote job/family,
   reproduce it, validate the correction there, then run the full batch.

Validate behavior rather than merely compare YAML text:

- A tiny scratch harness deliberately hangs on native Windows and POSIX. Use
  short harness limits. Require bounded non-success, identifiable test/worker
  context, retained stack/progress evidence and a failed aggregate gate.
- A passing control with the same options completes with expected test IDs,
  outcomes and useful artifacts.
- Verify production selects those validated options, and failed/cancelled
  outcomes cannot create successful `ci-ok` results.
- If provider cancellation loses artifacts, record the limitation and improve
  earlier diagnostics before claiming failures are observable.

### Milestone 4: Adopt a worthwhile Windows optimization

Task: P11A-T05, performance slice, after the diagnostic gate passes.

Use corrected P11 native timing before another full-suite probe. Identify a
slow family/helper or worker imbalance. Measure one candidate against identical
baseline source, tests and runner allocation.

Start with one baseline/candidate screening pair on the smallest representative
family. Stop an unpromising candidate. For a promising change, complete at least
three alternating baseline/candidate pairs. Keep Python patch, Git, uv, locked
plugins, coverage, runner image, worker count and cache state comparable. Vary
only the proposed mechanism. Record mismatches; discard confounded pairs.

Retain source/test hashes, test IDs, outcomes/skips, test-step elapsed time,
queue delay, allocated runner time and failure-detection behavior. Use medians
and observed ranges. Adopt a candidate when all three paired timings improve,
its median improvement exceeds the observed baseline spread, and results and
isolation remain equivalent. Treat contradictory or noisy evidence as
inconclusive. This is an engineering rule, not a significance test.

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
