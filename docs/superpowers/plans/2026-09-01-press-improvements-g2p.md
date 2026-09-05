# template-press improvements (gmail2pdf-driven) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the nine decided engine changes (E1, E2, E3, E4+E11, E5, E8, E9, E10) in three risk-ordered PR groups, each verified by `just check` and `just matrix`.

**Architecture:** PR1 changes no press behavior (diagnostics, warnings, docs, tests). PR2 relaxes one guard under an exact rule. PR3 adds three declared mechanisms — `[[edit]]`, `[[clean]]`, `[[remove]] dir` — each as its own PR, each reusing the existing declared-command runner and receipt/plan/verify plumbing. Every mutation stays declared, plan-visible, receipted, and post-checked; `press verify` semantics never change.

**Tech Stack:** Python 3.13 stdlib only (engine has zero runtime deps), pytest, ruff, ty, `just`, lefthook. Tests live in `tests/rebrand/`; fixtures `src_target`, `SOURCE`, `DEST` in `tests/rebrand/conftest.py`; CLI helpers `write_source_config`, `write_answers` in `tests/rebrand/test_cli.py`.

**Spec:** `docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md` (decisions D-E1…E11; review constraints; parked blueprint items). Adversarial reviews under `docs/superpowers/specs/reviews-2026-09-01/`.

## Global Constraints

- Branch `fork/press-improve-g2p` in worktree `~/c/template-press-pr90-fork-press-improve-g2p`; each PR group gets its own branch from `origin/main` via `git worktree add`; merge with a merge commit (`gh pr merge --merge`); never push to `main`.
- After ANY change to `src/template_press/rebrand/`, run `just matrix` (R1/R2/R3 acceptance matrix) — AGENTS.md rule.
- Gates before every commit: `just check` (ruff check/format, ty over `src/template_press/`, tests). Hooks: commit-msg commitlint (lowercase conventional subject), pre-commit gitleaks/codespell/ruff/taplo, pre-push gitleaks + bandit.
- Commit messages: Conventional Commits, lowercase subject; body ends with `Claude-Session: https://claude.ai/code/session_01QwBvPLRhrqAA6sW6gWhx3s`.
- Exit-code contract: `2` = precondition/config refusal, nothing written; `1` = applied but leaks found, no receipt; `0` = verified, receipt written. No new exit codes.
- Zero runtime dependencies: no `tomlkit`, no third-party imports in `src/`.
- "Dry-run refuses exactly what apply refuses" (`docs/source/reference/cli.md:40`) is inviolable.
- `mismatches()` in `discovery.py` keeps its semantics (used by `press verify`, `verify_cli.py:225-226`).
- New root tables: add to `_ROOT_KEYS` (`rules.py:264`) — `"edit"`, `"clean"`; unknown keys still fail loud.
- Receipt: one table per mechanism (`receipt.py:88-121`); readers stay tolerant of unknown keys.
- Field names, flags, and message substrings below are the spec's values verbatim; keep them.
- PROJECTS.md changes go through the `project-add` skill (Task 0), never hand-edits.

---

## PR group 0 — tracking

### Task 0: Register projects P09–P12

**Files:** `PROJECTS.md`, `projects/P09-…md` … `projects/P12-…md` (created by the skill)

- [ ] **Step 1:** Run the `project-add` skill four times with these titles and one-line goals: P09 "Declared in-place edit ([[edit]]) + command-phase snapshot gate" (spec E4, E11); P10 "Declared pre-press clean ([[clean]] paths, `press clean`)" (E10); P11 "Directory removals ([[remove]] dir) and removal phase" (E5c); P12 "Origin guard relaxation, closure diagnostics, warnings and docs" (E1, E2, E3, E5a/b/d, E8, E9). Each run commits its stub.
- [ ] **Step 2:** `git log --oneline -4` shows four `docs(projects): …` commits.

---

## PR group 1 — no behavior change (P12)

### Task 1: E2 — aggregate the rename-closure refusal

**Files:**
- Modify: `src/template_press/rebrand/substitutions.py:505-567` (`_prefix_closure`)
- Modify: `src/template_press/rebrand/safety.py` (new `RenameClosureUnauthorized(SafetyError)`)
- Test: `tests/rebrand/test_substitution_safety.py`

**Interfaces:**
- Produces: `class RenameClosureUnauthorized(SafetyError)` with attributes `code: str = "rename_closure_unauthorized"`, `source_prefix: str`, `findings: tuple[tuple[str, str], ...]` (kind ∈ {"absent", "empty-dir"}, posix path), `total: int`, `truncated: bool`, `phase: str` ("plan" | "apply"). `str(exc)` keeps the substring `absent from the authorized surface`.

- [ ] **Step 1: Write the failing test**

```python
def test_prefix_closure_error_lists_every_ignored_descendant(src_target: Path) -> None:
    _exclude_without_identity(src_target, "src/*/ignored*.txt")
    pkg = src_target / "src" / "demo_widget"
    (pkg / "ignored-a.txt").write_text("a\n", encoding="utf-8")
    (pkg / "ignored-b.txt").write_text("b\n", encoding="utf-8")
    (pkg / "empty").mkdir()
    with pytest.raises(SafetyError, match="absent from the authorized surface") as info:
        build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    exc = info.value
    assert exc.code == "rename_closure_unauthorized"
    assert exc.source_prefix == "src/demo_widget"
    assert {p for _, p in exc.findings} == {
        "src/demo_widget/ignored-a.txt",
        "src/demo_widget/ignored-b.txt",
        "src/demo_widget/empty",
    }
    assert exc.total == 3 and exc.truncated is False
    assert {k for k, _ in exc.findings} == {"absent", "empty-dir"}
```

- [ ] **Step 2:** `uv run pytest tests/rebrand/test_substitution_safety.py -k lists_every -q` → FAIL (`AttributeError: code`).
- [ ] **Step 3: Implement.** In `_prefix_closure`: keep the gitlink pre-check (`:513-522`) and the `missing`/`OSError`/kind-mismatch raises (`:532-536`, `:541-545`, `:560-564`) immediate. Replace the two `raise SafetyError` sites for "absent from inventory" (`:555-559`) and "uninventoried empty directory" (`:548-552`) with `findings.append(("absent", rel))` / `findings.append(("empty-dir", rel))`, returning 1 for the empty-dir case so the parent's `child_count` logic is unchanged. After `walk(root)`: if `findings`, raise `RenameClosureUnauthorized(source_prefix, findings, phase)` where the message renders `sorted(findings)[:20]`, `total`, and `… (N more)` when truncated, and contains `absent from the authorized surface inventory`. Render each path with `repr()` (safe for newlines/control characters).
- [ ] **Step 4:** Focused test passes; existing `test_prefix_closure_refuses_ignored_untracked_descendant` (`:78`), `…uninventoried_empty_directory` (`:88`), gitlink (`:96`), and live-divergence (`:107`) still pass: `uv run pytest tests/rebrand/test_substitution_safety.py -q`.
- [ ] **Step 5: Priority tests.** Add `test_prefix_closure_gitlink_wins_over_ignored_leaves` (gitlink + two ignored files → `match="would carry gitlink"`) and `test_prefix_closure_structural_refusal_is_immediate` (monkeypatch `_node_kind` to return `"missing"` for one child → `match="closure changed during planning"`, no `RenameClosureUnauthorized`). Run → PASS.
- [ ] **Step 6:** Commit: `fix(substitutions): report every uninventoried path in one closure refusal`

### Task 2: E2 — remedy text, `press clean` hint, and `--diagnostics-json`

**Files:**
- Modify: `src/template_press/rebrand/cli.py` (where `SafetyError` from planning is caught and printed — the `except SafetyError` around `build_plan`, ~`:371-378`)
- Modify: `src/template_press/rebrand/safety.py` (`RenameClosureUnauthorized.remedy_argv(target) -> tuple[list[str], list[str]]`)
- Test: `tests/rebrand/test_cli.py`

**Interfaces:**
- Consumes: `RenameClosureUnauthorized` from Task 1.
- Produces: CLI flag `--diagnostics-json` (opt-in); on a structured refusal prints one JSON object `{"schema": 1, "code": …, "source_prefix": …, "findings": [{"kind","path"}], "total", "truncated", "phase", "preview_argv": [...], "remove_argv": [...]}` to stdout instead of prose; exit 2 either way. Paths encoded with `surrogateescape` → `\uXXXX`-safe via `json.dumps(ensure_ascii=True)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_closure_refusal_prints_remedy_and_exits_2(src_target, tmp_path, capsys):
    write_source_config(src_target)
    (src_target / "src" / "demo_widget" / "__pycache__").mkdir()
    (src_target / "src" / "demo_widget" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 2
    assert "absent from the authorized surface" in out
    assert (
        "clean -ndX -- src/demo_widget" in out
        and "clean -fdX -- src/demo_widget" in out
    )
    assert "--literal-pathspecs" in out
    assert "broader than" in out  # destructive label
    assert "(dry run" not in out  # never the success terminator
    assert not (src_target / RECEIPT_REL).exists()


def test_closure_refusal_diagnostics_json(src_target, tmp_path, capsys):
    write_source_config(src_target)
    weird = src_target / "src" / "demo_widget" / "__pycache__"
    weird.mkdir()
    (weird / "a\nb.pyc").write_bytes(b"\0")
    answers = write_answers(tmp_path)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(answers),
            "--dry-run",
            "--diagnostics-json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["code"] == "rename_closure_unauthorized"
    assert payload["findings"][0]["path"] == "src/demo_widget/__pycache__/a\nb.pyc"
    assert payload["preview_argv"][:4] == [
        "git",
        "--literal-pathspecs",
        "-C",
        str(src_target),
    ]
```

- [ ] **Step 2:** Run both → FAIL (no flag; no remedy text).
- [ ] **Step 3: Implement.** `remedy_argv(target)` returns `(["git","--literal-pathspecs","-C",str(target),"clean","-ndX","--",prefix], [... "-fdX" ...])`. In `cli.py`'s planning `except SafetyError as exc:` branch: if `isinstance(exc, RenameClosureUnauthorized)` and `args.diagnostics_json` → print the JSON; else print `str(exc)` then `preview: <shlex.join(preview)>`, `remove:  <shlex.join(remove)>`, and the line `(destructive, and broader than the paths listed — run only if the preview shows nothing you keep)`. Add `--diagnostics-json` to the argparser (help: "on a structured refusal, print a JSON diagnostic instead of prose; exit code unchanged"). Apply (non-dry-run) takes the same branch — assert with a third test that omits `--dry-run` and checks README is unchanged.
- [ ] **Step 4:** Tests pass. `uv run pytest tests/rebrand/test_cli.py -k closure -q`.
- [ ] **Step 5:** Docs: `docs/source/reference/cli.md` — under the `--dry-run` paragraph (~`:40`) add a "Structured refusals" paragraph naming `--diagnostics-json`, `code = rename_closure_unauthorized`, and the remedy semantics (`-X` only removes ignored files; broader than the listed blockers). Update `docs/design/0009-substitution-table.md:345-352` wording ("first offending path" → "every offending path").
- [ ] **Step 6:** Commit: `feat(cli): remedy argv and --diagnostics-json for closure refusals`

### Task 3: E5(a)+(b) — declared-removal coverage warning and plan counts

**Files:**
- Modify: `src/template_press/rebrand/remove.py:102-108` (`render_remove_plan`)
- Modify: `src/template_press/rebrand/engine.py` (plan build, where rewrite candidates per file are known) — add `removal_coverage_warnings(rules, rewrite_paths, tracked_paths) -> list[str]`
- Modify: `src/template_press/rebrand/cli.py` (print warnings after the plan, before `(dry run …)`)
- Test: `tests/rebrand/test_remove_rules.py`

- [ ] **Step 1: Failing tests**

```python
def test_plan_warns_when_a_rewritten_directory_has_no_removal(
    src_target, tmp_path, capsys
):
    hist = src_target / "projects"
    hist.mkdir()
    (hist / "P01.md").write_text("demo_widget history\n", encoding="utf-8")
    (hist / "P02.md").write_text("more demo_widget\n", encoding="utf-8")
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "hist")
    write_source_config(src_target)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "warning: 2 tracked files under projects/ will be rewritten" in out
    assert "declare [[remove]] or [rules] verify_ignore" in out


def test_no_warning_when_directory_is_declared_removed(src_target, tmp_path, capsys):
    hist = src_target / "projects"
    hist.mkdir()
    (hist / "P01.md").write_text("demo_widget history\n", encoding="utf-8")
    (hist / "P02.md").write_text("more demo_widget\n", encoding="utf-8")
    _write_rules(
        src_target,
        '[[remove]]\nfile = "projects/P01.md"\nreason = "hist"\n'
        '[[remove]]\nfile = "projects/P02.md"\nreason = "hist"\n',
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "hist")
    write_source_config(src_target)
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "warning:" not in out
    assert "removing 2 files under projects/" in out  # (b)
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Warning rule: group rewrite candidates by top-level directory (excluding `src/`, `tests/`, and any directory containing the package — the code's own directories are expected to be rewritten); for a directory where every tracked file is a rewrite candidate and no `[[remove]]`/`[[reset]]` rule targets a path under it and the directory name is not in `verify_ignore`, emit `warning: N tracked files under <dir>/ will be rewritten to the new identity and no rule removes or resets them — declare [[remove]] or [rules] verify_ignore if this is template history`. Counts: `render_remove_plan` groups `rules.remove` by parent directory and appends `removing N files under <dir>/` lines. Non-fatal; printed on both dry-run and apply.
- [ ] **Step 4:** Tests pass; `just matrix` green (R3 self-press will now print warnings for `projects/` and `docs/research/` — expected until Task 4).
- [ ] **Step 5:** Commit: `feat(plan): warn on rewritten directories with no declared removal; show removal counts`

### Task 4: E5(d) — declare this repo's own template-history removals

**Files:** `press/press-rules.toml`

- [ ] **Step 1:** Add one `[[remove]]` per file under `projects/` (P01–P08 files) and `docs/research/*.md`, each with `reason = "template-press project history is engine history, not a fork's"` (research: "engine research notes"). Do NOT remove `PROJECTS.md` (add a `[[reset]]` with a stub containing only the status-legend table — copy lines 1–20 of the current file into the stub).
- [ ] **Step 2:** `just matrix` → R3 green and the Task 3 warnings gone from the R3 plan. `uv run press verify --target .` green.
- [ ] **Step 3:** Commit: `chore(press): declare removal of engine project history on self-press`

### Task 5: E9(b) — prefix-only occurrence warning

**Files:**
- Modify: `src/template_press/rebrand/doctor.py` or `engine.py` plan stage — new `prefix_only_warnings(corpus, source) -> list[str]` reusing `find_occurrences` (`matcher.py`)
- Test: `tests/rebrand/test_matcher.py` (unit) + `tests/rebrand/test_cli.py` (plan output)

- [ ] **Step 1: Failing test**

```python
def test_plan_warns_when_source_value_occurs_only_as_prefix(
    src_target, tmp_path, capsys
):
    for rel in ("README.md", "pyproject.toml"):
        p = src_target / rel
        p.write_text(
            p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
            encoding="utf-8",
        )
    _git(src_target, "commit", "-qam", "renamed upstream")
    write_source_config(src_target)  # still declares repo_name = demo-widget
    _git(
        src_target, "remote", "remove", "origin"
    )  # no origin: guard skips owner/repo_name
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "warning: repo_name 'demo-widget' occurs only as a prefix of 'demo-widget-2'"
        in out
    )
    assert "update press/press-source.toml" in out
```

- [ ] **Step 2:** FAIL. **Step 3: Implement.** For each changed identity field: collect occurrences; classify each as whole-token (followed by end/non-`[-_.]`-separator) or prefix (followed by `[-_.]` + alphanumerics). If prefix count > 0 and whole-token count == 0 → warning naming the field, value, the most common longer token, and the count. Skip `app_name` (hyphen already excluded on its right, `identity.py:205`). **Step 4:** PASS; `just matrix` green (no warnings expected on R1–R3). **Step 5:** Commit: `feat(plan): warn when a source value occurs only as a prefix of a longer token`

### Task 6: E8 — dir-only-ignore near-miss hint in verify findings

**Files:**
- Modify: `src/template_press/rebrand/verifier.py` (finding rendering) or `verify_cli.py` report stage — new `ignore_near_miss(target, rel) -> str | None`
- Test: `tests/rebrand/test_verifier.py` (`@requires_symlink`)

- [ ] **Step 1: Failing test**

```python
@requires_symlink
def test_untracked_symlink_matching_dir_only_ignore_pattern_is_scanned(
    src_target, tmp_path
):
    (src_target / ".gitignore").write_text(
        ".venv/\n__pycache__/\nnode_modules/\n", encoding="utf-8"
    )
    _git(src_target, "commit", "-qam", "ignore")
    outside = tmp_path / "press" / "node_modules"  # link text contains app_name 'press'
    outside.mkdir(parents=True)
    (src_target / "node_modules").symlink_to(outside)
    snapshot = capture_surface_snapshot(src_target)
    assert any(e.rel.as_posix() == "node_modules" for e in snapshot.entries)
    findings = scan_target(
        src_target, SOURCE, DEST, DEFAULT_RULES
    )  # existing verifier entry point
    f = next(x for x in findings if x.where == "symlink" and x.field == "app_name")
    assert "matches directories only" in f.note
    assert "node_modules/" in f.note and "git add -A" in f.note
```

- [ ] **Step 2:** FAIL. **Step 3: Implement.** For findings whose entry is untracked: run `git check-ignore --no-index -v -- <rel>` and `-- <rel>/` via the existing `_run_git` helper; if the first returns 1 and the second returns 0 with a pattern, attach `note = "this untracked entry is not ignored — <file>:<line> pattern '<pat>' matches directories only. git add -A would commit it. Ignore it without the trailing slash, remove it, or list its name under verify_ignore."`. Render the note under the finding in both prose and JSON output. Pass/fail unchanged. **Step 4:** PASS. **Step 5:** Docs: `cli.md` "The ignore set" (~`:49`) trailing-slash note; `.claude/skills/press-target/SKILL.md` troubleshooting: worktrees use `bun install --frozen-lockfile`. **Step 6:** Commit: `feat(verify): explain dir-only ignore near-misses on untracked findings`

### Task 7: E3 — docs + `[[regenerate]]` boundary test

**Files:** `.claude/skills/press-target/SKILL.md:40-45`, `docs/source/reference/cli.md:82-86`, `tests/rebrand/test_verify_exemption.py`

- [ ] **Step 1: Failing test**

```python
def test_regenerate_against_identity_bearing_source_file_is_refused(src_target):
    _write_rules(
        src_target,
        '[rules]\nextra_exclude_files = ["src/demo_widget/cli.py"]\n'
        '[[regenerate]]\nfile = "src/demo_widget/cli.py"\ncommand = ["ruff", "format", "src"]\n',
    )
    with pytest.raises((ValidationError, SafetyError)):
        build_plan(src_target, SOURCE, DEST, load_rules(src_target))
```
If this passes today because the refusal happens at the excluded-file preflight (`regen.py:448-479`) rather than at rules load, keep the test as a pin of whichever layer refuses and assert the message mentions the file.
- [ ] **Step 2:** Run; if it already passes, that is the pin — proceed. **Step 3:** Apply the two docs edits exactly as in spec §E3 (SKILL.md step 6 formatter sentence; `cli.md` "one rebuilt output … not a hook for repo-wide tools" paragraph). **Step 4:** Commit: `docs(press): formatter runs in the target after the press; regenerate is one output`

### Task 8: PR1 close — `just check`, `just matrix`, PR

- [ ] `just check` and `just matrix` green; `uv run press verify --target .` green.
- [ ] Push branch; `gh pr create` titled `feat: closure diagnostics, removal coverage warnings, verify hints (P12 part 1)`; body lists E2, E3, E5a/b/d, E8, E9 and links the spec; merge with `--merge` after review.

---

## PR group 2 — the origin guard (P12)

### Task 9: E1 — hoist answers, per-field relaxation, notice, receipt row

**Files:**
- Modify: `src/template_press/rebrand/cli.py:132-177` (`_resolve_source`) and `:220-246` (call order)
- Modify: `src/template_press/rebrand/receipt.py` (`[press] origin_named_destination = [...]`)
- Test: `tests/rebrand/test_cli.py`

**Interfaces:**
- Produces: `_resolve_source(target, override, accept_discovery, dest: Identity | None, accept_origin_mismatch: bool = False) -> tuple[Identity, bool, OriginDecision] | int` where `OriginDecision` has `named_destination: tuple[str, ...]` and `mismatch_accepted: tuple[str, ...]`.

- [ ] **Step 1: Failing tests**

```python
def _set_origin(target: Path, url: str) -> None:
    _git(target, "remote", "set-url", "origin", url)


def test_origin_already_names_destination_is_accepted_with_notice(
    src_target, tmp_path, capsys
):
    write_source_config(src_target)
    _set_origin(src_target, "https://github.com/potatolabs/potato-launcher.git")
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "notice: repo_name: origin already names the destination ('potato-launcher')"
        in out
    )
    assert "notice: owner: origin already names the destination ('potatolabs')" in out


def test_origin_naming_third_repo_still_exits_2(src_target, tmp_path, capsys):
    write_source_config(src_target)
    _set_origin(src_target, "https://github.com/someone/else.git")
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 2 and "repo_name" in out and "owner" in out
    assert not (src_target / RECEIPT_REL).exists()


def test_receipt_records_origin_relaxation(src_target, tmp_path):
    write_source_config(src_target)
    _set_origin(src_target, "https://github.com/potatolabs/potato-launcher.git")
    assert (
        main(["--target", str(src_target), "--config", str(write_answers(tmp_path))])
        == 0
    )
    receipt = (src_target / RECEIPT_REL).read_text(encoding="utf-8")
    assert 'origin_named_destination = ["owner", "repo_name"]' in receipt


def test_documented_blind_spot_stale_repo_name_with_destination_origin(
    src_target, tmp_path
):
    # DOCUMENTED ACCEPTANCE (spec E1/E9): template renamed upstream to demo-widget-2, source-config
    # stale, origin already the destination → accepted. A change here must be deliberate.
    for rel in ("README.md",):
        p = src_target / rel
        p.write_text(
            p.read_text(encoding="utf-8").replace("demo-widget", "demo-widget-2"),
            encoding="utf-8",
        )
    _git(src_target, "commit", "-qam", "renamed upstream")
    write_source_config(src_target)
    _set_origin(src_target, "https://github.com/potatolabs/potato-launcher.git")
    assert (
        main(
            [
                "--target",
                str(src_target),
                "--config",
                str(write_answers(tmp_path)),
                "--dry-run",
            ]
        )
        == 0
    )


def test_malformed_answers_reports_before_guard(src_target, tmp_path, capsys):
    write_source_config(src_target)
    bad = tmp_path / "answers.toml"
    bad.write_text("[answers\n", encoding="utf-8")
    assert main(["--target", str(src_target), "--config", str(bad)]) == 2
    assert not (src_target / SOURCE_CONFIG_REL).read_text().startswith("garbage")
```

- [ ] **Step 2:** FAIL (exit 2 on the first). **Step 3: Implement.** In `main`: load `dest = load_answers(args.config)` before `_resolve_source` when `args.config` is set (keep the `--config is required` failure ordering for the no-config case: resolve with `dest=None`, then fail as today). In `_resolve_source`: after `problems = mismatches(source, found)`, partition problems by field; for `owner`/`repo_name`, if `dest` and `getattr(found, f) == getattr(dest, f)`, drop the problem and record `named_destination`; print `notice: <field>: origin already names the destination ('<value>'); source-config says '<source value>' — accepted`. Remaining problems → exit 2 as today. Thread the decision to `write_receipt` (new kwarg `origin: OriginDecision`), rendered under `[press]`. Keep `write_pending` deferral ("exit 2 ⇒ no writes"). **Step 4:** All five pass; `tests/rebrand/test_cli.py:56-63`, `:707` (no-config discovery path) still pass; `just matrix` green. **Step 5:** Commit: `feat(guard): accept an origin that already names the destination`

### Task 10: E1 — `--accept-origin-mismatch`

**Files:** `cli.py` argparser + `_resolve_source`; `receipt.py`; `docs/source/reference/cli.md`; `tests/rebrand/test_cli.py`

- [ ] **Step 1: Failing tests**

```python
def test_accept_origin_mismatch_proceeds_with_warning_and_receipt(
    src_target, tmp_path, capsys
):
    write_source_config(src_target)
    _set_origin(src_target, "https://github.com/someone/else.git")
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--accept-origin-mismatch",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "warning: repo_name: source-config 'demo-widget', repository 'else', destination 'potato-launcher' — proceeding on --accept-origin-mismatch"
        in out
    )
    assert (
        'origin_mismatch_accepted = ["owner", "repo_name"]'
        in (src_target / RECEIPT_REL).read_text()
    )


def test_accept_origin_mismatch_never_covers_pyproject_fields(
    src_target, tmp_path, capsys
):
    wrong = SOURCE.__class__(
        **{**SOURCE.as_dict_prompted(), "package_name": "other_pkg"}
    )
    (src_target / "press").mkdir()
    (src_target / SOURCE_CONFIG_REL).write_text(
        render_source_config(wrong), encoding="utf-8"
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-qm", "cfg")
    code = main(
        [
            "--target",
            str(src_target),
            "--config",
            str(write_answers(tmp_path)),
            "--accept-origin-mismatch",
        ]
    )
    assert code == 2 and "package_name" in capsys.readouterr().out
```

- [ ] **Step 2:** FAIL. **Step 3: Implement.** Flag `--accept-origin-mismatch` (help: "proceed when origin's owner/repo_name match neither the source-config nor the destination; prints each mismatch and records it in the receipt. Never covers pyproject-derived fields."). In `_resolve_source`: for remaining `owner`/`repo_name` problems, if the flag is set, print the per-field warning line (exact format above) and record `mismatch_accepted`; other fields still return 2. **Step 4:** PASS; `just matrix` green. **Step 5:** Docs `cli.md`: guard section — the three states (source / destination / neither), the notice, the flag, the exact-case note, the documented blind spot. **Step 6:** Commit: `feat(guard): --accept-origin-mismatch with per-field warning and receipt row`

### Task 11: PR2 close — `just check`, `just matrix`, PR `feat(guard): origin relaxation (P12 part 2)`.

---

## PR group 3a — `[[edit]]` (P09, includes E11)

### Task 12: `[[edit]]` rules parsing

**Files:** `src/template_press/rebrand/rules.py` (`EditRule`, `_EditDeclaration`, `_parse_edit`, `_ROOT_KEYS`, `_validate_writer_overlaps`), `tests/rebrand/test_edit_rules.py` (new)

**Interfaces:**
- Produces: `@dataclass(frozen=True) class EditRule: file: str; command: tuple[str, ...]; expect: str; env: tuple[str, ...]`; `Rules.edit: tuple[EditRule, ...]`; `SelectedRules.edit`.

- [ ] **Step 1: Failing tests** (`_write_rules` helper as in `test_regenerate_rules.py:24`)

```python
def test_edit_rule_parses(src_target):
    _write_rules(
        src_target,
        '[[edit]]\nfile = "pyproject.toml"\ncommand = ["uv", "version", "0.1.0", "--frozen"]\nexpect = \'version = "0.1.0"\'\n',
    )
    rules = load_rules(src_target)
    assert (
        rules.edit[0].file == "pyproject.toml"
        and rules.edit[0].expect == 'version = "0.1.0"'
    )


@pytest.mark.parametrize(
    "body,needle",
    [
        (
            '[rules]\nextra_exclude_files=["pyproject.toml"]\n[[edit]]\nfile="pyproject.toml"\ncommand=["uv","version","0.1.0"]\nexpect="x"\n',
            "must not be listed in exclude_files",
        ),
        (
            '[[edit]]\nfile="pyproject.toml"\ncommand=["uv","version","0.1.0"]\n',
            "expect is required",
        ),
        (
            '[[edit]]\nfile="pyproject.toml"\ncommand=["uv","version","0.1.0"]\nexpect="x"\nverify_exempt=true\n',
            "unknown key",
        ),
        (
            '[[edit]]\nfile="pyproject.toml"\ncommand=["uv","version","0.1.0"]\nexpect="x"\nscan="boundary"\n',
            "unknown key",
        ),
        (
            '[[edit]]\nfile="pyproject.toml"\ncommand=["uv","version","0.1.0"]\nexpect="x"\n[[reset]]\nfile="pyproject.toml"\nstub=""\n',
            "may not also be",
        ),
    ],
)
def test_edit_rule_refusals(src_target, body, needle):
    _write_rules(src_target, body)
    with pytest.raises(ValidationError, match=needle):
        load_rules(src_target)
```

- [ ] **Step 2:** FAIL. **Step 3: Implement** `_parse_edit` mirroring `_parse_regenerate` (`rules.py:446-557`): keys `{"file","command","expect","env","platforms"}`; `file` via `_declared_rel_path`, `_reject_reserved`; refuse when `file in exclude_files` with message `[[edit]] target {file!r} must not be listed in exclude_files — an edit target is rewritten by the replace pass first, then edited in place`; `expect` required, non-empty, printable; command/env as regenerate. Add `"edit"` to `_ROOT_KEYS`. Extend `_validate_writer_overlaps` (`:641-724`): an edit file may not equal any reset/remove/regenerate file on the same platform (`may not also be a reset/remove/regenerate target`). **Step 4:** PASS. **Step 5:** Commit: `feat(rules): parse [[edit]] declarations`

### Task 13: `[[edit]]` planning, plan rendering, check-tools

**Files:** `regen.py` (`plan_edits` reusing `resolve_executable`/`command_env`; `render_edit_plan`), `cli.py` (call after regenerate planning; print `Edit (declared in-place edits, run after apply, before regenerations):` with `[edit   ] <file>  —  <argv>` and `executable:` lines), `check_tools.py:22` (include edit commands), tests `tests/rebrand/test_regenerate_plan.py`, `test_check_tools.py`

- [ ] **Step 1: Failing tests:** dry-run output contains `[edit   ] pyproject.toml  —  uv version 0.1.0 --frozen` and an `executable:` line; missing executable → exit 2 before the plan (same as regenerate, `regen.py:226-236`); `press check-tools` lists `uv — … (edits pyproject.toml)`. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat(plan): render and preflight [[edit]] commands`

### Task 14: `[[edit]]` execution, post-conditions, receipt, E11 gate

**Files:** `regen.py` (`execute_edits` — share the subprocess/sink-guard body of `execute_regenerations:296-338` via a helper `_run_declared(plan, …)`; post-conditions = `_postcondition_problems` + `expect in text`), `cli.py:470-500` (edit phase before regenerations; gate snapshots on `bool(edit_plans) or bool(regen_plans)`; restore on failure), `receipt.py` (`[[press.edit]] file/argv/expect`), tests `tests/rebrand/test_edit_execute.py` (new)

- [ ] **Step 1: Failing tests** (use a stub command script committed in the fixture, e.g. `scripts/setver.sh` that rewrites `version = "0.1.0"` → `version = "0.2.0"` in `pyproject.toml`; `expect = 'version = "0.2.0"'`):
  - success: exit 0, `pyproject.toml` has `name = "potato_launcher"` (rewritten) and `version = "0.2.0"`, receipt has `[[press.edit]]` row with `expect`.
  - command exits 3 → exit 1 path per regenerate failure semantics (`error: … failed`), no receipt, control files restored.
  - command exits 0 but leaves `version = "0.1.0"` (no-op) → `expect` post-condition fails, no receipt.
  - command writes `name = "demo_widget"` back → leak post-condition fails, no receipt.
  - edit target under a renamed prefix (`src/demo_widget/version.py` → translated path) succeeds.
  - **E11:** rules with one `[[edit]]` and no `[[regenerate]]`, command appends `secrets/\n` to `.gitignore` → the press exits nonzero with the existing visibility-changed error whose text names `.gitignore`, no receipt is written, and `press/press-rules.toml` is byte-identical to before (control files restored). Without the E11 gate this same fixture would exit 0 — assert that first to prove the test bites (RED), then implement.
  - phase order: one `[[edit]]` on `pyproject.toml` (`uv version 0.3.0 --frozen`) and `[[regenerate]] uv.lock` (`uv lock`) → `uv.lock` root package version is `0.3.0` (edit ran first).
- [ ] **Step 2:** FAIL. **Step 3:** Implement per spec E4/E11; edits are never passed to `exempt_regenerated_paths`. **Step 4:** PASS; `just matrix` green. **Step 5:** Commit: `feat(edit): execute declared in-place edits before regenerations; gate snapshots on any command`

### Task 15: `[[edit]]` docs, R3 three-mirror test, PR

- [ ] Docs: `cli.md` new `[[edit]]` section (declaration, phase, `expect`, not exempt, receipt row) + one paragraph in `docs/design/0006-external-target-model.md` regeneration section; ADR-style note in `docs/adr/` if the repo's convention requires one for new mechanisms (check `docs/adr/README.md`).
- [ ] R3 test (`tests/rebrand/test_matrix.py`): this repo's own `press-rules.toml` gains `[[reset]] .release-please-manifest.json` (stub `{".": "0.1.0"}\n`) and `[[edit]] pyproject.toml` (`uv version 0.1.0 --frozen`, `expect = 'version = "0.1.0"'`) before the `uv.lock` rule; assert the pressed output's `pyproject.toml`, manifest, and `uv.lock` root version all read `0.1.0`. (If the repo has no `.release-please-manifest.json`, use `pyproject.toml` + `uv.lock` only and note it.)
- [ ] `just check`, `just matrix`; PR `feat: declared in-place edit mechanism ([[edit]]) (P09)`; merge.

---

## PR group 3b — `[[clean]]` (P10)

> **Superseded (2026-09-05 planning gate).** Tasks 16–18 below are kept for
> history. The implementation-ready plan, reconciled against merged `main`
> at `bddbae3`, is `docs/superpowers/plans/2026-09-05-p10-declared-pre-press-clean.md`;
> the reconciliation and review record is
> `docs/superpowers/specs/reviews-2026-09-05/P10-planning-gate.md`.

### Task 16: `[[clean]]` rules parsing

**Files:** `rules.py` (`CleanRule(paths: tuple[str, ...])`, `_parse_clean`, `_ROOT_KEYS`), `tests/rebrand/test_clean_rules.py`

- [ ] **Step 1: Failing tests:** parses `[[clean]]\npaths = ["src/{package_name}", "tests"]\n` → `rules.clean[0].paths == ("src/{package_name}", "tests")`; rendering against `SOURCE` yields `("src/demo_widget", "tests")`; unknown placeholder `{nope}` → `ValidationError`; control character in a path → refused; `platforms` honored; empty `paths` → refused. **Step 2:** FAIL. **Step 3:** Implement (render with `render_replace_pattern`-style substitution against the source identity; reject absolute paths and `..` via `_declared_rel_path`). **Step 4:** PASS. **Step 5:** Commit: `feat(rules): parse [[clean]] path declarations`

### Task 17: `press clean` subcommand

**Files:** `src/template_press/rebrand/clean_cli.py` (new: `clean_command(argv) -> int`), `src/template_press/press_cli.py:39-43` (dispatch `"clean"`), `tests/rebrand/test_clean_cli.py`

**Interfaces:** `press clean --target <dir> [--show]`. Runs `git --literal-pathspecs -C <target> clean -fdX -- <rendered paths>` (or `-ndX` with `--show`), echoing the exact argv first. Exit 0 on success, 2 when no `[[clean]]` rules are declared or a path is outside the target, 1 when git fails.

- [ ] **Step 1: Failing tests:**
  - `--show`: with an ignored `src/demo_widget/__pycache__/x.pyc` present, stdout has the `-ndX` argv line and `Would remove src/demo_widget/__pycache__/`; file still exists; exit 0.
  - run: file removed; a non-ignored untracked file `src/demo_widget/new.py` survives; `capture_surface_snapshot` before == after; exit 0.
  - no rules declared → exit 2 with `no [[clean]] rules declared in press/press-rules.toml`.
  - E2 tie-in: with `[[clean]]` declared and caches present, `press rebrand --dry-run` refusal text ends with `declared clean rules exist — run: press clean --target <target>`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; add the hint at the `cli.py` catch site from Task 2 when `rules.clean` is non-empty. **Step 4:** PASS. **Step 5:** Commit: `feat(cli): press clean — declared, git-clean -X based pre-press cleanup`

### Task 18: `[[clean]]` check-tools, receipt, verify no-op, docs, PR

- [ ] `check-tools` reports `git` for clean rules; receipt writes `[[press.clean]] paths = [...]`; test that `press verify` output is unchanged with `[[clean]]` declared (sandbox never contains ignored files, `inventory.py:1011`); docs `cli.md` "`press clean`" section + `press-target` SKILL.md step "run `press clean` before the dry-run when the template declares clean rules".
- [ ] `just check`, `just matrix`; PR `feat: press clean and [[clean]] declarations (P10)`; merge.

---

## PR group 3c — `[[remove]] dir` (P11)

### Task 19: Phase decision note + adversarial review

**Files:** `docs/superpowers/specs/2026-09-01-remove-dir-phase.md`

- [ ] Write a two-page design note deciding the removal phase (proposal: after `[[reset]]`, before the rewrite; closure excludes removed paths; verify mirrors) against the three couplings in spec E5 (`rules.py:700`, `substitutions.py:591-609`, `receipt.py:126-155` / `verify_cli.py:473-493`). Dispatch one adversarial review (opus) of the note; fold its constraints in; commit `docs(design): removal phase for [[remove]] dir`.

### Task 20: `[[remove]] dir` parsing and plan-time expansion

**Files:** `rules.py` (`RemoveRule` gains `dir: str | None`; `file` XOR `dir`; `reason` mandatory), `remove.py` (`expand_remove_dirs(target, rules) -> tuple[str, ...]` frozen into the plan; `preflight_remove_targets` per-dir clean check incl. `??`; gitlink/symlink refusal), `render_remove_plan` lists `[remove] research/ (N files, dir)` + each path, tests `tests/rebrand/test_remove_rules.py`

- [ ] **Step 1: Failing tests:** parse `dir`; `file` and `dir` together → refused; untracked operator file inside the dir → `SafetyError` naming it; gitlink inside → refused; dry-run lists every expanded path. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat(rules): [[remove]] dir with frozen plan-time expansion`

### Task 21: `[[remove]] dir` apply, receipt, verify, phase

**Files:** `remove.py:133` (`apply_removals` consumes the frozen expansion; `rmdir` emptied dirs), `receipt.py` (one `[[press.remove]]` row per expanded path), `verify_cli.py:473-493` (reads the expanded set), engine phase change per Task 19, tests

- [ ] **Step 1: Failing tests:** the required test — a `[[replace]]` rename moves a file into the dir's expansion between plan and apply → unlinked set equals the dry-run set exactly; receipt names each path; mid-removal `SafetyError` → no receipt; emptied directory gone; `press verify` on the pressed target green. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS; `just matrix` green. **Step 5:** Commit: `feat(remove): apply directory removals with receipt and verify parity`

### Task 22: PR3c close — replace this repo's per-file `[[remove]]` rows (Task 4) with `dir = "projects"` / `dir = "docs/research"`; `just matrix`; docs `cli.md` `[[remove]] dir`; PR `feat: directory removals ([[remove]] dir) (P11)`; merge.

---

## Final

- [ ] `project-audit` skill: P09–P12 rows flipped to `[x]`; changelog entries via release-please on merge.
- [ ] Append to the fork's improvement log (`~/c/gmail2pdf/docs/blueprint-feedback-log.md`) a status line per entry #4, #5, #7, #10, #15 pointing at the shipped PRs; reclassify #15 per spec E8.
