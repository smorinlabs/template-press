# P10 exact-file `press clean` amendment

**Status:** Owner-approved contract; implementation validation and independent
closeout review are pending.

This amendment changes P10, the declared pre-press cleanup project, so one
`[[clean]]` path can select one regular file without authorizing deletion of
its siblings. It preserves the accepted standalone command, SOURCE placeholder
rendering, 0/1/2 exit-code family, and Git-delegated directory cleanup.

## Reason for the amendment

Real Git demonstrates that a root-level
`git --literal-pathspecs clean -fdX -- build/one.txt` command is not an exact
file deletion boundary when `build/` is ignored. Git can remove the ignored
parent, `build/two.txt`, and other unselected siblings. The widening also occurs
for some missing descendants. The permanent inverse controls in
[`test_clean_file_selection.py`](../../../tests/rebrand/test_clean_file_selection.py)
reproduce both failures with real Git, then apply the production
sibling-preservation oracle.

The owner approved exact individual-file selection plus the existing input and
scope protections. Changing Git's working directory, pinning `--git-dir`, or
dropping `-d` did not satisfy the same preservation oracle. The accepted design
therefore splits exact-file removal from directory cleanup.

## Approved contract

### Exact regular files

- Render and validate every literal `[[clean]]` path before cleanup. Missing,
  tracked, and nonignored file selections are silent no-ops.
- Classify present regular files with the target's current index and ignore
  policy. The query uses NUL-delimited, canonical root-relative names with
  `git check-ignore -z --stdin`. It uses the same resolved Git executable,
  hardening, scrubbed environment, and pinned `core.excludesFile` as cleanup.
- Unlink only a selected file that Git reports ignored and untracked. Preserve
  the parent and every unselected sibling. Distinct hardlink names remain
  independent selections; filesystem case aliases for one entry are
  deduplicated.
- Before each unlink, revalidate the frozen entry and real parent identities,
  current tracked names from `git ls-files -z --cached`, and current ignore
  eligibility. A change can refuse a planned action but can never authorize a
  new action or promote a file into recursive directory cleanup.
- File action output applies `repr`, Python's safe string representation, to
  the canonical root-relative POSIX string and never to a `Path` object. The
  exact preview and successful-apply lines are:

  ```text
  would remove file: 'build/one.txt'
  removed file: 'build/one.txt'
  ```

  Apply prints its line only after successful unlink. A file-only or no-op-only
  plan never launches an empty `git clean` command.

### Directories

- Reduce explicitly selected real directories to minimal roots, then run at
  most one hardened `git clean -fdX` command. `--show` uses `-ndX`.
- Refuse a selected directory beneath an ignored proper ancestor because Git
  can remove content outside that selected directory. Selecting the ancestor
  explicitly authorizes its broader scope.
- An explicitly selected directory covers declared descendants. This reduction
  occurs only after every original declaration passes input and no-follow path
  checks.

### Whole-batch safety

- Complete all initial checks before printing an action or command line. A
  preflight refusal preserves every selected entry.
- Protect active Git visibility and configuration inputs, all present declared
  Git include candidates, and all present press-owned control files when they
  are absent from the tracked-plus-nonignored surface. Preserve the stricter
  rule that an overlapping configured `core.excludesFile` refuses even when the
  configured file is missing.
- Inspect every declaration through a finite no-follow path walk. A tracked
  leaf is a no-op. Refuse symlink or junction ancestors, non-directory
  ancestors, nested repository boundaries, and unexpected metadata errors.
  Refuse an untracked symlink or special-file leaf. Always refuse a declared
  junction leaf before file-or-directory routing.
- Clear inherited `GIT_GLOB_PATHSPECS`, `GIT_NOGLOB_PATHSPECS`,
  `GIT_LITERAL_PATHSPECS`, and `GIT_ICASE_PATHSPECS` for engine Git calls.
- On Windows, retry an exact unlink once only after proving the same file has
  the read-only attribute. Revalidate before clearing the attribute and before
  retrying. A failed retry may leave the attribute cleared.

## Failure behavior

| Code | Contract |
|---|---|
| `0` | Every eligible action or preview succeeded, or nothing was eligible. |
| `1` | An exact unlink was attempted and failed; a Git cleanup or preview process started and returned nonzero; or a later refusal or launch failure occurred after cleanup began. Stop subsequent work and report that earlier cleanup may have completed. |
| `2` | A preflight or first pre-action check refused, or the initial cleanup process could not start, with no exact unlink attempted and no Git clean process started. Read-only Git queries may already have run. |

Cleanup is fail-fast and writes no success receipt. It is not transactional:
there is no rollback, and immediate revalidation does not make the final policy
check and unlink atomic. Ignore files, repository configuration, the index, and
selected paths must remain stable. `--show` describes those current inputs; it
does not guarantee that a later apply will produce the same plan or proceed.

Live tracked-name revalidation reads the complete cached index once per
selected exact file. Its work grows with both the selected-file count and the
index-entry count. Correct case-alias protection takes priority over an
unreviewed name prefilter in this amendment. Stronger concurrent-writer
protection is a later design question tracked as
[`P12-T-defer-10`](../../../projects/P12-origin-guard-and-diagnostics.md), the
P12 task for evaluating a stronger concurrent-writer guarantee.

## Validation still required

The delivery gate requires the permanent real-Git inverse controls and positive
file, directory, mixed-plan, no-op, input-protection, path, output, and partial
failure cases to pass. Native Windows jobs must prove junction refusal,
read-only exact-file removal with sibling preservation, and retry-failure
reporting. The repository's full checks, committed-head rebrand matrix,
independent major closeout review, and current pull-request CI and review-thread
refresh remain controller-owned gates. P10 is not complete until its pull
request merges.
