# Rust and Cargo Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make single-crate and workspace Cargo repositories first-class `press` targets through an optional role-keyed `cargo_names` identity table.

**Architecture:** `Identity` gains an immutable `cargo_names` tuple that stays out of the string-only `as_dict()`. A pure-stdlib `cargo_manifest.py` reads manifest facts, the substitution table gains boundary-exact Cargo rows in the shared longest-first order, and `verifier.py` derives its own hunts from `Identity`. `Cargo.lock` is regenerated through the existing target-declared `[[regenerate]]` mechanism.

**Tech Stack:** Python 3.13, stdlib `tomllib`, pytest, uv, just, Cargo for acceptance fixtures.

**Spec:** `docs/superpowers/specs/2026-11-22-rust-cargo-targets-design.md`

**Project:** P15

**Start gate:** Tasks 1-7 start only after `fix/hyphen-false-receipt`, `feat/explicit-target-languages`, and `feat/typescript-targets` have merged, in that order. Then rebase this branch on `origin/main`. Confirm these exact names exist and update this plan if any differ: the guard's `[rules]` key and Rust value, `Rules.keep_names`, `Discovered.source_kind`, `field_renames_paths`, and `regenerate_suggestion`.

## Global Constraints

- This branch does not change any existing target's outcome, except refusing a press that would leave a broken crate name.
- The language guard owns multi-language refusal. This branch adds no precedence between languages.
- The Python hyphenated-name false receipt is out of scope. Branch `fix/hyphen-false-receipt` owns it.
- Zero runtime dependencies.
- `verifier.py` must not import `substitutions`, `engine`, or `doctor`, or receive table data.
- Exit codes stay 0, 1, and 2. Every validation refusal exits 2 before any write. No receipt on a leak.
- Press adds no hidden regeneration command. `Cargo.lock` does not join default `exclude_files`.
- Role keys match `^[a-z][a-z0-9_]*$`. Cargo names match `^[A-Za-z][A-Za-z0-9_-]*$`.
- Cargo boundary is `(?<![A-Za-z0-9_-])VALUE(?![A-Za-z0-9_-])`.
- Fixtures use `example.test` values and no private names.
- Line length 88, strict typing in `src/`, Conventional Commits with lowercase subjects.
- Run `just check` before each commit. Run `just matrix` after the final rebrand change.
- Subagents run tests in the foreground with explicit timeouts, never in the background.

## Review Focus

1. A second press from the refreshed source config must succeed and bind to its receipt. Test in Task 1 and Task 7.
2. A `[lib] name` that differs from its package must be cross-checked and rewritten. Test in Task 3 and Task 7.
3. A renamed dependency (`core = { package = "acme-core", path = "../acme-core" }`) keeps its alias. Test in Task 2.
4. A workspace glob with `exclude`, and a member symlink leaving the target, must not read outside the root. Test in Task 3.
5. A declared Python target that excludes Rust must ignore even a malformed `Cargo.toml`. Test in Task 4.

---

### Task 0: Register the project

**Files:**
- Modify: `PROJECTS.md`
- Create: `projects/P15-rust-cargo-targets.md`

- [ ] **Step 1: Use `project-add`, then `project-refine`, to create P15.** Reference the spec and this plan, list Tasks 1-7 as `P15-T01`..`P15-T07`, and set status `[~]`. If `project-add` assigns another number because P13, P14, or P16 is not visible on this branch, correct it to P15.
- [ ] **Step 2: Verify.** Run `git log -1 --stat`. Expected: the commit contains `PROJECTS.md` and the P15 file.

### Task 1: Identity table and control-file round trip

**Files:**
- Modify: `src/template_press/rebrand/identity.py`, `config.py`, `receipt.py:147-150,557,839`
- Test: `tests/rebrand/test_cargo_identity.py`

**Interfaces:**
- Produces: `Identity.cargo_names: tuple[tuple[str, str], ...] = ()`, sorted by role, as the last dataclass field.
- Produces: `Identity.control_mapping() -> dict[str, str | dict[str, str]]`, equal to `as_dict_prompted()` plus `"cargo_names": {...}` only when non-empty.
- Produces: `cargo_ident(name: str) -> str`, replacing `-` with `_`.
- Produces: `cargo_name_pairs(source: Identity, dest: Identity) -> list[tuple[str, str, str]]`, returning `(tag, from, to)` with tags `cargo_exact_<role>` and `cargo_ident_<role>`, dropping an ident pair equal to its exact pair and unchanged pairs, longest `from` first.
- Produces: `is_cargo_field(field: str) -> bool` and `cargo_identity_problem(source: Identity, dest: Identity) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_absent_table_keeps_six_field_mapping(): ...  # control_mapping == as_dict_prompted
def test_loads_and_renders_table_round_trip(tmp_path): ...  # load(render(i)) == i
def test_rejects_bad_role_and_bad_name(
    tmp_path,
): ...  # ValidationError for "Core", "1x"
def test_rejects_non_string_table_value(tmp_path): ...
def test_problem_when_table_half_specified(): ...
def test_problem_when_role_sets_differ(): ...
def test_problem_when_ident_forms_collide(): ...  # "a-b" and "a_b"
def test_problem_when_destination_chains_into_other_source(): ...
def test_problem_when_package_name_is_not_a_map_value(): ...
def test_problem_when_package_destination_differs_from_role_destination(): ...
def test_pairs_drop_duplicate_spelling_for_single_word_name():
    assert [p[1] for p in cargo_name_pairs(src("core"), dst("base"))] == ["core"]


def test_receipt_binding_accepts_table_and_rejects_changed_table(tmp_path): ...
def test_receipt_without_table_stays_valid_for_six_field_identity(tmp_path): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_cargo_identity.py -v`
Expected: FAIL with an import error for `cargo_name_pairs`.

- [ ] **Step 3: Implement.** `load_identity_toml` accepts only a `cargo_names` table beyond the string fields. `render_source_config` and `_identity_table` emit `[identity.cargo_names]` or `[press.<name>.cargo_names]` after the scalar keys. Both receipt comparisons use `control_mapping()`.
- [ ] **Step 4: Run** `uv run pytest tests/rebrand/test_cargo_identity.py tests/rebrand/test_identity.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): add cargo_names identity table`.

### Task 2: Rewrite rows

**Files:**
- Modify: `src/template_press/rebrand/identity.py:205-209` (`token_pattern`), `substitutions.py:_identity_hunts,_identity_rows,_validate_rows`, `engine.py:_raw_replacement_pairs`
- Test: `tests/rebrand/test_cargo_substitutions.py`

**Interfaces:**
- Consumes: `cargo_name_pairs`, `is_cargo_field` from Task 1.
- Produces: rows with IDs `identity:cargo_exact_<role>` and `identity:cargo_ident_<role>`, rewriting content and path.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    "text,want",
    [
        ("acme-core/serde", "zeta-core/serde"),
        ("dep:acme-core", "dep:zeta-core"),
        ("acme_core::hi()", "zeta_core::hi()"),
        ("acme-core-extra", "acme-core-extra"),
        (
            'core = { package = "acme-core", path = "../acme-core" }',
            'core = { package = "zeta-core", path = "../zeta-core" }',
        ),
    ],
)
def test_cargo_row_boundaries(text, want): ...
def test_longer_cargo_row_precedes_shorter_identity_row(): ...
def test_equal_length_cargo_row_owns_merged_matcher(): ...
def test_app_name_cannot_rewrite_front_of_mapped_ident(): ...  # app acme, acme_core
def test_package_name_row_merges_with_primary_ident_row(): ...
def test_cargo_rows_rename_crate_directory(tmp_path): ...
def test_engine_pairs_match_table_rows_for_cargo_identity(): ...
def test_identity_without_table_compiles_identical_rows(): ...
def test_cargo_npm_and_cli_rows_sort_longest_first(): ...
def test_keep_names_protects_cargo_sibling(tmp_path): ...  # acme-core-extra
```

- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_cargo_substitutions.py -v`. Expected: FAIL on row order and boundaries.
- [ ] **Step 3: Implement.** Extend TypeScript's `_identity_rows` key `(-len(from_value), field != "npm_name")` so Cargo exact-name fields also win an equal-length tie, and their order survives `_normalize_rows`. Extend `field_renames_paths` for Cargo fields and use it in `_identity_hunts` and rewrite surfaces. Add each destination spelling to `_validate_rows` stability sinks. Keep the sort for targets without exact-name fields unchanged.
- [ ] **Step 4: Run** `uv run pytest tests/rebrand/test_cargo_substitutions.py tests/rebrand/test_substitutions.py tests/rebrand/test_substitution_safety.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): rewrite both spellings of cargo names`.

### Task 3: Cargo manifest reader

**Files:**
- Create: `src/template_press/rebrand/cargo_manifest.py`
- Test: `tests/rebrand/test_cargo_manifest.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CargoFacts:
    names: tuple[str, ...]  # package, lib, and bin names, sorted, unique
    packages: tuple[str, ...]  # package names in manifest order
    bins: tuple[str, ...]  # sorted, unique
    primary: str | None  # root package; None for a virtual manifest
    author: str | None
    email: str | None
    repository: str | None
    external_dependencies: tuple[str, ...]  # resolved package names, non-local


def read_cargo_facts(target: Path) -> CargoFacts: ...  # raises ValidationError
```

- [ ] **Step 1: Write the failing tests**

```python
def test_single_crate_auto_bin_and_lib_name(tmp_path): ...
def test_autobins_false_ignores_src_main_and_src_bin(tmp_path): ...
def test_src_bin_file_and_directory_stems(tmp_path): ...
def test_virtual_workspace_glob_with_exclude(tmp_path): ...
def test_root_package_and_members_are_both_read(tmp_path): ...
def test_authors_and_repository_inherit_from_workspace(tmp_path): ...
def test_member_outside_root_is_refused(tmp_path): ...
def test_symlinked_member_leaving_root_is_refused(tmp_path): ...
def test_malformed_manifest_raises_validation_error(tmp_path): ...
def test_external_dependency_honors_package_key_and_target_tables(tmp_path): ...
def test_path_and_workspace_dependencies_are_local(tmp_path): ...
def test_examples_tests_and_benches_are_not_names(tmp_path): ...
def test_symlinked_root_manifest_raises_validation_error(tmp_path): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_cargo_manifest.py -v`. Expected: FAIL with a module import error.
- [ ] **Step 3: Implement.** Expand member globs with `Path.glob`, validate each through `safety.assert_under_root`, and read manifests as regular UTF-8 files. A workspace-dependency entry resolves through `[workspace.dependencies]`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): read cargo manifest identity facts`.

### Task 4: Discovery gates and proposal

**Files:**
- Modify: `src/template_press/rebrand/discovery.py`, `cli.py:_resolve_source,main`, `verify_cli.py:_preflight`
- Test: `tests/rebrand/test_cargo_discovery.py`

**Interfaces:**
- Consumes: `CargoFacts`, `read_cargo_facts`, `cargo_identity_problem`, the guard's active-language result, `Rules.keep_names`, and `Discovered.source_kind`.
- Produces: `cargo_problems(target: Path, source: Identity, dest: Identity | None) -> list[str]`, `cargo_warnings(target: Path, source: Identity) -> list[str]`, and `cargo_table_hint(facts: CargoFacts) -> str`, all in `discovery.py`.
- Produces: `"cargo"` as a `Discovered.source_kind` value.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_map_broken_crate_name_exits_2_with_paste_ready_table(tmp_path): ...
def test_no_map_crate_equal_to_repo_name_continues(tmp_path): ...
def test_no_map_unrelated_crate_warns_on_stderr(tmp_path): ...
def test_no_map_name_in_keep_names_does_not_refuse(tmp_path): ...
def test_undeclared_discovered_name_exits_2(tmp_path): ...
def test_declared_name_missing_from_manifests_exits_2(tmp_path): ...
def test_third_party_dependency_with_mapped_name_exits_2(tmp_path): ...
def test_no_python_layout_check_for_cargo_target(tmp_path): ...
def test_malformed_manifest_warns_without_map_and_exits_2_with_map(tmp_path): ...
def test_declared_python_excluding_rust_ignores_malformed_cargo_toml(tmp_path): ...
def test_declared_python_and_rust_checks_each_manifest(tmp_path): ...
def test_declared_rust_and_node_checks_each_manifest(tmp_path): ...
def test_no_config_single_crate_proposes_table(tmp_path): ...
def test_no_config_library_only_proposes_app_name_from_package(tmp_path): ...
def test_no_config_virtual_workspace_exits_2(tmp_path): ...
def test_exit_2_leaves_git_tree_clean(tmp_path): ...
def test_verify_preflight_reports_cargo_problems(tmp_path): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_cargo_discovery.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Read Cargo manifests only when the guard reports Rust as active. Limit the layout mismatch to `source_kind == "python"`. Call `cargo_problems` and print `cargo_warnings` to stderr in `_resolve_source` and `_preflight`. Without a map, refuse only a name that contains a changing identity value and that no identity row rewrites whole. Call `cargo_identity_problem` beside `display_name_problem`.
- [ ] **Step 4: Run** `uv run pytest tests/rebrand/test_cargo_discovery.py tests/rebrand/test_discovery.py tests/rebrand/test_cli.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): cross-check cargo names against manifests`.

### Task 5: Independent verify and synthesis

**Files:**
- Modify: `src/template_press/rebrand/verifier.py:_changed_fields`, `synthesize.py:synthesize_dest`
- Test: `tests/rebrand/test_cargo_verify.py`

**Interfaces:**
- Consumes: `Identity.cargo_names`, `cargo_ident`.
- Produces: `_changed_fields` also returns `(f"cargo_exact_{role}", source_name)` when the role's value changed. The paranoid matcher treats `-` and `_` as equal, so one hunt covers both spellings.
- Produces: `synthesize_dest` returns an identity with synthetic `cargo_names`.

- [ ] **Step 1: Write the failing tests**

```python
def test_verifier_flags_hyphen_and_underscore_leaks(tmp_path): ...
def test_verifier_has_one_finding_per_occurrence_for_a_role(tmp_path): ...
def test_verifier_import_closure_is_unchanged(): ...
def test_synthesized_primary_matches_package_destination(): ...
def test_synthesized_names_preserve_hyphen_shape_and_contain_no_source_token(): ...
def test_synthesis_is_deterministic(): ...
def test_six_field_synthesis_is_byte_identical(): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/rebrand/test_cargo_verify.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement synthesis after the existing path.** The primary role's destination is `dest.package_name`, using `-` when the source name has a hyphen. Other roles use `<primary>-x<index>` or `<primary>_x<index>` by source shape, so role text never reaches a destination. Pass every Cargo source name into `_source_variants`.
- [ ] **Step 4: Run** `uv run pytest tests/rebrand/test_cargo_verify.py tests/rebrand/test_verifier.py tests/rebrand/test_verifier_independence.py tests/rebrand/test_synthesize.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): verify cargo names independently`.

### Task 6: Lockfile declaration

**Files:**
- Modify: `src/template_press/rebrand/pathing.py:20`, `rules.py:regenerate_suggestion`, `discovery.py:cargo_problems`
- Test: `tests/rebrand/test_cargo_lockfile.py`

**Interfaces:**
- Consumes: `cargo_problems`, `regenerate_suggestion`.
- Produces: `REGENERATE_EXEMPTIBLE` containing `Cargo.lock`, and `regenerate_suggestion("Cargo.lock")` returning the exact block in the spec.

- [ ] **Step 1: Write the failing tests**

```python
def test_cargo_lock_is_exempt_only_when_declared(): ...
def test_cargo_lock_is_not_a_default_exclude(): ...
def test_tracked_lock_without_regeneration_exits_2_with_hint(tmp_path): ...
def test_untracked_or_absent_lock_needs_no_declaration(tmp_path): ...
def test_declared_python_excluding_rust_ignores_cargo_lock(tmp_path): ...
@pytest.mark.slow
def test_update_workspace_preserves_vendored_version(tmp_path): ...  # 1.0.0 stays
```

- [ ] **Step 2: Run** `uv run pytest -m "" tests/rebrand/test_cargo_lockfile.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `cargo_problems` takes `rules: Rules` as a fourth argument in this task. Update both callers. Tracked state comes from the existing surface snapshot.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rebrand): support declared cargo lock regeneration`.

### Task 7: Acceptance, CI, and docs

**Files:**
- Create: `tests/rebrand/test_cargo_acceptance.py`
- Modify: `.github/workflows/rebrand-matrix.yml`, `scripts/rebrand_matrix.sh`, `.claude/skills/press-target/SKILL.md`, `AGENTS.md` (Running the press), `docs/design/0008-identity-variants-and-replace-rules.md`

**Interfaces:**
- Consumes: the whole press CLI through `template_press.rebrand.cli.main` and `verify_cli`.

- [ ] **Step 1: Write the failing acceptance tests, marked `slow`**

```python
@pytest.fixture
def cargo_or_skip():
    # Missing cargo: fail when CI is set, otherwise pytest.skip with the reason.
    ...


@pytest.mark.slow
@pytest.mark.parametrize("shape", ["single_crate", "workspace"])
def test_press_check_test_verify(shape, tmp_path, cargo_or_skip):
    target = build_fixture(shape, tmp_path)  # includes a [lib] name differing case
    assert press(target, answers(shape)) == 0
    assert run("cargo", "check", "--locked", "--offline", cwd=target) == 0
    assert run("cargo", "test", "--offline", cwd=target) == 0
    assert verify(target) == 0
    assert source_tokens_absent(target)


@pytest.mark.slow
def test_second_press_from_refreshed_source(tmp_path, cargo_or_skip): ...
```

- [ ] **Step 2: Run** `uv run pytest -m "" tests/rebrand/test_cargo_acceptance.py -v`. Fix any integration gap in the owning module. Expected after fixes: PASS.
- [ ] **Step 3: Update CI and docs.** Add this file with `-m slow` to `scripts/rebrand_matrix.sh`, and provision Cargo in the matrix workflow using its existing action-pinning style. Do not add Cargo to `mise.toml` or `.flox`. Document `cargo_names`, Rust in the language declaration, `keep_names` for sibling crates, the lockfile block, and the `CARGO_HOME` limitation.
- [ ] **Step 4: Run gates.** Run `just check`, then `just matrix`, each with a foreground timeout. Expected: both exit 0. Run `uv run ruff format --check .` for Markdown fences.
- [ ] **Step 5: Commit** `test(rebrand): prove cargo targets end to end`, flip P15 tasks through `project-refine`, then push and open the PR to `main`. Do not merge.
