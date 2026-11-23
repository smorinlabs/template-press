"""Declared keep_names: span helpers, content-rewrite protection, validation."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand import keep_names as keep_names_module
from template_press.rebrand.cli import main
from template_press.rebrand.engine import apply, build_plan
from template_press.rebrand.identity import Identity, ValidationError, display_forms
from template_press.rebrand.keep_names import (
    component_kept_spans,
    disjoint_from_kept,
    kept_spans,
    outside_kept,
    validate_keep_names,
)
from template_press.rebrand.pipeline import MatcherSpec
from template_press.rebrand.rules import DEFAULT_RULES, Rules, load_rules
from template_press.rebrand.substitutions import (
    RenderedSubstitution,
    Scope,
    SubstitutionTable,
    rewrite_with_row,
)
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verify_cli import verify_command

KEPT = "@acme/widget-extra"
SOURCE = Identity(
    package_name="acme_core",
    repo_name="acme-repo",
    app_name="acmeapp",
    author="Acme Author",
    email="author@example.test",
    owner="acme",
    display_name="Acme Widget",
    npm_name="@acme/widget",
    cli_name="acme-cli",
)
DEST = Identity(
    package_name="other_core",
    repo_name="other-repo",
    app_name="otherapp",
    author="Other Author",
    email="other@example.test",
    owner="other-owner",
    display_name="Other Thing",
    npm_name="@new/x",
    cli_name="new-cli",
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _toml_identity(identity: Identity, table: str) -> str:
    rows = identity.as_dict_prompted().items()
    return f"[{table}]\n" + "".join(f'{k} = "{v}"\n' for k, v in rows)


def _make_target(
    tmp_path: Path, rules_text: str, files: dict[str, str] | None = None
) -> Path:
    target = tmp_path / SOURCE.repo_name
    (target / "press").mkdir(parents=True)
    (target / "press" / "press-source.toml").write_text(
        _toml_identity(SOURCE, "identity"), encoding="utf-8"
    )
    (target / "press" / "press-rules.toml").write_text(rules_text, encoding="utf-8")
    (target / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{SOURCE.package_name}"\n'
        'version = "0.1.0"\n'
        f'authors = [{{name = "{SOURCE.author}", email = "{SOURCE.email}"}}]\n'
        "[project.scripts]\n"
        f'{SOURCE.app_name} = "{SOURCE.package_name}.cli:main"\n',
        encoding="utf-8",
    )
    (target / "package.json").write_text(
        json.dumps(
            {
                "name": SOURCE.npm_name,
                "version": "0.1.0",
                "bin": {SOURCE.cli_name: f"./bin/{SOURCE.cli_name}.js"},
            }
        ),
        encoding="utf-8",
    )
    (target / "README.md").write_text(f"# {SOURCE.display_name}\n", encoding="utf-8")
    package = target / "src" / SOURCE.package_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
    for rel, text in (files or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.test")
    _git(target, "config", "user.name", "t")
    _git(
        target,
        "remote",
        "add",
        "origin",
        f"https://github.com/{SOURCE.owner}/{SOURCE.repo_name}.git",
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "seed")
    return target


def _keep_rules(names: list[str], extra: str = "") -> str:
    return f"[rules]\nkeep_names = {json.dumps(names)}\n{extra}"


def _answers(tmp_path: Path, dest: Identity = DEST) -> Path:
    path = tmp_path / "answers.toml"
    path.write_text(_toml_identity(dest, "answers"), encoding="utf-8")
    return path


def _row(
    from_value: str,
    to_value: str,
    *,
    algorithm: str = "conservative",
    field: str | None = "owner",
    substring: bool = False,
) -> RenderedSubstitution:
    return RenderedSubstitution(
        row_id="row",
        provenance=(),
        matcher=MatcherSpec(algorithm, field, substring),  # type: ignore[arg-type]
        from_value=from_value,
        to_value=to_value,
        rewrite_surfaces=frozenset({"content"}),
        hunts=(),
        scope=Scope(),
    )


ROW_KINDS = {
    "owner": _row("acme", "other"),
    "repo_name": _row("widget", "thing", field="repo_name"),
    "substring": _row("acme", "other", substring=True),
    "replace": _row("acme/widget", "other/thing", algorithm="literal", field=None),
}


def test_kept_span_allows_subpath():
    assert kept_spans("@a/b-c/sub", ["@a/b-c"]) == ((0, 6),)


def test_kept_span_rejects_longer_name():
    assert kept_spans("@a/b-c-2", ["@a/b-c"]) == ()


def test_kept_span_is_case_sensitive():
    assert kept_spans("@A/B-C", ["@a/b-c"]) == ()


def test_kept_spans_are_not_merged():
    assert kept_spans("a.b.c", ["a.b", "b.c"]) == ((0, 3), (2, 5))


def test_outside_kept_drops_contained():
    assert outside_kept([(0, 4)], [(0, 6)]) == []


def test_outside_kept_retains_overlap():
    assert outside_kept([(4, 8)], [(0, 6)]) == [(4, 8)]


def test_outside_kept_does_not_span_two_kept_names():
    assert outside_kept([(0, 5)], [(0, 3), (2, 5)]) == [(0, 5)]


@pytest.mark.parametrize(
    ("span", "expected"),
    [((0, 2), True), ((2, 4), False), ((3, 5), False), ((5, 7), False), ((8, 9), True)],
)
def test_disjoint_from_kept_is_half_open(span, expected):
    assert disjoint_from_kept(span, [(2, 8)]) is expected


def test_component_spans_follow_a_scoped_name_across_components():
    parts = ["packages", "@acme", "widget-extra", "index.ts"]
    assert component_kept_spans(parts, 1, [KEPT]) == ((0, 5),)
    assert component_kept_spans(parts, 2, [KEPT]) == ((0, 12),)
    assert component_kept_spans(parts, 0, [KEPT]) == ()
    assert component_kept_spans(parts, 3, [KEPT]) == ()


def test_component_spans_use_true_neighbors():
    assert component_kept_spans(["@acme", "widget-extra-2"], 0, [KEPT]) == ()


@pytest.mark.parametrize("kind", sorted(ROW_KINDS))
def test_rewrite_preserves_kept_for_owner_repo_substring_and_replace_rows(kind):
    text = f"use {KEPT}/sub here"
    assert rewrite_with_row(ROW_KINDS[kind], text, keep_names=[KEPT]) == text


def test_rewrite_still_changes_adjacent_identity():
    row = _row("@acme/widget", "@new/x", field="npm_name")
    out = rewrite_with_row(row, f"@acme/widget {KEPT}", keep_names=[KEPT])
    assert out == "@new/x @acme/widget-extra"


def test_rewrite_near_miss_name_is_not_kept():
    out = rewrite_with_row(_row("acme", "other"), f"{KEPT}-2", keep_names=[KEPT])
    assert out == "@other/widget-extra-2"


def test_rewrite_leaves_partial_overlap_for_the_leak_scan():
    row = _row("x/@acme", "gone", algorithm="literal", field=None)
    text = f"x/{KEPT}"
    assert rewrite_with_row(row, text, keep_names=[KEPT]) == text


def test_rewrite_finds_a_match_hidden_behind_a_suppressed_overlap():
    row = _row("a.a", "Z", algorithm="literal", field=None)
    # (2, 5) overlaps kept (0, 3) and is suppressed; it must not shadow (4, 7).
    assert rewrite_with_row(row, "x.a.a.a", keep_names=["x.a"]) == "x.a.Z"


def test_rewrite_boundary_sees_text_before_a_suppressed_match():
    row = _row("a.a", "Z", field="npm_name")
    # After suppressing (2, 5), the candidate at (4, 7) has a true left neighbor.
    assert rewrite_with_row(row, "x.a.a.a", keep_names=["x.a"]) == "x.a.Z"
    assert rewrite_with_row(row, "x.a.b-a.a", keep_names=["x.a"]) == "x.a.b-a.a"


def test_rewrite_keeps_replacement_literal():
    row = _row("acme", r"\1\g<0>")
    assert (
        rewrite_with_row(row, f"acme {KEPT}", keep_names=[KEPT]) == rf"\1\g<0> {KEPT}"
    )


@pytest.mark.parametrize("kind", sorted(ROW_KINDS))
def test_rewrite_without_kept_occurrence_equals_legacy(kind):
    text = "acme/widget acme-x xacme acme_y widget acme/widgets"
    row = ROW_KINDS[kind]
    assert rewrite_with_row(row, text, keep_names=[KEPT]) == rewrite_with_row(row, text)


def test_rules_default_to_no_keep_names():
    assert DEFAULT_RULES.keep_names == ()
    assert SubstitutionTable(rows=(), rename_plan=None).keep_names == ()  # type: ignore[arg-type]


def test_keep_names_is_the_last_rules_field():
    assert list(Rules.__dataclass_fields__)[-1] == "keep_names"


def test_load_rules_reads_keep_names(tmp_path):
    target = _make_target(tmp_path, _keep_rules([KEPT]))
    assert load_rules(target).keep_names == (KEPT,)


@pytest.mark.parametrize(
    "extra",
    [
        "",
        'substring_rewrite_fields = ["owner"]\n',
        '[[replace]]\npattern = "{owner}/widget-extra"\nreason = "test"\n',
    ],
    ids=["conservative", "substring", "replace"],
)
def test_press_apply_preserves_kept_content(tmp_path, extra):
    files = {"src/use.ts": f'import "{KEPT}/sub";\nimport "@acme/widget";\n'}
    target = _make_target(tmp_path, _keep_rules([KEPT], extra), files)
    rules = load_rules(target)
    plan = build_plan(target, SOURCE, DEST, rules)
    assert plan.table.keep_names == (KEPT,)
    apply(target, SOURCE, DEST, rules, table=plan.table)
    assert (target / "src" / "use.ts").read_text(encoding="utf-8") == (
        f'import "{KEPT}/sub";\nimport "@new/x";\n'
    )


def test_plan_does_not_report_a_file_with_only_kept_names(tmp_path):
    files = {"notes.md": f"{KEPT}\n"}
    target = _make_target(tmp_path, _keep_rules([KEPT]), files)
    plan = build_plan(target, SOURCE, DEST, load_rules(target))
    assert "notes.md" not in {i.path for i in plan.items if i.kind == "replace"}


def test_visibility_projection_ignores_kept_names(tmp_path):
    files = {".gitignore": f"{KEPT}/\n"}
    target = _make_target(tmp_path, _keep_rules([KEPT]), files)
    build_plan(target, SOURCE, DEST, load_rules(target))


def _output(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _bad_values() -> dict[str, str]:
    return {
        "empty": "",
        "blank": "   ",
        "nul": "a\x00b",
        "newline": "a\nb",
        "delete": "a\x7fb",
        "source_npm": SOURCE.npm_name or "",
        "source_repo": SOURCE.repo_name,
        "source_upper": SOURCE.app_name_upper,
        "source_pascal": display_forms(SOURCE.display_name or "")["pascal"],
        "source_camel": display_forms(SOURCE.display_name or "")["camel"],
        "source_package_hyphen": SOURCE.package_name.replace("_", "-"),
        "dest_npm": DEST.npm_name or "",
        "dest_repo": DEST.repo_name,
        "dest_pascal": display_forms(DEST.display_name or "")["pascal"],
        "dest_package_hyphen": DEST.package_name.replace("_", "-"),
    }


@pytest.mark.parametrize("label", sorted(_bad_values()))
def test_invalid_keep_name_exits_2_without_writes(tmp_path, capsys, label):
    bad = _bad_values()[label]
    target = _make_target(tmp_path, _keep_rules([bad]))
    head = _git(target, "rev-parse", "HEAD")
    code = main(["--target", str(target), "--config", str(_answers(tmp_path))])
    assert code == 2
    assert "keep_names" in _output(capsys)
    assert _git(target, "status", "--porcelain") == ""
    assert _git(target, "rev-parse", "HEAD") == head


@pytest.mark.parametrize(
    "label", sorted(k for k in _bad_values() if not k.startswith("dest_"))
)
def test_verify_refuses_the_same_entries(tmp_path, capsys, label):
    target = _make_target(tmp_path, _keep_rules([_bad_values()[label]]))
    assert verify_command(["--target", str(target)]) == 2
    assert "keep_names" in _output(capsys)
    assert _git(target, "status", "--porcelain") == ""


@pytest.mark.parametrize("raw", ["[1]", '["ok", 2]', '"not-a-list"'])
def test_non_string_keep_names_exit_2(tmp_path, capsys, raw):
    target = _make_target(tmp_path, f"[rules]\nkeep_names = {raw}\n")
    code = main(["--target", str(target), "--config", str(_answers(tmp_path))])
    assert code == 2
    assert "keep_names" in _output(capsys)
    assert _git(target, "status", "--porcelain") == ""


@pytest.mark.parametrize("field", ["repo_name", "owner", "npm_name"])
def test_synthesized_destination_never_refuses_in_verify(tmp_path, capsys, field):
    entry = getattr(synthesize_dest(SOURCE), field)
    target = _make_target(tmp_path, _keep_rules([entry]))
    code = verify_command(["--target", str(target)])
    assert "keep_names" not in _output(capsys)
    assert code == 0


def test_same_entry_is_refused_as_a_real_destination(tmp_path, capsys):
    entry = synthesize_dest(SOURCE).repo_name
    target = _make_target(tmp_path, _keep_rules([entry]))
    answers = _answers(tmp_path, replace(DEST, repo_name=entry))
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert "keep_names" in _output(capsys)


def test_validate_direct_rejects_non_string():
    with pytest.raises(ValidationError, match="keep_names"):
        validate_keep_names([1], SOURCE, DEST)  # type: ignore[list-item]


def test_validate_accepts_independent_sibling():
    validate_keep_names([KEPT], SOURCE, DEST)


def test_module_imports_only_stdlib_identity_and_matcher():
    tree = ast.parse(Path(keep_names_module.__file__).read_text(encoding="utf-8"))
    allowed = {"template_press.rebrand.identity", "template_press.rebrand.matcher"}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            modules.add(node.module or "")
    for module in modules - allowed:
        assert module.split(".")[0] in sys.stdlib_module_names, module
