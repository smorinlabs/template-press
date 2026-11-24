"""Cargo discovery gates: language selection, name checks, and the proposal."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.cargo_manifest import read_cargo_facts
from template_press.rebrand.cli import main
from template_press.rebrand.discovery import (
    cargo_problems,
    cargo_table_hint,
    cargo_warnings,
    discover,
)
from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    cargo_identity_problem,
)
from template_press.rebrand.keep_names import (
    check_keep_surfaces,
    sibling_guidance,
    validate_keep_names,
)
from template_press.rebrand.languages import SUPPORTED_LANGUAGES
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules
from template_press.rebrand.substitutions import check_target_keep_names
from template_press.rebrand.verify_cli import verify_command

OWNER = "acme-org"
AUTHOR = 'authors = ["Ada Example <ada@example.test>"]\n'


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _repo(
    tmp_path: Path,
    files: dict[str, str],
    *,
    repo_name: str = "acme-core",
    owner: str = OWNER,
) -> Path:
    target = (tmp_path / "target").resolve()
    target.mkdir()
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(target, "init", "-q", "-b", "main")
    _git(target, "remote", "add", "origin", f"https://github.com/{owner}/{repo_name}")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "fixture")
    return target


def _toml_table(header: str, values: dict[str, str]) -> str:
    rows = "".join(f'{key} = "{value}"\n' for key, value in values.items())
    return f"[{header}]\n{rows}"


def _identity_values(**overrides: str) -> dict[str, str]:
    values = {
        "package_name": "acme_core",
        "repo_name": "acme-core",
        "app_name": "acme_core",
        "author": "Ada Example",
        "email": "ada@example.test",
        "owner": OWNER,
    }
    values.update(overrides)
    return values


def _dest_values(**overrides: str) -> dict[str, str]:
    values = {
        "package_name": "zeta_core",
        "repo_name": "zeta-core",
        "app_name": "zeta_core",
        "author": "Zed Example",
        "email": "zed@example.test",
        "owner": "zeta-org",
    }
    values.update(overrides)
    return values


def _source_config(cargo: dict[str, str] | None = None, **overrides: str) -> str:
    text = _toml_table("identity", _identity_values(**overrides))
    if cargo:
        text += _toml_table("identity.cargo_names", cargo)
    return text


def _answers(
    tmp_path: Path, cargo: dict[str, str] | None = None, **overrides: str
) -> Path:
    text = _toml_table("answers", _dest_values(**overrides))
    if cargo:
        text += _toml_table("answers.cargo_names", cargo)
    path = tmp_path / "answers.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _crate(name: str, extra: str = "") -> str:
    return f'[package]\nname = "{name}"\nversion = "0.1.0"\n{AUTHOR}{extra}'


def _press(target: Path, answers: Path | None = None) -> int:
    argv = ["--target", str(target), "--dry-run"]
    if answers is not None:
        argv += ["--config", str(answers)]
    return main(argv)


def _identity(cargo: dict[str, str] | None = None, **overrides: str) -> Identity:
    return Identity.from_mapping(_identity_values(**overrides), cargo)


def _clean(target: Path) -> bool:
    return _git(target, "status", "--porcelain") == ""


CORE_MAP = {"core": "acme-core"}
ZETA_MAP = {"core": "zeta-core"}


# --- Rust active without a map ---------------------------------------------


def test_no_map_broken_crate_name_exits_2_with_paste_ready_table(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-widget"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                package_name="acme_widget", repo_name="acme-repo"
            ),
        },
        repo_name="acme-repo",
    )
    code = _press(
        target, _answers(tmp_path, package_name="zeta_widget", repo_name="zeta-repo")
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "acme-widget" in out
    table = out[out.index("[identity.cargo_names]") :]
    parsed = tomllib.loads("\n".join(line.strip() for line in table.splitlines()))
    assert parsed["identity"]["cargo_names"] == {"acme_widget": "acme-widget"}
    assert _clean(target)


def test_no_map_crate_equal_to_repo_name_continues(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-widget"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                package_name="acme_widget", repo_name="acme-widget"
            ),
        },
        repo_name="acme-widget",
    )
    answers = _answers(tmp_path, package_name="zeta_widget", repo_name="zeta-widget")
    assert _press(target, answers) == 0


def test_no_map_equal_repo_with_diverging_identifier_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-widget"),
            "src/lib.rs": "pub fn hi() {}\n",
            "src/main.rs": "fn main() { acme_widget::hi(); }\n",
            "press/press-source.toml": _source_config(
                package_name="acme_widget", repo_name="acme-widget"
            ),
        },
        repo_name="acme-widget",
    )
    answers = _answers(tmp_path, package_name="zeta_other", repo_name="zeta-widget")
    assert _press(target, answers) == 2
    assert "[identity.cargo_names]" in capsys.readouterr().out


def test_no_map_python_hyphen_row_counts_only_when_package_changes(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "pyproject.toml": '[project]\nname = "acme-core"\n',
            "src/lib.rs": "pub fn hi() {}\n",
            "src/acme_core/__init__.py": "",
            "press/press-rules.toml": '[rules]\nlanguages = ["python", "rust"]\n',
        },
        repo_name="acme-repo",
    )
    rules = load_rules(target)
    source = _identity(repo_name="acme-repo")
    moved = Identity.from_mapping(_dest_values(repo_name="zeta-repo"))
    assert cargo_problems(target, source, moved, rules) == []
    kept = Identity.from_mapping(
        _dest_values(package_name="acme_core", repo_name="zeta-repo")
    )
    assert cargo_problems(target, source, kept, rules) != []


def test_no_map_hyphen_claimed_by_unchanged_repo_is_refused(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "pyproject.toml": '[project]\nname = "acme-core"\n',
            "src/lib.rs": "pub fn hi() {}\n",
            "src/acme_core/__init__.py": "",
            "press/press-rules.toml": '[rules]\nlanguages = ["python", "rust"]\n',
        },
    )
    dest = Identity.from_mapping(_dest_values(repo_name="acme-core"))
    assert cargo_problems(target, _identity(), dest, load_rules(target)) != []


def test_no_map_unrelated_crate_warns_on_stderr(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("tools-helper"),
            "src/lib.rs": "pub fn hi() {}\n",
            "README.md": "acme_core acme-core\n",
            "press/press-source.toml": _source_config(),
        },
    )
    assert _press(target, _answers(tmp_path)) == 0
    assert "tools-helper" in capsys.readouterr().err


def test_no_map_name_in_keep_names_does_not_refuse(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-widget"),
            "src/lib.rs": "pub fn hi() {}\n",
            "README.md": "acme_repo acme-repo\n",
            "press/press-source.toml": _source_config(
                package_name="acme_repo", repo_name="acme-repo", app_name="acme"
            ),
            "press/press-rules.toml": '[rules]\nkeep_names = ["acme-widget"]\n',
        },
        repo_name="acme-repo",
    )
    answers = _answers(
        tmp_path, package_name="zeta_repo", repo_name="zeta-repo", app_name="zeta"
    )
    assert _press(target, answers) == 0
    assert "acme-widget" in capsys.readouterr().err


# --- With a map -------------------------------------------------------------


def test_undeclared_discovered_name_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", '[[bin]]\nname = "other-tool"\n')
            + 'path = "src/main.rs"\n',
            "src/main.rs": "fn main() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert _press(target, _answers(tmp_path, ZETA_MAP)) == 2
    assert "other-tool" in capsys.readouterr().out
    assert _clean(target)


def test_default_lib_spelling_is_covered_by_its_hyphen_role(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", '[lib]\nname = "acme_core"\n'),
            "src/lib.rs": "pub fn hi() {}\n",
        },
    )
    assert cargo_problems(target, _identity(CORE_MAP), None, load_rules(target)) == []


def test_declared_name_missing_from_manifests_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                {"core": "acme-core", "ghost": "acme-ghost"}
            ),
        },
    )
    answers = _answers(tmp_path, {"core": "zeta-core", "ghost": "zeta-ghost"})
    assert _press(target, answers) == 2
    assert "acme-ghost" in capsys.readouterr().out


def test_third_party_dependency_with_mapped_name_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-core",
                '[dependencies]\nwidget = { package = "acme-widget", version = "1" }\n',
            ),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                {"core": "acme-core", "widget": "acme-widget"}
            ),
        },
    )
    answers = _answers(tmp_path, {"core": "zeta-core", "widget": "zeta-widget"})
    assert _press(target, answers) == 2
    assert "acme-widget" in capsys.readouterr().out


def test_extended_dependency_requires_keep_name(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-core", '[dependencies]\nacme-core-extra = "1"\n'
            ),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert _press(target, _answers(tmp_path, ZETA_MAP)) == 1
    assert 'keep_names = ["acme-core-extra"]' in capsys.readouterr().err


def test_excluded_manifest_dependency_is_still_a_sibling(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-core", '[dependencies]\nacme_core-extra = "1"\n'
            ),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-rules.toml": '[rules]\nextra_exclude_files = ["Cargo.toml"]\n',
        },
    )
    source = _identity(CORE_MAP)
    dest = Identity.from_mapping(_dest_values(), ZETA_MAP)
    check = check_target_keep_names(
        target, source, dest, load_rules(target), frozenset(), ("rust",)
    )
    assert [(i.path, i.token) for i in check.undeclared] == [
        ("Cargo.toml", "acme_core-extra")
    ]


def test_kept_extended_dependency_is_not_reported() -> None:
    source = _identity(CORE_MAP)
    check = check_keep_surfaces(
        (("Cargo.toml", "content", "acme-core-extra"),),
        source,
        ("acme-core-extra",),
        cargo_dependency_names=("acme-core-extra",),
    )
    assert check.undeclared == ()


def test_no_python_layout_check_for_cargo_target(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert _press(target, _answers(tmp_path, ZETA_MAP)) == 0
    assert "layout" not in capsys.readouterr().out


# --- Language selection -----------------------------------------------------


def test_rust_is_a_supported_language_value() -> None:
    assert "rust" in SUPPORTED_LANGUAGES


def test_source_kind_is_cargo_for_a_sole_cargo_target(tmp_path) -> None:
    target = _repo(tmp_path, {"Cargo.toml": _crate("acme-core")})
    found = discover(target, ("rust",))
    assert found.source_kind == "cargo"
    assert found.package_name is None


def test_malformed_root_manifest_exits_2_through_guard(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": "[package\n",
            "pyproject.toml": '[project]\nname = "acme-core"\n',
            "src/acme_core/__init__.py": "",
            "press/press-source.toml": _source_config(),
            "press/press-rules.toml": '[rules]\nlanguages = ["python"]\n',
        },
    )
    assert _press(target, _answers(tmp_path)) == 2
    assert "Cargo.toml" in capsys.readouterr().err
    assert _clean(target)


def test_malformed_workspace_member_exits_2_when_rust_is_active(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nmembers = ["crates/core"]\n',
            "crates/core/Cargo.toml": "[package\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert _press(target, _answers(tmp_path, ZETA_MAP)) == 2
    assert "crates/core" in capsys.readouterr().err
    assert _clean(target)


def test_declared_python_excluding_rust_skips_cargo_identity_checks(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nmembers = ["crates/broken"]\n',
            "crates/broken/Cargo.toml": "[package\n",
            "pyproject.toml": '[project]\nname = "acme-core"\n',
            "src/acme_core/__init__.py": "",
            "press/press-source.toml": _source_config(),
            "press/press-rules.toml": '[rules]\nlanguages = ["python"]\n',
        },
    )
    found = discover(target, ("python",))
    assert found.cargo is None
    assert _press(target, _answers(tmp_path)) == 0


def _python_and_rust(tmp_path: Path, crate: str, project: str) -> Path:
    return _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(crate),
            "pyproject.toml": f'[project]\nname = "{project}"\n',
            "src/lib.rs": "pub fn hi() {}\n",
            "src/acme_core/__init__.py": "",
            "press/press-source.toml": _source_config(CORE_MAP),
            "press/press-rules.toml": '[rules]\nlanguages = ["python", "rust"]\n',
        },
    )


@pytest.mark.parametrize(
    ("crate", "project", "expected", "named"),
    [
        ("acme-core", "acme-core", 0, None),
        ("other-crate", "acme-core", 2, "other-crate"),
        ("acme-core", "other-project", 2, "other_project"),
    ],
)
def test_declared_python_and_rust_checks_each_manifest(
    tmp_path, capsys, crate, project, expected, named
) -> None:
    target = _python_and_rust(tmp_path, crate, project)
    assert _press(target, _answers(tmp_path, ZETA_MAP)) == expected
    if named is not None:
        assert named in capsys.readouterr().out


@pytest.mark.parametrize(
    ("crate", "npm", "expected", "named"),
    [
        ("acme-core", "@acme-org/core", 0, None),
        ("other-crate", "@acme-org/core", 2, "other-crate"),
        ("acme-core", "@acme-org/other", 2, "@acme-org/other"),
    ],
)
def test_declared_rust_and_node_checks_each_manifest(
    tmp_path, capsys, crate, npm, expected, named
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(crate),
            "package.json": json.dumps({"name": npm}),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                CORE_MAP, npm_name="@acme-org/core"
            ),
            "press/press-rules.toml": '[rules]\nlanguages = ["rust", "node"]\n',
        },
    )
    answers = _answers(tmp_path, ZETA_MAP, npm_name="@zeta-org/core")
    assert _press(target, answers) == expected
    if named is not None:
        assert named in capsys.readouterr().out


# --- Without a source config ------------------------------------------------


def test_no_config_single_crate_proposes_table(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/main.rs": "fn main() {}\n",
            "src/bin/acme-tool.rs": "fn main() {}\n",
        },
    )
    assert _press(target) == 2
    out = capsys.readouterr().out
    proposed = tomllib.loads(
        out[out.index("# press/press-source.toml") :].split("\n\n")[0]
    )
    identity = proposed["identity"]
    assert identity["package_name"] == "acme_core"
    assert identity["app_name"] == "acme_core"
    assert identity["cargo_names"] == {
        "acme_core": "acme-core",
        "acme_tool": "acme-tool",
    }
    assert _clean(target)


def test_no_config_library_only_proposes_app_name_from_package(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        {"Cargo.toml": _crate("acme-core"), "src/lib.rs": "pub fn hi() {}\n"},
    )
    assert _press(target) == 2
    out = capsys.readouterr().out
    proposed = tomllib.loads(
        out[out.index("# press/press-source.toml") :].split("\n\n")[0]
    )
    assert proposed["identity"]["app_name"] == "acme_core"


def test_no_config_virtual_workspace_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nmembers = ["crates/core"]\n',
            "crates/core/Cargo.toml": _crate("acme-core"),
            "crates/core/src/lib.rs": "pub fn hi() {}\n",
        },
    )
    assert _press(target) == 2
    assert "virtual workspace" in capsys.readouterr().err
    assert _clean(target)


def test_exit_2_leaves_git_tree_clean(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config({"core": "acme-other"}),
        },
    )
    code = main(
        [
            "--target",
            str(target),
            "--config",
            str(_answers(tmp_path, {"core": "zeta-other"})),
        ]
    )
    assert code == 2
    assert _clean(target)
    assert not (target / "press" / "press-receipt.toml").exists()


# --- Identity-table refusals ------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new"), [("acme_core", "zeta-core"), ("acme", "zeta-core")]
)
def test_hyphen_destination_for_unhyphenated_source_is_explained(old, new) -> None:
    source = _identity({"core": old}, package_name=old.replace("-", "_"))
    dest = Identity.from_mapping(
        _dest_values(package_name=new.replace("-", "_")), {"core": new}
    )
    problem = cargo_identity_problem(source, dest)
    assert problem is not None
    assert "cannot tell" in problem


def test_rebrand_refuses_half_declared_table(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert _press(target, _answers(tmp_path)) == 2
    assert "cargo_names" in capsys.readouterr().err


def test_equal_source_values_must_stay_equal_in_answers(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    answers = _answers(tmp_path, ZETA_MAP, repo_name="other-repo")
    assert _press(target, answers) == 2
    err = capsys.readouterr().err
    assert "repo_name" in err
    assert "keep them equal" in err


# --- press verify ------------------------------------------------------------


def test_verify_preflight_reports_cargo_problems(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", '[[bin]]\nname = "other-tool"\n')
            + 'path = "src/main.rs"\n',
            "src/main.rs": "fn main() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    assert verify_command(["--target", str(target)]) == 2
    assert "other-tool" in capsys.readouterr().err
    assert _clean(target)


def test_verify_refuses_invalid_source_table(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config({"core": "acme-other"}),
        },
    )
    assert verify_command(["--target", str(target)]) == 2
    assert "underscore form" in capsys.readouterr().err


def test_verify_does_not_fail_on_synthetic_destination_without_table(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/main.rs": "fn main() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    verify_command(["--target", str(target)])
    err = capsys.readouterr().err
    assert "declared on both" not in err
    assert "neither discoverable nor present" not in err
    assert "WHOLLY undiscoverable" not in err


def test_verify_ignores_cargo_when_rust_is_not_declared(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nmembers = ["crates/broken"]\n',
            "crates/broken/Cargo.toml": "[package\n",
            "pyproject.toml": '[project]\nname = "acme-core"\n',
            "src/acme_core/__init__.py": "",
            "press/press-source.toml": _source_config(),
            "press/press-rules.toml": '[rules]\nlanguages = ["python"]\n',
        },
    )
    assert verify_command(["--target", str(target)]) == 0
    assert "crates/broken" not in capsys.readouterr().err


# --- Helpers ----------------------------------------------------------------


def test_table_hint_merges_spellings_and_lowercases_roles(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("Acme-Core", '[lib]\nname = "Acme_Core"\n'),
            "src/lib.rs": "pub fn hi() {}\n",
        },
    )
    hint = cargo_table_hint(read_cargo_facts(target))
    assert tomllib.loads(hint)["identity"]["cargo_names"] == {"acme_core": "Acme-Core"}


def test_warnings_are_empty_with_a_map(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {"Cargo.toml": _crate("acme-core"), "src/lib.rs": "pub fn hi() {}\n"},
    )
    assert cargo_warnings(target, _identity(CORE_MAP), load_rules(target)) == []


# --- Fix round 1 ------------------------------------------------------------


def test_verify_accepts_unmapped_crate_related_to_unchanged_owner(tmp_path) -> None:
    values = {
        "package_name": "tools_pkg",
        "repo_name": "tools-repo",
        "app_name": "tools_app",
        "owner": "acme",
    }
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-tools"),
            "src/lib.rs": "pub fn hi() {}\n",
            "README.md": "tools_pkg tools_app tools-repo acme\n",
            "press/press-source.toml": _source_config(**values),
        },
        repo_name="tools-repo",
        owner="acme",
    )
    answers = _answers(
        tmp_path,
        package_name="zeta_pkg",
        repo_name="tools-repo",
        app_name="zeta_app",
        owner="acme",
    )
    assert verify_command(["--target", str(target)]) == 0
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert 'name = "acme-tools"' in (target / "Cargo.toml").read_text()
    assert verify_command(["--target", str(target)]) == 0


@pytest.mark.parametrize(
    ("package", "new_package"),
    [("acme_core", "acme_core"), ("other_pkg", "zeta_pkg")],
)
def test_identifier_left_behind_exits_2_before_any_write(
    tmp_path, capsys, package, new_package
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "src/main.rs": "fn main() { acme_core::hi(); }\n",
            "press/press-source.toml": _source_config(
                package_name=package, app_name="tool_app"
            ),
        },
    )
    answers = _answers(tmp_path, package_name=new_package, app_name="zeta_app")
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert "[identity.cargo_names]" in capsys.readouterr().out
    assert _clean(target)
    assert not (target / "press" / "press-receipt.toml").exists()


def test_binary_only_crate_without_identifier_text_continues(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/main.rs": "fn main() {}\n",
            "press/press-source.toml": _source_config(
                package_name="other_pkg", app_name="tool_app"
            ),
        },
    )
    answers = _answers(tmp_path, package_name="zeta_pkg", app_name="zeta_app")
    assert _press(target, answers) == 0


def _nameless_node_target(tmp_path: Path) -> Path:
    return _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("tools-helper"),
            "src/lib.rs": "pub fn hi() {}\n",
            "package.json": json.dumps({"private": True, "bin": {"real-cli": "x.js"}}),
            "README.md": "acme_core acme-core declared-cli\n",
            "press/press-source.toml": _source_config(cli_name="declared-cli"),
        },
    )


def test_sole_cargo_keeps_declared_cli_check_for_nameless_package_json(
    tmp_path, capsys
) -> None:
    target = _nameless_node_target(tmp_path)
    assert _press(target, _answers(tmp_path, cli_name="zeta-cli")) == 2
    assert "cli_name" in capsys.readouterr().out
    assert verify_command(["--target", str(target)]) == 2
    assert "cli_name" in capsys.readouterr().err


def test_ignored_node_manifest_is_never_read_as_identity(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "package.json": json.dumps({"name": "other", "bin": {"real": "x.js"}}),
            "press/press-rules.toml": '[rules]\nlanguages = ["rust"]\n',
        },
    )
    found = discover(target, ("rust",), ignored=("node",))
    assert found.node_checked is False
    assert found.source_kind == "cargo"


def test_dependency_evidence_follows_checked_languages(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-core", '[dependencies]\nacme_core-extra = "1"\n'
            ),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-rules.toml": '[rules]\nextra_exclude_files = ["Cargo.toml"]\n',
        },
    )
    source = _identity(CORE_MAP)
    dest = Identity.from_mapping(_dest_values(), ZETA_MAP)
    check = check_target_keep_names(
        target, source, dest, load_rules(target), frozenset(), ("python",)
    )
    assert check.undeclared == ()


def test_warning_uses_changing_values_when_destination_is_known(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {"Cargo.toml": _crate("acme-tools"), "src/lib.rs": "pub fn hi() {}\n"},
    )
    source = _identity(owner="acme")
    rules = load_rules(target)
    assert cargo_warnings(target, source, rules) == []
    dest = Identity.from_mapping(_dest_values(owner="acme"))
    assert "acme-tools" in cargo_warnings(target, source, rules, dest)[0]


# --- Fix round 2 ------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "rule"),
    [
        ("old.md", '[[remove]]\nfile = "old.md"\nreason = "template only"\n'),
        (
            "history/old.md",
            '[[remove]]\ndir = "history"\nreason = "template only"\n',
        ),
    ],
)
def test_identifier_only_in_removed_path_is_not_surface(tmp_path, rel, rule) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/main.rs": "fn main() {}\n",
            rel: "acme_core\n",
            "press/press-source.toml": _source_config(
                package_name="other_pkg", app_name="tool_app"
            ),
            "press/press-rules.toml": rule,
        },
    )
    answers = _answers(tmp_path, package_name="zeta_pkg", app_name="zeta_app")
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert 'name = "zeta-core"' in (target / "Cargo.toml").read_text()
    assert not (target / rel).exists()


@pytest.mark.parametrize("field", ["cli_name", "npm_name"])
def test_rename_keeping_rust_identifier_continues(tmp_path, field) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/lib.rs": "pub fn hi() {}\n",
            "src/main.rs": "fn main() { acme_core::hi(); }\n",
            "press/press-source.toml": _source_config(
                package_name="other_pkg",
                repo_name="tools-repo",
                app_name="tool_app",
                **{field: "acme-core"},
            ),
        },
        repo_name="tools-repo",
    )
    answers = _answers(
        tmp_path,
        package_name="zeta_pkg",
        repo_name="zeta-repo",
        app_name="zeta_app",
        **{field: "acme_core"},
    )
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert 'name = "acme_core"' in (target / "Cargo.toml").read_text()
    assert "acme_core::hi()" in (target / "src" / "main.rs").read_text()


# --- Final review: judge rows, unloadable hints, env-prefix spans ------------

WORKSPACE_ROOT = '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n'
ROOT_PACKAGE = (
    '[package]\nname = "acme-root"\nversion = "0.1.0"\n'
    f'{AUTHOR}\n[workspace]\nmembers = ["crates/*"]\n'
)


def _prefix_files(root: str, **source: str) -> dict[str, str]:
    files = {
        "Cargo.toml": root,
        "crates/acme/Cargo.toml": _crate(
            "acme", '\n[dependencies]\nacme-core = { path = "../acme-core" }\n'
        ),
        "crates/acme/src/main.rs": "fn main() { acme_core::hi(); }\n",
        "crates/acme-core/Cargo.toml": _crate("acme-core"),
        "crates/acme-core/src/lib.rs": "pub fn hi() {}\n",
        "press/press-source.toml": _source_config(**source),
    }
    if root == ROOT_PACKAGE:
        files["src/lib.rs"] = "pub fn root() {}\n"
    return files


@pytest.mark.parametrize("root", [WORKSPACE_ROOT, ROOT_PACKAGE])
def test_no_map_prefix_workspace_continues(tmp_path, root) -> None:
    target = _repo(
        tmp_path,
        _prefix_files(root, package_name="acme", repo_name="acme", app_name="acme"),
        repo_name="acme",
    )
    answers = _answers(tmp_path, package_name="zeta", repo_name="zeta", app_name="zeta")
    assert _press(target, answers) == 0


def test_no_map_repo_only_prefix_continues(tmp_path) -> None:
    target = _repo(
        tmp_path,
        _prefix_files(
            WORKSPACE_ROOT,
            package_name="other_pkg",
            repo_name="acme",
            app_name="tool_app",
        ),
        repo_name="acme",
    )
    answers = _answers(
        tmp_path, package_name="zeta_pkg", repo_name="zeta", app_name="zeta_app"
    )
    assert _press(target, answers) == 0


def test_no_map_app_only_prefix_splits_the_spellings_and_exits_2(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        _prefix_files(
            WORKSPACE_ROOT,
            package_name="other_pkg",
            repo_name="other-repo",
            app_name="acme",
        ),
        repo_name="other-repo",
    )
    answers = _answers(
        tmp_path, package_name="zeta_pkg", repo_name="zeta-repo", app_name="zeta"
    )
    assert _press(target, answers) == 2
    assert "acme-core" in capsys.readouterr().out
    assert _clean(target)


def test_no_map_rewrite_cargo_cannot_use_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-tools"),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(
                package_name="other_pkg",
                repo_name="other-repo",
                app_name="tool_app",
                owner="acme",
            ),
        },
        repo_name="other-repo",
        owner="acme",
    )
    answers = _answers(
        tmp_path,
        package_name="zeta_pkg",
        repo_name="zeta-repo",
        app_name="zeta_app",
        owner="9zeta",
    )
    assert _press(target, answers) == 2
    assert "acme-tools" in capsys.readouterr().out
    assert _clean(target)


def _maturin_files(source: str) -> dict[str, str]:
    return {
        "Cargo.toml": _crate("acme-widget", '[lib]\nname = "_acme_widget"\n'),
        "pyproject.toml": '[project]\nname = "acme-widget"\nversion = "0.1.0"\n',
        "src/lib.rs": "pub fn hi() {}\n",
        "src/acme_widget/__init__.py": "",
        "press/press-rules.toml": '[rules]\nlanguages = ["python", "rust"]\n',
        "press/press-source.toml": source,
    }


def test_no_map_leading_underscore_lib_continues(tmp_path) -> None:
    target = _repo(
        tmp_path,
        _maturin_files(
            _source_config(package_name="acme_widget", repo_name="acme-widget")
        ),
        repo_name="acme-widget",
    )
    answers = _answers(tmp_path, package_name="zeta_widget", repo_name="zeta-widget")
    assert _press(target, answers) == 0


def test_table_hint_never_prints_an_unloadable_table(tmp_path) -> None:
    target = _repo(tmp_path, _maturin_files(_source_config()))
    hint = cargo_table_hint(read_cargo_facts(target))
    assert "[identity.cargo_names]" not in hint
    assert "_acme_widget" in hint
    assert "cannot represent" in hint


def test_declared_table_refusal_names_the_underscore_limit(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        _maturin_files(
            _source_config(
                {"widget": "acme-widget"},
                package_name="acme_widget",
                repo_name="acme-widget",
            )
        ),
        repo_name="acme-widget",
    )
    answers = _answers(
        tmp_path,
        {"widget": "zeta-widget"},
        package_name="zeta_widget",
        repo_name="zeta-widget",
    )
    assert _press(target, answers) == 2
    out = capsys.readouterr().out
    assert "_acme_widget" in out
    assert "cannot represent" in out
    assert _clean(target)


def test_role_equal_to_app_name_keeps_env_prefix(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme"),
            "src/main.rs": 'fn main() { let _ = std::env::var("ACME_HOME"); }\n',
            "press/press-source.toml": _source_config(
                {"acme": "acme"},
                package_name="acme",
                repo_name="acme",
                app_name="acme",
            ),
        },
        repo_name="acme",
    )
    answers = _answers(
        tmp_path,
        {"acme": "zeta"},
        package_name="zeta",
        repo_name="zeta",
        app_name="zeta",
    )
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert "ZETA_HOME" in (target / "src/main.rs").read_text()
    _git(target, "remote", "set-url", "origin", "https://github.com/zeta-org/zeta")
    assert verify_command(["--target", str(target)]) == 0


def test_accepted_discovery_with_bin_equal_to_app_keeps_env_prefix(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-widget", '\n[[bin]]\nname = "acme"\npath = "src/main.rs"\n'
            ),
            "src/main.rs": 'fn main() { let _ = std::env::var("ACME_TOKEN"); }\n',
        },
        repo_name="acme-repo",
    )
    answers = _answers(
        tmp_path,
        {"acme": "zeta", "acme_widget": "zeta-widget"},
        package_name="zeta_widget",
        repo_name="zeta-repo",
        app_name="zeta",
    )
    argv = ["--target", str(target), "--config", str(answers), "--accept-discovery"]
    assert main(argv) == 0
    assert "ZETA_TOKEN" in (target / "src/main.rs").read_text()


def test_real_sibling_of_a_role_is_still_refused(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core"),
            "src/main.rs": 'fn main() { let _ = std::env::var("ACME_CORE_HOME"); }\n',
            "press/press-source.toml": _source_config(CORE_MAP, app_name="acme"),
        },
    )
    answers = _answers(tmp_path, ZETA_MAP, app_name="zeta")
    assert main(["--target", str(target), "--config", str(answers)]) == 1
    assert "ACME_CORE_HOME" in capsys.readouterr().err
    assert _clean(target)


def test_destination_equal_to_third_party_dependency_exits_2(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", '\n[dependencies]\npadkit = "1"\n'),
            "src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP),
        },
    )
    answers = _answers(tmp_path, {"core": "padkit"}, package_name="padkit")
    assert main(["--target", str(target), "--config", str(answers)]) == 2
    assert "padkit" in capsys.readouterr().out
    assert _clean(target)


def _bin_env_target(tmp_path: Path, cargo: dict[str, str]) -> Path:
    return _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "acme-core", '\n[[bin]]\nname = "acme-cli"\npath = "src/main.rs"\n'
            ),
            "src/main.rs": "fn main() {}\n",
            "tests/cli.rs": 'const BIN: &str = env!("CARGO_BIN_EXE_acme-cli");\n',
            "press/press-source.toml": _source_config(cargo),
        },
    )


def test_bin_env_token_follows_a_changed_name(tmp_path) -> None:
    target = _bin_env_target(tmp_path, {"cli": "acme-cli", **CORE_MAP})
    answers = _answers(tmp_path, {"cli": "zeta-cli", **ZETA_MAP})
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert "CARGO_BIN_EXE_zeta-cli" in (target / "tests/cli.rs").read_text()


def test_bin_env_token_of_an_unchanged_name_needs_no_keep_entry(tmp_path) -> None:
    target = _bin_env_target(tmp_path, {"cli": "acme-cli", **CORE_MAP})
    answers = _answers(tmp_path, {"cli": "acme-cli", **ZETA_MAP})
    assert main(["--target", str(target), "--config", str(answers)]) == 0
    assert "CARGO_BIN_EXE_acme-cli" in (target / "tests/cli.rs").read_text()


@pytest.mark.parametrize("entry", ["CARGO_BIN_EXE_acme-cli", "CARGO_BIN_EXE_acme_cli"])
def test_bin_env_token_of_a_declared_name_cannot_be_kept(entry) -> None:
    cargo = {"cli": "acme-cli", **CORE_MAP}
    source = _identity(cargo)
    dest = Identity.from_mapping(_dest_values(), {"cli": "zeta-cli", **ZETA_MAP})
    with pytest.raises(ValidationError, match="CARGO_BIN_EXE"):
        validate_keep_names([entry], source, dest)
    assert sibling_guidance(entry, (0, 5), source) is None


def test_bin_env_keep_entry_stays_valid_without_a_table() -> None:
    source = _identity()
    dest = Identity.from_mapping(_dest_values())
    validate_keep_names(["CARGO_BIN_EXE_acme-cli"], source, dest)


# --- Final review: a content-only row must not split a crate from its path ---

_OWNER_ONLY = {
    "package_name": "other_pkg",
    "repo_name": "other-repo",
    "app_name": "tool_app",
    "owner": "acme",
}
_OWNER_ONLY_DEST = {
    "package_name": "zeta_pkg",
    "repo_name": "zeta-repo",
    "app_name": "zeta_app",
    "owner": "zeta",
}


def test_no_map_content_only_row_cannot_split_crate_directory(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        _prefix_files(WORKSPACE_ROOT, **_OWNER_ONLY),
        repo_name="other-repo",
        owner="acme",
    )
    assert _press(target, _answers(tmp_path, **_OWNER_ONLY_DEST)) == 2
    assert "acme-core" in capsys.readouterr().out
    assert _clean(target)


def test_no_map_content_only_row_cannot_split_claimed_bin(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "tool-pkg",
                '\n[[bin]]\nname = "acme-cli"\npath = "src/bin/acme-cli.rs"\n',
            ),
            "src/bin/acme-cli.rs": "fn main() {}\n",
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    assert _press(target, _answers(tmp_path, **_OWNER_ONLY_DEST)) == 2
    assert "acme-cli" in capsys.readouterr().out
    assert _clean(target)


def test_no_map_owner_merged_into_a_path_row_still_continues(tmp_path) -> None:
    source = {**_OWNER_ONLY, "repo_name": "acme"}
    target = _repo(
        tmp_path,
        _prefix_files(WORKSPACE_ROOT, **source),
        repo_name="acme",
        owner="acme",
    )
    answers = _answers(tmp_path, **{**_OWNER_ONLY_DEST, "repo_name": "zeta"})
    assert _press(target, answers) == 0


# --- P15-T08: judge the paths Cargo manifests declare ---------------------------

_DECLARED_SPLITS = {
    "lib": ('\n[lib]\npath = "lib/acme-x.rs"\n', "lib/acme-x.rs", "pub fn hi() {}\n"),
    "bin": (
        '\n[[bin]]\nname = "tool"\npath = "tools/acme-x.rs"\n',
        "tools/acme-x.rs",
        "fn main() {}\n",
    ),
    "test": (
        '\n[[test]]\nname = "smoke"\npath = "checks/acme-x.rs"\n',
        "checks/acme-x.rs",
        "",
    ),
    "example": (
        '\n[[example]]\nname = "demo"\npath = "demos/acme-x.rs"\n',
        "demos/acme-x.rs",
        "fn main() {}\n",
    ),
    "bench": (
        '\n[[bench]]\nname = "speed"\npath = "speed/acme-x.rs"\nharness = false\n',
        "speed/acme-x.rs",
        "fn main() {}\n",
    ),
    "build": (
        'build = "tools/acme-build.rs"\n',
        "tools/acme-build.rs",
        "fn main() {}\n",
    ),
}


def _press_for_real(target: Path, answers: Path) -> int:
    return main(["--target", str(target), "--config", str(answers)])


def _assert_refused_untouched(target: Path, code: int) -> None:
    assert code == 2
    assert not (target / RECEIPT_REL).exists()
    assert _clean(target)


@pytest.mark.parametrize("kind", sorted(_DECLARED_SPLITS))
def test_owner_row_cannot_split_declared_target_path(tmp_path, capsys, kind) -> None:
    extra, rel, body = _DECLARED_SPLITS[kind]
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", extra),
            "src/lib.rs": "pub fn hi() {}\n",
            rel: body,
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, **_OWNER_ONLY_DEST))
    _assert_refused_untouched(target, code)
    assert rel in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "source", "dest"),
    [("owner", "acme", "zeta"), ("author", "acme", "zeta")],
)
def test_unrelated_crate_path_split_is_refused(
    tmp_path, capsys, field, source, dest
) -> None:
    identity = {**_OWNER_ONLY, "owner": "other-org", field: source}
    answers = {**_OWNER_ONLY_DEST, "owner": "zeta-org", field: dest}
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n',
            "crates/app/Cargo.toml": _crate(
                "plain-app", '\n[dependencies]\nhelper = { path = "../acme-x" }\n'
            ),
            "crates/app/src/main.rs": "fn main() {}\n",
            "crates/acme-x/Cargo.toml": _crate("helper"),
            "crates/acme-x/src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(**identity),
        },
        repo_name="other-repo",
        owner=identity["owner"],
    )
    code = _press_for_real(target, _answers(tmp_path, **answers))
    _assert_refused_untouched(target, code)
    assert "../acme-x" in capsys.readouterr().out


def test_declared_table_cannot_split_declared_path(tmp_path, capsys) -> None:
    identity = {"repo_name": "other-repo", "app_name": "tool_app", "owner": "acme"}
    moved = {"repo_name": "zeta-repo", "app_name": "zeta_app", "owner": "zeta"}
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("acme-core", '\n[lib]\npath = "lib/acme-x.rs"\n'),
            "lib/acme-x.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(CORE_MAP, **identity),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, ZETA_MAP, **moved))
    _assert_refused_untouched(target, code)
    assert "lib/acme-x.rs" in capsys.readouterr().out


def test_split_in_a_path_dependency_of_a_plain_package_is_refused(
    tmp_path, capsys
) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate(
                "tool-pkg", '\n[dependencies]\nhelper = { path = "vendor/helper" }\n'
            ),
            "src/lib.rs": "pub fn hi() {}\n",
            "vendor/helper/Cargo.toml": _crate(
                "helper", '\n[lib]\npath = "lib/acme-x.rs"\n'
            ),
            "vendor/helper/lib/acme-x.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, **_OWNER_ONLY_DEST))
    _assert_refused_untouched(target, code)
    assert "lib/acme-x.rs" in capsys.readouterr().out


def test_glob_member_split_is_refused(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": '[workspace]\nresolver = "2"\nmembers = ["crates/acme-*"]\n',
            "crates/acme-x/Cargo.toml": _crate("helper"),
            "crates/acme-x/src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, **_OWNER_ONLY_DEST))
    _assert_refused_untouched(target, code)
    assert "crates/acme-*" in capsys.readouterr().out


def test_keep_name_protects_a_declared_path(tmp_path) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("tool-pkg", '\n[lib]\npath = "lib/acme-x.rs"\n'),
            "lib/acme-x.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
            "press/press-rules.toml": '[rules]\nkeep_names = ["acme-x"]\n',
        },
        repo_name="other-repo",
        owner="acme",
    )
    answers = _answers(tmp_path, **_OWNER_ONLY_DEST)
    assert _press_for_real(target, answers) == 0
    assert 'path = "lib/acme-x.rs"' in (target / "Cargo.toml").read_text()
    assert (target / "lib/acme-x.rs").is_file()


def test_bin_env_token_cannot_leave_an_auto_discovered_bin(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": _crate("plain-pkg"),
            "src/lib.rs": "pub fn hi() {}\n",
            "src/bin/acme-cli.rs": "fn main() {}\n",
            "tests/cli.rs": 'const BIN: &str = env!("CARGO_BIN_EXE_acme-cli");\n',
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, **_OWNER_ONLY_DEST))
    _assert_refused_untouched(target, code)
    assert "CARGO_BIN_EXE_acme-cli" in capsys.readouterr().out


def test_default_member_split_is_refused(tmp_path, capsys) -> None:
    target = _repo(
        tmp_path,
        {
            "Cargo.toml": (
                '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n'
                'default-members = ["crates/acme-x"]\n'
            ),
            "crates/acme-x/Cargo.toml": _crate("helper"),
            "crates/acme-x/src/lib.rs": "pub fn hi() {}\n",
            "press/press-source.toml": _source_config(**_OWNER_ONLY),
        },
        repo_name="other-repo",
        owner="acme",
    )
    code = _press_for_real(target, _answers(tmp_path, **_OWNER_ONLY_DEST))
    _assert_refused_untouched(target, code)
    assert "crates/acme-x" in capsys.readouterr().out
