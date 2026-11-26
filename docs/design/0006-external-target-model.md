# 0006 — template-press external-target model (canonical)

- **Status:** Accepted (2026-06-23). Supersedes 0004 §3–7 and 0005.
- **Decision record:** OPEN_QUESTIONS.md decision log (2026-06-15, on branch
  `feat/init-rebrand-robustness`) + phase-naming decisions (2026-06-23).

## What template-press is

A standalone rebrand/config utility, published to PyPI (`uvx template-press`),
that operates on **external target repos, one at a time**. It is NOT a Python
project template and ships no application. First target:
`smorinlabs/py-launch-blueprint` (the repo it was extracted from).

## The two phases

| Phase | Verb | Does | Deliverable |
|---|---|---|---|
| Rebrand | `press rebrand --target PATH` | identity press: files only | target compiles/imports/tests under new identity |
| Provision | `press provision --target PATH` | feature setup: repo + services | **launch-ready** repository |

`press status --target PATH` computes feature state from reality (files,
`gh` API, PyPI API) — never merely stored (design 0004 D10, retained).

## Rebrand model (this repo's current work)

1. **Source identity is config-first**: `<target>/press/press-source.toml`
   (committed in the target) is authoritative. Discovery (pyproject name,
   `[project.scripts]` key, git origin, src/flat layout) **validates** it and
   fails loudly on mismatch. Discovery never silently drives a run.
2. **Rules are generic and scan-based**: the tool carries rewrite rules
   (boundary-safe by default); it does not carry any target's identity or
   file list. Per-target overrides: `<target>/press/press-rules.toml` —
   `[[replace]]` exact glued-token rules (`pattern`/`reason`, scoped by
   `files` fnmatch globs, `paths`, `content`) and `substring_rewrite_fields`
   (a boundary-free, per-field opt-in). Identity itself is six required
   fields (`package_name`, `repo_name`, `app_name`, `author`, `email`,
   `owner`) plus four optional fields, each absent = feature off:
   `display_name` (humanized product name), `npm_name` (exact root
   `package.json` name, scope allowed), `cli_name` (exact `bin` key), and
   `cargo_names` (role-to-exact Cargo name table).
   `substring_rewrite_fields` also accepts derived display forms
   (`display_name_pascal`, `display_name_camel`, `display_name_spaced`).
   A target-authored `[rules] keep_names` list declares names independent of
   the identity, which every rewrite and scan honors; a pre-write sibling and
   glued-name preflight refuses undeclared glued or same-prefix names (across
   every field `press verify` scans) before any write (design 0008). Full
   field/rule semantics:
   [design 0008](0008-identity-variants-and-replace-rules.md); rendering
   pipeline: [design 0009](0009-substitution-table.md); operator
   walkthrough: [`press-target`](../../.claude/skills/press-target/SKILL.md).
   Node and Bun targets: [TypeScript and Bun targets
   design](../superpowers/specs/2026-11-22-typescript-bun-targets-design.md).
   BAML targets: [BAML targets
   design](../superpowers/specs/2026-11-25-baml-targets-design.md).
3. **Verify-then-mark**: after apply, a no-leak doctor pass scans the target
   for surviving source-identity tokens (changed fields only; the explicit
   `verify_ignore` list in `press/press-rules.toml` is the one sanctioned
   exemption). Any leak ⇒ exit 1 and NO receipt. The press then runs
   `press verify` on a private copy of the pressed tree that carries the new
   source-config, receipt, and origin; a verify exit 1 there ⇒ exit 1 and NO
   receipt (P17). The gate cannot establish the result in three cases, and
   the press then keeps its pre-P17 outcome: verify exits 2 on the copy,
   building the copy fails, or the target has a submodule, whose content the
   copy cannot hold, so a later `press verify` exits 1. The receipt
   (`<target>/press/press-receipt.toml`) records the verified state, and on
   success `press/press-source.toml` is refreshed to the new identity so a
   future re-press starts from a valid baseline. When declared regeneration
   commands run, the press fingerprints effective Git visibility immediately
   before the first command and revalidates it after the last. The snapshot
   records each exclusion input's origin, path, node kind, regular-file
   SHA-256, and symbolic-link text. It also records the content fingerprints
   of active repository-config sources, a SHA-256 of Git's effective ordered
   configuration, and the path and kind of every tracked index entry. The
   effective-config fingerprint detects conditional activation changes such as
   `includeIf.onbranch` after a `HEAD` change. A command that changes
   `.gitignore`, `.git/info/exclude`, the repository-local Git configuration,
   or index membership fails the press and cannot earn a receipt because the
   final doctor would otherwise scan a different surface. Global and system
   Git configuration are neutralized by the press and are not part of this
   snapshot. Intentional ignore-policy, repository-config, and index changes
   are unsupported during a press. Make and commit them separately before
   re-running the press.
   A declared `[[edit]]` command amends an ordinary rewritten, git-tracked
   file after renames and removals but before every declared regeneration.
   Its required `expect` string and the strict identity scan must hold both
   immediately after the edit and after all commands finish. Edit targets stay
   eligible for the doctor and hermetic-verify surface: the edit mechanism
   cannot grant a regeneration exemption or relaxed scan mode. The target's
   independent path-component `verify_ignore` policy still applies. Edits use
   the same pinned executable, target-root working directory, no-shell,
   deny-by-default environment, sink guards, and command-phase control/Git-
   visibility snapshots as regenerations.
   `[[regenerate]]` accepts either `file` (one excluded file) or `dir` (one
   whole generated directory rebuilt after renames, with every UTF-8 file
   post-scanned and optional `verify_exempt` + `reason`); both forms and
   `extra_exclude_files` expand `{package_name}` against source and destination
   identities. Before any write, a tracked BAML client
   (`baml_client/inlinedbaml.py` or `.ts`) without a covering `[[regenerate]]`
   or `[[remove]]` exits 2 with a suggested `[[regenerate]] dir` block.
4. **Multi-language targets must declare their languages**: when a target has
   several root manifests that declare a package identity, `[rules] languages`
   in `press/press-rules.toml` names the languages to check; without it
   `press rebrand` and `press verify` exit 2 and write nothing. The press
   supports `python`, `node`, and `rust` (there is no `"baml"` language value);
   discovery and cross-checks follow the declaration. Spec:
   [P16](../superpowers/specs/2026-11-22-explicit-target-languages-design.md).
5. **The tool never ships into the target** — no marker in the tool's tree,
   no self-prune, no self-commit.

## Superseded documents

- 0004 §3–7 (in-place `press/` directory contract, cwd-rewriting CLI) — the
  in-place operating model is replaced by `--target`.
- 0005 (TUI design) — deferred with Provision; reopens against the
  external-target model.
- Dogfood v1–v3 conclusions (py-launch-blueprint repo) — build #1 tested the
  in-place path only; its "convergence" claim was retracted.

## Provenance

Findings and the empirical 3-run matrix that proved the engine and located
the architectural defects (ARCH-01/02/03, EMP-01) live on branch
`feat/init-rebrand-robustness`: BUGS.md, EMPIRICAL_BUGS.md, EMPIRICAL_ARCH.md,
OPEN_QUESTIONS.md.
