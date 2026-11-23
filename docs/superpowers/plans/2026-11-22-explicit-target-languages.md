# Explicit Target Languages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `press rebrand` and `press verify` exit 2 with no writes when a target has several languages and declares none.

**Architecture:** A new standalone `languages.py` detects root manifests and resolves them against `[rules] languages`. Both CLIs call it before `discover()` reads a manifest, so one committed declaration governs both commands.

**Tech Stack:** Python 3.13 standard library (`tomllib`, `json`), pytest, uv, just.

**Spec:** `docs/superpowers/specs/2026-11-22-explicit-target-languages-design.md`

## Global Constraints

- Zero runtime dependencies.
- Exit codes stay 0/1/2. Every guard refusal is exit 2 with no writes.
- `Rules.languages` is appended as the LAST dataclass field.
- `languages.py` must not import `rules`, `substitutions`, `engine`, `doctor`, or `verifier`.
- `verifier.py` is not modified.
- Project ID is P16. Do not accept the next free ID, because `PROJECTS.md` on this branch ends at P12.
- Fixtures are synthetic and use `example.test`. No private names in commits, docs, or PR text.
- Never push to `py-launch-blueprint`. Never merge the PR.

## Review Focus

1. A malformed `package.json` (bad JSON, non-UTF-8, a top-level array) must exit 2 naming the file, never a traceback. Task 2.
2. A manifest symlink pointing outside the target must exit 2 without reading the link target. Task 2.
3. `--json` and `--diagnostics-json` stdout must stay one JSON object when languages are ignored. Task 3.
4. A declared manifest removed by `[[remove]]`, including a case-variant spelling such as `PACKAGE.JSON`, must refuse at `rebrand`. Task 2.
5. A target accepted by `rebrand` must also be accepted by `verify` after the press. Task 3.

---

### Task 1: Register P16 and parse `[rules] languages`

**Files:**
- Modify: `PROJECTS.md`, `src/template_press/rebrand/rules.py`
- Create: `projects/P16-explicit-target-languages.md`, `src/template_press/rebrand/languages.py` (constants only)
- Test: `tests/rebrand/test_languages.py`

**Interfaces:**
- Produces: `KNOWN_LANGUAGES = ("python", "node", "rust")`, `SUPPORTED_LANGUAGES = frozenset({"python"})`, `Rules.languages: tuple[str, ...] | None = None`.

- [ ] **Step 1: Register P16** through `project-add`, overriding the proposed ID to P16, linking the spec and this plan.
- [ ] **Step 2: Write failing tests** in `test_languages.py`:
  - `test_rules_languages_defaults_to_none`: no key gives `load_rules(t).languages is None`.
  - `test_rules_languages_parsed`: `["python"]` gives `("python",)`.
  - `test_rules_languages_rejects` parametrized over `[]`, `["python", "python"]`, `["perl"]`, `"python"`, `[1]`: `pytest.raises(ValidationError, match="languages")`.
  - `test_rules_languages_reserved_not_supported` over `["node"]`, `["python", "rust"]`: `match="not supported by this press version"`.
- [ ] **Step 3: Run** `uv run pytest tests/rebrand/test_languages.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement.** Add `"languages"` to `_RULES_KEYS`. Add `_parse_languages(table: dict) -> tuple[str, ...] | None` and pass its result to `Rules(...)` in `_parse_rules`. `_select_rules` keeps it through `replace`.
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit** `feat(rebrand): parse declared target languages`.

### Task 2: Detect and resolve languages

**Files:**
- Modify: `src/template_press/rebrand/languages.py`
- Test: `tests/rebrand/test_languages.py`

**Interfaces:**
- Produces:
  - `DetectedLanguage(language: str, manifest: str)`, frozen dataclass.
  - `LanguageDecision(checked: tuple[str, ...], ignored: tuple[DetectedLanguage, ...])`, frozen dataclass.
  - `detect_languages(target: Path) -> tuple[DetectedLanguage, ...]`, ordered as `KNOWN_LANGUAGES`.
  - `check_target_languages(target: Path, declared: tuple[str, ...] | None, removed_files: Iterable[str]) -> LanguageDecision`, raising `ValidationError`.
  - `render_ignored_languages(decision: LanguageDecision) -> list[str]`.

- [ ] **Step 1: Write failing tests:**
  - `test_detect_counts_identity_manifests_only`: `[project]`, `[package]`, `[workspace]`, and a named `package.json` count. `[tool.x]`-only `pyproject.toml` and a nameless `package.json` do not.
  - `test_detect_refuses_malformed` over invalid TOML, invalid JSON, non-UTF-8 bytes, a JSON array, `{"name": 1}`, `{"name": ""}`: `ValidationError` naming the manifest.
  - `test_detect_refuses_symlink` (`posix_only`): the link target holds valid content and the error names the manifest.
  - `test_detect_refuses_directory_manifest`.
  - `test_undeclared_multi_language_refused`: message contains `pyproject.toml`, `package.json`, and `languages = ["python"]`.
  - `test_single_language_undeclared_continues`, `test_no_manifest_continues`.
  - `test_declared_subset_ignores_rest`: `checked == ("python",)`, `ignored` holds node.
  - `test_declared_without_manifest_refused`.
  - `test_declared_manifest_removed_refused` over `pyproject.toml`, `PYPROJECT.TOML`.
- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_languages.py -v`. Expected: new tests FAIL.
- [ ] **Step 3: Implement.** Read each manifest with `read_regular_nofollow`. Treat `FileNotFoundError` as absent. Convert `OSError`, `SafetyError`, `UnicodeDecodeError`, `TOMLDecodeError`, and `JSONDecodeError` to `ValidationError` naming the manifest. Compare `removed_files` after `rstrip(" .").casefold()`. The paste-ready line lists every detected supported language.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): detect target languages from root manifests`.

### Task 3: Guard both commands

**Files:**
- Modify: `src/template_press/rebrand/cli.py`, `src/template_press/rebrand/verify_cli.py`
- Test: `tests/rebrand/test_languages_cli.py`

**Interfaces:**
- Consumes: `check_target_languages`, `render_ignored_languages`, `load_selected_rules`.

- [ ] **Step 1: Write failing tests** with a synthetic Python + `package.json` git target:
  - `test_rebrand_undeclared_exit2_no_writes`: exit 2, `git status --porcelain` empty, no receipt, also with `--dry-run`.
  - `test_verify_undeclared_exit2`.
  - `test_declared_rebrand_then_verify_pass`: rebrand 0, commit, repoint origin, verify 0, and stderr names `package.json` as ignored.
  - `test_verify_json_stdout_is_one_object_when_ignoring`.
  - `test_rebrand_diagnostics_json_stdout_clean_when_ignoring`: on a closure refusal, stdout parses as one JSON object.
  - `test_malformed_manifest_no_traceback` for both commands: exit 2.
- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_languages_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `cli.main`, run the guard after `check_preconditions` and before `_resolve_source`. In `verify_command`, run it after `load_selected_rules` and before `_preflight`. Pass `[rule.file for rule in rules.remove]` as `removed_files`. Print ignored-language lines to stderr.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS, apart from any existing test that asserted an old malformed-manifest message. Update such a test only to the new message.
- [ ] **Step 5: Commit** with a breaking marker: `feat(rebrand)!: require declared languages for multi-language targets`, with a `BREAKING CHANGE:` footer giving the `languages = [...]` fix.

### Task 4: Declare this repository and keep the matrix meaningful

**Files:**
- Modify: `press/press-rules.toml`, `tests/rebrand/test_matrix.py`

- [ ] **Step 1: Add** `languages = ["python"]` under `[rules]` in `press/press-rules.toml`.
- [ ] **Step 2: Add** `declare_blueprint_languages(target: Path) -> None` in `test_matrix.py`. If the parsed rules file already has `rules.languages`, it does nothing. Otherwise it inserts the line under `[rules]` (creating the file and table if absent) and commits in the disposable clone.
- [ ] **Step 3: Call it** after every `clone(BLUEPRINT, ...)`. In `test_r1a_undeclared_blueprint_refused_loudly`, call it after `shutil.rmtree(target / "press")`, so R1a and R2 still fail for their original reasons rather than at the new guard.
- [ ] **Step 4: Run** `just matrix`. Expected: R1, R2, and R3 pass.
- [ ] **Step 5: Commit** `test(matrix): declare languages in disposable blueprint clones`.

### Task 5: Document, verify, and open the PR

**Files:**
- Modify: `.claude/skills/press-target/SKILL.md`, `docs/source/reference/cli.md`, `docs/design/0006-external-target-model.md`, `AGENTS.md`, `PROJECTS.md`, `projects/P16-explicit-target-languages.md`

- [ ] **Step 1: Document** `[rules] languages`, the refusal, and the fix in the skill and CLI reference. Note in design 0006 that multi-language targets must declare.
- [ ] **Step 2: Run** `uv run ruff format --check .`, because CI formats Python fences in Markdown.
- [ ] **Step 3: Run** `make check`, `just check`, and `just matrix`. Expected: all pass.
- [ ] **Step 4: Update** P16 task status and confirm with `project-audit`.
- [ ] **Step 5: Commit** `docs(rebrand): document declared target languages`, and confirm with `git log -1`.
- [ ] **Step 6: Tell peers.** Send the TypeScript and Rust sessions the key, the values, the `SUPPORTED_LANGUAGES` seam, and that "`pyproject.toml` wins" no longer applies.
- [ ] **Step 7: Push and open** a PR to `main` whose body carries the release note and the blueprint follow-up. Do not merge.
