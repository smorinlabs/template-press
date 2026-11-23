# TypeScript and Bun targets: design

- **Status:** Implemented on `feat/typescript-targets`; behavior below matches the code
- **Created:** 2026-11-22
- **Branch:** `feat/typescript-targets`
- **Applies to:** `src/template_press/rebrand/` (`discovery.py`, `identity.py`,
  `config.py`, `pathing.py`, `rules.py`, `substitutions.py`, `engine.py`,
  `synthesize.py`, `verifier.py`, `verify_cli.py`, `cli.py`)

## Intent

TypeScript repositories using npm or Bun should be first-class `press` targets,
with the same rebrand and verification guarantees Python targets have.

Today a TypeScript repository can be pressed only with a hand-written source
config. Discovery ignores `package.json`, and identity validation cannot
represent a scoped npm name or a hyphenated CLI name. `press verify` also fails
on a correctly declared npm target because the regenerated `package-lock.json`
is not eligible for the verifier exemption.

## Goals

1. Discover TypeScript identity from `package.json`.
2. Represent exact npm package and CLI names, including scopes and hyphens.
3. Make declared `package-lock.json`, `bun.lock`, and `pnpm-lock.yaml`
   regeneration pass `press verify`.
4. Prove npm and Bun targets end to end with committed synthetic fixtures.

## Non-goals

- Monorepo or workspace-member identity. Only the root `package.json` is read.
- Choosing or running a package manager without a target declaration.
- Rust or other ecosystems.
- Provisioning, publishing, or Cloudflare resources.

## Anti-goals

The work fails, even if TypeScript presses succeed, if any of these happens:

- An existing Python target or existing source or answers file changes outcome,
  other than through the owner-approved language guard.
- A press writes a receipt while a source identity leak remains.
- The package gains a runtime dependency.
- `verifier.py` starts deriving its matches from the substitution table.

## Approaches considered

| Approach | Effect | Decision |
|---|---|---|
| A. Discovery only | Small, but cannot represent scoped or independent hyphenated names | Rejected |
| B. Optional `npm_name` and `cli_name` fields | Exact rewrites, existing configs unchanged, more field plumbing | **Chosen by owner, 2026-11-22** |
| C. Relax `package_name` and `app_name` for TypeScript | No new fields, but `/` reaches path logic and `app_name` can yield an invalid env prefix | Rejected |

The owner also chose to add npm and pnpm lockfiles to the exemption list instead
of requiring `verify_exempt = true` in every npm target.

## Design

### Identity fields

Add two optional fields to `OPTIONAL_FIELDS`. Absent means the feature is off.

```toml
[identity]
package_name = "acme_widget"
repo_name    = "acme-widget"
app_name     = "acme"
author       = "Example Author"
email        = "author@example.test"
owner        = "example-org"
npm_name     = "@acme/widget-api"
cli_name     = "acme-cli"
```

| Field | Meaning | Validation |
|---|---|---|
| `npm_name` | Exact root `package.json` `name` | At most 214 characters, matching `^(?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$` |
| `cli_name` | Exact `package.json` `bin` key | Matches `^[a-z0-9][a-z0-9._-]*$`, and is not a dot segment |

`package_name` and `app_name` keep their current validators.

A field declared on only one side, source or answers, exits 2 before any write.

If a source new field equals another source identity value, the destination must
preserve that equality or the press exits 2. For example, `npm_name` equal to
`repo_name` in the source requires the same equality in the answers.

### Rewrite and verify behavior

- `cli_name` and an unscoped `npm_name` join the rename, symlink-target, and
  doctor path surfaces. Without this, `"bin": {"acme-cli": "./bin/acme-cli.js"}`
  would be rewritten in content while `bin/acme-cli.js` kept its old name.
- A scoped `npm_name` stays content-only because it contains `/` and cannot be
  one path component.
- Their rewrite pattern is the exact value with
  `(?<![A-Za-z0-9_-])` on the left and `(?![A-Za-z0-9_-])` on the right.
  `@acme/widget/sub` rewrites its package prefix. `@acme/widget-extra` is not
  rewritten by the `npm_name` row.
- A same-prefix sibling such as `@acme/widget-extra` fails loudly by default.
  A sibling preflight runs before any rewrite in `press rebrand` and
  `press verify`: it exits 1 with no writes and no receipt and names each
  token with the `keep_names` line that would keep it, unless the target has
  declared it. See "Sibling preflight" below.
- These rows run before the shorter identity rows, so `owner` or `repo_name`
  cannot rewrite part of a scoped name first.
- `synthesize_dest` preserves shape. A scoped source yields a synthetic scoped
  destination, and an unscoped source yields an unscoped destination.
- `verifier.py` adds both fields to its independently derived scan fields and
  uses `matcher.find_occurrences`, as it does for other identity values.

### Explicit keep-list (`keep_names`)

Owner decision, 2026-11-22: a same-prefix name fails loudly by default, and a
template author can declare that the name is independent of the template's
identity and must survive a press.

```toml
# press/press-rules.toml
[rules]
keep_names = ["@acme/widget-extra"]
```

- **Matching:** each entry is an exact, case-sensitive name. It uses the same
  boundaries as `npm_name`, so `@acme/widget-extra/sub` is kept and
  `@acme/widget-extra-2` is not.
- **End-to-end effect:** a kept occurrence is unchanged by every rewrite row,
  including `owner`, `repo_name`, substring-mode, and `[[replace]]` rows. The
  doctor, reset scan, regeneration scan, and `press verify` all ignore identity
  matches wholly inside it. This covers content, path, and symlink-target
  surfaces. A later command must never refuse a name this list accepted.
- **Verifier independence:** `verifier.py` reads `keep_names` from `Rules` and
  subtracts kept spans itself. It does not obtain them from the substitution
  table.
- **Safety limits:** an entry equal to a source or destination identity value,
  or to a rendered `display_name` form, exits 2 before any write. Equality is
  tested after case-folding and removing `-`, `_`, `.`, and spaces, so case and
  separator variants are refused. An entry that starts or ends with `-` or `_`
  (for example `--acme-cli`) is compared exactly, so it may be kept. Empty
  entries, control characters, and non-string entries also exit 2. A match that merely
  overlaps a kept span, without lying wholly inside it, is still a leak.
- **Visibility:** the dry-run plan and the receipt list the kept names. An entry
  with no occurrence produces a non-fatal stale-entry warning on stderr.
- **Repeat presses:** entries are literal and are not rewritten, so the list stays
  valid after `press-source.toml` is refreshed.
- **Failure guidance:** a leak inside a longer same-prefix token names that token
  and shows the `keep_names` line that would keep it, if it is truly independent.

### Sibling preflight

Before any rewrite, `press rebrand` and `press verify` scan the rewrite surface
(content, paths, and symlink targets) for a token that joins a source
`npm_name` or `cli_name` to another name part. A token is a sibling unless one
`keep_names` entry wholly covers it. A finding exits 1, writes nothing, and
writes no receipt.

- **Multi-part values** (`acme-cli`, `@acme/widget`): any name character touching
  either side makes a sibling, for example `acme-cli2`, `xacme-cli`, and
  `acme-cli-helper`.
- **Single-token values** (`tsc`, `serve`): both sides must be real boundaries
  or joins, and at least one side must be a `-` or `_` join or a camelCase
  tail. `tsconfig`, `server`, and `web-server` are allowed. `tsc-helper` and
  `tscConfig` are refused.
- **Exempt:** a token that an applicable rewrite row or `[[replace]]` rule
  rewrites on that exact path and surface, and files planned for `[[remove]]`.
- **Outside the preflight:** non-UTF-8 files are not scanned by the preflight or
  the inline doctor; only `press verify` scans them.

### Discovery

**Manifest selection.** Owner decision, 2026-11-22: this design no longer gives
`pyproject.toml` precedence. When a target has more than one root manifest
declaring a project identity, `press` exits 2 before any write unless
`[rules] languages` in `press/press-rules.toml` declares which languages apply.
The supported values are `python` and `node`; `rust` is reserved. Discovery and
cross-checks in `press rebrand` and `press verify` follow that declaration. The
approved breaking change includes Python repositories with a named tooling
`package.json`. A `pyproject.toml` without `[project]` does not count as an
identity manifest.

**Fields read from `package.json`:**

| Manifest key | Forms | Used for |
|---|---|---|
| `name` | string | `npm_name`, and `package_name` from the unscoped part with `-` normalized to `_` |
| `author` | `Name <email> (url)` or `{name, email}` | `author`, `email` |
| `bin` | string or object | CLI names; a string uses the unscoped package name and has no key of its own, so it never proposes `cli_name` |
| `repository` | string or `{url}` | `owner` and `repo_name` only when git origin is unavailable |

Absent or malformed values are undiscoverable. They are never guessed.

**With a source config (cross-check).** Existing configs must not start failing:

- A declared `npm_name` must equal the manifest `name`, or the press exits 2.
- A declared `cli_name` must be a `bin` key, or the press exits 2.
- Those are the only fatal manifest checks. Every other manifest disagreement
  (`author`, `email`, derived `package_name`, `bin` versus `app_name`, and
  `repository` versus origin) is a non-fatal warning on stderr, whether or not a
  new field is declared. JSON-only stdout contracts stay intact.
- The Python `src/<package>` layout check applies only to `pyproject.toml`
  discovery.

**Without a source config (proposal).** The current flow still writes a pending
source config when every required field resolves:

- `npm_name` is proposed only when the manifest name differs from both proposed
  `repo_name` and `package_name`.
- `app_name` comes from the first `bin` key when it is a valid identifier.
- A hyphenated first object-form `bin` key sets `cli_name` and normalizes `-` to
  `_` for `app_name`.
- Several object-form `bin` keys that no other proposed value covers exit 2 and
  require a hand-written source config that lists each independent CLI in
  `keep_names`.
- Missing `author`, `email`, or `bin` keeps the current exit 2 and names the
  manifest keys to add or the source config to write.

### Lockfiles

- `REGENERATE_EXEMPTIBLE` becomes `uv.lock`, `bun.lock`, `package-lock.json`, and
  `pnpm-lock.yaml`. An exemption still requires a declared `[[regenerate]]`.
  The press only suggests commands and never runs an undeclared one.
- The default `exclude_files` does not gain `pnpm-lock.yaml`. Adding it would make
  existing pnpm targets fail the excluded-file preflight. A pnpm target adds it
  through `extra_exclude_files` and declares regeneration.
- When the preflight refuses an undeclared `bun.lock`, `package-lock.json`, or
  an opted-in `pnpm-lock.yaml`, the error prints a paste-ready `[[regenerate]]`
  block with `scan = "boundary"`. The press does not run it.

| Lockfile | Suggested command |
|---|---|
| `package-lock.json` | `npm install --package-lock-only --silent` |
| `bun.lock` | `sh -c 'command -v bun >/dev/null 2>&1 \|\| exit 127; rm -f bun.lock && exec bun install --lockfile-only'` |
| `pnpm-lock.yaml` | `pnpm install --lockfile-only` |

The Bun command deletes and rebuilds the lock, because Bun keeps a stale
workspace name in an existing lock. The `command -v` guard leaves the lock
intact when `bun` is missing. The block is POSIX-only; Windows targets declare
their own command.

The real press still runs the post-command scan on each regenerated lockfile.

### Known limits

- Keeping an unscoped npm basename while changing `package_name` exits 1.
- A scope-preserving press with a changed `owner` can exit 2 at press time while
  `press verify` exits 0.
- Non-UTF-8 files are outside the sibling preflight and the inline doctor and
  are scanned only by `press verify`.
- Workspace-member identity is out of scope.

### Compatibility

Apart from the owner-approved language guard, the new behavior is reached only by
a Node target, by declaring a new field, or by declaring a lockfile regeneration.
Regression tests must cover an existing six-field config and an existing
`display_name` config. Coverage for a Python target with a tooling `package.json`
follows the guard's final behavior after the rebase.

## Verification

- Unit tests: validators, manifest forms, precedence, cross-checks, proposals,
  matching boundaries, row order, synthesis, and half-specified fields.
- `keep_names` tests: an undeclared sibling fails with exit 1 and no receipt. A
  declared sibling survives rewrite, doctor, lockfile regeneration, receipt, and
  `press verify`. A near-miss name such as `@acme/widget-extra-2` still fails.
- Synthetic npm and Bun fixtures using `example.test` values and one pinned
  registry dev dependency, `typescript`. A zero-dependency fixture cannot work:
  `bun install --lockfile-only` 1.3.14 deletes the empty `bun.lock`. Each fixture
  runs press, the real lockfile command, its test and typecheck commands, and
  `press verify`.
- These fixture tests need network access and use the `live` marker. Unit tests
  stay offline. The CI job that runs them provisions Node and Bun, and Node does
  not join the repository's declared 10-tool developer toolchain.
- A pnpm fixture runs the same flow when `pnpm` is available.
- `just check` and `just matrix` must pass.
- Before pushing, the owner-provided private acceptance target is pressed in a
  scratch copy and checked with `npm ci`, `npm test`, `npm run typecheck`, and
  `npx wrangler deploy --dry-run`. Its identity must not appear in this repository.

## Left to the builder

- Internal helper names and module placement for manifest parsing.
- Exact warning and error wording, within the requirements above.
- How CI enforces that the npm and Bun fixtures never skip silently.
