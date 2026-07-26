# P04 — Regenerate bun.lock during a press

- **Status:** `[?]` idea

Neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks

### Decisions

All three open questions settled 2026-07-25 (walkthrough in chat).

- **D1 — Regeneration commands are fully target-declared.** A target declares
  both the file and the argv that rebuilds it, e.g.
  `{ file = "bun.lock", command = ["bun", "install"] }`. Nothing is inferred
  from a filename, so there is no hidden filename-to-command mapping.

  **`file` is validated as a contained relative path, not taken as given.** It
  must pass the same predicates P05 D5 requires of reset targets —
  `safety.SafeRelPath` plus a no-follow regular-file check — before anything
  runs. Without that, `file = "../outside"` paired with `command = ["true"]`
  satisfies a naive existence check against a pre-existing file the target's
  git-based scanner cannot see, buying an exemption for a path outside the repo.

  **A file may not be both a regeneration output and a `[[reset]]` target.**
  P05 D2 already bans reset/replace overlap because the result depends on pass
  order; the same hazard exists here and is currently worse, since reset runs
  first (P05 D5) and regeneration runs after `apply` — so a file declared as
  both gets its stub written and then immediately overwritten, with both
  operations counted successful. Reject the overlap at config-load time.

  **This deliberately reverses a documented guarantee, and it is a genuinely new
  trust boundary — not merely a more explicit one.** Today `regenerate` is a list
  of filenames and the only *regeneration* argv press ever runs is a literal
  `["uv", "lock"]` baked into `cli.py`, so a pressed repo's config cannot make
  press execute a program of its choosing (design 0007 D3/D5, EMP-01). After D1
  it can. (Press does invoke `git` unconditionally — `git status` in `cli.py`,
  `git ls-files` in `engine.py` — but never at a target's direction, which is
  the distinction that matters here and the reason D4 lists `git` separately.)

  An earlier draft of this decision justified that by arguing press already runs
  the target's build tooling, since `uv lock` can execute dependency build
  backends. **That argument does not hold** and is recorded here so it is not
  reached for again: executing a dependency's build hook during resolution
  requires a malicious dependency and is indirect; executing
  `command = ["/bin/sh", "-c", "…"]` from a config file is direct and trivial.
  They are not equivalent, and a decision this size should not rest on a
  comparison that collapses under one example.

  **The boundary D1 therefore requires — pick before implementing:** target-
  declared commands execute only with explicit operator consent, expressed as a
  flag rather than an interactive prompt so CI remains usable. Without it, press
  refuses and names the commands it would have run. An executable allowlist was
  considered and rejected as inconsistent with D1 (it reinstates a tool-side
  default); a sandbox was considered and judged disproportionate for a tool the
  operator runs locally against a repo they chose.

  Two facts that bound the exposure, both worth carrying into the design doc:
  - The plan and dry-run output must display the **exact argv** that would
    execute, so consent is informed rather than nominal.
  - The CI drift-guard path does not execute anything: `press verify` never
    regenerates (verified 2026-07-25 — `_regenerate_lockfiles` is called only
    from `cli.py:379`), so the usage most likely to run against an untrusted
    repo never reaches a target-declared command.

  D3 below is what keeps this change from also weakening leak detection.

  **Migration is a required part of this decision, not an afterthought.** The
  `regenerate` key changes from a list of filenames to a list of objects, so
  every existing config is invalid, and — more sharply — removing the hidden
  default removes `DEFAULT_RULES.regenerate = ("uv.lock",)`, which targets
  currently inherit without declaring anything. **template-press itself has no
  `press/press-rules.toml`** (verified 2026-07-25), so its own R3 self-press in
  the acceptance matrix depends on exactly that default: ship D1 without a
  migration and `just matrix` fails. Required:
  - Reject the old list-of-strings form with an error that prints the
    equivalent object form, rather than silently accepting it as shorthand —
    accepting it would reinstate the filename-to-command mapping D1 removes.
  - Create `press/press-rules.toml` in this repo declaring its own `uv.lock`
    regeneration, as part of the same change that removes the default.

- **D2 — Resolve every declared command at plan time; missing tool exits 2.**
  Before any write, check each command's executable resolves on PATH. A missing
  tool becomes a clean refusal with nothing written instead of a failure
  discovered after the rewrite pass has already mutated the repo. Consistent
  with P05 D5 (validate before mutating) and with the existing "exit 2 means
  nothing was written" contract. Considered and not taken: also recording the
  resolved binary path in the receipt for reproducibility across machines —
  worth revisiting, but not required for correctness.

- **D3 — Scan-exemption is earned by result, not by declaration.** Two parts,
  because the two contexts differ:
  - **Real press** (`cli._press`): after regeneration runs, SCAN what the command
    produced. A no-op command (`["true"]`) leaves source identity in the file and
    fails the press. This is newly possible because regeneration happens before
    the doctor scan — note it also requires the doctor to look at regenerated
    files at all, which it does not today (`iter_target_files` skips everything
    in `exclude_files`).

    **That scan must use the paranoid matcher (`matcher.find_occurrences`), not
    the doctor's conservative `identity.occurs`.** This is the decision's most
    important detail and an earlier draft got it wrong. The exemption being
    earned here is exemption from *verify*, whose whole reason for existing is a
    stricter matcher than the doctor's (design 0007) — the doctor misses
    case/separator-glued forms like `demoWidgetConfig`. Paying for a paranoid
    exemption with conservative evidence means a no-op regenerator that leaves a
    glued variant behind passes the doctor and is then skipped by verify: a
    false-clean receipt. The evidence must be at least as strong as what it buys.

    **Also require the declared output to still exist after the command runs.**
    Scanning alone is insufficient: a command that exits 0 having *deleted* its
    lockfile leaves nothing for `iter_target_files` to return, so the scan finds
    no stale identity and the press reports success over a silently removed
    tracked file. A declared regeneration that does not leave its file behind is
    a failed regeneration.
  - **Hermetic verify** (`verify_cli`): keeps an exemption, but it requires
    **both** conditions — the filename is on press's own exemptible list **and**
    the target actually declared a regeneration for it. The tool-side list caps
    what a target can exempt; the target's declaration is what proves the real
    press would have rebuilt it. Dropping the second condition would false-clean
    exactly the case today's keying already handles: a target that omits or
    disables regeneration for an otherwise-exemptible file like `uv.lock` gets
    no rebuild in the real press, so the file keeps source identity — and verify
    would wave it through on filename alone. Verified 2026-07-25:
    `_regenerate_lockfiles` is called only from `cli.py:379` and never from the
    verify path, so the sandbox copy of a lockfile still carries source identity
    and would flag forever without an exemption.

- **D4 — A standalone command that reports whether every external command is
  findable.** D2 makes the check happen during a press; this makes it runnable
  on its own, answering "can this machine press this repo at all?" It **reads
  the target's config** — it has to, since that is where the declared commands
  live — but writes nothing, mutates nothing, builds no sandbox, and executes
  none of the commands it reports on.

  Scope: **the `argv[0]` of every declared regeneration command**, plus the
  tools press itself invokes unconditionally (`git`) — reporting each as found
  (with its resolved path) or missing. Useful as a CI preflight and as the first
  thing to run when a press fails on someone else's machine.

  Nothing is derived from a filename: requiring `uv` because a target declared
  `uv.lock` would reinstate exactly the inference D1 removes, and would reject a
  machine that can perfectly well run the configured press — a target may
  rebuild `uv.lock` with any command it likes. After D1, press has no hardcoded
  regeneration command of its own, so `git` is the only tool it contributes to
  this list.

  Open: the verb name and whether it stays standalone. `press check-tools` is a
  working name; `press doctor` would collide with the existing leak-scanner
  module (`doctor.py`) and should be avoided. M6's planned `press status`
  ("computed from reality") may be the natural home, in which case this becomes
  a section of that output rather than its own verb — worth deciding when M6 is
  scoped rather than now.

  Together these preserve EMP-01's actual purpose — a target must not be able to
  blind the scanner to a file that still carries old identity — under a model
  where "does press have a regenerator for this file" has become vacuously true.

### Notes

Gap **G2** from the dogfood register
([research 0004 §G2](../docs/research/0004-py-launch-blueprint-conformance-gaps.md)),
tracked under issue #54 alongside P05.

`bun.lock` sits in `DEFAULT_RULES.exclude_files` (never rewritten) but, unlike
`uv.lock`, is absent from `regenerate` — so stale identity survives and the
verify scanner flags it. Re-verified 2026-07-25 against v3.3.0: still reproduces.

**Superseded implementation note:** this was originally scoped as "small in code
— a `bun install` branch in `cli._regenerate_lockfiles` plus the regenerate
entry". D1 removed that shape: there is no per-filename branch to add, because
the target supplies the argv. The remaining work is the declared-command model,
its migration, and D3's evidence-based exemption — larger than the original
estimate, and the reason the open questions were the real content all along.

Captured as the first of the three because it settles the declared-vs-default
policy before the destructive operation (P05) has to answer the same question.

<!-- Promote with `project-refine P04`. -->
