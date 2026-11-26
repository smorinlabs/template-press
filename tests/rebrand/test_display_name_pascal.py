"""P19-TS02: display_name_pascal in substring_rewrite_fields."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.cli import main
from template_press.rebrand.doctor import find_leaks
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.regen import scan_regenerated_output
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verifier import scan
from template_press.rebrand.verify_cli import verify_command

from .test_glued_name_preflight import (
    ACME_SOURCE,
    ZETA_DEST,
    _git,
    _init_repo,
    _python_files,
    _write_answers,
)


def _write_rules(tmp_path: Path, body: str) -> Path:
    press = tmp_path / "press"
    press.mkdir(parents=True, exist_ok=True)
    (press / "press-rules.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_rules_accepts_display_name_pascal_and_rejects_others(tmp_path: Path) -> None:
    target = _write_rules(
        tmp_path / "ok",
        '[rules]\nsubstring_rewrite_fields = ["display_name_pascal"]\n',
    )
    rules = load_rules(target)
    assert rules.substring_rewrite_fields == frozenset({"display_name_pascal"})

    # Bare display_name stays rejected and mentions display_name_pascal + display_forms.
    bad_bare = _write_rules(
        tmp_path / "bare",
        '[rules]\nsubstring_rewrite_fields = ["display_name"]\n',
    )
    with pytest.raises(ValidationError, match="display_name_pascal"):
        load_rules(bad_bare)

    # display_name_camel and display_name_spaced are not added.
    for rejected in ("display_name_camel", "display_name_spaced"):
        bad = _write_rules(
            tmp_path / rejected,
            f'[rules]\nsubstring_rewrite_fields = ["{rejected}"]\n',
        )
        with pytest.raises(ValidationError, match=rejected):
            load_rules(bad)

    # Contradictory config: pascal disabled in display_forms while opted into substring.
    bad_combo = _write_rules(
        tmp_path / "combo",
        '[rules]\ndisplay_forms = ["spaced"]\n'
        'substring_rewrite_fields = ["display_name_pascal"]\n',
    )
    with pytest.raises(ValidationError, match="display_name_pascal"):
        load_rules(bad_combo)


def test_display_name_pascal_rewrites_glued_baml_and_verifies(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path / "baml-ok",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {
                "baml_src/main.baml": (
                    'client<llm> AcmeWidgetClient {\n  provider "openai"\n}\n'
                )
            },
        ),
        rules_text='[rules]\nsubstring_rewrite_fields = ["display_name_pascal"]\n',
    )
    answers = _write_answers(tmp_path, ZETA_DEST)

    assert verify_command(["--target", str(repo)]) == 0
    assert main(["--target", str(repo), "--config", str(answers)]) == 0
    assert (repo / RECEIPT_REL).is_file()
    content = (repo / "baml_src" / "main.baml").read_text(encoding="utf-8")
    assert "ZetaToolClient" in content
    assert "AcmeWidget" not in content

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "after press")
    _git(
        repo,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{ZETA_DEST.owner}/{ZETA_DEST.repo_name}.git",
    )
    assert verify_command(["--target", str(repo)]) == 0


def test_display_name_pascal_caught_by_doctor_regen_and_verifier(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path / "leak-check",
        ACME_SOURCE,
        _python_files(
            ACME_SOURCE,
            {"notes.txt": "prefixAcmeWidgetSuffix\n"},
        ),
        rules_text='[rules]\nsubstring_rewrite_fields = ["display_name_pascal"]\n',
    )
    rules = load_rules(repo)

    # Doctor catches glued lowercase-prefixed form when display_name_pascal is opted in.
    leaks = find_leaks(
        repo,
        ACME_SOURCE,
        rules,
        dest=ZETA_DEST,
        substring_fields=rules.substring_rewrite_fields,
    )
    assert any(
        leak.path == "notes.txt" and leak.field == "display_name_pascal"
        for leak in leaks
    )

    # Regeneration output scan catches it too.
    regen_problems = scan_regenerated_output(
        "prefixAcmeWidgetSuffix\n",
        "notes.txt",
        source=ACME_SOURCE,
        dest=ZETA_DEST,
        rules=rules,
        renames={},
    )
    assert any("display_name_pascal" in p for p in regen_problems)

    # Standalone verifier scan catches it too.
    findings = scan(
        repo,
        ACME_SOURCE,
        ZETA_DEST,
        fields=(
            "app_name",
            "package_name",
            "repo_name",
            "owner",
            "display_name",
            "display_name_pascal",
        ),
        substring_fields=frozenset({"display_name_pascal"}),
        rules=rules,
    )
    assert any(
        f.path == "notes.txt" and f.field == "display_name_pascal" for f in findings
    )


def test_verify_preflight_accepts_glued_only_display_name_pascal(
    tmp_path: Path,
) -> None:
    source = replace(ACME_SOURCE, display_name="Sunburst Studio")
    files = _python_files(
        source,
        {
            "README.md": "# acme-widget\n",
            f"src/{source.package_name}/__init__.py": (
                "class mySunburstStudioClient:\n    pass\n"
                "def main() -> int:\n    return 0\n"
            ),
        },
    )
    repo = _init_repo(
        tmp_path / "glued-only",
        source,
        files,
        rules_text='[rules]\nsubstring_rewrite_fields = ["display_name_pascal"]\n',
    )
    assert verify_command(["--target", str(repo)]) == 0


def test_display_name_pascal_contained_destination_refused_exit_2(
    tmp_path: Path,
) -> None:
    dest = replace(ZETA_DEST, display_name="Acme Widget Pro")
    repo = _init_repo(
        tmp_path / "contained",
        ACME_SOURCE,
        _python_files(ACME_SOURCE),
        rules_text='[rules]\nsubstring_rewrite_fields = ["display_name_pascal"]\n',
    )
    answers = _write_answers(tmp_path, dest)
    assert main(["--target", str(repo), "--config", str(answers)]) == 2
    assert _git(repo, "status", "--porcelain") == ""
