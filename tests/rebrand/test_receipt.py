import os
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.receipt import RECEIPT_REL, read_receipt, write_receipt
from template_press.rebrand.safety import ContainmentError

from .conftest import DEST, SOURCE, requires_symlink


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
