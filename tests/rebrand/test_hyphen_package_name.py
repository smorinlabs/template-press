"""P13: no receipt while a hyphenated form of package_name survives."""

from __future__ import annotations

import tomllib
from pathlib import Path

from template_press.rebrand.cli import main
from template_press.rebrand.config import render_source_config
from template_press.rebrand.identity import Identity
from template_press.rebrand.receipt import RECEIPT_REL
from template_press.rebrand.verify_cli import verify_command

from .conftest import _git, init_git_repo, write_answers_file

SOURCE = Identity(
    package_name="acme_widget",
    repo_name="acme-repo",
    app_name="acme",
    author="Ann Example",
    email="ann@example.test",
    owner="acme-org",
)
DEST = Identity(
    package_name="zeta_gadget",
    repo_name="zeta-repo",
    app_name="zeta",
    author="Zed Example",
    email="zed@example.test",
    owner="zeta-org",
)
NEXT = Identity(
    package_name="kilo_tool",
    repo_name="kilo-repo",
    app_name="kilo",
    author="Kim Example",
    email="kim@example.test",
    owner="kilo-org",
)


def _with(identity: Identity, **changes: str) -> Identity:
    return Identity.from_mapping({**identity.as_dict_prompted(), **changes})


def _target(
    base: Path,
    *,
    manifest: str = "acme-widget",
    source: Identity = SOURCE,
    files: dict[str, str] | None = None,
    rules: str | None = None,
    manifest_prefix: str = "",
    manifest_suffix: str = "",
    crlf: bool = False,
) -> Path:
    repo = base / "target"
    package = repo / "src" / source.package_name
    package.mkdir(parents=True)
    (repo / "press").mkdir()
    (repo / "pyproject.toml").write_text(
        f"{manifest_prefix}[project]\n"
        f'name = "{manifest}"\n'
        'version = "0.1.0"\n'
        f'authors = [{{name="{source.author}", email="{source.email}"}}]\n'
        "[project.scripts]\n"
        f'{source.app_name} = "{source.package_name}:main"\n'
        f"{manifest_suffix}",
        encoding="utf-8",
        newline="\r\n" if crlf else None,
    )
    (package / "__init__.py").write_text("def main() -> None: ...\n", encoding="utf-8")
    (repo / "press" / "press-source.toml").write_text(
        render_source_config(source), encoding="utf-8"
    )
    if rules is not None:
        (repo / "press" / "press-rules.toml").write_text(rules, encoding="utf-8")
    for rel, text in (files or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    init_git_repo(
        repo,
        origin=f"https://github.com/{source.owner}/{source.repo_name}.git",
        commit_message="init",
    )
    return repo


def _press(base: Path, target: Path, dest: Identity = DEST) -> int:
    answers = write_answers_file(base, dest)
    return main(["--target", str(target), "--config", str(answers)])


def _settle(target: Path, dest: Identity = DEST) -> None:
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "pressed")
    _git(
        target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{dest.owner}/{dest.repo_name}.git",
    )


def _verify(target: Path) -> int:
    return verify_command(["--target", str(target)])


def _manifest_line(target: Path) -> str:
    return (target / "pyproject.toml").read_text(encoding="utf-8").splitlines()[1]


def _project_name(target: Path) -> str:
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["name"]


def test_proven_hyphen_name_is_rewritten_everywhere(tmp_path: Path) -> None:
    target = _target(tmp_path, files={"README.md": "pip install acme-widget\n"})

    assert _press(tmp_path, target) == 0

    assert _manifest_line(target) == 'name = "zeta-gadget"'
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert readme == "pip install zeta-gadget\n"
    assert (target / RECEIPT_REL).is_file()
    _settle(target)
    assert _verify(target) == 0


def test_proven_hyphen_name_renames_paths(tmp_path: Path) -> None:
    target = _target(tmp_path, files={"docs/acme-widget.md": "guide\n"})

    assert _press(tmp_path, target) == 0

    assert (target / "docs" / "zeta-gadget.md").is_file()
    assert not (target / "docs" / "acme-widget.md").exists()


def test_pressed_target_can_be_pressed_again(tmp_path: Path) -> None:
    target = _target(tmp_path)
    assert _press(tmp_path, target) == 0
    _settle(target)

    answers = write_answers_file(tmp_path, NEXT)
    code = main(["--target", str(target), "--config", str(answers), "--force"])

    assert code == 0
    assert _manifest_line(target) == 'name = "kilo-tool"'


def test_unproven_hyphen_mention_exits_one_without_receipt(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        manifest="acme_widget",
        files={"README.md": "pip install acme-widget\n"},
    )

    assert _press(tmp_path, target) == 1

    assert not (target / RECEIPT_REL).exists()


def test_unproven_prose_is_never_rewritten(tmp_path: Path) -> None:
    source = _with(SOURCE, package_name="well_known")
    target = _target(
        tmp_path,
        manifest="well_known",
        source=source,
        files={"README.md": "a well-known API\n"},
    )

    assert _press(tmp_path, target) == 1

    assert (target / "README.md").read_text(encoding="utf-8") == "a well-known API\n"
    assert not (target / RECEIPT_REL).exists()


def test_verify_ignore_accepts_an_unproven_mention(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        manifest="acme_widget",
        files={"README.md": "pip install acme-widget\n"},
        rules='[rules]\nverify_ignore = ["README.md"]\n',
    )

    assert _press(tmp_path, target) == 0

    assert "acme-widget" in (target / "README.md").read_text(encoding="utf-8")


def test_repo_name_collision_keeps_manifest_on_package_name(tmp_path: Path) -> None:
    source = _with(SOURCE, repo_name="acme-widget")
    target = _target(
        tmp_path,
        source=source,
        files={"README.md": "See acme-widget\n"},
    )

    assert _press(tmp_path, target) == 0

    assert _manifest_line(target) == 'name = "zeta-gadget"'
    assert (target / "README.md").read_text(encoding="utf-8") == "See zeta-repo\n"
    _settle(target)
    assert _verify(target) == 0


def test_collision_override_leaves_a_later_table_on_repo_name(tmp_path: Path) -> None:
    source = _with(SOURCE, repo_name="acme-widget")
    target = _target(
        tmp_path,
        source=source,
        manifest_suffix='[[tool.uv.index]]\nname = "acme-widget"\n',
    )

    assert _press(tmp_path, target) == 0

    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "zeta-gadget"
    assert data["tool"]["uv"]["index"][0]["name"] == "zeta-repo"


def test_collision_override_skips_an_earlier_table(tmp_path: Path) -> None:
    source = _with(SOURCE, repo_name="acme-widget")
    target = _target(
        tmp_path,
        source=source,
        manifest_prefix='[tool.example]\nname = "acme-widget"\n\n',
    )

    assert _press(tmp_path, target) == 0

    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "zeta-gadget"
    assert data["tool"]["example"]["name"] == "zeta-repo"


def test_collision_override_handles_crlf_manifest(tmp_path: Path) -> None:
    source = _with(SOURCE, repo_name="acme-widget")
    target = _target(tmp_path, source=source, crlf=True)

    assert _press(tmp_path, target) == 0

    assert _project_name(target) == "zeta-gadget"
    assert b"\r\n" in (target / "pyproject.toml").read_bytes()


def test_repo_name_collision_with_matching_destination_is_unchanged(
    tmp_path: Path,
) -> None:
    source = _with(SOURCE, repo_name="acme-widget")
    dest = _with(DEST, repo_name="zeta-gadget")
    target = _target(tmp_path, source=source, files={"README.md": "See acme-widget\n"})

    assert _press(tmp_path, target, dest) == 0

    assert _manifest_line(target) == 'name = "zeta-gadget"'
    assert (target / "README.md").read_text(encoding="utf-8") == "See zeta-gadget\n"


def test_destination_reusing_source_hyphen_form_is_not_a_leak(tmp_path: Path) -> None:
    dest = _with(DEST, repo_name="acme-widget")
    target = _target(
        tmp_path,
        manifest="acme_widget",
        files={"README.md": "Repository: acme-repo\n"},
    )

    assert _press(tmp_path, target, dest) == 0

    assert (target / "README.md").read_text(encoding="utf-8") == (
        "Repository: acme-widget\n"
    )


def test_existing_rules_keep_a_historical_file(tmp_path: Path) -> None:
    history = "Renamed from acme-widget by Ann Example.\n"
    target = _target(
        tmp_path,
        files={
            "docs/history.md": history,
            "README.md": "pip install acme-widget\n",
        },
        rules=(
            "[rules]\n"
            'extra_exclude_files = ["docs/history.md"]\n'
            'verify_ignore = ["history.md"]\n'
        ),
    )

    assert _verify(target) == 0
    assert _press(tmp_path, target) == 0

    assert (target / "docs/history.md").read_text(encoding="utf-8") == history
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert readme == "pip install zeta-gadget\n"
    assert _manifest_line(target) == 'name = "zeta-gadget"'
    _settle(target)
    assert _verify(target) == 0


def test_single_token_package_name_is_unaffected(tmp_path: Path) -> None:
    source = _with(SOURCE, package_name="acmewidget")
    target = _target(
        tmp_path,
        manifest="acmewidget",
        source=source,
        files={"README.md": "pip install acmewidget\n"},
    )

    assert _press(tmp_path, target) == 0
