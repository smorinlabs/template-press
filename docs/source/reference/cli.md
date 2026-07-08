# CLI reference

template-press exposes a single `press` command with a noun-verb shape.
`rebrand` is available today; `provision` and `status` arrive with the M6
Provision phase.

## `press rebrand`

Press the destination identity onto a target repository.

```bash
press rebrand --target <path> --config <answers.toml> [options]
```

In a development checkout, run it through uv: `uv run press rebrand …`
(equivalently `uv run python -m template_press.rebrand.cli …`).

### Options

| Option | Meaning |
|--------|---------|
| `--target PATH` | The target repository to press (required). |
| `--config PATH` | Answers TOML describing the **destination** identity (`[answers]` table). |
| `--source-config PATH` | Override the target's committed `.press/source.toml` (the **source** identity). |
| `--accept-discovery` | When the target has no source-config, write one from discovery and proceed. |
| `--dry-run` | Print the plan and exit without touching the target. |
| `--force` | Re-press a target that already has a receipt. |
| `--allow-dirty` | Allow a target whose working tree is not clean. |

### Exit codes

The exit code is the contract — scripts and CI can branch on it:

| Code | Meaning |
|------|---------|
| `0` | Verified: the rebrand completed and no source identity remains; a receipt was written. |
| `1` | Leaks found after applying — a partial/incorrect rebrand. **No receipt** is written; the target is left rewritten (restore with `git -C <target> checkout . && git clean -fd`). |
| `2` | Precondition or configuration error (missing target, dirty tree, source/target identity mismatch, an existing receipt without `--force`). **Nothing is written.** |

### The ignore set

If a target legitimately keeps some source-identity content (vendored code,
historical docs), list those directory names under `verify_ignore` in
`<target>/.press/rules.toml` so the no-leak scan skips them. To also stop
those directories from being rewritten, list the same names under
`extra_exclude_dirs`. Both keys match a single directory *name* at any depth,
not a path.

### After a successful press

A receipt is written to `<target>/.press/receipt.toml`, and
`<target>/.press/source.toml` is refreshed to the new identity so a future
re-press starts from a valid baseline. Review with `git -C <target> status`
(the `.press/` files are untracked on a first run) and commit in the target.

See [`press-target`](https://github.com/smorinlabs/template-press/blob/main/.claude/skills/press-target/SKILL.md)
for the full agent runbook and
[`rebrand-matrix`](https://github.com/smorinlabs/template-press/blob/main/.claude/skills/rebrand-matrix/SKILL.md)
for the R1/R2/R3 acceptance matrix.
