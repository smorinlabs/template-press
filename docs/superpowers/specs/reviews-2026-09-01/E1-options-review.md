# E1 options review — A vs B-checked vs E (origin guard in `_resolve_source`)

Independent adversarial pass at v4.0.0; read-only. Ranking **A > B-checked > E-as-replacement**; E-scoped is a real follow-up supplement.

## 0. Decisive new evidence — E does NOT catch the blind spot it was proposed for

E's headline claim: a presence check catches "template renamed upstream, source-config stale".
Executed, not read (`uv run python`, both matchers):

```
find_occurrences('…/smorinlabs/py-launch-blueprint-2/issues','repo_name','py-launch-blueprint',
                 substring=False)                                    -> [(30,49)]  # PRESENT
token_pattern('repo_name','py-launch-blueprint').sub('newname','see py-launch-blueprint-2 docs')
                                                                     -> 'see newname-2 docs'
```

Both matchers end on `(?![A-Za-z0-9])` (`matcher.py:62`, `identity.py:209`) and `-` satisfies that
lookahead, so for the prototypical rename shape (separator-joined suffix/prefix) the stale value
**is** "present" and E returns clean; E fires only on a wholly different string (typo
`py-launch-bluepint`, `alpha`→`omega`). The same fact upgrades the blind spot's severity for A and
B-checked — and it is a pre-existing v4.0.0 hazard on the no-origin path, not one any candidate
introduces: the press rewrites INSIDE the renamed token, the doctor scans for the declared old
value, finds none, and writes a receipt (`cli.py:640-647`, `receipt.py:53`) — silent corruption,
not a missed rewrite.

## 1. Baseline facts that reframe the whole comparison

- **The guard is already opt-out-able today, silently.** `_origin` returns `(None, None)` on any
  non-zero `git remote get-url` (`discovery.py:58-59`) and `mismatches` skips `None` fields
  (`discovery.py:113-114`), so `git remote remove origin` disables the owner/repo_name half with
  no flag, notice, or receipt entry — pinned as intended by `tests/rebrand/test_discovery.py:40`.
  Any argument that A "opens a hole" must first explain the open door.
- **The check is anti-correlated with risk.** Plain `git clone <template-url> newdir` leaves
  origin = template = source-config → zero mismatches → press proceeds. The hazardous provenance
  passes; the safe one (`gh repo create --template --clone`) is refused. No flag reaches the
  guard: `--force` only clears the receipt precondition (`cli.py:102-106`, `:364`) and
  `--accept-discovery` only authorizes writing a proposed config (`cli.py:227-238`).
- **Answers are parsed after the guard** (`_resolve_source` `cli.py:227`, `load_answers`
  `cli.py:240`), but hoisting is safe: `load_identity_toml` raises `ValidationError`/
  `TOMLDecodeError` (`config.py:67-92`), caught at `cli.py:371-378` → exit 2, and `write_pending`
  is deferred by design (`cli.py:132-137`), so "exit 2 ⇒ no writes" holds. Only visible flip — a
  mismatching config AND a malformed answers file now reports the answers error first; no test
  pins that ordering (`tests/rebrand/test_cli.py:178` is source-config only).
- **`press verify` already ships an E**: `_preflight` (`verify_cli.py:201-268`) does the presence
  check and deliberately scopes it — required only for fields BOTH undiscoverable AND in the
  effective scan scope (`verify_cli.py:210-217`), plus `display_name` (`:236-251`), which has no
  discovery entry at all. That scoping is why E cannot be a drop-in replacement (§4).

## 2. Per-candidate scenarios (strongest failure each)

| Scenario | A | B-checked | E (as replacement) |
|---|---|---|---|
| gh-created clone, same owner | accepted + notice | accepted **iff** flag pasted | accepted (values still present) |
| Cross-owner fork (`gh repo create other/new --template s/tmpl --clone`) | both fields relaxed per-field, accepted | same, with flag | accepted |
| Target with NO origin | unchanged: silently skipped | unchanged: silently skipped | **behavior change**: now judged on content |
| Plain clone of the TEMPLATE | origin==config ⇒ guard never engages; press proceeds | identical | identical |
| Re-press after a successful press | on the gh path origin already == dest1 == refreshed config (`cli.py:643`); relaxation never engages | identical | identical |
| Re-press of a locally-cloned target (origin still old) | still exit 2 — origin ≠ new dest (matches `test_cli.py:601-615`, which resets the remote by hand) | identical | passes (old values gone from tree… or present, per §0) |
| `--force` re-press of an exit-1 half-pressed tree | exit 2 on `package_name` (pyproject already rewritten) | same | same |
| `display_name`-only press | **no coverage** — `mismatches` never checks it | same | **only candidate with coverage** |
| `press verify` (`verify_cli.py:226`) | unchanged | unchanged | unchanged (already does this) |

**A's strongest failure** — the shared blind spot, now with teeth: template renamed
`py-launch-blueprint` → `py-launch-blueprint-2` upstream, package name unchanged, `press-source.toml`
still says the old repo_name, clone made with `gh repo create --clone` so origin == destination.
A relaxes `repo_name`/`owner`, the press rewrites the stale token *inside* the live one (§0),
doctor clean, receipt written. **B-checked fails identically** — same per-field rule; the flag
changes nothing about which values are compared.

**A's strongest false refusal:** origin and answers agree on the repo but differ in case
(`Owner/Repo` vs `owner/repo`); `_ORIGIN_RE` preserves case (`discovery.py:21-24`) and GitHub does
not, so the operator is blocked with no in-tool escape but deleting the remote. Same for one who
created the GitHub repo under a name they intend to rename later. **B-checked's is A's, plus one
A lacks** — the flag is unconditional on the documented bootstrap path, so it lives in the runbook
and gets pasted unread; a flag every user always passes attests nothing. Its one useful feature
(recording the acknowledgement, `receipt.py:53-122`) is portable to A as an unconditional
`[press] origin_relaxed` receipt line.

**E's strongest false refusal:** a target with no GitHub URLs in its tree (private repo, README
that never links itself) declares a correct `owner` occurring zero times → refusal, where v4.0.0
presses fine. Likewise `email`, which occurs only in `pyproject.toml [project.authors]`. `verify`
already had to solve this (`verify_cli.py:210-217`); a plan-time E must inherit that scoping,
shrinking its new coverage to almost nothing.

## 3. Against the spirit ("a declaration the repo contradicts cannot press silently")

- **A: keeps it, honestly.** The repo does not contradict the declaration — the *clone's origin*
  does, for a reason (`gh` set it) that A verifies per field against an independent artifact (the
  answers file) and announces out loud. It refuses an unrelated origin exactly as today.
- **B-checked: keeps it, at the price of blocking the documented path first.** Its added safety
  over A is an attestation on a path where the tool already proved the condition itself.
  **Ceremony:** it buys auditability (receipt line), not safety — and A can have that.
- **E: changes the sentence** to "the declared value appears somewhere" — neither necessary
  (URL-less targets) nor sufficient (§0; presence ≠ completeness — one surviving mention makes a
  wholly wrong config look supported). As a **replacement** it trades a real silent-pass
  (origin-less targets) for false refusals while missing the case it was pitched on. As a
  **supplement** it is additive in exactly one place: `display_name` plus the
  wholly-undiscoverable-and-absent verdict — i.e. porting `verify_cli.py:236-268` to plan time.
  So: A now, E-scoped later **alongside** the origin check, never instead of it.

## 4. Cost

| | engine lines | tests | docs |
|---|---|---|---|
| A | ~25: hoist `dest = load_answers(...) if args.config else None` above `cli.py:227`, add a 4th param, a per-field `or discovered == dest_value` branch, a notice; `mismatches()` untouched | 4 (below) | 1 para in `docs/source/reference/cli.md` + the case caveat; `.claude/skills/press-target/SKILL.md` unchanged |
| B-checked | A + ~20 (argparse flag, unsatisfied-condition error text, receipt line) | A's 4 + 3 (flag absent/present/unrelated-origin-with-flag) | A's + flag reference + runbook edit on every bootstrap example |
| E-scoped | ~60: extract `_target_text_corpus`/`_value_present`/scan-scope resolution out of `verify_cli` into a shared module, load `Rules` + verify config BEFORE the guard (today `load_selected_rules` runs at `cli.py:245`, after) | 8+ (present / absent / substring field / display_name / URL-less target / scoping) | new section on when presence is required |

**Corpus cost is not the objection.** `build_plan` already reads every content file at plan time
(`engine.py:857-868`) and `_target_text_corpus` (`verify_cli.py:130-157`) walks the same
`scan_paths` set — a second full read of a source repo, tens of ms. E's cost is the load-order
refactor and the scoping semantics, not I/O.

## 5. Verdict

**Ship A now. Confidence: high** on the ranking, **medium-high** on A's exact shape. Follow-up:
E-scoped as a *supplement* (display_name presence + wholly-absent verdict at plan time, reusing
verify's scoping), plus the separator-boundary blind spot written into
`docs/design/0006-external-target-model.md` §"Rebrand model" 1. Do NOT ship B-checked: its only
non-ceremonial part is the receipt line, which A should carry unconditionally. A's shape:
`owner`/`repo_name` only, per field; accept a discovered value that disagrees with the config iff
it equals the destination's value for that same field; no receipt precondition; exact
(case-sensitive) comparison; print field, config and origin values; keep exit-2 gates ahead of
`write_pending`.

**Minimal test set for A** (both halves + the blind spot asserted):

1. **Accepted state exits 0.** `press-source.toml` = template identity, origin = the DESTINATION
   GitHub URL, answers = that same destination ⇒ `--dry-run` exits 0 AND the notice naming
   `repo_name` (and `owner` in the cross-owner variant) prints. Parametrize same-owner /
   cross-owner to pin that the rule is per field, not whole-identity.
2. **Unrelated origin exits 2.** Same fixture, origin at a third repo ⇒ exit 2, message contains
   `repo_name`, no `press/press-source.toml` write, no receipt.
3. **Stale-config blind spot, asserted explicitly.** source-config `repo_name =
   "py-launch-blueprint"`, tree and origin both `py-launch-blueprint-2`, answers = destination ⇒
   `--dry-run` exits 0, commented as the DOCUMENTED accepted blind spot (E-scoped would not close
   it either — §0), so a future flip is deliberate, not accidental.
4. **No-`--config` discovery-proposal path still works** with `dest = None` threaded — regression
   on the `load_answers` hoist; `cli.py:231-238` must still print and return 2
   (guards `tests/rebrand/test_cli.py:56-63`, `:707`).
