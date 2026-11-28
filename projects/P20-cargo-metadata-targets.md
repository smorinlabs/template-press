# P20 — Ask Cargo which files it compiles

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [external target model](../docs/design/0006-external-target-model.md)
- **Design:** [identity variants and replace rules](../docs/design/0008-identity-variants-and-replace-rules.md)
- **Prior art:** [P15 Rust and Cargo targets](P15-rust-cargo-targets.md)
- **Code:** `src/template_press/rebrand/cargo_manifest.py`, `src/template_press/rebrand/substitutions.py`

## [x] Project P20: Ask Cargo which files it compiles

### Goal

Stop guessing Cargo's target roots and discovery rules in Python. Read target
roots, kinds, names, and workspace members from `cargo metadata --format-version 1 --no-deps`
(working offline), and seed the Rust source-path check from those exact roots.

- Keep the press's own Rust parser only for what Cargo metadata cannot report:
  path literals inside each file (`mod name;`, `#[path]`,
  `#[cfg_attr(..., path = ...)]`, `include_str!`, `include_bytes!`, `include!`)
  and the walk from each target root to reached files (including non-`.rs`
  files reached via `#[path]` or `include!`).
- Decide, implement, and document what happens when `cargo` is missing or
  fails: fall back to the hand-written manifest/target walk and refuse where
  the fallback cannot prove safety.
- Preserve the project's safety contract: no false receipts, no regressions on
  healthy targets (spec anti-goal 1), zero runtime dependencies, and
  `verifier.py` independence.
- Close every applicable P15 follow-up task resolved by this change, with tests
  proving each one.

### Out of scope

- Adding any runtime Python dependency.
- Network access during `cargo metadata` or tests (must work offline).
- Changing `verifier.py` to import `substitutions`, `engine`, or `doctor`.
- Unrelated P15 follow-ups that belong to doc-comment parsing, quadratic
  scanning, or non-Cargo-discovery areas unless directly addressed here.

### Tests & Tasks

- [x] [P20-T01] Compare `cargo metadata --format-version 1 --no-deps` against `_compiled_rust_files` on synthetic targets
- [x] [P20-T02] Add Cargo metadata reader with safe offline invocation and documented fallback when `cargo` is missing or fails
- [x] [P20-T03] Seed compiled Rust target roots, target discovery, and `CARGO_BIN_EXE_` checks from Cargo metadata (and close matching P15 follow-ups with failing tests first: P15-T12, T21, T24, T25, T28, T30, T31)
- [x] [P20-T04] Follow non-`.rs` files reached via `#[path]` and `include!` in the compiled-file walk (P15-T23, P15-T27)
- [x] [P20-T05] Verify parity against `origin/main` with real Cargo (`CARGO_BUILD_WARNINGS=deny`, `pytest -m slow`, `just check`, `just matrix`)
- [x] [P20-T06] Update design doc `0008`, `press-target` skill, `AGENTS.md`, and P15/P20 tracking
