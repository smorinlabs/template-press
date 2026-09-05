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

## 3. Why the outcome is "revise"

The 2026-09-01 tasks were correct in intent and wrong in no decision, but
they were written before P09/P12 landed and before the parallel matrix. Nine
points (R1–R9) were either silent, pointed at code that has since moved, or
relied on a claim the probe refuted. Leaving them for the implementer to
rediscover would violate the handoff's rule that tasks be implementation
ready. The spec's decisions are untouched; the non-goals (§4 of the spec)
are untouched.

## 4. Owner decisions

**D-A — git environment for `press clean`: scrubbed.** The resumed session
accepted the recommendation to continue with the scrubbed environment on
2026-09-05. Global and system Git configuration are disabled. Repository-local
ignore settings remain active, matching the existing surface inventory.
An entry ignored only by the operator's global excludes file is preserved.

**D-B — Muse review effort.** Context: the handoff requires Muse at ultra and
records that the `ultra_reasoning_effort` gate was closed on 2026-09-04 with
a one-time xhigh exception. This gate requests ultra; if the tool again
reports the downgrade, the review below records the actual effort and the
gate is not complete until Steve either grants an exception for this review
or ultra becomes available. Response needed only if the downgrade recurs.

## 5. Review log

Filled in by the gate as each review completes. "Findings" are counted as
received, not as fixes chosen.

| Reviewer | Effort requested / actual | Verdict | Required findings | Disposition |
| --- | --- | --- | --- | --- |
| Claude Fable (in-session, this document and the plan) | n/a | see §5.1 | — | — |
| Muse, pass 1 (plan at `d1f457e`) | ultra / **xhigh** (gate `ultra_reasoning_effort` reported closed) | FIX, confidence 0.8 | 3 | all three applied; two of four optional suggestions adopted (§5.2) |
| Muse, pass 2 (revised plan at `287e387`) | ultra / **xhigh** (gate still closed) | APPROVE, confidence 0.85 | 0 | no change; it verified each revision against `main` (`SafeRelPath` refuses `src/../escape` at `safety.py:215-216`; the gitfile failure test exits 128 deterministically and passes the test interceptor; the `.git` pre-check is the truthful exit 2 because `scrubbed_git_env` clears `GIT_DIR`) |
| Claude Fable, re-review of the revised plan | n/a | APPROVE | — | the three fixes and two adoptions are the only deltas; spec coverage and type consistency re-checked |
| Codex, resumed independent review | inherited session configuration; no Muse/Fable substitution | APPROVE on the plan hash below | 0 | extracted the exact gitfile helper and ran ten independent metadata cases; checked tuple shape, content preservation, task imports, and native commit ordering |

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

Muse's safety analysis (§3 of its review) independently confirmed D-A:
the inventory pins the target's own `core.excludesFile`
(`inventory.py:938-948`), which the scrubbed-environment clean reads
identically, so the scrubbed choice loses only global-excludes-ignored
entries and gains determinism.

### 5.3 Gate status

The approvals above cover `287e387` and its earlier inputs. They do not
approve the later bot-review fixes or the resumed revision. Implementation
remains gated until the final revision is independently reviewed and D-B is
settled. D-A uses the accepted scrubbed environment.

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

## 6. Verification record

- Empirical probe (git clean semantics): `Would remove src/pkg/__pycache__/`,
  exit 0; nonexistent pathspec exit 0 with no output; untracked non-ignored
  file survives `-X`.
- `SafeRelPath("src/{package_name}")`: accepted unchanged (`src/{package_name}`, `tests`, `build/{repo_name}` all round-trip through `SafeRelPath(...).as_posix()`), so the raw pattern can be validated before rendering.


### Resumed executable-plan validation

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

Final Muse/Fable review of this revision remains pending. Their older
approvals are historical. D-B still requires a completed ultra review or an
explicit owner exception for the actual effort; an unavailable review is
not an approval.
