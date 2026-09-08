# P11A measured CI baseline

Windows test execution is the primary target for healthy-run improvements.
Stall containment and diagnostics come first because the P11 Windows run lost
its usable test logs. No optimization has been implemented or benchmarked.

## Scope and measurement

Source: `6304a5d5c090d06272c744f9651e2520d53ce16d`, tree
`0ad63b29862c20d28479094ece5ded1f711e399f`.
Later P11 corrections require a fresh source binding before implementation.

The inventory contains 311 unique runs created from `2026-09-06T00:00:00Z`
through `2026-09-07T23:18:05Z`, across four REST pages. Fully paginated job
records were collected for 43 selected workflows. Eleven successful full CI
runs with all three platforms form the normal-duration sample. Source revisions
vary, so these are descriptive measurements, not controlled comparisons.

Workflow latency means creation through final job completion. Queue delay means
job creation through job start. Cumulative runner-minutes sum allocated jobs'
start-to-completion intervals. They do not apply CPU, OS or billing multipliers.
Actual monetary costs are unknown; no pricing contract or invoice was accessed.
The recorded duration of a stalled job is not proof of continuing billable CPU.

## Results

| Workflow | Elapsed time | Runner-minutes | Interpretation |
|---|---:|---:|---|
| [P10 shipping CI 34163591598](https://github.com/smorinlabs/template-press/actions/runs/34163591598) | 8m07s | 11.68 | Passing P10 source; Windows determined completion. |
| [P10 merged CI 34164525517](https://github.com/smorinlabs/template-press/actions/runs/34164525517) | 7m31s | 11.22 | Independent main validation. |
| [Earlier main CI 34066409746](https://github.com/smorinlabs/template-press/actions/runs/34066409746) | 5m30s | 8.63 | Older source; scale reference. |
| [Documentation-only CI 34065867682](https://github.com/smorinlabs/template-press/actions/runs/34065867682) | 35s | 0.65 | Heavy jobs deliberately skipped. |
| [P10 acceptance 34163591589](https://github.com/smorinlabs/template-press/actions/runs/34163591589) | 1m43s | 2.02 | Separate native acceptance workflow. |
| [P11 acceptance 34164445623](https://github.com/smorinlabs/template-press/actions/runs/34164445623) | 2m01s | 2.37 | POSIX and GitHub-hosted Windows passed. |
| [Cancelled P11 CI 34164445625](https://github.com/smorinlabs/template-press/actions/runs/34164445625) | 99m53s | 103.77 | Recorded allocation, excluded from normal performance. |

Successful full CI had median latency 6m17s, with a 5m20s–8m17s range.
Windows determined completion in all 11 successful runs.

| Platform | Median full-test step | Observed range | Dependency sync |
|---|---:|---:|---:|
| Linux, Blacksmith 4 vCPU | 49s | 44–72s | 1–2s |
| macOS, Blacksmith 6 vCPU | 99s | 84–117s | 1–3s |
| Windows, Blacksmith 4 vCPU | 263s | 234–381s | 2–3s |

P10's complete shipping-push batch consumed 985 allocated runner-seconds across
10 workflows. Full CI accounted for 701 seconds and acceptance for 121 seconds.
These are cumulative allocations; concurrent jobs overlap in elapsed time.

The P11 Windows job started at `21:49:50Z` and ended after cancellation at
`23:27:56Z` on September 7, a 98m06s interval. Its coverage step started at
`21:50:24Z`; the completed job record did not contain a finished pytest result.
Individual Windows logs returned `BlobNotFound`; the completed run ZIP contained
no Windows job logs. The stall cause and last active test are unknown.
`ci-ok` failed after cancellation, preserving the existing failure gate.

## Implications and constraints

The [full CI workflow](https://github.com/smorinlabs/template-press/blob/6304a5d5c090d06272c744f9651e2520d53ce16d/.github/workflows/ci.yml)
already runs parallel pytest workers: four on Linux, six on macOS and four on
Windows. It uses the default `load` scheduler. More workers are not automatically
faster because each collects tests and competes for filesystem/process resources.
No per-test duration report, JUnit report, explicit test-step timeout or test-job
timeout is configured in that source.

All three platforms collect coverage; only Linux uploads it. Removing non-Linux
instrumentation is a measurable candidate, with a platform-coverage tradeoff.
Keep current collection until that separate proposal is evaluated.

Live acceptance overlaps the full suite, but the
[separate acceptance workflow](https://github.com/smorinlabs/template-press/blob/6304a5d5c090d06272c744f9651e2520d53ce16d/.github/workflows/rebrand-matrix.yml)
uses an additional GitHub-hosted Windows image, different triggers and a separate
gate. It has no merge-group trigger; its path list omits general dependency and
workflow changes. Do not remove full-suite live coverage in favor of that
workflow without proving equivalent execution and required failure propagation.

The serial 12-case edit preflight repeats cases from the full suite. P10's
separate steps took 3s on Linux, 10s on macOS and 23s on Windows. Removing it
would lose early failure feedback. Profile and preserve that benefit before
changing the partition.

The separate hygiene workflow checks different tools from the main Ruff job;
it is not duplicate lint. Its P10 allocation was only 38 runner-seconds.
Four historical cancelled release-PR CI/CodeQL runs accounted for 120 allocated
runner-seconds in the inventory, much less than the P11 stall. Dependency sync
is already short. These are lower-priority opportunities.

The protection response requires eight contexts: `ci-ok`, `trufflehog`,
`commitlint (humans)`, `bandit`, `actionlint`, `yamllint`, `codespell` and
`editorconfig-check`. Strict up-to-date checking is false. No setting changed.
Keep the documentation-only fast path and required statuses present. Preserve
per-test Git isolation, native filesystem controls and committed-source R3
self-press validation, which exercises the checked-in regeneration helper.

## Evidence receipt

The complete investigator report and raw/derived measurements were retained in
the session evidence directory, `/private/tmp/template-press-group3-execution`.
The primary run and source links above make this summary reviewable without it.

| Artifact | SHA-256 |
|---|---|
| `p11a-ci-profile.md` | `8ecdc79d3d283bf2cd7af25e66452646246d0e29d18b1e7f1261fe9d60e20337` |
| `p11a-ci-baseline.json` | `914961d9346c844e393756e6764723e5de28f5f3315933bcc9b916af444b851d` |

Metric invariants, raw/source provenance hashes and configured actionlint passed.
The investigator performed no source/workflow edits, test runs or CI mutations.
P11 cancellation belonged to the separate authorized delivery task.

## Published credit model

A later read of [Blacksmith's official runner documentation](https://docs.blacksmith.sh/blacksmith-runners/overview)
provides relative credit weights. These are published rates, not verified
account pricing. One credit unit here means one x64 2-vCPU credit-minute.
The same documentation notes that a job may receive extra CPUs automatically,
so experiments must record actual CPU and worker counts as well as runner labels.

Applying the published weights to P10's 10-workflow shipping batch gives this
conditional model for Blacksmith jobs only:

| Runner | Recorded seconds | Credits per minute | Modeled credits |
|---|---:|---:|---:|
| Linux 4 vCPU | 320 | 2 | 10.67 |
| macOS 6 vCPU | 137 | 20 | 45.67 |
| Windows 4 vCPU | 419 | 4 | 27.93 |
| Total Blacksmith | 876 | Different by runner | 84.27 |

Each row is allocated seconds divided by 60, multiplied by published credits
per minute. macOS contributes about 54.2% and Windows about 33.1% of this model.
The other 109 runner-seconds use GitHub-hosted runners and are excluded.
No account credits, invoice rounding, contract discounts or actual charge is
inferred. This supplements the unweighted runner-time measurements; it does
not change them or establish delivered savings.

Windows remains the waiting-time target. Shared fixture improvements that also
reduce macOS work may have greater cost value than a Windows-only change.
Keep platform coverage intact while evaluating that possibility.
