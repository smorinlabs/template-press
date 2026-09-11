# P03 — External-target rebrand press (clean-core rebuild)

- **Status:** `[~]` in progress. M0–M5 and their recorded hardening work are
  complete. PR #131 closes M4d on merge; M6 provision implementation
  remains open. The M6 prerequisite, issue #42, is complete through P06 and
  no longer blocks planning M6.

Rebuild as standalone press: rebrand → provision, verify-then-mark

### Tests & Tasks

- [x] [P03-M0] Design doc 0006 (canonical external-target model);
      0004 §3–7 superseded (merged in #15)
- [x] [P03-M1] Clean core: identity + boundary matching, scan rules,
      engine (replace + fixpoint rename), no-leak doctor (merged in #15)
- [x] [P03-M2] Target & identity: discovery-as-validator, source-config,
      receipt, CLI pipeline with exit-code contract (merged in #15)
- [x] [P03-M3] R1/R2/R3 acceptance matrix (script + live tests + CI) and
      press-target / rebrand-matrix skills (merged in #15)
- [x] [P03-H1] Post-merge sweep hardening: identity validation
      (empty/degenerate values), cross-identity collision guard,
      changed-fields-only verification, `verify_ignore` ignore set,
      symlink confinement, literal replacement
- [x] [P03-M4] Shed residue: delete legacy app + init/, doc site →
      publishable skeleton, docs rewrite, repoint `press` console script
      (merged #18)
- [x] [P03-M4b] Rename press control dir to `press/` + `press-` file
      prefix (visible, uniquely greppable); `press-answers.toml` +
      `press/press-answers.example.toml` convention. Breaking (v3.0.0).
- [x] [P03-M4c] Guard the `press/` dir-name collision and warn about stray
      directories. The original delivery used control markers to identify
      the exempt directory. Later hardening narrowed rewrite/scan exemptions
      to exact root control artifacts through `engine.ROOT_CONTROL`;
      `engine.CONTROL_MARKERS` now serves the advisory warning only. Ordinary
      content under `press/` remains subject to rewrite and leak scanning.
- [x] [P03-M4d] Clarify preview/apply warnings for existing `press/`
      directories and derive the advice from the plan's validated inventory.
      Retain directory reuse; the owner declined a new consent/refusal policy.
      This closeout takes effect when the implementation change merges.
- [x] [P03-M5] Self-publish (2026-07-17): v3.0.0 + v3.1.0 live on PyPI AND
      TestPyPI via OIDC Trusted Publishing (both publishers configured +
      verified end-to-end); release-please bootstrapped (manifest 3.1.0),
      CHANGELOG generated, GitHub releases cut. NB: the planned "version
      reset to 0.1.0" was superseded — the project kept the 3.x line and
      self-published there.
- [x] [P03-M5b] Verify verb registration & docs: wire `press verify` into
      the CLI dispatcher, document the zero-arg CI usage and full `[verify]`
      config schema.
- [x] [P03-M5c] Conformance-gap closure (2026-07-24, v3.3.0): closed the
      py-launch-blueprint dogfood gaps G3/G4/G5 (register 0004) — optional
      `display_name` identity field with a closed, configurable form set;
      exact `[[replace]]` rules with identity interpolation (files/paths/
      content/reason args); per-field opt-in substring rewrite mode; path
      renames riding the shared matchers; doctor/verify scan-symmetry and
      containment hardening across 12 bot-review cycles (45 threads, every
      one fixed or refuted in writing). Decisions in design 0008; merged
      PR #41; released as v3.3.0. Follow-ups tracked as issues #42–#51 —
      #42 (substitution-set refactor) was the deliberate gate before M6.
      It closed as completed on 2026-08-15 through P06.
- [ ] [P03-M6] Provision phase: feature modules (detect/add/verify),
      `press status` computed from reality. The issue #42 prerequisite is
      satisfied; provision/status remain reserved commands that exit 2.
      Scope the successor design before implementation.

<a id="remaining-m4d-follow-ups"></a>

### M4d follow-up closeout

The owner approved this scope on 2026-09-10 after the value evaluation.
The implementation is carried by
[PR #131](https://github.com/smorinlabs/template-press/pull/131), branch
`feature/p03-p07-followups`, starting with commit `ee30a76`. Completion takes
effect on that PR's merge. The three parts are one bounded change.

| Part | Disposition | Value and preserved contract |
| --- | --- | --- |
| M4d (1): discovery-preview warning | Implemented: an unmarked root `press/` now receives a specific metadata-reuse warning. Preview says "would"; apply says "will". | Explains the intended directory reuse. Dry run remains read-only, and source-config writes remain after every exit-2 gate. |
| M4d (2): existing root control location | Implemented the reuse notice with part 1. Owner declined an additional consent prompt, flag or refusal. | Ordinary files remain present and follow normal rewrite/leak-scanning rules. A new blocking policy would add friction without a demonstrated safety benefit. Existing control-file validation and containment guards remain. |
| M4d (3): repeated inventory capture | Implemented: `build_plan()` supplies its validated snapshot to `stray_press_dirs()` and stores the advice on `Plan`. The CLI renders that advice. | Removes an additional inventory capture. Each new plan still captures fresh state, and all repeated capture, Git configuration and ignore-policy stability checks remain. |

Five regression cases cover read-only preview, successful apply with ordinary
file rewriting, nested-directory warnings, control-marker classification,
one capture for planning/advice, and refreshed advice on a later plan.
The affected [CLI reference](../docs/source/reference/cli.md#existing-press-directories)
documents the operator-facing behavior.

The complete local `just check` passed: 2,198 tests passed and 24 skipped,
followed by passing lint, type checking, YAML, spelling and EditorConfig.
All four committed-source live acceptance cases passed with `just matrix`.
PR review and CI remain separate delivery gates.

The local before/after benchmark used a committed seven-file target with
ordinary `press/notes.md`, Python 3.13.14, and five complete discovery dry runs
after one warm-up. Median time decreased from 1.543497 seconds to 1.030054
seconds. Inventory Git calls decreased from 93 to 62, including `ls-files`
calls from 9 to 6. These are measurements of that fixture on this Mac;
results on other targets and platforms are not established by this probe.

The older "one git ls-files" proposal is rejected: multiple reads inside
each capture are intentional stability checks. The change shares the
validated result within one plan and introduces no persistent cache.

### Tracking reconciliation evidence

- [Issue #42](https://github.com/smorinlabs/template-press/issues/42) is closed
  as completed. [P06](P06-substitution-set.md) records implementation PRs
  #73/#75/#76 and safety follow-ups #77/#78. The dependency is satisfied;
  this does not implement M6.
- Direct calls to `template_press.press_cli.main(["provision"])` and
  `main(["status"])` both return 2 with the "coming in M6" message.
- The initial M4d probes used disposable committed fixtures, captured dry-run output
  and before/after file bytes, observed the real Git calls, then applied to
  the fixture. They made no changes to repository product source.
- The initial reconciliation left M4d and M6 open. The subsequent approved
  M4d closeout above leaves the project `[~]` for M6 alone after merge.

### Open questions

- ~~R3 self-press allowlist~~ — resolved empirically: R3 presses this repo
  clean with no allowlist; `verify_ignore` in `press/press-rules.toml` is now
  the mechanism if one is ever needed.

### Notes

- Plan: [docs/superpowers/plans/2026-06-23-rebrand-core.md](../docs/superpowers/plans/2026-06-23-rebrand-core.md)
  covers M0–M3 (rebrand core). Its program map proposed M4 (shed residue),
  M5 (publish 0.1.0), and M6 (provision feature modules) as successors.
  M4 and M5 subsequently shipped; M5 retained the 3.x version line as
  recorded above. M6 remains unimplemented.
- Salvage branch `feat/init-rebrand-robustness` holds the audit docs
  (BUGS.md, EMPIRICAL_BUGS.md, EMPIRICAL_ARCH.md, OPEN_QUESTIONS.md) and
  the port sources (proven engine + boundary matcher + doctor).
- PyPI name `template-press` is already reserved.
- CI usage (to scope in refine): template-press must be usable in CI as a
  drift guard — a configuration declaring keywords that must be completely
  eliminated from the target repo, testable ("is anything still there?").
  The ignore-set half of this requirement shipped as `verify_ignore`
  (`press/press-rules.toml`); the CI-mode verify command shipped in
  P03-M5b (`press verify`, zero-arg CI usage documented).
