# P11A — CI speed and cost optimization

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Plan:** [CI measurement and optimization gates](../docs/superpowers/plans/2026-09-07-p11a-ci-optimization.md)
- **Review:** [Measured CI baseline](../docs/superpowers/reviews/2026-09-07-p11a-ci-baseline.md)
- **Depends on:** P11 for integration and delivery; profiling runs in parallel.
- **Discussion:** [P11 delivery and current CI](https://github.com/smorinlabs/template-press/pull/123)

- **Status:** `[~]` in progress — owner-requested follow-up between Group 3C/P11
  and the P12 value review. Measurement proceeds in parallel with P11 closeout.
  P11A is a deliberate owner-requested suffix; existing numeric IDs are unchanged.

### Scope

Measure CI latency and cumulative runner time, identify the causes, and produce
an independently reviewed optimization plan. Preserve required checks, meaningful
cross-platform coverage, failure isolation and committed-source native acceptance.
Distinguish queue delay, setup, test execution, duplicated work and stalled jobs.
Use runner minutes unless actual account pricing is available; do not invent
monetary savings. Implementation scope follows the measured plan and its review.

The owner requested this follow-up on 2026-09-07 before proceeding to P12.
No workflow, runner plan or test-coverage change is made by this capture.

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
plans and dependency versions remain within the reviewed contract. No speedup or controlled performance comparison is claimed complete.
Finite Windows diagnostics are validated at the checkpoint below; production
acceptance and timeout evidence remain open. Accepted P11 is required before performance experiments and delivery.
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
integration, controlled performance comparisons and delivery remain pending.
P11A-T05 and P11A-T06 are still open; this checkpoint does not claim faster
healthy CI or project closeout.

The owner approved continued public P11/P11A publication and bounded validation
on 2026-09-08. The earlier automatic push rejection is resolved. All four finite
Windows controls passed on disposable harness commit
`80e86255263cefdf3e83c28b98cf4c2adc474eb5`, and root inspected the downloaded
archives. Together they used 109 allocated job seconds and uploaded 16,358 ZIP
bytes. These are fixture measurements, not billing or healthy-CI savings.

Both independent Muse source sections passed, using `xhigh` because Ultra was
unavailable, with a 100-step maximum per request. Fable 5.1 completed its full
source review in 16 turns and requested changes for interrupt handling and
test-evidence weaknesses; those findings are being reproduced. The separate
production-gate harness passed local independent review, and its first native
control is running. The
[current validation checkpoint](../docs/superpowers/reviews/2026-09-09-p11-p11a-validation-checkpoint.md)
separates completed controls from open acceptance gates. Disposable diagnostic
branches must never merge into production. P11A-T05 and P11A-T06 remain open.

Uploads recur on successful and failed runs. Seven days expires each archive;
it does not stop future collection. At P11A-T06, before P12, review observed
upload duration, bytes, reliability and diagnostic value, and explicitly record
the ongoing policy. The current recommendation is to end routine successful-run
archives after P11A comparisons while retaining useful failure diagnostics.
That policy change remains a recommendation; no automatic sunset is configured.
