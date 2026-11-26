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
