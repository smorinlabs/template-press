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

1. Preconditions: target is a git repo with a clean tree, and
   `press check-tools --target <TARGET>` exits 0 — every declared
   `[[regenerate]]` command (plus `git`) resolves before anything runs.
   - If `press check-tools --target <TARGET>` printed a `git — … (cleans …)`
     row, a `[[clean]]` rule is active on this platform: preview it before
     the dry run with `press clean --target <TARGET> --show`, confirm the
     listing holds nothing to keep, then run `press clean --target <TARGET>`.
     Skip this when no such row appears (no rule, or a rule scoped to another
     platform; `press clean` would exit 2 with `no [[clean]] rules declared`).
     The dry run's closure refusal names `press clean` if it is needed.
2. Preview (never skip): if the target ships a
   `press/press-answers.example.toml` template, copy it first and fill in
   the destination identity:
   `cp <TARGET>/press/press-answers.example.toml press-answers.toml`
   Then run the dry run:
   `press rebrand --target <TARGET> --config <press-answers.toml> --dry-run`
   (in a dev checkout of template-press: `uv run press rebrand …`)
3. If the target has no `press/press-source.toml`, review the discovery proposal
   printed by the dry run; re-run with `--accept-discovery` only after the
   user confirms the identity is right.
4. Apply: same command without `--dry-run`.
5. Interpret exit codes: 0 = verified + receipt written; 1 = NO receipt.
   A pre-write preflight refusal (`nothing written, no receipt`) needs no
   cleanup. A post-write failure (`rebrand is INCOMPLETE`) left the target
   rewritten, so restore it first: run `git -C <TARGET> checkout .`, preview
   untracked removals with `git -C <TARGET> clean -nd`, then run
   `git -C <TARGET> clean -fd`. Then fix the root cause,
   or — for surviving identity that is VALID to keep, e.g. vendored code or
   historical docs — add its directory NAME to both `extra_exclude_dirs`
   (skips rewriting) and `verify_ignore` (skips the leak scan) in
   `press/press-rules.toml`, and press again from a clean tree; a `[symlink]`
   leak needs the link's OWN name in `verify_ignore` too, not just its
   target's directory — see the symlink gotcha below; do NOT re-run
   with `--force` as the remedy); 2 = precondition/mismatch (report, do not
   retry blindly). A refusal saying the target has several language manifests
   and `[rules] languages` is not declared is fixed by adding that key to
   `press/press-rules.toml` (see "`languages`" under Rules authoring), then
   re-running the dry run.
6. On success the press also refreshes `<TARGET>/press/press-source.toml` to the
   NEW identity (so a future re-press starts from a valid baseline). Show
   the receipt (`<TARGET>/press/press-receipt.toml`) and remind the user to
   review `git -C <TARGET> status` — the receipt and a first-run
   source-config are new/untracked files that `diff --stat` won't show —
   then run the target's own formatter before committing; identity values
   change length so wrapped lines can exceed the target's line-length limit
   and fail its own pre-commit; then commit in the target.

## Answers file shape

```toml
[answers]
package_name = "new_pkg"
repo_name = "new-repo"
app_name = "newcli"
author = "Jane Dev"
email = "jane@example.com"
owner = "janedev"
# display_name = "New CLI"   # optional; see Identity fields below
# npm_name = "@jane/new-widget"   # optional; exact package.json name
# cli_name = "new-cli"            # optional; exact package.json bin key
```

## Identity fields

`press/press-source.toml`'s `[identity]` table and `press-answers.toml`'s
`[answers]` table share one field set — six required, three optional:

| Field | Required | Notes |
|---|---|---|
| `package_name` | yes | lowercase Python identifier / import name |
| `repo_name` | yes | lowercase, letter-led, alphanumeric + hyphens (GitHub repo slug) |
| `app_name` | yes | lowercase Python identifier — becomes the CLI command and file/env prefixes |
| `author` | yes | free-form |
| `email` | yes | `local@domain.tld` |
| `owner` | yes | GitHub owner/org (1-39 chars, alphanumeric + hyphens, must start AND end with an alphanumeric — no leading/trailing hyphen) |
| `display_name` | no | humanized product name, e.g. `"Py Launch Blueprint"`; absent = feature off |
| `npm_name` | no | exact root `package.json` `name`; a scope is allowed (`@acme/widget`); at most 214 characters; absent = feature off |
| `cli_name` | no | exact `package.json` `bin` key, e.g. `acme-cli` (lowercase letters, digits, `.`, `_`, `-`); absent = feature off |

`app_name_upper` (uppercased `app_name`) is derived, not settable, but is a
valid `{app_name_upper}` placeholder in `[[replace]]` patterns (below).
Declaring `display_name`, `npm_name`, or `cli_name` on only one side —
source declares it, answers doesn't, or vice versa — is a precondition
failure (exit 2); declare each on both or neither. When declared,
`display_name` is rewritten as a CLOSED set of exact
forms (spaced / PascalCase / camelCase), each replaced with the
same-shaped form of the new name; narrow the set with
`[rules] display_forms` in `press/press-rules.toml` (default: all three). See
[design 0008](../../../docs/design/0008-identity-variants-and-replace-rules.md)
for the full semantics.

This built-in rewrite is CONTENT ONLY — display forms never rewrite path
components or symlink target text, even though the leak scan still checks
those surfaces for an enabled form. A display-form occurrence living in a
path or a symlink target survives the press unrewritten and then trips
exit 1 as a leak. Cover such an occurrence with an explicit `[[replace]]`
rule (`paths = true`) instead.

If a source name's forms coincide (e.g. `"NumPy"`: spaced and PascalCase
are both literally `NumPy`), the engine cannot rewrite each occurrence to a
DIFFERENT same-shaped destination form — it deterministically keeps the
first enabled form (per `[rules] display_forms` order, spaced by default)
and applies that same destination text everywhere the shared source
literal occurs. A destination `"Acme Widget"` therefore replaces every
`NumPy` occurrence with `Acme Widget` — not `AcmeWidget` for the would-be
PascalCase spots.

## Node and Bun targets (npm, Bun, pnpm)

An npm or Bun repository is a first-class target. Only the root
`package.json` is read; workspace-member identity is out of scope.

### `npm_name` and `cli_name`

- `npm_name` is the exact root `package.json` `name`, scoped names included
  (`@acme/widget`). `cli_name` is the exact `bin` key (`acme-cli`).
- Both are rewritten as exact values. A leading or trailing name character
  (`[A-Za-z0-9_-]`) stops a match, so `@acme/widget/sub` is rewritten and
  `@acme/widget-extra` is not (see "Sibling preflight").
- `cli_name` and an UNSCOPED `npm_name` also rename file and directory paths
  (a `bin/acme-cli.js` file follows the `bin` key). A SCOPED `npm_name`
  contains `/`, so it rewrites content only; a path component left holding the
  scoped name is a leak (exit 1).
- If a source `npm_name` or `cli_name` equals another source identity value
  (for example `npm_name` equal to `repo_name`), the answers must keep the
  same equality, or the press exits 2.
- A synthetic `press verify` destination keeps shape: a scoped source gets a
  scoped destination.

### Discovery from `package.json`

Keys read: `name`, `author` (string `Name <email> (url)` or object
`{name, email}`), `bin` (string or object), and `repository` (string or
`{url}`, used for `owner` and `repo_name` only when git `origin` is
unavailable). Absent or malformed keys are undiscoverable and never guessed.
A string-form `bin` has no key of its own: its command is the unscoped
package name.

- With a source config, only two checks are fatal (exit 2): a declared
  `npm_name` must equal the manifest `name`, and a declared `cli_name` must be
  a `bin` key. Every other disagreement (`author`, `email`, derived
  `package_name`, `bin` versus `app_name`, `repository` versus `origin`)
  prints a `warning:` on stderr and does not fail.
- With no source config and no `--accept-discovery`, any run (dry or not)
  prints a proposed source config and exits 2. A first object-form `bin` key
  containing `-` proposes `cli_name` and a `_` form for `app_name`. A
  string-form `bin` has no key, so it never proposes `cli_name`.
  When object-form `bin` declares several commands that no other proposed
  value covers, the press exits 2 and asks for a hand-written source config
  listing each independent CLI in `[rules] keep_names`.

### `keep_names` — names that are independent of the template

```toml
# press/press-rules.toml
[rules]
keep_names = ["@acme/widget-extra"]
```

Use it for a name that merely starts with the source `npm_name` or
`cli_name` but is a different thing (a sibling package, another CLI). Each
entry is an exact, case-sensitive name matched with the `npm_name`
boundaries, so `@acme/widget-extra/sub` is kept and `@acme/widget-extra-2` is
not. A kept occurrence is unchanged by every rewrite row (including `owner`,
`repo_name`, substring mode, and `[[replace]]`), and the doctor, the
reset and regeneration scans, and `press verify` all ignore identity matches
wholly inside it. A match that only overlaps a kept span is still a leak.

- Entries equal to a source or destination identity value exit 2. That
  includes case and separator variants (`Acme_CLI` for `acme-cli`) and
  rendered `display_name` forms.
  Leading and trailing characters outside `[A-Za-z0-9@/_-]` are ignored
  first, then edge `/` and `@`, keeping the `@` of a scoped name. So
  `"acme-cli"`, `/acme-cli`, and `@acme` (for `owner = "acme"`) also exit 2.
  An entry with an edge `-` or `_` is compared exactly, so `--acme-cli`
  (a flag spelling) may be kept.
- Empty, control-character, and non-string entries exit 2.
- An entry that occurs nowhere on the rewrite surface prints a stale-entry
  warning on stderr. The dry-run plan and the receipt list the kept names.

### Sibling preflight

Before any rewrite, `press rebrand` and `press verify` scan the target for a
token that joins a source `npm_name` or `cli_name` to another name part and is
not declared in `keep_names`. A finding exits 1 with nothing written and no
receipt, and prints each token with the `keep_names` line that would keep it.

- Multi-part values (`acme-cli`, `@acme/widget`): any name character touching
  either side is a sibling (`acme-cli2`, `xacme-cli`, `acme-cli-helper`).
- Single-token values (`tsc`, `serve`): an alphanumeric character glued to
  either side means an unrelated word, so `tsconfig`, `server`, `web-server`,
  and `observe-mode` are allowed. Otherwise a directly touching `-` or `_` or a
  camelCase tail is a sibling, so `tsc-helper`, `tscConfig`, `--tsc`, `_tsc_`,
  `_tsc`, and `tsc_` are refused.
- Scoped basenames: an unscoped value that is the basename of another package
  (`@vendor/tsc`) is a sibling, on content and path surfaces.
- Exempt: a token that an applicable rewrite row or `[[replace]]` rule
  rewrites on that exact path and surface, and any file planned for
  `[[remove]]`.

### Lockfiles

`press` never chooses or runs a lockfile command. Declare it with
`[[regenerate]]`; a declared `package-lock.json`, `bun.lock`, `uv.lock`, or
`pnpm-lock.yaml` is exempt from the hermetic `press verify` scan (the real
press still scans the regenerated file after the command). When the
preflight refuses an undeclared `bun.lock`, `package-lock.json`, or
`pnpm-lock.yaml`, it prints a paste-ready block:

```toml
# package-lock.json
[[regenerate]]
file = "package-lock.json"
command = ["npm", "install", "--package-lock-only", "--silent"]
scan = "boundary"

# bun.lock (POSIX-only; Windows targets declare their own command)
[[regenerate]]
file = "bun.lock"
command = ["sh", "-c", "command -v bun >/dev/null 2>&1 || exit 127; rm -f bun.lock && exec bun install --lockfile-only"]
scan = "boundary"

# pnpm-lock.yaml
[[regenerate]]
file = "pnpm-lock.yaml"
command = ["pnpm", "install", "--lockfile-only"]
scan = "boundary"
```

- `pnpm-lock.yaml` is not in the default excluded files; a pnpm target must
  also list it in `[rules] extra_exclude_files`.
- The Bun command deletes `bun.lock` and rebuilds it, because Bun keeps a
  stale workspace name in an existing lock. The guard keeps the lock intact
  when `bun` is missing. It needs a POSIX `sh`.
- Nested lockfile paths get no suggestion.

### Known limits

- When `package_name` changes: a six-field config whose `package.json` name
  equals the hyphen form exits 1. A scoped `npm_name` whose basename stays that
  hyphen form exits 1 from `press rebrand` after rewriting, while `press verify`
  exits 0. A declared unscoped `npm_name` left unchanged exits 0 legitimately.
  `keep_names = ["<that hyphen form>"]` exits 2.
- A scope-preserving press with a changed `owner` can exit 2 at press time
  while `press verify` exits 0.
- Non-UTF-8 files are outside the sibling preflight and the inline doctor;
  only `press verify` scans them.
- Workspace-member identity is out of scope.

## Rules authoring (`press/press-rules.toml`)

### `[[replace]]` — exact glued-token rules

The primary mechanism for tokens the boundary-safe default pass can't
reach on its own (e.g. a glued `PLBPOwned` or `x{app_name}owned`):

```toml
[[replace]]
pattern = "x{app_name}owned"
files = ["docs/*/data.txt"]   # fnmatch globs; omit for unscoped (all files)
paths = true                   # also match path components + symlink text (default false)
content = true                 # match file content (default true)
reason = "glued token in generated fixtures"
```

- `pattern` (required): a template string with `{field}` placeholders,
  rendered once against the SOURCE identity (the literal to find) and once
  against the DESTINATION identity (the literal to write) — exact
  replacement, no fuzzy matching. Must reference at least one placeholder;
  valid placeholders are the six required fields above, plus
  `app_name_upper`, `display_name`, `npm_name`, and `cli_name`.
- `reason` (required): free-form; documents intent.
- `files` (default: unscoped — all files): fnmatch globs (see the gotcha
  below).
- `paths` (default `false`): also scope path components and symlink text,
  not just content. For symlinks specifically, only CONTAINED relative
  targets are actually retargeted — an absolute symlink or one whose
  target resolves outside the repo (`../`-escaping) is left untouched
  regardless of this rule, and its source literal survives as a leak.
- `content` (default `true`): scope file content. UTF-8 TEXT ONLY — a
  tracked file that fails UTF-8 decoding is silently excluded from BOTH
  the rewrite pass and the leak scan, so a source literal inside a binary
  survives unrewritten and unflagged; a clean receipt does not mean binary
  artifacts are clean. Regenerate, remove, or otherwise exempt them
  deliberately rather than relying on `content = true`.

### `substring_rewrite_fields` — boundary-free opt-in

```toml
[rules]
substring_rewrite_fields = ["app_name", "app_name_upper"]
```

A per-field opt-in that switches a field to plain substring replacement,
instead of the boundary-guarded default. It always applies to content.
It ALSO reaches path components, but only for the four fields the engine
renames paths on at all — `package_name`, `repo_name`, `app_name`, and
`app_name_upper` — never for `author`, `email`, or `owner`: those never
appear in path components regardless of this setting, so opting one of
them in only changes its content matching. To rewrite one of them inside
a path anyway, declare an explicit `[[replace]]` rule with `paths = true`.
Gated on the target author declaring the token word-disjoint — never a
default. Fields are independent: opting in `app_name` alone does not cover
glued UPPERCASE forms (`PLBPOwned`); pair it with `app_name_upper` when
those exist. `display_name` itself may not appear here (it fails
validation as a no-op) — narrow which of its three forms rewrite via
`[rules] display_forms` instead.

### `languages` — declare multi-language targets

```toml
[rules]
languages = ["python"]
```

A target with several root manifests that each declare a package identity
makes `press rebrand` and `press verify` exit 2 (nothing written) until
`[rules] languages` is declared. Counted manifests: `pyproject.toml` with
`[project]` (python); `Cargo.toml` with `[package]` or `[workspace]` (rust);
`package.json` with a non-empty string `name` (node). A `[tool.*]`-only
`pyproject.toml` does not count; a tooling `package.json` with a `name` does.

- One detected language needs no declaration.
- Listed languages are checked; detected languages not listed are ignored
  and printed to stderr. Discovery and cross-checks in `press rebrand` and
  `press verify` follow this declaration: `["python"]` does not read
  `package.json`.
- This press version supports `python` and `node`. `rust` is a reserved name,
  so listing it exits 2 with "not supported by this press version".
- Each listed language's manifest is cross-checked against the source config:
  `["python"]` leaves `package.json` unchecked, `["node"]` does not check
  `pyproject.toml`, and `["python", "node"]` checks both.
- Declaring a language with no such manifest, or whose manifest is a
  `[[remove]]` target, exits 2. A malformed, non-UTF-8, or non-regular root
  manifest also exits 2.
- Breaking change for existing multi-language targets: add
  `languages = ["python"]`, `["node"]`, or `["python", "node"]` under
  `[rules]`.

### Gotcha: `files` glob semantics

`files` globs use Python `fnmatch` against the FULL POSIX relative path:
`*` crosses `/`, so `*.txt` matches nested files too, not just files
directly under a scoped directory. Scope by explicit path prefixes or
exact paths when directory-level scoping matters.

### Gotcha: symlink `verify_ignore` needs the link's own name

A `[symlink]` leak is keyed on the LINK'S OWN NAME, not its target's
directory. If a symlink points INTO a directory you've excluded via
`extra_exclude_dirs` + `verify_ignore`, that exclusion covers the
directory's contents but not the link itself — you must ALSO add the
link's own name to `verify_ignore`, or the post-apply doctor pass
(and `press verify`) will report exit 1 on that link indefinitely, even
though the directory it points into is correctly excluded.

`verify_ignore` matches by PATH COMPONENT, anywhere in the tree — not by
the link's full path. Adding a common basename (e.g. `current`) excludes
EVERY entry in the repo that has that name as any path component, not
just your one symlink; a real, unrelated leak sharing that component name
would then pass silently. Use a name specific enough to be unique across
the whole tree, not just locally unique next to the link.

### Gotcha: a `paths = true` rule's `files` scope matches a symlink's TARGET, not its own path

For a symlink specifically, the doctor's leak scan matches a rule's
`files` glob against the link's TARGET path, not the repository path of
the link itself. A rule scoped `files = ["links/**"]` intended to cover
every symlink stored under `links/` will not match a link under `links/`
whose target points somewhere else (e.g. `../vendor/data`) — the rule's
literal can survive there unflagged. Scope symlink-covering rules by
where their targets point, not by where the links themselves live.

### Gotcha: `node_modules/` in `.gitignore` does not ignore a symlinked `node_modules`

A `foo/` line in `.gitignore` (the trailing slash) matches DIRECTORIES
only, per `gitignore(5)`. A worktree tool that links a shared package
cache in as `node_modules -> /path/to/real/node_modules` replaces the
real directory with a symlink — which the `node_modules/` pattern no
longer matches. That symlink is now untracked-and-not-ignored, so
`press verify` enumerates and scans it like any other entry, and
`git add -A` would commit it; the post-apply doctor applies its own
built-in exclusions (`DEFAULT_RULES.exclude_dirs` includes
`node_modules`), so it never enumerates the symlink in the first place.
`press verify`'s report attaches a note identifying exactly this
near-miss when it fires. Three fixes, in order of preference:

1. **Best** — run `bun install --frozen-lockfile` (or your package
   manager's equivalent real-install) inside the worktree instead of
   symlinking a shared `node_modules` in; no symlink, no near-miss.
2. Write `node_modules` in `.gitignore` WITHOUT the trailing slash — this
   also matches a symlink of that name.
3. List `node_modules` under `verify_ignore` in
   `<target>/press/press-rules.toml`.
