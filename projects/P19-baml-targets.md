# P19 — BAML targets

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [BAML targets design](../docs/superpowers/specs/2026-11-25-baml-targets-design.md)
- **Design:** [external target model](../docs/design/0006-external-target-model.md)
- **Design:** [identity variants and replace rules](../docs/design/0008-identity-variants-and-replace-rules.md)
- **Depends on:** P13, P14, P15, P16, P17
- **Prior art:** [P11 directory removals](P11-directory-removals.md) (`[[remove]] dir` symlink/gitlink refusal rules)
- **Prior art:** [P18 one-press contained renames](P18-one-press-contained-renames.md) (explicitly out of scope here)

### Scope

- Branch `feat/baml-targets` (worktree `~/c/template-press-baml-targets`).
- Behavior changes: targets that pre-press `press verify` already flags now exit 1
  before writing; tracked BAML clients with no covering `[[regenerate]]` or
  `[[remove]]` rule exit 2 before writing.
- **Glued-name preflight (all target languages, scope (i)):** extend
  `check_target_keep_names` to cover the exact field set `press verify` scans so
  glued old names exit 1 with no writes and rewrite/keep guidance, without newly
  refusing any target that passes pre-press `press verify`.
- **`display_name_pascal`:** allow `display_name_pascal` in
  `substring_rewrite_fields` consistently across validation, rewrite, doctor, and
  verify.
- **`[[regenerate]] dir`:** support whole-directory regeneration (mutually exclusive
  with `file`) — excluded from text rewrite, preflight, and doctor; deleted and
  rebuilt after `apply()`; every generated file scanned; `verify_exempt` + `reason`,
  receipt recording, and path/overlap/symlink/gitlink guards.
- **`{package_name}` in regeneration paths:** allow `{package_name}` in
  `[[regenerate]]` `file`/`dir` and `extra_exclude_files` (not
  `extra_exclude_dirs`) so repeat presses work for in-package clients.
- **Undeclared tracked BAML client refusal:** refuse tracked
  `baml_client/inlinedbaml.py` or `.ts` at any depth when uncovered by
  `[[regenerate]]` or `[[remove]]` (exit 2 before writing, with a suggested
  `[[regenerate]] dir` block).
- **Diagnostics & docs:** fix the regeneration failure message ("regeneration of
  `<path>` failed" instead of "lockfile"), document the BAML recipe in `docs/` and
  the `press-target` skill, and update design docs `0006` and `0008`.
- **Verification:** test-first unit/CLI/property tests, live `baml-cli` acceptance
  tests (Python and TypeScript, root and in-package, repeat press), `just check`,
  and `just matrix`.

### Out of scope

- A `baml` value in `[rules] languages` (host manifest only when P16's guard
  applies).
- Built-in or hidden BAML commands, or running any command during `press verify`.
- A declared `[identity.baml_names]` map (kept in reserve for glued names not
  derived from `display_name`).
- Bare `display_name` or `display_name_camel` in `substring_rewrite_fields`.
- Live model calls, other BAML generators (Go, Ruby, REST), or `baml-cli` versions
  beyond the pinned fixture version.
- One-press contained renames (tracked in P18).
- Releasing or publishing.

### Open questions

All eight design decisions are approved; these four builder-level details will
be resolved in the implementation plan:

- How the paranoid field set is shared between `verifier.py` and
  `keep_names.py` without breaking design-0008 module independence.
- Exact receipt fields for a `[[regenerate]] dir` entry.
- Whether an absent or wholly gitignored client directory is regenerated in
  place or handled through the existing `[[clean]]` recipe (both paths tested).
- Ordering of the new glued-name preflight relative to existing keep-name
  checks, and guidance wording beyond the spec example.

### Tests & Tasks

- [ ] [P19-TS01] Failing tests for glued-name preflight across Python, TypeScript, Rust, and BAML fixtures, negative cases (`substring_rewrite_fields`, `keep_names`, `[[verify.ignore]]`, unrelated words), fixture-corpus scope-(i) property test, and verifier/keep-name module independence
- [ ] [P19-T01] Share the paranoid verify field set neutrally (`verify_config.py`) and extend `check_keep_surfaces` / `check_target_keep_names` + refusal guidance for glued old names (Decision 1, scope (i))
- [ ] [P19-TS02] Failing tests for `display_name_pascal` in `substring_rewrite_fields` across validation, rewrite, doctor, regeneration scan, and verify
- [ ] [P19-T02] Accept `display_name_pascal` in `substring_rewrite_fields` across rules, substitutions/pipeline, doctor, regen, and verify (Decision 2)
- [ ] [P19-TS03] Failing tests for `{package_name}` in `[[regenerate]]` `file`/`dir` and `extra_exclude_files`, including preflight rendering and repeat press
- [ ] [P19-T03] Render `{package_name}` in `[[regenerate]]` paths and `extra_exclude_files` (source and destination coordinates), rejecting unknown placeholders and `extra_exclude_dirs` (Decision 4)
- [ ] [P19-TS04] Failing tests for `[[regenerate]] dir`: schema/overlap/symlink/gitlink refusals, no text rewrite/preflight/doctor scan, delete-before-run, full-directory post-scan, absent/gitignored vs `[[clean]]` paths, `verify_exempt` + `reason`, receipt fields, and `check-tools`
- [ ] [P19-T04] Implement `[[regenerate]] dir` across rules, inventory/engine/doctor/verifier, `regen.py`, `receipt.py`, `check_tools.py`, `cli.py`, and `verify_cli.py` (Decision 3)
- [ ] [P19-TS05] Failing tests for undeclared tracked BAML client refusal (Python and TypeScript at root and nested depth; covered by `[[regenerate]] dir`/`file` or `[[remove]]`; gitignored not refused) and regeneration failure message wording
- [ ] [P19-T05] Refuse undeclared tracked BAML clients with exit 2 and suggested `[[regenerate]] dir` block (Decision 8), and update the regeneration failure message from "lockfile" to `"regeneration of <path> failed"` (Decision 6)
- [ ] [P19-TS06] Gated live `baml-cli` acceptance tests: Python and TypeScript clients, root and in-package, press, regenerate, target's own test, `press verify`, and repeat press
- [ ] [P19-T06] Document the BAML recipe in `docs/` and `.claude/skills/press-target/SKILL.md`, and update `docs/design/0006-external-target-model.md`, `docs/design/0008-identity-variants-and-replace-rules.md`, and `AGENTS.md` (Decisions 5 & 7)
- [ ] [P19-T07] Verify `uv run ruff format --check .`, `just check`, and `just matrix` pass, then open the PR for owner review
