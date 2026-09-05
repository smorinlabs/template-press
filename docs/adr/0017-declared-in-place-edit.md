# 0017. Declared in-place edits run before regenerations

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Maintainers
- **Related:** [external-target model](../design/0006-external-target-model.md);
  [press improvements design](../superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E4 and §E11; [project P09](../../projects/P09-declared-in-place-edit.md)

## Context

Some target metadata must preserve the identity rewrite and then receive a
deterministic, non-identity change before a derived file is regenerated. The
first use is setting `pyproject.toml`'s project version before `uv lock`
rebuilds `uv.lock`.

`[[regenerate]]` cannot represent this operation. A regeneration output is
excluded from the rewrite and may be exempt from hermetic verification, while
`pyproject.toml` must be rewritten before the edit and cannot be treated as a
regenerated output. An unbounded hook would hide the mutation's target and
postcondition.

## Decision

Add a separate `[[edit]]` declaration with `file`, argv-style `command`, and a
required printable `expect` substring. Optional `env` and `platforms` use the
existing declared-command semantics.

Every active edit runs after the identity rewrite, renames, and removals, and
before every active regeneration. The edit target must be git-tracked, clean,
unexcluded, contained, a no-follow regular file, and single-linked. It uses the
same pinned executable, target-root working directory, no-shell execution,
deny-by-default environment, and command-phase snapshots as regeneration.

The edited result must contain `expect` and pass the strict source-identity
scan immediately after its command and after all declared commands finish.
The edit mechanism grants no command-based hermetic `press verify` exemption,
cannot declare `verify_exempt` or `scan`, and does not alter doctor inventory
policy. It receives its own `[[press.edit]]` receipt row. A target's
independent path-component `verify_ignore` policy remains unchanged and can
still exclude the edited path from later inventories.

## Consequences

- Targets can compose an identity rewrite, a declared metadata edit, and
  derived-file regeneration in a deterministic order.
- Plans, tool reports, receipts, and failures identify the edited file and
  exact command contract.
- A command can still write outside its declared target. Final control-file,
  Git-visibility, edit, reset, and regeneration checks therefore gate every
  command phase, but target authors remain responsible for declaring commands
  whose intended writes are appropriately narrow.
- `expect` proves a required final substring is present; it does not prove
  that the edit command introduced that substring.

## Alternatives considered

- **Reuse `[[regenerate]]`** — rejected because regeneration skips the
  identity rewrite and can leave its output outside hermetic verification.
- **Add an arbitrary lifecycle hook** — rejected because it would not declare
  one reviewable target and postcondition.
- **Treat project version as an identity field** — rejected because a release
  version is metadata, not part of the repository's identity.
