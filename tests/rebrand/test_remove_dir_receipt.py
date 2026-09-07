from __future__ import annotations

import dataclasses
import os
import tomllib

import pytest

from template_press.rebrand.engine import ApplyReport
from template_press.rebrand.identity import ValidationError
from template_press.rebrand.receipt import read_receipt, write_receipt
from template_press.rebrand.removal_types import (
    DirectoryRemoval,
    RemovalMember,
    RemovalPlan,
)
from template_press.rebrand.remove import translate_removal_plan

from .conftest import DEST, SOURCE, requires_symlink


def history_row():
    return DirectoryRemoval(
        dir="research",
        current_dir="archive",
        reason="template research",
        members=(
            RemovalMember(
                file="research/demo.md",
                current_file="archive/renamed.md",
                reason="template research",
                source_dir="research",
                missing_ok=True,
            ),
        ),
    )


def test_translate_preserves_audit():
    plan = RemovalPlan(directories=(history_row(),))
    translated = translate_removal_plan(plan, {"archive": "final"})
    member = translated.directories[0].members[0]
    assert translated.directories[0].current_dir == "final"
    assert member.file == "research/demo.md"
    assert member.source_dir == "research"
    assert member.current_file == "final/renamed.md"


def test_history_round_trip(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    row = history_row()
    report = ApplyReport()
    report.removed.append("archive/renamed.md")
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        report,
        removals=[("research/demo.md", "template research")],
        remove_dirs=[row],
    )
    text = read_receipt(tmp_path)
    parsed = tomllib.loads(text)
    assert parsed["press"]["remove"] == [
        {"file": "research/demo.md", "reason": "template research"}
    ]
    assert parsed["press"]["remove_dir"] == [
        {
            "dir": "research",
            "current_dir": "archive",
            "reason": "template research",
            "complete": True,
            "members": [
                {
                    "file": "research/demo.md",
                    "source_dir": "research",
                    "current_file": "archive/renamed.md",
                }
            ],
        }
    ]
    assert directory_history_from_receipt(text, DEST) == (row,)
    with pytest.raises(ValidationError, match=r"match|verified"):
        directory_history_from_receipt(text, SOURCE)


@pytest.mark.parametrize(
    "old,new",
    [
        ("verified = true", "verified = false"),
        ("remove_dirs_version = 1", "remove_dirs_version = true"),
        ("remove_dirs_version = 1", "remove_dirs_version = 2"),
        ("complete = true", "complete = false"),
        ('current_dir = "archive"', 'current_dir = "../archive"'),
        ('current_file = "archive/renamed.md"', 'current_file = "other/file.md"'),
        ('source_dir = "research"', 'source_dir = "other"'),
        ('file = "research/demo.md"\nreason', 'file = "missing.md"\nreason'),
    ],
)
def test_history_refusals(tmp_path, old, new):
    from template_press.rebrand.receipt import directory_history_from_receipt

    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[history_row()],
    )
    text = read_receipt(tmp_path)
    assert old in text
    with pytest.raises(ValidationError):
        directory_history_from_receipt(text.replace(old, new), DEST)


def test_inactive_directory_history_is_still_strict(tmp_path):
    from template_press.rebrand.receipt import selected_directory_history

    row = history_row()
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[row],
    )
    text = read_receipt(tmp_path)
    assert selected_directory_history(text, DEST, directory_declared=False) == (row,)
    with pytest.raises(ValidationError, match=r"match|verified"):
        selected_directory_history(text, SOURCE, directory_declared=False)


def test_history_limits(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    text = "#" + "x" * (16 * 1024 * 1024)
    with pytest.raises(ValidationError, match=r"limit|large"):
        directory_history_from_receipt(text, DEST)


@pytest.mark.parametrize(
    "mutation", ["duplicate_flat", "duplicate_dir", "unknown_key", "no_members"]
)
def test_history_ambiguous_rows(tmp_path, mutation):
    from template_press.rebrand.receipt import directory_history_from_receipt

    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("research/demo.md", "template research")],
        remove_dirs=[history_row()],
    )
    text = read_receipt(tmp_path)
    if mutation == "duplicate_flat":
        text += (
            '\n[[press.remove]]\nfile="research/demo.md"\nreason="template research"\n'
        )
    elif mutation == "duplicate_dir":
        text += '\n[[press.remove_dir]]\ndir="RESEARCH."\ncurrent_dir="ARCHIVE."\n'
        text += 'reason="template research"\ncomplete=true\nmembers=[]\n'
    elif mutation == "unknown_key":
        text = text.replace("complete = true", "complete = true\ntrusted = true")
    else:
        begin = text.index("members = [")
        # Writer places members on one line as an inline-table array.
        end = text.index("\n", begin)
        text = text[:begin] + text[end:]
    with pytest.raises(ValidationError):
        directory_history_from_receipt(text, DEST)


def bound_history_text(*, directories=1, members=0, path_bytes=None):
    from template_press.rebrand.config import toml_string

    parts = ["[press]", "verified = true", "remove_dirs_version = 1", "[press.to]"]
    parts.extend(
        f"{key} = {toml_string(value)}"
        for key, value in DEST.as_dict_prompted().items()
    )
    for index in range(directories):
        root = f"d{index}"
        rels = [f"{root}/m{number}" for number in range(members if index == 0 else 0)]
        if path_bytes is not None and index == 0:
            rels = [root + "/" + "x" * (path_bytes - len(root) - 1)]
        parts.extend(
            [
                "[[press.remove_dir]]",
                f'dir = "{root}"',
                f'current_dir = "{root}"',
                'reason = "r"',
                "complete = true",
                "members = ["
                + ",".join(
                    '{ file = "'
                    + rel
                    + '", source_dir = "'
                    + root
                    + '", current_file = "'
                    + rel
                    + '" }'
                    for rel in rels
                )
                + "]",
            ]
        )
        for rel in rels:
            parts.extend(["[[press.remove]]", f'file = "{rel}"', 'reason = "r"'])
    return "\n".join(parts) + "\n"


@pytest.mark.parametrize(
    "kind,limit,diagnostic",
    [
        ("directories", 1024, "directory row limit 1024 exceeded"),
        ("members", 100000, "directory member limit 100000 exceeded"),
        ("path_bytes", 4096, "directory text byte limit 4096 exceeded"),
    ],
)
def test_history_count_and_text_limits(kind, limit, diagnostic):
    from template_press.rebrand.receipt import directory_history_from_receipt

    at_limit = bound_history_text(**{kind: limit})
    assert directory_history_from_receipt(at_limit, DEST)
    above_limit = bound_history_text(**{kind: limit + 1})
    with pytest.raises(ValidationError, match=diagnostic):
        directory_history_from_receipt(above_limit, DEST)


def test_history_byte_limit_has_valid_boundary():
    from template_press.rebrand.receipt import directory_history_from_receipt

    text = bound_history_text()
    ceiling = 16 * 1024 * 1024
    # ASCII comment padding preserves valid TOML and exact UTF-8 byte length.
    at_limit = text + "#" + "x" * (ceiling - len(text.encode("utf-8")) - 1)
    assert len(at_limit.encode("utf-8")) == ceiling
    assert directory_history_from_receipt(at_limit, DEST)
    with pytest.raises(
        ValidationError, match="directory receipt byte limit 16777216 exceeded"
    ):
        directory_history_from_receipt(at_limit + "x", DEST)


def test_writer_rejects_alias_and_oversize_before_writing(tmp_path):
    row = history_row()
    member = row.members[0]
    bad_rows = [
        dataclasses.replace(
            row,
            members=(
                member,
                dataclasses.replace(
                    member, file="RESEARCH./DEMO.MD", current_file="ARCHIVE./RENAMED.MD"
                ),
            ),
        ),
        dataclasses.replace(
            row, members=(dataclasses.replace(member, file="research/" + "x" * 4097),)
        ),
    ]
    for bad in bad_rows:
        with pytest.raises(ValidationError):
            write_receipt(
                tmp_path,
                SOURCE,
                DEST,
                ApplyReport(),
                removals=[(m.file, m.reason) for m in bad.members],
                remove_dirs=[bad],
            )
        assert not (tmp_path / "press/press-receipt.toml").exists()


@pytest.mark.parametrize("body", [b"\xff", b"#" + b"x" * (16 * 1024 * 1024)])
def test_bounded_read_rejects_invalid_or_oversize(tmp_path, body):
    (tmp_path / "press").mkdir()
    (tmp_path / "press/press-receipt.toml").write_bytes(body)
    with pytest.raises(ValidationError):
        read_receipt(tmp_path, max_bytes=16 * 1024 * 1024)


def test_bounded_read_requests_only_limit_plus_one(tmp_path, monkeypatch):
    import template_press.rebrand.receipt as module

    (tmp_path / "press").mkdir()
    (tmp_path / "press/press-receipt.toml").write_bytes(b"#" * 100)
    actual_fdopen = module.os.fdopen
    reads = []

    class CheckedReader:
        def __init__(self, *args, **kwargs):
            self.reader = actual_fdopen(*args, **kwargs)

        def __enter__(self):
            self.reader.__enter__()
            return self

        def __exit__(self, *args):
            return self.reader.__exit__(*args)

        def read(self, size=-1):
            reads.append(size)
            assert size == 33
            return self.reader.read(size)

    monkeypatch.setattr(module.os, "fdopen", CheckedReader)
    with pytest.raises(ValidationError, match="byte limit 32 exceeded"):
        read_receipt(tmp_path, max_bytes=32)
    assert reads == [33]


@requires_symlink
@pytest.mark.parametrize("link_parent", [False, True])
def test_bounded_read_rejects_symlinks(tmp_path, link_parent):
    from template_press.rebrand.safety import SafetyError

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "press-receipt.toml").write_text("sentinel", encoding="utf-8")
    if link_parent:
        (tmp_path / "press").symlink_to(outside, target_is_directory=True)
    else:
        (tmp_path / "press").mkdir()
        (tmp_path / "press/press-receipt.toml").symlink_to(
            outside / "press-receipt.toml"
        )
    with pytest.raises(SafetyError):
        read_receipt(tmp_path, max_bytes=1024)
    assert (outside / "press-receipt.toml").read_text() == "sentinel"


def test_receipt_routing_preserves_legacy_tolerance(tmp_path):
    from template_press.rebrand.receipt import (
        receipt_present,
        selected_directory_history,
    )
    from template_press.rebrand.remove import removal_receipt_text
    from template_press.rebrand.rules import RemoveDirRule, Rules

    assert not receipt_present(tmp_path)
    assert (
        removal_receipt_text(
            tmp_path,
            Rules(exclude_dirs=frozenset(), exclude_files=frozenset(), regenerate=()),
        )
        is None
    )
    (tmp_path / "press").mkdir()
    (tmp_path / "press/press-receipt.toml").write_text("invalid = [", encoding="utf-8")
    assert receipt_present(tmp_path)
    text = removal_receipt_text(
        tmp_path,
        Rules(exclude_dirs=frozenset(), exclude_files=frozenset(), regenerate=()),
    )
    assert selected_directory_history(text, DEST, directory_declared=False) == ()
    active = Rules(
        exclude_dirs=frozenset(),
        exclude_files=frozenset(),
        regenerate=(),
        remove_dirs=(RemoveDirRule("research", "r"),),
    )
    with pytest.raises(ValidationError, match="TOML"):
        selected_directory_history(
            removal_receipt_text(tmp_path, active), DEST, directory_declared=True
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_file", "archive"),
        ("file", "other/demo.md"),
        ("source_dir", "research/sub"),
        ("current_dir", "archive\\sub"),
        ("reason", "bad\nreason"),
    ],
)
def test_writer_rejects_incoherent_history(tmp_path, field, value):
    row = history_row()
    if field in {"file", "current_file", "source_dir"}:
        row = dataclasses.replace(
            row, members=(dataclasses.replace(row.members[0], **{field: value}),)
        )
    else:
        row = dataclasses.replace(row, **{field: value})
    with pytest.raises(ValidationError):
        write_receipt(
            tmp_path,
            SOURCE,
            DEST,
            ApplyReport(),
            removals=[(m.file, m.reason) for m in row.members],
            remove_dirs=[row],
        )
    assert not (tmp_path / "press/press-receipt.toml").exists()


def test_empty_metadata_still_refuses_duplicate_flat_rows():
    from template_press.rebrand.receipt import directory_history_from_receipt

    text = bound_history_text(directories=0)
    text = text.replace("[press.to]", "remove_dir = []\n[press.to]")
    text += '\n[[press.remove]]\nfile="legacy.txt"\nreason="r"\n' * 2
    with pytest.raises(ValidationError, match="duplicate"):
        directory_history_from_receipt(text, DEST)


def test_empty_history_writer_keeps_complete_expansion(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    row = dataclasses.replace(history_row(), members=())
    write_receipt(tmp_path, SOURCE, DEST, ApplyReport(), remove_dirs=[row])
    text = read_receipt(tmp_path)
    assert "members = []\n" in text
    assert tomllib.loads(text)["press"]["remove_dir"][0]["complete"] is True
    assert directory_history_from_receipt(text, DEST) == (row,)


def test_history_renewed_members_keep_their_actual_source_root(tmp_path):
    from template_press.rebrand.receipt import directory_history_from_receipt

    row = history_row()
    new = RemovalMember("archive/new.md", "archive/new.md", row.reason, "archive", True)
    row = dataclasses.replace(row, members=(*row.members, new))
    write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[(m.file, m.reason) for m in row.members],
        remove_dirs=[row],
    )
    assert directory_history_from_receipt(read_receipt(tmp_path), DEST) == (row,)


@pytest.mark.parametrize("field", ["dir", "current_dir"])
def test_history_nested_roots_refuse(tmp_path, field):
    row = history_row()
    other = DirectoryRemoval("other", "elsewhere", "r", ())
    other = dataclasses.replace(other, **{field: getattr(row, field) + "/sub"})
    with pytest.raises(ValidationError, match="overlap"):
        write_receipt(
            tmp_path,
            SOURCE,
            DEST,
            ApplyReport(),
            removals=[(m.file, m.reason) for m in row.members],
            remove_dirs=[row, other],
        )
    assert not (tmp_path / "press/press-receipt.toml").exists()


@pytest.mark.parametrize(
    "flat",
    [
        [],
        [("research/demo.md", "wrong")],
        [("research/demo.md", "template research")] * 2,
    ],
)
def test_writer_requires_one_matching_flat_row(tmp_path, flat):
    with pytest.raises(ValidationError):
        write_receipt(
            tmp_path,
            SOURCE,
            DEST,
            ApplyReport(),
            removals=flat,
            remove_dirs=[history_row()],
        )
    assert not (tmp_path / "press/press-receipt.toml").exists()


def test_bounded_read_accepts_exact_limit_and_legacy_remains_unbounded(tmp_path):
    text = "#" + "é" * 64
    (tmp_path / "press").mkdir()
    (tmp_path / "press/press-receipt.toml").write_text(text, encoding="utf-8")
    assert read_receipt(tmp_path, max_bytes=129) == text
    with pytest.raises(ValidationError, match="byte limit 128 exceeded"):
        read_receipt(tmp_path, max_bytes=128)
    assert read_receipt(tmp_path) == text


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO")
def test_bounded_read_refuses_fifo_before_open(tmp_path):
    import os

    from template_press.rebrand.safety import SafetyError

    (tmp_path / "press").mkdir()
    os.mkfifo(tmp_path / "press/press-receipt.toml")
    with pytest.raises(SafetyError, match="regular file"):
        read_receipt(tmp_path, max_bytes=1024)


@pytest.mark.skipif(
    os.name == "nt",
    reason="replace-open race fixture requires POSIX rename semantics",
)
def test_bounded_read_refuses_replaced_leaf(tmp_path, monkeypatch):
    import template_press.rebrand.receipt as module
    from template_press.rebrand.safety import SafetyError

    (tmp_path / "press").mkdir()
    path = tmp_path / "press/press-receipt.toml"
    path.write_bytes(b"first")
    actual_fdopen = module.os.fdopen

    class ReplacingReader:
        def __init__(self, *args, **kwargs):
            self.reader = actual_fdopen(*args, **kwargs)

        def __enter__(self):
            self.reader.__enter__()
            return self

        def __exit__(self, *args):
            return self.reader.__exit__(*args)

        def read(self, size):
            data = self.reader.read(size)
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"second")
            replacement.replace(path)
            return data

    monkeypatch.setattr(module.os, "fdopen", ReplacingReader)
    with pytest.raises(SafetyError, match="changed while reading"):
        read_receipt(tmp_path, max_bytes=1024)
    assert path.read_bytes() == b"second"


def test_bounded_read_refuses_junction_parent_predicate(tmp_path, monkeypatch):
    from pathlib import Path

    from template_press.rebrand.safety import SafetyError

    (tmp_path / "press").mkdir()
    path = tmp_path / "press/press-receipt.toml"
    path.write_text("sentinel", encoding="utf-8")
    actual_is_junction = Path.is_junction

    def junction_at_press(path):
        return path == tmp_path / "press" or actual_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", junction_at_press)
    with pytest.raises(SafetyError, match="junction"):
        read_receipt(tmp_path, max_bytes=1024)
    assert path.read_text() == "sentinel"
