```{figure} _static/template_press_logo_100x100.png
:alt: template-press
:width: 100px
:align: left
```

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

# template-press

**template-press** is a standalone command-line utility that presses a new
identity onto an existing repository. You point it at a target repo, it
discovers and validates that repo's current identity, rewrites every
occurrence to the new identity, and — only after verifying that nothing of the
old identity survives — writes a receipt.

It is **not** a project template you fork; it is a tool you run against other
repos, one at a time.

## Install

```bash
uvx template-press --help          # run without installing
# or
pip install template-press
```

## Quick start

```bash
press rebrand --target ../my-repo --config answers.toml --dry-run   # preview
press rebrand --target ../my-repo --config answers.toml             # apply
```

`answers.toml` describes the destination identity:

```toml
[answers]
package_name = "new_pkg"
repo_name    = "new-repo"
app_name     = "newcli"
author       = "Jane Dev"
email        = "jane@example.com"
owner        = "janedev"
```

## How it stays safe

- **Config-first identity.** The target's current identity is read from a
  committed `.press/source.toml`; discovery *validates* it and refuses to run
  on a mismatch, so the press never silently rewrites the wrong repo.
- **Verify-then-mark.** After rewriting, a no-leak scan confirms no source
  identity survives. Any leftover ⇒ exit 1 and **no receipt** — a partial
  rebrand fails loudly instead of pretending to succeed.
- **Boundary-safe.** Short tokens (`press`, an owner like `go`) are matched at
  word boundaries, so unrelated prose (`compress`, `ongoing`) is untouched.

The full design contract is
[design 0006 — external-target model](https://github.com/smorinlabs/template-press/blob/main/docs/design/0006-external-target-model.md).
The `provision` and `status` verbs (feature setup + computed state) arrive with
the M6 Provision phase.

```{toctree}
---
maxdepth: 2
---
reference/index
contributing/index
```
