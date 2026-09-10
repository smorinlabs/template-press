# P11A-R2-03: P10 allocation and conditional credit reconciliation

**Verdict: the suspected input inconsistency is refuted.** Raw job timestamps reproduce the published **701 runner-seconds for full CI** and **985 runner-seconds for the complete P10 shipping batch**. The requested per-job evidence is supplied below. Existing allocation totals and conditional credit shares require no correction.

This reconciles saved measurements only. No network request, billing access, test execution, CI dispatch or repository change occurred. The only writes are this report and `p11a-cost-reconciliation.json`.

The batch contains **10 workflows, 26 jobs, 23 allocated jobs and 3 unallocated skipped jobs**. All ten workflows are first-attempt pull-request runs created at `2026-09-07T21:33:55Z` for P10 head `34d95817e0dd4044c9f1ed9544cb76b5b6beac7e`. Their identities also match the saved run inventory. The later source-profile commit `6304a5d5c090d06272c744f9651e2520d53ce16d` describes the inspected repository source; it is not the P10 batch head.

## Per-workflow allocation

Each value below is a sum of allocated job intervals, in seconds. Concurrent jobs overlap in wall-clock time. Platform columns use the exact runner labels in the next table.

| Workflow | Run ID | Linux 4 vCPU | macOS 6 vCPU | Windows 4 vCPU | GitHub Windows | GitHub Ubuntu | Total seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| CI/CD | 34163591598 | 145 | 137 | 419 | 0 | 0 | 701 |
| commitlint | 34163591558 | 11 | 0 | 0 | 0 | 0 | 11 |
| CodeQL | 34163591560 | 36 | 0 | 0 | 0 | 0 | 36 |
| lint | 34163591562 | 38 | 0 | 0 | 0 | 0 | 38 |
| large-file-guard | 34163591577 | 6 | 0 | 0 | 0 | 0 | 6 |
| rebrand-matrix | 34163591589 | 23 | 0 | 0 | 98 | 0 | 121 |
| Claude Code Review | 34163591591 | 44 | 0 | 0 | 0 | 0 | 44 |
| Difftree PR Comment | 34163591593 | 0 | 0 | 0 | 0 | 11 | 11 |
| secret-scan | 34163591604 | 9 | 0 | 0 | 0 | 0 | 9 |
| Dependency review | 34163591617 | 8 | 0 | 0 | 0 | 0 | 8 |
| **Batch total** | **10 workflows** | **320** | **137** | **419** | **98** | **11** | **985** |

`701 + 11 + 36 + 38 + 6 + 121 + 44 + 11 + 9 + 8 = 985` runner-seconds. The full CI Linux total is `88 + 7 + 10 + 9 + 8 + 10 + 9 + 4 = 145` runner-seconds: one 88-second test job and seven other jobs totaling 57 seconds. The raw `ci-ok` step list contains no checkout, contrary to the review's assumption that all eight Linux jobs perform one.

## Every job interval

All start/end times below are UTC on **2026-09-07**. Allocated seconds equal `completed_at - started_at` when `runner_id` is present. A skipped job with no runner contributes zero. Exact job IDs, runner names, step timestamps and uncovered intervals are retained in the companion JSON.

| Workflow / run ID | Job | Runner label | Start UTC | End UTC | Allocated seconds |
|---|---|---|---|---|---:|
| CI/CD / 34163591598 | changes | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:13Z | 7 |
| CI/CD / 34163591598 | docs | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:16Z | 10 |
| CI/CD / 34163591598 | lint | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:15Z | 9 |
| CI/CD / 34163591598 | toml-format-check | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:14Z | 8 |
| CI/CD / 34163591598 | test (blacksmith-6vcpu-macos-latest / py3.13) | `blacksmith-6vcpu-macos-latest` | 21:34:32Z | 21:36:49Z | 137 |
| CI/CD / 34163591598 | build-smoke | `blacksmith-4vcpu-ubuntu-2404` | 21:34:26Z | 21:34:36Z | 10 |
| CI/CD / 34163591598 | typecheck | `blacksmith-4vcpu-ubuntu-2404` | 21:34:26Z | 21:34:35Z | 9 |
| CI/CD / 34163591598 | test (blacksmith-4vcpu-windows-2025 / py3.13) | `blacksmith-4vcpu-windows-2025` | 21:34:48Z | 21:41:47Z | 419 |
| CI/CD / 34163591598 | test (blacksmith-4vcpu-ubuntu-2404 / py3.13) | `blacksmith-4vcpu-ubuntu-2404` | 21:34:27Z | 21:35:55Z | 88 |
| CI/CD / 34163591598 | ci-ok | `blacksmith-4vcpu-ubuntu-2404` | 21:41:58Z | 21:42:02Z | 4 |
| commitlint / 34163591558 | commitlint (humans) | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:17Z | 11 |
| commitlint / 34163591558 | commitlint (dependabot) **(skipped; no runner)** | `blacksmith-4vcpu-ubuntu-2404` | 21:33:56Z | 21:33:55Z | 0 |
| CodeQL / 34163591560 | analyze (python) | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:42Z | 36 |
| lint / 34163591562 | lint-changes | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:12Z | 6 |
| lint / 34163591562 | codespell | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:15Z | 9 |
| lint / 34163591562 | bandit | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:20Z | 14 |
| lint / 34163591562 | editorconfig-check | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:15Z | 9 |
| lint / 34163591562 | actionlint **(skipped; no runner)** | `blacksmith-4vcpu-ubuntu-2404` | 21:34:12Z | 21:34:12Z | 0 |
| lint / 34163591562 | yamllint **(skipped; no runner)** | `blacksmith-4vcpu-ubuntu-2404` | 21:34:12Z | 21:34:12Z | 0 |
| large-file-guard / 34163591577 | reject-files-over-1mb | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:12Z | 6 |
| rebrand-matrix / 34163591589 | r3-windows | `windows-latest` | 21:34:00Z | 21:35:38Z | 98 |
| rebrand-matrix / 34163591589 | r1-r2-r3-posix | `blacksmith-4vcpu-ubuntu-2404` | 21:34:07Z | 21:34:30Z | 23 |
| Claude Code Review / 34163591591 | claude-review | `blacksmith-4vcpu-ubuntu-2404` | 21:34:07Z | 21:34:51Z | 44 |
| Difftree PR Comment / 34163591593 | difftree-pr-comment | `ubuntu-latest` | 21:33:59Z | 21:34:10Z | 11 |
| secret-scan / 34163591604 | trufflehog | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:15Z | 9 |
| Dependency review / 34163591617 | dependency-review | `blacksmith-4vcpu-ubuntu-2404` | 21:34:06Z | 21:34:14Z | 8 |

The skipped `commitlint (dependabot)` record has a raw start one second after its completion timestamp. It has no allocated runner and no steps, so it correctly contributes zero. The other two skipped jobs also contribute zero. Every allocated job has a nonnegative interval, and all of its steps fall within that interval.

## All full-CI test-job steps and uncovered intervals

These are enclosing step durations recomputed from the raw REST timestamps, in seconds. Zero means no whole second elapsed between the recorded timestamps; it does not establish zero work. Step numbers 10–14 are absent from the raw records. No step interval overlaps another.

| Step number | Recorded step | Linux seconds | macOS seconds | Windows seconds |
|---:|---|---:|---:|---:|
| 1 | Set up job | 3 | 3 | 4 |
| 2 | Set up runner | 0 | 0 | 1 |
| 3 | Run actions/checkout@v7 | 1 | 1 | 3 |
| 4 | Install uv | 1 | 1 | 0 |
| 5 | Install bun (pinned for native R3) | 0 | 0 | 2 |
| 6 | Sync dev env | 2 | 2 | 2 |
| 7 | Run edit visibility regressions first | 3 | 10 | 23 |
| 8 | Run tests with coverage | 72 | 117 | 380 |
| 9 | Upload coverage to Codecov | 2 | 0 | 0 |
| 15 | Post Install bun (pinned for native R3) | 0 | 0 | 0 |
| 16 | Post Install uv | 0 | 0 | 0 |
| 17 | Post Run actions/checkout@v7 | 0 | 0 | 1 |
| 18 | Complete runner | 0 | 0 | 1 |
| 19 | Complete job | 0 | 1 | 0 |
| | **All recorded steps** | **84** | **135** | **417** |
| | **Uncovered job intervals** | **4** | **2** | **2** |
| | **Job interval** | **88** | **137** | **419** |

Uncovered intervals are time inside the allocated job but outside recorded steps; their underlying activity is not inferred:

| Platform | Uncovered interval, UTC on 2026-09-07 | Seconds |
|---|---|---:|
| Linux | 21:34:27Z → 21:34:28Z | 1 |
| Linux | 21:35:52Z → 21:35:55Z | 3 |
| macOS | 21:36:47Z → 21:36:49Z | 2 |
| Windows | 21:41:45Z → 21:41:47Z | 2 |

Using matching REST step boundaries gives the complete residual identities:

| Platform | Job minus both pytest steps | Remaining recorded steps plus uncovered intervals |
|---|---|---|
| Linux | `88 - 3 - 72 = 13 s` | `9 + 4 = 13 s` |
| macOS | `137 - 10 - 117 = 10 s` | `8 + 2 = 10 s` |
| Windows | `419 - 23 - 380 = 16 s` | `14 + 2 = 16 s` |

The review instead subtracts pytest's internal full-suite timing from REST job/preflight intervals. Those internal timings are 71.24, 116.58 and 379.59 seconds, whereas their enclosing steps take 72, 117 and 380 seconds. The mixed residuals also reconcile when that measured difference is included:

| Platform | Review-style residual | Other recorded steps + uncovered time + step/internal difference |
|---|---|---|
| Linux test job | `88 - 3 - 71.24 = 13.76 s` | `9 + 4 + 0.76 = 13.76 s` |
| macOS test job | `137 - 10 - 116.58 = 10.42 s` | `8 + 2 + 0.42 = 10.42 s` |
| Windows test job | `419 - 23 - 379.59 = 16.41 s` | `14 + 2 + 0.41 = 16.41 s` |

The Windows residual covers setup (4 s), runner setup (1 s), checkout (3 s), bun setup (2 s), dependency sync (2 s), checkout cleanup (1 s), runner completion (1 s), uncovered intervals (2 s) and the enclosing-step/internal-pytest difference (0.41 s). The 16.41-second residual is sufficient. An exact equality to remaining step durations alone would incorrectly omit the uncovered intervals.

## Conditional published-credit arithmetic

The task supplies the previously published weights: Linux 4 vCPU = 2, Windows 4 vCPU = 4, macOS 6 vCPU = 20 credits per minute. This calculation holds those weights fixed; it does not refresh pricing, inspect account billing, verify actual CPU allocation or apply invoice rounding. Runner labels identify the conditional rows.

| Runner label | Allocated seconds | Assumed credits/minute | Exact modeled credits | Rounded modeled credits | Model share |
|---|---:|---:|---:|---:|---:|
| `blacksmith-4vcpu-ubuntu-2404` | 320 | 2 | 32/3 | 10.67 | 12.7% |
| `blacksmith-6vcpu-macos-latest` | 137 | 20 | 137/3 | 45.67 | 54.2% |
| `blacksmith-4vcpu-windows-2025` | 419 | 4 | 419/15 | 27.93 | 33.1% |
| **Blacksmith total** | **876** | mixed | **1264/15** | **84.27** | **100%** |

Each row is `allocated seconds / 60 × assumed credits per minute`. The remaining `98 + 11 = 109` runner-seconds belong to GitHub-hosted runners and remain excluded. Blacksmith `876 + 109 = 985` reconciles the batch. The published **84.27 modeled credits**, **54.2% macOS share** and **33.1% Windows share** all recompute correctly. This supports the conditional prioritization model, not an actual charge or delivered savings claim.

## Evidence receipt and reproduction

All 634 local arithmetic and source-consistency checks passed. These checks recomputed every job and step interval from the raw saved responses, compared them with derived fields, verified pagination/job identity, and checked platform/workflow/batch sums. No project tests were run. The JSON includes each check, exact fractions, raw-derived comparison results and every job's complete step/gap records.

To reproduce: read the ten `jobs_source` responses below; concatenate their `data[].jobs`; calculate each allocated job's `completed_at - started_at`; group by workflow and runner label; then compare each job interval with the union of its step intervals. Exclude jobs whose `runner_id` is null. For the credit rows, multiply each platform sum by its fixed weight and divide by 60.

| Source artifact, relative to `/private/tmp/template-press-group3-execution` | SHA-256 |
|---|---|
| `p11a-ci-baseline.json` | `914961d9346c844e393756e6764723e5de28f5f3315933bcc9b916af444b851d` |
| `p11a-plan-opus-scoped-v2-report.md` | `3f1bfa3ef280a3de804ba84da95d8d1c0a7fd290cc644d9cd58e3a875c59a47b` |
| `group3-closeout-p11a/docs/superpowers/reviews/2026-09-07-p11a-ci-baseline.md` | `2d69429c50fed43def59c8c4e975286e58aae19eb088f328659e14d3a69284e9` |
| `p11a-raw/runs-20260906-20260907.json` | `97251486b6eeff9dcfbd6cd5448114aa95998dabd7acb69af1e3055d210cb98e` |
| `p11a-raw/p10-ci-34163591598-jobs.json` | `207b64101537a19719bdb5795d6eb673bdab1a1ca2ea16a589320ba83e2ac4e3` |
| `p11a-raw/run-34163591558-jobs.json` | `97859466401f288d4fb752d8e4328710c7d16901252e795865d88897211fe7f0` |
| `p11a-raw/run-34163591560-jobs.json` | `b5ddf551525251b9e253823617626debb60096b01186c178b31c7399c60db797` |
| `p11a-raw/run-34163591562-jobs.json` | `448f07e01c97a4112501a7789d604c7dde1a3340ef462404bee1957753a3cf2e` |
| `p11a-raw/run-34163591577-jobs.json` | `2e498ee3756afccaacaab1bd4d18547e497aa7f4f8b18fd64c2e6b3f71f4301f` |
| `p11a-raw/run-34163591589-jobs.json` | `9ca7114c630bb252f2c9fcdbc7043cde089b8072be5e963015bd6d07cde2fe7b` |
| `p11a-raw/run-34163591591-jobs.json` | `aa30418053443df85072847a9e3cfd62c974d6ec441fea09eb967b36f1a03bd7` |
| `p11a-raw/run-34163591593-jobs.json` | `ad29b45422d9d8359826433e863b2f985353da49e0d4c59daefaeb99b0e4ab37` |
| `p11a-raw/run-34163591604-jobs.json` | `d625e68ad4afbd54ad12ec78bf877dac1bdef8a47f75820309f00ab32b19f694` |
| `p11a-raw/run-34163591617-jobs.json` | `50b91a3f60f62b0862c01d97af72bcc2eeb54cd0d47cd93c54e9216ae622a167` |
| `p10-shipping-linux-tests.log` | `9529cf06d7be8e63fe1eb05fc8dd68f6a8d0ca0fcfb0a1ade7c44b0702b89360` |
| `p10-shipping-macos-tests.log` | `2604590b9b3499a21ac0364e15504a9fc29b0e8678337a216d49cdfcf08d06f4` |
| `p10-shipping-windows-tests.log` | `4b315377ed4ff4fb36ab902e61e640d8d75262803d14420318b3a185a6e410ba` |
| `p11a-cost-reconciliation.json` | `5d08d93dbd160a8f6b1d281ee69d717fc1f339656a93d8a3f0a006f55b7b8263` |

All ten raw job-response hashes, the raw inventory hash and all three test-log hashes match their previously recorded provenance. The baseline JSON hash also matches its published receipt. Summary and review hashes bind the versions read for this reconciliation.
