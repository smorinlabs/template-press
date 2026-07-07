"""Identity model + boundary-safe token matching."""

import pytest

from template_press.rebrand.identity import (
    Identity,
    ValidationError,
    replace_token,
    token_occurs,
    token_pattern,
)


def make_identity(**overrides) -> Identity:
    base = {
        "package_name": "demo_widget",
        "repo_name": "demo-widget",
        "app_name": "press",
        "author": "Demo Author",
        "email": "demo@example.com",
        "owner": "demolabs",
    }
    base.update(overrides)
    return Identity(**base)


def test_app_name_upper_is_derived():
    ident = make_identity()
    assert ident.app_name_upper == "PRESS"
    assert ident.as_dict()["app_name_upper"] == "PRESS"


def test_as_dict_has_all_seven_fields():
    keys = set(make_identity().as_dict())
    assert keys == {
        "package_name",
        "repo_name",
        "app_name",
        "app_name_upper",
        "author",
        "email",
        "owner",
    }


def test_validate_accepts_good_identity():
    make_identity().validate()  # must not raise


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("package_name", "Demo-Widget"),
        ("repo_name", "Demo_Widget"),
        ("app_name", "my-app"),
        ("email", "not-an-email"),
        ("owner", "-bad-"),
    ],
)
def test_validate_rejects_bad_values(field, bad):
    with pytest.raises(ValidationError):
        make_identity(**{field: bad}).validate()


def test_from_mapping_round_trip():
    ident = make_identity()
    data = {k: v for k, v in ident.as_dict().items() if k != "app_name_upper"}
    assert Identity.from_mapping(data) == ident


def test_from_mapping_missing_key_raises():
    with pytest.raises(ValidationError, match="app_name"):
        Identity.from_mapping({"package_name": "x"})


# --- boundary safety: the C-1/INIT-02 regression tests -------------------

PROSE = "Compress the archive; express delivery raises pressure. Run press now."


def test_app_name_replacement_spares_english_words():
    out = replace_token(PROSE, "app_name", "press", "potato")
    assert "Compress" in out and "express" in out and "pressure" in out
    assert out.endswith("Run potato now.")


def test_app_name_matches_env_var_and_file_prefix_positions():
    # underscore is a separator on the RIGHT of app_name (press_config.toml)
    assert replace_token("press_config.toml", "app_name", "press", "potato") == (
        "potato_config.toml"
    )
    # but not on the left (foo_press is not the token)
    assert token_occurs("foo_press", "app_name", "press") is False


def test_app_name_upper_env_prefix_replaced():
    text = "export PRESS_LOG_LEVEL=debug  # _PRESS_COMPLETE too"
    out = replace_token(text, "app_name_upper", "PRESS", "POTATO")
    assert "POTATO_LOG_LEVEL" in out and "_POTATO_COMPLETE" in out


def test_app_name_upper_spares_embedded_words():
    assert (
        replace_token("EXPRESS IMPRESSION", "app_name_upper", "PRESS", "POTATO")
        == "EXPRESS IMPRESSION"
    )


def test_long_tokens_use_plain_substring():
    assert token_pattern("package_name", "demo_widget") is None
    out = replace_token(
        "import demo_widget.cli", "package_name", "demo_widget", "potato_launcher"
    )
    assert out == "import potato_launcher.cli"
