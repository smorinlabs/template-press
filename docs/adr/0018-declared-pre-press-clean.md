# 0018. Declared pre-press clean is a standalone verb over `git clean -X`

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** Maintainers
- **Related:** [external-target model](../design/0006-external-target-model.md);
  [press improvements design](../superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E10; [CLEAN review](../superpowers/specs/reviews-2026-09-01/CLEAN-review.md);
  [P10 planning gate](../superpowers/specs/reviews-2026-09-05/P10-planning-gate.md);
  [project P10](../../projects/P10-declared-pre-press-clean.md)

## Context

A press renames the package directory. The rename-closure guard refuses when
that directory holds content absent from the surface inventory, and the
commonest such content is an ignored build cache (`__pycache__`). The refusal
already prints a `git clean -fdX` remedy, but the remedy is undeclared,
operator-typed, and broader than the paths at fault. A template should be
able to declare which paths an operator may clean.

## Decision

Add `[[clean]] paths = [...]` (optional `platforms`) and a standalone
`press clean --target <dir> [--show]` verb. The engine renders each path from
the SOURCE identity (the rules file is never rewritten), echoes the exact
hardened argv, and runs `git --literal-pathspecs clean -fdX -- <paths>`
(`-ndX` under `--show`). Only ignored entries under the declared paths can be
removed. Global/system Git configuration is scrubbed, and the clean argv
pins the repository-configured excludes file or the null device. This
separate pin prevents Git from loading its default user ignore file.
Before constructing that argv, the verb captures the target's public
`SurfaceSnapshot`. It refuses with exit 2 when a rendered clean path equals or
contains a present active Git visibility or repository-config input that is
absent from the snapshot's protected tracked-plus-nonignored entries. This
prevents deletion of active self-ignored `.gitignore` and ignored repository
`include.path` files without duplicating inventory's active-ignore traversal.
Tracked, non-ignored, disjoint, missing, and inactive inputs retain Git's
normal behavior. The verb also keeps the stricter configured-excludes rule: a
configured path equal to or below a clean path refuses even when it is missing.
Both comparisons handle SOURCE-rendered paths and existing case aliases. Both
preview and apply refuse before an echoed command or Git clean invocation,
preserving input bytes and the complete surface snapshot.

Clean is never a phase of `press rebrand`: dry-run and apply must observe the
same tree. Ordering is structural — the closure refusal names `press clean`
when rules are declared — with no stamp file. `press verify` is unaffected by
construction (the sandbox holds inventoried entries only). The receipt records
`[[press.clean]] paths = [...]` as a declaration; `press clean` writes no
receipt. `press check-tools` lists one informational row per rule.

## Consequences

- Exit codes keep the 0/1/2 contract. Exit `2` includes configured-excludes or
  active-input overlap, snapshot-capture failure, and process-launch failure;
  no clean command ran. Exit `1` means git clean ran after preflight and failed,
  so the tree may have changed.
- Arbitrary clean commands remain out of scope; they would need the
  before/after invariant the CLEAN review specified.
- A declared path that matches nothing is a silent no-op (`git clean` exits 0).
