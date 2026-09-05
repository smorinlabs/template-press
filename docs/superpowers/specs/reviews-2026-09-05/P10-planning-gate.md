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
| F1 | Task 17 step 3: "add the hint at the `cli.py` catch site from Task 2 when `rules.clean` is non-empty" | The hint already exists at `cli.py:186` inside `_print_closure_refusal_prose`, guarded by `getattr(rules, "clean", ())` because `Rules.clean` did not exist yet. Message text matches the plan's expected substring exactly. | R1: replace the `getattr` with `rules.clean`; test both directions (the CLEAN review asked for the negative case; the plan had only the positive one). |
| F2 | Task 17: exit 2 "when a path is outside the target" | `_declared_rel_path` (rules.py:432) refuses absolute paths, `..`, NUL and control characters at config load, so this is an exit-2 `ValidationError` before anything runs. The CLEAN review (D5 b) also asked that the rendered string be validated again. | Task 1 validates the declared pattern; Task 2 validates the rendered path (control characters, `SafeRelPath`). |
| F3 | Task 16: "unknown placeholder `{nope}` → `ValidationError`" | Parse time has no identity to render against, but `ALLOWED_PLACEHOLDERS` (rules.py:36) and the `[[replace]]` brace-token scan (rules.py:355) give a parse-time vocabulary check with the same strictness (`{App_Name}` also refused). | Task 1 reuses that scan verbatim. |
| F4 | Task 16: "platforms honored" | Platform selection lives in `_ParsedRules` + `_select_rules` (rules.py:1213), which the plan never named; every mechanism needs a declaration wrapper and a selection line. `Rules` is constructed positionally in places, so a new field must be appended after `edit`. | Task 1 names all of `_CleanDeclaration`, `_ParsedRules.clean`, `_select_rules`, and the append-after-`edit` rule. |
| F5 | Task 17: `git --literal-pathspecs -C <target> clean -fdX -- <paths>` "echoing the exact argv first" | Every on-target git call in the codebase runs with `git_hardening_args()` (`-c core.fsmonitor=` …, safety.py:826) and `scrubbed_git_env()` (global/system config neutralized, safety.py:803), per G5. `git clean` reads the work tree, so a committed `core.fsmonitor` hook could execute without the flags. | R3: the argv carries the same prefix as `inventory._run_git` plus `--literal-pathspecs`, and the echoed line is that exact argv. Consequence recorded: the operator's global excludes file is not consulted. **Owner decision D-A below.** |
| F6 | Task 17: exit codes 0 / 2 / 1 | The plan omitted `git` unresolvable and `press/press-source.toml` missing. `check_tools.py:52` resolves git with `resolve_executable(target, "git", command_env(()))`; `load_source_config(target, None)` (config.py:95) returns `None` when absent. | Task 3 lists every exit-2 condition; `1` is reserved for "git ran and failed". R4 records that the E1 origin guard is not consulted. |
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

**D-A — git environment for `press clean` (recommendation: scrubbed).**
Context: every on-target git call runs under `scrubbed_git_env()`, which
points `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` at `/dev/null`. Evidence: a
`core.excludesFile` in the operator's global config would otherwise widen
what `git clean -X` removes, and the surface inventory that produced the E2
refusal already pins `core.excludesFile` the same way (inventory.py:148). Options:
(1) *scrubbed* — deterministic, matches the inventory's definition of
"ignored", matches every other git call; an entry ignored only by the global
excludes file is not removed. (2) *ambient* — matches the E2 remedy argv the
operator would type by hand; nondeterministic across machines. Effect of
the difference: only entries ignored solely by a global excludes file.
Recommendation: (1). Response needed: "scrubbed" or "ambient".

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
| Muse | ultra / _pending_ | _pending_ | _pending_ | _pending_ |

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

## 6. Verification record

- Empirical probe (git clean semantics): `Would remove src/pkg/__pycache__/`,
  exit 0; nonexistent pathspec exit 0 with no output; untracked non-ignored
  file survives `-X`.
- `SafeRelPath("src/{package_name}")`: accepted unchanged (`src/{package_name}`, `tests`, `build/{repo_name}` all round-trip through `SafeRelPath(...).as_posix()`), so the raw pattern can be validated before rendering.
