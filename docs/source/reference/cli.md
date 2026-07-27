# CLI reference

template-press exposes a single `press` command with a noun-verb shape.
`rebrand` and `verify` are available today; `provision` and `status` arrive
with the M6 Provision phase.

## `press rebrand`

Press the destination identity onto a target repository.

```bash
press rebrand --target <path> --config <press-answers.toml> [options]
```

In a development checkout, run it through uv: `uv run press rebrand …`
(equivalently `uv run python -m template_press.rebrand.cli …`).

### Options

| Option | Meaning |
|--------|---------|
| `--target PATH` | The target repository to press (required). |
| `--config PATH` | Answers TOML describing the **destination** identity (`[answers]` table). |
| `--source-config PATH` | Override the target's committed `press/press-source.toml` (the **source** identity). |
| `--accept-discovery` | When the target has no source-config, write one from discovery and proceed. |
| `--dry-run` | Print the plan and exit without touching the target. |
| `--force` | Re-press a target that already has a receipt. The prior receipt is removed once the plan gates pass, before the first write — a failed forced re-press cannot leave a stale receipt advertising a verified press. |
| `--allow-dirty` | Allow a target whose working tree is not clean. |

### Exit codes

The exit code is the contract — scripts and CI can branch on it:

| Code | Meaning |
|------|---------|
| `0` | Verified: the rebrand completed and no source identity remains; a receipt was written. |
| `1` | Leaks found after applying — a partial/incorrect rebrand. **No receipt** is written; the target is left rewritten (restore with `git -C <target> checkout . && git clean -fd`). |
| `2` | Precondition or configuration error (missing target, dirty tree, source/target identity mismatch, an existing receipt without `--force`). **Nothing is written.** |

`--dry-run` exits `0` after printing the plan — it is a preview and writes nothing (no receipt). Plan-time refusals (a missing declared tool, a stale argv, an undeclared excluded file) exit `2` before the plan renders, exactly as they would without `--dry-run`.

### The ignore set

If a target legitimately keeps some source-identity content (vendored code,
historical docs), list those directory names under `verify_ignore` in
`<target>/press/press-rules.toml` so the no-leak scan skips them. To also stop
those directories from being rewritten, list the same names under
`extra_exclude_dirs`. Both keys match a single directory *name* at any depth,
not a path.

### After a successful press

A receipt is written to `<target>/press/press-receipt.toml`, and
`<target>/press/press-source.toml` is refreshed to the new identity so a future
re-press starts from a valid baseline. Review with `git -C <target> status`
(the `press/` files are untracked on a first run) and commit in the target.

See [`press-target`](https://github.com/smorinlabs/template-press/blob/main/.claude/skills/press-target/SKILL.md)
for the full agent runbook and
[`rebrand-matrix`](https://github.com/smorinlabs/template-press/blob/main/.claude/skills/rebrand-matrix/SKILL.md)
for the R1/R2/R3 acceptance matrix.

## `press verify`

Check that a template presses cleanly — no source identity leaks survive the
hermetic self-press. Verify makes no mutations; it builds a sandbox copy,
presses toward a synthetic destination identity, and scans for surviving
source identity.

### Zero-argument CI usage

In a template repo's CI (e.g., as a drift guard after a rebrand):

```bash
press verify
```

The exit code signals the result:
- `0`: Clean over the scanned set — no source identity leaks survived the
  press in any scanned file. Files with a declared regeneration whose
  basename is on the tool's exemptible list (`uv.lock`, `bun.lock`) are
  NOT scanned (the hermetic sandbox never runs commands, so only the real
  press's post-command scan can certify them); they are listed as exempt
  in the report and in the `exempt` field of `--json` output.
- `1`: Verification failed — source identity found in the pressed copy.
- `2`: Configuration, environment, or unverifiable identity error.

### Options

```bash
press verify [--target PATH] [--json]
```

| Option | Meaning |
|--------|---------|
| `--target PATH` | The target repository to verify (default: `.` the current directory). |
| `--json` | Output structured JSON instead of human text. |

### Configuration: `[verify]` table

Customize the scan scope by adding a `[verify]` table to the target's
`press/press-rules.toml` file.

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `extra_fields` | string array | `[]` | Additional identity fields to scan. Accepts any identity field name; fields beyond the default scan are `author`, `email`, `app_name_upper`. (Default scans: `app_name`, `package_name`, `repo_name`, `owner`.) |
| `substring_fields` | string array | `[]` | Fields to scan using substring matching instead of boundary-safe matching. Must be a subset of the scanned fields. |
| `equal_fields` | `"warn"` or `"error"` | `"warn"` | Whether two equal source-identity fields trigger a failure. With `"error"`, `press verify` fails (exit 1) if any two field values are identical. |
| `[[verify.ignore]]` | table array | `[]` | Source-anchored ignores — surviving findings to suppress (see below). |

### Ignore set: `[[verify.ignore]]`

List findings to suppress as a TOML array of tables. Each ignore entry matches
a surviving finding and suppresses it.

| Key | Type | Optional | Meaning |
|-----|------|----------|---------|
| `field` | string | No* | The identity field name (e.g., `"app_name"`). |
| `value` | string | No* | The value string. |
| `file` | string | **No (required)** | File path (relative to the target root) in **source** coordinates where the finding occurs. It must equal the finding's source path exactly. Omitting it defaults to `""`, which matches no path — the ignore then suppresses nothing, is reported stale, and the run exits `1`. |
| `anchor` | string | Yes | A substring that must appear in the finding's source line (content findings) or source path (path/binary findings); if omitted (`""`) it matches everything. |
| `line` | integer | Yes | Line number (1-based) in the original source file — if set, the finding is suppressed only on exactly this line. |
| `ordinal` | integer | Yes | The **0-based** occurrence index of the field/value pair within its `(file, field, value, line)` group (first occurrence = `0`) — if set, suppresses only that occurrence. |
| `force` | boolean | Yes (default `false`) | Only exempts a zero-match ignore from the staleness failure — it does **not** force-suppress a finding. A `force` ignore that matches nothing is simply not reported stale. |
| `reason` | string | Yes | A short note explaining why the ignore exists (for documentation). |

\* Either `field` or `value` (or both) must be present.

### Example `[verify]` configuration

```toml
[verify]
extra_fields = ["email"]
substring_fields = ["app_name"]
equal_fields = "error"

[[verify.ignore]]
field = "app_name"
file = "vendor/legacy/old_name.py"
reason = "Vendored third-party code; cannot modify"

[[verify.ignore]]
value = "oldrepo"
file = "docs/CHANGELOG.md"
line = 42
reason = "Historical reference in changelog"
```

## `press check-tools`

Reports whether every declared `[[regenerate]]` command's `argv[0]` — plus
`git`, the one tool press itself needs — resolves on this machine, using
exactly the resolution the press will use (path-qualified names against the
target root, bare names on the deny-by-default effective `PATH`). It reads
the target's config, writes nothing, and executes nothing.

```console
$ press check-tools --target ../my-repo
git — /usr/bin/git
uv — /opt/homebrew/bin/uv (regenerates uv.lock)
bun — missing (declared to regenerate bun.lock)
```

| Code | Meaning |
|------|---------|
| `0` | Every tool resolved. |
| `1` | At least one tool is missing. |
| `2` | Configuration or usage error. |
