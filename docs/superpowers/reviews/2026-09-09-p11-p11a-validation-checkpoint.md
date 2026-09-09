# P11 and P11A validation checkpoint

P10 is merged. P11 remains open because final review reproduced additional
safety defects after its full CI passed. P11A Milestone 3 has native Windows
fixture evidence and completed external source reviews, with review corrections
and further acceptance controls still open. This checkpoint does not close
P11, P11A or their remaining tasks.

## Group 3B and Group 3C

P10 PR #122 is merged. Its delivered clean command includes individual-file
selection. No P10 delivery work remains.

P11 PR #123, source `3242c2d0112926f54facaf5c3a12b07f0975b149`, passed the
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
Corrections remain within existing directory-removal safety mechanisms. The
combined correction must pass independent review, isolated Windows validation
and full CI before merge. Earlier green results do not validate these new edits.

Repeated filesystem identity work is captured as `P12-T-defer-11` for later
value evaluation. Two small fixtures measured 7 and 595 input stat calls with
2/3 and 27/22 selected-member/input counts respectively. These measurements do
not establish large-repository latency or savings. No caching change is promised.

## P11A Phase 2, Milestone 3

Production source is `e7d7ea2e9843bcf7328808360ec4ac53edf9c617`. Its full local
pipeline, focused controls and committed self-press acceptance passed as recorded
in the [local checkpoint](2026-09-08-p11a-local-implementation.md).

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
| Claude Code Fable | `claude-fable-5-1`, high effort, 16 turns; no Opus fallback | SPEC PASS / QUALITY CHANGES REQUIRED. Interrupt handling and test-evidence claims are being reproduced. |

Two earlier full-source Muse attempts timed out and supply no verdict. The split
requests jointly cover the implementation files. All external reviews are static;
none substitutes for native execution or artifact inspection. Actual Muse model
step counts are not established by file-read counts.

The disposable gate harness at `9c8412f016c7e7876dbd6dd70a08c3ec5887d8b1` keeps
the three production validators and selection conditions exact while substituting
small dependency witnesses. Its 1,413 local checks, source freeze and independent
root review passed. The first
[all-pass native control](https://github.com/smorinlabs/template-press/actions/runs/34303945077)
is running. Missing/invalid selectors, selected skips, detector/tool failures and
genuine job cancellation remain separate controls. These are modeled events;
actual documentation-only PR and secret-scan controls remain open.

## Remaining hierarchy and upload policy

Milestone 3 must resolve confirmed review findings, finish native Linux and
body/collection/session/step/job timeout evidence, validate remote gates and
scanner outcomes, and integrate accepted P11 for production timing margins and
native acceptance. Diagnostic harnesses must never be merged.

Milestone 4 then compares a measured optimization on the accepted source using
the approved experiment budget and equivalent coverage. Milestone 5 delivers the
reviewed result and records remaining costs. `P11A-T05` and `P11A-T06` remain open.
P12 implementation and value decisions remain paused until this closeout.

The approved Q4 policy still uploads diagnostics on successful and failed runs.
Seven days expires each archive; it does not stop collection. At P11A-T06, review
actual duration, bytes, reliability and value before choosing the ongoing policy.
Ending routine success archives after the comparisons is a recommendation only.

Full local evidence includes `p11a-windows-finite-root-acceptance.json`,
`p11a-gate-root-clearance.json`, the three completed external-review receipts,
`p11-history-inputs-red-receipt.json` and `p11-identity-loop-measurement.json` in
the session evidence directory. Public run links above provide provider records.
