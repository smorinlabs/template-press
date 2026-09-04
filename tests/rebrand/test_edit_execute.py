"""P09 Task 14 (spec E4 + E11) — [[edit]] execution, post-conditions, receipt.

An edit AMENDS the file the replace pass has already rewritten, so it is the
inverse of a regeneration in every direction that matters here: the target is
never excluded from the rewrite, never exempt from ``press verify``, and the
declared command must leave the declared ``expect`` substring behind. What it
SHARES with a regeneration is the whole execution contract — cwd, no shell,
deny-by-default env, pinned executable, the sink guards re-run before each
launch, the post-command identity scan, control-file and Git-visibility
snapshots, and the exit-1-no-receipt failure path.

E11 is the gate this file pins hardest: those snapshots used to be taken only
when ``[[regenerate]]`` rules existed, so an edits-only target could change
Git's visibility surface mid-press and still earn a receipt.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from template_press.rebrand import verifier as verifier_mod
from template_press.rebrand.cli import main
from template_press.rebrand.config import SOURCE_CONFIG_REL, render_source_config
from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.pathing import exempt_regenerated_paths
from template_press.rebrand.receipt import RECEIPT_REL, write_receipt
from template_press.rebrand.rules import load_rules
from template_press.rebrand.verify_cli import verify_command

from .conftest import (
    DEST,
    SOURCE,
    _git,
    requires_symlink,
    write_answers_file,
)

PY = sys.executable
RULES_REL = Path("press") / "press-rules.toml"

# --------------------------------------------------------------------------
# Stub commands. Committed .py files launched through sys.executable: no exec
# bit, no `-c` payload (a control character in argv is a plan-time refusal),
# and no identity literal in any script BODY — a tracked script is rewritten
# by the replace pass like any other file, which would silently defuse the
# very substitution a test depends on. Identity literals therefore travel as
# argv from press/press-rules.toml, which is a press-owned control file and
# so is never rewritten.
# --------------------------------------------------------------------------
SUBST = """\
import pathlib
import sys

path = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else "pyproject.toml")
path.write_text(
    path.read_text(encoding="utf-8").replace(sys.argv[1], sys.argv[2]),
    encoding="utf-8",
)
"""

# Rename-independent by construction: the package directory is renamed by the
# press, so the argv may not name it (stale_argv_elements refuses that at plan
# time) and the script globs for it instead.
PKGVER = """\
import pathlib

(found,) = pathlib.Path("src").glob("*/version.py")
found.write_text('__version__ = "0.2.0"\\n', encoding="utf-8")
"""

APPEND = """\
import pathlib
import sys

with pathlib.Path(sys.argv[1]).open("a", encoding="utf-8") as handle:
    handle.write(sys.argv[2] + "\\n")
"""

CLOBBER_FAIL = """\
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text("# clobbered\\n", encoding="utf-8")
sys.exit(3)
"""

TAMPER_CONTROL_AND_DELETE = """\
import pathlib

pyproject = pathlib.Path("pyproject.toml")
text = pyproject.read_text(encoding="utf-8")
pyproject.write_text(
    text.replace('version = "0.1.0"', 'version = "0.3.0"'),
    encoding="utf-8",
)
(rules_path,) = pathlib.Path(".").glob("*/*-rules.toml")
receipt_path = rules_path.with_name(rules_path.name.replace("rules", "receipt"))
rules_path.write_text("tampered\\n", encoding="utf-8")
receipt_path.mkdir()
pathlib.Path("scripts/late.py").unlink()
"""

LATE_EXECUTABLE = """\
#!/usr/bin/env python3
raise SystemExit("this executable should have been deleted")
"""

# A stand-in for `uv lock`: derives the root package row from whatever
# pyproject.toml says AT THE MOMENT IT RUNS, which is what makes the edit ->
# regenerate phase order observable in the produced lockfile.
FAKELOCK = """\
import pathlib
import re

text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
name = re.search(r'name = "([^"]+)"', text).group(1)
version = re.search(r'version = "([^"]+)"', text).group(1)
pathlib.Path("uv.lock").write_text(
    'version = 1\\n\\n[[package]]\\nname = "%s"\\nversion = "%s"\\n' % (name, version),
    encoding="utf-8",
)
"""

# Writes a valid declared output, then undoes the earlier edit as an undeclared
# side effect. Immediate postconditions all pass; only the final edit recheck
# can refuse the now-invalid `expect` promise.
FAKELOCK_UNDO_EDIT = """\
import pathlib
import re

pyproject = pathlib.Path("pyproject.toml")
text = pyproject.read_text(encoding="utf-8")
name = re.search(r'name = "([^"]+)"', text).group(1)
version = re.search(r'version = "([^"]+)"', text).group(1)
pathlib.Path("uv.lock").write_text(
    'version = 1\\n\\n[[package]]\\nname = "%s"\\nversion = "%s"\\n' % (name, version),
    encoding="utf-8",
)
pyproject.write_text(
    text.replace('version = "0.3.0"', 'version = "0.1.0"'),
    encoding="utf-8",
)
"""

SCRIPTS = {
    "subst.py": SUBST,
    "pkgver.py": PKGVER,
    "append.py": APPEND,
    "clobber_fail.py": CLOBBER_FAIL,
    "tamper_control_and_delete.py": TAMPER_CONTROL_AND_DELETE,
    "late.py": LATE_EXECUTABLE,
    "fakelock.py": FAKELOCK,
    "fakelock_undo_edit.py": FAKELOCK_UNDO_EDIT,
}


def _argv(*parts: str) -> str:
    """A TOML array of basic strings (JSON string escaping is a subset)."""
    return "[" + ", ".join(json.dumps(part) for part in parts) + "]"


def _edit_block(file: str, *, command: str, expect: str) -> str:
    return f"[[edit]]\nfile = {json.dumps(file)}\ncommand = {command}\nexpect = {json.dumps(expect)}\n"


def _prepare(
    target: Path, rules_body: str, *, extra: dict[str, str] | None = None
) -> None:
    """Declare rules + stub scripts on the standard fixture and commit.

    The stock fixture's ``description = "Demo widget by Demo Author"`` becomes
    the prose ``"Demo widget by Potato Farmer"`` after the replace pass, and
    the STRICT post-command scan (separator- and case-glued matching, harsher
    than the doctor's) reads that surviving ``Demo widget`` as source
    package_name AND repo_name. Every pyproject.toml edit would then fail its
    identity post-condition for a reason that has nothing to do with the edit,
    so the description is neutralized here.
    """
    (target / "press").mkdir(exist_ok=True)
    (target / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    (target / RULES_REL).write_text(rules_body, encoding="utf-8")
    pyproject = target / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "Demo widget by Demo Author", "A tiny project"
        ),
        encoding="utf-8",
    )
    scripts = target / "scripts"
    scripts.mkdir(exist_ok=True)
    for name, body in SCRIPTS.items():
        (scripts / name).write_text(body, encoding="utf-8")
    for rel, body in (extra or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "declare edits")


def _press(target: Path, tmp_path: Path, *flags: str) -> int:
    answers = write_answers_file(tmp_path, DEST)
    return main(["--target", str(target), "--config", str(answers), *flags])


def _receipt(target: Path) -> dict:
    return tomllib.loads((target / RECEIPT_REL).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. The success path
# ---------------------------------------------------------------------------
def test_successful_edit_amends_the_rewritten_file_and_is_receipted(
    src_target: Path, tmp_path: Path
):
    """The two passes compose: the replace pass renames the package, then the
    declared command bumps the version the replace pass left alone."""
    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.2.0"'
            ),
            expect='version = "0.2.0"',
        ),
    )
    assert _press(src_target, tmp_path) == 0
    pyproject = (src_target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "potato_launcher"' in pyproject  # replace pass
    assert 'version = "0.2.0"' in pyproject  # declared edit
    rows = _receipt(src_target)["press"]["edit"]
    assert len(rows) == 1
    assert rows[0]["file"] == "pyproject.toml"
    assert rows[0]["expect"] == 'version = "0.2.0"'
    assert rows[0]["argv"][1:] == [
        "scripts/subst.py",
        'version = "0.1.0"',
        'version = "0.2.0"',
    ]
    assert os.path.isabs(rows[0]["argv"][0])  # the pinned executable


# ---------------------------------------------------------------------------
# 2. A failing command
# ---------------------------------------------------------------------------
def test_command_exit_3_fails_the_press_with_no_receipt_and_restores_control(
    src_target: Path, tmp_path: Path, capsys
):
    """Regeneration-equivalent failure semantics. The stub clobbers
    press/press-rules.toml BEFORE exiting nonzero, so the restoration is a
    real assertion rather than a vacuous one."""
    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(PY, "scripts/clobber_fail.py", "press/press-rules.toml"),
            expect="anything",
        ),
    )
    before = (src_target / RULES_REL).read_bytes()
    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "pyproject.toml" in err
    assert "3" in err
    assert not (src_target / RECEIPT_REL).exists()
    assert (src_target / RULES_REL).read_bytes() == before


def test_exceptional_later_launch_restores_control_files_and_planted_receipt(
    src_target: Path, tmp_path: Path, capsys
):
    """A missing pinned executable is an exception, not a nonzero result.

    The earlier edit tampers with both an existing and an absent control file,
    then deletes the later edit's target-relative executable. Recovery must
    cover this exceptional launch path exactly as it covers a reported edit
    failure.
    """
    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(PY, "scripts/tamper_control_and_delete.py"),
            expect='version = "0.3.0"',
        )
        + "\n"
        + _edit_block(
            "README.md",
            command=_argv("scripts/late.py"),
            expect="Potato Launcher",
        ),
    )
    late = src_target / "scripts" / "late.py"
    late.chmod(0o755)
    _git(src_target, "add", "scripts/late.py")
    _git(src_target, "commit", "-m", "test: make late command executable")
    rules_before = (src_target / RULES_REL).read_bytes()

    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "No such file or directory" in err
    assert "control-file restoration incomplete" in err
    assert "press/press-receipt.toml" in err
    assert "could not be restored" in err
    assert (src_target / RULES_REL).read_bytes() == rules_before
    assert (src_target / RECEIPT_REL).is_dir()


def test_post_validation_output_error_preserves_successful_control_writes(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Once command tampering is ruled out, recovery must be disarmed.

    A broken output pipe after the receipt write is an operational reporting
    failure, not a reason to delete the valid receipt or restore the source
    identity over the successful destination identity.
    """
    import builtins

    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.2.0"'
            ),
            expect='version = "0.2.0"',
        ),
    )
    real_print: Callable[..., Any] = builtins.print
    raised = False

    def break_first_success_report(*args: Any, **kwargs: Any) -> None:
        nonlocal raised
        if (
            not raised
            and args
            and isinstance(args[0], str)
            and args[0].startswith("Applied:")
        ):
            raised = True
            raise BrokenPipeError("test output pipe closed")
        real_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", break_first_success_report)
    assert _press(src_target, tmp_path) == 1
    assert raised
    assert _receipt(src_target)["press"]["verified"] is True
    source_config = (src_target / SOURCE_CONFIG_REL).read_text(encoding="utf-8")
    assert 'package_name = "potato_launcher"' in source_config
    assert 'package_name = "demo_widget"' not in source_config


def test_keyboard_interrupt_restores_controls_then_propagates(
    src_target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Operator interruption is outside Exception but inside the armed phase."""
    import template_press.rebrand.cli as cli_mod

    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(PY, "scripts/subst.py", "unused", "unused"),
            expect='version = "0.1.0"',
        ),
    )
    rules_before = (src_target / RULES_REL).read_bytes()

    def interrupt_after_tampering(target: Path, *_args: Any, **_kwargs: Any) -> None:
        (target / RULES_REL).write_text("tampered\n", encoding="utf-8")
        (target / RECEIPT_REL).write_text("forged\n", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_mod, "execute_edits", interrupt_after_tampering)
    with pytest.raises(KeyboardInterrupt):
        _press(src_target, tmp_path)
    assert (src_target / RULES_REL).read_bytes() == rules_before
    assert not (src_target / RECEIPT_REL).exists()


# ---------------------------------------------------------------------------
# 3. A silent no-op
# ---------------------------------------------------------------------------
def test_expect_missing_after_a_zero_exit_noop_fails_without_receipt(
    src_target: Path, tmp_path: Path, capsys
):
    """`expect` exists precisely for the command that succeeds and does
    nothing — the failure mode a plain exit-code check cannot see."""
    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "9.9.9"', 'version = "0.2.0"'
            ),
            expect='version = "0.2.0"',
        ),
    )
    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "expect" in err and 'version = "0.2.0"' in err
    assert not (src_target / RECEIPT_REL).exists()


# ---------------------------------------------------------------------------
# 4. An edit that re-introduces the source identity
# ---------------------------------------------------------------------------
def test_edit_that_restores_source_identity_fails_the_leak_postcondition(
    src_target: Path, tmp_path: Path, capsys
):
    """`expect` is satisfied here on purpose: the ONLY thing that can refuse
    this press is the post-command source-identity scan."""
    _prepare(
        src_target,
        _edit_block(
            "pyproject.toml",
            command=_argv(
                PY,
                "scripts/subst.py",
                'name = "potato_launcher"',
                'name = "demo_widget"',
            ),
            expect='name = "demo_widget"',
        ),
    )
    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "demo_widget" in err
    assert not (src_target / RECEIPT_REL).exists()


# ---------------------------------------------------------------------------
# 5. A target that moves during the press
# ---------------------------------------------------------------------------
def test_edit_target_under_a_renamed_prefix_translates_and_succeeds(
    src_target: Path, tmp_path: Path
):
    """Declared in SOURCE coordinates, executed at the post-rename path."""
    _prepare(
        src_target,
        _edit_block(
            "src/demo_widget/version.py",
            command=_argv(PY, "scripts/pkgver.py"),
            expect='__version__ = "0.2.0"',
        ),
        extra={"src/demo_widget/version.py": '__version__ = "0.1.0"\n'},
    )
    assert _press(src_target, tmp_path) == 0
    assert not (src_target / "src" / "demo_widget").exists()
    assert (src_target / "src" / "potato_launcher" / "version.py").read_text(
        encoding="utf-8"
    ) == '__version__ = "0.2.0"\n'
    rows = _receipt(src_target)["press"]["edit"]
    assert rows[0]["file"] == "src/demo_widget/version.py"  # declared coordinates


# ---------------------------------------------------------------------------
# 6. E11 — the snapshots must not depend on [[regenerate]] existing
# ---------------------------------------------------------------------------
_E11_RULES = _edit_block(
    ".gitignore",
    command=_argv(PY, "scripts/append.py", ".gitignore", "secrets/"),
    expect="secrets/",
)


def test_e11_edit_only_visibility_change_refuses_and_restores(
    src_target: Path, tmp_path: Path, capsys
):
    """An edits-only target changing Git's ignore policy mid-press must be
    refused by the same revalidation that has always covered regenerations."""
    _prepare(src_target, _E11_RULES)
    rules_before = (src_target / RULES_REL).read_bytes()
    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "effective Git visibility changed during declared commands" in err
    assert "changed: '.gitignore'" in err
    assert not (src_target / RECEIPT_REL).exists()
    assert (src_target / RULES_REL).read_bytes() == rules_before


def test_e11_fixture_would_pass_without_the_visibility_gate(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The discriminating probe for the test above: with ONLY the visibility
    revalidation neutralized (exactly what an edits-only press skipped before
    E11), this same fixture presses clean and earns a receipt. So the refusal
    above is attributable to the gate and to nothing else in the fixture."""
    import template_press.rebrand.cli as cli_mod

    monkeypatch.setattr(cli_mod, "validate_visibility_state", lambda *a, **k: [])
    _prepare(src_target, _E11_RULES)
    assert _press(src_target, tmp_path) == 0
    assert (src_target / RECEIPT_REL).exists()
    assert "secrets/" in (src_target / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 7. Phase order
# ---------------------------------------------------------------------------
def test_every_edit_runs_before_every_regeneration(src_target: Path, tmp_path: Path):
    """The lockfile stub reads pyproject.toml when it runs, so the version it
    records is a direct observation of the phase order — 0.3.0 only if the
    edit ran first. Declaration order is deliberately inverted in the rules
    file: the phase, not the file, decides."""
    _prepare(
        src_target,
        '[[regenerate]]\nfile = "uv.lock"\ncommand = '
        + _argv(PY, "scripts/fakelock.py")
        + "\n\n"
        + _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.3.0"'
            ),
            expect='version = "0.3.0"',
        ),
        extra={
            "uv.lock": 'version = 1\n\n[[package]]\nname = "x"\nversion = "0.0.0"\n'
        },
    )
    assert _press(src_target, tmp_path) == 0
    lock = tomllib.loads((src_target / "uv.lock").read_text(encoding="utf-8"))
    assert lock["package"][0]["version"] == "0.3.0"
    assert lock["package"][0]["name"] == "potato_launcher"


def test_real_uv_version_runs_before_real_uv_lock(src_target: Path, tmp_path: Path):
    """The binding Task 14 acceptance uses the actual declared toolchain."""
    _prepare(
        src_target,
        '[[regenerate]]\nfile = "uv.lock"\ncommand = ["uv", "lock"]\n'
        'env = ["UV_CACHE_DIR"]\n\n'
        '[[edit]]\nfile = "pyproject.toml"\n'
        'command = ["uv", "version", "0.3.0", "--frozen"]\n'
        'env = ["UV_CACHE_DIR"]\nexpect = "version = \\"0.3.0\\""\n',
        extra={
            "uv.lock": (
                "version = 1\n"
                "revision = 3\n"
                'requires-python = ">=3.12"\n\n'
                "[[package]]\n"
                'name = "demo-widget"\n'
                'version = "0.1.0"\n'
                'source = { virtual = "." }\n'
            )
        },
    )

    assert _press(src_target, tmp_path) == 0
    lock = tomllib.loads((src_target / "uv.lock").read_text(encoding="utf-8"))
    root = next(row for row in lock["package"] if row["name"] == "potato-launcher")
    assert root["version"] == "0.3.0"


def test_final_pass_refuses_a_regeneration_that_undoes_an_earlier_edit(
    src_target: Path, tmp_path: Path, capsys
):
    """A later command can invalidate an edit after its immediate check.

    The regeneration writes a valid lockfile first, then silently restores the
    old version in ``pyproject.toml``. No source identity returns, so only the
    final edit ``expect`` recheck can catch this side write.
    """
    _prepare(
        src_target,
        '[[regenerate]]\nfile = "uv.lock"\ncommand = '
        + _argv(PY, "scripts/fakelock_undo_edit.py")
        + "\n\n"
        + _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.3.0"'
            ),
            expect='version = "0.3.0"',
        ),
        extra={
            "uv.lock": 'version = 1\n\n[[package]]\nname = "x"\nversion = "0.0.0"\n'
        },
    )

    assert _press(src_target, tmp_path) == 1
    err = capsys.readouterr().err
    assert "final pass: edit pyproject.toml" in err
    assert "does not contain the declared expect string" in err
    assert not (src_target / RECEIPT_REL).exists()


def test_receipt_edit_argument_preserves_all_legacy_positional_slots(
    tmp_path: Path,
):
    """Adding edits must not reinterpret existing positional callers."""
    report = ApplyReport(regenerated=["uv.lock"])
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        report,
        [("uv.lock", ("/tools/uv", "lock"))],
        ["CHANGELOG.md"],
        [("old.md", "retired")],
        [("uv.lock", "generated")],
        [
            (
                "pyproject.toml",
                ("/tools/uv", "version", "0.1.0", "--frozen"),
                'version = "0.1.0"',
            )
        ],
    )

    press = _receipt(tmp_path)["press"]
    assert press["reset"] == [{"file": "CHANGELOG.md"}]
    assert press["remove"] == [{"file": "old.md", "reason": "retired"}]
    assert press["exempt"] == [{"file": "uv.lock", "reason": "generated"}]
    assert press["edit"] == [
        {
            "file": "pyproject.toml",
            "argv": ["/tools/uv", "version", "0.1.0", "--frozen"],
            "expect": 'version = "0.1.0"',
        }
    ]


# ---------------------------------------------------------------------------
# 8. Edits are never verification-exempt
# ---------------------------------------------------------------------------
def test_edit_paths_never_reach_the_verify_exemption(
    src_target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A regeneration exemption names a path no downstream inventory scans:
    `press verify` reports it as NOT verified. An edit never buys that command-
    based exemption; the target's independent `verify_ignore` remains outside
    this test.

    Proven where the exemption is actually consumed — the verifier — by
    recording every path the helper hands it across a real `press verify`.
    """
    seen: list[tuple[str, str]] = []
    real = verifier_mod.exempt_regenerated_paths

    def recording(*args, **kwargs):
        result = real(*args, **kwargs)
        seen.extend(result)
        return result

    monkeypatch.setattr(verifier_mod, "exempt_regenerated_paths", recording)
    _prepare(
        src_target,
        '[[regenerate]]\nfile = "uv.lock"\ncommand = '
        + _argv(PY, "scripts/fakelock.py")
        + "\n\n"
        + _edit_block(
            "pyproject.toml",
            command=_argv(
                PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.2.0"'
            ),
            expect='version = "0.2.0"',
        ),
        extra={
            "uv.lock": 'version = 1\n\n[[package]]\nname = "x"\nversion = "0.0.0"\n'
        },
    )
    assert _press(src_target, tmp_path) == 0
    # verify re-discovers owner/repo_name from `origin`; the fixture's remote
    # still names the SOURCE repo, which is a guard refusal unrelated to edits.
    _git(
        src_target,
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{DEST.owner}/{DEST.repo_name}.git",
    )
    _git(src_target, "add", "-A")
    _git(src_target, "commit", "-q", "-m", "pressed")
    assert verify_command(["--target", str(src_target)]) == 0
    assert seen, "the exemption helper was never consulted — the test proves nothing"
    assert any(path == "uv.lock" for path, _ in seen)
    assert all(path != "pyproject.toml" for path, _ in seen)
    # Structural, not incidental: the helper reads [[regenerate]] only, so no
    # rename map or platform selection can ever route an edit into it.
    rules = load_rules(src_target)
    assert rules.edit and [p for p, _ in exempt_regenerated_paths(rules)] == ["uv.lock"]
    exempt = _receipt(src_target)["press"].get("exempt", [])
    assert {row["file"] for row in exempt} == {"uv.lock"}


# ---------------------------------------------------------------------------
# 9. Plan-time edit-target preflight
# ---------------------------------------------------------------------------
def _declare_edit_only(target: Path, file: str) -> None:
    (target / "press").mkdir(exist_ok=True)
    (target / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    (target / RULES_REL).write_text(
        _edit_block(file, command=_argv("true"), expect="x"), encoding="utf-8"
    )
    _git(target, "add", "press")
    _git(target, "commit", "-q", "-m", "declare edit")


class TestEditTargetPreflight:
    """The regeneration output preflight's five checks, applied to edit
    targets: containment, tracked, clean, no-follow regular file, sole link.
    Unlike a regeneration output, an edit target is NOT excluded from the
    rewrite — but it is just as destructively overwritten by the command, so
    git must hold a committed copy to restore from."""

    def test_tracked_clean_target_passes(self, src_target: Path):
        from template_press.rebrand.regen import preflight_edit_targets

        _declare_edit_only(src_target, "pyproject.toml")
        assert preflight_edit_targets(src_target, load_rules(src_target)) == []

    def test_untracked_target_refused(self, src_target: Path):
        from template_press.rebrand.regen import preflight_edit_targets

        (src_target / "notes.txt").write_text("x\n", encoding="utf-8")
        _declare_edit_only(src_target, "notes.txt")
        problems = preflight_edit_targets(src_target, load_rules(src_target))
        assert problems and "notes.txt" in problems[0]
        assert any("tracked" in p for p in problems)

    def test_dirty_target_refused(self, src_target: Path):
        from template_press.rebrand.regen import preflight_edit_targets

        _declare_edit_only(src_target, "pyproject.toml")
        (src_target / "pyproject.toml").write_text("# edited\n", encoding="utf-8")
        problems = preflight_edit_targets(src_target, load_rules(src_target))
        assert problems and "pyproject.toml" in problems[0]
        assert any("uncommitted" in p for p in problems)

    @requires_symlink
    def test_symlinked_target_refused(self, src_target: Path):
        from template_press.rebrand.regen import preflight_edit_targets

        os.symlink("pyproject.toml", src_target / "link.toml")
        _git(src_target, "add", "link.toml")
        _git(src_target, "commit", "-q", "-m", "symlink")
        _declare_edit_only(src_target, "link.toml")
        problems = preflight_edit_targets(src_target, load_rules(src_target))
        assert problems and "link.toml" in problems[0]
        # Containment refuses first and hardest: a symlinked target would
        # redirect the command's write out of the checked tree entirely.
        assert any("symlink" in p for p in problems)

    def test_hardlinked_target_refused(self, src_target: Path):
        from template_press.rebrand.regen import preflight_edit_targets

        _declare_edit_only(src_target, "pyproject.toml")
        os.link(src_target / "pyproject.toml", src_target.parent / "outside-link")
        problems = preflight_edit_targets(src_target, load_rules(src_target))
        assert problems and "pyproject.toml" in problems[0]
        assert any("hardlink" in p or "st_nlink" in p for p in problems)

    def test_dirty_target_refused_at_exit_2_even_under_allow_dirty(
        self, src_target: Path, tmp_path: Path, capsys, snapshot_target
    ):
        """--allow-dirty relaxes the whole-repo precondition, never this one:
        the declared command overwrites the file wholesale and git restores
        only committed content, so uncommitted work here has no undo path."""
        _prepare(
            src_target,
            _edit_block(
                "pyproject.toml",
                command=_argv(
                    PY, "scripts/subst.py", 'version = "0.1.0"', 'version = "0.2.0"'
                ),
                expect='version = "0.2.0"',
            ),
        )
        (src_target / "pyproject.toml").write_text("# uncommitted\n", encoding="utf-8")
        before = snapshot_target(src_target)
        code = _press(src_target, tmp_path, "--allow-dirty")
        captured = capsys.readouterr()
        assert code == 2
        assert "edit target pyproject.toml" in captured.err
        assert "uncommitted" in captured.err
        assert captured.out == ""  # refused before any plan output
        assert snapshot_target(src_target) == before
        assert not (src_target / RECEIPT_REL).exists()
