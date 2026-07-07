import tomllib
from dataclasses import replace
from pathlib import Path

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.receipt import RECEIPT_REL, read_receipt, write_receipt

from .conftest import DEST, SOURCE


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
