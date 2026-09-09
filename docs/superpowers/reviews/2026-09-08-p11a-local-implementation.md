# P11A local implementation checkpoint

The first CI implementation slice was committed and locally validated at
`01fba91ee95cb40058d3e555c7cf7f669587a692`, tree
`7fed5bf15f26a8ff29e1d7ea950dbc5b8f3b0aa2`. This is a
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

All eleven reviewed file hashes matched the committed Git blobs and worktree
bytes at that checkpoint. No P11A push, remote dispatch, performance experiment
or merge occurred before the upload approval below.

## Approved upload step

The owner approved Decision Q4 on 2026-09-08 after reviewing the exact public
GitHub destination, generated-file paths, visibility, payload limits and
seven-day retention. The exact step is committed at
`e7d7ea2e9843bcf7328808360ec4ac53edf9c617`, tree
`46615c6fb07ed7ff0d411585acf56b36ba067a7b`, directly above the first slice.
Only `.github/workflows/ci.yml` changed, with seventeen added lines.

Root independently confirmed the inserted step equals the approved proposal
byte for byte, and removing it restores the parent workflow exactly. The
tested and committed workflow SHA-256 is
`36848b9e5af06c124b5e060596f7f55f71a14f1805aba673b6e1fbd770c9f7e2`.

Local macOS controls executed the upstream v7 `findFilesToUpload` function,
bound to upstream commit `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.
Complete, interrupted-preflight and absent-result cases selected exactly the
expected regular files. Unrelated files were excluded; a broad-directory
inverse selected the unwanted files. These controls do not prove native
Windows selection, actual upload, archive contents or expiry.

Actionlint, locked yamllint, the existing native-Bun workflow contract, diff
checks and commit hooks passed. Yamllint retained only the long artifact-name
warning. The unchanged full suite was not repeated for this one-step addition.
The exact receipt is `p11a-q4-local-receipt.json` in the session evidence
directory, SHA-256
`a2a3c0bb7376bac802bb4bdaa1dbf2be09e4a2578a5ed2d3b400152a738f5542`.

The owner also asked whether uploads are temporary. The approved step recurs
on successful and failed runs with no automatic stop date. Seven days is each
archive's retention period. At P11A-T06, before P12, review measured upload
duration, bytes, reliability and information unavailable from ordinary logs.
Preserve comparison results, source/run identifiers and limitations before
the archives expire. Record an explicit ongoing policy at that closeout.
Ending routine successful-run archives while retaining useful failure evidence
is currently a recommendation, not an implemented or approved policy change.

## Finite native harness checkpoint

The disposable diagnostic branch is frozen at
`80e86255263cefdf3e83c28b98cf4c2adc474eb5`, tree
`bcca8b2a3a7b02a57380796b9b22f8d0d7912e53`, above production commit
`e7d7ea2e9843bcf7328808360ec4ac53edf9c617`. Its six-file harness delta must
never merge into production. Production diagnostic helpers, dependencies and
the approved upload step remain unchanged.

Independent review found two harness defects before native dispatch. The
evidence checker accepted contradictory results, and its raw source hashes
rejected legitimate Windows line-ending conversion. The corrected checker
rejects all eight poisoned controls while retaining both valid controls.
Source checks permit only declared CRLF-to-LF conversion; generated diagnostic
evidence retains byte-exact hashes and rejects newline-only mutations.

Final local controls using the actual wrapper passed with child exits
0/0/1/7/1 for serial pass, parallel pass, assertion failure, early exit and
worker loss. These are macOS/Bash observations. Independent re-review returned
SPEC PASS / QUALITY APPROVE for this finite payload. The source-bound receipt
is `p11a-stage-a-native-payload-review-v2.md`, SHA-256
`f39298fcdccfc314b282f36ee9f27f757a355fe1092a376c084d6af637aa6978`.

The first native control is one Windows job with serial and parallel passing
invocations. Its nominal job limit is eight minutes. Actual Windows outcomes,
downloaded archive contents and expiry must pass inspection before the later
finite cases. Linux follows the finite Windows controls. Hangs, timeouts,
cancellation, production gates and performance remain separate validations.

## Remaining gates

The initial automatic rejection of the upload edit was resolved by the owner's
specific Q4 approval. The exact production step is now locally committed;
native upload and retention validation remain pending.

Milestone 3 still requires native Windows/Linux diagnostic and timeout proof,
actual GitHub job-condition and cancellation controls, scanner outcome checks,
and artifact-retention validation. Accepted P11 must be integrated before the
production timeout-margin check, performance experiments and final delivery.
The separate P11 diagnostic was approved as Q3.A. After automatic review
required literal destination/payload authorization, the owner explicitly
authorized diagnostic commit `493a0fc3cc6fe7e8f74a483b35015018b576c6af` on
`ci/p11-removal-isolated` in public `smorinlabs/template-press`. That cleared
the tool gate, and the bounded Windows proof passed in
[run 34286961815](https://github.com/smorinlabs/template-press/actions/runs/34286961815).
The small test identifier succeeded; the oversized identifier triggered the
Windows environment-variable limit in pytest's setup helper. Root verified
the downloaded JSON, archive digest and seven-day expiry. This does not
establish why the earlier Windows job lost its logs or stalled.

The corrected 44-test receipt-family diagnostic is prepared at
`d8b9372debd31f0e95ae511ec0dfe29b117c4f73`. Automatic approval review rejected
its push because the literal authorization named only the first diagnostic
commit. Broader authorization for the remaining P11 branch updates has been
requested; the rejected action has not been retried. P11 still owns that
isolated corrected-family gate before its full CI and merge.

Milestone 4 will measure an optimization before claiming a benefit. Milestone 5
will complete delivery and closeout. P12 remains paused behind P11 and P11A.
