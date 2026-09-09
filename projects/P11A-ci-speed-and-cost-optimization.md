# P11A — CI speed and cost optimization

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Plan:** [CI measurement and optimization gates](../docs/superpowers/plans/2026-09-07-p11a-ci-optimization.md)
- **Depends on:** P11, merged and integrated locally before performance comparisons.
- **Discussion:** [P11 delivery and current CI](https://github.com/smorinlabs/template-press/pull/123)
- **Review:** [Measured CI baseline](../docs/superpowers/reviews/2026-09-07-p11a-ci-baseline.md)
- **Report:** [Windows performance investigation](../docs/reports/2026-09-09-p11a-windows-performance.md)

- **Status:** `[~]` in progress — owner-requested follow-up between Group 3C/P11
  and the P12 value review. Performance investigation is complete without an
  adopted optimization; diagnostic validation and delivery remain open.
  P11A is a deliberate owner-requested suffix; existing numeric IDs are unchanged.

### Scope

Measure CI latency and cumulative runner time, identify the causes, and produce
an independently reviewed optimization plan. Preserve required checks, meaningful
cross-platform coverage, failure isolation and committed-source native acceptance.
Distinguish queue delay, setup, test execution, duplicated work and stalled jobs.
Use runner minutes unless actual account pricing is available; do not invent
monetary savings. Implementation scope follows the measured plan and its review.

The owner requested this follow-up on 2026-09-07 before proceeding to P12.
The initial capture changed no workflow, runner plan or test coverage.
Implementation follows the reviewed plan and checkpoints below.

### Tests & Tasks

- [x] [P11A-TS01] Preserve starting source/run IDs and existing passing controls; distinguish the stalled P11 Windows run from normal duration evidence.
- [x] [P11A-T01] Profile completed CI runs, queue/setup/test timing, cumulative runner minutes and repeated or canceled work.
- [x] [P11A-T02] Rank concrete optimizations by measured value, coverage risk, complexity and validation needs.
- [x] [P11A-TS02] Define discriminating correctness controls and before/after benchmarks for the selected candidates.
- [x] [P11A-T03] Complete independent major plan review, including Muse requested at Ultra with a 100-step maximum and the approved Fable/Opus fallback policy; record actual provider capability.
- [x] [P11A-T04] Resolve any real coverage, platform or spending decisions from the concrete reviewed plan and record the selected scope.
- [ ] [P11A-T05] Implement and validate selected optimizations in an isolated PR, or record an evidence-based decision to make no change.
- [ ] [P11A-T06] Complete required CI/reviews and authorized delivery for selected work, record measured results and remaining costs, then resume P12 evaluation.

### Starting evidence

P10 shipping head `34d95817e0dd4044c9f1ed9544cb76b5b6beac7e` passed
[full CI 34163591598](https://github.com/smorinlabs/template-press/actions/runs/34163591598).
Its test results took 71.24 seconds on Linux, 116.58 seconds on macOS and
379.59 seconds on Windows. Those are pytest durations, not whole-run latency
or billable totals. Separate acceptance repeated native pressing in
[34163591589](https://github.com/smorinlabs/template-press/actions/runs/34163591589).

P11 head `6304a5d5c090d06272c744f9651e2520d53ce16d` passed Linux/macOS and
[acceptance 34164445623](https://github.com/smorinlabs/template-press/actions/runs/34164445623).
Its Windows coverage step in
[34164445625](https://github.com/smorinlabs/template-press/actions/runs/34164445625)
was cancelled after a 98m06s Windows job allocation. Windows logs were
unavailable, so its cause remains unknown. It is not a passing performance
baseline. P11 delivery owns that investigation and
its correctness findings; P11A must not silently absorb or bypass those gates.

### Decision boundaries

Do not reduce required validation or cross-platform behavior coverage merely to
make a timing graph shorter. Evaluate equivalent coverage and better scheduling
first. Changes to paid runner plans or deliberate reductions in validation are
owner decisions. Benchmark plausible scheduling/cache candidates before claiming
savings. When Windows fails, run the isolated failed remote job or test family,
validate its correction there, then return to the full batch.

### Measurement closeout

The profile and concrete three-phase, five-milestone plan are recorded. Native
Windows tests dominate the healthy-run sample; setup is already short. Independent
major plan review is complete. Muse used `xhigh` because requested Ultra was
unavailable, with a 100-step maximum requested and actual steps unreported. Opus
completed the approved Fable fallback. A final internal Epicero review approved
revision 3 after checking the narrow corrections and independent cost evidence.
The [review closeout](../docs/superpowers/reviews/2026-09-07-p11a-plan-review-resolution.md)
records provider limitations and finding dispositions.

Milestone 3 implementation is in progress: bounded CI execution, retained
diagnostics and repairs to existing required checks. Platform coverage, runner
plans and dependency versions remain within the reviewed contract. The bounded
performance comparisons below are complete, with no optimization adopted.
Finite Windows diagnostics are validated at the checkpoint below; production
acceptance and timeout evidence remain open. P11 is now merged; its accepted
corrections are integrated and validated locally before performance and delivery.
P12 remains paused behind P11 and this follow-up.

### Local implementation checkpoint

Milestone 3's first local slice is committed at
`01fba91ee95cb40058d3e555c7cf7f669587a692`. It adds bounded diagnostics, execution
limits and required-check repairs. The full local pipeline passed with 2,125
tests and 24 skips. Focused controls and independent internal implementation
review passed. Committed R1a/R1b/R2/R3 acceptance passed all four cases and
preserved the empty project scaffolding. The
[implementation checkpoint](../docs/superpowers/reviews/2026-09-08-p11a-local-implementation.md)
records exact evidence and limitations.

The owner approved the exact seven-day diagnostic upload as Decision Q4 on
2026-09-08. Its seventeen-line workflow step is committed locally at
`e7d7ea2e9843bcf7328808360ec4ac53edf9c617`. Focused workflow checks and upstream
artifact-file selection controls passed. Native provider controls, accepted P11
integration and performance comparisons progressed at the checkpoints below;
production delivery remains pending.
P11A-T05 and P11A-T06 are still open; this checkpoint does not claim faster
healthy CI or project closeout.

The owner approved continued public P11/P11A publication and bounded validation
on 2026-09-08. That cleared the initial diagnostic push rejection. All four finite
Windows controls passed on disposable harness commit
`80e86255263cefdf3e83c28b98cf4c2adc474eb5`, and root inspected the downloaded
archives. Together they used 109 allocated job seconds and uploaded 16,358 ZIP
bytes. These are fixture measurements, not billing or healthy-CI savings.

Both independent Muse source sections passed, using `xhigh` because Ultra was
unavailable, with a 100-step maximum per request. Fable 5.1 completed its full
source review in 16 turns. Confirmed interrupt-output loss and weak stack
assertions were corrected at `5cd95f34c78e807f2c735ecd324fa0423ea75c78`, with
discriminating regression controls and independent review. The corrected full
local pipeline passed with 2,125 tests and 24 skips. The proposed temporary-file
isolation finding was refuted by an actual regression control; a latent lifecycle
policy change was declined.

All eight native production-gate controls passed their intended evidence checks.
The two positive workflows succeeded, and six negative workflows remained
unsuccessful, including real detector-job cancellation. Their 75 allocated jobs
totaled 352 job seconds. These modeled PR events exercise the preserved gate
logic; they do not establish scanner or native timeout behavior.

Two further disposable payloads are committed and independently reviewed:
scanner `b6f337da9aed01fe3d0c77be5233e21c2a5d49d4` and combined finite/timeout
`9bb9abd15e78866f4b26cf350f4cc2aacfb5a69f`. Automatic approval review rejected
the scanner push because it required authorization for the exact new commit and
public branch. Both publications are held pending the combined exact-payload
request. No new scanner or timeout run occurred. The
[current validation checkpoint](../docs/superpowers/reviews/2026-09-09-p11-p11a-validation-checkpoint.md)
separates completed controls from open acceptance gates. Disposable diagnostic
branches must never merge into production. P11A-T05 and P11A-T06 remain open.

Corrected P11's Windows full suite passed 2,015 tests with 108 skips in 552.96
pytest seconds; its job interval was 593 seconds. This is a full-suite timing
reference, not a directly comparable baseline for the selected-family pairs
below. Those worker and fixture comparisons establish no improvement to adopt.

Local integration commit `845eedcaaf2b6009b06bb848d05022807b15ee1c` combines
accepted P11 with corrected P11A. All 144 focused integration controls passed.
The canonical pipeline passed with 2,175 tests and 24 skips, and committed
R1/R2/R3 acceptance passed four cases with six deselections. The integration
preserves all eight P11 correction paths and all nineteen P11A paths exactly.
No disposable harness was imported. This combined source is not yet published
or validated by the normal all-platform provider checks.

### Performance investigation closeout

The owner-authorized Windows investigation finished on 2026-09-09 without an
adopted optimization. Four versus two workers took 63.939 versus 109.364 seconds
for the same 50 tests; two workers were 71.04% slower. Four versus eight took
66.355 versus 66.860 seconds; eight workers were 0.76% slower. Existing
four-worker behavior remains unchanged.

The fixture candidate passed 33 isolated Windows correctness cases, with one
POSIX-only skip. Both timed pairs passed the same 257 tests with four workers.
Original-first order measured 120.686 versus 110.508 seconds, an 8.43% candidate
improvement. Reversed order measured 125.819 candidate seconds versus 113.459
original seconds, making the candidate 10.89% slower. Both pairs passed the
evidence checks. The negative second pair fails the every-positive adoption
rule, so the candidate was rejected without a third run. The order-sensitive
ranking does not establish a cache cause or whole-suite speedup.

Independent balance and job-topology analysis did not justify additional
scheduler or runner-shard experiments. Those variants remain untested and
deferred. Muse returned SPEC PASS / QUALITY APPROVE for the benchmark design
and implementation, using actual `xhigh` effort with a 100-step maximum and
about 14 reported read/search steps. This was not an Ultra review or evidence
of a performance gain.

The five Windows allocations consumed 929 of the 1,800 runner-second budget;
871 runner-seconds remain unspent. The disposable `ci/p11a-performance` remote
branch was deleted, and a subsequent ref lookup returned HTTP 404. Local source,
raw archives, the verified source bundle and seven staged files for an unshipped
profiler remain preserved. The integration checkout is unchanged at `845eedc`;
neither the rejected fixture change nor temporary benchmark was imported.
The [performance report](../docs/reports/2026-09-09-p11a-windows-performance.md)
records run links, outcomes, cost and limitations.

Milestone 4's current investigation and no-adoption decision are complete.
Milestone 3 scanner/timeout proofs remain source-ready but unresolved under the
prior publication hold. Milestone 5 still requires normal all-platform CI,
production PR review and authorized delivery. P11A-T05 and P11A-T06 remain open;
P12 remains paused. Performance investigation did not close those gates.

The approved P11A workflow specifies uploads on successful and failed runs;
production delivery remains pending. Seven days expires each archive and does
not stop future collection. At P11A-T06, before P12, review observed
upload duration, bytes, reliability and diagnostic value, and explicitly record
the ongoing policy. The current recommendation is to end routine successful-run
archives after P11A comparisons while retaining useful failure diagnostics.
That policy change remains a recommendation; no automatic sunset is configured.
