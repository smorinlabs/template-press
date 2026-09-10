# P11A native timeout diagnostics — 2026-09-09

All fourteen controls were admitted, and the temporary remote branch was
removed after source and run evidence were preserved. The controls demonstrate
provider timeout enforcement and useful retained diagnostics, with explicit
limits on final output and cancellation timing. Independent Muse review returned
SPEC PASS / QUALITY APPROVE with no required fixes. These controls do not measure healthy
full-suite performance or complete Milestone 3 or Milestone 5 for
[P11A](../../projects/P11A-ci-speed-and-cost-optimization.md). The later
[owner closeout](../../projects/P11A-ci-speed-and-cost-optimization.md#owner-closeout-and-delivery-boundary)
records production acceptance and the final failure/cancellation upload policy;
project completion takes effect on PR #124's merge after final checks and review.

## Source and tested behavior

The disposable source is `9bb9abd15e78866f4b26cf350f4cc2aacfb5a69f`, tree
`fb8c9f5f35646bf169491829d828380d2b8f1114`. Its parent is corrected production
`5cd95f34c78e807f2c735ecd324fa0423ea75c78`. The three production collector helpers
and CI workflow match intended integration
`845eedcaaf2b6009b06bb848d05022807b15ee1c`. The diagnostic harness was not merged.

Each actual `workflow_dispatch` selected one case and one operating system.
`platform=posix` selected native Ubuntu, not macOS. The runners were
`blacksmith-4vcpu-windows-2025` and `blacksmith-4vcpu-ubuntu-2404`.
Both reported four CPUs through `cpu_count` and `process_cpu_count`.
Requested pytest workers and observed worker processes are distinct evidence.

| Recorded tool or image | Windows | Ubuntu |
| --- | --- | --- |
| Python | 3.13.7 | 3.13.15 |
| Image | `windows25`, `20250901215242` | `ubuntu24`, `20260121153938` |
| Git | `2.51.0.windows.1` | `2.52.0` |
| uv | `0.12.12` | `0.12.11` for the first three finite controls; `0.12.12` thereafter |
| Bun | `1.3.14` | `1.3.14` |
| pytest / xdist / coverage plugin | `9.1.1` / `3.8.0` / `7.1.0` | `9.1.1` / `3.8.0` / `7.1.0` |

The passing case ran one fixture through serial preflight and then a two-worker
full invocation. “Full” is this fixture's parallel mode, not the product suite.
The finite cases required actual child exits 0/0, 1, 7 and 1 for passing,
assertion failure, early session exit and worker loss. The expected nonzero
exits yielded successful control steps after exact exit assertions. Real stall
probes retained provider failure or cancellation.

The harness used a three-second fault-handler interval, one-minute ordinary
probe steps and eight-minute enclosing jobs. The separate job-limit case used
a three-minute job and a four-minute probe step. Intended production uses a
120-second fault-handler interval, five-minute preflight, fifteen-minute full
test, twenty-five-minute test job and two-minute upload, as specified by the
[plan](../superpowers/plans/2026-09-07-p11a-ci-optimization.md).

## Per-run outcomes and allocation

Every row is attempt 1 and was admitted by its recorded platform reviewer or
root gate. “Failure” and “cancelled” below are actual provider conclusions, not
failed evidence admission. No attempt was replaced or excluded from the ledger.

| Case | OS | Run | Child result or timeout cause | Probe / job outcome | Allocated job seconds |
| --- | --- | --- | --- | --- | ---: |
| pass | Ubuntu | [34366717640](https://github.com/smorinlabs/template-press/actions/runs/34366717640) | exits 0 / 0 | success / success | 17 |
| fail | Ubuntu | [34367154424](https://github.com/smorinlabs/template-press/actions/runs/34367154424) | exit 1 | success / success | 20 |
| exit7 | Ubuntu | [34367509203](https://github.com/smorinlabs/template-press/actions/runs/34367509203) | exit 7 | success / success | 14 |
| worker-loss | Ubuntu | [34404904813](https://github.com/smorinlabs/template-press/actions/runs/34404904813) | exit 1 | success / success | 16 |
| body-preflight | Windows | [34405229974](https://github.com/smorinlabs/template-press/actions/runs/34405229974) | step limit | failure / failure | 83 |
| body-preflight | Ubuntu | [34405694245](https://github.com/smorinlabs/template-press/actions/runs/34405694245) | step limit | failure / failure | 86 |
| body-full | Windows | [34406142317](https://github.com/smorinlabs/template-press/actions/runs/34406142317) | step limit | failure / failure | 90 |
| body-full | Ubuntu | [34406162088](https://github.com/smorinlabs/template-press/actions/runs/34406162088) | step limit | failure / failure | 87 |
| collection-full | Windows | [34407090424](https://github.com/smorinlabs/template-press/actions/runs/34407090424) | step limit | failure / failure | 98 |
| collection-full | Ubuntu | [34407105411](https://github.com/smorinlabs/template-press/actions/runs/34407105411) | step limit | failure / failure | 85 |
| session-full | Windows | [34408020829](https://github.com/smorinlabs/template-press/actions/runs/34408020829) | step limit | failure / failure | 90 |
| session-full | Ubuntu | [34408044691](https://github.com/smorinlabs/template-press/actions/runs/34408044691) | step limit | failure / failure | 86 |
| job-timeout-full | Windows | [34408395111](https://github.com/smorinlabs/template-press/actions/runs/34408395111) | enclosing-job limit | cancelled / cancelled | 227 |
| job-timeout-full | Ubuntu | [34408413324](https://github.com/smorinlabs/template-press/actions/runs/34408413324) | enclosing-job limit | cancelled / cancelled | 238 |

| Current-source diagnostic allocation | Allocated job seconds | Artifact ZIP bytes |
| --- | ---: | ---: |
| Ubuntu | 649 | 31,026 |
| Windows | 588 | 17,638 |
| Total | 1,237 | 48,664 |

Allocated seconds sum actual job start-to-completion intervals, including gaps
and failed or cancelled work. The separate preallocation delay totaled 494
seconds, measured from run creation to job allocation. It is not added to
allocation. These figures are not billing dollars or performance savings.
The sequence's summed nominal job ceilings were 6,120 seconds, not predicted
usage or a guarantee of exact termination.

Earlier Windows finite controls remain evidence on `80e8625`, not this source:
[pass](https://github.com/smorinlabs/template-press/actions/runs/34301263193),
[fail](https://github.com/smorinlabs/template-press/actions/runs/34302277973),
[exit7](https://github.com/smorinlabs/template-press/actions/runs/34302598215) and
[worker loss](https://github.com/smorinlabs/template-press/actions/runs/34302839473).
Their 109 allocated seconds are excluded from this fourteen-run subtotal.
The scanner's 22 Ubuntu seconds and the closed M4 performance ledger are also
separate. M4 remains at 929 of 1,800 Windows runner-seconds, with 871 unspent.

## Retained evidence and exact expiry

All fourteen downloaded ZIPs matched their artifact catalog digests and sizes.
Every member matched the approved paths. The passing control retained distinct,
passing preflight and full JUnit files, actual exits and serial/two-worker
journals. Its preflight files remained byte-identical after full execution.
The assertion, early-exit and lost-worker cases retained their distinct failure,
no-test or worker-down/replacement evidence.

The unchanged upload uses `always()`, `actions/upload-artifact@v7`, a two-minute
bound and seven-day retention. Its frozen 621-byte block has SHA-256
`604d54cebec192ef60374223421ce51d9c9e6a912e676923c41ec5fd9c1c32fe`.
Only `preflight.xml`, `full.xml` and direct `*.log`, `*.jsonl`, `*.json` children
of the corresponding `preflight/` or `full/` directory were uploaded. Archive
paths are relative to `ci-results/`. The exact artifact names were
`ci-tests-blacksmith-4vcpu-windows-2025-py3.13-attempt1` and
`ci-tests-blacksmith-4vcpu-ubuntu-2404-py3.13-attempt1` for the respective OS.
Provider upload steps lasted one or two whole seconds in these small controls;
that does not predict upload duration for the product suite.

The table copies exact provider UTC timestamps. Each expiry minus seven days
fell within that artifact's actual upload step. The check uses this upload
window, not an exact interval from the catalog's `created_at` field. Those
created-to-expiry intervals are 604,799 or 604,800 seconds. These are declared
future expiry times, not observed artifact deletions.

| Run | Artifact ID | Files | ZIP bytes | Created UTC | Exact expiry UTC |
| --- | --- | ---: | ---: | --- | --- |
| 34366717640 | 10110165147 | 16 | 6,492 | 2026-09-09T14:55:00Z | 2026-09-16T14:54:59Z |
| 34367154424 | 10110344053 | 6 | 3,138 | 2026-09-09T14:58:57Z | 2026-09-16T14:58:56Z |
| 34367509203 | 10110484366 | 5 | 1,803 | 2026-09-09T15:02:04Z | 2026-09-16T15:02:03Z |
| 34404904813 | 10124928837 | 12 | 4,635 | 2026-09-09T21:05:52Z | 2026-09-16T21:05:51Z |
| 34405229974 | 10125119241 | 6 | 3,146 | 2026-09-09T21:11:05Z | 2026-09-16T21:11:04Z |
| 34405694245 | 10125260038 | 5 | 2,559 | 2026-09-09T21:15:04Z | 2026-09-16T21:15:03Z |
| 34406142317 | 10125457937 | 10 | 4,458 | 2026-09-09T21:20:33Z | 2026-09-16T21:20:32Z |
| 34406162088 | 10125444339 | 9 | 3,834 | 2026-09-09T21:20:11Z | 2026-09-16T21:20:10Z |
| 34407090424 | 10125825085 | 10 | 3,685 | 2026-09-09T21:30:47Z | 2026-09-16T21:30:46Z |
| 34407105411 | 10125802227 | 9 | 3,059 | 2026-09-09T21:30:09Z | 2026-09-16T21:30:08Z |
| 34408020829 | 10126169201 | 5 | 1,890 | 2026-09-09T21:40:39Z | 2026-09-16T21:40:38Z |
| 34408044691 | 10126157890 | 5 | 1,682 | 2026-09-09T21:40:20Z | 2026-09-16T21:40:19Z |
| 34408395111 | 10126387901 | 10 | 4,459 | 2026-09-09T21:47:13Z | 2026-09-16T21:47:13Z |
| 34408413324 | 10126382243 | 9 | 3,824 | 2026-09-09T21:47:03Z | 2026-09-16T21:47:02Z |

| Artifact ID | Downloaded ZIP SHA-256 |
| --- | --- |
| 10110165147 | `aa6703918b356caadb403d29085b06a820bcef0b28314405851445779d40d1c5` |
| 10110344053 | `c81c665c760b13196670431cb909cd0f10440f8f73311aa1f4547edaa969a725` |
| 10110484366 | `743bd60001ddcd55389118c68a714a9f07eb73f1aef10ce7759391d1871b4f08` |
| 10124928837 | `d68f747d38fff34cd7b4ad78a82de2d9ad26c2c1b9777d0792afbeeaa796a78d` |
| 10125119241 | `c1a06b2e0fac5de960e31460076abb6537f54a824519a57a217ee880706478b9` |
| 10125260038 | `bccce7b6967aaef6a359c28656e033b49a94a41bf2dcd1dffd7781a571bf4dc7` |
| 10125457937 | `cbb1bfcaa1464b61bdd1d406535e2cb2e9a0ad624be79bb18d29f9c3e5690076` |
| 10125444339 | `46bab158feb5df13df4e6ac75b1fab0705e55b9f06adf73eb07435e2eee30b39` |
| 10125825085 | `7dfe6a18620cf4372f18e248de619b2bc796e1c3cbce1458845a561c02814a05` |
| 10125802227 | `be68935ea8b4bec9f74f33672ab5a37660d7c7b4c1418e183c85b6d757da8a8f` |
| 10126169201 | `0d8dbb72abfc9937ccc3233011f04aa179693f5e8468f00b062ba2a9a0fbe7c9` |
| 10126157890 | `892cb6057c42bbf818ea9ae445924e9c136f33eda4271530d8cacaef65597754` |
| 10126387901 | `f79eab564c857310894594100b982075d115ce0cc8390477f9415f605fec07ce` |
| 10126382243 | `fadd8e82e622f8d90e761d713ed7b7a1512ee85be70ee7618d30ec09e872eb8c` |

## Ordinary step limits and enclosing job limits

Body stalls retained actual test stack frames and the journal's worker,
process ID and test identity. Collection stalls retained explicit
`no_test_started: true` with no test node. Session stalls retained controller
session-setup state and zero launched workers, despite requesting `-n 2`.
Neither pre-test case requires or establishes test-body execution.

Windows interrupted runtimes recorded `interrupted: true` and child exit 2.
Where present, zero-test JUnit files or anonymous unfinished placeholders do
not establish a passing or normally completed test. Ubuntu stalls retained
useful activity or stack evidence without a final runtime exit, finish time or
JUnit file. The idle worker's exit 0 in parallel body stalls is not an overall
success. No graceful completion is inferred from missing terminal metadata.

Ordinary step-timeout uploads started with 388–402 seconds remaining within
the nominal 480-second job, exceeding the required 120-second upload window.
The Windows probes lasted 60–61 seconds; Ubuntu probes lasted 72–73 seconds.
The observed Ubuntu overrun was 12–13 seconds beyond the nominal minute. Its
cause and exact signal sequence were not isolated.

| Enclosing-job control | Nominal job limit | Actual job allocation | Observed overrun | Useful probe window before nominal deadline | Upload margin at start |
| --- | ---: | ---: | ---: | ---: | ---: |
| Windows 34408395111 | 180 s | 227 s | 47 s | 154 s | −42 s |
| Ubuntu 34408413324 | 180 s | 238 s | 58 s | 171 s | −54 s |

Both raw provider annotations state
`The job has exceeded the maximum execution time of 3m0s`. Their probes, jobs
and workflows remained cancelled. The actual probes lasted 196 seconds on
Windows and 225 seconds on Ubuntu, below their separate 240-second step limits.
Their useful pre-deadline probe windows exceeded the required thirty seconds.

Both archives survived, but uploads started 42 and 54 seconds after the nominal
job deadline. Those negative margins remain negative. The runs establish
provider-triggered job-limit cancellation and observed diagnostic recovery.
They establish neither a strict 180-second wall-clock cap nor a guaranteed
upload after enclosing-job cancellation. Raw evidence does not isolate the
whole overrun cause or a precise cancellation-start timestamp.

Missing ordinary-step archives would fail the required retained-evidence gate.
If an enclosing job or runner stops before upload, an absent archive can
document that limitation but cannot prove retained observability. All archives
happened to survive this campaign; partial runtime and JUnit limits still apply.

## Cleanup and remaining delivery

The exact temporary remote branch `ci/p11a-timeout-diagnostic` was removed after
all fourteen run evidence sets and a verified source bundle were preserved.
The subsequent ref lookup returned HTTP 404. Local branches and worktrees,
source and downloaded archives remain preserved. Removing the branch did not
remove provider artifacts or change their scheduled expiry.

### Historical checkpoint before production CI

Milestone 3 remains open for final integrated production source/options and
positive timing margins. The earlier corrected-P11 Windows job began preflight
15 seconds after allocation; combining that one setup observation with intended
production limits leaves 165 seconds of planning margin. That earlier source
had no P11A instrumentation, and the sample is not a future setup bound or final
combined production margin. These short controls do not supply normal
all-platform production CI or an artifact-delivery guarantee.

The independent native campaign closeout review returned SPEC PASS / QUALITY
APPROVE, with no required fixes. The actual model was `muse-spark-1.3` and the
actual effort was `xhigh`: requested `ultra` was unavailable because its gate
was closed. The configured maximum was 100 model steps; the actual count was
not reported. This was a read-only review of the frozen native proof packet.

Milestone 5, P11A-T05 and P11A-T06 remain open for final-source validation, committed
acceptance, normal CI, PR review and authorized delivery. Gate and scanner
proofs remain separately recorded. P12 remains paused.

The existing all-outcome seven-day upload policy is unchanged. At P11A-T06,
review observed runtime, bytes, reliability and diagnostic value before deciding
the ongoing policy. Ending routine successful-run archives remains a proposal.
The Windows performance investigation remains closed without adoption; these
diagnostic results establish no healthy-run speedup.

### Later production acceptance and owner disposition

The earlier open-gate and policy statements above are historical. Production
CI and committed-source acceptance subsequently passed at `f71d3dd`, with
positive production margins of 169 Linux, 171 macOS and 166 Windows seconds.
Fable approved that frozen source with no blocking defect. These product runs
and their source binding are recorded in the linked owner closeout; they are
separate from this short native fixture campaign.

The owner then closed optimization, declined Windows job splitting and selected
`failure() || cancelled()` uploads for the final PR #124 revision. The existing
paths, names, two-minute bound and seven-day retention remain. Routine
successful-job archives stop; local bounded diagnostics and ordinary logs
remain. Final-policy checks and review precede authorized merge. T05/T06
completion takes effect on that merge, after which P12's value evaluation may
resume. The campaign's partial-output, provider-overrun and non-guaranteed
upload limitations remain; no healthy-run speedup is claimed.
