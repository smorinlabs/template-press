# P18 — One-press renames to names containing the source

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [substitution table](../docs/design/0009-substitution-table.md)
- **Design:** [press verify](../docs/design/0007-press-verify-design.md)
- **Design:** [identity variants and replace rules](../docs/design/0008-identity-variants-and-replace-rules.md)
- **Project:** [P06 substitution set](P06-substitution-set.md)
- **Code:** `src/template_press/rebrand/pipeline.py` `_validate_dependencies` (stale-source check)
- **Code:** `src/template_press/rebrand/verifier.py` `_substring_occurrences` and `scan`
- **PR:** [#158](https://github.com/smorinlabs/template-press/pull/158) (owner decision Q4.A kept the rule there and tracked it here)

## [ ] Project P18: One-press renames to names containing the source
**Goal/Requirement**: An identity field that opts in can take a new value that
contains its old value in one press, such as `acme-core` to `acme-core-next`.
Today the stale-source check refuses these renames with exit 2 before any
write and tells the operator to press in two steps.
- Opt-in syntax: `[rules] allow_contained = ["repo_name", "cargo_names.core"]`.
  An unknown field or Cargo role exits 2.
- Occurrences of the new value are kept spans at rewrite time as well as in
  the checks: content, every path-rename pass, and symlink text.
- A pre-write check refuses (exit 2) when the new value already appears in the
  target. It runs only when this press actually contains, and it scans the
  doctor's surfaces, including symlink text and binary files.
- The two-step workaround no longer corrupts text that already holds the new
  value. Today `"acme-repo-next is the planned successor"` becomes
  `"acme-repo-next-next ..."` with press 0 and verify 0; this defect exists
  on `main`. The general guard must not refuse a legitimate back-press.
- `press verify` needs no exemption; it self-presses the current identity.

**Out of Scope**
- Cross-field containment, such as a Cargo name `zeta-acmeapp` while
  `app_name` is `acmeapp`. It stays refused: kept spans come from the
  original text only, so a later shorter row rewrites inside text a longer row
  just wrote (`zeta-zeta`, press 0, verify 0).

### Open questions
- How do the regeneration output scan (`regen.py:821`) and the reset scans
  (`reset.py:110`, `reset.py:189`) become variant-aware?
- Should a self-overlapping new value (`acme` to `acme-acme`) be refused?
- Should the receipt record the full rename lineage?

### Notes
Spike (read-only) verdict: safe with changes. Own-field containment works
only if new-value occurrences are kept spans during rewrite too; a
checks-only exemption never terminates the path-rename loop
(`pipeline.py:734`). Other checks to handle: destination stability
(`pipeline.py:520`) and the path-graph self edge.

### Tests & Tasks
