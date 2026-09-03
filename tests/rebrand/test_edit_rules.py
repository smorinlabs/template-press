"""P09-TS01 — [[edit]] schema + config-load validation (E4).

E4: an in-place edit is fully target-declared — one [[edit]] table per edited
file carrying `file`/`command`/`expect` (+ optional `env`/`platforms`),
validated at config load.

The exclusion contract is the INVERSE of [[regenerate]]'s: an edit target must
NOT be listed in exclude_files, because the replace pass rewrites the file
first and the declared command then edits that rewritten file in place. Two
keys [[regenerate]] accepts are deliberately refused here — `verify_exempt`
and `scan` — because an edited file stays wholly inside the doctor's and
`press verify`'s scan; there is no exemption to buy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.rules import (
    DEFAULT_RULES,
    EditRule,
    RegenerateRule,
    RemoveRule,
    ReplaceRule,
    ResetRule,
    Rules,
    load_rules,
    load_selected_rules,
)


def _write_rules(target: Path, body: str) -> Path:
    d = target / "press"
    d.mkdir(exist_ok=True, parents=True)
    (d / "press-rules.toml").write_text(body, encoding="utf-8")
    return target


# The canonical declaration from the E4 design note. `pyproject.toml` is NOT
# in exclude_files (default or extra) — that is the point of the mechanism.
EDIT_PYPROJECT = (
    "[[edit]]\n"
    'file = "pyproject.toml"\n'
    'command = ["uv", "version", "0.1.0", "--frozen"]\n'
    "expect = 'version = \"0.1.0\"'\n"
)


# ---------------------------------------------------------------------------
# Schema — shape, types, and config-load validation
# ---------------------------------------------------------------------------
class TestEditSchema:
    def test_valid_entry_parses(self, tmp_path: Path):
        target = _write_rules(tmp_path, EDIT_PYPROJECT)
        (rule,) = load_rules(target).edit
        assert isinstance(rule, EditRule)
        assert rule.file == "pyproject.toml"
        assert rule.command == ("uv", "version", "0.1.0", "--frozen")
        assert rule.expect == 'version = "0.1.0"'
        assert rule.env == ()

    def test_env_parses_when_declared(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            "[[edit]]\n"
            'file = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0"]\n'
            'expect = "0.1.0"\n'
            'env = ["UV_CACHE_DIR", "HOME"]\n',
        )
        (rule,) = load_rules(target).edit
        assert rule.env == ("UV_CACHE_DIR", "HOME")

    def test_no_declarations_is_empty(self, tmp_path: Path):
        target = _write_rules(tmp_path, '[rules]\nverify_ignore = ["vendor"]\n')
        assert load_rules(target).edit == ()

    def test_entry_must_be_table(self, tmp_path: Path):
        target = _write_rules(tmp_path, 'edit = "pyproject.toml"\n')
        with pytest.raises(ValidationError):
            load_rules(target)

    def test_unknown_key_rejected(self, tmp_path: Path):
        target = _write_rules(tmp_path, EDIT_PYPROJECT + "shell = true\n")
        with pytest.raises(ValidationError, match="shell"):
            load_rules(target)


# ---------------------------------------------------------------------------
# The six refusals named in the Task 12 brief, in brief order
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("body", "needle"),
    [
        (
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n' + EDIT_PYPROJECT,
            "must not be listed in exclude_files",
        ),
        (
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["uv", "version", "0.1.0"]\n',
            "expect is required",
        ),
        (EDIT_PYPROJECT + "verify_exempt = true\n", "unknown key"),
        (EDIT_PYPROJECT + 'scan = "boundary"\n', "unknown key"),
        (
            EDIT_PYPROJECT + '[[reset]]\nfile = "pyproject.toml"\nstub = ""\n',
            "may not also be",
        ),
    ],
)
def test_edit_rule_refusals(tmp_path: Path, body: str, needle: str):
    _write_rules(tmp_path, body)
    with pytest.raises(ValidationError, match=needle):
        load_rules(tmp_path)


# ---------------------------------------------------------------------------
# `expect`: required, non-empty, printable
# ---------------------------------------------------------------------------
class TestExpectValidation:
    """`expect` is the post-condition substring the edited file must contain
    after the command runs. An empty or whitespace-only value matches almost
    any file, so it would assert nothing; a non-printable one cannot be shown
    in the plan or the receipt."""

    @pytest.mark.parametrize(
        ("expect_toml", "needle"),
        [
            ("", "expect is required"),  # missing entirely
            ('expect = ""', "expect is required"),  # empty
            ('expect = "   "', "expect is required"),  # whitespace-only
            ("expect = 3", "expect is required"),  # non-string
            ('expect = ["0.1.0"]', "expect is required"),  # list, not string
            ('expect = "ver\\u0000sion"', "control or non-printable"),  # NUL
            ('expect = "ver\\u001b[2Jsion"', "control or non-printable"),  # ANSI
            ('expect = "ver\\nsion"', "control or non-printable"),  # newline
        ],
    )
    def test_malformed_expect_rejected(
        self, tmp_path: Path, expect_toml: str, needle: str
    ):
        target = _write_rules(
            tmp_path,
            "[[edit]]\n"
            'file = "pyproject.toml"\n'
            'command = ["uv", "version", "0.1.0"]\n'
            f"{expect_toml}\n",
        )
        with pytest.raises(ValidationError, match=needle):
            load_rules(target)

    def test_missing_expect_names_the_key(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["uv", "version"]\n',
        )
        with pytest.raises(ValidationError, match="expect is required"):
            load_rules(target)


# ---------------------------------------------------------------------------
# `command` / `env` — the same contracts [[regenerate]] enforces
# ---------------------------------------------------------------------------
class TestCommandValidation:
    """Parity with [[regenerate]]: a non-empty list of non-empty strings with
    no control characters (the exact argv — no shell)."""

    @pytest.mark.parametrize(
        "command_toml",
        [
            "command = []",  # empty list
            'command = ["uv", ""]',  # empty element
            'command = ["uv", 3]',  # non-string element
            'command = "uv version"',  # string, not list
            'command = ["uv\\u0000x"]',  # NUL in element
            'command = ["uv\\u001b[2Jx"]',  # ANSI escape in element
            "",  # missing entirely
        ],
    )
    def test_malformed_command_rejected(self, tmp_path: Path, command_toml: str):
        target = _write_rules(
            tmp_path,
            f'[[edit]]\nfile = "pyproject.toml"\n{command_toml}\nexpect = "x"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)


class TestEnvValidation:
    """Parity with [[regenerate]]: `env` lists variable NAMES, never values."""

    @pytest.mark.parametrize(
        "env_toml",
        [
            'env = ["A=B"]',  # a value, not a name
            'env = [""]',
            'env = ["A\\u0000B"]',
            'env = "UV_CACHE_DIR"',  # string, not list
            "env = [3]",  # non-string element
        ],
    )
    def test_malformed_env_rejected(self, tmp_path: Path, env_toml: str):
        target = _write_rules(
            tmp_path,
            "[[edit]]\n"
            'file = "pyproject.toml"\n'
            'command = ["uv", "version"]\n'
            'expect = "x"\n'
            f"{env_toml}\n",
        )
        with pytest.raises(ValidationError):
            load_rules(target)


# ---------------------------------------------------------------------------
# `file` — contained relative path, never a control file, never excluded
# ---------------------------------------------------------------------------
class TestFileValidation:
    @pytest.mark.parametrize(
        "file_toml",
        [
            'file = "/etc/passwd"',  # absolute
            'file = "../outside.toml"',  # traversal
            'file = ".git/config"',  # .git component
            'file = ""',  # empty
            "file = 3",  # non-string
            "",  # missing
            'file = "pyproject\\ntoml"',  # newline
            'file = "pyproject\\u001b[2Jx.toml"',  # ANSI escape
            'file = "pyproject\\rx.toml"',  # carriage return
        ],
    )
    def test_unsafe_file_rejected(self, tmp_path: Path, file_toml: str):
        target = _write_rules(
            tmp_path,
            f'[[edit]]\n{file_toml}\ncommand = ["true"]\nexpect = "x"\n',
        )
        with pytest.raises(ValidationError):
            load_rules(target)

    @pytest.mark.parametrize(
        "reserved",
        [
            "press/press-receipt.toml",
            "press/press-source.toml",
            "PRESS/press-source.toml",
            "press/press-source.toml.",
            "press/press-source.toml ",
        ],
    )
    def test_root_control_rejected(self, tmp_path: Path, reserved: str):
        """press writes its own control files after validation (reserved) —
        a declared command may not edit them."""
        target = _write_rules(
            tmp_path,
            f'[[edit]]\nfile = "{reserved}"\ncommand = ["true"]\nexpect = "x"\n',
        )
        with pytest.raises(ValidationError, match="control"):
            load_rules(target)

    def test_target_in_extra_exclude_files_rejected(self, tmp_path: Path):
        """The INVERSE of [[regenerate]]'s rule: excluding an edit target
        would deny it the replace pass, so the command would edit a file
        still carrying the SOURCE identity."""
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n' + EDIT_PYPROJECT,
        )
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        assert "must not be listed in exclude_files" in str(exc.value)

    def test_target_in_default_exclude_files_rejected(self, tmp_path: Path):
        """The default exclusion set counts too — no extra_exclude_files
        entry is needed to trip the refusal."""
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "CHANGELOG.md"\ncommand = ["true"]\nexpect = "x"\n',
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_non_excluded_target_accepted(self, tmp_path: Path):
        target = _write_rules(tmp_path, EDIT_PYPROJECT)
        (rule,) = load_rules(target).edit
        assert rule.file == "pyproject.toml"


# ---------------------------------------------------------------------------
# One writer per file per platform
# ---------------------------------------------------------------------------
class TestWriterOverlaps:
    """An edit target may not also be a reset, remove, or regenerate target on
    any platform, and two [[edit]] tables may not claim one file on a shared
    platform — the same one-writer invariant the sibling mechanisms carry."""

    @pytest.mark.parametrize(
        "other",
        [
            '[[reset]]\nfile = "pyproject.toml"\nstub = ""\n',
            '[[remove]]\nfile = "pyproject.toml"\nreason = "template-only"\n',
            '[[regenerate]]\nfile = "pyproject.toml"\ncommand = ["true"]\n',
        ],
    )
    def test_overlap_with_other_writer_rejected(self, tmp_path: Path, other: str):
        target = _write_rules(tmp_path, EDIT_PYPROJECT + other)
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        assert "may not also be a reset/remove/regenerate target" in str(exc.value)

    def test_duplicate_edit_targets_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            EDIT_PYPROJECT
            + '[[edit]]\nfile = "pyproject.toml"\ncommand = ["b"]\nexpect = "y"\n',
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(target)

    def test_partial_platform_overlap_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["a"]\n'
            'expect = "x"\nplatforms = ["darwin", "linux"]\n'
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["b"]\n'
            'expect = "y"\nplatforms = ["linux"]\n',
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(target)

    def test_platform_disjoint_duplicate_edits_accepted(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["mac"]\n'
            'expect = "x"\nplatforms = ["darwin"]\n'
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["nix"]\n'
            'expect = "y"\nplatforms = ["linux"]\n',
        )
        (rule,) = load_selected_rules(target, platform="darwin").rules.edit
        assert rule.command == ("mac",)

    def test_platform_disjoint_edit_and_remove_accepted(self, tmp_path: Path):
        """[[remove]] carries no exclude_files requirement, so an edit/remove
        pair on disjoint platforms is the reachable proof that the overlap
        ban is platform-aware rather than global."""
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["a"]\n'
            'expect = "x"\nplatforms = ["darwin"]\n'
            '[[remove]]\nfile = "pyproject.toml"\nreason = "r"\n'
            'platforms = ["linux"]\n',
        )
        selected = load_selected_rules(target, platform="darwin").rules
        assert [rule.file for rule in selected.edit] == ["pyproject.toml"]
        assert selected.remove == ()


# ---------------------------------------------------------------------------
# Platform selection
# ---------------------------------------------------------------------------
class TestPlatformSelection:
    def test_selector_free_edit_is_active_everywhere(self, tmp_path: Path):
        target = _write_rules(tmp_path, EDIT_PYPROJECT)
        for platform in ("darwin", "linux", "win32"):
            assert load_selected_rules(target, platform=platform).rules.edit

    def test_foreign_platform_edit_is_dropped(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["a"]\n'
            'expect = "x"\nplatforms = ["win32"]\n',
        )
        assert load_selected_rules(target, platform="darwin").rules.edit == ()
        assert load_selected_rules(target, platform="win32").rules.edit

    def test_invalid_platform_value_rejected(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "pyproject.toml"\ncommand = ["a"]\n'
            'expect = "x"\nplatforms = ["solaris"]\n',
        )
        with pytest.raises(ValidationError, match="platforms"):
            load_rules(target)

    def test_declaration_order_preserved(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "z.toml"\ncommand = ["a"]\nexpect = "x"\n'
            '[[edit]]\nfile = "a.toml"\ncommand = ["b"]\nexpect = "y"\n',
        )
        assert [rule.file for rule in load_rules(target).edit] == ["z.toml", "a.toml"]


# ---------------------------------------------------------------------------
# One file, two mechanisms, disjoint platforms
# ---------------------------------------------------------------------------
def _edit_table(file: str, command: str, platforms: str) -> str:
    return (
        f'[[edit]]\nfile = "{file}"\ncommand = ["{command}"]\n'
        f'expect = "x"\nplatforms = {platforms}\n'
    )


def _reset_table(file: str, platforms: str) -> str:
    return f'[[reset]]\nfile = "{file}"\nstub = ""\nplatforms = {platforms}\n'


def _regenerate_table(file: str, platforms: str) -> str:
    return (
        f'[[regenerate]]\nfile = "{file}"\ncommand = ["regen"]\n'
        f"platforms = {platforms}\n"
    )


class TestPlatformDisjointExcludedTarget:
    """The two exclusion contracts are inverse, so they cannot both bind the
    one platform-neutral exclude_files set: a [[reset]]/[[regenerate]] target
    MUST be excluded, an [[edit]] target must NOT be. When the declarations
    are platform-disjoint the one-writer invariant is already satisfied, so
    exclusion follows the platform's own active writer.

    This applies to TARGET-ADDED exclusions only — a path the target itself
    put in [rules] extra_exclude_files. A DEFAULT_RULES.exclude_files entry
    is press's own, and no target declaration unlocks it.
    """

    @pytest.mark.parametrize(
        ("file", "preamble"),
        [
            # Excluded by the target's own [rules] extra_exclude_files — the
            # ONLY exclusions this exception reaches. press's own defaults are
            # tool-owned (see TestDefaultExclusionsAreToolOwned).
            ("pyproject.toml", '[rules]\nextra_exclude_files = ["pyproject.toml"]\n'),
            ("docs/api.md", '[rules]\nextra_exclude_files = ["docs/api.md"]\n'),
        ],
    )
    @pytest.mark.parametrize("other", ["reset", "regenerate"])
    def test_disjoint_edit_and_discarding_writer_accepted(
        self, tmp_path: Path, file: str, preamble: str, other: str
    ):
        table = _reset_table if other == "reset" else _regenerate_table
        target = _write_rules(
            tmp_path,
            preamble
            + _edit_table(file, "amend", '["darwin"]')
            + table(file, '["linux"]'),
        )

        darwin = load_selected_rules(target, platform="darwin").rules
        linux = load_selected_rules(target, platform="linux").rules

        # Edit platform: the edit is active and the replace pass can reach
        # the file, so the command amends a file already carrying DESTINATION.
        assert [rule.file for rule in darwin.edit] == [file]
        assert darwin.reset == () and darwin.regenerate == ()
        assert file not in darwin.exclude_files

        # Discarding platform: the edit is gone and the exclusion stands, so
        # the reset/regeneration is not raced by the replace pass.
        assert linux.edit == ()
        selected = linux.reset if other == "reset" else linux.regenerate
        assert [rule.file for rule in selected] == [file]
        assert file in linux.exclude_files

    def test_same_platform_edit_and_reset_still_refused(self, tmp_path: Path):
        """Sharing a platform is two writers for one file, exclusion or not —
        and the writer diagnostic wins over the exclusion one."""
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n'
            + _edit_table("pyproject.toml", "amend", '["darwin"]')
            + _reset_table("pyproject.toml", '["darwin", "linux"]'),
        )
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        assert "may not also be a reset/remove/regenerate target" in str(exc.value)

    def test_standalone_excluded_edit_still_refused(self, tmp_path: Path):
        """No paired writer, no exception: the plain refusal is unchanged."""
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n'
            + _edit_table("pyproject.toml", "amend", '["darwin"]'),
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_disjoint_remove_does_not_license_an_excluded_edit(self, tmp_path: Path):
        """[[remove]] carries no exclusion requirement of its own, so it
        cannot be the reason a file is excluded — the exception is only for a
        [[reset]]/[[regenerate]] pairing."""
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n'
            + _edit_table("pyproject.toml", "amend", '["darwin"]')
            + '[[remove]]\nfile = "pyproject.toml"\nreason = "template-only"\n'
            'platforms = ["linux"]\n',
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_pairing_does_not_excuse_the_reset_sides_own_contract(self, tmp_path: Path):
        """The exception loosens the edit side only. An unexcluded file is
        still refused for the reset that needs it excluded."""
        target = _write_rules(
            tmp_path,
            _edit_table("pyproject.toml", "amend", '["darwin"]')
            + _reset_table("pyproject.toml", '["linux"]'),
        )
        with pytest.raises(
            ValidationError, match=r"\[\[reset\]\] target .* must be listed in"
        ):
            load_rules(target)


# ---------------------------------------------------------------------------
# Default exclusions are press's own
# ---------------------------------------------------------------------------
class TestDefaultExclusionsAreToolOwned:
    """DEFAULT_RULES.exclude_files is press's set, not the target's.

    The platform-disjoint exception exists so a target can declare one file
    two ways across platforms. It may not be turned into a lever that hands
    the replace pass a lockfile or a changelog: a disjoint [[reset]] or
    [[regenerate]] on a default-excluded path licenses nothing, so the edit
    refusal stands.
    """

    @pytest.mark.parametrize("file", sorted(DEFAULT_RULES.exclude_files))
    @pytest.mark.parametrize("other", ["reset", "regenerate"])
    def test_disjoint_writer_does_not_license_a_default_exclusion(
        self, tmp_path: Path, file: str, other: str
    ):
        table = _reset_table if other == "reset" else _regenerate_table
        target = _write_rules(
            tmp_path,
            _edit_table(file, "amend", '["darwin"]') + table(file, '["linux"]'),
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_disjoint_writer_does_not_license_a_default_alias_either(
        self, tmp_path: Path
    ):
        """Spelling the edit target as a filesystem alias of the default entry
        is the same refusal — the pairing check compares alias identity."""
        target = _write_rules(
            tmp_path,
            _edit_table("BUN.lock.", "amend", '["darwin"]')
            + _reset_table("bun.lock", '["linux"]'),
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_default_exclusions_survive_an_unrelated_edit(self, tmp_path: Path):
        """An accepted edit removes its own path and nothing else."""
        target = _write_rules(tmp_path, EDIT_PYPROJECT)
        for platform in ("darwin", "linux", "win32"):
            selected = load_selected_rules(target, platform=platform).rules
            assert DEFAULT_RULES.exclude_files <= selected.exclude_files


# ---------------------------------------------------------------------------
# Filesystem-alias identity (the union press validates against everywhere)
# ---------------------------------------------------------------------------
class TestFilesystemAliasIdentity:
    """Two declared spellings can name ONE file on a real filesystem.

    press validates every rule against the conservative union of the aliases
    any supported filesystem collapses — case-insensitivity (Windows, default
    macOS) and Windows' per-component trailing dot/space strip — exactly as
    _reject_reserved already documents for the control paths. An [[edit]]
    same-file check that compared raw strings would fail OPEN: the second
    writer, or the excluded path, would simply be spelled differently.
    """

    ALIAS = "META.TOML."  # `meta.toml` on every filesystem press supports

    def test_duplicate_edit_aliases_refused(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            _edit_table("meta.toml", "a", '["darwin"]')
            + _edit_table(self.ALIAS, "b", '["darwin"]'),
        )
        with pytest.raises(ValidationError, match="overlap"):
            load_rules(target)

    @pytest.mark.parametrize(
        "other",
        [
            '[[reset]]\nfile = "META.TOML."\nstub = ""\n',
            '[[remove]]\nfile = "META.TOML."\nreason = "template-only"\n',
            '[[regenerate]]\nfile = "META.TOML."\ncommand = ["true"]\n',
        ],
    )
    def test_alias_of_another_writer_refused(self, tmp_path: Path, other: str):
        target = _write_rules(
            tmp_path,
            '[[edit]]\nfile = "meta.toml"\ncommand = ["a"]\nexpect = "x"\n' + other,
        )
        with pytest.raises(ValidationError) as exc:
            load_rules(target)
        assert "may not also be a reset/remove/regenerate target" in str(exc.value)

    @pytest.mark.parametrize("file", ["CHANGELOG.MD", "BUN.lock.", "UV.LOCK"])
    def test_standalone_alias_of_a_default_exclusion_refused(
        self, tmp_path: Path, file: str
    ):
        target = _write_rules(
            tmp_path,
            f'[[edit]]\nfile = "{file}"\ncommand = ["true"]\nexpect = "x"\n',
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    def test_standalone_alias_of_a_target_added_exclusion_refused(self, tmp_path: Path):
        target = _write_rules(
            tmp_path,
            '[rules]\nextra_exclude_files = ["pyproject.toml"]\n'
            '[[edit]]\nfile = "PyProject.TOML "\ncommand = ["true"]\n'
            'expect = "x"\n',
        )
        with pytest.raises(
            ValidationError, match="must not be listed in exclude_files"
        ):
            load_rules(target)

    @pytest.mark.parametrize("other", ["reset", "regenerate"])
    def test_disjoint_alias_pair_on_a_target_added_exclusion_accepted(
        self, tmp_path: Path, other: str
    ):
        """The licensed case, spelled two ways: the exclusion entry and the
        discarding writer agree on `META.TOML.`, the edit says `meta.toml`.
        Selection must drop the exclusion by alias identity, not by string."""
        table = _reset_table if other == "reset" else _regenerate_table
        target = _write_rules(
            tmp_path,
            f'[rules]\nextra_exclude_files = ["{self.ALIAS}"]\n'
            + _edit_table("meta.toml", "amend", '["darwin"]')
            + table(self.ALIAS, '["linux"]'),
        )

        darwin = load_selected_rules(target, platform="darwin").rules
        linux = load_selected_rules(target, platform="linux").rules

        assert [rule.file for rule in darwin.edit] == ["meta.toml"]
        assert self.ALIAS not in darwin.exclude_files
        assert "meta.toml" not in darwin.exclude_files

        assert linux.edit == ()
        selected = linux.reset if other == "reset" else linux.regenerate
        assert [rule.file for rule in selected] == [self.ALIAS]
        assert self.ALIAS in linux.exclude_files

        # Only the edit's own alias leaves; every default exclusion stays.
        assert DEFAULT_RULES.exclude_files <= darwin.exclude_files
        assert DEFAULT_RULES.exclude_files <= linux.exclude_files


# ---------------------------------------------------------------------------
# Rules field order
# ---------------------------------------------------------------------------
def test_rules_positional_signature_predates_edit():
    """`edit` is appended AFTER every pre-existing field, so the historical
    positional argument sequence still binds each value to its own field. A
    mid-list insertion would rebind them silently — the dataclass keeps
    accepting the call and only the values move."""
    replace_rule = ReplaceRule(pattern="{app_name}", reason="brand")
    regenerate_rule = RegenerateRule(file="uv.lock", command=("uv", "lock"))
    reset_rule = ResetRule(file="CHANGELOG.md", stub="")
    remove_rule = RemoveRule(file="ci.yml", reason="template-only")

    rules = Rules(
        frozenset({"vendor"}),  # exclude_dirs
        frozenset({"uv.lock"}),  # exclude_files
        (regenerate_rule,),  # regenerate
        (reset_rule,),  # reset
        (remove_rule,),  # remove
        frozenset({"legacy"}),  # verify_ignore
        (replace_rule,),  # replace
        frozenset({"app_name"}),  # substring_rewrite_fields
        ("display_name_spaced",),  # display_forms
    )

    assert rules.exclude_dirs == frozenset({"vendor"})
    assert rules.exclude_files == frozenset({"uv.lock"})
    assert rules.regenerate == (regenerate_rule,)
    assert rules.reset == (reset_rule,)
    assert rules.remove == (remove_rule,)
    assert rules.verify_ignore == frozenset({"legacy"})
    assert rules.replace == (replace_rule,)
    assert rules.substring_rewrite_fields == frozenset({"app_name"})
    assert rules.display_forms == ("display_name_spaced",)
    assert rules.edit == ()
