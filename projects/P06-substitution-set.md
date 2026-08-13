# P06 — Derive checkers from one rendered substitution set

- **Status:** `[ ]` ready

One table the rewriter and inline checkers read; verify stays independent

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Ticket:** issue #42 — refactor: derive checkers from a rendered
  substitution set (pre-M6 gate); the canonical record of the three-lens
  architecture review
- **Design:** [0008 — identity variants and replace rules](../docs/design/0008-identity-variants-and-replace-rules.md)
  — what the table renders; D2's independence guardrail lands here
- **Design:** [0009 — rendered substitution table and surface inventory](../docs/design/0009-substitution-table.md)
  — D1's table-needs checkpoint and the implementation contracts
- **Design:** [0006 — external target model](../docs/design/0006-external-target-model.md)
- **Review:** PR #62 deferral — plan-time rename translation must read the
  fixpoint map (in scope; see Scope and D1 context)
  https://github.com/smorinlabs/template-press/pull/62#discussion_r3654853364
- **Siblings:** [P04 — regenerate bun.lock](P04-regenerate-bun-lock.md) ·
  [P05 — reset rule](P05-reset-rule.md) — their accumulated fixes (four
  bot-review cycles, 29 threads) are the refactor's behavioral spec

### Scope

- **One kind-tagged surface walker** replacing the five independent ones
  (`engine._git_listed`, `engine.iter_target_files`, `engine.copy_paths`,
  `engine.scan_paths`, `regen.tracked_paths`) — walker disagreement is why
  the doctor was once blind to submodule names. Its snapshot also records the
  Git ignore inputs needed to prove that content rewrites and resets cannot
  change path visibility underneath the shared rename plan.
- **One pipeline-stability validator** replacing the five accreted
  plan-time guards.
- **The rendered substitution table** — (field-aware matcher specification,
  from, to, rewrite
  surfaces, consumer-specific hunt policies, scope, provenance): the
  applier walks it; the doctor and the post-command / final-pass scans
  derive their hunts from it. Adding a mechanism becomes one row, not seven
  edit sites.
- **Plan-time rename translation reads the same fixpoint map apply uses**
  (PR #62 deferral, thread 3654853364): `build_plan`'s single-pass map
  false-refuses reset targets nested under multiple identity-bearing
  levels; the table unifies the map.
- **The independence guardrail (D2)**: binding module and data-flow constraints
  in design 0008. A structural test rejects direct or transitive verifier
  dependencies on table consumers. A call-boundary test rejects precompiled
  scan inputs. Discriminating rule and identity ablations prove that the
  verifier still derives both answers independently.
- Output-preserving for every stable configuration. P06 intentionally adds
  pre-write refusals for cross-row output dependencies, path cycles, and a
  press that would mutate Git's ignore inputs while relying on a frozen path
  inventory. It also refuses a prefix move that would carry a gitlink or a node
  absent from that inventory, and runtime divergence from the authorized
  rename plan. The full automated suite and the R1a/R1b/R2/R3 acceptance
  matrix stay green at every PR boundary.

### Out of scope

- Deriving `press verify`'s paranoid matcher from the table — FORBIDDEN
  by D2; it is the last independently-written check.
- M6 `provision`/`status` verbs.
- New rewrite mechanisms (platform-conditional commands etc. — P07 rides
  the table later as rows, not as part of this refactor).
- Declared-command timeout hardening (PR #62 thread 3654968981 —
  executor concern, unrelated to the table).
- Declared-command mutation of Git visibility inputs (issue #71 — a
  post-apply executor invariant, separate from P06's pre-mutation inventory
  authorization gate).

### Decisions

- **D0 (2026-07-26): land after P04/P05.** Two-round plan agreed in
  session: ship P04+P05 first (they unblock the py-launch-blueprint
  conform — the actual goal), then this refactor. That gate is now open
  (PR #62 merged, v3.4.0).
- **D1 (2026-07-27; checkpoint passed 2026-08-12): three PRs confirmed.**
  Design 0009 establishes one raw walker entry with relative path, separate
  index and worktree kinds, and tracked state, wrapped in a snapshot whose Git-visibility guard
  is independent of table matching. Table scope, rewrite and checker
  surfaces, and the fixed-point rename plan remain policies above that entry;
  none requires table-specific data inside the walker. The implementation
  therefore stays walker → validator → table, safest first, with each
  boundary provable against the suite and matrix. The recorded walker+table
  fallback is not needed. Context: PR #62's single 15-commit branch drew 29
  bot threads over four review cycles — small PRs demonstrably keep review
  waves convergent.
- **D2 (2026-07-27; boundary clarified 2026-08-12): correlated-failure trade accepted WITH enforced
  guardrail.** Once the doctor derives from the table, it inherits the
  rewriter's blind spots by construction — the independence that matters
  lives in `press verify`'s independently derived paranoid matcher for
  non-exempt surfaces. Declared regeneration outputs remain explicitly listed
  as not verified; their table-driven postconditions retain the existing
  correlated-risk tradeoff. Accepted (it is
  the point of the refactor), on condition the guardrail is stated in
  design 0008 AND enforced by a regression test (structurally
  impossible, not merely discouraged — same philosophy as the org's
  disabled squash merge). Evidence the paranoid side earns the role: it
  refused the stale bun.lock name and drove three review-cycle
  hardenings (path literals, reset filenames, display forms) during
  PR #62.

### Open questions

None — both capture-time questions were resolved 2026-07-27 as D1 and D2
(the design deep dive itself is D1's checkpoint, not an open question).

### Notes

GitHub issue **#42**. Origin: the three-lens architecture review run after PR #41
(12 bot-review cycles, 45 threads) — all three lenses independently reached the
same diagnosis and the same disposition (merge first, then this refactor).

**The problem.** Press does two jobs — rewrite the old identity, then check that
none survived — and each keeps its own hand-maintained list of what to look for.
Teach the rewriter a new trick and you must remember to teach the checker the
same trick in every place it looks. Adding `display_name` required edits in seven
places; several were missed and found one at a time by bots over multiple review
cycles. Measured shape: ~26 hand-written matcher-application loops across four
modules; six independent surface walkers that disagree about which nodes exist
(that disagreement is why the doctor was blind to submodule names); five
plan-time guards accreted one per cycle that are instances of two general rules.
It happened again during P04/P05 (2026-07-27): the postcondition scan did not
know display-name derived forms until review cycle 3 caught it.

**The fix.** Compile all mechanisms into one rendered substitution table —
(field-aware matcher specification, from, to, rewrite surfaces,
consumer-specific hunt policies, scope, provenance). The applier walks it; the
inline doctor and reset/regeneration scans derive their hunts from it, so they
cannot disagree by construction. `press verify` remains independently derived
under D2 for every non-exempt surface. Adding a mechanism becomes one row, not
seven edits.

**Constraint identified independently by all three architecture-review
lenses:** the conservative-rewriter / paranoid-verifier matcher asymmetry is
load-bearing design. Parameterize it, but never merge the two scanners into
one. The inline doctor intentionally derives from the rewriter's table under
D2; it is not a third independent scanner.

Sequenced as three PRs, safest first: (1) one kind-tagged, visibility-guarded
surface walker; (2) one pipeline-stability validator replacing the five
accreted guards; (3) the substitution table itself. Estimated ~1 focused week
against the full automated suite and the acceptance matrix. Stable
configurations preserve their current output. Shipped C/D/E validation
refusals remain refusals except issue #45's approved acceptance of
same-source/different-destination content rules with demonstrably disjoint
`files` scopes. The other intentional acceptance changes are earlier,
pre-write refusals for an order-dependent pipeline, a cross-pass path cycle,
mutation of Git's ignore inputs, an unsafe prefix closure, or runtime divergence
from the authorized rename plan. An existing symlink target that contains a
changed non-path identity field is left unchanged and fails the doctor instead
of being silently redirected.

### Tests & Tasks

- [ ] [P06-TS01] Failing characterization tests for the shared
      `SurfaceSnapshot`: tracked and untracked files, ignored paths, symlinks,
      gitlinks, non-UTF-8 path bytes, tracked deletions, file-to-directory
      replacements, and regular-versus-symlink Git visibility inputs.
- [ ] [P06-T02] Implement `inventory.py` with `SurfaceEntry`,
      `VisibilityInput`, and `SurfaceSnapshot`; make one hardened Git-backed
      capture pass the TS01 contract; delegate the five existing walker APIs
      to selectors over that snapshot; remove duplicate Git enumeration while
      preserving every consumer's distinct exclusions.
- [ ] [P06-T03] PR 1 gate: run the focused inventory and compatibility tests,
      `just check`, and `just matrix`; perform an adversarial architecture and
      defect review against design 0009, fix every reproduced in-scope defect,
      and rerun all gates before advancing.
- [ ] [P06-TS04] Failing validator tests: same-source ambiguity, ordered
      content dependencies, stale-source emission, path dependencies and
      cycles across passes, path-component structural safety, shared-prefix
      conflicts, provenance-rich errors, and issue #45's sole intentional
      relaxation for demonstrably disjoint content scopes.
- [ ] [P06-T05] Implement one pure pipeline-stability validator and replace the
      five accreted guards with it; preserve every existing stable output and
      refusal except issue #45's approved relaxation.
- [ ] [P06-T06] PR 2 gate: run the focused validator and compatibility tests,
      `just check`, and `just matrix`; perform an adversarial architecture and
      defect review against design 0009, fix every reproduced in-scope defect,
      and rerun all gates before advancing.
- [ ] [P06-TS07] Failing table/compiler tests: field-aware matcher specs,
      ordered provenance, compatible-row normalization, consumer-specific hunt
      policies, exact declared-rule matching, substring-aware paranoid hunts,
      fixed-point rename steps, virtual dangling-link translations, and
      source/current scope coordinates.
- [ ] [P06-T08] Implement `substitutions.py`, compile the immutable
      `SubstitutionTable` and target-specific `RenamePlan`, and make planning,
      application, path translation, and symlink retargeting consume the one
      ordered plan with predecessor gating.
- [ ] [P06-TS09] Failing integration and architecture tests: table-derived
      doctor/reset/regeneration hunts; visibility-input mutation projection and
      pre-mutation revalidation; prefix closures that refuse ignored untracked
      descendants, empty directories, and gitlinks; live-plan divergence;
      nested two-pass translation; and direct/transitive verifier independence
      with rule and identity ablations.
- [ ] [P06-T10] Migrate the rewriter, inline doctor, reset scans, regeneration
      scans, and final validation pass to the table; enforce visibility and
      prefix-closure guards at the top-level mutation boundary; keep
      `press verify` independently derived from `Identity`, `Rules`, and neutral
      inventory/safety helpers.
- [ ] [P06-T11] PR 3 and project-completion gate: run every focused P06 test,
      `just check`, and the R1a/R1b/R2/R3 `just matrix`; perform the final
      adversarial architecture, safety, and defect review; fix every reproduced
      in-scope defect; rerun all gates; then close issue #42 and mark P06
      complete only after the merged `main` state is verified.
