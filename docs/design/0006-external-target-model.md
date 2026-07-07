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

1. **Source identity is config-first**: `<target>/.press/source.toml`
   (committed in the target) is authoritative. Discovery (pyproject name,
   `[project.scripts]` key, git origin, src/flat layout) **validates** it and
   fails loudly on mismatch. Discovery never silently drives a run.
2. **Rules are generic and scan-based**: the tool carries rewrite rules
   (boundary-safe by default); it does not carry any target's identity or
   file list. Per-target overrides: `<target>/.press/rules.toml`.
3. **Verify-then-mark**: after apply, a no-leak doctor pass scans the target
   for surviving source-identity tokens (changed fields only; the explicit
   `verify_ignore` list in `.press/rules.toml` is the one sanctioned
   exemption). Any leak ⇒ exit 1 and NO receipt. The receipt
   (`<target>/.press/receipt.toml`) records the verified state, and on
   success `.press/source.toml` is refreshed to the new identity so a
   future re-press starts from a valid baseline.
4. **The tool never ships into the target** — no marker in the tool's tree,
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
