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
2. Preview (never skip):
   `uv run python -m template_press.rebrand.cli --target <TARGET> --config <ANSWERS.toml> --dry-run`
3. If the target has no `.press/source.toml`, review the discovery proposal
   printed by the dry run; re-run with `--accept-discovery` only after the
   user confirms the identity is right.
4. Apply: same command without `--dry-run`.
5. Interpret exit codes: 0 = verified + receipt written; 1 = leaks found,
   NO receipt (show the leak report; fix or add `.press/rules.toml`
   excludes for generated files, then re-run with `--force`); 2 =
   precondition/mismatch (report, do not retry blindly).
6. Show the receipt: `<TARGET>/.press/receipt.toml`, and remind the user to
   review `git -C <TARGET> diff --stat` and commit in the target.

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
