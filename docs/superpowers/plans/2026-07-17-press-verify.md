# `press verify` + Engine Hardening — Implementation Plan (v3, post round-2 reviews)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use `- [ ]` checkboxes.
>
> **STATUS:** v3 — rewritten after a **second** fable+codex adversarial round found that routing verify through `_press` was the root of several blockers. v3's keystone: **verify composes `apply()` + its own scan; it never calls `_press`.**

**Goal:** A trustworthy, hermetic, zero-arg `press verify` that proves a template presses clean — plus the engine fixes it depends on.

**Architecture:** Three matcher postures (conservative rewriter, moderate doctor — both fixed — and a paranoid verifier). Verify presses a faithful sandbox copy with **`apply()` directly** (hermetic: no regen, no receipt, no doctor), then runs its own occurrence-level identifier-aware scan, maps findings to source coordinates via the rename report, and suppresses false positives with source-coordinate, occurrence-pinned, self-policing ignores.

**Tech Stack:** Python 3.12+, stdlib only for core. Tests: pytest, `tests/rebrand/`.

## Global Constraints

- **Python `>=3.12`**, stdlib-only for engine/verifier.
- **Config under `press/`**: `press-{source,rules,receipt,answers}.toml` (no `.press/`).
- **Exit contract:** `0` clean · `1` surviving finding / stale ignore · `2` tool/env/config error (incl. every expected exception — `FileNotFoundError`, `OSError`, `CalledProcessError`). **Env failure is 2, never 1.**
- **Verify is hermetic + read-only + non-escaping:** it calls `apply()` (never `_press`), never regenerates lockfiles, never writes a receipt/source-config, never executes target code or the network.
- **Engine-wide symlink safety (Decision 8 — protects BOTH `rebrand` and `verify`):** a control location (`press/`, any control artifact, or an ancestor) must be a **real path, not a symlink** — else **exit 2**; control-file writes never traverse a symlink; in-repo relative link targets are rewritten. This makes real `rebrand` **non-destructive** on a hostile/accidental control symlink, from one engine rule rather than a verify-only patch. (rebrand's existing `--dry-run` is unchanged; a sandbox-diff dry-run is a noted follow-up, not in this plan.)
- **Rewriter is never made more aggressive.**
- **CLI entry:** `src/template_press/press_cli.py`.
- **Verify's correctness guarantee is scoped to its *configured* fields** (default: `package_name, repo_name, app_name, owner`), NOT "all six" — `author`/`email` are opt-in. State this; do not claim more.
- **Gates:** `just setup` once (preamble); `just check` per commit; `just matrix` per phase boundary + pre-PR.

---

## Defensive Hardening (MANDATORY — round-3 reviews; fable + codex concur v3 is NOT sound without these)

Overriding invariant: **nothing is written, renamed, or deleted outside the intended root** — the *target* for rebrand, the *sandbox* for verify — in production OR tests. Implemented as foundational primitives in **Task 0.5** and used by Tasks 2/3/6/11/12.

- **G1 Test isolation (the 152-file-wipe class):** new autouse `tests/conftest.py` — `monkeypatch.chdir(tmp_path)` every test + `GIT_CEILING_DIRECTORIES=<checkout parent>`; one guarded git helper requiring an explicit repo path, `resolve().is_relative_to(tmp_root)`, and a `rev-parse --show-toplevel` match before any mutating verb; ban raw git subprocesses and implicit `--target .` in tests; fix the existing unguarded `shutil.rmtree` at `tests/rebrand/test_discovery.py:51`.
- **G2 SafeRelPath (hostile inventory):** typed gate on every `git ls-files` entry AND every `_renamed_rel` result — reject empty/`.`/`..`/absolute/rooted/drive/UNC/noncanonical/`.git` → exit 2. (A pressed template is third-party input.)
- **G3 Containment at every I/O sink (no-follow, hardlink-safe):** before any `write_text`/`mkdir`/`rename`/copy (engine + `make_sandbox`), assert `path.parent.resolve().is_relative_to(root)` and that no path component is a symlink (lstat walk); write atomically (temp + `os.rename`) so a **hardlinked** sink isn't modified in place; reject a control/target file with `st_nlink > 1`. Extends D8 from control paths to ALL writes.
- **G4 Sink-local control-write guard (TOCTOU):** re-check "no ancestor symlink + resolves under target" immediately before EACH of the three control writes (`cli.py:205-209`, the receipt write, `cli.py:287-290`) via one shared `_write_control` — not once at preflight.
- **G5 Subprocess env scrub:** all tool/test git gets `GIT_CONFIG_GLOBAL=os.devnull`, `GIT_CONFIG_NOSYSTEM=1`, cleared `GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE/GIT_OBJECT_DIRECTORY`, `-c core.hooksPath= -c commit.gpgsign=false`, identity via `-c user.*`. Real rebrand's `uv lock` gets scrubbed `UV_WORKING_DIR/UV_CACHE_DIR/UV_*`, `cwd=target` only; a hardlinked/symlinked `uv.lock` is rejected.
- **G6 Owned sandbox:** root created internally via `tempfile.mkdtemp(prefix="press-verify-")` (mode 0700), disjoint from target; cleanup only that owned child in `finally: shutil.rmtree` (never a caller `dest_root`); refuse `/`, HOME, cwd, repo root, ancestors, symlinked roots.
- **G7 Gitlinks inert:** scan a submodule/gitlink by path name only; never recurse/clone/init/fetch or interpret a nested `.git`.
- **G8 Scanner input discipline:** scan only `os.lstat`-regular files (no FIFO/socket/device hang); bounded chunked reads for the byte-scan; symlinks contribute `readlink` text only — sandbox scan AND real-target presence check.
- **G9 Read-only verify, enforced:** tests assert the real target's `git status --porcelain` + tree hash are byte-identical before/after verify on BOTH the exit-0 and exit-1 paths.
- **Preserve (already sound):** a lone symlink leaf is never content-rewritten (`engine.py:160`); validated identity can't make `_renamed_rel` invent `/` or `..` (`identity.py:14`).

**Gate tightenings (opus focused gate, 2026-07-18) — required before code:**
- **G5+ repo-local `.git/config` (NEW-A — currently an open code-exec hole):** env-scrub is not enough. Every **on-target** git op (`git status --porcelain` `cli.py:53`; `git ls-files` `engine.py:67`, used by BOTH rebrand and verify `copy_paths`) reads the TARGET's own `.git/config` → a hostile committed `[core] fsmonitor=./evil` / `hooksPath` / clean-smudge filter executes during "read-only" enumeration. Add `-c core.fsmonitor= -c core.hooksPath= -c protocol.ext.allow=never` (and neutralize clean/smudge filters) to EVERY on-target git invocation, not just the sandbox.
- **G3+ engine bulk-write sites (NEW-B/NEW-C):** the safe-I/O conversion MUST explicitly name `engine.py:245` (`write_text`) and `:296-297` (`mkdir`/`rename`) as sites (Task 0.5 helpers; Tasks 1/3 wire them); add a hardlinked-*tracked*-file test through `apply()` (not only `write_control`). The atomic temp is `mkstemp(dir=<validated parent>)` created AFTER the parent is validated, same filesystem.
- **G2+ `.git` casefold (V6):** `.git` rejection casefolds and strips Windows 8.3 shortnames + trailing dot/space (`.GIT`, `.Git`, `git~1`, `.git.`, `.git ` all normalize to `.git`).
- **G1+ enforce the ban:** the autouse fixture also intercepts `subprocess.run`/`Popen` to reject any un-pinned/un-contained `git` call — enforced, not advisory; set `GIT_CEILING_DIRECTORIES` so the real checkout's `.git` is undiscoverable from any stray cwd; all `/tmp` decoys in Tasks 3/12/0.5 move to `tmp_path/"outside"/…`.

**Threat model (explicit):** IN SCOPE — static hostile template content (committed symlinks/hardlinks/`.git/config`/index entries) and test-harness escape onto the real checkout. DOCUMENTED RESIDUAL (out of scope unless a concurrent LOCAL attacker is assumed): the ancestor-component-swap TOCTOU between the lstat-walk and `os.rename` — fully closing it needs `openat`/`dir_fd` no-follow handles; the leaf write is already atomic-safe and static hostile ancestors are caught by the pre-write lstat-walk.

---

## Conceptual Model (read before any task)

**Three postures answer "what is an occurrence of an identity name?"** — conservative rewriter (`engine.py`), moderate doctor (`doctor.py`, inside real `rebrand`), paranoid verifier (new). The verifier is deliberately the most paranoid, and its false positives are silenced by self-policing ignores.

**The keystone (round-2):** verify does **not** reuse `_press`. `_press` runs the doctor (whose leaks have no line/span and fire *before* occurrence-ignores can act), writes a receipt (which a control-path symlink can redirect *outside* the sandbox), and regenerates lockfiles (breaks hermeticity). Instead:

```
verify: load source -> preflight -> equal-fields WARN -> synth (equality-preserving)
        -> sandbox copy -> apply(sandbox, source, synth, rules)   # hermetic; returns ApplyReport
        -> scan(sandbox, source, synth)                            # own occurrence-level scan
        -> map findings to SOURCE coords (forward map via ApplyReport.renamed)
        -> apply_ignores  -> exit 0/1/2
```

**Six load-bearing abstractions (the decisions):**

1. **Identifier-aware matcher (D1)** — per field, separator-equivalence + a *case-scoped* transition boundary (below); pure substring is per-field opt-in.
2. **Identity preflight (D2)** — `discover`/`mismatches` (Python consistency, testing *all* `[project.scripts]`) **plus** a language-agnostic presence check on the fields discovery could NOT confirm; if identity is wholly undiscoverable, that is **`unverifiable` (exit 2)**, not a pass.
3. **Three inventories (D3)** — copy (tracked + non-ignored untracked, minus `.git`) / rewrite (minus lockfiles + `ROOT_CONTROL`) / scan (copy minus `ROOT_CONTROL`, minus regenerable lockfiles in `regenerate ∩ DEFAULT.exclude_files`). Rule: **exempt an exact artifact, never a location**; and **protect the root `press` path component** from rename/path-scan.
4. **Source-coordinate, occurrence-pinned, self-policing ignores (D4)** — an ignore pins ONE occurrence by `(file, field/value, anchor, line?, ordinal?)`; valid only if it suppresses exactly the finding it names; suppressing zero = drift = failure. Findings map to source via the forward rename map + the **newline-free line invariant** (identity values can't contain `\n` — `identity.py:14-17,63` — so line N in source == line N in sandbox).
5. **Hermetic verify (D5)** — `apply()` never regenerates; lockfiles are copied and scanned, with only the regenerable set (`uv.lock`) scan-exempt (the real press provably regenerates-or-fails it).
6. **Equality-preserving synthesis + equal-fields WARN (D6)** — `synthesize_dest` maps **equal source fields to equal dest values** (so verify never manufactures a mis-press), all *distinct* source values to distinct dest values; and verify WARNs (exit-neutral; opt-in strict) whenever two SOURCE fields are equal, to flag the limitation for real splitting customers.

---

## File Structure

**New:** `matcher.py` (`identity_pattern`, `find_occurrences`), `verifier.py` (`Finding`, `scan`, `apply_ignores`), `verify_config.py` (`Ignore`, `VerifyConfig`, parse — dependency-neutral), `synthesize.py`, `verify_cli.py`. Tests: `test_matcher.py`, `test_verifier.py`, `test_verify_config.py`, `test_synthesize.py`, `test_verify_cli.py`.

**Modified:** `engine.py` (`RENAME_FIELDS` += `app_name_upper`; exact-root control exemption; protect root `press` component; symlink-target rewrite; expose `apply` + `ApplyReport.renamed`; retain git mode/gitlink info in the listing), `doctor.py` (`PATH_FIELDS` += `app_name_upper`; readlink scan; byte-scan for identity in binaries), `press_cli.py` (dispatch `verify`).

**Test helpers to ADD to `conftest.py`:** `make_pressable(base, source=SOURCE)` (= `make_target` + committed `press/press-source.toml`); `_commit(repo)`, `_tree(repo)` (used by verify tests; NOT currently present).

---

## Phase 0 — Re-verify facts (NO CODE)

- [ ] **0.1** `apply(target, source, dest, rules) -> ApplyReport` exists; `ApplyReport.renamed: list[tuple[str,str]]` gives forward rename prefixes (`engine.py:212-217`); `apply` does replace+rename only (regen/receipt/doctor live in `_press`, `cli.py`). ✓
- [ ] **0.2** FP-1 (`RENAME_FIELDS`/`PATH_FIELDS` lack `app_name_upper`), receipt embeds FROM identity (`receipt.py:47`), `_press` overwrites `press-source.toml` with DEST (`cli.py:287-290`), unknown verb→2 (`press_cli.py:45-46`), entry `template_press.press_cli:main`. ✓
- [ ] **0.3** Real conftest: `SOURCE` (app_name=`press`, package `demo_widget`), `DEST` (potato*), `src_target`/`flat_target`, `_git`, `make_target`, `write_answers_file`. `make_pressable`/`_commit`/`_tree` are NEW.
- [ ] **0.4** `discovery.discover` reads first `[project.scripts]` only (`discovery.py:58`) and skips undiscoverable fields (`discovery.py:95`) → Task 12 presence must handle both. `_git_listed` uses `--exclude-standard` (`engine.py:67`) → copy contract is tracked + non-ignored untracked (document it).

---

## Phase 0.5 — Safe-I/O + test-isolation harness (FOUNDATIONAL — before any other code)

### Task 0.5: Implement the Defensive-Hardening primitives (G1–G9)

**Files:** new `tests/conftest.py` (autouse guard, G1); `src/template_press/rebrand/safety.py` (`SafeRelPath`, `assert_under_root`, `safe_write`/`safe_rename`/`safe_mkdir` no-follow+atomic, `write_control`, `scrubbed_git_env`/`scrubbed_uv_env`, `owned_sandbox` ctx-mgr, `is_regular_lstat`); test helper `assert_target_unchanged`; fix `tests/rebrand/test_discovery.py:51`.

**Every later task routes its writes / git calls / scans through these primitives** — no raw `write_text`/`rename`/`subprocess git`/`open` in engine or verifier write/scan paths.

- [ ] **0.5.1** Failing hostile-input tests, one per guard: absolute/`..`/drive/UNC/`.git` path → `SafeRelPath` raises; a symlinked *ancestor* dir write → `safe_write` refuses (containment); a **hardlinked** control file (whose second link is at `tmp_path/"outside"/"victim"`) → `write_control` writes a NEW inode (the outside victim untouched); `st_nlink>1` target → refuse; poisoned `GIT_DIR`/`core.hooksPath`/`GIT_CONFIG_GLOBAL` → scrubbed env neutralizes; `UV_WORKING_DIR=/elsewhere` → scrubbed; a gitlink → path-name only, no recursion; a FIFO in scan → `unscannable`, no hang; an unpinned test git op → the autouse guard makes it fail in a non-repo, not the checkout; a `tmp_path`-based decoy (NOT `/tmp`) stays unchanged.
- [ ] **0.5.2** Run → FAIL. **0.5.3** Implement the primitives. **0.5.4** Run → PASS. **0.5.5** Commit `feat(safety): safe-I/O + test-isolation harness (containment, no-follow, hardlink-safe, env scrub)`.

- [ ] **Phase 0.5 gate:** `just check`; `just matrix`.

---

## Phase 1 — Engine/doctor foundation

> Every write/rename in Phase 1+ goes through the Task-0.5 primitives (`safe_write`/`safe_rename`/`write_control`, `scrubbed_git_env`); every `git ls-files` entry and `_renamed_rel` result passes `SafeRelPath`; every scan uses `is_regular_lstat`. Tasks 2/3/6/11/12 reference the specific guards (G2–G9) inline.

### Task 1: `app_name_upper` rename + path scan (case-sensitive)
`engine.py:18`, `doctor.py:18` += `"app_name_upper"`. Test: `PRESS_GUIDE.md`→`POTATO_GUIDE.md`; surviving `PRESS_X.md`→`where="path"` leak. Commit `fix(engine): rename & path-scan the uppercased app token`.

### Task 2: Exact-root control exemption + protect the root `press` component (C-14 + round-2)
**Files:** `engine.py`; test `test_engine_enumerate.py`.
- `ROOT_CONTROL = {press/press-{source,rules,receipt,answers}.toml}`; `iter_target_files`/`scan_paths` exempt a file iff `rel in ROOT_CONTROL`.
- **Rename guard:** in `_renamed_rel`/the rename-map builder, **never emit a rename whose old prefix is the root `press` component** (else with `app_name="press"` an ordinary `press/notes.md` renames the whole control dir out from under `ROOT_CONTROL`). Root `press/` descendants are still rewritten and scanned by content; only the literal root `press` *dirname* is protected from rename and path-scan.
- [ ] Tests: nested `docs/press/leak.md` IS scanned; root `press/press-source.toml` is exempt; a committed root `press/notes.md` does NOT trigger a `press/`-dir rename; `docs/press/` (nested) still renames normally. Commit `fix(engine): exact-root control exemption; protect root press component`.

### Task 3: Engine-wide symlink safety (Decision 8; FP-3/C-11 + round-2 destructiveness)
**Policy — applies to BOTH `rebrand` and `verify` (a control location is tool-managed and must be real):**
- **Reject control-path symlinks:** a new `assert_control_real(target)` raises (→ exit 2) if `press/`, any control artifact, or an ancestor is a symlink; called once at the top of the shared load path so real `rebrand` is protected, not just verify.
- **Never write through a symlink:** the control-file writes in `_press` (receipt, source-config) check the path + ancestors are real before writing.
- **Rewrite in-repo relative link targets** in the rename pass (pressed forks don't dangle).
- **Doctor** yields `os.readlink` text so a link target embedding identity is a leak.

**Files:** `engine.py`, `config.py`, `cli.py` (`_press` write guard), `doctor.py`.
- [ ] **Tests:** (rebrand) `press -> tmp_path/"outside"/"decoy"` → `rebrand` **exit 2**, decoy dir still empty; (verify) same → exit 2; a symlink whose target embeds the package → leak; a normal in-repo relative link target is rewritten. (Decoys under `tmp_path`, never literal `/tmp` — G1.) Commit `fix(engine): engine-wide control-path symlink rejection + never-write-through`.

### Task 4: Typed press outcome + exception taxonomy (B5/C-7/C-11)
**Files:** `cli.py`. `@dataclass PressOutcome: leaked; renamed: list[tuple[str,str]]; regenerated; env_error: str|None`. Normalize expected exceptions (`FileNotFoundError`/`OSError`/`CalledProcessError`) into `env_error` in one place; real `rebrand.main` keeps its post-mutation exit-1 semantics; the field carries `renamed` from `ApplyReport` so callers have provenance. Tests: nonzero regen, missing tool, apply IO error, receipt-write failure all → `env_error` set; `rebrand` exit codes unchanged. Commit `refactor(rebrand): typed outcome + normalized failure taxonomy`.

- [ ] **Phase 1 gate:** `just check` (each commit); `just matrix`.

---

## Phase 2 — Identifier-aware matcher

### Task 5: `matcher.py` (Decision 1 — CORRECTED regex)
**Produces:** `identity_pattern(field, value) -> re.Pattern`; `find_occurrences(text, field, value, *, substring) -> list[tuple[int,int]]` (spans; `substring=True` = plain case-insensitive find loop).

- [ ] **5.1 Failing tests** (fixture app_name=`press`, package=`demo_widget`):
```python
def test_word_traps_not_matched():
    for w in ("compress","express","pressure","Pressure","PRESSURE"):
        assert find_occurrences(w,"app_name","press",substring=False)==[]
def test_variants_matched():
    for s in ("0001-x-press.md","PRESS_LOG","demo-widget_x","demoWidgetConfig"):
        assert find_occurrences(s,"package_name" if "widget" in s.lower() else "app_name",
                                "demo_widget" if "widget" in s.lower() else "press",substring=False)
def test_glued_only_with_substring():
    assert find_occurrences("xdemo_widgety","package_name","demo_widget",substring=False)==[]
    assert find_occurrences("xdemo_widgety","package_name","demo_widget",substring=True)
```
- [ ] **5.2** Run → FAIL. **5.3** Implement (the `(?-i:...)` scopes the case-transition test case-SENSITIVE inside an IGNORECASE pattern — the v2 regex was broken because global IGNORECASE folded the trailing class):
```python
import re
_SEP = re.compile(r"[_\-. ]+")
def identity_pattern(field, value):
    core = "[-_. ]?".join(re.escape(t) for t in _SEP.split(value) if t)
    tail = r"(?:(?![A-Za-z0-9])|(?-i:(?<=[a-z])(?=[A-Z])))"   # full boundary OR lower->UPPER
    return re.compile(rf"(?<![A-Za-z0-9]){core}{tail}", re.IGNORECASE)
```
- [ ] **5.4** Run → PASS (incl. `PRESSURE` rejected, `demoWidgetConfig` matched). **5.5** Property test over a wordlist **excluding the identity values themselves**. Document the known residuals in Task 14 (leading camel `myPressConfig` not matched; `PressKit` matched — acceptable for a paranoid posture). Commit `feat(matcher): identifier-aware pattern (case-scoped transition) + opt-in substring`.

- [ ] **Phase 2 gate:** `just check`; `just matrix`.

---

## Phase 3 — Inventories + verifier scan

### Task 6: Three inventories (Decision 3 + round-2 fidelity)
**Produces:** `copy_paths` (tracked + non-ignored untracked, minus `.git`, symlinks-as-paths, **gitlinks retained with type**); `rewrite_paths` (= today's `iter_target_files` minus lockfiles + `ROOT_CONTROL`); `scan_paths` (copy minus `ROOT_CONTROL`, minus lockfiles in `rules.regenerate ∩ DEFAULT_RULES.exclude_files`, minus `verify_ignore` dirs). Tests: `bun.lock` in copy+scan; `uv.lock` in copy but NOT scan; root control not in scan; a `git add -f` gitignored file IS in copy; a gitlink path is present (type-tagged). Commit `feat(engine): copy/rewrite/scan inventories with lockfile + gitlink fidelity`.

### Task 7: `verifier.py` — occurrence-level scan (Decision 1; round-2 binaries)
**Produces:** `@dataclass Finding: path; field; value; where  # content|filename|dirname|symlink|binary|unscannable; line: int|None; col: int|None; context: str`; `scan(target, source, dest, *, fields, substring_fields, rules) -> list[Finding]` — occurrence-level (line+col), over `scan_paths`; content, each path component, symlink `readlink`, and **byte-scan for identity byte sequences in non-UTF-8 files** (a `where="binary"` finding with `line=None`); reserve `where="unscannable"` for real I/O errors only. Changed-fields only. Tests: hyphen filename found; `compress` in README NOT found; two leaks on one line → two findings with distinct `col`; a PNG embedding `demo_widget` bytes → a `binary` finding; an unreadable file → `unscannable`. Commit `feat(verifier): occurrence-level scan incl. binary byte-scan`.

- [ ] **Phase 3 gate:** `just check`; `just matrix`.

---

## Phase 4 — Ignores + config

### Task 8: Source-coordinate, occurrence-pinned, self-policing ignores (Decision 4; round-2 pinning)
**Produces:** `@dataclass Ignore: field|None; value|None; file; anchor; line: int|None; ordinal: int|None; force; reason` (reject `field is None and value is None`). `apply_ignores(findings, ignores, *, forward_map, source_line) -> (surviving, stale)`:
- Map each finding's sandbox path back to source via `forward_map` (built from `ApplyReport.renamed`: reverse the prefix map); read the **source** line for the anchor (newline invariant → same line number).
- An ignore suppresses a finding iff `file`+field/value match AND `anchor` is in the source line AND (`line` None or ==) AND (`ordinal` None or == the finding's occurrence index on that line). **One ignore suppresses at most the occurrences it uniquely identifies** — if an anchor+line is ambiguous across ≥2 findings and no `ordinal`, that is a **config error** (reject), not a silent multi-suppress.
- Line-less findings (`filename`/`dirname`/`symlink`/`binary`): the anchor matches against the **source path** (+ `ordinal` for repeats).
- An ignore that suppresses **zero** findings and is not `force` → **stale** (drift).

Tests: anchored line+col ignore suppresses exactly one of two same-line leaks; ambiguous anchor with no ordinal → config error; anchor-present-but-nothing-suppressed → stale; a filename ignore suppresses a `filename` finding; `force` stale not returned. Commit `feat(verifier): source-mapped, occurrence-pinned, self-policing ignores`.

### Task 9: `verify_config.py` (Decisions 1,4,6)
`VerifyConfig: fields; substring_fields; ignores; equal_fields  # "warn"|"error"`. Defaults `fields=("app_name","package_name","repo_name","owner")` (no `app_name_upper` — case-insensitive dedup), `substring_fields=∅`, `equal_fields="warn"`. `extra_fields` appends. Dependency-neutral (imports only `identity`). Tests: defaults; parse `extra_fields`/`substring_fields`/`[[verify.ignore]]` (incl. `ordinal`)/`equal_fields="error"`; unknown field → `ValidationError`. Commit `feat(verify): [verify] config`.

- [ ] **Phase 4 gate:** `just check`; `just matrix`.

---

## Phase 5 — Synthesis + sandbox

### Task 10: `synthesize.py` — deterministic, equality-preserving, containment-safe (Decision 6 + m4)
**Produces:** `synthesize_dest(source) -> Identity` — deterministic (`hashlib.sha256`), **equal source values map to the SAME dest value** (preserve equality classes, D6), distinct source values map to distinct dest values, valid, and no dest value is a substring of any source *variant* or vice-versa. Tests: `replace(SOURCE, app_name="demo_widget")` (package==app) → synth package==synth app; distinct fields → distinct; deterministic; containment-free vs variants. Commit `feat(verify): equality-preserving deterministic synthesis`.

### Task 11: List-driven sandbox (Decision 3; round-2)
`make_sandbox(target, dest_root) -> Path` — copy `copy_paths` preserving symlinks as links (**but the control-path-symlink rejection from Task 3 runs first**), `git add -f --pathspec-from-file=- --pathspec-file-nul` (ARG_MAX-safe) the exact list, commit. **Submodules:** copy the gitlink path entry so its name is scanned; if content is unavailable, record it and make the run **nonzero**, not a silent skip. Tests: untracked-but-listed + symlink land as-is; `git add -f` file present; a gitlink path is scannable; a control-path symlink is rejected. Commit `feat(verify): faithful, ARG_MAX-safe sandbox; submodule-aware`.

- [ ] **Phase 5 gate:** `just check`; `just matrix`.

---

## Phase 6 — The `verify` verb

### Task 12: `verify_cli.py` — the full flow (keystone; Decisions 2,3,4,5,6)
`verify_command(argv) -> int`:
1. `--target` (default `.`); load `press/press-source.toml` — absent → **2**.
2. **Preflight (D2), against the REAL target:** (a) consistency: `mismatches(source, discover(target))` — and `discover` must test membership across **all** `[project.scripts]`, not the first; (b) presence: for each field discovery could NOT confirm, assert the declared value occurs ≥1× via `find_occurrences` over `scan_paths`; (c) if identity is **wholly undiscoverable AND absent**, classify **`unverifiable` → 2** (do not pass on historical prose). Any problem → print + **2**. Use `discover`/`mismatches` directly (never `_resolve_source`).
3. **Equal-fields (D6):** any two SOURCE fields equal → WARN (exit-neutral); `equal_fields=="error"` → collect for exit 1.
4. `synth = synthesize_dest(source)` (equality-preserving) → `make_sandbox`.
5. **`report = apply(sandbox, source, synth, rules_with_regenerate_empty)`** — hermetic; NO `_press`, NO doctor, NO receipt, NO regen. Wrap in the Task-4 exception taxonomy → any `env_error` → **2**.
6. `findings = scan(sandbox, source, synth, fields, substring_fields, hardened_rules)` — **hardened to DEFAULT excludes** so a target's `extra_exclude_*` can't blind the verifier; lockfiles scanned except the regenerable set.
7. `surviving, stale = apply_ignores(findings, cfg.ignores, forward_map=report.renamed, source_line=…)`.
8. **Exit:** `2` if config/env; else `1` if any surviving finding OR stale ignore OR (`equal_fields=="error"` collision); else `0`. `binary`/`unscannable` findings are fatal unless ignored (Task 8 path/digest anchor). Human report + `--json`.

- [ ] **12.1 Failing tests** (via `make_pressable`, `_commit`, `_tree`):
```python
def test_clean_template_exits_0(tmp_path):                       # incl. compress/press README + a uv.lock
    r = make_pressable(tmp_path); (r/"uv.lock").write_text('name = "demo_widget"\n'); _commit(r)
    assert verify_command(["--target", str(r)]) == 0
def test_bun_lock_leak_exits_1(tmp_path):                        # unregenerable lockfile IS scanned
    r = make_pressable(tmp_path); (r/"bun.lock").write_text('"name":"demo_widget"\n'); _commit(r)
    assert verify_command(["--target", str(r)]) == 1
def test_hyphen_token_leak_exits_1(tmp_path): ...
def test_missing_source_config_exits_2_no_write(tmp_path): ...   # _tree(before)==_tree(after)
def test_declared_app_absent_exits_2(tmp_path):                  # discovery-invisible: drop [project.scripts]
    ...  # source declares app_name="ghost"; presence fails -> 2
def test_control_path_symlink_rejected_exits_2(tmp_path): ...    # press -> tmp_path/"outside" ; no external write
def test_ignore_suppresses_then_drifts(tmp_path): ...            # real leftover + ignore -> 0 ; break anchor -> 1
def test_equal_fields_warns_exits_0(tmp_path): ...               # package==app ; warn ; 0 ; error-mode -> 1
def test_env_regen_absent_is_2(monkeypatch, tmp_path): ...       # force env_error -> 2
```
- [ ] **12.2** Run → FAIL. **12.3** Implement the flow (apply, not _press). **12.4** Run → PASS. **12.5** Commit `feat(cli): press verify — hermetic sandbox self-press leak check`.

### Task 13: Register verb + docs (correct path)
`src/template_press/press_cli.py` dispatch + help; `docs/source/reference/cli.md` (zero-arg CI + `[verify]` schema incl. `anchor`/`line`/`ordinal`/`force`, `substring_fields`, `equal_fields`); tick P03. Tests: `press verify --help`→0, `press bogus`→2. Commit `feat(verify): register verb + docs`.

### Task 14: Design decision record (project documentation)
Write `docs/design/00NN-press-verify-design.md` (next free index) capturing the three-posture model, the **keystone (`apply` not `_press`)**, and per decision *context→options→choice→why* (D1 matcher incl. the corrected regex + residuals; D2 preflight incl. presence + `unverifiable`; D3 inventories + root-`press` protection; D4 occurrence-pinned source-mapped ignores; D5 hermetic verify; D6 equality-preserving synthesis + WARN; D7 batched `just matrix` gates; D8 engine-wide symlink safety incl. why it makes `rebrand` non-destructive). Note the adversarial-review rounds (design + two plan iterations). Cross-link P03 + this plan. Commit `docs(design): press verify design + decision record`.

- [ ] **Phase 6 gate:** `just check`; `just matrix`; PR.

---

## Self-Review

**Round-2 blockers resolved:** lockfile hermeticity (D5 + Task 12.5 `apply` with `regenerate=()` + scan-exempt only `uv.lock`); control-dir ancestor rename (Task 2 root-`press` guard); control-path symlink escape (Task 3 rejection + Task 12 no-receipt-write); provenance (Task 4 `renamed` in `PressOutcome`/`ApplyReport` + Task 8 forward map + newline invariant); doctor-vs-ignore ordering (keystone: verify scans itself, no doctor); equal-fields corrupt-output (Task 10 equality-preserving synthesis); matcher regex (Task 5 case-scoped tail); binaries (Task 7 byte-scan); presence soundness (Task 12.2 all-scripts + `unverifiable`); occurrence pinning (Task 8 line+col+ordinal); submodules (Task 11); copy contract (Task 6, documented); exception taxonomy (Task 4); "hunt configured fields" not "all six" (Global Constraints + Task 9).

**Placeholder scan:** none. **Type consistency:** `Finding`, `Ignore`, `VerifyConfig`, `PressOutcome`, `ApplyReport`, `identity_pattern`, `find_occurrences`, `scan`, `apply_ignores`, `synthesize_dest`, `make_sandbox`, `copy_paths`/`scan_paths` — each defined once, used identically.

**Note:** v3 makes an architectural change (verify uses `apply()`, not `_press`) that neither prior version had. It warrants a light confirmation pass (the matcher regex and the `apply`-based flow are the two highest-risk spots) before or early in implementation.
