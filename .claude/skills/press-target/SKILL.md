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
5. Interpret exit codes: 0 = verified + receipt written; 1 = leaks found,
   NO receipt (the target is already rewritten — restore it first:
   `git -C <TARGET> checkout . && git clean -fd`; then fix the root cause,
   or — for surviving identity that is VALID to keep, e.g. vendored code or
   historical docs — add its directory NAME to both `extra_exclude_dirs`
   (skips rewriting) and `verify_ignore` (skips the leak scan) in
   `press/press-rules.toml`, and press again from a clean tree; a `[symlink]`
   leak needs the link's OWN name in `verify_ignore` too, not just its
   target's directory — see the symlink gotcha below; do NOT re-run
   with `--force` as the remedy); 2 = precondition/mismatch (report, do not
   retry blindly).
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
# display_name = "New CLI"   # optional 7th field; see Identity fields below
```

## Identity fields

`press/press-source.toml`'s `[identity]` table and `press-answers.toml`'s
`[answers]` table share one field set — six required, one optional:

| Field | Required | Notes |
|---|---|---|
| `package_name` | yes | lowercase Python identifier / import name |
| `repo_name` | yes | lowercase, letter-led, alphanumeric + hyphens (GitHub repo slug) |
| `app_name` | yes | lowercase Python identifier — becomes the CLI command and file/env prefixes |
| `author` | yes | free-form |
| `email` | yes | `local@domain.tld` |
| `owner` | yes | GitHub owner/org (1-39 chars, alphanumeric + hyphens, must start AND end with an alphanumeric — no leading/trailing hyphen) |
| `display_name` | no | humanized product name, e.g. `"Py Launch Blueprint"`; absent = feature off |

`app_name_upper` (uppercased `app_name`) is derived, not settable, but is a
valid `{app_name_upper}` placeholder in `[[replace]]` patterns (below).
Declaring `display_name` on only one side — source declares it, answers
doesn't, or vice versa — is a precondition failure (exit 2); declare it on
both or neither. When declared, it is rewritten as a CLOSED set of exact
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
  `app_name_upper` and `display_name`.
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
