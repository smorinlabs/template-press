# P10 planning gate — `[[clean]]` / `press clean` reconciled against merged `main`

**Date:** 2026-09-05 · **Baseline:** `main` at `bddbae3` (after PR #116 `[[edit]]`,
PR #117 parallel test matrix, PR #118 batched `rev-parse`) · **Scope:** plan
Tasks 16–18 of `docs/superpowers/plans/2026-09-01-press-improvements-g2p.md`
· **Output:** `docs/superpowers/plans/2026-09-05-p10-declared-pre-press-clean.md`

## Purpose

The P09 closeout handoff requires a major planning review before P10
implementation: reconcile every P10 task and acceptance criterion with the
merged code, dependencies, open findings, and risks; review with Claude
Fable and Muse; revise only where justified; re-review the result. This
record is that review. A no-change outcome was allowed; the outcome here is
**revise**, for the reasons in §3.

## 1. Inputs

| Input | Where | Standing |
| --- | --- | --- |
| Binding design, §E10 | `docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md` | Decided (Steve, 2026-09-01) |
| Adversarial design review | `docs/superpowers/specs/reviews-2026-09-01/CLEAN-review.md` | Historical input; produced the restricted form the spec adopted |
| Plan Tasks 16–18 | `docs/superpowers/plans/2026-09-01-press-improvements-g2p.md:576-603` | Superseded by the new plan |
| Tracker | `projects/P10-declared-pre-press-clean.md`, `PROJECTS.md` row P10 `[ ]` | Unchanged by this gate |
| Merged code | `rules.py`, `cli.py`, `press_cli.py`, `check_tools.py`, `receipt.py`, `inventory.py`, `safety.py`, `regen.py` at `bddbae3` | Read directly |
| Empirical probe | `git clean -ndX` in a scratch repository | Run on this machine, git 2.x |

## 2. Reconciliation findings

Each row names the plan text, what the merged code or a probe shows, and
the disposition carried into the new plan (R-numbers match the plan's
"Decisions fixed by the planning gate").

| # | Plan said | Found | Disposition |
| --- | --- | --- | --- |
| F1 | Task 17 step 3: "add the hint at the `cli.py` catch site from Task 2 when `rules.clean` is non-empty" | The hint already exists at `cli.py:185-186` inside `_print_closure_refusal_prose`, guarded by `getattr(rules, "clean", ())` because `Rules.clean` did not exist yet. Message text matches the plan's expected substring exactly. | R1: replace the `getattr` with `rules.clean`; test both directions (the CLEAN review asked for the negative case; the plan had only the positive one). |
| F2 | Task 17: exit 2 "when a path is outside the target" | `_declared_rel_path` (rules.py:432) refuses absolute paths, `..`, NUL and control characters at config load, so this is an exit-2 `ValidationError` before anything runs. The CLEAN review (D5 b) also asked that the rendered string be validated again. | Task 1 validates the declared pattern; Task 2 validates the rendered path (control characters, `SafeRelPath`). |
| F3 | Task 16: "unknown placeholder `{nope}` → `ValidationError`" | Parse time has no identity to render against, but `ALLOWED_PLACEHOLDERS` (rules.py:36) and the `[[replace]]` brace-token scan (rules.py:355) give a parse-time vocabulary check with the same strictness (`{App_Name}` also refused). | Task 1 reuses that scan verbatim. |
| F4 | Task 16: "platforms honored" | Platform selection lives in `_ParsedRules` + `_select_rules` (rules.py:1213), which the plan never named; every mechanism needs a declaration wrapper and a selection line. `Rules` is constructed positionally in places, so a new field must be appended after `edit`. | Task 1 names all of `_CleanDeclaration`, `_ParsedRules.clean`, `_select_rules`, and the append-after-`edit` rule. |
| F5 | Task 17: `git --literal-pathspecs -C <target> clean -fdX -- <paths>` "echoing the exact argv first" | Every on-target git call in the codebase runs with `git_hardening_args()` (`-c core.fsmonitor=` …, safety.py:826) and `scrubbed_git_env()` (global/system config neutralized, safety.py:803), per G5. `git clean` reads the work tree, so a committed `core.fsmonitor` hook could execute without the flags. | R3: the argv carries the same prefix as `inventory._run_git` plus `--literal-pathspecs`, and the echoed line is that exact argv. Consequence recorded: the operator's global excludes file is not consulted. **Owner decision D-A below.** |
| F6 | Task 17: exit codes 0 / 2 / 1 | The plan omitted `git` unresolvable and `press/press-source.toml` missing. `check_tools.py:47` resolves git with `resolve_executable(target, "git", command_env(()))`; `load_source_config(target, None)` (config.py:95) returns `None` when absent. | Task 3 lists every exit-2 condition; `1` is reserved for "git ran and failed". R4 records that the E1 origin guard is not consulted. |
| F7 | Task 17 test: "no rules declared → exit 2" | With platform selection, the precise condition is "no ACTIVE rule on this platform" (a `win32`-only rule on darwin). | Task 3's test declares a foreign-platform rule and expects the plan's message verbatim. |
| F8 | Task 17: E2 tie-in expects `press rebrand --dry-run` to refuse | Verified on `main`: the refusal fires when the source package directory holds an ignored file; `make_target` ignores `__pycache__/`, so `src/demo_widget/__pycache__/x.pyc` reproduces it without extra fixtures. | Task 3's hint tests use exactly that. |
| F9 | Task 17 test: `capture_surface_snapshot` before == after | With the restricted form the invariant is git's own `-X` semantics; the CLEAN review's runtime comparator (D3) was written for the arbitrary-argv variant the spec rejected. | R7: keep the equality as a test assertion, add no runtime exit-1 tripwire. |
| F10 | Task 17: "Would remove src/demo_widget/__pycache__/" | Probe: `git --literal-pathspecs clean -ndX -- src/pkg tests` prints exactly `Would remove src/pkg/__pycache__/`; an untracked non-ignored file survives; a pathspec matching nothing exits 0 and prints nothing (the CLEAN review's "pathspec did not match" claim does not hold for `git clean`). | R2: absent declared path is a silent no-op with its own test. |
| F11 | Task 18: "receipt writes `[[press.clean]] paths = [...]`" | `write_receipt` (receipt.py:83) takes one sequence per mechanism and the call site at `cli.py:962` has the active `rules` in scope. The CLEAN review preferred an explicit `ran = false`; the spec says "declared, never ran". | R5: record the declared patterns unrendered, no `ran` key, docs state the meaning; a test asserts no `ran` text. |
| F12 | Task 18: "`check-tools` reports `git` for clean rules" | `check_tools.py:47` already reports git first and counts it as missing when unresolvable; the review's concern ("a declared clean would fail after a clean bill of health") is therefore already covered. | Task 4 adds one informational row per active rule; no new missing path. |
| F13 | Task 18: docs `cli.md` + `press-target` SKILL.md | `cli.md:231-235` already documents that the refusal names `press clean`; `cli.md` has one `##` section per verb; P09 shipped `docs/adr/0017-declared-in-place-edit.md`. | R9: add `## press clean` after `## press check-tools`, the SKILL step 1b, and ADR 0018. |
| F14 | (absent) native coverage | `press/press-rules.toml` declares `[[reset]]`, `[[edit]]`, `[[regenerate]]`, `[[remove]]` for this repository and the R3 self-press asserts the receipt; nothing declares `[[clean]]`. | R8: declare `paths = ["src/{package_name}", "tests"]` and assert the receipt row plus a `--show` preview in R3. |
| F15 | (absent) writer overlap | `_validate_writer_overlaps(regenerate, reset, remove, edit)` refuses two writers on one file. Clean paths name directories whose ignored children are removed; inventoried writer targets cannot be ignored. | R6: no overlap check. |
| F16 | `press_cli.py:39-43` dispatch | The dispatcher is at lines 40–46 now and `_USAGE` is asserted only for the presence of verb names (`test_press_cli.py`), not snapshot-tested, so adding a `clean` line has no snapshot cost. | Task 3. |
| F17 | Dependencies | P10 depends on nothing unmerged: the E2 hint (P12 Task 2) and `[[edit]]` (P09) are on `main`; P11 is independent. The Windows retry-test flake (#119) is unrelated but means new tests must stay `tmp_path`-isolated for the parallel matrix. | No change. |
| F18 | Task 3 allowed the repository-configured `core.excludesFile` to equal or sit below a rendered clean path. | A real `git clean -fdX` probe deleted that active, untracked visibility input and exited 0. Exact-file and containing-directory cases reproduced with relative and absolute configured forms. On this case-insensitive macOS volume, `normcase(abspath(...))` and `realpath` preserve alternate casing even though `samefile` reports the paths as one node. | R11: refuse overlap with exit 2 before echo or Git clean. Use the normalized lexical relation plus existing-node identity for case aliases. Tests preserve configured bytes, cache bytes, and the complete snapshot. |
| F19 | R11 protected only `core.excludesFile`; R7 still treated Git `-X` alone as sufficient for complete snapshot equality. | The exact planned helper deleted an active self-ignored `.gitignore` under exact and containing clean roots and an ignored repository `include.path` input under a clean root, then exited 0. These paths are recorded in `SurfaceSnapshot.visibility_inputs` or `git_config_inputs` but absent from its tracked-plus-nonignored `entries`. A distinct hardlink to a tracked path proved that inode equality cannot grant protected membership: Git deletes the active input's directory entry independently. | R7 and R12: capture the public snapshot before echo or clean; refuse every present active input below a clean path unless its exact directory entry is protected. Preserve tracked, non-ignored, disjoint, missing, and inactive controls. Keep R11's conservative identity rule for overlap only. |

## 3. Why the outcome is "revise"

The 2026-09-01 tasks were correct in intent and wrong in no decision, but
they were written before P09/P12 landed and before the parallel matrix. Twelve
points (R1–R12) were either silent, pointed at code that has since moved, or
relied on a claim the probe refuted. Leaving them for the implementer to
rediscover would violate the handoff's rule that tasks be implementation
ready. The spec's decisions are untouched; the non-goals (§4 of the spec)
are untouched.

## 4. Owner decisions

**D-A — git environment for `press clean`: scrubbed.** The resumed session
accepted the recommendation to continue with the scrubbed environment on
2026-09-05. Global and system Git configuration are disabled. Repository-local
ignore settings remain active. The explicit excludes-file pin in §5.5 also
disables Git's default user ignore fallback, matching the surface inventory.
An entry ignored only by the operator's global excludes file is preserved.

**D-B — Muse review effort: UNRESOLVED owner exception.** The handoff requires
ultra or a specific exception. Muse passes 3 and 4 requested ultra; both CLI
startup diagnostics reported the closed `ultra_reasoning_effort` gate and
actual xhigh. Pass 4 approved the final correction. Steve's universal
authorization covers sending review material; the actual-effort exception
for this planning gate remains a separate recorded decision.

## 5. Review log

Filled in by the gate as each review completes. "Findings" are counted as
received, not as fixes chosen.

| Reviewer | Effort requested / actual | Verdict | Required findings | Disposition |
| --- | --- | --- | --- | --- |
| Claude Fable (in-session, this document and the plan) | n/a | see §5.1 | — | — |
| Muse, pass 1 (plan at `d1f457e`) | ultra / **xhigh** (gate `ultra_reasoning_effort` reported closed) | FIX, confidence 0.8 | 3 | all three applied; two of four optional suggestions adopted (§5.2) |
| Muse, pass 2 (revised plan at `287e387`) | ultra / **xhigh** (gate still closed) | APPROVE, confidence 0.85 | 0 | no change; it verified each revision against `main` (`SafeRelPath` refuses `src/../escape` at `safety.py:215-216`; the gitfile failure test exits 128 deterministically and passes the test interceptor; the `.git` pre-check is the truthful exit 2 because `scrubbed_git_env` clears `GIT_DIR`) |
| Claude Fable, re-review of the revised plan | n/a | APPROVE | — | the three fixes and two adoptions are the only deltas; spec coverage and type consistency re-checked |
| Codex, resumed independent review | inherited session configuration; no Muse/Fable substitution | APPROVE on the original resumed plan hash below | 0 | extracted the exact gitfile helper and ran ten independent metadata cases; checked tuple shape, content preservation, task imports, and native commit ordering |
| Muse, resumed pass 3 at `4588d5e` | ultra / **xhigh** (provider gate closed) | FIX | 1 | default user excludes can delete an inventoried file; reproduced and corrected below |
| Claude Fable 5.1, resumed pass 3 at `4588d5e` | max / **max**, no fallback | FIX | 1 | invalid ordinary `.git` permits ancestor discovery; reproduced and corrected below |
| Muse, final delta re-review | ultra / **xhigh** (provider gate closed) | APPROVE | 0 | plan hash `2306e917…` in §6; all five corrections checked against source |
| Claude Fable 5.1, final delta re-review | max / **max**, no fallback | APPROVE | 0 | plan hash `2306e917…` in §6; prior unchanged sections retain their earlier review coverage |
| Muse, configured-excludes overlap delta (plan `56549d64…`) | ultra / **xhigh** (provider gate closed); configured 100 max steps | APPROVE | 0 | historical R11-only verdict; the later whole-plan review found F19 |
| Claude Fable 5.1, configured-excludes overlap delta (plan `56549d64…`) | max requested; usage-credit error before review | **NOT REVIEWED** | — | no verdict; no substitution inferred |
| Internal whole-plan active-input review (plan `56549d64…`) | independent source and executable probes | FIX | 1 | F19 applied as R7/R12 in plan `b10ca82f…` |
| Muse, combined active-input exact-delta review (plan `b10ca82f…`) | ultra / **xhigh** (provider gate closed); configured 100 max model steps | APPROVE | 0 | exact correction approved; receipt `muse-p10-active-inputs.log` |
| Claude Fable 5.1, bounded combined active-input retry (plan `b10ca82f…`) | max requested; usage-credit rejection before review | **NOT REVIEWED** | — | no verdict; receipt `fable-p10-active-inputs.json`; substitution remains an owner decision |
| Internal `gpt-6-astra` scoped final review (plan `b10ca82f…`) | session-configured effort | APPROVE | 0 | spec compliance and task quality approved; prior R1 resolved; receipt `p10-internal-major-rereview.md` |

### 5.1 Fable review of the reconciled plan

Checked against spec §E10 line by line and against the CLEAN review's
"tests that must exist" list. Every spec bullet maps to a numbered task and
a named test. Two residual risks are recorded rather than closed:

- The git output strings `Would remove …` / `Removing …` are pinned from one
  git version; Task 3 step 4 says what to do if a runner's git differs.
- `SafeRelPath` must accept `{` and `}` in a declared pattern for Task 1's
  raw-path validation to work as written; verified before this plan was
  committed (see the note below the table in §6).

Verdict: APPROVE for Muse review.

### 5.2 Muse pass 1 — findings and dispositions

Required (all applied in the plan):

1. `clean_cli.py`'s exit-2 exception set missed `ContainmentError`, which
   `load_source_config` raises through `assert_control_real` for a symlinked
   `press/` directory and which is a `SafetyError`, not a `ValidationError`
   (`safety.py:94`, `config.py:26-47`). Fixed: added to `_CONFIG_ERRORS`.
2. The receipt test asserted `"ran" not in` a substring of the raw receipt,
   which also matches `reason` and `brand` in later tables. Fixed: the
   assertion now checks the parsed `[[press.clean]]` table's keys.
3. Task 3's RED description claimed the positive E2-hint test would fail
   before Step 3; after Task 1 the `getattr`-guarded hint already fires, so
   only the dispatcher tests fail. Fixed: the description now says which
   tests fail and why the hint tests are kept as pins.

Optional, adopted: a `.git` pre-check in `clean_cli.py` so a wrong directory
exits 2 ("nothing ran") instead of the 1 git would produce, with the exit-1
test rewritten around a gitfile that points nowhere; the revalidation test
now proves a refusal through a hostile stub instead of a benign pass; a
`cli.md` sentence contrasts the ambient hand-typed remedy with the scrubbed
`press clean`. Optional, declined: no action on nested repositories (git
skips them without `-ff`; the refusal persists and is self-correcting).

Documentation corrections from the same pass: F1 and the plan cite
`cli.py:185-186`, the `getattr` guard and its `print` (was 186 alone); F6
cites `check_tools.py:47` (was 52).

Muse's original safety analysis supported D-A but missed Git's built-in
default user ignore fallback. The resumed pass reproduced that deletion path;
§5.5 records the explicit excludes-file pin needed to make D-A true.

### 5.3 Gate status

The reviewed `b10ca82f…` correction has completed its available reviews and
executable checks. The current `95c16db4…` plan differs only by the
Ruff-required reflow of one condition in its fifth Python fence. All 17 Python
fences retain the same code: the changed fifth fence has an equivalent abstract
syntax tree, and the other 16 fences are byte-identical to commit `216061b…`.
No behavioral or provider approval is attributed to the new hash. Muse
approved at actual xhigh after ultra was requested,
with 100 max model steps configured. The internal `gpt-6-astra` scoped final
review approved both spec compliance and task quality and marked prior R1
resolved. Claude Fable's bounded retry failed before review because usage
credits were exhausted, so it supplied no verdict. Historical approvals remain
bound to their recorded hashes. The earlier GitHub findings retain their
verified dispositions.

Implementation remains gated on D-B's explicit owner exception for Muse's
actual xhigh effort and on an explicit owner decision about substituting for
the missing Fable review. Neither gate is waived or inferred. D-A uses the
accepted scrubbed environment plus the excludes pin. The documentation
worktree's final `just check` passed with 1412 tests and 2 skips in 247.86s.
The exact materialized inventory suite passed 75 tests in 86.81s. The
controller owns commit, push, and PR closeout.

### 5.4 Resumed review corrections

- Correct `_select_rules` to pass a tuple of `CleanRule` objects, without
  an extra enclosing tuple. The code fence now computes `active_clean`
  separately so formatting it cannot change a keyword argument into a tuple.
- Bind regular gitfiles to the selected linked-worktree metadata through
  its regular `gitdir` backlink. A target redirected to a sibling worktree
  otherwise uses that sibling's index and can delete a file tracked by the
  requested target. Both preview and apply enforce the same precondition.
- Declare the supported layouts explicitly: ordinary `.git` directories
  and registered linked worktrees. Gitfiles without that backlink, including
  submodule roots and standalone separate-Git-directory layouts, are refused.
  No E10 requirement promises those layouts for this new verb.
- Preserve path whitespace and relative backlinks. Read backlinks with
  `read_regular_nofollow`; map its `SafetyError` to exit 2. A read-only Git
  query may run before refusal, so exit 2 means no clean command ran.
- Replace the dangling-gitfile exit-1 fixture with a corrupt index in an
  otherwise valid ordinary repository. Invalid gitfiles now test exit 2.
- Commit the native declaration before running the acceptance test that
  clones `HEAD`. Keep the test sequence executable without an implicit step.
- Keep the previous local fixes for malformed braces, symlinked control
  directories and `.git`, platform-active runbook conditions, command-display
  wording, documentation fences, checker configuration, and source citations.
- Assert protected file bytes as well as snapshot equality. The inventory
  alone does not prove that tracked and untracked file contents survived.
- Rename the command-display test to remove its obsolete copyability claim;
  use an executable placeholder for the pure argv-construction test.
- Add test imports at the task that first uses them. Ruff auto-fixes unused
  imports, so putting Task 3/4 dependencies into Task 2 would remove them
  before later tests were appended. Each intermediate module is checked.

The metadata correction was checked independently with ordinary, absolute
and relative linked, foreign normal, foreign sibling, malformed, dangling,
and symlink-backlink fixtures. The actual deletion control preserved a
tracked file with correct metadata and deleted it with the sibling index.
The new rule follows Git's documented
[per-worktree backlink](https://git-scm.com/docs/gitrepository-layout) and
[linked-worktree metadata](https://git-scm.com/docs/git-worktree).

### 5.5 Further review and verified corrections

Steve explicitly authorized sending review material to Muse, Fable, and
Claude on 2026-09-05. Provider authorization is settled. D-B remains the
separate requirement to record and accept the actual review effort.

The next GitHub wave contained four findings: three from Codex and one
duplicate forged-backlink finding from CodeRabbit. The changes stay within
the planned clean verb and its supported-layout checks.

- **Forged backlink:** a foreign ordinary Git directory with a fabricated
  regular `gitdir` file passed the old guard and deleted tracked fixture
  bytes. Require a regular `commondir` file and a selected directory directly
  under its resolved common repository's `worktrees/` registry as well as
  the target backlink. Tests include a forged `commondir` and valid absolute
  and relative common-directory paths.
- **Successful-command warnings:** a real unreadable-directory probe made
  preview and apply exit 0 with a permission warning only on stderr. Forward
  stderr regardless of return code. Controlled CLI tests preserve that
  warning and the existing 0/1/2 mapping.
- **Windows junction:** the original directory check accepted a marker
  reported as a junction. Use `Path.is_junction()` before directory acceptance.
  The portable regression simulates that filesystem classification, matching
  existing inventory-test conventions. Native Windows execution is an
  implementation-CI obligation outside this planning-gate record.
- **Muse default-excludes finding:** a temporary XDG default Git ignore file
  made the old command delete an inventoried `debug.log`. Mirror inventory's
  NUL-delimited configured-excludes lookup and pin that path or the null
  device. Tests cover absent, empty, relative, and absolute configured values
  in both preview and apply, including protected bytes and snapshot equality.
- **Fable ancestor-discovery finding:** an invalid ordinary `.git` directory
  inside a parent repository let Git select the parent's index and excludes,
  deleting the target's `src/` directory. Query both marker kinds and require
  an ordinary marker's discovered Git directory to be the target's own `.git`.
  Both preview and apply now refuse that fixture and preserve its bytes.

The Git layout and default ignore behavior match the primary documentation:
[repository layout](https://git-scm.com/docs/gitrepository-layout),
[ignore sources](https://git-scm.com/docs/gitignore). Relative gitfile paths
in the test fixtures now resolve against their target before metadata edits.

Final re-review approved these corrections with no required findings. The
earlier review verdicts remain tied to their original snapshots.

### 5.6 Final bounded review wave

Steve authorized continued review and merging this planning PR when ready.
The stricter review bar applies: only demonstrated defects in the proposed
behavior receive changes. The latest GitHub wave had three findings:

- **Configured excludes can block Git:** CodeRabbit identified a named pipe
  used as `core.excludesFile`. A real Git invocation timed out after two
  seconds; a regular-file control completed successfully. Named pipes are
  unsupported inputs, not a feature requirement. Reuse
  `read_regular_nofollow` before calling clean. Its nonblocking regular-file
  check rejects pipes, directories, and symlinks. An absent configured file
  remains valid, and the explicit null-device setting maps to the existing
  null-device pin. Six refusal cases fail promptly on the previous helper;
  four missing/null-file controls pass. All ten pass with the guard.
- **Complete replacement of linked registration:** Greptile's fixture can
  delete a file tracked only by displaced original metadata. Both fabricated
  registration and a genuine `git worktree add --detach --no-checkout` control
  exclude that file from the current inventory before cleaning. Both preserve
  the exact current surface snapshot. E10 protects that current inventory;
  it does not authenticate a previous repository after its metadata was
  replaced. The finding was refuted with these two independent controls.
- **Review-provider authorization wording:** the live PR body already records
  Steve's universal sending authorization and separates it from D-B. The
  stale conditional wording request was refuted and resolved.

### 5.7 Configured-excludes overlap correction — historical review state

At commit `94cbd40868dd0273e632549527dddade53ee4045`, the previous
planned helper could pass its configured `core.excludesFile` to the same
`git clean -fdX` command whose pathspec selected that file or an ignored parent
directory. Git deleted the active visibility input and exited 0. The complete
`SurfaceSnapshot` therefore changed, violating E10.

R11 adds a pre-execution `ValidationError` refusal after
`_clean_excludes_path` and before argv construction, the `preview:` or `run:`
line, and `execute_clean`. It compares `os.path.normcase(os.path.abspath(...))`
paths for the ordinary exact-or-descendant relation. It then compares each
existing configured-path ancestor to the clean root with `os.path.samefile`,
because POSIX `normcase` is a no-op on case-insensitive macOS volumes. The
existing `read_regular_nofollow` call remains the no-follow gate for the
configured leaf and its ancestors. The correction adds no Git classification,
post-mutation comparison, restoration, or race protocol.

The refusal covers relative and absolute configured forms, SOURCE-rendered
clean paths, exact-file and containing-directory relations, and missing
configured paths inside a clean root. Absent and null-device configuration,
plus disjoint existing or missing configured paths, retain the earlier
behavior. Both preview and apply refuse with exit 2 while preserving configured
bytes, cache bytes, and the complete snapshot. Muse approved this R11-only
revision at requested ultra / actual xhigh with 100 configured max steps.
Claude Fable returned a usage-credit error before reviewing; no Fable verdict
or substitution is inferred. The later whole-plan review then found F19, so
that Muse verdict remains historical and does not cover R12.

### 5.8 Active Git-input preservation correction — final review outcome

The whole-plan review of `56549d64…` demonstrated that Git `-X` can delete
active inputs that are intentionally absent from ordinary inventory entries.
Both preview and apply reached Git clean for an active self-ignored
`.gitignore` under exact and containing clean roots and for an ignored
repository config include under a clean root. Apply deleted the inputs and
changed the complete `SurfaceSnapshot` while returning 0.

R12 calls the existing public `capture_surface_snapshot` before any command
echo or clean invocation. It checks every present `visibility_inputs` and
`git_config_inputs` path below a rendered clean root. An input absent from
`listed_paths(snapshot)` refuses with exit 2. Tracked and non-ignored paths are
listed and remain protected by Git `-X`; disjoint active inputs are outside the
clean roots; missing inputs cannot be deleted; inactive `.gitignore` files
beneath ignored parents are absent from the active-input tuples and remain
cleanable. The plan adds no second ignore traversal, post-mutation comparison,
restoration, retry, or new classification protocol.

Protected membership uses exact absolute spelling or verifies a filesystem
case alias of the same directory entry. Unrestricted `samefile` membership is
unsafe: a real ignored `.gitignore` hardlinked to a disjoint tracked file was
still deleted by Git clean. R11 retains its conservative same-node fallback for
overlap refusal, where a false positive cannot grant deletion authority.

The new snapshot preflight moves a corrupt-index failure from executed-clean
exit 1 to precondition exit 2. `subprocess.CalledProcessError` from the public
snapshot API is therefore normalized inside the pre-clean exception boundary.
A separate controlled clean failure proves that an invoked Git clean still
forwards stdout and stderr and returns exit 1. The null-device control exposed
one public-snapshot interaction: device timestamps change when Git opens
`/dev/null`, causing the two-candidate capture to reject its own read. The plan
normalizes the literal platform null device to the inventory's existing absent
representation; it contributes no policy bytes, and `clean_argv` remains
pinned to the null device.

The reviewed behavior plan SHA-256 is
`b10ca82f9323aafcf2823562e9aa5bc45bf5870725a7851e9c8d3329210ebb85`.
The current Ruff-formatted plan SHA-256 is
`95c16db4ae1ac43899e50f1ceec31c22285c16bfd65e0f46be3bc26bd8e4fcbd`.
The hashes differ only because Ruff joined one condition in the fifth Python
fence. An AST comparison against commit
`216061b8610b36998a548f46dcaf17996c932145` found the changed fence equivalent;
the other 16 Python fences are byte-identical. This formatting-only result adds
no behavioral or provider approval for the current hash.
Muse approved the reviewed `b10ca82f…` behavior plan at requested ultra /
actual xhigh with 100 max model steps configured. The internal `gpt-6-astra`
final rereview approved that same `b10ca82f…` snapshot for spec compliance and
task quality, with prior R1 resolved. Claude Fable's
bounded retry failed before review because usage credits were exhausted and is
recorded as NOT REVIEWED. D-B and the Fable-substitution decision remain
unresolved owner gates; neither is waived or inferred.

## 6. Verification record

- Empirical probe (git clean semantics): `Would remove src/pkg/__pycache__/`,
  exit 0; nonexistent pathspec exit 0 with no output; untracked non-ignored
  file survives `-X`.
- `SafeRelPath("src/{package_name}")`: accepted unchanged (`src/{package_name}`, `tests`, `build/{repo_name}` all round-trip through `SafeRelPath(...).as_posix()`), so the raw pattern can be validated before rendering.


### Resumed executable-plan validation at `4588d5e`

The plan SHA-256 reviewed by Codex and materialized for these checks is
`0533044d2a09168073c8e525c31f78a218659ebfc6004e8dffec689300199250`.
These checks validate proposed snippets in a disposable clone. They do not
mean that P10 has been implemented in this branch or released.

| Check | Result |
| --- | --- |
| Full repository `just check` on the documentation revision | Passed; 1412 tests passed, 2 skipped, 4 deselected |
| Parser and complete clean CLI tests assembled from the plan | 55 passed |
| Task 2 boundary: pure helper tests and no unused imports | 6 passed; Ruff F401 clean |
| Task 3 boundary: CLI tests and no unused imports | 29 passed; Ruff F401 clean |
| Task 4 boundary: integrations and no unused imports | 33 passed; Ruff F401 clean |
| Inverse control: restore the extra tuple around active rules | Parser assertion failed as expected |
| Inverse control: bypass the gitfile validation call | Three preservation/precondition cases failed as expected; the unguarded apply deleted protected fixture files |
| Independent exact-helper check | Ten cases: absolute/relative/newline worktrees accepted; foreign/sibling/dangling/malformed/symlink-backlink/separate-directory/submodule cases refused |

The full proposed test command was
`pytest tests/rebrand/test_clean_rules.py tests/rebrand/test_clean_cli.py -q -o addopts=`
inside the disposable clone with the plan snippets applied. The inverse
controls failed assertions with exit 1, rather than failing setup or imports;
the scratch source was restored after each control.

This original resumed revision was superseded by the further corrections
below. Its results remain historical evidence, not the final safety verdict.

### Further executable-plan validation

Previously approved plan SHA-256: `2306e9175189804d631a1c51779143f61c8df86738ffb3714dd36b2d79aa58db`.
Muse and Fable reviewed this exact plan. Later changes to this record only
record the returned verdicts and validation results.

| Check | Result |
| --- | --- |
| Full repository `just check` after the corrections | Passed; 1412 tests passed, 2 skipped, 4 deselected |
| Exact revised plan materialized in a disposable clone | 73 passed |
| Task 2 / 3 / 4 boundaries | 6 / 47 / 51 passed; no unused imports at each boundary |
| Proposed source and tests | Ruff check/format and source type checking passed |
| Inverse: remove linked metadata registration check | Four forged-backlink assertions fail |
| Inverse: allow ordinary-directory discovery to select an ancestor | Two precondition/preservation assertions fail |
| Inverse: remove the excludes-file argv pin | Two default-ignore preservation/preview assertions fail; six configured-value controls pass |
| Relative-worktree fixture configuration | Six selected cases pass with `worktree.useRelativePaths=true` |
| Real Git permission-warning probe | Preview and apply both exit 0 with a warning on stderr |

These are executable-plan checks, not shipped P10 implementation or a native
Windows result. The simulated junction regression remains an explicit limit.
All scratch source was restored after the inverse controls.

### Final configured-excludes correction

Plan SHA-256: `65bb256e7b567215c60d10823ad960175e9287d34f18ca9be7df4ddeb8f56a48`.
Both named providers reviewed this exact delta: Muse APPROVE at actual
xhigh (ultra requested, provider gate closed), and Claude Fable 5.1 APPROVE
at max with no fallback. No required findings remain. Earlier full reviews
continue to cover unchanged plan sections.

| Check | Result |
| --- | --- |
| Full repository `PYTEST_ADDOPTS="-n 8" just check` | Passed; 1412 tests passed, 2 skipped; same default marker selection, eight workers |
| Exact plan materialized in a disposable clone | 83 passed |
| Task 2 / 3 / 4 boundaries | 6 / 57 / 61 passed; no unused imports at each boundary |
| Proposed source and tests | Ruff check/format and source type checking passed |
| New configured-excludes tests on the previous helper | Six refusal cases fail promptly; four missing/null controls pass |
| New configured-excludes tests with the guard | All ten pass |

This PR remains documentation only. D-B gates implementation, not merging
this planning record. Steve's instruction to merge when ready is recorded
separately from an exception for Muse's actual effort.

### Configured-excludes overlap correction

Corrected plan SHA-256:
`56549d64795b1676851e665bacde6599f3f60ed98d24450953809d31b6e6ede9`.
At materialization time, the plan was pending a new exact-delta review. The
results below validate its proposed snippets in disposable clones; they do not
implement P10 in this branch or replace D-B. §5.7 records the later Muse
approval, the Fable usage-credit failure, and supersession by F19.

| Check | Result |
| --- | --- |
| Previous complete helper plus the new regressions | `12 failed, 83 passed in 50.08s`; all eight exact/ancestor, relative/absolute, preview/apply cases, both missing-overlap cases, and both case-alias cases reached the Git clean interceptor |
| Corrected exact plan materialization | `95 passed in 54.27s` at `/private/tmp/pr120-overlap-fix-c7do6ai6` |
| Case-alias normalization probe on this macOS volume | Alternate casing existed; `normcase(abspath(...))`, `realpath`, and `Path.resolve()` preserved different spellings while `os.path.samefile` returned true |
| Inverse: remove only the `samefile` ancestor fallback | `2 failed, 71 deselected in 2.06s`; preview and apply both reached the Git clean interceptor |
| Restored case-alias fallback | `2 passed, 71 deselected in 3.31s` |
| Round-one exact Task 3 lint materialization | `/private/tmp/pr120-overlap-fix-lint-7t4vwwgc`; the rehearsal placed staged imports with the locked Ruff sorter and did not rerun behavioral tests |
| Task 3 proposed source and test lint | `ruff check --no-fix` passed for `clean_cli.py`, `press_cli.py`, `cli.py`, and `test_clean_cli.py` |
| Task 3 proposed source and test format | `ruff format --check` reported four files already formatted |
| Proposed source type check | `All checks passed!` |

The RED checkout was `/private/tmp/pr120-overlap-fix-qviybsgl`. The GREEN
materialization used
`/private/tmp/pr120_overlap_fix_rehearse.py`, which writes its latest checkout
to `/private/tmp/template-press-group3-execution/pr120-fix-materialized-path`
instead of overwriting the earlier session's evidence pointer.
The round-one lint correction writes its materialization to
`/private/tmp/template-press-group3-execution/pr120-fix-round1-lint-materialized-path`.

### Active Git-input preservation correction

Previous plan SHA-256:
`56549d64795b1676851e665bacde6599f3f60ed98d24450953809d31b6e6ede9`.
Reviewed behavior plan SHA-256:
`b10ca82f9323aafcf2823562e9aa5bc45bf5870725a7851e9c8d3329210ebb85`.
Current Ruff-formatted plan SHA-256:
`95c16db4ae1ac43899e50f1ceec31c22285c16bfd65e0f46be3bc26bd8e4fcbd`.

| Check | Result |
| --- | --- |
| Previous complete helper plus new active-input regressions | `7 failed, 107 passed in 75.32s`; four exact/containing `.gitignore` and two repository-include cases reached the clean interceptor, while the corrupt index executed clean and returned 1 |
| First corrected materialization | `1 failed, 113 passed in 101.55s`; all active-input guards passed, while corrupt-index snapshot capture propagated `subprocess.CalledProcessError` instead of returning exit 2 |
| CalledProcessError normalization added | Corrupt-index preflight returned exit 2; a controlled invoked-clean failure retained exit 1 and stdout/stderr forwarding |
| Second corrected materialization | `2 failed, 112 passed in 100.43s`; only explicit-null-device preview/apply failed because `/dev/null` timestamps changed between public snapshot candidates |
| Null-device inventory normalization | Maps the literal platform null device to the existing absent representation; 26 active-input, exit-phase, null, and inverse controls passed with 68 deselected |
| Inverse: grant protected membership by unrestricted `samefile` identity | `2 failed, 92 deselected in 3.16s`; preview and apply reached the clean interceptor for an ignored active `.gitignore` hardlinked to a disjoint tracked file |
| Restored exact-directory-entry membership | Hardlink cases refuse; tracked/non-ignored and case-aliased tracked entries remain allowed; the controller's independent real-clean probe is `/private/tmp/template-press-group3-execution/p10-hardlink-probe.json` |
| Final exact parser and clean-CLI materialization | `118 passed in 108.33s` |
| Final combined parser/CLI interaction command | `220 passed, 1 skipped in 300.76s`; included `test_clean_rules.py`, `test_clean_cli.py`, `test_press_cli.py`, and `test_cli.py` |
| Proposed source and test lint | Ruff check passed |
| Proposed source and test format | Ruff reported 84 files already formatted |
| Proposed source type check | `All checks passed!` |
| CI Markdown-fence formatting correction | The locked repository-wide Ruff check rejected the three-line condition at plan line 299. Ruff's required one-line reflow is the only plan-text change from commit `216061b…`; fence 5 is AST-equivalent and the other 16 Python fences are byte-identical. Post-change root checks passed: `ruff check .` reported `All checks passed!`, and `ruff format --check .` reported 172 files already formatted. |
| Materialized shared-inventory suite | `tests/rebrand/test_surface_inventory.py`: 75 passed in 86.81s; receipt `p10-materialized-inventory-tests.log` |
| Exact null-device interaction validation | The internal rereview verified that the final materialized `inventory.py` differs from the current source only by the two-line `os.devnull` normalization in `_core_excludes_path`; the downstream `None` path still pins `/dev/null`, and the 75-test shared-inventory suite passed; receipts `p10-internal-major-rereview.md` and `p10-materialized-inventory-tests.log` |
| Final docs-worktree `just check` | 1412 passed, 2 skipped in 247.86s; Ruff, `ty`, spelling, and EditorConfig passed; existing YAML warnings remained; receipt `pr120-final-just-check.log` |
| Muse exact-delta review | **APPROVE** at actual xhigh after ultra was requested, with 100 max model steps configured; receipt `muse-p10-active-inputs.log` |
| Claude Fable 5.1 bounded retry | **NOT REVIEWED** because the provider rejected the attempt for exhausted usage credits before review; receipt `fable-p10-active-inputs.json` |
| Internal `gpt-6-astra` scoped final review | **APPROVE** for spec compliance and task quality; prior R1 resolved; receipt `p10-internal-major-rereview.md` |

The exact final materialization is
`/private/tmp/pr120-overlap-fix-lint-nxss9xqc`; its pointer is
`/private/tmp/template-press-group3-execution/pr120-active-inputs-final2-materialized-path`.
The RED checkout is `/private/tmp/pr120-overlap-fix-lint-jbesfhvg`. The first
and second integration-failure checkouts are
`/private/tmp/pr120-overlap-fix-lint-pjnibvzh` and
`/private/tmp/pr120-overlap-fix-lint-ip84jkhv`. The task-specific rehearsal is
`/private/tmp/pr120_active_inputs_rehearse.py`; it derives from the prior
rehearsal and uses distinct evidence pointers, so no earlier scratch evidence
was overwritten.

These results cover the executable plan in disposable clones and the final
docs-worktree validation. A shipping-source implementation, matrix run, native
R3 result, native Windows result, commit, and PR action remain outside this
record-only correction. The exact correction has completed its available
reviews: Muse and internal `gpt-6-astra` approved it, while Fable supplied no
verdict. D-B and the decision to substitute for the unavailable Fable review
remain unresolved owner gates. The controller owns commit, push, and PR
closeout.
