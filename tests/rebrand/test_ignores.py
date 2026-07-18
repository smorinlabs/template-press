"""Source-coordinate, occurrence-pinned, self-policing ignores (Task 8).

`apply_ignores` silences the paranoid scanner's false positives WITHOUT
letting a stale ignore mask a real leak:

- an ignore is pinned to a SOURCE coordinate (file + anchor substring +
  optional line + optional occurrence ordinal), mapped back from the
  sandbox path via `build_forward_map` (reverse longest-prefix of
  `ApplyReport.renamed`);
- an `ordinal`-less ignore that matches >=2 findings is a CONFIG ERROR
  (fail closed — never silently multi-suppress);
- an ignore that suppresses ZERO findings and is not `force` is STALE.

Tests use small hand-built `Finding` lists plus stub `source_line` /
`forward_map` — no real press run needed.
"""

from __future__ import annotations

import pytest

from template_press.rebrand.identity import ValidationError
from template_press.rebrand.ignores import Ignore, apply_ignores, build_forward_map
from template_press.rebrand.verifier import Finding


def make_finding(
    path: str,
    field: str,
    value: str,
    where: str,
    line: int | None,
    col: int | None,
    context: str = "",
) -> Finding:
    return Finding(
        path=path,
        field=field,
        value=value,
        where=where,
        line=line,
        col=col,
        context=context,
    )


def source_line_stub(mapping: dict[tuple[str, int], str]):
    def source_line(path: str, line: int) -> str | None:
        return mapping.get((path, line))

    return source_line


def identity_map(p: str) -> str:
    return p


# --- build_forward_map ------------------------------------------------------


def test_build_forward_map_reverses_renamed_prefix():
    fmap = build_forward_map([("src/demo_widget", "src/potato_launcher")])
    # sandbox (pressed) path maps back to its source path
    assert fmap("src/potato_launcher/x.py") == "src/demo_widget/x.py"
    # the renamed dir itself (exact prefix) maps back too
    assert fmap("src/potato_launcher") == "src/demo_widget"


def test_build_forward_map_no_match_passes_through():
    fmap = build_forward_map([("src/demo_widget", "src/potato_launcher")])
    assert fmap("README.md") == "README.md"


def test_build_forward_map_is_component_aware():
    # 'src/potato_launcher' is NOT a path-prefix of 'src/potato_launcher_x/...'
    fmap = build_forward_map([("src/demo_widget", "src/potato_launcher")])
    assert fmap("src/potato_launcher_x/y.py") == "src/potato_launcher_x/y.py"


def test_build_forward_map_longest_prefix_wins():
    fmap = build_forward_map(
        [
            ("src/demo_widget", "src/potato_launcher"),
            ("src/demo_widget/core", "src/potato_launcher/kernel"),
        ]
    )
    assert fmap("src/potato_launcher/kernel/z.py") == "src/demo_widget/core/z.py"
    # a path under the shorter prefix still resolves via the shorter one
    assert fmap("src/potato_launcher/cli.py") == "src/demo_widget/cli.py"


# --- Ignore dataclass validation --------------------------------------------


def test_ignore_requires_field_or_value():
    with pytest.raises(ValidationError):
        Ignore(
            field=None,
            value=None,
            file="README.md",
            anchor="x",
            line=None,
            ordinal=None,
            force=False,
            reason="bad",
        )


def test_ignore_field_only_is_valid():
    ig = Ignore(
        field="io",
        value=None,
        file="a.bin",
        anchor="a",
        line=None,
        ordinal=None,
        force=False,
        reason="ok",
    )
    assert ig.field == "io"


def test_ignore_value_only_is_valid():
    ig = Ignore(
        field=None,
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=1,
        ordinal=None,
        force=False,
        reason="ok",
    )
    assert ig.value == "demo_widget"


# --- (a) anchored line+ordinal suppresses exactly ONE of two same-line leaks -


def test_ordinal_suppresses_exactly_one_of_two_same_line():
    line_text = "demo_widget and demo_widget again"
    f0 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 0)
    f1 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 16)
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=3,
        ordinal=0,
        force=False,
        reason="first is intentional",
    )
    surviving, stale = apply_ignores(
        [f0, f1],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({("README.md", 3): line_text}),
    )
    assert surviving == [f1]
    assert stale == []


def test_ordinal_one_suppresses_the_second():
    line_text = "demo_widget and demo_widget again"
    f0 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 0)
    f1 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 16)
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=3,
        ordinal=1,
        force=False,
        reason="second is intentional",
    )
    surviving, stale = apply_ignores(
        [f0, f1],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({("README.md", 3): line_text}),
    )
    assert surviving == [f0]
    assert stale == []


# --- (b) ambiguous anchor+line, no ordinal -> config error ------------------


def test_ambiguous_anchor_without_ordinal_is_config_error():
    line_text = "demo_widget and demo_widget again"
    f0 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 0)
    f1 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 16)
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=3,
        ordinal=None,
        force=False,
        reason="ambiguous",
    )
    with pytest.raises(ValidationError):
        apply_ignores(
            [f0, f1],
            [ig],
            forward_map=identity_map,
            source_line=source_line_stub({("README.md", 3): line_text}),
        )


# --- (c) anchor present but suppresses nothing -> stale ---------------------


def test_ignore_suppressing_nothing_is_stale():
    f0 = make_finding("README.md", "package_name", "demo_widget", "content", 3, 0)
    # anchor IS present in the file (line 7 still contains the token) but no
    # finding lands there -> the ignore is drift.
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=7,
        ordinal=None,
        force=False,
        reason="drifted",
    )
    surviving, stale = apply_ignores(
        [f0],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub(
            {("README.md", 3): "demo_widget here", ("README.md", 7): "demo_widget"}
        ),
    )
    assert surviving == [f0]
    assert stale == [ig]


# --- (d) filename ignore (line=None) via path-anchor ------------------------


def test_filename_ignore_suppresses_filename_finding():
    f = make_finding(
        "src/pkg/demo_widget.py",
        "package_name",
        "demo_widget",
        "filename",
        None,
        None,
        context="demo_widget.py",
    )
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="src/pkg/demo_widget.py",
        anchor="demo_widget",
        line=None,
        ordinal=None,
        force=False,
        reason="legit filename",
    )
    surviving, stale = apply_ignores(
        [f],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({}),
    )
    assert surviving == []
    assert stale == []


# --- (e) force ignore that suppresses nothing is NOT stale ------------------


def test_force_ignore_suppressing_nothing_is_not_stale():
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="README.md",
        anchor="demo_widget",
        line=99,
        ordinal=None,
        force=True,
        reason="forced placeholder",
    )
    surviving, stale = apply_ignores(
        [],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({}),
    )
    assert surviving == []
    assert stale == []


# --- unscannable path-anchor (interface reconciliation) ---------------------


def test_unscannable_suppressed_by_path_anchor_ignore():
    f = make_finding("assets/logo.bin", "io", "unreadable", "unscannable", None, None)
    ig = Ignore(
        field="io",
        value=None,
        file="assets/logo.bin",
        anchor="assets/",
        line=None,
        ordinal=None,
        force=False,
        reason="known-unreadable asset",
    )
    surviving, stale = apply_ignores(
        [f],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({}),
    )
    assert surviving == []
    assert stale == []


def test_unscannable_path_ignore_is_stale_when_no_finding():
    ig = Ignore(
        field="io",
        value=None,
        file="assets/logo.bin",
        anchor="assets/",
        line=None,
        ordinal=None,
        force=False,
        reason="stale io ignore",
    )
    surviving, stale = apply_ignores(
        [],
        [ig],
        forward_map=identity_map,
        source_line=source_line_stub({}),
    )
    assert surviving == []
    assert stale == [ig]


# --- source-mapping: a sandbox finding is anchored in the SOURCE line -------


def test_finding_anchored_against_source_via_forward_map():
    # finding lives on the sandbox (pressed) path; the anchor must be tested
    # against the SOURCE line at the mapped source path.
    f = make_finding(
        "src/potato_launcher/cli.py", "package_name", "demo_widget", "content", 2, 0
    )
    fmap = build_forward_map([("src/demo_widget", "src/potato_launcher")])
    ig = Ignore(
        field="package_name",
        value="demo_widget",
        file="src/demo_widget/cli.py",
        anchor="demo_widget",
        line=2,
        ordinal=None,
        force=False,
        reason="source-anchored",
    )
    surviving, stale = apply_ignores(
        [f],
        [ig],
        forward_map=fmap,
        source_line=source_line_stub({("src/demo_widget/cli.py", 2): "demo_widget"}),
    )
    assert surviving == []
    assert stale == []
