"""P17: no receipt when `press verify` would fail on the pressed target."""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.receipt import RECEIPT_REL

from .test_hyphen_package_name import DEST, _press, _settle, _target, _verify, _with


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"app_name": "zapp"}, "_zapp_"),
        ({"app_name": "zapp"}, "--zapp"),
        ({"app_name": "zapp"}, "zapp-cli"),
        ({"app_name": "zapp"}, "Zapp"),
        ({"package_name": "zapp_core"}, "ZAPP_CORE"),
        ({"package_name": "zapp_core"}, "zappCore"),
        ({"package_name": "zapp_core"}, "zapp.core"),
    ],
)
def test_press_refuses_receipt_when_verify_would_fail(
    tmp_path: Path, changes: dict[str, str], text: str
) -> None:
    target = _target(tmp_path, files={"NOTES.md": f"{text}\n"})
    source_config = (target / SOURCE_CONFIG_REL).read_text(encoding="utf-8")

    assert _press(tmp_path, target, _with(DEST, **changes)) == 1

    assert not (target / RECEIPT_REL).exists()
    assert (target / SOURCE_CONFIG_REL).read_text(encoding="utf-8") == source_config


def test_clean_press_still_writes_receipt_and_verifies(tmp_path: Path) -> None:
    target = _target(tmp_path, files={"NOTES.md": "acme_widget\n"})

    assert _press(tmp_path, target) == 0

    assert (target / RECEIPT_REL).is_file()
    _settle(target)
    assert _verify(target) == 0


def test_declared_keep_name_allows_the_press(tmp_path: Path) -> None:
    dest = _with(DEST, app_name="zapp")
    target = _target(
        tmp_path,
        files={"NOTES.md": "zapp-cli\n"},
        rules='[rules]\nkeep_names = ["zapp-cli"]\n',
    )

    assert _press(tmp_path, target, dest) == 0

    assert (target / RECEIPT_REL).is_file()
    _settle(target, dest)
    assert _verify(target) == 0
