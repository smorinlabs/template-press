---
name: press-target
description: Run template-press against a target repo — dry-run preview,
  identity validation, apply, verify, receipt. Use when the user says
  "press <repo>", "rebrand <repo> with template-press", "run the press on
  <path>", or "point template-press at <target>".
---

# press-target

Rebrand an external target repo with the press. The tool validates the
target's committed source-config against discovery and REFUSES to run on
mismatch; a completed run is verified leak-free before a receipt is written.

## Steps

1. Preconditions: target is a git repo with a clean tree.
2. Preview (never skip): if the target ships a
   `press/press-answers.example.toml` template, copy it first and fill in
   the destination identity:
   `cp <TARGET>/press/press-answers.example.toml press-answers.toml`
   Then run the dry run:
   `press rebrand --target <TARGET> --config <press-answers.toml> --dry-run`
   (in a dev checkout of template-press: `uv run press rebrand …`)
3. If the target has no `press/press-source.toml`, review the discovery proposal
   printed by the dry run; re-run with `--accept-discovery` only after the
   user confirms the identity is right.
4. Apply: same command without `--dry-run`.
5. Interpret exit codes: 0 = verified + receipt written; 1 = leaks found,
   NO receipt (the target is already rewritten — restore it first:
   `git -C <TARGET> checkout . && git clean -fd`; then fix the root cause,
   or — for surviving identity that is VALID to keep, e.g. vendored code or
   historical docs — add its directory NAME to both `extra_exclude_dirs`
   (skips rewriting) and `verify_ignore` (skips the leak scan) in
   `press/press-rules.toml`, and press again from a clean tree; do NOT re-run
   with `--force` as the remedy); 2 = precondition/mismatch (report, do not
   retry blindly).
6. On success the press also refreshes `<TARGET>/press/press-source.toml` to the
   NEW identity (so a future re-press starts from a valid baseline). Show
   the receipt (`<TARGET>/press/press-receipt.toml`) and remind the user to
   review `git -C <TARGET> status` — the receipt and a first-run
   source-config are new/untracked files that `diff --stat` won't show —
   then commit in the target.

## Answers file shape

```toml
[answers]
package_name = "new_pkg"
repo_name = "new-repo"
app_name = "newcli"
author = "Jane Dev"
email = "jane@example.com"
owner = "janedev"
```
