#!/usr/bin/env bash
# ITM-006 — gitleaks wrapper. Single entry-point for hooks, CI, manual scans.
# Modes: --staged (commit-time, staged diff) | --range (pre-push, upstream range).
# Decided round 2.

set -euo pipefail

MODE="${1:-}"
CONFIG=".gitleaks.toml"

usage() {
    cat >&2 <<'EOF'
Usage: scripts/check-gitleaks.sh [--staged|--range]
  --staged   Scan staged changes only (pre-commit hook mode).
  --range    Scan commits not yet on the upstream (pre-push hook mode).
             A new branch is compared with origin's default branch.
EOF
    exit 2
}

require_gitleaks() {
    if ! command -v gitleaks >/dev/null 2>&1; then
        echo "FAIL: gitleaks not on PATH — install via scripts/install-gitleaks.sh" >&2
        exit 127
    fi
}

scan_staged() {
    require_gitleaks
    if gitleaks protect --staged --config "${CONFIG}" --no-banner --redact; then
        echo "PASS: no secrets in staged diff"
    else
        echo "FAIL: gitleaks found secret(s) in staged diff" >&2
        exit 1
    fi
}

scan_range() {
    require_gitleaks
    local base range ref
    base=""
    for ref in '@{u}' origin/HEAD origin/main; do
        if git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null; then
            base="${ref}"
            break
        fi
    done
    # With no remote base, every commit is unpushed, so scan them all.
    range="${base:+${base}..}HEAD"
    if gitleaks detect --config "${CONFIG}" --no-banner --redact \
            --log-opts="${range}"; then
        echo "PASS: no secrets in ${range}"
    else
        echo "FAIL: gitleaks found secret(s) in ${range}" >&2
        exit 1
    fi
}

case "${MODE}" in
    --staged) scan_staged ;;
    --range)  scan_range ;;
    *) usage ;;
esac
