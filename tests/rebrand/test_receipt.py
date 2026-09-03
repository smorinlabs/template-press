import os
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import (
    RECEIPT_REL,
    OriginDecision,
    accepted_origin_from_receipt,
    read_receipt,
    write_receipt,
)
from template_press.rebrand.safety import ContainmentError

from .conftest import DEST, SOURCE, requires_symlink


def test_read_receipt_non_utf8_raises_validation_error(tmp_path: Path):
    """Issue #86: a corrupted or hand-edited receipt must fail clean, not
    crash the caller with a raw UnicodeDecodeError."""
    press_dir = tmp_path / "press"
    press_dir.mkdir()
    (press_dir / "press-receipt.toml").write_bytes(
        b"[press]\nverified = true\n\xff\xfe"
    )
    with pytest.raises(ValidationError, match="UTF-8"):
        read_receipt(tmp_path)


def test_write_and_read_receipt(tmp_path: Path):
    report = ApplyReport(replaced=["README.md"], renamed=[("a", "b")])
    path = write_receipt(tmp_path, SOURCE, DEST, report)
    assert path == tmp_path / RECEIPT_REL
    raw = read_receipt(tmp_path)
    assert raw is not None
    data = tomllib.loads(raw)
    assert data["press"]["verified"] is True
    assert data["press"]["from"]["package_name"] == "demo_widget"
    assert data["press"]["to"]["package_name"] == "potato_launcher"
    assert data["press"]["counts"]["replaced"] == 1


def test_read_receipt_absent(tmp_path: Path):
    assert read_receipt(tmp_path) is None


@requires_symlink
def test_write_receipt_refuses_symlinked_press_dir(tmp_path: Path):
    """D8: write_receipt routes through write_control, so a symlinked press/
    control dir is refused and nothing is written through the link."""
    decoy = tmp_path / "outside" / "decoy"
    decoy.mkdir(parents=True)
    os.symlink(decoy, tmp_path / "press", target_is_directory=True)
    with pytest.raises(ContainmentError):
        write_receipt(tmp_path, SOURCE, DEST, ApplyReport())
    assert list(decoy.iterdir()) == []  # nothing written through the symlink


def test_write_and_read_receipt_escapes_special_chars(tmp_path: Path):
    source = replace(SOURCE, author='Demo "Quoted" Back\\slash')
    dest = replace(DEST, author="Line1\nLine2")
    report = ApplyReport()
    write_receipt(tmp_path, source, dest, report)
    raw = read_receipt(tmp_path)
    assert raw is not None
    data = tomllib.loads(raw)
    assert data["press"]["from"]["author"] == 'Demo "Quoted" Back\\slash'
    assert data["press"]["to"]["author"] == "Line1\nLine2"


def test_origin_mismatch_accepted_is_a_sorted_inline_table(tmp_path: Path):
    """The accepted origin VALUES (not merely the field names) are recorded,
    keys sorted, so `press verify` can waive exactly those and nothing else."""
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        origin=OriginDecision(
            mismatch_accepted=(("repo_name", "else"), ("owner", "someone")),
        ),
    )
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert 'origin_mismatch_accepted = { owner = "someone", repo_name = "else" }' in raw
    assert tomllib.loads(raw)["press"]["origin_mismatch_accepted"] == {
        "owner": "someone",
        "repo_name": "else",
    }
    assert accepted_origin_from_receipt(raw) == {
        "owner": "someone",
        "repo_name": "else",
    }


def test_origin_mismatch_accepted_round_trips_special_characters(tmp_path: Path):
    """The value comes straight from `.git/config` and is never validated, so
    the writer must escape it and the reader must return it verbatim."""
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        origin=OriginDecision(mismatch_accepted=(("owner", 'some"one\x1b'),)),
    )
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert accepted_origin_from_receipt(raw) == {"owner": 'some"one\x1b'}


def test_accepted_origin_from_receipt_omits_the_key_when_nothing_was_accepted(
    tmp_path: Path,
):
    write_receipt(tmp_path, SOURCE, DEST, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert "origin_mismatch_accepted" not in raw
    assert accepted_origin_from_receipt(raw) == {}


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "[press\nnot toml",
        "press = 1\n",
        # The 4.1 list form: field names with no values — unusable, and
        # trusting it would waive ANY future origin value for those fields.
        '[press]\norigin_mismatch_accepted = ["owner", "repo_name"]\n',
        "[press]\norigin_mismatch_accepted = 3\n",
    ],
)
def test_accepted_origin_from_receipt_tolerates_garbage(text: str | None):
    assert accepted_origin_from_receipt(text) == {}


def test_accepted_origin_from_receipt_drops_non_string_values():
    text = "[press]\norigin_mismatch_accepted = { owner = 3, repo_name = 'else' }\n"
    assert accepted_origin_from_receipt(text) == {"repo_name": "else"}
