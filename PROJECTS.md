# PROJECTS.md

Project trunk. One row per project below; detailed scope, tasks, and
references live in per-project files under `projects/`.

Route every project-state change through a project-harness skill
(`project-add`, `project-refine`, `project-audit`) rather than editing this
file by hand — see Conventions.

## Status legend

| Glyph | Meaning                | Reach for…                    |
|-------|------------------------|-------------------------------|
| `[?]` | Idea                   | `project-refine` to scope     |
| `[ ]` | Scoped, not started    | start work; flip to `[~]`     |
| `[~]` | In progress            | continue; check next task     |
| `[x]` | Completed              | leave alone                   |
| `[-]` | Decided not to do      | leave alone                   |
| `[>]` | Proceeded to successor | follow the redirect           |

## Projects

| ID  | St    | Project                                                                 |
|-----|-------|------------------------------------------------------------------------|
| P01 | `[x]` | [Init app-name rebrand robustness](projects/P01-init-rebrand-robustness.md) — per-field drift coverage (B) + derive non-contract internals (C) |
| P02 | `[x]` | [Repo simplification & organization (SIMP series)](projects/P02-repo-simplification.md) — single-purpose PRs to simplify/consolidate Justfile, docs, setup, tests, workflows, agent configs |
| P03 | `[~]` | [External-target rebrand press (clean-core rebuild)](projects/P03-external-target-rebrand-press-.md) — M0–M5 complete; PR #131 closes M4d on merge; M6 provision remains; issue #42 prerequisite satisfied |
| P04 | `[x]` | [Regenerate bun.lock during a press](projects/P04-regenerate-bun-lock.md) — neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks |
| P05 | `[x]` | [Reset rule: blank a file to a declared stub](projects/P05-reset-rule.md) — first destructive op: blank CHANGELOG-style files instead of leaking their history |
| P06 | `[x]` | [Derive checkers from one rendered substitution set](projects/P06-substitution-set.md) — one table the rewriter applies and every checker reads (issue #42) |
| P07 | `[x]` | [Platform-conditional declared commands](projects/P07-platform-conditional-declared-commands.md) — complete upon PR #131's merge; original implementation/native validation delivered in PR #79; both T07 review threads resolved |
| P08 | `[x]` | [Declared removal and declared verify exemption](projects/P08-declared-removal-and-exemption.md) — [[remove]] for blueprint-only files (#80) + verify_exempt with reason on [[regenerate]] (#81); run 4 dogfood gaps |
| P09 | `[x]` | [Declared in-place edit ([[edit]]) and command-phase snapshot gate](projects/P09-declared-in-place-edit.md) — new [[edit]] mechanism with required `expect` post-condition; snapshot gate for any declared command (E4, E11) |
| P10 | `[x]` | [Declared pre-press clean ([[clean]] paths, press clean)](projects/P10-declared-pre-press-clean.md) — restricted `[[clean]] paths` declaration + standalone `press clean` subcommand (E10) |
| P11 | `[x]` | [Directory removals ([[remove]] dir) and removal phase](projects/P11-directory-removals.md) — frozen plan-time expansion, per-directory clean check, gitlink/symlink refusal, receipt/verify parity (E5c) |
| P11A | `[x]` | [CI speed and cost optimization](projects/P11A-ci-speed-and-cost-optimization.md) — closeout effective on PR #124 merge; diagnostics and gate repairs, no performance adoption, Windows job splitting declined |
| P12 | `[x]` | [Origin guard relaxation, closure diagnostics, warnings and docs](projects/P12-origin-guard-and-diagnostics.md) — base and four corrections merged; six follow-ups declined by owner on 2026-09-10 with limitations recorded |
| P13 | `[x]` | [Hyphenated package-name false receipt](projects/P13-hyphenated-package-name-false-receipt.md) — no receipt while a hyphenated package name survives |
| P14 | `[x]` | [TypeScript and Bun targets](projects/P14-typescript-bun-targets.md) — package.json discovery, exact npm and CLI names, keep_names, declared lockfile exemptions |
| P15 | `[~]` | [Rust and Cargo targets](projects/P15-rust-cargo-targets.md) — single-crate and workspace Cargo repositories, optional role-keyed `cargo_names` identity table |
| P16 | `[x]` | [Explicit target languages](projects/P16-explicit-target-languages.md) — multi-language targets must declare `[rules] languages` or press exits 2 |
| P18 | `[ ]` | [One-press renames to names containing the source](projects/P18-one-press-contained-renames.md) — Allow a new name that contains the old one, for every identity field. |
| P20 | `[x]` | [Ask Cargo which files it compiles](projects/P20-cargo-metadata-targets.md) — replace the hand-written Cargo target and compiled-file rules with cargo metadata |

- [x] **P17** — [Pressed-target verify false receipt](projects/P17-pressed-target-verify-false-receipt.md) — no receipt when `press verify` would exit 1 on the pressed target
- [x] **P19** — [BAML targets](projects/P19-baml-targets.md) — Press BAML repos: regenerate the client, refuse glued old names before writing

## Conventions

Planning system: **Superpowers** — specs/plans live under
`docs/superpowers/specs/`. Per-project `**References**` blocks point there.

### Project workflow skills (plugin: project-harness)

- `using-project-harness` — bootstrap: when to use which skill below
- `project-next` — orient: what's in progress, what's next, what's recently touched
- `project-add` — capture an idea (≤3 questions, reserves the ID with a commit)
- `project-refine` — flesh out / scope / decompose an existing project
- `project-audit` — verify state matches conventions; fix per finding
