# P11 — Directory removals (`[[remove]] dir`) and removal phase

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [Directory membership and history contract](../docs/superpowers/specs/2026-09-06-p11-directory-removals-design.md)
- **Design:** [Original press improvements specification](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md), E5(c)
- **Plan:** [Six implementation tasks](../docs/superpowers/plans/2026-09-06-p11-directory-removals.md)
- **Depends on:** P10
- **Review:** [Original removal review](../docs/superpowers/specs/reviews-2026-09-01/E5-review.md)

- **Status:** `[~]` in progress — Group 3C; declaration parsing, frozen
  directory selection, exact deletion, and complete receipt history are reviewed
  and validated. Public directory execution remains gated until CLI and verifier
  integration are complete.

### Scope

`[[remove]] dir` selects tracked regular files before mutation. The press removes
only those selected members after rewriting and renaming, records their complete
source and current paths, and uses that recorded membership during verification.
Directory safety checks preserve untracked work and refuse unsafe nodes or Git
visibility inputs. The approved acceptance amendment pairs a supported production
rename with a separate injected nonmember and broken-executor control.

### Tests & Tasks

- [x] [P11-TS01] Establish parser and frozen-selection refusal controls; 51 focused tests passed with one Windows-only skip before the first implementation commit.
- [x] [P11-T01] Task 1: typed directory declarations, static overlap checks, and temporary public execution gate.
- [x] [P11-T02] Task 2: immutable membership, directory safety/status checks, compatibility view, rendering, and command-conflict checks.
- [ ] [P11-TS02] Add executor/history, CLI/verify, renewal, and discriminating membership controls before their corresponding implementations.
- [x] [P11-T03] Task 3: exact deletion, safe empty-directory pruning, and complete bounded receipt history.
- [ ] [P11-T04] Task 4: real press, historical verification, and explicit membership renewal.
- [ ] [P11-T05] Task 5: prove production preserves nonmembers and deliberately broken alternatives fail the same oracles.
- [ ] [P11-T06] Task 6: migrate research declarations, preserve project scaffolding, document behavior, and validate committed-head acceptance.
- [ ] [P11-T07] Delivery: final independent review, PR checks and thread resolution, authorized merge, then project closeout.

### Verification

Tasks 1–2 passed independent specification and quality review. The first batch
passed `just check` with 1,594 tests and three skips, root formatting, and the
four-case acceptance matrix. Native Windows execution of the new junction test
remains a remote CI gate. These results do not certify the unfinished tasks.

Task 3 passed independent specification and quality review, `just check` with
1,651 tests and three skips, root formatting, and all four acceptance tests.
The receipt reader enforces complete bounded history; the executor deletes exact
frozen members and preserves unselected contents. CLI and verifier integration,
renewal controls, native migration, and remote Windows validation remain open.
