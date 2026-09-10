# P11A Windows performance investigation — 2026-09-09

Keep the existing four-worker behavior and original test fixtures. The bounded
worker screens found no useful improvement, and the fixture candidate failed
confirmation. No production speedup or billing-dollar saving is established.
This records the completed performance investigation for
[P11A](../../projects/P11A-ci-speed-and-cost-optimization.md). The later
[owner closeout](../../projects/P11A-ci-speed-and-cost-optimization.md#owner-closeout-and-delivery-boundary)
ends further optimization, declines Windows job splitting and makes delivery
completion effective on PR #124's merge after final checks and review.

Each comparison ran on native Windows with four logical CPUs and coverage.
Durations below measure the test invocation, including startup and completion,
and are rounded to three decimal places. They are not whole-job durations.

| Worker comparison and order | Four workers | Alternative | Alternative result |
| --- | ---: | ---: | --- |
| [Four, then two](https://github.com/smorinlabs/template-press/actions/runs/34316763202) | 63.939 s | 109.364 s | 71.04% slower |
| [Four, then eight](https://github.com/smorinlabs/template-press/actions/runs/34317153176) | 66.355 s | 66.860 s | 0.76% slower |

The fastest observed 50-test invocation took **63.939 seconds with four
workers**. Pytest itself reported 63.08 seconds; the outer measurement includes
process startup and completion. The surrounding job took 196 seconds because
it ran both alternatives, provisioned tools and uploaded evidence. That job
interval is not the duration of a single normal CI job.

All four invocations passed the same 50 history, configuration and removal
tests, covering the same 3,719 production source lines. Production `-n auto`
selected four workers on this runner. No worker setting was changed, and eight
workers were not tested on the later 257-test family.

The fixture candidate avoided three Git configuration subprocesses for an
ordinary fresh repository. It preserved independent repositories, real Git
initialization/staging/commit and original-command fallback for other inputs.
Its isolated [Windows correctness run](https://github.com/smorinlabs/template-press/actions/runs/34354420198)
passed 33 cases and skipped one POSIX-only read-only-directory case. Symlink
and hardlink controls passed. Correctness did not establish a speedup.

| Fixture comparison and order | Original fixture | Candidate fixture | Candidate result |
| --- | ---: | ---: | --- |
| [Original, then candidate](https://github.com/smorinlabs/template-press/actions/runs/34355461670) | 120.686 s | 110.508 s | 8.43% faster |
| [Candidate, then original](https://github.com/smorinlabs/template-press/actions/runs/34356345752) | 113.459 s | 125.819 s | 10.89% slower |

All four invocations passed the same 257 existing tests with four workers and
covered the same 4,754 production source lines. Both archives passed independent
source, runtime, test/outcome, coverage, worker and fixture-isolation checks.
The selected runs verified each test's repository and output ownership. They
do not certify every full-suite interleaving. Tests that launch nested pytest
add worker processes. Live uv/Bun caches were not stress-tested; peak memory and
Git child-process CPU were not measured. Other families or parallel execution
settings require their own validation.
The frozen runtime included Python 3.13.7, Git 2.51.0.windows.1, uv 0.12.11,
Bun 1.3.14, pytest 9.1.1 and xdist 3.8.0 on Windows Server 2025.

Both pairs favored the implementation that ran second. This order-sensitive
ranking does not prove a cache mechanism or isolate variation between runner
allocations. The adoption rule required at least three valid alternating pairs
with every improvement positive, plus effect-size and variability checks.
The negative second pair already fails that rule. No third run was justified,
and the fixture candidate was rejected. No whole-suite comparison was made.

Independent worker-balance and existing-job-topology analysis did not justify
an alternate scheduler or additional runner shards. Those variants were not
executed or adopted. Additional jobs would duplicate setup and reporting; no
aggregate runner-time saving was demonstrated. Preflight remains a sequential
failure gate before the full suite.

Muse returned SPEC PASS / QUALITY APPROVE for benchmark commit
`732e15a3ef8b68e93fd6049b26cbb3c780a1138d` and its design. Actual effort was
`xhigh` with `muse-spark-1.3` because Ultra was unavailable. The configured
maximum was 100 steps; the review reported about 14 read/search steps.
This records source review, not a 100-step or Ultra completion or native gain.

| Completed Windows allocation | Runner-seconds |
| --- | ---: |
| Four versus two workers | 196 |
| Four versus eight workers | 163 |
| Fixture correctness controls | 32 |
| Fixture pair, original first | 265 |
| Fixture pair, candidate first | 273 |
| **Total used** | **929 of 1,800** |
| **Unspent** | **871** |

These allocated job intervals include setup and teardown. They are not billing
dollars. All five jobs completed; no additional experiment is planned.

The disposable remote branch `ci/p11a-performance` was deleted after evidence
preservation, and a subsequent ref lookup returned HTTP 404. Local source,
archives and the verified source bundle remain available. Seven staged files
for an unshipped full-suite profiler were preserved without publication.
Uploaded artifacts keep their seven-day expiry.

## Historical delivery checkpoint before later native validation

The integration checkout remains unchanged at
`845eedcaaf2b6009b06bb848d05022807b15ee1c`, with original fixtures and no disposable
benchmark. The rejected candidate was never integrated, so no production revert
was needed.

Milestone 3 scanner and timeout payloads remain source-ready with their earlier
publication hold unresolved. Milestone 5 still requires the intended production
patch's normal all-platform CI, PR review and authorized delivery. P11A-T05 and
P11A-T06 remain open. The ongoing success/failure diagnostic upload policy must
be reviewed at P11A-T06; seven-day retention does not stop future uploads.
P12 remains paused, and this investigation changes no P12 scope or status.

### Later owner disposition

The checkpoint above is superseded by the linked owner closeout. Scanner and
native timeout proof, production margins, all-platform CI and the frozen-source
Fable review subsequently passed. Windows job splitting remains untested and
is expressly declined, not an active deferred optimization. No performance
candidate was adopted. The owner authorized failure/cancellation-only archives
and delivery in PR #124; final-policy checks precede merge. This dated report's
measurements and rejected-candidate evidence remain unchanged. P12 may resume
its value evaluation after P11A's authorized delivery completes.
