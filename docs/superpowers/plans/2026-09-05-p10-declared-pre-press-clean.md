# P10 — Declared pre-press clean (`[[clean]] paths`, `press clean`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the restricted `[[clean]] paths = [...]` declaration and the standalone `press clean [--show]` verb, which removes only ignored entries under the declared paths with `git clean -fdX`, so a target can clear stale build caches before a press instead of tripping the rename-closure refusal.

**Architecture:** One new rule table parsed like the other declared mechanisms (`rules.py`), one new pure module that renders paths from the SOURCE identity and builds the exact hardened git argv (`clean.py`), one new verb module that maps outcomes to the existing 0/1/2 exit contract (`clean_cli.py`), plus three integrations that already exist for every other mechanism: the `press check-tools` report, the receipt, and the E2 closure-refusal hint. `press rebrand` never runs clean; dry-run/apply parity is untouched.

**Tech Stack:** Python 3.13 stdlib only (engine has zero runtime deps), pytest, ruff, ty, `just`, lefthook. Tests live in `tests/rebrand/`; fixtures `src_target`, `SOURCE`, `DEST`, `make_target` in `tests/rebrand/conftest.py`; CLI helpers `write_source_config`, `write_answers` in `tests/rebrand/test_cli.py`.

**Spec:** `docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md` §E10 (binding decisions), `docs/superpowers/specs/reviews-2026-09-01/CLEAN-review.md` (the adversarial review that produced the restricted form), and `docs/superpowers/specs/reviews-2026-09-05/P10-planning-gate.md` (the reconciliation of this plan against merged `main` at `bddbae3`, with the decisions below and their rationale). This plan supersedes Tasks 16–18 of `docs/superpowers/plans/2026-09-01-press-improvements-g2p.md`.

## Global Constraints

- Work in a worktree on a branch from `origin/main` via `git worktree add`; merge with a merge commit (`gh pr merge --merge`); never push to `main`.
- After ANY change to `src/template_press/rebrand/`, run `just matrix` (R1/R2/R3 acceptance matrix) — AGENTS.md rule.
- Gates before every commit: `just check` (ruff check/format, ty over `src/template_press/`, tests). Hooks: commit-msg commitlint (lowercase conventional subject), pre-commit gitleaks/codespell/ruff/editorconfig/yamllint, pre-push gitleaks + bandit.
- Commit messages: Conventional Commits, lowercase subject; body ends with the session trailer the harness prescribes.
- Exit-code contract: `2` = precondition/config refusal, nothing ran; `1` = a command ran and failed (for `press clean`: git exited non-zero, so the tree may have changed); `0` = success. No new exit codes.
- Zero runtime dependencies: no third-party imports in `src/`.
- "Dry-run refuses exactly what apply refuses" (`docs/source/reference/cli.md:40`) is inviolable: clean is never a phase of `press rebrand`.
- New root table: add `"clean"` to `_ROOT_KEYS` (`rules.py:304`); unknown keys still fail loud.
- Receipt: one table per mechanism (`receipt.py:83-193`); readers stay tolerant of unknown keys.
- Field names, flags, and message substrings below are the spec's values verbatim; keep them.
- PROJECTS.md changes go through the project-harness skills, never hand-edits.

## Decisions fixed by the planning gate (2026-09-05)

These are the points where the 2026-09-01 plan was silent or where merged code changed the ground. Rationale and evidence are in the gate record.

- **R1 — the E2 hint already exists.** `cli.py:186` prints `declared clean rules exist — run: press clean --target {target}` behind `getattr(rules, "clean", ())`. Task 3 replaces the `getattr` with `rules.clean` and tests both directions; it adds no new message.
- **R2 — an absent declared path is a silent no-op.** Verified on git 2.x: `git clean -ndX -- nonexistent` exits 0 and prints nothing. `press clean` therefore exits 0 and prints only the command line; nothing is special-cased.
- **R3 — every git invocation is hardened and scrubbed.** `press clean` builds its argv with `git_hardening_args()` and runs under `scrubbed_git_env()`, exactly as every other on-target git call does (G5). Consequence: "ignored" means ignored by the target's own `.gitignore` files and `.git/info/exclude`, never by the operator's global excludes file. The echoed command is the exact argv that runs, hardening flags included.
- **R4 — `press clean` requires `press/press-source.toml`.** Paths render from the SOURCE identity loaded with `load_source_config(target, None)`; the E1 origin guard is not consulted, because clean writes no identity and only removes ignored entries under paths the target's own rules declare.
- **R5 — the receipt records the declaration, unrendered.** `[[press.clean]] paths = [...]` carries the declared patterns as written; `press clean` itself never writes a receipt. No `ran` key: the table name plus docs state that it is a declaration.
- **R6 — no writer-overlap check for clean paths.** `-X` removes only ignored entries, and every `[[edit]]`/`[[regenerate]]`/`[[reset]]`/`[[remove]]` target is inventoried, so the sets cannot intersect; `_validate_writer_overlaps` is unchanged.
- **R7 — the snapshot-equality invariant is a test, not a runtime tripwire.** With the restricted form the invariant is git's own `-X` semantics; a runtime comparison would add an exit-1 path that cannot legitimately fire.
- **R8 — this repository declares `[[clean]]` for itself.** The native R3 self-press then exercises parse → check-tools → receipt end to end, as it already does for `[[edit]]`.
- **R9 — an ADR records the mechanism** (`docs/adr/0018-declared-pre-press-clean.md`), following ADR 0017 for `[[edit]]`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/template_press/rebrand/rules.py` (modify) | `CleanRule`, `_CleanDeclaration`, `_CLEAN_KEYS`, `_parse_clean`, `_ParsedRules.clean`, raw-table extraction in `_parse_rules`, platform selection in `_select_rules`, `Rules.clean`, `_ROOT_KEYS`. |
| `src/template_press/rebrand/clean.py` (create) | Pure logic: `render_clean_paths`, `clean_argv`, `shell_join`, `execute_clean`. No argparse, no exit codes. |
| `src/template_press/rebrand/clean_cli.py` (create) | `clean_command(argv) -> int`: argument parsing, config loading, the 0/1/2 mapping, echo and output. |
| `src/template_press/press_cli.py` (modify) | `clean` in `_USAGE` and the verb dispatch. |
| `src/template_press/rebrand/cli.py` (modify) | Line 186: `rules.clean` instead of `getattr`; the `write_receipt` call passes `clean=`. |
| `src/template_press/rebrand/receipt.py` (modify) | `write_receipt(..., clean=...)` emits `[[press.clean]]` rows. |
| `src/template_press/rebrand/check_tools.py` (modify) | One informational row per active clean rule. |
| `press/press-rules.toml` (modify) | This repository's own `[[clean]]` declaration. |
| `tests/rebrand/test_clean_rules.py` (create) | Parser contract. |
| `tests/rebrand/test_clean_cli.py` (create) | `clean.py`, `press clean`, the E2 hint, check-tools row, receipt row, verify no-op, dispatcher. |
| `tests/rebrand/test_matrix.py` (modify) | R3 asserts the native receipt row and a `--show` preview. |
| `docs/adr/0018-declared-pre-press-clean.md` (create) | The decision record. |
| `docs/source/reference/cli.md` (modify) | `## press clean` section after `## press check-tools`. |
| `.claude/skills/press-target/SKILL.md` (modify) | Step 1b: run `press clean` before the dry run when rules are declared. |

---

### Task 1: `[[clean]]` rules parsing

**Files:**
- Modify: `src/template_press/rebrand/rules.py` (dataclasses near line 126–195; `_ROOT_KEYS` line 304; `Rules` line 210; `_ParsedRules` line 246; `_parse_rules` lines 1111–1212; `_select_rules` lines 1213–1264; the table-list comment at line 300)
- Test: `tests/rebrand/test_clean_rules.py`

**Interfaces:**
- Produces: `CleanRule(paths: tuple[str, ...])` frozen dataclass; `Rules.clean: tuple[CleanRule, ...]` (platform-selected, appended after `edit`); `load_rules(target).clean` and `load_selected_rules(target, platform=...).rules.clean`.
- Paths stay UNRENDERED here (declared patterns in SOURCE coordinates). Rendering is Task 2's job.

- [ ] **Step 1: Write the failing tests**

```python
"""P10-TS01 — [[clean]] schema + config-load validation (E10).

A restricted declaration: a non-empty list of contained relative paths whose
placeholders name known identity fields, optionally scoped by `platforms`.
Nothing else — v1 carries no argv. Paths stay unrendered at parse time;
`press clean` renders them from press/press-source.toml (SOURCE identity),
because press/press-rules.toml is never rewritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import DEFAULT_RULES, CleanRule, load_rules, load_selected_rules


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


CLEAN_SRC_TESTS = '[[clean]]\npaths = ["src/{package_name}", "tests"]\n'


def test_valid_entry_parses_unrendered(tmp_path: Path):
    target = _write_rules(tmp_path, CLEAN_SRC_TESTS)
    (rule,) = load_rules(target).clean
    assert isinstance(rule, CleanRule)
    assert rule.paths == ("src/{package_name}", "tests")


def test_absent_table_and_defaults_yield_no_rules(tmp_path: Path):
    assert DEFAULT_RULES.clean == ()
    target = _write_rules(tmp_path, "[rules]\n")
    assert load_rules(target).clean == ()


def test_unknown_root_table_still_fails_loud(tmp_path: Path):
    target = _write_rules(tmp_path, '[[cleanup]]\npaths = ["x"]\n')
    with pytest.raises(ValidationError, match="unknown root-level table"):
        load_rules(target)


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ('clean = "src"\n', "must be an array of tables"),
        ("[[clean]]\n", "paths must be a non-empty list of strings"),
        ("[[clean]]\npaths = []\n", "paths must be a non-empty list of strings"),
        ('[[clean]]\npaths = "src"\n', "paths must be a non-empty list of strings"),
        ('[[clean]]\npaths = ["src", 3]\n', "paths must be a non-empty list of strings"),
        ('[[clean]]\npaths = ["src"]\nreason = "x"\n', "unknown key"),
        ('[[clean]]\npaths = ["/abs"]\n', "paths"),
        ('[[clean]]\npaths = ["../up"]\n', "paths"),
        ('[[clean]]\npaths = ["src\\u001b"]\n', "control characters"),
        ('[[clean]]\npaths = ["src/{nope}"]\n', "unknown placeholder"),
        ('[[clean]]\npaths = ["src/{App_Name}"]\n', "unknown placeholder"),
        ('[[clean]]\npaths = ["src", "src"]\n', "duplicate"),
        ('[[clean]]\npaths = ["src"]\nplatforms = []\n', "platforms must be"),
        ('[[clean]]\npaths = ["src"]\nplatforms = ["plan9"]\n', "platforms values"),
    ],
)
def test_malformed_entries_refuse(tmp_path: Path, body: str, fragment: str):
    target = _write_rules(tmp_path, body)
    with pytest.raises(ValidationError, match=fragment):
        load_rules(target)


def test_platform_selection_makes_a_foreign_rule_inert(tmp_path: Path):
    target = _write_rules(
        tmp_path,
        '[[clean]]\npaths = ["build"]\nplatforms = ["win32"]\n'
        '[[clean]]\npaths = ["dist"]\n',
    )
    darwin = load_selected_rules(target, platform="darwin").rules.clean
    win32 = load_selected_rules(target, platform="win32").rules.clean
    assert [rule.paths for rule in darwin] == [("dist",)]
    assert [rule.paths for rule in win32] == [("build",), ("dist",)]


def test_clean_coexists_with_every_other_mechanism(tmp_path: Path):
    target = _write_rules(
        tmp_path,
        CLEAN_SRC_TESTS
        + '[[edit]]\nfile = "pyproject.toml"\ncommand = ["uv", "version", "0.1.0"]\n'
        "expect = 'version = \"0.1.0\"'\n"
        '[[remove]]\nfile = "docs/old.md"\nreason = "history"\n',
    )
    rules = load_rules(target)
    assert rules.clean[0].paths == ("src/{package_name}", "tests")
    assert rules.edit[0].file == "pyproject.toml"
    assert rules.remove[0].file == "docs/old.md"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_rules.py -q`
Expected: every test errors with `ImportError: cannot import name 'CleanRule'` (feature missing).

- [ ] **Step 3: Implement the parser**

In `rules.py`, next to `RemoveRule` / `_RemoveDeclaration`:

```python
@dataclass(frozen=True)
class CleanRule:
    """One declared pre-press clean (E10, restricted v1).

    `press clean` runs ``git clean -fdX -- <paths>`` against the target with
    each path rendered from the SOURCE identity, so only IGNORED entries
    under the declared paths can be removed. It is a standalone verb, never
    a phase of ``press rebrand``. Paths are stored as declared; rendering
    happens in `clean.py` at run time.
    """

    paths: tuple[str, ...]  # declared patterns, SOURCE coordinates, unrendered


@dataclass(frozen=True)
class _CleanDeclaration:
    """One parsed clean rule plus its environment-independent selector."""

    rule: CleanRule
    platforms: frozenset[str]
```

`Rules` — append after `edit`, with the same positional-construction warning:

```python
    # Declared pre-press clean paths (E10). Appended AFTER `edit` for the
    # same reason edit follows every earlier field: Rules is constructed
    # positionally in places.
    clean: tuple[CleanRule, ...] = ()
```

`_ParsedRules` — add `clean: tuple[_CleanDeclaration, ...] = ()` after `edit`.

Constants — `_ROOT_KEYS` gains `"clean"`; add `_CLEAN_KEYS = frozenset({"paths", "platforms"})` next to `_EDIT_KEYS`; extend the table-list comment at line 300 with `[[clean]]`.

Parser, next to `_parse_edit`:

```python
def _parse_clean(entry: object) -> _CleanDeclaration:
    """One [[clean]] table (E10): a non-empty list of contained relative
    paths whose placeholders must name known identity fields. The paths stay
    UNRENDERED here; `press clean` renders them from press/press-source.toml
    and re-validates the rendered form.
    """
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[clean]] entry must be a table")
    unknown = set(entry) - _CLEAN_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[clean]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    raw_paths = entry.get("paths")
    if (
        not isinstance(raw_paths, list)
        or not raw_paths
        or any(not isinstance(p, str) for p in raw_paths)
    ):
        raise ValidationError(
            f"{RULES_REL}: [[clean]] paths must be a non-empty list of strings"
        )
    paths: list[str] = []
    for raw in raw_paths:
        path = _declared_rel_path("[[clean]] paths", raw)
        # Same brace-token scan as [[replace]]: any token that is not exactly
        # a known field is refused, so a typo cannot render literally.
        for token in re.findall(r"\{[^{}]*\}", path):
            inner = token[1:-1]
            if not re.fullmatch(r"[a-z_]+", inner) or inner not in ALLOWED_PLACEHOLDERS:
                raise ValidationError(
                    f"{RULES_REL}: [[clean]] path {path!r} references an invalid "
                    f"or unknown placeholder {token!r}"
                )
        if path in paths:
            raise ValidationError(
                f"{RULES_REL}: [[clean]] paths contains duplicate value {path!r}"
            )
        paths.append(path)
    return _CleanDeclaration(
        rule=CleanRule(paths=tuple(paths)),
        platforms=_parse_platforms(entry, "[[clean]]", ", ".join(paths)),
    )
```

`_parse_rules` — after the `raw_edit` block:

```python
    raw_clean = data.get("clean", [])
    if not isinstance(raw_clean, list) or any(
        not isinstance(e, dict) for e in raw_clean
    ):
        raise ValidationError(f"{RULES_REL}: [[clean]] must be an array of tables")
```

and after `edit = tuple(_parse_edit(e) for e in raw_edit)`: `clean = tuple(_parse_clean(e) for e in raw_clean)`, then pass `clean=clean` to the `_ParsedRules(...)` constructor.

`_select_rules` — inside the `replace(parsed.rules, ...)` call, after `edit=active_edits,`:

```python
        clean=tuple(
            declaration.rule
            for declaration in parsed.clean
            if platform in declaration.platforms
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_rules.py tests/rebrand/test_rules.py tests/rebrand/test_edit_rules.py -q`
Expected: all pass. Then `uv run --no-sync ruff check src/template_press/rebrand/rules.py tests/rebrand/test_clean_rules.py && uv run --no-sync ruff format --check src/ tests/ && uv run --no-sync ty check src/template_press/`.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/rules.py tests/rebrand/test_clean_rules.py
git commit -m "feat(rules): parse [[clean]] path declarations"
```

---

### Task 2: `clean.py` — rendering, argv, execution

**Files:**
- Create: `src/template_press/rebrand/clean.py`
- Test: `tests/rebrand/test_clean_cli.py` (the `clean.py` unit tests open this module; Task 3 appends the CLI tests)

**Interfaces:**
- Consumes: `CleanRule` (Task 1); `Identity.as_dict()`; `SafeRelPath`, `UnsafePathError`, `scrubbed_git_env`, `git_hardening_args` from `safety.py`.
- Produces:
  - `render_clean_paths(rules: tuple[CleanRule, ...], source: Identity) -> tuple[str, ...]` — every declared path rendered, re-validated, in declaration order; raises `ValidationError`.
  - `clean_argv(git: Path, target: Path, paths: tuple[str, ...], *, show: bool) -> list[str]` — the exact argv that runs.
  - `shell_join(argv: list[str]) -> str` — copy-pasteable rendering.
  - `execute_clean(argv: list[str], target: Path) -> subprocess.CompletedProcess[bytes]` — runs under the scrubbed git environment; never raises on a non-zero exit.

- [ ] **Step 1: Write the failing tests**

```python
"""P10-TS02/TS03 — `press clean` (E10): rendering, the exact git argv, the
standalone verb, and its integrations (E2 hint, check-tools, receipt, verify).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from template_press import press_cli
from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.cli import main
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.inventory import capture_surface_snapshot
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import CleanRule, load_selected_rules
from template_press.rebrand.safety import git_hardening_args
from template_press.rebrand.verify_cli import verify_command

from .conftest import SOURCE, _git
from .test_cli import write_answers, write_source_config

CLEAN_SRC_TESTS = '[[clean]]\npaths = ["src/{package_name}", "tests"]\n'


def _declare(target: Path, body: str) -> None:
    """Write press/press-rules.toml and commit it (a press wants a clean tree)."""
    (target / "press").mkdir(exist_ok=True)
    (target / "press" / "press-rules.toml").write_text(body, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "declare rules")


class TestRender:
    def test_renders_from_source_in_declaration_order(self):
        rules = (CleanRule(paths=("src/{package_name}", "tests")), CleanRule(paths=("build/{repo_name}",)))
        assert render_clean_paths(rules, SOURCE) == (
            "src/demo_widget",
            "tests",
            "build/demo-widget",
        )

    def test_optional_field_absent_from_source_refuses(self):
        rules = (CleanRule(paths=("docs/{display_name}",)),)
        with pytest.raises(ValidationError, match="does not declare it"):
            render_clean_paths(rules, SOURCE)  # SOURCE has no display_name

    def test_rendered_path_is_revalidated(self):
        hostile = Identity(**{**SOURCE.as_dict_prompted(), "package_name": "x"})
        rules = (CleanRule(paths=("src/{package_name}",)),)
        assert render_clean_paths(rules, hostile) == ("src/x",)


class TestArgv:
    def test_preview_and_run_argv(self, tmp_path: Path):
        git = Path("/usr/bin/git")
        paths = ("src/demo_widget", "tests")
        preview = clean_argv(git, tmp_path, paths, show=True)
        run = clean_argv(git, tmp_path, paths, show=False)
        assert preview[0] == str(git)
        assert preview[1:3] == ["-C", str(tmp_path)]
        assert f"--work-tree={tmp_path.absolute()}" in preview
        for flag in git_hardening_args():
            assert flag in preview
        assert preview[-6:] == ["--literal-pathspecs", "clean", "-ndX", "--", "src/demo_widget", "tests"]
        assert run[-6:] == ["--literal-pathspecs", "clean", "-fdX", "--", "src/demo_widget", "tests"]

    def test_shell_join_is_copy_pasteable(self):
        joined = shell_join(["git", "clean", "-ndX", "--", "src/demo widget"])
        assert "src/demo widget" in joined or "'src/demo widget'" in joined
        assert joined.startswith("git clean -ndX --")

    def test_execute_returns_nonzero_without_raising(self, tmp_path: Path):
        result = execute_clean([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
        assert result.returncode == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'template_press.rebrand.clean'`.

- [ ] **Step 3: Write `clean.py`**

```python
"""Declared pre-press clean (E10, restricted v1).

`press clean` removes IGNORED entries under declared paths with
``git clean -fdX``. It is a standalone verb, never a phase of
``press rebrand`` (dry-run/apply parity, docs/source/reference/cli.md), so
this module holds only the pure pieces: render the declared paths from the
SOURCE identity, build the exact hardened git argv, run it.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.rules import CleanRule
from template_press.rebrand.safety import (
    SafeRelPath,
    UnsafePathError,
    git_hardening_args,
    scrubbed_git_env,
)

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _render_one(pattern: str, values: dict[str, str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValidationError(
                f"[[clean]] path {pattern!r} references {{{name}}} but "
                f"press/press-source.toml does not declare it"
            )
        return values[name]

    return _PLACEHOLDER_RE.sub(_sub, pattern)


def render_clean_paths(
    rules: tuple[CleanRule, ...], source: Identity
) -> tuple[str, ...]:
    """Every declared path rendered from `source`, re-validated, in order.

    Rendering happens at run time because press/press-rules.toml is never
    rewritten (ROOT_CONTROL): a literal ``src/template_press`` would go stale
    after the first press, so the declaration names the SOURCE identity.
    The rendered form is validated again (control characters, containment)
    because a declared pattern was only validated before substitution.
    """
    values = source.as_dict()
    rendered: list[str] = []
    for rule in rules:
        for pattern in rule.paths:
            path = _render_one(pattern, values)
            if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
                raise ValidationError(
                    f"[[clean]] rendered path must not contain control "
                    f"characters: {path!r}"
                )
            try:
                rendered.append(SafeRelPath(path).as_posix())
            except UnsafePathError as exc:
                raise ValidationError(f"[[clean]] rendered path {path!r}: {exc}") from exc
    return tuple(rendered)


def clean_argv(
    git: Path, target: Path, paths: tuple[str, ...], *, show: bool
) -> list[str]:
    """The exact git invocation `press clean` runs (``--show`` previews).

    Same prefix as every other on-target git call (G5: pinned work tree,
    hardening flags) plus ``--literal-pathspecs`` so a declared path is a
    path, never a glob. ``-X`` removes ignored entries only — never ``-x``.
    """
    mode = "-ndX" if show else "-fdX"
    return [
        str(git),
        "-C",
        str(target),
        f"--work-tree={target.absolute()}",
        *git_hardening_args(),
        "--literal-pathspecs",
        "clean",
        mode,
        "--",
        *paths,
    ]


def shell_join(argv: list[str]) -> str:
    """Render `argv` as a copy-pasteable shell command for this platform."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def execute_clean(argv: list[str], target: Path) -> subprocess.CompletedProcess[bytes]:
    """Run `argv` in `target` under the scrubbed git environment.

    Global and system git config are neutralized (``scrubbed_git_env``), so
    "ignored" means ignored by the target's own ignore files, never by the
    operator's global excludes file. A non-zero exit is returned, not raised:
    the caller maps it to exit 1.
    """
    return subprocess.run(  # noqa: S603 # nosec B603
        argv, cwd=target, capture_output=True, env=scrubbed_git_env(), check=False
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py -q && uv run --no-sync ruff check src/template_press/rebrand/clean.py tests/rebrand/test_clean_cli.py && uv run --no-sync ruff format --check src/ tests/ && uv run --no-sync ty check src/template_press/`
Expected: all pass, no lint or type findings (bandit at pre-push accepts the annotated `subprocess.run`).

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/clean.py tests/rebrand/test_clean_cli.py
git commit -m "feat(clean): render declared clean paths and build the git clean argv"
```

---

### Task 3: `press clean` verb, dispatcher, and the E2 hint

**Files:**
- Create: `src/template_press/rebrand/clean_cli.py`
- Modify: `src/template_press/press_cli.py` (`_USAGE` and the verb dispatch, lines 18–46)
- Modify: `src/template_press/rebrand/cli.py:186` (`getattr(rules, "clean", ())` → `rules.clean`)
- Test: `tests/rebrand/test_clean_cli.py` (append)

**Interfaces:**
- Consumes: Task 2's four functions; `load_selected_rules`, `RULES_REL` (rules.py); `load_source_config`, `SOURCE_CONFIG_REL` (config.py); `resolve_executable`, `command_env` (regen.py).
- Produces: `clean_command(argv: list[str] | None = None) -> int` with `--target <dir>` (required) and `--show`.
- Exit codes: `0` ran (or previewed) successfully; `2` target not a directory, rules invalid, no active `[[clean]]` rule, `press/press-source.toml` missing or malformed, a rendered path invalid, or `git` unresolvable — nothing ran; `1` git exited non-zero — the tree may have changed.

- [ ] **Step 1: Write the failing tests** (append to `tests/rebrand/test_clean_cli.py`)

```python
class TestPressClean:
    def _target(self, src_target: Path, body: str = CLEAN_SRC_TESTS) -> Path:
        write_source_config(src_target)
        _declare(src_target, body)
        return src_target

    def test_show_previews_and_removes_nothing(self, src_target: Path, capsys):
        target = self._target(src_target)
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")
        assert press_cli.main(["clean", "--target", str(target), "--show"]) == 0
        out = capsys.readouterr().out
        assert "clean -ndX -- src/demo_widget tests" in out
        assert "Would remove src/demo_widget/__pycache__/" in out
        assert cache.exists()

    def test_run_removes_only_ignored_entries_under_declared_paths(self, src_target: Path, capsys):
        target = self._target(src_target)
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")
        survivor = target / "src" / "demo_widget" / "new.py"
        survivor.write_text("# untracked, not ignored\n", encoding="utf-8")
        outside = target / ".venv" / "lib"
        outside.parent.mkdir()
        outside.write_text("ignored, but outside the declared paths\n", encoding="utf-8")
        before = capture_surface_snapshot(target)
        assert press_cli.main(["clean", "--target", str(target)]) == 0
        out = capsys.readouterr().out
        assert "clean -fdX -- src/demo_widget tests" in out
        assert "Removing src/demo_widget/__pycache__/" in out
        assert not cache.exists()
        assert survivor.exists()
        assert outside.exists()
        assert capture_surface_snapshot(target) == before

    def test_absent_declared_path_is_a_silent_no_op(self, src_target: Path, capsys):
        target = self._target(src_target, '[[clean]]\npaths = ["missing"]\n')
        assert press_cli.main(["clean", "--target", str(target)]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1 and lines[0].startswith("run: ")

    def test_no_active_rule_exits_2(self, src_target: Path, capsys):
        foreign = "linux" if sys.platform == "win32" else "win32"
        target = self._target(src_target, f'[[clean]]\npaths = ["src"]\nplatforms = ["{foreign}"]\n')
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        assert "no [[clean]] rules declared in press/press-rules.toml" in capsys.readouterr().err

    def test_missing_source_config_exits_2(self, src_target: Path, capsys):
        _declare(src_target, CLEAN_SRC_TESTS)  # rules, but no press-source.toml
        assert press_cli.main(["clean", "--target", str(src_target)]) == 2
        assert "press-source.toml" in capsys.readouterr().err

    def test_unrenderable_placeholder_exits_2(self, src_target: Path, capsys):
        target = self._target(src_target, '[[clean]]\npaths = ["docs/{display_name}"]\n')
        assert press_cli.main(["clean", "--target", str(target)]) == 2
        assert "does not declare it" in capsys.readouterr().err

    def test_git_failure_exits_1(self, tmp_path: Path, capsys):
        # Rules and source config but no repository: git clean exits 128.
        not_a_repo = tmp_path / "plain"
        (not_a_repo / "press").mkdir(parents=True)
        (not_a_repo / "press" / "press-rules.toml").write_text(CLEAN_SRC_TESTS, encoding="utf-8")
        from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config

        (not_a_repo / SOURCE_CONFIG_REL).write_text(render_source_config(SOURCE), encoding="utf-8")
        assert press_cli.main(["clean", "--target", str(not_a_repo)]) == 1
        assert "git clean exited" in capsys.readouterr().err

    def test_missing_target_exits_2(self, tmp_path: Path):
        assert press_cli.main(["clean", "--target", str(tmp_path / "nope")]) == 2


class TestClosureRefusalHint:
    def _stale_cache(self, target: Path) -> None:
        cache = target / "src" / "demo_widget" / "__pycache__" / "x.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00")

    def test_names_press_clean_when_declared(self, src_target: Path, tmp_path: Path, capsys):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        self._stale_cache(src_target)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers), "--dry-run"]) == 2
        out = capsys.readouterr().out
        assert "absent from the authorized surface" in out
        assert f"declared clean rules exist — run: press clean --target {src_target}" in out

    def test_silent_when_not_declared(self, src_target: Path, tmp_path: Path, capsys):
        write_source_config(src_target)
        self._stale_cache(src_target)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers), "--dry-run"]) == 2
        out = capsys.readouterr().out
        assert "absent from the authorized surface" in out
        assert "press clean" not in out


def test_dispatcher_lists_and_routes_clean(tmp_path: Path, capsys):
    assert press_cli.main([]) == 0
    assert "clean" in capsys.readouterr().out
    assert press_cli.main(["clean", "--target", str(tmp_path / "nope")]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py -q`
Expected: the new tests fail with `unknown command 'clean'` (exit 2 where 0 was expected) and, for the hint test, the E2 hint absent because `Rules.clean` was empty before Task 1; the negative-direction test passes already.

- [ ] **Step 3: Write `clean_cli.py`, wire the dispatcher, drop the `getattr`**

```python
"""`press clean` — remove ignored entries under declared [[clean]] paths (E10).

A standalone verb: it renders the declared paths from press/press-source.toml,
echoes the exact git argv, runs ``git clean -fdX -- <paths>`` (``-ndX`` under
``--show``), and prints git's own output. It never runs inside
``press rebrand`` and never writes a receipt.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from template_press.rebrand.clean import (
    clean_argv,
    execute_clean,
    render_clean_paths,
    shell_join,
)
from template_press.rebrand.config import SOURCE_CONFIG_REL, load_source_config
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.regen import command_env, resolve_executable
from template_press.rebrand.rules import RULES_REL, load_selected_rules

# The configuration exception set every entry point normalizes to exit 2.
_CONFIG_ERRORS = (ValidationError, tomllib.TOMLDecodeError, UnicodeDecodeError, OSError)


def clean_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press clean", description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--show",
        action="store_true",
        help="preview with git clean -ndX and remove nothing",
    )
    args = parser.parse_args(argv)

    target = args.target.resolve()
    if not target.is_dir():
        print(f"error: target {target} is not a directory", file=sys.stderr)
        return 2
    try:
        rules = load_selected_rules(target).rules
        if not rules.clean:
            print(
                f"error: no [[clean]] rules declared in {RULES_REL.as_posix()}",
                file=sys.stderr,
            )
            return 2
        source = load_source_config(target, None)
        if source is None:
            print(
                f"error: {SOURCE_CONFIG_REL.as_posix()} is required to render "
                f"[[clean]] paths",
                file=sys.stderr,
            )
            return 2
        paths = render_clean_paths(rules.clean, source)
    except _CONFIG_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    git = resolve_executable(target, "git", command_env(()))
    if git is None:
        print("error: git — missing (press clean needs it)", file=sys.stderr)
        return 2

    command = clean_argv(git, target, paths, show=args.show)
    print(f"{'preview' if args.show else 'run'}: {shell_join(command)}")
    result = execute_clean(command, target)
    sys.stdout.write(result.stdout.decode("utf-8", "replace"))
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", "replace"))
        print(f"error: git clean exited {result.returncode}", file=sys.stderr)
        return 1
    return 0
```

`press_cli.py` — import `clean_cli` alongside `check_tools`, add the usage line between `verify` and `check-tools`:

```
  clean        remove ignored entries under declared [[clean]] paths (press clean --help)
```

and the dispatch before `check-tools`:

```python
    if verb == "clean":
        return clean_cli.clean_command(rest)
```

`cli.py:186` — replace `if getattr(rules, "clean", ()):` with `if rules.clean:`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py tests/rebrand/test_press_cli.py tests/rebrand/test_cli.py -q && uv run --no-sync ruff check src/ tests/rebrand/test_clean_cli.py && uv run --no-sync ruff format --check src/ tests/ && uv run --no-sync ty check src/template_press/`
Expected: all pass. If `Removing src/demo_widget/__pycache__/` is not in the output on some git version, read git's actual line from the failure and pin that exact text.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/clean_cli.py src/template_press/press_cli.py src/template_press/rebrand/cli.py tests/rebrand/test_clean_cli.py
git commit -m "feat(cli): press clean — declared, git clean -X based pre-press cleanup"
```

---

### Task 4: check-tools row and receipt row

**Files:**
- Modify: `src/template_press/rebrand/check_tools.py` (after the `git` row, before the edit loop, line ~54)
- Modify: `src/template_press/rebrand/receipt.py` (`write_receipt` signature line 83 and the row loops)
- Modify: `src/template_press/rebrand/cli.py` (`write_receipt(...)` call at line ~962)
- Test: `tests/rebrand/test_clean_cli.py` (append)

**Interfaces:**
- Produces: `write_receipt(..., clean: Sequence[Sequence[str]] = ())` (keyword-only, after `origin`) emitting one `[[press.clean]]` table with `paths = [...]` per rule, the declared patterns unrendered.
- `press check-tools` prints one informational row per active clean rule: `git — <path> (cleans src/{package_name}, tests)`. A missing git is already counted by the existing first row, so no new missing path is added.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestIntegrations:
    def test_check_tools_reports_one_row_per_clean_rule(self, src_target: Path, capsys):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS + '[[clean]]\npaths = ["build"]\n')
        assert press_cli.main(["check-tools", "--target", str(src_target)]) == 0
        out = capsys.readouterr().out
        assert "(cleans src/{package_name}, tests)" in out
        assert "(cleans build)" in out

    def test_receipt_records_the_declaration_unrendered(self, src_target: Path, tmp_path: Path):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        raw = (src_target / RECEIPT_REL).read_text(encoding="utf-8")
        assert "[[press.clean]]" in raw
        assert 'paths = ["src/{package_name}", "tests"]' in raw
        receipt = tomllib.loads(raw)
        assert receipt["press"]["clean"] == [{"paths": ["src/{package_name}", "tests"]}]
        assert "ran" not in raw.split("[[press.clean]]", 1)[1]

    def test_receipt_has_no_clean_table_without_rules(self, src_target: Path, tmp_path: Path):
        write_source_config(src_target)
        answers = write_answers(tmp_path)
        assert main(["--target", str(src_target), "--config", str(answers)]) == 0
        assert "[[press.clean]]" not in (src_target / RECEIPT_REL).read_text(encoding="utf-8")

    def test_verify_is_unaffected_by_a_clean_declaration(self, src_target: Path, capsys):
        write_source_config(src_target)
        _declare(src_target, CLEAN_SRC_TESTS)
        code = verify_command(["--target", str(src_target)])
        with_rule = capsys.readouterr().out
        _declare(src_target, "[rules]\n")
        assert verify_command(["--target", str(src_target)]) == code
        assert capsys.readouterr().out == with_rule
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py::TestIntegrations -q`
Expected: the check-tools and receipt tests fail on the missing row/table; the no-rules and verify tests pass already.

- [ ] **Step 3: Implement**

`check_tools.py`, directly after the `git` row block:

```python
    # Clean runs BEFORE a press, so its rows lead. Git is the only tool a
    # clean needs and is already reported above; these rows are informational.
    if git is not None:
        for clean in rules.clean:
            reports.append(f"git — {git} (cleans {', '.join(clean.paths)})")
```

`receipt.py` — add `clean: Sequence[Sequence[str]] = (),` as the last keyword-only parameter of `write_receipt`, and after the `[[press.remove]]` loop:

```python
    # Declared clean paths (E10). `press clean` is a standalone verb that
    # never writes a receipt, so this row records the DECLARATION an
    # operator should run before re-pressing — never that cleaning ran.
    for paths in clean:
        lines += [
            "",
            "[[press.clean]]",
            "paths = [" + ", ".join(toml_string(p) for p in paths) + "]",
        ]
```

`cli.py` — in the `write_receipt(...)` call, add `clean=[rule.paths for rule in rules.clean],` after `origin=origin,` (`rules` is the active `Rules` already in scope there).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync pytest tests/rebrand/test_clean_cli.py tests/rebrand/test_check_tools.py tests/rebrand/test_receipt.py tests/rebrand/test_verify_cli.py -q && uv run --no-sync ruff check src/ && uv run --no-sync ruff format --check src/ tests/ && uv run --no-sync ty check src/template_press/`
Expected: all pass (use the receipt test module's actual filename if it differs from `test_receipt.py`).

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/check_tools.py src/template_press/rebrand/receipt.py src/template_press/rebrand/cli.py tests/rebrand/test_clean_cli.py
git commit -m "feat(clean): report clean rules in check-tools and record them in the receipt"
```

---

### Task 5: Docs, ADR, runbook step, and this repository's own declaration

**Files:**
- Create: `docs/adr/0018-declared-pre-press-clean.md`
- Modify: `docs/source/reference/cli.md` (new `## press clean` section after `## press check-tools`, which ends near line 670)
- Modify: `.claude/skills/press-target/SKILL.md` (Steps, line 17 onward)
- Modify: `press/press-rules.toml` (this repository's declaration)
- Modify: `tests/rebrand/test_matrix.py::test_r3_self_press_native` (line 85 onward)

- [ ] **Step 1: Write the failing R3 assertion**

In `test_r3_self_press_native`, after `receipt = tomllib.loads(raw_receipt)` (line ~130):

```python
    # E10: this repo declares its own clean paths; the native press records
    # the declaration, unrendered, and `press clean --show` previews cleanly.
    assert receipt["press"]["clean"] == [{"paths": ["src/{package_name}", "tests"]}]
    assert press_cli.main(["clean", "--target", str(target), "--show"]) == 0
```

(add `from template_press import press_cli` to the module imports if absent).

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --no-sync pytest tests/rebrand/test_matrix.py::test_r3_self_press_native -m live -q`
Expected: `KeyError: 'clean'` — the repository declares no `[[clean]]` yet.

- [ ] **Step 3: Declare, document, record**

`press/press-rules.toml`, after the `[[edit]]` table:

```toml
# Stale build caches under the package directory (`__pycache__`, `.pytest_cache`
# trees) are ignored, so they are invisible to the surface inventory and would
# trip the rename-closure refusal (E2) when the package directory is renamed.
# Declaring them lets `press clean --target <clone>` remove exactly those
# before a press; nothing inventoried can be touched (git clean -X).
[[clean]]
paths = ["src/{package_name}", "tests"]
```

`docs/adr/0018-declared-pre-press-clean.md`:

```markdown
# 0018. Declared pre-press clean is a standalone verb over `git clean -X`

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** Maintainers
- **Related:** [external-target model](../design/0006-external-target-model.md);
  [press improvements design](../superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E10; [CLEAN review](../superpowers/specs/reviews-2026-09-01/CLEAN-review.md);
  [P10 planning gate](../superpowers/specs/reviews-2026-09-05/P10-planning-gate.md);
  [project P10](../../projects/P10-declared-pre-press-clean.md)

## Context

A press renames the package directory. The rename-closure guard refuses when
that directory holds content absent from the surface inventory, and the
commonest such content is an ignored build cache (`__pycache__`). The refusal
already prints a `git clean -fdX` remedy, but the remedy is undeclared,
operator-typed, and broader than the paths at fault. A template should be
able to declare which paths an operator may clean.

## Decision

Add `[[clean]] paths = [...]` (optional `platforms`) and a standalone
`press clean --target <dir> [--show]` verb. The engine renders each path from
the SOURCE identity (the rules file is never rewritten), echoes the exact
hardened argv, and runs `git --literal-pathspecs clean -fdX -- <paths>`
(`-ndX` under `--show`). Only ignored entries under the declared paths can be
removed; the operator's global excludes file is not consulted because every
on-target git call runs under the scrubbed environment.

Clean is never a phase of `press rebrand`: dry-run and apply must observe the
same tree. Ordering is structural — the closure refusal names `press clean`
when rules are declared — with no stamp file. `press verify` is unaffected by
construction (the sandbox holds inventoried entries only). The receipt records
`[[press.clean]] paths = [...]` as a declaration; `press clean` writes no
receipt. `press check-tools` lists one informational row per rule.

## Consequences

- Exit codes keep the 0/1/2 contract, with `1` meaning git ran and failed,
  so the tree may have changed.
- Arbitrary clean commands remain out of scope; they would need the
  before/after invariant the CLEAN review specified.
- A declared path that matches nothing is a silent no-op (`git clean` exits 0).
```

`docs/source/reference/cli.md`, after the `## press check-tools` section:

```markdown
## `press clean`

Removes ignored entries under the paths a target declares in
`press/press-rules.toml`, so a stale build cache under a directory that a
press will rename does not trip the rename-closure refusal. It is a
standalone verb — never a phase of `press rebrand`, because dry-run and apply
must observe the same tree — and it writes no receipt.

```toml
[[clean]]
paths = ["src/{package_name}", "tests"]   # optional: platforms = ["darwin", "linux"]
```

Placeholders render from the SOURCE identity in `press/press-source.toml`
(the rules file is never rewritten). Each path must be relative and
contained; unknown placeholders and control characters are refused at
config load, and the rendered path is validated again at run time.

```console
$ press clean --target ../my-repo --show
preview: git -C /abs/my-repo --work-tree=/abs/my-repo -c core.fsmonitor= … --literal-pathspecs clean -ndX -- src/my_pkg tests
Would remove src/my_pkg/__pycache__/
$ press clean --target ../my-repo
run: git -C /abs/my-repo --work-tree=/abs/my-repo -c core.fsmonitor= … --literal-pathspecs clean -fdX -- src/my_pkg tests
Removing src/my_pkg/__pycache__/
```

The echoed line is the exact command that runs, hardening flags included.
`-X` removes ignored entries only (never `-x`), `--literal-pathspecs` makes
each declared path a path rather than a glob, and the scrubbed git
environment means "ignored" is decided by the target's own ignore files, not
by your global excludes file. A declared path that matches nothing is a
silent no-op.

| Code | Meaning |
|------|---------|
| `0` | The preview or the clean ran and git exited 0. |
| `1` | git ran and exited non-zero — the tree may have changed; read git's message. |
| `2` | Nothing ran: target missing, rules invalid, no active `[[clean]]` rule, `press/press-source.toml` missing, a path unrenderable, or `git` unresolvable. |

A successful `press rebrand` records the declaration in the receipt as
`[[press.clean]] paths = [...]` (as declared, unrendered) so a later operator
knows to run `press clean` before re-pressing; the row never means that a
clean ran. `press check-tools` lists one `git — … (cleans …)` row per active
rule. `press verify` ignores the declaration by construction: its sandbox
receives inventoried entries only.
```

`.claude/skills/press-target/SKILL.md` — insert after step 1:

```markdown
1b. If `<TARGET>/press/press-rules.toml` declares `[[clean]]`, preview and
    then run it before the dry run: `press clean --target <TARGET> --show`,
    confirm the listing holds nothing to keep, then
    `press clean --target <TARGET>`. Skip this when no rules are declared;
    the dry run's closure refusal names `press clean` if it is needed.
```

- [ ] **Step 4: Run the native R3 and the docs gates**

Run: `uv run --no-sync pytest tests/rebrand/test_matrix.py::test_r3_self_press_native -m live -q && uv run --no-sync codespell docs/adr/0018-declared-pre-press-clean.md docs/source/reference/cli.md .claude/skills/press-target/SKILL.md press/press-rules.toml && uv run --no-sync ec docs/adr/0018-declared-pre-press-clean.md docs/source/reference/cli.md .claude/skills/press-target/SKILL.md press/press-rules.toml && taplo check press/press-rules.toml --config .taplo.toml`
Expected: R3 passes (the native press clones committed content, so commit `press/press-rules.toml` first if the test reads the committed tree — it does); spelling, editorconfig, and TOML checks clean.

- [ ] **Step 5: Commit**

```bash
git add press/press-rules.toml tests/rebrand/test_matrix.py docs/adr/0018-declared-pre-press-clean.md docs/source/reference/cli.md .claude/skills/press-target/SKILL.md
git commit -m "docs(clean): adr 0018, press clean reference, runbook step, and this repo's own [[clean]] declaration"
```

---

### Task 6: PR close

- [ ] `just check` (full pipeline) and `just matrix` (mandatory after any `rebrand/` change) both green; background anything longer than five minutes with a log file.
- [ ] Push; open PR `feat: press clean and [[clean]] declarations (P10)` against `main`; body cites spec §E10, the gate record, the exit-code table, and states explicitly that clean never runs inside `press rebrand`.
- [ ] Triage every bot review thread (fix, refute, decline, or defer with a tracked reference); merge with a merge commit.
- [ ] Route the P10 tracker flip through the project-harness skills; do not hand-edit PROJECTS.md.

## Self-review

- **Spec coverage (§E10):** declaration shape and placeholder rules → Task 1; engine runs `git clean -fdX` with no arbitrary argv → Task 2; standalone verb with `--show` and the echoed command → Task 3; structural ordering via the E2 hint → Task 3; verify unaffected, check-tools row, receipt row → Task 4; `_ROOT_KEYS` → Task 1; every spec test bullet has a named test in Tasks 1–4; native coverage → Task 5.
- **Placeholder scan:** none; every step carries its code or exact text.
- **Type consistency:** `CleanRule.paths: tuple[str, ...]` (Task 1) is what `render_clean_paths(rules: tuple[CleanRule, ...], source: Identity)` consumes (Task 2); `clean_argv(git: Path, target: Path, paths: tuple[str, ...], *, show: bool) -> list[str]` and `execute_clean(argv: list[str], target: Path)` are the names Task 3 imports; `write_receipt(..., clean: Sequence[Sequence[str]])` receives `[rule.paths for rule in rules.clean]` (Task 4).
