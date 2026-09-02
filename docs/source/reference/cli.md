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
| `--force` | Override a safety guard. It permits re-pressing a target that already has a receipt and, when atomic no-replacement rename is unavailable, permits a warned non-atomic fallback. The fallback checks the destination immediately before each move, but a destination created in the remaining race window may be overwritten. |
| `--allow-dirty` | Allow a target whose working tree is not clean. |

### Exit codes

The exit code is the contract — scripts and CI can branch on it:

| Code | Meaning |
|------|---------|
| `0` | Verified: the rebrand completed and no source identity remains; a receipt was written. |
| `1` | Leaks found after applying — a partial/incorrect rebrand. **No receipt** is written; the target is left rewritten (restore with `git -C <target> checkout . && git clean -fd`). |
| `2` | Precondition or configuration error (missing target, dirty tree, source/target identity mismatch, an existing receipt without `--force`, or unavailable atomic rename without `--force`). **Nothing is written.** |

`--dry-run` exits `0` after printing the plan — it is a preview and writes nothing (no receipt). It performs a read-only host check; a statically unsupported host produces a warning that real apply requires `--force`. The target filesystem's operational atomic-rename capability is probed only during real apply. Other plan-time refusals (a missing declared tool, a stale argv, an undeclared excluded file) exit `2` before the plan renders, exactly as they would without `--dry-run`.

### Structured refusals

A rename-prefix closure that carries content absent from the authorized
surface inventory (`code = rename_closure_unauthorized`) refuses at the
plan-time check with exit `2` — "nothing written" — under both `--dry-run`
and a real apply, since a real apply runs the same plan-time check before
writing anything; dry-run never prints the `(dry run — nothing applied)`
success terminator on a refusal. The prose form names every offending path
in the rendered message (up to 20, sorted, plus a total/truncated count —
`truncated` describes only this rendering; the typed exception's `findings`
and the `--diagnostics-json` payload's `findings` always carry every one of
them, uncapped) and prints a remedy as literal-pathspec `git clean` argv: a
preview (`clean -ndX`) and a remove (`clean -fdX`). Both are restricted to
`-d` (directories) and `-X` (ignored files only — never `-x`), and are
deliberately broader than the specific paths listed — run only after
confirming the preview shows nothing worth keeping. When the target declares
`[[clean]]` rules, the refusal also names `press clean` as the fix to run
first. Pass `--diagnostics-json` to get the same information as one JSON
object on stdout instead of prose (schema `{"schema", "code", "source_prefix",
"findings", "total", "truncated", "phase", "preview_argv", "remove_argv"}`) —
the exit code is unchanged.

If the target tree changes between planning and apply — e.g. a new ignored
file appears under a prefix being renamed — the same check runs again as an
apply-time revalidation immediately before the first mutation. It prints the
same aggregated findings and remedy argv, but never as JSON (the plan has
already printed to stdout by then), and it exits `1` under the partial-
rewrite contract (target may be partially rewritten; restore with
`git -C <target> checkout . && git clean -fd`), not `2`.

### The ignore set

If a target legitimately keeps some source-identity content (vendored code,
historical docs), list those directory names under `verify_ignore` in
`<target>/press/press-rules.toml` so the no-leak scan skips them. To also stop
those directories from being rewritten, list the same names under
`extra_exclude_dirs`. Both keys match a single directory *name* at any depth,
not a path.

### Platform-conditional reset and regeneration

`[[regenerate]]` and `[[reset]]` declarations may include an optional
`platforms` selector. The selector is a non-empty list containing one or more
of these exact Python runtime platform values:

| Value | Supported host |
|-------|----------------|
| `"darwin"` | macOS |
| `"linux"` | Linux |
| `"win32"` | Windows |

Omitting `platforms` makes the declaration active on all three supported
platforms. Values are case-sensitive and whitespace-sensitive. Empty lists,
duplicate values, non-string values, and any value outside the table are
configuration errors.

This example assigns one `bun.lock` output to a native command on each host:

```toml
[[regenerate]]
file = "bun.lock"
command = ["scripts/regen-bun-lock.sh"]
platforms = ["darwin", "linux"]

[[regenerate]]
file = "bun.lock"
command = ["powershell", "-NoProfile", "-File", "scripts/regen-bun-lock.ps1"]
platforms = ["win32"]
```

The same file may appear in multiple `[[regenerate]]` declarations, multiple
`[[reset]]` declarations, or one declaration of each kind only when their
platform sets are disjoint. If two declarations can write the same file on
the same platform, configuration loading fails with exit code `2`.

### Regeneration scan policy

A `[[regenerate]]` declaration may set `scan` to choose how the post-command
content scan hunts the changed identity fields in the produced output:

| Value | Meaning |
|-------|---------|
| `"strict"` (default) | The paranoid matcher, including per-field substring mode — case-insensitive, no boundary check. |
| `"boundary"` | Boundary-safe matching only. The declared escape hatch for hash-dense outputs: a lockfile's base64 integrity hashes will eventually contain a short substring-mode `app_name` by chance, failing the press on noise. |

`scan = "boundary"` downgrades only the output's **content** scan; the
translated-path scan and rendered `[[replace]]` literal checks stay strict.

```toml
[[regenerate]]
file = "bun.lock"
command = ["scripts/regen-bun-lock.sh"]
scan = "boundary"
```

### Declared removal

Template-only files — maintenance CI workflows, dogfood history — must not
ship to pressed forks. A `[[remove]]` declaration deletes the file during
the press, after the rewrite/rename passes, at its post-rename location:

```toml
[[remove]]
file = "docs/maintenance-log.md"
reason = "template maintenance history; forks must not inherit it"
```

`reason` is required — a removal is a deliberate, documented decision.
Targets must exist, be git-tracked, and be clean at plan time; a
`[[remove]]` naming a missing file refuses the press (exit 2 — a stale
declaration is config drift, never a silent no-op). Removals are rendered
in the plan, counted in the receipt (`[[press.remove]]` with the reason),
and count as a §6 neutralization for excluded files. Hermetic
`press verify` performs removals in its sandbox — no command is needed, so
unlike regeneration there is no exemption and no coverage gap. An optional
`platforms` selector scopes a removal like reset/regenerate.

When `[[remove]]` declares at least one file under a directory, the plan
appends a `removing N files under <dir>/` summary line beneath the
per-file lines — a quick count check, grouped by the removal's declared
SOURCE path, top-level directory only.

### Declared-removal coverage warning

Plan time also checks, independently of any `[[remove]]` declaration,
whether a top-level directory (depth 1 — a target's `<dir>/`, not any
directory nested inside it) looks like undeclared template history: every
one of its git-tracked files is a rewrite candidate — it either gets a
content substitution, or its path falls under a planned rename (a
rename-only file, such as a logo image or a directory named after the
package, counts too) — and no `[[remove]]` or `[[reset]]` rule touches
anything under it. When that happens, the plan prints a non-fatal
`warning: N tracked files under <dir>/ will be rewritten to the new
identity and no rule removes or resets them — declare [[remove]] or
[rules] verify_ignore if this is template history` line — on both
`--dry-run` and a real apply, after the plan, with the exit code
unchanged. The directories `src/`, `tests/`, and the top-level directory
named after the SOURCE identity's `package_name` (the flat-layout package
root — under `src/` layout the package sits a level deeper, already
covered by the `src/` exclusion) are never flagged: a fully rewritten
package or test tree is the expected, unremarkable case, not a sign of
leftover history. A directory named in `[rules] verify_ignore` is likewise
never flagged. This is advisory only — it never blocks a press, and a
directory with even one untouched tracked file (an image, an unrelated
config) does not count as "fully rewritten" and stays silent.

### Prefix-only occurrence warning

Plan time also checks, per identity field and per rendered display form
(skipping `app_name` and `app_name_upper`, whose own rewrite matchers
already treat a trailing hyphen as a boundary — and `app_name_upper`'s own
designed usage is `_`+alphanumeric, e.g. `_PRESS_COMPLETE`), whether the
declared SOURCE value shows up in the target's tracked content ONLY as a
separator-joined prefix of a longer token — never as a whole token on its
own. A "separator-joined prefix" means a `-` or `_` right after the value,
followed by an alphanumeric — `demo-widget-2` — NOT a `.`: a dot right
after the value is an extension or domain suffix (`demo-widget.git`,
`template-press.svg`, `name.toml`), not a rename continuation, and always
classifies whole-token. This is the signature of a target that renamed
itself upstream (`demo-widget` -> `demo-widget-2`, or a spaced display
name `Demo Widget` -> `Demo Widget-2`) after `press/press-source.toml` was
written, since the rewrite matcher's own boundary rule treats a hyphen or
underscore right after the value as a non-boundary: `demo-widget` still
matches, and still rewrites, inside `demo-widget-2`, so nothing else flags
the drift. When a field or display form has at least one prefix
occurrence and zero whole-token occurrences, the plan prints a non-fatal
`warning: <field> '<value>' occurs only as a prefix of '<longer-token>'
(N places); if the template was renamed, update press/press-source.toml`
line — on both `--dry-run` and a real apply, after the plan, with the
exit code unchanged. A field with even one whole-token occurrence stays
silent even when a prefix form also exists (`demo-widget` alongside
`demo-widget-web`): a compound naming convention living next to the plain
value is a deliberate, rewritable form, not a stale source config.

### Declared verify exemption

Hermetic `press verify` never runs declared commands, so a regenerated
output cannot be certified in the sandbox. By default only the tool cap
(`uv.lock`, `bun.lock`) is exempted from the leak scan; any other declared
output is scanned and will fail verify while it still carries source
identity. A target may exempt such an output — loudly — by declaring it:

```toml
[[regenerate]]
file = "docs/generated-api.md"
command = ["scripts/render-api-docs.sh"]
verify_exempt = true
reason = "rendered from source at build time; press cannot rewrite it"
```

`verify_exempt = true` requires a non-empty `reason` (control characters
rejected — the reason is rendered in reports); a `reason` without
`verify_exempt` — even an empty one — is rejected as dead config. The
reason is carried verbatim in the receipt's `[[press.exempt]]` record and
included in verify's not-verified listing and `--json` output, so the
coverage gap stays visible and reviewed rather than silently purchased.
The real press's post-command scan still certifies the output at press
time.

Configuration loading has two phases:

1. Press parses and validates every declaration, including declarations that
   are inactive on the current host. Schema errors and overlapping same-file
   writers therefore cannot hide behind a platform selector.
2. Press captures `sys.platform` once and selects the active declarations.
   Host-dependent checks, such as executable resolution and `stub_file`
   reading, run only for that selected set.

The selected platform is printed once before rebrand plans and
`press check-tools` reports. Plans, tool checks, resets, regenerations, and
receipts contain active declarations only. A successful receipt records the
captured value as `press.platform`, successful regeneration actions as
`[[press.regenerate]]`, and applied reset actions as `[[press.reset]]`.

Git is not a declared regeneration tool. Press and `press check-tools` require
and check Git on every supported platform, including when no reset or
regeneration declaration is active.

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

Reports whether every active `[[regenerate]]` command's `argv[0]` — plus
`git`, the one tool press itself needs — resolves on the captured platform,
using exactly the resolution the press will use (path-qualified names against
the target root, bare names on the deny-by-default effective `PATH`). It
validates all declarations before platform selection, writes nothing, and
executes nothing.

```console
$ press check-tools --target ../my-repo
Platform: darwin
git — /usr/bin/git
uv — /opt/homebrew/bin/uv (regenerates uv.lock)
bun — missing (declared to regenerate bun.lock)
```

| Code | Meaning |
|------|---------|
| `0` | Every tool resolved. |
| `1` | At least one tool is missing. |
| `2` | Configuration or usage error. |
