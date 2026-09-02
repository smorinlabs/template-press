# E8 (entry #15) adversarial review — "press verify should skip gitignored nodes"

**Verdict: REJECT.** Confidence: high. The proposal rests on a factual premise
that the code makes impossible, and the two engine variants would not have
prevented the incident even if implemented.

## 1. Steelman (argued first, in good faith)

The never-follow symlink scan is deliberate and load-bearing. `verifier.py:20-24`
names it the **Task-3 I2 gap** closure: "a dir/dangling symlink whose readlink
text embeds a changed identity value now produces a `where="symlink"` finding
regardless of what (if anything) it points at." Git stores a symlink as a blob
**whose content is the link text**, so `docs/x -> ../py_launch_blueprint/…`
ships the old identity in the repository itself; scanning readlink text is the
only way to see it. `docs/design/0007-press-verify-design.md:42` sets the
posture: "False **negatives** are the expensive mistake … false positives are
cheap." Pinned by `tests/rebrand/test_verifier.py:330` and `:584`. The behavior
the operator hit is a deliberately built, tested invariant.

## 2. Attack — what actually happened

### 2a. Is this a from/to swap artifact? No.

`press/press-source.toml` is **this repo's CURRENT identity**, not the
upstream template's — `config.py:105` writes the header literally: "this
repo's CURRENT identity (the FROM side". `verify_command` loads it as
`source` (`verify_cli.py:390`), synthesizes a dest (`:444`
`synthesize_dest(source)`), and presses `source → synth` in the sandbox
(`:461`). In a pressed gmail2pdf fork, `source.app_name == 'gmail2pdf'`.
Therefore `app_name='gmail2pdf'` surviving **is** the source identity
surviving. The report string at `verify_cli.py:353` is accurate, not swapped.

### 2b. Is it a sandbox symlink-copy bug? No.

`sandbox.py:126-132` recreates symlinks **verbatim** by design ("do not follow
and do not rewrite the target; rewriting is apply's job"); faithful copy is the
stated invariant (`sandbox.py:11-14`).

### 2c. Is it a verify bug — did verify "reach a gitignored node"? **It cannot.**

This is the decisive point, and it inverts the proposal:

- The only source of scan candidates is the surface snapshot.
  `_enumerate_entries` (`inventory.py:915-930`) runs
  `git ls-files -z -t --stage --cached --others --exclude-standard`;
  `--exclude-standard` means **ignored untracked paths are never enumerated**.
- `select_copy_entries` (`inventory.py:1011-1019`) and
  `select_verifier_entries` (`inventory.py:1089-1105`) filter *that* snapshot.
  Neither can see a path git omitted. Pinned by
  `tests/rebrand/test_surface_inventory.py:40-63`
  (`assert "ignored.txt" not in entries`).

**So the fact that verify flagged `node_modules` is itself proof that git did
not consider it ignored.** Cause confirmed empirically (git 2.50.1, repro in
scratchpad `gt/`): a `.gitignore` pattern with a trailing slash matches
**directories only** — per `gitignore(5)` — and a *symlink* is not a
directory to git.

| `.gitignore` line | node type | `git check-ignore` | `ls-files --others --exclude-standard` |
|---|---|---|---|
| `node_modules/` | real directory | rc=0 (ignored) | omitted |
| `node_modules/` | **symlink** | **rc=1 (NOT ignored)** | **`? node_modules`** |
| `node_modules` (no slash) | symlink | rc=0 (ignored) | omitted |

This repo's own `.gitignore:25` is `node_modules/` — the trailing-slash form.
The operator replaced a directory with a symlink and thereby moved the node
*out* of the ignore set. Verify enumerated an untracked, **non-ignored**
root symlink and scanned its text. Correct behavior against a genuinely
mis-declared tree.

### 2d. Was the flagged leak real under the design's own definition? Yes.

A real press would never rewrite this link: `node_modules` is in
`DEFAULT_RULES.exclude_dirs` (`rules.py:224`), so `select_rename_entries`
(`inventory.py:1043-1064`, via `_excluded`'s `any(part in exclude_dirs …)`)
drops it; and `_retarget_symlinks` "leaves a symlink untouched when its
target is absolute" (`engine.py:1050-1051`). The link text keeps `gmail2pdf`
after any press. Verify's job is to report exactly that.

## 3. Alternatives, judged

| Option | Verdict |
|---|---|
| **(a) Skip gitignored paths in the verify walk** | **Reject — twice.** (i) No-op for this incident: the node was not ignored, so an ignore-respecting walk still scans it. (ii) Actively harmful if implemented as a `check-ignore` filter: it would skip **tracked force-added ignored files** — the precise false-clean the `-f` restage exists to prevent (`verify_cli.py:325-334`; PoC in `docs/design/0007-press-verify-design.md:496-513`; pinned by `tests/rebrand/test_inventories.py:188`). The design already litigated and closed this hole. |
| **(b) Scan symlink text only for tracked symlinks** | **Reject.** Same no-op/harm shape: an untracked-but-visible symlink is copied into the sandbox and ships in a `git add -A` a moment later. It also silently reopens half the I2 gap that `verifier.py:20-24` closed. |
| **(c) Ship `node_modules`/`.venv` as a *default* `verify_ignore`** | **Reject as a default.** `verify_ignore` is documented as the *per-target sanctioned lever* (`docs/design/0006-external-target-model.md:35`). A shipped default blinds the scan to **tracked** `node_modules` content that genuinely ships, contradicting EMP-01 (`0007:...` D3: "a target cannot add its own `extra_exclude_files` entry to blind the verifier's scan"). Fine as an *operator* remedy in a specific target's `press/press-rules.toml`. |
| **(d) Leave the engine; document the operator remedy** | **Accept.** |

## 4. Recommended resolution (all target-side; engine untouched)

Reclassify entry #15 from *friction* to **operator error / docs gap**, and
document, in the `press-target` skill's troubleshooting notes:

1. **One-character fix** — write `node_modules` (no trailing slash) in the
   target's `.gitignore`. Verified above: this ignores the symlink too.
2. **Or** add `node_modules` to `verify_ignore` in that target's
   `press/press-rules.toml` (component match, `inventory.py:1104`).
3. **Or, best** — the operator's own discovery: `bun install
   --frozen-lockfile` inside the worktree, so no symlink exists at all.

Plus a one-line note in `docs/source/reference/cli.md` (near :45, the existing
`verify_ignore` guidance): *a `foo/` ignore pattern does not ignore a symlink
named `foo`; verify only ever sees what `git ls-files --exclude-standard` lists.*

## 5. The one test that must exist

It does **not** exist today (`test_verifier.py` covers dangling and escaping
symlinks; `test_surface_inventory.py:40` covers an ignored *file*; nothing
covers the dir-only-pattern/symlink interaction). Add to
`tests/rebrand/test_verifier.py`, marked `@requires_symlink`:

> **`test_untracked_symlink_matching_dir_only_ignore_pattern_is_scanned`** —
> given `.gitignore` containing `node_modules/` and an untracked *symlink*
> `node_modules -> /abs/path/<source app_name>/node_modules`, assert the entry
> **is** enumerated by `capture_surface_snapshot`, **is** copied by
> `make_sandbox`, and yields a `Finding(where="symlink", field="app_name")`.

This locks today's behavior against a future "helpful" skip-ignored patch and
documents the git semantics that caused the incident.
