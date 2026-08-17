# P07 — Platform-conditional declared commands

- **Status:** `[~]` in progress

Platform-scoped rules; only matching platform triggers

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [0006 — external-target model](../docs/design/0006-external-target-model.md)
  — defines the target/config trust boundary and pre-write safety contract
- **Design:** [0009 — rendered substitution table](../docs/design/0009-substitution-table.md)
  — defines the shared consumer architecture P07 must preserve
- **Depends on:** [P06 — rendered substitution set](P06-substitution-set.md) —
  platform selection must produce the one active `Rules` view consumed by the
  shared substitution pipeline
- **Discussion:** [PR #62](https://github.com/smorinlabs/template-press/pull/62)
  — its Windows CI run exposed the need for platform-scoped declared commands
- **Prior art:** [P04 — regenerate bun.lock](P04-regenerate-bun-lock.md) —
  introduced declared `[[regenerate]]` commands and their safety gates
- **Prior art:** [P05 — reset rule](P05-reset-rule.md) — introduced declared
  `[[reset]]` rules and cross-mechanism overlap validation

### Decisions

- **D1 — Per-entry platform selector:** Add an optional `platforms` key to
  each `[[regenerate]]` and `[[reset]]` declaration. Omitting `platforms`
  keeps the declaration active on every supported platform. Parallel
  declarations for the same `file` are valid only when their normalized
  platform sets do not overlap; duplicate-target validation therefore becomes
  platform-aware.
- **D2 — Selector contract:** Accept exactly `darwin`, `linux`, and `win32`,
  matching Python's `sys.platform` values on the three supported operating
  systems. Omitting `platforms` selects all three values; it is not a wildcard
  for future values. Reject an empty list, duplicates, unknown values, malformed
  containers or elements, and values with different case or surrounding
  whitespace. A runtime outside the three-value vocabulary fails before
  selection with configuration/usage exit 2. Adding another operating system
  is welcome as a later pull request with its own contract, tests, docs, and
  package metadata.
- **D3 — Two validation phases:** Before selection, parse every declaration and
  perform environment-independent schema and global writer-overlap validation,
  including declarations inactive on the current host. After selection,
  perform declaration-specific filesystem, Git-visibility, reset-stub,
  executable-resolution, and tool checks only for active declarations; global
  product preconditions such as Git availability remain unconditional. An
  inactive declaration may reference an unavailable tool or host-specific
  file, but it may not be malformed or overlap another writer on any selected
  platform.
- **D4 — Select once and carry the result:** Introduce an immutable internal
  `SelectedRules` value containing the captured platform and the active
  `Rules`. Raw declarations remain private to config loading. Each CLI command
  obtains one `SelectedRules` value at its config boundary and passes it to all
  consumers; consumers must not reread `sys.platform` or reselect rules.
- **D5 — Active-only audit output with Git preserved:** Plans and
  `press check-tools` name the captured platform exactly once per invocation.
  Plans render only active rules. `press check-tools` always checks Git, then
  reports only regeneration tools required by active rules; missing Git or an
  active tool exits 1, while invalid config or an unsupported runtime exits 2.
  Receipts record the captured platform and only successfully executed active
  reset/regenerate actions, preserving resolved regeneration argv evidence.
- **D6 — Narrow condition boundary:** Support `platforms` only on
  `[[regenerate]]` and `[[reset]]`. Do not add conditions to `[[replace]]`,
  `[[remove]]`, or `[[rename]]`, and do not introduce architecture,
  distribution, environment, or general `when` predicates.
- **D7 — Preserve verifier independence:** Platform selection may provide the
  active `Rules` to `press verify`, but it must not provide a compiled
  substitution table, selector data, or derived scan inputs. The verifier
  continues to derive its paranoid scan independently under design 0009.
- **D8 — Prove the motivating host paths:** The repository's checked-in
  self-press configuration must contain real POSIX and Windows declarations
  for `bun.lock`. Native acceptance runs on Windows and at least one POSIX host
  must execute the matching declaration, write platform/action receipt
  evidence, and leave the regenerated lockfile identity-clean.

### Configuration shape

Option A attaches `platforms` directly to each declared action. Repeating a
`file` is valid only when the normalized platform sets are disjoint:

```toml
[[regenerate]]
file = "bun.lock"
command = ["scripts/regen-bun-lock.sh"]
platforms = ["darwin", "linux"]

[[regenerate]]
file = "bun.lock"
command = ["powershell", "-NoProfile", "-File", "scripts/regen-bun-lock.ps1"]
platforms = ["win32"]

[[reset]]
file = "CHANGELOG.md"
stub = "# Changelog\n"
platforms = ["darwin", "linux", "win32"]
```

### Scope

- Add optional `platforms` selectors to `[[regenerate]]` and `[[reset]]`.
- Validate every declaration and reject overlapping writers for the same file
  on any platform.
- Support exactly macOS (`darwin`), Linux (`linux`), and Windows (`win32`) in
  this project; fail fast on any other runtime.
- Select the current platform once into `SelectedRules`, using an injectable
  platform value in tests and `sys.platform` in production.
- Pass that one selected result through preflight, planning,
  `press check-tools`, apply, doctor, verification support, and receipts.
- Keep pre-selection validation environment-independent and run environmental
  preflight only for active declarations.
- Preserve `press check-tools`' unconditional Git requirement while making
  declared-tool checks active-only.
- Preserve existing behavior when `platforms` is omitted.
- Add macOS, Linux, and Windows tests for selection, validation, safety gates,
  output, and receipts.
- Add real Windows and POSIX self-press acceptance for the checked-in
  `bun.lock` regeneration declarations.
- Update the CLI reference, design 0009, support documentation, and package
  operating-system classifiers to match the three-host contract.

### Out of scope

- Conditions on `[[replace]]`, `[[remove]]`, or `[[rename]]`.
- Architecture, distribution, environment, or arbitrary `when` predicates.
- A user-facing `--platform` override.
- Automatic command translation or fallback between platforms.
- Changes to existing command-execution or reset-stub semantics.
- Runtime support outside macOS, Linux, and Windows in this project; later pull
  requests may extend the explicit selector, test, documentation, and metadata
  contract.

### Open questions

- None.

### Tests & Tasks

- [x] [P07-TS01] Add failing unit tests for the exact `darwin`/`linux`/`win32`
      vocabulary; omitted, empty, duplicate, unknown, wrong-case, and
      whitespace-padded selectors; string containers; integer, Boolean, and
      mixed-type elements; unsupported runtimes; environment-independent
      validation of inactive declarations; disjoint same-file declarations;
      same-mechanism and reset/regenerate overlap rejection; stable declaration
      order; unchanged behavior for configurations without `platforms`; and a
      supported-runtime replacement for the existing FreeBSD-specific atomic
      rename scenario plus an explicit unsupported-runtime assertion.
- [ ] [P07-T01] Extend the regenerate/reset models and config allowlists with
      normalized platform sets; validate raw declarations and overlaps before
      selection; reject unsupported runtimes; and implement the immutable
      `SelectedRules` boundary with one pure, injectable selector that defaults
      to `sys.platform` in production. Keep raw declarations private, make TS01
      pass without a CLI override.
- [ ] [P07-TS02] Add failing integration tests proving that rebrand preflight,
      planning, `press check-tools`, apply, doctor, and `press verify` derive
      the same captured `SelectedRules`; inactive declarations do not fail for
      missing executables or missing/non-UTF-8 reset stub files; the paired
      active cases do fail; the excluded-file safety gate evaluates
      neutralization on the selected platform only; and `press verify` remains
      independent of table-derived scan inputs.
- [ ] [P07-T02] Implement the two validation phases and thread one
      `SelectedRules` value through every existing consumer without
      consumer-local filtering or platform reads. Make TS02 pass while
      preserving the plan-before-write, independent-verifier, and
      no-receipt-on-failure guarantees.
- [ ] [P07-TS03] Add failing output and receipt tests requiring the selected
      platform exactly once in combined reset/regenerate plan and
      `press check-tools` output; active declarations only in normal output;
      Git always checked even when no declaration is active; only active
      regeneration tools checked after Git; exit 1 for missing Git/active
      tools; exit 2 for invalid config/unsupported runtimes; and the captured
      platform plus successfully executed active actions in
      `press/press-receipt.toml`.
- [ ] [P07-T03] Implement the active-only audit contract for plans,
      `press check-tools`, and receipts; preserve the unconditional Git check
      and resolved regeneration argv evidence; add machine-readable
      reset-action evidence; and make TS03 pass.
- [ ] [P07-TS04] Add failing native acceptance coverage for the repository's
      self-press on Windows and at least one POSIX host. Use the real checked-in
      platform-specific `bun.lock` declarations and require successful matching
      command execution, captured platform/action receipt evidence, a
      regenerated identity-clean `bun.lock`, and no inactive action evidence.
- [ ] [P07-T04] Add the Windows-capable `bun.lock` regeneration helper and
      disjoint POSIX/Windows Option A declarations to `press/press-rules.toml`;
      extend the acceptance workflow so R3 self-press runs natively on Windows
      and at least one POSIX host; and make TS04 pass.
- [ ] [P07-T05] Update `docs/source/reference/cli.md` with the schema,
      three-host support contract, omission and validation behavior, disjoint
      same-file rules, two validation phases, active-only behavior, and Git
      requirement. Update design 0009 with the flow `parsed declarations` →
      `schema/overlap validation` → `platform selection` → `active Rules` →
      table consumers plus the independent verifier path. Replace the
      `Operating System :: OS Independent` package classifier with
      `Operating System :: MacOS`, `Operating System :: POSIX :: Linux`, and
      `Operating System :: Microsoft :: Windows`.
- [ ] [P07-T06] Run the focused rule, preflight, CLI, check-tools, verify,
      receipt, and native-acceptance suites; run `just check` and `just matrix`;
      verify the Linux/macOS/Windows CI matrix and native Windows/POSIX R3
      self-press; perform an adversarial review against D1-D8 and the P04-P06
      safety contracts; fix reproduced in-scope defects; then rerun every
      affected gate before merge.

### Notes

Independent Fable and Sol adversarial reviews on 2026-08-16 returned
revise-before-execution. Decisions D2-D8 and tasks TS01-T06 incorporate the
accepted R1-R7 amendments; no owner decisions remain open.

Born from PR #62's Windows CI run: declared commands are target-declared and
inherently platform-specific. Today, a POSIX `sh` regeneration script cannot
resolve on Windows, so the engine refuses before mutation and
`press check-tools` exposes the missing tool. P07 preserves that fail-closed
behavior while allowing a declared Windows alternative to become active.

The mechanism composes with the existing contracts for free: with
platform-scoped entries, the §6 excluded-file preflight evaluates
**per-platform** — if `bun.lock`'s only declared command is POSIX-scoped and
the press runs on Windows, the file has no neutralization *there*, so the
press refuses loudly (exit 2, naming the file), which remains the correct
behavior. `press check-tools` still checks Git unconditionally, then reports
only declared tools active on the captured platform.

The selected Option A shape uses two declarations covering three platforms:
an `sh` script for `darwin` and `linux`, and a PowerShell script for `win32`.
Only the matching declaration triggers.
