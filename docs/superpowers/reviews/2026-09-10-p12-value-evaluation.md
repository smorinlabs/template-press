# P12 follow-ups: validity, value and requirements review

**Final owner dispositions (2026-09-10):** the earlier "Solve all four" decision
approved P12-T-defer-2, P12-T-defer-4, P12-T-defer-5 and P12-T-defer-7.
Those corrections merged in
[PR #125](https://github.com/smorinlabs/template-press/pull/125) at
`9b265813a4ce36da6ae3e170e914949b480a4eab`.
The owner then instructed: "Yes close the 6 recommended to close and document the pass on those".
P12-T-defer-1, P12-T-defer-3, P12-T-defer-8, P12-T-defer-9, P12-T-defer-10 and
P12-T-defer-11 are closed without implementation. Their accepted limitations
and conditions for reopening are recorded in
[P12's closed follow-ups](../../../projects/P12-origin-guard-and-diagnostics.md#closed-follow-ups).
P12 is complete; these closures do not claim the limitations were fixed.

## Historical evaluation

The review below preserves the evidence and recommendations at its evaluation
snapshot. Its proposed work and review status describe that earlier assessment.
The owner decisions above and the project record give the current disposition.

**Recommendation at evaluation time: implement four narrowly scoped corrections
and close six follow-ups without implementation.** At that point, these were
recommendations, not approved dispositions, and all ten original open task entries
remained open. No P12 product change was made during the evaluation itself.

P12 is the origin-guard, diagnostics, warnings and documentation project. Its
base implementation shipped in PRs [#109](https://github.com/smorinlabs/template-press/pull/109)
and [#111](https://github.com/smorinlabs/template-press/pull/111).
`P12-T-defer-6`, receipt-bound acceptance of an origin mismatch during verification,
is already complete and is not one of the ten remaining items.

The assessment uses merged source
`7ac8c1744485081d973ac6b910f13de3fb459d83`, tree
`097a7bf234ef9072309891c428911ac16ca57c7c`. P09, P10, P11 and P11A are merged;
P11A's [main CI run](https://github.com/smorinlabs/template-press/actions/runs/34429509534)
also passed. Those deliveries do not establish a newer package publication or
a fresh downstream rebrand. This reconciliation and all ten follow-up evaluations
are limited to Template Press. Historical downstream feedback work is separate
and is not a dependency of P12.

The owner asked for a high value threshold: distinguish actual bugs from
optional improvements, consider encounter likelihood, and reject changes that
quietly create new requirements. A reproducible bug clears a lower threshold,
but advisory omissions still need benefits proportionate to their complexity.
No usage statistics or real incident rate was available for any item. Likelihood
below describes the trigger and the evidence, not a measured frequency.

## Recommended scope within the existing P12 project

The groups below organize the decision; they are not new phases or task IDs.
`FIX` means correct an existing requirement mismatch. `MODIFY` means keep the
valuable problem but narrow or define the proposed solution. `CLOSE` means do
not implement now, while recording the remaining limitation accurately.

| Existing task | Finding | Recommendation | Value and requirements consequence |
| --- | --- | --- | --- |
| P12-T-defer-1 | Slow advice for many distinct untracked findings | CLOSE now | Real synthetic cost, no affected real workload. Preserve current Git ignore semantics. |
| P12-T-defer-2 | Excluded descendants disappear from rename-coverage accounting | FIX | Small repair to the existing content-or-path warning contract. |
| P12-T-defer-3 | Retargeted stable-name symlinks do not count toward the warning | CLOSE | Accept a narrow advisory omission; do not call it fixed or silently narrow the broad specification. |
| P12-T-defer-4 | Five retained references point into removed research | MODIFY | Correct those references; preserve research removal and retained design history. |
| P12-T-defer-5 | Windows recovery hints are not safely shell-quoted | MODIFY | Define safe argument presentation; any narrower copy-paste promise must be explicit. |
| P12-T-defer-7 | Structured-refusal reference omits `rmdir_paths` | FIX | Document existing output; no schema or runtime change. |
| P12-T-defer-8 | Prefix warning counts original content before declared replacements | CLOSE | Current behavior follows the accepted source-content policy; moving the count changes that policy. |
| P12-T-defer-9 | Operational verify refusals leave JSON stdout empty | CLOSE as written | Current stderr/exit-2 contract is documented and tested; no demonstrated consumer needs a new format. |
| P12-T-defer-10 | Cleanup cannot defeat arbitrary concurrent writers atomically | CLOSE | Preserve the explicit stable-input prerequisite; stronger coordination is a new capability. |
| P12-T-defer-11 | Directory-removal guards repeatedly inspect input identities | CLOSE now | About 5 ms in the native case; changing safety-sensitive code lacks demonstrated benefit. |

If the owner selects these recommendations, the implementation order should be:

1. Correct Windows recovery presentation, task 5. It has the highest consequence.
2. Repair the existing directory-warning coverage, task 2.
3. Bundle the small documentation corrections, tasks 4 and 7.
4. Record explicit dispositions and limitations for the six closures, then
   reconcile P12's project status. Do not mark an accepted limitation as a fix.

Task 5 needs a defined presentation contract before implementation. Each product
correction needs focused failing and inverse controls, followed by the repository's
required validation. This assessment does not reopen P11A, split Windows jobs,
enable diagnostic uploads, or authorize additional performance experiments.

## P12-T-defer-1: batch Git ignore-hint queries

**Validity and example.** The repeated process cost is real; verification results
are not wrong. For each distinct untracked finding, the hint code asks Git about
the literal path and its directory-shaped spelling. Ordinary cases use two
processes, not the one-process shorthand in the original task. A symlink-related
Git refusal can require an additional mirror query. Duplicate paths share a
per-call answer; tracked findings launch no hint probes.

A bulk template-preparation failure with 500 untracked files containing the old
identity could therefore spend substantial time constructing optional advice.
The local scratch measurement took 73.211 seconds for 1,000 Git processes.
Fifty paths took 7.393 seconds and 100 processes. These measure only the hint
stage on macOS during other local work. They are not whole-command timings,
CI results, a comparison with an optimized candidate, or evidence that this
workload is common. The old 19-second observation used a different context.

**Value if solved.** Batching could make large failure reports much more
responsive. It offers no demonstrated benefit for clean or tracked-only
verification. No actual affected downstream target was identified.

**Costs, drift and recommendation: CLOSE now.** Under the owner's high threshold,
the synthetic case alone does not justify implementation. This leaves a known
scaling limitation, not an incorrect result. Reconsider only when a real target
repeatedly encounters the cost. The preliminary performance review favored a
low-priority batching change; this final recommendation gives more weight to
the lack of an affected workload.

If revisited, keep batching within one diagnostic invocation. Preserve literal
NUL-delimited paths, the captured `core.excludesFile` input, per-path fallback,
symlink mirror behavior, escaped notes and unchanged pass/fail. One invalid
query must not erase unrelated useful hints. A global cache or general Git
batching framework would exceed the demonstrated problem. Git supports batched
NUL-delimited queries, but mixed-query failures and result mapping still need
careful treatment. [Git `check-ignore` documentation](https://git-scm.com/docs/git-check-ignore).

**Evidence:** `doctor.py:74–101`; `verifier.py:182–276,356–412`;
E8 in the [accepted specification](../specs/2026-09-01-press-improvements-g2p-design.md).
Tracked-path and duplicate-path inverse controls passed.

## P12-T-defer-2: count excluded files carried by directory renames

**Validity: confirmed advisory bug.** The warning is intended to identify an
undeclared top-level history directory when all its tracked files change content
or fall under a planned rename. The accounting omits excluded descendants even
when the authorized parent move carries them. One missing leaf suppresses the
entire warning, rather than merely reducing its count.

**Example and encounter.** A directory `legacy_demo_widget_notes/` contains two
tracked neutral-text files. Exclude one file and rename the parent to
`legacy_potato_launcher_notes/`: both files move with unchanged bytes, but no
warning appears. Removing only the exclusion produces the same final files and
a warning for two tracked files. Custom exclusions inside renamed directories
are plausible; ordinary unexcluded renames already work. No frequency is known.

**Value if solved.** Restore the promised reminder to declare disposable history.
Leaving it misses that reminder. The probes found no broken move, unauthorized
deletion, receipt defect or containment failure. The warning remains a heuristic;
a fully renamed directory can contain useful content.

**Cost, drift and recommendation: FIX.** The planner already captures the complete
no-follow rename closure: the descendants carried by the directory move. Reuse
that evidence in original path coordinates, intersect it with tracked leaves and
deduplicate counts. This is a small correction to an explicit current contract.
It adds warnings for intentionally excluded files carried by a parent rename,
as the published path-based rule already requires. Do not change exclusions,
rename authorization or directory depth.

**Acceptance if selected.** The two-file case must warn once while producing
identical output. Preserve an unchanged-parent/excluded-sibling inverse. Cover
excluded subdirectories and chained renames without duplicate counts. Retain
remove/reset/`verify_ignore` and package-directory suppression.

**Evidence:** `engine.py:912–941,1009–1015`; captured closure in
`substitutions.py:506–606`; E5(a) and the
[CLI warning contract](../../source/reference/cli.md#declared-removal-coverage-warning).
Real plan/apply positive and inverse probes passed.

## P12-T-defer-3: count symlink target changes in the same warning

**Validity: confirmed narrow omission.** A symlink is a filesystem entry holding
a reference to another path. A tracked symlink can keep its own name while the
press changes that reference. Such a change is absent from the plan's warning
coverage. The broad E5 wording about all rewritten files supports counting it;
the detailed reference describes content and planned-path rewrites without an
explicit promise about a stationary link's reference. Record that precision gap.

**Example and encounter.** `history/current` points to
`../src/demo_widget/data.txt`. The press correctly retargets it to
`../src/potato_launcher/data.txt` and rewrites the other history file, but omits
the directory warning. Naming the link `history/demo_widget` makes its own path
rename and the warning correctly counts both entries. Unchanged, absolute and
escaping links remained unchanged in inverse controls.

The trigger needs a tracked stable-name link, actual retargeting, an otherwise
fully rewritten non-exempt top-level directory and no history declaration. The
current repository has no tracked symlinks. That establishes limited benefit
here, not a statistical claim about external targets.

**Value, costs and recommendation: CLOSE.** Fixing it improves one advisory;
leaving it does not break the demonstrated link retargeting. A link to live
package data is also weak evidence of disposable history. There is no complete
planned set of links that will actually retarget: the result depends on executed
moves, link geometry and containment. Predicting it duplicates safety logic;
extracting shared prediction touches that logic for a narrow advisory benefit.

Closing accepts a known advisory limitation. It does not refute the observation,
fulfill E5's broad wording, or authorize weakening link safety. Keep that explicit
in the eventual disposition. Revisit if a concrete target needs the reminder.

**Evidence:** `inventory.py:1064–1083`; `engine.py:1495–1567,1624–1632`;
five real symlink plan/apply controls and the captured Git mode `120000`.

## P12-T-defer-4: repair references into removed research

**Validity: confirmed documentation defect by static removal projection.** Five
link occurrences in three retained documents become dangling after the native
rules remove `docs/research`: `docs/README.md:10`, design 0004 at lines 14 and
324, and design 0008 at lines 10–11. For example, design 0008 retains a link to
`../research/0005-scaffolder-identity-variant-handling.md` after its target is gone.

**Encounter and impact.** This affects readers of retained design/history
documents in a self-pressed Template Press fork. Ordinary external targets do
not inherit these native declarations. No actual failed click or build was
observed. Solving it repairs navigation/context; leaving it gives those readers
broken references. It does not affect press safety or verification.

**Costs, drift and recommendation: MODIFY.** Correct only the five references so
their historical titles and meaning remain understandable without local removed
targets. Bundle with task 7. Preserve the approved research removal and useful
retained design documents. Replacing links with historical references reduces
navigation in the original repository, so preserve enough context to locate
the source history. Retaining research reverses E5(d); resetting whole design
documents discards useful context; an automatic link-rewriting mechanism adds
unjustified scope.

**Acceptance if selected.** The three referrers have no local links into the
declared removed directory. Research removal, historical meaning and unrelated
links remain unchanged. A bounded path check is sufficient; no general engine
link-validation requirement is created.

**Evidence:** `press/press-rules.toml:145–148`; E5(d);
`tests/rebrand/test_matrix.py:169–178`. This review projected removal; it did
not run a fresh self-press.

## P12-T-defer-5: make Windows recovery guidance safe to interpret

**Validity: confirmed rendering defect; native shell consequence is inferred.**
The Windows branch uses `subprocess.list2cmdline`, which follows C-runtime
argument quoting. It does not produce universally safe Windows shell text.
Exercising the actual renderer on macOS produced this hint for an ampersand path:

```text
git --literal-pathspecs -C C:\work\A&B clean -ndX -- src/demo_widget
```

`cmd.exe` treats the unprotected `&` as a command separator. A spaced-path
control was quoted; an unspaced caret path was not. No native Windows command
or destructive remedy was executed in this review. This conclusion combines
the actual rendered text with [Microsoft's shell rules](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)
and [Python's argument conversion contract](https://docs.python.org/3/library/subprocess.html#converting-an-argument-sequence-to-a-string-on-windows).

**Encounter and impact.** A Windows operator pastes a recovery hint from a path
such as an `R&D` directory. Ampersands and carets are legal path characters;
the task's pipe example is reserved in ordinary Win32 filenames and is less
plausible. The result can be a failed command or unintended additional shell
execution. This is consequential because related hints include cleanup. Actual
press subprocess calls already use argument arrays; the defect is in guidance.
No incident frequency is known. [Microsoft filename rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).

**Value, costs and recommendation: MODIFY; highest priority.** Prefer explicitly
labeled argument arrays on Windows, reusing the lossless `preview_argv` and
`remove_argv` fields that describe preview and removal commands. Keep POSIX
shell quoting. This avoids claiming one string is safe in every Windows shell.
It makes manual execution less convenient and explicitly narrows the current
copy-paste promise. If shell-ready commands are required instead, name one
supported shell and prove its parsing with a harmless native argument witness.

Inspect all affected recovery text. The renderer is also used in a compound
restore command; a separate declared-clean hint interpolates the target raw.
Substituting JSON arrays into `command && command` prose is not a complete fix.
Do not extend cleanup scope, change preview-first guidance, automatically execute
remedies or treat three escaped characters as a universal shell guarantee.

**Acceptance if selected.** Preserve exact arguments for ordinary, spaced,
ampersand and caret paths. Keep preview `-ndX`, removal `-fdX`, and destructive
warnings. Preserve structured fields and partial-restore/declared-clean guidance.
Any shell-copy-paste claim needs the actual named Windows shell test. POSIX
round-trip controls passed; [Python limits `shlex` quoting to Unix shells](https://docs.python.org/3/library/shlex.html#shlex.quote).

**Evidence:** `cli.py:122–138,180–205`; E2's safe-remedy contract. This correction
restores literal argument safety while requiring an explicit presentation choice.

## P12-T-defer-7: document the existing empty-directory JSON field

**Validity: confirmed documentation omission.** `rmdir_paths` is the array of
repository-relative empty-directory paths in structured closure refusals.
The CLI emits it; the schema key list omits it. A renderer probe retained all
25 directory paths even when prose was capped at 20 and `truncated` was true.

**Encounter and impact.** A person implementing a refusal consumer cannot learn
the field's interpretation from the reference. For example,
`src/demo_widget/empty` is relative to the invocation's target, not the consumer's
working directory. The output is already correct. Leaving the omission forces
source inspection or guesswork; fixing it improves integration guidance.

**Costs, drift and recommendation: FIX.** Document the existing sorted array,
empty-list case, target-relative interpretation and completeness despite prose
truncation. This is a small documentation correction with no schema version,
runtime or exit-code change. Do not imply automatic deletion or continued safety
after the filesystem changes.

**Acceptance if selected.** The reference matches the emitted values and
existing empty-directory controls. No new schema framework is needed.

**Evidence:** `docs/source/reference/cli.md:236–239`; `cli.py:153–168,226`;
`tests/rebrand/test_cli.py:2397–2425` and the 25-path probe.

## P12-T-defer-8: count prefixes after declared replacement rows

**Validity: the observation is true, but it does not establish a bug.** E9 warns
about the original tracked source content: an identity value appears only as a
separator-joined prefix and never as a whole token. It does not promise to
describe old tokens surviving replacement. These prefixes often rewrite
successfully by design.

**Example and encounter.** A declared `[[replace]]` row consumes the only
`demo-widget-api` occurrence. The warning still describes its original prefix.
Without that row, the generic identity replacement produces the same final bytes
and the same warning. This can be noisy for deliberate compound-only identities;
no stale output or failed press was demonstrated.

There is an inverse consequence: source containing both `whole demo-widget`
and `demo-widget-api` correctly stays silent under E9. If an earlier row consumes
the whole-token line, tallying after that row newly warns about the remaining
prefix. The proposed change can therefore add warnings as well as remove them.
Counting after all replacements would erase the intended stale-source signal.

**Value, costs and recommendation: CLOSE as a required bug fix.** The historical
PR-triage promise should be reconciled, not implemented mechanically. Current
behavior meets the accepted original-content policy. Solving the proposed item
changes whole-token suppression and diagnostic timing. A better noise policy
could be designed, but would need explicit semantics and a real affected target.
Leaving it retains occasional conditional advice for deliberate compounds and
preserves successful output. No new noise-reduction task is recommended now.

**Evidence:** `engine.py:883–907,1085–1143`; `substitutions.py:1128–1159`;
E9 and the [published prefix warning](../../source/reference/cli.md#prefix-only-occurrence-warning).
Real apply controls and four production-function tally comparisons passed.

## P12-T-defer-9: emit JSON for operational verification refusals

**Validity: current behavior is intentional under the detailed contract.**
`press verify --json` produces completed verification reports as JSON. Operational
preflight failures return exit 2, useful prose on stderr and empty stdout. Four
real subprocess probes confirmed this for missing configuration, malformed
configuration, origin mismatch and an unhonored receipt. A valid control emitted
`verified:true` JSON with exit 0. Target files remained unchanged.

**Encounter and impact.** Configuration or origin errors are plausible during
onboarding or automation. A consumer that parses stdout regardless of exit code
will fail. A consumer honoring exit 2 already knows verification did not complete
and can display stderr. Leaving the behavior means consumers must interpret prose
to classify the reason. No actual dependent consumer needing a new object was
identified.

**Value, costs and recommendation: CLOSE as written.** Copying the rebrand
structured-refusal exception onto verify would change an existing stream
contract. The reference documents receipt refusal on stderr, and an existing
test explicitly requires empty stdout. E2's special rebrand diagnostic mode does
not establish the same requirement for verify. Do not emit `verified:false`
as if verification completed when preflight refused.

If a future consumer needs machine-readable reasons, a defined error object on
stderr could preserve the current stream/exit distinction. That still requires
stable codes, multiple-reason semantics and stderr compatibility decisions.
A newly consulted general CLI standard has no recorded adoption here; it does
not establish an unmet project requirement or a new compliance gate. Clarifying
the short `--json` description is reasonable if needed, but it is not a reason
to introduce a new output mode now.

**Evidence:** `verify_cli.py:129–131,459–469,516–529,670–689`;
`tests/rebrand/test_cli.py:2617–2634`;
[CLI reference](../../source/reference/cli.md) lines 130–169 and 626–646;
[verify design](../../design/0007-press-verify-design.md) lines 533–549.

## P12-T-defer-10: stronger protection against concurrent cleanup writers

**Validity: known residual outside the supported stable-input contract.**
Exact-file cleanup freezes and rechecks file identity, mode, size, modification
time, parents, ignore status and live index membership, then unlinks a pathname.
Directory cleanup delegates to Git. Neither makes checking and deletion
indivisible with respect to another process.

**Example and encounter.** A build watcher replaces a selected ignored file or
stages it after the final check but before deletion. The replacement can be
deleted despite the earlier checks. This requires concurrent mutation; the
documented prerequisite requires selected paths, ignore/configuration inputs and
the index to remain stable. The interval for a file is narrow; a directory
cleanup has a longer sequence. No incident rate or new timed race was measured.
Thirteen existing late-tracking and file/parent-change controls passed unchanged.

**Value, costs and recommendation: CLOSE.** Keep the stable-input prerequisite
visible and retain all current guards. Closing accepts the documented concurrent
replacement risk; it does not claim the risk is impossible. A second filesystem
check moves the race. A cooperative lock cannot control arbitrary editors or
build tools. Binding selection to a snapshot does not provide a portable
conditional unlink operation.

Solving this might enable a specifically defined concurrent workflow, but it
requires a stronger coordination or platform-specific design. That expands
cleanup guarantees, portability and test obligations beyond P10. Without a
required concurrent workflow, the benefit does not justify that scope. No new
coordination mechanism is recommended.

**Evidence:** `clean_cli.py:450–530,599–620`; ADR 0018 lines 129–136;
CLI reference lines 834–849 and P10's stable-input contract. Targeted unchanged
controls: 13 passed in 47.20 seconds on macOS.

## P12-T-defer-11: cache repeated directory-removal input identities

**Validity: repeated work is confirmed; an important real bottleneck is not.**
For each selected member, the guard compares captured Git input paths and
filesystem identities to prevent deletion of those inputs or their hardlinks.
That safety purpose must remain.

Instrumented guard timings on local macOS were:

| Selected members | Existing Git inputs | Input stat calls per invocation | Two guard timings, seconds |
| ---: | ---: | ---: | --- |
| 27 | 22 | 594 | 0.067 / 0.071 |
| 500 | 22 | 11,000 | 2.501 / 2.108 |
| 500 | 100 | 50,000 | 8.825 / 7.802 |

These isolate the guard, include instrumentation overhead and ran during other
local work. The original 595-call observation included an extra full-freeze
call; it does not contradict the isolated 594-call count.

**Encounter and impact.** A large removed directory with many active ignore and
configuration inputs can pay this cost. No real large affected consumer was
identified. The actual native `docs/research` declaration had six members and
four inputs: the guard took **0.004808 seconds**, about **0.16%** of the observed
**2.975-second** complete directory freeze. These are not CI timings or measured
savings. A hardlink-to-input inverse still refused.

**Value, costs and recommendation: CLOSE now.** Saving approximately five
milliseconds in the native case does not justify changing safety-sensitive
identity capture. Leaving it accepts the demonstrated synthetic scaling limit;
it does not certify large-target performance. Reopen for a representative real
target where this guard consumes meaningful time.

A future cache must preserve direct paths, hardlinks, aliases, nonzero identity
handling, missing inputs and changes at the validated snapshot boundary. A stale
cache could weaken those guards. Do not create cross-invocation state, reduce
checks or interpret the maximum member limit as a new performance promise.

**Evidence:** `remove.py:189–257`; synthetic call counts, hardlink inverse and
the native declaration freeze measurement.

## Verification and review record

Product source, tests, workflows, rules and lockfile remained identical to the
named merged source. All changes in this branch are documentation. Probe targets
were isolated scratch repositories; no real consumer target was rebranded.

- Template Press setup and required `just check` passed. The check used
  `PYTEST_ADDOPTS='-n 8'` locally: 2,175 passed, 24 skipped; pytest 515.06 seconds,
  complete command 518.751 seconds. This is validation, not a CI optimization.
- Twelve real Git warning plan/apply controls passed in 41.824 seconds. Four
  additional production-function prefix comparisons passed after a scratch
  constructor argument was corrected. The initial harness error is retained.
- Structured-output, five-reference projection and POSIX-rendering controls
  passed. Windows rendering was exercised locally; native Windows shell
  execution was not performed and remains required for any shell-safety claim.
- The 13 targeted clean controls passed in 47.20 seconds. Performance probes
  include tracked/duplicate-path and hardlink inverse controls.
- Evidence, raw outputs, scripts and file-hash receipts are retained under
  `/private/tmp/template-press-group3-execution/p12-evaluation/`. The warning and
  output subagent reports were reconciled against source before synthesis.
- An independent internal documentation review returned `SPEC PASS / QUALITY
  APPROVE`. It verified all ten open IDs, the unchanged completed item, local
  references, source/evidence consistency and the distinction between
  recommendations and decisions.
- Independent external review has not run. Automatic approval review blocked
  sending the new local evaluation and evidence to Muse, including after all
  30 packet source files were verified byte-for-byte through unauthenticated
  public GitHub downloads and a secret scan passed. Specific transfer approval
  is pending. The prepared invocation requests Ultra and a 100-step maximum;
  no actual model effort, step count or external verdict is claimed.

**Evaluation-time next action:** obtain owner decisions on the four-item scope
and the six recorded limitations. Those decisions have since been made, as
recorded at the top of this document and in P12's closed follow-ups. The original
probe and review evidence above is retained without claiming a new test run or
an external review verdict.
