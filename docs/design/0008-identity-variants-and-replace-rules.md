# 0008 — Identity Variants & Replace Rules (C/D/E gap fixes)

- **Status:** Accepted (codesign 2026-07-23)
- **Type:** Design / decision record
- **Created:** 2026-07-23
- **Applies to:** the rebrand engine's identity model and replace-rule
  mechanism (`src/template_press/rebrand/identity.py`, `engine.py`,
  `rules.py`, `doctor.py`)
- **Informed by:**
  [research 0005](../research/0005-scaffolder-identity-variant-handling.md),
  [research 0004 §5](../research/0004-py-launch-blueprint-conformance-gaps.md),
  [design 0009](0009-substitution-table.md)

## Decisions

1. **`display_name` — optional 7th identity field** (sec-01 ch-01-a).
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
- **Historical, fixed by the map-driven retarget below:** a `paths = true`
  rule whose `files` glob was scoped under a directory that was itself
  renamed during the multi-pass rename fixpoint used to be able to diverge
  from what `--dry-run` predicted. A narrow glob (e.g.
  `files = ["docs/*/data.txt"]`) could satisfy the rename pass, which
  scope-matched the rule against the FILE's own posix (`_renamed_rel`), but
  miss the retarget pass, which scope-matched the SAME rule against the
  link's TARGET/directory posix (`_retarget_symlinks`) — leaving a symlink
  pointing at that directory dangling, undetected by either `doctor.find_leaks`
  or `press verify` (both reused the same predicate). The map-driven
  retarget (`_retarget_planned_symlinks`) closed this: symlinks are now
  retargeted from the actual executed `(old -> new)` rename map instead of
  re-evaluating the rule's scope predicate a second time, so a narrowly
  scoped `files` glob on a `paths = true` rule is safe — the earlier advice
  to prefer unscoped globs as a workaround no longer applies.
- **Straddling matches (cycle 10):** `rendered_replace_rules`'s rendered-TO
  stability check (commit `9d347d3`) catches every mutation of a rule's
  rendered TO that lies wholly WITHIN that TO. A match that STRADDLES the
  boundary between surrounding file content and the inserted TO (context
  `"x"` + TO `"bar_data"` forming `"xbar"`, which matches a changed
  `package_name` `"xbar"` -> `"qq"`) is content-dependent and not checkable
  at plan time — not a claim of impossibility, just outside what a
  plan-time check can see.
- **Symlink retarget's map-driven refactor (cycle 10):** the principled fix
  for the retarget predicate (`_retarget_symlinks`, commit `a0f0f98`) is to
  run renames first and retarget links from the actual `(old -> new)` rename
  map, eliminating the second derivation of "does this rule govern this
  path" entirely. Design 0009 accepts this change for P06 PR 3. It requires
  reordering `apply()` and using the source surface inventory to locate links
  in the post-rename tree while Git's index still holds pre-rename paths. A
  further predicate edge no per-link check closes: a rule's `files`
  scope is evaluated against the FILE posix in `_renamed_rel` but the
  DIRECTORY posix in retarget, and the two can disagree — evidence that
  predicate variants will keep leaking until the refactor lands.
