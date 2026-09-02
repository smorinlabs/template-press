# Adversarial review — proposed `[[clean]]` table (template-press v4.0.0)

**Verdict: APPLY MODIFIED. Confidence: medium-high (0.75).**

## 1. Steelman: do NOT add it
- **The outcome is already reachable.** The closure refusal fires at *plan* time
  (`build_plan` engine.py:841 → `_enrich_rename_plan` substitutions.py:571 →
  `_prefix_closure` substitutions.py:505); the `SafetyError` is caught at cli.py:365-372 →
  `_fail` → exit 2, nothing written. So `--dry-run` already names the blocker before any
  mutation, and a better diagnostic plus an operator-typed `git clean -fdX -- src/foo` closes
  the loop with zero engine surface.
- **First pre-snapshot mutation phase.** Every existing mutation runs after
  `capture_surface_snapshot` (inventory.py:903) and inside the stability brackets
  (`_capture_candidate` inventory.py:937; `snapshot_visibility_state` regen.py:743). Clean
  runs before any snapshot exists — structurally outside every guarantee the codebase buys.
- **Marginal attack surface: small but real.** `[[regenerate]]` already runs arbitrary argv
  (`execute_regenerations` regen.py:248; `subprocess.run([plan.executable, *rule.command[1:]], cwd=target)`
  regen.py:307) under the same deny-by-default env (`command_env` regen.py:116), so trust parity
  holds for *what* runs — not for *when*: regenerate runs after
  `check_preconditions` (cli.py:96) proved a clean tree and after the full plan gate; clean
  runs before all of it, on an unvalidated tree, with no receipt at stake.
- **The ignored-only invariant is a tripwire, not a guard** — the strongest objection. A
  one-character typo (`-fdx` for `-fdX`) deletes non-ignored untracked files; the comparison
  detects that *after* the deletion, and untracked files have no git recovery path. Calling
  it "enforced" is wrong. Related holes, all real: ignore status is path-based
  (`_ignored_directories` inventory.py:264 shells `check-ignore --no-index` with
  `core.excludesFile` pinned, inventory.py:148-149), so editing `.gitignore` changes what
  "ignored" means mid-flight; tracked-file *content* changes are invisible to
  `SurfaceSnapshot` — `SurfaceEntry` (inventory.py:33-40) carries rel/tracked/index_kind/
  worktree_kind and **no hash**; delete-and-recreate with identical content leaves snapshot and
  status identical; paths outside the target are unobserved; nested repos are handled only
  incidentally (inventory.py:864; `git clean` skips them absent `-ff`). Symlinks partly win: a
  swap of an *inventoried* path is a `worktree_kind` inequality (inventory.py:39) and downstream
  ops are no-follow (`_node_kind` substitutions.py:476, `assert_ancestors_real`), but an *ignored*
  path replaced by a symlink is the same detection-not-prevention class.

## 2. Attacking decisions 1-5
**D1 standalone subcommand — correct, keep.** Dry-run parity is a documented contract
(docs/source/reference/cli.md:39). Auto-invoking clean inside a non-dry-run `press rebrand` would
make the two modes observe different trees — exactly what the closure guard exists to make
impossible (`revalidate_rename_plan` substitutions.py:591 re-derives the closure before the first
move). Reject any "auto-clean when not --dry-run" variant.

**D2 structural ordering, no stamp — correct, keep.** A stamp lies the moment the operator
touches the tree after cleaning, and rebrand re-derives the closure live anyway
(substitutions.py:591). The confusing-failure case (pytest re-run after `press clean`) is
self-correcting: the refusal fires again and names `press clean` again. Note: `_prefix_closure`
has no access to `Rules`, so the "names `press clean` iff `[[clean]]` declared" enrichment
belongs at the cli.py:257-265 layer that holds `selected.rules`, not in substitutions.py.

**D3 before/after comparison — insufficient as described.** Full `SurfaceSnapshot` equality
catches index membership, untracked non-ignored add/remove, kind flips, ignore-policy inputs
and git-config fingerprints (`VisibilityInput` inventory.py:42, `GitConfigInput`
inventory.py:55, `git_config_effective_sha256` inventory.py:63). It does **not** catch
tracked-file content edits. Required mechanism: (1) whole-dataclass `capture_surface_snapshot`
equality; (2) `git status --porcelain -z` before/after equality — catches worktree content
edits; (3) the hidden-bit sweep `has_uncommitted_changes` uses (`ls-files -v` lowercase / `S`
first column, regen.py:380-390), since assume-unchanged hides edits from `status`; (4) reuse
`validate_visibility_state` regen.py:760 verbatim for the ignore/config/index half rather
than writing a second comparator. Content-hashing every tracked file is the honest maximum
but is O(repo) per clean; `status` + hidden-bit sweep is git's stat-cache-backed equivalent
and the right stopping point. Document it as detection, not prevention.

**D4 dry-run rendering — correct, cheap.** `_ignored_directories` inventory.py:264 already enumerates
ignored children; listing them per rename prefix plus `shlex.join(argv)` mirrors `render_regenerate_plan`
regen.py:342. Keep the "arbitrary commands cannot be previewed" caveat.

**D5 `{package_name}` from source identity — justified, with guards.** Decisive fact:
`press/press-rules.toml` is in `ROOT_CONTROL` and is excluded from content rewrite *and*
renames (`_excluded` inventory.py:996-1008, used by `select_content_rewrite_entries`
inventory.py:1021 and `select_rename_entries` inventory.py:1043). A literal
`src/template_press` therefore goes stale after the first press and the next
`git clean -- <path>` dies with "pathspec did not match". Guards: (a) refuse unknown
placeholder names at parse time — a typo'd `{pkg_nam}` must not pass through; (b) re-run
`_parse_regenerate`'s control-character/non-empty argv validation (rules.py:479-492) on the
*rendered* string; (c) do **not** apply `stale_argv_elements` (regen.py:159) to clean —
naming a rename-prefix path is clean's whole purpose, and clean runs pre-rename so the path
is live. State this explicitly; the two rules look contradictory side by side.

**`press verify`: skip by construction.** `make_sandbox` copies via `copy_paths` over
`select_copy_entries` (inventory.py:1011), which enumerates only inventoried entries — ignored
files are never copied, so the sandbox cannot hold a `__pycache__` for the closure guard to
trip on. Verify must neither run `[[clean]]` nor refuse rules whose executables are absent;
that would make a leak check depend on the operator's toolchain, against verify_cli.py:22-30
("a pure, repeatable observation, never a mutation").

**Receipt — weaken further.** Recording declared-but-unrun argv invites the reading that clean
ran. Omit it, or emit `[[press.clean]]` with explicit `ran = false`; contrast
`[[press.regenerate]]` receipt.py:92-98, which records *resolved* argv precisely because it ran.

**Exit codes.** Mirror cli.md:33-38. `0` = ran, invariant held. `2` = config/preconditions/
missing tool — **nothing ran**. `1` = a command ran and the invariant was violated, or the
command failed — the tree *was* mutated. The 1/2 split is load-bearing here in a way it is not
for regenerate: exit 1 means "an unauthorized mutation may have happened; inspect first".

**Windows — no new problem.** `COMMAND_ENV_BASE` regen.py:66-71 is platform-split and
`_parse_platforms` rules.py:419 lets a PowerShell variant be declared as press/press-rules.toml:14-19
does for `bun.lock`. **`check-tools` must cover clean** — check_tools.py:52-59 loops
`rules.regenerate` only, so a declared clean would fail at run time after a clean bill of health.

## 3. Alternatives
- **Restricted `[[clean]]` = path list, engine runs `git clean -X -- <paths>`.** Strictly safer:
  the invariant becomes structural (git's own `-X` semantics) instead of a tripwire, the typo
  class disappears, dry-run preview becomes exact, no new executable-resolution surface appears.
  Cost: cannot express `bun install`-style regeneration of an ignored tree, or a script. The
  motivating case is literally `__pycache__`, which this covers. **Ship this first.**
- **`[[regenerate]]`-like rule with `phase = "pre"`.** Rejected: re-imports the phase into
  `press rebrand`, breaking D1's dry-run parity; and `[[regenerate]]` is keyed on a tracked
  `file` output (rules.py:456-465) that clean does not have.
- **Skill/wrapper only.** Honest, but leaves the remedy undeclared and unreviewable — the
  ad-hoc state design 0006 §3 (docs/design/0006-external-target-model.md:30-56) pushes into
  declared config. Fine as the interim.

## 4. Verdict and minimal change set
**APPLY MODIFIED:** (1) ship the restricted path-list form (`[[clean]] paths = [...]` →
`git clean -fdX -- <rendered paths>`), not arbitrary argv — argv is a later, separately justified
increment; (2) keep D1, D2, D4 and D5's source-identity rendering with the three guards;
(3) replace D3's comparison with snapshot equality + `status --porcelain -z` + hidden-bit sweep,
documented as detection; (4) verify skips clean, receipt says `ran = false` or nothing.

**Engine change set (minimal)**
- rules.py: `CleanRule`, `_CLEAN_KEYS`, `_parse_clean` (reuse `_parse_platforms`
  rules.py:419), `Rules.clean`, `_select_rules` rules.py:822, `load_selected_rules` rules.py:851.
- new clean.py: `plan_clean`, `execute_clean`, `render_clean_plan`, `snapshot_clean_invariant` /
  `validate_clean_invariant` (wrapping `capture_surface_snapshot` inventory.py:903 + `validate_visibility_state` regen.py:760).
- press_cli.py:39-44 dispatch `clean`; new clean_cli.py (`--target`, `--dry-run`, exit 0/1/2).
- cli.py ~257-265: when `rules.clean` is non-empty, enrich the closure `SafetyError` with "run `press clean --target …` first".
- check_tools.py:52; receipt.py:88 (`[[press.clean]]`, `ran = false`); docs cli.md, 0006, 0009.

**Tests that must exist**
- tracked file deleted by clean → exit 1; tracked file *content edited* → exit 1 (this one
  fails today if only `SurfaceSnapshot` equality is compared).
- non-ignored untracked file added → exit 1.
- ignored add and ignored remove both → exit 0 (`node_modules` created, `__pycache__` deleted).
- `.gitignore` or repo config edited → exit 1 via `validate_visibility_state`.
- assume-unchanged-hidden edit → exit 1 (mirrors regen.py:380).
- `--dry-run` renders argv + ignored listing, mutates nothing, launches no subprocess.
- closure refusal names `press clean` iff `[[clean]]` declared — assert both directions.
- `press verify` exits 0 with `[[clean]]` declared and its executable absent; a `win32`-scoped clean rule is inert on darwin/linux.
- placeholders: `{package_name}` renders from SOURCE identity; an unknown placeholder is a parse-time `ValidationError`; a rendered control character is refused.
