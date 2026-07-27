# P06 — Derive checkers from one rendered substitution set

- **Status:** `[?]` idea

One table the rewriter applies and every checker reads

### Open questions

- ~~Q: Land **before M6** as the three-lens review recommends, or after P04/P05?~~
  **A (2026-07-26): after P04/P05.** Two-round plan agreed in session: ship
  P04+P05 together first (they unblock the py-launch-blueprint conform — the
  actual goal), then take this refactor up once that work is integrated.
  Original trade-off, for the record: M6 adds new mechanisms to this engine;
  building them on the current structure multiplies the hand-written cells.
  But a week of internal refactoring with no user-visible output is its own
  risk.
- Q: Does the three-PR split (walker → validator → table) hold up under design,
  or do the walker and table need to land together to be coherent?
- Q: Correlated-failure risk: once doctor derives from the same table the
  rewriter applies, it can no longer catch the rewriter's *model* bugs. The
  independence that matters would then live entirely in `press verify`'s
  paranoid matcher. Is that acceptable, and is it stated anywhere binding?

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

**The fix.** Compile all mechanisms into one rendered substitution table —
(matcher, from, to, surfaces, scope). The applier walks it; doctor and verify
derive their scan set from the same table, so they cannot disagree by
construction. Adding a mechanism becomes one row, not seven edits.

**Constraint all three lenses named independently:** the conservative-rewriter /
paranoid-verify matcher asymmetry is load-bearing design — parameterize it, never
merge the two scanners into one.

Sequenced as three PRs, safest first: (1) one kind-tagged surface walker;
(2) one pipeline-stability validator replacing the five accreted guards;
(3) the substitution table itself. Estimated ~1 focused week against the existing
459-test suite and the acceptance matrix. Semantics-preserving — no rollback of
the shipped C/D/E work; the accumulated fixes are the spec for the refactor.

<!-- Promote with `project-refine P06`. -->
