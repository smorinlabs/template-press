# P07 — Platform-conditional declared commands

- **Status:** `[?]` idea

Platform-scoped rules; only matching platform triggers

### Open questions

- Q: A `platforms` key on each `[[regenerate]]`/`[[reset]]` entry (e.g.
  `platforms = ["darwin"]`), or three parallel entries for the same `file`
  where the platform selects one? The parallel-entry form collides with the
  duplicate-target ban at config load, which would need a platform-aware
  relaxation.

### Notes

Born from PR #62's Windows CI run: declared commands are target-declared and
inherently platform-specific — a POSIX `sh` regeneration script is a
legitimate declaration that simply cannot resolve on Windows, and the engine
already reports exactly that (missing tool, loud plan-gate refusal;
`press check-tools` shows it before pressing).

The mechanism composes with the existing contracts for free: with
platform-scoped entries, the §6 excluded-file preflight evaluates
**per-platform** — if `bun.lock`'s only declared command is POSIX-scoped and
the press runs on Windows, the file has no neutralization *there*, so the
press refuses loudly (exit 2, naming the file), which is already the correct
behavior. `check-tools` likewise reports only the entries active on the
current platform.

Example shape: the same regeneration declared three ways (darwin / linux /
win32) with only the matching entry triggering — e.g. an sh script on POSIX
and a `.bat`/`.exe` shim on Windows.

<!-- Promote with `project-refine P07`. -->
