# 0007 — `press verify` design & decision record

- **Status:** Accepted (2026-07-18)
- **Type:** Design / decision record
- **Created:** 2026-07-18
- **Applies to:** `template_press.rebrand.{matcher,verifier,ignores,synthesize,
  sandbox,verify_config,verify_cli}` (new modules); `engine.py` / `safety.py`
  hardening shared with `rebrand`; `src/template_press/press_cli.py` (verb
  dispatch)
- **References:** [`docs/superpowers/plans/2026-07-17-press-verify.md`](../superpowers/plans/2026-07-17-press-verify.md)
  (implementation plan — full D1–D8 rationale, task-by-task TDD sequence,
  the G1–G9 defensive-hardening spec); `PROJECTS.md` project **P03**
  (External-target rebrand press); [0006](0006-external-target-model.md)
  (external-target model — the "verify-then-mark" line item this design
  fulfills as a standalone verb)

## 1. Summary

`press verify` is a zero-arg, hermetic, read-only CLI verb that proves a
template presses clean: it presses a faithful sandbox copy of the target
toward a synthetic destination identity and scans the result for surviving
source-identity tokens. It exists alongside — not instead of — the
inline no-leak doctor that already runs as part of a real `press rebrand`.
This document records why the design has the shape it has: the three-posture
model that motivates a *separate*, more paranoid matcher/scanner; the
architectural keystone (`apply()`, never `_press`); the eight load-bearing
decisions (D1–D8) and their rejected alternatives; and — because the user
asked this be captured explicitly — the real defects the adversarial-review
process found *during implementation*, which is what forced the final shape
of the engine's symlink-safety code.

## 2. The three-posture model

Three different pieces of code answer the same underlying question — "is
this text an occurrence of the identity value?" — with three different
answers, because each is optimized for a different failure mode:

| Posture | Module | Used by | Bias |
|---|---|---|---|
| Conservative rewriter | `identity.token_pattern` / `replace_token` (`engine.py`) | `rebrand`'s replace/rename pass | False **negatives** are cheap (an untouched token stays); a false **positive** is catastrophic (rewriter corrupts unrelated text, e.g. mangles `compress` while chasing `press`). Requires a full boundary on *both* sides. |
| Moderate doctor | `doctor.py` (`find_leaks`) | `rebrand`'s inline no-leak gate, inside `_press`, before the receipt is written | Presence/absence only, no line/column; runs against the REAL target as the last check before a real press is allowed to succeed. |
| Paranoid verifier | `matcher.py` + `verifier.py` (new, this design) | the standalone `press verify` verb | False **negatives** are the expensive mistake (a leftover it fails to flag ships); false positives are cheap — they're silenced by explicit, self-policing ignores (D4). |

The verifier is deliberately the *most* paranoid of the three: its only job
is to find leftovers a human might otherwise ship, so it adds occurrence
detection the conservative matcher intentionally omits (e.g. a
camelCase-glued join like `demoWidgetConfig`), and it never gets to silently
skip a finding — every suppression has to be an explicit, named, drift-checked
ignore (D4), not a structural blind spot in the pattern itself.

## 3. The keystone — verify uses `apply()`, never `_press`

```
verify: load source -> preflight -> equal-fields WARN -> synth (equality-preserving)
        -> sandbox copy -> apply(sandbox, source, synth, rules)   # hermetic; returns ApplyReport
        -> scan(sandbox, source, synth)                            # own occurrence-level scan
        -> map findings to SOURCE coords (forward map via ApplyReport.renamed)
        -> apply_ignores  -> exit 0/1/2
```

`verify_cli.py`'s own module docstring calls this "the architectural
KEYSTONE of `press verify`" — and it is the one decision that changed
between plan drafts (see §6). `_press` (`cli.py`, real `rebrand`'s pipeline)
is unusable for verify for three independent reasons:

1. **The doctor's leaks have no line/span.** `doctor.find_leaks` is
   presence/absence only, so a verify built on top of it could never support
   D4's occurrence-pinned ignores — there would be nothing precise enough to
   pin an ignore to. Worse, the doctor's leak check fires *before*
   occurrence-level ignores could even be evaluated, so a legitimate,
   deliberately-kept token would abort the run with no way to suppress it.
2. **`_press` writes a receipt.** `press-receipt.toml` is written via a
   control-path write — a control-path symlink could redirect that write
   *outside* the sandbox, which is exactly the class of escape D8 (§4, §5)
   exists to close. Verify must never write anything outside its own owned,
   torn-down sandbox.
3. **`_press` regenerates lockfiles.** Real `_press` shells out to `uv lock`
   after replace/rename so the lockfile's own embedded name matches. That
   means network access, an external tool invocation, and a file mutation —
   none of which belong in a read-only, repeatable check (D5).

So verify composes its own pipeline directly from `engine.apply()` (replace +
symlink-retarget + rename only — no doctor, no receipt write, no
regeneration) and its own occurrence-level `scan()` (Decision 1), mapping
sandbox findings back to source coordinates via the forward rename map built
from `ApplyReport.renamed` (Decision 4), never touching `_press` at all.

## 4. Decisions (D1–D8): context → options → choice → why

### D1 — Identifier-aware matcher (`matcher.py`)

**Context.** The conservative matcher (`identity.token_pattern`) requires a
full alphanumeric-or-separator boundary on *both* sides — the right call for
a rewriter, which must never corrupt unrelated text, but wrong for a
verifier: it silently misses a camelCase-glued leftover like
`demoWidgetConfig` (no boundary character between `demoWidget` and
`Config`).

**Options considered.**
- Reuse the conservative matcher as-is — rejected: misses camelCase leaks
  entirely, defeating the verifier's purpose.
- Go fully substring / case-insensitive everywhere — rejected: reopens the
  classic false-positive class for short tokens (`press` inside `compress`,
  `express`, `pressure`).
- A case-scoped transition boundary: a full boundary OR a lower→UPPER
  transition counts as a boundary too, with plain substring matching kept
  as an explicit, per-field, opt-in escape hatch (`substring_fields`).

**Choice.** The third option.

**Why — and the corrected regex.** The shipped pattern:

```python
_SEP = re.compile(r"[_\-. ]+")

def identity_pattern(field, value):
    core = "[-_. ]?".join(re.escape(t) for t in _SEP.split(value) if t)
    tail = r"(?:(?![A-Za-z0-9])|(?-i:(?<=[a-z])(?=[A-Z])))"
    return re.compile(rf"(?<![A-Za-z0-9]){core}{tail}", re.IGNORECASE)
```

The first version of this pattern was broken: under a global
`re.IGNORECASE`, a bare `(?=[A-Z])` lookahead is folded by the flag and
matches a *lowercase* letter too — silently reopening the `pressure`
false-positive the whole boundary rule exists to prevent. The fix,
`(?-i:(?<=[a-z])(?=[A-Z]))`, locally turns `IGNORECASE` back **off** for
just that one alternative, so the case-transition test stays case-sensitive
even nested inside the outer case-insensitive pattern. This was
ablation-verified: `test_word_traps_not_matched` (rejects `compress`,
`express`, `pressure`, `Pressure`, `PRESSURE`) and
`test_variants_matched` (accepts `demoWidgetConfig`) both had to pass with
the corrected regex, and a property test runs the pattern over a wordlist
that excludes the identity values themselves.

**Accepted residuals** (paranoid posture, not a bug — documented in
`matcher.py`'s module docstring):
- `myPressConfig` (leading camelCase) is **not** matched — there is no
  lower→UPPER transition immediately after the token itself.
- `PressKit` (a trailing capital directly after the token) **is** matched —
  intentional: a scanner that would rather over-flag than miss a real
  leftover.

### D2 — Identity preflight (`verify_cli._preflight`)

**Context.** Verify needs to know the target's declared source identity
(`press/press-source.toml`) is actually real before pressing toward a
synthetic destination and scanning for it — if the source config is stale or
wrong, verify would confidently scan for the wrong tokens and report a false
clean.

**Options considered.**
- Trust the committed source-config blindly — rejected: a stale config
  passes silently.
- Run discovery only and treat it as ground truth — rejected: per design
  0006, discovery is a *validator*, not authoritative, and several fields
  (`author`, `email`) are never discoverable at all.
- `mismatches(source, discover(target))` for whatever discovery *can*
  confirm, plus a presence check (`find_occurrences` over `scan_paths`) for
  fields discovery cannot confirm; total silence on a field classifies as
  `unverifiable`.

**Choice.** The third option, implemented in `_preflight`.

**Why.** Discovery reliably confirms `package_name`/`repo_name`/`app_name`
via the pyproject name and testing membership across **all**
`[project.scripts]` entries (not just the first — an earlier bug would only
check the first script key) plus git origin/owner; `author`/`email` are
never discoverable. For every field discovery leaves unconfirmed, the
declared value must occur at least once in the target's scan corpus, or the
run is meaningless. If the identity is **wholly** undiscoverable *and*
absent from content, that is classified `unverifiable` and exits **2** —
the code's own comment states the reasoning directly: "refusing to pass on
historical prose." Any preflight problem exits 2, before any sandbox is
built.

### D3 — Three inventories + root-`press` protection (`engine.py`)

**Context.** Rebrand only ever needed one inventory (what to rewrite).
Verify needs three, and conflating them either makes the sandbox unfaithful
or lets a scan exemption hide a real leak: a **copy** inventory (everything
— tracked, non-ignored untracked, force-added, symlinks, gitlinks — so the
sandbox is a true copy), a **rewrite** inventory (what `apply()` actually
changes), and a **scan** inventory (copy minus a small, principled
exemption set).

**Options considered.**
- Exempt `press/` by directory name — rejected: collides when
  `app_name == "press"`; an ordinary `press/notes.md` would trigger renaming
  the whole control directory out from under the tool's own control files.
- Exempt by content-keyed subtree (`CONTROL_MARKERS`, the mechanism
  `stray_press_dirs` still uses to answer "is this `press/` dir *some*
  repo's control dir?") — kept for that question, but not used for the
  exemption itself.
- Exempt an **exact** artifact list, never a location.

**Choice.** `ROOT_CONTROL` — a frozen set of exactly four literal root
paths (`press/press-{source,rules,receipt,answers}.toml`) — is the only
thing `iter_target_files`/`scan_paths` ever skip, membership-tested by
`rel.as_posix()`. Orthogonally, `_is_root_press(rel, i)` protects the
literal root `press` **path component** (index 0) from being renamed *or*
path-scanned — the rename-map builders (`build_plan` and
`_rename_pass_once`) both refuse to ever emit a rename whose collapsed
prefix *is* the root `press` component.

**Why.** "Exempt an exact artifact, never a location" means a nested
`docs/press/leak.md` is scanned normally, and a root `press/notes.md` does
**not** trigger a rename of the whole `press/` dir even when
`app_name == "press"` — only the four literal control files are ever
invisible to the scan or the rename pass; everything else under a `press/`
dir, root or nested, is ordinary content. `scan_paths`' regenerable-lockfile
exemption is deliberately keyed on `DEFAULT_RULES.exclude_files` (the
tool's **own** built-in set) rather than `rules.exclude_files` (the
target's config) — this is EMP-01: a target cannot add its own
`extra_exclude_files` entry to blind the verifier's scan to content it wants
hidden. Only a lockfile that is *both* in this target's `regenerate` list
*and* the tool's own default exclude set is exempt (because the real press
provably regenerates-or-fails it — see D5).

### D4 — Source-coordinate, occurrence-pinned, self-policing ignores (`ignores.py`)

**Context.** Some findings are legitimate — a fork's changelog legitimately
mentions its own prior name. A verify config needs a way to suppress a
*specific known* leftover without opening a hole that also suppresses a real
leak of the same token elsewhere.

**Options considered.**
- A directory/file-level allowlist (`verify_ignore`, the doctor's existing
  coarse mechanism) as the sole tool — rejected: too coarse (silences an
  entire file, not one occurrence) and cannot detect drift when the
  suppressed occurrence moves or disappears.
- Content-hash-pinned ignores — rejected: brittle across any surrounding
  edit, and doesn't fit the sandbox's deterministic coordinate mapping.
- Source-coordinate, occurrence-pinned ignores: `(file, field/value,
  anchor, line?, ordinal?)`, matched against the **source** file (not the
  sandbox), fail-closed on ambiguity, self-policing on staleness.

**Choice.** The third option, implemented as `Ignore`/`apply_ignores`.

**Why — three load-bearing invariants:**
- **Source coordinates.** A `Finding` carries a sandbox (pressed) path; an
  `Ignore` is authored against the original target. `build_forward_map`
  reverses `ApplyReport.renamed` ((old_prefix, new_prefix) pairs) to map
  every finding's path back to source before any ignore is evaluated.
- **The newline invariant.** Identity values can never contain `\n`
  (`identity.py`'s validators reject control characters, and every field's
  charset regex is newline-exclusive already), so a content finding's line
  number is identical in the source file and the pressed sandbox file — line
  N in source is always line N in sandbox — letting an ignore pin a stable
  source line even though the file's bytes differ after the press.
- **Occurrence pinning, fail-closed.** An `ordinal`-less ignore that would
  suppress ≥2 findings (an ambiguous anchor+line) raises `ValidationError`
  rather than silently multi-suppressing — the plan calls this the
  "universal fail-closed ambiguity guard," not a paranoid-posture-only rule.
  An `ordinal` pins exactly one occurrence within its `(src_path, field,
  value, line)` group.
- **Staleness is drift.** An ignore that suppresses **zero** findings and is
  not `force` is returned as `stale`, and a stale ignore fails the run —
  so an ignore list can never quietly accumulate dead entries that would
  mask a *regression* if the leak reappeared somewhere else.

Line-less findings (`filename`/`dirname`/`symlink`/`binary`/`unscannable`)
anchor against the **source path** rather than a line. `unscannable`
carries `field="io", value="unreadable"` (mirroring `doctor.Leak`'s existing
`("io", "unreadable")` convention) precisely so it remains ignorable by a
field/path-anchored rule even though it isn't really about any one identity
field.

### D5 — Hermetic verify (`apply()` never regenerates)

**Context.** Real `_press` runs `uv lock` after replace/rename so the
lockfile's own embedded package name matches the new identity — but that
means network access, an external tool invocation, and a mutation, none of
which belong in a read-only, repeatable check.

**Options considered.**
- Let verify also run `uv lock` in the sandbox — rejected: breaks
  hermeticity, adds network dependency and nondeterminism to a check meant
  to be trustworthy in CI.
- Exempt *all* lockfiles from the scan — rejected: a non-regenerable
  lockfile (`bun.lock`, `package-lock.json`) legitimately still embeds the
  old name after a real press and would be a genuine, undetected leak.
- `apply()` is invoked with `regenerate=()` (never regenerates anything);
  only `uv.lock` — the one lockfile the *real* press provably
  regenerates-or-fails — is scan-exempt (see D3's EMP-01 keying). Every
  other lockfile stays in the scan corpus.

**Choice.** The third option.

**Why.** This is what makes hermeticity and correctness compatible:
`uv.lock` is exempted from verify's own scan not because it's uninteresting,
but because the real `rebrand`'s `_regenerate_lockfiles` provably either
regenerates it correctly or fails the whole press with no receipt — so
verify doesn't need to re-derive that guarantee itself. A lockfile format
with no regenerator has no such backstop, so verify must catch a leftover
there directly.

### D6 — Equality-preserving deterministic synthesis + equal-fields WARN (`synthesize.py`)

**Context.** Verify needs a synthetic destination identity to press the
sandbox toward. If `package_name` and `app_name` happen to be equal in the
*source* (a common, valid, intentional setup) but synthesis mapped them to
two *different* dest values, the sandbox press would look like it "split" an
intentional equality — manufacturing a mismatch that isn't a real defect in
the template, just an artifact of verify's own synthetic identity.

**Options considered.**
- Random/independent dest values per field — rejected: not deterministic,
  breaks equality preservation, reproducibility suffers.
- Always map every source field to a distinct dest value regardless of
  source equality — rejected: same corruption problem.
- `synthesize_dest`: deterministic (`hashlib.sha256`-derived only — no
  `random`/`time`/`uuid`), maps **equal** source values to the **same**
  dest value (an equality class) and **distinct** source values to
  **distinct** dest values (checked explicitly against a running `used` set,
  not merely assumed from hash entropy), every dest value passes
  `Identity.validate()`, and no dest value is a substring of any source
  variant (separator/case/concat/camelCase/PascalCase forms) or vice versa.

**Choice.** The third option.

**Why, paired with equal-fields WARN.** Even with equality-preserving
synthesis, a source identity with two fields equal (e.g.
`package_name == app_name`) is a genuine scope limitation: verify's
own correctness guarantee can't fully exercise "these become distinct after
a real customer press" for that pair, because it never presses toward two
distinct values for them. So verify separately WARNs (exit-neutral by
default — `_equal_pair` in `verify_cli.py`) whenever two source fields are
equal, with opt-in `equal_fields = "error"` for templates that want to make
field independence a hard requirement. (The synthesis module also had to
harden its containment-free prefix derivation against a single-character
source value creating a universal collision floor — a hash-derived, not
hardcoded, leading character — a smaller implementation detail in the same
family as the ancestor-symlink fix in §5: a fixed "safe" constant turned out
not to be safe for every input.)

### D7 — Batched `just matrix` phase gates

**Context.** The plan spans Phase 0.5 through Phase 6 across 14 tasks. Per-
task gating with the full acceptance matrix (`scripts/rebrand_matrix.sh`,
the R1/R2/R3-style empirical proof from P03-M3) would be far too slow and
noisy to run after every micro-commit; gating only once at the very end
risks a late, expensive discovery of an integration break.

**Options considered.**
- Run `just matrix` after every commit — rejected: the matrix is the slow,
  holistic acceptance run, not a per-commit unit check.
- Run it only once at the very end — rejected: round-2 review found the
  `_press`-vs-`apply` keystone defect (§3, §6) precisely because
  verification was too infrequent during planning; the same risk applies to
  implementation.
- Batch it at phase boundaries: `just check` (fast) runs every commit,
  `just matrix` (slow, empirical) runs at each phase gate (after Phase 0.5,
  1, 2, 3, 4, 5, 6) and again pre-PR.

**Choice.** The third option.

**Why.** Phase boundaries are natural integration points — each phase's
tasks are functionally cohesive (e.g. Phase 3 = inventories + scanner) — so
a matrix run there catches an integration regression while it is still
cheap to bisect to a handful of tasks, without paying the matrix's cost on
every micro-commit.

### D8 — Engine-wide symlink safety

**Context.** This applies to **both** `rebrand` and `verify` — a control
location (`press/`, any control artifact inside it, or an ancestor
directory) is tool-managed and must be a real path. If it's a symlink, both
real `rebrand` (writing `press-receipt.toml`/`press-source.toml`) and
`verify` (reading it, copying it into the sandbox) could be redirected
outside the intended root.

**Options considered.**
- A verify-only guard — rejected: leaves real `rebrand` exposed to the
  identical hole; the plan explicitly frames v3's guard as engine-wide, not
  "a verify-only patch."
- Trust-on-first-write with no re-check — rejected: a TOCTOU window between
  an initial preflight check and the actual write.
- One shared `assert_control_real` (`config.py`) at the top of the shared
  load path (`load_source_config`, so both rebrand's resolve/write-from-
  discovery and verify's preflight are guarded by the same call), plus
  never write through a symlink at each individual control-file write site
  (`write_control`'s per-write re-check), plus rewrite in-repo relative
  symlink targets so a pressed fork's links don't dangle.

**Choice.** The third option — one engine-wide rule, not a verify-local
patch.

**Why.** Closing this once at the shared load boundary protects both
consumers from a single code path instead of duplicating the guard, and it
is what makes real `rebrand` non-destructive on a hostile or accidental
control symlink. What that guarantee actually required in practice — and
why it needed more than the single load-path check — is the subject of §5.1.

## 5. Implementation-time hardening

The plan's own self-review is explicit that this was not a formality: a
second fable+codex adversarial round on the *plan* forced the keystone flip
in §3, and later, task-level adversarial reviews on the *shipped code* found
real, demonstrable defects — not style nits — in the D8 symlink-safety
mechanism. These are the findings that explain the final shape of
`safety.py`, and documenting them is the most important part of this record.

### 5.1 D8 ancestor-symlink escape (the headline)

The first cut of the D8 guard validated where a symlink's target *pointed*
(the sink) but not the ancestors of where the symlink itself *lived*. That
meant a mutation like `os.unlink`/`os.symlink` could traverse a **symlinked
ancestor directory** and mutate a file **outside** the intended target or
sandbox root — confirmed by a proof-of-concept, not merely theoretical, and
not a race: a purely static hostile (or even accidental) ancestor layout is
enough, no concurrent attacker required. This is the plan's own
"152-file-wipe failure class" — the exact defect category the entire
Defensive Hardening (G1–G9) section exists to close, and the reason
documenting it is the point rather than an afterthought.

The **same** hole existed independently at three separate mutation sites:

1. **The symlink-retarget pass** (`engine.py:_retarget_symlinks`) — when
   unlinking/re-symlinking a token-bearing in-repo relative link.
2. **The rename pass** (`engine.py:_rename_pass_once`) — moving a path
   whose ancestor could be a symlink.
3. **The content-replace pass** (`engine.py:_apply_replacements`, via
   `safe_write`'s containment check) — and equivalently `sandbox.py`'s
   symlink recreation step.

It was closed with **one shared primitive**, `safety.assert_ancestors_real
(path, root)`: a no-follow `lstat` walk of every ancestor directory from
`root` down to — but excluding — the leaf. It deliberately:

- **tolerates a symlink leaf** — moving or retargeting a token-bearing
  symlink itself is legitimate (e.g. renaming a symlink, or rewriting its
  `readlink` target);
- **rejects a symlinked ancestor** — any directory between `root` and the
  leaf;
- **passes a root-level leaf** — nothing to walk.

This is deliberately distinct from the pre-existing `assert_under_root`
(used by `safe_write`/`safe_mkdir`/`safe_rename` for new-content writes,
which rejects a symlink *leaf* outright): the two primitives model two
different legitimate operations — writing new content into a path that
should not itself be a symlink, versus moving or retargeting a path that is
allowed to *be* a symlink. `assert_ancestors_real` is called at all three
sites: `engine.py`'s `_retarget_symlinks` (before `os.unlink`/`os.symlink`),
`_rename_pass_once` (on both the rename source and destination, before
`src.rename(dst)`), and `sandbox.py`'s `make_sandbox` (before recreating a
copied symlink verbatim in the sandbox).

**Why this makes real `rebrand` non-destructive.** Because D8 was scoped
engine-wide rather than verify-only, the same `assert_ancestors_real` calls
run during a **real** press against a **real** target, not only inside
verify's disposable sandbox — so a real rebrand run against a target with a
hostile or accidental symlinked ancestor now fails closed (raises,
propagates to a non-zero exit) instead of silently mutating outside the
target. This combines with two other primitives to close the write-through
surface completely: `write_control`'s per-write, sink-local containment
re-check (the control-file writes for the receipt and source-config
re-validate immediately before *each* write, not once at an earlier
preflight, closing the TOCTOU window between check and write) and the
atomic-write pattern in `safe_write` (temp file + `os.replace`, which always
creates a **new inode** rather than editing an existing one in place, so a
hardlinked sink's other links are never touched). Never-write-through +
always-new-inode + per-site ancestor validation together are what make it
safe to run `rebrand` against untrusted, third-party target content — which
the tool's whole premise (pressing an *external* target repo, per design
0006) depends on.

### 5.2 m1 lockfile guard

`_regenerate_lockfiles` (`cli.py`) refused to run `uv lock` through a
symlinked lockfile. Before the fix, a symlinked `uv.lock` would have `uv
lock`'s own file write land on whatever the symlink actually pointed at —
the exact same "trust the sink, not the leaf" gap as §5.1, just reached via
an external tool invocation rather than direct engine code. It is fixed
with an explicit `lockpath.is_symlink()` `lstat`-based, no-follow check
**before** ever invoking `uv lock` (`cli.py:250`), treated as a
regeneration failure — the press fails, no receipt is written — rather than
a silent skip. The plan calls this out as its own, separate task ("a
dedicated destruction-safety task") because it is a *third* kind of
write-through vector — an external tool's own I/O, not the engine's direct
file operations — that the D8 guard alone does not cover.

### 5.3 Exception taxonomy (`PressOutcome`)

Real `_press` keeps its existing post-mutation exit-1 semantics unchanged.
Verify, however, needs a clean three-way split that real `rebrand` never
needed: config/env problems (exit 2) must never be confused with a genuine
leak surviving the scan (exit 1). `PressOutcome` (`cli.py`) structurally
separates `leaked: bool` from `env_error: str | None`, and carries
`renamed`/`regenerated` provenance through even on failure (from
`ApplyReport`). Verify's own exception taxonomy in `verify_cli.py`
(`_CONFIG_ERRORS` for anything on the pre-sandbox/sandbox-setup path;
`_PRESS_ENV_ERRORS` for a failure raised *by* the press itself — `apply()`
or the sandbox re-stage) mirrors this split: an env/tool error during the
sandbox press maps to exit 2 ("the press could not complete, so verify
cannot claim clean"), never exit 1, which is reserved for an actual
surviving finding, stale ignore, unavailable submodule, or an
`equal_fields="error"` collision.

## 6. Adversarial-review process

This design went through more than one round of review, and the process is
part of why it can be trusted:

1. **Design pass**, then **two plan iterations** (v1 → v2 → v3). The plan's
   own header records why v2 was abandoned: *"rewritten after a **second**
   fable+codex adversarial round found that routing verify through
   `_press` was the root of several blockers. v3's keystone: verify
   composes `apply()` + its own scan; it never calls `_press`."* This is
   the keystone decision documented in §3 — it is not how the design
   started, it is what an adversarial round forced it to become.
2. **A two-pass defensive gate** ("Gate tightenings — opus focused gate,
   2026-07-18" in the plan) hardened the G1–G9 primitives *before any code
   was written*: named entries for `.git` casefold/8.3-shortname
   normalization (G2+), repo-local `.git/config` execution surfaces on
   *every* on-target git call, not just the sandbox (G5+), enforcing the
   test-isolation ban rather than leaving it advisory (G1+), and the
   documented residual that a repo-local clean/smudge filter driver cannot
   be disabled by name via any fixed `-c` flag set (G5++).
3. **Per-task reviews during implementation** caught the two concrete
   defects in §5 (the ancestor-symlink escape and the lockfile guard) —
   these were not anticipated in the same form by the original G1–G9 list;
   they were found by exercising the *actual shipped code* against the
   stated threat model, which is why they are hardening findings rather
   than planned decisions.

None of D1–D8 is a single-pass author's-first-draft decision — each survived
at least one adversarial round that could veto or reroute it, the keystone
flip in §3 being the largest example — and the two implementation-time
findings in §5 show the review process kept working past the planning
stage, catching real, PoC-confirmed defects in shipped code rather than only
theoretical gaps in a plan document.

## 7. Scope note

Verify's correctness guarantee is scoped to its **configured** fields —
`DEFAULT_FIELDS = (app_name, package_name, repo_name, owner)` in
`verify_config.py` — not all six of `identity.REQUIRED_FIELDS`. `author`
and `email` are opt-in via `extra_fields`; they are excluded by default
because they are frequently intentionally shared with real-world content
(a name, a contact address) in ways that would make a default-on scan noisy
without configuration. This is a deliberate scope limit, not an oversight,
and should not be read as "verify checks every identity field."

## 8. Cross-links

- **Plan:** [`docs/superpowers/plans/2026-07-17-press-verify.md`](../superpowers/plans/2026-07-17-press-verify.md)
  — the full D1–D8 rationale, the task-by-task TDD sequence (Tasks 0–14),
  and the complete G1–G9 defensive-hardening specification this design
  summarizes.
- **`PROJECTS.md` P03** (External-target rebrand press, clean-core rebuild)
  — this design covers `press verify`, the standalone fulfillment of P03's
  "verify-then-mark" line; see task `P03-M5b` (verb registration & docs)
  and the `P03-M6` (Provision phase) follow-on.
- **[0006 — external-target model](0006-external-target-model.md)** — the
  "verify-then-mark" rebrand-model line item this design fulfills as a
  *separate* verb. 0006 describes the inline, doctor-based check inside
  `_press`; this design is the standalone, paranoid `press verify` verb.
  Per the keystone decision (§3), the two deliberately do **not** share a
  code path — `_press` still runs its own inline doctor gate before writing
  a receipt, unaffected by this design.
