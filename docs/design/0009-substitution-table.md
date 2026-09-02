# 0009 — Rendered substitution table and surface inventory

- **Status:** Accepted (P06 design checkpoint, 2026-08-12; P07 platform
  selection amendment, 2026-08-16)
- **Type:** Design / decision record
- **Created:** 2026-08-12
- **Applies to:** `template_press.rebrand.engine`, `doctor`, `regen`, and
  `reset`; the new `inventory` and `substitutions` modules; and the
  independence boundary around `verifier`
- **References:** [P06 — derive checkers from one rendered substitution
  set](../../projects/P06-substitution-set.md); [P07 — platform-conditional
  declared commands](../../projects/P07-platform-conditional-declared-commands.md);
  [0006 — external-target model](0006-external-target-model.md); [0007 —
  `press verify` design](0007-press-verify-design.md); [0008 — identity
  variants and replace rules](0008-identity-variants-and-replace-rules.md)

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
path, index-kind, worktree-kind, and tracked-state facts. Table-specific
matching, scope, and rename translation remain in pure policies above it.

## Terms

- A **surface entry** is one Git-listed relative path plus separate index and
  worktree facts. A gitlink is the Git index entry that represents a submodule.
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
- **Parsed declarations** are the private, pre-selection `[[regenerate]]` and
  `[[reset]]` entries, including each entry's platform set. `SelectedRules` is
  the frozen boundary containing one captured platform value and a `Rules`
  value with only the declarations active on that platform.
- `DISPLAY_FORM_NAMES` is the closed display-form set: `spaced`, `pascal`, and
  `camel`.
- A **rename plan** is the ordered, target-specific sequence of path-prefix
  changes required to reach a fixed point. A fixed point is reached when
  another rename pass would make no path change.

## Architecture

The diagram shows the P07 selection boundary, which consumers share compiled
behavior, and which checker stays independent.

```text
press/press-rules.toml
          |
          v
parsed declarations
          |
          | validate every schema and same-file writer overlap
          v
platform selection (capture once)
          |
          v
SelectedRules {platform, active Rules}
          |
          +--> active Rules + source identity + destination identity
          |                 |
          |                 | render and validate
          |                 v
          |         SubstitutionTable rows
          |            |       |       |
          |            |       |       +--> reset/regeneration hunts
          |            |       +----------> inline doctor hunts
          |            +------------------> conservative rewriter
          |                 |
          |    inventory ---+--> fixed-point RenamePlan
          |                          |
          |                          +--> plan/apply/translation
          |
          +--> active Rules + source identity + destination identity
                + VerifyConfig + source snapshot
                              |
                              +--> verifier matcher + verifier scan
                                   (no SubstitutionTable dependency)
```

The shared table removes accidental disagreement among the rewriter and its
inline checks. `press verify` uses that rewriter in its sandbox, but the
separate verifier-scan dependency path preserves an independent failure
detector after the sandbox press.

Selection never hides invalid configuration. Parsing validates every declared
schema and rejects any pair of `[[regenerate]]` or `[[reset]]` writers whose
platform sets overlap for the same file. Only after that global phase does the
pure selector build `SelectedRules`. The selected `Rules` value then governs
plan, preflight, apply, doctor, reset, regeneration, and table construction;
no consumer filters declarations or reads the runtime platform again.

Environmental validation occurs after selection. Missing active executables,
unreadable active reset stubs, and active excluded-file coverage failures stop
the operation before mutation. An inactive declaration can trigger a global
schema or overlap error, but its executable, stub, plan item, action, and
receipt evidence are absent. Git remains an unconditional preflight tool.

The verifier follows the same selected `Rules` boundary so platform-inactive
exemptions cannot affect its sandbox. Its scanner still derives matches from
source identity, destination identity, active `Rules`, `VerifyConfig`, and the
source snapshot. It does not consume `SubstitutionTable`, compiled hunts, or
engine findings.

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
    matcher: MatcherSpec
    from_value: str
    to_value: str
    rewrite_surfaces: frozenset[Surface]
    hunts: tuple[HuntPolicy, ...]
    scope: Scope


@dataclass(frozen=True)
class HuntPolicy:
    consumer: HuntConsumer
    matcher: MatcherSpec
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


@dataclass(frozen=True)
class MatcherSpec:
    algorithm: MatcherKind
    identity_field: str | None
    substring: bool
```

For identity provenance, `name` is the exact identity field and the last three
fields are `None`. For a display form, `name` is `display_name_spaced`,
`display_name_pascal`, or `display_name_camel`. For a declared rule, `name` is
`replace[N]`, where `N` is its one-based declaration index, and the remaining
fields retain that index, the unrendered pattern, and its required reason.

An empty `Scope.files` tuple means all paths, matching the current
`ReplaceRule.files` contract. Otherwise, the tuple contains the declared POSIX
path globs.

`MatcherSpec` preserves every input that changes matching behavior. Its
`algorithm` field has three values:

- `conservative` uses the field-specific identity-token matcher for a rewrite
  or inline-doctor hunt. `identity_field` is the exact field tag required by
  that matcher. `substring=True` selects its explicit substring mode;
- `literal` uses case-sensitive exact replacement or occurrence matching for a
  rendered `[[replace]]` rule; and
- `paranoid` uses `matcher.find_occurrences` for a reset or regeneration
  identity hunt. `identity_field` and `substring` remain required. It is valid
  only in a hunt policy, never as the rewriter's matcher.

An identity `MatcherSpec` never reduces to a generic boundary marker. For
example, `app_name`, `app_name_upper`, and `display_name_spaced` have different
boundary expressions even when their source text is equal. A paranoid hunt
also retains the effective substring flag from
`Rules.substring_rewrite_fields`; otherwise a glued opted-in occurrence could
survive a reset or regenerated output scan.

`HuntConsumer` is `doctor`, `reset_stub`, `reset_path`, or `regeneration`.
`ScopeCoordinates` is `source` or `current_or_source`. Reset and regeneration
policies use the declared source path. Doctor policies match the current path
or its reverse-mapped source path so an ancestor rename cannot move a leftover
outside the rule that was meant to govern it.

`Surface` has `content`, `path`, and `symlink` values. Table rows directly
rewrite `content` and `path`; eligible symlink text is derived from the final
path translation. Hunt policies may inspect all three surfaces. Separate
rewrite surfaces and consumer-specific hunt policies are required for behavior
parity. A single `surfaces` set would lose two existing asymmetries:

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
| Symlink | No direct row rewrite; retargeting uses the path plan | The path-plan trigger that moved the target prefix; direct current or reverse-source target scope remains a supplemental match |

The post-apply union preserves the doctor's current fail-safe behavior. A
source-coordinate `files` glob must still govern a path after an ancestor has
been renamed.

Symlink scope cannot be decided only by applying a rule's `files` glob to the
normalized target path. A scoped descendant can trigger an ancestor-prefix
rename even when the target directory itself does not match the glob. Each
`RenamePlan` step therefore records the source entries that triggered the step
and the contributing row IDs. The inline doctor selects a row's symlink hunt
when the normalized old or current target falls under a planned or executed
prefix contributed by that row. A direct current-target or reverse-source
scope match remains sufficient, including for a dangling target's virtual
translation.

The standalone verifier reaches the same safety result through its independent
path. It renders each `paths = true` rule from `Identity` and `Rules`, applies
that rule's scope to the raw source `SurfaceSnapshot`, and derives the ancestor
prefixes those matching entries can trigger. It does not consume table row IDs,
plan provenance, or compiled hunt policies. This preserves the verifier's
independence while preventing the rewriter, doctor, and verifier from sharing a
target-directory-only scope blind spot.

### Mechanism-to-row mapping

The compiler uses the following mapping. `RENAME_FIELDS` means the existing
path-renamable identity fields: `package_name`, `repo_name`, `app_name`, and
`app_name_upper`.

| Provenance | Rewrite | Doctor hunt | Reset-stub hunt | Reset-path hunt | Regeneration hunt | Scope |
|---|---|---|---|---|---|---|
| Changed identity field in `RENAME_FIELDS` | content, path; field-specific `conservative` | content, path, symlink; rewrite matcher | content; `paranoid` with effective substring flag | path; `paranoid` with effective substring flag | content, path; `paranoid` with effective substring flag | all paths |
| Other changed identity field | content; field-specific `conservative` | content, symlink; rewrite matcher | content; `paranoid` with effective substring flag | path; `paranoid` with effective substring flag | content, path; `paranoid` with effective substring flag | all paths |
| Enabled derived `display_name` form | content; field-specific `conservative` | content, path, symlink; rewrite matcher | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Disabled derived `display_name` form | none | none | content; `paranoid` | path; `paranoid` | content, path; `paranoid` | all paths |
| Rendered `[[replace]]` rule | `literal`; content when `content`, path when `paths`; eligible symlink text derives from the path plan | content when `content`, path and symlink when `paths`; `literal` | content when `content`; `literal` | path when `paths`; `literal` | content when `content`, path when `paths`; `literal` | the rule's `files` globs |

Rows whose rendered source and destination values are equal are omitted.
Declared `[[replace]]` rows run before identity rows, matching the current
pipeline. Declared rows retain declaration order. Identity candidates retain
the current longest-source-value-first order.

Identity candidates are normalized by source and destination before rewrite
surfaces are expanded. For equal source and destination values, the first
ordered candidate owns all rewrite behavior. A later candidate adds provenance
and hunt policies, but it adds no matcher or rewrite surface. This preserves
the current global first-pair rule when, for example, `app_name` and
`display_name_spaced` both render `press` to `tool`: the later display matcher
must not newly rewrite `_press_` in content. The same rule also prevents a later
path-renamable field from introducing a path rewrite that the current global
deduplication drops.

After that normalization, candidates with the same matcher, source,
destination, rewrite surfaces, hunt policies, and scope coalesce into one row
and retain all provenance. The current display-family exception also remains:
if multiple `display_name` forms collapse to the same source text but render
different destinations, the first configured enabled form supplies the rewrite
destination. Later enabled forms and all disabled forms remain as hunt
provenance. If no form is enabled, the first canonical form supplies the unused
`to_value`.

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
rows with one guarded `SurfaceSnapshot`, defined in D2, to build `rename_plan`
to a fixed point. `build_plan()` and `apply()` consume that same plan; neither
independently re-derives rename candidates. The snapshot is accepted only when
the planner proves that position-zero resets, content rewrites, and path renames
leave Git's ignore inputs unchanged.

`RenamePlan` retains ordered steps rather than collapsing them into one
single-pass dictionary. Each step records a stable step ID, the old prefix, the
new prefix, the pass number, contributing row IDs, source entries that triggered
the prefix change, and predecessor step IDs. A predecessor is a step whose
successful move creates the intermediate coordinate used by the later step.
Apply executes a step only when every predecessor executed. A skipped or failed
predecessor therefore cannot cause a later step to rename unrelated content
that already occupies the intermediate path.

Each executable prefix step also retains a closure formed from two sources:
all no-follow worktree descendants and all `SurfaceEntry` index paths beneath
the prefix. A covered entry whose `index_kind` is `gitlink` causes immediate
refusal regardless of whether its `worktree_kind` is `directory` or `missing`;
the closure never descends into a checked-out gitlink. A non-directory
worktree node must appear in the authorized `SurfaceSnapshot`. Ordinary
directories are structural containers and are authorized by their descendants,
but an uninventoried empty directory is refused because Git cannot restore it.
Authorization findings — every absent node and every uninventoried empty
directory — are aggregated across the whole closure walk and raised together
in one `RenameClosureUnauthorized`, instead of raising on the first one hit.
The rendered message caps the list at 20 (sorted) entries plus a total/
truncated count; the typed exception's `findings` tuple, and the JSON emitted
under `--diagnostics-json`, carry every one of them uncapped.

This closure is a movement-safety guard, not a second consumer inventory. Apply
revalidates the closure and destination occupancy before the top-level press
executor performs its first mutation. A mismatch is runtime divergence and
raises `SafetyError`; apply does not continue with a partially valid static
plan.

The plan retains the snapshot's `visibility_inputs` for the same pre-mutation
revalidation. These fields preserve both the path coordinates and the
inventory lifecycle that produced them. A nested rename therefore records:

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
steps actually ran and why a blocked step did not run. Post-apply consumers use
that executed view; preflight and dry-run consumers use the full planned view.
These are two lifecycle views of one plan, not independently derived maps.

P06 changes the `apply()` order to content rewrite, fixed-point renames, then
symlink retarget. The retarget pass reads the executed rename-plan view and
must not maintain a second calculation of which existing targets were movable.
It locates each link by translating the source-inventory entry to its executed
post-rename path; Git's index may still contain the source path.

For an existing relative in-tree target, retargeting is eligible only when the
executed plan moved that target or one of its ancestors. The compiler also
builds non-executable, validated virtual translations for dangling relative
in-tree targets. A virtual translation applies the same fixed-point path-row
algorithm but can never authorize a filesystem move. It preserves the current
safe dangling-link behavior without recreating a private symlink rewrite
pipeline.

For an eligible target, the pass translates both the link location and target
location to their final coordinates and computes the final relative link text.
An existing target that the executed plan did not move is never retargeted.
This prevents a non-path identity field in a link target from silently
redirecting the link to unrelated content. Existing fail-safe behavior for
absolute, escaping, and ignored existing targets remains unchanged.

## D2 — One surface inventory, policies above it

The inventory returns raw path facts and an inventory-lifecycle guard:

```python
@dataclass(frozen=True)
class SurfaceEntry:
    rel: Path
    tracked: bool
    index_kind: Literal["file", "symlink", "gitlink"] | None
    worktree_kind: Literal["file", "symlink", "directory", "missing", "other"]


@dataclass(frozen=True)
class VisibilityInput:
    origin: Literal["gitignore", "info_exclude", "core_excludes_file"]
    path: Path
    kind: Literal["file", "symlink", "directory", "missing", "other"]
    sha256: str | None
    link_text: str | None


@dataclass(frozen=True)
class SurfaceSnapshot:
    entries: tuple[SurfaceEntry, ...]
    visibility_inputs: tuple[VisibilityInput, ...]
```

`SurfaceSnapshot.entries` is sorted by POSIX relative path and decodes Git path
bytes with `surrogateescape`, the Python error handler that preserves
undecodable bytes for round-trip filesystem access. The inventory module is the
only rebrand component that shells out to Git to enumerate tracked,
non-ignored untracked, and gitlink entries. `index_kind` records the Git index
mode when an index entry exists. `worktree_kind` is classified independently
without following symbolic links. The separate facts represent tracked
deletions and dirty replacements without misclassifying a missing path as a
regular file.

`VisibilityInput` records the no-follow node kind and bytes of every ignore
source that the hardened `git ls-files --exclude-standard` invocation uses:
worktree `.gitignore` files, `.git/info/exclude`, and the repository-local
`core.excludesFile` when configured. `sha256` is populated only for a regular
file read without traversing a symbolic-link ancestor. `link_text` is populated
only for a symbolic link. This distinction is required because Git does not
treat a `.gitignore` symlink like a regular file even when following the link
would produce identical bytes.

The walker does not accept a `copy`, `rewrite`, or `scan` mode. Those modes are
policies, not path facts. Pure selectors above the inventory preserve the
current contracts:

| Consumer | Selection from the raw inventory |
|---|---|
| Copy sandbox | Every worktree-present entry, excluding Git's own metadata |
| Content rewrite | Current rewrite exclusions and exact root-control exemptions |
| Rename planning | Rewrite-eligible regular files and symlinks; never missing entries, directories, other nodes, or gitlinks |
| Inline doctor | Exact root-control exemptions, built-in rewrite exclusions, and `verify_ignore` |
| Standalone verifier | Exact root-control exemptions, `verify_ignore`, and only outputs that are both declared regenerations and on the tool's regeneration-exemption cap |
| Regeneration/reset preflight | Entries whose `tracked` field is true |
| Symlink retarget | Entries whose `worktree_kind` is `symlink` |

This interface replaces `engine._git_listed`, `engine.iter_target_files`,
`engine.copy_paths`, `engine.scan_paths`, and `regen.tracked_paths`. Compatibility
adapters may preserve those names during the first pull request, but they must
all delegate to the one inventory. Exclusion logic stays in named selectors so
one consumer cannot silently change another consumer's coverage.

### Git-visibility stability gate

The snapshot is phase-stable, not assumed immutable merely because it was
captured once. Before accepting the snapshot, the top-level planner projects
every mutation that can change a visibility input: a position-zero reset, a
table-driven content rewrite, a path-row rename of the input itself, or an
ancestor-prefix rename that moves the input. Planning fails if the projected
path, node kind, existence, bytes, or link text differs from the captured
state. The diagnostic names the input and explains that changing Git visibility
would make the shared plan stale. A target must change and commit its ignore
policy separately before it can be pressed.

The top-level `_press()` mutation executor owns revalidation because
`apply_resets()` runs before `engine.apply()`. Immediately before
`apply_resets()`, `_press()` recaptures the visibility inputs, prefix closures,
and planned destinations. A mismatch raises `SafetyError` before a reset,
content rewrite, or rename runs. Once that check passes, apply does not ask Git
for a new rename-candidate set between content rewriting and renames; it
executes the snapshot-backed `RenamePlan`. Post-apply doctor and verifier scans
may capture a new snapshot because they observe the completed tree rather than
decide what apply was authorized to move.

This gate covers every in-process mutation that can change ignore behavior. It
also makes concurrent pre-apply changes to `.git/info/exclude` or a
repository-local `core.excludesFile` fail closed. The gate does not add a
table-specific field to `SurfaceEntry`, so the walker interface still survives
the D1 checkpoint.

The table requires no additional per-entry inventory field. Table scopes
operate on `SurfaceEntry.rel`; node-specific behavior dispatches on
`SurfaceEntry.index_kind` and `SurfaceEntry.worktree_kind`; tracked-only
preflights use `SurfaceEntry.tracked`; and rename coordinates live in
`RenamePlan`. Therefore the walker entry interface survives the table-needs
checkpoint and can land independently.

## D3 — One pipeline-stability validator

The second pull request replaces the current scattered plan-time guards with
one pure validator over rendered source-to-destination candidates. The
validator enforces two properties before any target write:

1. **Pipeline stability and termination.** On the content surface, one source
   literal has one destination meaning. A row's output must be stable under
   every later overlapping content row. It also must not emit an earlier
   overlapping row's source literal, because the earlier row will not run again
   and the doctor will reject the survivor. The first check rejects an ordered
   rewrite dependency; the second rejects a stale-source emission.

   Path rows have a stronger rule because the complete ordered path pipeline
   runs again on every rename pass: each path row's output must be stable under
   every overlapping path row, including itself and rows declared earlier. A
   static proof that two `files` glob languages do not overlap is insufficient.
   One row can move a path into the other row's scope on a later pass. A path
   scope exemption is valid only when target-specific reachability proves that
   no intermediate coordinate enters both scopes; the conservative validator
   may decline every glob-based path exemption.

   Target-specific overlap also includes shared rewritten prefixes. Two rules
   scoped to different leaves can still conflict when both leaves cause a
   change to the same ancestor component. If two reachable candidates assign
   different destinations to one source prefix, planning refuses the conflict
   even when the leaf-level `files` globs do not overlap.

   The validator builds the cross-row dependency graph by applying the
   potential receiving row's exact `MatcherSpec` to each output. It rejects
   every dependency. When dependencies form a cycle, the error reports the full
   cycle and every row's provenance. The target-specific `RenamePlan` simulation
   separately records every complete relative-path state and rejects a repeated
   state or a pass-bound exhaustion. That simulation catches context-dependent
   path behavior that row-local output comparison cannot see. Symlink text is
   derived from the validated final rename plan, not a third ordered rewrite
   pipeline.
2. **Path-component structural safety.** A path row's `from_value` cannot
   contain `/` or `\`, because the component-wise matcher can never observe a
   cross-component source. Its `to_value` cannot contain either separator,
   produce an empty component, produce `.` or `..`, or otherwise change the
   component count. These checks preserve the current source- and
   destination-side refusals.

The row-local checks see matches wholly inside `to_value`. They do not claim to
detect a content match that straddles surrounding file text and the inserted
output; design 0008 records that existing limitation. Target-specific path
simulation has full path context and therefore does not receive the same
exception.

The validator preserves current harmless cases: equal source and destination
rows are omitted; compatible duplicates are coalesced without losing their
scope or provenance; the same-source display-family exception keeps its first
configured enabled destination; hunt-only rows do not create rewrite
conflicts; and rows on disjoint rewrite surfaces do not conflict. Content rows
with demonstrably disjoint `files` scopes may avoid an output-dependency
conflict because content scope is evaluated at one unchanged coordinate. The
same proof may allow content rows with one source and different destinations,
which implements issue #45. A path rule receives a scope exemption only from
the target-specific reachability proof described above. The content-scope proof
is conservative: it must recognize disjoint finite sets of exact paths, and it
may treat wildcard-bearing glob pairs as overlapping unless their non-overlap
is proven. Validation errors name every conflicting `row_id` and its
provenance.

This validator intentionally tightens plan-time acceptance. The current engine
accepts some configurations where an earlier row's output feeds a later
content row, or a path row's output feeds a row that runs on the next rename
pass. Their results depend on row order or pass count, and a path cycle can
mutate until the 32-pass runtime bound fails after writes. P06 rejects these
configurations before any write. Existing configurations whose outputs are
stable under the rules above retain their current output. Existing validation
refusals remain refusals except issue #45's intentional acceptance of
demonstrably disjoint content scopes.

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
cover both when the declared rule enables both. Every identity policy carries
the effective `substring` flag from `Rules.substring_rewrite_fields`.

The final regeneration pass reruns the `regeneration` hunt policies for every
declared output. The final reset check still compares the file with its exact
approved stub bytes; it does not need another identity hunt policy.

### Standalone verifier

`verifier.py` receives source and destination `Identity`, `Rules`, and the
effective `VerifyConfig` field names and substring flags. Field names are
neutral scan configuration; pre-rendered field values are not. The verifier
independently derives values only for the configured fields. This preserves
design 0007's opt-in treatment of fields such as `author` and `email`.

For an identity field, the verifier uses `matcher.find_occurrences` with the
effective substring flag. For a rendered `[[replace]]` source, it uses
case-sensitive exact-literal occurrence matching on the rule's declared
surfaces and scope. It does not pass a rule literal through the identity
matcher. Sharing the raw surface inventory, executed path translations, and
neutral scope primitives is allowed because those facts do not decide what
identity occurrence counts as a leak.

The independence guarantee has an explicit boundary. Declared regenerated
outputs remain listed by `press verify` as not verified, so their post-command
and final-pass certification comes from the table-driven regeneration hunts.
The independent verifier covers non-exempt surfaces; it does not eliminate
correlated table risk for a declared regenerated output. This is the existing
regeneration-exemption tradeoff, now stated without claiming broader coverage.

## D5 — Independence guardrail

Design 0008 contains the binding dependency rule. P06 must enforce both the
module boundary and the data-flow boundary:

1. A structural regression test resolves the repository-local import graph
   rooted at `verifier.py`, including aliases and `TYPE_CHECKING` blocks. No
   module in that transitive closure may import table-consuming
   `substitutions`, `engine`, or `doctor` modules. Shared path translation,
   scope, root protection, symlink normalization, and scan selection therefore
   live in named neutral modules whose own import closures satisfy the same
   rule. The test parses `verify_cli.py` separately: it may call
   `engine.apply()` as orchestration, but it must not pass table-derived scan
   data across the `verifier.scan()` call boundary.
2. The same test rejects a `verifier.scan()` parameter or caller argument that
   supplies a `SubstitutionTable`, rows, precompiled identity values, rendered
   rule literals, hunt policies, or matcher dispatch. The permitted inputs are
   `Identity`, `Rules`, effective configured field names and substring flags,
   the surface snapshot, executed path translations, and neutral scan options.
3. A rule ablation removes one rendered `[[replace]]` row from the rewriter's
   table before sandbox apply. Its fixture uses a boundary-invisible literal
   such as `x{app_name}owned`. The verifier must independently derive the
   literal from `Rules` and report a `replace_rule` finding.
4. An identity ablation removes one identity row and leaves a glued or
   camel-case source occurrence that only the paranoid matcher detects. The
   verifier must independently derive the configured identity value and report
   that identity field.

All four checks are acceptance criteria, not optional documentation coverage.
The structural and call-boundary checks block direct and transitive data paths.
The discriminating ablations prove rule and identity independence even if a
future refactor hides shared data behind a new helper name.

The intended dependency boundary is:

```text
allowed:   verifier -> inventory, matcher, rules, safety,
                       neutral scope and path-translation helpers
forbidden: verifier -> substitutions, engine, doctor,
                       or any precompiled substitution data
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
- Preserve index and worktree facts separately for a tracked deletion and for a
  tracked file replaced by a directory.
- Prove that visibility revalidation distinguishes a regular `.gitignore` from
  a symbolic link to identical bytes.

### PR 2 — Pipeline-stability validator

- Move the scattered ambiguity, output-stability, termination, and structural
  checks behind one validator.
- Preserve output for every currently accepted stable configuration. Preserve
  every current refusal except issue #45's intentional relaxation for
  demonstrably disjoint content scopes. Add the intentional pre-write refusals
  for cross-row output dependencies and cycles.
- Report conflicts with provenance rather than tuple positions.
- Regress an identity output that emits an earlier declared-rule source and
  would otherwise fail the post-apply doctor.
- Regress two path scopes where one rename moves a path into the other scope,
  and accept same-source/different-destination content rules when their
  declared `files` scopes are demonstrably disjoint.

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
  source and multi-word destination case, plus an aligned `app_name` and
  `display_name` whose field-specific matchers treat `_press_` differently;
- current-path and reverse-source-path rule scope after an ancestor rename;
- rejection of a path output that feeds an earlier row, a two-row path cycle,
  a content output that feeds a later row, and a content output that emits an
  earlier row's doctor source;
- rejection when two leaf-scoped path rules assign different destinations to a
  shared ancestor prefix, and rejection of a path-row source containing `/` or
  `\`;
- pre-write rejection when a content rewrite, reset, direct path rename, or
  ancestor-prefix rename would change a Git visibility input and expose a
  previously ignored untracked path;
- pre-write rejection when a prefix move would carry an ignored untracked
  descendant, uninventoried empty directory, or gitlink, and when the live
  closure or destination diverges from the authorized plan; exercise both a
  checked-out-directory and an uninitialized-missing gitlink;
- predecessor gating when an occupied parent destination blocks a later-pass
  step whose intermediate coordinate already contains unrelated content;
- substring-aware identity hunts in reset content, reset paths, regenerated
  content, and regenerated paths;
- preservation of dangling-link translation through a virtual plan entry, and
  refusal to retarget an existing link for a changed non-path identity field;
- retargeting and leak detection when a scoped descendant triggers an ancestor
  rename but a symlink target names only that ancestor; require the standalone
  verifier to derive the trigger from `Rules` and the source snapshot rather
  than table or plan provenance;
- derivation of doctor, reset, and regeneration hunts from a newly added row;
  and
- rejection of direct or transitive verifier dependencies on table consumers,
  including both discriminating ablations described in D5.

## Rejected alternatives

### Combine the walker and table in one pull request

Rejected after the table-needs checkpoint. The table needs only `rel`,
`index_kind`, `worktree_kind`, and `tracked` from the walker. Combining them
would increase review scope without resolving an interface dependency.

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
- Every Git-listed target path is classified once per phase snapshot, while
  each consumer's exclusions remain explicit and independently testable. A
  no-follow prefix closure separately proves which filesystem nodes one
  directory rename would carry.
- A press that would change Git's ignore inputs, move a gitlink or
  uninventoried node through a prefix rename, or execute a plan that diverged
  from live state is newly refused before any write.
- An existing symlink target that contains a changed non-path identity field is
  no longer silently redirected. The link remains unchanged, and the inline
  doctor refuses the press if the source value survives.
- Configurations with order-dependent row outputs or cross-pass path cycles are
  newly refused before any write; stable configurations retain their current
  output.
- Plan-time and apply-time rename translation share one fixed-point derivation,
  closing the nested-target false refusal deferred from PR #62.
- The shared doctor can inherit a table defect. The structurally independent
  verifier remains a backstop for non-exempt surfaces. Declared regenerated
  outputs are explicitly reported as not verified and retain the existing
  correlated-risk tradeoff in their table-driven postconditions.
- Acceptance of this design makes P06 ready for task decomposition; this
  document does not decompose or implement the work.
