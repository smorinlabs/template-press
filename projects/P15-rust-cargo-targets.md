# P15 — Rust and Cargo targets

- **Status:** `[~]` in progress on branch `feat/rust-targets`

Make single-crate and Cargo workspace repositories first-class `press` targets
through an optional role-keyed `cargo_names` identity table.

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Rust and Cargo targets design](../docs/superpowers/specs/2026-11-22-rust-cargo-targets-design.md)
- **Plan:** [Rust and Cargo targets plan](../docs/superpowers/plans/2026-11-22-rust-cargo-targets.md)

### Scope

- Represent every Cargo package, library, and binary name exactly, and rewrite
  both spellings of each name (`acme-core` and `acme_core`).
- Read Cargo manifests for identity, with discovery gates and a proposal step.
- Verify Rust targets independently and synthesize their source config.
- Declare lockfile handling for Cargo.lock.
- Prove single-crate and workspace targets end to end with synthetic fixtures.

### Merge order

Depends on, in merge order: P13 (`fix/hyphen-false-receipt`), P16
(`feat/explicit-target-languages`, merged), and P14 (`feat/typescript-targets`).
This branch rebases on each before its dependent task starts.

### Out of scope

- Provisioning, publishing, and automatic regeneration commands.

### Tests & Tasks

- [ ] [P15-T01] Identity table and control-file round trip
- [ ] [P15-T02] Rewrite rows
- [ ] [P15-T03] Cargo manifest reader
- [ ] [P15-T04] Discovery gates and proposal
- [ ] [P15-T05] Independent verify and synthesis
- [ ] [P15-T06] Lockfile declaration
- [ ] [P15-T07] Acceptance, CI, and docs
