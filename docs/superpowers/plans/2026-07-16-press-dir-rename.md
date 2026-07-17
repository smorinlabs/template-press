# Press control-file rename (`.press/` → `press/press-*`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: COMPLETE (2026-07-16)** — implemented and merged as `P03-M4b`. The unchecked `- [ ]` boxes below are the plan exactly as authored (a pre-execution record); they are not open work.

**Goal:** Rename the per-target press control files from the hidden
`.press/{source,rules,receipt}.toml` to a visible, uniquely-greppable
`press/press-{source,rules,receipt}.toml`, and adopt `press-answers.toml`
(plus a committed `press/press-answers.example.toml`) as the answers-file
convention.

**Architecture:** The whole convention is driven by three `*_REL` path
constants and one `exclude_dirs` entry, all read through
`target / <CONST>`. Change the constants + the exclusion, update the
human-visible strings that hardcode the old paths, then fan the rename out
to tests and docs. Clean break — no `.press/` fallback.

**Tech Stack:** Python 3.12+, uv, pytest, ruff, ty; lefthook hooks +
commitlint; release-please for versioning.

## Global Constraints

- New file contract (exact): `<target>/press/press-source.toml`,
  `<target>/press/press-rules.toml`, `<target>/press/press-receipt.toml`.
- Answers file: recommended name `press-answers.toml`, passed via the
  unchanged, still-required `--config` (no default lookup, no fallback).
  Committed shape template `press/press-answers.example.toml` is a
  documentation convention only — the tool never generates it.
- Clean break: recognize only the new names; no `.press/` fallback code.
- TOML table names unchanged: `[identity]`, `[answers]`, `[rules]`,
  `[press]`.
- Line length 88; strict typing; ruff lint+format; `just check` must pass.
- After ANY change under `src/template_press/rebrand/`, run `just matrix`
  (R1/R2/R3 live acceptance matrix) — mandatory.
- Commit convention: Conventional Commits, lowercase subject. The
  behavioral commit is a breaking change — use `feat!:` with a
  `BREAKING CHANGE:` footer so release-please cuts 2.1.1 → 3.0.0. Never
  hand-edit `version` in `pyproject.toml`.
- Verification gate for the rename: `grep -rnE '\.press(/|")'` over
  `src/` and `tests/` must return zero hits (note: `template_press` and
  `press_cli` contain `_press`/`.press_cli`, NOT `.press/` or `".press"`,
  so they never match this pattern).

---

## File Structure

Files touched, by responsibility:

- `src/template_press/rebrand/config.py` — `SOURCE_CONFIG_REL` constant +
  source-config rendered header + module docstring.
- `src/template_press/rebrand/rules.py` — `RULES_REL` constant +
  `DEFAULT_RULES.exclude_dirs` entry + docstrings.
- `src/template_press/rebrand/receipt.py` — `RECEIPT_REL` constant +
  receipt rendered header.
- `src/template_press/rebrand/cli.py` — one hardcoded receipt-path message.
- `src/template_press/rebrand/doctor.py` — one leak-report hint string.
- `tests/rebrand/test_config.py`, `test_rules.py`, `test_cli.py`,
  `test_matrix.py` — fixtures that hardcode `.press` mkdir + `rules.toml`.
  (`test_receipt.py` and `test_press_cli.py` need no edits — they use the
  `RECEIPT_REL` constant / do not reference the dir.)
- Docs: `README.md`, `AGENTS.md`, `docs/design/0006-external-target-model.md`,
  `docs/source/index.md`, `docs/source/reference/cli.md`,
  `.claude/skills/press-target/SKILL.md`.
- Tracking: `projects/P03-external-target-rebrand-press-.md`.

---

## Task 1: Rename the source + tests (behavioral)

**Files:**
- Modify: `src/template_press/rebrand/config.py` (L3, L15, L56)
- Modify: `src/template_press/rebrand/rules.py` (L5, L16, L36, L70)
- Modify: `src/template_press/rebrand/receipt.py` (L17, L40)
- Modify: `src/template_press/rebrand/cli.py` (L44)
- Modify: `src/template_press/rebrand/doctor.py` (L94)
- Test: `tests/rebrand/test_config.py` (L19, L60),
  `tests/rebrand/test_rules.py` (L8, L18, L20, L39, L41, L53, L55),
  `tests/rebrand/test_cli.py` (L16, L67, L134, L135, L150, L281, L326,
  L342, L418, L419), `tests/rebrand/test_matrix.py` (L59)

**Interfaces:**
- Produces (later tasks + docs rely on these exact values):
  - `SOURCE_CONFIG_REL == Path("press") / "press-source.toml"`
  - `RULES_REL == Path("press") / "press-rules.toml"`
  - `RECEIPT_REL == Path("press") / "press-receipt.toml"`
  - `"press" in DEFAULT_RULES.exclude_dirs` (was `".press"`)

- [ ] **Step 1: Update the test fixtures to the new names (this is the failing test)**

The tests hardcode the old dir/file; point them at the new ones. Run these
scoped replacements (safe — `".press"` and `"rules.toml"` appear only as
these fixture literals in the test files):

```bash
cd "$(git rev-parse --show-toplevel)"
# dir literal .press -> press (test_config, test_rules, test_cli, test_matrix)
sed -i '' 's/"\.press"/"press"/g' \
  tests/rebrand/test_config.py tests/rebrand/test_rules.py \
  tests/rebrand/test_cli.py tests/rebrand/test_matrix.py
# rules fixture filename rules.toml -> press-rules.toml (test_rules, test_cli)
sed -i '' 's#/ "rules\.toml"#/ "press-rules.toml"#g' \
  tests/rebrand/test_rules.py tests/rebrand/test_cli.py
```

Verify the intended lines changed (spot-check):

```bash
grep -n '"press"' tests/rebrand/test_rules.py        # L8, L18, L39, L53
grep -n 'press-rules.toml' tests/rebrand/test_cli.py # L135, L326, L342, L419
```

Expected: `test_rules.py:8` now reads `assert "press" in DEFAULT_RULES.exclude_dirs`; fixture dirs read `tmp_path / "press"`; rules fixtures read `press / "press-rules.toml"`.

- [ ] **Step 2: Run the rebrand tests to confirm they now FAIL**

Run: `uv run pytest tests/rebrand/ -q`
Expected: FAIL. `test_rules.py` fails on the exclusion assertion (code still
has `.press`); the fixture-writing tests fail because they `mkdir("press")`
but the code writes/reads `RULES_REL`/`SOURCE_CONFIG_REL` under `.press`.

- [ ] **Step 3: Change the three path constants + the exclusion**

Apply these exact edits:

`src/template_press/rebrand/config.py:15`
```python
SOURCE_CONFIG_REL = Path("press") / "press-source.toml"
```

`src/template_press/rebrand/rules.py:16`
```python
RULES_REL = Path("press") / "press-rules.toml"
```

`src/template_press/rebrand/rules.py:36` — inside `DEFAULT_RULES.exclude_dirs`, replace the `".press",` entry with:
```python
            "press",
```

`src/template_press/rebrand/receipt.py:17`
```python
RECEIPT_REL = Path("press") / "press-receipt.toml"
```

- [ ] **Step 4: Update the human-visible strings that hardcode the old paths**

These are in the same five source files. Run scoped replacements over the
rebrand package (matches only literal `.press/<name>.toml` path strings; the
constants are already changed in Step 3):

```bash
cd "$(git rev-parse --show-toplevel)"
sed -i '' \
  -e 's#\.press/source\.toml#press/press-source.toml#g' \
  -e 's#\.press/rules\.toml#press/press-rules.toml#g' \
  -e 's#\.press/receipt\.toml#press/press-receipt.toml#g' \
  src/template_press/rebrand/config.py \
  src/template_press/rebrand/rules.py \
  src/template_press/rebrand/receipt.py \
  src/template_press/rebrand/cli.py \
  src/template_press/rebrand/doctor.py
```

This updates: config.py L3 docstring + L56 rendered header; rules.py L5 +
L70 docstrings; receipt.py L40 rendered header; cli.py L44 receipt message;
doctor.py L94 hint.

- [ ] **Step 5: Verify no old path strings remain in src**

Run: `grep -rnE '\.press(/|")' src/template_press/`
Expected: no output (zero hits).

- [ ] **Step 6: Run the rebrand tests to confirm they PASS**

Run: `uv run pytest tests/rebrand/ -q`
Expected: PASS (all green).

- [ ] **Step 7: Confirm no old references remain in tests either**

Run: `grep -rnE '\.press(/|")' tests/`
Expected: no output.

- [ ] **Step 8: Full checks + live acceptance matrix**

Run: `just check`
Expected: format/lint/typecheck/test all pass.

Run: `just matrix`
Expected: R1/R2/R3 pass — a dry-run/apply against a fresh blueprint clone
now writes and reads `press/press-source.toml` and
`press/press-receipt.toml`. (Mandatory after any `rebrand/` change.)

- [ ] **Step 9: Commit (breaking change)**

```bash
git add src/template_press/rebrand/ tests/rebrand/
git commit -m "feat!: rename press control dir to press/ with press- prefix

Move per-target control files from .press/{source,rules,receipt}.toml to
press/press-{source,rules,receipt}.toml — a visible directory and uniquely
greppable filenames for humans and agents. Clean break, no fallback.

BREAKING CHANGE: targets pressed under .press/ read as unpressed until their
directory is renamed (git mv .press press + rename the three files)."
```

---

## Task 2: Docs + answers-file convention

**Files:**
- Modify: `README.md` (L36, L39, L42, L55)
- Modify: `AGENTS.md` (L41, L128)
- Modify: `docs/design/0006-external-target-model.md` (L26, L32, L35, L37, L38)
- Modify: `docs/source/index.md` (L31, L32, L35, L50)
- Modify: `docs/source/reference/cli.md` (L12, L23, L24, L46, L53, L54, L56)
- Modify: `.claude/skills/press-target/SKILL.md` (L19, L21, L31, L34, L36)

**Interfaces:**
- Consumes: the constant values from Task 1 (documents the new paths).

- [ ] **Step 1: Rewrite the old paths in all live docs**

Run the same path replacements over the doc set, plus the answers-file
name (`answers.toml` → `press-answers.toml`) and its angle-bracket
placeholder forms:

```bash
cd "$(git rev-parse --show-toplevel)"
DOCS="README.md AGENTS.md docs/design/0006-external-target-model.md \
docs/source/index.md docs/source/reference/cli.md \
.claude/skills/press-target/SKILL.md"
sed -i '' \
  -e 's#\.press/source\.toml#press/press-source.toml#g' \
  -e 's#\.press/rules\.toml#press/press-rules.toml#g' \
  -e 's#\.press/receipt\.toml#press/press-receipt.toml#g' \
  -e 's#`\.press/`#`press/`#g' \
  -e 's#<answers\.toml>#<press-answers.toml>#g' \
  -e 's#<ANSWERS\.toml>#<press-answers.toml>#g' \
  -e 's#--config answers\.toml#--config press-answers.toml#g' \
  -e 's#`answers\.toml`#`press-answers.toml`#g' \
  $DOCS
```

- [ ] **Step 2: Verify the path/name sweep landed and nothing stale remains**

Run: `grep -rnE '\.press(/|`)|(^|[^[:alnum:]_-])answers\.toml([^[:alnum:]_.-]|$)' README.md AGENTS.md docs/design/0006-external-target-model.md docs/source/index.md docs/source/reference/cli.md .claude/skills/press-target/SKILL.md`
Expected: no output. (Any remaining hit is a form the sed missed — fix it by hand to the `press/press-*` / `press-answers.toml` equivalent.)

- [ ] **Step 3: Document the `press-answers.example.toml` convention**

In `.claude/skills/press-target/SKILL.md`, in the step that currently tells
the operator to supply `--config press-answers.toml` (was L19), add the
copy-and-fill convention. Insert after that line:

```markdown
   If the target ships a `press/press-answers.example.toml` template, copy it
   first and fill in the destination identity:
   `cp <TARGET>/press/press-answers.example.toml press-answers.toml`
```

In `README.md`, right after the sentence introducing `press-answers.toml`
(was L42), add the example-file note and a shape sample:

````markdown
Keep your filled-in `press-answers.toml` out of the target (it is transient
operator input, not committed state). A repo may commit a
`press/press-answers.example.toml` placeholder to advertise the field
shape — copy it, fill it, and pass it via `--config`:

```toml
[answers]
package_name = "my_package"
repo_name    = "my-repo"
app_name     = "my-app"
author       = "Your Name"
email        = "you@example.com"
owner        = "your-gh-owner"
```
````

- [ ] **Step 4: Review design 0001 (no change expected)**

Run: `grep -n '\.press' docs/design/0001-press-cli-conventions.md`
`docs/design/0001` L87 references a superseded `./press_config.toml` /
`./.press_config.toml` config-precedence idea — a different, pre-0006
concept, NOT the `.press/` file contract this plan renames. Leave it as-is
(historical/superseded). No edit.

- [ ] **Step 5: Verify docs build / render**

Run: `grep -rnE 'press/press-(source|rules|receipt|answers)' README.md docs/`
Expected: the new paths appear. Eyeball `docs/source/reference/cli.md` and
`.claude/skills/press-target/SKILL.md` to confirm sentences still read
correctly (e.g. "refreshes `<target>/press/press-source.toml`").

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md docs/design/0006-external-target-model.md \
  docs/source/index.md docs/source/reference/cli.md \
  .claude/skills/press-target/SKILL.md
git commit -m "docs: adopt press/press-* paths and press-answers.toml convention"
```

---

## Task 3: Update P03 tracking + final verification

**Files:**
- Modify: `projects/P03-external-target-rebrand-press-.md` (L33, L50; add one task row)

**Interfaces:**
- Consumes: completion status of Tasks 1–2.

- [ ] **Step 1: Fix the two stale path references in the P03 tracking file**

`projects/P03-external-target-rebrand-press-.md` L33 and L50 both reference
`.press/rules.toml` in prose describing the verify_ignore mechanism. Update
both to the new path:

```bash
cd "$(git rev-parse --show-toplevel)"
sed -i '' 's#\.press/rules\.toml#press/press-rules.toml#g' \
  projects/P03-external-target-rebrand-press-.md
```

- [ ] **Step 2: Add a completed task row for this rename**

In `projects/P03-external-target-rebrand-press-.md`, in the `### Tests &
Tasks` list, add a row immediately after the `[P03-M4]` row:

```markdown
- [x] [P03-M4b] Rename press control dir to `press/` + `press-` file
      prefix (visible, uniquely greppable); `press-answers.toml` +
      `press/press-answers.example.toml` convention. Breaking (v3.0.0).
```

- [ ] **Step 3: Confirm the tracking edit is consistent**

Run: `grep -nE '\.press/|P03-M4b' projects/P03-external-target-rebrand-press-.md`
Expected: the `P03-M4b` row is present; no `.press/` path strings remain.

- [ ] **Step 4: Final full-pipeline + matrix gate**

Run: `just check`
Expected: all pass.

Run: `just matrix`
Expected: R1/R2/R3 pass.

Run: `grep -rnE '\.press(/|")' src/ tests/`
Expected: no output (final proof the rename is complete).

- [ ] **Step 5: Commit**

```bash
git add projects/P03-external-target-rebrand-press-.md
git commit -m "docs(projects): record P03-M4b press dir rename"
```

- [ ] **Step 6: Branch handoff**

Implementation complete on `feat/press-dir-rename`. Hand off to
`superpowers:finishing-a-development-branch` to open the PR (a `feat!:`
breaking change → release-please will propose 3.0.0 on merge).

---

## Self-Review

**Spec coverage:**
- New three-file contract → Task 1 (constants) + Task 2/3 (docs, tracking). ✅
- `exclude_dirs` `.press`→`press` (rewrite + doctor exemption) → Task 1 Step 3. ✅
- Rendered header comments written into targets → Task 1 Step 4 (config.py L56, receipt.py L40). ✅
- CLI/doctor messages → Task 1 Step 4 (cli.py L44, doctor.py L94). ✅
- Tests (test_config/rules/cli/matrix; receipt/press_cli untouched) → Task 1. ✅
- Answers `press-answers.toml` name + `press-answers.example.toml` doc-only convention → Task 2 Steps 1, 3; Out-of-scope (no codegen) respected. ✅
- Clean break, no fallback → no fallback code added anywhere. ✅
- Live docs updated, historical plans untouched (only 0006/README/AGENTS/sphinx/skill/P03 edited; `docs/superpowers/plans/*` and design 0001 left) → Tasks 2–3. ✅
- Breaking-change release (2.1.1→3.0.0, no hand-edit) → Task 1 Step 9 `feat!:` + footer. ✅
- Accepted risk (a target dir literally named `press` is skipped) → inherent to the constant change; documented in the spec, no code action. ✅

**Placeholder scan:** No TBD/TODO; every edit shows exact strings/commands. ✅

**Type consistency:** Constant names (`SOURCE_CONFIG_REL`, `RULES_REL`,
`RECEIPT_REL`) and values match across Task 1 interfaces, Task 2 docs, and
Task 3. ✅
