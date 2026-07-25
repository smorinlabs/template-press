# Scaffolder Identity-Variant Handling — Research for the C/D/E Gap Fixes

> Research feeding the design decisions for the three remaining
> py-launch-blueprint conformance gaps
> ([0004 §5](0004-py-launch-blueprint-conformance-gaps.md): G5 doc-filename
> tokens, G3 app_name boundary variants, G4 humanized display name). Surveys
> how established scaffolding/rename tools handle (1) human display name vs
> machine slug, (2) multi-variant token substitution and scan/rewrite
> symmetry, (3) filename/path templating — then folds in code-recon findings
> against the v3.2.x engine that reframe two of the three gaps.
>
> **Non-normative** (per `docs/research/` convention). The decisions this
> informs are captured via the C/D/E codesign selection and the design/ADR
> entries that follow it.

---

# 1. Question & conclusion

**Question.** For the three scanner/rewriter-asymmetry gaps (G3/G4/G5),
should `press` close each asymmetry (make the rewriter variant-aware) or
accept the residual — and what do established tools (cookiecutter, copier,
Yeoman, cargo-generate, dotnet templating, repren, vim-abolish, VS Code,
fastmod, gitleaks) do for the equivalent problems?

**Conclusion (headline findings).**

1. **Per-field, opt-in, closed-form variant handling is the overwhelming
   industry norm** — no surveyed tool ships an open-ended
   "rewrite-all-known-variants" sweep. Even repren, the most aggressive
   case-preserving renamer, caps itself at 4 fixed casing forms behind
   explicit flags. A unified fuzzy sweep is the wrong shape.
2. **The display name splits by ecosystem, and the input-of-record norm
   (cookiecutter, copier) treats the human name as first-class**, with
   machine slugs derived-but-overridable. No surveyed tool derives a
   *display* name from a slug and trusts it — real product names
   ("NumPy", "PyTorch") are not reliable titleizations of their slugs.
3. **Path renaming should reuse the content matcher, not grow a second
   ruleset** — every surveyed tool drives paths and contents from the same
   engine/pattern set (repren: verified in source — identical pattern list,
   one boolean gate). Where an override exists (dotnet `rename` dict), it is
   an explicit, literal, secondary escape hatch.
4. **Code recon reframes gap C: it is gap D in path components.** The
   engine's rename pass (`engine.py:_renamed_rel`/`_apply_renames`) already
   runs `replace_token` over every path component; the two `…-plbp.md`
   filenames survive only because of the same app_name boundary guard
   (`(?<![A-Za-z0-9_-])plbp(?![A-Za-z0-9-])`) that causes D. Verified
   empirically: `plbp_config.toml` renames; `0001-app-short-name-plbp.md`
   does not. Whatever closes D's asymmetry closes C's, because paths ride
   the same matcher.
5. **An exact-match `[[replace]]` rule with identity interpolation is
   viable and self-maintaining.** `press rebrand` rewrites
   `press-source.toml` to the destination identity after apply
   (`cli.py:333`), so a committed rule written as ONE template string
   rendered twice — source identity ⇒ FROM literal, destination identity ⇒
   TO literal (e.g. `pattern = "_{app_name}_owned"`) — stays correct across
   repeated presses, where a literal from/to pair goes stale after one.
   Precedent: dotnet templating's `rename` dictionary (literal key,
   templated value).

---

# 2. Method

- Three parallel research passes (2026-07-23), primary-sources-first:
  official docs cross-checked against actual template/source code and issue
  trackers; every load-bearing claim ≥2 independent sources or verified in
  source. Full per-pass reports (with per-claim confidence) were produced in
  session; their sources are consolidated in [§7](#7-sources).
- Code recon against the v3.2.x engine in this repo (`identity.py`,
  `matcher.py`, `rules.py`, `verify_config.py`, `engine.py`, `config.py`,
  `discovery.py`), with the C-is-D-in-paths claim and the scanner's
  PascalCase coverage verified by executing the real matchers.

---

# 3. Survey findings by sub-question

## 3.1 Display name vs machine slug (→ G4)

| Tool | Input of record | Display form | Derived forms |
|---|---|---|---|
| cookiecutter (pypackage, django) | `project_name` (human, spaced) | first-class — it IS the input | `project_slug`/`package_name`/`import_name` via Jinja defaults, shown as editable prompts (derive-but-let-override) |
| copier (copier-uv) | `project_name` (human) | first-class | repo/distribution/import/CLI names via `slugify` filters, all overridable |
| Yeoman | `appname` (dirname) | absent — `humanize` used transiently, never retained | one canonical camelized machine form |
| cargo-generate | `project-name` (machine) | none retained; `title_case` exists only as a per-use Liquid filter | `crate_name` (snake) — exactly one built-in derivation |
| dotnet templating | `sourceName` (machine token) | absent for project identity (template.json `name` labels the *template*, a different axis) | named value forms: `titleCase`, `kebabCase`, casings — each explicitly declared |

**Takeaways for `press`:** a humanized form is either the *input of record*
or *absent* — nobody round-trips slug→display and trusts it. The derivation
`repo_name → title` happens to reproduce "Py Launch Blueprint" but fails the
general case (acronyms, stylized casing). Cookiecutter's own flagship
template has an open issue (#487) showing even the name/slug *pair* confuses
users without docs — a caution for how `press` documents a 7th field.

## 3.2 Variant substitution & scan/rewrite symmetry (→ G3, cross-cutting)

- **Named pattern exists:** "case-preserving substitution" (repren,
  vim-abolish `:Subvert`, VS Code/JetBrains *Preserve Case*). Always a
  **small closed set** (repren: exactly `lowerCamel`, `UpperCamel`,
  `lower_underscore`, `UPPER_UNDERSCORE`), always opt-in for batch tools
  (`--preserve-case`; word boundaries a *further* opt-in `--word-breaks`).
- **Scaffolders chose the safer shape:** named per-field derived symbols
  (dotnet value forms; cargo-generate's single `crate_name` derivation +
  per-use filters), never a variant-sweep engine.
- **Documented corruption stories** (primary sources): dotnet #1168/#6853 —
  content and path transforms silently diverged on the same token (dash in
  filenames, underscore in contents → broken `.sln`), *structurally
  identical to G3+G5*, caught only when builds broke because there is no
  verify step. VS Code #81779 — a live casing-corruption bug in shipping
  preserve-case logic (separator branch ordering). The lesson: variant
  rewrite logic is fiddly; closed sets + tests, never heuristics.
- **Scan-wider-than-rewrite residuals:** no rename tool has a first-class
  reconciliation; the transferable precedent is gitleaks' **allowlist**
  (permanent, reviewed, committed exceptions) — which `press` already has as
  `[[verify.ignore]]` + `verify_ignore`. (gitleaks' *baseline* half doesn't
  transfer — verify is one-shot, not scan-over-time.)
- **fastmod** demonstrates the orthogonal safety strategy: no boundaries at
  all, per-match interactive confirm. `press` (batch, unattended) cannot
  lean on that; boundaries/exactness must carry the safety.

## 3.3 Filename/path templating & renaming (→ G5)

- **One matcher for paths and contents is universal.** repren (verified in
  source): the identical pattern list feeds `multi_replace` for both; a
  boolean (`--renames`/`--full`) gates *whether* paths participate — not
  *how* they match. cookiecutter/copier/cargo-generate: same engine renders
  paths and contents (with path-only extras layered on: cargo-generate
  sanitizes filesystem-invalid characters post-substitution). dotnet: same
  `sourceName` pass drives both, with the `rename` dict as a literal
  escape hatch.
- **Failure modes to guard when extending path renaming** (all
  primary-sourced): empty-rendered path segment collapses into the parent
  (cookiecutter #1518); collision policy varies — fail-loud (cookiecutter)
  vs silent auto-suffix (repren) — nobody silently overwrites; a
  case-only rename is invisible on case-insensitive filesystems (macOS,
  Windows) without a two-step move; repren leaves empty source dirs behind
  (source-verified); a rename + heavy content rewrite in one commit can
  drop below git's 50% similarity threshold and render as delete+add
  (diff-readability, not correctness).
- `press`'s existing rename pass already: executes deepest-first to a
  fixpoint (parents stay valid), skips-with-report on destination collision,
  and never renames the root control dir. Its identity validators make the
  empty-segment collapse unreachable today; a cheap guard is still
  indicated if interpolated rules can touch paths.

---

# 4. Code-recon findings (this repo, v3.2.x)

1. **C is D in path components** (§1.4). There is no missing "filename
   rename capability"; there is one boundary guard producing both gaps.
2. **The scanner already covers glued PascalCase.** `identity_pattern`
   joins value tokens with `[-_. ]*` under IGNORECASE, so
   `PyLaunchBlueprint` and "Py Launch Blueprint" are both flagged today (as
   `package_name`/`repo_name` variants) — verified by execution. A
   display-name fix is therefore **rewrite-side only** for verify-parity;
   scanning `display_name` as its own field matters only when the display
   name's words diverge from the slug's words.
3. **Committed rules survive presses only if interpolated** (§1.5,
   `cli.py:333`).
4. **`Identity` is a frozen 6-field dataclass** with per-field validators;
   an optional 7th field is additive (`REQUIRED_FIELDS` unchanged, absent →
   feature off), rippling to `config.py` (load/render), `synthesize.py`,
   `verify_config.KNOWN_FIELDS`, and answers loading — but not to
   discovery (undiscoverable fields go unchallenged by design,
   `discovery.mismatches`).

---

# 5. Direction set during research review (2026-07-23)

Reviewing these findings, the maintainer set three points of direction that
override/refine the raw research recommendations:

- **G4 = explicit, optional `display_name`** — NOT derived from
  `repo_name` (derivation is "too far of a stretch"; §3.1 supports this).
  Optional: absent field ⇒ no display-name pass, existing
  `press-source.toml` files stay valid.
- **Display matching must cover glued variants** ("PyLaunchBlueprint") via
  a **closed exact form set** (spaced / Pascal / camel), each matched
  exactly and replaced with the corresponding form of the new name — the
  repren shape, never an elastic regex.
- **A generic exact-match `[[replace]]` rule** (press-rules.toml) should
  exist alongside the field — with identity interpolation (one pattern
  rendered twice, §1.5) and *no* fuzzy/regex matching.

---

# 6. Design space handed to the codesign

With the above settled, the remaining choices (one section each on the
codesign page):

- **D/G3 mechanism:** opt-in per-field substring rewrite mode (automatic;
  the old `init/` design; corruption-guard machinery required) **vs**
  explicit interpolated `[[replace]]` rules (~3 rules cover all 16
  findings; exact-match safe; requires target authoring) **vs** both.
- **C/G5:** ride whichever D mechanism is chosen (paths inherit the
  matcher) **vs** `[[replace]]` rules with a `paths` argument **vs**
  accept + ignore (2 files).
- **E/G4 sub-choices:** variant form set (spaced only / +Pascal / +camel);
  scan `display_name` as its own verify field when present; half-specified
  behavior (source has it, answers doesn't → fail loud vs skip).
- **`[[replace]]` argument set:** `files` globs, `paths` toggle, expected
  `count` drift check, mandatory `reason`.

The G1/G2/§6 exclude-contract work (P1) is a separate stream, already
designed — none of the above re-solves it.

---

# 7. Sources

Consolidated from the three research passes (all fetched 2026-07-23):

- cookiecutter: `cookiecutter.json` of audreyfeldroy/cookiecutter-pypackage
  and cookiecutter/cookiecutter-django; docs (private variables, template
  extensions, copy_without_render, tutorials); issues #487, #1518, #1596.
- copier: docs (configuring, creating); pawamoy/copier-uv `copier.yml`;
  issue #1595.
- Yeoman: yeoman.io authoring docs; generator-angular source (legacy —
  lower currency, flagged).
- cargo-generate: book (builtin/template-defined placeholders, pitfalls,
  include-exclude); CHANGELOG (v0.16.0 case filters, v0.17.0 rename bug).
- dotnet templating: Reference-for-template.json, Value-Forms wiki,
  Naming-and-default-value-forms; issues #1168, #6853, #2210.
- repren: README + `repren/repren.py` source (variant set, `--word-breaks`,
  `do_renames`/`do_contents` gates, collision auto-suffix, no empty-dir
  cleanup); issue #13.
- vim-abolish `doc/abolish.txt`; VS Code issues #9798/#81779 + PR #79111;
  facebookincubator/fastmod README; gitleaks allowlist/baseline model.
- git: git-diff rename detection; `core.ignoreCase` two-step rename
  pattern (4 independent corroborating write-ups; manual page not
  verbatim-fetched — flagged).
- This repo: `src/template_press/rebrand/{identity,matcher,rules,
  verify_config,engine,config,discovery}.py`, `cli.py:333`; claims in §4
  verified by executing the real matchers.
