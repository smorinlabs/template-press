# Rebrand Core (Clean-Core Rebuild M0–M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `press rebrand --target PATH` — a standalone utility that discovers/validates an external target repo's identity, rewrites it with the proven engine, verifies zero identity leftovers, and only then writes a receipt — so a wrong or partial run fails loudly instead of silently corrupting the target.

**Architecture:** New subpackage `src/template_press/rebrand/` (the tool IS the package; the legacy app in `core/`/`cli/`/`web/` is untouched residue until successor plan M4). Scan-based rules replace the per-file manifest: every tracked text file in the *target* is rewritten with field-driven boundary-safe token replacement; renames are computed per path component; a doctor pass gates the receipt. Ports come from the salvage branch `feat/init-rebrand-robustness` (the empirically verified R3 engine + word-boundary matcher combination), generalized from module-global identity to per-run `Identity` values.

**Tech Stack:** Python 3.12+ stdlib only (`tomllib`, `re`, `dataclasses`, `subprocess`, `argparse`) — zero new dependencies. pytest for tests. `git ls-files` for target file enumeration.

## Global Constraints

- Phase names (locked): **Rebrand** (identity press) / **Provision** (feature setup); end-state "launch-ready".
- CLI form (locked, OQ decision log): `press rebrand --target PATH`; interim invocation until M4 repoints console scripts: `python -m template_press.rebrand.cli`.
- Identity model (locked, OQ3): source/FROM identity is authoritative from a committed config (`<target>/.press/source.toml`); discovery is a **validator** that fails loudly on mismatch — never the silent source of truth. Destination/TO identity from an answers TOML.
- Verify-then-mark (locked, EMP-01): receipt (`<target>/.press/receipt.toml`) is written **only** after the no-leak doctor pass; leaks ⇒ exit 1, no receipt.
- Boundary-safe replacement is the **default** (locked, OQ12), field-driven: `app_name`/`app_name_upper` use lookaround token patterns; long unique tokens use plain substring, longest-first.
- State lives in the **target** (locked, OQ5): `.press/` directory. The tool's repo stays clean between runs.
- Version stays `2.1.1` in this plan; reset to `0.1.0` happens in successor plan M5 (locked).
- Do NOT modify `init/`, the legacy app (`src/template_press/core|cli|web`), or existing tests — they are residue handled by successor plan M4.
- Code style: 88-char lines, strict typing on all functions, absolute intra-package imports (`from template_press.rebrand…`), ruff clean.
- Commits: Conventional Commits, lowercase subject. Hooks must be live (`just setup` once per fresh clone).
- Exit codes (contract for all tasks): `0` success · `1` verification failure (leaks after apply) · `2` precondition/config/validation error (nothing applied).

## Program map (context — this plan is M0–M3)

| Milestone | Scope | Plan |
|---|---|---|
| M0 | Design doc 0006 (canonical external-target model), supersession banner on 0004 | **this plan, Task 1** |
| M1 | Clean core: identity, rules, engine (replace+rename), doctor — fixtures-first | **this plan, Tasks 2–8** |
| M2 | Target & identity: discovery, source-config, receipt, CLI orchestrator | **this plan, Tasks 9–13** |
| M3 | Prove it: R1/R2/R3 matrix (script + live tests + CI), press-target & rebrand-matrix skills | **this plan, Tasks 14–15** |
| M4 | Shed residue: delete app+tests+init/, doc site → publishable skeleton, docs rewrite (incl. stale "Py Launch Blueprint" CLAUDE.md heading), repoint `press` console script | successor plan |
| M5 | Self-publish: version reset 0.1.0, fresh CHANGELOG, release-please bootstrap, PyPI (`template-press` reserved), release skill | successor plan |
| M6 | Provision phase: feature modules (detect/add/verify), `press status` computed from reality; reference = blueprint's post_init.py @ HEAD | successor plan |

Port sources (read-only references; never merge the salvage branch):
`git show feat/init-rebrand-robustness:init/common.py` (matcher, validators),
`git show feat/init-rebrand-robustness:init/_engine.py` (engine),
`git show feat/init-rebrand-robustness:init/init_doctor.py` (no-leak check).

## File structure

```
src/template_press/rebrand/
  __init__.py        # empty marker
  identity.py        # Identity dataclass, validators, boundary token patterns
  rules.py           # Rules dataclass, DEFAULT_RULES, per-target overrides
  engine.py          # iter_target_files, build_plan, apply (replace + rename)
  doctor.py          # find_leaks — the verify-then-mark gate
  discovery.py       # discover(target), mismatches(source, found)
  config.py          # source-config + answers TOML load/render
  receipt.py         # read/render/write .press/receipt.toml
  cli.py             # argparse main(); python -m template_press.rebrand.cli
tests/rebrand/
  __init__.py
  conftest.py        # SOURCE/DEST identities + make_target fixture factory
  test_identity.py   test_rules.py   test_engine_replace.py
  test_engine_rename.py  test_doctor.py  test_discovery.py
  test_config.py     test_receipt.py    test_cli.py
  test_matrix.py     # @pytest.mark.live — real blueprint clone (M3)
scripts/rebrand_matrix.sh          # R1/R2/R3 acceptance matrix (M3)
.github/workflows/rebrand-matrix.yml
.claude/skills/press-target/SKILL.md
.claude/skills/rebrand-matrix/SKILL.md
docs/design/0006-external-target-model.md
```

---

### Task 1: Design doc 0006 + supersession banner (M0)

**Files:**
- Create: `docs/design/0006-external-target-model.md`
- Modify: `docs/design/0004-template-press-plan.md:3` (status line)

**Interfaces:**
- Produces: the canonical model doc every later task's docstrings may cite.

- [ ] **Step 1: Write the design doc**

Create `docs/design/0006-external-target-model.md`:

```markdown
# 0006 — template-press external-target model (canonical)

- **Status:** Accepted (2026-06-23). Supersedes 0004 §3–7 and 0005.
- **Decision record:** OPEN_QUESTIONS.md decision log (2026-06-15, on branch
  `feat/init-rebrand-robustness`) + phase-naming decisions (2026-06-23).

## What template-press is

A standalone rebrand/config utility, published to PyPI (`uvx template-press`),
that operates on **external target repos, one at a time**. It is NOT a Python
project template and ships no application. First target:
`smorinlabs/py-launch-blueprint` (the repo it was extracted from).

## The two phases

| Phase | Verb | Does | Deliverable |
|---|---|---|---|
| Rebrand | `press rebrand --target PATH` | identity press: files only | target compiles/imports/tests under new identity |
| Provision | `press provision --target PATH` | feature setup: repo + services | **launch-ready** repository |

`press status --target PATH` computes feature state from reality (files,
`gh` API, PyPI API) — never merely stored (design 0004 D10, retained).

## Rebrand model (this repo's current work)

1. **Source identity is config-first**: `<target>/.press/source.toml`
   (committed in the target) is authoritative. Discovery (pyproject name,
   `[project.scripts]` key, git origin, src/flat layout) **validates** it and
   fails loudly on mismatch. Discovery never silently drives a run.
2. **Rules are generic and scan-based**: the tool carries rewrite rules
   (boundary-safe by default); it does not carry any target's identity or
   file list. Per-target overrides: `<target>/.press/rules.toml`.
3. **Verify-then-mark**: after apply, a no-leak doctor pass scans the target
   for surviving source-identity tokens. Any leak ⇒ exit 1 and NO receipt.
   The receipt (`<target>/.press/receipt.toml`) records the verified state.
4. **The tool never ships into the target** — no marker in the tool's tree,
   no self-prune, no self-commit.

## Superseded documents

- 0004 §3–7 (in-place `press/` directory contract, cwd-rewriting CLI) — the
  in-place operating model is replaced by `--target`.
- 0005 (TUI design) — deferred with Provision; reopens against the
  external-target model.
- Dogfood v1–v3 conclusions (py-launch-blueprint repo) — build #1 tested the
  in-place path only; its "convergence" claim was retracted.

## Provenance

Findings and the empirical 3-run matrix that proved the engine and located
the architectural defects (ARCH-01/02/03, EMP-01) live on branch
`feat/init-rebrand-robustness`: BUGS.md, EMPIRICAL_BUGS.md, EMPIRICAL_ARCH.md,
OPEN_QUESTIONS.md.
```

- [ ] **Step 2: Add the supersession banner to 0004**

In `docs/design/0004-template-press-plan.md`, change line 3:

```markdown
- **Status:** Accepted (implementation not started)
```

to:

```markdown
- **Status:** Superseded in part (2026-06-23) — §3–7 (in-place model) are
  replaced by [0006](0006-external-target-model.md); §1–2 naming decisions
  and D10 (computed status) remain accepted.
```

- [ ] **Step 3: Commit**

```bash
git add docs/design/0006-external-target-model.md docs/design/0004-template-press-plan.md
git commit -m "docs(design): add 0006 external-target model; supersede 0004 in-place sections"
```

---

### Task 2: identity.py — Identity, validators, boundary patterns (M1)

**Files:**
- Create: `src/template_press/rebrand/__init__.py` (empty)
- Create: `src/template_press/rebrand/identity.py`
- Test: `tests/rebrand/__init__.py` (empty), `tests/rebrand/test_identity.py`

**Interfaces:**
- Produces: `Identity` (frozen dataclass; fields `package_name, repo_name, app_name, author, email, owner`; property `app_name_upper`; methods `as_dict() -> dict[str, str]`, `validate() -> None`, classmethod `from_mapping(data: dict[str, str]) -> Identity`), `ValidationError(ValueError)`, `token_pattern(field: str, value: str) -> re.Pattern[str] | None`, `replace_token(text: str, field: str, current: str, replacement: str) -> str`, `token_occurs(text: str, field: str, value: str) -> bool`. Every later task consumes these.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_identity.py`:

```python
"""Identity model + boundary-safe token matching."""

import pytest

from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    replace_token,
    token_occurs,
    token_pattern,
)


def make_identity(**overrides) -> Identity:
    base = dict(
        package_name="demo_widget",
        repo_name="demo-widget",
        app_name="press",
        author="Demo Author",
        email="demo@example.com",
        owner="demolabs",
    )
    base.update(overrides)
    return Identity(**base)


def test_app_name_upper_is_derived():
    ident = make_identity()
    assert ident.app_name_upper == "PRESS"
    assert ident.as_dict()["app_name_upper"] == "PRESS"


def test_as_dict_has_all_seven_fields():
    keys = set(make_identity().as_dict())
    assert keys == {
        "package_name",
        "repo_name",
        "app_name",
        "app_name_upper",
        "author",
        "email",
        "owner",
    }


def test_validate_accepts_good_identity():
    make_identity().validate()  # must not raise


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("package_name", "Demo-Widget"),
        ("repo_name", "Demo_Widget"),
        ("app_name", "my-app"),
        ("email", "not-an-email"),
        ("owner", "-bad-"),
    ],
)
def test_validate_rejects_bad_values(field, bad):
    with pytest.raises(ValidationError):
        make_identity(**{field: bad}).validate()


def test_from_mapping_round_trip():
    ident = make_identity()
    data = {k: v for k, v in ident.as_dict().items() if k != "app_name_upper"}
    assert Identity.from_mapping(data) == ident


def test_from_mapping_missing_key_raises():
    with pytest.raises(ValidationError, match="app_name"):
        Identity.from_mapping({"package_name": "x"})


# --- boundary safety: the C-1/INIT-02 regression tests -------------------

PROSE = "Compress the archive; express delivery raises pressure. Run press now."


def test_app_name_replacement_spares_english_words():
    out = replace_token(PROSE, "app_name", "press", "potato")
    assert "Compress" in out and "express" in out and "pressure" in out
    assert out.endswith("Run potato now.")


def test_app_name_matches_env_var_and_file_prefix_positions():
    # underscore is a separator on the RIGHT of app_name (press_config.toml)
    assert replace_token("press_config.toml", "app_name", "press", "potato") == (
        "potato_config.toml"
    )
    # but not on the left (foo_press is not the token)
    assert token_occurs("foo_press", "app_name", "press") is False


def test_app_name_upper_env_prefix_replaced():
    text = "export PRESS_LOG_LEVEL=debug  # _PRESS_COMPLETE too"
    out = replace_token(text, "app_name_upper", "PRESS", "POTATO")
    assert "POTATO_LOG_LEVEL" in out and "_POTATO_COMPLETE" in out


def test_app_name_upper_spares_embedded_words():
    assert (
        replace_token("EXPRESS IMPRESSION", "app_name_upper", "PRESS", "POTATO")
        == "EXPRESS IMPRESSION"
    )


def test_long_tokens_use_plain_substring():
    assert token_pattern("package_name", "demo_widget") is None
    out = replace_token(
        "import demo_widget.cli", "package_name", "demo_widget", "potato_launcher"
    )
    assert out == "import potato_launcher.cli"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'template_press.rebrand'`

- [ ] **Step 3: Implement identity.py**

Create empty `src/template_press/rebrand/__init__.py` and `tests/rebrand/__init__.py`. Then create `src/template_press/rebrand/identity.py` (validators ported verbatim from `git show feat/init-rebrand-robustness:init/common.py` lines 133–197; token patterns ported from lines 102–130, generalized from module-global identity to field-driven):

```python
"""Identity model and boundary-safe token matching for the rebrand press.

Ported from the proven init/ engine (branch feat/init-rebrand-robustness):
validators from init/common.py:133-197, boundary patterns from
init/common.py:102-130 — generalized from a module-global BLUEPRINT_IDENTITY
to per-run values so any target's identity can be pressed (ARCH-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PYTHON_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REPO_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
GITHUB_OWNER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(ValueError):
    """Raised when an identity field fails its validator."""


def validate_package_name(name: str) -> str:
    if not PYTHON_IDENTIFIER_RE.fullmatch(name):
        raise ValidationError(
            f"package name must be a valid lowercase Python identifier "
            f"(matching {PYTHON_IDENTIFIER_RE.pattern}): {name!r}"
        )
    return name


def validate_repo_name(name: str) -> str:
    if not REPO_NAME_RE.fullmatch(name):
        raise ValidationError(
            f"repo name must be lowercase alphanumeric + hyphens "
            f"(matching {REPO_NAME_RE.pattern}): {name!r}"
        )
    return name


def validate_owner(name: str) -> str:
    if not GITHUB_OWNER_RE.fullmatch(name):
        raise ValidationError(
            f"GitHub owner must be 1-39 chars, alphanumeric + hyphens, "
            f"not starting/ending with hyphen: {name!r}"
        )
    return name


def validate_email(value: str) -> str:
    if not EMAIL_RE.fullmatch(value):
        raise ValidationError(f"email must look like local@domain.tld: {value!r}")
    return value


def validate_app_name(name: str) -> str:
    # The app short name becomes the CLI command, file name prefixes
    # (<app>_config.toml), and — uppercased — the env-var prefix, so it must
    # be identifier-safe (no hyphens: ACME-X is not a valid env var).
    if not PYTHON_IDENTIFIER_RE.fullmatch(name):
        raise ValidationError(
            f"app name must be a valid lowercase Python identifier "
            f"(matching {PYTHON_IDENTIFIER_RE.pattern}): {name!r}"
        )
    return name


VALIDATORS = {
    "package_name": validate_package_name,
    "repo_name": validate_repo_name,
    "app_name": validate_app_name,
    "owner": validate_owner,
    "email": validate_email,
}

REQUIRED_FIELDS: tuple[str, ...] = (
    "package_name",
    "repo_name",
    "app_name",
    "author",
    "email",
    "owner",
)


@dataclass(frozen=True)
class Identity:
    """One repo identity — either the source (FROM) or destination (TO)."""

    package_name: str
    repo_name: str
    app_name: str
    author: str
    email: str
    owner: str

    @property
    def app_name_upper(self) -> str:
        return self.app_name.upper()

    def as_dict(self) -> dict[str, str]:
        return {
            "package_name": self.package_name,
            "repo_name": self.repo_name,
            "app_name": self.app_name,
            "app_name_upper": self.app_name_upper,
            "author": self.author,
            "email": self.email,
            "owner": self.owner,
        }

    def validate(self) -> None:
        for field_name, value in self.as_dict().items():
            validator = VALIDATORS.get(field_name)
            if validator is not None:
                validator(value)

    @classmethod
    def from_mapping(cls, data: dict[str, str]) -> Identity:
        missing = [k for k in REQUIRED_FIELDS if k not in data]
        if missing:
            raise ValidationError(f"identity is missing fields: {', '.join(missing)}")
        return cls(**{k: data[k] for k in REQUIRED_FIELDS})


def token_pattern(field: str, value: str) -> re.Pattern[str] | None:
    """Boundary matcher for fields whose values are unsafe as raw substrings.

    An app token like ``press`` is an English word inside unrelated prose
    (compress, expression, pressure). Match it as a standalone token or a
    filename/env prefix, never inside another word. Underscore counts as a
    separator on the RIGHT of app_name (press_config.toml) and on the LEFT
    of app_name_upper (_PRESS_COMPLETE) — mirroring the proven matcher.
    Long compound tokens (package/repo names) return None: plain substring
    replacement, longest-first, is exact for them.
    """
    if field == "app_name":
        return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9-])")
    if field == "app_name_upper":
        return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z0-9-])")
    return None


def token_occurs(text: str, field: str, value: str) -> bool:
    pattern = token_pattern(field, value)
    if pattern is not None:
        return pattern.search(text) is not None
    return value in text


def replace_token(text: str, field: str, current: str, replacement: str) -> str:
    pattern = token_pattern(field, current)
    if pattern is not None:
        return pattern.sub(replacement, text)
    return text.replace(current, replacement)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_identity.py -q`
Expected: all PASS

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand && uv run ruff format src/template_press/rebrand tests/rebrand
uv run --extra web ty check src/template_press/
git add src/template_press/rebrand tests/rebrand
git commit -m "feat(rebrand): identity model with boundary-safe token matching"
```

---

### Task 3: rules.py — scan rules + per-target overrides (M1)

**Files:**
- Create: `src/template_press/rebrand/rules.py`
- Test: `tests/rebrand/test_rules.py`

**Interfaces:**
- Produces: `Rules` (frozen dataclass: `exclude_dirs: frozenset[str]`, `exclude_files: frozenset[str]`, `regenerate: tuple[str, ...]`), `DEFAULT_RULES: Rules`, `load_rules(target: Path) -> Rules` (merges `<target>/.press/rules.toml` if present).
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_rules.py`:

```python
from pathlib import Path

from template_press.rebrand.rules import DEFAULT_RULES, Rules, load_rules


def test_defaults_exclude_state_and_vcs_dirs():
    assert ".git" in DEFAULT_RULES.exclude_dirs
    assert ".press" in DEFAULT_RULES.exclude_dirs
    assert "uv.lock" in DEFAULT_RULES.exclude_files
    assert "uv.lock" in DEFAULT_RULES.regenerate


def test_load_rules_without_override_returns_defaults(tmp_path: Path):
    assert load_rules(tmp_path) == DEFAULT_RULES


def test_load_rules_merges_target_overrides(tmp_path: Path):
    press = tmp_path / ".press"
    press.mkdir()
    (press / "rules.toml").write_text(
        '[rules]\n'
        'extra_exclude_dirs = ["vendored"]\n'
        'extra_exclude_files = ["docs/history.md"]\n'
        'regenerate = ["uv.lock", "bun.lock"]\n',
        encoding="utf-8",
    )
    rules = load_rules(tmp_path)
    assert "vendored" in rules.exclude_dirs
    assert ".git" in rules.exclude_dirs  # defaults kept
    assert "docs/history.md" in rules.exclude_files
    assert rules.regenerate == ("uv.lock", "bun.lock")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_rules.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.rules`

- [ ] **Step 3: Implement rules.py**

```python
"""Scan rules the tool carries + per-target overrides (OQ4 hybrid model).

The tool never carries a target's identity or file list — only generic
rules: what to skip and which lockfiles to regenerate after a rebrand.
A target may extend them via <target>/.press/rules.toml.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

RULES_REL = Path(".press") / "rules.toml"


@dataclass(frozen=True)
class Rules:
    exclude_dirs: frozenset[str]
    exclude_files: frozenset[str]  # POSIX paths relative to the target root
    regenerate: tuple[str, ...]  # lockfiles regenerated (not rewritten)


DEFAULT_RULES = Rules(
    exclude_dirs=frozenset(
        {
            ".git",
            ".press",
            "node_modules",
            ".venv",
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
        }
    ),
    exclude_files=frozenset(
        {"uv.lock", "bun.lock", "package-lock.json", "CHANGELOG.md"}
    ),
    regenerate=("uv.lock",),
)


def load_rules(target: Path) -> Rules:
    """DEFAULT_RULES, extended by the target's .press/rules.toml if present."""
    override_path = target / RULES_REL
    if not override_path.is_file():
        return DEFAULT_RULES
    data = tomllib.loads(override_path.read_text(encoding="utf-8"))
    table = data.get("rules", {})
    return Rules(
        exclude_dirs=DEFAULT_RULES.exclude_dirs
        | frozenset(table.get("extra_exclude_dirs", [])),
        exclude_files=DEFAULT_RULES.exclude_files
        | frozenset(table.get("extra_exclude_files", [])),
        regenerate=tuple(table.get("regenerate", DEFAULT_RULES.regenerate)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_rules.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/rules.py tests/rebrand/test_rules.py
git commit -m "feat(rebrand): scan rules with per-target overrides"
```

---

### Task 4: Fixture target factory (M1)

**Files:**
- Create: `tests/rebrand/conftest.py`
- Test: `tests/rebrand/test_fixtures.py`

**Interfaces:**
- Produces: `SOURCE: Identity` (demo_widget/demo-widget/press/Demo Author/demo@example.com/demolabs), `DEST: Identity` (potato_launcher/potato-launcher/potato/Potato Farmer/potato@example.com/potatolabs), `make_target(base: Path, layout: str = "src") -> Path` — builds a committed mini git repo impersonating a real target, and the pytest fixture `src_target(tmp_path)`.
- Consumes: `Identity` from Task 2.

- [ ] **Step 1: Write conftest.py**

```python
"""Fixture targets: minimal-but-real repos the press is aimed at in tests.

app_name deliberately = "press" so English-word traps (compress, express,
pressure) exercise boundary safety — the empirically proven danger case.
DEST mirrors the potato identity used by the EMPIRICAL_BUGS.md live matrix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.identity import Identity

SOURCE = Identity(
    package_name="demo_widget",
    repo_name="demo-widget",
    app_name="press",
    author="Demo Author",
    email="demo@example.com",
    owner="demolabs",
)

DEST = Identity(
    package_name="potato_launcher",
    repo_name="potato-launcher",
    app_name="potato",
    author="Potato Farmer",
    email="potato@example.com",
    owner="potatolabs",
)

PYPROJECT = """\
[project]
name = "demo_widget"
version = "0.1.0"
description = "Demo widget by Demo Author"
authors = [{ name = "Demo Author", email = "demo@example.com" }]
requires-python = ">=3.12"

[project.scripts]
press = "demo_widget.cli:main"
"""

README = """\
# demo-widget

Compress the archive before express delivery; do not let the pressure rise.
Run `press --help`. Repo: https://github.com/demolabs/demo-widget
Maintained by Demo Author <demo@example.com>.
"""

CLI_PY = '''\
"""demo_widget CLI (env prefix PRESS_*)."""

import os


def main() -> int:
    level = os.environ.get("PRESS_LOG_LEVEL", "info")
    complete = os.environ.get("_PRESS_COMPLETE")
    print(f"demo_widget cli level={level} complete={complete}")
    return 0
'''


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def make_target(base: Path, layout: str = "src") -> Path:
    """Build a committed mini target repo. layout: 'src' or 'flat'."""
    repo = base / "target"
    pkg_root = repo / "src" if layout == "src" else repo
    pkg = pkg_root / "demo_widget"
    pkg.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "README.md").write_text(README, encoding="utf-8")
    (repo / "press_config.toml").write_text(
        '# press config for demo_widget\ntheme = "dark"\n', encoding="utf-8"
    )
    (pkg / "__init__.py").write_text(
        '"""demo_widget package."""\n', encoding="utf-8"
    )
    (pkg / "cli.py").write_text(CLI_PY, encoding="utf-8")
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/demolabs/demo-widget.git",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init fixture")
    return repo


@pytest.fixture
def src_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="src")


@pytest.fixture
def flat_target(tmp_path: Path) -> Path:
    return make_target(tmp_path, layout="flat")
```

- [ ] **Step 2: Write the fixture smoke test**

Create `tests/rebrand/test_fixtures.py`:

```python
from pathlib import Path


def test_src_target_shape(src_target: Path):
    assert (src_target / ".git").is_dir()
    assert (src_target / "src" / "demo_widget" / "cli.py").is_file()
    assert "Compress" in (src_target / "README.md").read_text(encoding="utf-8")


def test_flat_target_shape(flat_target: Path):
    assert (flat_target / "demo_widget" / "cli.py").is_file()
    assert not (flat_target / "src").exists()
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_fixtures.py -q`
Expected: all PASS (factory has no untested dependencies)

- [ ] **Step 4: Commit**

```bash
git add tests/rebrand/conftest.py tests/rebrand/test_fixtures.py
git commit -m "test(rebrand): fixture target factory with boundary-trap content"
```

---

### Task 5: engine.py — file enumeration + plan (M1)

**Files:**
- Create: `src/template_press/rebrand/engine.py`
- Test: `tests/rebrand/test_engine_plan.py`

**Interfaces:**
- Produces: `PlanItem` (dataclass: `kind: str, path: str, detail: str`), `Plan` (dataclass: `items: list[PlanItem]`, methods `render() -> str`, `counts() -> dict[str, int]`), `iter_target_files(target: Path, rules: Rules) -> list[Path]`, `replacement_pairs(source: Identity, dest: Identity) -> list[tuple[str, str, str]]` ((field, current, replacement), longest-current-first), `build_plan(target: Path, source: Identity, dest: Identity, rules: Rules) -> Plan`.
- Consumes: `Identity`, `token_occurs` (Task 2); `Rules` (Task 3); fixtures (Task 4).

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_engine_plan.py`:

```python
from pathlib import Path

from template_press.rebrand.engine import (
    build_plan,
    iter_target_files,
    replacement_pairs,
)
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_iter_target_files_respects_gitignore_and_excludes(src_target: Path):
    (src_target / ".venv").mkdir()
    (src_target / ".venv" / "junk.py").write_text("x", encoding="utf-8")
    files = iter_target_files(src_target, DEFAULT_RULES)
    rels = {f.relative_to(src_target).as_posix() for f in files}
    assert "README.md" in rels and "src/demo_widget/cli.py" in rels
    assert not any(r.startswith(".venv") for r in rels)
    assert not any(r.startswith(".git/") for r in rels)


def test_replacement_pairs_longest_first():
    pairs = replacement_pairs(SOURCE, DEST)
    currents = [cur for _, cur, _ in pairs]
    assert currents == sorted(currents, key=len, reverse=True)
    assert ("app_name", "press", "potato") in pairs


def test_build_plan_lists_files_with_occurrences(src_target: Path):
    plan = build_plan(src_target, SOURCE, DEST, DEFAULT_RULES)
    replace_paths = {i.path for i in plan.items if i.kind == "replace"}
    assert "README.md" in replace_paths
    assert "pyproject.toml" in replace_paths
    rename_paths = {i.path for i in plan.items if i.kind == "rename"}
    assert "src/demo_widget" in rename_paths
    assert "press_config.toml" in rename_paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_plan.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.engine`

- [ ] **Step 3: Implement enumeration + plan in engine.py**

Create `src/template_press/rebrand/engine.py` (`iter_target_files` ported from `git show feat/init-rebrand-robustness:init/common.py` `iter_repo_files`, re-rooted at the target; plan/report shapes ported from `init/_engine.py`):

```python
"""Rebrand engine: enumerate, plan, and apply identity rewrites on a target.

Scan-based (ARCH-03): no per-target file lists. Every tracked text file is a
replace candidate; every path component containing an identity token is a
rename candidate. Failure mode: any op raising propagates — git in the
TARGET is the undo button (`git checkout . && git clean -fd`).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from template_press.rebrand.identity import Identity, replace_token, token_occurs
from template_press.rebrand.rules import Rules

RENAME_FIELDS: tuple[str, ...] = ("package_name", "repo_name", "app_name")


@dataclass
class PlanItem:
    kind: str  # "replace" | "rename"
    path: str
    detail: str

    def render(self) -> str:
        return f"  [{self.kind:<7}] {self.path}  —  {self.detail}"


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)

    def render(self) -> str:
        if not self.items:
            return "(plan is empty — nothing to do)"
        return "\n".join(["Plan:", *(i.render() for i in self.items)])

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"replace": 0, "rename": 0}
        for i in self.items:
            out[i.kind] = out.get(i.kind, 0) + 1
        return out


def _is_excluded(rel: Path, rules: Rules) -> bool:
    if rel.as_posix() in rules.exclude_files:
        return True
    return any(part in rules.exclude_dirs for part in rel.parts)


def iter_target_files(target: Path, rules: Rules) -> list[Path]:
    """All non-excluded tracked+untracked files under target, sorted.

    Uses `git ls-files --cached --others --exclude-standard` so the scan
    respects the target's .gitignore.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    out: list[Path] = []
    for line in result.stdout.splitlines():
        rel = Path(line)
        if _is_excluded(rel, rules):
            continue
        path = target / rel
        if path.is_file():
            out.append(path)
    return sorted(out)


def replacement_pairs(
    source: Identity, dest: Identity
) -> list[tuple[str, str, str]]:
    """(field, current, replacement) triples, longest current first."""
    src, dst = source.as_dict(), dest.as_dict()
    pairs = [(k, src[k], dst[k]) for k in src if src[k] != dst[k]]
    pairs.sort(key=lambda t: -len(t[1]))
    return pairs


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary or unreadable — never a rewrite candidate


def _renamed_rel(rel: Path, pairs: list[tuple[str, str, str]]) -> Path:
    parts = []
    for component in rel.parts:
        new = component
        for f, cur, repl in pairs:
            if f in RENAME_FIELDS:
                new = replace_token(new, f, cur, repl)
        parts.append(new)
    return Path(*parts)


def build_plan(
    target: Path, source: Identity, dest: Identity, rules: Rules
) -> Plan:
    """Resolve what apply() would do; executes nothing."""
    source.validate()
    dest.validate()
    plan = Plan()
    pairs = replacement_pairs(source, dest)
    rename_map: dict[str, str] = {}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        text = _read_text(path)
        if text is not None:
            hit_fields = [f for f, cur, _ in pairs if token_occurs(text, f, cur)]
            if hit_fields:
                plan.items.append(
                    PlanItem("replace", rel.as_posix(), f"fields={hit_fields}")
                )
        new_rel = _renamed_rel(rel, pairs)
        if new_rel != rel:
            # collapse to the shallowest differing ancestor (dir rename)
            for i, (old_part, new_part) in enumerate(
                zip(rel.parts, new_rel.parts, strict=True)
            ):
                if old_part != new_part:
                    old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                    new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                    rename_map.setdefault(old_prefix, new_prefix)
    for old, new in sorted(rename_map.items()):
        plan.items.append(PlanItem("rename", old, f"→ {new}"))
    return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_engine_plan.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_plan.py
git commit -m "feat(rebrand): target file enumeration and rebrand plan"
```

---

### Task 6: engine.py — apply: replace pass (M1)

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (append)
- Test: `tests/rebrand/test_engine_replace.py`

**Interfaces:**
- Produces: `ApplyReport` (dataclass: `replaced: list[str]`, `renamed: list[tuple[str, str]]`, `skipped: list[str]`, `regenerated: list[str]`, method `render() -> str`), `apply(target: Path, source: Identity, dest: Identity, rules: Rules) -> ApplyReport`.
- Consumes: everything from Task 5.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_engine_replace.py`:

```python
from pathlib import Path

from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_apply_rewrites_identity_everywhere(src_target: Path):
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert "README.md" in report.replaced
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "potato-launcher" in readme and "demo-widget" not in readme
    assert "potatolabs/potato-launcher" in readme
    assert "Potato Farmer <potato@example.com>" in readme
    pyproject = (src_target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "potato_launcher"' in pyproject
    assert 'potato = "potato_launcher.cli:main"' in pyproject


def test_apply_preserves_english_press_words(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "Compress" in readme and "express" in readme and "pressure" in readme
    assert "`potato --help`" in readme


def test_apply_rewrites_env_prefixes(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    cli = (src_target / "src" / "potato_launcher" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "POTATO_LOG_LEVEL" in cli and "_POTATO_COMPLETE" in cli
    assert "PRESS_" not in cli


def test_apply_skips_excluded_files(src_target: Path):
    (src_target / "CHANGELOG.md").write_text(
        "history of demo_widget\n", encoding="utf-8"
    )
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    text = (src_target / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "demo_widget" in text  # excluded by default rules
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_replace.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply'`

- [ ] **Step 3: Implement ApplyReport + apply (replace pass; rename pass lands in Task 7)**

Append to `src/template_press/rebrand/engine.py`:

```python
@dataclass
class ApplyReport:
    replaced: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    regenerated: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (
            f"Applied: {len(self.replaced)} replaced, "
            f"{len(self.renamed)} renamed, "
            f"{len(self.regenerated)} regenerated, "
            f"{len(self.skipped)} skipped."
        )


def _apply_replacements(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target).as_posix()
        text = _read_text(path)
        if text is None:
            report.skipped.append(f"replace {rel} (binary)")
            continue
        new_text = text
        for f, cur, repl in pairs:
            new_text = replace_token(new_text, f, cur, repl)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            report.replaced.append(rel)


def apply(
    target: Path, source: Identity, dest: Identity, rules: Rules
) -> ApplyReport:
    """Execute the rebrand: replace pass, then rename pass."""
    source.validate()
    dest.validate()
    report = ApplyReport()
    pairs = replacement_pairs(source, dest)
    _apply_replacements(target, pairs, rules, report)
    _apply_renames(target, pairs, rules, report)
    return report
```

And add a stub so this task is runnable before Task 7 (Task 7 replaces it):

```python
def _apply_renames(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    raise NotImplementedError  # implemented in the rename-pass task
```

For THIS task's tests to pass, `test_apply_rewrites_env_prefixes` reads a renamed path — so implement Task 7's `_apply_renames` immediately after seeing these tests fail for the right reason, or run only the non-rename tests: `uv run pytest tests/rebrand/test_engine_replace.py -q -k "not env_prefixes"`. Preferred: proceed straight to Task 7 and run both test files together at its Step 4.

- [ ] **Step 4: Run the non-rename tests**

Run: `uv run pytest tests/rebrand/test_engine_replace.py -q -k "not env_prefixes"`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_replace.py
git commit -m "feat(rebrand): boundary-safe replace pass"
```

---

### Task 7: engine.py — apply: rename pass (M1)

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (replace the `_apply_renames` stub)
- Test: `tests/rebrand/test_engine_rename.py`

**Interfaces:**
- Produces: working `_apply_renames` (private); `apply` now complete.
- Consumes: `_renamed_rel`, `RENAME_FIELDS` from Task 5.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_engine_rename.py`:

```python
from pathlib import Path

from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_package_dir_renamed_src_layout(src_target: Path):
    report = apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "src" / "potato_launcher" / "cli.py").is_file()
    assert not (src_target / "src" / "demo_widget").exists()
    assert ("src/demo_widget", "src/potato_launcher") in report.renamed


def test_package_dir_renamed_flat_layout(flat_target: Path):
    apply(flat_target, SOURCE, DEST, DEFAULT_RULES)
    assert (flat_target / "potato_launcher" / "cli.py").is_file()
    assert not (flat_target / "demo_widget").exists()


def test_app_token_filename_renamed(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert (src_target / "potato_config.toml").is_file()
    assert not (src_target / "press_config.toml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_rename.py -q`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement the rename pass**

Replace the `_apply_renames` stub in `src/template_press/rebrand/engine.py` with:

```python
def _apply_renames(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
) -> None:
    """Rename tracked paths whose components carry identity tokens.

    Collapses each differing path to its shallowest renamed ancestor so a
    package dir moves once (src/demo_widget → src/potato_launcher) instead
    of file-by-file, then renames deepest-first to keep parents valid.
    """
    rename_map: dict[str, str] = {}
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        new_rel = _renamed_rel(rel, pairs)
        if new_rel == rel:
            continue
        for i, (old_part, new_part) in enumerate(
            zip(rel.parts, new_rel.parts, strict=True)
        ):
            if old_part != new_part:
                old_prefix = Path(*rel.parts[: i + 1]).as_posix()
                new_prefix = Path(*new_rel.parts[: i + 1]).as_posix()
                rename_map.setdefault(old_prefix, new_prefix)
    for old in sorted(rename_map, key=lambda p: -len(Path(p).parts)):
        src, dst = target / old, target / rename_map[old]
        if not src.exists():
            report.skipped.append(f"rename {old} (missing)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        report.renamed.append((old, rename_map[old]))
```

- [ ] **Step 4: Run the full engine suite**

Run: `uv run pytest tests/rebrand/ -q`
Expected: all PASS (including Task 6's deferred `test_apply_rewrites_env_prefixes`)

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_rename.py
git commit -m "feat(rebrand): identity-token rename pass"
```

### Task 8: doctor.py — the verify-then-mark gate (M1)

**Files:**
- Create: `src/template_press/rebrand/doctor.py`
- Test: `tests/rebrand/test_doctor.py`

**Interfaces:**
- Produces: `Leak` (frozen dataclass: `path: str, field: str, value: str, where: str` — `where` is `"content"` or `"path"`), `find_leaks(target: Path, source: Identity, rules: Rules) -> list[Leak]`, `render_leak_report(leaks: list[Leak], limit: int = 20) -> str`.
- Consumes: `Identity`, `token_occurs` (Task 2); `Rules` (Task 3); `iter_target_files`, `_renamed_rel` helpers via own scan (Task 5). Port reference: `git show feat/init-rebrand-robustness:init/init_doctor.py` `check_no_identity_leftover` (lines 99–139), generalized to take target + identity + rules and to also check path names.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_doctor.py`:

```python
from pathlib import Path

from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import apply
from template_press.rebrand.rules import DEFAULT_RULES

from .conftest import DEST, SOURCE


def test_clean_rebrand_has_no_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_content_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "notes.md").write_text(
        "demo_widget survived here\n", encoding="utf-8"
    )
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(
        e.path == "notes.md" and e.field == "package_name" and e.where == "content"
        for e in leaks
    )


def test_path_leak_detected(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    (src_target / "demo_widget_old.txt").write_text("x", encoding="utf-8")
    leaks = find_leaks(src_target, SOURCE, DEFAULT_RULES)
    assert any(e.where == "path" for e in leaks)


def test_english_press_words_are_not_leaks(src_target: Path):
    apply(src_target, SOURCE, DEST, DEFAULT_RULES)
    # README still contains Compress/express/pressure — must NOT count
    assert find_leaks(src_target, SOURCE, DEFAULT_RULES) == []


def test_render_leak_report_is_actionable():
    from template_press.rebrand.doctor import Leak

    text = render_leak_report(
        [Leak(path="a.md", field="app_name", value="press", where="content")]
    )
    assert "a.md" in text and "press" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_doctor.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.doctor`

- [ ] **Step 3: Implement doctor.py**

```python
"""No-leak verification: the gate between apply() and the receipt (EMP-01).

A rebrand that leaves ANY source-identity token behind — in file content or
in a path name — is a failed rebrand. The CLI must exit non-zero and write
no receipt. Port of init_doctor.check_no_identity_leftover, generalized to
(target, identity, rules) and extended with path-name checking.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.engine import _read_text, iter_target_files
from template_press.rebrand.identity import Identity, token_occurs
from template_press.rebrand.rules import Rules

PATH_FIELDS: tuple[str, ...] = ("package_name", "repo_name", "app_name")


@dataclass(frozen=True)
class Leak:
    path: str
    field: str
    value: str
    where: str  # "content" | "path"


def find_leaks(target: Path, source: Identity, rules: Rules) -> list[Leak]:
    leaks: list[Leak] = []
    fields = source.as_dict()
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target)
        rel_posix = rel.as_posix()
        text = _read_text(path)
        if text is not None:
            for field_name, value in fields.items():
                if token_occurs(text, field_name, value):
                    leaks.append(Leak(rel_posix, field_name, value, "content"))
        for component in rel.parts:
            for field_name in PATH_FIELDS:
                if token_occurs(component, field_name, fields[field_name]):
                    leaks.append(
                        Leak(rel_posix, field_name, fields[field_name], "path")
                    )
    return leaks


def render_leak_report(leaks: list[Leak], limit: int = 20) -> str:
    lines = [
        f"error: {len(leaks)} source-identity leftover(s) — rebrand is "
        f"INCOMPLETE; no receipt written."
    ]
    for leak in leaks[:limit]:
        lines.append(
            f"  [{leak.where}] {leak.path}: {leak.field}={leak.value!r}"
        )
    if len(leaks) > limit:
        lines.append(f"  … and {len(leaks) - limit} more")
    lines.append(
        "hint: fix the leftovers (or exclude generated files via "
        ".press/rules.toml) and re-run with --force."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_doctor.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/doctor.py tests/rebrand/test_doctor.py
git commit -m "feat(rebrand): no-leak doctor gate for verify-then-mark"
```

---

### Task 9: discovery.py — discover + validate (M2)

**Files:**
- Create: `src/template_press/rebrand/discovery.py`
- Test: `tests/rebrand/test_discovery.py`

**Interfaces:**
- Produces: `Discovered` (frozen dataclass: `package_name: str | None, app_name: str | None, owner: str | None, repo_name: str | None, author: str | None, email: str | None, layout: str | None`), `discover(target: Path) -> Discovered`, `mismatches(source: Identity, found: Discovered) -> list[str]` (empty list = validated; non-None discovered fields must equal source).
- Consumes: `Identity` (Task 2); fixtures (Task 4). Origin regex ported from `git show feat/init-rebrand-robustness:init/common.py` lines 82–94.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_discovery.py`:

```python
import subprocess
from pathlib import Path

from template_press.rebrand.discovery import discover, mismatches

from .conftest import SOURCE


def test_discover_src_layout(src_target: Path):
    found = discover(src_target)
    assert found.package_name == "demo_widget"
    assert found.app_name == "press"
    assert found.owner == "demolabs"
    assert found.repo_name == "demo-widget"
    assert found.author == "Demo Author"
    assert found.email == "demo@example.com"
    assert found.layout == "src"


def test_discover_flat_layout(flat_target: Path):
    assert discover(flat_target).layout == "flat"


def test_discover_tolerates_missing_origin(src_target: Path):
    subprocess.run(
        ["git", "-C", str(src_target), "remote", "remove", "origin"],
        check=True,
        capture_output=True,
    )
    found = discover(src_target)
    assert found.owner is None and found.repo_name is None
    assert found.package_name == "demo_widget"  # rest still discovered


def test_mismatches_empty_when_source_matches(src_target: Path):
    assert mismatches(SOURCE, discover(src_target)) == []


def test_mismatches_reported_loudly(src_target: Path):
    wrong = SOURCE.__class__(**{**SOURCE.as_dict_prompted(), "package_name": "other_pkg"})
    msgs = mismatches(wrong, discover(src_target))
    assert any("package_name" in m and "other_pkg" in m for m in msgs)
```

Also add to `src/template_press/rebrand/identity.py` (tiny helper the test above and config task use — the prompted six fields, no derived `app_name_upper`):

```python
    def as_dict_prompted(self) -> dict[str, str]:
        d = self.as_dict()
        d.pop("app_name_upper")
        return d
```

(method on `Identity`, after `as_dict`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_discovery.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.discovery`

- [ ] **Step 3: Implement discovery.py**

```python
"""Discover a target repo's identity — the VALIDATOR, never the authority.

Per OQ3 (decision log 2026-06-15): the committed source-config is the
authoritative FROM identity; discovery cross-checks it against the target
(pyproject [project].name / authors, the [project.scripts] key, git origin,
src-vs-flat layout) and the CLI fails loudly on any mismatch. This replaces
the silent half-rebrand failure mode (EMPIRICAL R2) with a hard stop.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from template_press.rebrand.identity import Identity

_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class Discovered:
    package_name: str | None
    app_name: str | None
    owner: str | None
    repo_name: str | None
    author: str | None
    email: str | None
    layout: str | None  # "src" | "flat" | None


def _origin(target: Path) -> tuple[str | None, str | None]:
    result = subprocess.run(
        ["git", "-C", str(target), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, None
    m = _ORIGIN_RE.match(result.stdout.strip())
    return (m["owner"], m["repo"]) if m else (None, None)


def discover(target: Path) -> Discovered:
    package_name = app_name = author = email = None
    pyproject_path = target / "pyproject.toml"
    if pyproject_path.is_file():
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        raw_name = project.get("name")
        if isinstance(raw_name, str):
            package_name = raw_name.replace("-", "_")
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            app_name = next(iter(scripts))
        authors = project.get("authors", [])
        if authors and isinstance(authors[0], dict):
            author = authors[0].get("name")
            email = authors[0].get("email")
    owner, repo_name = _origin(target)
    layout: str | None = None
    if package_name is not None:
        if (target / "src" / package_name).is_dir():
            layout = "src"
        elif (target / package_name).is_dir():
            layout = "flat"
    return Discovered(
        package_name=package_name,
        app_name=app_name,
        owner=owner,
        repo_name=repo_name,
        author=author,
        email=email,
        layout=layout,
    )


def mismatches(source: Identity, found: Discovered) -> list[str]:
    """Non-empty means the source-config does NOT describe this target."""
    out: list[str] = []
    checks: tuple[tuple[str, str | None], ...] = (
        ("package_name", found.package_name),
        ("app_name", found.app_name),
        ("owner", found.owner),
        ("repo_name", found.repo_name),
        ("author", found.author),
        ("email", found.email),
    )
    declared = source.as_dict()
    for field_name, discovered_value in checks:
        if discovered_value is None:
            continue  # undiscoverable field — config stands unchallenged
        if discovered_value != declared[field_name]:
            out.append(
                f"{field_name}: source-config says "
                f"{declared[field_name]!r} but target shows "
                f"{discovered_value!r}"
            )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_discovery.py tests/rebrand/test_identity.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/discovery.py src/template_press/rebrand/identity.py tests/rebrand/test_discovery.py
git commit -m "feat(rebrand): identity discovery as config validator"
```

---

### Task 10: config.py — source-config + answers (M2)

**Files:**
- Create: `src/template_press/rebrand/config.py`
- Test: `tests/rebrand/test_config.py`

**Interfaces:**
- Produces: `SOURCE_CONFIG_REL = Path(".press/source.toml")`, `load_identity_toml(path: Path, table: str) -> Identity`, `load_source_config(target: Path, override: Path | None) -> Identity | None` (None when no file exists), `render_source_config(identity: Identity) -> str`, `load_answers(path: Path) -> Identity` (reads `[answers]` — compatible with the existing root `answers.toml` format).
- Consumes: `Identity`, `ValidationError`, `as_dict_prompted` (Tasks 2/9).

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_config.py`:

```python
from pathlib import Path

import pytest

from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.identity import ValidationError

from .conftest import DEST, SOURCE


def test_source_config_round_trip(tmp_path: Path):
    (tmp_path / ".press").mkdir()
    (tmp_path / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    assert load_source_config(tmp_path, override=None) == SOURCE


def test_load_source_config_absent_returns_none(tmp_path: Path):
    assert load_source_config(tmp_path, override=None) is None


def test_load_source_config_override_path(tmp_path: Path):
    p = tmp_path / "elsewhere.toml"
    p.write_text(render_source_config(SOURCE), encoding="utf-8")
    assert load_source_config(tmp_path, override=p) == SOURCE


def test_load_answers_answers_table(tmp_path: Path):
    p = tmp_path / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(
            f'{k} = "{v}"' for k, v in DEST.as_dict_prompted().items()
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_answers(p) == DEST


def test_missing_field_raises_validation_error(tmp_path: Path):
    p = tmp_path / "answers.toml"
    p.write_text('[answers]\npackage_name = "x_only"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_answers(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.config`

- [ ] **Step 3: Implement config.py**

```python
"""Load/render the two per-run identity configs (OQ3 two-file model).

source-config (FROM, committed in the target at .press/source.toml) — the
authoritative identity being replaced. answers (TO) — the identity being
pressed in, from an [answers] TOML (same shape as the repo's answers.toml).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from template_press.rebrand.identity import Identity, ValidationError

SOURCE_CONFIG_REL = Path(".press") / "source.toml"


def load_identity_toml(path: Path, table: str) -> Identity:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    section = data.get(table)
    if not isinstance(section, dict):
        raise ValidationError(f"{path}: missing [{table}] table")
    identity = Identity.from_mapping(
        {k: v for k, v in section.items() if isinstance(v, str)}
    )
    identity.validate()
    return identity


def load_source_config(target: Path, override: Path | None) -> Identity | None:
    path = override if override is not None else target / SOURCE_CONFIG_REL
    if not path.is_file():
        return None
    return load_identity_toml(path, "identity")


def render_source_config(identity: Identity) -> str:
    lines = [
        "# .press/source.toml — this repo's CURRENT identity (the FROM side",
        "# of a rebrand). Authoritative: press validates it against the repo",
        "# and refuses to run on mismatch. Commit this file.",
        "[identity]",
    ]
    lines += [f'{k} = "{v}"' for k, v in identity.as_dict_prompted().items()]
    return "\n".join(lines) + "\n"


def load_answers(path: Path) -> Identity:
    return load_identity_toml(path, "answers")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_config.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/config.py tests/rebrand/test_config.py
git commit -m "feat(rebrand): source-config and answers loading"
```

---

### Task 11: receipt.py (M2)

**Files:**
- Create: `src/template_press/rebrand/receipt.py`
- Test: `tests/rebrand/test_receipt.py`

**Interfaces:**
- Produces: `RECEIPT_REL = Path(".press/receipt.toml")`, `read_receipt(target: Path) -> str | None`, `write_receipt(target: Path, source: Identity, dest: Identity, report: ApplyReport) -> Path`.
- Consumes: `Identity` (Task 2), `ApplyReport` (Task 6).

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_receipt.py`:

```python
import tomllib
from pathlib import Path

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.receipt import RECEIPT_REL, read_receipt, write_receipt

from .conftest import DEST, SOURCE


def test_write_and_read_receipt(tmp_path: Path):
    report = ApplyReport(replaced=["README.md"], renamed=[("a", "b")])
    path = write_receipt(tmp_path, SOURCE, DEST, report)
    assert path == tmp_path / RECEIPT_REL
    raw = read_receipt(tmp_path)
    assert raw is not None
    data = tomllib.loads(raw)
    assert data["press"]["verified"] is True
    assert data["press"]["from"]["package_name"] == "demo_widget"
    assert data["press"]["to"]["package_name"] == "potato_launcher"
    assert data["press"]["counts"]["replaced"] == 1


def test_read_receipt_absent(tmp_path: Path):
    assert read_receipt(tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_receipt.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.receipt`

- [ ] **Step 3: Implement receipt.py**

```python
"""The rebrand receipt — written into the TARGET, only after verification.

The receipt is the anti-EMP-01 artifact: it exists only when the no-leak
doctor pass succeeded, and it records what was verified, not what was
answered. Its presence also guards re-runs (require --force).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import Identity

RECEIPT_REL = Path(".press") / "receipt.toml"


def read_receipt(target: Path) -> str | None:
    path = target / RECEIPT_REL
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _identity_table(name: str, identity: Identity) -> list[str]:
    lines = [f"[press.{name}]"]
    lines += [f'{k} = "{v}"' for k, v in identity.as_dict_prompted().items()]
    return lines


def write_receipt(
    target: Path, source: Identity, dest: Identity, report: ApplyReport
) -> Path:
    path = target / RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# .press/receipt.toml — written by template-press AFTER the no-leak",
        "# verification pass. Presence means: this rebrand completed and was",
        "# verified. Delete it (or use --force) to press again.",
        "[press]",
        "verified = true",
        f'completed_at = "{stamp}"',
        "",
        *_identity_table("from", source),
        "",
        *_identity_table("to", dest),
        "",
        "[press.counts]",
        f"replaced = {len(report.replaced)}",
        f"renamed = {len(report.renamed)}",
        f"regenerated = {len(report.regenerated)}",
        f"skipped = {len(report.skipped)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_receipt.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/receipt.py tests/rebrand/test_receipt.py
git commit -m "feat(rebrand): verified receipt written into the target"
```

---

### Task 12: cli.py — preconditions, plumbing, dry-run, R2 regression (M2)

**Files:**
- Create: `src/template_press/rebrand/cli.py`
- Test: `tests/rebrand/test_cli.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`; module runnable as `python -m template_press.rebrand.cli`. Flags: `--target PATH` (required), `--config PATH` (answers; required unless `--dry-run` with discovery), `--source-config PATH`, `--accept-discovery`, `--dry-run`, `--force`, `--allow-dirty`.
- Consumes: everything from Tasks 2–11.
- Exit codes: `0` ok · `1` leaks (Task 13) · `2` precondition/config/validation.

- [ ] **Step 1: Write the failing tests**

Create `tests/rebrand/test_cli.py`:

```python
import subprocess
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, SOURCE


def write_source_config(target: Path) -> None:
    (target / ".press").mkdir(exist_ok=True)
    (target / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(target), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(target), "commit", "-q", "-m", "add source config"],
        check=True,
        capture_output=True,
    )


def write_answers(base: Path) -> Path:
    p = base / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(f'{k} = "{v}"' for k, v in DEST.as_dict_prompted().items())
        + "\n",
        encoding="utf-8",
    )
    return p


def test_missing_target_dir_exits_2(tmp_path: Path):
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(tmp_path / "nope"), "--config", str(answers)]
    )
    assert code == 2


def test_dirty_target_exits_2(src_target: Path, tmp_path: Path):
    write_source_config(src_target)
    (src_target / "dirty.txt").write_text("x", encoding="utf-8")
    answers = write_answers(tmp_path)
    assert main(["--target", str(src_target), "--config", str(answers)]) == 2


def test_missing_source_config_prints_proposal_and_exits_2(
    src_target: Path, tmp_path: Path, capsys
):
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2
    out = capsys.readouterr().out
    assert "[identity]" in out and 'package_name = "demo_widget"' in out
    assert "--accept-discovery" in out


def test_mismatched_source_config_fails_loudly_no_writes(
    src_target: Path, tmp_path: Path, capsys
):
    """The R2 regression: wrong identity must be a hard stop, not a half-run."""
    wrong = SOURCE.__class__(
        **{**SOURCE.as_dict_prompted(), "package_name": "other_pkg"}
    )
    (src_target / ".press").mkdir()
    (src_target / SOURCE_CONFIG_REL).write_text(
        render_source_config(wrong), encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(src_target), "add", "-A"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(src_target), "commit", "-q", "-m", "cfg"],
        check=True,
        capture_output=True,
    )
    before = (src_target / "README.md").read_text(encoding="utf-8")
    answers = write_answers(tmp_path)
    code = main(["--target", str(src_target), "--config", str(answers)])
    assert code == 2
    assert "package_name" in capsys.readouterr().out
    assert (src_target / "README.md").read_text(encoding="utf-8") == before
    assert not (src_target / RECEIPT_REL).exists()


def test_dry_run_prints_plan_and_writes_nothing(
    src_target: Path, tmp_path: Path, capsys
):
    write_source_config(src_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--dry-run"]
    )
    assert code == 0
    assert "README.md" in capsys.readouterr().out
    assert "demo-widget" in (src_target / "README.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError` for `template_press.rebrand.cli`

- [ ] **Step 3: Implement cli.py (pipeline through dry-run; apply/verify wired in Task 13)**

```python
"""press rebrand — point the press at a target repo (ARCH-01).

Pipeline: preconditions → source identity (config-first, discovery
validates) → answers → plan → [--dry-run stops here] → apply → regenerate
lockfiles → VERIFY (no-leak doctor) → receipt. Exit codes: 0 ok, 1 leaks
found after apply (no receipt), 2 precondition/config error (no writes).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.discovery import discover, mismatches
from template_press.rebrand.doctor import find_leaks, render_leak_report
from template_press.rebrand.engine import apply, build_plan
from template_press.rebrand.identity import Identity, ValidationError
from template_press.rebrand.receipt import read_receipt, write_receipt
from template_press.rebrand.rules import DEFAULT_RULES, Rules, load_rules


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def check_preconditions(target: Path, force: bool, allow_dirty: bool) -> str | None:
    """Return an error message, or None when the target is pressable."""
    if not target.is_dir():
        return f"target does not exist or is not a directory: {target}"
    if not (target / ".git").exists():
        return f"target is not a git repository: {target}"
    if read_receipt(target) is not None and not force:
        return (
            "target already has a press receipt (.press/receipt.toml); "
            "re-press with --force"
        )
    if not allow_dirty:
        status = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            return "target working tree is dirty; commit/stash or --allow-dirty"
    return None


def _resolve_source(
    target: Path, override: Path | None, accept_discovery: bool
) -> Identity | int:
    source = load_source_config(target, override)
    if source is None:
        found = discover(target)
        proposal = {
            "package_name": found.package_name,
            "repo_name": found.repo_name,
            "app_name": found.app_name,
            "author": found.author,
            "email": found.email,
            "owner": found.owner,
        }
        unresolved = [k for k, v in proposal.items() if v is None]
        if unresolved:
            return _fail(
                f"no source-config at {SOURCE_CONFIG_REL} and discovery "
                f"could not resolve: {', '.join(unresolved)}. Write the "
                f"source-config by hand."
            )
        candidate = Identity.from_mapping({k: v for k, v in proposal.items() if v})
        if not accept_discovery:
            print(
                f"no source-config found at {SOURCE_CONFIG_REL}.\n"
                f"Discovery proposes:\n\n{render_source_config(candidate)}\n"
                f"Save it there (and commit), or re-run with "
                f"--accept-discovery to write + use it.",
            )
            return 2
        path = target / SOURCE_CONFIG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_source_config(candidate), encoding="utf-8")
        print(f"wrote {SOURCE_CONFIG_REL} from discovery")
        source = candidate
    problems = mismatches(source, discover(target))
    if problems:
        print(
            "error: source-config does not match the target "
            "(refusing to press — this is the silent-half-rebrand guard):",
        )
        for p in problems:
            print(f"  {p}")
        return 2
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="press rebrand", description=__doc__
    )
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="answers TOML (TO identity)")
    parser.add_argument("--source-config", type=Path, dest="source_config")
    parser.add_argument("--accept-discovery", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    target = args.target.resolve()
    problem = check_preconditions(target, args.force, args.allow_dirty)
    if problem is not None:
        return _fail(problem)

    source = _resolve_source(target, args.source_config, args.accept_discovery)
    if isinstance(source, int):
        return source

    if args.config is None:
        return _fail("--config ANSWERS.toml is required")
    try:
        dest = load_answers(args.config)
    except (ValidationError, OSError) as exc:
        return _fail(str(exc))

    rules = load_rules(target)
    plan = build_plan(target, source, dest, rules)
    print(plan.render())
    if args.dry_run:
        print("(dry run — nothing applied)")
        return 0
    return _press(target, source, dest, rules)


def _press(target: Path, source: Identity, dest: Identity, rules: Rules) -> int:
    raise NotImplementedError  # wired in the apply/verify/receipt task


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_cli.py -q`
Expected: all PASS (none of these tests reach `_press`)

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand
git add src/template_press/rebrand/cli.py tests/rebrand/test_cli.py
git commit -m "feat(rebrand): cli preconditions, config-first identity, dry-run"
```

---

### Task 13: cli.py — apply → verify → receipt (the EMP-01 gate) (M2)

**Files:**
- Modify: `src/template_press/rebrand/cli.py` (replace `_press` stub)
- Test: append to `tests/rebrand/test_cli.py`

**Interfaces:**
- Produces: complete `_press(target, source, dest, rules) -> int`; full pipeline live.
- Consumes: `apply` (Task 6/7), `find_leaks`/`render_leak_report` (Task 8), `write_receipt` (Task 11).

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_cli.py`:

```python
def test_happy_path_presses_verifies_and_writes_receipt(
    src_target: Path, tmp_path: Path
):
    write_source_config(src_target)
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 0
    assert (src_target / RECEIPT_REL).is_file()
    assert (src_target / "src" / "potato_launcher" / "cli.py").is_file()
    readme = (src_target / "README.md").read_text(encoding="utf-8")
    assert "demo" not in readme and "Compress" in readme


def test_leak_after_apply_exits_1_and_writes_no_receipt(
    src_target: Path, tmp_path: Path
):
    """EMP-01 regression: a partial rebrand must fail loudly, no receipt."""
    write_source_config(src_target)
    # Excluded from rewriting but NOT from the doctor scan → guaranteed leak.
    (src_target / ".press").mkdir(exist_ok=True)
    (src_target / ".press" / "rules.toml").write_text(
        '[rules]\nextra_exclude_files = ["notes.md"]\n', encoding="utf-8"
    )
    (src_target / "notes.md").write_text(
        "demo_widget must survive rewriting\n", encoding="utf-8"
    )
    answers = write_answers(tmp_path)
    code = main(
        ["--target", str(src_target), "--config", str(answers), "--allow-dirty"]
    )
    assert code == 1
    assert not (src_target / RECEIPT_REL).exists()
```

Design rule the test encodes: **excluding a file from rewriting never
excludes it from verification** (EMP-01). `_press` therefore builds
`doctor_rules` whose `exclude_files` is reset to
`DEFAULT_RULES.exclude_files` (lockfiles/changelog only), discarding any
target-side `extra_exclude_files`. In this test `notes.md` is excluded from
the rewrite by the target override but IS scanned by the doctor — so the
surviving `demo_widget` is a leak, exit 1, no receipt.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_cli.py -q`
Expected: the two new tests FAIL with `NotImplementedError`

- [ ] **Step 3: Implement _press**

Replace the `_press` stub in `src/template_press/rebrand/cli.py` with:

Also extend the engine import at the top of cli.py to
`from template_press.rebrand.engine import ApplyReport, apply, build_plan`.

```python
def _regenerate_lockfiles(
    target: Path, rules: Rules, report: ApplyReport
) -> None:
    for lockfile in rules.regenerate:
        if not (target / lockfile).is_file():
            continue
        if lockfile == "uv.lock":
            result = subprocess.run(
                ["uv", "lock"], cwd=target, capture_output=True, text=True
            )
            if result.returncode == 0:
                report.regenerated.append(lockfile)
            else:
                report.skipped.append(f"regenerate {lockfile} (uv lock failed)")
        else:
            report.skipped.append(f"regenerate {lockfile} (no regenerator)")


def _press(target: Path, source: Identity, dest: Identity, rules: Rules) -> int:
    report = apply(target, source, dest, rules)
    _regenerate_lockfiles(target, rules, report)
    # Verification never honors target-side rewrite exclusions: opting a file
    # out of rewriting must not opt it out of the leak scan (EMP-01).
    doctor_rules = Rules(
        exclude_dirs=rules.exclude_dirs,
        exclude_files=DEFAULT_RULES.exclude_files,
        regenerate=rules.regenerate,
    )
    leaks = find_leaks(target, source, doctor_rules)
    if leaks:
        print(render_leak_report(leaks), file=sys.stderr)
        print(report.render(), file=sys.stderr)
        return 1
    receipt_path = write_receipt(target, source, dest, report)
    print(report.render())
    print(f"verified: no identity leftovers. receipt: {receipt_path}")
    return 0
```

- [ ] **Step 4: Run the full rebrand suite**

Run: `uv run pytest tests/rebrand/ -q`
Expected: all PASS

- [ ] **Step 5: Run the repo gates and commit**

```bash
uv run ruff check src/template_press/rebrand tests/rebrand && uv run ruff format --check src/template_press/rebrand tests/rebrand
uv run --extra web ty check src/template_press/
git add src/template_press/rebrand/cli.py tests/rebrand/test_cli.py
git commit -m "feat(rebrand): apply-verify-receipt pipeline with leak gate"
```

---

### Task 14: The acceptance matrix — script, live tests, CI (M3)

**Files:**
- Create: `scripts/rebrand_matrix.sh`
- Create: `tests/rebrand/test_matrix.py` (`@pytest.mark.live`)
- Create: `.github/workflows/rebrand-matrix.yml`
- Modify: `Justfile` (add `matrix` recipe next to the existing test recipes)

**Interfaces:**
- Consumes: the complete CLI (Task 13). R-run semantics from EMPIRICAL_BUGS.md: R1 = press a real py-launch-blueprint clone cleanly; R2-class = mismatched identity fails loudly with no receipt; R3 = press a clone of this repo.

- [ ] **Step 1: Write the live test**

Create `tests/rebrand/test_matrix.py`:

```python
"""Live acceptance matrix (network + real clones). Excluded by default
addopts; run explicitly: uv run pytest tests/rebrand/test_matrix.py -m live
"""

import subprocess
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL

from .conftest import DEST, write_answers_file

BLUEPRINT = "https://github.com/smorinlabs/py-launch-blueprint.git"


def clone(url: str, dest: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--depth=1", "-q", url, str(dest)],
        check=True,
        capture_output=True,
    )
    return dest


@pytest.mark.live
def test_r1_press_blueprint_clone_clean(tmp_path: Path):
    target = clone(BLUEPRINT, tmp_path / "plb")
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(answers),
            "--accept-discovery",
            "--allow-dirty",
        ]
    )
    assert code in (0, 1)  # 1 = leaks found: loud, actionable — never silent
    if code == 0:
        assert (target / RECEIPT_REL).is_file()
        grep = subprocess.run(
            ["git", "-C", str(target), "grep", "-l", "py_launch_blueprint"],
            capture_output=True,
            text=True,
        )
        assert grep.stdout.strip() == ""
    else:
        assert not (target / RECEIPT_REL).exists()


@pytest.mark.live
def test_r2_mismatched_identity_fails_loudly(tmp_path: Path):
    target = clone(BLUEPRINT, tmp_path / "plb2")
    (target / ".press").mkdir()
    (target / SOURCE_CONFIG_REL).write_text(
        "[identity]\n"
        'package_name = "template_press"\n'
        'repo_name = "template-press"\n'
        'app_name = "press"\n'
        'author = "Steve Morin"\n'
        'email = "steve.morin@gmail.com"\n'
        'owner = "smorinlabs"\n',
        encoding="utf-8",
    )
    answers = write_answers_file(tmp_path, DEST)
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(answers),
            "--allow-dirty",
        ]
    )
    assert code == 2  # hard stop BEFORE any writes — the R2 scenario, inverted
    assert not (target / RECEIPT_REL).exists()
```

Add the shared helper to `tests/rebrand/conftest.py`:

```python
def write_answers_file(base: Path, identity: Identity) -> Path:
    p = base / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(
            f'{k} = "{v}"' for k, v in identity.as_dict_prompted().items()
        )
        + "\n",
        encoding="utf-8",
    )
    return p
```

(and refactor `tests/rebrand/test_cli.py::write_answers` to call it.)

- [ ] **Step 2: Write the matrix script**

Create `scripts/rebrand_matrix.sh` (mode `755`):

```bash
#!/usr/bin/env bash
# R1/R2/R3 acceptance matrix for the rebrand press (EMPIRICAL_BUGS.md,
# reborn as a repeatable harness). R3 presses a clone of THIS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== R1 + R2 (live tests against a real py-launch-blueprint clone) =="
uv run pytest tests/rebrand/test_matrix.py -m live -q

echo "== R3 (self-press: a clone of this repo) =="
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone -q . "$WORK/self"
cat > "$WORK/answers.toml" <<'EOF'
[answers]
package_name = "potato_launcher"
repo_name = "potato-launcher"
app_name = "potato"
author = "Potato Farmer"
email = "potato@example.com"
owner = "potatolabs"
EOF
uv run python -m template_press.rebrand.cli \
  --target "$WORK/self" --config "$WORK/answers.toml" \
  --accept-discovery --allow-dirty
echo "R3: exit $? — rebrand verified (receipt written)"
```

- [ ] **Step 3: Add the Justfile recipe and CI workflow**

Justfile (place next to the existing `test` recipe):

```make
# R1/R2/R3 rebrand acceptance matrix (live: clones py-launch-blueprint)
matrix:
    scripts/rebrand_matrix.sh
```

Create `.github/workflows/rebrand-matrix.yml`:

```yaml
name: rebrand-matrix
"on":
  workflow_dispatch: {}
  schedule:
    - cron: "0 6 * * 1"  # weekly Monday
  pull_request:
    paths:
      - "src/template_press/rebrand/**"
      - "tests/rebrand/**"
      - "scripts/rebrand_matrix.sh"
permissions:
  contents: read
jobs:
  matrix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --group dev --extra web
      - run: scripts/rebrand_matrix.sh
```

- [ ] **Step 4: Run the matrix locally**

Run: `just matrix`
Expected: R1 exit 0 or a loud leak report (triaged, never silent), R2 exit 2, R3 exit 0 with receipt. Fast suite still green: `uv run pytest tests/rebrand/ -q` (live tests auto-excluded by default addopts).

Note: R3 (self-press) exercising this repo will surface any real leftovers in
OUR tree (e.g. the stale "Py Launch Blueprint" CLAUDE.md heading is a
*py_launch_blueprint-identity* leftover, not a template_press one, so it does
not block R3 — it is M4 doc-rewrite scope). If R3 reports template_press
leaks in files that are legitimately identity-bearing forever (e.g.
`docs/design/0006`), add them to `.press/rules.toml` in the R3 clone step or
accept exit 1 with an explicit allowlist assertion — decide at execution
time with the evidence in hand, and record the choice in the commit message.

- [ ] **Step 5: Commit**

```bash
git add scripts/rebrand_matrix.sh tests/rebrand/test_matrix.py tests/rebrand/conftest.py tests/rebrand/test_cli.py Justfile .github/workflows/rebrand-matrix.yml
git commit -m "test(rebrand): r1/r2/r3 acceptance matrix as script, live tests, ci"
```

---

### Task 15: Skills + agent docs (M3)

**Files:**
- Create: `.claude/skills/press-target/SKILL.md`
- Create: `.claude/skills/rebrand-matrix/SKILL.md`
- Modify: `AGENTS.md` (Canonical commands table: add matrix + rebrand rows)

**Interfaces:**
- Consumes: the CLI (Task 13), the matrix (Task 14).

- [ ] **Step 1: Write the press-target skill**

Create `.claude/skills/press-target/SKILL.md`:

```markdown
---
name: press-target
description: Run template-press against a target repo — dry-run preview,
  identity validation, apply, verify, receipt. Use when the user says
  "press <repo>", "rebrand <repo> with template-press", "run the press on
  <path>", or "point template-press at <target>".
---

# press-target

Rebrand an external target repo with the press. The tool validates the
target's committed source-config against discovery and REFUSES to run on
mismatch; a completed run is verified leak-free before a receipt is written.

## Steps

1. Preconditions: target is a git repo with a clean tree.
2. Preview (never skip):
   `uv run python -m template_press.rebrand.cli --target <TARGET> --config <ANSWERS.toml> --dry-run`
3. If the target has no `.press/source.toml`, review the discovery proposal
   printed by the dry run; re-run with `--accept-discovery` only after the
   user confirms the identity is right.
4. Apply: same command without `--dry-run`.
5. Interpret exit codes: 0 = verified + receipt written; 1 = leaks found,
   NO receipt (show the leak report; fix or add `.press/rules.toml`
   excludes for generated files, then re-run with `--force`); 2 =
   precondition/mismatch (report, do not retry blindly).
6. Show the receipt: `<TARGET>/.press/receipt.toml`, and remind the user to
   review `git -C <TARGET> diff --stat` and commit in the target.

## Answers file shape

```toml
[answers]
package_name = "new_pkg"
repo_name = "new-repo"
app_name = "newcli"
author = "Jane Dev"
email = "jane@example.com"
owner = "janedev"
```
```

- [ ] **Step 2: Write the rebrand-matrix skill**

Create `.claude/skills/rebrand-matrix/SKILL.md`:

```markdown
---
name: rebrand-matrix
description: Run the R1/R2/R3 rebrand acceptance matrix to answer "did we
  break the press?". Use when the user asks to "run the matrix", "verify
  the press still works", "run the rebrand acceptance tests", or after any
  change to src/template_press/rebrand/.
---

# rebrand-matrix

The empirical harness from EMPIRICAL_BUGS.md as a repeatable check:

- **R1** — press a real py-launch-blueprint clone: must verify clean (or
  fail LOUDLY with a leak report; silence is the only unacceptable outcome).
- **R2** — mismatched source-config: must hard-stop (exit 2) before any
  writes, no receipt.
- **R3** — self-press a clone of this repo: must verify clean.

## Run

`just matrix` (live: clones py-launch-blueprint; needs network), or only the
pytest half: `uv run pytest tests/rebrand/test_matrix.py -m live -q`.

CI runs the same script weekly and on PRs touching the rebrand core
(.github/workflows/rebrand-matrix.yml).

## Interpreting failures

- R1 exit 1: the blueprint gained identity-bearing files the rules don't
  cover — read the leak report, extend rules/excludes deliberately.
- R2 exit ≠ 2: the mismatch guard regressed — this is the silent-corruption
  failure mode (EMP-01); fix before anything else ships.
- R3 exit ≠ 0: our own repo has un-pressable content — usually a new file
  that must be excluded or made identity-clean.
```

- [ ] **Step 3: Add AGENTS.md canonical-commands rows**

In the `## Canonical commands` table of `AGENTS.md`, add after the "Run tests" row:

```markdown
| Rebrand a target (preview) | `uv run python -m template_press.rebrand.cli --target <dir> --config <answers.toml> --dry-run` |
| Rebrand acceptance matrix | `just matrix` (live; see `.claude/skills/rebrand-matrix/`) |
```

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/rebrand/ -q && uv run ruff check .`
Expected: PASS / clean.

```bash
git add .claude/skills/press-target .claude/skills/rebrand-matrix AGENTS.md
git commit -m "docs(skills): press-target and rebrand-matrix runbooks"
```

---

## Self-review checklist (run after all tasks)

1. **Spec coverage**: ARCH-01 → Tasks 12–13 (`--target`); ARCH-03 → Tasks 9–10 (config-first + discovery-validation); EMP-01 → Tasks 8, 13 (verify-then-mark, leak ⇒ exit 1, no receipt); OQ12 → Task 2 (boundary-safe default); OQ4 → Task 3 (rules + overrides); OQ5 → Task 11 (state in target); M3 dogfood → Tasks 14–15. ARCH-02/EMP-02 are deliberately OUT (successor plan M4).
2. **Full pipeline green**: `uv run pytest tests/rebrand/ -q` then `just check` (existing suite + new suite together), then `just matrix`.
3. **No cross-task type drift**: `Identity.as_dict_prompted()` (Tasks 9/10/11/14), `ApplyReport.regenerated` (Tasks 6/13), `Rules` field names (Tasks 3/13 doctor_rules), exit-code contract (Tasks 12/13/14/15 skills).
4. **Legacy init gates — known-red, marker-gated, do NOT chase green.** On main (this branch's base) the drift check and `init/tests/` are red pre-existing (15 failures — the exact state BUGS.md documented as "expected mid-extraction"). They do not block work: the lefthook pre-push init checks are marker-gated (`test -f init/.blueprint-initialized || …`) and the marker exists, so they no-op; no CI workflow in this repo runs them (blueprint-guard / init-integration workflows are absent). Per BUGS.md B-3, do not reconcile `init/manifest.toml` to make them green — the whole `init/` system is deleted in successor plan M4. The gates that DO apply to this plan: `just check` (full pipeline) and the new `tests/rebrand/` suite.

