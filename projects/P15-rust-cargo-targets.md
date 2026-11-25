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
- [x] [P15-T04] Discovery gates and proposal
- [x] [P15-T05] Independent verify and synthesis
- [x] [P15-T06] Lockfile declaration
- [x] [P15-T07] Acceptance, CI, and docs
- [x] [P15-T08] Judge declared Cargo paths instead of inferred path components
      Compare rewrites on the paths manifests declare: `members`, dependency
      `path`, target `path`, and `build`. This must fix two open defects:
      a rewrite that splits `[lib] path`, `[[bin]] path`, or `build` from its
      file still earns a receipt on a crate that no longer builds, and
      owner-only targets with an auto-discovered `src/bin/acme-cli.rs` or an
      unreferenced `testdata/acme-sample/Cargo.toml` are falsely refused.
- [x] [P15-T09] One-press rename of a hyphen-free crate to a hyphenated name ([[cargo_split]])
- [x] [P15-T10] Cargo placeholders in [[replace]] ({cargo_exact_<role>}, {cargo_ident_<role>}, {cargo_ident_<role>_upper})
- [ ] [P15-T11] Follow Rust's path rules for inline modules in the source-path check (final re-review 3 F1-F3)
      Also: Unicode inline module names (bot thread 4689117701).
      Also: `#[path]` values inside inline modules (bot thread 4689117747).
- [ ] [P15-T12] Apply Cargo's edition-2015 auto-discovery default (resolving an inherited workspace edition) in bin discovery and the compiled-file walk (bot thread 4689117656)
- [ ] [P15-T13] Refuse an inferred-target rename whose destination name has both src/bin/<name>.rs and src/bin/<name>/main.rs after the press (bot thread 4689117676)
- [ ] [P15-T14] Make doc-comment scanning linear in block length: keep closure information apart from per-line starts (bot thread 4689117709)
- [ ] [P15-T15] Check Rust-declared paths whose file a path-only rule moves while the argument text stays the same (bot thread 4689117731)
- [ ] [P15-T16] Apply the rustdoc rules only to include_str! files that are doc text, without missing concat!/cfg_attr doc forms (final review N6, bot thread 4689117753)
