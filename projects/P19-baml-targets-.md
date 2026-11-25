# P19 — BAML targets

Press BAML repos: regenerate the client, refuse glued old names before writing

### Notes
Design approved 2026-11-25: docs/superpowers/specs/2026-11-25-baml-targets-design.md (scope (i), undeclared-client refusal A).
Branch feat/baml-targets, worktree ~/c/template-press-baml-targets.
Behavior change: targets that pre-press `press verify` already flags now exit 1 at press time; tracked BAML clients with no regenerate rule exit 2.

<!-- Idea state. Minimal by convention.
     Promote with `project-refine P19` when ready. -->
