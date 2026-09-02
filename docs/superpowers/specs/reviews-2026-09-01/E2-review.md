# E2 adversarial review — `_prefix_closure` refuses gitignored nodes

**Verdict: APPLY MODIFIED (diagnostics only). Confidence: high. Severity: NOT a blocker — downgrade to minor/usability.**

## 0. Severity first, because it changes what is worth building

The failure is discovered **read-only, at dry-run, with the offending path already named**:

- `build_plan()` runs at `src/template_press/rebrand/cli.py:257`, *before* the `if args.dry_run:` exit at
  `cli.py:356`, inside the `try` whose handler is `except (… SafetyError) as exc: return _fail(str(exc))`
  (`cli.py:371-377`). So the operator sees the refusal on `--dry-run`, with zero mutation.
- The message already interpolates the path: `f"rename prefix {source_prefix!r} would carry {rel!r}, which is
  absent from the authorized surface inventory"` (`substitutions.py:556-559`). The entry claims the path is
  unnamed; it is not.
- Remediation is one command the operator already owns: `git clean -fdX -- src/`.

"Blocked entirely, must delete caches first" is accurate but is a one-command speed bump found before any write,
not a blocker. Everything below argues the guard itself must stay.

## 1. Steelman: the refusal is the ONLY guard against an ignore-status flip

The visibility gate fingerprints ignore **inputs** — `.gitignore` / `info/exclude` / `core.excludesFile` bytes and
node identity (`inventory.py:766-788`, `_visibility_inputs` at `inventory.py:817`), and refuses a press that would
change them (`docs/design/0009-substitution-table.md:481-500`). It does **not** track whether a given path stays
ignored. Ignore patterns are frequently path-anchored:

```gitignore
/src/demo_widget/generated/
/src/demo_widget/local_secrets.py
```

Rename `src/demo_widget` → `src/potato_launcher` and those patterns stop matching. Carrying the files makes
`local_secrets.py` an ordinary untracked visible file in the pressed repo — the next `git add -A` commits it.
Nothing else in the pipeline catches this: the visibility gate saw unchanged `.gitignore` bytes, and the
verifier/doctor recapture (`0009:481-490`) sees the newly visible file as legitimate surface. The current refusal
is the only thing standing between an ignored secret and a public fork.

Same shape for a `.venv/` inside the package dir (absolute paths in `pyvenv.cfg`/shebangs silently break; hundreds
of MB moved), an ignored `.env`, or an ignored large build tree.

## 2. Per-variant attacks

### 2a. Carry-allowed — fails on three independent grounds

**(i) Closure-volatility dilemma.** `revalidate_rename_plan` re-runs `_prefix_closure` before the first mutation
and refuses on `current_closure != step.closure` (`substitutions.py:591-609`). Two horns:
- Ignored nodes IN the closure → a `.pyc` rewritten between plan and apply (exactly what `pytest`/`ty` do) raises
  `"rename prefix closure changed after planning"`. Carry-allowed is **flakier than refusal for the very
  `__pycache__` case that motivates it**.
- Ignored nodes OUT of the closure → the closure stops proving what the move carries, which is its stated purpose
  ("Capture and authorize every no-follow node carried by one move", `substitutions.py:510`; design rationale at
  `0009:785-790`).

**(ii) Carried symlinks are never retargeted or leak-checked.** `_retarget_planned_symlinks` iterates
`plan.source_entries` only (`engine.py:1255-1257`) and raises `"symlink was not captured during planning"` for
anything else (`engine.py:1268`; test at `tests/rebrand/test_substitution_safety.py:45`). A carried *ignored*
symlink is not in `source_entries`, so it is silently moved, never retargeted, never leak-scanned — and it may
point outside the target. This kills carry-allowed on its own.

**(iii) Receipt/inventory incoherence.** `select_copy_entries` / `select_verifier_entries` /
`select_rename_entries` (`inventory.py:1011-1104`) all derive from `snapshot.entries`. Carried nodes appear in
none of them, so the receipt would under-report what the press moved — the opposite of the attributability the
design asks for.

### 2b. Delete-and-report — categorically worse than refusing

It destroys untracked, un-restorable operator data (`.env`, a local sqlite DB, scratch notes) in a repo the press
does **not** own. This contradicts the module's overriding invariant, "*nothing is written, renamed, or deleted
outside the intended root*" (`safety.py:3-5`), and contradicts the sibling refusal's own reason — Git cannot
restore it (`substitutions.py:549-552`). Rejecting a press costs a `git clean`; deleting costs data.

### 2c. `--clean-ignored` — inverts ownership, breaks dry-run symmetry

Prefixes are only known *after* planning, and planning is where the refusal fires — so the flag must either delete
mid-plan (mutation inside a "read-only" phase) or re-plan after deleting (a two-phase mutate/replan the frozen-plan
design deliberately avoids). Under `--dry-run` it can only print, so the flag's dry-run and apply behaviour diverge
precisely where this codebase demands they not. And it hands a destructive verb to a tool whose entire posture is
fail-closed, to save the operator one command they can run and inspect themselves.

### 2d. Default-authorized globs (`__pycache__`, `.pytest_cache`, …) — wrong owner, attacker-nameable

`.gitignore` *is* the authoritative list, and it says these paths are not surface. A press-owned second list
(a) reopens §1's visibility flip for everything on it, (b) is attacker-nameable — put the payload in
`__pycache__/evil.pyc` and it is carried unexamined, (c) is a maintenance treadmill per ecosystem. The codebase's
precedent for suppressing a check is a **target-committed, occurrence-pinned, self-policing** ignore file
(`ignores.py:1-24`: "REFUSING to let a stale ignore mask a real leak"), not a hardcoded glob set.

## 3. Alternatives judged

- **Skip ignored nodes from the closure (leave them behind)** — breaks two things. (a) The move is one atomic
  `rename_noreplace` (`safety.py:704`, `545`); leaving children behind requires decomposing into per-child moves,
  destroying the atomic no-replacement design. (b) What is left behind
  (`src/demo_widget/__pycache__/demo_widget.cpython-313.pyc`) keeps the old directory non-empty (unremovable) and
  carries the source identity in both path and bytecode — the post-press verifier flags it as a leak.
- **`[[rename]] carry_ignored = true`** — config-owned opt-in fits `ignores.py`'s precedent, but §2a(ii) and §1
  apply regardless of who opts in. Safe only if scoped to regular files with a post-rename ignore-status re-check.
  That is a redesign, not a modification. Future work at most; not endorsed here.
- **Fail-closed with an actionable message (RECOMMENDED)** — keeps every invariant, costs the operator nothing
  beyond one command, and fixes the only genuine defect: the diagnostic tells you what is wrong and not what to do.

## 4. Exactly what to apply

1. In `_prefix_closure` (`substitutions.py:529-567`), **collect-then-raise** rather than raising on first hit.
   This is a real code change: accumulate uninventoried paths (and uninventoried empty directories) during the
   walk, then raise once after `walk(root)` at `substitutions.py:567` listing all of them (cap the printed list,
   e.g. first 20 + a count).
2. Append the remediation to the message, verbatim and runnable:
   `preview: git clean -ndX -- <source_prefix>` / `remove: git clean -fdX -- <source_prefix>`.
   **`-d` is required** — deleting only the `.pyc` files leaves an empty `__pycache__`, which then trips the
   separate empty-directory refusal at `substitutions.py:548-552`.
3. Keep the substring `absent from the authorized surface` so
   `tests/rebrand/test_substitution_safety.py:69` and `:107` pass unchanged.
4. No behaviour change: still `SafetyError`, still before any write, still no new flag, no default globs, no
   deletion by the press.

Docs touch: `docs/design/0009-substitution-table.md:345-352` and `:742` describe the refusal correctly; only the
diagnostic wording changes, so no ADR amendment is needed.

## 5. The one test that must exist

`test_prefix_closure_error_lists_every_ignored_descendant_and_offers_git_clean`: with **two** ignored untracked
files under `src/demo_widget` (via `_exclude_without_identity`, `test_substitution_safety.py:38`), `build_plan`
raises one `SafetyError` whose text contains **both** relative paths **and** the literal
`git clean -ndX -- src/demo_widget`. Guard against regression to first-hit-only reporting; the existing
single-file test at `:69` must still pass untouched.
