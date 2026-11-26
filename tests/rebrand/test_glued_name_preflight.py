"""P19-TS01: pre-write glued-name preflight across all target languages (scope (i))."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_selected_rules
from template_press.rebrand.substitutions import check_target_keep_names
from template_press.rebrand.synthesize import synthesize_dest
from template_press.rebrand.verify_cli import verify_command
from template_press.rebrand.verify_config import load_verify_config

from .conftest import DEST, SOURCE, make_target, write_answers_file

ACME_SOURCE = Identity(
    package_name="acme_widget",
    repo_name="acme-widget",
    app_name="acme",
    author="Acme Author",
    email="acme@example.test",
    owner="acmelabs",
    display_name="Acme Widget",
)

ZETA_DEST = Identity(
    package_name="zeta_tool",
    repo_name="zeta-tool",
    app_name="zeta",
    author="Zeta Author",
    email="zeta@example.test",
    owner="zetalabs",
    display_name="Zeta Tool",
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
    lines = [f"[{table}]"]
    for key, value in identity.as_dict_prompted().items():
        lines.append(f'{key} = "{value}"')
    if identity.cargo_names:
        lines.append(f"\n[{table}.cargo_names]")
        for role, name in identity.cargo_names:
            lines.append(f'{role} = "{name}"')
    return "\n".join(lines) + "\n"


def _init_repo(
    repo: Path,
    source: Identity,
    files: dict[str, str],
    rules_text: str | None = None,
) -> Path:
    (repo / "press").mkdir(parents=True, exist_ok=True)
    (repo / "press" / "press-source.toml").write_text(
        _toml_identity(source, "identity"), encoding="utf-8"
    )
    if rules_text is not None:
        (repo / "press" / "press-rules.toml").write_text(rules_text, encoding="utf-8")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.test")
    _git(repo, "config", "user.name", "CI")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        f"https://github.com/{source.owner}/{source.repo_name}.git",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed fixture")
    return repo


def _python_files(
    source: Identity, extra: dict[str, str] | None = None
) -> dict[str, str]:
    files = {
        "pyproject.toml": (
            "[project]\n"
            f'name = "{source.package_name}"\n'
            'version = "0.1.0"\n'
            f'authors = [{{ name = "{source.author}", email = "{source.email}" }}]\n'
            "[project.scripts]\n"
            f'{source.app_name} = "{source.package_name}:main"\n'
        ),
        f"src/{source.package_name}/__init__.py": (
            f'"""{source.display_name or source.package_name}."""\n'
            "def main() -> int:\n    return 0\n"
        ),
        "README.md": f"# {source.display_name or source.repo_name}\n",
    }
    if extra:
        files.update(extra)
    return files


def _ts_files(source: Identity, extra: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "package.json": json.dumps(
            {
                "name": source.repo_name,
                "version": "0.1.0",
                "author": f"{source.author} <{source.email}>",
                "bin": {source.app_name: "./dist/cli.js"},
                "repository": f"https://github.com/{source.owner}/{source.repo_name}",
            },
            indent=2,
        )
        + "\n",
        "src/index.ts": f"// {source.display_name or source.repo_name}\nexport const ok = true;\n",
    }
    if extra:
        files.update(extra)
    return files


def _rust_files(
    source: Identity, extra: dict[str, str] | None = None
) -> dict[str, str]:
    crate_name = dict(source.cargo_names)["core"]
    files = {
        "Cargo.toml": (
            "[package]\n"
            f'name = "{crate_name}"\n'
            'version = "0.1.0"\n'
            'edition = "2021"\n'
            f'authors = ["{source.author} <{source.email}>"]\n'
            f'repository = "https://github.com/{source.owner}/{source.repo_name}"\n'
        ),
        "src/lib.rs": f"// {source.display_name or crate_name}\npub fn hi() {{}}\n",
    }
    if extra:
        files.update(extra)
    return files


def _write_answers(tmp_path: Path, dest: Identity) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "press-answers.toml"
    path.write_text(_toml_identity(dest, "answers"), encoding="utf-8")
    return path


def test_python_glued_display_name_refused_before_writes(
    tmp_path: Path, capsys
) -> None:
    repo = _init_repo(
        tmp_path / "py-glued",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"src/acme_widget/config.py": "class AcmeWidgetConfig:\n    pass\n"},
        ),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert (
        'src/acme_widget/config.py: AcmeWidgetConfig extends display_name "Acme Widget"'
        in err
    )
    assert 'rewrite it:  substring_rewrite_fields = ["display_name_pascal"]' in err
    assert 'or keep it:  keep_names = ["AcmeWidgetConfig"]' in err


def test_baml_glued_client_name_refused_with_guidance(tmp_path: Path, capsys) -> None:
    repo = _init_repo(
        tmp_path / "baml-glued",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {
                "baml_src/main.baml": (
                    'client<llm> AcmeWidgetClient {\n  provider "openai"\n}\n'
                )
            },
        ),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert (
        'baml_src/main.baml: AcmeWidgetClient extends display_name "Acme Widget"' in err
    )
    assert 'rewrite it:  substring_rewrite_fields = ["display_name_pascal"]' in err
    assert 'or keep it:  keep_names = ["AcmeWidgetClient"]' in err


def test_typescript_glued_app_name_refused_before_writes(
    tmp_path: Path, capsys
) -> None:
    repo = _init_repo(
        tmp_path / "ts-glued",
        ACME_SOURCE,
        _ts_files(ACME_SOURCE, {"src/config.ts": "export const acmeConfig = 1;\n"}),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert 'src/config.ts: acmeConfig extends app_name "acme"' in err
    assert 'rewrite it:  substring_rewrite_fields = ["app_name"]' in err
    assert 'or keep it:  keep_names = ["acmeConfig"]' in err


def test_rust_glued_display_name_refused_before_writes(tmp_path: Path, capsys) -> None:
    rust_source = replace(
        ACME_SOURCE,
        package_name="acme_core",
        repo_name="acme-core",
        app_name="acme_core",
        cargo_names=(("core", "acme-core"),),
    )
    rust_dest = replace(
        ZETA_DEST,
        package_name="zeta_core",
        repo_name="zeta-core",
        app_name="zeta_core",
        cargo_names=(("core", "zeta-core"),),
    )
    repo = _init_repo(
        tmp_path / "rs-glued",
        rust_source,
        _rust_files(
            rust_source,
            {"src/lib.rs": "// Acme Widget\npub struct AcmeWidgetClient;\n"},
        ),
    )
    answers = _write_answers(tmp_path, rust_dest)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert 'src/lib.rs: AcmeWidgetClient extends display_name "Acme Widget"' in err


def test_p17_source_form_gap_underscore_app_name_refused(
    tmp_path: Path, capsys
) -> None:
    zapp_source = replace(ACME_SOURCE, app_name="zapp")
    zapp_dest = replace(ZETA_DEST, app_name="kapp")
    repo = _init_repo(
        tmp_path / "zapp-glued",
        zapp_source,
        _python_files(zapp_source, {"src/acme_widget/util.py": 'TAG = "_zapp_"\n'}),
    )
    answers = _write_answers(tmp_path, zapp_dest)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert "_zapp_" in err


def test_camel_display_name_omits_rewrite_suggestion(tmp_path: Path, capsys) -> None:
    repo = _init_repo(
        tmp_path / "camel-glued",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"src/acme_widget/client.py": "acmeWidgetClient = object()\n"},
        ),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)

    code = main(["--target", str(repo), "--config", str(answers)])
    err = capsys.readouterr().err

    assert code == 1
    assert not (repo / RECEIPT_REL).exists()
    assert _git(repo, "status", "--porcelain") == ""
    assert "acmeWidgetClient" in err
    assert "rewrite it:" not in err
    assert 'keep_names = ["acmeWidgetClient"]' in err


def test_negative_cases_not_refused(tmp_path: Path) -> None:
    # 1. Rewritten by substring_rewrite_fields
    repo_sub = _init_repo(
        tmp_path / "sub",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"src/acme_widget/config.py": "acmeConfig = 1\n"},
        ),
        rules_text='[rules]\nsubstring_rewrite_fields = ["app_name"]\n',
    )
    answers = _write_answers(tmp_path, ZETA_DEST)
    assert main(["--target", str(repo_sub), "--config", str(answers)]) == 0
    assert (repo_sub / RECEIPT_REL).exists()

    # 2. Covered by keep_names
    repo_keep = _init_repo(
        tmp_path / "keep",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"src/acme_widget/config.py": "class AcmeWidgetConfig:\n    pass\n"},
        ),
        rules_text='[rules]\nkeep_names = ["AcmeWidgetConfig"]\n',
    )
    assert main(["--target", str(repo_keep), "--config", str(answers)]) == 0

    # 3. Covered by [[verify.ignore]] (and verify exits 0 on the same target)
    ign_source = replace(ACME_SOURCE, display_name="Sunburst Studio")
    ign_dest = replace(ZETA_DEST, display_name="Moonbeam Labs")
    repo_ign = _init_repo(
        tmp_path / "ign",
        ign_source,
        _python_files(
            ign_source,
            {"src/acme_widget/config.py": "class SunburstStudioConfig:\n    pass\n"},
        ),
        rules_text=(
            "[[verify.ignore]]\n"
            'field = "display_name"\n'
            'file = "src/acme_widget/config.py"\n'
            'anchor = "SunburstStudioConfig"\n'
            "line = 1\n"
            'reason = "intentional historical type name"\n'
        ),
    )
    ign_answers = _write_answers(tmp_path / "ign-ans", ign_dest)
    assert verify_command(["--target", str(repo_ign)]) == 0
    assert (
        main(["--target", str(repo_ign), "--config", str(ign_answers), "--dry-run"])
        == 0
    )

    # 4. Unrelated word ("pressure" for app_name="press")
    repo_word = make_target(tmp_path / "word", layout="src")
    (repo_word / "press").mkdir()
    (repo_word / "press" / "press-source.toml").write_text(
        _toml_identity(SOURCE, "identity"), encoding="utf-8"
    )
    _git(repo_word, "add", "-A")
    _git(repo_word, "commit", "-q", "-m", "add source config")
    dest_answers = write_answers_file(tmp_path / "word", DEST)
    assert main(["--target", str(repo_word), "--config", str(dest_answers)]) == 0


def test_scope_i_property_clean_verify_never_refused_by_glued_preflight(
    tmp_path: Path,
) -> None:
    """Whenever pre-press `press verify` exits 0, the glued preflight never refuses."""
    rust_source = replace(
        ACME_SOURCE,
        package_name="acme_core",
        repo_name="acme-core",
        app_name="acme_core",
        cargo_names=(("core", "acme-core"),),
    )
    fixtures: list[tuple[Path, Identity, tuple[str, ...]]] = [
        (
            _init_repo(
                tmp_path / "corp-py",
                ACME_SOURCE,
                _python_files(ACME_SOURCE),
            ),
            ACME_SOURCE,
            ("python",),
        ),
        (
            _init_repo(
                tmp_path / "corp-ts",
                ACME_SOURCE,
                _ts_files(ACME_SOURCE),
            ),
            ACME_SOURCE,
            ("node",),
        ),
        (
            _init_repo(
                tmp_path / "corp-rs",
                rust_source,
                _rust_files(rust_source),
            ),
            rust_source,
            ("rust",),
        ),
        (
            _init_repo(
                tmp_path / "corp-press",
                SOURCE,
                _python_files(
                    SOURCE,
                    {
                        "README.md": (
                            "# demo-widget\n"
                            "Compress the archive; do not let pressure rise.\n"
                            "Run `press --help` for demolabs/demo-widget.\n"
                        ),
                        "src/demo_widget/cli.py": (
                            'VAL = "_PRESS_COMPLETE"\nCFG = "press_config.toml"\n'
                        ),
                    },
                ),
            ),
            SOURCE,
            ("python",),
        ),
        (
            _init_repo(
                tmp_path / "corp-verify-ignore",
                ACME_SOURCE,
                _python_files(
                    ACME_SOURCE,
                    {"legacy/keep.py": "class AcmeWidgetLegacy:\n    pass\n"},
                ),
                rules_text='[rules]\nverify_ignore = ["legacy"]\n',
            ),
            ACME_SOURCE,
            ("python",),
        ),
    ]
    for repo, source, langs in fixtures:
        assert verify_command(["--target", str(repo)]) == 0
        rules = load_selected_rules(repo).rules
        verify_cfg = load_verify_config(repo)
        dest = synthesize_dest(source)
        check = check_target_keep_names(
            repo,
            source,
            dest,
            rules,
            frozenset(),
            langs,
            verify_config=verify_cfg,
        )
        assert check.undeclared == (), (
            f"{repo.name} falsely refused: {check.undeclared}"
        )
