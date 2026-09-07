"""File-removal verification retains its actionable configuration diagnostic."""

from __future__ import annotations

import pytest

from template_press.rebrand.verify_cli import verify_command

from .test_remove_rules import REMOVE_NOTES, _write_rules
from .test_verify_cli import _commit, make_pressable


@pytest.mark.parametrize("as_json", [False, True])
def test_stale_file_removal_keeps_configuration_remedy(tmp_path, capsys, as_json):
    repo = make_pressable(tmp_path)
    _write_rules(repo, REMOVE_NOTES)
    _commit(repo)
    before = (repo / "press/press-source.toml").read_bytes()
    argv = ["--target", str(repo)]
    if as_json:
        argv.append("--json")

    assert verify_command(argv) == 2
    captured = capsys.readouterr()
    assert captured.err == (
        "error: [[remove]] target docs/legacy-notes.md does not exist and no "
        "receipt records its removal — a stale declaration is config drift; "
        "delete it or restore the file\n"
    )
    assert captured.out == ""
    assert (repo / "press/press-source.toml").read_bytes() == before
    assert not (repo / "press/press-receipt.toml").exists()
