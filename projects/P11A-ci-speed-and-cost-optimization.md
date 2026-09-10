# P11A — CI speed and cost optimization

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Plan:** [CI measurement and optimization gates](../docs/superpowers/plans/2026-09-07-p11a-ci-optimization.md)
- **Depends on:** P11, merged and integrated locally before performance comparisons.
- **Discussion:** [P11 delivery and current CI](https://github.com/smorinlabs/template-press/pull/123)
- **Review:** [Measured CI baseline](../docs/superpowers/reviews/2026-09-07-p11a-ci-baseline.md)
- **Report:** [Windows performance investigation](../docs/reports/2026-09-09-p11a-windows-performance.md); [native timeout diagnostics](../docs/reports/2026-09-09-p11a-timeout-diagnostics.md)

- **Status:** `[x]` effective when [PR #124](https://github.com/smorinlabs/template-press/pull/124)
  merges after its final required checks and review. The owner closed the
  optimization phase, declined Windows job splitting and authorized delivery.
  This PR carries the completed main-branch record; while it is unmerged,
  delivery and P11A-T06 are still pending. P11A is a deliberate suffix;
  existing numeric IDs are unchanged.

### Owner closeout and delivery boundary

This section supersedes the earlier checkpoint statements about publication,
production margins, pending reviews and upload-policy proposals. Those dated
records below remain historical evidence. The completion markers in this file
and PROJECTS.md take effect on PR #124's merge, not its preparation or approval.

M3 diagnostics and gate behavior were validated, and M4 ended with no adopted
performance change. Original fixtures, coverage, the existing job graph and
`-n auto` remain. Neither worker-count screen improved the 50-test family; the
reversed fixture pair failed the every-positive rule. The five Windows
experiments consumed 929 of 1,800 runner-seconds. No further optimization run is
planned. Windows job splitting was not tested and is declined by the owner,
rather than deferred as an active P11A candidate.

At source `f71d3ddd3edc55c9d54b610103575834f153e437`,
[production CI 34412702217](https://github.com/smorinlabs/template-press/actions/runs/34412702217)
passed all eight required contexts and all three full suites: Linux 2,156
passed / 59 skipped, macOS 2,191 / 24, and Windows 2,105 / 110. Measured setup
left 169, 171 and 166 seconds of reserve under the configured job/step/upload
limits. [Native acceptance 34412702233](https://github.com/smorinlabs/template-press/actions/runs/34412702233)
passed the four POSIX cases and Windows self-press. These runs checked a
synthetic merge with the identical production tree. They are validation
results, not a controlled whole-suite speedup.

Fable's final review of that frozen source returned SPEC PASS / QUALITY APPROVE
with no blocking defect. The provider reported 72 turns, Fable 5.1 and a small
Haiku usage entry. High effort was requested; no separate actual-effort field
was exposed. The optional dependency/comment/setup changes were declined with
evidence. This review preceded the final upload-condition correction; it is
not claimed as a review of that later edit.

The owner selected `if: failure() || cancelled()` for diagnostic uploads.
Successful test jobs stop uploading routine diagnostic archives. Failure and
cancellation keep the same narrow paths, unique names, two-minute upload bound
and seven-day retention. Ordinary logs, timing, bounded local diagnostics and
coverage remain. The preceding successful matrix uploaded 1,211,389 ZIP bytes
in four summed step seconds; this is historical upload cost, not an estimate
of total collector overhead or guaranteed savings. Seven days expires each
archive and does not end future failure diagnostics. Earlier `always()`
approval, measurements and frozen review packets remain preserved.

PR #124's final revision must pass the required checks and review for this
policy correction before merge. Its final commit, check runs and merge record
are the delivery evidence; the earlier `f71d3dd` results are not substituted
for them. M5, T05 and T06 close when that authorized delivery completes. P12's
value evaluation may then resume; no P12 implementation is authorized by this
closeout.

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
- [x] [P11A-T05] Implement and validate selected optimizations in an isolated PR, or record an evidence-based decision to make no change.
- [x] [P11A-T06] Complete required CI/reviews and authorized delivery for selected work, record measured results and remaining costs, then resume P12 evaluation.

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

Milestone 3's bounded execution, diagnostics and required-check repairs passed
native controls and normal production validation. Platform coverage, runner
plans and dependency versions remain within the reviewed contract. The bounded
performance comparisons ended without adoption. P11 is merged and integrated.
The owner closeout above records the final upload-policy correction and its
delivery boundary. PR #124 has since merged, and P12's reassessment is complete.
[P12's project record](P12-origin-guard-and-diagnostics.md#closed-follow-ups)
documents the four merged corrections and six owner-declined follow-ups.

### Historical local implementation checkpoints

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
`9bb9abd15e78866f4b26cf350f4cc2aacfb5a69f`. At that earlier checkpoint,
automatic approval review rejected
the scanner push because it required authorization for the exact new commit and
public branch. Both publications were held pending the combined exact-payload
request; no new scanner or timeout run had occurred. The
[dated validation checkpoint](../docs/superpowers/reviews/2026-09-09-p11-p11a-validation-checkpoint.md)
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

Independent balance and job-topology analysis did not lead to additional
scheduler or runner-shard experiments. A later audit identified a possible
two-runner Windows comparison, which the owner explicitly declined. These
variants remain untested; no additional P11A experiment is pending.
Muse returned SPEC PASS / QUALITY APPROVE for the benchmark design
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

Milestone 4's investigation and no-adoption decision are complete. Scanner and
finite/timeout proofs, production margins and source review subsequently passed.
The final upload-policy correction and authorized delivery follow the owner
closeout above. T05/T06 completion takes effect on that delivery; closing the
performance investigation alone did not satisfy those delivery gates.

### Scanner proof checkpoint — 2026-09-09

The owner explicitly approved the scanner publication. Both native Ubuntu
controls were independently admitted on unchanged disposable source
`b6f337da9aed01fe3d0c77be5233e21c2a5d49d4`:

- [Clean scan 34362849542](https://github.com/smorinlabs/template-press/actions/runs/34362849542)
  succeeded and used 12 allocated Ubuntu runner-seconds.
- [Scanner failure 34363223859](https://github.com/smorinlabs/template-press/actions/runs/34363223859)
  passed its negative-control evidence checks: the scanner rejected an unknown
  long option with exit 1, and its step, job and workflow remained failed.
  It used 10 allocated Ubuntu runner-seconds.

Both runs checked the same two-parent revision with 449 commits of full history
and used the same Docker image and scanner version, 3.97.1. They uploaded no
artifacts. The total was 22 allocated Ubuntu runner-seconds, separate from the
Windows performance budget. Their actual event was `workflow_dispatch`; the
harness modeled the `merge_group` scan input. This is scanner behavior evidence,
not an actual merge-queue event or a performance gain.

The temporary remote branch `ci/p11a-scanner-diagnostic` was removed after its
source and run evidence were preserved.

The scanner proof slice is complete. The later finite/timeout checkpoint below
records its separate approval and native results. Final production margins and
delivery remain open.

### Native timeout proof checkpoint — 2026-09-09

The owner approved publication, execution, seven-day retention and temporary
branch cleanup for `9bb9abd15e78866f4b26cf350f4cc2aacfb5a69f`. All fourteen native
controls were admitted: four Ubuntu finite cases plus five Windows/Ubuntu
pairs covering serial body, parallel body, collection, session and enclosing-job
stalls. The campaign used 1,237 allocated runner-seconds: 588 Windows and 649
Ubuntu. All fourteen archives survived and matched their catalog digests,
approved paths and seven-day expiry; downloaded ZIPs totaled 48,664 bytes.
This M3 diagnostic allocation is separate from the closed M4 performance budget.

The ordinary step-stall jobs remained failed and retained their phase/process
information. Collection and session journals explicitly recorded no test start;
session stalls launched no workers despite requesting two. Windows interruptions
retained final runtime exit 2 where recorded. Ubuntu could retain activity and
body stacks without a final runtime exit, JUnit or controller completion.
These partial records do not establish normally completed tests.

Both enclosing-job controls remained cancelled with the provider's explicit
three-minute-limit annotation. Actual job allocations were 227 Windows seconds
and 238 Ubuntu seconds. Uploads began 42 and 54 seconds after their nominal
180-second deadlines. The surviving archives prove observed recovery, not an
exact wall-clock cap, positive upload margin or guaranteed future upload.

The temporary remote `ci/p11a-timeout-diagnostic` branch was removed after
source and run evidence were preserved; a subsequent ref lookup returned HTTP
404. Local source and artifacts remain preserved, and provider expiry is
unchanged. The [timeout report](../docs/reports/2026-09-09-p11a-timeout-diagnostics.md)
records all run links, exact retention timestamps, costs and limitations.
Independent Muse review of the completed native campaign returned SPEC PASS /
QUALITY APPROVE with no required fixes. The actual model was `muse-spark-1.3`,
using `xhigh` because requested `ultra` was unavailable under the closed gate.
The maximum was 100 model steps; the actual count was not reported.

Milestone 3 remains open for final production source/options and positive timing
margins. Milestone 5, P11A-T05 and P11A-T06 remain open for required final-source
validation, normal all-platform CI, review and authorized delivery. P12 remains
paused. Native fixture proof supplies no healthy-CI speedup or product-suite
validation.

The approved P11A workflow specifies uploads on successful and failed runs;
production delivery remains pending. Seven days expires each archive and does
not stop future collection. At P11A-T06, before P12, review observed
upload duration, bytes, reliability and diagnostic value, and explicitly record
the ongoing policy. The current recommendation is to end routine successful-run
archives after P11A comparisons while retaining useful failure diagnostics.
That policy change remains a recommendation; no automatic sunset is configured.
