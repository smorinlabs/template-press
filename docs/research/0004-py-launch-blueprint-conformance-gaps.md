# py-launch-blueprint Conformance Gaps — `press verify` Dogfood Findings

> Register of the capability gaps that surface when the **released `press`
> engine (v3.2.0)** is run against **py-launch-blueprint** (the primary
> consumer template). Produced by the dogfood-v3 effort (issue
> [smorinlabs/py-launch-blueprint#423](https://github.com/smorinlabs/py-launch-blueprint/issues/423),
> the init/post-init engine extraction). Each gap is stated as *symptom →
> evidence → root cause (with code refs) → what the old `init/` engine did →
> proposed `press` change → acceptance test*.
>
> **Non-normative** (per `docs/research/` convention): this informs the
> parity work; the actual fixes should land as design/ADR entries and/or
> tracked issues. Onward links are collected in [§8](#8-onward).

---

# Table of contents

1. [Question & conclusion](#1-question--conclusion)
2. [Method (reproducible)](#2-method-reproducible)
3. [Executive summary](#3-executive-summary)
4. [The unifying root cause](#4-the-unifying-root-cause-scannerrewriter-asymmetry)
5. [Gap register](#5-gap-register)
6. [Cross-cutting architectural note](#6-cross-cutting-architectural-note)
7. [Recommended sequencing](#7-recommended-sequencing)
8. [Onward](#8-onward)
9. [Appendix](#9-appendix)

---

# 1. Question & conclusion

**Question.** Does the released `press` engine (v3.2.0) `press rebrand` /
`press verify` py-launch-blueprint *cleanly* — i.e. with no source identity
surviving a hermetic self-press — so that py-launch-blueprint can drop its
embedded `init/` engine and depend on `press` as its external rebrand +
drift-check tool?

**Conclusion. Not yet.** `press verify` reports **784 surviving findings
across 39 files** (exit 1). The findings are real, but they are **not
"py-launch-blueprint is broken"** — they are **five concrete capability gaps
where the released `press` engine is less capable at rebranding
py-launch-blueprint than the old `init/` engine was**, plus one architectural
interaction that guarantees false-looking leaks for any excluded file.

**Decision this drives (dogfood-v3):** *pause* the py-launch-blueprint conform
(do **not** delete `init/` on a verify-green-via-ignores signal — that would
ship a rebrand regression) and *enhance `press` to `init/` parity first*. This
register is the parity spec.

---

# 2. Method (reproducible)

```bash
# In py-launch-blueprint @ 1649334 (v2.4.2), add the source identity the press needs:
cat > press/press-source.toml <<'EOF'
[identity]
package_name = "py_launch_blueprint"
repo_name    = "py-launch-blueprint"
app_name     = "plbp"
author       = "Steve Morin"
email        = "steve.morin@gmail.com"
owner        = "smorinlabs"
EOF

# From template-press @ v3.2.0 (origin/main e9b188c), run the hermetic leak check:
uv run press verify --target /path/to/py-launch-blueprint --json > verify.json
echo "exit=$?"   # => 1 (leak)
```

- **Target:** py-launch-blueprint `main` @ `1649334`, v2.4.2.
- **Engine:** template-press `v3.2.0` (`origin/main` @ `e9b188c`; the rebrand
  engine modules — `rules.py`, `matcher.py`, `identity.py`, `verify_config.py`,
  `config.py` — are byte-identical from `d7e5c9d` through `e9b188c`, so the code
  refs below hold for the whole v3.2.0 line).
- The identity was cross-checked against py-launch-blueprint's `pyproject.toml`
  (`name`, `authors`, `[project.scripts] plbp`, urls) and its `init/manifest.toml`
  (`app_name current=["plbp"]`). The tool accepted the config (no exit 2).

---

# 3. Executive summary

| Gap | Findings | Files | Root cause (verified) | `init/` did | Class |
|-----|---------:|------:|-----------------------|-------------|-------|
| **G1 CHANGELOG excluded-not-reset** | 678 | 1 | `CHANGELOG.md` in `exclude_files` → not rewritten, and not reset/scan-excluded → every token survives | `[[reset]]` → blank stub | **regression** |
| **G2 bun.lock excluded-not-regenerated** | 2 | 1 | `bun.lock` in `exclude_files` but NOT in `regenerate` → stale tokens survive | regenerated | **regression** |
| **G3 app_name boundary variants** | 16 | 8 | rewriter protects `_plbp` / `plbp-`; scanner matches them → asymmetry | text-mode substring replace | **regression** |
| **G4 humanized display name** | 74 | 24 | scanner matches spaced/case variant "Py Launch Blueprint"; rewriter can't; no display-name field | never handled | **design decision** (pre-existing) |
| **G5 doc filename tokens** | 2 (+4 refs) | 2 | `…-plbp.md` filenames renamed by neither engine's default rules | (content only) | **minor** |
| *(init/ self-refs)* | 8 | 7 | leaks inside `init/` itself | n/a | vanish on `init/` deletion — not a press gap |

Total accounted: 678 + 2 + 16 + 74 + 2 + (4 F-refs folded into G5) + 8 = **784**.

**86% of all findings are G1 (CHANGELOG).** G1 + G2 share one class
(*excluded-but-not-neutralized*); G3 + G4 share another (*scanner/rewriter
asymmetry*). Fix those two classes and the surface collapses to a handful.

---

# 4. The unifying root cause: scanner/rewriter asymmetry

`press verify` deliberately runs **two different matchers**, and the
difference between them is the source of most findings. This is stated
outright in the matcher's own module docstring
(`src/template_press/rebrand/matcher.py:1-28`):

- **The rewriter** (`identity.token_pattern` / `replace_token`,
  `src/template_press/rebrand/identity.py:144-184`) is **conservative** — a
  full alphanumeric/separator boundary on both sides, matching only the exact
  literal token, "so it never corrupts unrelated text." For `app_name = plbp`
  it additionally protects a leading `_`/`-` and a trailing `-`
  (`identity.py:163-167`).
- **The verify scanner** (`matcher.identity_pattern` / `find_occurrences`,
  `matcher.py:37-90`) is **paranoid** — it joins the value's tokens with
  `[-_. ]*` under `re.IGNORECASE` (`matcher.py:34,59-61`). `_SEP` **includes a
  space** (`matcher.py:34`), so `py_launch_blueprint` matches `py-launch-blueprint`,
  `Py Launch Blueprint`, `pyLaunchBlueprint`, `PyLaunchBlueprint`, … and the
  lower→UPPER transition counts as a boundary so `demoWidgetConfig` is caught.

The asymmetry is **by design** — a scanner should over-flag rather than miss a
leak; a rewriter must never corrupt text. But the consequence is:

> **Any separator/case/space *variant* of an identity value that the
> conservative rewriter intentionally leaves untouched is flagged by the
> paranoid scanner as a leak.**

That is exactly G3 (`_plbp_owned`, `plbp-web`) and G4 ("Py Launch Blueprint").
Neither is a bug in isolation; the open question each raises is **"close the
asymmetry for this field (make the rewriter handle the variant), or accept the
residual (a first-class ignore)?"**

---

# 5. Gap register

## G1 — `CHANGELOG.md`: excluded from rewrite, never neutralized (678 findings) — **P1**

**Symptom.** Every identity token in `CHANGELOG.md` survives the hermetic
press: `smorinlabs` (owner), `py-launch-blueprint` (repo), and the hyphen form
matched as a `package_name` variant — all inside
`github.com/smorinlabs/py-launch-blueprint/…` release links.

**Evidence.**
```
CHANGELOG.md
  L3 owner='smorinlabs'            : ## [2.4.2](https://github.com/smorinlabs/py-launch-blueprint/compare/…)
  L3 repo_name='py-launch-blueprint': ## [2.4.2](https://github.com/smorinlabs/py-launch-blueprint/compare/…)
  L3 package_name (hyphen variant) : (same span)
  … ×678
```
The tokens are **exact literals** the rewriter *would* rewrite — so their
survival proves the file was **not rewritten at all**.

**Root cause.** `CHANGELOG.md` is in `DEFAULT_RULES.exclude_files`
(`src/template_press/rebrand/rules.py:48-50`) → the rewriter skips it. But it
is **not** in `regenerate` (`rules.py:51`, only `uv.lock`) and **not** in
`verify_ignore`, so the verify scanner still reads it
(`verifier.scan` via `scan_paths`). Excluded-from-rewrite + scanned-anyway =
guaranteed leak.

**What `init/` did.** A `[[reset]]` rule blanked it on rebrand
(`py-launch-blueprint init/manifest.toml:579-581`:
`path = "CHANGELOG.md"`, `stub = "# Changelog\n"`) — a fork's changelog should
start fresh, not inherit the blueprint's release history.

**Proposed `press` change (recommended).** Add a **reset** rule kind — a
`[[reset]]` in `press-rules.toml` (`path` + `stub`) applied by `engine.apply`,
where reset targets are blanked *before* the verify scan reads them (so a reset
file contributes zero findings). This restores `init/` parity and is the
semantically-correct rebrand behavior.
*Alternative (inferior):* add `CHANGELOG.md` to `verify_ignore` — makes verify
green but leaves a real rebrand keeping the blueprint's changelog history.

**Acceptance.** A target declaring `CHANGELOG.md` as a reset → `press rebrand`
blanks it to the stub; `press verify` reports **0** `CHANGELOG.md` findings.

---

## G2 — `bun.lock`: excluded from rewrite, not regenerated (2 findings) — **P1**

**Symptom.** `py-launch-blueprint` survives in `bun.lock`
(`"name": "py-launch-blueprint-tooling"`), flagged as `repo_name` (exact) and
`package_name` (variant).

**Root cause.** Same class as G1: `bun.lock` is in `exclude_files`
(`rules.py:48-50`) but, unlike `uv.lock`, is **not** in `regenerate`
(`rules.py:51`). `uv.lock` is regenerated fresh after a rebrand (so it carries
no stale identity); `bun.lock` is left as-is and scanned → leak.

**What `init/` did.** Regenerated `bun.lock` (via `bun install`) as part of the
rebrand.

**Proposed `press` change.** Add `bun.lock` to the `regenerate` set with its
regen command (`bun install`), or make `regenerate` fully configurable in
`press-rules.toml [rules]` so a target can declare the lockfile + command.

**Acceptance.** After `press rebrand`, `bun.lock` is regenerated with the new
identity; `press verify` reports **0** `bun.lock` findings.

---

## G3 — `app_name` boundary variants `_plbp_owned` / `plbp-web` (16 findings) — **P2**

**Symptom.** The app identity survives where it is glued to `_` on the left or
`-` on the right:
```
tests/core/test_logging.py  L23  app_name='plbp'  …getattr(h, "_plbp_owned", False)…
tests/conftest.py           L28  app_name='plbp'  …getattr(handler, "_plbp_owned", …
Dockerfile                  L3-4 app_name='plbp'  …plbp-web…
Justfile                    L317 app_name='plbp'  …tag="plbp-web:dev"…
docs/adr/*, docs/design/*   app_name='plbp'  (prose refs)
```

**Root cause.** The **rewriter** protects these on purpose:
`token_pattern("app_name", "plbp")` =
`(?<![A-Za-z0-9_-])plbp(?![A-Za-z0-9-])` (`identity.py:163-164`) — a leading
`_`/`-` fails the lookbehind, a trailing `-` fails the lookahead, so
`_plbp_owned` and `plbp-web` are left untouched (a private-var / compound
guard). The **scanner** has no such guard (`matcher.py:59-61`) and matches
them → asymmetry (§4).

**What `init/` did.** `app_name` **text mode** — a substring replace of `plbp`
across 49 listed files (319 occurrences), explicitly justified because "`plbp`
was invented to be substring-disjoint from real words"
(`py-launch-blueprint init/manifest.toml` app_name text block).

**Proposed `press` change.** A **per-field opt-in "substring/text" rewrite
mode** — the rewrite-side mirror of the verify `substring_fields` knob that
already exists (`verify_config.py`). A target whose `app_name` is provably
word-disjoint (like `plbp`) opts in; the default stays conservative.
*Alternative:* leave the rewriter conservative and `[[verify.ignore]]` these
specific occurrences — but that leaves `_plbp_owned`/`plbp-web` un-rebranded in
a real fork.

**Acceptance.** With app_name substring mode enabled, `_plbp_owned` →
`_<app>_owned`, `plbp-web` → `<app>-web`; `press verify` reports **0** app_name
findings of this shape.

**Risk.** Aggressive substring replacement is why the rewriter is conservative
— this MUST be opt-in and gated on a word-disjoint token, never a default.

---

## G4 — humanized display name "Py Launch Blueprint" (74 findings) — **design decision** (pre-existing)

**Symptom.** The spaced/title-case product name survives across 24 doc/config
files (README ×10, `docs/source/index.md` ×10, `.github/CONTRIBUTING.md` ×6,
`CLAUDE.md` ×2, most `docs/source/**`), flagged as **both** `package_name` and
`repo_name` (both underscore and hyphen forms normalize to "py launch
blueprint").

**Evidence.**
```
README.md  L11  package_name & repo_name  : "# Py Launch Blueprint: A Production-Ready 🐍 …"
docs/source/index.md  L9  package_name & repo_name : "# Py Launch Blueprint"
```

**Root cause.** The scanner's space-inclusive, case-insensitive matcher
(`matcher.py:34,59-61`) treats "Py Launch Blueprint" as a variant of
`py_launch_blueprint` / `py-launch-blueprint`. The **rewriter cannot** rewrite
it (its literal pattern requires the exact token), and **there is no
display-name field** in the identity model — `Identity` has exactly six
machine fields (`identity.py:99-108`, `REQUIRED_FIELDS` `identity.py:89-96`).

**What `init/` did.** *Nothing* — `init/manifest.toml` has **no** rule for the
humanized form. Both engines leave "Py Launch Blueprint" in place; `press
verify`'s normalized scan is simply the first tool to *surface* it. So this is
**pre-existing**, not a regression `press` introduced.

**Proposed `press` change — this is a genuine design choice:**
- **Option A (rewrite it):** add a 7th identity field — `display_name` /
  `title` (e.g. "Py Launch Blueprint") — with a humanized matcher + rewriter, so
  forks get *their* product name in prose. Highest value for template quality;
  most work; expands the identity contract + `press-source.toml` schema.
- **Option B (accept the residual):** formally classify the humanized/spaced
  variant as un-rewritable-by-design and give it a first-class, low-ceremony
  ignore (it's a human product name a forker renames by hand, not machine
  identity). Cheapest; documents the limitation honestly.

**Acceptance.** Depends on the choice: Option A → "Py Launch Blueprint" →
"<Display Name>" and 0 findings; Option B → these 74 are ignorable in one
concise rule with a documented reason.

---

## G5 — doc filename tokens `…-plbp.md` (2 findings + 4 content refs) — **P3**

**Symptom.** Two doc *filenames* carry the app token and are flagged as
`filename` findings, plus content links to them:
```
docs/adr/0001-app-short-name-plbp.md      (filename + a self/related ref)
docs/design/0001-plbp-cli-conventions.md  (filename + refs from ADR 0016, ADR README, design_decisions)
```

**Root cause.** `press` renames the package directory (`src/py_launch_blueprint/`
→ `src/<pkg>/`) but has no rule to rename *arbitrary doc filenames* containing
an identity token; the scanner's path-component pass (`verifier._scan_path_components`)
flags them.

**Proposed `press` change.** A path/filename **rename rule** (glob → identity
token substitution in the path), or fold into G3's app_name handling extended
to path components. *Alternative:* `[[verify.ignore]]` the two files (low value;
2 files).

**Acceptance.** `0001-app-short-name-plbp.md` → `0001-app-short-name-<app>.md`
with content refs updated; 0 filename findings.

---

# 6. Cross-cutting architectural note

**Any file in `exclude_files` that contains identity tokens and is neither
regenerated nor reset will *always* leak in `press verify`.** G1 (CHANGELOG)
and G2 (bun.lock) are both instances. This is a structural interaction between
two rule sets that don't currently reconcile:

- `exclude_files` (`rules.py:48-50`) removes a file from the **rewriter**.
- `verify` still **scans** it (only `verify_ignore` and regenerable lockfiles
  are dropped from the scan inventory in `scan_paths`).

Three ways `press` could make this coherent (design decision for template-press):
1. **Reset/regenerate as the contract:** every `exclude_files` entry MUST also
   be a `regenerate` or `reset` target (so it carries no stale identity), and
   `press verify` fails loudly if an excluded file is neither.
2. **Scan-exclude by default:** an excluded file is dropped from the verify
   scan too, unless explicitly opted back in.
3. **Warn:** keep current behavior but have `press verify` emit a distinct
   diagnostic ("excluded-but-scanned; add a reset/regenerate/ignore") instead
   of ordinary leak findings, so the signal isn't drowned (678 of 784 here).

Whichever is chosen, the current default makes `press verify` **unable to reach
exit 0 on any repo with a `CHANGELOG.md`** without target-side ignores — worth
resolving before more templates adopt `press`.

---

# 7. Recommended sequencing

1. **P1 — collapse 86%+ of the surface:** G1 (reset) + G2 (regenerate bun.lock)
   + the §6 exclude/scan reconciliation. One coherent change to the
   exclude/reset/regenerate contract.
2. **P2 — close the app_name asymmetry:** G3 (opt-in substring rewrite mode,
   gated on a word-disjoint token).
3. **Design decision — G4:** pick Option A (display-name field) or B (accepted
   residual + first-class ignore). This is the one that needs a human call
   before implementation.
4. **P3 — G5:** filename rename rule, or accept 2 ignores.
5. **Then** conform py-launch-blueprint (write `press/press-source.toml` +
   minimal `press-rules.toml`), prove `press verify` exit 0, and only *then*
   remove `init/` and cut CI over to `press verify`.

Only after P1–P2 (and a G4 decision) does "`verify` green" actually mean
"`press rebrand` is at `init/` parity" — the signal the py-launch-blueprint
migration is waiting on.

---

# 8. Onward

- Consumer-side dogfood record + this register's pointer:
  py-launch-blueprint `docs/research/0004-template-press-dogfood-log.md`.
- Governing spec: py-launch-blueprint
  `docs/superpowers/specs/2026-06-13-template-press-bootstrap-dogfood-v3-design.md`;
  engine-extraction plan `docs/design/0004-template-press-plan.md`.
- **TODO (to be filed):** a design/ADR entry for the exclude/reset/regenerate
  contract (§6, G1, G2); an ADR for the G4 display-name decision; issues per gap.

---

# 9. Appendix

## 9.1 `press/press-source.toml` used (accepted by v3.2.0)

```toml
[identity]
package_name = "py_launch_blueprint"
repo_name    = "py-launch-blueprint"
app_name     = "plbp"
author       = "Steve Morin"
email        = "steve.morin@gmail.com"
owner        = "smorinlabs"
```

## 9.2 Full leak inventory (39 files, 784 findings)

| Findings | File | Dominant gap |
|---------:|------|--------------|
| 678 | `CHANGELOG.md` | G1 |
| 10 | `README.md` | G4 |
| 10 | `docs/source/index.md` | G4 |
| 7 | `docs/source/about/design_decisions.md` | G4/G3 |
| 7 | `init/manifest.toml` | init/ self-ref (vanishes) |
| 6 | `.github/CONTRIBUTING.md` | G4 |
| 6 | `docs/source/tutorials/full_project_setup.md` | G4 |
| 4 | `docs/source/about/index.md` | G4 |
| 4 | `docs/source/contributing/index.md` | G4 |
| 2 | `CLAUDE.md`, `Dockerfile`, `bun.lock`, `docs/adr/0001-app-short-name-plbp.md`, `docs/adr/0016-app-short-name-placeholder.md`, `docs/design/0001-plbp-cli-conventions.md`, `docs/source/about/features.md`, `docs/source/about/philosophy.md`, `docs/source/reference/cli_reference.md`, `docs/source/reference/configuration_files.md`, `docs/source/reference/index.md`, `docs/source/reference/project_structure.md`, `docs/source/tasks/index.md`, `docs/source/tasks/using_ci_cd.md`, `docs/source/tools/{cla-assistant,github_actions,index,uv,vs_code}.md`, `docs/source/tutorials/index.md`, `projects/P01-init-rebrand-robustness.md`, `tests/core/test_logging.py` | G4 / G3 |
| 1 | `Justfile`, `docs/adr/{0002,0003,0004}-*.md`, `docs/adr/README.md`, `docs/design/README.md`, `init/tests/integration/run-mode.sh`, `tests/conftest.py` | G3 / init self-ref |

## 9.3 Key code references (template-press v3.2.0)

| Concern | Location |
|---------|----------|
| `exclude_files` = uv.lock, bun.lock, package-lock.json, CHANGELOG.md | `src/template_press/rebrand/rules.py:48-50` |
| `regenerate` = (uv.lock,) | `src/template_press/rebrand/rules.py:51` |
| `Rules` dataclass (no reset kind) | `src/template_press/rebrand/rules.py:19-29` |
| `Identity` — 6 fields, no display name | `src/template_press/rebrand/identity.py:99-108`, `89-96` |
| rewriter app_name boundary (protects `_plbp`/`plbp-`) | `src/template_press/rebrand/identity.py:163-167` |
| scanner variant matcher (space in `_SEP`, IGNORECASE) | `src/template_press/rebrand/matcher.py:34`, `59-61` |
| scanner deliberately-separate-from-rewriter rationale | `src/template_press/rebrand/matcher.py:1-28` |
| verify default fields (app_name, package_name, repo_name, owner) | `src/template_press/rebrand/verify_config.py:31` |
| source-config contract (`press/press-source.toml`, `[identity]`) | `src/template_press/rebrand/config.py:18`, `62-79` |

## 9.4 py-launch-blueprint `init/` references (at `1649334`)

| Concern | Location |
|---------|----------|
| CHANGELOG reset | `init/manifest.toml:579-581` (`[[reset]]`, `stub = "# Changelog\n"`) |
| app_name text mode (319 occurrences, 49 files) | `init/manifest.toml` app_name text `[[replace]]` block |
