# press C/D/E Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three remaining py-launch-blueprint conformance gaps (G3 glued app tokens, G4 humanized display name, G5 doc-filename tokens) per the 2026-07-23 codesign decisions.

**Architecture:** Three additive mechanisms on the existing rebrand engine: (1) an optional 7th identity field `display_name` with a closed, configurable set of exact rewrite forms (spaced/pascal/camel); (2) exact-match `[[replace]]` rules in `press-rules.toml` — one template string with `{field}` placeholders, rendered twice (source identity → FROM literal, destination identity → TO literal) — scoped by `files` globs, `paths`/`content` booleans, and a required `reason`; (3) a per-field opt-in substring rewrite mode. Path renames inherit (2) and (3) through the existing `_renamed_rel` pass — no second matching surface. Verify scans `display_name` as its own field when the target declares one.

**Tech Stack:** Python 3.12+, stdlib only (`re`, `fnmatch`, `hashlib`, `tomllib`), pytest, ruff, ty. Dev commands run via `uv run` / `just`.

## Global Constraints

- Worktree: ALL work happens in `/Users/stevemorin/c/template-press-cde` on branch `feat/press-cde-gaps` (never the live checkout at `~/c/template-press`).
- Runtime dependencies: NONE — the shipped package is pure stdlib. Do not add any.
- Python: `requires-python = ">=3.12"` — no 3.13-only APIs (e.g. no `Path.full_match`).
- Line length 88; strict typing on all non-test functions; absolute intra-package imports (`from template_press.…`).
- Commits: Conventional Commits, lowercase subject (commitlint enforces, hooks are installed in this worktree).
- Test command: `uv run pytest tests/rebrand/<file>::<test> -v` (plain `pytest` also works; default excludes `slow`/`live` markers).
- After the final task: `just check` must pass AND `just matrix` (live rebrand acceptance matrix) must pass — required after ANY change to `src/template_press/rebrand/`.
- Decision provenance: codesign export 2026-07-23 (sec-01 ch-01-a, sec-02 ch-02-c "rules primary", sec-03 ch-03-a + per-rule paths control, sec-04 ch-04-c configurable, sec-05 ch-05-a, sec-06 ch-06-a, sec-07 ch-07-a/b/d). Research: `docs/research/0005-scaffolder-identity-variant-handling.md`.

---

### Task 1: `display_name` — optional 7th identity field + form derivation

**Files:**
- Modify: `src/template_press/rebrand/identity.py` (VALIDATORS block ~line 80; `Identity` dataclass lines 99-141)
- Test: `tests/rebrand/test_identity.py`

**Interfaces:**
- Consumes: existing `ValidationError`, `REQUIRED_FIELDS`.
- Produces (later tasks rely on these exact names):
  - `OPTIONAL_FIELDS: tuple[str, ...] = ("display_name",)`
  - `DISPLAY_FORM_NAMES: tuple[str, ...] = ("spaced", "pascal", "camel")`
  - `validate_display_name(value: str) -> str`
  - `Identity.display_name: str | None = None` (frozen dataclass field, default None)
  - `Identity.as_dict()` / `as_dict_prompted()` include the `"display_name"` key ONLY when the field is set (sparse — None never enters a token path)
  - `Identity.from_mapping(data)` picks up an optional `"display_name"` key
  - `display_forms(value: str) -> dict[str, str]` returning all three forms keyed by `DISPLAY_FORM_NAMES`

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_identity.py`:

```python
import pytest

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    validate_display_name,
)


def _identity(**overrides):
    base = dict(
        package_name="py_launch_blueprint",
        repo_name="py-launch-blueprint",
        app_name="plbp",
        author="Steve Morin",
        email="steve.morin@gmail.com",
        owner="smorinlabs",
    )
    base.update(overrides)
    return Identity(**base)


class TestDisplayName:
    def test_validator_accepts_spaced_title(self):
        assert validate_display_name("Py Launch Blueprint") == "Py Launch Blueprint"

    def test_validator_rejects_empty_and_control_chars(self):
        with pytest.raises(ValidationError):
            validate_display_name("   ")
        with pytest.raises(ValidationError):
            validate_display_name("Py\x00Launch")

    def test_field_defaults_to_none_and_is_absent_from_dicts(self):
        ident = _identity()
        assert ident.display_name is None
        assert "display_name" not in ident.as_dict()
        assert "display_name" not in ident.as_dict_prompted()

    def test_field_present_appears_in_dicts_and_validates(self):
        ident = _identity(display_name="Py Launch Blueprint")
        assert ident.as_dict()["display_name"] == "Py Launch Blueprint"
        assert ident.as_dict_prompted()["display_name"] == "Py Launch Blueprint"
        ident.validate()  # must not raise

    def test_validate_rejects_bad_display_name(self):
        with pytest.raises(ValidationError):
            _identity(display_name="\x01").validate()

    def test_from_mapping_optional_display_name(self):
        data = _identity().as_dict_prompted()
        assert Identity.from_mapping(data).display_name is None
        data["display_name"] = "Py Launch Blueprint"
        assert Identity.from_mapping(data).display_name == "Py Launch Blueprint"


class TestDisplayForms:
    def test_three_forms_from_title_case(self):
        forms = display_forms("Py Launch Blueprint")
        assert forms == {
            "spaced": "Py Launch Blueprint",
            "pascal": "PyLaunchBlueprint",
            "camel": "pyLaunchBlueprint",
        }
        assert tuple(forms) == DISPLAY_FORM_NAMES

    def test_forms_capitalize_lowercase_words(self):
        forms = display_forms("acme widget")
        assert forms["pascal"] == "AcmeWidget"
        assert forms["camel"] == "acmeWidget"

    def test_single_word_keeps_inner_casing(self):
        forms = display_forms("NumPy")
        assert forms == {"spaced": "NumPy", "pascal": "NumPy", "camel": "numPy"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/stevemorin/c/template-press-cde && uv run pytest tests/rebrand/test_identity.py -v -k "DisplayName or DisplayForms"`
Expected: FAIL — `ImportError: cannot import name 'display_forms'`

- [ ] **Step 3: Implement in `identity.py`**

Add after `validate_app_name` (before the `VALIDATORS` dict):

```python
def validate_display_name(value: str) -> str:
    # The humanized product name ("Py Launch Blueprint"). Same posture as
    # author: worldwide charset, but empty/control values are catastrophic
    # (empty compiles to a match-anywhere pattern; control chars break TOML).
    if not value.strip():
        raise ValidationError("display name must not be empty")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
        raise ValidationError(
            f"display name must not contain control characters: {value!r}"
        )
    return value
```

Add `"display_name": validate_display_name,` to the `VALIDATORS` dict.

After `REQUIRED_FIELDS`, add:

```python
# Optional identity fields: absent means the feature is off — existing
# 6-field press-source.toml files stay valid (codesign sec-01/sec-06).
OPTIONAL_FIELDS: tuple[str, ...] = ("display_name",)

# The closed set of exact display-name rewrite forms (codesign sec-04).
DISPLAY_FORM_NAMES: tuple[str, ...] = ("spaced", "pascal", "camel")
```

In the `Identity` dataclass: add field `display_name: str | None = None` after `owner`. In `as_dict()`, after building the dict, add:

```python
        if self.display_name is not None:
            d["display_name"] = self.display_name
```

(rename the returned literal to a local `d` first). `as_dict_prompted()` already derives from `as_dict()` — no change needed. In `from_mapping()`, replace the return with:

```python
        fields = {k: data[k] for k in REQUIRED_FIELDS}
        for opt in OPTIONAL_FIELDS:
            if data.get(opt) is not None:
                fields[opt] = data[opt]
        return cls(**fields)
```

Add module-level function after `replace_token`:

```python
def display_forms(value: str) -> dict[str, str]:
    """The closed set of exact display-name forms, keyed by DISPLAY_FORM_NAMES.

    spaced is the value verbatim; pascal capitalizes each space-separated
    word's first letter and joins (inner casing preserved: "NumPy" stays
    "NumPy"); camel is pascal with its first character lowercased. A closed,
    enumerable set — never an elastic pattern (codesign sec-04).
    """
    words = value.split()
    pascal = "".join(w[:1].upper() + w[1:] for w in words)
    camel = pascal[:1].lower() + pascal[1:]
    return {"spaced": value, "pascal": pascal, "camel": camel}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_identity.py -v`
Expected: ALL PASS (new tests plus every pre-existing identity test — the sparse-dict change must not break them).

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/identity.py tests/rebrand/test_identity.py
git commit -m "feat(identity): optional display_name field with closed form set"
```

---

### Task 2: config round-trip for `display_name`

**Files:**
- Modify: `src/template_press/rebrand/config.py` only if Step 2 shows a failure (expected: no change — `load_identity_toml` → `from_mapping` and `render_source_config` → `as_dict_prompted` already carry the optional field after Task 1)
- Test: `tests/rebrand/test_config.py`

**Interfaces:**
- Consumes: Task 1's `Identity.display_name`, sparse `as_dict_prompted()`.
- Produces: guarantee that a `press-source.toml`/answers `[identity]`/`[answers]` table with `display_name = "..."` loads it, and `render_source_config` emits a `display_name = "..."` line when set (and no line when unset).

- [ ] **Step 1: Write the failing/proving tests**

Append to `tests/rebrand/test_config.py`:

```python
from template_press.rebrand.config import load_identity_toml, render_source_config
from template_press.rebrand.identity import Identity


def _base_toml(extra: str = "") -> str:
    return (
        "[identity]\n"
        'package_name = "py_launch_blueprint"\n'
        'repo_name    = "py-launch-blueprint"\n'
        'app_name     = "plbp"\n'
        'author       = "Steve Morin"\n'
        'email        = "steve.morin@gmail.com"\n'
        'owner        = "smorinlabs"\n' + extra
    )


class TestDisplayNameConfig:
    def test_load_without_display_name(self, tmp_path):
        p = tmp_path / "press-source.toml"
        p.write_text(_base_toml(), encoding="utf-8")
        assert load_identity_toml(p, "identity").display_name is None

    def test_load_with_display_name(self, tmp_path):
        p = tmp_path / "press-source.toml"
        p.write_text(
            _base_toml('display_name = "Py Launch Blueprint"\n'), encoding="utf-8"
        )
        ident = load_identity_toml(p, "identity")
        assert ident.display_name == "Py Launch Blueprint"

    def test_render_includes_display_name_only_when_set(self, tmp_path):
        p = tmp_path / "press-source.toml"
        p.write_text(
            _base_toml('display_name = "Py Launch Blueprint"\n'), encoding="utf-8"
        )
        ident = load_identity_toml(p, "identity")
        rendered = render_source_config(ident)
        assert 'display_name = "Py Launch Blueprint"' in rendered
        p.write_text(_base_toml(), encoding="utf-8")
        assert "display_name" not in render_source_config(
            load_identity_toml(p, "identity")
        )

    def test_render_load_round_trip(self, tmp_path):
        p = tmp_path / "press-source.toml"
        p.write_text(
            _base_toml('display_name = "Py Launch Blueprint"\n'), encoding="utf-8"
        )
        ident = load_identity_toml(p, "identity")
        p2 = tmp_path / "round.toml"
        p2.write_text(render_source_config(ident), encoding="utf-8")
        assert load_identity_toml(p2, "identity") == ident
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/rebrand/test_config.py -v -k DisplayNameConfig`
Expected: PASS immediately (the Task 1 plumbing carries it). If any FAIL, fix `config.py` minimally until green — do not restructure.

- [ ] **Step 3: Commit**

```bash
git add tests/rebrand/test_config.py
git commit -m "test(config): display_name round-trips through source-config and answers"
```

---

### Task 3: engine display pairs + doctor coverage

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (`replacement_pairs` lines 314-319; `apply` line 476; `build_plan` line 349)
- Modify: `src/template_press/rebrand/doctor.py` (`find_leaks` lines 53-70)
- Modify: `src/template_press/rebrand/cli.py` (doctor call line 325)
- Test: `tests/rebrand/test_engine_replace.py`, `tests/rebrand/test_doctor.py`

**Interfaces:**
- Consumes: `display_forms`, `DISPLAY_FORM_NAMES` from Task 1.
- Produces:
  - `replacement_pairs(source: Identity, dest: Identity, display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES) -> list[tuple[str, str, str]]` — emits pairs tagged `display_name_spaced` / `display_name_pascal` / `display_name_camel` (never a raw `display_name` pair), only when BOTH identities declare a display name and the form values differ. These tags hit `token_pattern`'s generic branch. They are NOT in `RENAME_FIELDS`, so display forms never rename paths.
  - `find_leaks(..., display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES)` — scans per-form display values in content/symlink passes.
  - `build_plan(target, source, dest, rules)` and `apply(...)` pass `rules.display_forms` once Task 5 adds that knob; until then they call with the default (leave call sites unchanged in this task).

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_engine_replace.py` (reuse that file's existing identity-builder helper if one exists; otherwise define `_identity` exactly as in Task 1's test):

```python
from template_press.rebrand.engine import replacement_pairs


class TestDisplayPairs:
    def test_no_display_no_display_pairs(self):
        pairs = replacement_pairs(_identity(), _identity(app_name="acme"))
        assert not any(f.startswith("display_name") for f, _, _ in pairs)

    def test_three_form_pairs_when_both_sides_declare(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Acme Widget")
        pairs = {f: (c, r) for f, c, r in replacement_pairs(src, dst)}
        assert pairs["display_name_spaced"] == ("Py Launch Blueprint", "Acme Widget")
        assert pairs["display_name_pascal"] == ("PyLaunchBlueprint", "AcmeWidget")
        assert pairs["display_name_camel"] == ("pyLaunchBlueprint", "acmeWidget")
        assert "display_name" not in pairs

    def test_half_specified_emits_no_display_pairs(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme")  # no display_name
        pairs = replacement_pairs(src, dst)
        assert not any(f.startswith("display_name") for f, _, _ in pairs)

    def test_form_subset_is_honored(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(display_name="Acme Widget")
        pairs = replacement_pairs(src, dst, display_form_names=("spaced",))
        fields = [f for f, _, _ in pairs if f.startswith("display_name")]
        assert fields == ["display_name_spaced"]
```

Append to `tests/rebrand/test_doctor.py` (mirroring that file's existing tmp-target fixture style — it builds a target dir with files and calls `find_leaks(target, source, rules, dest=...)`; use `DEFAULT_RULES`):

```python
class TestDisplayNameLeaks:
    def test_surviving_pascal_form_is_a_leak(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# PyLaunchBlueprint docs\n", encoding="utf-8"
        )
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(display_name="Acme Widget")
        leaks = find_leaks(tmp_path, src, DEFAULT_RULES, dest=dst)
        assert any(
            lk.field == "display_name_pascal" and lk.where == "content"
            for lk in leaks
        )

    def test_unchanged_display_name_is_not_a_leak(self, tmp_path):
        (tmp_path / "README.md").write_text("Py Launch Blueprint\n", encoding="utf-8")
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme", display_name="Py Launch Blueprint")
        leaks = find_leaks(tmp_path, src, DEFAULT_RULES, dest=dst)
        assert not any(lk.field.startswith("display_name") for lk in leaks)
```

NOTE: `find_leaks` enumerates via `iter_target_files` → `git ls-files`, so the tmp target must be a git repo with the file tracked/untracked-listed. Follow the exact fixture pattern already used in `test_doctor.py` (it initializes a git repo in tmp_path); if it uses a helper like `_git_target(tmp_path)`, reuse it verbatim.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_replace.py -v -k DisplayPairs && uv run pytest tests/rebrand/test_doctor.py -v -k DisplayNameLeaks`
Expected: FAIL — no `display_name_*` pairs / leaks produced.

- [ ] **Step 3: Implement**

`engine.py` — imports: add `DISPLAY_FORM_NAMES, display_forms` to the `identity` import. Replace `replacement_pairs`:

```python
def replacement_pairs(
    source: Identity,
    dest: Identity,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[tuple[str, str, str]]:
    """(field, current, replacement) triples, longest current first.

    display_name is expanded into one pair per enabled exact form
    (display_name_spaced/…_pascal/…_camel) — generic-boundary tags, never in
    RENAME_FIELDS, so display forms rewrite content but never paths. The
    `k in dst` guard keeps a half-specified display name (source has it,
    dest doesn't) out of the pair list entirely — the CLI gates that case.
    """
    src, dst = source.as_dict(), dest.as_dict()
    pairs = [
        (k, src[k], dst[k])
        for k in src
        if k != "display_name" and k in dst and src[k] != dst[k]
    ]
    if "display_name" in src and "display_name" in dst:
        sf = display_forms(src["display_name"])
        df = display_forms(dst["display_name"])
        for form in display_form_names:
            if sf[form] != df[form]:
                pairs.append((f"display_name_{form}", sf[form], df[form]))
    pairs.sort(key=lambda t: -len(t[1]))
    return pairs
```

`doctor.py` — imports: add `DISPLAY_FORM_NAMES, display_forms` to the `identity` import. In `find_leaks`, change the signature to:

```python
def find_leaks(
    target: Path,
    source: Identity,
    rules: Rules,
    dest: Identity | None = None,
    display_form_names: tuple[str, ...] = DISPLAY_FORM_NAMES,
) -> list[Leak]:
```

and replace the fields-building block (lines 67-70) with:

```python
    fields = source.as_dict()
    if "display_name" in fields:
        # Expand into the exact per-form values so a surviving glued form
        # (PyLaunchBlueprint) is a leak, not just the spaced original.
        sf = display_forms(fields.pop("display_name"))
        for form in display_form_names:
            fields[f"display_name_{form}"] = sf[form]
    if dest is not None:
        dest_fields = dest.as_dict()
        if "display_name" in dest_fields:
            df = display_forms(dest_fields.pop("display_name"))
            for form in display_form_names:
                dest_fields[f"display_name_{form}"] = df[form]
        fields = {k: v for k, v in fields.items() if dest_fields.get(k) != v}
```

`cli.py` line 325: no signature change needed yet (defaults carry it); leave as is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_engine_replace.py tests/rebrand/test_doctor.py tests/rebrand/test_engine_plan.py tests/rebrand/test_engine_rename.py -v`
Expected: ALL PASS (existing pair/plan/rename tests must survive the signature default).

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/engine.py src/template_press/rebrand/doctor.py tests/rebrand/test_engine_replace.py tests/rebrand/test_doctor.py
git commit -m "feat(engine): display-name form pairs in rewrite and doctor scans"
```

---

### Task 4: CLI half-specified gate (exit 2)

**Files:**
- Modify: `src/template_press/rebrand/cli.py` (add pure helper near `_collisions` line 133; wire into `main` right after `dest = load_answers(args.config)` line 187)
- Test: `tests/rebrand/test_cli.py`

**Interfaces:**
- Consumes: `Identity.display_name`.
- Produces: `display_name_problem(source: Identity, dest: Identity) -> str | None` — pure; non-None message when source declares `display_name` and dest doesn't (codesign sec-06 ch-06-a). The reverse direction returns None (new name simply gets recorded by the post-apply source-config write, `cli.py:333`).

- [ ] **Step 1: Write the failing test**

Append to `tests/rebrand/test_cli.py` (reuse/define `_identity` as in Task 1):

```python
from template_press.rebrand.cli import display_name_problem


class TestDisplayNameGate:
    def test_half_specified_is_a_problem(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(app_name="acme")
        msg = display_name_problem(src, dst)
        assert msg is not None and "display_name" in msg

    def test_reverse_direction_is_fine(self):
        src = _identity()
        dst = _identity(app_name="acme", display_name="Acme Widget")
        assert display_name_problem(src, dst) is None

    def test_both_or_neither_is_fine(self):
        assert display_name_problem(_identity(), _identity(app_name="acme")) is None
        assert (
            display_name_problem(
                _identity(display_name="Py Launch Blueprint"),
                _identity(display_name="Acme Widget"),
            )
            is None
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rebrand/test_cli.py -v -k DisplayNameGate`
Expected: FAIL — `ImportError: cannot import name 'display_name_problem'`

- [ ] **Step 3: Implement**

In `cli.py`, add after `_collisions`:

```python
def display_name_problem(source: Identity, dest: Identity) -> str | None:
    """Half-specified display identity is refused (codesign sec-06).

    The press knows what to erase but not what to write — proceeding would
    ship a half-rebrand where every prose mention keeps the old product
    name. The reverse direction is harmless: nothing to rewrite, and the
    post-apply source-config write records the new display name.
    """
    if source.display_name is not None and dest.display_name is None:
        return (
            f"source-config declares display_name "
            f"({source.display_name!r}) but the answers file does not — "
            f"add display_name to [answers]; press cannot know the new "
            f"display name"
        )
    return None
```

In `main()`, immediately after `dest = load_answers(args.config)`:

```python
        display_problem = display_name_problem(source, dest)
        if display_problem is not None:
            return _fail(display_problem)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_cli.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/cli.py tests/rebrand/test_cli.py
git commit -m "feat(cli): fail loud on half-specified display_name"
```

---

### Task 5: rules schema — `[[replace]]`, `substring_rewrite_fields`, `display_forms`

**Files:**
- Modify: `src/template_press/rebrand/rules.py` (dataclass lines 19-30; `load_rules` lines 72-90)
- Test: `tests/rebrand/test_rules.py`

**Interfaces:**
- Consumes: `REQUIRED_FIELDS`, `DISPLAY_FORM_NAMES`, `ValidationError` from `identity`.
- Produces (exact shapes later tasks build on):

```python
@dataclass(frozen=True)
class ReplaceRule:
    pattern: str                 # template with {field} placeholders
    reason: str                  # REQUIRED documentation (codesign ch-07-d)
    files: tuple[str, ...] = ()  # fnmatch globs vs POSIX rel path; () = all
    paths: bool = False          # participate in path renames (ch-07-b)
    content: bool = True         # participate in content rewrites
```

- `Rules` gains: `replace: tuple[ReplaceRule, ...] = ()`, `substring_rewrite_fields: frozenset[str] = frozenset()`, `display_forms: tuple[str, ...] = DISPLAY_FORM_NAMES`.
- `ALLOWED_PLACEHOLDERS: frozenset[str]` = `frozenset(REQUIRED_FIELDS) | {"app_name_upper", "display_name"}`.
- TOML surface in `press/press-rules.toml`: top-level `[[replace]]` array-of-tables; `[rules] substring_rewrite_fields = [...]` (subset of ALLOWED_PLACEHOLDERS); `[rules] display_forms = [...]` (non-empty subset of `DISPLAY_FORM_NAMES`).
- Fail-closed validation: unknown `[[replace]]` keys; empty/missing `pattern` or `reason`; a pattern with NO placeholder (from==to would be a committed no-op); an unknown placeholder name; `paths`/`content` both false; wrong types anywhere.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_rules.py`:

```python
import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import DEFAULT_RULES, load_rules


def _write_rules(tmp_path, body: str):
    d = tmp_path / "press"
    d.mkdir(exist_ok=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path


class TestReplaceRules:
    def test_defaults_empty(self):
        assert DEFAULT_RULES.replace == ()
        assert DEFAULT_RULES.substring_rewrite_fields == frozenset()
        assert DEFAULT_RULES.display_forms == ("spaced", "pascal", "camel")

    def test_parse_full_rule(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "_{app_name}_owned"\n'
            'files = ["tests/**"]\npaths = false\ncontent = true\n'
            'reason = "logging ownership guard"\n',
        )
        rules = load_rules(target)
        (rule,) = rules.replace
        assert rule.pattern == "_{app_name}_owned"
        assert rule.files == ("tests/**",)
        assert rule.paths is False and rule.content is True
        assert rule.reason == "logging ownership guard"

    def test_reason_is_required(self, tmp_path):
        target = _write_rules(tmp_path, '[[replace]]\npattern = "{app_name}-web"\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_pattern_must_reference_a_field(self, tmp_path):
        target = _write_rules(
            tmp_path, '[[replace]]\npattern = "plbp-web"\nreason = "r"\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_placeholder_rejected(self, tmp_path):
        target = _write_rules(
            tmp_path, '[[replace]]\npattern = "{appname}-web"\nreason = "r"\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_paths_and_content_not_both_false(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "{app_name}-web"\nreason = "r"\n'
            "paths = false\ncontent = false\n",
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_key_rejected(self, tmp_path):
        target = _write_rules(
            tmp_path,
            '[[replace]]\npattern = "{app_name}-web"\nreason = "r"\nglob = "x"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestRewriteKnobs:
    def test_substring_fields_parse_and_validate(self, tmp_path):
        target = _write_rules(
            tmp_path, '[rules]\nsubstring_rewrite_fields = ["app_name"]\n'
        )
        assert load_rules(target).substring_rewrite_fields == frozenset({"app_name"})
        target = _write_rules(
            tmp_path, '[rules]\nsubstring_rewrite_fields = ["nope"]\n'
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_display_forms_subset(self, tmp_path):
        target = _write_rules(tmp_path, '[rules]\ndisplay_forms = ["spaced"]\n')
        assert load_rules(target).display_forms == ("spaced",)
        target = _write_rules(tmp_path, '[rules]\ndisplay_forms = []\n')
        with pytest.raises(ValidationError):
            load_rules(target)
        target = _write_rules(tmp_path, '[rules]\ndisplay_forms = ["kebab"]\n')
        with pytest.raises(ValidationError):
            load_rules(target)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_rules.py -v -k "ReplaceRules or RewriteKnobs"`
Expected: FAIL — `Rules` has no `replace` attribute / unknown knobs ignored.

- [ ] **Step 3: Implement in `rules.py`**

Add imports: `import re` and extend the identity import to `from template_press.rebrand.identity import REQUIRED_FIELDS, DISPLAY_FORM_NAMES, ValidationError` (note: `DISPLAY_FORM_NAMES` lives in identity per Task 1).

Add before `Rules`:

```python
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# Every {field} a [[replace]] pattern may reference: the six required
# identity fields, the derived uppercase app form, and the optional
# display name (rendering fails loud at press time if the identity in
# play doesn't declare it).
ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset(REQUIRED_FIELDS) | {
    "app_name_upper",
    "display_name",
}

_REPLACE_KEYS = frozenset({"pattern", "files", "paths", "content", "reason"})


@dataclass(frozen=True)
class ReplaceRule:
    """One exact-match rewrite rule: a template rendered twice.

    The SOURCE identity renders `pattern` into the literal to find; the
    DESTINATION identity renders it into the literal to write. Exact string
    replacement of the rendered forms — no fuzzy matching, no boundary
    heuristics (codesign sec-02: rules are the primary glued-token
    mechanism). Interpolation is what keeps a committed rule correct across
    repeated presses: press rewrites press-source.toml to the new identity
    after apply, so the same rule re-renders for every future fork.
    """

    pattern: str
    reason: str
    files: tuple[str, ...] = ()
    paths: bool = False
    content: bool = True
```

Add fields to `Rules` (after `verify_ignore`):

```python
    replace: tuple[ReplaceRule, ...] = ()
    # Fields rewritten by plain substring replacement instead of the
    # boundary-guarded token pattern (codesign sec-02 secondary). Opt-in,
    # per field, for provably word-disjoint tokens ONLY — a word-embedded
    # value here WILL corrupt prose; that risk is the author's to accept.
    substring_rewrite_fields: frozenset[str] = frozenset()
    display_forms: tuple[str, ...] = DISPLAY_FORM_NAMES
```

Add parser after `_str_list`:

```python
def _parse_replace(entry: object) -> ReplaceRule:
    if not isinstance(entry, dict):
        raise ValidationError(f"{RULES_REL}: [[replace]] entry must be a table")
    unknown = set(entry) - _REPLACE_KEYS
    if unknown:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] unknown key(s): {', '.join(sorted(unknown))}"
        )
    pattern = entry.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValidationError(f"{RULES_REL}: [[replace]] pattern must be a non-empty string")
    names = _PLACEHOLDER_RE.findall(pattern)
    if not names:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] pattern {pattern!r} references no identity "
            f"field — a placeholder-free rule renders FROM == TO (a committed "
            f"no-op); use e.g. {{app_name}}"
        )
    bad = set(names) - ALLOWED_PLACEHOLDERS
    if bad:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] pattern {pattern!r} references unknown "
            f"field(s): {', '.join(sorted(bad))}"
        )
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError(
            f"{RULES_REL}: [[replace]] {pattern!r}: reason is required"
        )
    files = entry.get("files", [])
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise ValidationError(
            f"{RULES_REL}: [[replace]] files must be a list of glob strings"
        )
    paths = entry.get("paths", False)
    content = entry.get("content", True)
    for key, value in (("paths", paths), ("content", content)):
        if not isinstance(value, bool):
            raise ValidationError(f"{RULES_REL}: [[replace]] {key} must be a boolean")
    if not paths and not content:
        raise ValidationError(
            f"{RULES_REL}: [[replace]] {pattern!r}: paths and content are both "
            f"false — the rule would do nothing"
        )
    return ReplaceRule(
        pattern=pattern,
        reason=reason,
        files=tuple(files),
        paths=paths,
        content=content,
    )
```

In `load_rules`, validate/collect the new surfaces. After `table = data.get("rules", {})` checks, add:

```python
    raw_replace = data.get("replace", [])
    if not isinstance(raw_replace, list):
        raise ValidationError(f"{RULES_REL}: [[replace]] must be an array of tables")
    substring_fields = frozenset(_str_list(table, "substring_rewrite_fields", []))
    bad_substring = substring_fields - ALLOWED_PLACEHOLDERS
    if bad_substring:
        raise ValidationError(
            f"{RULES_REL}: [rules] substring_rewrite_fields unknown field(s): "
            f"{', '.join(sorted(bad_substring))}"
        )
    display_forms_list = _str_list(
        table, "display_forms", list(DISPLAY_FORM_NAMES)
    )
    bad_forms = set(display_forms_list) - set(DISPLAY_FORM_NAMES)
    if bad_forms or not display_forms_list:
        raise ValidationError(
            f"{RULES_REL}: [rules] display_forms must be a non-empty subset of "
            f"{list(DISPLAY_FORM_NAMES)}: {display_forms_list!r}"
        )
```

and extend the returned `Rules(...)` with:

```python
        replace=tuple(_parse_replace(e) for e in raw_replace),
        substring_rewrite_fields=substring_fields,
        display_forms=tuple(dict.fromkeys(display_forms_list)),
```

(`_str_list` gains a third positional `default` argument use — it already has one.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_rules.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/rules.py tests/rebrand/test_rules.py
git commit -m "feat(rules): [[replace]] rules, substring and display-form knobs"
```

---

### Task 6: rule rendering + file scoping helpers

**Files:**
- Modify: `src/template_press/rebrand/rules.py`
- Test: `tests/rebrand/test_rules.py`

**Interfaces:**
- Consumes: `ReplaceRule`, `_PLACEHOLDER_RE`, `Identity` (new import in rules.py — safe, identity does not import rules).
- Produces:
  - `render_replace_pattern(pattern: str, identity: Identity) -> str` — substitutes each `{field}` with `identity.as_dict()[field]`; raises `ValidationError` naming the pattern and field when the identity doesn't declare it (the optional-display case).
  - `rule_matches_path(rule: ReplaceRule, posix: str) -> bool` — `True` when `files` is empty or any `fnmatch.fnmatch(posix, glob)` hits.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_rules.py` (reuse `_identity` from Task 1's pattern — import `Identity` and build inline if the file has no helper):

```python
from template_press.rebrand.rules import (
    ReplaceRule,
    render_replace_pattern,
    rule_matches_path,
)


class TestRuleRendering:
    def test_renders_both_sides(self):
        src = _identity()
        dst = _identity(app_name="acme")
        assert render_replace_pattern("_{app_name}_owned", src) == "_plbp_owned"
        assert render_replace_pattern("_{app_name}_owned", dst) == "_acme_owned"

    def test_app_name_upper_placeholder(self):
        assert render_replace_pattern("{app_name_upper}_HOME", _identity()) == "PLBP_HOME"

    def test_missing_display_name_fails_loud(self):
        with pytest.raises(ValidationError):
            render_replace_pattern("{display_name}!", _identity())

    def test_display_name_renders_when_declared(self):
        ident = _identity(display_name="Py Launch Blueprint")
        assert render_replace_pattern("{display_name}!", ident) == "Py Launch Blueprint!"


class TestRuleScoping:
    def test_empty_files_matches_everything(self):
        rule = ReplaceRule(pattern="{app_name}", reason="r")
        assert rule_matches_path(rule, "any/where.py")

    def test_glob_scopes(self):
        rule = ReplaceRule(pattern="{app_name}", reason="r", files=("tests/**",))
        assert rule_matches_path(rule, "tests/core/test_logging.py")
        assert not rule_matches_path(rule, "src/pkg/mod.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_rules.py -v -k "RuleRendering or RuleScoping"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement in `rules.py`**

Add `import fnmatch` and `from template_press.rebrand.identity import Identity` (merge into the existing identity import). Add:

```python
def render_replace_pattern(pattern: str, identity: Identity) -> str:
    """Substitute {field} placeholders with this identity's values.

    Called twice per rule per press: once with the SOURCE identity (the
    literal to find) and once with the DESTINATION (the literal to write).
    """
    values = identity.as_dict()

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in values:
            raise ValidationError(
                f"[[replace]] pattern {pattern!r} references {{{name}}} but "
                f"this identity does not declare it (display_name is optional "
                f"— add it to the identity or drop the rule)"
            )
        return values[name]

    return _PLACEHOLDER_RE.sub(_sub, pattern)


def rule_matches_path(rule: ReplaceRule, posix: str) -> bool:
    """POSIX rel-path scope check: empty files = every file; else fnmatch."""
    if not rule.files:
        return True
    return any(fnmatch.fnmatch(posix, glob) for glob in rule.files)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_rules.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/rules.py tests/rebrand/test_rules.py
git commit -m "feat(rules): render replace patterns per identity and scope by glob"
```

---

### Task 7: engine — `[[replace]]` content pass + plan items

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (`_apply_replacements` lines 400-425; `apply` lines 476-485; `build_plan` lines 349-381)
- Test: `tests/rebrand/test_engine_replace.py`, `tests/rebrand/test_engine_plan.py`

**Interfaces:**
- Consumes: `ReplaceRule`, `render_replace_pattern`, `rule_matches_path` (Task 6); `rules.replace`, `rules.display_forms` (Task 5).
- Produces:
  - `rendered_replace_rules(rules: Rules, source: Identity, dest: Identity) -> list[tuple[ReplaceRule, str, str]]` — (rule, FROM, TO), skipping rules whose two renderings are identical (referenced fields unchanged).
  - `_apply_replacements(target, pairs, rules, report, rendered)` — replace rules run FIRST (a rule's FROM may embed identity tokens the token pass would otherwise rewrite from under it), then the token pairs.
  - `apply(...)` and `build_plan(...)` now render rules once and pass `rules.display_forms` into `replacement_pairs`. `build_plan` emits `PlanItem("replace", path, f"rule {FROM!r} -> {TO!r}")` per rule hit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_engine_replace.py`. Mirror the file's existing apply-fixture idiom (it builds a git-tracked tmp target and calls `apply(target, src, dst, rules)`); the essential new assertions:

```python
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
import dataclasses


def _rules_with(**overrides):
    return dataclasses.replace(DEFAULT_RULES, **overrides)


class TestReplaceRuleContent:
    def test_glued_token_rewritten_by_rule(self, git_target):
        # git_target: existing fixture creating a tracked tmp repo — reuse
        # the file's actual fixture name.
        (git_target / "conftest.py").write_text(
            'getattr(h, "_plbp_owned", False)\n', encoding="utf-8"
        )
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(pattern="_{app_name}_owned", reason="ownership guard"),
            )
        )
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        text = (git_target / "conftest.py").read_text(encoding="utf-8")
        assert "_acme_owned" in text and "_plbp_owned" not in text

    def test_rules_run_before_token_pass(self, git_target):
        # FROM embeds package_name; if the token pass ran first the rule's
        # rendered FROM would no longer match.
        (git_target / "note.md").write_text(
            "see py_launch_blueprint-extra\n", encoding="utf-8"
        )
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(pattern="{package_name}-extra", reason="compound ref"),
            )
        )
        apply(
            git_target,
            _identity(),
            _identity(package_name="acme_widget"),
            rules,
        )
        assert "acme_widget-extra" in (git_target / "note.md").read_text(
            encoding="utf-8"
        )

    def test_files_glob_scopes_rule(self, git_target):
        (git_target / "in_scope.txt").write_text("plbp-web\n", encoding="utf-8")
        sub = git_target / "docs"
        sub.mkdir()
        (sub / "out_of_scope.txt").write_text("plbp-web\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web", reason="image name", files=("*.txt",)
                ),
            )
        )
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert "acme-web" in (git_target / "in_scope.txt").read_text(encoding="utf-8")
        assert "plbp-web" in (sub / "out_of_scope.txt").read_text(encoding="utf-8")

    def test_content_false_rule_leaves_content(self, git_target):
        (git_target / "a.txt").write_text("plbp-web\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}-web",
                    reason="paths only",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert "plbp-web" in (git_target / "a.txt").read_text(encoding="utf-8")
```

Append to `tests/rebrand/test_engine_plan.py`:

```python
class TestReplaceRulePlan:
    def test_plan_lists_rule_hits(self, git_target):
        (git_target / "conftest.py").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(ReplaceRule(pattern="_{app_name}_owned", reason="guard"),)
        )
        plan = build_plan(git_target, _identity(), _identity(app_name="acme"), rules)
        assert any(
            i.kind == "replace" and "_plbp_owned" in i.detail for i in plan.items
        )
```

NOTE to implementer: `git_target`, `_git_add_all`, `_identity`, `_rules_with` — reuse the exact fixture/helper names already present in these two test files; if a helper doesn't exist, define it at the top of the test file using `subprocess.run(["git", "init"], ...)` + `git add -A` the way `tests/rebrand/conftest.py` does elsewhere. Do not invent a new fixture style.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_replace.py tests/rebrand/test_engine_plan.py -v -k ReplaceRule`
Expected: FAIL — rules ignored (old text survives) / no plan items.

- [ ] **Step 3: Implement in `engine.py`**

Imports: add `ReplaceRule, render_replace_pattern, rule_matches_path` to the rules import.

Add after `replacement_pairs`:

```python
def rendered_replace_rules(
    rules: Rules, source: Identity, dest: Identity
) -> list[tuple[ReplaceRule, str, str]]:
    """(rule, FROM, TO) with both sides rendered; identical sides dropped.

    Rendering raises ValidationError when a pattern references a field this
    identity pair doesn't declare (optional display_name) — surfacing at
    plan time, before any write.
    """
    out: list[tuple[ReplaceRule, str, str]] = []
    for rule in rules.replace:
        frm = render_replace_pattern(rule.pattern, source)
        to = render_replace_pattern(rule.pattern, dest)
        if frm != to:
            out.append((rule, frm, to))
    return out
```

`_apply_replacements` — new signature and rule pass (rules FIRST, then tokens):

```python
def _apply_replacements(
    target: Path,
    pairs: list[tuple[str, str, str]],
    rules: Rules,
    report: ApplyReport,
    rendered: list[tuple[ReplaceRule, str, str]],
) -> None:
    for path in iter_target_files(target, rules):
        rel = path.relative_to(target).as_posix()
        text = _read_text(path)
        if text is None:
            kind = "symlink" if path.is_symlink() else "binary"
            report.skipped.append(f"replace {rel} ({kind})")
            continue
        new_text = text
        # [[replace]] rules run BEFORE the token pass: a rule's rendered
        # FROM may embed an identity token (e.g. "{package_name}-extra");
        # the token pass would rewrite that token out from under the rule.
        for rule, frm, to in rendered:
            if rule.content and rule_matches_path(rule, rel):
                new_text = new_text.replace(frm, to)
        for f, cur, repl in pairs:
            new_text = replace_token(new_text, f, cur, repl)
        if new_text != text:
            safe_write(target, rel, new_text, refuse_hardlink=False)
            report.replaced.append(rel)
```

(keep the existing safe_write comment block in place above the call).

`apply()` becomes:

```python
def apply(target: Path, source: Identity, dest: Identity, rules: Rules) -> ApplyReport:
    """Execute the rebrand: replace pass, symlink-retarget pass, rename pass."""
    source.validate()
    dest.validate()
    report = ApplyReport()
    pairs = replacement_pairs(source, dest, rules.display_forms)
    rendered = rendered_replace_rules(rules, source, dest)
    _apply_replacements(target, pairs, rules, report, rendered)
    _retarget_symlinks(target, pairs, report)
    _apply_renames(target, pairs, rules, report)
    return report
```

`build_plan()`: change the pairs line to `pairs = replacement_pairs(source, dest, rules.display_forms)`, add `rendered = rendered_replace_rules(rules, source, dest)` after it, and inside the file loop's `if text is not None:` block, before the token-field check, add:

```python
            for rule, frm, to in rendered:
                if rule.content and rule_matches_path(rule, rel.as_posix()):
                    if frm in text:
                        plan.items.append(
                            PlanItem("replace", rel.as_posix(), f"rule {frm!r} -> {to!r}")
                        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_engine_replace.py tests/rebrand/test_engine_plan.py tests/rebrand/test_engine_rename.py tests/rebrand/test_cli.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_replace.py tests/rebrand/test_engine_plan.py
git commit -m "feat(engine): exact replace rules run before the token pass"
```

---

### Task 8: engine — rules & tokens in path renames + empty-segment guard

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (`_renamed_rel` lines 331-346; its two callers in `build_plan` and `_rename_pass_once`)
- Test: `tests/rebrand/test_engine_rename.py`

**Interfaces:**
- Consumes: Task 7's `rendered_replace_rules`; Task 5's `rules.substring_rewrite_fields`.
- Produces:
  - `_renamed_rel(rel: Path, pairs, rendered: list[tuple[ReplaceRule, str, str]] = [], substring_fields: Collection[str] = frozenset()) -> Path` — per component: (1) `paths=True` rules whose `files` glob matches the FULL rel posix apply exact `str.replace`; (2) `RENAME_FIELDS` token pairs apply — `str.replace` for substring-mode fields, `replace_token` otherwise; (3) a component that renders EMPTY raises `ValidationError` (cookiecutter #1518 path-collapse guard) — this fires during `build_plan` (pre-write), so the CLI exits 2 before any mutation.
  - Both callers pass `rendered` + `rules.substring_rewrite_fields`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_engine_rename.py` (reuse that file's fixture idiom; `_rules_with` from Task 7):

```python
class TestRulePathRenames:
    def test_paths_rule_renames_doc_filename(self, git_target):
        docs = git_target / "docs"
        docs.mkdir()
        (docs / "0001-plbp-cli-conventions.md").write_text("x\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="-{app_name}-",
                    reason="doc filename token",
                    paths=True,
                    content=False,
                ),
            )
        )
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-acme-cli-conventions.md").exists()
        assert not (docs / "0001-plbp-cli-conventions.md").exists()

    def test_paths_false_rule_never_renames(self, git_target):
        (git_target / "plbp-web.txt").write_text("x\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(ReplaceRule(pattern="{app_name}-web", reason="content only"),)
        )
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert (git_target / "plbp-web.txt").exists()

    def test_empty_component_fails_loud_at_plan_time(self, git_target):
        (git_target / "plbp").mkdir()
        (git_target / "plbp" / "keep.txt").write_text("x\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(
            replace=(
                ReplaceRule(
                    pattern="{app_name}", reason="degenerate", paths=True,
                    content=False,
                ),
            )
        )
        # A paths rule whose TO renders empty would collapse "plbp/" into its
        # parent — build a dest whose app_name yields an empty TO is not
        # constructible (validators forbid empty), so simulate the guard via
        # a rule that strips the whole component: FROM == component text.
        # Direct unit check on _renamed_rel:
        from template_press.rebrand.engine import _renamed_rel

        with pytest.raises(ValidationError):
            _renamed_rel(
                Path("plbp/keep.txt"),
                [],
                rendered=[(rules.replace[0], "plbp", "")],
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_rename.py -v -k RulePathRenames`
Expected: FAIL — files not renamed / no guard.

- [ ] **Step 3: Implement in `engine.py`**

Add `from collections.abc import Collection` to imports and `ValidationError` to the identity import. Replace `_renamed_rel`:

```python
def _renamed_rel(
    rel: Path,
    pairs: list[tuple[str, str, str]],
    rendered: list[tuple[ReplaceRule, str, str]] | None = None,
    substring_fields: Collection[str] = frozenset(),
) -> Path:
    rendered = rendered or []
    posix = rel.as_posix()
    parts = []
    for i, component in enumerate(rel.parts):
        if _is_root_press(rel, i):
            parts.append(component)
            continue
        new = component
        for rule, frm, to in rendered:
            if rule.paths and rule_matches_path(rule, posix):
                new = new.replace(frm, to)
        for f, cur, repl in pairs:
            if f in RENAME_FIELDS:
                if f in substring_fields:
                    new = new.replace(cur, repl)
                else:
                    new = replace_token(new, f, cur, repl)
        if component and not new:
            # A substitution that empties a path segment would collapse the
            # path into its parent (cookiecutter #1518's corruption class).
            raise ValidationError(
                f"rename would empty a path component of {posix!r} — refusing"
            )
        parts.append(new)
    return Path(*parts)
```

Update the two call sites — in `build_plan`: `new_rel = _renamed_rel(rel, pairs, rendered, rules.substring_rewrite_fields)`; in `_rename_pass_once`, thread `rendered` and the substring set through: change its signature to accept `rendered: list[tuple[ReplaceRule, str, str]]`, call `_renamed_rel(rel, pairs, rendered, rules.substring_rewrite_fields)`, and update `_apply_renames` to accept and forward `rendered` (its caller `apply()` passes the `rendered` list it already built in Task 7).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_engine_rename.py tests/rebrand/test_engine_plan.py tests/rebrand/test_engine_replace.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_rename.py
git commit -m "feat(engine): replace rules and substring fields in path renames"
```

---

### Task 9: engine — substring rewrite mode (content + plan)

**Files:**
- Modify: `src/template_press/rebrand/engine.py` (`_apply_replacements` token loop from Task 7; `build_plan` hit detection line ~360)
- Test: `tests/rebrand/test_engine_replace.py`, `tests/rebrand/test_engine_rename.py`

**Interfaces:**
- Consumes: `rules.substring_rewrite_fields` (Task 5); Task 8 already wired renames.
- Produces: in `_apply_replacements`, a field in `substring_rewrite_fields` uses `new_text.replace(cur, repl)`; others keep `replace_token`. In `build_plan`, hit detection for substring fields is `cur in text` instead of `token_occurs`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_engine_replace.py`:

```python
class TestSubstringMode:
    def test_glued_token_rewritten_when_opted_in(self, git_target):
        (git_target / "Justfile").write_text('tag="plbp-web:dev"\n', encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert 'tag="acme-web:dev"' in (git_target / "Justfile").read_text(
            encoding="utf-8"
        )

    def test_substring_mode_replaces_inside_words_by_design(self, git_target):
        # THE documented risk (codesign sec-02): substring mode on a
        # word-embedded token corrupts prose. plbp is word-disjoint so this
        # uses a synthetic embedding to pin the behavior as intentional.
        (git_target / "note.txt").write_text("xplbpy\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert (git_target / "note.txt").read_text(encoding="utf-8") == "xacmey\n"

    def test_default_stays_conservative(self, git_target):
        (git_target / "note.txt").write_text("_plbp_owned\n", encoding="utf-8")
        _git_add_all(git_target)
        apply(git_target, _identity(), _identity(app_name="acme"), DEFAULT_RULES)
        assert "_plbp_owned" in (git_target / "note.txt").read_text(encoding="utf-8")
```

Append to `tests/rebrand/test_engine_rename.py`:

```python
class TestSubstringRenames:
    def test_doc_filename_renamed_with_substring_mode(self, git_target):
        docs = git_target / "docs"
        docs.mkdir()
        (docs / "0001-app-short-name-plbp.md").write_text("x\n", encoding="utf-8")
        _git_add_all(git_target)
        rules = _rules_with(substring_rewrite_fields=frozenset({"app_name"}))
        apply(git_target, _identity(), _identity(app_name="acme"), rules)
        assert (docs / "0001-app-short-name-acme.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_engine_replace.py -v -k SubstringMode && uv run pytest tests/rebrand/test_engine_rename.py -v -k SubstringRenames`
Expected: content tests FAIL (boundary guard blocks); rename test may already PASS via Task 8's wiring — if so, keep it as a regression pin.

- [ ] **Step 3: Implement in `engine.py`**

In `_apply_replacements`, replace the token loop body:

```python
        for f, cur, repl in pairs:
            if f in rules.substring_rewrite_fields:
                # Opt-in per-field substring mode (codesign sec-02 secondary):
                # plain replacement, no boundary guard — gated on the target
                # declaring the token word-disjoint in press-rules.toml.
                new_text = new_text.replace(cur, repl)
            else:
                new_text = replace_token(new_text, f, cur, repl)
```

In `build_plan`, replace the `hit_fields` comprehension:

```python
            hit_fields = [
                f
                for f, cur, _ in pairs
                if (
                    (cur in text)
                    if f in rules.substring_rewrite_fields
                    else token_occurs(text, f, cur)
                )
            ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/ -v -x -k "SubstringMode or SubstringRenames or engine"`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/engine.py tests/rebrand/test_engine_replace.py tests/rebrand/test_engine_rename.py
git commit -m "feat(engine): opt-in per-field substring rewrite mode"
```

---

### Task 10: synthesize a display name for hermetic verify

**Files:**
- Modify: `src/template_press/rebrand/synthesize.py` (`synthesize_dest` lines 66-86; new `_synth_display`)
- Test: `tests/rebrand/test_synthesize.py`

**Interfaces:**
- Consumes: sparse `as_dict_prompted()` (Task 1), `_collides`, `_leading_letter`, `_source_variants`, `_MAX_ATTEMPTS`.
- Produces: `synthesize_dest(source)` returns an `Identity` whose `display_name` is a deterministic two-word Title-Case string when `source.display_name` is set (None otherwise), containment-free against the source's variant set in spaced AND glued (pascal/camel) forms. Without this, `press verify` on a display-declaring target would synthesize a half-specified destination and the display pass would never run — the scan (Task 11) would then flag the un-rewritten display name forever.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_synthesize.py` (reuse the file's identity builder; else `_identity` per Task 1):

```python
class TestSynthDisplayName:
    def test_none_stays_none(self):
        assert synthesize_dest(_identity()).display_name is None

    def test_deterministic_two_word_title(self):
        src = _identity(display_name="Py Launch Blueprint")
        a = synthesize_dest(src)
        b = synthesize_dest(src)
        assert a.display_name == b.display_name
        words = a.display_name.split()
        assert len(words) == 2
        assert all(w[0].isupper() and w[1:].islower() for w in words)

    def test_display_containment_free_vs_source_variants(self):
        src = _identity(display_name="Py Launch Blueprint")
        dst = synthesize_dest(src)
        lowered = dst.display_name.lower()
        glued = lowered.replace(" ", "")
        for value in src.as_dict().values():
            v = value.lower().replace("_", "").replace("-", "").replace(" ", "")
            assert v not in glued and glued not in v

    def test_dest_validates(self):
        synthesize_dest(_identity(display_name="Py Launch Blueprint")).validate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_synthesize.py -v -k SynthDisplayName`
Expected: `test_none_stays_none` PASSES (dataclass default); the others FAIL (`display_name is None`).

- [ ] **Step 3: Implement in `synthesize.py`**

In `synthesize_dest`, change the body to thread the display value:

```python
def synthesize_dest(source: Identity) -> Identity:
    """Build the deterministic synthetic TO-identity for `source`."""
    values = source.as_dict_prompted()
    display = values.pop("display_name", None)
    classes: dict[str, list[str]] = {}
    for field in REQUIRED_FIELDS:
        classes.setdefault(values[field], []).append(field)

    variant_inputs = list(values.values())
    if display is not None:
        variant_inputs.append(display)
    variants = _source_variants(variant_inputs)
    prefix = _safe_prefix(variants)

    dest_by_value: dict[str, str] = {}
    used: set[str] = set()
    for value, fields in classes.items():
        dest_by_value[value] = _synth_value(value, fields, prefix, used, variants)

    dest = Identity(
        **{field: dest_by_value[values[field]] for field in REQUIRED_FIELDS},
        display_name=(
            _synth_display(display, variants, used) if display is not None else None
        ),
    )
    dest.validate()
    return dest
```

Add after `_email_form`:

```python
def _synth_display(value: str, variants: frozenset[str], used: set[str]) -> str:
    """Deterministic two-word Title-Case synthetic display name.

    Both words are hash-derived (letter + hex body, like `_safe_prefix`);
    the candidate is rejected if its spaced OR glued (pascal ≈ camel under
    the case-insensitive `_collides`) form collides with any source
    variant, so the display rewrite pass and the paranoid scanner can never
    confuse synthetic output with surviving source identity.
    """
    for counter in range(_MAX_ATTEMPTS):
        digest = hashlib.sha256(f"display\x00{value}\x00{counter}".encode()).digest()
        hexes = digest.hex()
        w1 = _leading_letter(digest) + hexes[1:6]
        w2 = chr(ord("a") + digest[1] % 26) + hexes[6:11]
        candidate = f"{w1.capitalize()} {w2.capitalize()}"
        glued = w1.capitalize() + w2.capitalize()
        if (
            candidate not in used
            and not _collides(candidate, variants)
            and not _collides(glued, variants)
        ):
            used.add(candidate)
            return candidate
    raise ValidationError(
        f"synthesize: could not derive a containment-free display name within "
        f"{_MAX_ATTEMPTS} attempts"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_synthesize.py -v`
Expected: ALL PASS (including the four existing property tests).

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/synthesize.py tests/rebrand/test_synthesize.py
git commit -m "feat(synthesize): deterministic synthetic display name"
```

---

### Task 11: verify side — scan `display_name` when declared

**Files:**
- Modify: `src/template_press/rebrand/verify_config.py` (KNOWN_FIELDS line 25)
- Modify: `src/template_press/rebrand/verifier.py` (`_changed_fields` lines 73-83)
- Modify: `src/template_press/rebrand/verify_cli.py` (after `rules = load_rules(target)` line 314: derive `scan_fields`; use it at the `_preflight` call line 316 and the `scan(fields=...)` call line 352)
- Test: `tests/rebrand/test_verify_config.py`, `tests/rebrand/test_verifier.py`

**Interfaces:**
- Consumes: Task 1's sparse dicts; Task 10's synthetic display.
- Produces:
  - `KNOWN_FIELDS` includes `"display_name"` (so `[verify] extra_fields = ["display_name"]` is accepted).
  - `verifier._changed_fields` is total under sparse dicts: `[(f, src[f]) for f in fields if f in src and f in dst and src[f] != dst[f]]` (using a `dst = dest.as_dict()` local).
  - `verify_cli`: `scan_fields = cfg.fields if source.display_name is None or "display_name" in cfg.fields else (*cfg.fields, "display_name")` — display is scanned automatically whenever the target declares it (codesign sec-05); `_preflight(..., scan_fields)` and `scan(..., fields=scan_fields, ...)` both use it. (`_preflight` already skips fields discovery can't confirm, and `display_name` is never in `Discovered` — no further change.)
  - No matcher change: `matcher.identity_pattern("display_name", "Py Launch Blueprint")` already matches spaced/Pascal/camel via the `[-_. ]*` join.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rebrand/test_verify_config.py`:

```python
def test_display_name_is_a_known_extra_field():
    cfg = parse_verify_config({"extra_fields": ["display_name"]})
    assert "display_name" in cfg.fields
```

Append to `tests/rebrand/test_verifier.py` (reuse its git-target fixture idiom):

```python
class TestDisplayNameScan:
    def test_scan_flags_glued_display_variant(self, git_target):
        (git_target / "README.md").write_text(
            "# PyLaunchBlueprint intro\n", encoding="utf-8"
        )
        _git_add_all(git_target)
        src = _identity(display_name="Py Launch Blueprint")
        dst = _identity(display_name="Acme Widget")
        findings = scan(
            git_target,
            src,
            dst,
            fields=("display_name",),
            substring_fields=frozenset(),
            rules=DEFAULT_RULES,
        )
        assert any(
            f.field == "display_name" and f.where == "content" for f in findings
        )

    def test_sparse_identity_does_not_crash(self, git_target):
        _git_add_all(git_target)
        findings = scan(
            git_target,
            _identity(),           # no display_name
            _identity(app_name="acme"),
            fields=("app_name", "display_name"),
            substring_fields=frozenset(),
            rules=DEFAULT_RULES,
        )
        assert not any(f.field == "display_name" for f in findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rebrand/test_verify_config.py -v -k display && uv run pytest tests/rebrand/test_verifier.py -v -k DisplayNameScan`
Expected: verify_config test FAILS (`unknown field 'display_name'`); `test_sparse_identity_does_not_crash` FAILS with `KeyError`.

- [ ] **Step 3: Implement**

`verify_config.py` line 25:

```python
KNOWN_FIELDS: frozenset[str] = frozenset(REQUIRED_FIELDS) | {
    "app_name_upper",
    "display_name",
}
```

`verifier.py` `_changed_fields`:

```python
def _changed_fields(
    source: Identity, dest: Identity, fields: Sequence[str]
) -> list[tuple[str, str]]:
    """(field, source_value) pairs for fields that actually differ.

    Total under the sparse identity dicts: a field absent on either side
    (optional display_name) is simply not scanned.
    """
    src, dst = source.as_dict(), dest.as_dict()
    return [
        (f, src[f]) for f in fields if f in src and f in dst and src[f] != dst[f]
    ]
```

`verify_cli.py`: right after `rules = load_rules(target)` (line 314), add:

```python
        scan_fields: tuple[str, ...] = cfg.fields
        if source.display_name is not None and "display_name" not in scan_fields:
            # codesign sec-05: a declared display name is scanned as its own
            # field — the only coverage when its words diverge from the slug.
            scan_fields = (*scan_fields, "display_name")
```

then replace `cfg.fields` with `scan_fields` at the `_preflight(...)` call (line 316) and the `scan(..., fields=cfg.fields, ...)` call (line 352).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rebrand/test_verify_config.py tests/rebrand/test_verifier.py tests/rebrand/test_verify_cli.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/template_press/rebrand/verify_config.py src/template_press/rebrand/verifier.py src/template_press/rebrand/verify_cli.py tests/rebrand/test_verify_config.py tests/rebrand/test_verifier.py
git commit -m "feat(verify): scan display_name as its own field when declared"
```

---

### Task 12: end-to-end gap fixture, design doc, full gate

**Files:**
- Create: `tests/rebrand/test_cde_gaps.py`
- Create: `docs/design/0008-identity-variants-and-replace-rules.md`
- Modify: `docs/design/README.md` (index table — add the 0008 row following the existing format)

**Interfaces:**
- Consumes: everything above, `cli.main`.
- Produces: one integration test proving all three gap shapes press clean in a single `press rebrand`, and the normative design record the register's §8 TODO asked for.

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/rebrand/test_cde_gaps.py`:

```python
"""End-to-end: the three C/D/E gap shapes press clean in one rebrand.

Fixture reproduces the py-launch-blueprint leak shapes from
docs/research/0004 §5 (G3 _plbp_owned / plbp-web, G4 humanized display
name incl. the glued Pascal variant, G5 -plbp- doc filenames) and asserts
`press rebrand` exits 0 with every shape rewritten.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from template_press.rebrand.cli import main


def _git(target: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(target), *args], check=True, capture_output=True
    )


def _build_target(tmp_path: Path) -> Path:
    target = tmp_path / "plbp-repo"
    (target / "press").mkdir(parents=True)
    (target / "docs").mkdir()
    (target / "press" / "press-source.toml").write_text(
        "[identity]\n"
        'package_name = "py_launch_blueprint"\n'
        'repo_name    = "py-launch-blueprint"\n'
        'app_name     = "plbp"\n'
        'author       = "Steve Morin"\n'
        'email        = "steve.morin@gmail.com"\n'
        'owner        = "smorinlabs"\n'
        'display_name = "Py Launch Blueprint"\n',
        encoding="utf-8",
    )
    (target / "press" / "press-rules.toml").write_text(
        '[rules]\nsubstring_rewrite_fields = ["app_name"]\n\n'
        "[[replace]]\n"
        'pattern = "_{app_name}_owned"\n'
        'reason  = "logging handler ownership guard"\n',
        encoding="utf-8",
    )
    (target / "conftest.py").write_text(
        'getattr(h, "_plbp_owned", False)\n', encoding="utf-8"
    )
    (target / "Dockerfile").write_text("FROM plbp-web:dev\n", encoding="utf-8")
    (target / "README.md").write_text(
        "# Py Launch Blueprint\nAlso known as PyLaunchBlueprint.\n",
        encoding="utf-8",
    )
    (target / "docs" / "0001-app-short-name-plbp.md").write_text(
        "the app short name\n", encoding="utf-8"
    )
    (target / "pyproject.toml").write_text(
        "[project]\n"
        'name = "py-launch-blueprint"\n'
        'version = "0.1.0"\n'
        'authors = [{name = "Steve Morin", email = "steve.morin@gmail.com"}]\n'
        "[project.scripts]\n"
        'plbp = "py_launch_blueprint.cli:main"\n',
        encoding="utf-8",
    )
    (target / "src" / "py_launch_blueprint").mkdir(parents=True)
    (target / "src" / "py_launch_blueprint" / "__init__.py").write_text(
        '"""Py Launch Blueprint."""\n', encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "t")
    _git(
        target,
        "remote",
        "add",
        "origin",
        "https://github.com/smorinlabs/py-launch-blueprint.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def _answers(tmp_path: Path) -> Path:
    answers = tmp_path / "press-answers.toml"
    answers.write_text(
        "[answers]\n"
        'package_name = "acme_widget"\n'
        'repo_name    = "acme-widget"\n'
        'app_name     = "acme"\n'
        'author       = "Ada Lovelace"\n'
        'email        = "ada@example.com"\n'
        'owner        = "acmelabs"\n'
        'display_name = "Acme Widget"\n',
        encoding="utf-8",
    )
    return answers


class TestCdeGapsEndToEnd:
    def test_all_three_gap_shapes_press_clean(self, tmp_path):
        target = _build_target(tmp_path)
        answers = _answers(tmp_path)
        code = main(["--target", str(target), "--config", str(answers)])
        assert code == 0
        assert "_acme_owned" in (target / "conftest.py").read_text(encoding="utf-8")
        assert "acme-web:dev" in (target / "Dockerfile").read_text(encoding="utf-8")
        readme = (target / "README.md").read_text(encoding="utf-8")
        assert "# Acme Widget" in readme and "AcmeWidget" in readme
        assert "Py Launch Blueprint" not in readme
        assert (target / "docs" / "0001-app-short-name-acme.md").exists()
        source_cfg = (target / "press" / "press-source.toml").read_text(
            encoding="utf-8"
        )
        assert 'display_name = "Acme Widget"' in source_cfg

    def test_half_specified_answers_exit_2(self, tmp_path):
        target = _build_target(tmp_path)
        answers = tmp_path / "half.toml"
        answers.write_text(
            "[answers]\n"
            'package_name = "acme_widget"\n'
            'repo_name    = "acme-widget"\n'
            'app_name     = "acme"\n'
            'author       = "Ada Lovelace"\n'
            'email        = "ada@example.com"\n'
            'owner        = "acmelabs"\n',
            encoding="utf-8",
        )
        assert main(["--target", str(target), "--config", str(answers)]) == 2
```

NOTE: `press rebrand` runs `git status` (dirty check) — the fixture commits everything, so the tree is clean. The rebrand renames `src/py_launch_blueprint/` → `src/acme_widget/` via the existing package-dir rename. The doctor + regeneration paths run live: no `uv.lock` exists in the fixture, so lockfile regeneration is a no-op.

- [ ] **Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/rebrand/test_cde_gaps.py -v`
Expected: PASS if Tasks 1-11 are complete and correct — this is the integration gate. Any FAIL points at the incomplete task; fix there, not here.

- [ ] **Step 3: Write the design record**

Create `docs/design/0008-identity-variants-and-replace-rules.md` with this content (normative counterpart to research 0005; trim nothing):

```markdown
# 0008 — Identity Variants & Replace Rules (C/D/E gap fixes)

**Status:** accepted (codesign 2026-07-23) · **Informed by:**
[research 0005](../research/0005-scaffolder-identity-variant-handling.md),
[research 0004 §5](../research/0004-py-launch-blueprint-conformance-gaps.md)

## Decisions

1. **`display_name` — optional 7th identity field** (sec-01 ch-01-a).
   Declared in `[identity]`/`[answers]`; absent = feature off (existing
   configs stay valid). Rewritten as a CLOSED set of exact forms —
   spaced / PascalCase / camelCase — each replaced with the same-shaped
   form of the new name; the set is configurable via
   `[rules] display_forms` (sec-04 ch-04-c, default all three). Verify
   scans it as its own field whenever declared (sec-05 ch-05-a).
   Half-specified (source declares, answers doesn't) is exit 2 (sec-06
   ch-06-a). Derivation from repo_name was REJECTED — real product names
   ("NumPy", "PyTorch") are not titleized slugs.
2. **`[[replace]]` exact rules — the primary glued-token mechanism**
   (sec-02 ch-02-c, "rules primary"). One template string with `{field}`
   placeholders, rendered twice: source identity → literal to find,
   destination identity → literal to write. Exact replacement, no fuzzy
   matching. Interpolation keeps committed rules correct across repeated
   presses (press rewrites press-source.toml post-apply). Arguments
   (sec-07): `files` globs, `paths` (default false), `content` (default
   true), required `reason`. `count` was rejected — occurrence counts rot.
3. **Substring mode — secondary, per-field opt-in** (sec-02 ch-02-c).
   `[rules] substring_rewrite_fields = ["app_name"]` switches that field
   to plain substring replacement in content AND path components. Gated on
   the target author declaring the token word-disjoint; never a default.
4. **Paths ride the shared matcher** (sec-03 ch-03-a). Rules with
   `paths = true` and substring-mode fields flow into the existing
   `_renamed_rel` rename pass — no second matching surface (the dotnet
   content-vs-path divergence lesson). `paths=true, content=false` IS the
   dedicated path-only rename rule. New guard: a substitution that would
   empty a path component fails loud (cookiecutter #1518 class).

## Order of operations (engine.apply)

`[[replace]]` rules → boundary/substring token pairs (content), then
symlink retarget, then renames to fixpoint. Rules run first because a
rendered FROM may embed an identity token the token pass would rewrite
out from under it.

## Consequences

- py-launch-blueprint's conform needs: `display_name = "Py Launch
  Blueprint"`, `substring_rewrite_fields = ["app_name"]`, and ~1-3
  `[[replace]]` rules — closing G3/G4/G5 without verify ignores.
- `press verify` on a display-declaring target auto-extends its scan
  fields; the hermetic press synthesizes a containment-free display name.
```

Add to `docs/design/README.md`'s index table (match the existing row format exactly):

```markdown
| [0008](0008-identity-variants-and-replace-rules.md) | Identity variants & replace rules (C/D/E gap fixes) | accepted |
```

(If the README's table has different columns, follow its actual columns.)

- [ ] **Step 4: Full gate**

Run: `cd /Users/stevemorin/c/template-press-cde && just check`
Expected: format, lint, typecheck (`ty`), tests — ALL PASS. Fix anything it flags (line length and typing are the usual suspects).

Run: `just matrix`
Expected: R1/R2/R3 acceptance matrix PASS (required after any `src/template_press/rebrand/` change).

- [ ] **Step 5: Commit**

```bash
git add tests/rebrand/test_cde_gaps.py docs/design/0008-identity-variants-and-replace-rules.md docs/design/README.md
git commit -m "test(rebrand): end-to-end c/d/e gap fixture; docs(design): 0008 decision record"
```

---

## Self-Review Notes

- **Spec coverage:** sec-01 → Tasks 1-4 (field) + 5-8 (rules); sec-02 → Tasks 5, 7 (rules primary), 9 (substring secondary); sec-03 → Task 8 (+ per-rule `paths`/`content` control satisfying the export note); sec-04 → Task 1 forms + Task 5 `display_forms` knob (configurable, per the note); sec-05 → Task 11; sec-06 → Task 4; sec-07 → Tasks 5-6 (`files`/`paths`/`reason`, no `count`). Register §8 TODO (design record) → Task 12.
- **Type consistency:** `replacement_pairs(source, dest, display_form_names)` (Tasks 3, 7); `_renamed_rel(rel, pairs, rendered, substring_fields)` (Task 8); `rendered_replace_rules(rules, source, dest) -> list[tuple[ReplaceRule, str, str]]` (Tasks 7-8); `find_leaks(..., display_form_names=...)` (Task 3); `ReplaceRule(pattern, reason, files, paths, content)` (Tasks 5-9, 12).
- **Known deferred (documented, not planned):** `_retarget_symlinks` stays token-only (no rules/substring in symlink strings); `_collisions` does not consider display_name; `[[replace]]` patterns cannot contain literal `{`/`}`.
