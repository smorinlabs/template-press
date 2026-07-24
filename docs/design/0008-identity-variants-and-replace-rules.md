# 0008 — Identity Variants & Replace Rules (C/D/E gap fixes)

- **Status:** Accepted (codesign 2026-07-23)
- **Type:** Design / decision record
- **Created:** 2026-07-23
- **Applies to:** the rebrand engine's identity model and replace-rule
  mechanism (`src/template_press/rebrand/identity.py`, `engine.py`,
  `rules.py`, `doctor.py`)
- **Informed by:**
  [research 0005](../research/0005-scaffolder-identity-variant-handling.md),
  [research 0004 §5](../research/0004-py-launch-blueprint-conformance-gaps.md)

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

## Order of operations (engine.apply)

`[[replace]]` rules → boundary/substring token pairs (content), then
symlink retarget, then renames to fixpoint. Rules run first because a
rendered FROM may embed an identity token the token pass would rewrite
out from under it.

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
- A `paths = true` rule whose `files` glob is scoped under a directory that
  is itself renamed during the multi-pass rename fixpoint can diverge from
  what `--dry-run` predicted (glob matched against the current path each
  pass); `press verify`'s scanner is the backstop that catches any
  silently-dropped rename. Prefer unscoped or filename-anchored globs for
  paths rules.
