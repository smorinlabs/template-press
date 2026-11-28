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
- [x] [P15-T11] Follow Rust's path rules for inline modules in the source-path check (final re-review 3 F1-F3)
      Also: Unicode inline module names (bot thread 4689117701).
      Also: `#[path]` values inside inline modules (bot thread 4689117747).
- [ ] [P15-T12] Apply Cargo's edition-2015 auto-discovery default (resolving an inherited workspace edition) in bin discovery, the compiled-file walk, and auto_target_sections, including the legacy fallback for a pathless `[[bin]]`: `src/<name>.rs` in a package without a lib, then `src/main.rs`, then `src/bin/main.rs` (bot threads 4689117656, 4690594456, 4690959568)
- [x] [P15-T13] Refuse an inferred-target rename whose destination name has both src/bin/<name>.rs and src/bin/<name>/main.rs after the press (bot thread 4689117676)
- [ ] [P15-T14] Make doc-comment scanning linear in block length: keep closure information apart from per-line starts (bot thread 4689117709)
- [ ] [P15-T15] Check Rust-declared paths whose file a path-only rule moves while the argument text stays the same (bot thread 4689117731)
- [ ] [P15-T16] Apply the rustdoc rules only to include_str! files that are doc text, without missing concat!/cfg_attr doc forms (final review N6, bot thread 4689117753)
- [ ] [P15-T17] Resolve a #[path] that uses .. inside a renamed inline module against the real directory, not its normalized form (review 3 I2)
- [ ] [P15-T18] Collect Rust path-literal candidates in one pass over the code view instead of a per-literal string_role prefix scan (quadratic: 8,000 literals take about 14 s) (bot thread 4691551858)
- [ ] [P15-T19] Find a module's item boundary outside attribute token groups, so a brace inside another attribute (#[doc = concat!{...}]) does not drop its #[path] (bot thread 4691551866; same false receipt on main)
- [ ] [P15-T21] Preflight CARGO_BIN_EXE_ tokens for declared [[bin]] targets and the conventional src/main.rs binary, so an excluded token is refused before any write instead of by the post-write doctor (bot thread 4691543021; with verify_ignore, same false receipt on main)
- [ ] [P15-T22] Refuse a crate-name token that is the prefix of a string, byte, or C-string literal (r#"", b"", br"", b'', c"") in the generic Rust rewrite, not only under [[cargo_split]] (bot thread 4691543031; same false receipt on main for a table-less target)
- [ ] [P15-T23] Judge Rust paths written inside a #[path] module file that does not end in .rs (such as bridge.inc); today only .rs files are judged, so a rewrite there can give a receipt for a failing build, as on main (cycle-3 F7 follow-up)
- [ ] [P15-T24] Check a legacy [project]-table Cargo manifest like a [package] one; today its paths are not judged, so a rewrite can give a receipt for a failing build, as on main (cycle-3 probe t9_project_table)
- [ ] [P15-T25] Refuse a rename that moves a conventional Cargo root (src/main.rs, src/lib.rs, build.rs) whose stem is a crate name, such as package main mapped to zeta, which leaves no target (bot thread 4697837215; same false receipt on main for a table-less target)
- [ ] [P15-T26] Refuse a rewrite of a dependency's package name when its path points outside the target, whose manifest the press cannot rename (bot thread 4697837250; same false receipt on main for a table-less target)
- [ ] [P15-T27] Follow a plain-string include!("x.inc") to a file that does not end in .rs, so the modules and paths it declares are judged; keep skipping include_str!/include_bytes! (bot thread 4697837258; same false receipt on main; sibling of P15-T23)
- [ ] [P15-T28] Exclude auto-discovered target files that a named [[bin]], [[test]], [[example]] or [[bench]] with another path overrides, so an uncompiled file such as tests/foo.rs cannot refuse a healthy press (bot thread 4700788542)
- [ ] [P15-T29] Refuse a [[cargo_split]] source crate name that is a Rust keyword (such as `type`), or refuse its unprovable keyword occurrences, so language syntax is never rewritten as a crate name (bot thread 4700788560)
