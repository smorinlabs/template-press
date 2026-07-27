# Session handoff — implement P04+P05 (round 1) — 2026-07-26

## 🎯 Outcome

**Goal: implement P04 + P05 together, TDD, as one change** — per the merged
task lists in `projects/P04-regenerate-bun-lock.md` (TS01…T17) and
`projects/P05-reset-rule.md` (TS01…T07), starting at **P04-TS01**. Ends with a
PR, the R3 acceptance matrix green, and both trunk rows flipped as tasks
complete.

**Out of scope:** P06 substitution-set refactor (round 2, after this
integrates — issue #42); `stub_url`; saved-plan mode (`--plan-out`/
`--apply-plan`); M6 `provision`/`status`; py-launch-blueprint conformance.

**Self-contained:** ✓ stands alone. Everything load-bearing is merged to
`main` @ `fcb188a` and substantive; the essence is inlined below.

## ⚠ Portability & dependency preflight — read first

- **Uncommitted:** none (this handoff file itself excepted — commit it if it
  must reach another machine).
- **Unpushed:** none. `main` @ `fcb188a` matches origin.
- **Stashes:** none.
- **Referenced docs:** `projects/P04-regenerate-bun-lock.md` ✓ committed ·
  ~740 lines · substantive. `projects/P05-reset-rule.md` ✓ committed · ~250
  lines · substantive. `docs/design/0006-external-target-model.md`,
  `docs/research/0004-*.md` ✓ committed. All travel.

## 🧭 Where you are

- **Repo:** template-press · origin `https://github.com/smorinlabs/template-press.git` · default `main`
- **Branch:** `main` @ `fcb188a` · repo root (this machine): `/Users/stevemorin/c/template-press` ← may differ on yours
- **Setup (every fresh worktree/clone):** `just setup` **and**
  `bun install --frozen-lockfile` — or commitlint silently no-ops and the
  first commit dies.
- **Verify:** `just check` (full pipeline) · `just matrix` (MANDATORY after
  any change under `src/template_press/rebrand/`) · `pytest` (excludes
  slow/live; full: `pytest -m ""`)
- **Discipline:** never commit to local `main`; fresh worktree off
  `origin/main` before the first file (EnterWorktree works when the session
  starts inside the repo); Conventional Commits, lowercase subject; merge
  method `--merge` (squash disabled org-wide).

## 📎 Artifacts & sources of truth

| What | Repo-relative path (canonical) | Status | Ticket/PR |
|------|-------------------------------|--------|-----------|
| P04 decisions + 17 tasks | `projects/P04-regenerate-bun-lock.md` | ✓ merged | PRs #57, #58 |
| P05 decisions + 7 tasks | `projects/P05-reset-rule.md` | ✓ merged | PRs #56, #58 |
| Design contract | `docs/design/0006-external-target-model.md` | ✓ merged | — |
| Gap register (G1/G2) | `docs/research/0004-py-launch-blueprint-conformance-gaps.md` | ✓ merged | issue #54 |
| Engine code | `src/template_press/rebrand/` (cli, engine, safety, config, rules, doctor, verifier, verify_cli) | ✓ v3.3.0 | — |
| Trunk | `PROJECTS.md` (rows P04/P05 at `[ ]`) | ✓ merged | — |

Abs paths on this machine: prefix `/Users/stevemorin/c/template-press/`.

## 📋 Plan · inlined skeleton

TDD pairs, in order (each TS = failing tests first, then its T implements):

1. **Schemas** — P04-TS01/T02 (`[[regenerate]]`: `file`/`command`/`env` keys;
   remove `DEFAULT_RULES.regenerate`) and P05-TS01/T02 (`[[reset]]`: `file` +
   `stub` XOR `stub_file`). Either mechanism first; the cross-mechanism
   reset⊗regenerate overlap test waits for TS11.
2. **Plan time** — P04-TS03/T04: executable resolution (bare→PATH under the
   deny-by-default env, slash→target root, pinned absolute path), stale-argv
   refusal (normalized, prefix-aware, best-effort), plan→apply rendering
   (verbatim argv + pinned path + env names), exit-2-nothing-written.
3. **Reset preflight/preview** — P05-TS03/T04: untracked/dirty refusal even
   under `--allow-dirty`, named safety predicates, two-level preview
   (`--verbose`, 20-line bound), planned reset-path identity scan.
4. **Executor** — P04-TS05/T06: cwd=target, no shell, deny-by-default env
   (platform base + declared names), mode preservation, per-command sink
   guard recheck; replaces the hardcoded `uv lock` branch in
   `cli._regenerate_lockfiles` (called only from `cli.py:379`).
5. **Reset apply** — P05-TS05/T06: reset first (position zero, source
   coordinates), `safe_write` with mode preservation, `ApplyReport.reset` +
   receipt count, failed reset aborts (no receipt).
6. **Postconditions** — P04-TS07/T08: output exists, full containment/type
   recheck, UTF-8 two-point gate, paranoid changed-fields scan (+ rendered
   FROM literals, translated path components, reverse-mapped scopes), final
   pass over outputs + reset stubs + `ROOT_CONTROL`; receipt records each
   regeneration's resolved argv.
7. **Verify exemption** — P04-TS09/T10: explicit constant (`uv.lock`,
   `bun.lock`) matched by basename + declared exact path translated through
   renames; exempt files listed not-verified; `exempt` field in report AND
   receipt; cli.md exit-0 rewording.
8. **§6 preflight** — P04-TS11/T12: excluded file with no
   regenerate/reset/verify_ignore → exit 2 naming the file and the three
   fixes; plus the cross-mechanism overlap rejection.
9. **check-tools** — P04-TS13/T14: standalone verb, D2's exact resolution
   semantics, reads config, executes nothing.
10. **Migration** — P04-T15: create `press/press-rules.toml` (uv.lock +
    bun.lock regenerations, CHANGELOG reset), pinned bun installer + rules
    path filter in `.github/workflows/rebrand-matrix.yml`, runbooks.
11. **Receipt lifecycle** — P04-T16: `--force` invalidates the prior receipt
    before first mutation (failing test first).
12. **Close** — P04-T17 `just check` + `just matrix` green · P05-T07 joint
    acceptance (stub CHANGELOG, regenerated lockfiles, clean verify) · PR ·
    check task boxes and flip trunk glyphs as work lands.

## 🔧 State to resume

Nothing in flight — implementation has not started. All 24 tasks unchecked;
both projects `[ ]`. PRs #56/#57/#58 merged; every review thread (55 + 18)
dispositioned.

**Wave-3 carried items** (post-merge PR #58 comments, agreed to be honored in
implementation, permanently recorded by id on the merged PR):

- **3654059282 (P1):** plan rendering must escape or reject control
  characters (newline/CR/ANSI) in argv elements — plan visibility is the
  entire approval guard, so a literal renderer can be forged. Test these
  inputs (belongs with TS03/T04).
- **3654059283:** duplicate `[[reset]]` targets rejected at config load
  (belongs with P05-TS01/T02).
- **3654059287:** a declared command exiting nonzero aborts the press, no
  receipt, even if the output scans clean — explicit test (TS05/TS07).
- **3654059289:** the planned reset-path identity scan runs at preflight
  (plan-time-knowable → exit 2 before writes), with the final recheck
  retained (P05-TS03 + final pass).

## 🧠 Critical context that won't survive a fresh window

**Decisions & why (the essentials — full record in the project files):**

- **Plan→apply, no consent machinery.** Dry-run renders every command
  verbatim + the pinned executable + env names; running apply IS the
  approval. The consent/fingerprint apparatus in P04's D1 record region is
  deliberately dead — an `END of the record-only region` marker bounds it.
- **Everything declared, no hidden defaults** — the governing constraint.
  The hardcoded `uv lock` and `DEFAULT_RULES.regenerate` go away; the
  hermetic-verify exemptible cap becomes its own explicit constant.
- **Deny-by-default env** (platform-specific base + declared names) survives
  on correctness grounds, not trust: stray `UV_INDEX_URL`-class settings and
  CI tokens must not reach child processes.
- **UTF-8 fail-closed in both mechanisms**; reset target key is `file`;
  verbose preview = `--verbose`, N=20.

**Rejected approaches — do not re-derive:**

- Consent tokens/hashes/fingerprints (superseded — do not rebuild while
  implementing; the record region is history, not spec).
- Filename→command inference — banned by D1; it re-tempts in diagnostics
  (the legacy-form error prints a TEMPLATE with a placeholder, never a
  derived command).
- "Abort = atomicity" — false; `apply` is incremental, no rollback
  (`cli.py:442`); git is the undo.
- Merging the two matchers — the conservative-rewriter / paranoid-verifier
  asymmetry is load-bearing (P06's constraint too).

**Code facts that took work to establish:** `press verify` never regenerates
(`_regenerate_lockfiles` only from the apply path); `scrubbed_uv_env` at
`safety.py:384` is a one-family blocklist being replaced; `verifier.scan` is
changed-fields-only (`_changed_fields`) and has a `_scan_binary` raw-bytes
path; `ROOT_CONTROL` lives in `engine.py` and is excluded from downstream
inventories.

**Process dynamics (they shaped this work):** the repo's bots (Codex,
CodeRabbit, Greptile, Copilot) review every push ~10 min later — triage each
thread (fix-commit-reply or refute-reply), reply via REST
(`gh api …/comments/{id}/replies`; GraphQL rate-limits constantly on this
machine), never poll faster than 1/20s, bound every wait. The user resolves
threads and merges manually — hand them steps, don't do it. `pr-merge-flow`
skill drives the endgame.

## 👉 First action

Create the worktree and set up, then write the first failing tests:

```bash
# in a session started inside the repo, EnterWorktree works; CLI fallback:
git fetch origin && git worktree add ../template-press-p04p05 -b feat/p04-p05-declared-commands origin/main
cd ../template-press-p04p05 && just setup && bun install --frozen-lockfile
```

Then **P04-TS01**: failing tests for the `[[regenerate]]` schema +
config-load validation (see the task text in
`projects/P04-regenerate-bun-lock.md` for the full case list).

## ℹ How this was made

digest: skipped (composed from the live, full-context session) · gathered
2026-07-26 · machine `Steves-MacBook-Pro.local` · self-contained: ✓
