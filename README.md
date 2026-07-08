<!-- ITM-081 — badges. Single horizontal row (decided round 23). -->
[![PyPI version](https://img.shields.io/pypi/v/template-press.svg)](https://pypi.org/project/template-press/)
[![Python versions](https://img.shields.io/pypi/pyversions/template-press.svg)](https://pypi.org/project/template-press/)
[![CI](https://github.com/smorinlabs/template-press/actions/workflows/ci.yml/badge.svg)](https://github.com/smorinlabs/template-press/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/smorinlabs/template-press/branch/main/graph/badge.svg)](https://codecov.io/gh/smorinlabs/template-press)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://www.conventionalcommits.org/)

# template-press

**Press a new identity onto an existing repository.** template-press is a
standalone command-line utility: you point it at a target repo, it discovers
and *validates* that repo's current identity, rewrites every occurrence to a
new identity, and — only after verifying that none of the old identity
survives — writes a receipt. A wrong or partial run fails loudly instead of
silently corrupting the target.

It is **not** a project template you fork; it is a tool you run against other
repos, one at a time. The rebrand engine is pure standard library, so the
installed package has **zero runtime dependencies**.

## Install

```bash
uvx template-press --help          # run without installing
# or
pip install template-press
```

## Usage

```bash
# preview the plan (writes nothing)
press rebrand --target ../my-repo --config answers.toml --dry-run

# apply, verify, and write a receipt
press rebrand --target ../my-repo --config answers.toml
```

`answers.toml` describes the **destination** identity:

```toml
[answers]
package_name = "new_pkg"
repo_name    = "new-repo"
app_name     = "newcli"
author       = "Jane Dev"
email        = "jane@example.com"
owner        = "janedev"
```

The target's **current** identity is read from a committed
`<target>/.press/source.toml`. On a first run, `--dry-run` prints a proposed
source-config from discovery; review it and re-run with `--accept-discovery`
to write and use it.

## How it stays safe

- **Config-first identity, discovery as a guard.** The committed source-config
  is authoritative; discovery cross-checks it against the target and *refuses
  to run on a mismatch*, so the press never rewrites the wrong repo.
- **Verify-then-mark.** After rewriting, a no-leak scan confirms no source
  identity remains. Any leftover ⇒ **exit 1 and no receipt** — a partial
  rebrand is a loud failure, not a false success.
- **Boundary-safe replacement.** Short tokens (`press`, an owner like `go`)
  match only at word boundaries, so ordinary prose (`compress`, `ongoing`) is
  never touched.

## Exit codes

The exit code is the contract:

| Code | Meaning |
|------|---------|
| `0` | Verified — rebrand complete, no source identity remains, receipt written. |
| `1` | Leaks found after applying. No receipt; restore with `git -C <target> checkout . && git clean -fd`. |
| `2` | Precondition/config error (missing target, dirty tree, identity mismatch, existing receipt without `--force`). Nothing written. |

## Documentation

- Full docs: <https://template-press.readthedocs.io/>
- Design contract: [`docs/design/0006-external-target-model.md`](docs/design/0006-external-target-model.md)
- Agent runbooks: [`press-target`](.claude/skills/press-target/SKILL.md) (drive a
  press) and [`rebrand-matrix`](.claude/skills/rebrand-matrix/SKILL.md) (the
  R1/R2/R3 acceptance matrix)

## Contributing

See [`AGENTS.md`](AGENTS.md) for the canonical toolchain and verification flow
(`just setup` → `just check` → commit) and
[`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for the human contributor
guide.

## License

MIT — see [`LICENSE`](LICENSE).
