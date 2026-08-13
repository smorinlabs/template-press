# 0009 — Rendered substitution table and surface inventory

- **Status:** Accepted (P06 design checkpoint, 2026-08-12)
- **Type:** Design / decision record
- **Created:** 2026-08-12
- **Applies to:** `template_press.rebrand.engine`, `doctor`, `regen`, and
  `reset`; the new `inventory` and `substitutions` modules; and the
  independence boundary around `verifier`
- **References:** [P06 — derive checkers from one rendered substitution
  set](../../projects/P06-substitution-set.md); [0006 — external-target
  model](0006-external-target-model.md); [0007 — `press verify`
  design](0007-press-verify-design.md); [0008 — identity variants and replace
  rules](0008-identity-variants-and-replace-rules.md)

## Purpose and decision

`P06` (derive checkers from one rendered substitution set) will compile the
conservative rewriter's identity fields and declared
`[[replace]]` rules into one rendered substitution table. The rewriter will
apply that table. The inline doctor and the reset and regeneration scans will
derive their source-value hunt sets from the same table. This removes the
current requirement to add each rewrite mechanism separately to every checker.

`verifier.py`, the occurrence scanner inside `press verify`, remains an
independent check. The command still uses the table-driven `engine.apply()` to
press its sandbox, then `verifier.py` independently derives what to hunt. The
scanner may share the surface inventory and neutral path-safety primitives,
but it must not import or consume the substitution table. This asymmetry is
deliberate: the table prevents ordinary rewriter/checker drift, while the
verifier scanner remains able to detect a defect in the table or in the
conservative matcher itself.

The table-needs checkpoint confirms the three-pull-request implementation
split:

1. one kind-tagged surface inventory;
2. one pipeline-stability validator; and
3. the rendered substitution table and its consumers.

The walker and table do not need to land together. The inventory supplies only
path facts. Table-specific matching, scope, and rename translation remain in
pure policies above it.

## Terms

- A **surface entry** is one Git-visible relative path and its node kind:
  regular file, symbolic link, or gitlink. A gitlink is the Git index entry
  that represents a submodule.
- A **rewrite surface** is a location the rewriter may change: file content, a
  path component, or symbolic-link text.
- A **hunt policy** names one table-consuming checker, the surfaces that
  checker inspects, and the evidence matcher it uses. The consumers are the
  inline doctor, reset-stub scan, reset-path scan, and regeneration-output
  scan. The final regeneration pass reuses the regeneration-output policy.
- **Provenance** identifies the configuration fact that produced a row: an
  identity field, a derived `display_name` form, or one declared `[[replace]]`
  rule.
- `Identity` is the value object that holds one source or destination identity.
  `Rules` is the parsed `press/press-rules.toml` configuration model.
- `DISPLAY_FORM_NAMES` is the closed display-form set: `spaced`, `pascal`, and
  `camel`.
- A **rename plan** is the ordered, target-specific sequence of path-prefix
  changes required to reach a fixed point. A fixed point is reached when
  another rename pass would make no path change.

## Architecture

The diagram shows which consumers share compiled behavior and which checker
stays independent.

```text
source identity + destination identity + Rules
                     |
                     | render and validate
                     v
             SubstitutionTable rows
                |       |       |
                |       |       +--> reset/regeneration hunt terms
                |       +----------> inline doctor hunt terms
                +------------------> conservative rewriter
                     |
surface inventory ---+--> fixed-point RenamePlan --> plan/apply/translation

source identity + destination identity + Rules
                     |
                     +--> verifier matcher + verifier scan
                          (no SubstitutionTable dependency)
```

The shared table removes accidental disagreement among the rewriter and its
inline checks. `press verify` uses that rewriter in its sandbox, but the
separate verifier-scan dependency path preserves an independent failure
detector after the sandbox press.

## D1 — Rendered table shape

### Row contract

Each changed source-to-destination value produces one immutable candidate row.
The compiler then normalizes compatible duplicates into the final rows. A row
has these fields:

```python
@dataclass(frozen=True)
class RenderedSubstitution:
    row_id: str
    provenance: tuple[Provenance, ...]
    matcher: MatcherKind
    from_value: str
    to_value: str
    rewrite_surfaces: frozenset[Surface]
    hunts: tuple[HuntPolicy, ...]
    scope: Scope


@dataclass(frozen=True)
class HuntPolicy:
    consumer: HuntConsumer
    matcher: MatcherKind
    surfaces: frozenset[Surface]
    scope_coordinates: ScopeCoordinates


@dataclass(frozen=True)
class Provenance:
    kind: Literal["identity", "display_form", "replace_rule"]
    name: str
    declaration_index: int | None
    pattern: str | None
    reason: str | None


@dataclass(frozen=True)
class Scope:
    files: tuple[str, ...]
```

For identity provenance, `name` is the exact identity field and the last three
fields are `None`. For a display form, `name` is `display_name_spaced`,
`display_name_pascal`, or `display_name_camel`. For a declared rule, `name` is
`replace[N]`, where `N` is its one-based declaration index, and the remaining
fields retain that index, the unrendered pattern, and its required reason.

An empty `Scope.files` tuple means all paths, matching the current
`ReplaceRule.files` contract. Otherwise, the tuple contains the declared POSIX
path globs.

`MatcherKind` has four values:

- `boundary` uses the conservative identity-token boundary matcher;
- `substring` uses literal substring replacement for an identity field that
  `substring_rewrite_fields` explicitly enables;
- `literal` uses exact string replacement for a rendered `[[replace]]` rule;
  and
- `paranoid` uses `matcher.find_occurrences`, the verifier-grade occurrence
  matcher. It is valid only in a hunt policy, never as the rewriter's matcher.

`HuntConsumer` is `doctor`, `reset_stub`, `reset_path`, or `regeneration`.
`ScopeCoordinates` is `source` or `current_or_source`. Reset and regeneration
policies use the declared source path. Doctor policies match the current path
or its reverse-mapped source path so an ancestor rename cannot move a leftover
outside the rule that was meant to govern it.

`Surface` has `content`, `path`, and `symlink` values. Separate rewrite
surfaces and consumer-specific hunt policies are required for behavior parity.
A single `surfaces` set would lose two existing asymmetries:

- enabled `display_name` forms are rewritten only in content but the doctor
  also hunts them in path names and symlink text; and
- disabled `display_name` forms are not rewritten or hunted by the doctor, but
  the paranoid reset and regeneration scans still hunt all derived forms before
  granting a verifier exemption.

The ordered `provenance` tuple retains every field, display form, or declared
rule that normalized into the row. Its first item determines `row_id` and any
rewrite precedence. The complete tuple lets diagnostics explain every source
of a shared literal without applying that literal more than once.

`Scope` is either all paths or the declared `files` glob set from one
`[[replace]]` rule. Identity and display-form rows use all paths. Scope matching
uses the subject appropriate to the surface:

| Surface | Rewrite scope subject | Post-apply hunt scope subject |
|---|---|---|
| Content | The file's current relative path | The current path or its reverse-mapped source path |
| Path | The entry's current relative path | The current path or its reverse-mapped source path |
| Symlink | The normalized link-target path | The current target path or its reverse-mapped source path |

The post-apply union preserves the doctor's current fail-safe behavior. A
source-coordinate `files` glob must still govern a path after an ancestor has
been renamed.

### Mechanism-to-row mapping

The compiler uses the following mapping. `RENAME_FIELDS` means the existing
path-renamable identity fields: `package_name`, `repo_name`, `app_name`, and
`app_name_upper`.

| Provenance | Rewrite | Doctor hunt | Reset-stub hunt | Reset-path hunt | Regeneration hunt | Scope |
|---|---|---|---|---|---|---|
| Changed identity field in `RENAME_FIELDS` | content, path, symlink; `boundary` or declared `substring` | content, path, symlink; rewrite matcher | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Other changed identity field | content, symlink; `boundary` or declared `substring` | content, symlink; rewrite matcher | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Enabled derived `display_name` form | content; `boundary` | content, path, symlink; `boundary` | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Disabled derived `display_name` form | none | none | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Rendered `[[replace]]` rule | `literal`; content when `content`, path and symlink when `paths` | the same enabled surfaces; `literal` | content when `content`; `literal` | path when `paths`; `literal` | content when `content`, path when `paths`; `literal` | the rule's `files` globs |

Rows whose rendered source and destination values are equal are omitted.
Declared `[[replace]]` rows retain declaration order. Identity rows retain the
current longest-source-value-first order.

Candidates with the same matcher, source, destination, rewrite surfaces, hunt
policies, and scope coalesce into one row and retain all provenance. The
current display-family exception also remains: if multiple `display_name`
forms collapse to the same source text but render different destinations, the
first configured enabled form supplies the rewrite destination. Later enabled
forms and all disabled forms remain as hunt provenance. If no form is enabled,
the first canonical form supplies the unused `to_value`.

For example, the source display name `NumPy` can produce the same source text
for its spaced and Pascal forms while the destination `Acme Widget` produces
`Acme Widget` and `AcmeWidget`. Rejecting that pair would make a common default
configuration unpressable. The exception is limited to derived forms of the
same `display_name`; the validator refuses the same ambiguity across unrelated
fields or rules with overlapping rewrite surfaces.

`row_id` and `provenance` make every validation error, plan item, leak, and test
failure traceable to its originating field, display form, or declared rule.

### Table contract

`SubstitutionTable` owns the ordered rows and the target-specific rename plan:

```python
@dataclass(frozen=True)
class SubstitutionTable:
    rows: tuple[RenderedSubstitution, ...]
    rename_plan: RenamePlan
```

The compiler first renders and validates the rows. It then combines the path
rows with one surface-inventory snapshot to build `rename_plan` to a fixed
point. `build_plan()` and `apply()` consume that same plan; neither independently
re-derives rename candidates.

`RenamePlan` retains ordered steps rather than collapsing them into one
single-pass dictionary. Each step records the old prefix, new prefix, pass
number, and contributing row IDs. This preserves intermediate coordinates for
a nested rename such as:

```text
packages/demo_widget/demo_widget.py
  pass 1: packages/demo_widget -> packages/potato_launcher
  pass 2: packages/potato_launcher/demo_widget.py
          -> packages/potato_launcher/potato_launcher.py
```

Plan-time translation applies both steps. This closes PR #62 review thread
`3654853364`, where `build_plan()` recorded only pass 1 but `apply()` performed
both passes and a valid reset target was refused before the press.

Apply executes the planned steps with the existing containment, ancestor,
destination, and time-of-check/time-of-use checks. The apply report marks which
steps actually ran. Post-apply consumers use that executed view; preflight and
dry-run consumers use the full planned view. These are two lifecycle views of
one plan, not independently derived maps.

P06 changes the `apply()` order to content rewrite, fixed-point renames, then
symlink retarget. The retarget pass reads the executed rename-plan view and
must not maintain a second calculation of which existing targets were movable.
It locates each link by translating the source-inventory entry to its executed
post-rename path; Git's index may still contain the source path.

For an existing relative in-tree target, a symlink row is eligible only when
the executed plan moved that target or one of its descendants. For a dangling
relative in-tree target, the current safe behavior remains: path rows may
rewrite its text because no existing content can be silently redirected. For
an eligible target, the pass translates both the link location and target
location to their final coordinates and computes the final relative link text.
Existing fail-safe behavior for absolute, escaping, and ignored existing
targets remains unchanged.

## D2 — One surface inventory, policies above it

The inventory returns raw path facts:

```python
@dataclass(frozen=True)
class SurfaceEntry:
    rel: Path
    kind: Literal["file", "symlink", "gitlink"]
    tracked: bool
```

The inventory is sorted by POSIX relative path and decodes Git path bytes with
`surrogateescape`, the Python error handler that preserves undecodable bytes for
round-trip filesystem access. It is the only rebrand component that shells out
to Git to enumerate tracked, non-ignored untracked, and gitlink entries.
Symbolic-link classification never follows the link.

The walker does not accept a `copy`, `rewrite`, or `scan` mode. Those modes are
policies, not path facts. Pure selectors above the inventory preserve the
current contracts:

| Consumer | Selection from the raw inventory |
|---|---|
| Copy sandbox | Every entry, excluding Git's own metadata |
| Content rewrite | Current rewrite exclusions and exact root-control exemptions |
| Rename planning | Rewrite-eligible files and symlinks; never gitlinks |
| Inline doctor | Exact root-control exemptions, built-in rewrite exclusions, and `verify_ignore` |
| Standalone verifier | Exact root-control exemptions, `verify_ignore`, and only outputs that are both declared regenerations and on the tool's regeneration-exemption cap |
| Regeneration/reset preflight | Entries whose `tracked` field is true |
| Symlink retarget | Entries whose kind is `symlink` |

This interface replaces `engine._git_listed`, `engine.iter_target_files`,
`engine.copy_paths`, `engine.scan_paths`, and `regen.tracked_paths`. Compatibility
adapters may preserve those names during the first pull request, but they must
all delegate to the one inventory. Exclusion logic stays in named selectors so
one consumer cannot silently change another consumer's coverage.

The table requires no additional inventory field. Table scopes operate on
`SurfaceEntry.rel`; node-specific behavior dispatches on `SurfaceEntry.kind`;
tracked-only preflights use `SurfaceEntry.tracked`; and rename coordinates live
in `RenamePlan`. Therefore the walker interface survives the table-needs
checkpoint and can land independently.

## D3 — One pipeline-stability validator

The second pull request replaces the current scattered plan-time guards with
one pure validator over rendered source-to-destination candidates. The
validator enforces two properties before any target write:

1. **Pipeline stability and termination.** On any overlapping surface, one
   source literal has one destination meaning, a row's output is stable under
   every later row, and a path row cannot match its own output indefinitely.
2. **Path-component structural safety.** A path substitution cannot introduce
   a separator, an empty component, `.` or `..`, or another value that changes
   the component count.

The validator preserves current harmless cases: equal source and destination
rows are omitted; compatible duplicates are coalesced without losing their
scope or provenance; the same-source display-family exception keeps its first
configured enabled destination; hunt-only rows do not create rewrite
conflicts; and rules on disjoint rewrite surfaces do not conflict. Validation
errors name every conflicting `row_id` and its provenance.

The validator lands before the table. It initially accepts the existing
identity-pair and rendered-rule tuples. The table compiler becomes its only
caller in the third pull request. This sequencing centralizes the invariants
without making the walker depend on the table.

## D4 — Checker derivation contracts

### Inline doctor

The doctor receives `SubstitutionTable` and the executed rename-plan view. It
selects the `doctor` hunt policies, searches each row's `from_value` on the
policy's surfaces with the policy's matcher, applies the row's scope in current
and source coordinates, and reports the row's provenance. It does not call
`replacement_pairs()`, expand `display_name`, or render `[[replace]]` rules
independently.

The doctor remains a presence/absence gate on the real target. Binary files
remain outside the conservative rewrite-and-doctor contract; unreadable text
remains an `unverifiable` leak.

### Reset and regeneration scans

Plan-time reset-stub scans, per-command regeneration postconditions, and the
final validation pass receive the same table. They derive changed identity
values and rendered rule literals from rows instead of calling
`changed_identity_pairs()` and `rendered_replace_rules()` separately.

These scans select their own hunt-policy consumer. The policies keep the
current paranoid evidence standard where a file is exempt from the hermetic
verifier. Identity and display-form policies use `paranoid`; declared-rule
policies use `literal`. Reset-stub policies use a declared rule's content
surface; reset-path policies use its path surface; and regeneration policies
cover both when the declared rule enables both.

The final regeneration pass reruns the `regeneration` hunt policies for every
declared output. The final reset check still compares the file with its exact
approved stub bytes; it does not need another identity hunt policy.

### Standalone verifier

`verifier.py` does not receive the table, its rows, its rename-plan provenance,
or its matcher dispatch. It independently derives changed identity fields and
rendered rule literals from `Identity` and `Rules`, then scans them with the
paranoid matcher from design 0007. Sharing the raw surface inventory, executed
path translations, and neutral scope primitives is allowed because those facts
do not decide what identity occurrence counts as a leak.

## D5 — Independence guardrail

Design 0008 contains the binding dependency rule. P06 must enforce both the
module boundary and the data-flow boundary:

1. A structural regression test parses `verifier.py` and `verify_cli.py`. The
   test fails if `verifier.py` imports `template_press.rebrand.substitutions`,
   including inside a `TYPE_CHECKING` block. It also fails if `verifier.scan()`
   accepts a `SubstitutionTable`, substitution rows, or pre-rendered rule
   literals, or if `verify_cli.py` passes any of those values into the scan.
2. An ablation test deliberately removes one rendered `[[replace]]` row from
   the rewriter's table before the sandbox apply. The independent verifier scan
   must still derive that rule from `Rules` and report the surviving source
   literal.

Both tests are acceptance criteria, not optional documentation coverage. The
structural test blocks the known direct data path. The ablation test proves the
independence property even if a future refactor hides shared data behind a new
helper name.

The intended dependency boundary is:

```text
allowed:   verifier -> inventory, matcher, rules, safety, neutral scope helpers
forbidden: verifier -> substitutions or SubstitutionTable
```

This guard prevents a future deduplication refactor from making the final
independent checker inherit the rewriter's blind spots.

## Pull-request boundaries and acceptance evidence

### PR 1 — Surface inventory

- Introduce `SurfaceEntry` and the single Git-backed inventory.
- Delegate all five existing walker APIs to it, then remove duplicate Git
  enumeration.
- Preserve inventory behavior for tracked and untracked files, symbolic links,
  gitlinks, non-UTF-8 path bytes, root-control artifacts, rewrite exclusions,
  and scan exemptions.

### PR 2 — Pipeline-stability validator

- Move the scattered ambiguity, output-stability, termination, and structural
  checks behind one validator.
- Preserve every currently accepted and refused identity/rule configuration.
- Report conflicts with provenance rather than tuple positions.

### PR 3 — Substitution table

- Compile rows and the fixed-point rename plan.
- Make plan, apply, doctor, reset, and regeneration consumers read the table.
- Make symlink retargeting read the rename plan instead of its private
  movability derivation.
- Add the verifier-independence architecture test.

Each pull request must pass the full automated suite and the R1a/R1b/R2/R3
rebrand acceptance matrix. PR 3 also needs focused regression tests for:

- a two-pass nested rename whose reset and regeneration paths translate to the
  final location;
- every mechanism-to-surface row in the mapping table above;
- duplicate and collapsed `display_name` forms, including the valid one-word
  source and multi-word destination case;
- current-path and reverse-source-path rule scope after an ancestor rename;
- derivation of doctor, reset, and regeneration hunts from a newly added row;
  and
- rejection of any verifier dependency on `substitutions`, including the
  rewriter-row ablation described in D5.

## Rejected alternatives

### Combine the walker and table in one pull request

Rejected after the table-needs checkpoint. The table needs only `rel`, `kind`,
and `tracked` from the walker. Combining them would increase review scope
without resolving an interface dependency.

### Put exclusions inside walker modes

Rejected because copy, rewrite, rename, scan, and preflight exclusions express
different policies. A modeful walker would hide those differences in one large
conditional and make future coverage drift difficult to review.

### Make the verifier consume the table

Forbidden by P06 D2. This would remove the last independently derived answer to
whether a source identity survived the press.

## Consequences

- Adding a rewriter mechanism requires one compiler change and its row tests;
  the doctor and reset/regeneration hunt sets update by construction.
- Every target path is classified once, while each consumer's exclusions
  remain explicit and independently testable.
- Plan-time and apply-time rename translation share one fixed-point derivation,
  closing the nested-target false refusal deferred from PR #62.
- The shared doctor can inherit a table defect. That correlated-failure risk is
  accepted because the independent verifier remains structurally separated.
- Acceptance of this design makes P06 ready for task decomposition; this
  document does not decompose or implement the work.
