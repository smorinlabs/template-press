# E6 (entry #8) — adversarial review: "identity rewrite erases provenance"

**Verdict: APPLY MODIFIED — take the blueprint-config half (with identity-free
stubs), REJECT both engine mechanisms. Confidence: high.**

Scope note: paths are relative to the repo root; `src/` is elided as `sp/` =
`src/template_press/rebrand/`.

---

## 1. Steelman — the engine is right as-is

**Provenance already ships, machine-readable and durably exempt.**
`sp/receipt.py:75` writes `[press.from]` from the full source `Identity`
(`_identity_table`, `sp/receipt.py:47`), and `press/press-receipt.toml` is one
of exactly four literal paths in `ROOT_CONTROL` (`sp/pathing.py:12-19`). Design
0007 D3 (`docs/design/0007-press-verify-design.md:200-215`) makes that exemption
"an exact artifact, never a location" — so the receipt carries the source
identity forever and is structurally invisible to both scanners. The receipt is
written *only* after the no-leak gate passes (`sp/receipt.py:1-7`), so its
presence is itself the provenance attestation.

The proposal's premise — "nothing asserts that the upstream template is still
named where provenance belongs" — conflates *provenance is gone* with
*provenance is not in README*. Only the second is true.

**"No source identity survives" is a falsifiable invariant; the proposal makes
it unfalsifiable.** Every scanner in the tool is changed-fields-only and
one-directional: `verifier._changed_fields` (`sp/verifier.py:165`) and
`doctor.find_leaks` (`sp/doctor.py:278-295`) look for the SOURCE value and
report occurrences. Nothing else. That is why the paranoid posture
(0007 §2, `docs/design/0007-press-verify-design.md:38-56`) can afford false
positives: every suppression is explicit, named, and drift-checked.

**A targeted exemption already exists for exactly this case.** 0007 D4's
motivating example is verbatim "a fork's changelog legitimately mentions its own
prior name" (`docs/design/0007-press-verify-design.md:225-227`). The answer
shipped was occurrence-pinned, source-coordinate, self-policing ignores
(`sp/ignores.py:1-27`) — strictly better than a path allowlist: it pins one
occurrence, fails closed on ambiguity, and a zero-match ignore is *stale* and
fails the run.

## 2. Attacks on the engine half

**A2.1 — `provenance_paths` cannot tell provenance from a leak.** The proposed
assertion is "`README.md` must still contain the source `owner`/`repo_name`".
Satisfied by *any* surviving occurrence — including a missed rewrite. Paired
with its own companion (a `[[replace]]` exemption that stops README's provenance
line being rewritten), the two halves compose into a mechanism that converts a
genuine leak into a PASS. Neither an exact declared line, a path allowlist, nor
a field subset fixes this: the scanner has no notion of *why* a token is there,
and adding one means the config author asserts correctness the tool then cannot
check. That is the inversion of EMP-01 (`0007:210-218`: a target must never be
able to blind the verifier to content it wants hidden).

**A2.2 — wrong verb, so it gates nothing.** The proposal targets `press verify`.
Real presses are gated by the *inline doctor*, and the two do not share the
ignore machinery: `cli.py:557-562` feeds the real press only the coarse
component-level `rules.verify_ignore`, while the D4 occurrence-pinned `Ignore`
objects are parsed from `[verify.ignore]` (`sp/verify_config.py:38-40`) and used
only by the standalone verb. A `[verify] provenance_paths` assertion would let
`press verify` pass while `press rebrand` still aborts on the same line (and
vice versa). A provenance guarantee that does not run on the real press is
theatre.

**A2.3 — template-of-templates.** `[[reset]]` of README/POST_INIT and
`[[remove]]` of the bootstrap skill live in the SOURCE template's
`press/press-rules.toml` and apply to every press of it. A fork that *should*
stay a template needs the opposite. There is no per-press intent selector: the
only selector is `platforms`, which is `sys.platform` (`sp/rules.py:419-443`,
`_select_rules` at `sp/rules.py:822-847`) — an OS, not an intent. This does not
sink the config fix (leaf forks are the overwhelming majority and E6's actual
symptom), but it does mean the fix is a blueprint-author policy choice, not a
universal rule — and it is one more reason not to bake it into the engine.

**A2.4 — interpolated reset stubs are dead on arrival, twice over.** Stubs take
no interpolation: inline `stub` "is returned verbatim"
(`sp/reset.py:84-88`). A stub carrying the source identity is refused at plan
time by `scan_stub_text` (`sp/reset.py:106-160`; test
`tests/rebrand/test_reset_rules.py:229-247`, `TestStubScan::
test_changed_token_flagged`). Adding interpolation therefore needs hole #1
(exempt the rendered source values from the stub scan). But it also needs hole
#2: a `[[reset]]` target must be in `exclude_files` (`sp/rules.py:574-577`),
and per 0007 D3's EMP-01 keying the scan corpus is exempted only by the tool's
OWN `DEFAULT_RULES.exclude_files` — so a reset README stays fully in the
post-press corpus of both `doctor.find_leaks` and `verifier.scan`. Two
coordinated holes across three layers, for one line of prose.

**A2.5 — the tempting wrong fix.** `verify_ignore = ["README.md"]` does
mechanically work: `sp/inventory.py:1092-1103` matches any path *part*. But
`verify_ignore` is documented as a directory component set
(`sp/rules.py:184-188`) and it silences every `README.md` at every depth,
entirely — a real missed rewrite in README becomes invisible. Strictly worse
than the status quo.

## 3. The honest concession

There is a genuine gap, and it is narrower than E6 states: **today it is
structurally impossible for a completed press to keep a human-readable source
name in any scanned file.** `extra_exclude_files` stops rewriting but not
scanning (EMP-01); `verify_ignore` is file-wide and doctor-only; reset stubs are
verbatim and identity-refusing. If a human-readable provenance line ever becomes
a hard requirement, the correct mechanism is **extending D4's occurrence-pinned,
self-policing ignores to the inline doctor gate** — one existing, drift-checked
concept reused, still fail-closed, still stale-detecting. It is not
`provenance_paths`. Recording this as future direction, not as a recommendation.

## 4. What to apply

Blueprint-side only, in `py-launch-blueprint`'s `press/press-rules.toml`:

1. `[[reset]] README.md` and `[[reset]] docs/POST_INIT.md` with **identity-free**
   stubs that *point at* provenance rather than restating it — e.g. "This repo
   was pressed from a template; see `press/press-receipt.toml` (`[press.from]`)
   for the source." No source `owner`/`repo_name` token, so the stub scan
   (`sp/reset.py:106`) and both post-press scans pass unchanged. Each reset file
   must also be added to `[rules] extra_exclude_files` (`sp/rules.py:574-577`).
2. `[[remove]] .claude/skills/new-python-project/SKILL.md` with a `reason`.
   `[[remove]]` needs no `exclude_files` membership (`_parse_remove`,
   `sp/rules.py:606-638`) — only a non-empty printable `reason`, and the target
   must be git-tracked and clean (`sp/remove.py:50-90`).
3. **No engine change.** Drop `[verify] provenance_paths` and the `[[replace]]`
   provenance exemption.

**Known residuals** (state, do not fix):
- A receipt-pointing stub is itself refused when `app_name == "press"`: `/` is a
  boundary, so the matcher fires on `press` inside `press/press-receipt.toml`.
  Irrelevant for py-launch-blueprint; real for template-press pressing itself.
- Provenance stays machine-readable-first. A human reading only README learns
  *that* it was pressed, not *from what*, without opening the receipt.

## 5. The one test that must exist

Matrix-level (`just matrix`, `tests/rebrand/test_matrix.py`): press the
blueprint fixture end-to-end, then assert **both** halves in one test —
(a) `README.md` yields zero source-identity findings from `verifier.scan`, and
(b) the written receipt's `[press.from].repo_name` equals the SOURCE
`repo_name`. That single test is what discriminates E6's fear ("provenance was
erased") from the actual design ("provenance was relocated to the receipt"), and
it fails loudly if either the reset stub regresses or `[press.from]` stops being
written.
