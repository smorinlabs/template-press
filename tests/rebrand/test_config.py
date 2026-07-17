import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from template_press.rebrand.config import (
    SOURCE_CONFIG_REL,
    load_answers,
    load_source_config,
    render_source_config,
)
from template_press.rebrand.identity import ValidationError

from .conftest import DEST, SOURCE


def test_source_config_round_trip(tmp_path: Path):
    (tmp_path / "press").mkdir()
    (tmp_path / SOURCE_CONFIG_REL).write_text(
        render_source_config(SOURCE), encoding="utf-8"
    )
    assert load_source_config(tmp_path, override=None) == SOURCE


def test_load_source_config_absent_returns_none(tmp_path: Path):
    assert load_source_config(tmp_path, override=None) is None


def test_load_source_config_override_path(tmp_path: Path):
    p = tmp_path / "elsewhere.toml"
    p.write_text(render_source_config(SOURCE), encoding="utf-8")
    assert load_source_config(tmp_path, override=p) == SOURCE


def test_load_answers_answers_table(tmp_path: Path):
    p = tmp_path / "answers.toml"
    p.write_text(
        "[answers]\n"
        + "\n".join(f'{k} = "{v}"' for k, v in DEST.as_dict_prompted().items())
        + "\n",
        encoding="utf-8",
    )
    assert load_answers(p) == DEST


def test_missing_field_raises_validation_error(tmp_path: Path):
    p = tmp_path / "answers.toml"
    p.write_text('[answers]\npackage_name = "x_only"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_answers(p)


def test_render_source_config_escapes_quotes_in_author(tmp_path: Path):
    source = replace(SOURCE, author='Demo "Quoted" Author')
    rendered = render_source_config(source)
    data = tomllib.loads(rendered)
    assert data["identity"]["author"] == 'Demo "Quoted" Author'

    (tmp_path / "press").mkdir()
    (tmp_path / SOURCE_CONFIG_REL).write_text(rendered, encoding="utf-8")
    assert load_source_config(tmp_path, override=None) == source
