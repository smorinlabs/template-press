# P04 — Regenerate bun.lock during a press

- **Status:** `[~]` in progress

Neutralize bun.lock: excluded from rewrite but never regenerated, so it always leaks

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Research:** [0004 — py-launch-blueprint conformance gaps, §G2](../docs/research/0004-py-launch-blueprint-conformance-gaps.md)
- **Research:** [0005 — scaffolder identity-variant handling](../docs/research/0005-scaffolder-identity-variant-handling.md)
- **Design:** [0006 — external target model](../docs/design/0006-external-target-model.md)
- **Ticket:** issue #54 (the G1/G2 dogfood gaps)
- **PRs:** #56 (P05 decisions) · #57 (P04 decisions — four adversarial review
  rounds; findings cited in-body by thread id)
- **Sibling:** [P05 — reset rule](P05-reset-rule.md) — ships together per D5

### Scope

The declared-command regeneration model per D1–D5 as revised: the
`[[regenerate]]` config schema and its load-time validation; the plan→apply
flow (dry-run renders every command verbatim; a mutating run prints the same
plan and executes it — no consent tokens); the execution contract (cwd =
target root, no shell, deny-by-default platform-specific environment);
plan-time executable resolution and stale-path refusal; the post-command and
final-pass scans; hermetic-verify exemption semantics with the
machine-readable `exempt` field; the §6 excluded-file preflight (shared with
P05); `press check-tools`; and the migration — this repo's own
`press/press-rules.toml`, bun provisioning in the rebrand-matrix workflow,
and rejection of the legacy list-of-strings `regenerate` form.

### Out of scope

- Saved-plan mode (`--plan-out` / `--apply-plan`) — deferred until a
  plan/apply-separated workflow actually exists.
- P06 substitution-set refactor (issue #42) — sequenced after this ships.
- M6 `provision` / `status` verbs.
- py-launch-blueprint conformance work (it consumes this; separate effort).

### Open questions

None — the five 2026-07-26 walkthrough answers are recorded in the decisions,
the D4 verb is decided (`check-tools`), and the consent machinery is
superseded by plan→apply.

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
  knows exactly which paths it will rename, so the check is precise. It is
  **prefix-aware, not exact-match** — the rename set collapses to the
  shallowest moved directory (`packages/demo_widget`), and an argv naming a
  descendant (`packages/demo_widget/regenerate.py`) goes just as stale, so
  refusal fires when an element equals OR sits beneath any renamed path.
  Elements are **normalized before comparison** — resolved against the target
  root, separators unified (`.\tools\regenerate.exe` is path-qualified just
  like `./tools/regenerate`), `.`/`..` segments collapsed — so spellings like
  `./packages/demo_widget` or `packages/demo_widget/../demo_widget` cannot
  slip past the membership test; the same normalization feeds the
  path-qualified `argv[0]` classification in D2.
  Auto-rewriting path-looking elements was considered and not
  taken — a wrong guess silently corrupts the command that then runs against
  the freshly rewritten tree; refusal fails loudly before anything is written.
  The consequence for config authors: commands must be written in
  rename-independent form (run from the target root and let `cwd` carry the
  location), and a config that cannot be is a loud plan-time error rather than
  a mid-press failure.

  **Detection is best-effort over recognized shapes, and recorded as such.**
  An attached-option payload (`--config=packages/demo_widget/config.toml`) or
  other tool-specific syntax can carry a path the membership test cannot see
  without guessing argv semantics — the same guesswork this decision rejects.
  An undetected stale path is not silent corruption: the command fails loudly
  mid-press and D4's abort withholds the receipt. Enumerating further shapes
  is an implementation-test concern, not a decision.

  **Execution contract — three properties the generic executor must preserve,
  all of which `_regenerate_lockfiles` has today and none of which are implied
  by "run the declared argv":**
  - **`cwd` is the target root.** Commands like `bun install` resolve relative
    paths against their working directory; omitting `cwd=target` means invoking
    press from another checkout can mutate *that* checkout. The output check
    would fail afterwards, but only after the out-of-target write.
  - **The environment is deny-by-default (decided 2026-07-26).** Declared
    commands run under a minimal fixed base (`PATH`, `HOME`, `LANG`, `TMPDIR`)
    plus only the variables the declaration names:

    ```toml
    [[regenerate]]
    file    = "bun.lock"
    command = ["bun", "install"]
    env     = ["NODE_ENV"]           # optional; names, never values
    ```

    `env` lists names — press copies each from the operator's environment at
    run time; values never live in the config, so a repo cannot smuggle
    secrets in and the operator's real setting is what flows through. The
    list is part of the declaration: every plan and apply prints it beside
    the argv, so widening it (say, adding `GITHUB_TOKEN`) is visible on each
    run — under plan→apply, visibility is the guard.

    `env` is validated at config load like `command`: a list of non-empty,
    platform-valid variable names — no `=`, no NUL, no non-strings. A
    declared name absent from the operator's environment is simply omitted
    from the child env (the declaration is permission, not a requirement),
    and the dry-run shows which declared names would actually apply.

    **The minimal base is platform-specific.** The Unix base (`PATH`, `HOME`,
    `LANG`, `TMPDIR`) is wrong on Windows — a first-class platform here —
    where process loading and tool discovery need `SystemRoot`, `PATHEXT`,
    `USERPROFILE`, and `TEMP`/`TMP`, while `HOME` and `TMPDIR` may not exist
    at all. Each platform defines its own base, and D2's plan-time resolution
    runs under that exact effective environment, so a command cannot pass
    planning under the operator's env and then fail at launch under the
    stripped one.

    This supersedes the uv-specific scrub as the general mechanism, and
    subsumes it: inherited `UV_*` overrides simply never arrive.
    Inherit-minus-blocklist was considered and not taken — today's
    `scrubbed_uv_env` IS a one-family blocklist, and it aged out the moment
    the command stopped being fixed; a blocklist's miss is silent, while
    deny-by-default fails loudly and the fix is one visible declared line.
    Inherit-everything was rejected for the CI case alone: an Actions
    runner's `GITHUB_TOKEN` must not be readable by target-declared code.
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

  **Press-owned control files are reserved.** `ROOT_CONTROL` paths — the
  receipt and `press/press-source.toml`, which press itself writes *after*
  regeneration validation has finished — may not be declared as regeneration
  outputs or reset targets; rejected at config load. Otherwise the validated
  "final" artifact would be silently overwritten by press's own source-config
  persistence, leaving the reported regenerated result different from what
  ends up on disk.

  Reservation alone is not protection, because a declared command can
  mutate arbitrary files and `ROOT_CONTROL` is omitted from the downstream
  doctor and verifier inventories. The final validation pass therefore
  snapshots reserved control files before the first command and revalidates
  their type, containment, and content after the last one; a mismatch aborts
  the press — the rules that ran are no longer the rules that were planned
  and validated.

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

  **REVISED 2026-07-26 (post-merge): the consent machinery below is SUPERSEDED
  by a plan→apply flow.** The token/hash model — argv hashes, referenced-file
  fingerprints, env names and command order folded into a consent record,
  pre-launch fingerprint revalidation, the appeared-between-plan-and-launch
  and symlink-reference refusals — is not implemented. The recorded decision
  is Terraform-shaped:

  - `press rebrand --dry-run` renders the full plan, including every declared
    command verbatim — argv, cwd, the env names it may see, what it rebuilds.
  - A mutating `press rebrand` prints the same plan and executes it. Running
    apply IS the approval; there are no tokens.
  - A saved-plan mode (`--plan-out` / `--apply-plan`, refusing on drift like
    `terraform apply <planfile>`) is deferred until a plan/apply-separated
    workflow actually exists; the deterministic plan object keeps that purely
    additive.

  Why: press is a deliberately invoked tool with a plan step — the tool class
  (make, just, pre-commit, terraform) that gates by visibility, not by hash.
  Hash-scoped standing consent (direnv `allow`, mise `trust`) compensates for
  AMBIENT execution, which press does not have. The CI argument for argv-scoped
  consent does not hold either: the R3 workflow already executes arbitrary
  repo code (tests, scripts, hooks), so guarding one argv is a locked window
  next to an open door — the real boundary is the runner's isolation. And four
  review rounds spent roughly half their findings on edge cases of the consent
  mechanism itself, the signature of a feature generating bug surface faster
  than it closes exposure.

  What survives, on correctness (not approval) grounds: the deny-by-default
  environment, `cwd` = target root, no shell, plan-time executable resolution,
  mode preservation on rewritten files, and every scan, postcondition, and
  preflight. In-repo helper scripts are simply allowed and shown in the plan.
  The paragraphs below are kept for the record.

  **The boundary D1 requires: consent scoped to the exact command.** Target-
  declared commands execute only with explicit operator consent, and that consent
  is keyed to the specific argv — a recorded hash of the declared command, not a
  standing boolean. A changed argv requires a fresh decision.

  Consent is checked at plan time, under the same exit-2-nothing-written
  contract as D2's executable resolution: a missing or stale hash refuses the
  press before any rewrite, rename, reset, or deferred `press-source.toml`
  write — not in the regeneration executor, which runs only after `apply()` has
  already mutated the tree, where refusal would mean a partial-mutation failure
  on the common first attempt. Enforcement gates mutation, not visibility:
  `--dry-run` still renders the full plan — the exact argv, the declared env
  list, and the consent value a grant would need — and keeps its documented
  exit-0 contract, so the operator can obtain the token they are being asked
  to approve. Only a mutating run refuses on missing or stale consent.

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

  **The fingerprint covers the bytes that will EXECUTE, not the bytes on disk
  at plan time.** A referenced helper may itself be rewritten by the replace
  pass before the executor runs, and the `[[replace]]` rules are
  target-supplied — hashing the pre-apply file would leave consent standing
  while a changed rule changes the executed code. Press computes the planned
  post-apply content of each referenced file at plan time (the replacement
  pass is deterministic from the plan) and consent covers THAT. And because a
  preceding declared command can rewrite a file a later command references,
  each referenced file's fingerprint is revalidated immediately before its
  command launches — a mismatch aborts the press (D4 posture).

  Two boundary conditions of that membership test, decided the same way as
  everything else here (no-follow, fail closed):
  - **A symlink is refused as a command reference, wherever it points.**
    A tracked link to a file outside the target fails the inside-target test
    while still executing target-controlled bytes; re-pointing the link
    changes what runs while the argv and the unfollowed reference stay
    stable. The membership test uses the same no-follow containment
    discipline as every other path check.
  - **Rewriting a referenced helper preserves its file mode.** `safe_write`'s
    atomic temp-plus-rename creates a fresh inode and today never restores
    the original permission bits (`_atomic_write_bytes`), so a `0755` helper
    would come out non-executable and fail only at launch, after the tree is
    mutated. The replacement pass restores each rewritten file's original
    mode.
  - **A reference that appears between plan and launch aborts.** If an
    earlier declared command *creates* `scripts/regenerate.py` and a later
    command names it, the file was absent at plan time — nothing was
    fingerprinted, so nothing exists to revalidate, and standing argv-only
    consent would execute newly minted code. The pre-launch revalidation
    therefore re-runs the same membership test against the *current* tree:
    an argv element that now resolves to an in-target file but carries no
    plan-time fingerprint refuses the launch. Precise — the same test run
    twice, no path-guessing — and running produced code requires a fresh
    consent round after the payload exists.

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

  **END of the record-only region — text from here on is live.** (One
  requirement from the record region survives on its own merits, restated
  here as live: `press/press-rules.toml` is executable configuration — it
  names the commands R3 runs — so the rebrand-matrix workflow's path filter
  must include it, or a change to those commands would not itself trigger
  the matrix. Lands with P04-T15.)

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
  - ~~Update `scripts/rebrand_matrix.sh` to carry consent for its own
    command.~~ **Superseded by the plan→apply revision** — with no consent
    token, R3's existing invocation keeps working; the remaining migration
    items are the rules file plus the workflow's bun provisioning and its
    `press-rules.toml` path filter (all in P04-T15).
  - Provision the declared commands in CI: `.github/workflows/rebrand-matrix.yml`
    installs only uv today, and the migrated rules file makes D2's preflight
    require `bun` — without the pinned bun installer in the workflow, R3
    exits 2 before pressing on any runner lacking an incidental bun install.

- **D2 — Resolve every declared command at plan time; missing tool exits 2.**
  Before any write, check each command's executable resolves. A missing
  tool becomes a clean refusal with nothing written instead of a failure
  discovered after the rewrite pass has already mutated the repo.

  Resolution semantics must match execution exactly: a path-qualified
  `argv[0]` (`"./tools/regenerate"` — anything containing a slash) resolves
  relative to the target root, which is the mandatory execution `cwd`, and
  never via PATH; only bare names resolve on PATH. Checking a target-local
  executable from the press caller's directory would exit 2 for a command
  the real invocation, running with `cwd=target`, would find and run.

  Resolution is bound to the effective execution environment and then
  **pinned**: plan-time lookup runs under the same deny-by-default env whose
  fixed base supplies `PATH`, and the resolved absolute path is what
  executes — no second runtime PATH lookup exists to diverge from what was
  planned and shown in the plan. And the plan renders that pinned path
  beside the declared argv: plan visibility is the approval guard, so the
  plan must show the executable that will actually launch, not only the
  words that selected it. Consistent
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

    Two path-shaped refinements of the same evidence standard: the paranoid
    scan covers every component of the **translated output path** as well as
    its contents — an identity token that doubles as the lockfile's own name
    (`app_name = "bun"` with output `bun.lock`) survives in the *filename*
    precisely because the output is excluded from the rename pass. And
    rendered rules carry file scopes in source coordinates, so scanning a
    renamed output at its destination must **reverse-map the scope through
    `ApplyReport.renamed`** — the same reverse-mapped predicate the doctor
    and verifier already use — or a rule scoped `packages/demo_widget/**`
    silently stops matching the moved file it was written for.

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
    output. For every reset target it repeats the same full guard set —
    `assert_under_root`, `assert_ancestors_real`, and the no-follow
    regular-file check — before comparing content: stub equality alone would
    follow a symlink a later command planted and accept matching outside
    content. And because reset paths are consumed in source coordinates
    before the rename pass (P05 D5) while this check runs after it, reset
    paths are translated through `ApplyReport.renamed` here exactly as
    regeneration outputs are — validating the declared source path would
    report a validly moved stub as missing.

    **A stub must not itself restore old identity.** Stub equality proves
    only that later commands did not alter the reset result — a declared stub
    whose content carries a changed source token or a rendered `[[replace]]`
    FROM literal would "neutralize" the exclusion while deliberately keeping
    old identity in the tree, invisible to every downstream inventory. Stub
    content is validated at plan time with the same changed-only paranoid
    identity and rendered-literal scan the post-command check uses. The final
    pass also scans the **translated reset-target path components** with the
    same paranoid matcher — an excluded filename can itself carry changed
    identity (`app_name = "changelog"` → `CHANGELOG.md`), and downstream
    inventories never look at it (thread 3653398575).

    **Sink guards re-run immediately before EACH command launches.** With
    multiple declarations, an earlier command can plant a symlink or hardlink
    at a later output's path or an ancestor; an in-place-truncating later
    command would then corrupt an outside file before any post-command check
    runs. The full set — containment, real ancestors, no-follow regular
    file, `st_nlink == 1` — is re-checked per command, not only at plan time
    and afterwards.

    **Decided 2026-07-26: a non-UTF-8 output cannot earn the exemption — fail
    closed.** The exemption is bought with the post-command text scan; a file
    that scan cannot read cannot buy it. The gate applies at both ends:
    at plan time the tracked pre-state must decode as UTF-8 (outputs are
    required tracked and clean, so there is a pre-state to check), and as a
    postcondition the produced output must still decode — a command that
    exits 0 having emitted undecodable bytes fails the press. The verifier
    does carry a raw-bytes path (`_scan_binary`) for its own inventory, but
    parity with it was rejected along with the raw-bytes option: fail-closed
    means no undecodable output is ever scanned-and-exempted at all.
    Such files route through the explicit `verify_ignore` list instead, keeping
    the coverage gap visible and deliberate rather than an unchecked free pass.
    This restricts what may be exempt from scanning — not what files a repo may
    contain or what a command may produce. Practical cost today is zero: every
    real regeneration target is a text lockfile. Extending a raw-bytes scan to
    binaries was considered and not taken — it catches ASCII-embedded identity
    only, partial evidence that can still false-clean.

    **The undeclared case is not handled here.** A target with `uv.lock` and no
    declaration produces nothing for this scan to look at, and
    `iter_target_files` still skips it — that gap is closed by D5's preflight,
    which refuses the press outright, not by this branch. The two must ship
    together, which is exactly why D5 ships §6 with P04 and P05 as one change.
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

    **The tool-side list matches by basename at any depth, not by exact
    root-relative path.** Today's `scan_paths` exemption names only literal
    root-level artifacts, so a supported nested declaration like
    `packages/demo_widget/bun.lock` would never be exempted — hermetic verify
    would flag forever a file the real press regenerates and validates.
    Basename-on-the-list plus the target's declaration for that exact path
    keeps the tool-side cap while covering nested outputs. And since T02
    removes `DEFAULT_RULES.regenerate` — today's de-facto source of that
    cap in `scan_paths` — the list becomes its own explicit constant
    (`uv.lock`, `bun.lock`), never derived from `exclude_files`, which would
    wrongly exempt `CHANGELOG.md`-class artifacts. The declaration-side half
    maps coordinates too: sandbox `apply()` has renamed the tree by scan
    time, so declared source-coordinate outputs are translated through
    `ApplyReport.renamed` before the exact-path comparison — basename alone
    matches a nested `packages/demo_widget/bun.lock`, but the path half
    would fail forever without the translation.

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
  projects rather than the second. *(This "first project" framing is itself
  superseded by the final ruling above: the preflight ships with both projects
  together.)*

  **REVISED 2026-07-26 with the plan→apply supersession: the receipt records
  each regeneration's resolved argv.** The count-only form was accepted twice
  on grounds the supersession deleted — command-scoped consent meant a
  substituted command stopped, so the consent record doubled as the forensic
  trace. Under plan→apply nothing stops a config change between two runs, and
  the receipt is the only artifact recording what actually ran; recording the
  resolved argv per output is cheap and closes the gap (lands with P04-T08).

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

  Resolution uses D2's exact semantics — path-qualified `argv[0]` against
  the target root, bare names on PATH under the deny-by-default effective
  environment, the resolved path pinned — so its answer cannot diverge from
  what the real press would do (thread 3653479445).

  Nothing is derived from a filename: requiring `uv` because a target declared
  `uv.lock` would reinstate exactly the inference D1 removes, and would reject a
  machine that can perfectly well run the configured press — a target may
  rebuild `uv.lock` with any command it likes. After D1, press has no hardcoded
  regeneration command of its own, so `git` is the only tool it contributes to
  this list.

  **Decided 2026-07-26: `press check-tools`, a standalone verb.** `press
  doctor` stays avoided (it collides with the leak-scanner module
  `doctor.py`). If M6's planned `press status` later wants this as a section,
  it can absorb the standalone verb then — shipping it now is not blocked on
  M6 scoping.

  Together these preserve EMP-01's actual purpose — a target must not be able to
  blind the scanner to a file that still carries old identity — under a model
  where "does press have a regenerator for this file" has become vacuously true.

### Tests & Tasks

- [x] [P04-TS01] Failing tests: `[[regenerate]]` schema + config-load
      validation — legacy list form rejected with a schema TEMPLATE carrying
      a placeholder command (never a derived argv, which would reinstate the
      filename→command inference D1 removes); `command` a non-empty list of
      non-empty NUL-free strings; `env` valid names; `file` containment
      (SafeRelPath, no-follow); output must be in `exclude_files`, tracked,
      clean even under `--allow-dirty`, `st_nlink == 1`; replace +
      `ROOT_CONTROL` overlap bans (the cross-mechanism reset⊗regenerate
      overlap test lands in TS11, once both schemas exist)
- [x] [P04-T02] Implement the schema + validation to pass TS01; remove
      `DEFAULT_RULES.regenerate`
- [x] [P04-TS03] Failing tests: plan time — executable resolution (bare name
      → PATH, slash → target root, under the effective env, pinned absolute
      path); stale-argv refusal (normalized, prefix-aware, best-effort);
      dry-run renders every command verbatim PLUS its resolved pinned
      executable path (the plan must show what will actually launch);
      exit 2 = nothing written
- [x] [P04-T04] Implement plan-time resolution, stale-path refusal, and the
      plan→apply rendering (no consent machinery)
- [x] [P04-TS05] Failing tests: executor — cwd = target root, no shell,
      deny-by-default env (platform base + declared names, absent names
      omitted), file-mode preservation on rewritten files; sink guards
      re-run before each command launch (symlink/hardlink planted by an
      earlier command at a later output's path)
- [x] [P04-T06] Implement the generic executor replacing the hardcoded
      `uv lock` branch in `_regenerate_lockfiles`
- [x] [P04-TS07] Failing tests: postconditions — output exists; full
      containment + type recheck; UTF-8 two-point gate; paranoid
      changed-fields scan incl. rendered FROM literals, translated path
      components, reverse-mapped scopes; final pass over outputs, reset
      stubs, and `ROOT_CONTROL` after the last command (multi-command
      corruption cases)
- [x] [P04-T08] Implement the postconditions + final validation pass; the
      receipt records each regeneration's resolved argv
- [x] [P04-TS09] Failing tests: hermetic verify — exemption requires
      tool-list basename + target declaration; the tool list is an explicit
      constant (`uv.lock`, `bun.lock`), not derived from the removed default
      or from `exclude_files` (CHANGELOG.md must NOT be exemptible); exempt
      files listed as not-verified; exit 0 with a machine-readable `exempt`
      field
- [x] [P04-T10] Implement verify exemption semantics + the `exempt` field in
      BOTH the verify report and the receipt (each skipped file with its
      reason); update `docs/source/reference/cli.md` exit-0 wording
- [x] [P04-TS11] Failing tests: §6 preflight — a tracked excluded file with
      no regenerate/reset/verify_ignore refuses (exit 2) naming the file and
      the three fixes (shared with P05); plus the cross-mechanism
      reset⊗regenerate overlap rejection, now that both schemas exist
- [x] [P04-T12] Implement the §6 preflight
- [x] [P04-TS13] Failing tests: `press check-tools` — reports `argv[0]` of
      every declared command plus `git`, each found (resolved path) or
      missing, using D2's exact resolution semantics (target-root
      path-qualified, deny-by-default effective env); reads config, writes
      nothing, executes nothing
- [x] [P04-T14] Implement `press check-tools`
- [x] [P04-T15] Migration: create `press/press-rules.toml` (uv.lock +
      bun.lock regenerations, CHANGELOG reset); pinned bun installer and a
      `press-rules.toml` path filter in `.github/workflows/rebrand-matrix.yml`;
      update runbooks
- [ ] [P04-T16] On a `--force` re-press, invalidate the prior receipt after
      the plan gates pass and before the first mutation — with a failing
      test for the failed-forced-re-press case first; a failed forced
      re-press must not leave the old receipt advertising a verified press
      (PR #56 thread 3651682614, previously undispositioned)
- [ ] [P04-T17] Full verification LAST: `just check` and `just matrix` green
      with the migrated rules and every behavior above inside the pipeline

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

**Carried to implementation (final review round; tasks, not decision prose):**

- Reset targets get the same path-component scan as regeneration outputs — an
  excluded filename that itself carries changed identity
  (`app_name = "changelog"` → `CHANGELOG.md`) must not survive under a clean
  receipt (thread 3653398575).
- Regeneration outputs with `st_nlink > 1` are refused at plan time — an
  in-place-truncating regenerator would corrupt the external inode, and unlike
  reset, no `safe_write` new-inode guarantee applies (thread 3653398576).
- P05's reset write preserves the target's original permission mode —
  `mkstemp`'s `0600` must not replace a `0644` changelog or strip execute
  bits (thread 3653398581).

