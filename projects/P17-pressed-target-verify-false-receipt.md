# [~] Project P17: Pressed-target verify false receipt

**Goal/Requirement**: `press rebrand` must not write a receipt when `press verify`
would exit 1 on the pressed target.

- The press runs the verify check on a private copy of the pressed tree before
  it writes the new source-config or the receipt.
- A verify exit 1 makes the press exit 1 with no receipt and the source-config
  unchanged.
- Targets whose pressed tree passes `press verify` keep their current outcome.

**Out of Scope**

- TypeScript, Bun, Rust, and BAML target work.
- `[P14-T09]` and closing P14.
- A source `app_name` form that survives a press while verify passes afterward.
- Publishing or release work.

### Tests & Tasks

- [x] [P17-TS01] Regression tests in `tests/rebrand/test_pressed_verify_gate.py`
- [x] [P17-T01] Run the verify check before the source-config and receipt writes
- [x] [P17-T02] `make check`, `just check`, `just matrix`, and
      `uv run ruff format --check .` pass
- [ ] [P17-T03] PR opened for owner review

### Deliverable

```text
new app_name "zapp", existing text "_zapp_"
press rebrand: exit 1, no receipt
```

### Automated Verification

- `just check`
- `just matrix`

### Manual Verification

- Owner reviews the PR.
