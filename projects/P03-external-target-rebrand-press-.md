# P03 — External-target rebrand press (clean-core rebuild)

- **Status:** `[~]` in progress — M0–M3 merged (#15) + post-merge sweep
  hardening; M4–M6 are scoped successor plans.

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
- [x] [P03-M4c] Guard the `press/` dir-name collision: exempt a `press/`
      dir from rewrite + no-leak scan ONLY when it holds a control marker
      (`press-*.toml`, content-keyed via `engine.CONTROL_MARKERS`), so an
      unrelated `press/` in a target is rewritten + scanned like any content
      and can never yield a false "verified" receipt; the CLI warns about
      such stray dirs. Closes the "Accepted risk" note in the 2026-07-16
      press-dir-rename spec.
- [ ] [P03-M4d] Follow-ups from the M4c review: (1) on a first
      `--accept-discovery` press the preview's stray-`press/` warning can
      transiently mislabel the soon-to-be control dir (non-mutating; apply
      /doctor are correct) — compute the preview after the deferred
      source-config write or seed the known control path; (2) a pre-existing
      root `press/` still collides with the tool's control location (the
      control files get written into it) — add a precondition warn/refuse;
      (3) minor: share one `git ls-files` between build_plan and
      stray_press_dirs.
- [x] [P03-M5] Self-publish (2026-07-17): v3.0.0 + v3.1.0 live on PyPI AND
      TestPyPI via OIDC Trusted Publishing (both publishers configured +
      verified end-to-end); release-please bootstrapped (manifest 3.1.0),
      CHANGELOG generated, GitHub releases cut. NB: the planned "version
      reset to 0.1.0" was superseded — the project kept the 3.x line and
      self-published there.
- [x] [P03-M5b] Verify verb registration & docs: wire `press verify` into
      the CLI dispatcher, document the zero-arg CI usage and full `[verify]`
      config schema.
- [ ] [P03-M6] Provision phase: feature modules (detect/add/verify),
      `press status` computed from reality

### Open questions

- ~~R3 self-press allowlist~~ — resolved empirically: R3 presses this repo
  clean with no allowlist; `verify_ignore` in `press/press-rules.toml` is now
  the mechanism if one is ever needed.

### Notes

- Plan: [docs/superpowers/plans/2026-06-23-rebrand-core.md](../docs/superpowers/plans/2026-06-23-rebrand-core.md)
  covers M0–M3 (rebrand core); M4 (shed residue), M5 (publish 0.1.0), and
  M6 (provision feature modules) are successor plans with decisions locked
  in the plan's program map.
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
