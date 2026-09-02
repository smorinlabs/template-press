# E5 adversarial review — `[[remove]]` directories / globs (entries #6, #17)

**Verdict: APPLY MODIFIED** — ship the coverage warning + plan-time expansion count;
allow a `dir` form only under a plan-time-expansion-once contract; **reject globs**.
Confidence: high on the diagnosis, medium-high on the prescription.

## 0. Premise check — do this first

The entry's file list does not describe this repo. `git ls-files` finds **zero**
`research/`, `prototypes/`, `EXAMPLECLI.md`, `EXAMPLEWEB.md` paths. Those are
**py-launch-blueprint** paths — the downstream target P08 cites as evidence
(`projects/P08-declared-removal-and-exemption.md` References). What is real *here*:
`press/press-rules.toml` declares two `[[regenerate]]` rules and `[[reset]] CHANGELOG.md`
and **no `[[remove]]` at all**, so an R3 self-press rewrites `projects/P01..P08`,
`PROJECTS.md`, and `docs/research/0001..0005` into the fork's identity. The gap is real;
the cited inventory is borrowed — correct the entry before it drives work.

## 1. Steelman: single explicit `file` was the right v1

- **Declared, not discovered.** P08 T2 states it: "directories are out of scope for v1
  (the real targets are files)." Every guard in `remove.py:50-100` is per-path —
  `assert_under_root`, `assert_ancestors_real`, `is_regular_lstat` no-follow,
  git-tracked, and *clean even under `--allow-dirty`* (`remove.py:93-99`).
- **Fail-loud drift depends on 1:1.** `remove.py:76-84` treats a missing target as
  config drift, never a no-op. A glob matching nothing is indistinguishable from one
  whose files a prior press already deleted — the tri-state (`receipt.py:126-155`,
  `verify_cli.py:473-493`) collapses.
- **The receipt is per-declaration.** `cli.py:593-612` writes one `[[press.remove]]`
  row per `rule.file` in SOURCE coordinates with its reason; a pattern would record
  `"research/*"` and stop naming what was deleted.
- **The plan is the approval surface.** `remove.py:102-108` renders one
  `[remove ] <file> — <reason>` line — what `--dry-run` puts before the operator.
- The `os.path.normcase` argument (`rules.py:162-171`) is **weak**: `[[replace]]`
  already solved it with `fnmatchcase`, which `[[remove]]` would inherit.

## 2. Attacks on the proposal (severity order)

**A2.1 — Glob expansion straddles the rename boundary. This is the killer.**
`[[replace]] files` matches once, inside one scan pass, in one coordinate system
(`rules.py:162-173`). `[[remove]]` does not: declarations are SOURCE coordinates,
preflight runs pre-`apply()` (`cli.py:313-317`), execution runs post-rename through
`translate_path(rule.file, renamed)` (`remove.py:143`). A glob re-expanded at apply time
expands against a *renamed* tree, matching files the plan never showed. Any multi-path
form must expand **exactly once, at plan time, over `tracked_paths()` — the git index,
never the filesystem** — freeze that list into the rule, and translate each frozen path.
The proposal's "`fnmatch` like `[[replace]] files`" wording does not say this.

**A2.2 — Blast-radius amplification on partial failure.** `apply_removals`
(`remove.py:133-163`) unlinks in a loop and raises `SafetyError` mid-loop on a missing
or non-regular target. Today that strands at most N declared files; a directory form
strands an arbitrary subtree, with no receipt and no printed recovery command. A `dir`
form must name the undo (`git checkout -- <dir>`) on that path, or unlink last.

**A2.3 — The receipt stops listing every removed path.** `removed_files_from_receipt`
(`receipt.py:126-155`) would return patterns, and the "satisfied by a prior press"
comparisons at `remove.py:78`, `cli.py:602-603`, and `verify_cli.py:488` would compare a
*pattern* against a *path set*. Plan-time expansion (A2.1) fixes this for free.

**A2.4 — `verify` re-derives the removal set independently.** `verify_cli.py:473-493`
loops `rules.remove` inside the sandbox; a pattern makes that a *second, independent*
expansion over a synthesized-identity tree, and divergence is silent, not an error.
Verify must consume the receipt's expanded set instead.

**A2.5 — Empty directories are never cleaned.** `apply_removals` calls `os.unlink` only
(`remove.py:161`), so an emptied `research/` remains; git reports clean (it tracks no
directories) while the operator sees the shell of the template's history. A `dir` form
must `rmdir` what it emptied, and refuse when untracked operator files remain inside.

**A2.6 — Gitlinks and non-regular entries inside a subtree.** The inventory tags
`gitlink` as its own `IndexKind` (`inventory.py:28,371,986-992`). Subtree removal must
enumerate from the index and **hard-refuse** a subtree containing a gitlink or symlink
rather than skipping it: `unlink` on a submodule corrupts index/`.gitmodules` state, and
`.gitmodules` is already an explicit `[[remove]]` refusal (`rules.py:620-626`).

**A2.7 — "Should remove run before replace?" No.** `apply()` revalidates the tree
against its plan-time snapshot at the mutation boundary (`cli.py:445-462`,
`engine.py:299-306`), so deleting first breaks that contract — stated in
`remove.py:14-19` and P08 T2. Rewriting a doomed file only wastes CPU. (`[[reset]]`
requires `exclude_files` membership because its outcome *is* order-dependent,
`rules.py:574-580`; removal's is not — the file is gone either way.)

**A2.8 — Severity is overstated.** A rewritten `projects/P05-reset-rule.md` does **not**
leak: verify and the doctor pass, `preflight_excluded_files` (`regen.py:448-479`) is
satisfied, R3 is green. The invariant is "no source identity survives"; shipping
template project history under a new name violates *editorial curation*, not that
invariant. Medium, not high — a target-authoring defect before an engine defect.

## 3. Alternatives, ranked

1. **Declared-removal coverage warning (best value/risk).** `regen.py:448-479` already
   fails loud for *excluded* files with no neutralization. Add a **non-fatal** sibling
   listing tracked directories the plan rewrites entirely and no rule removes or resets:
   "N tracked files under `<dir>` will be rewritten to the new identity; declare
   `[[remove]]` or `[rules] verify_ignore` if this is template history." No new
   destructive surface, no schema change, catches the reported miss.
2. **Plan-time expansion count.** `render_remove_plan` (`remove.py:102-108`) renders the
   frozen expanded list under a header (`removing 8 files under research/`). Mandatory
   if any multi-path form lands — widening must be visible at approval time.
3. **Explicit `dir = "research"` key, separate from `file`, mandatory `reason`.**
   Acceptable only with all six: plan-time expansion over `tracked_paths()` frozen into
   the rule; per-directory clean check (`git status --porcelain -- <dir>` also surfaces
   `??` untracked operator files → refuse); gitlink/symlink hard-refusal; `rmdir` of
   emptied directories; expanded paths in the receipt; verify reading that expanded set.
4. **Bare `fnmatch` globs on `file` — reject.** They buy nothing the `dir` form does not
   and silently widen as the template grows — the exact failure single paths prevent.

## 4. Verdict

**APPLY MODIFIED.** (a) Ship alternatives 1 and 2 now. (b) Treat alternative 3 as its
own project with the six constraints — not a patch to `_parse_remove` (`rules.py:606`).
(c) Reject globs. (d) Independently, declare the missing removals for `projects/` and
`docs/research/` in this repo's `press/press-rules.toml` — the concrete reported gap
needs no engine change at all.

**The one test that must exist** (`tests/rebrand/test_remove_rules.py`): a press
declaring a multi-path removal where an active `[[replace]]` rule renames a file *into*
that removal's expansion between plan and apply. Assert the unlinked set equals exactly
the set rendered in the `--dry-run` plan, and that the receipt's `[[press.remove]]` rows
name each path individually — frozen plan-time expansion passes, apply-time re-expansion
fails. Second priority: a mid-removal `SafetyError` leaves no receipt and prints the git
undo path.
