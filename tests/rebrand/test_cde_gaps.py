"""End-to-end: the three C/D/E gap shapes press clean in one rebrand.

Fixture reproduces the py-launch-blueprint leak shapes from
docs/research/0004 §5 (G3 _plbp_owned / plbp-web, G4 humanized display
name incl. the glued Pascal variant, G5 -plbp- doc filenames) and asserts
`press rebrand` exits 0 with every shape rewritten.

G3/G5 are closed by two DISTINCT, non-overlapping mechanisms, and this
module keeps them in two separate fixture variants (``mode="rules"`` /
``mode="substring"``) rather than combining both in one press-rules.toml.
With ``substring_rewrite_fields = ["app_name"]`` ALSO active, its plain
substring replacement subsumes any single-field ``[[replace]]`` rule
output byte-for-byte — a broken rule mechanism would be silently masked.
Each variant below is discriminating on its own: ``mode="rules"`` carries
NO substring knob (only the rule mechanism can close G3/G5), and
``mode="substring"`` carries NO ``[[replace]]`` rules (only substring mode
can close them).
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


# mode="rules" — the codesign's PRIMARY mechanism: three [[replace]] rules,
# no substring knob. One rule per gap shape, each closing exactly its own
# shape (no overlap with the others).
_RULES_MODE_TOML = (
    "[[replace]]\n"
    'pattern = "_{app_name}_owned"\n'
    'reason  = "logging handler ownership guard"\n'
    "\n"
    "[[replace]]\n"
    'pattern = "{app_name}-web"\n'
    'reason  = "docker image tag"\n'
    "\n"
    "[[replace]]\n"
    'pattern = "-{app_name}.md"\n'
    "paths   = true\n"
    "content = false\n"
    'reason  = "doc filename short-name suffix"\n'
)

# mode="substring" — the secondary, per-field opt-in: plain substring
# replacement in content AND path components closes all three shapes at
# once via the existing token/rename pass. No [[replace]] rules at all.
_SUBSTRING_MODE_TOML = '[rules]\nsubstring_rewrite_fields = ["app_name"]\n'


def _build_target(tmp_path: Path, mode: str, extra_rules: str = "") -> Path:
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
    rules_toml = _RULES_MODE_TOML if mode == "rules" else _SUBSTRING_MODE_TOML
    rules_toml = rules_toml + extra_rules
    (target / "press" / "press-rules.toml").write_text(rules_toml, encoding="utf-8")
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


def _assert_gap_shapes_closed(target: Path) -> None:
    assert "_acme_owned" in (target / "conftest.py").read_text(encoding="utf-8")
    assert "acme-web:dev" in (target / "Dockerfile").read_text(encoding="utf-8")
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "# Acme Widget" in readme and "AcmeWidget" in readme
    assert "Py Launch Blueprint" not in readme
    assert (target / "docs" / "0001-app-short-name-acme.md").exists()
    source_cfg = (target / "press" / "press-source.toml").read_text(encoding="utf-8")
    assert 'display_name = "Acme Widget"' in source_cfg


class TestCdeGapsEndToEnd:
    def test_all_three_gap_shapes_press_clean(self, tmp_path):
        """mode="rules" — the [[replace]] rule mechanism, load-bearing on its
        own (no substring knob to mask a broken rule application)."""
        target = _build_target(tmp_path, mode="rules")
        answers = _answers(tmp_path)
        code = main(["--target", str(target), "--config", str(answers)])
        assert code == 0
        _assert_gap_shapes_closed(target)

    def test_substring_mode_variant_presses_clean(self, tmp_path):
        """mode="substring" — the per-field substring opt-in, load-bearing on
        its own (no [[replace]] rules present to mask a broken substring
        pass)."""
        target = _build_target(tmp_path, mode="substring")
        answers = _answers(tmp_path)
        code = main(["--target", str(target), "--config", str(answers)])
        assert code == 0
        _assert_gap_shapes_closed(target)

    def test_half_specified_answers_exit_2(self, tmp_path):
        target = _build_target(tmp_path, mode="rules")
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

    def test_display_forms_subset_press_succeeds(self, tmp_path):
        """[rules] display_forms = ["spaced"] deliberately narrows BOTH the
        apply rewrite and the post-apply doctor scan to the spaced form: the
        glued Pascal occurrence ("PyLaunchBlueprint") in README.md is left
        un-rewritten on purpose, and the doctor must not flag it as a leak —
        the hermetic `press verify` scanner independently catches glued
        variants via package_name/repo_name matching, so narrowing the
        doctor's display scan here cannot hide a real leak from the
        verification pipeline."""
        target = _build_target(
            tmp_path,
            mode="rules",
            extra_rules='\n[rules]\ndisplay_forms = ["spaced"]\n',
        )
        answers = _answers(tmp_path)
        code = main(["--target", str(target), "--config", str(answers)])
        assert code == 0
        readme = (target / "README.md").read_text(encoding="utf-8")
        assert "# Acme Widget" in readme
        assert "PyLaunchBlueprint" in readme
        assert (target / "press" / "press-receipt.toml").exists()

    def test_verify_end_to_end(self, tmp_path):
        """`press verify` on the rules-mode fixture closes every gap
        hermetically: scan_fields auto-appends display_name (the source
        declares it), the synthetic dest identity gets a synthetic display
        name, and the [[replace]] rules close the G3/G5 shapes inside the
        sandbox press — so no source identity survives the paranoid scan."""
        target = _build_target(tmp_path, mode="rules")
        assert verify_command(["--target", str(target)]) == 0
