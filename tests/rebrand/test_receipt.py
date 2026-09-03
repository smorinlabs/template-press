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
    receipt_binding_problem,
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


def test_receipt_binding_problem_accepts_a_verified_press_of_this_identity(
    tmp_path: Path,
):
    """`[press.to]` is the press's own record of the identity it wrote into
    `press-source.toml`, so a genuine receipt binds to that same identity."""
    write_receipt(tmp_path, SOURCE, DEST, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert receipt_binding_problem(raw, DEST) is None


def test_receipt_binding_problem_rejects_another_repo_s_identity(tmp_path: Path):
    write_receipt(tmp_path, SOURCE, DEST, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    other = replace(DEST, owner="otherlabs")
    assert receipt_binding_problem(raw, other) == (
        "[press.to] does not match press-source.toml"
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "[press\nnot toml",
        # No `verified = true`: not a completed, verified press.
        '[press]\norigin_mismatch_accepted = { owner = "someone" }\n',
        "[press]\nverified = false\n",
    ],
)
def test_receipt_binding_problem_rejects_a_non_press(text: str | None):
    assert receipt_binding_problem(text, DEST) == "receipt is not a verified press"


def test_receipt_binding_problem_rejects_a_verified_receipt_without_an_identity():
    """`verified = true` alone proves nothing about WHICH target: with no
    `[press.to]` there is no identity to bind against."""
    assert receipt_binding_problem("[press]\nverified = true\n", DEST) == (
        "[press.to] does not match press-source.toml"
    )


def test_receipt_binding_problem_rejects_an_extra_receipt_field(tmp_path: Path):
    """Key-set equality, not one-way containment (fix round 2): deleting an
    optional field from press-source.toml must not leave the old receipt —
    which still carries it — honored."""
    write_receipt(
        tmp_path, SOURCE, replace(DEST, display_name="Potato Launcher"), ApplyReport()
    )
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert "display_name" in raw
    assert receipt_binding_problem(raw, DEST) == (
        "[press.to] does not match press-source.toml"
    )


def test_receipt_binding_problem_rejects_a_missing_receipt_field(tmp_path: Path):
    """The mirror case: the source-config declares a field the receipt never
    recorded, so the receipt describes a different identity."""
    write_receipt(tmp_path, SOURCE, DEST, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert receipt_binding_problem(
        raw, replace(DEST, display_name="Potato Launcher")
    ) == ("[press.to] does not match press-source.toml")


def test_receipt_binding_problem_display_name_participates_on_both_sides(
    tmp_path: Path,
):
    """A display name declared on both sides is compared like any other
    field: equal binds, different does not."""
    dest = replace(DEST, display_name="Potato Launcher")
    write_receipt(tmp_path, SOURCE, dest, ApplyReport())
    raw = read_receipt(tmp_path)
    assert raw is not None
    assert receipt_binding_problem(raw, dest) is None
    assert receipt_binding_problem(raw, replace(dest, display_name="Spud Thrower")) == (
        "[press.to] does not match press-source.toml"
    )
