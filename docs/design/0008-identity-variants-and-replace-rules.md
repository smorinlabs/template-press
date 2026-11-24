# 0008 — Identity Variants & Replace Rules (C/D/E gap fixes)

- **Status:** Accepted (codesign 2026-07-23)
- **Type:** Design / decision record
- **Created:** 2026-07-23
- **Applies to:** the rebrand engine's identity model and replace-rule
  mechanism (`src/template_press/rebrand/identity.py`, `engine.py`,
  `rules.py`, `doctor.py`)
- **Informed by:**
  historical research 0005, *Scaffolder Identity-Variant Handling — Research
  for the C/D/E Gap Fixes* (`0005-scaffolder-identity-variant-handling.md`);
  historical research 0004 §5, *py-launch-blueprint Conformance Gaps —
  `press verify` Dogfood Findings* (`0004-py-launch-blueprint-conformance-gaps.md`);
  [design 0009](0009-substitution-table.md)

The research filenames identify documents under `docs/research/` in the
original source history. Native self-press removes that directory; this
retained decision record does not require those files to remain present.

## Decisions

1. **`display_name` — optional identity field** (sec-01 ch-01-a).
   Declared in `[identity]`/`[answers]`; absent = feature off (existing
   configs stay valid). Rewritten as a CLOSED set of exact forms —
   spaced / PascalCase / camelCase — each replaced with the same-shaped
   form of the new name; the set is configurable via
   `[rules] display_forms` (sec-04 ch-04-c, default all three). Verify
   scans it as its own field whenever declared (sec-05 ch-05-a).
   Half-specified (source declares, answers doesn't) is exit 2 (sec-06
   ch-06-a). Derivation from repo_name was REJECTED — real product names
   ("NumPy", "PyTorch") are not titleized slugs.
2. **`[[replace]]` exact rules — the primary glued-token mechanism**
   (sec-02 ch-02-c, "rules primary"). One template string with `{field}`
   placeholders, rendered twice: source identity → literal to find,
   destination identity → literal to write. Exact replacement, no fuzzy
   matching. Interpolation keeps committed rules correct across repeated
   presses (press rewrites press-source.toml post-apply). Arguments
   (sec-07): `files` globs, `paths` (default false), `content` (default
   true), required `reason`. `count` was rejected — occurrence counts rot.
3. **Substring mode — secondary, per-field opt-in** (sec-02 ch-02-c).
   `[rules] substring_rewrite_fields = ["app_name"]` switches that field
   to plain substring replacement in content AND path components. Gated on
   the target author declaring the token word-disjoint; never a default.
   Fields are independently selectable — opting in `app_name` does not
   cover glued UPPERCASE forms (e.g. `PLBPOwned`); a target with those
   needs the derived field opted in too, so the recommended pair when
   uppercase glued forms exist is
   `substring_rewrite_fields = ["app_name", "app_name_upper"]`.
4. **Paths ride the shared matcher** (sec-03 ch-03-a). Rules with
   `paths = true` and substring-mode fields flow into the existing
   `_renamed_rel` rename pass — no second matching surface (the dotnet
   content-vs-path divergence lesson). `paths=true, content=false` IS the
   dedicated path-only rename rule. New guard: a substitution that would
   empty a path component fails loud (cookiecutter #1518 class).

5. **Hyphenated package names (P13, approved 2026-11-22).** The hyphenated
   form of `package_name` is handled by evidence, not by assumption:

   | Target | Result |
   |---|---|
   | `[project].name` is the hyphenated form | Rewritten in content and paths |
   | Manifest does not prove it, and the form survives | Text unchanged, exit 1, no receipt |
   | Another identity value equals the form | That field's row owns it; `[project].name` still follows `package_name` |

   A word-like name such as `well_known` is why an unproven form is never
   rewritten: `a well-known API` is prose. To accept an unproven mention, list
   the file in `[rules] verify_ignore`. To preserve a whole historical file
   when the manifest does prove the form, list its path in
   `extra_exclude_files` and its name in `verify_ignore`.

6. **Exact npm and CLI names, and `keep_names` (P14, approved 2026-11-22).**
   Two more optional identity fields, declared on both sides or neither (one
   side only is exit 2): `npm_name` (exact root `package.json` `name`, scope
   allowed) and `cli_name` (exact `bin` key). Both are rewritten as exact
   values with `[A-Za-z0-9_-]` boundaries. `cli_name` and an unscoped
   `npm_name` also rename paths; a scoped `npm_name` is content-only, and a
   leftover scoped path is a leak. A source equality between either field and
   another identity value must be preserved in the answers.

   `[rules] keep_names` lists exact, case-sensitive names that are independent
   of the identity. A kept occurrence survives every rewrite row, and every
   scan ignores a match wholly inside it; an overlap is still a leak. An entry
   equal to a source or destination identity value (including case and
   separator variants and display forms) exits 2, after ignoring leading and
   trailing characters outside `[A-Za-z0-9@/_-]` and then edge `/` and `@`
   (a scoped name keeps its `@`). An entry with an edge `-` or
   `_` (`--acme-cli`) is compared exactly and may be kept.

   Before any rewrite, `press rebrand` and `press verify` run a sibling
   preflight and exit 1 with no writes and no receipt on an undeclared name
   joining a source `npm_name` or `cli_name` to another name part or touching
   a bare separator. A multi-part value treats any touching name character as
   a sibling. For a single-token value (`tsc`), a glued alphanumeric means an
   unrelated word, so `tsconfig` and `web-server` pass; otherwise a touching
   `-`, `_`, or camelCase tail fails, including `tsc-helper`, `tscConfig`,
   `--tsc`, and `_tsc_`. Tokens a row or `[[replace]]` rewrites are exempt, as
   are planned `[[remove]]` files. Known limits when `package_name` changes: a
   six-field config whose `package.json` name equals the hyphen form exits 1;
   a scoped `npm_name` whose basename stays that form exits 1 from
   `press rebrand` after rewriting while `press verify` exits 0; a declared
   unscoped `npm_name` left unchanged exits 0; `keep_names` holding that form
   exits 2. Separately, a scope-preserving press with a changed `owner` can exit 2 at press time while
   `press verify` exits 0; non-UTF-8 files are scanned only by `press verify`.
   Spec: [TypeScript and Bun
   targets](../superpowers/specs/2026-11-22-typescript-bun-targets-design.md).

7. **Exact Cargo names (P15, approved 2026-11-22).** `cargo_names` is an
   optional table of stable role to exact Cargo package, library, or binary
   name, declared on both sides or neither (one side only is exit 2). Each role
   rewrites its exact name and its underscore form, in content and paths, with
   `[A-Za-z0-9_-]` boundaries. So `acme-core/serde`, `dep:acme-core`, and
   `acme_core::hi` match, and the sibling `acme-core-extra` does not.
   `package_name` must be the underscore form of one source value, and its
   destination must be the underscore form of the same role's destination.

   Rust is a `[rules] languages` value. A sole root `Cargo.toml` activates it.
   A target with another identity manifest declares `["python", "rust"]` to
   check both, or omits `"rust"` when `Cargo.toml` is tooling only. An
   independent sibling crate is declared in `keep_names`.

   Two more table refusals exit 2 before any write. A hyphen-free source name
   cannot take a hyphenated destination, because text cannot separate its
   package spelling from its Rust identifier. A source or destination name
   cannot equal a non-local dependency, because Cargo would resolve the wrong
   crate.

   A target with `cargo_names` and a tracked `Cargo.lock` must declare
   regeneration, or the press exits 2 and prints the block:

   ```toml
   [rules]
   extra_exclude_files = ["Cargo.lock"]

   [[regenerate]]
   file = "Cargo.lock"
   command = ["cargo", "update", "--workspace", "--offline"]
   ```

   That command keeps locked third-party versions, which
   `cargo generate-lockfile` would move. Its environment passes `HOME` but not
   `CARGO_HOME`, so a custom Cargo home needs dependencies vendored or cached in
   the default location.

   Deliberate refusals before any write: a destination that extends a source
   name or contains another field's source spelling (exit 2), a crate whose
   Rust identifier would be left behind (exit 2), and a versioned string such
   as `acme-core-0.1.0` (sibling preflight, exit 1, unless the exact token is in
   `keep_names`). The verifier derives its Cargo hunts directly from `Identity`.
   Spec: [Rust and Cargo
   targets](../superpowers/specs/2026-11-22-rust-cargo-targets-design.md).

8. **`[[cargo_split]]`: one-press rename of a hyphen-free crate (P15-T09,
   owner decision Q2.A).** The hyphen-free refusal stays the default. A target
   opts in per role in `press/press-rules.toml`:

   ```toml
   [[cargo_split]]
   role = "core"                                       # a cargo_names role
   package_files = ["README.md", "scripts/release.sh"]  # fnmatch globs
   identifier_files = ["docs/api.md"]
   ```

   With `core = "acme"` pressed to `core = "zeta-gadget"`, every `Cargo.toml`
   takes the package spelling `zeta-gadget`, and Rust code in every `.rs` file
   takes the identifier spelling `zeta_gadget`. That structural rule outranks
   the globs. Inside a `.rs` string literal, the press writes `zeta-gadget`
   only where real Cargo proves it right: a `feature = "acme"` value inside
   `cfg(`, `cfg!(` or `cfg_attr(`; an `include_*!` or `#[path]` string naming
   a file the press renames (the string must resolve to that file's new
   path); and `"acme"` as the other side of an `==`, `!=`, `assert_eq!` or
   `assert_ne!` comparison with `env!("CARGO_PKG_NAME")`. Strings inside doc
   comments (`///`, `//!`, `/**`, `/*!`), which rustdoc compiles, follow the
   same rules. Any other string occurrence exits 2.
   `CARGO_BIN_EXE_acme` becomes `CARGO_BIN_EXE_zeta-gadget`. Paths take the
   package spelling, so `crates/acme` becomes `crates/zeta-gadget` and declared
   manifest paths follow. A file matched by `package_files` or
   `identifier_files` takes that spelling.

   Before any write, the press exits 2 and lists `file:line` for each
   occurrence that the ordered rows leave behind. These checks also exit 2:

   - a file that matches both lists;
   - an explicit `[lib] name = "acme"`, because Cargo refuses a hyphen in a
     library name;
   - a renamed path below `src/`, other than `src/bin/<name>`, and a renamed
     `acme.rs` or `acme/` anywhere when a `.rs` file declares `mod acme;`;
   - a `package_files` file whose rewrite puts `zeta-gadget` where only an
     identifier fits: `::` paths, `extern crate`, `use`, and log filters such
     as `RUST_LOG=acme=debug`; the remedies are `identifier_files` or an exact
     `[[replace]]`;
   - a target that also checks `python` or `node`.

   A file holding both spellings works only when the split crate is the
   `package_name` crate. List the file in `package_files`, and add an exact
   `[[replace]]` rule scoped to it, such as `pattern = "{package_name}::hi"`.
   Declared rules run first and write `zeta_gadget::hi`. A non-primary role
   cannot do this yet, because `[[replace]]` cannot reference `cargo_names`;
   P15-T10 adds `{cargo_exact_<role>}` and `{cargo_ident_<role>}`.

   The block is validated against both tables. Its role must exist in both
   tables. The source must have no hyphen and the destination must have one;
   otherwise the block is refused as unnecessary. After a press, a block left
   in place is inert: when a receipt exists and the source already has a
   hyphen, the press prints a warning instead of refusing. The receipt and the
   rewritten `press-source.toml` record the hyphenated name, so later presses
   use the normal two-spelling rows. `press verify` ignores the block.

## Independence guardrail (P06 D2)

The rendered substitution table introduced by design 0009 is the conservative
rewriter's compiled behavior. The inline doctor and the reset and regeneration
scans may derive their hunt sets from it. The standalone paranoid verifier must
not.

`src/template_press/rebrand/verifier.py` **must not** import table-consuming
`template_press.rebrand.substitutions`, `engine`, or `doctor` modules; accept a
`SubstitutionTable`; or derive its occurrence matcher from table data. It must
continue to derive configured changed identity fields and rendered
`[[replace]]` literals independently from `Identity`, `Rules`, and neutral
`VerifyConfig` field names and substring flags. Identity values use
`matcher.find_occurrences` with the effective substring flag. Rendered rule
sources use case-sensitive exact-literal occurrence matching on the rule's
declared surfaces and scope. Sharing the raw surface inventory, path
translation, safety checks, and neutral rule-scope primitives is allowed
because those facts do not define what counts as an identity occurrence.

P06 must enforce this dependency rule at the module and call boundaries. A
structural regression test parses `verifier.py` and `verify_cli.py`, including
aliases and `TYPE_CHECKING` blocks. It rejects a `verifier.py` import of
`substitutions`, `engine`, or `doctor`, and any `verifier.scan()` parameter or
caller argument that supplies table rows, precompiled identity values, rendered
rule literals, hunt policies, or matcher dispatch. Neutral helpers move out of
table-consuming modules. `verify_cli.py` may still call `engine.apply()` for
orchestration.

Two discriminating ablation tests enforce behavior. The rule ablation uses a
boundary-invisible source such as `x{app_name}owned` and requires a
`replace_rule` finding. The identity ablation leaves a glued or camel-case
source occurrence that only the paranoid matcher detects and requires the
configured identity-field finding.

Prose alone is not sufficient because a future deduplication refactor could
otherwise remove the final independent check without changing runtime output
on ordinary fixtures.

## Order of operations (engine.apply)

`[[replace]]` rules → boundary/substring token pairs (content), then
symlink retarget, then renames to fixpoint. Rules run first because a
rendered FROM may embed an identity token the token pass would rewrite
out from under it.

Design 0009 supersedes this order for P06 PR 3: content rewrite, renames to
fixpoint, then symlink retarget from the executed rename plan. The reordered
pass closes the duplicate retarget predicate described under Known limitations.

## Consequences

- py-launch-blueprint's conform needs: `display_name = "Py Launch
  Blueprint"`, `substring_rewrite_fields = ["app_name"]`, and ~1-3
  `[[replace]]` rules — closing G3/G4/G5 without verify ignores.
- `press verify` on a display-declaring target auto-extends its scan
  fields; the hermetic press synthesizes a containment-free display name.

## Known limitations

- `files` globs use Python fnmatch against the full POSIX relative path:
  `*` crosses `/` (so `*.txt` matches nested files); scope rules by explicit
  path prefixes or exact paths when directory scoping matters.
- **Historical, fixed by the map-driven retarget:** a `paths = true` rule
  whose `files` glob was scoped under a directory that was itself renamed
  during the multi-pass rename fixpoint used to be able to diverge from
  what `--dry-run` predicted. A narrow glob (e.g.
  `files = ["docs/*/data.txt"]`) could satisfy the rename pass, which
  scope-matched the rule against the FILE's own posix (`_renamed_rel`), but
  miss the retarget pass, which scope-matched the SAME rule against the
  link's TARGET/directory posix (the pre-refactor `_retarget_symlinks`,
  commit `a0f0f98`) — leaving a symlink pointing at that directory
  dangling, undetected by either `doctor.find_leaks` or `press verify`
  (both reused the same predicate). The map-driven retarget
  (`_retarget_planned_symlinks`) closed this for good: symlinks are now
  retargeted from the actual executed `(old -> new)` rename map instead of
  re-evaluating any rule's scope predicate a second time, so a narrowly
  scoped `files` glob on a `paths = true` rule is safe — the earlier advice
  to prefer unscoped globs as a workaround no longer applies, and the FILE-
  posix-vs-DIRECTORY-posix predicate divergence this bullet used to warn
  about no longer exists (there is no second predicate to diverge from).
- **Straddling matches (cycle 10):** `rendered_replace_rules`'s rendered-TO
  stability check (commit `9d347d3`) catches every mutation of a rule's
  rendered TO that lies wholly WITHIN that TO. A match that STRADDLES the
  boundary between surrounding file content and the inserted TO (context
  `"x"` + TO `"bar_data"` forming `"xbar"`, which matches a changed
  `package_name` `"xbar"` -> `"qq"`) is content-dependent and not checkable
  at plan time — not a claim of impossibility, just outside what a
  plan-time check can see.
