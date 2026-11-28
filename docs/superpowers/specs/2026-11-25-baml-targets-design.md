# BAML targets: design

Status: approved by the owner on 2026-11-25 (design and scope (i)). Builds on
`main` at `04769b2`, after P13, P14, P15, P16, and P17 merged.

## Intent

Make repositories that use [BAML](https://docs.boundaryml.com) first-class
`template-press` targets. A BAML repository keeps `.baml` sources (usually in
`baml_src/`) and a client that `baml-cli generate` writes in Python or
TypeScript (usually a `baml_client/` directory). Pressing such a repository must
rename identity in the sources and handwritten code, rebuild the client from
the renamed sources, and never write a receipt while an old name survives.

The work also closes a general false receipt: an old identity glued into a
longer name, such as `AcmeWidgetConfig` for a `display_name` of `Acme Widget`,
survives a press today with exit 0 and a receipt, in any target language.

## Evidence

Measured on `main` `04769b2` with `baml-cli` 0.226.3 and synthetic
`example.test` fixtures. Identity `acme_widget` / `Acme Widget` is pressed to
`zeta_tool` / `Zeta Tool`.

| Target content | Press today | `press verify` afterward |
|---|---|---|
| Neutral BAML names, Python or TypeScript client, one-file `[[regenerate]]` | 0, receipt | 0 |
| `client<llm> AcmeWidgetClient` in `baml_src/main.baml`, no rules | 0, receipt, 2 files keep the old name | 0 |
| `class AcmeWidgetConfig` in plain Python, no BAML | 0, receipt, 1 file keeps the old name | 0 |
| Same glued BAML name with a one-file `[[regenerate]]` | 1, no receipt (regeneration scan) | n/a |
| `ZetaToolClient` already present (new name) | 1, no receipt (P17 gate) | n/a |
| `press verify` before pressing either glued target | exit 1 | n/a |

Further findings:

- The post-apply doctor hunts the old identity with the conservative,
  whole-word matcher (`identity.token_pattern`), so it misses glued forms.
  `press verify` after a press hunts only the new identity, and P17's gate runs
  that same verify, so neither catches an old glued name.
- The reset and regeneration scans already hunt the old identity with the
  paranoid matcher (`matcher.find_occurrences`). That is why the glued case
  with a regenerate step fails safely.
- BAML derives generated names from source names (`<Type>Viewer`, `<Type>Ast`,
  `<Type>Properties`), and renaming a type reorders generated output. A text
  rewrite of the client differed from a fresh generate in 4 Python files and 8
  TypeScript files. Only regeneration produces a correct client.
- A scratch prototype that allowed `display_name_pascal` in
  `substring_rewrite_fields`, plus a one-file `[[regenerate]]` on
  `inlinedbaml.py` or `inlinedbaml.ts`, pressed with exit 0, produced a client
  equal to a fresh generate, and passed `press verify`.
  `uv run --offline baml-cli generate` worked as the declared command.
- A repeat press of a client inside the package exits 2: the
  `[[regenerate]] file` path still names the old package, and
  `{package_name}` is not accepted in that path today.
- The regeneration failure message calls every regenerated file a "lockfile".

## Goals

1. A BAML target on a Python or TypeScript host presses, regenerates its
   client, passes its own checks, and passes `press verify`.
2. The client is always regenerated from the renamed sources. Generated code is
   never rewritten as text.
3. Old identity glued into a longer name is refused before any write, for every
   target type, with guidance naming both fixes.
4. A repeat press works when the client lives inside the renamed package.

## Non-goals

- A `baml` value in `[rules] languages`. That list names the host manifest
  (`python`, `node`, `rust`). BAML has no root manifest.
- Built-in BAML commands. Every regeneration command is declared by the target.
- A declared BAML name map (`[identity.baml_names]`). It stays in reserve for
  glued names that do not derive from `display_name`.
- Live model calls, other BAML generators (Go, Ruby, REST), or other
  `baml-cli` versions beyond what the fixtures pin.
- P18 (a new name that contains the old one). BAML inherits today's exit 2
  refusal for, say, `Acme Widget` becoming `Acme Widget Pro`.

## Anti-goals

- A press that exits 0 while an old name survives.
- A newly refused target that `press verify` passes today (see scope below).
- Hidden default commands, or any command run by `press verify`.

## Constraints

- Safety contract unchanged: config-first identity, discovery cross-check,
  verify-then-mark, exit codes 0 / 1 / 2, no receipt on leaks.
- Zero runtime dependencies.
- `verifier.py` and `keep_names.py` stay independent of `substitutions`,
  `engine`, and `doctor` (design 0008 guardrail).
- Existing targets, `press-source.toml`, and answers files keep working,
  except the owner-accepted behavior change in Decision 1.
- The repository is public: synthetic `example.test` fixtures only.

## Approaches considered

### Glued-name leak check

| Option | Where it refuses | Outcome |
|---|---|---|
| A. Extend the pre-write sibling check (`check_keep_surfaces`) to the core identity fields | Before any write, exit 1 | **Chosen.** No files change on refusal. Same pattern P14 and P15 use for npm, CLI, and Cargo names. |
| B. Make the post-apply doctor hunt the old identity with the paranoid matcher | After rewrite, exit 1 | Rejected: the operator restores with git, and guidance is weaker. |
| C. Add a second `press verify` with the old identity inside the P17 gate | After rewrite, exit 1 | Rejected: verify's origin and receipt checks assume one identity, so it needs a new scan-only mode. It is also the slowest. |

### Generated client

| Option | Outcome |
|---|---|
| Text-rewrite the client | Rejected: wrong output after a type rename (evidence above). |
| One-file `[[regenerate]]` on `inlinedbaml.*` | Works today, but leaves the rest of the client text-rewritten and the declared file is a proxy for the directory. |
| `[[regenerate]] dir` | **Chosen** (owner, 2026-11-22): the directory is never text-rewritten and is rebuilt as a whole. |
| `[[remove]] dir` on the client | Rejected: passes, but leaves glued names in `.baml` sources and ships no client. |

## Decisions

### 1. Glued-name check (option A, scope (i))

Before any write, the press runs the keep-name preflight
(`check_target_keep_names`) over the core identity fields as well as the npm,
CLI, and Cargo names it covers today. An occurrence is refused when the
paranoid matcher finds an old identity value joined to another name part, and
none of these apply:

- a compiled rewrite row rewrites that occurrence on that path and surface
  (for example `display_name_pascal` in `substring_rewrite_fields`);
- one `keep_names` entry wholly covers it;
- a `[[verify.ignore]]` entry covers it;
- the file is a declared regeneration output, `[[remove]]` member, or excluded
  file or directory.

**Scope (i), owner decision 2026-11-25:** the fields checked are exactly the
fields `press verify` scans for this target: the effective `[verify] fields`
set (default `DEFAULT_FIELDS`), plus `display_name` and its forms, the declared
`npm_name`, `cli_name`, and Cargo names, plus any `substring_rewrite_fields`,
matched the way verify matches them. The required property is:

> If `press verify` exits 0 on an unpressed target, the press is never refused
> by this check.

A target that `press verify` already flags before pressing, such as a short
`app_name` inside `acmeConfig`, is now refused at press time with exit 1 and no
writes. The owner accepted that change on 2026-11-22. It also closes P17's
out-of-scope source-form gap (`_zapp_` for an old `app_name` of `zapp`).

Refusal output names the file, the token, the field, and both fixes:

```text
error: baml_src/main.baml: AcmeWidgetClient extends display_name "Acme Widget"
  rewrite it:  substring_rewrite_fields = ["display_name_pascal"]
  or keep it:  keep_names = ["AcmeWidgetClient"]
```

The rewrite suggestion is printed only when a substring field exists that
would rewrite that token. Otherwise only the keep fix is printed.

### 2. `display_name_pascal` in `substring_rewrite_fields`

Accept `display_name_pascal` in `substring_rewrite_fields`. Bare
`display_name` stays rejected. `display_name_camel` is not added; a glued camel
form is refused by Decision 1 and can be kept or renamed by hand. Validation,
rewrite, doctor, and verify must all treat the new values consistently, as the
existing substring fields do. The target opts in; the press never enables it
automatically.

### 3. `[[regenerate]] dir`

A `[[regenerate]]` entry takes exactly one of `file` or `dir`. For `dir`:

- No file under the directory is text-rewritten, scanned by the pre-write
  check, or hunted by the doctor. The directory path itself still moves with a
  renamed parent.
- After `apply()`, the press deletes the directory at its pressed location,
  runs the declared command, and requires the directory to exist afterward.
  Deleting first makes stale generated files impossible.
- Every file the command produced is scanned with the existing regeneration
  scan (paranoid, old identity, `scan = "strict"` by default; `"boundary"`
  stays the declared escape hatch). Any finding exits 1 with no receipt.
- `verify_exempt = true` with a `reason` exempts the whole directory from
  hermetic verify, and the reason appears in verify's not-verified listing and
  in the receipt. Without it, verify must be able to check the directory.
- The receipt records the directory, the command, and the reason.
- The directory must be inside the target, must not be the root or a control
  path (`press/`), and must not overlap another rule's file or directory. The
  same symlink and gitlink refusals as `[[remove]] dir` (P11) apply.
- A command failure exits 1 with no receipt and prints the restore hint.

### 4. `{package_name}` in regeneration paths

`[[regenerate]]` `file` and `dir`, and `extra_exclude_files`, accept
`{package_name}`. `extra_exclude_dirs` does not: its entries match single path
components (`engine._is_excluded`), so a rendered package name would exclude
the whole package. Builder-check call: a `[[regenerate]] dir` excludes itself
from rewriting and scanning, so it needs no `extra_exclude_dirs` entry, unlike
a `[[regenerate]] file`, which must still appear in `extra_exclude_files`. It renders with the source
identity to find the path before the press, and with the destination identity
for the pressed location. A repeat press then finds the client under the
current package name.

### 5. Languages

No BAML language value. A BAML repository declares its host, for example
`languages = ["python"]`, only when P16's guard requires a declaration.

### 6. Messages

The regeneration failure message names the declared output ("regeneration of
`<path>` failed") instead of calling it a lockfile.

### 7. Documentation

Document the BAML recipe in `docs/` and in the `press-target` skill, with the
example below, a `press verify` run before the first press, and the
gitignored-client path. Update design 0006 and 0008 where they describe the
leak check, substring fields, and regeneration.

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

### 8. Refuse an undeclared BAML client (owner decision, 2026-11-25)

Before any write, the press refuses a tracked BAML client that no
`[[regenerate]]` rule covers, with exit 2. A client is identified by a tracked
`baml_client/inlinedbaml.py` or `baml_client/inlinedbaml.ts` at any depth. It
is covered when a `[[regenerate]] dir` contains it or a `[[regenerate]] file`
names that marker. The refusal prints a `[[regenerate]] dir` block to paste,
following the existing undeclared `Cargo.lock` refusal
(`discovery._undeclared_lock_problem`). The press suggests the command and never
runs it. A gitignored or absent client is not refused, because the press has
nothing to rewrite. A `[[remove]]` of the client directory also counts as
covered.

```text
error: baml client src/acme_widget/baml_client has no [[regenerate]] declaration,
so it would be text-rewritten. Add this block to press/press-rules.toml
(press does not run it; review the command first):
  [[regenerate]]
  dir = "src/{package_name}/baml_client"
  command = ["uv", "run", "--offline", "baml-cli", "generate"]
  verify_exempt = true
  reason = "BAML client, rebuilt from baml_src"
```

This makes Goal 2 hold for every BAML target with a committed client. BAML
targets that press today without the declaration now exit 2 until they add it.

## Testing and acceptance

Tests are written first and fail before the change.

- Decision 1: failing Python, TypeScript, Rust, and BAML fixtures for an old
  glued name, then exit 1 with no writes. Negative cases: a glued name that a
  substring row rewrites, one declared in `keep_names`, one covered by
  `[[verify.ignore]]`, and unrelated words (`pressure` for `press`). A property
  test over the fixture corpus: wherever pre-press `press verify` exits 0, the
  press is not refused by this check. Verifier and keep-name independence stays
  enforced.
- Decision 2: validation, rewrite, doctor, and verify tests for the new values.
- Decision 3: schema validation (exactly one of `file` or `dir`, overlap,
  symlink and gitlink refusals), no text rewrite under the directory, stale
  files removed, added files present, every file scanned, verify exemption, and
  receipt content.
- Decision 4: preflight rendering and a repeat press with a client inside the
  package.
- Decision 8: a tracked Python and TypeScript client with no rule exits 2 with
  no writes and the suggested block; covered by a `dir`, a `file`, or a
  `[[remove]]` passes; a gitignored client is not refused.
- Real `baml-cli` acceptance, gated like other live tests: Python and
  TypeScript clients, client at the root and inside the package, press,
  regenerate, the target's own test, `press verify`, and a repeat press.
- `just check` and `just matrix` pass.

## Left to the builder

- How the paranoid field set is shared between verify and the preflight
  without breaking module independence.
- The exact receipt fields for a directory regeneration.
- Whether an absent or wholly gitignored client directory is regenerated in
  place or documented through the existing `[[clean]]` recipe. Both paths need
  a test.
- Ordering of the new preflight relative to the existing keep-name checks, and
  the wording of guidance beyond the example above.
