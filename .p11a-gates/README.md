# Disposable production-gate proof

This branch is a local diagnostic payload for independent review. Never merge it into production. Do not push or dispatch it before root reviews the frozen commit. Its base is `e7d7ea2e9843bcf7328808360ec4ac53edf9c617`; it changes no production workflow, tool, dependency, product test or required-check setting.

The replacement `rebrand-matrix.yml` runs only through `workflow_dispatch`, on `blacksmith-4vcpu-ubuntu-2404` with Bash. It has 15 named jobs, with 11 ordinary jobs and four cancellation helpers that are skipped outside their one case. No artifacts, secret scanner, live PR, merge queue, full product suite or performance measurement are included. Git, Bash and system `python3` are required by the checkout/source and API helpers; no package installation runs in these jobs.

## Exact production bindings and substitutions

`ci-ok`, `actionlint` and `yamllint` retain their production names, `needs`, `if`, runner, permissions and literal validator bodies. Every expensive lint step retains its exact production selection condition. The three heavy main jobs retain their exact code-selector conditions. `freeze.json` binds production CI/lint, the existing gate-test module, package/lock inputs and the payload. Only declared text source permits CRLF-to-LF checkout normalization. The final commit and external receipt bind the manifest itself.

These are the complete intended substitutions:

| Surface | Harness substitution |
| --- | --- |
| Workflow entry point | Replace the disposable branch's acceptance workflow with dispatch inputs `case` and `event_model`; no automatic triggers or workflow-wide concurrency. |
| Detector bodies | Emit controlled real job outputs instead of examining a Git diff. Omit outputs, emit uppercase values, fail, or wait only for the corresponding selected case. `changes` first checks out the selected commit and verifies source. |
| Main heavy/always-required bodies | Replace checks/builds/docs/tests with tiny success/failure Bash witnesses. The matrix test is one `test (inert dependency)` job. Its ID remains `test`. |
| Selected-but-skipped stimulus | Add `lint-changes` to the synthetic `test` prerequisites; skip that detector only for `selected-skipped`. The production test selector expression is unchanged. This tests a real skipped dependency result, not a fake status string. |
| Selected lint work | Replace each checkout/setup/tool body with an inert witness while retaining step order and every `if` condition. Selected tool witnesses exit 1 only for `selected-tool-failure`; `test` also exits 1 in that case. |
| Main gate event input | Replace only `EVENT_NAME` with the explicit event model. A following always-run log step records the actual event, modeled event and real `needs` values. Every actual run is still `workflow_dispatch`. |
| Bounds | Main gate/lint/ordinary witness jobs and steps have one-minute limits. Detector and arming jobs have two-minute limits. These are safety bounds, not runtime estimates or substitutes for cancellation. |
| Cancellation | Add two job concurrency groups, an arming job, two successors and a conclusion witness, as described below. Only the arming job adds `actions: read`; it also needs `contents: read` for checkout. No API mutation permission is requested. |

## Proposed minimum remote set

One case per invocation, initially with `event_model=pull_request`. First run `all-pass` and inspect its source, job/step outcomes and durations before expanding. The following is the minimum proposed set, not a record of completed runs.

| Case | Required detector/dependency behavior | `ci-ok` | `actionlint` / `yamllint` |
| --- | --- | --- | --- |
| `all-pass` | Both detectors emit lowercase true; selected witnesses succeed | success | success; selected tool steps execute |
| `valid-false` | Lowercase false; all heavy jobs skipped | success | success; every selected setup/tool step skipped |
| `missing-output` | Both detectors succeed while omitting outputs | failure | failure before selected tools |
| `uppercase-false` | Both detectors succeed and emit uppercase FALSE | failure | failure before selected tools |
| `selected-skipped` | Main detector emits true; lint detector and synthetic test are actually skipped | failure | failure because detection was skipped |
| `detector-failure` | Both detector jobs fail after writing valid outputs | failure | failure before selected tools |
| `selected-tool-failure` | Test and both selected tool witnesses execute and exit 1 | failure | failure in their selected tool steps |
| `cancel-detectors` | Both actual detector wait jobs become cancelled through job concurrency | failure | failure; cancellation conclusion witness succeeds |

All negative cases must remain non-successful workflows. A successful witness or checker must not hide the failed/cancelled dependency or gate. Independently inspect source-freeze success, resolved source/run/attempt IDs, detector conclusions/outputs, heavy job conclusions and lint step presence/absence. A checkout/setup failure is not the intended negative control. Ordinary job logs and the Actions job/step metadata provide the receipt; there is no archive upload.

Local tests also cover both other event models, all eight valid success/skipped heavy combinations for a false PR model, missing dependencies, every unsafe dependency result and complete selector equivalence-class combinations for both lint contexts. Actual PR path detection, actual push/merge-group execution and scanner behavior remain unproven.

## Genuine cancellation control

Both detectors enter the named `Emit controlled detector outputs` step and wait for 90 seconds under different groups containing the run ID, attempt and target name. The fallback fails; reaching it proves that cancellation did not arrive.

The independent arming job reads the current run-attempt jobs endpoint for at most 30 seconds, with a five-second request timeout and at least 20 seconds between requests. It emits `armed=true` only after observing both named jobs and both wait steps actually `in_progress`. Successor jobs then acquire the matching groups with `cancel-in-progress: true`. No whole-workflow concurrency or cancellation endpoint is used.

The final `cancellation-proof` job requires both detector results to be exactly `cancelled`, both successors successful, and all three production gates failed. Exit 130, a detector failure/timeout, a skipped job, or a gate that accidentally passes fails this witness. API errors, excessive queue/setup delay or unsupported provider behavior leave cancellation unproven; do not substitute simulated results or extend scope to cancel the workflow.

## Local validation

Run the existing tests and harness boundaries from the repository root:

```sh
uv run --no-sync pytest -q -c .p11a-gates/pytest.ini --rootdir=. --confcutdir=. .p11a-gates/test_payload.py tests/meta/test_ci_gates.py
```

The harness imports `tests/meta/test_ci_gates.py` and executes its production-body evaluator. It does not create a second gate evaluator. Sixteen inverse cases also load the original pre-fix predicates from `8a8de788d857e2084c506a455a7b7984802a1718`, show their unsafe acceptance/skip, and require rejection by the repaired production predicates. Local cancellation metadata fixtures validate the arming/conclusion checks; they do not claim provider cancellation.

The saved P11A duration profile is reused for scope selection. Historical `ci-ok` samples have a four-second median, while this new diagnostic topology has no successful native sample and is classified unmeasured. Focused local results are recorded separately in the external receipt. No full product check or remote verification is claimed.
