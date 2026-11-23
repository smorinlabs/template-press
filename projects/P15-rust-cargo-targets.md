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

- [x] [P15-T01] Identity table and control-file round trip
- [x] [P15-T02] Rewrite rows
- [x] [P15-T03] Cargo manifest reader
- [~] [P15-T04] Discovery gates and proposal
      Open through P15-T08.
- [x] [P15-T05] Independent verify and synthesis
- [x] [P15-T06] Lockfile declaration
- [x] [P15-T07] Acceptance, CI, and docs
- [ ] [P15-T08] Judge declared Cargo paths instead of inferred path components
      Compare rewrites on the paths manifests declare: `members`, dependency
      `path`, target `path`, and `build`. This must fix two open defects:
      a rewrite that splits `[lib] path`, `[[bin]] path`, or `build` from its
      file still earns a receipt on a crate that no longer builds, and
      owner-only targets with an auto-discovered `src/bin/acme-cli.rs` or an
      unreferenced `testdata/acme-sample/Cargo.toml` are falsely refused.
