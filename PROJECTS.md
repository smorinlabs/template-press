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
| P03 | `[~]` | [External-target rebrand press (clean-core rebuild)](projects/P03-external-target-rebrand-press-.md) — rebuild as standalone press: rebrand → provision, verify-then-mark |
| P04 | `[x]` | [Regenerate bun.lock during a press](projects/P04-regenerate-bun-lock.md) — neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks |
| P05 | `[x]` | [Reset rule: blank a file to a declared stub](projects/P05-reset-rule.md) — first destructive op: blank CHANGELOG-style files instead of leaking their history |
| P06 | `[x]` | [Derive checkers from one rendered substitution set](projects/P06-substitution-set.md) — one table the rewriter applies and every checker reads (issue #42) |
| P07 | `[ ]` | [Platform-conditional declared commands](projects/P07-platform-conditional-declared-commands.md) — platform-scoped rules; only matching platform triggers |

## Conventions

Planning system: **Superpowers** — specs/plans live under
`docs/superpowers/specs/`. Per-project `**References**` blocks point there.

### Project workflow skills (plugin: project-harness)

- `using-project-harness` — bootstrap: when to use which skill below
- `project-next` — orient: what's in progress, what's next, what's recently touched
- `project-add` — capture an idea (≤3 questions, reserves the ID with a commit)
- `project-refine` — flesh out / scope / decompose an existing project
- `project-audit` — verify state matches conventions; fix per finding
