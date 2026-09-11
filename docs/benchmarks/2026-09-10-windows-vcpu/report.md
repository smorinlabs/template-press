**Template Press Windows runner comparison — 10 September 2026**

Keep `blacksmith-4vcpu-windows-2025` for the current CI configuration.
Switching to `blacksmith-2vcpu-windows-2025` increased the median Windows
job duration by 66.4%, from 14m 34s to 24m 14s. Estimated Windows runner
cost fell by 16.8%, approximately $0.04 per job at published rates.
Every 2-vCPU sample exceeded CI's existing 15-minute full-suite timeout.
The production CI configuration was not changed.

The [benchmark run](https://github.com/smorinlabs/template-press/actions/runs/34541041291)
ran three fresh jobs per runner label. All six succeeded under the
experiment's longer timeout. Each ran the same 2,233 test cases:
2,123 passed and 110 were skipped. Line coverage was 92% in every sample.

The following values are medians of three jobs per label. The full-suite
duration is the GitHub Actions step named `Run tests with coverage`.
The shared-workload duration sums checkout, uv installation, Bun installation,
dependency sync, the initial regression tests, and the full suite.
Total job duration also includes runner setup, benchmark metadata collection,
artifact uploads, and cleanup. Queue time is excluded from these durations.

| Metric | 4 vCPUs | 2 vCPUs | Change with 2 vCPUs |
| --- | ---: | ---: | ---: |
| Full test suite | 13m 40s | 22m 59s | +9m 19s / +68.2% |
| Shared CI workload | 14m 17s | 23m 53s | +9m 36s / +67.2% |
| Total benchmark job | 14m 34s | 24m 14s | +9m 40s / +66.4% |
| Estimated Windows cost per benchmark job | $0.233 | $0.194 | -16.8% |
| Full suites within the current 15-minute limit | 3 of 3 | 0 of 3 | Requires a timeout change |

Individual results show the observed variation. Every row has a successful
full-suite result under the experiment's 30-minute step timeout.

| Runner size | Sample | Initial regression tests | Full suite | Total job | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| 4 vCPUs | 1 | 26s | 12m 38s | 13m 26s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525771) |
| 4 vCPUs | 2 | 28s | 13m 40s | 14m 34s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525605) |
| 4 vCPUs | 3 | 26s | 14m 17s | 15m 19s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525749) |
| 2 vCPUs | 1 | 49s | 21m 51s | 23m 35s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525686) |
| 2 vCPUs | 2 | 42s | 22m 59s | 24m 14s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525622) |
| 2 vCPUs | 3 | 36s | 23m 45s | 24m 55s | [Job](https://github.com/smorinlabs/template-press/actions/runs/34541041291/job/103083525453) |

The cost model uses $0.008 per minute for 2-vCPU Windows and $0.016 per
minute for 4-vCPU Windows. It applies these rates to total job seconds
divided by 60. It excludes billing rounding, free credits, and account
discounts. The reduction concerns the Windows job; other CI jobs retain
their existing costs. Applying the same model to the shared CI workload
gives a similar 16.4% reduction.
[Blacksmith pricing](https://www.blacksmith.sh/pricing) and
[runner pricing ratios](https://docs.blacksmith.sh/blacksmith-runners/overview)
provide the published-rate basis.

All jobs checked out the unmodified main-branch source at
[`b07d60f290af821806597e9f12523119aadd8493`](https://github.com/smorinlabs/template-press/commit/b07d60f290af821806597e9f12523119aadd8493).
The benchmark workflow is on the separate branch
`ci/windows-vcpu-benchmark-20260910`, at
[`287a5353f181df72800f5a418f0c96aeb17b2bbd`](https://github.com/smorinlabs/template-press/commit/287a5353f181df72800f5a418f0c96aeb17b2bbd).
That commit adds the experimental workflow and registers the 2-vCPU label
with actionlint, the workflow syntax checker. It leaves `.github/workflows/ci.yml`
unchanged. No pull request was opened and nothing was merged.

The setup action versions and all three workload commands match production
CI exactly. In particular, `pytest -n auto` selects workers from the available
CPUs: the recorded worker counts were four and two, respectively. The
benchmark changes the full-suite timeout from 15 to 30 minutes and the job
timeout from 25 to 40 minutes so a slowdown can be measured to completion.
The initial regression step retains its production timeout of five minutes.

Verification established the following controls:

- Actual CPU allocations matched all six requested sizes. No sample received
  an automatic CPU upgrade. The smaller label also reduced nominal RAM from
  14 GB to 7 GB, as specified by Blacksmith.
- All jobs used Windows build `26100`, image version `20250901215242`,
  Python `3.13.7`, uv `0.12.13`, Bun `1.3.14`, and the same Git version.
- Every checked-out dependency lockfile had SHA-256
  `E408479DCEBA2D22498B04952C2B264EE9D1037FBD8936DF694B5E1CDC1EBA7A`.
- Every job restored the same Bun cache key. Dependency setup was included
  in the shared-workload and total-job comparisons.
- The external fixture repository, `smorinlabs/py-launch-blueprint`, reported
  HEAD `c1216c6089f768ae0a3f3a465460d2d384f5fa44` before and after each job.
  These are observed ref checks; the existing live tests still perform their
  normal network clones.
- JUnit test identities and outcome counts matched across all six samples.
  The SHA-256 of the sorted test-identity list was
  `38c16173d530496a9e99a147206224fec058b6491f2caca664fff0168854214c`.

Blacksmith assigned an Intel Core i9-14900K host CPU model to 4-vCPU sample 3.
The other five samples reported AMD EPYC 4565P. The main comparison therefore
includes host variation within the offered runner labels. Restricting the
4-vCPU baseline to its two AMD samples gives a 13m 09s full-suite median;
the three AMD 2-vCPU samples still have a 22m 59s median, approximately
75% slower. The direction of the result is unchanged.

This is a three-sample comparison for one source revision and one time
window. It does not estimate long-term tail latency. Windows was already
the slowest test platform in the latest main-branch CI run: its suite took
13m 37s, versus 3m on macOS and 2m 12s on Linux. A Windows slowdown is
therefore likely to extend overall CI completion time.
[Main-branch run](https://github.com/smorinlabs/template-press/actions/runs/34534979723)

The experiment was validated locally with `just setup`, workflow syntax
validation, direct comparison against the production workload commands,
and `PYTEST_ADDOPTS='-n auto' just check`. The local check completed with
2,193 passed and 24 skipped tests, followed by passing lint and type checks.
Commit and push hooks also passed. These local results are preparation
checks; the six Windows jobs above provide the runner comparison.

The owner chose to keep `blacksmith-4vcpu-windows-2025` after reviewing
these results. No permanent CI change is needed. Choosing 2 vCPUs would
trade roughly ten extra minutes per Windows job for a modest cost reduction
and would require revisiting the CI timeouts.

The local evidence packet contains [computed results](summary.json),
[GitHub job and step timings](jobs.json), and [the benchmark protocol](protocol.json).
The [complete evidence archive](../../assets/benchmarks/2026-09-10-windows-vcpu-evidence.zip)
includes the analysis script, both workflow definitions, all six job logs,
and all six artifacts with runtime metadata, test journals, JUnit reports,
and coverage XML. [File hashes](SHA256SUMS) identify the saved packet contents.
