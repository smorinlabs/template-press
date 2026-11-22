# P13 — Hyphenated package-name false receipt

`press rebrand` must not write a receipt while a hyphenated package name survives.

### Notes
Approved design (Option C, 2026-11-22): rewrite the hyphenated form when
`[project].name` proves it is the package's real spelling. Otherwise detect it
and exit 1 with no receipt. When `repo_name` equals the hyphenated form, the
manifest name still follows `package_name`. `[rules] keep_hyphen_name` preserves
intentional mentions in declared files.

<!-- Idea state. Minimal by convention.
     Promote with `project-refine P13` when ready. -->
