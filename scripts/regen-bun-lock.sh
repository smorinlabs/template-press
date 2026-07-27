#!/bin/sh
# Regenerate bun.lock FROM SCRATCH for the declared [[regenerate]] rule.
# `bun install` never rewrites an existing lockfile's workspace name
# (verified on bun 1.3.14: plain and --force both report "no changes" and
# keep the stale name when resolution is unchanged), so a pressed identity
# survives in bun.lock unless the lock is removed first.
set -e
# Refuse BEFORE the destructive step: check-tools resolves this script,
# not the bun inside it, so a missing bun must fail here with the lock
# still intact rather than after rm has consumed it.
command -v bun >/dev/null 2>&1 || { echo "regen-bun-lock: bun not found" >&2; exit 127; }
rm -f bun.lock
exec bun install
