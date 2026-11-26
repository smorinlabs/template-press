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

# [answers.cargo_names]           # optional; see "Rust and Cargo targets"
# core = "new-core"
```

## Identity fields

`press/press-source.toml`'s `[identity]` table and `press-answers.toml`'s
`[answers]` table share one field set — six required, four optional:

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
| `cargo_names` | no | table of role to exact Cargo package, library, or binary name; see "Rust and Cargo targets"; absent = feature off |

`app_name_upper` (uppercased `app_name`) is derived, not settable, but is a
valid `{app_name_upper}` placeholder in `[[replace]]` patterns (below).
Declaring `display_name`, `npm_name`, `cli_name`, or `cargo_names` on only one side —
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
  (a flag spelling) may be kept. An entry holding a complete source
  `npm_name` or `cli_name` (`widget-extra@acme/widget`) exits 2; rename it.
  A `.` or `~` continuation (`acme-cli.extra`) is a different name and may
  be kept.
- Empty, control-character, and non-string entries exit 2.
- An entry that occurs nowhere on the rewrite surface prints a stale-entry
  warning on stderr. The dry-run plan and the receipt list the kept names.

### Sibling and glued-name preflight

Before any rewrite, `press rebrand` and `press verify` scan the target for a
token that joins a source `npm_name` or `cli_name` to another name part and is
not declared in `keep_names`. In addition, `press rebrand` scans every identity
field that `press verify` checks (including derived `display_name` forms) for
glued occurrences across all target languages. A finding exits 1 with nothing
written and no receipt, and prints each token with the rewrite rule
(`substring_rewrite_fields` / `[[replace]]`) or keep rule (`keep_names` /
`[[verify.ignore]]`) that resolves it.

- Multi-part values (`acme-cli`, `@acme/widget`): any name character touching
  either side is a sibling (`acme-cli2`, `xacme-cli`, `acme-cli-helper`).
- Single-token values (`tsc`, `serve`): an alphanumeric character glued to
  either side means an unrelated word, so `tsconfig`, `server`, `web-server`,
  and `observe-mode` are allowed. Otherwise a directly touching `-` or `_` or a
  camelCase tail is a sibling, so `tsc-helper`, `tscConfig`, `--tsc`, `_tsc_`,
  `_tsc`, and `tsc_` are refused.
- Scoped basenames: an unscoped value that is the basename of another package
  (`@vendor/tsc`) is a sibling, on content and path surfaces.
- Dependency keys: a root `package.json` dependency that extends a declared
  name with `.` or `~` (`tsc.extra`) is a sibling. Without such a key,
  `tsc.js` stays rewritable.
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

## Rust and Cargo targets

A single-crate repository or a Cargo workspace is a first-class target. A root
`Cargo.toml` counts when it has `[package]` or `[workspace]`. Workspace members
come from root `[workspace] members`, with globs expanded and `exclude` removed.
A repository whose only manifest is in a subdirectory is not detected.

### `cargo_names`

`cargo_names` maps a stable role to one exact Cargo name. Declare the same roles
on both sides:

```toml
# press/press-source.toml
[identity.cargo_names]
core = "acme-core"
engine = "acme_engine"  # a [lib] name that differs from its package
widget = "acme-widget"

# press-answers.toml
[answers.cargo_names]
core = "zeta-core"
engine = "zeta_engine"
widget = "zeta-gadget"
```

- One role covers every use of one name. A package and a binary with the same
  name share a role. A `[lib]` or `[[bin]]` with a different name gets its own.
- Role keys match `^[a-z][a-z0-9_]*$`. Values start with a letter or underscore, use letters, digits, `_`, and `-`, and
  contain at least one letter or digit (`^(?=.*[A-Za-z0-9])[A-Za-z_][A-Za-z0-9_-]*$`).
  A maturin library name such as `_acme_widget` is a valid value. A proposed
  role key drops leading underscores.
- `package_name` must be the underscore form of one source value, and its
  destination must be the underscore form of the same role's destination. In a
  virtual workspace, choose one member as the primary crate.
- Each role rewrites both spellings, `acme-core` and `acme_core`, in content and
  in paths. Crate directories, `members`, and path dependencies follow.
- A renamed dependency keeps its local alias. In
  `core = { package = "acme-core", path = "../acme-core" }`, only the `package`
  and `path` values change.
- Every Cargo name found in the manifests must be a source value, and every
  source value must be found in a manifest. Otherwise the press exits 2.
- `[[replace]]` patterns may reference `cargo_names` roles with
  `{cargo_exact_<role>}`, `{cargo_ident_<role>}`, and `{cargo_ident_<role>_upper}`
  (see the `[[replace]]` section). `[[clean]]` paths may not. A role name may
  not end in `_upper`.
- Without a source config, the press proposes the table. A virtual workspace has
  no primary crate, so it exits 2 and asks for a source config.
- A proposed role key is the old name's underscore form. It stays unchanged
  after a press, by design, because a role is a stable key and not a name.
- `env!("CARGO_BIN_EXE_<name>")` follows a changed name. It cannot be listed in
  `keep_names`.
- An uppercase crate whose underscore form equals a separated `app_name_upper`
  (crate `ACME-TOOL` with `app_name = "acme_tool"`) presses but cannot be
  verified: `press verify` exits 2.

### Language declaration

A target whose only identity manifest is `Cargo.toml` needs no declaration. A
target that also has an identity-bearing `pyproject.toml` or `package.json` must
declare `[rules] languages`:

```toml
# press/press-rules.toml
[rules]
languages = ["python", "rust"]  # PyO3 or maturin: check both manifests
# languages = ["python"]        # Cargo.toml is tooling only: skip Cargo checks
```

The tooling-only choice skips Cargo identity checks, but a malformed root
`Cargo.toml` still exits 2.

### `keep_names` for sibling crates

An independent crate whose name extends a declared name, such as
`acme-core-extra`, is not rewritten. The sibling preflight exits 1 with nothing
written until the name is declared:

```toml
[rules]
keep_names = ["acme-core-extra"]
```

Comparison against identity values ignores case and `-`, `_`, `.`, and space, so
`Acme_Widget` cannot keep crate `acme-widget`.

### `Cargo.lock`

`press` adds no hidden command. A target with `cargo_names` and a tracked
`Cargo.lock` must declare regeneration, or the press exits 2 and prints this
block:

```toml
[rules]
extra_exclude_files = ["Cargo.lock"]

[[regenerate]]
file = "Cargo.lock"
command = ["cargo", "update", "--workspace", "--offline"]
```

- The command renames the workspace entries and keeps locked third-party
  versions. `cargo generate-lockfile` would move them, so do not substitute it.
- A staged `Cargo.lock` counts as tracked, as does a force-added ignored one.
- `press verify` lists `Cargo.lock` as exempt. The real press scans the
  regenerated file after the command.
- A failed regeneration exits 1 with no receipt and no automatic rollback.
  Restore the target from git.
- **`CARGO_HOME` limitation:** the command environment passes `HOME` but not
  `CARGO_HOME`. A machine with a custom Cargo home, or without cached
  dependencies, needs the dependencies vendored or cached in the default
  location.

### `[[cargo_split]]`: rename `acme` to `zeta-gadget` in one press

`[[cargo_split]]` is experimental: its spelling proofs may miss Rust shapes
that real targets use. If it writes a receipt and `cargo test` then fails,
that is a bug to report.

A hyphen-free crate name such as `acme` spells its package and its Rust
identifier identically. By default, a hyphenated destination is refused with
exit 2, because text alone cannot choose a spelling. Opt in per role:

```toml
# press-answers.toml
[answers.cargo_names]
core = "zeta-gadget"

# press/press-rules.toml
[[cargo_split]]
role = "core"
package_files = ["README.md", "scripts/release.sh"]  # fnmatch globs: zeta-gadget
identifier_files = ["docs/api.md"]                   # fnmatch globs: zeta_gadget
```

| Where `acme` appears | Result |
|---|---|
| Any `Cargo.toml`: package name, dependency keys, `package =` | `zeta-gadget` |
| Rust code in any `.rs` file, such as `acme::hi()` or `mod acme;` | `zeta_gadget` |
| A `.rs` string Cargo proves, in code or in doc-comment text that rustdoc may compile: `feature = "acme"` inside `cfg(`, `cfg!(` or `cfg_attr(`; an `include_str!`/`include_bytes!`/`include!`/`#[path]` path to a file the press renames; or `"acme"` as the other side of an `==`, `!=`, `assert_eq!` or `assert_ne!` comparison with `env!("CARGO_PKG_NAME")`, when both operands are bare (`"acme" == env!("CARGO_PKG_NAME").replace('-', "_")` and `"acme".to_string()` are not, and exit 2) | `zeta-gadget` (the path follows the rename) |
| Any other `.rs` string literal, such as `println!("acme")` or `#[command(name = "acme")]`, in code or in doc-comment text that rustdoc may compile | exit 2 before any write, with `file:line` |
| A name in the arguments of a direct `stringify!` or `concat!` call, which turns it into text, in code or in doc-comment text that rustdoc may compile (there the arguments run to the end of the item's doc text when the press cannot find where the call ends; a call that another macro makes is not seen) | exit 2 before any write, with `file:line` |
| A character literal of the name in `.rs` code, such as `'x'` for a crate `x` (a lifetime `'x` takes `'zeta_gadget`) | exit 2 before any write, with `file:line` |
| A rename of `stringify!` or `concat!` anywhere in a `.rs` file, such as `use core::stringify as s;` or `use core::{stringify as s};`, because a call through the new name, in that file or another, is not seen | exit 2 before any write, with `file:line` of the rename |
| Doc-comment text that rustdoc never compiles: prose and non-Rust fences in a `///` comment (see **Doc comments** below) | `zeta_gadget`, inside double quotes too |
| `env!("CARGO_BIN_EXE_acme")` | `CARGO_BIN_EXE_zeta-gadget` |
| Paths, such as `crates/acme` | `crates/zeta-gadget`; declared manifest paths follow |
| A file matched by `package_files` or `identifier_files` | that spelling |
| Any other file | exit 2 before any write, listing each `file:line` |

- The `Cargo.toml` and `.rs` rule outranks the globs. A file that matches both
  lists exits 2.
- Every key is optional except `role`. Both lists default to empty. Unknown
  keys, a repeated `role`, and a glob in both lists are refused when the rules
  load.
- The role must exist in both `cargo_names` tables. The source must have no
  hyphen and the destination must have one; otherwise the block exits 2 as
  unnecessary.
- **Doc comments.** rustdoc compiles the code blocks of a doc comment as
  doctests: fenced blocks, and blocks indented by four spaces. The press does
  not parse Markdown. It reads doc-comment text as Rust code under the string
  rules above, unless it can prove that rustdoc compiles nothing there.
  - **Read as prose** (the name takes `zeta_gadget`, even inside double
    quotes), only in a run of `///` comments that starts an item's
    documentation. The code before the run must end with `;`, `}`, `{`, `,`
    or `(`, or the run must start the file. Attributes without `doc =`, such
    as `#[derive(Debug)]`, may stand before or inside the run. In such a run:
    - a line outside every fence that holds no tab and no run of four spaces;
    - a fence that starts at the comment's left margin and whose tags are all
      non-Rust language names: `text`, `txt`, `plain`, `plaintext`, `console`,
      `sh`, `shell`, `bash`, `toml`, `json`, `yaml`, `yml`, `ini`, `xml`,
      `html`, `css`, `sql`, `diff`, `c`, `cpp`, `python`, `javascript`,
      `typescript`, `markdown`, `md`, `makefile`, `dockerfile`, `asm`,
      `notrust` (`NOT_RUST_TAGS` in `src/template_press/rebrand/rust_text.py`);
    - a fence at the left margin with the tag `ignore` and no
      `ignore-<target>` tag.
  - **Read as code** (a string the press cannot prove exits 2):
    - every `//!`, `/** */` and `/*! */` comment, because rustdoc joins it to
      doc text the press may not see;
    - a run of `///` comments beside a `#[doc = ...]` attribute, one that does
      not start an item's documentation, one that holds a tab, or one that
      indents every line by more than three spaces;
    - a doc comment inside a macro call or a `macro_rules!` definition,
      because the macro may add doc text, such as a fence line, around it;
    - a line that holds a run of four spaces, which Markdown can read as an
      indented code block;
    - a fence with any other tag, including an unknown tag and a misspelt one
      such as `should-panic` or `Rust`;
    - after a line that starts with `<` (a possible HTML block), or after a
      fence that is not at the left margin (it may sit in a list or a block
      quote): all text that follows any later fence line, whatever its tag.
  - A code block may start at more than one line when the press cannot prove
    the Markdown structure. The press reads the text from each such line, and
    writes a spelling only when every reading agrees. A reading that ends
    inside a string or a comment is ignored, because that doctest cannot
    compile.
  - **Doc text the press cannot read.** A `#[doc = ...]` attribute adds doc
    text. The press reads its value only when it is a plain string with no
    quote, no backslash, and no `/*` or `*/`, such as
    `#[cfg_attr(feature = "std", doc = "```")]`. Any other value may leave a
    string or a comment open: `#[doc = include_str!("intro.md")]`,
    `#[doc = concat!(...)]`, `#[doc = "let s = \"x\";"]`. The same holds for
    an outer doc comment that ends inside a string or a block comment. What
    follows such text is read like this:
    - **In a `///` comment:** nothing is read. Every occurrence of the name
      below the attribute exits 2, in code position too, because the string
      may close only in doc text further on. Remedy: move the attribute below
      the doc comments.
    - **In a `//!` comment**, which ends the item's doc text: the press also
      reads the comment as the rest of a string, a raw string, or a block
      comment. Such a reading counts only if the comment closes it and is back
      in code at the end of some line. Where it counts and disagrees with the
      plain reading, the occurrence exits 2. So an inner doc comment below
      `#![doc = include_str!("../README.md")]` presses, unless a later line
      can close such a string: a line with an odd number of double quotes (a
      string literal that spans lines has two of them), or the `"#` end of a
      raw string. Then the names above that line exit 2.
    - A `mod name;` declaration exits 2 at the declaration when its doc
      comment ends inside a string or a block comment, or when it has such an
      attribute, because rustdoc joins the doc comment of the module's own
      file to that text. Remedy: move the attribute into the module's file,
      below its doc comment.
  - **Remedy for a doc-comment refusal:** name the crate in backticks, not in
    double quotes, or edit the line by hand before pressing.
  - **Limits.** The press reads the doc comments and `doc` attributes in each
    file. It does not see doc text that a macro produces: if a macro puts part
    of a string or a comment in front of a doc comment it is given, the press
    reads that comment wrongly. An `ignore` fence is prose to the press, so
    `cargo test -- --ignored` can fail on it after a press.
  - **Limits: code that names no crate token.** The press cannot see code
    that expects the crate name and the package name to be equal without
    spelling either one: `module_path!()`, `core::any::type_name::<T>()`, or
    `env!("CARGO_CRATE_NAME")` compared with `env!("CARGO_PKG_NAME")`. After a
    split press those differ (`zeta_gadget` and `zeta-gadget`), so such a test
    fails although the press wrote a receipt. The same holds for a target's
    own macro that forwards its arguments to `stringify!` or `concat!`: the
    press sees only direct calls.
- **A file with both spellings**, such as a README holding `cargo run -p acme`
  and `acme::hi()`, works only for the `package_name` crate. If Rust reads
  the README with `include_str!`, see **A file that rustdoc compiles** below
  instead. List the file in
  `package_files`, and add an exact rule for the identifier spans:

  ```toml
  [[replace]]
  pattern = "{package_name}::hi"
  files = ["README.md"]
  reason = "the README names the crate both ways"
  ```

  A `package_files` file is refused, with `file:line`, when its rewrite
  would put `zeta-gadget` where only a Rust identifier fits: `zeta-gadget::`,
  `extern crate`, `use`, or a log filter such as `RUST_LOG=acme=debug` or
  `acme=info` (`env_logger` matches the module path `zeta_gadget`). The two
  remedies are to list the file in `identifier_files`, or to cover the span with
  an exact `[[replace]]`. For any role, use `{cargo_ident_<role>}` in the
  pattern, for example `extern crate {cargo_ident_core};` or
  `{cargo_ident_core}::`, scoped with `files`.
- **A file that rustdoc compiles**, such as a README that a `.rs` file reads
  with `include_str!` (`#![doc = include_str!("../README.md")]`), is Rust in
  every code block rustdoc may compile: every fence except `ignore` and the
  non-Rust tags listed under **Doc comments**, and every line holding a tab or
  four spaces in a row. After a fence that is not at the left margin (in a
  block quote or a list item) or a line that starts with `<`, every line after
  a later fence line counts as code. In `package_files`, any `zeta-gadget` the press would
  write on such a line, or at an identifier position, exits 2 with
  `file:line`, because no `[[replace]]` rule can cover every position there
  (`use acme::{acme, hi};` and `acme!()` each need `zeta_gadget`). The remedy
  is to list the file in `identifier_files` and cover each span that needs the
  package spelling with an exact rule:

  ```toml
  [[cargo_split]]
  role = "core"
  identifier_files = ["README.md"]

  [[replace]]
  pattern = "cargo add {cargo_exact_core}"
  files = ["README.md"]
  reason = "install line"
  ```

  Limits: the press finds such a file only through a plain string argument,
  `include_str!("../README.md")`, not through
  `include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/README.md"))`. It does
  not read a doc-included file as Rust, so under `identifier_files` a string
  literal inside one of its code blocks takes `zeta_gadget` without the `.rs`
  string rules.
- Also refused before any write: an explicit `[lib] name = "acme"` (Cargo
  refuses a hyphen in a library name), a renamed path below `src/` other than
  `src/bin/<name>`, a renamed `acme.rs` or `acme/` anywhere when some `.rs`
  file declares `mod acme;` (for example `tests/acme/mod.rs`), and a target
  that also checks `python` or `node`. Target files such as `tests/acme.rs` and
  `examples/acme.rs` rename to `zeta-gadget.rs`, which Cargo accepts.
- **After the press**, leave the block in place. The receipt and the rewritten
  `press-source.toml` record `zeta-gadget`, so the next press uses the normal
  two-spelling rows. When a receipt exists and the source already has a
  hyphen, the press prints `warning: [[cargo_split]] role 'core' is inert` and
  continues. Remove the block when convenient. `press verify` ignores it.

### Deliberate refusals

These stop the press before any write:

| Situation | Example | Exit |
|---|---|---|
| Destination extends a source name | `acme-core` to `acme-core-next` | 2 |
| Destination contains another field's source spelling | `zeta-acme` when `app_name = "acme"` | 2 |
| A crate's Rust identifier would be left behind | crate `acme-widget`, no table, `repo_name` changes | 2 |
| A hyphenated crate is declared only by its underscore form, so its package name would stay behind | role `widget = "acme_widget"` for package `acme-widget` | 2 |
| A destination crate name is a Rust keyword | `acme-core` to `type` | 2 |
| A hyphen-free source name takes a hyphenated destination, without `[[cargo_split]]` | `acme_core` to `zeta-core` | 2 |
| A source or destination name equals a non-local dependency | crate pressed to `padkit` beside `padkit = "1"` | 2 |
| A rewrite would separate a declared or name-inferred Cargo path from its file (`cargo paths:`) | `owner = "acme"` rewrites `[lib] path = "lib/acme-x.rs"`, but no row renames the file | 2 |
| A rewrite would separate a path that Rust source declares from its file (`cargo paths:`): the file of `mod name;`, a `#[path = "..."]` or `#[cfg_attr(<cond>, path = "...")]` value, or an `include_str!`/`include_bytes!`/`include!` argument | `owner = "acmelabs"` rewrites `pub mod acmelabs;` or `include_str!("../data/acmelabs.txt")`, but no row renames the file | 2 |
| A `#[cfg(...)]`-disabled `mod name;` with no file on disk, inside a renamed inline module or as the renamed module itself | `mod acmelabs { #[cfg(any())] mod x; }` or `#[cfg(any())] mod acmelabs;` with `owner = "acmelabs"` | 2 |
| A `CARGO_BIN_EXE_<name>` token would not match its auto-discovered binary (`cargo paths:`) | `src/bin/acme.rs` renames to `zeta.rs`, but the token in an excluded file stays | 2 |
| Versioned string that extends a declared name | `acme-core-0.1.0` in a README | 1 |

For the first two, press in two steps through an intermediate identity. For a
versioned string, edit the text or add the exact token to `keep_names`. For a
`cargo paths:` refusal, rename the path so a path row moves it, or add the shared
name to `keep_names`. For a binary token, declare a `cargo_names` table that
names the binary; when the token sits in an excluded file, remove the
exclusion or edit the token by hand.

Limits: the press checks only paths that a manifest declares or Cargo infers,
and paths that Rust source declares with a plain string literal in a `.rs`
file Cargo compiles. Such a file is a crate root or target file that Cargo
infers or a manifest declares (`src/lib.rs`, `src/main.rs`, `src/bin/`,
`tests/`, `benches/`, `examples/`, a target `path`, `build.rs`), or a file one
of those reaches through `mod` (including inline `mod name { ... }` blocks and
their `#[path]` attributes), `#[path]`, `#[cfg_attr(<cond>, path = "...")]`, or
`include!`. Under `autotests = false`
or another `auto*` flag set to false, Cargo builds only the targets the
manifest names in that directory, so only those files are read. Dependency
paths are read from every dependency table, including the pre-2024
`[dev_dependencies]` and `[build_dependencies]` spellings. These are not checked:

- a path built by a macro, such as
  `include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/x"))`;
- a `.rs` file excluded from rewriting;
- a `.rs` file no crate root reaches, such as `tests/fixtures/sample.rs`,
  which Cargo does not compile;
- a path that code reads at run time, such as
  `std::fs::read_to_string("data/acmelabs.txt")` in `build.rs`;
- with `autobins = false`, a file already named for the destination binary:
  renaming `acme-cli` to `zeta-cli` while `src/bin/zeta-cli/main.rs` already exists leaves both `src/bin/zeta-cli.rs` and `src/bin/zeta-cli/main.rs`, so `cargo check` fails after a receipt.
- a `#[path]` value that uses `..`, inside an inline module that a rename changes, such as `pub mod acmelabs { #[path = "../shared.rs"] pub mod x; }` when `acmelabs` is renamed to `zetalabs`: Rust then looks for `src/zetalabs/../shared.rs`, which needs a `src/zetalabs/` directory, so `cargo check` can fail after a receipt. `main` behaves the same way.

An `owner`, `author`, or `email` row that rewrites such a path without
renaming its file can give a receipt for a build that then fails.

## BAML targets

BAML repositories keep their generated `baml_client/` out of text rewriting and
rebuild it with `[[regenerate]] dir` after `.baml` sources and host code have
been pressed.

1. Run `press verify --target <TARGET>` before the first press to find any
   glued names in `.baml` or host files (for example `AcmeWidgetClient` when
   `display_name = "Acme Widget"`).
2. Add `[rules]` and `[[regenerate]] dir` to `press/press-rules.toml`:

```toml
[rules]
languages = ["python"]
substring_rewrite_fields = ["display_name_pascal"]

[[regenerate]]
dir = "src/{package_name}/baml_client"
command = ["uv", "run", "--offline", "baml-cli", "generate"]
verify_exempt = true
reason = "BAML client, rebuilt from baml_src"
```

- For a TypeScript host, use `languages = ["node"]` (only if multi-manifest),
  `dir = "baml_client"` (or `"src/baml_client"`), and
  `command = ["npx", "baml-cli", "generate"]`. Never list `"baml"` in
  `[rules] languages`.
- `{package_name}` in `[[regenerate]] dir` renders against the source identity
  before the press and the destination identity after renames, so repeat
  presses work without editing `press/press-rules.toml`.
- A tracked `baml_client/inlinedbaml.py` or `baml_client/inlinedbaml.ts` at any
  depth with no covering `[[regenerate]]` or `[[remove]]` exits 2 before any
  write and prints a paste-ready `[[regenerate]] dir` block.
- For a gitignored client inside the package, add
  `[[clean]] paths = ["src/{package_name}/baml_client"]` and run `press clean`
  before `press rebrand`; `[[regenerate]] dir` rebuilds the client at the new
  package path.

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
  `app_name_upper`, `display_name`, `npm_name`, and `cli_name`. A Cargo
  target adds three role placeholders, valid only in `[[replace]]` patterns.
  For role `core` with name `acme-core`: `{cargo_exact_core}` renders
  `acme-core`, `{cargo_ident_core}` renders `acme_core`, and
  `{cargo_ident_core_upper}` renders `ACME_CORE`. There is no
  `{cargo_exact_<role>_upper}`. An identity without the role exits 2 before any
  write.
  `{cargo_exact_<role>}` never fits a Rust identifier position: for a
  `[[cargo_split]]` role, the press refuses it (exit 2, before any write) when
  the rule applies to a `.rs` file. Use `{cargo_ident_<role>}` there.
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
those exist. `display_name` itself (and `display_name_camel`/`display_name_spaced`) may not
appear here — opt in `"display_name_pascal"` when glued PascalCase occurrences
like `AcmeWidgetClient` must rewrite, or narrow which forms rewrite via
`[rules] display_forms`.

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
- This press version supports `python`, `node`, and `rust`.
- Each listed language's manifest is cross-checked against the source config:
  `["python"]` leaves `package.json` and `Cargo.toml` unchecked, `["node"]` does
  not check `pyproject.toml`, and `["python", "rust"]` checks both of its
  manifests.
- Declaring a language with no such manifest, or whose manifest is a
  `[[remove]]` target, exits 2. A malformed, non-UTF-8, or non-regular root
  manifest also exits 2.
- Breaking change for existing multi-language targets: add
  `languages = ["python"]`, `["node"]`, `["rust"]`, or a combination such as
  `["python", "node"]` under `[rules]`.

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
