# P11 directory removals: frozen membership and explicit history

**Status:** implementation authorized after independent major review. The owner
adopted the exact two-part acceptance amendment with: “Yes, approve the
recommendation for decision 2.”

**Purpose:** support `[[remove]] dir = "research"` without deleting a file merely
because it appears under that directory after the removal plan was captured.

**Baseline:** `18946d5cf3de857da34b1677faff424b91a7a070`, branch
`feat/directory-removals`. P10 implementation and local review are complete at
this parent. P10 PR #122 is open and undergoing CI/review correction. The user
has explicitly authorized both P10 and P11 PR creation and merge when their
gates pass. The controller owns delivery. P12 remains a separate reassessment.

## Contract and reconciliation

The binding source is E5(c) of
`2026-09-01-press-improvements-g2p-design.md`, with historical implementation
Tasks 19–22 in `../plans/2026-09-01-press-improvements-g2p.md`. The six substantive
requirements remain: freeze tracked membership before mutation, reject directory
status changes including untracked files, refuse symlinks and gitlinks, remove
empty selected directories, record every selected file, and verify the recorded
expansion. Globs remain invalid. Existing file declarations retain their behavior.

The reviewed plan reconciles three historical instructions:

1. **Removal phase:** retain reset → rewrite/rename → removal → edits →
   regenerations. E5(c) explicitly leaves the earlier phase as a proposal.
   `substitutions.py:589–627` captures and revalidates rename closures; deleting
   members before that revalidation causes legitimate plans to refuse. P11 does
   not redesign projected closures. Verify retains its existing sandbox sequence
   of rewrite/rename → captured reset stubs → removals. That reset-order difference
   is existing behavior, not claimed phase parity.
2. **Inbound-rename acceptance:** replace only the impossible production fixture
   in E5(c)/Task 21 with the exact two-part acceptance below. Current substitutions
   rewrite individual components, refuse separators, and rename whole nodes to
   absent sibling destinations. They cannot move an outside file into an existing
   selected directory. Expanding rename semantics is out of scope. This is a
   reviewed acceptance clarification adopted by the owner answer recorded above.
3. **Native migration:** retain explicit `projects/P01…P12` file declarations and
   `projects/.gitkeep`. Replace only research file declarations with
   `dir = "docs/research"`. Historical Task 22 would remove the placeholder that
   the current `PROJECTS.md` stub deliberately preserves. This migration preserves
   that scaffolding without adding exclusions or special `.gitkeep` semantics.

Replacement acceptance text:

> Production CLI acceptance: a legal noncolliding `[[replace]]` rename of the
> selected directory must unlink exactly the frozen dry-run members translated
> through successful renames, record each member in source coordinates, preserve
> an outside nonmember, remove emptied directories, and pass `press verify` on
> the pressed target. A separate lower-level test injects an outside nonmember
> into the translated selected directory after successful rewrite/rename and
> immediately before removal. Only frozen members are unlinked; the injected file
> and its nonempty parent survive. A deliberately broken removal implementation
> that re-expands at removal time must fail that lower-level oracle.

The lower-level injection is test-controlled movement. It does not establish
that the full CLI accepts concurrent filesystem mutation. The existing mid-apply
`SafetyError`/no-success-receipt requirement remains unchanged.

## Global constraints

- Python >=3.13; shipped package uses only the Python standard library.
- Preserve unrelated code and all existing file-only removal behavior.
- Exactly one of `file` or `dir` is declared; `reason` is required and printable.
- No globs, exclusions within directory removals, special `.gitkeep` handling,
  reparenting, directory merging, or new removal phase.
- Freeze membership once before any target mutation. Never enumerate filesystem
  contents or Git membership to choose deletions during removal execution.
- Never delete untracked or ignored nonmembers by directory expansion.
- Retain existing static no-follow/containment guards. Do not claim that P11
  closes the documented concurrent ancestor-swap residual in `safety.py`.
- Every actual implementation commit requires `PYTEST_ADDOPTS='-n 8' just check`.
  Any change under `src/template_press/rebrand/` additionally requires
  `just matrix`. Native R3 clones committed HEAD; commit its native declaration
  before claiming its acceptance test exercised that declaration.
- Use conventional lowercase commit subjects. Do not publish intermediate commits.

## Data model and source/current coordinates

A **declaration** is the target-authored request. A **frozen plan** is the exact
set of file operations authorized by this invocation. An **audit path** is the
source-coordinate file path when a member was first selected in its latest fresh
expansion. A **current path** is that exact member's latest known location.

Keep `RemoveRule(file: str, reason: str)` and `Rules.remove` file-only. Introduce
`RemoveDirRule(dir: str, reason: str)` and `Rules.remove_dirs`, appended after
`clean` so all existing positional `Rules` constructions retain their bindings. Parse/select both
through the existing environment-independent platform machinery. An unresolved
directory is never represented as `RemoveRule(file=None)` or as a fake file.

Put immutable shared records in `removal_types.py` to avoid a receipt/engine/
removal import cycle:

```python
@dataclass(frozen=True)
class RemovalMember:
    file: str
    current_file: str
    reason: str
    source_dir: str | None = None
    missing_ok: bool = False


@dataclass(frozen=True)
class DirectoryRemoval:
    dir: str
    current_dir: str
    reason: str
    members: tuple[RemovalMember, ...]


@dataclass(frozen=True)
class RemovalPlan:
    files: tuple[RemovalMember, ...] = ()
    directories: tuple[DirectoryRemoval, ...] = ()
    retained_history: tuple[DirectoryRemoval, ...] = ()

    @property
    def members(self) -> tuple[RemovalMember, ...]:
        return self.files + tuple(
            member for directory in self.directories for member in directory.members
        )
```

`retained_history` carries inactive directory rows for receipt preservation only;
it never contributes deletion members. `source_dir` belongs to each directory
member. A later real press may add a
member whose actual source root differs from older members' source roots. This
avoids inventing an original spelling by reverse-prefix guessing. `missing_ok`
is transient authorization from validated history and is not serialized.

Before the current invocation's rename, `current_file` names the actual target
path. After successful renames, translate each `current_file` and `current_dir`
through `report.renamed`; keep `file` and `source_dir` unchanged. Never translate
historical audit paths as if they were current paths.

## Parsing and overlaps

Use `_declared_rel_path`, `_reject_reserved`, and `_control_alias_key` for the
existing contained-path and filesystem-alias policies. Explicitly reject glob
characters `*?[` in a directory declaration. Reject `dir = "press"` and any
ancestor/alias of a root control path, as well as ordinary reserved paths.
Expanded members receive the existing file-remove visibility-input protection:
no `.gitignore`, `.gitattributes`, `.gitmodules`, or configured Git visibility
input can be removed. Compare captured visibility inputs by exact resolved path
and nonzero device/inode identity, following existing configured-input handling.
Apply the same checks to active Git configuration sources and present declared
include candidates from the captured snapshot. This includes empty and inactive
conditional includes. Directory removals must not delete configuration that
informed planning or that Git can activate later; missing or disjoint include
paths remain allowed.

Before platform selection, reject overlapping declarations when their platform
sets intersect. A directory covers itself and descendants under conservative
alias comparison. Reject directory-directory nesting/duplicates, directory-file
removal overlap, and directory overlap with reset/edit/regenerate targets or
reset `stub_file` sources. Containment checks include a file writer naming the
directory itself or an ancestor of it. Platform-disjoint declarations remain
valid. Validate current physical locations again after historical root resolution
and against planned successful-path candidates: translated aliases cannot turn
separate declared operations into two writers of one path.

## Fresh plan and filesystem policy

`plan_removals(target, rules, *, source, receipt_text=None, mode="press")`
returns `RemovalPlan` or raises `SafetyError`/`ValidationError` before mutation.
For file declarations, retain the current clean/tracked/regular/missing-history
rules and legacy tolerant receipt behavior. `plan_removals` constructs their
exact member records; the CLI retains its existing aggregated file preflight
call instead of turning legacy file problems into earlier exceptions. Directory history uses the strict
reader described below.

For a fresh directory expansion:

1. Resolve the declared root using exact metadata, if present. Without metadata,
   the declared directory must exist as a real directory. A missing declaration
   is stale configuration, including a nonexistent root with zero tracked files.
2. If a prior `current_dir` differs from `dir`, and both locations exist, refuse
   ambiguity. If only the prior current root exists, select it. If only the
   declared root exists while history points to a different root, refuse; the
   author must restore a coherent root or intentionally revise the old declaration
   and history. Do not silently retarget history. If neither exists,
   reuse valid complete history and translate its locations through later ancestor
   renames; do not require already-successful deletions to become clean again.
   A recorded pathname alone does not authorize staged blob or mode changes;
   only the same ordinary deletion states accepted below qualify as history.
3. Capture one Git surface snapshot; take sorted tracked files beneath the exact
   selected root. Each selected root component must match its stored filesystem
   spelling. Refuse alternate-spelling declarations and index paths that reach
   that same physical root through a different root spelling. Do not combine
   physically distinct case-sensitive trees through a portable alias key.
   Reject tracked symlink/gitlink entries even if an inventory exclusion would
   hide them from rewriting. Refuse missing selected files unless that exact
   current path is a completed member of matching directory history.
4. Check the selected root and all present descendants without following links.
   Refuse symlinks, Windows junctions, gitlinks, and other non-regular leaf kinds.
   Do not walk `.git` of an embedded repository; refuse that boundary. Use
   `Path.is_junction()` on supported platforms as well as `lstat()` checks.
5. Run hardened, literal-pathspec `git --no-optional-locks status --porcelain=v1 -z
   --untracked-files=all -- <root>`. Any entry, including `??`, refuses, except an
   exact missing recorded member with status ` D` or `D ` and no second rename
   path. Parse NUL records; never split filenames on whitespace. A rename/copy,
   conflict, modified file, untracked file, or unrecognized status never receives
   the deletion-history exception. Use one additional hardened `git ls-files -v -z -- <root>` query to reject
   lowercase or `S` tags on present selected members, preserving the existing
   assume-unchanged/skip-worktree refusal. Both directory queries pin
   `--work-tree=<target>` and use literal pathspecs. This controller refinement
   avoids two subprocesses per member without changing legacy file helpers.
6. Ignored ordinary files are not selected unless tracked. They may remain and
   cause empty-directory cleanup to retain their parent. Ignored symlinks and
   unsafe nodes still refuse. A tracked ignored file is still a member. An
   untracked ordinary file refuses even under `--allow-dirty`.
7. Freeze all present tracked members with `file == current_file`, `source_dir`
   equal to the selected physical root, and the declaration's reason. Retain
   absent prior members at their exact recorded locations with `missing_ok=True`.
   A fresh present member replaces history at the identical current path. Reject
   duplicate/alias-ambiguous current paths and conflicting audit keys. This
   retains prior deletion evidence while allowing a later explicit press to add
   newly committed files. No permanent one-time declaration is introduced.

An existing empty selected root is valid and has explicit empty history. Cleanup
attempts that root. A pre-existing empty child directory that is not a selected
member's ancestor remains; the selected root then remains nonempty. This bounded
policy avoids discovering more removal targets after planning. Dirty untracked
empty directories do not appear in Git status but are preserved by the same rule.

Planning precedes `build_plan` in `cli.main`, and precedes the direct `_press`
fallback. The frozen plan feeds excluded-file gates, plan rendering, command-path
conflicts and warning coverage. No second expansion is allowed while rendering or
applying. The engine's rewrite inventory and closure remain unchanged.

## Removal execution and failure

`apply_removal_plan(target, plan, renamed) -> list[str]` walks only `plan.members`.
For each member, translate its exact current path through successful renames,
repeat containment/ancestor/regular-file guards immediately before unlink, and
skip absence only when `missing_ok` is true. Return only paths actually unlinked,
so `ApplyReport.removed` counts current work rather than inherited history.

After all member unlinks succeed, derive cleanup candidates from each translated
`current_dir` and parent paths of its exact translated members, bounded by that
root. Sort deepest first. Guard each candidate without following links, and call
`os.rmdir`. Ignore only absence and `ENOTEMPTY`/`EEXIST`; propagate permission,
wrong-kind and other failures. Never use `rmtree`, `git clean`, `glob`, a walk, or
fresh Git expansion at this stage. Empty file-removal parents remain untouched,
preserving file-only behavior.

Partial failure is not rollback. Already-rewritten/unlinked paths may remain
changed; existing CLI failure diagnostics and Git recovery guidance apply. The
prior receipt is invalidated before mutation. No new success receipt is written
if unlink, cleanup, commands, or the final doctor fails.

## Receipt schema, validation and renewal

Retain one `[[press.remove]]` row per directory member, using `file` and `reason`.
Keep unrelated legacy file rows exactly as the current writer does. Add complete
versioned metadata even for a zero-member directory:

```toml
[press]
verified = true
remove_dirs_version = 1

[[press.remove_dir]]
dir = "research"
current_dir = "archive"
reason = "template research"
complete = true
members = [
  { file = "research/one.md", source_dir = "research", current_file = "archive/one.md" },
  { file = "archive/new.md", source_dir = "archive", current_file = "archive/new.md" },
]
```

The corresponding flat rows name `research/one.md` and `archive/new.md`. Those are
actual source-coordinate audit paths from their respective fresh selections.
Reason belongs to the directory row and must agree with every associated flat
row. An empty directory writes `members = []`; a missing key does not mean empty.

`directory_history_from_receipt(text, source) -> tuple[DirectoryRemoval, ...]`
returns `()` if directory metadata is absent. If a directory metadata key or
version is present, malformed TOML or malformed metadata is a hard refusal.
Require `receipt_binding_problem(text, source) is None`: verified success and
exact destination/current-source identity equality. This is identity binding,
not repository provenance, authentication, or tamper resistance.

**Controller routing refinement:** presence-only decisions in `check_preconditions`
and the equal-identity branch use `receipt_present(target)`, without reading
receipt contents. Once rules are loaded, an active directory declaration selects
one bounded no-follow receipt text read, reused for planning and later history.
No-active-directory rules preserve the existing legacy read and malformed-file
history tolerance. If that legacy text parses as recognized directory metadata,
strict identity/schema/size/count validation and retention apply before use.
Discovery through the legacy path does not guarantee the active-directory
pre-read allocation bound: inactive metadata inherits the existing legacy
allocation residual, never wider deletion authority. Do not add streaming TOML
classification or uniformly cap legacy file-only receipts.

Use a bounded no-follow receipt read for callers with directory declarations:
16 MiB maximum input bytes, 1,024 directory rows, 100,000 members across rows,
4,096 UTF-8 bytes per path/reason, and at most 20 displayed error paths. Reject
unknown schema versions, wrong/bool-as-int versions, missing/unknown directory
or member keys, duplicate/alias-equivalent directory/current roots, overlapping
current roots, duplicate/alias-equivalent member audit/current paths, unsafe
paths, a member outside its own `source_dir`, a current member outside its
`current_dir`, incomplete rows, missing/duplicate/conflicting flat rows, and
metadata reason conflicts. Check raw flat rows before the tolerant reader can
collapse duplicates. Keep the existing legacy reader unchanged for file-only
receipts and file declarations. Directory parser limits apply equally to writer
output, before mutation when a frozen plan would exceed them.

The output-size preflight includes the complete receipt envelope and every
planned phase, clean, exemption, removal, and retained-history row. It shares
serialization with the writer. Count fields reserve the maximum decimal width
of a Python list length; translated current paths use a bound derived from the
frozen rename map, including skipped shortening steps. This conservative budget
can refuse a near-limit receipt whose eventual counts or executed renames would
produce fewer bytes. Dry-run and real press use the same budget before source
writes or prior receipt invalidation. Direct directory `_press` calls enforce
it before their first write. The final writer repeats the complete limit check;
legacy file-only receipts keep their existing uncapped behavior.

The preflight separately bounds the raw UTF-8 lengths of `current_dir` and each
`current_file` against the 4,096-byte field limit. For component-count-preserving
rename maps, each component's bound is the maximum width reachable through
same-position component substitutions. Sum those widths and the unchanged
separators. Ignore parent correlations conservatively, terminate graph cycles,
and do not charge paths that match no initial old prefix. This may refuse a
near-limit path even if every rename would execute and its final value would fit.
Unrelated sibling renames must not multiply an ordinary path's field budget.
For arbitrary depth-changing maps supplied to the receipt helper, use the raw
prefix-growth bound over at most the mapping's entry count; that fallback is
coarser and is not used by the component-count-preserving production compiler.
This field check precedes the same mutation boundaries as the complete-output
budget. It changes neither destination-occupancy skips nor removal membership.

Use all validated directory metadata to retain absence authorization, including
rows whose declarations are no longer active. They cannot authorize new
expansion or delete files without an active matching declaration. Re-emit their
history with translated current locations when a later successful press changes
an ancestor. Refuse a new active declaration whose alias/current root conflicts
with inactive history, rather than guessing which generation it replaced.

For an active declaration, the latest accepted reason replaces its prior
reason in the directory metadata and associated flat rows. Missing history-only
members remain audit records, not newly removed counts. New present members must
satisfy the fresh clean/tracked gate. This policy makes ordinary verification
stable while permitting deliberately renewed real presses.

## Verification

Plan directory removal against the real target before constructing the sandbox.
If valid complete matching history exists for an active declaration, `mode=
"verify"` uses exactly those members and current locations. It never enumerates
that directory to add members and does not run the fresh directory cleanliness
check. Previously removed tracked files can therefore remain unstaged deletions.
New tracked/untracked ordinary files remain in the sandbox and its scanner.
Static unsafe root/member paths still refuse before a destructive sandbox action.
Check those recorded roots and members against current captured Git visibility
and configuration inputs as well, without expanding the recorded selection.

Without history, verify freezes a fresh directory expansion against the real
target using the same clean/safety rules as a fresh press. A missing root without
complete history refuses. Metadata is never inferred from flat file rows.

Carry the frozen plan across `make_sandbox`, run the existing sandbox rewrite and
reset modeling, then call `apply_removal_plan` with the sandbox report's successful
renames. `current_file` starts in real-target coordinates and is translated once
through this sandbox run. Do not reread an unbound sandbox receipt, expand a
sandbox directory, translate `member.file`, or bypass the scanner for new files.
Retain legacy file-only verification behavior through its existing branch.

## Implementation and review map

| Historical task | Concrete task | Reviewable deliverable |
| --- | --- | --- |
| 19 | This design plus Task 1 entry gate | Reconciliation and phase decision |
| 20 | Tasks 1–2 | Typed declarations, parser overlap safety, frozen planner |
| 21 | Tasks 3–5 | Bounded history, removal executor, CLI/verify integration and discriminating controls |
| 22 | Task 6 | Research-only native migration, docs and committed-head acceptance |

The companion implementation plan supplies interfaces, concrete tests, RED/GREEN
commands, controls, and the requirement-to-test matrix. Implementation is
authorized and underway. This design describes the contract; passing tests,
implementation commits, and PR delivery remain separate evidence.
