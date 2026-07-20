"""The `press` noun-verb dispatcher (console-script entry)."""

import pytest

from template_press.press_cli import main


def test_bare_invocation_lists_verbs(capsys):
    code = main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "rebrand" in out
    assert "provision" in out and "M6" in out


def test_help_flag_lists_verbs(capsys):
    assert main(["-h"]) == 0
    assert "rebrand" in capsys.readouterr().out


def test_unknown_verb_exits_2(capsys):
    assert main(["frobnicate"]) == 2
    assert "unknown" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("verb", ["provision", "status"])
def test_reserved_verbs_exit_2_with_m6_note(verb, capsys):
    assert main([verb, "--target", "."]) == 2
    assert "M6" in capsys.readouterr().err


def test_rebrand_delegates_and_enforces_target():
    # `rebrand` delegates to the rebrand CLI, whose argparse exits 2 when the
    # required --target is absent.
    with pytest.raises(SystemExit) as exc:
        main(["rebrand"])
    assert exc.value.code == 2


def test_version_flag(capsys):
    from template_press import __version__

    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == f"press {__version__}"


def test_verify_help_exits_0(capsys):
    # argparse --help raises SystemExit(0) instead of returning 0
    with pytest.raises(SystemExit) as exc:
        main(["verify", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "verify" in out or "hermetic" in out


def test_unknown_verb_bogus_exits_2(capsys):
    assert main(["bogus"]) == 2
    assert "unknown" in capsys.readouterr().err.lower()
