---
name: rebrand-matrix
description: Run the R1/R2/R3 rebrand acceptance matrix to answer "did we
  break the press?". Use when the user asks to "run the matrix", "verify
  the press still works", "run the rebrand acceptance tests", or after any
  change to src/template_press/rebrand/.
---

# rebrand-matrix

The empirical harness from EMPIRICAL_BUGS.md as a repeatable check:

- **R1** — press a real py-launch-blueprint clone: must verify clean (or
  fail LOUDLY with a leak report; silence is the only unacceptable outcome).
- **R2** — mismatched source-config: must hard-stop (exit 2) before any
  writes, no receipt.
- **R3** — self-press a clone of this repo: must verify clean.

## Run

`just matrix` (live: clones py-launch-blueprint; needs network), or only the
pytest half: `uv run pytest tests/rebrand/test_matrix.py -m live -q`.

CI runs the same script weekly and on PRs touching the rebrand core
(.github/workflows/rebrand-matrix.yml).

## Interpreting failures

- R1 exit 1: the blueprint gained identity-bearing files the rules don't
  cover — read the leak report, extend rules/excludes deliberately.
- R2 exit ≠ 2: the mismatch guard regressed — this is the silent-corruption
  failure mode (EMP-01); fix before anything else ships.
- R3 exit ≠ 0: our own repo has un-pressable content — usually a new file
  that must be excluded or made identity-clean.
