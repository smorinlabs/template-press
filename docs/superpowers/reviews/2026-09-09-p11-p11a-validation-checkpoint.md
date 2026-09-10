# P11 and P11A validation checkpoint

P10 and P11 are merged. P11's final review corrections passed independent review,
isolated Windows validation, full CI and native acceptance before PR 123 merged.
P11A Milestone 3 has corrected local implementation, four native Windows finite
controls and eight native gate controls. Scanner and timeout publications await
exact-payload approval. P11A-T05 and P11A-T06 remain open.

## Group 3B and Group 3C

P10 PR #122 is merged. Its delivered clean command includes individual-file
selection. No P10 delivery work remains.

Earlier P11 source `3242c2d0112926f54facaf5c3a12b07f0975b149` passed the
[isolated Windows receipt-family control](https://github.com/smorinlabs/template-press/actions/runs/34301255305)
with 42 passes and two existing POSIX-only skips. Its
[full CI](https://github.com/smorinlabs/template-press/actions/runs/34301561290)
then passed Linux, macOS and Windows plus native acceptance. Windows had
1,982 passes and 108 skips; its allocated job interval was 555 seconds.

A fresh pre-merge review found active Git configuration includes could be
removed while a success receipt was written. Two further reproductions found
changed index blobs/modes at recorded absent paths could pass and historical
verification could bypass protection for restored Git inputs. An independent
review also caught an index stat-cache refresh before a hardlink refusal.
The corrections preserve the existing directory-removal safety mechanisms.
Corrected source `b2737a0cf77bd300a4a66d7fac7c52b1b837ca9d` passed independent
SPEC PASS / QUALITY PASS, local `just check` with 2,095 passes and 24 skips,
and all four committed acceptance cases. The final
[isolated Windows safety run](https://github.com/smorinlabs/template-press/actions/runs/34306959880)
passed all 50 cases with coverage before shipping publication.

The corrected [full CI](https://github.com/smorinlabs/template-press/actions/runs/34307256114)
passed 2,064/59 cases on Linux, 2,099/24 on macOS and 2,015/108 on Windows,
where each pair means passed/skipped. The separate
[native acceptance](https://github.com/smorinlabs/template-press/actions/runs/34307256146)
passed four POSIX cases and one Windows case. All eight required contexts were
satisfied; `actionlint` and `yamllint` validly skipped. All seven review threads
were resolved.

[PR 123](https://github.com/smorinlabs/template-press/pull/123) merged normally
at 03:45:20 UTC on September 9, September 8 Pacific time, as
`6079a22b3fb3069b965ee1061765bc67a95349b4`. Its tree equals reviewed source
`b2737a0c`. The optional Codex review completed five seconds after merge with no
additional findings observed. No disposable diagnostic workflow was merged.

Repeated filesystem identity work is captured as `P12-T-defer-11` for later
value evaluation. Two small fixtures measured 7 and 595 input stat calls with
2/3 and 27/22 selected-member/input counts respectively. These measurements do
not establish large-repository latency or savings. No caching change is promised.

## P11A Phase 2, Milestone 3

Production candidate `845eedcaaf2b6009b06bb848d05022807b15ee1c` integrates
accepted P11 with the review correction at
`5cd95f34c78e807f2c735ecd324fa0423ea75c78`. All 144 focused integration controls
passed. The combined local `just check` passed with 2,175 tests and 24 skips;
committed R1/R2/R3 acceptance passed four cases with six deselections. All eight
P11 correction paths and all nineteen P11A paths remain byte-equal to their
accepted inputs. No disposable harness was imported. Normal all-platform
provider checks for this combined candidate remain pending. The earlier
implementation and acceptance are recorded in the
[local checkpoint](2026-09-08-p11a-local-implementation.md).

The owner approved continued publication and bounded validation after the
initial diagnostic-branch push rejection. The unchanged finite harness at
`80e86255263cefdf3e83c28b98cf4c2adc474eb5` produced these native Windows results.
Every archive was downloaded and independently inspected against source/run IDs,
provider digest and expiry, exact selected files, runtime exits and journal/JUnit
content. Artifact expiry was seven days minus one second at provider timestamp
resolution; future deletion has not been observed.

| Control | Observed child exit | Allocated job seconds | ZIP bytes | Run |
|---|---|---|---|---|
| Serial and parallel pass | 0 / 0 | 23 | 6,647 | [34301263193](https://github.com/smorinlabs/template-press/actions/runs/34301263193) |
| Assertion failure | 1 | 25 | 3,129 | [34302277973](https://github.com/smorinlabs/template-press/actions/runs/34302277973) |
| Early exit before tests | 7 | 36 | 1,861 | [34302598215](https://github.com/smorinlabs/template-press/actions/runs/34302598215) |
| Abrupt worker loss | 1 | 25 | 4,721 | [34302839473](https://github.com/smorinlabs/template-press/actions/runs/34302839473) |

The four jobs used 109 allocated seconds and 16,358 compressed bytes. Upload
steps took one or two seconds at whole-second provider resolution. Allocated
time excludes queue delay and is not billed time. Expected child failures are
asserted by successful control steps, so these jobs do not prove provider-level
failed-step or timeout upload behavior. Small archives do not exercise rotation
caps or measure isolated instrumentation overhead.

The independent external source reviews are complete:

| Reviewer | Actual execution | Source verdict and consequence |
|---|---|---|
| Muse diagnostics | `muse-spark-1.3`, `xhigh`; Ultra requested with a 100-step maximum | SPEC PASS / QUALITY APPROVE for this section. |
| Muse gates and integration | Same model/effort and maximum | SPEC PASS / QUALITY APPROVE for this section. |
| Claude Code Fable | `claude-fable-5-1`, high effort, 16 turns; no Opus fallback | SPEC PASS / QUALITY CHANGES REQUIRED on the earlier source. Confirmed findings are corrected at `5cd95f3`. |

Two earlier full-source Muse attempts timed out and supply no verdict. The split
requests jointly cover the implementation files. All external reviews are static;
none substitutes for native execution or artifact inspection. Actual Muse model
step counts are not established by file-read counts.

Real POSIX interruption reproduced output loss when the wrapper closed its pipe
before the child finished. The correction keeps draining after interruption and
retains the child's exit. Stack assertions now require an actual fixture frame;
removing those frames makes the tests fail. The claimed temporary-directory
isolation weakness was refuted by removing the existing isolation safeguard and
observing the existing regression fail. A latent post-unconfigure policy change
was declined because no current call path reproduced it. The narrow correction
passed independent local review; native interruption remains an explicit gate.

The disposable gate harness at `9c8412f016c7e7876dbd6dd70a08c3ec5887d8b1` keeps
the three production validators and selection conditions exact while substituting
small dependency witnesses. Its 1,413 local checks, source freeze and independent
root review passed. All eight native controls passed their intended assertions:

| Control | Actual workflow result | Job seconds | Run |
|---|---|---:|---|
| All selected work succeeds | success | 48 | [34303945077](https://github.com/smorinlabs/template-press/actions/runs/34303945077) |
| Valid false selectors | success | 33 | [34304586870](https://github.com/smorinlabs/template-press/actions/runs/34304586870) |
| Missing selector output | failure | 35 | [34305036092](https://github.com/smorinlabs/template-press/actions/runs/34305036092) |
| Invalid uppercase selector | failure | 34 | [34305156417](https://github.com/smorinlabs/template-press/actions/runs/34305156417) |
| Selected job unexpectedly skipped | failure | 37 | [34305277598](https://github.com/smorinlabs/template-press/actions/runs/34305277598) |
| Detector failure | failure | 34 | [34305561242](https://github.com/smorinlabs/template-press/actions/runs/34305561242) |
| Selected tool failure | failure | 47 | [34305707713](https://github.com/smorinlabs/template-press/actions/runs/34305707713) |
| Actual detector-job cancellation | cancelled | 84 | [34305971128](https://github.com/smorinlabs/template-press/actions/runs/34305971128) |

The 75 allocated jobs total 352 job seconds; summed workflow intervals total
402 seconds. Both detector wait steps were actually cancelled before their
fallback, and all three production gates rejected their results. Every actual
event was `workflow_dispatch` with a modeled PR event and documented inert
dependencies. Real PR path detection and live merge-queue execution are outside
this proof. The approved plan permits a bounded modeled merge-group scanner
control without changing owner settings.

The scanner payload `b6f337da9aed01fe3d0c77be5233e21c2a5d49d4` uses an actual
two-parent commit, full checkout history and preserved production scan inputs.
Its passing and intentional invalid-option controls retain the `trufflehog`
context. Independent source review and 11 Git plus three metadata controls
passed. Native admission still requires the actual scanner outcome and image
digest, image ID and CLI version.

The combined finite/timeout payload
`9bb9abd15e78866f4b26cf350f4cc2aacfb5a69f` preserves the reviewed finite verifier
and exact Q4 upload. Its five stall cases cover serial and parallel bodies,
collection, session setup and a separate enclosing-job timeout. Independent
review passed, including one committed parallel-body signal control and 12
additional evidence controls. Local signals do not establish provider timeouts.

Automatic approval review rejected the scanner push because it required the
exact new public commit and branch to be authorized. The combined exact-payload
request covers both frozen payloads. Neither was pushed or dispatched; both
remain held pending the user's answer. Outgoing secret and workflow checks pass.

## Remaining hierarchy and upload policy

Milestone 3 must finish corrected-source Linux finite controls and native
Windows/POSIX timeout evidence, validate both scanner outcomes, and validate the
combined source's production timing margins and native provider acceptance.
The corrected P11 Windows run measured 15 seconds from job start to preflight.
With the full proposed 5/15/2-minute preflight/test/upload budgets, the 25-minute
job leaves a 165-second planning margin. Final P11A timing and native interruption
still need validation; this is not an artifact-delivery guarantee. Diagnostic
harnesses must never be merged.

Milestone 4 assesses a measured optimization on the accepted source using the
approved experiment budget and equivalent coverage. Current isolated timing
does not justify changing scheduling; fixture/press/verify phase attribution
is needed before a helper experiment. No benchmark has started. An
evidence-based decision to adopt no optimization is permitted by the plan.
Milestone 5 delivers the reviewed result and records remaining costs.
`P11A-T05` and `P11A-T06` remain open.
P12 implementation and value decisions remain paused until this closeout.

The approved Q4 policy specifies diagnostics on successful and failed runs;
production delivery remains pending. Seven days expires each archive and does
not stop collection. At P11A-T06, review
actual duration, bytes, reliability and value before choosing the ongoing policy.
Ending routine success archives after the comparisons is a recommendation only.

Full local evidence includes `p11-pr123-final-delivery-receipt.json`,
`p11a-windows-finite-root-acceptance.json`,
`p11a-gate-native-9c8412f/eight-case-receipt.json`, the three completed external
review receipts, `p11a-interrupt-correction-committed-receipt.json`,
`p11a-stage-b-root-clearance.json`, `p11a-scanner-root-clearance.json`,
`p11a-corrected-p11-production-margin-planning.json` and
`p11a-m4-candidate-assessment-final-evidence.json` in the session evidence
directory. Combined local validation is retained under `p11a-p11-integration/`.
Public run links above provide provider records.
