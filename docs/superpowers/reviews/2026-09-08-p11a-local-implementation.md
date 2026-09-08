# P11A local implementation checkpoint

The first CI implementation slice is committed and locally validated at
`01fba91ee95cb40058d3e555c7cf7f669587a692`, tree
`7fed5bf15f26a8ff29e1d7ea950dbc5b8f3b0aa2`. The worktree is clean. This is a
local checkpoint for Milestone 3, not completion of P11A or a delivered speedup.

## Implemented scope

The eleven changed files add an opt-in pytest progress journal and a small
standard-library runner. Both CI test invocations retain their original
selection and coverage, add timing and separate JUnit output, and request the
existing pytest fault handler after 120 seconds in a test. Preflight, full-test
and enclosing-job limits are 5, 15 and 25 minutes respectively.

The journal records phase, worker, process, last test and explicit no-test-started
state. Test names use a bounded prefix with the complete name's hash and length.
Whole-record rotation preserves readable JSONL evidence. Output files and
provider console output have separate bounds, with recent failure output retained.

The main merge check, `ci-ok`, and required lint checks, `actionlint` and
`yamllint`, now reject missing or malformed selectors and unsuccessful
dependencies. Required lint checks validate first and skip expensive work for
a valid documentation-only selection. The `trufflehog` secret-scanning check
now declares the merge-group event with its existing full-history scan behavior.
Required context names, native platform coverage, dependencies and runner plans
remain within the reviewed contract.

The self-press rules remove exactly the new P11A project-history file and retain
`projects/.gitkeep`. Its existing regression expects thirteen history removals.
The native-Bun workflow assertion now reads command semantics across whitespace.
Generated `ci-results/` files are ignored by Git.

## Evidence and review

| Check | Recorded result |
|---|---|
| Original required-check guards | 51 failing negative cases and 22 passing controls. |
| Final focused controls | 91 passes, plus one separately passing parent-temp isolation regression added afterward. |
| Full canonical local pipeline | 2,125 passes and 24 skips in the test stage; all later checks passed. Eight workers changed parallelism only; default slow/live exclusions remained. |
| Independent internal Epicero implementation review | SPEC PASS for implemented scope / QUALITY APPROVE. Independent positive/inverse rotation, console-bound and exit-0/7 probes passed. |
| Committed R1a/R1b/R2/R3 acceptance | Four passes and six deselections in 49.67 seconds; commit and clean status unchanged. |
| Other validation | Workflow linting, Ruff, formatting, helper type checking and commit hooks passed. |

The original serial full-check attempt was interrupted after 287 passes and
322.39 seconds. It is not a pass. The replacement full test stage took 628.43
seconds with eight workers. These local host observations are not a controlled
CI performance comparison.

The final test-only isolation correction removes inherited `PYTEST_ADDOPTS` from
nested diagnostic probes, preventing an outer `--basetemp` from deleting parent
temporary data. A disposable sentinel failed before the correction and survived
afterward. Production pytest option handling is unchanged. That new slow control
passed separately after its addition during the default-selection full run.

The session evidence directory retains these complete receipts:

- `p11a-ci-final-receipt.json`, SHA-256
  `8f53d6f3695b74e0648a76528fb7f1a2daefdae460ea3285004d5ddfe98e0775`.
- `p11a-m3-internal-review-v1.md`, reviewing composite source v2, SHA-256
  `baa5990aef7d1e57684dc271eb69bb681e4c8e81325b52be1cc64d1d96e00f9e`.
- `p11a-committed-matrix-receipt.json`, binding the four acceptance results to
  the commit and tree above.

All eleven reviewed file hashes match the committed Git blobs and worktree bytes.
No push, remote dispatch, performance experiment or merge occurred.

## Remaining gates

The diagnostic-upload workflow step remains absent. Automatic approval review
rejected the edit because it did not accept authorization for the exact future
GitHub artifact destination and payload. The concrete proposal identifies
generated pytest reports, bounded logs/progress and allowlisted runtime metadata
in `smorinlabs/template-press`, retained for seven days. Root requested approval;
the response remains pending. No alternate tool wrote the rejected step.

Milestone 3 still requires native Windows/Linux diagnostic and timeout proof,
actual GitHub job-condition and cancellation controls, scanner outcome checks,
and artifact-retention validation. Accepted P11 must be integrated before the
production timeout-margin check, performance experiments and final delivery.
The separate P11 diagnostic approval is also pending.

Milestone 4 will measure an optimization before claiming a benefit. Milestone 5
will complete delivery and closeout. P12 remains paused behind P11 and P11A.
