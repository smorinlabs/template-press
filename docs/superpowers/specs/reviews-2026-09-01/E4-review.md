# E4 (entry #10) — adversarial review: reset `[project] version` during a press

**Verdict: REJECT** — no new `[[set]]` rule kind, no `[[replace]]` expression.
**Confidence: high** on the mechanism attacks (both decided by existing code);
**medium** on severity (the gap is real but cosmetic). (The proposal cites
`2.4.2`; this repo is `4.0.0`, `pyproject.toml:23` — the argument is unaffected.)

## 1. Steelman: leaving version alone is defensible

- A press is an **identity** operation: every `Identity` field
  (`identity.py:116-127`) is a *name* the fork must own; a version is release
  state.
- Version here is **release-please's owned state**: `release-please-config.json`
  writes `$.project.version` into `pyproject.toml` as an `extra-files` mirror of
  `.release-please-manifest.json` (`{".": "4.0.0"}`), the real source of truth. A
  press editing only `pyproject.toml` is *worse than nothing*: the fork's first
  release-please run reads the untouched manifest and resurrects `4.0.0`.
- `CHANGELOG.md` is already stubbed (`press/press-rules.toml` `[[reset]]`), so
  release-please re-versions the fork from its own history unprompted; a reset is
  a cosmetic head-start, and a vendored fork may want inheritance anyway.

## 2. Attacking the proposal

**2a — the `[[replace]]` expression is statically impossible.** `_parse_replace`
rejects a placeholder-free pattern outright: "references no identity field … a
placeholder-free rule renders FROM == TO (a committed no-op)"
(`rules.py:301-307`), and every brace token must be in the closed
`ALLOWED_PLACEHOLDERS` set (`rules.py:33-37`, enforced `rules.py:316-320`). So
`pattern = 'version = "2.4.2"'` fails config load; a pattern that *does* carry a
legal placeholder still renders the version literal identically under both
identities (`render_replace_pattern`, `rules.py:63-83`) — a self-replacement.
`[[replace]]` cannot change a non-identity value **by construction**.

**2b — `[[set]]` breaks the zero-dependency contract.** AGENTS.md: "the rebrand
engine is pure standard library — the shipped package has zero runtime
dependencies." `tomllib` is **read-only**, so a structured `key` setter needs
`tomlkit` (new runtime dep, violating design 0006), and the `pattern` fallback
is a regex line-edit inside a byte-exact rewriter — re-importing CRLF (nothing
normalizes line endings on the write path), quote style, spacing, and stray
matches in `[tool.ruff] target-version` or a pin.

**2c — one scalar is at least three files.** `pyproject.toml:23`,
`.release-please-manifest.json`, `uv.lock:1277-1279` (root package). `__version__`
is *not* a fourth mirror — it reads installed metadata (`__init__.py:24`) — and
`tests/meta/test_version_consistency.py` already pins the first two, so a
`[[set]]` touching one file leaves a tree failing that meta-test on the fork.

**2d — receipt and verify have no home for it.** `write_receipt` emits one table
per mechanism (`receipt.py:88-121`); a fifth writer needs its own plus a tolerant
reader (cf. `removed_files_from_receipt`, `receipt.py:124-157`). Worse, verify
has **no concept of a version leak**: `verifier.py` is "changed-fields only" over
identity values and rendered `[[replace]]` literals, which design 0008's
independence guardrail makes it derive independently. `[[set]]` would be the only
writer verify cannot certify — an unverified mutation in the artifact whose whole
purpose is "verified, no leak".

**2e — a `version` identity field poisons both matchers.** The paranoid matcher
splits on `_SEP = [_\-. ]+` (`matcher.py:33`) and rejoins with `[-_. ]*`
(`matcher.py:56-58`), so `2.4.2` compiles to `2[-_. ]*4[-_. ]*2`, IGNORECASE,
non-alphanumeric boundaries — flagging `242`, `2-4-2`, and every dependency
pinned at `2.4.2`; "no leak" becomes meaningless. `token_pattern`
(`identity.py:186-210`) is worse: it would **rewrite** every bounded `2.4.2`
repo-wide, corrupting third-party pins in `uv.lock`. Plus rot:
`press/press-source.toml` holds the committed FROM identity (`config.py:98-108`)
and release-please never bumps it — so either `discovery.mismatches`
(`discovery.py:101-134`) learns `version` and every release breaks the press
preflight, or the FROM version silently rots.

## 3. Alternatives

| Option | Cost | Call |
|---|---|---|
| `[[set]]` rule | new writer, new receipt table, unverifiable, parser or regex | reject (2b/2d) |
| `version` in `Identity`/answers | matcher poisoning, source-config rot | reject (2e) |
| `[[regenerate]]` + `[[reset]]`, today's schema | manual declaration ordering | viable, zero engine change |
| blueprint `VERSION` file + `[[reset]]` | a new mirror release-please must learn | worse than above |

**Zero-code remedy, already expressible** in the blueprint's `press-rules.toml`:
`[[reset]] file = ".release-please-manifest.json"` with a `0.1.0` stub (resets run
at position zero, before renames and regenerations — `reset.py:361-370`), plus
`[[regenerate]] file = "pyproject.toml"`, `command = ["uv","version","0.1.0"]`
declared **before** the `uv.lock` entry (plans build and execute in declaration
order — `regen.py:211`, `regen.py:278`). `pyproject.toml` is **not** in
`REGENERATE_EXEMPTIBLE` (`pathing.py:20`), so it stays in the ordinary no-leak
scan (`engine.py:396`, `pathing.py:109`) — no coverage lost. Residual risk:
`_validate_writer_overlaps` (`rules.py:641-724`) does not enforce that ordering,
so a reordered file silently pins the lock to the old version.

## 4. Verdict

**REJECT** the new rule kind and the `[[replace]]` expression. If the gap is worth
closing, close it **blueprint-side** with the two declarations above: no engine
change, every mutation stays one of the five verified mechanisms.

**The one test that must exist** (only if the blueprint-side remedy is adopted):
an R3 self-press assertion that the *pressed* tree's version agrees across all
three mirrors — `pyproject.toml [project] version`,
`.release-please-manifest.json["."]`, and `uv.lock`'s root package — i.e.
`tests/meta/test_version_consistency.py` run against the pressed output, not the
source repo. Without it the reset half-lands and release-please undoes it.
