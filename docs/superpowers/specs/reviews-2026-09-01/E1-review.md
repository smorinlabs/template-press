# E1 adversarial review — origin-mismatch guard in `_resolve_source`

Reviewed at v4.0.0. Read-only; no press run, no writes to the repo.
Entry #4, severity "blocker". Verdict at the bottom.

## 0. What the code actually does

- `src/template_press/rebrand/cli.py:168` runs `mismatches(source, discover(target))`
  unconditionally once a source identity exists (loaded from disk at :141 or
  proposed by discovery at :143), and returns 2 at :176.
- `src/template_press/rebrand/discovery.py:82` fills `owner`/`repo_name` from
  `git remote get-url origin` (`_origin`, :39-61); `mismatches` (:101-134)
  skips only fields discovery could not resolve (:113-114).
- So for a clone created by `gh repo create <owner>/<new> --template <tmpl> --clone`,
  `origin` names the DESTINATION repo while the committed
  `press/press-source.toml` names the template. Two fields mismatch, exit 2,
  before `--config` is ever read. Consistent with the reported 4.0.1 / 3.6.0
  reproduction.
- No bypass exists: `--force` only clears the receipt precondition
  (cli.py:102-106) and invalidates a receipt later (cli.py:364);
  `--accept-discovery` only authorizes writing a proposed source-config
  (cli.py:231-238); `--source-config` changes which file is loaded (cli.py:141).

## 1. Steelman: what the guard genuinely protects

Design 0006 §"Rebrand model" 1 makes the committed source-config authoritative and
discovery a validator that "fails loudly on mismatch". The load-bearing part for
`owner`/`repo_name` is this: the post-apply doctor scans only for tokens of the
DECLARED source identity, changed fields only (0006 §3; `find_leaks` at
cli.py:25). If the declared `owner` or `repo_name` is stale or mistyped, the
press rewrites strings that do not exist, the doctor finds no surviving declared
token, and the run earns a receipt while every real occurrence of the true old
name survives. That is exactly EMPIRICAL R2, the failure the guard was built for
(discovery.py:1-8), and the origin check is the ONLY pre-apply detector of it.

Concrete scenario the proposal would newly allow: a target whose committed
`press-source.toml` says `repo_name = "py-launch-blueprint"` while the repo was
renamed months ago and its files say `py-launch-blueprint-2`; the operator
presses it to `py-launch-blueprint-2`-something and the answers file happens to
carry the same `owner`. Today: exit 2 on `owner`. Under the proposal: relaxed,
pressed, doctor passes, `smorinlab*`-owned URLs left half-rewritten with a
receipt asserting success.

## 2. Attack on the proposal as written

1. **`--config` is not available where the check lives.** `_resolve_source` is
   called at cli.py:227; `load_answers` runs at cli.py:240-242. The proposal is
   under-specified: it needs `dest` threaded into `_resolve_source`, and the
   no-`--config` discovery-proposal path (cli.py:231-238, exercised by
   `tests/rebrand/test_cli.py:707`) must still work with `dest = None` and the
   guard unrelaxed. Any implementation that reorders `load_answers` above the
   guard also moves an exit-2 gate and must preserve "exit 2 ⇒ no writes"
   (tests/rebrand/test_cli.py:1109, :1163, :1187).
2. **"No receipt" is a false proxy for "first press".** The module docstring
   (cli.py:5-6) states exit 1 = leaks after apply, NO receipt — the target is
   already rewritten. `--force` deletes the receipt BEFORE apply
   (cli.py:364) so an aborted forced re-press also leaves a mutated,
   receiptless target. The press-target skill even documents the exit-1 state
   (`.claude/skills/press-target/SKILL.md:31-40`). Gating a safety relaxation on
   receipt absence therefore turns it ON precisely in the half-pressed states.
   (Package_name still catches most of these, but the gate is wrong on its own
   terms.)
3. **Anti-correlated with the real hazard.** `origin` encodes clone provenance,
   not code identity. The guard fires on the safe workflow
   (`gh repo create --template --clone`) and stays silent on the dangerous one:
   `git clone <template-url> newdir` leaves `origin` equal to the template, so
   `mismatches` returns `[]` and the press happily rewrites the operator's clone
   of the shared template. The check is inverted relative to risk.
4. **Re-press interactions are benign, so the gate buys nothing.** On success
   the press refreshes `press-source.toml` to the destination (cli.py:640-647),
   so after any completed press `origin == source-config` and the guard passes
   with or without a relaxation. The receipt condition adds branch complexity
   for no protection.
5. **Case and host forms.** GitHub owner/repo are case-insensitive; `_ORIGIN_RE`
   (discovery.py:21-24) matches only `github.com` HTTPS/SSH and preserves case.
   `Owner/Repo` in `origin` vs `owner/repo` in the answers file leaves the user
   stuck with the same blocker and no bypass. SSH-alias or GHES remotes yield
   `None, None` and are unaffected.
6. **Owner matches, repo_name does not** (same-org press) — a whole-identity
   equality test would fail to relax; the rule must be per field.
7. **Adjacent, out of scope, but real:** when the target has NO source-config,
   discovery on a fresh gh-created clone proposes the DESTINATION owner/repo as
   the SOURCE identity (cli.py:143-151), so `--accept-discovery` writes a wrong
   source-config. The fix must not make that path quieter.

## 3. Alternatives

| # | Option | Trade-off |
|---|---|---|
| A | Accept a discovered value equal to EITHER identity, per field, no receipt condition | Simplest correct rule; loses nothing vs. the receipt gate (§2.4); still silences a genuine stale-config case that coincides with the destination value |
| B | `--expect-remote destination\|source` opt-in flag | Guard stays absolutely strict; but the flag would be required on the PRIMARY workflow, so every consumer hits the wall first — bad default UX, and a flag is easy to paste blindly |
| C | Origin-derived fields advisory (warn, not exit 2) when no receipt | Restores the workflow but accepts ARBITRARY origins — strictly weaker than A, and contradicts 0006 principle 1's "fails loudly" |
| D | Document the `git remote rename origin origin-pending` dance only | Zero code risk; institutionalizes mutating the user's remotes, and an aborted press leaves the repo with no `origin` (broken push/CI) |
| E | Replace the origin comparison for `owner`/`repo_name` with a content-presence check, reusing `_value_present` / `_target_text_corpus` (`src/template_press/rebrand/verify_cli.py:205-260`) | Deepest fix — tests what the press will actually rewrite instead of clone provenance; larger change, new scan cost, more than a blocker fix warrants now |

## 4. Verdict

**APPLY MODIFIED — confidence: medium-high.**

Modification, exactly:

1. Thread the destination identity into the guard (`_resolve_source(target,
   override, accept_discovery, dest)`), `dest = None` when `--config` is absent;
   with `dest is None` behavior is unchanged. Keep every exit-2 gate ordered so
   "exit 2 ⇒ no writes" still holds.
2. Per field, for `owner` and `repo_name` ONLY: a discovered value that
   disagrees with the source-config is accepted iff it equals the destination's
   value for that SAME field (alternative A). No other field is relaxed.
3. **Drop the receipt condition** (§2.2, §2.4) — it is a false proxy and buys
   nothing.
4. When the relaxation fires, print a notice naming the field, the source value,
   and the origin value ("origin already names the destination; accepted"). The
   mismatch is answered out loud, not ignored — 0006 principle 1 stays honest.
5. Compare exactly; add one line to `docs/source/reference/cli.md` noting that a
   case-different `origin` still trips the guard. Do not touch `mismatches()`
   semantics (used by `press verify`, verify_cli.py:225-226).
6. Do not add a flag. Alternative E is the right follow-up issue, not this fix.

**The one test that must exist** (CLI level, both halves in one test):
committed `press-source.toml` = template identity, `origin` = the DESTINATION
GitHub URL, answers = that same destination ⇒ `--dry-run` exits 0 and the notice
is printed; negative control, same fixture with `origin` pointing at an
unrelated third repo ⇒ still exit 2 with the `repo_name`/`owner` mismatch
message. Either half alone does not pin the semantics.
