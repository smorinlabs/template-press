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
  matching Python's `sys.platform` values on the supported hosts. Omitting
  `platforms` selects all three. Reject an empty list, duplicate values, and
  unknown values during config loading.
- **D3 — Validate, then select once:** Parse and validate every declaration on
  every host, including declarations inactive on that host. Validate selector
  syntax and cross-declaration platform overlaps before selecting the current
  platform. Selection then produces one active `Rules` view, which is compiled
  into the P06 substitution pipeline and shared by every downstream consumer.
- **D4 — Active-only audit output:** Plans name the selected platform once and
  render only active rules. `press check-tools` names that platform and reports
  only tools required by active rules. Receipts record the selected platform
  and active reset/regenerate actions. Normal output omits inactive
  declarations because they are not planned actions on that host.
- **D5 — Narrow condition boundary:** Support `platforms` only on
  `[[regenerate]]` and `[[reset]]`. Do not add conditions to `[[replace]]`,
  `[[remove]]`, or `[[rename]]`, and do not introduce architecture,
  distribution, environment, or general `when` predicates.

### Scope

- Add optional `platforms` selectors to `[[regenerate]]` and `[[reset]]`.
- Validate every declaration and reject overlapping writers for the same file
  on any platform.
- Select the current platform once, using an injectable platform value in
  tests and `sys.platform` in production.
- Pass one active `Rules` view through preflight, planning,
  `press check-tools`, apply, doctor, verification support, and receipts.
- Preserve existing behavior when `platforms` is omitted.
- Add macOS, Linux, and Windows tests for selection, validation, safety gates,
  output, and receipts.

### Out of scope

- Conditions on `[[replace]]`, `[[remove]]`, or `[[rename]]`.
- Architecture, distribution, environment, or arbitrary `when` predicates.
- A user-facing `--platform` override.
- Automatic command translation or fallback between platforms.
- Changes to existing command-execution or reset-stub semantics.

### Open questions

- None.

### Tests & Tasks

- [ ] [P07-TS01] Add failing tests for selector validation, platform
      selection, overlap rejection, and active-rule propagation.
- [ ] [P07-T01] Implement `platforms` parsing, normalization, overlap
      validation, and a pure platform-selection function that makes TS01 pass
      while preserving configurations that omit `platforms`.

### Notes

Born from PR #62's Windows CI run: declared commands are target-declared and
inherently platform-specific — a POSIX `sh` regeneration script is a
legitimate declaration that simply cannot resolve on Windows, and the engine
already reports exactly that (missing tool, loud plan-gate refusal;
`press check-tools` shows it before pressing).

The mechanism composes with the existing contracts for free: with
platform-scoped entries, the §6 excluded-file preflight evaluates
**per-platform** — if `bun.lock`'s only declared command is POSIX-scoped and
the press runs on Windows, the file has no neutralization *there*, so the
press refuses loudly (exit 2, naming the file), which is already the correct
behavior. `check-tools` likewise reports only the entries active on the
current platform.

Example shape: the same regeneration declared three ways (darwin / linux /
win32) with only the matching entry triggering — e.g. an sh script on POSIX
and a `.bat`/`.exe` shim on Windows.
