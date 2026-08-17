#!/usr/bin/env bash
# R1/R2/R3 acceptance matrix for the rebrand press (EMPIRICAL_BUGS.md,
# reborn as a repeatable harness). The pytest R3 presses a clone of THIS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== R1 + R2 + native R3 acceptance =="
uv run pytest tests/rebrand/test_matrix.py -m live -q
