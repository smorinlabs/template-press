# P14 — TypeScript and Bun targets

- **Status:** `[~]` in progress on branch `feat/typescript-targets`

Make npm and Bun TypeScript repositories first-class `press` targets without
changing any existing target's outcome.

**References**

- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Design:** [TypeScript and Bun targets design](../docs/superpowers/specs/2026-11-22-typescript-bun-targets-design.md)
- **Plan:** [TypeScript and Bun targets plan](../docs/superpowers/plans/2026-11-22-typescript-bun-targets.md)

### Scope

- Discover identity from the root `package.json`; a target with several root
  manifests declares `[rules] languages`.
- Add optional exact `npm_name` and `cli_name` identity fields.
- Add an explicit `keep_names` list honored by every rewrite and scan.
- Refuse undeclared same-prefix names before any write, with a sibling preflight.
- Exempt declared `package-lock.json` and `pnpm-lock.yaml` regeneration from
  hermetic verify, and suggest declarations without running them.
- Prove npm and Bun targets end to end with synthetic fixtures.

### Merge order

Prerequisites landed before this work: PR #152 and PR #156.

### Out of scope

- Workspace-member identity, Rust or other ecosystems, provisioning, publishing,
  and automatic regeneration commands.

### Tests & Tasks

- [x] [P14-T01] Add identity fields and validators
- [x] [P14-T02] Discover and cross-check `package.json`
- [x] [P14-T03] Propose a source config from `package.json`
- [x] [P14-T04] Rewrite and scan exact npm and CLI names
- [x] [P14-T05] Load `keep_names` and protect rewrites
- [x] [P14-T06] Honor `keep_names` in every scan and report
- [x] [P14-T07] Handle npm, Bun, and pnpm lockfiles
- [x] [P14-TS01] Prove npm, Bun, and pnpm targets end to end
- [ ] [P14-T08] Update documentation and open the PR
