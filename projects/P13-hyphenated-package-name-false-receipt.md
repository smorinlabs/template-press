# [~] Project P13: Hyphenated package-name false receipt

**Goal/Requirement**: `press rebrand` must never write a receipt while a
hyphenated form of the source `package_name` survives in the target.

- When `[project].name` is the hyphenated form, rewrite that form in content and
  paths.
- When the manifest does not prove that spelling, leave the text alone and exit
  1 with no receipt.
- When another identity field owns the hyphenated value, keep `[project].name`
  on `package_name`.
- Whole historical files stay unchanged through the existing
  `extra_exclude_files` plus `verify_ignore` rules.

**Out of Scope**

- Rust/Cargo, TypeScript/Bun, and BAML target support.
- Publishing or release work.

### Tests & Tasks

- [x] [P13-TS01] Regression tests in `tests/rebrand/test_hyphen_package_name.py`
- [x] [P13-T01] Hyphen rows in the substitution table
- [x] [P13-T02] Manifest-name row for identity collisions
- [-] [P13-T03] `keep_hyphen_name` removed by owner decision; existing rules cover it
- [x] [P13-T04] Design 0008 records the decision
- [x] [P13-T05] `just check` and `just matrix` pass
- [x] [P13-T06] PR opened for owner review

### Deliverable

```text
pyproject.toml: name = "acme-widget"  ->  name = "zeta-gadget"
press verify on the pressed target: exit 0
```

### Automated Verification

- `just check`
- `just matrix`

### Manual Verification

- Owner reviews the PR.
