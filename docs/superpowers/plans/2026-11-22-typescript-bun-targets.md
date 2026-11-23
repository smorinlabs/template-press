# TypeScript and Bun Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make npm and Bun TypeScript repositories first-class `press` targets without changing any existing target's outcome.

**Architecture:** `package.json` becomes a second discovery source, selected in one function that rebases onto the owner-approved language guard. Two optional identity fields carry exact npm and CLI names through the existing substitution table. A neutral `keep_names` module lets every rewrite and scan honor declared independent names, while `verifier.py` stays independent of the table.

**Tech Stack:** Python 3.13 standard library, pytest, uv, just, npm, Bun, optional pnpm.

**Spec:** `docs/superpowers/specs/2026-11-22-typescript-bun-targets-design.md`

## Global Constraints

- Existing Python targets and existing source or answers files keep their outcome, other than through the owner-approved language guard from `feat/explicit-target-languages`.
- Merge order: `fix/hyphen-false-receipt`, `feat/explicit-target-languages`, TypeScript, Rust. Do not open the PR before the first two are on `origin/main`.
- Safety contract: config-first identity, discovery cross-check, verify-then-mark, exit codes 0/1/2, no receipt on leaks.
- The shipped package has zero runtime dependencies.
- `verifier.py` must not import `substitutions`, `engine`, or `doctor`, or accept table data.
- Regeneration commands are always target-declared. `press` only suggests them.
- Public repository: fixtures use `example.test` values. No private target name, hostname, or account detail may appear in any commit or PR text.
- Commits use lowercase Conventional Commits and end with `Claude-Session: https://claude.ai/code/session_01HuEtW7Y5qYixJQabGXsLxi`.
- Subagents run tests in the foreground with explicit timeouts, never in the background.
- Line length is 88. All functions are strictly typed.

## Review Focus

1. A `package.json` that is invalid JSON, BOM-prefixed, or not a top-level object is undiscoverable and never produces a traceback (Task 2).
2. A symlinked `package.json` is never followed out of an untrusted target (Task 2).
3. `npm_name` equal to `repo_name` keeps the npm boundary after row merging, so `acme-widget-extra` is not rewritten (Task 4).
4. A repeat press keeps `keep_names` valid after `press-source.toml` is refreshed (Task 6).
5. A string `bin` on a scoped package resolves to the unscoped CLI name (Task 2).

---

### Task 1: Register the project and add identity fields

**Files:**
- Modify: `PROJECTS.md`, `src/template_press/rebrand/identity.py`, `src/template_press/rebrand/cli.py:440-455`, `src/template_press/rebrand/rules.py:39-42`
- Create: `projects/P14-typescript-bun-targets.md`
- Test: `tests/rebrand/test_identity.py`, `tests/rebrand/test_node_identity_cli.py`

**Interfaces:**
- Produces: `validate_npm_name(name: str) -> str`, `validate_cli_name(name: str) -> str`, `Identity.npm_name: str | None`, `Identity.cli_name: str | None`, `OPTIONAL_FIELDS == ("display_name", "npm_name", "cli_name")`.

- [ ] **Step 1: Register P14 through `project-add`, then scope it through `project-refine`**

Record the spec and this plan as references. Expected: `PROJECTS.md` has a P14 row with status `[~]`, committed.

- [ ] **Step 2: Write failing tests**

```python
@pytest.mark.parametrize("name", ["acme-widget", "@acme/widget-api", "a.b_c~d"])
def test_npm_name_accepts(name):
    assert validate_npm_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "Acme", "@acme", "@acme/", "a/b", "@a/b/c", "a" * 215]
)
def test_npm_name_rejects(name):
    with pytest.raises(ValidationError):
        validate_npm_name(name)


@pytest.mark.parametrize("name", ["acme-cli", "acme.cli", "a1"])
def test_cli_name_accepts(name):
    assert validate_cli_name(name) == name


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "-a", "Acme"])
def test_cli_name_rejects(name):
    with pytest.raises(ValidationError):
        validate_cli_name(name)
```

In `test_node_identity_cli.py`, add `test_new_field_on_one_side_exits_2_without_writes`, parametrized over `npm_name` and `cli_name` and over source-only and answers-only. Assert exit 2 and an unchanged `git status`. Add `test_source_equality_must_survive_in_answers`: source `npm_name == repo_name`, answers differ, exit 2.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_identity.py tests/rebrand/test_node_identity_cli.py -q`
Expected: FAIL on missing validators and fields.

- [ ] **Step 4: Implement the fields**

Use the spec's exact regexes and the 214-character limit. Register both validators in `VALIDATORS`. Keep `as_dict` key order stable and add a key only when its value is not `None`. Add both fields to `ALLOWED_PLACEHOLDERS`. Extend the `display_name` half-specified guard in `cli.py` to both new fields in both directions.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/template_press/rebrand tests/rebrand PROJECTS.md projects/P14-typescript-bun-targets.md
git commit -m "feat(identity): add optional npm and cli name fields"
```

### Task 2: Discover and cross-check `package.json`

**Files:**
- Create: `src/template_press/rebrand/node_manifest.py`
- Modify: `src/template_press/rebrand/discovery.py`, `src/template_press/rebrand/cli.py:424-436`, `src/template_press/rebrand/verify_cli.py:280-283`
- Test: `tests/rebrand/test_node_discovery.py`

**Interfaces:**
- Consumes: `Identity.npm_name`, `Identity.cli_name`.
- Produces:
  - `NodeManifest(name: str | None, author: str | None, email: str | None, bins: tuple[str, ...], owner: str | None, repo_name: str | None)`
  - `read_node_manifest(target: Path) -> NodeManifest | None`
  - `Discovered.source_kind: str | None` (`"python"`, `"node"`, or `None`) and `Discovered.npm_name: str | None`, both defaulted
  - `manifest_warnings(source: Identity, found: Discovered) -> list[str]`

- [ ] **Step 1: Write failing tests**

Cover these named cases with exact assertions:

```python
def test_pyproject_without_project_table_uses_package_json(...): assert found.source_kind == "node"
def test_author_string_form(...): assert (m.author, m.email) == ("Ann Lee", "ann@example.test")  # "Ann Lee <ann@example.test> (https://example.test)"
def test_author_object_form(...): assert (m.author, m.email) == ("Ann Lee", "ann@example.test")
def test_string_bin_on_scoped_name_uses_unscoped_name(...): assert m.bins == ("widget-api",)
def test_object_bin_preserves_order(...): assert m.bins == ("first-cli", "second")
def test_repository_string_and_object_forms(...): assert (m.owner, m.repo_name) == ("example-org", "acme-widget")
@pytest.mark.parametrize("raw", ["{not json", "[]", "﻿{bad"])
def test_malformed_manifest_is_undiscoverable(...): assert read_node_manifest(t) is None
def test_symlinked_manifest_is_not_followed(...): assert read_node_manifest(t) is None
def test_declared_npm_name_mismatch_is_fatal(...): assert any("npm_name" in p for p in mismatches(source, found))
def test_declared_cli_name_must_be_bin_key(...): assert any("cli_name" in p for p in mismatches(source, found))
def test_undeclared_manifest_disagreement_only_warns(...): assert mismatches(source, found) == [] and manifest_warnings(source, found)
def test_node_target_skips_python_layout_check(...): assert not any("layout" in p for p in mismatches(source, found))
```

A valid manifest with a leading BOM parses normally.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_node_discovery.py -q`
Expected: FAIL on missing module.

- [ ] **Step 3: Implement discovery**

`read_node_manifest` refuses a symlink with `is_symlink()`, reads with `utf-8-sig`, and returns `None` on `OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`, or a non-object root. Reuse `_ORIGIN_RE` semantics for `repository`, after removing a `git+` prefix. For a node source, do not populate `Discovered.package_name` or `app_names`, since those drive fatal checks. Git origin wins over `repository`. Print `manifest_warnings` to stderr from both `rebrand` and `verify`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_node_discovery.py
git commit -m "feat(discovery): read identity from package.json"
```

### Task 3: Propose a source config from `package.json`

**Files:**
- Modify: `src/template_press/rebrand/discovery.py`, `src/template_press/rebrand/cli.py:399-422`
- Test: `tests/rebrand/test_node_discovery.py`

**Interfaces:**
- Consumes: `NodeManifest`, `Discovered.source_kind`.
- Produces: `node_proposal(manifest: NodeManifest, owner: str | None, repo_name: str | None) -> dict[str, str | None]`, with the six required keys plus `npm_name` and `cli_name`.

- [ ] **Step 1: Write failing tests**

```python
def test_proposal_derives_package_from_unscoped_name(): assert p["package_name"] == "widget_api"
def test_proposal_omits_npm_name_equal_to_repo_name(): assert p["npm_name"] is None
def test_proposal_keeps_scoped_npm_name(): assert p["npm_name"] == "@acme/widget-api"
def test_proposal_hyphenated_bin_sets_cli_name(): assert (p["app_name"], p["cli_name"]) == ("acme_cli", "acme-cli")
def test_proposal_identifier_bin_needs_no_cli_name(): assert (p["app_name"], p["cli_name"]) == ("acme", None)
def test_sparse_manifest_exit_2_names_missing_keys(...): assert code == 2 and "author" in out and "bin" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_node_discovery.py -q -k proposal`
Expected: FAIL on missing `node_proposal`.

- [ ] **Step 3: Implement and wire `node_proposal`**

`_resolve_source` uses it only when `found.source_kind == "node"`. The Python proposal path stays byte-identical. Pass non-`None` optional fields to `Identity.from_mapping`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_node_discovery.py
git commit -m "feat(discovery): propose source config from package.json"
```

### Task 4: Rewrite and scan the new fields

**Files:**
- Modify: `src/template_press/rebrand/identity.py:205-209`, `substitutions.py:57-59,855-870,966-1029`, `engine.py:93-98`, `synthesize.py`, `verify_cli.py:290-310,477-480`
- Test: `tests/rebrand/test_node_rewrite.py`

**Interfaces:**
- Consumes: Task 1 fields.
- Produces: `field_renames_paths(field: str, value: str) -> bool` in `identity.py`. It is true for existing rename fields, for `cli_name`, and for an `npm_name` without `/`.

- [ ] **Step 1: Write failing tests**

```python
def test_scoped_rewrite_keeps_subpath():
    assert replace_token('"@acme/widget/sub"', "npm_name", "@acme/widget", "@new/x") == '"@new/x/sub"'
def test_sibling_not_rewritten_by_npm_row():
    assert replace_token("@acme/widget-extra", "npm_name", "@acme/widget", "@new/x") == "@acme/widget-extra"
def test_npm_row_runs_before_owner_row(...): assert "@new-org/new-api" in pressed_package_json
def test_equal_npm_and_repo_keep_npm_boundary(...): assert "acme-widget-extra" in pressed_text
def test_cli_name_renames_bin_file(...): assert (t / "bin/new-cli.js").exists() and not (t / "bin/acme-cli.js").exists()
def test_scoped_npm_name_has_no_path_surface(...): assert "path" not in row.rewrite_surfaces
def test_synthesis_preserves_scoped_shape(...): assert re.fullmatch(r"@[a-z0-9-]+/[a-z0-9-]+", dest.npm_name)
def test_synthesis_preserves_npm_repo_equality(...): assert dest.npm_name == dest.repo_name
def test_verify_scans_declared_new_fields(...): assert code == 1 and "npm_name" in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_node_rewrite.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add a `token_pattern` branch for both fields using the spec's boundaries. In `_identity_rows`, sort by `(-len(from_value), field != "npm_name")`, so an equal-valued `npm_name` row owns the merged matcher. Use `field_renames_paths` for rewrite and doctor path surfaces. Add both fields to the `synthesize_dest` slots so equality is preserved. Keep `verifier.py` deriving fields from `Identity`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS, including the structural verifier-independence tests.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_node_rewrite.py
git commit -m "feat(rebrand): rewrite exact npm and cli names"
```

### Task 5: Load `keep_names` and protect rewrites

**Files:**
- Create: `src/template_press/rebrand/keep_names.py`
- Modify: `rules.py:239-252,322-330,1399`, `substitutions.py:185-211`, `engine.py` (`rewrite_with_row` callers)
- Test: `tests/rebrand/test_keep_names.py`

**Interfaces:**
- Consumes: `Identity`, `display_forms`.
- Produces:
  - `Rules.keep_names: tuple[str, ...] = ()`
  - `kept_spans(text: str, names: Sequence[str]) -> tuple[tuple[int, int], ...]`
  - `outside_kept(spans: Iterable[tuple[int, int]], kept: Sequence[tuple[int, int]]) -> list[tuple[int, int]]`, which drops only spans wholly inside a kept span
  - `disjoint_from_kept(span: tuple[int, int], kept: Sequence[tuple[int, int]]) -> bool`
  - `component_kept_spans(parts: Sequence[str], index: int, names: Sequence[str]) -> tuple[tuple[int, int], ...]`
  - `validate_keep_names(names: Sequence[str], source: Identity, dest: Identity) -> None`
  - `SubstitutionTable.keep_names: tuple[str, ...]`
  - `rewrite_with_row(row, text, *, keep_names: Sequence[str] = ()) -> str`

`keep_names.py` imports only the standard library and `identity`.

- [ ] **Step 1: Write failing tests**

```python
def test_kept_span_allows_subpath(): assert kept_spans("@a/b-c/sub", ["@a/b-c"]) == ((0, 6),)
def test_kept_span_rejects_longer_name(): assert kept_spans("@a/b-c-2", ["@a/b-c"]) == ()
def test_outside_kept_drops_contained(): assert outside_kept([(0, 4)], [(0, 6)]) == []
def test_outside_kept_retains_overlap(): assert outside_kept([(4, 8)], [(0, 6)]) == [(4, 8)]
def test_rewrite_preserves_kept_for_owner_repo_substring_and_replace_rows(...): assert "@acme/widget-extra" in out
def test_rewrite_still_changes_adjacent_identity(...): assert "@new/x @acme/widget-extra" == out
@pytest.mark.parametrize("bad", ["", "a\x00b", "<source npm_name>", "<dest repo_name>", "<display pascal form>"])
def test_invalid_keep_name_exits_2_without_writes(...): assert code == 2
def test_non_string_keep_names_exit_2(...): assert code == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_keep_names.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Build `kept_spans` from the exact-name pattern with the `npm_name` boundaries. `rewrite_with_row` must evaluate each row's pattern over the whole text, so boundaries see true neighbors, and replace only matches where `disjoint_from_kept` is true. With empty `keep_names`, it must take the existing code path unchanged. Add `keep_names` to `_RULES_KEYS`. Validate before any write.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_keep_names.py
git commit -m "feat(rules): protect declared keep names from rewrites"
```

### Task 6: Honor `keep_names` in every scan and report

**Files:**
- Modify: `substitutions.py:214-290` (`hunt_occurs`, `matching_hunts`), `doctor.py`, `regen.py:834-861`, `reset.py`, `verifier.py:540-660`, `verify_cli.py`, `receipt.py:153`, `cli.py`
- Test: `tests/rebrand/test_keep_names_end_to_end.py`

**Interfaces:**
- Consumes: all Task 5 helpers.
- Produces: `sibling_guidance(text: str, span: tuple[int, int]) -> str | None` in `keep_names.py`, built on `matcher.classify_occurrence`. The receipt gains a `keep_names` array only when non-empty.

- [ ] **Step 1: Write failing tests**

```python
def test_undeclared_sibling_exit_1_no_receipt(...): assert code == 1 and not receipt.exists()
def test_undeclared_sibling_error_suggests_keep_names(...): assert 'keep_names = ["@acme/widget-extra"]' in out
def test_declared_sibling_survives_press_and_verify(...): assert press == 0 and verify == 0 and sibling in package_json
def test_declared_sibling_survives_regeneration_scan(...): assert code == 0
def test_near_miss_still_fails(...): assert code == 1  # @acme/widget-extra-2
def test_kept_name_in_filename_and_symlink_survives(...): assert code == 0
def test_scoped_kept_name_across_path_components_survives(...): assert code == 0
def test_repeat_press_keeps_list_valid(...): assert second_press == 0 and second_verify == 0
def test_dry_run_and_receipt_list_kept_names(...): assert "@acme/widget-extra" in dry_run and receipt["keep_names"] == [sibling]
def test_stale_keep_name_warns_on_stderr_only(...): assert code == 0 and "keep_names" in err and json.loads(out)
def test_verifier_derives_kept_spans_from_rules(...): assert "keep_names" in verifier_imports and "substitutions" not in verifier_imports
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_keep_names_end_to_end.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Filter every `find_occurrences` result through `outside_kept`, and pass `rules.keep_names` into `verifier.scan`'s internal helpers from `Rules`, not from the table. Component scans use `component_kept_spans`. Boolean hunts must become false only when no occurrence remains outside a kept span. Keep the existing fast path when the list is empty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_keep_names_end_to_end.py
git commit -m "feat(verify): honor keep names across every scan"
```

### Task 7: First-class lockfile handling

**Files:**
- Modify: `src/template_press/rebrand/pathing.py:20`, `rules.py:820-835`, `engine.py:413` (docstring)
- Test: `tests/rebrand/test_node_lockfiles.py`

**Interfaces:**
- Produces: `regenerate_suggestion(file: str) -> str | None` in `rules.py`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("file", ["package-lock.json", "pnpm-lock.yaml"])
def test_declared_lockfile_is_verify_exempt(...): assert file in exempt
@pytest.mark.parametrize("file", ["package-lock.json", "pnpm-lock.yaml"])
def test_undeclared_lockfile_is_not_exempt(...): assert file not in exempt
def test_default_excludes_do_not_gain_pnpm(): assert "pnpm-lock.yaml" not in DEFAULT_RULES.exclude_files
def test_suggestion_npm(): assert '["npm", "install", "--package-lock-only", "--silent"]' in regenerate_suggestion("package-lock.json")
def test_suggestion_bun(): assert '["bun", "install", "--lockfile-only"]' in regenerate_suggestion("bun.lock")
def test_suggestion_pnpm(): assert '["pnpm", "install", "--lockfile-only"]' in regenerate_suggestion("pnpm-lock.yaml")
def test_preflight_prints_block_and_runs_nothing(...): assert code == 2 and "[[regenerate]]" in out and not marker.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_node_lockfiles.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Extend `REGENERATE_EXEMPTIBLE` and append the suggestion to the existing excluded-file preflight message. Update the engine docstring, which still names `package-lock.json` as non-exemptible.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand tests/rebrand/test_node_lockfiles.py
git commit -m "feat(regen): exempt declared npm and pnpm lockfiles"
```

### Task 8: Prove npm, Bun, and pnpm targets end to end

**Files:**
- Create: `tests/rebrand/test_node_targets.py`
- Modify: `.github/workflows/rebrand-matrix.yml`, `scripts/rebrand_matrix.sh`
- Test: `tests/rebrand/test_node_targets.py`

**Interfaces:**
- Consumes: all earlier behavior through the `press` CLI.
- Produces: `make_node_target(base: Path, manager: Literal["npm", "bun", "pnpm"]) -> Path`, local to the test file.

- [ ] **Step 1: Write the live tests**

Each fixture has an `example.test` identity, a scoped `npm_name`, a hyphenated `cli_name` with `bin/<cli>.js`, one pinned `typescript` dev dependency, a declared `[[regenerate]]`, a `test` script, and a `typecheck` script.

```python
@pytest.mark.live
@pytest.mark.parametrize("manager", ["npm", "bun"])
def test_real_target_presses_clean(manager, tmp_path):
    assert press_code == 0 and verify_code == 0 and receipt.exists()
    assert frozen_install == test_run == typecheck == 0


@pytest.mark.live
def test_real_pnpm_target_presses_clean(tmp_path): ...  # skip only when pnpm is absent


def test_ci_never_skips_required_managers(): ...  # missing npm or bun fails when CI is set
```

- [ ] **Step 2: Run them to verify current behavior**

Run: `uv run pytest tests/rebrand/test_node_targets.py -m live -q`
Expected: PASS after Tasks 1-7. Any failure is a defect to fix in the owning task's code.

- [ ] **Step 3: Wire CI**

Add `tests/rebrand/test_node_targets.py` to `scripts/rebrand_matrix.sh`. Add `actions/setup-node` to the matrix workflow using that workflow's existing action-pinning style. Do not add Node to `mise.toml` or `.flox`.

- [ ] **Step 4: Verify the matrix**

Run: `just matrix`
Expected: R1, R2, R3, npm, and Bun pass.

- [ ] **Step 5: Commit**

```bash
git add tests/rebrand/test_node_targets.py .github/workflows/rebrand-matrix.yml scripts/rebrand_matrix.sh
git commit -m "test(rebrand): prove npm and bun targets end to end"
```

### Task 9: Document, verify, and open the PR

**Files:**
- Modify: `.claude/skills/press-target/SKILL.md`, `docs/design/0006-external-target-model.md`, `docs/design/0008-identity-variants-and-replace-rules.md`, `docs/source/reference/cli.md`, `AGENTS.md`, `PROJECTS.md`, `projects/P14-typescript-bun-targets.md`

**Interfaces:**
- Consumes: final behavior.

- [ ] **Step 1: Update the docs**

Document `npm_name`, `cli_name`, `keep_names`, `package.json` discovery and precedence, and the lockfile table. Update "six required plus optional `display_name`" wherever it appears.

- [ ] **Step 2: Run the repository gates**

Run: `make check && just check && just matrix && uv run ruff format --check .`
Expected: all exit 0.

- [ ] **Step 3: Run real-world acceptance in a scratch copy only**

Clone the owner's real-world acceptance target over HTTPS into the session scratchpad. Press it, then run its install, test, typecheck, and build checks and `press verify`. Expected: all exit 0. Never push to it. Report any needed config change in the final message.

- [ ] **Step 4: Run the privacy gate**

Search `git diff origin/main...HEAD` for the acceptance target's identifying values from the session handoff. Keep that search pattern out of the repository.
Expected: no matches.

- [ ] **Step 5: Commit docs and project state**

Route status changes through the project-harness skills. Keep P14 at `[~]` until the PR merges.

```bash
git add .claude/skills/press-target/SKILL.md docs AGENTS.md PROJECTS.md projects/P14-typescript-bun-targets.md
git commit -m "docs: document typescript and bun targets"
```

- [ ] **Step 6: Push and open the PR without merging**

Run `git push -u origin feat/typescript-targets`, then create the PR to `main` with `gh pr create`. End the PR body with `https://claude.ai/code/session_01HuEtW7Y5qYixJQabGXsLxi`. Confirm it with `gh api repos/smorinlabs/template-press/pulls`. Do not merge or release.
