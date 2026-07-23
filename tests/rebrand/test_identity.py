"""Identity model + boundary-safe token matching."""

import pytest

from template_press.rebrand.identity import (
    DISPLAY_FORM_NAMES,
    Identity,
    ValidationError,
    display_forms,
    replace_token,
    token_occurs,
    token_pattern,
    validate_display_name,
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


def test_all_fields_are_boundary_matched():
    # OQ12: boundary-safe replacement is the default for every field.
    assert token_pattern("package_name", "demo_widget") is not None
    out = replace_token(
        "import demo_widget.cli", "package_name", "demo_widget", "potato_launcher"
    )
    assert out == "import potato_launcher.cli"
    # underscore stays a separator: compound names still rewrite
    assert (
        replace_token(
            "demo_widget_extra.py", "package_name", "demo_widget", "potato_launcher"
        )
        == "potato_launcher_extra.py"
    )
    # but letter-adjacent occurrences do not
    assert (
        replace_token("xdemo_widget", "package_name", "demo_widget", "p")
        == "xdemo_widget"
    )


def test_short_owner_author_do_not_rewrite_inside_words():
    assert replace_token("ongoing work", "owner", "go", "potatolabs") == (
        "ongoing work"
    )
    assert replace_token("go run it", "owner", "go", "potatolabs") == (
        "potatolabs run it"
    )
    assert replace_token("Announcement", "author", "Ann", "Potato Farmer") == (
        "Announcement"
    )


def test_app_name_upper_rewrites_digit_suffixed_codes():
    text = "raise PressError('PRESS000') from PRESS_LOG"
    out = replace_token(text, "app_name_upper", "PRESS", "POTATO")
    assert "POTATO000" in out and "POTATO_LOG" in out
    assert replace_token("EXPRESS", "app_name_upper", "PRESS", "POTATO") == ("EXPRESS")


def test_empty_author_is_rejected():
    with pytest.raises(ValidationError, match="author"):
        make_identity(author="").validate()
    with pytest.raises(ValidationError, match="author"):
        make_identity(author="line\nbreak").validate()


def test_token_pattern_refuses_empty_value():
    with pytest.raises(ValidationError, match="empty"):
        token_pattern("author", "")


def test_replacement_is_literal_not_a_regex_template():
    out = replace_token("by Old Name.", "author", "Old Name", r"C:\Users\1 Bob")
    assert out == r"by C:\Users\1 Bob."


# --- display_name field and form derivation (Task 1) ----------------------


def _identity(**overrides):
    base = {
        "package_name": "py_launch_blueprint",
        "repo_name": "py-launch-blueprint",
        "app_name": "plbp",
        "author": "Steve Morin",
        "email": "steve.morin@gmail.com",
        "owner": "smorinlabs",
    }
    base.update(overrides)
    return Identity(**base)


class TestDisplayName:
    def test_validator_accepts_spaced_title(self):
        assert validate_display_name("Py Launch Blueprint") == "Py Launch Blueprint"

    def test_validator_rejects_empty_and_control_chars(self):
        with pytest.raises(ValidationError):
            validate_display_name("   ")
        with pytest.raises(ValidationError):
            validate_display_name("Py\x00Launch")

    def test_field_defaults_to_none_and_is_absent_from_dicts(self):
        ident = _identity()
        assert ident.display_name is None
        assert "display_name" not in ident.as_dict()
        assert "display_name" not in ident.as_dict_prompted()

    def test_field_present_appears_in_dicts_and_validates(self):
        ident = _identity(display_name="Py Launch Blueprint")
        assert ident.as_dict()["display_name"] == "Py Launch Blueprint"
        assert ident.as_dict_prompted()["display_name"] == "Py Launch Blueprint"
        ident.validate()  # must not raise

    def test_validate_rejects_bad_display_name(self):
        with pytest.raises(ValidationError):
            _identity(display_name="\x01").validate()

    def test_from_mapping_optional_display_name(self):
        data = _identity().as_dict_prompted()
        assert Identity.from_mapping(data).display_name is None
        data["display_name"] = "Py Launch Blueprint"
        assert Identity.from_mapping(data).display_name == "Py Launch Blueprint"


class TestDisplayForms:
    def test_three_forms_from_title_case(self):
        forms = display_forms("Py Launch Blueprint")
        assert forms == {
            "spaced": "Py Launch Blueprint",
            "pascal": "PyLaunchBlueprint",
            "camel": "pyLaunchBlueprint",
        }
        assert tuple(forms) == DISPLAY_FORM_NAMES

    def test_forms_capitalize_lowercase_words(self):
        forms = display_forms("acme widget")
        assert forms["pascal"] == "AcmeWidget"
        assert forms["camel"] == "acmeWidget"

    def test_single_word_keeps_inner_casing(self):
        forms = display_forms("NumPy")
        assert forms == {"spaced": "NumPy", "pascal": "NumPy", "camel": "numPy"}
