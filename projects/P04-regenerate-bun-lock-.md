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
  runs. Concretely: **absolute paths are rejected, `..` traversal is rejected,
  and containment is decided on the canonicalized path**, not the literal
  string. Without that, `file = "../outside.lock"` paired with
  `command = ["true"]` satisfies a naive existence check against a pre-existing
  file the target's git-based scanner cannot see, buying an exemption for a path
  outside the repo — and press would then report on a file it does not own.

  **`command` is validated at config load as well: a non-empty list of
  non-empty strings.** A malformed declaration — `command = []`, a non-string
  element, an empty `argv[0]` — fails with the intended validation error before
  planning, rather than surfacing as an incidental exception when D2 resolves
  `argv[0]` or D4 reports it.

  **Regeneration outputs must be git-tracked and clean at plan time — refused
  even under `--allow-dirty`.** Same undo-path rationale as P05 D2's dirty-reset
  refusal: the declared command overwrites the file wholesale, and git restores
  only committed content, so uncommitted edits to a declared output have no
  recoverable copy. This extends P05 D5's validate-before-mutate predicates to
  regeneration outputs.

  **Declared paths are in SOURCE coordinates and must be translated before use.**
  `apply()` renames identity-bearing directories before regeneration runs, so a
  declared `packages/demo_widget/bun.lock` no longer exists at that path by the
  time the command executes — the command produces the file at the renamed
  location while the postcondition and scan address the old one. Translate every
  declared path through `ApplyReport.renamed` before the existence check and the
  scan. (P05 solved the analogous problem for reset by running it first; that is
  unavailable here, because a regeneration command must run against the final
  tree.)

  **Path-bearing argv is rejected at plan time (decided 2026-07-26).** Only
  `file` is translated through the rename report — the command's argv is not,
  so `["bun", "--cwd", "packages/demo_widget", "install"]` goes stale the
  moment the rename pass moves that directory. Any argv element that names a
  path in the plan's rename set is a plan-time refusal (exit 2): the tool
  knows exactly which paths it will rename, so the check is a precise
  membership test. Auto-rewriting path-looking elements was considered and not
  taken — a wrong guess silently corrupts the command that then runs against
  the freshly rewritten tree; refusal fails loudly before anything is written.
  The consequence for config authors: commands must be written in
  rename-independent form (run from the target root and let `cwd` carry the
  location), and a config that cannot be is a loud plan-time error rather than
  a mid-press failure.

  **Execution contract — three properties the generic executor must preserve,
  all of which `_regenerate_lockfiles` has today and none of which are implied
  by "run the declared argv":**
  - **`cwd` is the target root.** Commands like `bun install` resolve relative
    paths against their working directory; omitting `cwd=target` means invoking
    press from another checkout can mutate *that* checkout. The output check
    would fail afterwards, but only after the out-of-target write.
  - **The environment stays scrubbed.** `cli.py` currently runs `uv lock` with
    `env=scrubbed_uv_env()`; migrating this repo's own `uv.lock` to a declared
    command must not silently drop it. An inherited `UV_*` index or config
    override can steer resolution against attacker-selected inputs.
  - **No shell.** argv is executed directly, as today — the declared form is a
    list precisely so there is no shell to inject into.

  **A file may not be both a regeneration output and a `[[reset]]` target.**
  P05 D2 already bans reset/replace overlap because the result depends on pass
  order; the same hazard exists here and is currently worse, since reset runs
  first (P05 D5) and regeneration runs after `apply` — so a file declared as
  both gets its stub written and then immediately overwritten, with both
  operations counted successful. Reject the overlap at config-load time.

  **Every regeneration output must also be listed in `exclude_files` — rejected
  at config load otherwise.** An output that is not excluded is selected by the
  normal replace pass: `apply()` rewrites and records it, then the regeneration
  command immediately overwrites that work — a misleading double-success and an
  order-dependent result, the same hazard the reset/replace overlap ban above
  exists for.

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

  **The boundary D1 requires: consent scoped to the exact command.** Target-
  declared commands execute only with explicit operator consent, and that consent
  is keyed to the specific argv — a recorded hash of the declared command, not a
  standing boolean. A changed argv requires a fresh decision.

  Consent is checked at plan time, under the same exit-2-nothing-written
  contract as D2's executable resolution: a missing or stale hash refuses the
  press before any rewrite, rename, reset, or deferred `press-source.toml`
  write — not in the regeneration executor, which runs only after `apply()` has
  already mutated the tree, where refusal would mean a partial-mutation failure
  on the common first attempt.

  **In-repo command references are allowed, and consent fingerprints their
  contents (decided 2026-07-26).** An argv like
  `["python", "scripts/regenerate.py"]` names mutable code with stable words:
  the target can change the script while the argv — and its hash — stay
  identical. So any argv element that resolves to an existing file inside the
  target (a plain membership test, no guessing which elements are paths) gets
  its content hash folded into the consent record alongside the argv hash.
  Editing the referenced script then invalidates standing consent exactly as
  editing the argv does — scheduled automation stops instead of running
  substituted code. Refusing in-repo references outright was considered and
  not taken (a target regenerating via its own helper script is expected to be
  legitimate); it remains the recorded fallback if fingerprinting proves
  insufficient in practice. **Known limit, recorded:** the fingerprint covers
  only files the argv names directly — a fingerprinted script that imports an
  unfingerprinted helper reintroduces the same exposure one level down.

  A plain `--allow-target-commands` boolean was considered and rejected because
  it collides with the R3 self-press: `scripts/rebrand_matrix.sh` invokes
  `press rebrand` with only `--accept-discovery --allow-dirty`, and the matrix
  runs automatically on PRs and on a schedule. A boolean would either break R3
  or, once added to that script, permanently authorize whatever argv the rules
  file happens to contain — scheduled automation running unreviewed commands.
  Command-scoped consent lets R3 carry standing consent for its own known
  command while a substituted one still stops.

  Two related requirements fall out of that:
  - `press/press-rules.toml` becomes **executable configuration**, so the
    rebrand-matrix workflow's path filter must include it. Today
    (`.github/workflows/rebrand-matrix.yml`) it does not, meaning a change to
    the command R3 executes would not itself trigger the matrix.
  - `--force` must NOT double as command consent. It means only "bypass an
    existing receipt" (`cli.py`), and overloading it would grant execution
    authority as a side effect of an unrelated flag.

  An executable allowlist was considered and rejected as inconsistent with D1
  (it reinstates a tool-side default); a sandbox was judged disproportionate for
  a tool the operator runs locally against a repo they chose.

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
  - Create `press/press-rules.toml` in this repo declaring **every** excluded
    file that exists here — `uv.lock` AND `bun.lock` regenerations, plus the
    `CHANGELOG.md` reset from P05 — as part of the same change that removes the
    default. An earlier draft named only `uv.lock`; a literal implementation of
    that would fail D5's own preflight on the other two.
  - Update `scripts/rebrand_matrix.sh` to carry consent for its own command.
    Adding the rules file alone does not keep the matrix green: R3 invokes the
    real self-press with only `--accept-discovery --allow-dirty`, and D1 says a
    press without consent refuses. Runbooks that document the R3 invocation need
    the same update.

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

    **The scan must also cover rendered `[[replace]]` FROM literals, not only
    identity fields.** Both `doctor.find_leaks` and `verifier.scan` check those
    literals; a post-command scan that checks only identity occurrences is again
    weaker than the exemption it buys, so a no-op regenerator leaving a rendered
    rule literal in an exempt lockfile would pass. Same failure shape as the
    matcher choice above, one level down.

    **Both scans feed on the same changed-only inputs the verifier uses.**
    `verifier.scan` compares source with destination first and scans only
    identity fields that actually differ (`_changed_fields` — a field identical
    between the two is skipped by design), and the analogous rule holds for
    rendered replacement rules whose FROM equals TO. The post-command scan must
    do the same: feeding it the full source identity turns legitimately
    retained values — an unchanged owner or author in a correct, freshly
    regenerated lockfile — into false leaks, failing exactly the partial
    rebrands the existing doctor and verifier handle.

    **Also require the declared output to still exist after the command runs.**
    Scanning alone is insufficient: a command that exits 0 having *deleted* its
    lockfile leaves nothing for `iter_target_files` to return, so the scan finds
    no stale identity and the press reports success over a silently removed
    tracked file. A declared regeneration that does not leave its file behind is
    a failed regeneration.

    **Existence is not enough — re-check type AND containment after the
    command runs.** The pre-run checks say nothing about what the command left
    behind: a command exiting 0 having replaced its output with a symlink
    satisfies a bare existence test, and the scan would then follow it. And the
    leaf check alone is not enough either — a command that replaces an
    *ancestor* directory with a symlink to an outside tree leaves
    `is_regular_lstat(target/dir/output)` passing (it checks only the leaf and
    follows the symlinked ancestor), so an outside regular file would be
    accepted and scanned. The postcondition re-runs the full containment set:
    `assert_under_root`, `assert_ancestors_real`, and the regular-file
    no-follow predicate.

    **After the LAST declared command finishes, run a final validation pass
    over every regeneration output — and re-verify P05 reset stubs.**
    Per-command postconditions are not enough once a target declares multiple
    regenerations: a later command can delete, replace, or reintroduce source
    identity into an earlier output — or modify a reset stub — after that
    output's own postcondition and scan passed, and these files stay excluded
    from the ordinary doctor and hermetic-verify inventories, so nothing
    downstream would notice. The final pass repeats the postcondition
    (existence, type, containment) and the paranoid scan for every declared
    output, plus stub equality for every reset target.

    **The undeclared case is not handled here.** A target with `uv.lock` and no
    declaration produces nothing for this scan to look at, and
    `iter_target_files` still skips it — that gap is closed by D5's preflight,
    which refuses the press outright, not by this branch. The two must ship
    together, which is exactly why D5 moves §6 to the first project.
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

    **That exemption is a gap in coverage, and verify must say so.** Declaring a
    regeneration does not prove the command rebuilds anything — a target
    declaring `{ file = "uv.lock", command = ["true"] }` still gets the file
    exempted in the sandbox, where no command ever runs. Verify therefore cannot
    certify a regenerated output; only the real press's post-command scan can.
    So verify's report must **list exempted files as not-verified rather than
    omitting them**, and its clean result must be understood as "clean over the
    scanned set". A standalone `press verify` on such a config is silent about
    that file today, which is precisely the false-clean this decision must not
    ship.

    **Decided 2026-07-26: exit-code semantics stay; the report carries the
    coverage.** Verify keeps exit 0 for a clean scan, and the report and
    receipt gain a machine-readable `exempt` field listing every skipped file
    and why it was skipped; `docs/source/reference/cli.md`'s definition of
    exit 0 changes from "fully verified" to "clean over the scanned set,
    exemptions listed". A third "clean but incomplete" exit code and treating
    skips as unclean were both considered and not taken — the former redefines
    an interface existing automation reads, the latter fails every repo with a
    lockfile forever.

- **D5 — §6's excluded-file contract preflight ships with P04 and P05 TOGETHER.**
  Revised twice. P05 D3 first said "whichever lands second"; that was changed to
  "the first project" after a review showed the interval between them leaves a
  false-clean hole. Re-verification then showed **"first" is not implementable
  either**: `CHANGELOG.md` is a built-in exclusion (`rules.py`), it exists in
  this repo carrying source identity, and P05 deliberately ships no default
  reset — so a preflight landing with P04 alone would reject this repo's own R3
  self-press, seeing a tracked excluded file with no regeneration, no reset, and
  no ignore. §6 needs *both* neutralizing mechanisms to exist before it can pass
  on a real target, and P04 alone supplies only one of them. The two projects
  therefore ship as one change, with one migration and one `press-rules.toml`
  declaring both the regenerations and the CHANGELOG reset.

  ~~lands WITH this project, not after it.~~ Revises P05 D3, which deferred it to "whichever of P04/P05 lands
  second". The deep review showed that leaves a real hole for the interval
  between them: removing the `uv.lock` default means an excluded file with no
  declared regeneration is never rebuilt **and** never scanned — the doctor
  receives all of `DEFAULT_RULES.exclude_files` and `iter_target_files` omits
  them — so source identity survives under a clean receipt. The R3 harness runs
  only a real `rebrand` with no independent grep or `press verify`, so it cannot
  catch that specific missing migration either. §6's fail-loud preflight (exit 2
  when an excluded file is neither regenerated nor reset nor `verify_ignore`d)
  is exactly the check that closes it, so it must ship with the first of the two
  projects rather than the second.

  **Known limitation, accepted:** the receipt records `regenerated = <count>`
  only, so two presses running different commands for the same output are
  indistinguishable after the fact. Recording the argv or resolved binary was
  considered twice and declined both times — the plan and dry-run already show
  the exact argv at consent time, and D1's command-scoped consent means a
  substituted command stops rather than running silently. Revisit if forensic
  reconstruction of a past press is ever needed.

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
