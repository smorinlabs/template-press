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
  the doctor was once blind to submodule names.
- **One pipeline-stability validator** replacing the five accreted
  plan-time guards.
- **The rendered substitution table** — (matcher, from, to, rewrite
  surfaces, consumer-specific hunt policies, scope, provenance): the
  applier walks it; the doctor and the post-command / final-pass scans
  derive their hunts from it. Adding a mechanism becomes one row, not seven
  edit sites.
- **Plan-time rename translation reads the same fixpoint map apply uses**
  (PR #62 deferral, thread 3654853364): `build_plan`'s single-pass map
  false-refuses reset targets nested under multiple identity-bearing
  levels; the table unifies the map.
- **The independence guardrail (D2)**: a binding constraint in design
  0008 plus a regression test that fails if `verifier.py` ever imports
  the table module; the test is a named acceptance criterion.
- Semantics-preserving throughout — the full automated suite and the
  R1a/R1b/R2/R3 acceptance matrix stay green at every PR boundary.

### Out of scope

- Deriving `press verify`'s paranoid matcher from the table — FORBIDDEN
  by D2; it is the last independently-written check.
- M6 `provision`/`status` verbs.
- New rewrite mechanisms (platform-conditional commands etc. — P07 rides
  the table later as rows, not as part of this refactor).
- Declared-command timeout hardening (PR #62 thread 3654968981 —
  executor concern, unrelated to the table).

### Decisions

- **D0 (2026-07-26): land after P04/P05.** Two-round plan agreed in
  session: ship P04+P05 first (they unblock the py-launch-blueprint
  conform — the actual goal), then this refactor. That gate is now open
  (PR #62 merged, v3.4.0).
- **D1 (2026-07-27; checkpoint passed 2026-08-12): three PRs confirmed.**
  Design 0009 establishes one raw walker entry with relative path, node
  kind, and tracked state. Table scope, rewrite and checker surfaces, and
  the fixed-point rename plan remain policies above that entry; none
  requires table-specific data inside the walker. The implementation
  therefore stays walker → validator → table, safest first, with each
  boundary provable against the suite and matrix. The recorded walker+table
  fallback is not needed. Context: PR #62's single 15-commit branch drew 29
  bot threads over four review cycles — small PRs demonstrably keep review
  waves convergent.
- **D2 (2026-07-27): correlated-failure trade accepted WITH enforced
  guardrail.** Once the doctor derives from the table, it inherits the
  rewriter's blind spots by construction — the independence that matters
  lives entirely in `press verify`'s paranoid matcher. Accepted (it is
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
(matcher, from, to, rewrite surfaces, consumer-specific hunt policies, scope,
provenance). The applier walks it; the inline doctor and reset/regeneration
scans derive their hunts from it, so they cannot disagree by construction.
`press verify` remains independently derived under D2. Adding a mechanism
becomes one row, not seven edits.

**Constraint identified independently by all three architecture-review
lenses:** the conservative-rewriter / paranoid-verifier matcher asymmetry is
load-bearing design. Parameterize it, but never merge the two scanners into
one. The inline doctor intentionally derives from the rewriter's table under
D2; it is not a third independent scanner.

Sequenced as three PRs, safest first: (1) one kind-tagged surface walker;
(2) one pipeline-stability validator replacing the five accreted guards;
(3) the substitution table itself. Estimated ~1 focused week against the full
automated suite and the acceptance matrix. Semantics-preserving — no rollback
of the shipped C/D/E work; the accumulated fixes are the spec for the refactor.

### Tests & Tasks

<!-- Decompose with `project-refine P06` (tasks; TS-first per the TDD bias). -->
