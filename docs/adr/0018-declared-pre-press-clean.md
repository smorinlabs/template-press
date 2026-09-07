# 0018. Declared pre-press clean is a standalone exact-scope verb

- **Status:** Accepted
- **Date:** 2026-09-05
- **Amended:** 2026-09-07
- **Deciders:** Maintainers
- **Related:** [external-target model](../design/0006-external-target-model.md);
  [press improvements design](../superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E10; [CLEAN review](../superpowers/specs/reviews-2026-09-01/CLEAN-review.md);
  [P10 planning gate](../superpowers/specs/reviews-2026-09-05/P10-planning-gate.md);
  [exact-file amendment](../superpowers/specs/2026-09-07-p10-exact-file-clean-amendment.md);
  [project P10](../../projects/P10-declared-pre-press-clean.md)

## Context

A press renames the package directory. The rename-closure guard refuses when
that directory holds content absent from the surface inventory. The commonest
such content is an ignored build cache such as `__pycache__`. The refusal
already prints a `git clean -fdX` remedy, but the remedy is undeclared,
operator-typed, and broader than the paths at fault. A template should be able
to declare which paths an operator may clean.

The original decision sent every rendered declaration to one root-level,
literal `git clean -fdX` command. Real Git evidence disproved exact file
selection under that architecture. When `build/` is ignored, a declaration of
`build/one.txt` can remove `build/two.txt` and the parent directory. The same
widening can occur when the declared descendant is missing. Changing Git's
working directory, pinning `--git-dir`, or dropping `-d` does not restore the
required exact-file boundary.

## Decision

Add `[[clean]] paths = [...]` with optional `platforms`, and add the standalone
`press clean --target <dir> [--show]` verb. The engine renders each literal
path from the SOURCE identity. The rules file is never rewritten. A rendered
path may name one regular file or one directory; a missing path is a no-op.

Use two removal mechanisms because Git cannot enforce the approved exact-file
boundary:

1. For a regular file, query Git's current ignore and index policy with
   `check-ignore -z --stdin`. Unlink only that selected directory entry when it
   is ignored and untracked. Identity validation may enumerate stored names,
   but it never selects or removes an unselected sibling and never adds deletion
   authority. Do not prune the parent or send the file to `git clean`.
2. For directories, run at most one hardened
   `git --literal-pathspecs clean -fdX -- <directories>` command. Use `-ndX`
   under `--show`. A directory with an ignored proper ancestor is refused
   because Git may widen deletion to that ancestor. An explicitly selected
   ancestor authorizes that broader scope. Collapse duplicate and covered
   declarations first, and never invoke Git with an empty directory list.

Both mechanisms scrub global and system Git configuration and clear inherited
Git pathspec-mode variables. They pin the repository-configured
`core.excludesFile` or the null device, which prevents Git from loading its
default user ignore file. Exact-file queries use NUL-delimited, canonical
root-relative names. `check-ignore` does not receive `--literal-pathspecs` or
`--no-index`; its standard-input names are already literal, and its index-aware
result is required to protect tracked files.

Before planning any action, `press clean` captures the target's public
`SurfaceSnapshot`. It checks the original rendered scope against active Git
visibility and repository-configuration inputs. It also checks every present
declared configuration-include candidate and every present press-owned control
file. A candidate that lies inside cleanup scope and is absent from the
protected tracked-plus-nonignored surface causes exit `2`. The stricter
configured-excludes rule remains: a configured path equal to or below a clean
path refuses even when that configured file is missing. Comparisons support
SOURCE-rendered paths and existing filesystem case aliases, while distinct
hardlink names remain independently selectable.

Every declaration receives a finite, no-follow ancestor and node check before
planning. Symlink or junction ancestors, non-directory ancestors, unexpected
metadata errors, and nested repository boundaries refuse the complete batch. A
tracked leaf is a no-op. An untracked selected leaf must be a regular file or
directory; an untracked symlink or special-file leaf refuses. A declared
junction leaf always refuses before file-or-directory routing. These checks
also apply to declarations later covered by an explicitly selected directory.

All initial checks finish before any action or command output or deletion;
refusals can print diagnostic errors. Exact-file output always applies `repr`,
Python's safe string representation, to the canonical root-relative POSIX
string and never to a `Path` object:

```text
would remove file: 'build/one.txt'
removed file: 'build/one.txt'
```

`--show` prints the first line for an eligible exact file and runs only the real
Git directory preview, if present. Apply prints the second line only after a
successful unlink. It revalidates the frozen entry, its real parent chain,
current tracked names, and ignore eligibility immediately before each unlink.
Revalidation can refuse an action but cannot add one. A batch containing only
no-ops produces no stdout. `--show` describes current inputs; a later apply can
differ or refuse after those inputs change.

On Windows, a `PermissionError` from an exact unlink receives one retry only
when a fresh no-follow check proves the same file has the read-only attribute.
The engine revalidates before clearing that attribute and before the retry. A
failed retry may leave the selected file's read-only attribute cleared. This
follows [Git for Windows' unlink handling](https://github.com/git/git/blob/master/compat/mingw.c)
and Python's documented [`os.chmod` Windows behavior](https://docs.python.org/3.13/library/os.html#os.chmod),
where `stat.S_IWRITE` controls the read-only attribute.

Clean is never a phase of `press rebrand`: dry-run and apply must observe the
same tree. Ordering is structural — the closure refusal names `press clean`
when rules are declared — with no stamp file. `press verify` is unaffected by
construction (the sandbox holds inventoried entries only). The receipt records
`[[press.clean]] paths = [...]` as a declaration; `press clean` writes no
receipt. `press check-tools` lists one informational row per rule.

## Consequences

- Exit codes keep the 0/1/2 contract. Exit `0` means every eligible action or
  preview succeeded, including a batch with nothing eligible. Exit `2` means a
  preflight or first pre-action refusal, or an initial cleanup-launch failure,
  occurred with no exact unlink attempted and no Git clean process started;
  read-only Git queries may already have run. Exit `1` means an exact unlink was
  attempted and failed, a Git cleanup or preview process started and returned
  nonzero, or a later refusal occurred after cleanup began. Failure stops later
  actions and reports that earlier cleanup may have completed.
- Arbitrary clean commands remain out of scope; they would need the
  before/after invariant the CLEAN review specified.
- Exact cleanup supports untracked regular files only. Tracked leaves are
  no-ops. Untracked symlink and special-file leaves refuse, and declared
  junction leaves always refuse. Directory cleanup still relies on Git's
  nested-repository behavior below an explicitly selected directory.
- Cleanup is fail-fast but not transactional. Ignore files, repository
  configuration, the index, and selected paths must remain stable. Immediate
  revalidation does not make policy checks and unlink atomic. There is no
  rollback or success receipt.
- Live tracked-name revalidation lists the complete cached index once per
  selected exact file. Its work therefore grows with both the selected-file
  count and the index-entry count. This amendment accepts that cost to avoid an
  unreviewed name prefilter at the safety boundary.
