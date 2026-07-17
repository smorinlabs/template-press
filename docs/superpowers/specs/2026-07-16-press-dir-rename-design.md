# Press control-file rename: `.press/` → `press/` with `press-` prefix

- **Date:** 2026-07-16
- **Status:** Approved (brainstorming) — ready for implementation plan
- **Project:** P03 (external-target rebrand press)
- **Type:** Breaking change to the on-disk target contract

## Problem

template-press writes and reads its per-target control files under a hidden
`.press/` directory with short names (`source.toml`, `rules.toml`,
`receipt.toml`). Two discoverability problems follow:

1. **The hidden directory is invisible.** A plain `ls`, a file tree in
   template files, or a glance at the local working area does not show
   `.press/`. Users and agents don't see that a repo carries press state.
2. **Short names are not uniquely greppable.** A bare `source.toml` or
   `rules.toml` collides with unrelated files and is hard for an agent to
   locate deterministically — especially since the files live one level
   down in a subdirectory, a different context that is easy to miss. A
   repo may hold several `*.toml` files; nothing marks which belong to the
   press.

## Goal

Make the press control files visible and uniquely identifiable to both
humans and agents:

- A **visible directory** named `press/` (no leading dot).
- A **`press-` filename prefix** so each file is unique across a repo,
  greppable deterministically, and self-evidently tied to the `press` CLI
  command ("it says press — it's for the press").

## New contract

| Old (hidden dir, short names)   | New (visible dir, prefixed names)      |
|---------------------------------|----------------------------------------|
| `<target>/.press/source.toml`   | `<target>/press/press-source.toml`     |
| `<target>/.press/rules.toml`    | `<target>/press/press-rules.toml`      |
| `<target>/.press/receipt.toml`  | `<target>/press/press-receipt.toml`    |

The TOML table names inside each file are unchanged: `[identity]` in
press-source.toml, `[answers]` in the answers file, `[rules]` in
press-rules.toml, `[press]` in press-receipt.toml. The answers file passed
via `--config` is unaffected — it is an arbitrary caller-supplied path, not
a fixed target artifact.

## Decisions

- **Layout:** visible `press/` directory containing `press-`-prefixed files
  (`press/press-source.toml`, etc.). Chosen over flat root-level files and
  over a visible dir with short names, because it satisfies both goals at
  once: the folder is visible in listings, and each filename is uniquely
  greppable.
- **Backward compatibility: clean break.** The tool recognizes only the new
  names. No `.press/` fallback code. A target already pressed under the old
  scheme reads as unpressed until its directory is renamed by hand
  (`git mv .press press` plus the three file renames). This matches the
  project's "no backwards-compat shims unless asked" rule and carries
  near-zero risk: there are effectively no live externally-pressed targets
  yet. The break is recorded in the changelog via a breaking-change commit.

## Changes

### Behavioral (4 spots)

- `src/template_press/rebrand/config.py:15` —
  `SOURCE_CONFIG_REL = Path("press") / "press-source.toml"`
- `src/template_press/rebrand/rules.py:16` —
  `RULES_REL = Path("press") / "press-rules.toml"`
- `src/template_press/rebrand/rules.py:36` — the `.press` entry in
  `DEFAULT_RULES.exclude_dirs` becomes `press`. This exemption must track
  the new folder name: the press directory has to be excluded from **both**
  the rewrite pass and the no-leak doctor scan, or the tool would rewrite
  its own control files and flag them as identity leaks.
- `src/template_press/rebrand/receipt.py:17` —
  `RECEIPT_REL = Path("press") / "press-receipt.toml"`

### Cosmetic (strings + comments)

These are not behavior, but several are written *into* the target and must
self-describe the new path:

- `config.py` `render_source_config` header comment (config.py:56) — written
  into the target's press-source.toml.
- `receipt.py` `write_receipt` header comment (receipt.py:40) — written into
  the target's press-receipt.toml.
- CLI messages: `cli.py:44` ("already has a press receipt …") and any other
  message rendering `SOURCE_CONFIG_REL` (those already interpolate the
  constant and will update automatically; verify).
- `doctor.py:94` leak-report hint referencing `.press/rules.toml`.
- Module docstrings in `config.py`, `rules.py`, `receipt.py`.

### Tests (test-first)

Update expectations to the new names before flipping the code, watch them
fail, then apply the code change:

- `tests/rebrand/test_cli.py` (heaviest — ~10 references)
- `tests/rebrand/test_rules.py` (~4)
- `tests/rebrand/test_config.py` (~2)
- `tests/rebrand/test_matrix.py` (~1)
- `tests/rebrand/test_press_cli.py` (~1)

### Docs

- **Update (live/canonical):** `README.md`;
  `docs/design/0006-external-target-model.md` (canonical current model);
  `docs/source/index.md`; `docs/source/reference/cli.md`;
  `.claude/skills/press-target/SKILL.md`; the `projects/P03-…` tracking
  file. Review `docs/design/0001-press-cli-conventions.md` — update if it
  documents the live contract.
- **Leave as-is (historical records):**
  `docs/superpowers/plans/2026-06-23-rebrand-core.md` and
  `docs/superpowers/plans/2026-07-08-m4-shed-residue.md`. These are dated
  implementation records of what was built at the time; rewriting them
  would falsify history.

## Accepted risk

`exclude_dirs` matches a single path component at any depth, so excluding a
directory literally named `press` means any unrelated `press/` folder in a
*target* repo is skipped from both rewriting and the leak scan. With the old
hidden `.press` this never collided; with the visible `press` it is a small,
inherent cost of the chosen name. Accepted for the discoverability benefit;
recorded here so it is not a surprise later.

## Verification

- `just check` (full pipeline) passes.
- `just matrix` (R1/R2/R3 rebrand acceptance matrix) passes — mandatory
  after any change under `src/template_press/rebrand/`.
- A dry-run against a scratch target shows the new `press/press-source.toml`
  path in output; a full press writes `press/press-receipt.toml` and
  refreshes `press/press-source.toml`.

## Release

Breaking change to the target-file contract. Commit as a breaking
conventional commit (e.g. `feat!: …` with a `BREAKING CHANGE:` footer) so
release-please computes the major bump (2.1.1 → 3.0.0). The `version` field
is not hand-edited — release-please owns it.

## Out of scope

- No `.press/` migration tooling or fallback reads (clean break decided).
- No change to the answers-file (`--config`) mechanism or the `[identity]`
  /`[answers]`/`[rules]`/`[press]` table names.
- No changes to the rewrite/rename engine, discovery, or the exit-code
  contract beyond the four constants and their strings.
