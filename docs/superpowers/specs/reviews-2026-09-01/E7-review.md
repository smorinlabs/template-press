# E7 adversarial review — declared-command tool version pinning (entry #11, friction)

**Verdict: REJECT the engine change.** The fix is required and belongs in the blueprint's
`scripts/regen-bun-lock.sh`. Confidence: high. The incident is real, but the remedy is aimed
at the wrong layer and half of it already shipped.

## 1. Steelman: the engine as-is is already correct here
- **Nothing is inferred from a filename.** P04 D1 (`projects/P04-regenerate-bun-lock.md:53`,
  `:369`) removed the filename→command mapping; `RegenerateRule` (`rules.py:85-108`) states
  "the target supplies the command." `tool = "bun"` re-imports the semantics D1 evicted.
- **Resolution is already pinned and visible.** `resolve_executable` (`regen.py:135-157`)
  returns an absolute path under the deny-by-default env; `execute_regenerations` launches
  `plan.executable` (`regen.py:306`), no second PATH lookup; `render_regenerate_plan`
  (`regen.py:342-357`) prints it; an absolute argv0 already works (`regen.py:145-150`).
- **`env` passthrough already exists**, names-only (`regen.py:116-131`, `rules.py:88-89`);
  the proposed `env = {…}` *values* map reverses P04 D1 and re-opens the `UV_INDEX_URL`-class
  leak the base env exists to close.
- **P07 D6** (`projects/P07-platform-conditional-declared-commands.md:62-66`) forbids
  "architecture, distribution, **environment**, or general `when` predicates"; a version
  constraint is one.

## 2. Attacking the proposal
**(a) Half of it already shipped.** P04 D2 logged receipt capture as "considered and not
taken" (`P04:406-408`), but the revision landed: `cli.py:587-591` writes
`(plan.executable, *rule.command[1:])` into `[[press.regenerate]]`, documented at
`receipt.py:87-89` as the "P04 D5 revision", asserted by
`tests/rebrand/test_regenerate_postconditions.py:518-532`. Only **version** capture is new.
The receipt already carries absolute machine paths and `platform` (`receipt.py:72`), so
"non-comparable receipts" is not a fresh objection — that precedent shipped.

**(b) The proxy problem — the check verifies a binary the command never names.** argv0 for
the failing rule is `scripts/regen-bun-lock.sh` (`press/press-rules.toml:12-15`), not `bun`;
`bun` is reached by `exec bun install` inside the script (`regen-bun-lock.sh:13`). An engine
`tool = "bun"` check resolves a *second, unrelated* binary and asserts the script will pick
it — true here only because the script inherits the same child PATH, false the instant the
script does `exec "$HOME/.bun/bin/bun"`, the very pin the proposal wants to enable
(`regen-bun-lock.sh:8-10` says so itself).

**(c) Version probing is unsafe by construction, so "record only" dies too.** The only
generic probe runs argv0 with a version flag. `scripts/regen-bun-lock.sh --version` ignores
the flag and runs `rm -f bun.lock; exec bun install` (`regen-bun-lock.sh:12-13`) — destructive
mutation at *plan/record* time. This also kills extending `press check-tools`, whose contract
is "Reads config, writes nothing, **executes nothing**" (`check_tools.py:1-9`).

**(d) Parsing is unbounded; a hard pin creates false failures.** `bun --version` prints
`1.3.5`; `uv --version` prints `uv 0.9.2 (hash date)`; `powershell -File …` has no version.
The schema therefore needs `version_command` + regex per tool — config-supplied execution and
pattern matching in the engine, the unbounded schema the steelman predicts. And
`version = "1.3.5"` fails closed against a 1.3.6 writing a byte-identical lockfile; fixing
that means comparators, i.e. semver inside a zero-runtime-dependency package (`AGENTS.md`).

**(e) P07 multiplies declarations.** Every constraint restates per platform
(`press-rules.toml:11-20`); `win32` needs a PowerShell idiom unrelated to bun.

**(f) An engine field would be the FOURTH bun-version declaration and contradict the other
three.** `scripts/install-bun.sh:14` pins `BUN_VERSION=1.3.5`; `mise.toml:22` says
`bun = "latest"`; `.flox/env/manifest.toml:20` is unpinned; `justfile:121` prepends
`$HOME/.bun/bin`, so `just setup` silently gets the pinned bun while a bare press does not.
**That divergence is the actual root cause of entry #11**, and `version =` in
`press-rules.toml` would disagree with `mise.toml` on day one.

## 3. Alternatives, judged
| Option | Verdict |
|---|---|
| Engine `tool`/`version`/`version_command`, fail-closed | Reject — (b),(c),(d),(e),(f) |
| Record resolved path in receipt | Already shipped (`cli.py:587-591`) |
| Record best-effort `--version` | Reject — (c): destructive probe; breaks no-execute contract |
| `env = {NAME = "value"}` values map | Reject — reverses P04 D1; names passthrough already exists |
| Absolute argv0 in `press-rules.toml` | Supported but uncommittable: no shell, so `~` never expands; a literal `/Users/<name>/…` cannot ship in a template |
| **Fix in `scripts/regen-bun-lock.sh`** | **Accept** |

**Recommended fix (config-side, ~4 lines, no engine change).** `HOME` is in
`COMMAND_ENV_BASE` (`regen.py:69-73`), so `$HOME` expands *inside* the script — the only
committable place a pin can live. Assert the version rather than pinning the path (hardcoding
`~/.bun/bin/bun` fights mise/flox provisioning; a version assert accepts any provisioner
yielding the right bun):
```sh
BUN_VERSION="${BUN_VERSION:-1.3.5}"          # single source: scripts/install-bun.sh:14
have="$(bun --version 2>/dev/null || true)"
[ "$have" = "$BUN_VERSION" ] || { echo "regen-bun-lock: bun $BUN_VERSION required, found ${have:-none}" >&2; exit 127; }
```
The engine then fails the press for free: a nonzero exit is an unconditional failure
(`regen.py:312-317`) and the abort withholds the receipt — fail-closed behavior identical to
the proposal, no new schema, version pinned in one place. The same pattern is the remedy for
the `uv lock` rule (`press-rules.toml:6-8`), identical exposure — which is precisely why this
is a config pattern, not an engine feature. Separately (blueprint hygiene, not E7): reconcile
`mise.toml:22` and `.flox` with the 1.3.5 pin.

## 4. The one test that must exist
With a stub `bun` first on PATH printing a wrong version (e.g. `1.4.0`), running
`scripts/regen-bun-lock.sh` in a fixture target **exits nonzero AND leaves `bun.lock`
byte-identical**. The intact-lockfile half is the whole test: the ordering bug a hasty fix
introduces is placing the version gate *after* `rm -f bun.lock`, destroying the artifact
before refusing — the ordering the script already documents for missing bun
(`regen-bun-lock.sh:8-11`). Cheap second assertion: the press-level case exits nonzero with
no receipt (pattern at `tests/rebrand/test_cli.py:274`).

## 5. Footnote, out of scope
`execute_regenerations` calls `command_env(rule.env)` with no `base_env` (`regen.py:310`),
reading live `os.environ`, while planning used the injected `ambient` (`regen.py:209`).
