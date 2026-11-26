"""P19-TS04: whole-directory [[regenerate]] dir support."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

import pytest

from template_press.rebrand.check_tools import check_tools_command
from template_press.rebrand.clean_cli import clean_command
from template_press.rebrand.cli import main
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import requires_symlink
from .test_glued_name_preflight import (
    ACME_SOURCE,
    ZETA_DEST,
    _git,
    _init_repo,
    _python_files,
    _write_answers,
)
from .test_package_path_placeholders import NOVA_DEST

PY = sys.executable


def _write_rules(tmp_path: Path, body: str) -> Path:
    press = tmp_path / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path


class TestRegenerateDirSchema:
    def test_requires_exactly_one_of_file_or_dir(self, tmp_path: Path) -> None:
        both = _write_rules(
            tmp_path / "both",
            "[[regenerate]]\n"
            'file = "uv.lock"\n'
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n",
        )
        with pytest.raises(ValidationError, match="exactly one of file or dir"):
            load_rules(both)

        neither = _write_rules(
            tmp_path / "neither",
            f"[[regenerate]]\ncommand = {json.dumps([PY, '-c', 'pass'])}\n",
        )
        with pytest.raises(ValidationError, match="exactly one of file or dir"):
            load_rules(neither)

    @pytest.mark.parametrize(
        "bad_dir",
        [
            ".",
            "..",
            "../outside",
            "press",
            "PRESS",
            "press/press-source.toml",
            "src/*/client",
            "src/{repo_name}/client",
        ],
    )
    def test_rejects_unsafe_or_invalid_dir(self, tmp_path: Path, bad_dir: str) -> None:
        target = _write_rules(
            tmp_path / "bad",
            "[[regenerate]]\n"
            f"dir = {json.dumps(bad_dir)}\n"
            f"command = {json.dumps([PY, '-c', 'pass'])}\n",
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_dir_needs_no_extra_exclude_entries(self, tmp_path: Path) -> None:
        target = _write_rules(
            tmp_path / "ok",
            "[[regenerate]]\n"
            'dir = "src/{package_name}/baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n"
            "verify_exempt = true\n"
            'reason = "BAML client, rebuilt from baml_src"\n',
        )
        rules = load_rules(target)
        assert len(rules.regenerate_dirs) == 1
        assert rules.regenerate_dirs[0].dir == "src/{package_name}/baml_client"

    def test_rejects_overlaps_with_other_rules(self, tmp_path: Path) -> None:
        nested_dirs = _write_rules(
            tmp_path / "nested",
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n\n"
            "[[regenerate]]\n"
            'dir = "baml_client/sub"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n",
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(nested_dirs)

        file_inside_dir = _write_rules(
            tmp_path / "file-in-dir",
            '[rules]\nextra_exclude_files = ["baml_client/a.py"]\n\n'
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n\n"
            "[[regenerate]]\n"
            'file = "baml_client/a.py"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n",
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(file_inside_dir)

        remove_overlap = _write_rules(
            tmp_path / "remove-overlap",
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n\n"
            "[[remove]]\n"
            'dir = "baml_client"\n'
            'reason = "drop"\n',
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(remove_overlap)

    def test_verify_exempt_requires_reason_and_vice_versa(self, tmp_path: Path) -> None:
        missing_reason = _write_rules(
            tmp_path / "no-reason",
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n"
            "verify_exempt = true\n",
        )
        with pytest.raises(ValidationError, match="reason"):
            load_rules(missing_reason)

        stray_reason = _write_rules(
            tmp_path / "stray-reason",
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n"
            'reason = "unused"\n',
        )
        with pytest.raises(ValidationError, match="verify_exempt"):
            load_rules(stray_reason)


def _client_regen_script(subdir_from_pkg: bool = True) -> str:
    if subdir_from_pkg:
        return (
            "import pathlib, tomllib; "
            "pkg = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['name']; "
            "d = pathlib.Path('src') / pkg / 'baml_client'; "
            "d.mkdir(parents=True, exist_ok=True); "
            "(d / '__init__.py').write_text(f'# generated for {pkg}\\n', encoding='utf-8'); "
            "(d / 'fresh.py').write_text(f'CLIENT = {pkg!r}\\n', encoding='utf-8')"
        )
    return (
        "import pathlib, tomllib; "
        "pkg = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['name']; "
        "d = pathlib.Path('baml_client'); "
        "d.mkdir(parents=True, exist_ok=True); "
        "(d / '__init__.py').write_text(f'# generated for {pkg}\\n', encoding='utf-8'); "
        "(d / 'fresh.py').write_text(f'CLIENT = {pkg!r}\\n', encoding='utf-8')"
    )


def test_regenerate_dir_deletes_stale_rebuilds_scans_and_records_receipt(
    tmp_path: Path, capsys
) -> None:
    rules_text = (
        "[[regenerate]]\n"
        'dir = "src/{package_name}/baml_client"\n'
        f"command = {json.dumps([PY, '-c', _client_regen_script(True)])}\n"
        "verify_exempt = true\n"
        'reason = "BAML client, rebuilt from baml_src"\n'
    )
    repo = _init_repo(
        tmp_path / "regen-dir",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {
                # Contains a glued name inside the generated dir that would fail
                # preflight if the directory were not excluded from text rewriting.
                "src/acme_widget/baml_client/stale.py": (
                    "class AcmeWidgetClientViewer:\n    pass\n"
                ),
            },
        ),
        rules_text=rules_text,
    )

    assert check_tools_command(["--target", str(repo)]) == 0
    assert verify_command(["--target", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "not verified (exempt): src/acme_widget/baml_client/" in out
    assert "BAML client, rebuilt from baml_src" in out

    # JSON output includes directory exemption.
    assert verify_command(["--target", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verified"] is True
    assert any(
        entry.get("dir") == "src/acme_widget/baml_client"
        and "BAML client, rebuilt from baml_src" in entry.get("reason", "")
        for entry in payload["exempt"]
    )

    # Press acme_widget -> zeta_tool
    answers = _write_answers(tmp_path / "a1", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    assert (repo / RECEIPT_REL).is_file()

    client_dir = repo / "src" / "zeta_tool" / "baml_client"
    assert client_dir.is_dir()
    assert not (client_dir / "stale.py").exists()
    assert (client_dir / "fresh.py").read_text(
        encoding="utf-8"
    ) == "CLIENT = 'zeta_tool'\n"

    receipt = tomllib.loads((repo / RECEIPT_REL).read_text(encoding="utf-8"))
    regen_dirs = receipt["press"]["regenerate_dir"]
    assert len(regen_dirs) == 1
    assert regen_dirs[0]["dir"] == "src/zeta_tool/baml_client"
    assert regen_dirs[0]["source_dir"] == "src/acme_widget/baml_client"
    assert regen_dirs[0]["reason"] == "BAML client, rebuilt from baml_src"
    assert receipt["press"]["counts"]["regenerated"] == 1
    assert any(
        e.get("dir") == "src/zeta_tool/baml_client"
        and e.get("reason") == "BAML client, rebuilt from baml_src"
        for e in receipt["press"]["exempt"]
    )

    # Repeat press (--force) zeta_tool -> nova_app
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pressed to zeta")
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{ZETA_DEST.owner}/{ZETA_DEST.repo_name}.git",
    )
    assert verify_command(["--target", str(repo)]) == 0
    answers_2 = _write_answers(tmp_path / "a2", NOVA_DEST)
    assert main(["--target", str(repo), "--config", str(answers_2), "--force"]) == 0
    assert (repo / "src" / "nova_app" / "baml_client" / "fresh.py").read_text(
        encoding="utf-8"
    ) == "CLIENT = 'nova_app'\n"


def test_regenerate_dir_leaking_output_fails_exit_1_no_receipt(
    tmp_path: Path,
) -> None:
    bad_script = (
        "import pathlib; "
        "d = pathlib.Path('baml_client'); "
        "d.mkdir(parents=True, exist_ok=True); "
        "(d / 'leak.py').write_text('OLD = \"acme_widget\"\\n', encoding='utf-8')"
    )
    repo = _init_repo(
        tmp_path / "leak-dir",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {"baml_client/old.py": "OLD = 'acme_widget'\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', bad_script])}\n"
            "verify_exempt = true\n"
            'reason = "client"\n'
        ),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 1
    assert not (repo / RECEIPT_REL).exists()


def test_regenerate_dir_missing_after_command_fails_exit_1_no_receipt(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path / "missing-after",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {"baml_client/old.py": "x = 1\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', 'pass'])}\n"
            "verify_exempt = true\n"
            'reason = "client"\n'
        ),
    )
    answers = _write_answers(tmp_path, ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 1
    assert not (repo / RECEIPT_REL).exists()


def test_regenerate_dir_without_verify_exempt_is_checked_by_verify(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path / "no-exempt",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"baml_client/inlined.py": 'NAME = "acme_widget"\n'},
        ),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
        ),
    )
    # Without verify_exempt, hermetic verify scans baml_client and catches acme_widget.
    assert verify_command(["--target", str(repo)]) == 1


@requires_symlink
def test_regenerate_dir_refuses_symlink_at_preflight(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path / "sym-dir",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {"baml_client/a.py": "x = 1\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
            "verify_exempt = true\n"
            'reason = "client"\n'
        ),
    )
    os.symlink("a.py", repo / "baml_client" / "link.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add symlink")
    answers = _write_answers(tmp_path, ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 2
    assert _git(repo, "status", "--porcelain") == ""


def test_regenerate_dir_refuses_dirty_tracked_even_with_allow_dirty(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path / "dirty-dir",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {"baml_client/a.py": "x = 1\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
            "verify_exempt = true\n"
            'reason = "client"\n'
        ),
    )
    (repo / "baml_client" / "a.py").write_text("x = 2\n", encoding="utf-8")
    answers = _write_answers(tmp_path, ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers), "--allow-dirty"]) == 2
    assert not (repo / RECEIPT_REL).exists()


def test_gitignored_root_dir_and_clean_in_package_dir_both_work(
    tmp_path: Path,
) -> None:
    # Path 1: wholly gitignored root baml_client/ rebuilt in place.
    root_repo = _init_repo(
        tmp_path / "gitignored-root",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {".gitignore": "baml_client/\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
            "verify_exempt = true\n"
            'reason = "BAML client"\n'
        ),
    )
    (root_repo / "baml_client").mkdir()
    (root_repo / "baml_client" / "stale.py").write_text(
        "acme_widget\n", encoding="utf-8"
    )
    answers = _write_answers(tmp_path / "ans", ZETA_DEST)
    assert main(["--target", str(root_repo), "--config", str(answers)]) == 0
    assert not (root_repo / "baml_client" / "stale.py").exists()
    assert (root_repo / "baml_client" / "fresh.py").read_text(
        encoding="utf-8"
    ) == "CLIENT = 'zeta_tool'\n"

    # Path 2: gitignored in-package client cleared via [[clean]], then rebuilt.
    pkg_repo = _init_repo(
        tmp_path / "gitignored-pkg",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {".gitignore": "baml_client/\n"}),
        rules_text=(
            "[[clean]]\n"
            'paths = ["src/{package_name}/baml_client"]\n\n'
            "[[regenerate]]\n"
            'dir = "src/{package_name}/baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(True)])}\n"
            "verify_exempt = true\n"
            'reason = "BAML client"\n'
        ),
    )
    ignored = pkg_repo / "src" / "acme_widget" / "baml_client"
    ignored.mkdir()
    (ignored / "stale.py").write_text("acme_widget\n", encoding="utf-8")

    # Rename-closure refuses while the ignored dir sits inside src/acme_widget/.
    assert main(["--target", str(pkg_repo), "--config", str(answers)]) == 2
    assert clean_command(["--target", str(pkg_repo)]) == 0
    assert not ignored.exists()
    assert main(["--target", str(pkg_repo), "--config", str(answers)]) == 0
    assert (pkg_repo / "src" / "zeta_tool" / "baml_client" / "fresh.py").read_text(
        encoding="utf-8"
    ) == "CLIENT = 'zeta_tool'\n"


def test_placeholder_dir_refuses_preexisting_destination_on_disk(
    tmp_path: Path, capsys
) -> None:
    """Regression (codex 4704119216): an unrenamed placeholder dir must not
    delete an unrelated pre-existing directory at its destination path."""
    script = (
        "import pathlib; "
        "d = pathlib.Path('clients/zeta_tool'); d.mkdir(parents=True, exist_ok=True); "
        "(d / 'fresh.py').write_text(\"CLIENT = 'zeta_tool'\\n\", encoding='utf-8')"
    )
    repo = _init_repo(
        tmp_path / "dest-collision",
        ACME_SOURCE,
        _python_files(ACME_SOURCE),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "clients/{package_name}"\n'
            f"command = {json.dumps([PY, '-c', script])}\n"
            "verify_exempt = true\n"
            'reason = "generated client"\n'
        ),
    )
    local_file = repo / "clients" / "zeta_tool" / "local.txt"
    local_file.parent.mkdir(parents=True)
    local_file.write_text("keep me\n", encoding="utf-8")
    answers = _write_answers(tmp_path / "ans", ZETA_DEST)

    code = main(["--target", str(repo), "--config", str(answers), "--allow-dirty"])
    assert code == 2
    assert local_file.read_text(encoding="utf-8") == "keep me\n"
    assert "already exists" in capsys.readouterr().err
    assert not (repo / RECEIPT_REL).exists()


def test_placeholder_dir_without_parent_rename_exempts_actual_sandbox_path(
    tmp_path: Path, capsys
) -> None:
    """Regression (codex 4704119226): when a placeholder dir has no sibling
    causing its parent to move, hermetic verify exempts its real sandbox path
    and a real press removes the stale source dir before rebuilding."""
    script = (
        "import pathlib, tomllib; "
        "pkg = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['name']; "
        "d = pathlib.Path('clients') / pkg; d.mkdir(parents=True, exist_ok=True); "
        "(d / 'fresh.py').write_text(f'CLIENT = {pkg!r}\\n', encoding='utf-8')"
    )
    repo = _init_repo(
        tmp_path / "standalone-placeholder-dir",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"clients/acme_widget/generated.py": "CLIENT = 'acme_widget'\n"},
        ),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "clients/{package_name}"\n'
            f"command = {json.dumps([PY, '-c', script])}\n"
            "verify_exempt = true\n"
            'reason = "generated client"\n'
        ),
    )
    assert verify_command(["--target", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "clients/acme_widget/" in out

    answers = _write_answers(tmp_path / "ans", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    assert not (repo / "clients" / "acme_widget").exists()
    assert (repo / "clients" / "zeta_tool" / "fresh.py").read_text(
        encoding="utf-8"
    ) == "CLIENT = 'zeta_tool'\n"


def test_regenerate_dir_command_conflicting_with_remove_refused_before_apply(
    tmp_path: Path, capsys
) -> None:
    """Regression (codex 4704119232): [[regenerate]] dir commands referencing a
    [[remove]] file or directory must be refused at plan time (exit 2)."""
    for remove_block in (
        '[[remove]]\nfile = "scripts/generate.py"\nreason = "drop script"\n',
        '[[remove]]\ndir = "scripts"\nreason = "drop scripts"\n',
    ):
        sub = tmp_path / ("rm_dir" if "dir =" in remove_block else "rm_file")
        repo = _init_repo(
            sub / "repo",
            ACME_SOURCE,
            _python_files(
                ACME_SOURCE,
                {
                    "scripts/generate.py": "print('hi')\n",
                    "baml_client/a.py": "x = 1\n",
                },
            ),
            rules_text=(
                f"{remove_block}\n"
                "[[regenerate]]\n"
                'dir = "baml_client"\n'
                f"command = {json.dumps([PY, 'scripts/generate.py'])}\n"
                "verify_exempt = true\n"
                'reason = "generated client"\n'
            ),
        )
        answers = _write_answers(sub / "ans", ZETA_DEST)
        assert main(["--target", str(repo), "--config", str(answers), "--dry-run"]) == 2
        assert "scripts/generate.py" in capsys.readouterr().err
        assert not (repo / RECEIPT_REL).exists()


def test_resolve_regenerate_dir_composes_ancestor_rename_and_placeholder() -> None:
    """Regression (coderabbit 4704144779): ancestor rename and {package_name}
    substitution both apply when dest is provided, while dest=None stays in
    sandbox coordinates."""
    from template_press.rebrand.pathing import resolve_regenerate_dir
    from template_press.rebrand.rules import RegenerateDirRule

    rule = RegenerateDirRule(
        dir="acmelabs/generated/acme_widget/baml_client",
        command=("baml-cli", "generate"),
        raw_dir="acmelabs/generated/{package_name}/baml_client",
    )
    renames = {"acmelabs": "zetalabs"}
    assert (
        resolve_regenerate_dir(rule, renames, ZETA_DEST)
        == "zetalabs/generated/zeta_tool/baml_client"
    )
    assert (
        resolve_regenerate_dir(rule, renames, None)
        == "zetalabs/generated/acme_widget/baml_client"
    )


def test_ancestor_renamed_with_placeholder_removes_translated_source_dir(
    tmp_path: Path,
) -> None:
    """Regression (codex 4707354023): when an ancestor dir renames but the
    {package_name} component does not, execute_dir_regenerations must remove
    the translated stale source dir rather than leaving it behind."""
    script = (
        "import pathlib, tomllib; "
        "pkg = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['name']; "
        "repo_slug = pkg.replace('_', '-'); "
        "d = pathlib.Path(repo_slug) / 'generated' / pkg / 'baml_client'; "
        "d.mkdir(parents=True, exist_ok=True); "
        "(d / 'fresh.py').write_text(f'CLIENT = {pkg!r}\\n', encoding='utf-8')"
    )
    repo = _init_repo(
        tmp_path / "ancestor-plus-placeholder",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {
                "acme-widget/README.md": "# acme-widget\n",
                "acme-widget/generated/acme_widget/baml_client/old.py": (
                    "CLIENT = 'acme_widget'\n"
                ),
            },
        ),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "acme-widget/generated/{package_name}/baml_client"\n'
            f"command = {json.dumps([PY, '-c', script])}\n"
            "verify_exempt = true\n"
            'reason = "generated client"\n'
        ),
    )
    answers = _write_answers(tmp_path / "ans", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    assert not (repo / "zeta-tool" / "generated" / "acme_widget").exists()
    assert (
        repo / "zeta-tool" / "generated" / "zeta_tool" / "baml_client" / "fresh.py"
    ).read_text(encoding="utf-8") == "CLIENT = 'zeta_tool'\n"


def test_regenerate_dir_refuses_active_core_excludes_file_inside_dir(
    tmp_path: Path, capsys
) -> None:
    """Regression (codex 4707354036): an active core.excludesFile inside a
    [[regenerate]] dir must be refused at preflight (exit 2) before any write."""
    repo = _init_repo(
        tmp_path / "active-excludes",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {
                "baml_client/a.py": "x = 1\n",
                "baml_client/ignore-rules": "*.tmp\n",
            },
        ),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
            "verify_exempt = true\n"
            'reason = "generated client"\n'
        ),
    )
    _git(repo, "config", "core.excludesFile", str(repo / "baml_client/ignore-rules"))
    answers = _write_answers(tmp_path / "ans", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers), "--dry-run"]) == 2
    assert "active Git visibility input" in capsys.readouterr().err
    assert not (repo / RECEIPT_REL).exists()


def test_regenerate_dir_refuses_untracked_file_under_show_untracked_no(
    tmp_path: Path, capsys
) -> None:
    """Regression (coderabbit 4707367515): untracked files under a [[regenerate]]
    dir must still be refused when status.showUntrackedFiles=no."""
    repo = _init_repo(
        tmp_path / "show-untracked-no",
        ACME_SOURCE,
        _python_files(ACME_SOURCE, {"baml_client/a.py": "x = 1\n"}),
        rules_text=(
            "[[regenerate]]\n"
            'dir = "baml_client"\n'
            f"command = {json.dumps([PY, '-c', _client_regen_script(False)])}\n"
            "verify_exempt = true\n"
            'reason = "generated client"\n'
        ),
    )
    _git(repo, "config", "status.showUntrackedFiles", "no")
    personal = repo / "baml_client" / "personal.txt"
    personal.write_text("keep me\n", encoding="utf-8")
    answers = _write_answers(tmp_path / "ans", ZETA_DEST)
    assert main(["--target", str(repo), "--config", str(answers), "--allow-dirty"]) == 2
    assert personal.read_text(encoding="utf-8") == "keep me\n"
    assert "uncommitted or untracked" in capsys.readouterr().err
    assert not (repo / RECEIPT_REL).exists()
