# BAML Targets and Glued-Name Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repositories that use BAML (Python or TypeScript host) first-class `template-press` targets with whole-directory client regeneration, `{package_name}` regeneration paths, `display_name_pascal` substring rewriting, and undeclared tracked BAML client refusal — while closing the general glued-name false receipt across all target languages.

**Architecture:** Extend the pre-write keep-name preflight (`keep_names.check_keep_surfaces` / `substitutions.check_target_keep_names`) to scan the exact changed field set `press verify` scans (sharing field selection through `verify_config.py` and `verifier.py` without breaking design-0008 module independence). Allow `display_name_pascal` in `substring_rewrite_fields` consistently across rules, substitutions, doctor, regen, and verifier. Add `{package_name}` path rendering for `[[regenerate]]` and `extra_exclude_files`, add `RegenerateDirRule` (`[[regenerate]] dir`) paralleling `RemoveDirRule`, refuse undeclared tracked `baml_client/inlinedbaml.{py,ts}` before writing, and prove everything with synthetic fixtures plus gated live `baml-cli` acceptance tests.

**Tech Stack:** Python 3.13 standard library (`tomllib`, `re`, `dataclasses`, `subprocess`, `shutil`, `pathlib`), pytest, uv, just, `baml-cli` 0.226.3 (live acceptance only).

**Spec:** `docs/superpowers/specs/2026-11-25-baml-targets-design.md`

**Project:** `projects/P19-baml-targets.md` (P19)

## Global Constraints

- Zero runtime dependencies (stdlib only in `src/template_press/`).
- Safety contract unchanged: config-first identity, discovery cross-check, verify-then-mark, exit codes `0` / `1` / `2`, no receipt on leaks or failures.
- Module independence (design 0008, enforced by `tests/rebrand/test_verifier_independence.py`): neither `verifier.py` nor `keep_names.py` may import `substitutions`, `engine`, or `doctor`, directly or transitively.
- `Rules` dataclass positional safety: any new field on `Rules` (such as `regenerate_dirs`) is appended LAST with a default value.
- No `baml` value in `[rules] languages` (Decision 5); no built-in/hidden BAML commands; `press verify` never runs external commands.
- Public repository: synthetic `example.test` fixtures only. No private repository names, hostnames, or account details in code, commits, docs, or PR text.
- Line length 88, strict typing on all functions in `src/template_press/`, Conventional Commits with lowercase subjects.
- Run `uv run ruff format --check .` before committing Markdown files with Python code fences, and run `just check` and `just matrix` after changes to `src/template_press/rebrand/`.

## Builder Decisions

These settle the four items left to the builder in `docs/superpowers/specs/2026-11-25-baml-targets-design.md`:

1. **Sharing the paranoid verify field set without breaking module independence.**
   Keep the import DAG strictly acyclic and below `substitutions`/`engine`/`doctor`:
   `identity` -> `matcher` -> `keep_names` -> `verifier` -> `ignores` -> `verify_config` -> (`substitutions`, `cli`, `verify_cli`).
   - Promote `_load_verify_config` from `verify_cli.py` to `verify_config.load_verify_config(target: Path) -> VerifyConfig`.
   - Add `effective_verify_fields(source: Identity, cfg: VerifyConfig, substring_rewrite_fields: Collection[str]) -> tuple[tuple[str, ...], frozenset[str]]` in `verify_config.py`.
   - Expose `changed_verify_fields(source: Identity, dest: Identity, fields: Sequence[str], substring_fields: Collection[str]) -> list[tuple[str, str]]` from `verifier.py` (replacing private `_changed_fields`).
   - Keep `keep_names.py` neutral (imports only stdlib, `identity`, `matcher`). `check_keep_surfaces` accepts optional `glued_fields: Sequence[tuple[str, str]] = ()` and `glued_substring_fields: Collection[str] = ()`.
   - `substitutions.check_target_keep_names` calls `verify_config.effective_verify_fields` and `verifier.changed_verify_fields`, skips `rules.verify_ignore` components, `[[regenerate]] dir` trees, `[[remove]]` targets, `exclude_files`, and `exclude_dirs`, and filters candidate core-field glued findings through `ignores.apply_ignores` in source coordinates (using identity `forward_map = lambda p: p` and a cached source-line reader, ignoring stale ignores because an ignore may cover a binary or symlink finding only `press verify` sees).

2. **Exact receipt fields for a `[[regenerate]] dir` entry.**
   Add `[[press.regenerate_dir]]` rows to `receipt.py` (paralleling `[[press.remove_dir]]`), recording destination directory, rendered source directory, pinned argv, and optional reason:

   ```toml
   [[press.regenerate_dir]]
   dir = "src/zeta_tool/baml_client"
   source_dir = "src/acme_widget/baml_client"
   argv = ["/abs/path/to/uv", "run", "--offline", "baml-cli", "generate"]
   reason = "BAML client, rebuilt from baml_src"
   ```

   (`reason` is written when `verify_exempt = true` and omitted otherwise). `[press.counts] regenerated` counts both file and directory regenerations. When `verify_exempt = true`, `[[press.exempt]]` records `dir = "<dest_dir>"` and `reason = "<reason>"` (leaving existing `file = ...` rows unchanged). In `press verify --json`, directory exemptions appear in `exempt` as `{"dir": "<source_dir>", "reason": "<reason>"}` and in human output as `not verified (exempt): <source_dir>/ — <reason>`.

3. **Absent or wholly gitignored client directory.**
   - **Tracked directory:** must exist as a real directory at plan time with no symlinks, junctions, gitlinks, embedded `.git`, Git visibility inputs (`.gitignore`/`.gitattributes`/`.gitmodules`), dirty tracked files, or unignored untracked files (refused even under `--allow-dirty`). After `apply()`, press deletes the directory at its pressed location, runs the declared command, requires the directory to exist afterward, and scans every produced file.
   - **Absent directory** (fresh clone of a gitignored-client repo or post-`press clean`): accepted at plan time (nothing uncommitted to destroy); after `apply()`, the declared command creates it at the pressed destination path and every produced file is verified and scanned.
   - **Wholly gitignored directory present on disk** (zero tracked files, zero unignored untracked files): if inside a renamed parent directory (e.g. `src/acme_widget/baml_client`), the existing E2 rename-closure guard refuses before writing and directs the operator to `press clean` (`[[clean]] paths = ["src/{package_name}/baml_client"]`), after which it follows the absent-directory path; if outside any renamed parent (e.g. root `baml_client/`), preflight validates no symlinks/junctions/embedded `.git`/visibility inputs/unignored untracked files, then deletes and rebuilds it in place. Both paths are tested explicitly in Task 4 and documented in Task 7.

4. **Ordering of the glued-name preflight and guidance wording.**
   Existing exact-name checks (`npm_name`, `cli_name`, `cargo_*`, plus manifest dependency checks) run first on each surface, followed by core verify-field glued-name checks, deduplicated by `(path, where, token)` so an exact-name field keeps its exact-name diagnostic when it shares a value with a core field.
   - Core-field glued-name refusal format matches Decision 1:

     ```text
     error: baml_src/main.baml: AcmeWidgetClient extends display_name "Acme Widget"
       rewrite it:  substring_rewrite_fields = ["display_name_pascal"]
       or keep it:  keep_names = ["AcmeWidgetClient"]
     ```

   - Print `  rewrite it:  substring_rewrite_fields = ["<field>"]` only when an allowed `substring_rewrite_fields` entry exists whose literal source spelling would rewrite that occurrence (e.g. `"display_name_pascal"` when `display_forms(source.display_name)["pascal"]` occurs in the token; `"app_name"` when `source.app_name` occurs in the token; never for `display_name_camel` or case-mismatched spellings).
   - Print `  or keep it:` (or `  keep it:` when no rewrite option applies) only when `validate_keep_names` accepts the token; otherwise explain that the token equals or contains a source identity value and must be renamed or handled with `[[replace]]`.

## Review Focus

1. **Scope (i) invariant:** Any target where pre-press `press verify` exits 0 must never be refused by the new glued-name preflight (verified by the fixture-corpus property test in Task 1).
2. **Module independence:** `tests/rebrand/test_verifier_independence.py` must pass and additionally assert `keep_names` cannot import `substitutions`, `engine`, `doctor`, `verifier`, or `verify_config` (Task 1).
3. **`display_name_pascal` parity:** Validation, rewrite, pipeline validator, doctor, regeneration scan, and `verifier.scan` must all agree on `display_name_pascal`, while bare `display_name` and `display_name_camel` stay rejected (Task 2).
4. **Repeat press with `{package_name}`:** Pressing `acme_widget` -> `zeta_tool` -> `nova_app` must resolve `src/{package_name}/baml_client` in both source and destination coordinates without editing `press/press-rules.toml` (Tasks 3, 4, 6).
5. **No stale generated files or symlink escapes in `[[regenerate]] dir`:** The directory is deleted before the command runs (using no-follow containment guards), re-checked after the command for symlinks/gitlinks/non-UTF-8/leaks, and re-checked in `final_validation_pass` (Task 4).
6. **Undeclared BAML client refusal:** Tracked `baml_client/inlinedbaml.py` or `.ts` at any depth exits 2 with zero writes unless covered by `[[regenerate]] dir`, `[[regenerate]] file`, or `[[remove]]`; gitignored clients are not refused (Task 5).
7. **Existing test impact:** Check whether any existing test intentionally plants a glued core-field token expecting `apply()` to proceed; only update tests whose premise was the pre-P19 false-receipt behavior, never weaken Scope (i) (Task 1).

---

### Task 1: Glued-name preflight across all target languages (P19-TS01, P19-T01)

**Files:**
- Modify: `src/template_press/rebrand/verify_config.py`, `src/template_press/rebrand/verifier.py`, `src/template_press/rebrand/keep_names.py`, `src/template_press/rebrand/substitutions.py`, `src/template_press/rebrand/cli.py`, `src/template_press/rebrand/verify_cli.py`
- Create: `tests/rebrand/test_glued_name_preflight.py`
- Modify: `tests/rebrand/test_verifier_independence.py`, `tests/rebrand/test_keep_names.py`

**Interfaces:**
- Produces:
  - `verify_config.load_verify_config(target: Path) -> VerifyConfig`
  - `verify_config.effective_verify_fields(source: Identity, cfg: VerifyConfig, substring_rewrite_fields: Collection[str]) -> tuple[tuple[str, ...], frozenset[str]]`
  - `verifier.changed_verify_fields(source: Identity, dest: Identity, fields: Sequence[str], substring_fields: Collection[str]) -> list[tuple[str, str]]`
  - Extended `UndeclaredName` carrying optional `value: str = ""`, `line: int | None = None`, `col: int | None = None`, `kind: str = "exact"` (`"exact"` | `"glued"`)
  - Extended `check_keep_surfaces(..., glued_fields=..., glued_substring_fields=...)` and `check_target_keep_names(..., verify_config=...)`
  - Updated `render_undeclared(findings, source)` emitting Decision 1's rewrite/keep guidance for glued findings

- [ ] **Step 1 (`P19-TS01`): Write failing tests** in `tests/rebrand/test_glued_name_preflight.py` and `tests/rebrand/test_verifier_independence.py`:
  - Glued old name refused before any write (exit 1, `git status --porcelain` empty, no receipt) across four synthetic targets:
    - Python (`class AcmeWidgetConfig:` with `display_name = "Acme Widget"` and `acmeConfig` with `app_name = "acme"`)
    - TypeScript (`const acmeConfig = 1;` in `src/index.ts`)
    - Rust (`struct AcmeWidgetClient;` in `src/lib.rs`)
    - BAML (`client<llm> AcmeWidgetClient` in `baml_src/main.baml`)
  - Source-form gap from P17: `_zapp_` for source `app_name = "zapp"` exits 1 before writing.
  - Refusal output tests:
    - `AcmeWidgetClient` prints `baml_src/main.baml: AcmeWidgetClient extends display_name "Acme Widget"`, `rewrite it:  substring_rewrite_fields = ["display_name_pascal"]`, and `or keep it:  keep_names = ["AcmeWidgetClient"]`.
    - `acmeWidgetClient` (camelCase, no allowed substring field) omits the `rewrite it:` line and prints only the keep fix.
    - A glued token that `validate_keep_names` rejects prints no invalid `keep_names = [...]` suggestion.
  - Negative cases (must NOT be refused by this check):
    - Glued token rewritten by `substring_rewrite_fields` (e.g. `app_name` in `substring_rewrite_fields` with `acmeConfig`) or by a `[[replace]]` rule.
    - Glued token covered by `keep_names`.
    - Glued token covered by `[[verify.ignore]]` (line/anchor/ordinal) or `[rules] verify_ignore`.
    - Unrelated word (`pressure` for `app_name = "press"`).
    - File excluded by `exclude_files`, `exclude_dirs`, `[[remove]]`, or `[[regenerate]]`.
    - Unchanged field between `source` and `dest`.
  - Property test over the synthetic fixture corpus (Python, Node/TS, Rust, and clean BAML fixtures): wherever pre-press `press verify` exits 0, `check_target_keep_names` returns zero undeclared findings.
  - In `tests/rebrand/test_verifier_independence.py`, add `test_keep_names_import_closure_excludes_forbidden_modules` asserting `_transitive_imports(f"{PACKAGE}.keep_names")` is disjoint from `FORBIDDEN | {f"{PACKAGE}.verifier", f"{PACKAGE}.verify_config"}`.
- [ ] **Step 2: Run tests to verify they fail.**
  Run: `uv run pytest tests/rebrand/test_glued_name_preflight.py tests/rebrand/test_verifier_independence.py -v`
  Expected: FAIL on missing helpers and unrefused glued names.
- [ ] **Step 3 (`P19-T01`): Implement shared verify field helpers.**
  - Move `_load_verify_config` into `verify_config.py` as `load_verify_config(target: Path) -> VerifyConfig`.
  - Add `effective_verify_fields(source, cfg, substring_rewrite_fields)` in `verify_config.py` matching `verify_cli.py`'s exact logic (`cfg.fields` + optional `display_name`, `npm_name`, `cli_name` + `substring_rewrite_fields` in `KNOWN_FIELDS`, and `cfg.substring_fields | substring_rewrite_fields`).
  - Expose `changed_verify_fields` in `verifier.py` and call it from `verifier.scan` and `verify_cli.py`.
- [ ] **Step 4 (`P19-T01`): Implement core-field glued-name detection and guidance.**
  - In `keep_names.py`, scan each surface line-by-line (content) or per-component (path, skipping root `press/`) or readlink text (symlink) for `glued_fields` using `find_outside_kept(..., substring=field in glued_substring_fields, kept=kept)`.
  - Skip any matched span rewritten by `rewritten.patterns` (`_row_rewrites`) or covered by `rewritten.tokens` / `rewritten.literals` (`occupied`).
  - Expand the unmatched span to its full `_NAME_CHARS` token and emit `UndeclaredName(..., value=value, line=lineno, col=start, kind="glued")`.
  - Update `render_undeclared` to format glued findings per Decision 1 (showing `rewrite it:` only when an allowed `substring_rewrite_fields` entry would literally rewrite that token, and `or keep it:` only when `validate_keep_names` accepts the token).
  - In `substitutions.check_target_keep_names`, load/accept `VerifyConfig`, compute `(scan_fields, scan_substring)` and `changed_verify_fields`, exclude `rules.verify_ignore` components on core glued checks, filter candidate glued findings through `ignores.apply_ignores` in source coordinates (propagating `ValidationError` on ambiguous ignores, ignoring stale ignores), and pass `VerifyConfig` from both `cli.py` and `verify_cli.py`.
- [ ] **Step 5: Run tests and full rebrand suite.**
  Run: `uv run pytest tests/rebrand/test_glued_name_preflight.py tests/rebrand/test_verifier_independence.py tests/rebrand/test_keep_names.py tests/rebrand/test_keep_names_end_to_end.py -v`
  Then: `uv run pytest tests/rebrand -q`
  Expected: PASS (review and adjust any legacy test whose sole premise was the pre-P19 false receipt on a glued core field).
- [ ] **Step 6: Commit.**
  `feat(rebrand)!: refuse glued old identity names before writing` with a `BREAKING CHANGE:` footer explaining that targets already flagged by pre-press `press verify` now exit 1 before writing.

---

### Task 2: `display_name_pascal` in `substring_rewrite_fields` (P19-TS02, P19-T02)

**Files:**
- Modify: `src/template_press/rebrand/rules.py`, `src/template_press/rebrand/verify_config.py`, `src/template_press/rebrand/verifier.py`, `src/template_press/rebrand/verify_cli.py`, `src/template_press/rebrand/keep_names.py`
- Create: `tests/rebrand/test_display_name_pascal.py`
- Modify: `tests/rebrand/test_rules.py`

**Interfaces:**
- Produces:
  - `rules.ALLOWED_SUBSTRING_REWRITE_FIELDS = (ALLOWED_PLACEHOLDERS - {"display_name"}) | {"display_name_pascal"}`
  - `verify_config.KNOWN_FIELDS` includes `"display_name_pascal"`
  - `verifier.changed_verify_fields` expands `"display_name_pascal"` to `display_forms(source.display_name)["pascal"]` when both sides declare `display_name` and their Pascal forms differ

- [ ] **Step 1 (`P19-TS02`): Write failing tests** in `tests/rebrand/test_display_name_pascal.py`:
  - Validation: `substring_rewrite_fields = ["display_name_pascal"]` accepted; bare `["display_name"]` still rejected with clear error naming `display_name_pascal`; `["display_name_camel"]` and `["display_name_spaced"]` still rejected.
  - Rewrite + preflight + doctor + verify end-to-end: target with `client<llm> AcmeWidgetClient` in `baml_src/main.baml` and `substring_rewrite_fields = ["display_name_pascal"]` passes preflight, rewrites to `ZetaToolClient`, passes doctor, and passes `press verify` (exit 0, receipt written).
  - Substring leak coverage: when a glued lowercase-prefixed occurrence (`myAcmeWidgetClient`) survives an unrewritable spot (e.g. an escaping symlink or ablated row), doctor, regeneration scan, and `verifier.scan` all catch it as `display_name_pascal`.
  - Preflight presence in `verify_cli._preflight`: target declaring `display_name = "Acme Widget"` and `substring_rewrite_fields = ["display_name_pascal"]` where the display name appears only glued (`AcmeWidgetClient`) passes `press verify` preflight (does not falsely exit 2 as absent).
  - Pipeline validation: destination containment/stability check rejects a `display_name_pascal` rename where destination Pascal form contains source Pascal form (exit 2).
- [ ] **Step 2: Run tests to verify they fail.**
  Run: `uv run pytest tests/rebrand/test_display_name_pascal.py tests/rebrand/test_rules.py -v`
  Expected: FAIL on `rules.py` rejecting `display_name_pascal`.
- [ ] **Step 3 (`P19-T02`): Implement `display_name_pascal` support.**
  - In `rules.py`, add `ALLOWED_SUBSTRING_REWRITE_FIELDS`, validate `substring_rewrite_fields` against it, and keep the dedicated refusal for bare `"display_name"` (pointing to `display_name_pascal` and `display_forms`).
  - Verify `substitutions.py`, `engine.py`, `doctor.py`, and `regen.py` already handle `display_name_pascal` via `display_name_{form}`; adjust any edge case where `display_forms` disables `"pascal"` while `substring_rewrite_fields` lists `"display_name_pascal"` (refuse contradictory config at load time with exit 2).
  - In `verify_config.py`, add `"display_name_pascal"` to `KNOWN_FIELDS`.
  - In `verifier.changed_verify_fields`, handle `"display_name_pascal"` via `display_forms(...)["pascal"]` when both identities declare `display_name` and the Pascal forms differ (skipping duplicate boundary pattern only when not in `substring_fields`).
  - In `verify_cli._preflight`, ensure presence check for `display_name` / `display_name_pascal` checks `display_forms(source.display_name)["pascal"]` with `substring=True` when `display_name_pascal` is in `substring_fields`.
  - Ensure `keep_names.render_undeclared` suggests `substring_rewrite_fields = ["display_name_pascal"]` whenever a glued `display_name` token contains the literal `display_forms(source.display_name)["pascal"]`.
- [ ] **Step 4: Run tests.**
  Run: `uv run pytest tests/rebrand/test_display_name_pascal.py tests/rebrand/test_glued_name_preflight.py tests/rebrand/test_rules.py tests/rebrand/test_verifier.py -v`
  Expected: PASS.
- [ ] **Step 5: Commit.**
  `feat(rebrand): allow display_name_pascal in substring_rewrite_fields`

---

### Task 3: `{package_name}` in regeneration paths and `extra_exclude_files` (P19-TS03, P19-T03)

**Files:**
- Modify: `src/template_press/rebrand/rules.py`, `src/template_press/rebrand/cli.py`, `src/template_press/rebrand/verify_cli.py`, `src/template_press/rebrand/check_tools.py`
- Create: `tests/rebrand/test_package_path_placeholders.py`

**Interfaces:**
- Produces:
  - `rules.render_package_paths(rules: Rules, identity: Identity) -> Rules` (renders `{package_name}` in `exclude_files`, `regenerate` `file`, and — in Task 4 — `regenerate_dirs` `dir`, validating each rendered path with `_declared_rel_path` and `_reject_reserved`, and re-running overlap/membership checks on the rendered paths)

- [ ] **Step 1 (`P19-TS03`): Write failing tests** in `tests/rebrand/test_package_path_placeholders.py`:
  - Schema validation:
    - `[[regenerate]] file = "src/{package_name}/baml_client/inlinedbaml.py"` paired with `extra_exclude_files = ["src/{package_name}/baml_client/inlinedbaml.py"]` loads cleanly.
    - Unknown placeholder (`{repo_name}`, `{app_name}`) or unbalanced brace (`src/{package_name/x`) in `[[regenerate]] file` or `extra_exclude_files` raises `ValidationError`.
    - `{package_name}` in `extra_exclude_dirs` is rejected (`extra_exclude_dirs` remains single literal path components).
    - Overlap check rejects a literal path (`src/acme_widget/out.txt`) colliding with a rendered `{package_name}` path (`src/{package_name}/out.txt`) once rendered for `source`.
  - Preflight rendering and press:
    - First press (`acme_widget` -> `zeta_tool`) finds `src/acme_widget/out.txt` at plan time, skips rewriting it, translates/runs regeneration at `src/zeta_tool/out.txt`, and writes a receipt.
    - Repeat press (`--force`, `zeta_tool` -> `nova_app`) without editing `press/press-rules.toml` finds `src/zeta_tool/out.txt`, regenerates `src/nova_app/out.txt`, and passes `press verify`.
    - `press check-tools` loads a rules file containing `{package_name}` in `[[regenerate]]` without failing.
- [ ] **Step 2: Run tests to verify they fail.**
  Run: `uv run pytest tests/rebrand/test_package_path_placeholders.py -v`
  Expected: FAIL on `{package_name}` parsing/rendering.
- [ ] **Step 3 (`P19-T03`): Implement `{package_name}` support.**
  - Add a small placeholder validator `_validate_package_placeholder(context: str, path: str) -> None` in `rules.py` allowing ONLY `{package_name}` and rejecting unknown placeholders or unbalanced braces; enforce it on `[[regenerate]] file` (and `dir` in Task 4) and `extra_exclude_files`, and reject `{...}` in `extra_exclude_dirs`.
  - Allow `{package_name}` in `_declared_rel_path` (SafeRelPath already allows ASCII braces; confirm and keep control-char / traversal guards intact).
  - Add `render_package_paths(rules: Rules, source: Identity) -> Rules` in `rules.py` that renders `{package_name}` -> `source.package_name` in `exclude_files` and `regenerate` (preserving the raw template or rendering cleanly), re-validates `_reject_reserved`, writer overlaps, and exclude membership on rendered coordinates.
  - Call `rules = render_package_paths(rules, source)` in `cli.py` (right after `source` is resolved, before `check_target_keep_names`, `build_plan`, `preflight_*`, and `plan_regenerate_commands`) and in `verify_cli.py` (right after `source` and `rules` are loaded).
- [ ] **Step 4: Run tests.**
  Run: `uv run pytest tests/rebrand/test_package_path_placeholders.py tests/rebrand/test_regenerate_rules.py tests/rebrand/test_regenerate_plan.py tests/rebrand/test_check_tools.py -v`
  Expected: PASS.
- [ ] **Step 5: Commit.**
  `feat(rebrand): support {package_name} in regeneration paths`

---

### Task 4: Whole-directory regeneration `[[regenerate]] dir` (P19-TS04, P19-T04)

**Files:**
- Modify: `src/template_press/rebrand/rules.py`, `src/template_press/rebrand/pathing.py`, `src/template_press/rebrand/inventory.py`, `src/template_press/rebrand/engine.py`, `src/template_press/rebrand/doctor.py`, `src/template_press/rebrand/verifier.py`, `src/template_press/rebrand/substitutions.py`, `src/template_press/rebrand/regen.py`, `src/template_press/rebrand/receipt.py`, `src/template_press/rebrand/check_tools.py`, `src/template_press/rebrand/cli.py`, `src/template_press/rebrand/verify_cli.py`
- Create: `tests/rebrand/test_regenerate_dir.py`

**Interfaces:**
- Produces:
  - `rules.RegenerateDirRule(dir: str, command: tuple[str, ...], env: tuple[str, ...] = (), scan: str = "strict", verify_exempt: bool = False, reason: str = "", raw_dir: str = "")`
  - `Rules.regenerate_dirs: tuple[RegenerateDirRule, ...] = ()` (appended LAST on `Rules` for positional safety)
  - `regen.RegenerationDirPlan(rule: RegenerateDirRule, executable: str, env_present: tuple[str, ...], env_absent: tuple[str, ...], dest_dir: str)`
  - `pathing.exempt_regenerated_dirs(rules: Rules, renamed: ...) -> list[tuple[str, str]]`
  - `receipt.write_receipt(..., regenerate_dirs=..., exempt_dirs=...)`

- [ ] **Step 1 (`P19-TS04`): Write failing tests** in `tests/rebrand/test_regenerate_dir.py`:
  - Schema & overlap validation (all exit 2, no writes):
    - Exactly one of `file` or `dir` required on `[[regenerate]]` (neither -> error; both -> error).
    - `dir` rejects glob characters (`*`, `?`, `[`), root (`.`), traversal (`..`), control paths (`press`, `press/press-source.toml`, case/dot aliases), and unknown placeholders (only `{package_name}` allowed).
    - `[[regenerate]] dir` needs NO `extra_exclude_dirs` or `extra_exclude_files` entry.
    - Overlap refusals: two `[[regenerate]] dir` with nested/equal paths on overlapping platforms; `[[regenerate]] dir` overlapping `[[regenerate]] file`, `[[reset]]` (file or `stub_file`), `[[edit]]`, `[[remove]]` (`file` or `dir`) on overlapping platforms; platform-disjoint rules still allowed.
    - `verify_exempt = true` requires non-empty printable `reason`; `reason` without `verify_exempt = true` rejected.
  - Preflight safety (exit 2, no writes):
    - Symlink at `dir`, symlink inside `dir`, gitlink at or inside `dir`, embedded `.git`, Git visibility input (`.gitignore` etc.) inside `dir` -> refused.
    - Dirty tracked file or unignored untracked file inside `dir` -> refused even under `--allow-dirty`.
    - Absent `dir` (fresh clone of gitignored client, or after `press clean`) -> accepted at preflight, created by command after `apply()`, scanned.
    - Wholly gitignored root `baml_client/` present on disk -> accepted at preflight, deleted and rebuilt in place, scanned.
    - Wholly gitignored in-package `src/acme_widget/baml_client/` present on disk -> refused by rename-closure guard; after `press clean` (using `[[clean]] paths = ["src/{package_name}/baml_client"]`), press succeeds and rebuilds `src/zeta_tool/baml_client/`.
  - Execution & post-conditions:
    - No file under `dir` is text-rewritten by `apply()`, scanned by pre-write glued-name preflight, or hunted by doctor.
    - Parent directory rename (`src/acme_widget` -> `src/zeta_tool`) moves the directory cleanly and rebuilds at `src/zeta_tool/baml_client`.
    - Stale file present in old `dir` is gone after regeneration; newly generated file is present.
    - Command fails (nonzero exit) -> exit 1, no receipt, restore hint printed.
    - Command exits 0 but does not leave `dir` behind (or leaves a symlink/binary/old-identity leak in any generated file) -> exit 1, no receipt.
    - `scan = "boundary"` downgrades content scan inside generated files while keeping path and `[[replace]]` checks strict.
    - `final_validation_pass` catches a later command reintroducing a leak or symlink into an earlier regenerated directory.
  - Verify, receipt, and `check-tools`:
    - `verify_exempt = true` with `reason`: `press verify` skips the directory, prints `not verified (exempt): <dir>/ — <reason>`, emits it in `--json`, and the receipt records `[[press.regenerate_dir]]` (`dir`, `source_dir`, `argv`, `reason`) and `[[press.exempt]]` (`dir`, `reason`).
    - Without `verify_exempt = true`: `press verify` checks the directory (fails if old identity survives in the sandbox, passes if the directory holds no old identity).
    - `press check-tools` resolves and reports `argv[0]` of `[[regenerate]] dir` entries.
    - Repeat press (`--force`) with `dir = "src/{package_name}/baml_client"` works cleanly across two consecutive renames.
- [ ] **Step 2: Run tests to verify they fail.**
  Run: `uv run pytest tests/rebrand/test_regenerate_dir.py -v`
  Expected: FAIL on unknown key `dir` in `[[regenerate]]`.
- [ ] **Step 3 (`P19-T04`): Implement `RegenerateDirRule` parsing, validation, and `{package_name}` rendering.**
  - In `rules.py`, add `dir` to `_REGENERATE_KEYS`, add `RegenerateDirRule`, append `regenerate_dirs: tuple[RegenerateDirRule, ...] = ()` LAST on `Rules`, update `_parse_regenerate` (mirroring `_parse_remove`'s `has_file == has_dir`, glob rejection, `ROOT_CONTROL` containment rejection, plus `_validate_package_placeholder`), update `_validate_writer_overlaps` for all directory-vs-file/dir/stub overlaps, update `_validate_exclude_membership` so `RegenerateDirRule` requires no `exclude_files` entry (and is not paired with `[[edit]]` inside it), update `_select_rules`, and extend `render_package_paths` to render `RegenerateDirRule.dir` (preserving `raw_dir` so destination coordinates can also render `{package_name}` with `dest.package_name` when the directory was absent before `apply()`).
- [ ] **Step 4 (`P19-T04`): Exclude `[[regenerate]] dir` subtrees from rewrite, preflight, doctor, and (when exempt) verifier.**
  - In `inventory.py`, add optional `exclude_prefixes: frozenset[str] = frozenset()` to `_excluded`, `select_content_rewrite_entries`, `select_rename_entries`, `select_inline_doctor_entries`, `select_verifier_entries`, and `rewrite_surface_texts` (matching `posix == prefix or posix.startswith(prefix + "/")`).
  - Thread `rules.regenerate_dirs` prefixes through `engine.py`, `substitutions.py`, `doctor.py` (using translated post-rename prefixes!), and `verifier.py` (only for `verify_exempt = true` dirs via `pathing.exempt_regenerated_dirs`).
  - Ensure `engine.py` still allows parent directories of a `[[regenerate]] dir` (like `src/acme_widget/`) to rename even though members inside `src/acme_widget/baml_client/` are excluded from content rewriting and individual-entry renaming! (Double-check rename closure: tracked members under `baml_client/` are moved with `src/acme_widget/` as a single parent directory rename, or removed cleanly before rebuild — verify how `_rename_pass_once` handles an excluded subdir inside a renamed parent directory so the parent rename succeeds!)
- [ ] **Step 5 (`P19-T04`): Implement preflight, execution, post-conditions, receipt, verify, and `check-tools`.**
  - In `regen.py`, implement `preflight_regenerate_dirs`, `plan_regenerate_dirs`, `execute_dir_regenerations`, directory post-condition scan (recursively walk with `os.scandir`, `follow_symlinks=False`, refusing symlinks/junctions/gitlinks/non-regular/non-UTF-8 and running `scan_regenerated_output` on every file), and extend `final_validation_pass` + `render_regenerate_plan`.
  - Before launching a directory regeneration command, verify containment and no-follow safety on the pressed directory path (computed from `translate_path(rule.dir, renames)` or rendering `rule.raw_dir` with `dest` when absent pre-press), delete it safely without following symlinks (reusing no-follow directory removal helpers), run the pinned command, then run full directory post-conditions.
  - In `receipt.py`, add `[[press.regenerate_dir]]` and directory `[[press.exempt]]` rendering (also budgeted in `preflight_receipt`).
  - In `check_tools.py`, report `rules.regenerate_dirs`.
  - In `cli.py` and `verify_cli.py`, wire preflight, plan rendering, execution, receipt, and verify exemption reporting.
- [ ] **Step 6: Run tests.**
  Run: `uv run pytest tests/rebrand/test_regenerate_dir.py tests/rebrand/test_regenerate_rules.py tests/rebrand/test_regenerate_plan.py tests/rebrand/test_regenerate_execute.py tests/rebrand/test_regenerate_postconditions.py tests/rebrand/test_verify_exemption.py tests/rebrand/test_receipt.py -v`
  Expected: PASS.
- [ ] **Step 7: Commit.**
  `feat(rebrand): support whole-directory [[regenerate]] dir`

---

### Task 5: Undeclared tracked BAML client refusal and message fix (P19-TS05, P19-T05)

**Files:**
- Modify: `src/template_press/rebrand/discovery.py`, `src/template_press/rebrand/rules.py`, `src/template_press/rebrand/cli.py`, `src/template_press/rebrand/verify_cli.py`
- Create: `tests/rebrand/test_baml_client_guard.py`
- Modify: `tests/rebrand/test_regenerate_execute.py`, `tests/rebrand/test_cli.py` (if existing assertions check the old `"lockfile regeneration failed"` text)

**Interfaces:**
- Produces:
  - `rules.baml_regenerate_suggestion(client_dir: str, marker_ext: str, source: Identity | None = None) -> str`
  - `discovery.undeclared_baml_client_problems(target: Path, source: Identity, rules: Rules) -> list[str]`

- [ ] **Step 1 (`P19-TS05`): Write failing tests** in `tests/rebrand/test_baml_client_guard.py`:
  - Tracked Python client (`baml_client/inlinedbaml.py` at root and `src/acme_widget/baml_client/inlinedbaml.py` nested) with no rule -> exits 2, `git status --porcelain` empty, stderr contains `baml client src/acme_widget/baml_client has no [[regenerate]] declaration` and the paste-ready `[[regenerate]]` block using `dir = "src/{package_name}/baml_client"`, `verify_exempt = true`, and `reason = "BAML client, rebuilt from baml_src"`.
  - Tracked TypeScript client (`baml_client/inlinedbaml.ts` and `src/baml_client/inlinedbaml.ts`) with no rule -> exits 2, no writes, suggested `[[regenerate]] dir` block printed.
  - Covered cases (must NOT exit 2):
    - Covered by `[[regenerate]] dir` containing the marker (exact dir or ancestor dir, including `{package_name}` rendered).
    - Covered by `[[regenerate]] file` naming that marker (`baml_client/inlinedbaml.py` or `.ts`).
    - Covered by `[[remove]] dir` containing the marker or `[[remove]] file` naming the marker.
  - Gitignored or untracked-ignored client (`baml_client/` in `.gitignore`) -> NOT refused.
  - Decision 5 regression check: `languages = ["baml"]` still exits 2 as unknown language.
  - Decision 6 message fix: a failed `[[regenerate]]` (both `file` and `dir`) prints `regeneration of <path> failed` and does NOT call the output a `"lockfile"`.
- [ ] **Step 2: Run tests to verify they fail.**
  Run: `uv run pytest tests/rebrand/test_baml_client_guard.py -v`
  Expected: FAIL on missing BAML guard and old `"lockfile regeneration failed"` message.
- [ ] **Step 3 (`P19-T05`): Implement undeclared BAML client refusal (Decision 8) and message fix (Decision 6).**
  - In `rules.py`, add `baml_regenerate_suggestion(client_dir, marker_ext, source)` that substitutes `{package_name}` when `source.package_name` appears as a path component in `client_dir`, suggests `["uv", "run", "--offline", "baml-cli", "generate"]` for `.py` and `["npx", "baml-cli", "generate"]` for `.ts`, and sets `verify_exempt = true` and `reason = "BAML client, rebuilt from baml_src"`.
  - In `discovery.py`, add `undeclared_baml_client_problems(target, source, rules)`: scan `tracked_path_strings(capture_surface_snapshot(target))` for paths ending in `baml_client/inlinedbaml.py` or `baml_client/inlinedbaml.ts` (at root or any nested depth, matching path components `parts[-2] == "baml_client"` and `parts[-1] in ("inlinedbaml.py", "inlinedbaml.ts")`). Treat a marker as covered when any rendered `rules.regenerate_dirs` contains it, any rendered `rules.regenerate` names it, any `rules.remove_dirs` contains it, or any `rules.remove` names it. For each uncovered marker, emit Decision 8's exact message and suggested block.
  - Call `undeclared_baml_client_problems(target, source, rules)` in `cli.py` (before any write, exit 2) — and in `verify_cli.py`? Check Decision 8: it says "Before any write, the press refuses a tracked BAML client..." — keep it in `cli.py` (pre-write press gate, matching `_undeclared_lock_problem` or run in `cli.py` before `check_target_keep_names` so an uncovered client gets the clear exit-2 declaration block rather than a storm of exit-1 glued-name findings inside generated code!).
  - In `cli.py:1406-1428`, replace `"lockfile regeneration failed for ..."` with `"regeneration of <paths> failed — the regenerated output still carries the old identity or failed its postcondition and is exempt from the doctor scan, so this rebrand is INCOMPLETE; no receipt written. ..."` and include `_partial_rewrite_restore_hint(target)`. Update any existing unit test assertions that matched the old `"lockfile regeneration failed"` wording.
- [ ] **Step 4: Run tests.**
  Run: `uv run pytest tests/rebrand/test_baml_client_guard.py tests/rebrand/test_regenerate_execute.py tests/rebrand/test_cli.py -v`
  Expected: PASS.
- [ ] **Step 5: Commit.**
  `feat(rebrand)!: refuse undeclared tracked baml clients and fix regen message` with a `BREAKING CHANGE:` footer noting that tracked BAML clients without a `[[regenerate]]` or `[[remove]]` rule now exit 2 with a suggested block.

---

### Task 6: Real `baml-cli` live acceptance tests (P19-TS06)

**Files:**
- Create: `tests/rebrand/test_baml_acceptance.py`

**Interfaces:**
- Follows `tests/rebrand/test_cargo_acceptance.py` gating pattern: marked `@pytest.mark.live` (and `@pytest.mark.slow`), skipped locally when `baml-cli` is not available unless explicitly pointed to via `PATH` or a fixture venv, never fails offline default `pytest`.

- [ ] **Step 1 (`P19-TS06`): Write live `baml-cli` acceptance tests** in `tests/rebrand/test_baml_acceptance.py`:
  - Helper locating `baml-cli` (via `shutil.which("baml-cli")` or `BAML_CLI_BIN` env var; skips cleanly if absent when running locally). All fixtures use synthetic `example.test` identities (`acme_widget` / `Acme Widget` -> `zeta_tool` / `Zeta Tool` -> `nova_app` / `Nova App`).
  - Test matrix (using real `baml-cli generate` 0.226.3, no live LLM calls):
    1. **Python host, client at root (`baml_client/`):** `.baml` source with `client<llm> AcmeWidgetClient` and a typed class `AcmeWidgetReply`, `substring_rewrite_fields = ["display_name_pascal"]`, `[[regenerate]] dir = "baml_client"`, press -> regenerated client matches a fresh `baml-cli generate` -> target's own Python import/type test passes -> `press verify` exits 0.
    2. **Python host, client inside package (`src/{package_name}/baml_client`):** press `acme_widget` -> `zeta_tool` -> target's own test passes -> `press verify` exits 0 -> **repeat press** (`--force`) `zeta_tool` -> `nova_app` without editing `press/press-rules.toml` -> target's own test passes -> `press verify` exits 0.
    3. **TypeScript host, client at root (`baml_client/`):** `package.json`, `baml_src/` with `generator target { output_type "typescript" ... }` and glued `AcmeWidgetClient`, press -> regenerated TS client equals fresh `baml-cli generate` -> `press verify` exits 0 -> repeat press passes.
    4. **TypeScript host, client nested (`src/baml_client/`):** press -> regenerate -> `press verify` exits 0.
    5. **Gitignored client path:** Python target with `src/acme_widget/baml_client/` in `.gitignore` and `[[clean]] paths = ["src/{package_name}/baml_client"]` -> `press clean` -> `press rebrand` -> rebuilds `src/zeta_tool/baml_client` -> `press verify` exits 0.
- [ ] **Step 2: Run live acceptance tests against real `baml-cli` 0.226.3.**
  Run: `PATH="<baml-cli-venv-bin>:$PATH" uv run pytest -m "" tests/rebrand/test_baml_acceptance.py -v`
  (If the scratchpad venv was cleared, create a scratch venv with `uv pip install baml-py==0.226.3`.)
  Expected: ALL PASS.
- [ ] **Step 3: Verify default `pytest` (without `-m ""`) stays fast and green.**
  Run: `uv run pytest tests/rebrand/test_baml_acceptance.py -v`
  Expected: live tests deselected by default marker config.
- [ ] **Step 4: Commit.**
  `test(rebrand): add live baml-cli acceptance tests`

---

### Task 7: Documentation, `press-target` skill recipe, and design docs (P19-T06)

**Files:**
- Modify: `docs/source/reference/cli.md`, `.claude/skills/press-target/SKILL.md`, `docs/design/0006-external-target-model.md`, `docs/design/0008-identity-variants-and-replace-rules.md`, `AGENTS.md`

- [ ] **Step 1: Document BAML targets and the new mechanisms.**
  - In `docs/source/reference/cli.md` and `.claude/skills/press-target/SKILL.md`:
    - Add the BAML target recipe (with the exact `press/press-rules.toml` example from Decision 7, running `press verify` before the first press, the gitignored-client + `[[clean]]` path, and the note that `languages` lists only the host manifest, never `"baml"`).
    - Document `[[regenerate]] dir`, `{package_name}` in regeneration paths and `extra_exclude_files`, `display_name_pascal` in `substring_rewrite_fields`, the general glued-name preflight (and its rewrite/keep guidance), and the undeclared tracked BAML client exit-2 refusal.
  - In `docs/design/0006-external-target-model.md`: update the regeneration and preflight summary to include `[[regenerate]] dir`, `{package_name}` paths, and the glued-name preflight.
  - In `docs/design/0008-identity-variants-and-replace-rules.md`: update `substring_rewrite_fields` (`display_name_pascal`), the pre-write leak/glued-name preflight (scope (i)), and `[[regenerate]] dir`.
  - In `AGENTS.md`: add a concise BAML targets paragraph under "Running the press" matching the existing Rust/npm guidance.
- [ ] **Step 2: Format-check docs (including Python fences in Markdown).**
  Run: `uv run ruff format --check .`
  Expected: PASS with zero formatting drift.
- [ ] **Step 3: Commit.**
  `docs(rebrand): document baml targets, regenerate dir, and glued-name preflight`

---

### Task 8: Full verification and PR preparation (P19-T07)

**Files:**
- Modify: `projects/P19-baml-targets.md`, `PROJECTS.md` (update task checkboxes as completed)

- [ ] **Step 1: Run the full verification pipeline.**
  Run:
  - `uv run ruff format --check .`
  - `just check`
  - `just matrix` (R1/R2/R3 acceptance matrix, required after any change to `src/template_press/rebrand/`)
  - Live BAML acceptance suite: `uv run pytest -m "" tests/rebrand/test_baml_acceptance.py -v` (with `baml-cli` on `PATH`)
  Expected: all green.
- [ ] **Step 2: Audit project tracking.**
  Check `projects/P19-baml-targets.md` and `PROJECTS.md` (all finished tasks ticked, references resolve, no drift).
- [ ] **Step 3: Commit final tracking update, push, and open PR (only with owner go-ahead).**
  Include a clear release note in the PR body calling out the two owner-approved behavior changes (glued-name preflight exit 1 before writing; undeclared tracked BAML client exit 2 before writing) and synthetic-only examples. Do not merge without owner review.
