"""``[verify]`` configuration for `press verify` (Task 9).

`parse_verify_config` is PURE (no file I/O): it takes the already-loaded
`[verify]` TOML mapping (or ``None`` when the table is absent) and returns a
`VerifyConfig`. Defaults deliberately exclude `app_name_upper` (the matcher
is case-insensitive, so scanning `app_name` already covers it) and `email`
(opt in via `extra_fields`).
"""

from __future__ import annotations

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.ignores import Ignore
from template_press.rebrand.verify_config import VerifyConfig, parse_verify_config


def test_defaults_no_table():
    config = parse_verify_config(None)
    assert config == VerifyConfig(
        fields=("app_name", "package_name", "repo_name", "owner"),
        substring_fields=frozenset(),
        ignores=(),
        equal_fields="warn",
    )


def test_defaults_empty_table():
    assert parse_verify_config({}) == parse_verify_config(None)


def test_extra_fields_appends_dedup_order_preserving():
    config = parse_verify_config({"extra_fields": ["email", "package_name", "email"]})
    # email is new -> appended once; package_name is already a default ->
    # not duplicated; original default order is preserved.
    assert config.fields == (
        "app_name",
        "package_name",
        "repo_name",
        "owner",
        "email",
    )


def test_unknown_extra_field_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_verify_config({"extra_fields": ["not_a_real_field"]})


def test_substring_fields_parsed():
    config = parse_verify_config({"substring_fields": ["package_name"]})
    assert config.substring_fields == frozenset({"package_name"})


def test_substring_field_not_in_fields_raises_validation_error():
    with pytest.raises(ValidationError):
        # "email" is not in the (default) effective fields set.
        parse_verify_config({"substring_fields": ["email"]})


def test_equal_fields_error_parsed():
    config = parse_verify_config({"equal_fields": "error"})
    assert config.equal_fields == "error"


def test_equal_fields_invalid_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_verify_config({"equal_fields": "ignore"})


def test_verify_ignore_table_with_ordinal_parses_into_ignore():
    config = parse_verify_config(
        {
            "ignore": [
                {
                    "field": "package_name",
                    "value": "demo_widget",
                    "file": "README.md",
                    "anchor": "demo_widget",
                    "line": 3,
                    "ordinal": 1,
                    "reason": "second occurrence is intentional",
                }
            ]
        }
    )
    assert config.ignores == (
        Ignore(
            field="package_name",
            value="demo_widget",
            file="README.md",
            anchor="demo_widget",
            line=3,
            ordinal=1,
            force=False,
            reason="second occurrence is intentional",
        ),
    )


def test_verify_ignore_table_missing_optionals_default():
    config = parse_verify_config(
        {"ignore": [{"field": "io", "file": "assets/logo.bin", "anchor": "assets/"}]}
    )
    assert config.ignores == (
        Ignore(
            field="io",
            value=None,
            file="assets/logo.bin",
            anchor="assets/",
            line=None,
            ordinal=None,
            force=False,
            reason="",
        ),
    )


def test_unknown_top_level_key_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_verify_config({"typo_kye": True})


def test_raw_fields_key_not_accepted():
    # Only `extra_fields` (append) is settable — a raw `fields` key is a
    # typo/misunderstanding of the append-only model, not silently honored.
    with pytest.raises(ValidationError):
        parse_verify_config({"fields": ["app_name"]})


# --- fail-closed shape validation (malformed TOML) ---------------------


def test_extra_fields_non_list_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a list of strings"):
        parse_verify_config({"extra_fields": 42})


def test_extra_fields_bare_string_raises_validation_error():
    # A bare str is iterable (char-by-char) — must be rejected as a shape
    # error, not silently walked as ["e", "m", "a", "i", "l"].
    with pytest.raises(ValidationError, match="must be a list of strings"):
        parse_verify_config({"extra_fields": "email"})


def test_extra_fields_non_str_element_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a list of strings"):
        parse_verify_config({"extra_fields": ["email", 42]})


def test_substring_fields_non_list_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a list of strings"):
        parse_verify_config({"substring_fields": 42})


def test_substring_fields_non_str_element_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a list of strings"):
        parse_verify_config({"substring_fields": ["package_name", 42]})


def test_ignore_non_list_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a list of tables"):
        parse_verify_config({"ignore": "x"})


def test_ignore_entry_non_dict_raises_validation_error():
    with pytest.raises(ValidationError, match="must be a table"):
        parse_verify_config({"ignore": [1]})


def test_ignore_entry_unknown_key_raises_validation_error():
    with pytest.raises(ValidationError, match="unknown key"):
        parse_verify_config(
            {
                "ignore": [
                    {
                        "field": "app_name",
                        "file": "a",
                        "anchor": "a",
                        "raeson": "typo for reason",
                    }
                ]
            }
        )


def test_equal_fields_non_str_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_verify_config({"equal_fields": 42})


def test_non_dict_table_int_raises_validation_error():
    # A scalar top-level [verify] value (e.g. `verify = 42`) must fail closed
    # with ValidationError, not a raw TypeError from `set(table)`.
    with pytest.raises(ValidationError, match="must be a table"):
        parse_verify_config(42)


def test_non_dict_table_bool_raises_validation_error():
    # bool is an int subclass in Python — must still be rejected as non-dict.
    with pytest.raises(ValidationError, match="must be a table"):
        parse_verify_config(True)
