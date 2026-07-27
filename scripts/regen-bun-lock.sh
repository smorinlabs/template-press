#!/bin/sh
# Regenerate bun.lock FROM SCRATCH for the declared [[regenerate]] rule.
# `bun install` never rewrites an existing lockfile's workspace name
# (verified on bun 1.3.14: plain and --force both report "no changes" and
# keep the stale name when resolution is unchanged), so a pressed identity
# survives in bun.lock unless the lock is removed first.
set -e
rm -f bun.lock
exec bun install
