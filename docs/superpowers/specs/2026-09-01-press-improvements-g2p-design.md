# template-press improvements from the gmail2pdf bootstrap — design spec

Date: 2026-09-01 · Status: decided (Steve, 2026-08-30 … 2026-09-01) · Base: v4.0.0 (`a88cff4`) · Branch: `fork/press-improve-g2p`

## 1. Purpose

Stage 1 of bootstrapping `smorinlabs/gmail2pdf` from py-launch-blueprint with template-press 4.0.1 recorded 21 hardships in the fork's `docs/blueprint-feedback-log.md`. Eight concerned the press engine (E1–E8). Each got an independent adversarial review (opus; Codex for E2), three follow-ups surfaced (E9, E10, E11), and every item was decided one at a time. This spec records the decisions and the review constraints the implementation must satisfy. Items that turned out to be py-launch-blueprint work (E6, E7, E4's declarations) are listed in §5 and are out of scope here.

Vocabulary: **source identity** = the template's names in `press/press-source.toml`; **destination identity** = the answers file passed with `--config`; **declared command** = argv listed in a `[[regenerate]]` (today) or `[[edit]]` (new) table; **surface inventory** = tracked files plus non-ignored untracked files, from `git ls-files`.

## 2. Decisions

### E1 — origin-remote guard (`cli.py:_resolve_source`, `discovery.py`)
Engine change.
- Thread the destination identity into `_resolve_source(target, override, accept_discovery, dest)`; `dest = None` when `--config` is absent → behavior unchanged. The answers file is loaded before the guard (hoist of `load_answers`, `cli.py:240`); a malformed answers file now reports first — exit 2, no writes.
- For `owner` and `repo_name` only: a discovered value that disagrees with the source-config is accepted iff it equals the destination's value for that field. Exact comparison (case-different origin still refuses; documented). Print a notice naming field, source value, origin value. Record in the receipt: `[press] origin_named_destination = ["repo_name", …]`.
- New flag `--accept-origin-mismatch` (name provisional): when origin's `owner`/`repo_name` equals neither identity, proceed anyway; print, per field, source / repo / destination values plus a warning; record `[press] origin_mismatch_accepted = [...]` in the receipt. The flag never applies to `package_name`, `app_name`, `author`, `email` — those mismatches exit 2 regardless. Distinct from `--force`.
- `mismatches()` semantics unchanged (`press verify` uses it, `verify_cli.py:225-226`).
- Documented blind spot: template repo renamed upstream without a package rename, stale source-config, origin = destination → accepted (E9 covers the warning).
Tests (4): accepted state exits 0 with notice + receipt row; unrelated origin exits 2 (and exits 0 with the flag, with the per-field print and receipt row); blind-spot scenario asserted as exit 0 with a comment; no-`--config` discovery-proposal path unchanged (`tests/rebrand/test_cli.py:56-63`, `:707`).

### E2 — rename-closure refusal diagnostics (`substitutions.py:_prefix_closure`)
Engine change, diagnostics only; the refusal stays.
- Aggregate only authorization findings (nodes absent from the inventory; uninventoried empty directories); raise once after a complete walk. Gitlink pre-check and structural refusals (missing node, unreadable directory, inventory-kind mismatch) stay immediate.
- Cap the rendered list at 20 paths; carry `total` and `truncated`; render hostile filenames safely; keep the substring `absent from the authorized surface`.
- Remedy rendered as literal-pathspec argv: `git --literal-pathspecs -C <target> clean -ndX -- <prefix>` (preview) and `-fdX` (remove), labeled "destructive, and broader than the paths listed — run only if the preview shows nothing you keep". `-X`, never `-x`. When `[[clean]]` rules are declared, the CLI layer appends "declared clean rules exist — run `press clean` first".
- Typed `SafetyError` subclass `RenameClosureUnauthorized` with `code = "rename_closure_unauthorized"`, `source_prefix`, `findings: [{kind, path}]`, `total`, `truncated`, `phase`; serialized under an opt-in `--diagnostics-json` flag (schema versioned, lossless path encoding); exit stays 2. Dry-run still exits 2 and never prints the success terminator.
- Rejected: carry, delete, `--clean-ignored`, default-authorized globs, skip ignored nodes, non-refusing dry-run.
Tests (Codex list, 8): aggregation of two ignored leaves + one empty dir (count, cap, kinds, legacy substring); gitlink still wins; each structural refusal immediate; `test_substitution_safety.py:107` preserved; dry-run and apply exit 2 with the same structured code and no writes; hostile filename round-trip; `git clean -X` integration; focused suite + `just check` + `just matrix`.

### E10 — `[[clean]]` (new mechanism, restricted v1)
- Declaration: `[[clean]] paths = ["src/{package_name}", "tests"]` (+ optional `platforms`); placeholders render from the **source** identity because `press/press-rules.toml` is never rewritten (ROOT_CONTROL). Reject unknown placeholders and control characters.
- The engine itself runs `git --literal-pathspecs -C <target> clean -fdX -- <paths>`; no arbitrary argv in v1 (arbitrary argv is a separate future increment requiring surface-snapshot equality + `git status --porcelain -z` + hidden-bit sweep via `validate_visibility_state`, `regen.py:760`).
- Standalone subcommand `press clean [--target] [--show]`; never a phase inside `press rebrand` (dry-run/apply parity, `cli.md:40`). `--show` prints the rendered command and the output of `git clean -ndX -- <paths>` and exits 0 without removing anything. Without `--show`, `press clean` echoes the command before running it.
- Ordering enforced structurally: no stamp file; the E2 refusal names `press clean` when rules are declared.
- `press verify` skips clean by construction (sandbox receives inventoried entries only, `inventory.py:1011`). `press check-tools` reports `git` for `[[clean]]` rules. Receipt records the declared rule as `[[press.clean]] paths = [...]` — declared, never "ran".
- Add `"clean"` to `_ROOT_KEYS` (`rules.py:264`).
Tests: parser (paths list, placeholder rendering, unknown placeholder refused, platforms); `press clean --show` removes nothing and lists exactly `git clean -ndX` output; `press clean` removes ignored paths under the declared paths and nothing inventoried (assert surface snapshot equal before/after); E2 message names `press clean` iff rules declared; verify unaffected; check-tools row.

### E3 — post-apply formatting
Docs + test only. `press-target` SKILL.md step 6: run the target's formatter before the first commit. `docs/source/reference/cli.md` `[[regenerate]]` section: one rebuilt output, excluded from rewrite; not a hook for repo-wide tools; formatters run in the target after the press. Test (`tests/rebrand/test_verify_exemption.py`): a `[[regenerate]]` whose `file` is an identity-bearing source file added to `extra_exclude_files` is refused at plan time.

### E4 — `[[edit]]` (new mechanism) with E11 folded in
- Declaration: `[[edit]] file = "pyproject.toml"  command = ["uv", "version", "0.1.0", "--frozen"]  expect = 'version = "0.1.0"'` (+ optional `env`, `platforms`). `file` must NOT be in `exclude_files` (mirror of the regenerate check with the inverted message); `verify_exempt`/`scan` keys are not accepted; `expect` is required and must be a non-empty printable string.
- Phase: all edits run as a fixed phase **before** all regenerations, after renames; declaration order within edits. Edited paths translate through renames like regenerate outputs.
- Runner: `execute_regenerations`' machinery (`command_env`, `resolve_executable`, exit-code failure, sink guards). Post-conditions: exists, regular, UTF-8, no source-identity leak (`scan_regenerated_output`), **and** `expect` occurs as a substring of the edited file. Failure withholds the receipt and restores control files.
- Not verify-exempt: an edited file stays in the whole-tree doctor and in `press verify`'s scan; `exempt_regenerated_paths` never sees edits. Receipt: `[[press.edit]] file = … argv = [...] expect = …`. Plan renders `[edit   ] <file> — <argv>` with the pinned executable. `check-tools` covers edit commands. Add `"edit"` to `_ROOT_KEYS`; `_validate_writer_overlaps`: an edit target may not also be a reset/remove/regenerate target.
- E11: gate `snapshot_control_files`/`snapshot_visibility_state` (`cli.py:481-482`) and the dependent revalidation and `restore_control_files` calls on `bool(edit_plans) or bool(regen_plans)`.
Tests: parser refusals (excluded file; missing `expect`; `verify_exempt`/`scan` present); command exits nonzero → no receipt; `expect` absent after command → no receipt; command rewrites the destination identity away → leak post-condition fails; edit under a renamed prefix; edits-only rules whose command appends to `.gitignore` → visibility revalidation fails, control files restored, no receipt (E11); R3 self-press with `[[reset]] .release-please-manifest.json` + `[[edit]] pyproject.toml` + `[[regenerate]] uv.lock` → all three mirrors read `0.1.0`.

### E5 — multi-file removals (`rules.py:_parse_remove`, `remove.py`)
- (a) Plan-time non-fatal warning: for each tracked directory whose files are all rewritten and no rule removes or resets anything under it: `warning: N tracked files under <dir>/ will be rewritten to the new identity and no rule removes or resets them — declare [[remove]] or [rules] verify_ignore if this is template history`.
- (b) `render_remove_plan` (`remove.py:102-108`) prints per-directory counts.
- (c) `[[remove]] dir = "research"  reason = "…"` — distinct from `file`; six constraints: expansion over `tracked_paths()` frozen into the rule at plan time; per-directory clean check (`git status --porcelain -- <dir>` non-empty, incl. `??`, → refuse); gitlink/symlink hard refusal; `rmdir` of emptied directories; every expanded path in the receipt as its own `[[press.remove]]` row; verify reads the expanded set. Phase question decided inside (c): proposed — removals run after `[[reset]]` and before the rewrite; the rename closure excludes removed paths; verify mirrors the phase; couplings to respect: `stub_file == remove.file` (`rules.py:700`), closure revalidation (`substitutions.py:591-609`), receipt/verify expansion (`receipt.py:126-155`, `verify_cli.py:473-493`).
- (d) This repo's `press/press-rules.toml` declares removals for `projects/P01…P08*.md` and `docs/research/*` so the R3 self-press stops rebranding template history.
- Globs rejected.
Tests: (a) warning appears for an undeclared template-history directory and not for a declared one; (b) counts; (c) a `[[replace]]` rename that moves a file into a `dir` expansion between plan and apply → unlinked set equals the dry-run set exactly, receipt names each path; untracked operator file inside the dir → refuse; mid-removal `SafetyError` → no receipt; (d) R3 green.

### E8 — verify vs an untracked symlink
Verify was correct (the symlink was not ignored: `node_modules/` matches directories only). Engine: on any finding for an untracked entry, run `git check-ignore --no-index -v -- <path>` and `-- <path>/`; when the first is "not ignored" and the second names a pattern, append a note: the pattern matches directories only, `git add -A` would commit this entry, remedies (ignore without trailing slash; remove the link; `verify_ignore`). Read-only; pass/fail unchanged. Docs: `cli.md` "The ignore set" note; `press-target` troubleshooting: `bun install --frozen-lockfile` in worktrees. Test: untracked symlink matching a dir-only pattern **is** enumerated, copied to the sandbox, and yields `Finding(where="symlink", field="app_name")` with the note. Log #15 → operator error / docs gap.

### E9 — hyphen boundary
Not a matcher bug (`identity.py:186-210`: separators keep compound forms rewritable by design). (a) E1's blind-spot test asserts the `py-launch-blueprint-2` scenario as exit 0. (b) Plan-time warning when a source value occurs only as a separator-joined prefix of a longer token and never as a whole token: `warning: repo_name 'py-launch-blueprint' occurs only as a prefix of 'py-launch-blueprint-2' (N places); if the template was renamed, update press/press-source.toml`.

**(b) amendment (fix round 1, task 5, both reviews concurring):** the continuation is a hyphen or underscore followed by an alphanumeric ONLY — a `.` right after the value is an extension or domain suffix (`demo-widget.git`, `template-press.svg`, `name.toml`), not a rename continuation, and classifies whole-token. Excludes `app_name` **and** `app_name_upper` (both patterns already permit their own designed continuations — `app_name`'s right boundary blocks a trailing hyphen; `app_name_upper`'s blocks a trailing hyphen too, and its own designed usage is `_`+alphanumeric, e.g. `_PRESS_COMPLETE`, `PRESS000`). Rendered display forms (`display_name_spaced`/`display_name_pascal`/`display_name_camel` — whichever the table actually carries, i.e. enabled by `[rules] display_forms` and not equal to their destination) are checked with the identical rule alongside the plain identity fields, not skipped: the same stale-rename shape can hide behind a spaced display name (`Demo Widget` -> `Demo Widget-2` upstream) as easily as behind a hyphenated repo_name.

## 3. Grouping and tracking (Steve, 2026-09-01)
Three PR groups by risk, `just check` + `just matrix` after each:
- PR1 — no behavior change: E2 diagnostics, E3 docs+test, E5 (a)(b)(d), E8, E9.
- PR2 — guard: E1.
- PR3 — new mechanisms, one PR each: E4+E11 `[[edit]]`; E10 `[[clean]]`; E5(c) `[[remove]] dir`.
PROJECTS.md via `project-add`: P09 `[[edit]]` (+E11), P10 `[[clean]]`, P11 `[[remove]] dir` (+phase), P12 guard + diagnostics + docs.

## 4. Non-goals
Arbitrary-argv `[[clean]]`; a `[[set]]` scalar rule; `version` as an identity field; verify skipping ignored/untracked entries; `press clean` inside `rebrand`; `[[remove]]` globs; changing matcher boundaries.

## 5. Parked for py-launch-blueprint
E6 identity-free README/POST_INIT stubs pointing at `press/press-receipt.toml` `[press.from]`, `[[remove]]` the `new-python-project` skill, matrix test; E7 version assert in `scripts/regen-bun-lock.sh` before `rm -f bun.lock`, reconcile `mise.toml`/`.flox` with the 1.3.5 pin; E4 declarations (`[[reset]] .release-please-manifest.json`, `[[edit]] pyproject.toml`, ordering before `uv.lock`); `.gitignore` `node_modules` without slash; runbook: `press clean` before pressing, `bun install --frozen-lockfile` in worktrees, genesis via PR.

## 6. Review artifacts
Adversarial reviews (session scratch, to be attached to the PRs): E1-review, E1-options-review, E2-review, E2-codex-review, E3-review, E4-review, O3-review, CLEAN-review, E5-review, E6-review, E7-review, E8-review.
