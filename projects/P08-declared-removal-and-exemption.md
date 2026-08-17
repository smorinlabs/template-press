# P08 — Declared removal and declared verify exemption

- **Status:** `[~]` in progress

Close the two engine gaps the py-launch-blueprint Run 4 dogfood filed:
forks inherit blueprint-only files the press cannot delete (#80), and any
declared regeneration beyond the lockfile cap makes hermetic verify
structurally fail (#81).

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Tickets:** issue #80 (`[[remove]]` mechanism) · issue #81 (verify
  exemption cap)
- **Evidence:** py-launch-blueprint
  `docs/research/0004-template-press-dogfood-log.md` Run 4 — PROBLEM-26
  (blueprint-guard.yml / init-integration.yml failed in the pressed
  instance's CI until hand-deleted) and PROBLEM-24/-28 (the proven
  `.ambr` `[[regenerate]]` reverted because verify's exemption cap covers
  only `uv.lock`/`bun.lock`)
- **Cap rationale being extended, not discarded:** commit `7f0b4aa`
  (exemption requires BOTH the tool cap AND the declaration; exempt files
  are listed as not-verified in report, `--json`, and receipt) and
  [P04 §TS09/T10](P04-regenerate-bun-lock.md)
- **Downstream consumer:** the py-launch-blueprint full-conform campaign
  (its P06), gated on the v3.6.0 release of this project

### Scope

**T1 — `verify_exempt` (issue #81, decided: declared + reason).** An
opt-in `verify_exempt = true` key on `[[regenerate]]`, valid only with a
non-empty `reason`; `reason` without `verify_exempt` is rejected (no
meaningless config). The tool cap (`REGENERATE_EXEMPTIBLE`) stays the
silent default; a declared exemption is the loud, committed, reviewed way
to buy coverage-gap visibility for any other regenerated output. The
declared reason flows into the verify report's not-verified listing,
`--json`, and the receipt's exempt records.

**T2 — `[[remove]]` (issue #80).** Declared file removal mirroring
`[[reset]]`'s shape and guards: `file` + required `reason` (+ `platforms`
selector, shared parser); executes AFTER apply() with declared paths
translated through the rename report — the regeneration pattern, not
position zero: apply() revalidates the tree against its plan-time
snapshot, so deleting files before it breaks the mutation-boundary
contract (design refinement recorded during T2 study);
sink-guard set before unlink (containment, real ancestors, no-follow);
targets must be tracked; a `[[remove]]` naming a missing file fails loud
at plan time (stale config is drift); press-control files are rejected;
directories are out of scope for v1 (the real targets are files). Plan
renders `[remove ]` lines with reasons; `ApplyReport` and the receipt
record removals. Hermetic verify APPLIES removals in the sandbox — no
command is needed — so removed files vanish from the scan with no
exemption and no coverage gap.

### Tests & Tasks

- [x] [P08-T01] `verify_exempt` schema: parse, validation (exempt without
      reason rejected; reason without exempt rejected), docs
- [x] [P08-TS01] verify exempts a declared non-lockfile output only with
      `verify_exempt`; report/json/receipt carry the declared reason
- [x] [P08-T02] `[[remove]]` schema + plan-time guards (missing file,
      control files, overlap with reset/regenerate)
- [x] [P08-TS02] removal applies post-apply at the translated location
      with sink guards; report, receipt, and dry-run preview record it
- [x] [P08-TS03] hermetic verify models removals (removed identity-bearing
      file no longer leaks; no exemption listed)
- [ ] [P08-T03] release v3.6.0 after both PRs merge

### Automated Verification

- `just check` green on both PRs; `just matrix` (R1/R2/R3) green after T2
- E2E: a target declaring a non-lockfile `[[regenerate]]` +
  `verify_exempt` passes `press verify` (exit 0, exempt listed with
  reason); a target declaring `[[remove]]` of an identity-bearing file
  passes verify with the file absent from the scan
