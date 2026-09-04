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
| `--accept-origin-mismatch` | Proceed when `origin`'s `owner`/`repo_name` match neither the source-config nor the destination; prints each mismatch and records it in the receipt. Never covers pyproject-derived fields. |
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

### The source-identity guard and the `origin` remote

Before planning anything, the press cross-checks the committed
`press/press-source.toml` (the **source** identity) against what the target
actually shows — `pyproject.toml`, the `[project.scripts]` key, the package
layout, and the `origin` remote's GitHub URL, from which `owner` and
`repo_name` are read. Any disagreement is the silent-half-rebrand guard's
business and exits `2` with nothing written.

`origin` is the one input that legitimately runs ahead of the source-config:
the usual bootstrap is `gh repo create --template …` (or a clone whose
remote was repointed), so the fresh target's `origin` already names the
repository you are pressing *to*, not the template you are pressing *from*.
For `owner` and `repo_name` only, and independently per field, the guard
therefore recognizes three states:

| `origin` names, for that field | Default | With `--accept-origin-mismatch` |
|---|---|---|
| The **source** identity (matches `press-source.toml`) | Agrees — no message. | Identical: there is nothing to relax. |
| The **destination** identity (matches the `--config` answers for that same field) | Accepted, with a `notice:`; the press proceeds. | Identical: destination-equality is tried first, so the field is a notice, never a warning. |
| **Neither** identity | Exit `2` with the mismatch message, as before. | Accepted, with a `warning:`; the press proceeds. |

The destination case prints one line per relaxed field to stdout, immediately before the plan:

```text
notice: repo_name: origin already names the destination ('potato-launcher'); source-config says 'demo-widget' — accepted
```

and the receipt records exactly which fields were relaxed, as a sorted list
under `[press]`:

```toml
origin_named_destination = ["owner", "repo_name"]
```

The key is written only when the relaxation actually fired, so a receipt
without it means the guard relaxed nothing for that press: `origin` agreed
with the source-config, or had no discoverable value (no `origin` remote, or
one that is not a GitHub URL — discovery skips such fields).

`--accept-origin-mismatch` covers the third state, where `origin` names
neither identity — an `owner` or `repo_name` the press has never been told
about. It is not `--force` and does not imply it: it relaxes this guard, for
these two fields, and nothing else. Each accepted field prints one warning
line to stdout, in the same place as the notices:

```text
warning: repo_name: source-config 'demo-widget', repository 'else', destination 'potato-launcher' — proceeding on --accept-origin-mismatch
```

and the receipt records the accepted fields with the **exact `origin` value**
accepted for each, as a key-sorted inline table under `[press]`, written only
when the flag actually accepted something:

```toml
origin_mismatch_accepted = { owner = "someone", repo_name = "else" }
```

A field appears in at most one of the two records: destination-equality is
tried first, so a field the origin already names the destination for is a
notice under the `origin_named_destination` list even when the flag is passed.
That list carries no values because it needs none — its values are the
destination's, which the press writes into `press-source.toml`.

The press never touches git remotes, so after a flag-accepted press
`press-source.toml` names the destination while `origin` still names the third
repository. **`press verify` honors the receipt**: it drops an `owner` or
`repo_name` mismatch when — and only when — the value it discovers *now* is
byte-for-byte the value the receipt recorded, and prints one line per waived
field before its verdict:

```text
note: owner: origin 'someone' accepted by the press receipt (--accept-origin-mismatch)
```

A receipt describes one identity's press, so verify honors one only when it is
**bound to this target**. Both conditions must hold:

1. **It is a verified press.** The `[press]` table carries `verified = true` —
   the receipt is written only after the no-leak pass, so anything else is not
   a completed press.
2. **Its `[press.to]` equals this target's identity.** The press writes the
   same field mapping into `[press.to]` and into `press/press-source.toml`, so
   a genuine receipt matches its own target exactly — the same field names and
   the same values, so an extra or a missing field is a mismatch too. Value
   comparison is exact, like the guard's.

The binding is by **identity, not provenance**. A receipt describing a
different identity fails the second condition; a hand-written `[press]` table
asserting an acceptance fails the first. Two targets that declare the *same*
identity are indistinguishable to this check, so a receipt moved between them
is honored — by design: the check exists to stop a receipt speaking for an
identity it does not describe, not to trace which directory it was written in.
On either failure verify exits `2` and says which condition failed, on stderr,
next to the mismatch it refused:

```text
error: press receipt not honored: [press.to] does not match press-source.toml
error: owner: source-config says 'potatolabs' but target shows 'someone'
```

Past that binding, the waiver is by value, not by field name, so it cannot go
stale into a free pass:

- Repoint `origin` at *yet another* repository and verify exits `2` again,
  naming the field — the receipt says nothing about that new value.
- A receipt written by template-press **4.1 or earlier** records field names
  only (`origin_mismatch_accepted = ["owner", "repo_name"]`) and so cannot say
  which value was accepted. It is not honored: verify exits `2` exactly as it
  did before. There is no in-place upgrade — a target already carrying the
  destination identity meets the `source and destination identities are
  identical` guard, which `--force` does not bypass. Repoint `origin` at the
  destination instead:

  ```bash
  git -C <target> remote set-url origin https://github.com/<owner>/<repo_name>.git
  press verify --target <target>
  ```

- Nothing else is waived. A `package_name`, `app_name`, `author`, or `email`
  mismatch still exits `2`, and so does an origin mismatch on a target with no
  receipt at all.

The `note:` lines are prose-mode only; `press verify --json` keeps its contract
that the JSON object is the whole of stdout, and its payload is unchanged. The
`error: press receipt not honored:` line is *not* mode-gated — it goes to
stderr, which the stdout contract does not cover, so a machine-mode run gets
the same explanation a prose run does.

Notices and warnings appear only on a run that clears every plan-time gate —
they are printed with the plan, not when the guard makes the decision. A run
that refuses at a plan-time gate carries neither: its refusal text is
complete on its own, and the `--diagnostics-json` payload keeps its promise
that the JSON object is the whole of stdout. This includes the partial case,
where one field names the destination and the other names neither and the
flag was not passed: the guard exits `2` naming the field that failed, and
says nothing about the field it would have accepted. (A failure *after* the
plan renders — an I/O error while writing, or a leak found by the
verification pass — can of course exit non-zero with the lines already on
stdout.)

Three limits are deliberate:

- **`owner` and `repo_name` only.** A `package_name`, `app_name`, `author`,
  `email`, or `layout` that disagrees with the source-config still exits `2`,
  whatever the answers file says and whatever flags were passed —
  `--accept-origin-mismatch` never covers a pyproject-derived field.
- **Per field, not whole-identity.** A cross-owner press relaxes `owner`
  alone if `repo_name` still matches the source-config; and if one field
  names the destination while the other names a third repository, the guard
  still exits `2` on the second (silently, as described above) unless
  `--accept-origin-mismatch` accepts it.
- **Exact comparison.** `github.com/PotatoLabs/potato-launcher` against an
  answers file saying `potatolabs` is a mismatch, not a match: the case
  difference trips the guard and exits `2`. Fix the answers file (or the
  remote) so the two agree exactly. Such a field is in the "neither" state,
  so `--accept-origin-mismatch` does accept it — as a warning and an
  `origin_mismatch_accepted` receipt entry, not as a destination match.

Without `--config` there is no destination identity to compare against, and
the guard behaves exactly as it did before; `--accept-origin-mismatch` is
inert on that path too — both relaxations require a destination to compare
against, so without one the guard's decision is never relaxed.

**Documented blind spot.** If the template repository was renamed upstream
(`demo-widget` → `demo-widget-2`) *without* a package rename, the target's
`press/press-source.toml` still carries the old `repo_name`, and `origin`
already points at the destination, then the stale `repo_name` is accepted
along with everything else — the guard cannot tell a stale source-config
from an ahead-of-time remote, because `origin` no longer describes the
template at all. This is accepted, not overlooked; the mitigation is the
plan-time [prefix-only occurrence warning](#prefix-only-occurrence-warning),
which flags a source value that appears in the target's content only as a
separator-joined prefix of a longer token and tells you to update
`press/press-source.toml`.

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
the exit code is unchanged. The prose form, like the JSON, is printed to
stdout — unlike every other exit-`2` refusal, it does not go to stderr
with the `error:` prefix that `_fail` puts there, so a check that greps
stderr for `error:` will not see it. The removal-coverage and prefix-only
warnings documented below print to stdout as well.

If the target tree changes between planning and apply — e.g. a new ignored
file appears under a prefix being renamed — the same check runs again as an
apply-time revalidation immediately before the first mutation. It prints the
same aggregated findings and remedy argv, but never as JSON (the plan has
already printed to stdout by then), and it exits `1` under the partial-
rewrite contract (target may be partially rewritten; restore with
`git -C <target> checkout . && git clean -fd`), not `2`.

### The ignore set

If a target legitimately keeps some source-identity content (vendored code,
historical docs), list a matching path-component name under `verify_ignore`
in `<target>/press/press-rules.toml` so the no-leak scan skips those entries.
To also stop them from being rewritten, list the same component names under
`extra_exclude_dirs`. Both keys match one file-or-directory component at any
depth, including an entry's basename; neither accepts a multi-component path.

A `foo/` line in `.gitignore` (the trailing slash) matches DIRECTORIES only —
it does not ignore a symlink or a regular file also named `foo`. `press
verify` and the post-apply doctor only ever see what
`git ls-files --exclude-standard` lists, so an untracked `foo` that is
anything other than a real directory (most commonly a symlink standing in for
a vendored directory, e.g. `node_modules` created by `bun install
--frozen-lockfile` — see the `press-target` skill's
troubleshooting notes) is enumerated and scanned like any other untracked
entry, and `git add -A` would commit it. When a finding lands on such an
entry, the report attaches a note identifying the exact `.gitignore` line and
naming the fix: drop the trailing slash, remove the entry, or list its name
under `verify_ignore`.

### Platform-conditional declared mutations

`[[edit]]`, `[[regenerate]]`, `[[remove]]`, and `[[reset]]` declarations may
include an optional `platforms` selector. The selector is a non-empty list
containing one or more of these exact Python runtime platform values:

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

The same file may appear in multiple declarations only when their platform
sets are disjoint. An active `[[edit]]` may not share its target with an active
`[[regenerate]]`, `[[remove]]`, or `[[reset]]`. If two declarations can write
the same file on the same platform, configuration loading fails with exit code
`2`.

A `[[regenerate]]` declaration names one output: the declared `file`, which
must already be excluded from the identity rewrite. The engine enforces that
much — and post-checks only that one file for leaked identity — but it does
not police what the declared command writes elsewhere; nothing stops a
command from touching other files. `[[regenerate]]` is still not a hook for
repo-wide tools: a declared command MUST NOT edit files other than its
declared output, and a whole-tree formatter cannot be declared this way. Run
the target's own formatter in the target after the press, before the first
commit.

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

### Declared in-place edits

An `[[edit]]` declaration amends an ordinary, git-tracked text file after the
identity rewrite, renames, and removals, but before any `[[regenerate]]`
command. This example changes the project version before rebuilding
`uv.lock`:

```toml
[[edit]]
file = "pyproject.toml"
command = ["uv", "version", "0.1.0", "--frozen"]
expect = 'version = "0.1.0"'

[[regenerate]]
file = "uv.lock"
command = ["uv", "lock"]
```

`file` uses source coordinates: if the rewrite renames one of its path
components, press translates the path to its final location before launching
the command. Normally, the target must not be listed in `exclude_files`
because it is rewritten before the edit. The only exception is an
exact-spelling, target-added exclusion required by a platform-disjoint
`[[reset]]` or `[[regenerate]]`; press removes that exclusion on platforms
where the edit is active. Default exclusions and alias-only spellings cannot
use this exception. Every edit target is scanned directly by its immediate and
final command postconditions. The edit earns no command-based hermetic
`press verify` exemption, so `[[edit]]` accepts neither `verify_exempt` nor a
relaxed `scan` mode. Later doctor and verify inventories still honor the
general `verify_ignore` policy: if it matches any component of the edit
target's path, they skip that entry.

An edit target must not match `exclude_dirs`, including default exclusions or
excluded components at any depth. Directory exclusions have no
platform-disjoint exception. A root or nested `.gitignore` also cannot be an
edit target: declared commands must preserve Git visibility inputs. Make
intentional ignore-policy changes in a separate commit. Both refusals occur
before any target mutation, including during dry-run.

`expect` is a required, non-empty printable string. The edited UTF-8 file must
contain it after the command and again after every declared command has run.
It detects many successful no-op or later-undo cases, but it does not prove
that this command introduced the string: choose a value that describes the
required final state.

Before writing anything, press requires every edit target to be contained by
the repository, git-tracked, clean, a regular file reached without following a
symbolic link, and backed by exactly one hard link. These checks still apply
with `--allow-dirty`. Immediately before each launch, press repeats the
containment, no-follow, regular-file, and single-link checks. After the command
exits `0`, the file must still exist as contained regular UTF-8 text, contain
`expect`, and pass the strict source-identity scan. A final pass repeats the
content checks after all edits and regenerations.

Edits share the declared-command contract with regenerations: an argv array,
no shell, the target repository as the working directory, a plan-time pinned
executable, and a deny-by-default environment. Optional `env` names explicitly
copy selected variables from the operator's environment. The plan shows the
argv, pinned executable, and whether each declared environment variable is
present.

When any edit or regeneration is active, press snapshots its control files and
Git visibility inputs before the first command and revalidates them after the
last. A command that changes the rules, source configuration, answers,
receipt, ignore inputs, repository-local Git configuration, or index
membership fails the press. These control files are
`press/press-rules.toml`, `press/press-source.toml`,
`press/press-answers.toml`, and `press/press-receipt.toml`. A successful
receipt records each edit in a `[[press.edit]]` table with its
source-coordinate `file`, pinned `argv`, and `expect`. Edits are not listed as
regenerated or exempt files.

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
appends a `removing N file(s) under <dir>/` summary line (singular for
`N == 1`) beneath the per-file lines — a quick count check, grouped by the
removal's declared SOURCE path, top-level directory only.

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
value is a deliberate, rewritable form, not a stale source config. A field
listed in `[rules] substring_rewrite_fields` is never checked: its
rewriter matches the value as a plain substring, so a glued occurrence
(`xdemo_widgety`) is a real whole occurrence to that rewriter but
invisible to this check's boundary-aware matcher, which would otherwise
misreport it as stale.

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
`press check-tools` reports. Plans and tool checks show active declarations
only. A successful receipt records the captured value as `press.platform`,
successful edit actions as `[[press.edit]]`, successful regeneration actions
as `[[press.regenerate]]`, and applied reset actions as `[[press.reset]]`.

Git is not a declared command. Press and `press check-tools` require and check
Git on every supported platform, including when no declared mutation is
active.

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
  in the report and in the `exempt` field of `--json` output. A declared edit
  receives no command-based exemption and is scanned normally unless the
  general `verify_ignore` policy matches a component of its path.
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

Reports whether every active `[[edit]]` and `[[regenerate]]` command's
`argv[0]` — plus `git`, the one tool press itself needs — resolves on the
captured platform, using exactly the resolution the press will use
(path-qualified names against the target root, bare names on the
deny-by-default effective `PATH`). It validates all declarations before
platform selection, writes nothing, and executes nothing. Edit tools appear
before regeneration tools, matching execution order.

```console
$ press check-tools --target ../my-repo
Platform: darwin
git — /usr/bin/git
uv — /opt/homebrew/bin/uv (edits pyproject.toml)
uv — /opt/homebrew/bin/uv (regenerates uv.lock)
bun — missing (declared to regenerate bun.lock)
```

| Code | Meaning |
|------|---------|
| `0` | Every tool resolved. |
| `1` | At least one tool is missing. |
| `2` | Configuration or usage error. |
