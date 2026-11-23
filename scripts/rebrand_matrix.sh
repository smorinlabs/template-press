#!/usr/bin/env bash
# R1/R2/R3 acceptance matrix for the rebrand press (EMPIRICAL_BUGS.md,
# reborn as a repeatable harness). The pytest R3 presses a clone of THIS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== R1 + R2 + native R3 acceptance =="
# loadgroup keeps tests marked xdist_group on one worker. R1b and R3 share the
# user's uv and bun caches, so they must not regenerate lockfiles concurrently.
uv run pytest tests/rebrand/test_matrix.py -m live -q -n auto --dist loadgroup

echo "== npm, Bun, and pnpm end-to-end targets =="
# Each test keeps its package-manager cache inside its own tmp_path.
uv run pytest tests/rebrand/test_node_targets.py -m live -q -n auto --dist loadgroup

echo "== Cargo single-crate and workspace end-to-end targets =="
# Direct cargo commands keep CARGO_HOME in tmp_path. The press's declared
# `cargo update` uses the default Cargo home, so those tests share one worker.
uv run pytest tests/rebrand/test_cargo_acceptance.py tests/rebrand/test_cargo_lockfile.py -m slow -q -n auto --dist loadgroup
