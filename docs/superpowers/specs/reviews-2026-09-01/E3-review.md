# E3 (entry #7, nit) — adversarial review: a new `[[format]]` rule type
**Verdict: REJECT the engine change (a). Adopt (b), the runbook line, plus a two-sentence
doc note. Confidence: high (0.85).** Paths relative to the repo root.

## 0. Two premises in the proposal are factually wrong
**"The template declares `uv run ruff format .` as a `[[regenerate]]` today" — false.**
`press/press-rules.toml` declares three `[[regenerate]]` tables (`uv.lock` :6, `bun.lock`
darwin/linux :12, `bun.lock` win32 :17) and one `[[reset]]` (:22); `grep -n format` on it
returns nothing.

**"Formatting changes files the receipt already fingerprinted" — false.** The receipt stores
no content hashes: `write_receipt` (`receipt.py:52-121`) writes identity tables,
`[press.counts]` integers, resolved argv, and file names only. And `press verify` is a leak
scan, not a byte-equality replay — it re-presses a sandbox copy toward a synthetic identity
and hunts surviving SOURCE tokens (`verify_cli.py:1-30`). `ruff format` cannot reintroduce
`py_launch_blueprint`, so post-press formatting breaks neither verify nor the receipt.
Severity "nit" is right: the real blast radius is four files and one command.

## 1. Steelman: do nothing in the engine
The press's contract is identity rewriting under a no-leak gate — `cli.py:5` states it:
"lockfiles → VERIFY (no-leak doctor) → receipt". Formatting is not identity work. The four
files were leak-free and byte-correct; they merely exceeded 88 columns once
`py_launch_blueprint` (19 chars) became `gmail2pdf` (9). Line length is the *target's*
config, which the press never reads. A formatter also drags the target's dev toolchain into
the press's critical path: a freshly pressed repo is not `uv sync`'d, so `uv run ruff format
.` can resolve environments, hit the network, and fail for reasons unrelated to the rebrand.

## 2. Attacks on (a)
**A1 — "skipped when the executable is absent" inverts the engine's loudest invariant.** A
missing executable is today a plan-time refusal with nothing written (`regen.py:226-236`),
and a whole `check-tools` verb exists to surface declared tools up front
(`check_tools.py`). Skip-on-absent means two machines produce different trees from identical
inputs and identical exit 0. `verify_exempt` had to buy its far smaller gap loudly, with a
mandatory `reason` (`rules.py:532-545`); this would buy a larger gap with nothing.

**A2 — a new class of non-determinism.** Regeneration's non-determinism is confined to files
the target already excluded from rewriting. A formatter mutates the *scanned source corpus
itself*, and its output varies by formatter version — press output becomes version-dependent
for real source code for the first time.

**A3 — the receipt/verify interaction is a non-issue, so (a) buys nothing there.** The
post-command scan is per-declared-output only (`_postcondition_problems` `regen.py:622-667`;
`final_validation_pass` `regen.py:669-731`) and never enumerates unauthorized writes.
`cli.py:479-480` says so outright: *"Reservation alone is not protection because a command
can mutate arbitrary files."* The engine already tolerates a command touching arbitrary
files; it defends only Press-owned control files (`regen.py:779-830`) and git visibility
(`regen.py:743-777`). The doctor then scans the whole tree after regeneration using
`DEFAULT_RULES.exclude_files`, ignoring target-side exclusions (`cli.py:556-568`), and
`doctor.py` never mentions `regenerate` — so formatter-touched files stay fully leak-scanned
either way.

**A4 — Windows and the rule zoo.** `platforms` already scopes any declaration
(`rules.py:822-847`), so (a) adds no cross-platform capability. It does add a fourth writer
type to `_validate_writer_overlaps` (`rules.py:641-690`), `preflight_excluded_files`
(`regen.py:448-479`), the receipt schema, plan renderer, verify exemption table, and docs —
permanent surface for a four-file cosmetic nit.

## 3. Option (c): can the current schema express a many-file formatter?
**No — not honestly.** `_parse_regenerate` (`rules.py:446-557`) forces four things a
formatter cannot satisfy together:
1. Exactly one `file`, a single declared relative path (`rules.py:456`) — no glob or list.
2. That `file` **must** be in `exclude_files` (`rules.py:458-464`) — the replace pass will
   not rewrite it.
3. It must be git-tracked, clean, sole-linked, UTF-8 at plan time (`regen.py:391-445`).
4. It gets the paranoid changed-fields scan afterwards (`regen.py:622-667`, `regen.py:506-620`).

Concretely: declaring `uv run ruff format .` with `file = "src/py_launch_blueprint/cli.py"`
forces that file into `extra_exclude_files`, so the replace pass skips it, `ruff format` does
not rewrite identifiers, `py_launch_blueprint` survives in its contents, and both the
post-command scan and the doctor fail the press. Worse, `preflight_excluded_files`
(`regen.py:448-479`) then demands a regenerate/reset/remove/ignore neutralization for every
excluded file — the four files become four failing declarations.

The only way to run a formatter today is to smuggle it into a legitimate output's command —
e.g. make `uv.lock`'s command a script running `uv lock && uv run ruff format .`, mirroring
`scripts/regen-bun-lock.sh` (`press/press-rules.toml:12-14`). That works mechanically and is
invisible to every check, which is exactly why it must not be recommended: the declaration
would claim to produce `uv.lock` while silently rewriting the source tree. So E3 is **not**
documenting an existing capability — the capability is absent by design; it is a runbook fix.

## 4. Verdict — REJECT (a), APPLY (b); confidence high (0.85)
- One line in the `press-target` skill's post-apply step and the pressed target's runbook:
  after a successful `press rebrand`, before the first commit, run the target's own formatter
  (`uv run ruff format .`) — identity length changes can push lines past the target's
  line-length limit.
- Two sentences in `docs/source/reference/cli.md` (near the `[[regenerate]]` section, ~lines
  100-155): `[[regenerate]]` declares **one** rebuilt output and is not a hook for repo-wide
  tools; a declared command must not be used to smuggle whole-tree edits.

Residual risk of doing nothing: a cosmetic diff on a handful of files, caught by the target's
own `just check` / pre-commit hooks on the first commit after the press — the press is not
the last gate here.

**The one test that must exist** (absent today): a rules-validation regression asserting that
a `[[regenerate]]` whose `file` is a normal, identity-bearing source file is refused — adding
a source `.py` to `extra_exclude_files` and declaring a formatter command against it must
fail (plan-time exclusion/neutralization error, or the post-command leak path), never exit 0.
It pins the boundary this review rests on. Nearest home:
`tests/rebrand/test_verify_exemption.py`, which already exercises `_parse_regenerate`
rejection paths at lines 259-340.
