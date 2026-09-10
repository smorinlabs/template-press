# P12 — Origin guard relaxation, closure diagnostics, warnings and docs

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [2026-09-01 press-improvements-g2p design spec](../docs/superpowers/specs/2026-09-01-press-improvements-g2p-design.md)
  §E1, §E2, §E3, §E5(a)(b)(d), §E8, §E9
- **Review:** [E1-review.md](../docs/superpowers/specs/reviews-2026-09-01/E1-review.md)
- **Review:** [E1-options-review.md](../docs/superpowers/specs/reviews-2026-09-01/E1-options-review.md)
- **Review:** [E2-review.md](../docs/superpowers/specs/reviews-2026-09-01/E2-review.md)
- **Review:** [E2-codex-review.txt](../docs/superpowers/specs/reviews-2026-09-01/E2-codex-review.txt)
- **Review:** [E3-review.md](../docs/superpowers/specs/reviews-2026-09-01/E3-review.md)
- **Review:** [E8-review.md](../docs/superpowers/specs/reviews-2026-09-01/E8-review.md)
- **Review:** [2026-09-10 follow-up value evaluation](../docs/superpowers/reviews/2026-09-10-p12-value-evaluation.md)

- **Status:** `[~]` in progress. Base parts 1 and 2 were delivered in
  [PR #109](https://github.com/smorinlabs/template-press/pull/109) and
  [PR #111](https://github.com/smorinlabs/template-press/pull/111). Four follow-up
  corrections are implemented on `fix/p12-follow-up-corrections`; six proposed
  closures still need owner disposition. P12-T-defer-6 is already complete.

The owner inserted [P11A — CI speed and cost optimization](P11A-ci-speed-and-cost-optimization.md)
before this value review. P09, P10, P11 and P11A are now merged. P11A closed in
[PR #124](https://github.com/smorinlabs/template-press/pull/124), and its merged
source `7ac8c1744485081d973ac6b910f13de3fb459d83` passed main-branch CI.

On 2026-09-10, the owner requested a critical evaluation of the ten open items:
confirm the actual behavior and likelihood, distinguish bugs from optional
improvements, compare the value with the complexity, and identify any departure
from accepted requirements. This evaluation is not implementation approval or a
new decision to close an item. The task entries below preserve the original
claims until that evaluation and the owner's dispositions are recorded.

The evaluation recommends fixing P12-T-defer-2 and P12-T-defer-7, narrowing
P12-T-defer-4 and P12-T-defer-5, and closing the other six without implementation.
The owner then instructed: "Solve all four." Commit `86e0885` implements those
four corrections. The other six recommended closures have not
been recorded as owner decisions. This project and its closeout are limited to
Template Press; downstream feedback-log work is not a P12 dependency.

The task checkboxes below record implementation, not merge or release status.
Delivery of these four corrections is tracked by the pull request for
`fix/p12-follow-up-corrections`. Local validation passed `just check` with
2,193 tests passed and 24 skipped, followed by the two-test cleanup-hint family
after correcting its platform-specific expectation. The native self-rebrand
case passed against committed source `86e0885`. Independent internal review
found no unresolved implementation issue. Native Windows execution remains
a pull-request CI gate.

E1 origin==destination acceptance + `--accept-origin-mismatch`; E2
aggregated closure refusal with remedy argv and `--diagnostics-json`;
E5(a)(b)(d) removal coverage warning/counts/own declarations; E8
dir-only-ignore near-miss hint; E9 prefix-only warning; E3 docs + boundary
test.

### Tests & Tasks

- [ ] [P12-T-defer-1] Batch the verify/doctor ignore-probe `git check-ignore --stdin` calls (one process per path today; ~19 s per 500 untracked findings) — from PR #109 review.
- [x] [P12-T-defer-2] Removal-coverage warning: count excluded tracked descendants carried by directory renames using the captured closure, deduplicated in original source coordinates. Rename authorization and excluded-file content remain unchanged.
- [ ] [P12-T-defer-3] Removal-coverage warning: count tracked symlinks whose target is retargeted as rewritten paths.
- [x] [P12-T-defer-4] Retained documentation: replace the five links into deliberately removed research with named historical references in `docs/README.md`, `docs/design/0004` and `0008`. Research removal policy is unchanged.
- [x] [P12-T-defer-5] Windows recovery presentation: show explicitly labeled JSON argument arrays for cleanup and restoration guidance, preserve preview-first and conditional cleanup instructions, and retain POSIX shell quoting. Structured refusal output is unchanged.
- [x] [P12-T-defer-6] `press verify` policy for a flag-accepted press: today verify exits 2 (unrelaxed `mismatches()`) until `origin` is repointed. Options: a matching `--accept-origin-mismatch` on verify, or record the exact accepted origin values in the receipt and accept only those. A field-name-only receipt list must not be trusted automatically (a stale receipt would waive any future value) — from the Task 10 Codex review.
      Done (Task 10b): the receipt records `origin_mismatch_accepted = { owner = "…", repo_name = "…" }` and verify waives a mismatch only when the discovered value equals the recorded one, and only from a receipt BOUND to that target (`verified = true` plus a `[press.to]` equal to its own `press-source.toml`); the 4.1 list form, a receipt describing a different identity, and a hand-written one are all not honored (fail closed); binding is by identity, not provenance.
- [x] [P12-T-defer-7] Document the existing `rmdir_paths` field in `docs/source/reference/cli.md`: sorted empty-directory paths relative to the target, complete even when prose is truncated, and empty when no empty directories were found.
- [ ] [P12-T-defer-8] Prefix-only tally: count occurrences after earlier `[[replace]]` rows have consumed their matches, so a token rewritten by a prior row is not reported as a prefix-only survivor — promised in PR #109 triage.
- [ ] [P12-T-defer-9] `press verify --json` emits no JSON object on a preflight refusal (source-config, identity mismatch, unhonored receipt): stderr + exit 2 with empty stdout, pre-existing. Give it a structured refusal object like `press rebrand --diagnostics-json` — from the Task 10b Codex re-check.

- [ ] [P12-T-defer-10] Evaluate stronger concurrent-writer protection for `press clean`. P10 requires ignore/configuration inputs, the index, and selected paths to stay stable; its immediate file checks can refuse detected changes but do not make Git directory cleanup or exact unlink atomic. Assess whether binding deletion to a frozen selection or adding a stronger coordination protocol is worth the complexity, or close this follow-up with the stable-input contract documented. This is a P12 value decision after P10/P11 delivery, not a promised implementation. Tracked from [PR #122 concurrency review](https://github.com/smorinlabs/template-press/pull/122#discussion_r3946789616).

- [ ] [P12-T-defer-11] Evaluate repeated filesystem identity checks during directory removal. The P11 review measured 7 Git-input `os.stat` calls for 2 selected members and 3 existing inputs, versus 595 calls for 27 members and 22 inputs. This demonstrates repeated work, not large-repository latency or CI savings. Consider capturing input identities once per validated snapshot only if representative timing shows useful value and path, hardlink and concurrent-change guards remain equivalent; otherwise close the follow-up with the measured limits. This is a value-evaluation candidate after P11/P11A, not an approved caching implementation. Tracked from [PR #123 identity-check review](https://github.com/smorinlabs/template-press/pull/123#discussion_r3964065441).
