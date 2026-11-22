# P16 — Explicit target languages (design)

- **Status:** Approved by the owner on 2026-11-22
- **Project:** P16
- **Merge order:** hyphen fix (P13), this guard (P16), TypeScript (P14), Rust (P15)

## Intent

`press rebrand` and `press verify` must not guess what a multi-language target
means. Today a target with a Python `pyproject.toml` and a `package.json` presses
and verifies with exit 0, and neither command mentions `package.json`. A clean
result therefore says nothing about the Node half of the repository.

## Goals

- Exit 2 with no writes when a target has several languages and declares none.
- Name the manifests found and print the exact line to add.
- Make `press rebrand` and `press verify` follow one committed declaration.

## Non-goals

- Rust/Cargo, TypeScript/Bun, or BAML target support.
- The hyphenated-name false receipt (P13).
- Publishing, or any push to `py-launch-blueprint`.

## Anti-goals

- A declaration that claims a check press did not run.
- A grandfathering exception for existing targets. This is a deliberate breaking
  change, shipped with a paste-ready fix and a release note.
- A later command refusing what an earlier command accepted.

## What counts as a language

Only root manifests that declare a project identity count:

| Manifest | Counts when | Language |
|---|---|---|
| `pyproject.toml` | it has a `[project]` table | `python` |
| `Cargo.toml` | it has a `[package]` or `[workspace]` table | `rust` |
| `package.json` | it has a non-empty string `name` | `node` |

A `pyproject.toml` with only `[tool.*]` does not count. A tooling `package.json`
with a `name` does count and must be declared.

## Declaration

```toml
# press/press-rules.toml
[rules]
languages = ["python"]
```

Listed languages are checked. Detected languages that are not listed are
explicitly ignored, and press prints them. The setting has no CLI flag, so the
two commands cannot disagree.

## Behavior

| Target state | Result |
|---|---|
| No counted manifest | Continues as today |
| One language, nothing declared | Continues as today |
| Several languages, nothing declared | Exit 2, no writes |
| Declared languages all have manifests | Checks those, prints ignored ones |
| Declared language has no manifest | Exit 2 |
| Declared language's manifest is a `[[remove]]` target | Exit 2 |
| `languages = []`, a duplicate, or an unknown value | Exit 2 |
| Declared `node` or `rust` before support lands | Exit 2, "not supported by this press version" |
| Root manifest is malformed, non-UTF-8, or not a regular file | Exit 2, never a traceback, never followed |

The `[[remove]]` row exists because `press verify` would otherwise refuse the
pressed result for a missing declared manifest.

## Approaches

1. **`[rules] languages` in the committed rules file (chosen).** Both commands
   read the same value, so parity holds by construction.
2. **A CLI flag.** Rejected: it can be passed to `rebrand` and forgotten on
   `verify`.
3. **Infer a primary language (`pyproject.toml` wins).** Rejected: this is the
   silent behavior the guard removes.

## Owner decisions

- **Blueprint (1A).** The matrix test adds `languages = ["python"]` to its
  disposable `py-launch-blueprint` clone only when the line is absent. After
  release, one blueprint PR upgrades press and adds the line together. The
  blueprint cannot declare first because released press versions reject an
  unknown `[rules]` key.
- **Unsupported languages (2A).** `node` and `rust` are reserved names that exit 2
  until the TypeScript and Rust PRs add them to `SUPPORTED_LANGUAGES`.

## Structure

- New module `src/template_press/rebrand/languages.py`: `KNOWN_LANGUAGES`,
  `SUPPORTED_LANGUAGES`, manifest detection, and declaration resolution. It must
  not import `rules`, `substitutions`, `engine`, `doctor`, or `verifier`.
- `rules.py`: add `languages` to `_RULES_KEYS`, validate it, and append
  `Rules.languages: tuple[str, ...] | None = None` as the last field because
  `Rules` is constructed positionally in places. `None` means undeclared.
- `cli.py` and `verify_cli.py`: run the guard before discovery reads a manifest.
- Manifests are read with the no-follow helpers in `safety.py`. JSON and Unicode
  decode failures are converted to `ValidationError`, because they are
  `ValueError`s that neither CLI's error tuple catches.
- Ignored-language notices go to stderr, so `--json` and `--diagnostics-json`
  keep stdout as a single JSON object.
- This repository declares `languages = ["python"]` for its R3 self-press.

## Left to the builder

Exact error wording beyond the required content, helper names, and test layout.
