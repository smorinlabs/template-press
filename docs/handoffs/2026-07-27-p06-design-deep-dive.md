# Session handoff — P06 design deep dive (design 0009) — 2026-07-27

## 🎯 Outcome

**Goal: the exploratory design for P06** — author
`docs/design/0009-substitution-table.md`, the table-needs sketch that is
**D1's checkpoint** in [`projects/P06-substitution-set.md`](../../projects/P06-substitution-set.md).
Ends with: the design doc landed as its OWN small PR (bots review it —
cheap insurance before code), the D1 verdict recorded in the P06 file
(three-PR split confirmed, or fallback to walker+table combined), and P06
ready to decompose. **Design before tasks, deliberately**: decomposing
first would bake in the very assumptions the checkpoint exists to test.

**Out of scope:** any implementation; task decomposition (comes after this
doc); M6 verbs; P07.

**Self-contained:** ✓ — everything referenced is merged to `main` @
`9793e3b` and pushed. No uncommitted work, no stashes, no worktrees.

## 🧭 Where you are

- **Repo:** template-press · `https://github.com/smorinlabs/template-press.git`
  · default `main` · this machine: `/Users/stevemorin/c/template-press`
- **State:** v3.4.0 released today (PR #62 merged — P04+P05 complete:
  declared `[[regenerate]]`/`[[reset]]`, §6 preflight, check-tools,
  R1a/R1b/R2/R3 matrix green). Trunk: P06 `[ ]` ready · P07 `[?]` idea.
- **Setup (fresh worktree/clone):** `just setup` and
  `bun install --frozen-lockfile`, or commitlint silently no-ops.
- **Discipline:** worktree before the first file (EnterWorktree works when
  the session starts inside the repo); superpowers **brainstorming first**
  (this is creative design work); Conventional Commits lowercase; merge
  method `--merge` (squash disabled org-wide); bot-review triage with the
  convergence bar (from cycle 3: fix only invariant holes, few lines, no
  new config surface; refute or defer the rest — see auto-memory
  `review-triage-convergence`).
- **Explaining decisions to Steve:** plain language, big-picture backdrop,
  real code examples per option (auto-memory
  `decision-pages-need-big-picture`). He'll deny question widgets when he
  wants prose — analysis first, then ask.

## 📎 Artifacts & sources of truth

| What | Where | Why it matters here |
|------|-------|---------------------|
| The spec: scope, D0–D2, notes | `projects/P06-substitution-set.md` | THE input — read first |
| Canonical ticket + three-lens review record | issue #42 | origin of the three-PR plan |
| Replace-rules/matcher design | `docs/design/0008-identity-variants-and-replace-rules.md` | what the table renders; D2 guardrail lands here |
| External-target contract | `docs/design/0006-external-target-model.md` | governing model |
| Fixpoint deferral (in scope) | PR #62 `#discussion_r3654853364` | the table must carry the unified rename map |
| Behavioral spec | `projects/P04-…​.md` + `projects/P05-…​.md` + PR #62's 29 threads | accumulated fixes = what the refactor must preserve |

## 📐 The design questions the doc must answer

1. **Table shape** — exact columns of the rendered substitution table
   (matcher kind, from, to, surfaces, scope) and whether it carries
   rename/provenance data. The PR #62 deferral says yes-ish:
   `build_plan()` records a SINGLE-pass rename map while `apply()`
   renames in MULTIPLE passes, so plan-time translation can false-refuse
   deeply nested targets; `engine.translate_path` is already a fixpoint
   (commit `1a62e81`) but the MAP it consumes is still single-pass. The
   table is where the one true map should live.
2. **Walker interface** — one kind-tagged surface walker replacing five
   (`engine._git_listed`, `engine.iter_target_files`, `engine.copy_paths`,
   `engine.scan_paths`, `regen.tracked_paths`). What does it return
   (paths? kind-tagged entries — file/symlink/gitlink? exclude handling
   inside or at callers?). **D1's checkpoint: sketch the table's needs
   FIRST, then test whether this interface survives them.** Survives →
   three-PR split confirmed. Doesn't → record fallback (walker+table one
   PR) in P06 D1.
3. **Derivation contracts** — exactly how the doctor and the
   post-command/final-pass scans derive their hunt sets from the table.
4. **The D2 guardrail** — where the binding sentence goes in design 0008
   and the shape of the regression test that FAILS if `verifier.py` ever
   imports the table module (structural, like the org's disabled squash
   button). Named P06 acceptance criterion.

## 🧠 Critical context that won't survive a fresh window

- **The load-bearing asymmetry (all three lenses, independently):** the
  conservative rewriter and the paranoid verifier must never merge.
  `press verify`'s matcher is deliberately NOT table-driven and must stay
  that way (D2, FORBIDDEN in Out of scope). After P06, doctor and rewriter
  cannot disagree by construction — verify is the last independent brain.
- **Why D2's guardrail must be a TEST, not just prose:** a future
  "tidy the duplication" refactor is exactly how the last independent
  check silently dies. PR #62 evidence that the paranoid side earns its
  keep: it refused the stale bun.lock workspace name and drove three
  review-cycle hardenings (path literals, reset filenames, display forms).
- **Why three small PRs:** PR #62's single 15-commit branch drew 29 bot
  threads over four review cycles. Small PRs demonstrably converge.
- **Why design-before-decompose:** P04/P05's 24-task list was writable in
  an afternoon only because decisions D1–D5 existed first; every task
  cited a settled decision. Same order here.
- **Fresh dogfood for the walkers being wrong:** walker disagreement is
  why the doctor was once blind to submodule names; and the postcondition
  scan didn't know display-name derived forms until review cycle 3 —
  the seven-edit-sites disease struck again THIS week.

## 👉 First action

```bash
# in a session started inside the repo, EnterWorktree works; CLI fallback:
git -C /Users/stevemorin/c/template-press fetch origin
git -C /Users/stevemorin/c/template-press worktree add ../template-press-p06-design -b docs/p06-substitution-table-design origin/main
cd ../template-press-p06-design && just setup && bun install --frozen-lockfile
```

Then read `projects/P06-substitution-set.md` + design 0008 + the five
walker implementations, and start **superpowers:brainstorming** toward
design 0009 — the table-needs sketch first (question 1), because
question 2's checkpoint depends on it.

## ℹ How this was made

Composed live from the full-context session (crash recovery → P04/P05
round 1 → PR #62 four-cycle review → v3.4.0 → P06 scope+promotion) ·
2026-07-27 · machine `Steves-MacBook-Pro.local` · self-contained: ✓
