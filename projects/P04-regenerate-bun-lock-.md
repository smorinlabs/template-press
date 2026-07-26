# P04 — Regenerate bun.lock during a press

- **Status:** `[?]` idea

Neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks

### Decisions

All three open questions settled 2026-07-25 (walkthrough in chat).

- **D1 — Regeneration commands are fully target-declared.** A target declares
  both the file and the argv that rebuilds it, e.g.
  `{ file = "bun.lock", command = ["bun", "install"] }`. Nothing is inferred
  from a filename, so there is no hidden filename-to-command mapping.

  **This deliberately reverses a documented guarantee** and must be recorded as
  such rather than discovered later: today `regenerate` is a list of filenames
  and the only argv press ever runs is a literal `["uv", "lock"]` baked into
  `cli.py`, so a pressed repo's config cannot make press execute a program of
  its choosing (design 0007 D3/D5, EMP-01). After D1 it can. The threat model
  that makes this acceptable: pressing a repo already means running that repo's
  build tooling — `uv lock` itself executes arbitrary build backends — so the
  config is not a new trust boundary, only a more explicit one. Whoever
  implements this should carry that reasoning into the design doc, and D3 below
  is what keeps the change from also weakening leak detection.

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
  on its own, answering "can this machine press this repo at all?" without
  touching the repo. Read-only, no writes, no sandbox.

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
