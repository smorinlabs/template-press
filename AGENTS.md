# AGENTS.md

Canonical guidance for ALL coding agents (Claude Code, Cursor, Codex,
Windsurf, Aider, etc.) — this is the single file to edit.
[`CLAUDE.md`](CLAUDE.md) imports it verbatim (`@AGENTS.md`); Cursor,
Windsurf, and Codex read this file natively. For human-contributor flow see
[`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

## Required tools

- **Python 3.12+** (per `requires-python = ">=3.12"`; see ITM-033).
- **uv** — Python dependency + venv management.
- **bun** — commitlint runtime (per ADR-04).
- **lefthook** — hook manager (per ADR-01).
- **gitleaks** — secret scanner (per ADR-02).

Setup is two levels, in order (both idempotent):

```bash
make bootstrap   # Level 1 — base toolchain (just + uv); bare machines only
just setup       # Level 2 — everything else (run every fresh clone/container/session)
```

`just setup` syncs the dev env (`uv sync --group dev`), wires
lefthook git hooks, and installs the hook toolchain (bun + `bun install`,
gitleaks, taplo, yamlfmt). It starts by running the Makefile's `make check`
gate and fails with a pointer to `make bootstrap` if the base toolchain is
missing — so running it "too early" is safe. The hook wiring is REQUIRED
before any commit/push work: without it none of the hooks below fire. Fresh
clones, containers, and remote agent sessions start without it — run
`just setup` as part of environment setup, every session. (The underlying
`scripts/install-*.sh` installers remain available individually.)

## Canonical commands

| Task | Command |
|---|---|
| Sync dev env | `uv sync --group dev` (PEP 735 — not `pip install '.[dev]'`) |
| All checks | `just check` |
| Run tests | `pytest` (default excludes `slow`/`live` markers per ITM-046; full: `pytest -m ""`) |
| Rebrand a target (preview) | `uv run press rebrand --target <dir> --config <answers.toml> --dry-run` |
| Rebrand acceptance matrix | `just matrix` (live; see `.claude/skills/rebrand-matrix/`) |
| Run one test | `pytest tests/test_file.py::test_name` |
| Lint | `uv run ruff check .` |
| Format | `just format` or `uv run ruff format src/template_press/` |
| Format check | `uv run ruff format --check .` |
| Typecheck | `uv run ty check src/template_press/` (ITM-026 / ADR-03) |
| Dependency CVE audit | `just audit` (WL-014; same pipeline as the weekly CI workflow) |
| Secret scan | `scripts/check-gitleaks.sh --staged` or `--range` |
| Build | `uv build` (uv_build backend per ADR-06) |

Hook/CI tools run from the locked dev group (`uv run`, never floating
`uvx`) per WL-001 — versions come from `uv.lock`.

The rebrand engine is pure standard library — the shipped package has zero
runtime dependencies. The design contract is
[`docs/design/0006-external-target-model.md`](docs/design/0006-external-target-model.md).

## Verification flow before commit/PR

1. `just setup` (idempotent — REQUIRED in fresh clones/containers so the
   hooks in step 3 actually fire; also refreshes deps).
2. `just check` (full pipeline must pass).
3. Stage + commit. Lefthook fires automatically:
   - **commit-msg** → commitlint (Conventional Commits, lowercase subject).
   - **pre-commit** → gitleaks + editorconfig-checker + yamllint + codespell
     + ruff check/format on staged Python files.
   - **pre-push** → gitleaks range scan + bandit.

   If lefthook was not installed (step 1 skipped), the hooks are silent
   no-ops — do NOT push until you have either installed it or run `just
   check` manually.
4. After ANY change to `src/template_press/rebrand/`, run `just matrix`
   (the R1/R2/R3 acceptance matrix; see `.claude/skills/rebrand-matrix/`).

## Commit message format

Conventional Commits with lowercase subject (commitlint enforces):

```
<type>(<optional scope>): <lowercase subject>
```

Allowed types: `feat`, `fix`, `perf`, `refactor`, `revert`, `chore`,
`docs`, `style`, `test`, `ci`, `build` (commitlint-enforced; `deps` is NOT
a type here — use `build(deps):` for dependency bumps).

## Code style

- Line length: 88 characters (Black standard)
- Types: strict typing required for all functions
- Imports: sorted (ruff isort); absolute intra-package imports
  (`from template_press…` — the codebase convention)
- Naming: PEP 8 conventions enforced via Ruff
- Errors: prefer explicit error handling over assertions
- Tests: type annotations optional for test files
- Security: no hardcoded credentials, follow bandit rules

## Developer environment

- Toolchain provisioning (per ADR 0005) — three first-class options, all
  declaring the SAME 10-tool set (python, uv, ruff, taplo, gitleaks, just,
  bun, gh, lefthook, make); keep them in sync when adding/removing a tool:
  1. Native installs (Makefile + Justfile `install-*` targets,
     `scripts/install-*.sh`)
  2. `mise install` (root `mise.toml`)
  3. `flox activate` (root `.flox/`)
- Deliberately NOT in `mise.toml`/`.flox`: yamllint, codespell, bandit,
  editorconfig-checker (run via `uv run` from the locked dev group, per WL-001)
  and commitlint (run via `bunx --bun @commitlint/cli`) — `uv sync`/bun provide
  them, and a mise `commitlint` shim shadows bun's PATH fallback (see note in
  lefthook.yml)
- Build backend: `uv_build` with static `[project] version` (per ADR-06)
- IDE: VS Code with Ruff, Pyright, EditorConfig extensions

## Releases

`release-please` opens a release PR on every push to `main`; merging the PR
cuts a `v*` tag; `publish.yml` uploads to TestPyPI then PyPI via OIDC
Trusted Publishing. See [ITM-053..060] for the full chain.

## Running the press

template-press is a utility you point at an external target repo, not a
project template. To press an identity onto a repo, follow the
[`press-target`](.claude/skills/press-target/SKILL.md) skill (dry-run →
identity validation → apply → verify → receipt). Command shape:
`press rebrand --target <path> --config <answers.toml>` (in a dev checkout,
`uv run press rebrand …`). The design contract is
[`docs/design/0006-external-target-model.md`](docs/design/0006-external-target-model.md);
`provision`/`status` verbs arrive with the M6 Provision phase.

## Single source of truth

`AGENTS.md` is the canonical agent guidance; `CLAUDE.md` imports it, so add
Claude-specific notes there only. Vendor-specific rule files (`.cursor/`,
`.windsurf*`) are deliberately absent: Cursor, Windsurf, and Codex all read
`AGENTS.md` directly.

## Project tracking (plugin: project-harness)

Project state lives in `PROJECTS.md` (trunk) + `projects/` (per-project files).
Route state changes through these skills rather than hand-editing:

- `using-project-harness` — bootstrap / which skill to use
- `project-next` — what's in progress / next / recently touched
- `project-add` — capture an idea (reserves the ID with a commit)
- `project-refine` — scope / decompose a project
- `project-audit` — verify state matches conventions

Planning system: Superpowers (specs under `docs/superpowers/specs/`).
