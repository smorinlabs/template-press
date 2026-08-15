"""P06-TS09: standalone verifier dependency and data-flow guardrails."""

from __future__ import annotations

import ast
import inspect
import subprocess
from dataclasses import replace
from pathlib import Path

from template_press.rebrand.engine import apply, build_plan
from template_press.rebrand.rules import DEFAULT_RULES, ReplaceRule
from template_press.rebrand.substitutions import SubstitutionTable
from template_press.rebrand.verifier import scan

from .conftest import DEST, SOURCE

PACKAGE = "template_press.rebrand"
PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "template_press" / "rebrand"
FORBIDDEN = {
    f"{PACKAGE}.substitutions",
    f"{PACKAGE}.engine",
    f"{PACKAGE}.doctor",
}
FORBIDDEN_SCAN_PARAMETERS = {
    "table",
    "rows",
    "rendered_rules",
    "hunt_policies",
    "matcher_dispatch",
}


def _module_path(module: str) -> Path | None:
    if module == PACKAGE:
        path = PACKAGE_ROOT / "__init__.py"
    elif module.startswith(f"{PACKAGE}."):
        path = PACKAGE_ROOT / f"{module.removeprefix(f'{PACKAGE}.')}.py"
    else:
        return None
    return path if path.is_file() else None


def _local_imports(module: str) -> set[str]:
    path = _module_path(module)
    assert path is not None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_module = node.module
            if node.level:
                package_parts = module.split(".")[:-1]
                retained_parts = len(package_parts) - node.level + 1
                if retained_parts <= 0:
                    continue
                relative_parts = (
                    imported_module.split(".") if imported_module is not None else []
                )
                imported_module = ".".join(
                    (*package_parts[:retained_parts], *relative_parts)
                )
            if imported_module is not None:
                imports.add(imported_module)
            if node.module is None or imported_module == PACKAGE:
                imports.update(
                    f"{imported_module}.{alias.name}" for alias in node.names
                )
    return {name for name in imports if _module_path(name) is not None}


def _transitive_imports(root: str) -> set[str]:
    seen: set[str] = set()
    pending = [root]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        pending.extend(_local_imports(module) - seen)
    return seen


def test_verifier_import_closure_excludes_table_consumers() -> None:
    closure = _transitive_imports(f"{PACKAGE}.verifier")

    assert closure.isdisjoint(FORBIDDEN), sorted(closure & FORBIDDEN)


def test_local_imports_resolves_relative_modules(tmp_path: Path, monkeypatch) -> None:
    package_root = tmp_path / "rebrand"
    package_root.mkdir()
    (package_root / "verifier.py").write_text(
        "from .substitutions import SubstitutionTable\n",
        encoding="utf-8",
    )
    (package_root / "substitutions.py").write_text("", encoding="utf-8")
    monkeypatch.setitem(globals(), "PACKAGE_ROOT", package_root)

    assert _local_imports(f"{PACKAGE}.verifier") == {f"{PACKAGE}.substitutions"}


def test_verifier_scan_boundary_rejects_precompiled_substitution_data() -> None:
    assert set(inspect.signature(scan).parameters).isdisjoint(FORBIDDEN_SCAN_PARAMETERS)

    verify_cli = PACKAGE_ROOT / "verify_cli.py"
    tree = ast.parse(
        verify_cli.read_text(encoding="utf-8"),
        filename=str(verify_cli),
    )
    scan_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "scan"
    ]
    assert scan_calls
    for call in scan_calls:
        keyword_names = {item.arg for item in call.keywords}
        assert keyword_names.isdisjoint(FORBIDDEN_SCAN_PARAMETERS)


def _git_add_all(target: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "add", "-A"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def test_rule_ablation_does_not_remove_independent_verifier_finding(
    src_target: Path,
) -> None:
    rule = ReplaceRule(pattern="x{app_name}owned", reason="independence fixture")
    rules = replace(DEFAULT_RULES, replace=(rule,))
    residual = src_target / "rule-ablation.txt"
    residual.write_text("xpressowned\n", encoding="utf-8")
    _git_add_all(src_target)
    plan = build_plan(src_target, SOURCE, DEST, rules)
    assert plan.table is not None
    ablated = SubstitutionTable(
        rows=tuple(
            row for row in plan.table.rows if row.provenance[0].kind != "replace_rule"
        ),
        rename_plan=plan.table.rename_plan,
    )

    apply(src_target, SOURCE, DEST, rules, table=ablated)
    findings = scan(
        src_target,
        SOURCE,
        DEST,
        fields=("app_name",),
        substring_fields=frozenset(),
        rules=rules,
    )

    assert any(
        finding.path == "rule-ablation.txt"
        and finding.field == "replace_rule"
        and finding.value == "xpressowned"
        for finding in findings
    )


def test_identity_ablation_does_not_remove_independent_verifier_finding(
    src_target: Path,
) -> None:
    destination = replace(SOURCE, app_name="potato")
    rules = replace(
        DEFAULT_RULES,
        substring_rewrite_fields=frozenset({"app_name"}),
    )
    residual = src_target / "identity-ablation.txt"
    residual.write_text("xpressowned\n", encoding="utf-8")
    _git_add_all(src_target)
    plan = build_plan(src_target, SOURCE, destination, rules)
    assert plan.table is not None
    ablated = SubstitutionTable(
        rows=tuple(
            row
            for row in plan.table.rows
            if all(item.name != "app_name" for item in row.provenance)
        ),
        rename_plan=plan.table.rename_plan,
    )

    apply(src_target, SOURCE, destination, rules, table=ablated)
    findings = scan(
        src_target,
        SOURCE,
        destination,
        fields=("app_name",),
        substring_fields=rules.substring_rewrite_fields,
        rules=rules,
    )

    assert any(
        finding.path == "identity-ablation.txt"
        and finding.field == "app_name"
        and finding.value == "press"
        for finding in findings
    )
