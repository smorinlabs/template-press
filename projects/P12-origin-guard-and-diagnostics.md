# P12 — Origin guard relaxation, closure diagnostics, warnings and docs

- **Status:** `[~]` in progress — PR #109 is part 1.

E1 origin==destination acceptance + `--accept-origin-mismatch`; E2
aggregated closure refusal with remedy argv and `--diagnostics-json`;
E5(a)(b)(d) removal coverage warning/counts/own declarations; E8
dir-only-ignore near-miss hint; E9 prefix-only warning; E3 docs + boundary
test.

### Tests & Tasks

- [ ] [P12-T-defer-1] Batch the verify/doctor ignore-probe `git check-ignore --stdin` calls (one process per path today; ~19 s per 500 untracked findings) — from PR #109 review.
- [ ] [P12-T-defer-2] Removal-coverage warning: count excluded descendants carried by directory renames (closure), not only `source_entries` — under-warns today.
- [ ] [P12-T-defer-3] Removal-coverage warning: count tracked symlinks whose target is retargeted as rewritten paths.
- [ ] [P12-T-defer-4] Self-press rules: retained docs (`docs/README.md`, `docs/design/0004`, `0008`) link to `docs/research/*` files the rules remove — reset/update the referrers or retain the targets.

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
