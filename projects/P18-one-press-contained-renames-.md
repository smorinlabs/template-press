# P18 — One-press renames to names containing the source

Allow a new name that contains the old one, for every identity field.

### Open questions
- Can the post-press leftover scan, and the independent press verify, exempt exact destination spans without hiding a real leftover?
- Does today's two-press workaround leave a correct receipt and pass press verify?

### Notes
Today the stale-source check in src/template_press/rebrand/pipeline.py refuses these renames with exit 2 before any write, telling the operator to press in two steps via an intermediate identity.
Examples: acme-core -> acme-core-next; a Cargo name becoming zeta-acmeapp while app_name is acmeapp.
The check exists because the press confirms the old name is gone after writing, and an old name inside the new one looks left behind.
Origin: owner decision Q4.A on PR #158 (kept the rule there, tracked here).

<!-- Idea state. Minimal by convention.
     Promote with `project-refine P18` when ready. -->
