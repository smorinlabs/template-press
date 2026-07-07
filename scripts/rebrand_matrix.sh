#!/usr/bin/env bash
# R1/R2/R3 acceptance matrix for the rebrand press (EMPIRICAL_BUGS.md,
# reborn as a repeatable harness). R3 presses a clone of THIS repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== R1 + R2 (live tests against a real py-launch-blueprint clone) =="
uv run pytest tests/rebrand/test_matrix.py -m live -q

echo "== R3 (self-press: a clone of this repo) =="
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# `git clone .` gives the clone a local-filesystem origin, which discovery's
# github.com regex never matches (owner/repo_name would come back
# unresolved) — reset origin to the real remote so discovery works the same
# way it would against an actual fork.
ORIGIN_URL="$(git remote get-url origin 2>/dev/null || true)"
git clone -q . "$WORK/self"
if [ -n "$ORIGIN_URL" ]; then
  git -C "$WORK/self" remote set-url origin "$ORIGIN_URL"
fi
cat > "$WORK/answers.toml" <<'EOF'
[answers]
package_name = "potato_launcher"
repo_name = "potato-launcher"
app_name = "potato"
author = "Potato Farmer"
email = "potato@example.com"
owner = "potatolabs"
EOF
uv run python -m template_press.rebrand.cli \
  --target "$WORK/self" --config "$WORK/answers.toml" \
  --accept-discovery --allow-dirty
echo "R3: exit $? — rebrand verified (receipt written)"
