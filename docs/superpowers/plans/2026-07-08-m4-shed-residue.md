# M4 — Shed residue Implementation Plan

> **For agentic workers:** this is a mostly-subtractive milestone executed on
> branch `feat/m4-shed-residue` in logical commits, each verified green before
> the next. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn template-press from a repo that still *contains* the
py-launch-blueprint app into a pure, publishable rebrand utility: delete the
legacy application, `init/`, and web extras; repoint the `press` console
script at a noun-verb dispatcher (`press rebrand …`); replace the inherited
Sphinx site with a minimal but instantly-publishable skeleton; rewrite the
user-facing prose.

**Architecture:** After M4 the package is `src/template_press/` = `__init__.py`
+ `py.typed` + `rebrand/` only. Zero runtime dependencies (the rebrand engine
is pure stdlib). The console entry `press` dispatches verbs; `rebrand` is
wired, `provision`/`status` are reserved stubs exiting 2 with "available in
M6". Publishing machinery (Sphinx/RTD, release-please, publish.yml) is kept.

**Decisions (locked with the user, 2026-07-08):**
- **CLI shape:** noun-verb dispatcher — `press rebrand --target …`;
  `provision`/`status` reserved for M6.
- **Doc site:** keep Sphinx + ReadTheDocs machinery; replace blueprint content
  pages with a press skeleton that builds clean.
- **ADR/design/research folders:** KEEP as decision history (records aren't
  deleted). Only user-facing site content and code artifacts are removed.
- **Version:** stays `2.1.1` here; the reset to `0.1.0` is M5.
- Carried from the program map: gut-in-place (keep repo + settings/secrets);
  post_init stays parked on salvage (M6 rebuilds provision).

## Global Constraints

- Keep the tree green after every commit: `just check` must pass.
- Line length 88; strict typing on new code; absolute intra-package imports.
- Conventional Commits, lowercase subject (commitlint). `deps` is NOT a type —
  use `build(deps):`.
- Do NOT delete `tests/rebrand/**`, `tests/meta/test_version_consistency.py`,
  `docs/adr/**`, `docs/design/**`, `docs/research/**`, `docs/superpowers/**`,
  the salvage branch, or any release/publish machinery.
- The rebrand engine and its 99 tests must remain untouched and green.

## Delete inventory (exact)

**Code + tests**
- `src/template_press/core/`, `src/template_press/cli/`, `src/template_press/web/`
- `tests/core/`, `tests/cli/`, `tests/web/`, `tests/conftest.py`, `tests/__init__.py`
- `init/` (entire tree, incl. `init/tests/`)
- `scripts/export_openapi.py`

**Root residue**
- `Dockerfile`, `EXAMPLECLI.md`, `EXAMPLEWEB.md`, `llms.txt`
- `docs/api/` (generated OpenAPI web artifact)

**Config**
- pyproject `[project].dependencies` → `[]` (drop click/pydantic/requests)
- pyproject `[project.optional-dependencies]` → delete `web` and `otel`
- pyproject dev group → drop `httpx` (web TestClient transport)
- Justfile recipes: `serve`, `test-web`, `export-openapi`, `client-python`,
  `docker-web`; drop `--extra web` from `setup`, `check`/ty, docs sync
- lefthook `pre-push`: the four `init-*` hooks + their comment block
- `.github/workflows/api-contract.yml`; drop `--extra web` from `ci.yml` syncs
  and remove any web test/build job

**Keep-but-edit**
- `[project.scripts]` → `press`/`tpress` = `template_press.press_cli:main`
- README.md, CLAUDE.md heading, AGENTS.md, docs/source content — rewritten

---

## Task 1: Shed the legacy application (code, tests, config, workflow)

**Deletes/edits:** app packages + app tests + `scripts/export_openapi.py` +
`Dockerfile`/`EXAMPLECLI.md`/`EXAMPLEWEB.md`/`llms.txt` + `docs/api/` +
pyproject deps/extras + Justfile web recipes + `api-contract.yml` + ci.yml web
syncs.

- [ ] **Step 1: Delete the app + its tests + web artifacts**

```bash
git rm -r src/template_press/core src/template_press/cli src/template_press/web \
  tests/core tests/cli tests/web tests/conftest.py tests/__init__.py \
  scripts/export_openapi.py Dockerfile EXAMPLECLI.md EXAMPLEWEB.md llms.txt \
  docs/api .github/workflows/api-contract.yml
```

- [ ] **Step 2: pyproject — zero runtime deps, drop extras**

In `pyproject.toml`: set `[project] dependencies = []`; delete the entire
`[project.optional-dependencies]` block (`web` + `otel`); in
`[dependency-groups] dev` remove the `httpx` line. Leave `docs` group,
`[tool.*]`, markers, and version untouched.

- [ ] **Step 3: Justfile — drop web/openapi/docker recipes and `--extra web`**

Remove recipes `serve`, `test-web`, `export-openapi`, `client-python`,
`docker-web`. Change `uv sync --group dev --extra web` → `uv sync --group dev`
(setup, both occurrences). Change `uv run --extra web ty check …` →
`uv run ty check …`. In the docs recipe drop `--extra web`.

- [ ] **Step 4: ci.yml — drop `--extra web` and any web job**

Replace `uv sync --locked --group dev --extra web` → `uv sync --locked --group dev`
(both). Docs sync: `uv sync --locked --group docs` (drop `--extra web`).
Remove any step that runs `tests/web` or builds the web image.

- [ ] **Step 5: Resync + verify the app is gone and gates pass**

```bash
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run ty check src/template_press/
uv run pytest -q                 # rebrand + meta only; app tests gone
uv run --script - <<'PY'
import template_press.rebrand.cli  # rebrand imports clean
PY
```
Expected: ruff/ty clean; pytest ~82 passed (99 rebrand + version-consistency),
no import errors, no `template_press.core/cli/web` remaining.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: shed the legacy py-launch-blueprint application

Delete src/template_press/{core,cli,web} and their tests, the web extras
(fastapi/uvicorn/otel), Dockerfile, EXAMPLE docs, llms.txt, the OpenAPI
artifact + api-contract workflow, and export_openapi.py. The rebrand press
is pure stdlib, so [project] now has zero runtime dependencies."
```

---

## Task 2: Shed the `init/` self-rebrand machinery

**Deletes/edits:** `init/` tree + the four lefthook `init-*` pre-push hooks +
AGENTS.md init-integrity section.

- [ ] **Step 1: Delete init/ and its hooks**

```bash
git rm -r init
```
In `lefthook.yml` `pre-push.commands`, delete the four steps
`init-guard-wiring`, `init-manifest-drift`, `init-path-filter`, `init-tests`
and the leading "Init-system integrity …" comment block. Keep
`gitleaks-range` and `bandit`.

- [ ] **Step 2: AGENTS.md — remove the init-integrity verification step**

Delete the "3. Init-system integrity …" list item from the Verification flow
(and renumber), plus the "Blueprint-guard/init-integration" references and the
init-manifest drift rule paragraph.

- [ ] **Step 3: Verify hooks still load + gates pass**

```bash
uv run lefthook validate 2>/dev/null || lefthook validate
uv run pytest -q
```
Expected: lefthook config valid (no missing-file refs); tests green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove init/ self-rebrand machinery

The external-target press replaces the in-place init system (design 0006);
drop init/ and the four marker-gated init-* pre-push hooks. Audit docs and
port sources remain on the feat/init-rebrand-robustness salvage branch."
```

---

## Task 3: Repoint `press` to a noun-verb dispatcher

**Creates:** `src/template_press/press_cli.py` + `tests/rebrand/test_press_cli.py`.
**Edits:** `[project.scripts]`; the `prog=` in `rebrand/cli.py`.

**Interface (produces):** `press_cli.main(argv: list[str] | None = None) -> int`
— dispatches `argv[0]`: `rebrand` → `rebrand.cli.main(rest)`; `provision`/
`status` → print "available in M6", return 2; no/`-h`/unknown verb → usage
listing the three verbs (rebrand active; provision/status "(coming in M6)"),
return 0 for `-h`/none, 2 for unknown.

- [ ] **Step 1: Write the failing test**

`tests/rebrand/test_press_cli.py`:

```python
import pytest

from template_press.press_cli import main


def test_bare_invocation_lists_verbs(capsys):
    code = main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "rebrand" in out
    assert "provision" in out and "M6" in out


def test_unknown_verb_exits_2(capsys):
    assert main(["frobnicate"]) == 2
    assert "unknown" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("verb", ["provision", "status"])
def test_reserved_verbs_exit_2_with_m6_note(verb, capsys):
    assert main([verb, "--target", "."]) == 2
    assert "M6" in capsys.readouterr().err


def test_rebrand_delegates_and_reports_missing_target():
    # rebrand requires --target; argparse exits 2 on its absence.
    with pytest.raises(SystemExit) as exc:
        main(["rebrand"])
    assert exc.value.code == 2
```

- [ ] **Step 2: Run — fails (no module)**

`uv run pytest tests/rebrand/test_press_cli.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement the dispatcher**

`src/template_press/press_cli.py`:

```python
"""press — the template-press command line.

Noun-verb dispatcher (design 0006): `press rebrand --target …` presses an
identity onto an external target repo. `provision` and `status` are reserved
for the M6 Provision phase and currently exit 2 with a pointer.
"""

from __future__ import annotations

import sys

from template_press.rebrand import cli as rebrand_cli

_RESERVED = {"provision", "status"}

_USAGE = """\
usage: press <command> [options]

commands:
  rebrand    press an identity onto a target repo (press rebrand --help)
  provision  configure a target's features (coming in M6)
  status     report a target's provisioned state (coming in M6)
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    verb, rest = args[0], args[1:]
    if verb == "rebrand":
        return rebrand_cli.main(rest)
    if verb in _RESERVED:
        print(
            f"error: '{verb}' is part of the Provision phase and is not "
            f"available yet (coming in M6).",
            file=sys.stderr,
        )
        return 2
    print(f"error: unknown command {verb!r}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Also change `rebrand/cli.py`'s `argparse.ArgumentParser(prog="press rebrand", …)`
— it is already `prog="press rebrand"`, so no change needed; confirm.

- [ ] **Step 4: Repoint the console scripts**

In `pyproject.toml` `[project.scripts]`:

```toml
[project.scripts]
# Noun-verb CLI (design 0006 §2): press <verb>. rebrand is live; provision
# and status arrive with the M6 Provision phase.
press = "template_press.press_cli:main"
# tpress: collision-proof alias (a legacy `press` exists on PyPI).
tpress = "template_press.press_cli:main"
```

- [ ] **Step 5: Run tests + smoke the installed entry**

```bash
uv sync --group dev
uv run pytest tests/rebrand/ -q          # +4 new
uv run press                              # prints the verb list, exit 0
uv run press rebrand --help               # rebrand usage
uv run press provision                    # exit 2, M6 note
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(cli): press noun-verb dispatcher; repoint console scripts

press rebrand is live; provision/status are reserved M6 stubs. The console
entry now targets the rebrand utility, not the deleted app."
```

---

## Task 4: Doc site skeleton (Sphinx machinery kept, content replaced)

**Edits/creates:** rewrite `docs/source/index.md`; replace the blueprint content
pages under `docs/source/` with a press `reference/` page; delete
`docs/source/web/` and app-describing pages; keep `conf.py`, `.readthedocs.yaml`,
`docs` dep-group, `just docs`.

- [ ] **Step 1: Inventory the current site pages**

`ls -R docs/source` — note which pages describe the app/blueprint (about,
tasks, tools, tutorials, reference/cli_reference, web) vs machinery
(`conf.py`, `_static`, `_templates`).

- [ ] **Step 2: Replace content**

- Delete `docs/source/web/` and the app-only content pages (about the
  blueprint app, its CLI, tasks/tools/tutorials describing it).
- Rewrite `docs/source/index.md` to describe the press: what it is
  (external-target rebrand utility), the `press rebrand --target` command,
  a link to design doc 0006, and a toctree pointing only at pages that exist.
- Create `docs/source/reference/cli.md` documenting `press rebrand` flags and
  the exit-code contract (0 verified / 1 leaks-no-receipt / 2 config-error).

- [ ] **Step 3: Build the site**

```bash
uv sync --group docs
just docs            # or: uv run sphinx-build -b html docs/source docs/_build/html
```
Expected: build succeeds, zero warnings about missing toctree documents /
broken autodoc (autodoc no longer imports the web app).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(site): replace blueprint content with a press skeleton

Keep the Sphinx + ReadTheDocs machinery; rewrite index + a press-rebrand CLI
reference so the site builds clean and is instantly publishable."
```

---

## Task 5: Rewrite the user-facing prose

**Edits:** `CLAUDE.md` heading, `README.md`, `AGENTS.md`, the two skills'
interim-invocation references.

- [ ] **Step 1: CLAUDE.md heading**

Line 1: `# CLAUDE.md - Claude Code entrypoint for Py Launch Blueprint` →
`# CLAUDE.md - Claude Code entrypoint for template-press`.

- [ ] **Step 2: README.md — full rewrite**

Describe template-press as a standalone external-target rebrand utility;
install (`uvx template-press` / `pip install template-press`); quick start
(`press rebrand --target ../repo --config answers.toml`); the safety model
(config-first identity, verify-then-mark); link design 0006 and the skills.
Remove blueprint/app badges and feature lists.

- [ ] **Step 3: AGENTS.md — align commands**

Remove the web-API-conventions paragraph and app command rows (`test-web`,
`serve`, `export-openapi`, `--extra web` in ty). Keep the rebrand/matrix rows.
Update the "For generated projects" framing if it references the app.

- [ ] **Step 4: Skills — canonical invocation**

In `.claude/skills/press-target/SKILL.md` and `rebrand-matrix/SKILL.md`,
replace `uv run python -m template_press.rebrand.cli` with `press rebrand`
(note `uv run press rebrand` in a dev checkout). Keep the `-m` form as a
one-line fallback.

- [ ] **Step 5: Full verification**

```bash
just check                    # full pipeline green
just audit                    # 0 CVEs (web deps gone too)
uv run --script init/ci/... : N/A (init removed)
just matrix                   # R1/R2/R3 live green (unchanged engine)
grep -rin "py.launch.blueprint\|py_launch_blueprint" --include=*.md --include=*.py \
  src docs README.md AGENTS.md CLAUDE.md .claude || echo "no blueprint self-references"
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: rewrite prose for the press (readme, claude heading, agents, skills)"
```

---

## Self-review checklist (after all tasks)

1. **Nothing kept-list was deleted**: `tests/rebrand/`, `tests/meta/`,
   `docs/{adr,design,research,superpowers}/`, publish/release workflows,
   salvage branch — all present.
2. **Zero blueprint self-identity** in shipped prose/code (the grep in T5-S5).
3. **Package is importable + entry works**: `uv run press` and
   `uv run press rebrand --help`; `python -m template_press.rebrand.cli`
   still works.
4. **Gates**: `just check`, `just audit`, `just matrix` all green; ty clean
   with NO `--extra web`.
5. **No dangling refs**: grep configs/workflows/justfile/lefthook for `web`,
   `init/`, `openapi`, `export_openapi`, `fastapi` — only intentional history
   in docs/adr remains.
