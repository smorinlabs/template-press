# P16 — Explicit target languages

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [explicit target languages design](../docs/superpowers/specs/2026-11-22-explicit-target-languages-design.md)
- **Plan:** [implementation plan](../docs/superpowers/plans/2026-11-22-explicit-target-languages.md)

## [x] Project P16: Explicit target languages (v5.0.0)
**Goal/Requirement**: `press rebrand` and `press verify` exit 2 with no writes when a
target has several languages and declares none in `[rules] languages`.
- Declared targets behave the same through both commands.
- The refusal names the manifests found and prints the line to add.

**Out of Scope**
- Rust/Cargo, TypeScript/Bun, and BAML target support
- The hyphenated-name false receipt (P13)
- Publishing, or any push to `py-launch-blueprint`

### Tests & Tasks
- [x] [P16-T01] Parse and validate `[rules] languages`
- [x] [P16-T02] Detect root manifests and resolve declarations
- [x] [P16-T03] Guard `press rebrand` and `press verify`; declare this repository
- [x] [P16-T04] Declare languages in disposable blueprint matrix clones
- [x] [P16-T05] Document the guard and open the PR
- [x] [P16-TS01] Unit tests in `tests/rebrand/test_languages.py`
- [x] [P16-TS02] CLI tests in `tests/rebrand/test_languages_cli.py`
- [x] [P16-TS03] `just check` and `just matrix`

### Deliverable
```text
$ press rebrand --target <python-and-node-repo> --config answers.toml
error: target has several language manifests (pyproject.toml, package.json) and [rules] languages is not declared; add this to press/press-rules.toml under [rules]: languages = ["python"]
```

### Automated Verification
- `just check` passes
- `just matrix` passes

### Manual Verification
- The owner reviews the PR. After release, one `py-launch-blueprint` PR upgrades
  press and adds `languages = ["python"]`.
