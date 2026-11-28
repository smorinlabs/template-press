# SDD ledger — plan: docs/superpowers/plans/2026-11-22-typescript-bun-targets.md

> Archived record of P14 execution, kept for the reasoning behind its 43
> rulings (R1-R43). It is a working log: commit IDs, task numbers, and session
> names refer to the run as it happened. The behavior it settled is documented
> in `docs/design/0008-identity-variants-and-replace-rules.md`, the
> `press-target` skill, and `docs/source/reference/cli.md`. PR #157 merged it at
> `28165f0`.

Spec: docs/superpowers/specs/2026-11-22-typescript-bun-targets-design.md
Branch: feat/typescript-targets. Start HEAD: edfef92. origin/main: c64e2e4 at start.
Owner authorized: subagent-driven execution, push, open PR. NOT merge or release.
Models: sonnet standard; opus for Tasks 4-6 (leak detection); fable final review.

## Pre-flight scan

| Scope | Produces / consumes | Finding |
|---|---|---|
| T1 self | validators, fields, half-specified guard | Step 1 uses interactive project skills; see R1 |
| T2 self | manifest reader, cross-check | `repository` must not feed fatal owner check; see R2 |
| T3 self | proposal | Needs manifest access; see R3 |
| T4 self | rows, paths, synthesis | Consistent |
| T5 self | keep helpers, content rewrite | Import limit conflicts with T6; see R4 |
| T6 self | all scans, receipt | Owns path and symlink rewrite protection; see R5 |
| T7 self | exemption, suggestion | Consistent |
| T8 self | live fixtures, CI | Consistent |
| T9 self | docs, acceptance, PR | Private details not available to subagents; see R6 |
| T1-T2 | `Identity.npm_name/cli_name` | Match |
| T1-T4 | fields flow into `_identity_rows` | Match; T4 adds matcher and paths |
| T2-T3 | `NodeManifest`, `source_kind` | Match with R3 |
| T4-T5 | `npm_name` boundary reused | Match |
| T5-T6 | keep helpers | Match with R4, R5 |
| T5-verify | `validate_keep_names` caller | See R7 |
| T7-T8 | exemption used by fixtures | Match |

## Rulings

- Ruling R1: controller registers P13 before Task 1; implementer skips Task 1 Step 1 — project skills are interactive — cost if wrong: a small tracking edit.
- Ruling R2: `Discovered.owner/repo_name` stay git-origin only; `repository` is used for warnings and `node_proposal` fallback — spec makes repository disagreement non-fatal — cost if wrong: one discovery branch.
- Ruling R3: `_resolve_source` calls `read_node_manifest` directly for a node source — avoids adding a manifest object to `Discovered` — cost if wrong: one extra file read.
- Ruling R4: `keep_names.py` may import `identity` and neutral `matcher` — Task 6 requires `classify_occurrence`, and verifier already imports `matcher` — cost if wrong: move one helper.
- Ruling R5: Task 5 protects content rewrites; Task 6 protects path-component and symlink-target rewrites and scans — spec requires all surfaces — cost if wrong: rework in Task 6.
- Ruling R6: Task 9 implementer does Steps 1, 2, 5 only; controller does private acceptance, privacy gate, push, PR — private identity must not enter subagent-authored repo work — cost if wrong: none.
- Ruling R7: `validate_keep_names` runs in both `rebrand` and `verify` before any write, using the real or synthesized destination — overrides must behave end to end — cost if wrong: one call site.

## Notes

- Sibling branches may land first: `fix/hyphen-false-receipt`, `feat/rust-targets`. Recheck origin/main before pushing.

## Progress

Ruling R8: P13 registered directly from approved scope, without project-add questions — owner already approved title and scope, and SDD forbids pausing — cost if wrong: edit one row.

Owner decision (2026-11-22, option A): merge order is fix/hyphen-false-receipt, feat/explicit-target-languages, TypeScript, Rust. Multiple root manifests exit 2 unless `[rules] languages` is declared; the guard session owns that. TypeScript moves to P14.
Ruling R9: after Task 1, controller renumbers P13 to P14 and marks spec and plan manifest precedence as superseded — owner chose A — cost if wrong: small doc edits.
Ruling R10: Tasks 2-8 continue now. Task 2 isolates manifest selection in one function and adds NO test pinning pyproject-over-package.json precedence; the plan's two precedence tests are dropped or reduced to "a [tool.*]-only pyproject does not count". Rebase onto the guard before final gates — waiting idle buys nothing — cost if wrong: rework one function.
Ruling R11: keep `Rules.keep_names`, `Discovered.source_kind`, `field_renames_paths`, `regenerate_suggestion` names stable for Rust. Exact-name rows share one longest-first tier.
Open: owner did NOT decide keep_names vs keep_hyphen_name. Do not merge them; resurface at rebase.
Hold: do not open the PR until the hyphen fix and language guard are on origin/main, unless the owner says otherwise.

Resolved: keep-list question closed. The hyphen worktree's uncommitted P13 file records `[-] [P13-T03] keep_hyphen_name removed by owner decision`; its committed b9777dd still mentions the setting. `keep_names` stays the only new keep setting.
Note: the hyphen worktree has uncommitted changes in identity.py, design 0008, and cli.md. Expect rebase conflicts in identity.py.

R9 applied: P14 renumber and superseded precedence committed at 3a6272c.

Task 1: complete (commits 6225fac..4cca2fb, review clean). Reviewer connection failed after delivering its complete Approved report; minor notes deferred to final review: assert refusal messages, broaden equality cases, stale `display_name_problem` name and placeholder comment.
Test note: use `uv run pytest -q -n auto`; serial runs exceed 30 minutes.

Ruling R12: Task 5 `validate_keep_names` also refuses (exit 2, before writes) an entry equal to `source.package_name.replace("_", "-")` or `dest.package_name.replace("_", "-")` when that differs from `package_name`; parametrize both in `test_invalid_keep_name_exits_2_without_writes`. After rebasing on P13, add a test that `keep_names = ["acme-widget-extra"]` survives press and verify beside rewritten `acme-widget`. Source: relayed by Rust session as owner-approved, not heard directly; adopted on merit because it only tightens the spec's safety limit — cost if wrong: one refusal to relax.

Task 2 implementer: 13b2c1c, DONE_WITH_CONCERNS. Presence-check concern assessed: package_name, author, and email were already undiscoverable on node targets before this task, so that route is unchanged; recheck in Task 8 live fixtures.

Task 2: complete (commits 3a6272c..13b2c1c, review clean). Minor notes deferred to final review: duplicated origin regex, thin owner/repo warning coverage, ignored return codes in stderr test.
Ruling R13: Task 3 also treats `RecursionError` from a deeply nested package.json as undiscoverable — plan Review Focus 1 says malformed manifests never produce a traceback — cost if wrong: one except clause.

Task 3: minor (deferred): rebuilds NodeManifest from Discovered in cli.py.
Task 3: minor (deferred): redundant local `main` import in test_node_discovery.py.
Task 3: minor (deferred): no test for capitalized bin such as Acme-CLI.
Task 3: fix round 1/5 started (1 open: full-proposal test assertion is near-vacuous; review head a10372b).

Task 3: fix round 1/5 (1 addressed, 0 open; commits a10372b..8e4566b)
Task 3: complete (commits 13b2c1c..8e4566b, review clean)

Task 4 implementer: e074355, 4f1438f, DONE_WITH_CONCERNS.
Ruling R14 (load-bearing, carry into Task 6): undeclared same-prefix siblings must fail BEFORE any rewrite. Today the `owner` row can turn `@acme/widget-api-extra` into `@other-owner/widget-api-extra`, then verify and press exit 0 with a receipt, and the inline doctor misses an untouched sibling. Task 6 adds one neutral preflight in `keep_names.py`, used by both `rebrand` (including dry-run) and `verify`: on the source tree, find tokens where a declared source `npm_name` or `cli_name` is followed by a `-` or `_` continuation, excluding entries in `keep_names`; any hit exits 1, writes nothing, writes no receipt, and prints the `keep_names` guidance. Owner chose fail-loud-by-default; spec anti-goal forbids a receipt over a leak — cost if wrong: one preflight to relax.
Task 4: note for Rust at rebase: `engine.RENAME_FIELDS`, `substitutions.RENAME_FIELDS`, and `doctor.PATH_FIELDS` were replaced by `identity.RENAME_FIELDS` and `field_renames_paths`.

Task 4: fix round 1/5 started (review head 4f1438f; open: Critical scoped npm_name in multi-component path gets clean receipt).
Ruling R15 (extends R14, carry into Task 6): preflight covers any token containing a declared source `npm_name` or `cli_name` with a name character on EITHER side (`pre-acme-cli`, `x-@acme/widget-api`, `acme-cli-helper`, `@acme/widget-extra`), unless wholly covered by `keep_names`. Tests: both owner cases from Task 4 review Important 1 — reviewer's recommended routing; cost if wrong: one preflight to relax.
Task 4: minor (deferred): scope-preserving press with changed owner exits 2 at press time while verify exits 0; document the limit.
Task 4: gap for Task 6/8: dedicated regeneration-scan test for new fields.

Task 4: minor (deferred): non-normalized symlink target such as `@acme/./widget-api` is not matched; assess in final review.
Task 4: carry to Task 6: verifier flags a sibling directory `packages/@acme/widget-api-extra/` but doctor does not; preflight and keep_names must handle path siblings.

Task 4: fix round 1/5 (1 addressed, 0 open; commits 4f1438f..e81f1ed)
Task 4: minor (deferred): whole-path scans in doctor.py:429 and verifier.py:557 do not skip root `press/`.
Task 4: complete (commits 8e4566b..e81f1ed, review clean; left-extended and sibling detection carried to Task 6 by R14/R15)

Owner direction (2026-11-22): rebase to pick up faster checks. PR #152 merged to origin/main at 20ec28f, including a87ef59 `perf: run just check tests in parallel`.
Ruling R16: rebase feat/typescript-targets onto origin/main immediately after Task 5 commits and before Task 5 review, because the Task 5 implementer is active in this worktree and a rebase now would rewrite its checkout — cost if wrong: one task of delay. After rebase: resolve identity.py conflicts, add the R12 `acme-widget-extra` sibling test in Task 6, rerun `just check`, and regenerate review bases from new SHAs.

Guard contract (relayed by explicit-languages session, verify against origin/main): `[rules] languages`; `languages.py` has KNOWN_LANGUAGES, SUPPORTED_LANGUAGES, LANGUAGE_MANIFESTS, detect_languages, check_target_languages, render_ignored_languages. This PR adds `node` to SUPPORTED_LANGUAGES and updates tests/docs. Declaration drives discover()/mismatches() in rebrand and verify: ["python"] leaves package.json unchecked, ["node"] does not cross-check pyproject, both checks both. No second rules load in rebrand.
Merge authority: session handoff from owner says "Do not merge or release. Steve reviews the PR." A peer relayed that Steve now approves merging. Peer relay is NOT approval. Finish, open PR, run review triage, then ask owner directly before merge.

OWNER APPROVAL (direct, 2026-11-22): "when Tasks 5-9 and checks pass, run pr-merge-flow and merge the TypeScript PR with a merge commit. This overrides the handoff's 'Do not merge or release' for the merge only. Do not release."
After verified merge: message template-press-explicit-languages-40 with PR number and merge commit. Do not start Rust or BAML.

Rebase done: feat/typescript-targets onto origin/main c80743d, old tip ddc513e saved at refs/backup/typescript-before-rebase, new tip 3714fdc. Conflicts resolved in PROJECTS.md, cli.py, verify_cli.py, identity.py, rules.py, substitutions.py. Task 5 review base is the rebased Task 4 tip 4b79f44.

Task 5 concern 4 (case/separator keep_names variants such as ACME-REPO can hide a paranoid-scanner match after Task 6): owner asked to suggest the fix to the Rust update; sent to template-press-rust-targets-d5. NOT implemented on TypeScript. Open question to owner: whether TypeScript should also carry it, since TypeScript merges first and Task 6 creates the exposure.

Ruling R17 (carry into Task 6): `validate_keep_names` normalizes each entry and identity value by case-folding and removing `-`, `_`, `.`, space; exit 2 before writes when a normalized entry equals a normalized source value, including display_name forms and the package_name hyphen form; same for real destination values; `synthetic_dest=True` still skips destination checks. Refusal cases: `ACME-REPO`, `acme_repo`, `AcmeRepo`. Control: true sibling `acme-widget-extra` accepted and survives press and verify. No Cargo cases here. Source: relayed by Rust session as owner decision, not heard directly; adopted on merit because it matches controller's recommendation and only tightens safety — cost if wrong: one refusal to relax.

Post-rebase suite at 3714fdc: 52 failed, 2414 passed, 24 skipped. Causes: fixtures with pyproject+package.json now hit the guard; IndexError from `row.provenance[0]` in rebased rewrite_with_row; row-order regression in sort-key test.
Ruling R18: Task 5 implementer does guard integration before Task 5 review. `discover(target, languages=None)` receives the guard's checked languages from the single existing rules load; python fields only when python is checked; node checks only when node is checked; both when both. `source_kind` is the first checked language in KNOWN_LANGUAGES order. Add node to SUPPORTED_LANGUAGES and update unsupported-node tests/docs — guard contract — cost if wrong: discovery signature rework.

Task 5: fix round 1/5 started (review head 23a3740; open: kept spans recomputed per row can corrupt or falsely protect; nameless package.json loses fatal cli_name cross-check).
Ruling R19 (plan-mandated finding): amend Task 5 interface. Kept spans are computed ONCE from each file's original text and carried through all rows with shifted offsets, via one per-file helper at all content-rewrite call sites. Spec "a kept occurrence is unchanged by every rewrite row" outranks the plan signature — cost if wrong: helper rework.
Ruling R20: `discover(languages=())` behaves like None so readable manifests are still checked — preserves prior exit 2 — cost if wrong: one branch.
Ruling R21: controller-confirmed gaps enter this round: with python+node and no source config, propose `npm_name` when manifest name differs from proposed repo_name and package_name; `_manifest_name_rows` and `_hyphen_rows` must not read pyproject when declared languages exclude python.
Task 5: minor (carry to Task 6): overlapping kept occurrences missed by finditer; refuse Unicode Cc/Zl/Zp in keep_names; keep_names docstring accuracy; pipeline.py keep_names consistency check.
Task 5: minor (deferred): weak RED evidence. Owner-facing limit: keeping an unscoped npm basename while changing package_name exits 1 (fail closed, same before this range); document it.

Task 5: fix round 1/5 (4 addressed, 0 open; commits 23a3740..ea59985)
Task 5: complete (commits 4b79f44..ea59985 after rebase, review clean)
Ruling R22 (carry to Task 6): with python+node and no source config, a distinct `bin` name must also be proposed as `cli_name`, the same way R21 handled `npm_name` — re-review found the press exits 0 leaving `web-cli` — cost if wrong: one proposal branch.

OWNER DIRECTION (direct, 2026-11-22): "Don't block the merge call. Just do the merge. Continue. When the time comes." At merge time, after Tasks 6-9, final review, and checks pass, run the merge directly with a merge commit. Do not pause to ask again. Do not release.

Task 6 implementer: d1259e8, report DONE_WITH_CONCERNS (2585 passed, 24 skipped; matrix green).
Ruling R23 (apply in Task 6 fix round): a no-source-config node proposal with more than one distinct `bin` exits 2 and asks for a hand-written source config plus `keep_names` for independent CLIs — identity holds one `cli_name`, and guessing could leave a second CLI behind with exit 0 — cost if wrong: one refusal to relax.
Task 6: minor (deferred): rebrand inline doctor does not scan binary content; verify does; pre-existing behavior.

Task 6: fix round 1/5 started (review head d1259e8; open: Critical preflight identity-form exemption allows receipt over leftovers; Important word-like CLI names over-refused).
Ruling R24 (narrows R15; plan-mandated finding): a preflight token is a sibling only when the declared name is joined to another name part by `-` or `_` on either side (`acme-cli-helper`, `pre-acme-cli`, `x-@acme/widget-api`, `@acme/widget-extra`). Glued alphanumerics are unrelated words under the existing boundary convention (`tsconfig.json` for `tsc`, `server` for `serve`). `/` and `.` are not joins (`bin/acme-cli.js`). Still case-insensitive — keeps every reproduced false-clean case closed without forcing English words into keep_names — cost if wrong: glued variants need a later rule; verifier's paranoid matcher still reports camelCase joins.
Ruling R25: identity-form exemption survives only for a form a row actually rewrites on that exact surface: changed field, enabled display form, path-capable field for path rows.
Task 6: minor (included in round): exclude planned [[remove]] files from preflight; add exact controller cases.
Task 6: minor (deferred): verify_cli guidance token length for separator variants; `_hunt_pattern` vs `hunt_occurs` duplication parity test.

Task 6: implementer also committed e206694 before receiving round 1; round 1 message is being processed.
Ruling R26 (extends R25): a same-prefix token wholly inside the rendered source literal of a `[[replace]]` rule that actually applies on that path and surface is rewritten, so it is exempt from the preflight — otherwise such a target can neither pass nor rewrite the token — cost if wrong: one exemption branch.

Task 6: fix commit a42ec71 (2607 passed, 24 skipped; matrix green).
Ruling R27: the preflight also treats a right-side lower-to-UPPER transition as a join (`acme-cliFoo`), matching `matcher.identity_pattern`'s camelCase tail. `press verify` already refuses that token, while `press rebrand` could write a receipt; both must agree. `tscConfig` will need `keep_names`, but `tsconfig` and `server` stay allowed — cost if wrong: one extra keep entry for camelCase names.

Task 6: fix round 1/5 (most addressed, 2 open — pure-node multi-bin receipt; hyphen-adjacent glued words over-refused; commits d1259e8..9ee4f29)
Ruling R28 (clarifies R24/R27): each side of the declared-name match must be either a real boundary (non-alphanumeric or text edge; on the right also a lower-to-UPPER transition) or a `-`/`_` join. A lowercase/digit glue on either side means the token is an unrelated word and is not a sibling: `web-server`, `observe-mode`, `vite-tsconfig-paths` pass for `serve`/`tsc`. At least one side must be a join or camelCase tail. Matches matcher.identity_pattern and suggested reviewer rule — cost if wrong: fail-open only for glued words no rewrite row or verifier would touch.
Task 6: fix round 2/5 started (review head 9ee4f29).

Task 6: implementer round 2 commit adf8058 (2638 passed, 24 skipped; matrix green).
Ruling R29 (refines R28; invariant hole, few lines): a declared value containing `-`, `_`, or `/` is multi-part and cannot be a chance English substring, so ANY name character (`[A-Za-z0-9_-]`) touching either side makes a sibling (`acme-cli2`, `acme-clients`, `xacme-cli`). R28's both-sides word rule applies only to single-token values (`tsc`, `serve`). This closes owner-row mangling of glued multi-part names, because owner can only match inside a multi-part value — cost if wrong: extra keep_names entries for multi-part glued names.

Task 6: implementer round 2 commits adf8058, 32d6dad (2650 passed, 24 skipped; matrix passed on rerun after one py-launch-blueprint clone failure with no captured error).
Ruling R30: `--acme-cli` and `acme-cli-` are refused for multi-part values — fails closed, the owner row would otherwise rewrite them, and `keep_names` is the escape — cost if wrong: an occasional keep entry.

Task 6: fix round 2/5 (2 addressed, 1 open — bare-separator siblings have no keep_names path; commits 9ee4f29..32d6dad)
Ruling R31: normalized identity refusal applies only to an entry with no leading or trailing `-`/`_`. `--acme-cli` and `acme-cli-` are explicit, boundary-exact spellings and may be kept; `acme_cli`, `Acme.CLI`, `ACME-CLI` stay refused. The refusal for bare-separator tokens prints a `keep_names` line — honors the "declare to pass" rule — cost if wrong: an explicit entry protects only that exact spelling.
Task 6: fix round 3/5 started (review head 32d6dad).

Task 6: fix round 3/5 (1 addressed, 0 open; commits 32d6dad..bf209ca)
Task 6: minor (deferred): keep_names.py:50-51 docstring line exceeds 88 characters.
Task 6: complete (commits ea59985..bf209ca, review clean)
Task 7 base: bf209ca

Task 7: minor (deferred): lockfile leak test asserts exit and receipt only, not the leak message.
Task 7: minor (deferred): pnpm suggestion prints only when the target excludes pnpm-lock.yaml.
Task 7: complete (commits bf209ca..4e5bab5, review clean)
Task 8 base: 4e5bab5

Task 8 implementer: e3a7939 (live npm/bun/pnpm pass; 2695 passed, 24 skipped; matrix green). Also added setup-node to ci.yml because full-suite live tests require npm in CI.
Task 8 finding: `bun install --lockfile-only` keeps the old workspace name in an existing bun.lock, so the suggested block cannot succeed.
Ruling R32: bun.lock suggestion becomes `["sh", "-c", "command -v bun >/dev/null 2>&1 || exit 127; rm -f bun.lock && exec bun install --lockfile-only"]` — existing repo evidence confirms Bun keeps stale workspace names, and the guard must run before deleting the lock. POSIX-only; Windows targets declare their own command. Spec Lockfiles table updates in Task 9 — cost if wrong: one suggestion string.

Task 8: minor (deferred): rules.py:140 f-string over 88 characters (E501 ignored); no test for npm/bun skip when CI unset.
Task 8: complete (commits 4e5bab5..43bb0d8, review clean)
Task 9 base: 43bb0d8. Implementer does Steps 1, 2, 5 only; controller does private acceptance, privacy gate, push, PR, merge.

Task 9 implementer: 1a562d1; make check, just check, just matrix, ruff format all exit 0.
Private acceptance PASSED on a real npm target in a scratch copy, on code through 1a562d1: press verify 0, press rebrand 0, npm ci 0, npm test 0, npm run typecheck 0, dry-run deploy 0. No config change was needed. Nothing pushed to that repository. Rerun if product code changes.

Task 9: minor (deferred): SKILL Lockfiles sentence reads as if pnpm is refused by default; cli.md omits string-form bin note; long Markdown lines.
Task 9: unverified doc claims for final review: unscoped-basename limit, scope-preserving owner limit, non-UTF-8 preflight limit.
Task 9: complete (commits 43bb0d8..1a562d1, review clean)

Final review: first run failed on ECONNRESET before reporting; resumed same reviewer on c80743d..1a562d1.

Final review (c80743d..1a562d1): ready with fixes; 0 Critical, 4 Important, 10 Minor. Reviewer verified compatibility, verifier independence, zero runtime dependencies, and public-repository safety.
Ruling R33 (I1): for single-token values, alphanumeric glue on either side still means an unrelated word; otherwise any directly touching `-` or `_` is a sibling, including bare `_name_`, `__name__`, `--name`, `name_`. Corrects R28's wrong claim that no verifier would flag these — cost if wrong: extra keep entries.
Ruling R34 (I2): carry named object-form bins into the pure-Node proposal; string-form `bin` never proposes `cli_name`.
Ruling R35 (I3): replace `_AUTHOR_RE` with linear parsing, cap input length, and read package.json with `read_regular_nofollow`.
Ruling R36 (I4): before identity comparison, strip leading/trailing characters outside `[A-Za-z0-9@/_-]`, so `"ledger-cli"` and backtick-wrapped values are refused while R31 edge-separator entries remain keepable — closes the only both-commands-clean leftover — cost if wrong: an unusual punctuated keep entry is refused.
Ruling R37: include M1 (offer both language lines), M3 limit wording, M5 document `undeclared_names`, M8 docs, and M9 generic public wording. Park M2, M4, M6, M7, M10 as non-safety follow-ups: exit codes stay fail-closed — cost if wrong: later polish.
Final fix wave started from 1a562d1.

Final fix wave commits: c1f235b..ea1da38 on 1a562d1 (2741 passed, 24 skipped; matrix green).
Ruling R38 (completes I4 within the same wave): identity comparison also removes edge `/` and `@`, so `/ledger-cli`, `ledger-cli/`, `@ledger-cli`, and `@acme` when owner is `acme` exit 2. A kept `@acme` would otherwise protect the owner token inside every scoped name — cost if wrong: a template must list full package names instead of a bare scope.
Ruling R39: generic wording also replaces the vendor name in spec non-goals.
Parked: string-form bin docs mentioning bare command exit 1 after rewrite (post-write category, no receipt); hand-written cli_name equal to string-bin derived name accepted (unprobed; no receipt risk identified).

Final fix wave complete at 7d60d85 (2765 passed, 24 skipped; make check, just check, just matrix, ruff format exit 0). Private acceptance rerun on this head.

Final fix re-review at 7d60d85: I2, I3, M1, M3, M5, M8, M9 addressed. I1 residual: non-ASCII neighbor treated as glue. I4 residual: mixed `/`/`@` plus punctuation wrappers.
Ruling R40: one small invariant-only patch despite the one-wave default, because owner's merge approval requires passing checks and both residuals give exit 0 with a receipt over a leftover. Neighbor test uses ASCII alphanumerics; edge stripping removes the union of both edge sets in one linear pass, preserving the scoped-`@` rule. Verified by reviewer probes rr1.py/rr5.py and full gates, not another broad review — cost if wrong: PR bot review catches it before merge.
Parked: `Ann <a<b@example.test>` is now undiscoverable (fails safe). Python `_zapp_`/`--zapp` receipt behavior is pre-existing and constrained by Python compatibility; report to owner.

Final patch 661b0b6 verified by controller: reviewer probes rerun against exact export show refusals with no receipt; make check, just check (2789 passed, 24 skipped), just matrix, format reported green; private acceptance rerun all exit 0; privacy search clean. Pushing and opening PR.

PR #157 opened at 661b0b6. pr-merge-flow mode: merge (owner explicit), merge commit, no release. Thread ledger starts: 0 inline at open; greptile review present. After verified merge: notify template-press-explicit-languages-40.

PR #157 cycle 1 at 661b0b6: CI red with one root cause: fixture script `node --test test/` fails on Node 22 (local Node 26 passes). Threads: 10 inline + 1 CodeRabbit outside-diff.
Thread ledger (comment id -> disposition):
- 4669979514 Codex P1 scoped basename renamed -> FIX: `@vendor/<name>` is a sibling in preflight unless kept.
- 4669979528 Codex P2 verify config rejects new fields -> FIX.
- 4670056077 SKILL display_name referent -> FIX.
- 4670056101 cli.md guard warning/fatal wording -> FIX.
- 4670056109 cli.md language detection wording -> FIX.
- 4670056138 P14 preflight qualification -> FIX.
- 4670056143 parent move relocates kept path -> VERIFY, FIX by pre-write refusal in both planners.
- 4670056147 pnpm suggestion needs exclusion -> FIX.
- 4670056150 kept name loses right boundary -> VERIFY; if only fail-closed exit 1 with no receipt, DEFER to P14 task.
- 4670056162 `node --test test/` -> FIX.
- outside-diff SKILL.md:40 `git clean -fd` in caller repo -> FIX docs.

PR cycle 1 local fixes through 457d21e (2807 passed, 24 skipped; gates green; Node 22 fixture proven). 4670056150 deferred to [P14-T09]: verify 1, press 1, no writes, no receipt.
Ruling R41: `validate_keep_names` refuses an entry that contains a declared source `npm_name` or `cli_name` as a complete token under that field's own boundary pattern, and refusal guidance never suggests such an entry. `@acme/widget-extra` stays keepable because `@acme/widget` is not a complete token there; `widget-extra@acme/widget` is refused — closes a clean receipt over a leftover — cost if wrong: an unusual composite entry must be split.
Ruling R42: the doctor recovery hint scopes clean to the target and previews first, because the printed command can delete untracked files in the caller's directory — cost if wrong: one message string.

PR cycle 1 pushed at 34c692a; all 10 threads replied and resolved; private acceptance passed on this head.

PR cycle 2 at 34c692a: CI green, mergeable clean. Findings 11 -> 1. New thread 4670366013 (PRRT_kwDOS6BR0867Afej): `zeta-tool.extra` dependency renamed with a receipt.
Ruling R43: FIX narrowly using manifest evidence. A root package.json dependency key (`dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies`) that extends declared `npm_name`/`cli_name` with `.` or `~` is a sibling and refuses before writes unless kept. Text alone cannot distinguish `zeta-tool.js` from a package, so ordinary filenames stay rewritable. Complete-token keep validation treats `.`/`~` continuation as not complete so `zeta-tool.extra` is keepable — cost if wrong: an explicit keep could preserve a dotted filename.

PR cycle 2 pushed at 8695943; thread 4670366013 replied and resolved; private acceptance passed. Accepted limit: dotted import with no root dependency key is rewritten; disclosed in PR body.

PR #157 merged: 28165f0c66d1a73fea4ebec4253a04b2a9c52608. No release cut.
