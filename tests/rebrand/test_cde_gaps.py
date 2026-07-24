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
from template_press.rebrand.verify_cli import verify_command


def _git(target: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(target), *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def _git_status(target: Path) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(target), "status", "--porcelain"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


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
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)  # noqa: S607
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
        # exit 2 must mean no writes — the tree stays exactly as committed.
        assert _git_status(target) == ""

    def test_verify_end_to_end(self, tmp_path):
        """`press verify` on the same fixture closes every gap hermetically:
        scan_fields auto-appends display_name (the source declares it), the
        synthetic dest identity gets a synthetic display name, and the
        [[replace]] + substring rules close the G3/G4/G5 shapes inside the
        sandbox press — so no source identity survives the paranoid scan."""
        target = _build_target(tmp_path)
        assert verify_command(["--target", str(target)]) == 0
