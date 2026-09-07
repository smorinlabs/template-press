# P11 Directory Removals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove exactly the tracked directory members selected before mutation,
record their complete history, and preserve that membership during verification.

**Architecture:** Keep file declarations separate from directory declarations.
One immutable removal plan supplies the CLI, executor and verifier; receipts
preserve exact current paths alongside original audit paths. Keep reset →
rewrite/rename → removal → edits → regeneration ordering.

**Tech Stack:** Python 3.13+, standard library only at runtime, uv, pytest, Ruff,
ty, Git, existing just/lefthook checks.

**Spec:** `docs/superpowers/specs/2026-09-06-p11-directory-removals-design.md`.

**Status:** implementation authorized after independent major review. Owner
adoption is recorded exactly: “Yes, approve the recommendation for decision
2.” The proposed acceptance clarification is now the accepted two-part
amendment. Baseline is
`18946d5cf3de857da34b1677faff424b91a7a070` on `feat/directory-removals`.

## Global Constraints

- Python >=3.13; shipped package uses only the Python standard library.
- Preserve unrelated code and all existing file-only removal behavior.
- Exactly one of `file` or `dir` is declared; `reason` is required and printable.
- No globs, exclusions within directory removals, special `.gitkeep` handling,
  reparenting, directory merging, or new removal phase.
- Freeze membership once before any target mutation. Never enumerate filesystem
  contents or Git membership to choose deletions during removal execution.
- Never delete untracked or ignored nonmembers by directory expansion.
- Retain existing static no-follow/containment guards. Do not claim that P11
  closes the documented concurrent ancestor-swap residual in `safety.py`.
- Every actual implementation commit requires `PYTEST_ADDOPTS='-n 8' just check`.
  Any change under `src/template_press/rebrand/` additionally requires
  `just matrix`. Native R3 clones committed HEAD; commit its native declaration
  before claiming its acceptance test exercised that declaration.
- Use conventional lowercase commit subjects. Do not publish intermediate commits.

---

## Entry, evidence and scope

The baseline's reported validation is 1,543 passed/2 skipped and the complete
matrix 4 passed/5 deselected. These are baseline results, not results for P11.
Setup is already complete. Do not repeat installations or label environment
failures as behavioral RED. Commands below run from
`/Users/stevemorin/c/template-press-p10-gate` with its existing environment.

Tasks 1–6 are independently reviewable components of one unreleased feature.
Task 1 temporarily refuses public execution of directory rules until Task 4
wires the complete plan; no intermediate commit may silently ignore a directory
removal. Retain that explicit gate until receipt and verifier support exist.
Each task ends with its targeted GREEN tests, full required checks, a conventional
commit, and independent review. Correct in-scope findings before beginning the
next dependent task. The controller owns publication and tracker transitions;
this plan contains no push/PR/merge instructions.

Historical mapping: Task 19 becomes this design and the entry review; Task 20
becomes Tasks 1–2; Task 21 becomes Tasks 3–5; Task 22 becomes Task 6. P12 is a
separate reassessment after P11, not an automatic successor implementation.

## File and interface map

| File | Responsibility |
| --- | --- |
| `src/template_press/rebrand/rules.py` | Raw directory declaration parsing, selection and all-platform overlap checks |
| `src/template_press/rebrand/removal_types.py` (new) | Immutable plan/history data with no engine or receipt imports |
| `src/template_press/rebrand/remove.py` | Fresh freeze, history selection, runtime conflicts, display and exact-member removal |
| `src/template_press/rebrand/receipt.py` | Bounded directory-history reader and writer, legacy file reader retained |
| `src/template_press/rebrand/cli.py` | Freeze before `build_plan`, pass plan through `_press`, emit successful history |
| `src/template_press/rebrand/verify_cli.py` | Freeze/select on real target, carry exact plan into sandbox |
| `src/template_press/rebrand/engine.py` | Warning coverage for raw directory declarations and resolved current roots |
| `src/template_press/rebrand/regen.py` | Excluded-file gate consumes explicit frozen current paths |
| `tests/rebrand/test_remove_dirs.py` (new) | Schema, safety, executor, CLI and renewal tests |
| `tests/rebrand/test_remove_dir_receipt.py` (new) | Strict bounded history shape, binding and coordinates |
| `tests/rebrand/test_remove_dir_controls.py` (new) | Positive and deliberately broken membership/verify controls |
| `tests/rebrand/test_matrix.py`, `press/press-rules.toml`, `docs/source/reference/cli.md` | Native research-only migration and public contract |

`check_tools.py` needs no new tool or runtime deletion logic. Its existing
`load_selected_rules` call receives parser validation; add a test proving a
valid directory declaration does not require a new executable.

| Producer | Exact shared interface | Consumer |
| --- | --- | --- |
| Rules | `RemoveDirRule(dir: str, reason: str)`; `Rules.remove_dirs: tuple[RemoveDirRule, ...] = ()`, appended after `clean` for positional compatibility | Planner and static warnings |
| Types | `RemovalMember(file, current_file, reason, source_dir=None, missing_ok=False)` | Planner, history parser and executor |
| Types | `DirectoryRemoval(dir, current_dir, reason, members)`; `RemovalPlan(files=(), directories=(), retained_history=())` | All directory operations |
| Receipt | `directory_history_from_receipt(text: str | None, source: Identity) -> tuple[DirectoryRemoval, ...]` | Planner |
| Receipt | `receipt_present(target: Path) -> bool`; `read_receipt(target: Path, *, max_bytes: int | None = None) -> str | None` | Directory callers use `16 * 1024 * 1024`; file-only callers retain default |
| Receipt | `selected_directory_history(text: str | None, source: Identity, *, directory_declared: bool) -> tuple[DirectoryRemoval, ...]` | Planner; preserves tolerant no-directory legacy routing |
| Remove | `removal_receipt_text(target: Path, rules: Rules) -> str | None` | Main, guarded verify preflight and directory fallback |
| Remove | `plan_removals(target: Path, rules: Rules, *, source: Identity, receipt_text: str | None = None, mode: Literal["press", "verify"] = "press", legacy_removed: Mapping[str, str] | None = None) -> RemovalPlan` | CLI and verify before mutation |
| Remove | `removal_rules_view(rules: Rules, plan: RemovalPlan) -> Rules` | Build-plan warnings and existing file-oriented gates |
| Remove | `apply_removal_plan(target: Path, plan: RemovalPlan, renamed: Mapping[str, str]) -> list[str]` | Real press and sandbox |
| Remove | `translate_removal_plan(plan: RemovalPlan, renamed: Mapping[str, str]) -> RemovalPlan` | Receipt construction only |
| Remove | `render_frozen_remove_plan(plan: RemovalPlan) -> str` | CLI |
| Remove | `frozen_remove_command_conflicts(rules: Rules, plan: RemovalPlan, renamed: Mapping[str, str]) -> list[str]` | CLI preflight |
| Receipt | `write_receipt(..., *, remove_dirs: Sequence[DirectoryRemoval] = (), ...) -> Path` | Existing writer gets successful translated directory metadata |
| CLI | `_press(..., *, removal_plan: RemovalPlan | None = None, ...) -> PressOutcome` | Normal entry and existing direct-test entry |

`removal_rules_view` preserves all non-removal fields, turns frozen members into
`RemoveRule(file=member.current_file, reason=member.reason)`, and sets directory
rules to exact current roots. It is a read-only compatibility view for gates and
warnings, not a new expansion or declaration serialization. The executor always
uses the frozen plan. Never feed this view back through overlap parsing: it
intentionally contains directory roots and their expanded members.

## Requirement-to-task/test matrix

| Requirement | Task | Concrete test/oracle |
| --- | --- | --- |
| XOR declaration, reason, paths, selectors | 1 | `test_directory_schema`, `test_directory_invalid`, `test_directory_platform_selection` |
| Writer/removal/stub overlap, alias and platform semantics | 1, 2 | `test_directory_writer_overlap`, `test_directory_disjoint_platforms`, `test_resolved_history_writer_conflict` |
| Frozen tracked members and visible dry-run | 2, 4 | `test_freeze_exact_members`, `test_cli_directory_rename_receipt_verify` |
| Dirty, untracked, assume-unchanged, gitlink, symlink/junction refusal | 2 | `test_directory_dirty_refuses`, `test_directory_unsafe_nodes_refuse` |
| Ignored nonmembers and unrelated empty children survive | 2, 3 | `test_ignored_file_is_not_member`, `test_cleanup_preserves_nonmembers` |
| Empty existing directory and missing-history behavior | 2, 3, 4 | `test_empty_and_stale_directory`, `test_empty_history_round_trip` |
| Exact translated members; source audit rows | 3, 4 | `test_translate_preserves_audit`, `test_cli_directory_rename_receipt_verify` |
| No expansion during apply | 5 | `test_apply_membership_oracle`, broken `reexpand_at_apply` rejected by same oracle |
| No expansion during historical verify | 5 | `test_verify_membership_oracle`, broken `fresh_verify_plan` rejected by same oracle |
| Bounded, complete, identity-bound, unambiguous history | 3 | `test_history_round_trip`, `test_history_refusals`, `test_history_limits` |
| Prior unstaged deletions and fresh later press | 4 | `test_renewal_keeps_tombstones`, `test_renewal_refuses_operator_changes` |
| Renamed root, internal filename, later ancestor rename | 4 | `test_cli_directory_rename_receipt_verify`, `test_historical_ancestor_translation` |
| Mid-removal failure invalidates success receipt | 4 | `test_partial_directory_failure_has_no_receipt` |
| Existing file-only compatibility | every task | Existing `tests/rebrand/test_remove_rules.py` unchanged behavior assertions |
| Native research migration, retained projects scaffold | 6 | `test_native_directory_declaration`, committed `test_r3_self_press_native` |

## Task 1: Typed declarations and static safety

**Files:** modify `rules.py`, `engine.py`, `cli.py`, `verify_cli.py`; create
`removal_types.py`, `tests/rebrand/test_remove_dirs.py`.

**Interfaces:** produces `RemoveDirRule`, `Rules.remove_dirs`, the three records
in the shared table, and `_parse_remove` returning a declaration whose `rule` is
`RemoveRule | RemoveDirRule`. Existing `RemoveRule(file, reason)` is unchanged.

- [x] **Step 1: Add these schema tests before source edits.** Start the new test
  module with the imports and fixture helpers below; later tasks append to it.

```python
from __future__ import annotations

import dataclasses
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules, load_selected_rules
from template_press.rebrand.safety import SafetyError
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, SOURCE, _git, requires_symlink, write_answers_file
from .test_verify_cli import _commit, make_pressable

DIR_RULE = '[[remove]]\ndir = "research"\nreason = "template research"\n'


def write_dir_rules(repo: Path, body: str = DIR_RULE) -> None:
    (repo / "press").mkdir(parents=True, exist_ok=True)
    (repo / "press/press-rules.toml").write_text(body, encoding="utf-8")


def point_origin(repo, destination):
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{destination.owner}/{destination.repo_name}.git",
    )


def directory_repo(tmp_path: Path, body: str = DIR_RULE) -> Path:
    repo = make_pressable(tmp_path)
    write_dir_rules(repo, body)
    (repo / "research/sub").mkdir(parents=True)
    (repo / "research/one.md").write_text("first member\n", encoding="utf-8")
    (repo / "research/sub/two.md").write_text("second member\n", encoding="utf-8")
    (repo / "incoming").mkdir()
    (repo / "incoming/late.md").write_text("outside member\n", encoding="utf-8")
    _commit(repo)
    return repo


def test_directory_schema(tmp_path):
    write_dir_rules(tmp_path)
    rules = load_rules(tmp_path)
    assert rules.remove == ()
    assert [(r.dir, r.reason) for r in rules.remove_dirs] == [
        ("research", "template research")
    ]


@pytest.mark.parametrize(
    "body",
    [
        '[[remove]]\nfile="x"\ndir="research"\nreason="r"\n',
        '[[remove]]\nreason="r"\n',
        '[[remove]]\ndir="research"\n',
        '[[remove]]\ndir="research"\nreason=" "\n',
        '[[remove]]\ndir="research/*"\nreason="r"\n',
        '[[remove]]\ndir="../research"\nreason="r"\n',
        '[[remove]]\ndir="."\nreason="r"\n',
        '[[remove]]\ndir="PRESS."\nreason="r"\n',
        '[[remove]]\ndir=".git"\nreason="r"\n',
        '[[remove]]\ndir="research"\nexclude=[".gitkeep"]\nreason="r"\n',
    ],
)
def test_directory_invalid(tmp_path, body):
    write_dir_rules(tmp_path, body)
    with pytest.raises(ValidationError):
        load_rules(tmp_path)


@pytest.mark.parametrize(
    "other",
    [
        '[[remove]]\nfile="research/one.md"\nreason="r"\n',
        '[[remove]]\ndir="research/sub"\nreason="r"\n',
        '[[edit]]\nfile="RESEARCH./one.md"\ncommand=["python"]\nexpect="x"\n',
        '[[reset]]\nfile="out.md"\nstub_file="research/one.md"\n',
        '[[regenerate]]\nfile="research/one.md"\ncommand=["python"]\n',
    ],
)
def test_directory_writer_overlap(tmp_path, other):
    write_dir_rules(tmp_path, DIR_RULE + other)
    with pytest.raises(ValidationError, match="overlap|stub_file"):
        load_rules(tmp_path)


def test_directory_platform_selection(tmp_path):
    write_dir_rules(tmp_path, DIR_RULE + 'platforms=["win32"]\n')
    assert load_selected_rules(tmp_path, platform="linux").rules.remove_dirs == ()
    assert len(load_selected_rules(tmp_path, platform="win32").rules.remove_dirs) == 1


def test_directory_disjoint_platforms(tmp_path):
    write_dir_rules(
        tmp_path,
        DIR_RULE
        + 'platforms=["win32"]\n'
        + '[[remove]]\nfile="research/one.md"\nreason="r"\n'
        + 'platforms=["linux", "darwin"]\n',
    )
    assert len(load_selected_rules(tmp_path, platform="linux").rules.remove) == 1
```

- [x] **Step 2: Establish RED.** Run:

```bash
uv run pytest tests/rebrand/test_remove_dirs.py -q -x
```

Expected first behavioral failure: valid `dir` is rejected as an unknown key.
Baseline invalid-declaration passes are controls, not feature RED. Save the
failure command/output in the controller's task evidence.

- [x] **Step 3: Implement types, parsing and overlap predicates.** Put the three
  frozen dataclasses from the spec verbatim in `removal_types.py`, importing
  `dataclass`. In `rules.py`, add:

```python
@dataclass(frozen=True)
class RemoveDirRule:
    dir: str
    reason: str


def _path_at_or_below(path: str, root: str) -> bool:
    path_key = _control_alias_key(path)
    root_key = _control_alias_key(root)
    return path_key == root_key or path_key.startswith(root_key + "/")
```

  Extend `_REMOVE_KEYS` by `dir`. `_parse_remove` checks
  `("file" in entry) == ("dir" in entry)` first and raises an XOR diagnostic.
  Validate the selected key with `_declared_rel_path`; reject `*?[` for `dir`.
  Use the existing shared reason/platform validation; construct
  `RemoveDirRule(dir=path, reason=reason)` or `RemoveRule(file=path, reason=reason)`.
  Append `remove_dirs: tuple[RemoveDirRule, ...] = ()` after `Rules.clean`,
  never adjacent to `remove`; type `_RemoveDeclaration.rule` as the union. `_select_rules` uses
  `isinstance(declaration.rule, RemoveRule)` and `RemoveDirRule` to populate the
  two tuples. No optional file field is introduced.

  In `_validate_writer_overlaps`, retain the existing file-only path by filtering
  file declarations first. For each directory declaration and every other
  removal, reset/edit/regenerate target and reset `stub_file`, apply:

```python
shared_platforms = directory.platforms & other.platforms
conflict = _path_at_or_below(other_path, directory.rule.dir)
if other_is_directory_or_writer:
    conflict = conflict or _path_at_or_below(directory.rule.dir, other_path)
if shared_platforms and conflict:
    raise ValidationError(
        f"{RULES_REL}: [[remove]] dir {directory.rule.dir!r} has "
        f"{other_kind} overlap at {other_path!r} on "
        f"{sorted(shared_platforms)!r}"
    )
```

  Here `other_path` is exactly `other.rule.file`, `other.rule.dir`, or
  `other.rule.stub_file`; `other_kind` is the literal table name or `stub_file`.
  `other_is_directory_or_writer` is true for a directory removal or a writer
  target, false for a regular removal file or stub input. Skip comparison with
  the same declaration object. Reject ancestors of `ROOT_CONTROL` using the same
  conservative predicate, including the root `press` directory.

  Extend engine warning coverage by adding `r.dir.split("/", 1)[0]` from
  `rules.remove_dirs`; retain existing file/reset behavior. Until Task 4,
  immediately after public CLI/verify rule loading, return exit 2 with
  `directory removals require the complete P11 executor and history integration`
  when `rules.remove_dirs` is nonempty. This temporary gate prevents silent
  successful presses that ignore the new declaration.

- [x] **Step 4: GREEN and compatibility.**

```bash
uv run pytest tests/rebrand/test_remove_dirs.py tests/rebrand/test_remove_rules.py -q
PYTEST_ADDOPTS='-n 8' just check
just matrix
```

- [x] **Step 5: Commit and review.**

```bash
git add src/template_press/rebrand/rules.py src/template_press/rebrand/removal_types.py src/template_press/rebrand/engine.py src/template_press/rebrand/cli.py src/template_press/rebrand/verify_cli.py tests/rebrand/test_remove_dirs.py
git commit -m "feat(rules): parse typed directory removal declarations"
```

## Task 2: Fresh immutable expansion and clean-directory guards

**Files:** modify `remove.py`, `tests/rebrand/test_remove_dirs.py`.

**Interfaces:** consumes Task 1 records; produces private
`_freeze_directory(target: Path, declaration: RemoveDirRule, *, current_dir: str,
prior: DirectoryRemoval | None = None) -> DirectoryRemoval`,
`_directory_status_problems(target: Path, root: str,
missing_recorded: frozenset[str]) -> list[str]`,
`removal_rules_view`, `render_frozen_remove_plan`, and
`frozen_remove_command_conflicts`. Task 4 composes `_freeze_directory` with strict
history into public `plan_removals`.

- [x] **Step 1: Add concrete fresh-freeze tests.** These import the new helper
  locally so schema tests retain their independent first RED.

```python
def freeze_fresh(repo: Path):
    from template_press.rebrand.remove import _freeze_directory

    (declaration,) = load_rules(repo).remove_dirs
    return _freeze_directory(repo, declaration, current_dir=declaration.dir)


def test_freeze_exact_members(tmp_path):
    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    assert [m.file for m in directory.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]
    assert [m.current_file for m in directory.members] == [
        "research/one.md",
        "research/sub/two.md",
    ]
    assert all(m.source_dir == "research" for m in directory.members)
    assert all(not m.missing_ok for m in directory.members)


@pytest.mark.parametrize("change", ["modified", "staged", "untracked", "hidden"])
def test_directory_dirty_refuses(tmp_path, change):
    repo = directory_repo(tmp_path)
    path = repo / "research/one.md"
    if change == "untracked":
        path = repo / "research/operator note.md"
    if change == "hidden":
        _git(repo, "update-index", "--assume-unchanged", "research/one.md")
    path.write_text("operator work\n", encoding="utf-8")
    if change == "staged":
        _git(repo, "add", "research/one.md")
    with pytest.raises(SafetyError, match="uncommitted|dirty|untracked"):
        freeze_fresh(repo)
    assert path.read_text(encoding="utf-8") == "operator work\n"


@pytest.mark.parametrize("kind", ["gitlink", "visibility"])
def test_directory_unsafe_nodes_refuse(tmp_path, kind):
    repo = directory_repo(tmp_path)
    if kind == "gitlink":
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{head},research/submodule",
        )
        _git(repo, "commit", "-q", "-m", "gitlink fixture")
    else:
        (repo / "research/.gitignore").write_text("cache/\n", encoding="utf-8")
        _commit(repo)
    with pytest.raises((SafetyError, ValidationError), match=kind):
        freeze_fresh(repo)
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"


@requires_symlink
def test_directory_symlink_refuses(tmp_path):
    repo = directory_repo(tmp_path)
    (repo / "research/link").symlink_to("../incoming/late.md")
    _commit(repo)
    with pytest.raises(SafetyError, match="symlink"):
        freeze_fresh(repo)
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"


def test_ignored_file_is_not_member(tmp_path):
    repo = directory_repo(tmp_path)
    with (repo / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("research/cache.bin\n")
    _commit(repo)
    (repo / "research/cache.bin").write_bytes(b"operator cache")
    directory = freeze_fresh(repo)
    assert {m.file for m in directory.members} == {
        "research/one.md",
        "research/sub/two.md",
    }


def test_empty_and_stale_directory(tmp_path):
    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    _commit(repo)
    with pytest.raises(SafetyError, match="does not exist|stale"):
        freeze_fresh(repo)
    (repo / "research").mkdir()
    assert freeze_fresh(repo).members == ()
```

  Add a Windows-only junction test that creates a junction with the existing
  Windows helper if present; otherwise use `subprocess.run(["cmd", "/c",
  "mklink", "/J", str(repo / "research/junction"), str(repo / "incoming")],
  check=True, capture_output=True)`, gated by `sys.platform == "win32"`.
  Assert `freeze_fresh` raises and the outside bytes survive. Do not call a
  skipped POSIX run Windows validation.

- [x] **Step 2: RED.**

```bash
uv run pytest tests/rebrand/test_remove_dirs.py -k 'freeze or dirty or unsafe or ignored or empty' -q -x
```

  Missing `_freeze_directory` is initial API RED. After defining its signature,
  confirm a deliberately permissive expansion (tracked list only, no guards)
  fails the dirty/untracked tests before adding guards. Save that behavioral
  failure; a missing import alone does not demonstrate the safety requirement.

- [x] **Step 3: Implement one fresh snapshot and explicit status parsing.** Use
  `capture_surface_snapshot` and its `entries`; use `tracked_paths` only through
  a supplied snapshot adapter if necessary, never recapture per member. Select
  `entry.tracked and rel.startswith(current_dir + "/")`; reject a root gitlink.
  Require `entry.index_kind == "file"` for each selected entry. Keep sorted
  source strings and inspect no-follow current kinds before creating records:

```python
members = tuple(
    RemovalMember(
        file=rel,
        current_file=rel,
        reason=declaration.reason,
        source_dir=current_dir,
    )
    for rel in sorted(present_tracked)
)
return DirectoryRemoval(
    dir=declaration.dir,
    current_dir=current_dir,
    reason=declaration.reason,
    members=members + retained_missing,
)
```

  `retained_missing` contains validated prior members absent at their exact
  `current_file` and marked `missing_ok=True`; Task 4 supplies that history.
  Sort the final tuple by `(file, current_file)` and reject alias collisions.
  A present path replaces a prior member at the exact same current path, after
  its fresh clean check. Never infer `file` by replacing a directory prefix.

  Build a no-follow safety walk with an explicit stack of real directories;
  `os.scandir` plus `entry.stat(follow_symlinks=False)` checks every descendant,
  including ignored nodes. Reject symlink, junction, FIFO/socket/device and
  embedded `.git` boundaries. Do not collect extra members from the walk. Protect
  expanded visibility files with the same removal-file validation and captured
  configured visibility-input path/inode comparisons used elsewhere in P09.

  Use the existing hardened Git invocation (`git_hardening_args`,
  `scrubbed_git_env`) and `--literal-pathspecs`. Parse status without quoting or
  line assumptions:

```python
records = raw_status.split(b"\0")
index = 0
while index < len(records):
    record = records[index]
    index += 1
    if not record:
        continue
    if len(record) < 4 or record[2:3] != b" ":
        raise SafetyError("malformed directory status record")
    code = record[:2]
    rel = record[3:].decode("utf-8", "surrogateescape")
    has_second_path = b"R" in code or b"C" in code
    if has_second_path:
        if index >= len(records) or not records[index]:
            raise SafetyError("malformed directory rename status record")
        index += 1
    missing_history = (
        not has_second_path
        and code in (b" D", b"D ")
        and rel in missing_recorded
        and not os.path.lexists(target / rel)
    )
    if not missing_history:
        problems.append(f"remove directory {root!r}: dirty path {rel!r}")
```

  **Controller refinement (Opus O1/O3):** use exactly one directory status
  query and one index-flags query, both hardened, literal, and pinned to the
  supplied worktree. This preserves the existing hidden-flag clean contract
  while avoiding two subprocesses per member; do not alter legacy file helpers.

```python
def _directory_git_bytes(target: Path, *args: str) -> bytes:
    return subprocess.run(
        [
            "git",
            "--literal-pathspecs",
            "-C",
            str(target),
            f"--work-tree={target}",
            *git_hardening_args(),
            *args,
        ],
        check=True,
        capture_output=True,
        env=scrubbed_git_env(),
    ).stdout


raw_status = _directory_git_bytes(
    target, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", root
)
raw_flags = _directory_git_bytes(target, "ls-files", "-v", "-z", "--", root)
for record in raw_flags.split(b"\0"):
    if not record:
        continue
    if len(record) < 3 or record[1:2] != b" ":
        raise SafetyError("malformed directory index-flag record")
    rel = record[2:].decode("utf-8", "surrogateescape")
    tag = record[:1]
    if rel in present_tracked and (tag.islower() or tag == b"S"):
        problems.append(
            f"remove directory {root!r}: {rel!r} has uncommitted changes "
            "(assume-unchanged/skip-worktree) — refused even under --allow-dirty"
        )
```

  `root` is the exact selected current root; `present_tracked` is the frozen
  set of present tracked members. The status parser above consumes `raw_status`.
  Bound displayed problems to 20 with a total and `repr` paths. A nonempty
  problem list raises `SafetyError` before mutation even with `--allow-dirty`.
  Add paired flag controls and a local `core.worktree` adversary:

```python
@pytest.mark.parametrize("flag", ["assume-unchanged", "skip-worktree"])
def test_directory_hidden_flags_have_paired_control(tmp_path, flag):
    repo = directory_repo(tmp_path)
    assert len(freeze_fresh(repo).members) == 2
    _git(repo, "update-index", "--" + flag, "research/one.md")
    with pytest.raises(
        SafetyError, match="uncommitted changes.*assume-unchanged/skip-worktree"
    ):
        freeze_fresh(repo)
    _git(repo, "update-index", "--no-" + flag, "research/one.md")
    assert len(freeze_fresh(repo).members) == 2


def test_directory_status_pins_real_worktree(tmp_path):
    repo = directory_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(repo, "config", "core.worktree", str(other))
    assert len(freeze_fresh(repo).members) == 2
    (repo / "research/one.md").write_text("unfinished\n", encoding="utf-8")
    with pytest.raises(SafetyError, match="dirty path.*research/one.md"):
        freeze_fresh(repo)
```

  Implement `removal_rules_view` with `dataclasses.replace`. Rendering produces
  the existing file rows/counts and for each directory
  `  [remove ] research/ (2 files, dir) — template research` followed by its
  member audit paths; include `(0 files, dir)` for empty membership. Show current
  location when it differs. Command conflicts compare every member's exact
  before/translated current path using existing alias normalization; also check
  directory-root/descendant argv paths so a command cannot depend on a selected
  empty directory or future output below a removed root. Do not parse attached
  options or command language beyond the existing best-effort contract.

- [x] **Step 4: GREEN and existing controls.**

```bash
uv run pytest tests/rebrand/test_remove_dirs.py tests/rebrand/test_remove_rules.py -q
PYTEST_ADDOPTS='-n 8' just check
just matrix
```

- [x] **Step 5: Commit and review.**

```bash
git add src/template_press/rebrand/remove.py tests/rebrand/test_remove_dirs.py
git commit -m "feat(remove): freeze clean tracked directory members"
```

## Task 3: Exact execution and complete bounded receipt history

**Files:** modify `remove.py`, `receipt.py`; create
`tests/rebrand/test_remove_dir_receipt.py`; append executor tests to
`tests/rebrand/test_remove_dirs.py`.

**Interfaces:** produces `apply_removal_plan`, `translate_removal_plan`,
`directory_history_from_receipt`, bounded `read_receipt`, and the `remove_dirs`
writer keyword in the shared interface table. Legacy file helpers stay callable.

- [x] **Step 1: Add executor and round-trip tests.**

```python
def test_cleanup_preserves_nonmembers(tmp_path):
    from template_press.rebrand.removal_types import RemovalPlan
    from template_press.rebrand.remove import apply_removal_plan

    repo = directory_repo(tmp_path)
    directory = freeze_fresh(repo)
    (repo / "research/unselected-empty").mkdir()
    (repo / "research/cache.bin").write_bytes(b"must survive")
    removed = apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {})
    assert removed == ["research/one.md", "research/sub/two.md"]
    assert not (repo / "research/sub").exists()
    assert (repo / "research/unselected-empty").is_dir()
    assert (repo / "research/cache.bin").read_bytes() == b"must survive"


def test_empty_history_round_trip(tmp_path):
    from template_press.rebrand.removal_types import RemovalPlan
    from template_press.rebrand.remove import apply_removal_plan

    repo = make_pressable(tmp_path)
    write_dir_rules(repo)
    _commit(repo)
    (repo / "research").mkdir()
    directory = freeze_fresh(repo)
    assert apply_removal_plan(repo, RemovalPlan(directories=(directory,)), {}) == []
    assert not (repo / "research").exists()
```

  New receipt test module:

```python
from __future__ import annotations

import dataclasses
import tomllib

import pytest

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import read_receipt, write_receipt
from template_press.rebrand.removal_types import (
    DirectoryRemoval,
    RemovalMember,
    RemovalPlan,
)
from template_press.rebrand.remove import translate_removal_plan

from .conftest import DEST, SOURCE


def history_row():
    return DirectoryRemoval(
        dir="research",
        current_dir="archive",
        reason="template research",
        members=(
            RemovalMember(
                file="research/demo.md",
                current_file="archive/renamed.md",
                reason="template research",
                source_dir="research",
                missing_ok=True,
            ),
        ),
    )


def test_translate_preserves_audit():
    plan = RemovalPlan(directories=(history_row(),))
    translated = translate_removal_plan(plan, {"archive": "final"})
    member = translated.directories[0].members[0]
    assert translated.directories[0].current_dir == "final"
    assert member.file == "research/demo.md"
    assert member.source_dir == "research"
    assert member.current_file == "final/renamed.md"


def test_history_round_trip(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    row = history_row()
    report = ApplyReport()
    report.removed.append("archive/renamed.md")
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        report,
        removals=[("research/demo.md", "template research")],
        remove_dirs=[row],
    )
    text = read_receipt(tmp_path)
    parsed = tomllib.loads(text)
    assert parsed["press"]["remove"] == [
        {"file": "research/demo.md", "reason": "template research"}
    ]
    assert parsed["press"]["remove_dir"] == [
        {
            "dir": "research",
            "current_dir": "archive",
            "reason": "template research",
            "complete": True,
            "members": [
                {
                    "file": "research/demo.md",
                    "source_dir": "research",
                    "current_file": "archive/renamed.md",
                }
            ],
        }
    ]
    assert directory_history_from_receipt(text, DEST) == (row,)
    with pytest.raises(ValidationError, match="match|verified"):
        directory_history_from_receipt(text, SOURCE)


@pytest.mark.parametrize(
    "old,new",
    [
        ("verified = true", "verified = false"),
        ("remove_dirs_version = 1", "remove_dirs_version = true"),
        ("remove_dirs_version = 1", "remove_dirs_version = 2"),
        ("complete = true", "complete = false"),
        ('current_dir = "archive"', 'current_dir = "../archive"'),
        ('current_file = "archive/renamed.md"', 'current_file = "other/file.md"'),
        ('source_dir = "research"', 'source_dir = "other"'),
        ('file = "research/demo.md"\nreason', 'file = "missing.md"\nreason'),
    ],
)
def test_history_refusals(tmp_path, old, new):
    from template_press.rebrand.receipt import directory_history_from_receipt

    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[history_row()],
    )
    text = read_receipt(tmp_path)
    assert old in text
    with pytest.raises(ValidationError):
        directory_history_from_receipt(text.replace(old, new), DEST)


def test_inactive_directory_history_is_still_strict(tmp_path):
    from template_press.rebrand.receipt import selected_directory_history

    row = history_row()
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[row],
    )
    text = read_receipt(tmp_path)
    assert selected_directory_history(text, DEST, directory_declared=False) == (row,)
    with pytest.raises(ValidationError, match="match|verified"):
        selected_directory_history(text, SOURCE, directory_declared=False)


def test_history_limits(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    text = "#" + "x" * (16 * 1024 * 1024)
    with pytest.raises(ValidationError, match="limit|large"):
        directory_history_from_receipt(text, DEST)
```

  `ApplyReport()` is the actual baseline constructor; its fields have defaults.

- [x] **Step 2: RED.**

```bash
uv run pytest tests/rebrand/test_remove_dir_receipt.py tests/rebrand/test_remove_dirs.py -k 'history or translate or cleanup' -q -x
```

  After adding signatures, verify the production control that omits directory
  metadata fails the independently expected TOML object; a parser/writer
  round-trip alone is not sufficient evidence.

- [x] **Step 3: Implement exact operations and bounded serialization.**

```python
def translate_removal_plan(plan, renamed):
    def member_at_current(member):
        return dataclasses.replace(
            member,
            current_file=translate_path(member.current_file, renamed),
        )

    def directory_at_current(directory):
        return dataclasses.replace(
            directory,
            current_dir=translate_path(directory.current_dir, renamed),
            members=tuple(member_at_current(m) for m in directory.members),
        )

    return RemovalPlan(
        files=tuple(member_at_current(m) for m in plan.files),
        directories=tuple(directory_at_current(d) for d in plan.directories),
        retained_history=tuple(directory_at_current(d) for d in plan.retained_history),
    )
```

  Add the explicit type annotations from the shared table to production code.
  `apply_removal_plan` performs this translation once and loops over
  `translated.members`. Reuse current apply guards; on missing members only
  `member.missing_ok` licenses skipping. Collect actual unlinks. Derive cleanup:

```python
cleanup: set[str] = set()
for directory in translated.directories:
    cleanup.add(directory.current_dir)
    root = PurePosixPath(directory.current_dir)
    for member in directory.members:
        for parent in PurePosixPath(member.current_file).parents:
            if parent == root:
                break
            if root not in parent.parents:
                raise SafetyError("directory member escaped its recorded current root")
            cleanup.add(parent.as_posix())
for rel in sorted(cleanup, key=lambda value: (-value.count("/"), value)):
    path = target / rel
    assert_under_root(path, target)
    assert_ancestors_real(path, target)
    if not os.path.lexists(path):
        continue
    if (
        path.is_symlink()
        or path.is_junction()
        or not stat.S_ISDIR(path.lstat().st_mode)
    ):
        raise SafetyError(f"remove directory {rel!r} is not a real directory")
    try:
        os.rmdir(path)
    except FileNotFoundError:
        continue
    except OSError as exc:
        if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
            raise
```

  Pin the writer's exact whitespace and key ordering to these templates.
  Add `"remove_dirs_version = 1"` in the initial `[press]` lines before any
  nested table when `remove_dirs` is nonempty. The array is intentionally one
  line so raw malformed-shape tests can remove that line without parsing away
  duplicate evidence. Keep legacy flat rows as `file = ...` then `reason = ...`.

```python
for directory in remove_dirs:
    rendered_members = []
    for member in directory.members:
        if member.source_dir is None:
            raise ValidationError("directory member requires source_dir")
        rendered_members.append(
            "{ file = "
            + toml_string(member.file)
            + ", source_dir = "
            + toml_string(member.source_dir)
            + ", current_file = "
            + toml_string(member.current_file)
            + " }"
        )
    lines += [
        "",
        "[[press.remove_dir]]",
        f"dir = {toml_string(directory.dir)}",
        f"current_dir = {toml_string(directory.current_dir)}",
        f"reason = {toml_string(directory.reason)}",
        "complete = true",
        "members = [" + ", ".join(rendered_members) + "]",
    ]
```

  Empty expansion writes exactly `members = []`. Do not serialize `missing_ok`.
  Before writing, validate exactly one flat row of matching reason per member.
  The CLI's single-emission union below prevents carry-forward duplicates.

  Define constants in `receipt.py`: `REMOVE_HISTORY_MAX_BYTES = 16 * 1024 * 1024`,
  `REMOVE_HISTORY_MAX_DIRS = 1024`, `REMOVE_HISTORY_MAX_MEMBERS = 100000`,
  `REMOVE_HISTORY_MAX_TEXT_BYTES = 4096`. Pin the four limit diagnostics to
  `directory receipt byte limit 16777216 exceeded`, `directory row limit 1024
  exceeded`, `directory member limit 100000 exceeded`, and `directory text byte
  limit 4096 exceeded`. The strict reader checks byte length
  before TOML parsing, then exact key/type sets, `type(version) is int`, version
  `== 1`, completeness, safe canonical paths, current containment, per-member
  source containment, pairwise root overlap, alias uniqueness, reason agreement,
  and raw flat-row uniqueness. An absent directory version and absent directory
  array returns `()`; either key present activates strict validation. In a
  directory-declared call, invalid TOML refuses even when the parser cannot
  establish whether metadata was present. Raise `ValidationError` with bounded,
  `repr`-escaped diagnostics. A current member outside its root must name
  `current_dir` in the diagnostic, e.g. `directory member current_file is outside
  current_dir`. Return members with `missing_ok=True`.

  `read_receipt(..., max_bytes=...)` must use a bounded no-follow read before
  decoding, not unrestricted `read_text` followed by a size check. Open through
  the existing safe read mechanism and enforce the limit while reading. If the
  current safe helper cannot bound allocation, add a narrow bounded reader in
  `receipt.py` using the same ancestor and regular-file guards plus
  `os.open(..., O_NOFOLLOW when available)` and `os.fdopen(...).read(max_bytes + 1)`;
  compare descriptor/leaf identities as existing safe reads do. Keep the original
  unbounded default behavior for legacy file-only callers. Validate a frozen plan
  against identical schema limits before any mutation, not first at receipt time.

  Add `receipt_present` for presence-only decisions and this exact conditional
  history router. The active-directory reader is bounded before its first
  allocation. No-active rules retain legacy read behavior, including malformed
  TOML tolerance; recognized inactive directory metadata then receives strict
  validation. Its discovery has the existing legacy allocation residual, not
  the active-directory pre-read allocation bound (controller ruling C1/C2).

```python
def receipt_present(target: Path) -> bool:
    # Matches the old read_receipt missing-versus-file predicate without I/O
    # of file contents. Later semantic reads own decoding and safety checks.
    return (target / RECEIPT_REL).is_file()


def removal_receipt_text(target: Path, rules: Rules) -> str | None:
    return read_receipt(
        target,
        max_bytes=REMOVE_HISTORY_MAX_BYTES if rules.remove_dirs else None,
    )


def selected_directory_history(
    text: str | None,
    source: Identity,
    *,
    directory_declared: bool,
) -> tuple[DirectoryRemoval, ...]:
    if directory_declared:
        return directory_history_from_receipt(text, source)
    # _press_table is the existing tolerant TOML adapter. Do not require a
    # legacy file-only receipt to be verified or identity-bound.
    table = _press_table(text)
    if "remove_dir" not in table and "remove_dirs_version" not in table:
        return ()
    return directory_history_from_receipt(text, source)
```

  Define `removal_receipt_text` in `remove.py` (import reader and limit there),
  and `selected_directory_history` in `receipt.py`. Add them to the Task 3
  produced interfaces. `directory_history_from_receipt` returns `()` for no
  receipt or valid TOML without directory metadata, but rejects invalid TOML
  when called. Only the no-active router bypasses malformed legacy TOML. A
  recognized inactive row is never silently discarded because it is unbound.
  Normalize active strict TOML failures explicitly before table processing:

```python
if text is None:
    return ()
if len(text.encode("utf-8")) > REMOVE_HISTORY_MAX_BYTES:
    raise ValidationError("directory receipt byte limit 16777216 exceeded")
try:
    parsed = tomllib.loads(text)
except tomllib.TOMLDecodeError as exc:
    raise ValidationError(f"directory receipt TOML is invalid: {exc}") from exc
```

  Bound the rendered TOML diagnostic to the documented display limit; do not
  echo entire receipt text. The no-active router still uses `_press_table`
  first and preserves its tolerant invalid-TOML outcome.

  Add these concrete raw duplicate/unknown/limit cases to the receipt module:

```python
@pytest.mark.parametrize(
    "mutation", ["duplicate_flat", "duplicate_dir", "unknown_key", "no_members"]
)
def test_history_ambiguous_rows(tmp_path, mutation):
    from template_press.rebrand.receipt import directory_history_from_receipt

    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[history_row()],
    )
    text = read_receipt(tmp_path)
    if mutation == "duplicate_flat":
        text += (
            '\n[[press.remove]]\nfile="research/demo.md"\nreason="template research"\n'
        )
    elif mutation == "duplicate_dir":
        text += '\n[[press.remove_dir]]\ndir="RESEARCH."\ncurrent_dir="ARCHIVE."\n'
        text += 'reason="template research"\ncomplete=true\nmembers=[]\n'
    elif mutation == "unknown_key":
        text = text.replace("complete = true", "complete = true\ntrusted = true")
    else:
        begin = text.index("members = [")
        # Writer places members on one line as an inline-table array.
        end = text.index("\n", begin)
        text = text[:begin] + text[end:]
    with pytest.raises(ValidationError):
        directory_history_from_receipt(text, DEST)


def bound_history_text(*, directories=1, members=0, path_bytes=None):
    from template_press.rebrand.config import toml_string

    parts = ["[press]", "verified = true", "remove_dirs_version = 1", "[press.to]"]
    parts.extend(
        f"{key} = {toml_string(value)}"
        for key, value in DEST.as_dict_prompted().items()
    )
    for index in range(directories):
        root = f"d{index}"
        rels = [f"{root}/m{number}" for number in range(members if index == 0 else 0)]
        if path_bytes is not None and index == 0:
            rels = [root + "/" + "x" * (path_bytes - len(root) - 1)]
        parts.extend(
            [
                "[[press.remove_dir]]",
                f'dir = "{root}"',
                f'current_dir = "{root}"',
                'reason = "r"',
                "complete = true",
                "members = ["
                + ",".join(
                    '{ file = "'
                    + rel
                    + '", source_dir = "'
                    + root
                    + '", current_file = "'
                    + rel
                    + '" }'
                    for rel in rels
                )
                + "]",
            ]
        )
        for rel in rels:
            parts.extend(["[[press.remove]]", f'file = "{rel}"', 'reason = "r"'])
    return "\n".join(parts) + "\n"


@pytest.mark.parametrize(
    "kind,limit,diagnostic",
    [
        ("directories", 1024, "directory row limit 1024 exceeded"),
        ("members", 100000, "directory member limit 100000 exceeded"),
        ("path_bytes", 4096, "directory text byte limit 4096 exceeded"),
    ],
)
def test_history_count_and_text_limits(kind, limit, diagnostic):
    from template_press.rebrand.receipt import directory_history_from_receipt

    at_limit = bound_history_text(**{kind: limit})
    assert directory_history_from_receipt(at_limit, DEST)
    above_limit = bound_history_text(**{kind: limit + 1})
    with pytest.raises(ValidationError, match=diagnostic):
        directory_history_from_receipt(above_limit, DEST)


def test_history_byte_limit_has_valid_boundary():
    from template_press.rebrand.receipt import directory_history_from_receipt

    text = bound_history_text()
    ceiling = 16 * 1024 * 1024
    # ASCII comment padding preserves valid TOML and exact UTF-8 byte length.
    at_limit = text + "#" + "x" * (ceiling - len(text.encode("utf-8")) - 1)
    assert len(at_limit.encode("utf-8")) == ceiling
    assert directory_history_from_receipt(at_limit, DEST)
    with pytest.raises(
        ValidationError, match="directory receipt byte limit 16777216 exceeded"
    ):
        directory_history_from_receipt(at_limit + "x", DEST)
```

  Add member-alias and oversize-path cases by using the actual writer on
  `dataclasses.replace(history_row(), members=(member, alias_member))` and
  `dataclasses.replace(member, file="research/" + "x" * 4097)` respectively;
  writer refusal must happen without creating a receipt. Invalid UTF-8 uses
  `(tmp_path / "press/press-receipt.toml").write_bytes(b"\xff")` followed by
  `read_receipt(tmp_path, max_bytes=16 * 1024 * 1024)`; assert `ValidationError`.

- [x] **Step 4: GREEN, compatibility and full gates.**

```bash
uv run pytest tests/rebrand/test_remove_dir_receipt.py tests/rebrand/test_remove_dirs.py tests/rebrand/test_remove_rules.py -q
PYTEST_ADDOPTS='-n 8' just check
just matrix
```

- [x] **Step 5: Commit and review.**

```bash
git add src/template_press/rebrand/remove.py src/template_press/rebrand/receipt.py tests/rebrand/test_remove_dirs.py tests/rebrand/test_remove_dir_receipt.py
git commit -m "feat(remove): execute frozen members and record complete history"
```

## Task 4: Real press, historical verify and explicit renewal

**Files:** modify `remove.py`, `cli.py`, `verify_cli.py`, `regen.py`,
`tests/rebrand/test_remove_dirs.py`.

**Interfaces:** completes `plan_removals` and the `_press(removal_plan=...)`
keyword. All producers/consumers in the shared interface table are now connected.
Remove the temporary public gate from Task 1 only in this task.

- [ ] **Step 1: Add production composition and history tests.** Use a legal
  component substitution: source author `research` → destination author
  `archive`, not a fabricated path separator or filesystem injection.

```python
def rename_directory_repo(tmp_path):
    source = dataclasses.replace(SOURCE, author="research")
    destination = dataclasses.replace(DEST, author="archive")
    repo = make_pressable(tmp_path, identity=source.as_dict_prompted())
    write_dir_rules(
        repo,
        '[[replace]]\npattern="{author}"\npaths=true\ncontent=false\n'
        'files=["research/**", "archive/**"]\nreason="rename research directory"\n'
        + DIR_RULE,
    )
    (repo / "research").mkdir()
    (repo / "research/one.md").write_text("first member\n", encoding="utf-8")
    (repo / "research/two.md").write_text("second member\n", encoding="utf-8")
    (repo / "incoming").mkdir()
    (repo / "incoming/late.md").write_text("outside member\n", encoding="utf-8")
    _commit(repo)
    return repo, source, destination


def test_cli_directory_rename_receipt_verify(tmp_path, capsys):
    repo, source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    args = ["--target", str(repo), "--config", str(answers)]
    assert main([*args, "--dry-run"]) == 0
    preview = capsys.readouterr().out
    assert "research/ (2 files, dir)" in preview
    assert "research/one.md" in preview and "research/two.md" in preview
    assert (repo / "research/one.md").read_text(encoding="utf-8") == "first member\n"
    assert main(args) == 0
    point_origin(repo, destination)
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert receipt["press"]["remove"] == [
        {"file": "research/one.md", "reason": "template research"},
        {"file": "research/two.md", "reason": "template research"},
    ]
    row = receipt["press"]["remove_dir"][0]
    assert row["dir"] == "research"
    assert row["current_dir"] == "archive"
    assert [m["current_file"] for m in row["members"]] == [
        "archive/one.md",
        "archive/two.md",
    ]
    assert not (repo / "research").exists()
    assert not (repo / "archive").exists()
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"
    assert verify_command(["--target", str(repo), "--json"]) == 0


def test_renewal_keeps_tombstones(tmp_path):
    from template_press.rebrand.config import load_source_config
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    (repo / "research/new.md").write_text("new committed member\n", encoding="utf-8")
    # Commit ONLY the new member; prior successful deletions remain unstaged.
    _git(repo, "add", "research/new.md")
    _git(repo, "commit", "-q", "-m", "new member only")
    source = load_source_config(repo, None)
    assert source is not None
    plan = plan_removals(
        repo, load_rules(repo), source=source, receipt_text=read_receipt(repo)
    )
    members = {m.current_file: m for m in plan.directories[0].members}
    assert set(members) == {"research/one.md", "research/sub/two.md", "research/new.md"}
    assert members["research/one.md"].missing_ok is True
    assert members["research/sub/two.md"].missing_ok is True
    assert members["research/new.md"].missing_ok is False
    assert members["research/new.md"].file == "research/new.md"
    assert verify_command(["--target", str(repo)]) == 0
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    next_answers = write_answers_file(tmp_path, next_identity)
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(next_answers),
                "--force",
                "--allow-dirty",
            ]
        )
        == 0
    )
    text = (repo / RECEIPT_REL).read_text(encoding="utf-8")
    receipt = tomllib.loads(text)
    assert receipt["press"]["counts"]["removed"] == 1
    assert {row["file"] for row in receipt["press"]["remove"]} == {
        "research/one.md",
        "research/sub/two.md",
        "research/new.md",
    }


@pytest.mark.parametrize("operator_change", ["modified", "untracked"])
def test_renewal_refuses_operator_changes(tmp_path, operator_change):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    path = repo / "research/operator.md"
    path.write_text("committed\n", encoding="utf-8")
    if operator_change == "modified":
        _git(repo, "add", "research/operator.md")
        _git(repo, "commit", "-q", "-m", "operator file only")
    path.write_text("private unfinished work\n", encoding="utf-8")
    with pytest.raises(SafetyError, match="dirty|uncommitted|untracked"):
        plan_removals(
            repo, load_rules(repo), source=DEST, receipt_text=read_receipt(repo)
        )
    assert path.read_text(encoding="utf-8") == "private unfinished work\n"


def test_partial_directory_failure_has_no_receipt(tmp_path, monkeypatch):
    import template_press.rebrand.remove as removal

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    real_unlink = removal.os.unlink
    removed_members = []

    def fail_second(path, *args, **kwargs):
        try:
            rel = Path(path).relative_to(repo).as_posix()
        except (TypeError, ValueError):
            return real_unlink(path, *args, **kwargs)
        if rel == "research/sub/two.md":
            raise SafetyError("injected second removal failure")
        result = real_unlink(path, *args, **kwargs)
        if rel == "research/one.md":
            removed_members.append(rel)
        return result

    monkeypatch.setattr(removal.os, "unlink", fail_second)
    assert main(["--target", str(repo), "--config", str(answers)]) == 1
    assert removed_members == ["research/one.md"]
    assert (repo / "research/sub/two.md").is_file()
    assert not (repo / RECEIPT_REL).exists()
```

  `os` is shared across modules. The explicit prior-receipt fixture below
  delegates unrelated paths/`dir_fd` cleanup and pins the injected diagnostic,
  actual first unlink, retained second member and invalidated receipt.

  Add this exact resolved-history overlap test to the same module:

```python
def test_resolved_history_writer_conflict(tmp_path):
    from template_press.rebrand.receipt import read_receipt
    from template_press.rebrand.remove import plan_removals

    repo, source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    rules_path = repo / "press/press-rules.toml"
    with rules_path.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[[edit]]\nfile="archive/new.md"\ncommand=["python"]\nexpect="x"\n'
        )
    # Static declarations use research versus archive, so raw parser accepts;
    # exact recorded current-root overlap must refuse before execution.
    rules = load_rules(repo)
    with pytest.raises((SafetyError, ValidationError), match="overlap|conflict"):
        plan_removals(repo, rules, source=destination, receipt_text=read_receipt(repo))
```

  Add these routing and prior-receipt failure regressions to Task 4 before
  implementation. These tests exercise the real CLI/private fallback boundary,
  rather than accepting an isolated parser result as proof of bounded access.

```python
def test_cli_active_directory_first_receipt_read_is_bounded(
    tmp_path, monkeypatch, capsys
):
    import template_press.rebrand.cli as cli_module
    import template_press.rebrand.receipt as receipt_module
    import template_press.rebrand.remove as remove_module

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    (repo / RECEIPT_REL).write_bytes(b"#" + b"x" * (16 * 1024 * 1024))
    original_read = receipt_module.read_receipt
    calls = []

    def bounded_read(target, *, max_bytes=None):
        assert max_bytes == 16 * 1024 * 1024, (
            "active directory reached unbounded text read"
        )
        calls.append(max_bytes)
        return original_read(target, max_bytes=max_bytes)

    for module in (cli_module, receipt_module, remove_module):
        monkeypatch.setattr(module, "read_receipt", bounded_read, raising=False)
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(answers),
            "--force",
            "--allow-dirty",
            "--dry-run",
        ]
    )
    assert code == 2
    assert "directory receipt byte limit 16777216 exceeded" in capsys.readouterr().err
    assert calls == [16 * 1024 * 1024]
    assert (repo / "research/one.md").read_text(encoding="utf-8") == "first member\n"


def test_directory_history_router_preserves_malformed_legacy():
    from template_press.rebrand.receipt import selected_directory_history

    malformed = "[press\nnot toml"
    assert selected_directory_history(malformed, SOURCE, directory_declared=False) == ()
    with pytest.raises(ValidationError, match="TOML|receipt"):
        selected_directory_history(malformed, SOURCE, directory_declared=True)


def test_direct_press_directory_fallback_reads_history(tmp_path):
    from template_press.rebrand.cli import _press

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    outcome = _press(repo, DEST, next_identity, load_rules(repo), [], [])
    assert outcome.env_error is None
    assert not outcome.leaked
    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    assert len(receipt["press"]["remove"]) == 2
    assert len({row["file"] for row in receipt["press"]["remove"]}) == 2
    assert receipt["press"]["counts"]["removed"] == 0


def test_partial_repress_invalidates_previous_receipt(tmp_path, monkeypatch, capsys):
    import template_press.rebrand.remove as removal

    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    prior_receipt = (repo / RECEIPT_REL).read_bytes()
    assert b"verified = true" in prior_receipt
    (repo / "research/sub").mkdir(parents=True)
    (repo / "research/one.md").write_text("restored first\n", encoding="utf-8")
    (repo / "research/sub/two.md").write_text("restored second\n", encoding="utf-8")
    _git(repo, "add", "research/one.md", "research/sub/two.md")
    _git(repo, "commit", "-q", "-m", "restore only removal members")
    assert (repo / RECEIPT_REL).read_bytes() == prior_receipt
    next_identity = dataclasses.replace(DEST, author="Next Maintainer")
    next_answers = write_answers_file(tmp_path, next_identity)
    original_unlink = removal.os.unlink
    removed = []

    def fail_second(path, *args, **kwargs):
        try:
            rel = Path(path).relative_to(repo).as_posix()
        except (TypeError, ValueError):
            return original_unlink(path, *args, **kwargs)
        if rel == "research/sub/two.md":
            raise SafetyError("injected second removal failure")
        result = original_unlink(path, *args, **kwargs)
        if rel == "research/one.md":
            removed.append(rel)
        return result

    monkeypatch.setattr(removal.os, "unlink", fail_second)
    capsys.readouterr()
    code = main(
        [
            "--target",
            str(repo),
            "--config",
            str(next_answers),
            "--force",
            "--allow-dirty",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "injected second removal failure" in captured.err
    assert "prior receipt invalidated" in captured.out
    assert removed == ["research/one.md"]
    assert (repo / "research/sub/two.md").read_text(
        encoding="utf-8"
    ) == "restored second\n"
    assert not (repo / RECEIPT_REL).exists()
```

- [ ] **Step 2: RED.**

```bash
uv run pytest tests/rebrand/test_remove_dirs.py -k 'cli_directory or renewal or partial_directory or partial_repress or receipt_read or direct_press or history_router' -q -x
```

  Expected failure is Task 1's deliberate public exit-2 guard. After wiring the
  real executor, retain the directory-rename test until its exact independent
  receipt object and subsequent real verify both pass. A parser-only acceptance
  or internal helper pass does not satisfy this task.

- [ ] **Step 3: Implement history selection and all consumers.**

```python
history = selected_directory_history(
    receipt_text, source, directory_declared=bool(rules.remove_dirs)
)
history_by_dir = {row.dir: row for row in history}
directories = []
for declaration in rules.remove_dirs:
    prior = history_by_dir.get(declaration.dir)
    if mode == "verify" and prior is not None:
        directories.append(prior)
        continue
    current_dir = declaration.dir
    if prior is not None and prior.current_dir != declaration.dir:
        declared_exists = os.path.lexists(target / declaration.dir)
        if declared_exists:
            raise SafetyError(
                f"remove directory {declaration.dir!r} conflicts with recorded "
                f"current root {prior.current_dir!r}; restore a coherent root"
            )
        current_dir = prior.current_dir
    if prior is not None and not os.path.lexists(target / current_dir):
        directories.append(prior)
        continue
    directories.append(
        _freeze_directory(target, declaration, current_dir=current_dir, prior=prior)
    )
```

  Replace a matched history row's reason and each member reason with the active
  declaration's reason via `dataclasses.replace`; retain audit/current paths.
  Use alias-aware refusal checks before exact-key lookup, and verify prior
  absence means every recorded member is absent without following unsafe
  ancestors. `mode="verify"` must still guard the recorded roots and present
  members but cannot fresh-check directory status or add membership. Fresh
  file declarations keep `removed_files_from_receipt`'s legacy missing history
  behavior. In verify mode preserve the existing file sandbox semantics: a
  present regular file can be modeled even when the real file is dirty, and
  a missing file is allowed only by its existing legacy row. Do not accidentally
  apply the new directory clean policy to legacy file-only verification.

  Compose `RemovalPlan(files=file_members, directories=tuple(directories),
  retained_history=tuple(row for row in history if row.dir not in
  {rule.dir for rule in rules.remove_dirs}))`, where `file_members` is the
  tuple produced by the legacy file branch above. Validate
  unique audit/current keys, metadata limits, resolved writer/stub overlaps and
  current-path aliases before returning it. Inactive history is carried for
  receipt preservation in `plan.retained_history`; it never contributes
  `plan.members`. Translation updates those current paths too.

  Wire the source locations in this exact order:

  1. Change the content reads in `check_preconditions` (current `cli.py:223`)
     and the equal-identity branch (`:506`) to `receipt_present(target)`. Preserve
     their existing presence decisions/exit codes; do not decode contents there.
     Keep `--force` invalidation in `main` at its current last pre-mutation
     boundary (`:659`), after all plan gates. `_press` does not own normal CLI
     invalidation. Public `--force` callers receive the frozen plan and text
     history captured before that invalidation.
  2. In `main`, after rule loading and before `build_plan`, read once with
     `removal_receipt_text(target, rules)`, retain `prior_removed =
     removed_files_from_receipt(receipt_text)`, and call `plan_removals(...,
     source=source, receipt_text=receipt_text, legacy_removed=prior_removed)`.
     Construct `effective_rules = removal_rules_view(rules, removal_plan)` for
     `build_plan`, excluded-file gates and warning coverage. Preserve raw rules
     for serialization. Do not filter rewrite/closure inventory.
  3. Retain `gate_problems += preflight_remove_targets(target, rules,
     previously_removed=frozenset(prior_removed))` for raw file declarations at
     its existing aggregated-gate position. `plan_removals` constructs file
     records without newly enforcing their clean/tracked preflight. Directory
     checks run during freezing; other existing gates retain ordering. Use
     `frozen_remove_command_conflicts`, frozen rendering and the translated
     writer/stub/alias checks before showing the plan.
  4. Pass `removal_plan` into `_press`. Replace its initial default/fallback
     block with the code below. This preserves explicitly supplied legacy
     `previously_removed` mappings and does not infer file-history permissions
     from a newly read receipt when a direct caller supplied another mapping.
     Direct file-only `_press` callers keep their existing apply path and do
     not gain a new receipt read. Public no-active callers still supply a plan
     with any recognized inactive history; private legacy callers must supply
     that plan explicitly to opt into new directory-history transport. Active
     directories read bounded history inside the existing exception guard
     before fallback planning/reset; a caller-supplied substitution table does
     not bypass that step.

```python
# At _press entry, before normalizing the optional mapping:
legacy_removed_was_supplied = previously_removed is not None
if previously_removed is None:
    previously_removed = {}
if edit_plans is None:
    edit_plans = []
try:
    if removal_plan is None and rules.remove_dirs:
        receipt_text = removal_receipt_text(target, rules)
        removal_plan = plan_removals(
            target,
            rules,
            source=source,
            receipt_text=receipt_text,
            legacy_removed=(previously_removed if legacy_removed_was_supplied else {}),
        )
    effective_rules = (
        removal_rules_view(rules, removal_plan) if removal_plan is not None else rules
    )
    if table is None:
        fallback_plan = build_plan(target, source, dest, effective_rules)
        rendered_rules = fallback_plan.rendered_rules
        table = fallback_plan.table
    elif rendered_rules is None:
        rendered_rules = declared_rule_triples(table)
except (ValidationError, OSError, subprocess.CalledProcessError, SafetyError) as exc:
    print(f"error: {exc} — nothing applied", file=sys.stderr)
    return PressOutcome(False, [], [], env_error=str(exc))
```

  5. At the existing post-rewrite removal phase, call `apply_removal_plan` when
     a frozen plan exists. Otherwise keep the existing `apply_removals(...,
     previously_removed=frozenset(previously_removed))` call for direct legacy
     callers. Add only actual unlinks to `report.removed`. After success build
     the exact single-emission flat union below. Plan construction validates
     conflicting duplicate audit keys before mutation; this union cannot
     silently collapse two different directory members.

```python
translated = translate_removal_plan(removal_plan, dict(report.renamed))
all_directories = (*translated.directories, *translated.retained_history)
directory_rows = [
    (member.file, member.reason)
    for directory in all_directories
    for member in directory.members
]
file_rows = [
    (member.file, member.reason)
    for member in translated.files
    if member.current_file in report.removed or member.missing_ok
]
emitted = {file for file, _ in (*file_rows, *directory_rows)}
removals = [
    *file_rows,
    *directory_rows,
    *(
        (file, reason)
        for file, reason in previously_removed.items()
        if file not in emitted
    ),
]
# Feed removals=removals and remove_dirs=all_directories to write_receipt.
```

     Keep the old writer construction unchanged for the direct legacy branch
     with `removal_plan is None`. The keyword is a precise union; do not append
     the old `rules.remove`-filtered carry-forward a second time.
  6. In `verify_command`, call `removal_receipt_text`, the existing binding
     check, and `plan_removals(..., mode="verify")` **inside the existing
     preflight `try` at `verify_cli.py:466–507`**, immediately after the receipt
     binding check. Its `_CONFIG_ERRORS` handler then returns `_fail(...)`
     with exit 2 for malformed/unsafe history. Do not put planning between
     that handler and the sandbox `try`. Keep file-only present-regular sandbox
     semantics: no new real-target clean/tracked requirement for file rules.
     Carry the already-frozen plan into `make_sandbox`; use it after existing
     rewrite/reset modeling, then restage. Do not reread the sandbox receipt.
  7. Remove Task 1's temporary public gate only after these paths exist.
     `check_tools` still reports Git and declared commands; no new tool is added.

  In `plan_removals`, resolve its optional `legacy_removed` explicitly:

```python
legacy = (
    removed_files_from_receipt(receipt_text)
    if legacy_removed is None
    else legacy_removed
)
file_members = tuple(
    RemovalMember(
        file=rule.file,
        current_file=rule.file,
        reason=rule.reason,
        missing_ok=rule.file in legacy,
    )
    for rule in rules.remove
)
```

  Legacy preflight and existing apply-time no-follow guards continue to own
  file-only validation. Historical directory absence always comes from the
  strict directory rows, never this tolerant flat mapping.

  Add the following small, independent history-coordinate tests:

```python
def test_historical_ancestor_translation():
    from template_press.rebrand.removal_types import (
        DirectoryRemoval,
        RemovalMember,
        RemovalPlan,
    )
    from template_press.rebrand.remove import translate_removal_plan

    row = DirectoryRemoval(
        dir="old/research",
        current_dir="old/archive",
        reason="r",
        members=(
            RemovalMember(
                file="old/research/demo.md",
                source_dir="old/research",
                current_file="old/archive/renamed.md",
                reason="r",
                missing_ok=True,
            ),
        ),
    )
    updated = translate_removal_plan(RemovalPlan(directories=(row,)), {"old": "new"})
    assert updated.directories[0].current_dir == "new/archive"
    member = updated.directories[0].members[0]
    assert (member.file, member.source_dir, member.current_file) == (
        "old/research/demo.md",
        "old/research",
        "new/archive/renamed.md",
    )
    assert member.missing_ok
```

  Extend the legal CLI fixture with a second active rule
  `pattern="{app_name}.md", paths=true, content=false,
  files=["research/**", "archive/**"]` and member `research/press.md`.
  Independently assert its receipt `file="research/press.md"`,
  `current_file="archive/potato.md"`, and subsequent verify success. This checks
  internal filename translation rather than only a root rename. Add a direct
  `_press` call using `load_rules(repo)`, empty command/reset lists and no supplied
  plan; assert it produces the same member receipt and refuses a dirty directory
  before mutation. Existing `_press` tests provide the actual call fixture.

- [ ] **Step 4: GREEN and required gates.**

```bash
uv run pytest tests/rebrand/test_remove_dirs.py tests/rebrand/test_remove_dir_receipt.py tests/rebrand/test_remove_rules.py tests/rebrand/test_verify_cli.py -q
PYTEST_ADDOPTS='-n 8' just check
just matrix
```

- [ ] **Step 5: Commit and review.**

```bash
git add src/template_press/rebrand/remove.py src/template_press/rebrand/cli.py src/template_press/rebrand/verify_cli.py src/template_press/rebrand/regen.py tests/rebrand/test_remove_dirs.py
git commit -m "feat(remove): integrate directory history with press and verify"
```

## Task 5: Discriminating membership and historical scanner controls

**Files:** create `tests/rebrand/test_remove_dir_controls.py`; change production
only for a demonstrated in-scope defect. These tests are not a rename-model
expansion. They expose the exact destructive widening that ordinary happy-path
assertions cannot detect.

**Interfaces:** consumes `plan_removals`, `apply_removal_plan` and real
`verify_command`; produces independent expected-output oracles. Injected movement
occurs strictly after successful production `engine.apply` and immediately before
`apply_removal_plan`. The lower-level harness does not call the full CLI after
injection and does not promise concurrent CLI acceptance.

- [ ] **Step 1: Add the actual production and broken-control harness.**

```python
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from template_press.rebrand.engine import apply
from template_press.rebrand.receipt import read_receipt
from template_press.rebrand.remove import apply_removal_plan, plan_removals
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import DEST, _git, write_answers_file
from .test_remove_dirs import directory_repo, point_origin, rename_directory_repo
from template_press.rebrand.cli import main


def apply_oracle(tmp_path: Path, execute) -> None:
    repo, source, destination = rename_directory_repo(tmp_path)
    rules = load_rules(repo)
    plan = plan_removals(repo, rules, source=source)
    assert [m.file for m in plan.members] == ["research/one.md", "research/two.md"]
    report = apply(repo, source, destination, rules)
    assert (repo / "archive/one.md").is_file()
    # Explicit lower-level injection; this is not an alleged [[replace]] move.
    os.rename(repo / "incoming/late.md", repo / "archive/late.md")
    removed = execute(repo, plan, dict(report.renamed))
    assert set(removed) == {"archive/one.md", "archive/two.md"}
    assert not (repo / "archive/one.md").exists()
    assert not (repo / "archive/two.md").exists()
    assert (repo / "archive/late.md").read_text(encoding="utf-8") == "outside member\n"
    assert (repo / "archive").is_dir()


def reexpand_at_apply(repo, plan, renamed):
    # Deliberately broken production alternative: current filesystem widens
    # deletion authority after successful renames.
    removed = []
    for path in sorted((repo / "archive").rglob("*")):
        if path.is_file():
            path.unlink()
            removed.append(path.relative_to(repo).as_posix())
    return removed


def test_apply_membership_oracle(tmp_path):
    apply_oracle(tmp_path / "candidate", apply_removal_plan)
    with pytest.raises(AssertionError):
        apply_oracle(tmp_path / "broken", reexpand_at_apply)


def run_verify_fixture(tmp_path: Path, capsys):
    repo = directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, DEST)
    (repo / "research").mkdir()
    # A tracked, excluded, identity-bearing nonmember is not rewritten. Only
    # the independent scan exposes it unless verify wrongly deletes it.
    (repo / "research/nonmember.md").write_text(
        DEST.package_name + "\n", encoding="utf-8"
    )
    rules_path = repo / "press/press-rules.toml"
    rules_path.write_text(
        '[rules]\nextra_exclude_files=["research/nonmember.md"]\n'
        + rules_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(repo, "add", "research/nonmember.md", "press/press-rules.toml")
    _git(repo, "commit", "-q", "-m", "new nonmember and exclusion only")
    capsys.readouterr()
    code = verify_command(["--target", str(repo), "--json"])
    import json

    payload = json.loads(capsys.readouterr().out)
    assert (repo / "research/nonmember.md").read_text(
        encoding="utf-8"
    ) == DEST.package_name + "\n"
    return code, payload


def assert_historical_nonmember_visible(code, payload):
    assert code == 1, "historical verify lost the nonmember finding"
    assert payload["verified"] is False
    assert any(
        row["path"] == "research/nonmember.md" and row["field"] == "package_name"
        for row in payload["surviving"]
    )


def test_verify_membership_oracle(tmp_path, monkeypatch, capsys):
    import template_press.rebrand.verify_cli as verify_module

    assert_historical_nonmember_visible(
        *run_verify_fixture(tmp_path / "candidate", capsys)
    )
    real_planner = verify_module.plan_removals

    def fresh_verify_plan(target, rules, **kwargs):
        # Deliberately broken verify: preserve receipt-based missing-file
        # handling but renew the set as though an explicit press was requested.
        return real_planner(target, rules, **{**kwargs, "mode": "press"})

    monkeypatch.setattr(verify_module, "plan_removals", fresh_verify_plan)
    code, payload = run_verify_fixture(tmp_path / "broken", capsys)
    # First prove the mutant falsely succeeds; an early refusal cannot pass.
    assert code == 0, (code, payload)
    assert payload["verified"] is True
    assert payload["surviving"] == []
    assert payload["stale_ignores"] == []
    assert payload["unavailable_submodules"] == []
    with pytest.raises(AssertionError, match="lost the nonmember finding"):
        assert_historical_nonmember_visible(code, payload)
```

  The concrete broken-path guard above must reach exit 0, `verified=true`, and
  empty `surviving`, `stale_ignores`, and `unavailable_submodules` before the
  shared oracle is expected to fail. JSON parsing or fixture/discovery failure
  occurs outside `pytest.raises`, so it cannot masquerade as discrimination.

- [ ] **Step 2: Execute positive and inverse controls.**

```bash
uv run pytest tests/rebrand/test_remove_dir_controls.py -q -vv
```

  Expected: both tests pass because real production satisfies each oracle and
  each deliberately broken alternative is caught. Record the candidate success,
  the broken alternative's actual output, and the precise failing oracle
  assertion. Never report the broken implementation's anticipated failure as a
  production RED from Task 1. If either candidate fails, reproduce its defect
  before fixing and repeat only the affected tests plus required gates.

- [ ] **Step 3: Pressure-test no-receipt and history ambiguity.** Add exact
  paired controls: after a successful directory press, recreate both the
  declaration root and different recorded current root, then assert re-press
  exits 2 without rewriting either file. Change one receipt member's current
  location to an outside sentinel and assert verify exits 2 and the sentinel
  is unchanged. These exercise refusal rather than scanner correctness:

```python
def test_history_cannot_delete_outside_member(tmp_path, capsys):
    repo, source, destination = rename_directory_repo(tmp_path)
    answers = write_answers_file(tmp_path, destination)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    point_origin(repo, destination)
    receipt_path = repo / "press/press-receipt.toml"
    text = receipt_path.read_text(encoding="utf-8")
    assert 'current_file = "archive/one.md"' in text
    receipt_path.write_text(
        text.replace(
            'current_file = "archive/one.md"', 'current_file = "incoming/late.md"'
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert verify_command(["--target", str(repo)]) == 2
    assert "current_dir" in capsys.readouterr().err
    assert (repo / "incoming/late.md").read_text(encoding="utf-8") == "outside member\n"
```

- [ ] **Step 4: Full required gates.**

```bash
PYTEST_ADDOPTS='-n 8' just check
just matrix
```

- [ ] **Step 5: Commit and review.**

```bash
git add tests/rebrand/test_remove_dir_controls.py
git commit -m "test(remove): discriminate frozen membership from re-expansion"
```

  If a confirmed production defect required correction, stage only its exact
  source files with their tests and choose a corresponding lowercase `fix(remove)`
  subject. Keep the broken alternatives in tests; never install them in shipped
  code or leave a temporary mutant in the worktree.

## Task 6: Native research migration, docs and final committed-head acceptance

**Files:** modify `press/press-rules.toml`, `tests/rebrand/test_matrix.py`,
`docs/source/reference/cli.md`. Preserve all explicit project file declarations and
`projects/.gitkeep`. This task also finalizes the reviewed design/plan documents.

**Interfaces:** public TOML `[[remove]] dir` and existing native matrix harness.

- [ ] **Step 1: Verify the native migration boundary and add RED assertions.**

```bash
git ls-files -- docs/research projects/.gitkeep
git status --porcelain -- docs/research press/press-rules.toml
rg -n 'docs/research|projects/|\[\[remove\]\]' press/press-rules.toml
```

  At this baseline the six research members are the exact list below. If the
  parent changes, reconcile the explicit list with tracked content before
  adopting it; never delete a newly added operator file by assuming this list is
  current. Add a non-live native declaration test and extend native R3:

```python
def test_native_directory_declaration():
    from template_press.rebrand.rules import load_rules

    rules = load_rules(REPO_ROOT)
    assert [(r.dir, r.reason) for r in rules.remove_dirs] == [
        ("docs/research", "engine research notes")
    ]
    assert not any(r.file.startswith("docs/research/") for r in rules.remove)
    assert not any(r.file == "projects/.gitkeep" for r in rules.remove)
    assert sum(r.file.startswith("projects/") for r in rules.remove) == 12
```

  Append these assertions inside existing `test_r3_self_press_native`, after its
  parsed receipt:

```python
expected_research = {
    "docs/research/0001-skill-trigger-optimization.md",
    "docs/research/0002-dev-tooling-wishlist.md",
    "docs/research/0003-init-post-init-analysis.md",
    "docs/research/0004-py-launch-blueprint-conformance-gaps.md",
    "docs/research/0005-scaffolder-identity-variant-handling.md",
    "docs/research/README.md",
}
assert not (target / "docs/research").exists()
assert (target / "projects/.gitkeep").is_file()
(directory,) = receipt["press"]["remove_dir"]
assert directory["dir"] == "docs/research"
assert {row["file"] for row in directory["members"]} == expected_research
assert expected_research <= {row["file"] for row in receipt["press"]["remove"]}
_git(
    target,
    "remote",
    "set-url",
    "origin",
    f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
)
assert verify_command(["--target", str(target)]) == 0
```

  Import `verify_command` from the production verifier and `_git` from
  `tests/rebrand/conftest.py`. Repoint fixture `origin` after every successful
  press before verification or another press: press rewrites identities in
  files, never Git configuration. Existing R3's native
  command/exemption assertions remain. The additional verify models declared
  commands according to existing exemptions; it is not a second real tool run.

- [ ] **Step 2: RED against the six file declarations.**

```bash
uv run pytest tests/rebrand/test_matrix.py::test_native_directory_declaration -q
```

  Expected mismatch: no directory declarations. This is the meaningful native
  RED before changing the checked-in TOML.

- [ ] **Step 3: Replace only the six research rows and add public documentation.**

```toml
# Engine design research is template history; the project scaffold is retained.
[[remove]]
dir = "docs/research"
reason = "engine research notes"
```

  Insert this complete documentation under the existing `[[remove]]` section in
  `docs/source/reference/cli.md`, preserving the file example:

> Use `dir` to remove the tracked files selected from a directory at planning
> time. Declare exactly one of `file` or `dir`, with a nonempty reason. Globs and
> per-directory exclusions are not supported.
>
> ```toml
> [[remove]]
> dir = "research"
> reason = "template-only research notes"
> ```
>
> The preview lists every selected file and the directory count, including zero
> files for an existing empty directory. Uncommitted or untracked work inside the
> directory refuses the press even with `--allow-dirty`. Symlinks, junctions and
> gitlinks refuse. A `.gitignore`, `.gitattributes`, `.gitmodules`, or configured
> Git visibility input anywhere under the directory also refuses. Move that input
> out of the directory or declare the remaining files individually. Ignored ordinary files are not added to the selection; they
> remain and can prevent the directory from becoming empty.
>
> Removals run after rewriting and renaming, before declared commands. Only the
> selected members are deleted, at their successfully renamed locations. The
> selected directory and member ancestors are removed when empty. Unrelated empty
> child directories remain. A partial failure can leave changed files and writes
> no success receipt; use the reported Git recovery guidance.
>
> The receipt records each member's source path and its current location, including
> complete empty selections. `press verify` uses that recorded membership and
> keeps subsequently added files visible to its scan. Without recorded history,
> `press verify` applies the same clean-directory check as a real press, so
> uncommitted work inside that directory refuses verification too. A later explicit real
> press can select newly committed members after its clean-directory checks.
> Missing directories require complete, verified history matching the current
> source identity. Ambiguous old/current roots refuse. Older versions that do
> not understand `dir` or directory history cannot safely re-press this target.

- [ ] **Step 4: GREEN and full checks before the native declaration commit.**

```bash
uv run pytest tests/rebrand/test_matrix.py::test_native_directory_declaration -q
PYTEST_ADDOPTS='-n 8' just check
```

  Root-wide Ruff is required: CI formats Python code fences in Markdown. Do not
  limit formatting to `src/`. Review any formatting changes so unrelated files
  are not swept into the commit.

- [ ] **Step 5: Commit the native declaration, then run committed-head acceptance.**

```bash
git add press/press-rules.toml tests/rebrand/test_matrix.py docs/source/reference/cli.md docs/superpowers/specs/2026-09-06-p11-directory-removals-design.md docs/superpowers/plans/2026-09-06-p11-directory-removals.md
git commit -m "feat(remove): migrate native research cleanup to directory rules"
just matrix
```

  Native R3 clones committed HEAD; the earlier baseline matrix cannot prove this
  declaration. If acceptance fails, retain that failure evidence, fix only the
  demonstrated cause, rerun targeted/full checks, commit the fix, and rerun
  `just matrix` against the corrected committed HEAD. Do not publish the failing
  candidate. Finish with controller review of the exact final commit, clean Git
  status, task evidence and preserved file-only regressions. Windows native
  acceptance remains an explicit platform result; a POSIX run cannot certify it.

## Acceptance and delivery status

The corrected major plan review passed, and the owner adopted the two-part
acceptance amendment as recorded above. Implementation proceeds through these
six tasks under the existing PR creation and merge authorization. Technical
review approval does not substitute for the required tests, committed-head
acceptance, or current PR checks and review-thread resolution. P12 remains an
evaluation step after P10 and P11 delivery.
