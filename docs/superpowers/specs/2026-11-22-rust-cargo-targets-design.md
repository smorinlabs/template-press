# Rust and Cargo targets: design

- **Status:** Approved by owner on 2026-11-22, then aligned with the TypeScript
  design and the explicit-language guard on the same date.
- **Created:** 2026-11-22
- **Branch:** `feat/rust-targets`
- **Project:** P15
- **Depends on, in merge order:** `fix/hyphen-false-receipt` (P13),
  `feat/explicit-target-languages` (P16), `feat/typescript-targets` (P14). This
  branch rebases on each before its dependent task starts.
- **Applies to:** `src/template_press/rebrand/` (`discovery.py`, `identity.py`,
  `config.py`, `pathing.py`, `substitutions.py`, `synthesize.py`,
  `verify_config.py`, `verifier.py`, `verify_cli.py`, `receipt.py`, `cli.py`)

## Intent

Rust repositories, both single-crate and Cargo workspaces, should be first-class
`press` targets with the same guarantees Python targets have.

Today a press can report success on a broken Cargo repository. For a crate named
`acme-widget` with a different `repo_name`, `press rebrand` exited 0, printed
`verified: no identity leftovers`, and wrote a receipt. `Cargo.toml` still said
`acme-widget`, `src/main.rs` imported `zeta_gadget`, and `cargo check` failed.
The value `package_name = "acme_widget"` does not match the hyphenated spelling
in either the rewrite or the inline leak check.

## Goals

1. Represent every Cargo package, library, and binary name exactly.
2. Rewrite both spellings of each name: `acme-core` and `acme_core`.
3. Rename crate directories and keep workspace members and path dependencies valid.
4. Cross-check declared names against the Cargo manifests.
5. Preserve locked dependency versions when `Cargo.lock` is regenerated.
6. Prove single-crate and workspace targets with press, `cargo check`,
   `cargo test`, and `press verify`.

## Non-goals

- Publishing to crates.io or PyPI.
- TypeScript, Bun, or BAML support. Parallel branches own them.
- The Python hyphenated-name false receipt. Branch `fix/hyphen-false-receipt`
  owns it. This branch leaves Python outcomes unchanged.

## Anti-goals

The work fails, even if Rust presses succeed, if any of these happens:

- An existing target or source or answers file changes outcome because of this
  branch. The language guard owns its own approved breaking change.
- A pure Cargo target receives a receipt while a declared crate name survives.
- A press silently moves a locked third-party dependency version.
- The package gains a runtime dependency.
- `verifier.py` derives its matches from the substitution table.

## Approaches considered

| Approach | Effect | Decision |
|---|---|---|
| A. Derive a hyphen form of `package_name` | No new config, but crates not named after `package_name` still leak | Rejected |
| B. One `crate_name` plus TypeScript's `cli_name` | Matches the TypeScript shape, but cannot describe a workspace | Rejected |
| C. Role-keyed crate-name map | Handles workspaces exactly, with more plumbing | **Chosen by owner, 2026-11-22** |

## Design

### Identity table

Add an optional table to the source and answers files. Keys are stable roles
that pair FROM and TO values. Values are exact Cargo names.

```toml
# press/press-source.toml
[identity.cargo_names]
core = "acme-core"
widget = "acme-widget"

# press-answers.toml
[answers.cargo_names]
core = "zeta-core"
widget = "zeta-gadget"
```

- One entry covers every use of one name. A package and a binary with the same
  name share one role. A binary or `[lib] name` with a different name gets its
  own role.
- Role keys match `^[a-z][a-z0-9_]*$`. Values match `^[A-Za-z][A-Za-z0-9_-]*$`.
- `Identity` stores the table as an immutable sorted tuple of `(role, name)`
  pairs. It stays out of `as_dict()`, whose values are all strings.
- `render_source_config` writes the table, so the refreshed source config can
  describe the target for the next press.

These conditions exit 2 before any write:

- The table is declared on only one side, or the role sets differ.
- Two roles on one side have the same underscore-normalized name.
- A destination name equals a different role's source name in either spelling.
  Sequential rewrites could otherwise chain.
- `package_name` is not the underscore form of a source map value, or its
  destination is not the underscore form of the same role's destination.

The six required identity fields stay required for Cargo targets:

- `package_name` names the primary crate. In a virtual workspace, the author
  chooses one member as primary, so the rule above can always be satisfied.
- `app_name` keeps its validator and env-prefix meaning. It does not need to
  match a Cargo name. A library-only crate proposes `app_name = package_name`.
- `repo_name`, `owner`, `author`, and `email` keep their current meanings.

### Rewrite

Each role produces up to two rows: the exact name and its underscore form. Both
rewrite content and path components.

The match boundary is `(?<![A-Za-z0-9_-])` and `(?![A-Za-z0-9_-])`. So
`acme-core/serde`, `dep:acme-core`, and `acme_core::hi` match, while the
third-party name `acme-core-extra` does not.

Cargo map rows join TypeScript's `npm_name` and `cli_name` rows in one exact-name
tier. That tier runs before all other identity rows, longest source first. This
order is required: the existing `app_name` boundary treats `_` as a right-hand
separator, so `acme` would otherwise rewrite the front of `acme_core`.

Path handling reuses TypeScript's `field_renames_paths`. An independent sibling
such as `acme-core-extra` is not rewritten, and it fails verification by default.
A target that really depends on it declares it in TypeScript's `keep_names`:

```toml
[rules]
keep_names = ["acme-core-extra"]
```

```diff
-members = ["crates/acme-core", "crates/acme-widget"]
+members = ["crates/zeta-core", "crates/zeta-gadget"]
-acme-core = { path = "../acme-core" }
+zeta-core = { path = "../zeta-core" }
-println!("{}", acme_core::hi());
+println!("{}", zeta_core::hi());
```

A renamed dependency keeps its local alias. In
`core = { package = "acme-core", path = "../acme-core" }`, only the package and
path values change.

### Discovery

**Language selection.** The explicit-language guard owns this decision. Press
exits 2 before any write when a target has more than one root manifest that
declares a project identity and no `[rules] languages` declaration. This branch
adds no precedence between languages.

- Rust is active when `Cargo.toml` is the only counted manifest, or when the
  target's declaration includes Rust. The exact declaration value comes from the
  guard branch.
- A target that declares other languages but not Rust ignores `Cargo.toml`.
- A declared multi-language target checks each language against its own manifest.
  For example, `cargo_names` is checked against Cargo and `npm_name` against
  `package.json`. This covers PyO3, maturin, Tauri, and napi-rs repositories.
- `Discovered.source_kind` gains `"cargo"`. The Python `src/<package>` layout check
  applies only to Python discovery.

A root `Cargo.toml` counts when it has `[package]` or `[workspace]`. Nested
manifests are read only as workspace members. A repository whose only manifest is
in a subdirectory is not detected and keeps today's behavior. A root manifest with
both tables contributes the root package plus its members.

**Cargo names read:**

| Source | Names |
|---|---|
| `[package] name` | package |
| `[lib] name` | library |
| `[[bin]] name` | binary |
| `src/main.rs` | package name, unless `autobins = false` |
| `src/bin/*.rs`, `src/bin/*/main.rs` | file or directory stem, unless `autobins = false` |

- Workspace members come from root `[workspace] members`, with glob expansion,
  minus `exclude`. A member outside the target root exits 2.
- `authors.workspace = true` and `repository.workspace = true` resolve through
  `[workspace.package]`.
- Authors parse as `Name <email>`. The first entry is the discovered author.
- `package.repository` supplies `owner` and `repo_name` only when git origin is
  unavailable.
- A malformed or symlinked manifest is undiscoverable and produces a warning when
  no map is declared. When `cargo_names` is declared it exits 2, because the map
  cannot be checked.
- `[[example]]`, `[[test]]`, `[[bench]]`, and feature names are not cross-checked.
  The content rewrite still updates any declared crate name inside them.

**With a source config.** Every discovered Cargo name must be a source map value,
or the press exits 2. A declared map value that no manifest contains also exits 2.

**Third-party name collision.** The press exits 2 when a dependency table entry
resolves to a declared source name but is not a local crate. A local crate uses
`path` or `workspace = true`. The check covers `dependencies`, `dev-dependencies`,
`build-dependencies`, their `target.*` forms, and `[workspace.dependencies]`, and
it honors the `package` key. Rewriting such an entry would point it at a different
registry crate.

**Rust active without a map.** Existing configs keep working unless the press
would leave a broken identity behind:

| Discovered Cargo name | Result |
|---|---|
| Contains a changing identity value, and no identity row rewrites the whole name | Exit 2 with a paste-ready `cargo_names` table |
| Equals a changing identity value that a row rewrites whole | Continue |
| Unrelated to the identity, or listed in `keep_names` | Warning on stderr, then continue |

```text
Crate acme-widget, repo acme-widget   continues
Crate acme-widget, repo acme-repo     exit 2
Crate tools-helper, unrelated name    warning
```

**Without a source config.** The current pending-config flow proposes the table,
using each name's underscore form as its role. A single crate proposes
`package_name` from its package and `app_name` from its first binary's underscore
form. A virtual workspace has no primary crate, so it exits 2 and asks for a
source config.

### Lockfile

The target declares regeneration. Press adds no hidden command.

```toml
[rules]
extra_exclude_files = ["Cargo.lock"]

[[regenerate]]
file = "Cargo.lock"
command = ["cargo", "update", "--workspace", "--offline"]
```

- `Cargo.lock` joins `REGENERATE_EXEMPTIBLE`. An exemption still requires a
  declared `[[regenerate]]`.
- `Cargo.lock` does **not** join the default `exclude_files`, because that would
  change existing Python targets that contain one.
- A target with `cargo_names` and a tracked `Cargo.lock` but no declared
  regeneration exits 2 and prints the block above through TypeScript's
  `regenerate_suggestion`.
- Probe result: `cargo update --workspace --offline` kept a vendored dependency
  at 1.0.0, while `cargo generate-lockfile --offline` moved it to 1.1.0.
- The real press still runs its post-command scan on the regenerated lockfile.
- `Cargo.lock` is excluded from the text rewrite. The existing regeneration phase
  runs after rewrites and renames, so Cargo reads the renamed manifests and
  updates the workspace entries itself.
- A failed regeneration keeps the existing contract: exit 1, no receipt, and no
  automatic rollback. The operator restores the target from git.

**Known limitation.** The command environment passes `HOME` but not `CARGO_HOME`.
A machine with a custom Cargo home, or without cached dependencies, needs the
dependencies vendored or cached in the default location.

### Verify and synthesis

- `verifier.py` derives its Cargo hunt values directly from `Identity`: each exact
  source name and its underscore form, using `matcher.find_occurrences`.
- `synthesize_dest` creates a synthetic destination per role. It preserves hyphen
  positions and contains no source token.
- A name without a hyphen or underscore difference yields one row and one hunt,
  because the two spellings are deduplicated.
- The receipt records the destination table as an optional key. A receipt without
  that key stays valid.

### Compatibility

New behavior is reached only by declaring `cargo_names`, or when Rust is active
and a press would otherwise leave a broken crate name. Regression tests cover a
six-field config, a `display_name` config, a Cargo target whose crate equals
`repo_name`, and a declared Python target that excludes Rust.

## Verification

- Unit tests: validators, half-specified tables, collisions, chains, boundaries,
  row order, manifest forms, workspace inheritance, precedence, and synthesis.
- Committed synthetic single-crate and workspace fixtures using `example.test`.
  Each runs press, `cargo check --locked --offline`, `cargo test --offline`, and
  `press verify`.
- Fixtures use only the Rust standard library and path dependencies, so they need
  no registry or vendored crates. A separate unit test uses a local directory
  source to prove locked-version preservation.
- Cargo is a test prerequisite, not an eleventh tool in the shared provisioning
  set. Locally, real-Cargo tests skip with a clear reason when `cargo` is missing.
  When `CI` is set, a missing `cargo` fails the run. The acceptance tests use the
  `slow` marker and run through `scripts/rebrand_matrix.sh`, whose workflow
  provisions Cargo.
- `just check` and `just matrix` must pass.

## Left to the builder

- Helper names and module placement for Cargo manifest parsing.
- Exact error wording, within the requirements above.
