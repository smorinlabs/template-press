"""Complete directory-receipt budgets must refuse before the first write."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

import template_press.rebrand.receipt as receipt
from template_press.rebrand.cli import _press, main
from template_press.rebrand.config import SOURCE_CONFIG_REL
from template_press.rebrand.engine import ApplyReport, build_plan
from template_press.rebrand.remove import (
    plan_removals,
    removal_receipt_metadata,
    removal_rules_view,
)
from template_press.rebrand.rules import load_rules

from .conftest import DEST, SOURCE, write_answers_file
from .test_remove_dirs import directory_repo
from .test_verify_cli import _commit

TEST_LIMIT = 2048


def snapshot(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


def budget_target(tmp_path: Path, reason: str = "r" * 500) -> Path:
    return directory_repo(tmp_path, f'[[remove]]\ndir="research"\nreason="{reason}"\n')


def assert_partial_fits_but_complete_does_not(repo: Path, tmp_path: Path) -> None:
    """Independent writer output proves the scaled fixture crosses the gap."""
    rules = load_rules(repo)
    plan = plan_removals(repo, rules, source=SOURCE)
    removals, directories = removal_receipt_metadata(plan, {})
    partial_bytes = len("[press]\nverified = true\nremove_dirs_version = 1\n")
    partial_bytes += sum(
        len(line.encode("utf-8")) + 1 for line in receipt._directory_lines(directories)
    )
    partial_bytes += sum(
        len(
            (
                f"\n[[press.remove]]\nfile = {receipt.toml_string(file)}\n"
                f"reason = {receipt.toml_string(reason)}\n"
            ).encode()
        )
        for file, reason in removals
    )
    rendered = receipt.write_receipt(
        tmp_path / "rendered",
        SOURCE,
        DEST,
        ApplyReport(),
        platform=sys.platform,
        removals=removals,
        remove_dirs=directories,
    )
    assert partial_bytes < TEST_LIMIT < rendered.stat().st_size


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
@pytest.mark.parametrize("initial", ["ordinary", "prior-receipt", "discovery"])
def test_main_complete_receipt_budget_refuses_before_any_write(
    tmp_path, monkeypatch, capsys, dry_run, initial
):
    repo = budget_target(tmp_path)
    assert_partial_fits_but_complete_does_not(repo, tmp_path)
    args = ["--target", str(repo), "--config", str(write_answers_file(tmp_path, DEST))]
    if initial == "prior-receipt":
        receipt.write_receipt(repo, DEST, SOURCE, ApplyReport())
        args.append("--force")
    elif initial == "discovery":
        (repo / SOURCE_CONFIG_REL).unlink()
        args.append("--accept-discovery")
    _commit(repo)
    if dry_run:
        args.append("--dry-run")
    before = snapshot(repo)
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)

    result = main(args)

    assert result == 2
    assert "directory receipt byte limit" in capsys.readouterr().err
    assert snapshot(repo) == before


@pytest.mark.parametrize("supplied_plan", [False, True], ids=["no-plan", "plan"])
@pytest.mark.parametrize("supplied_table", [False, True], ids=["no-table", "table"])
def test_direct_complete_receipt_budget_refuses_before_any_write(
    tmp_path, monkeypatch, capsys, supplied_plan, supplied_table
):
    repo = budget_target(tmp_path)
    assert_partial_fits_but_complete_does_not(repo, tmp_path)
    receipt.write_receipt(repo, DEST, SOURCE, ApplyReport())
    _commit(repo)
    rules = load_rules(repo)
    removal_plan = plan_removals(repo, rules, source=SOURCE)
    plan = build_plan(repo, SOURCE, DEST, removal_rules_view(rules, removal_plan))
    before = snapshot(repo)
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)

    outcome = _press(
        repo,
        SOURCE,
        DEST,
        rules,
        [],
        [],
        removal_plan=removal_plan if supplied_plan else None,
        table=plan.table if supplied_table else None,
    )

    assert outcome.env_error is not None
    assert "directory receipt byte limit" in outcome.env_error
    assert "nothing applied" in capsys.readouterr().err
    assert outcome.renamed == []
    assert outcome.regenerated == []
    assert snapshot(repo) == before


@pytest.mark.parametrize("direct", [False, True], ids=["main", "direct"])
def test_short_reason_complete_receipt_fits_and_succeeds(tmp_path, monkeypatch, direct):
    repo = budget_target(tmp_path, reason="r")
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)
    if direct:
        outcome = _press(repo, SOURCE, DEST, load_rules(repo), [], [])
        assert outcome.env_error is None
        assert not outcome.leaked
    else:
        assert (
            main(
                [
                    "--target",
                    str(repo),
                    "--config",
                    str(write_answers_file(tmp_path, DEST)),
                ]
            )
            == 0
        )
    text = (repo / receipt.RECEIPT_REL).read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < TEST_LIMIT
    parsed = tomllib.loads(text)["press"]
    assert parsed["counts"]["removed"] == 2
    assert parsed["to"] == DEST.as_dict_prompted()
    assert not (repo / "research").exists()


def test_file_only_writer_remains_uncapped(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)
    path = receipt.write_receipt(
        tmp_path,
        SOURCE,
        DEST,
        ApplyReport(),
        removals=[("old.md", "r" * (TEST_LIMIT + 1))],
    )
    assert path.stat().st_size > TEST_LIMIT
    assert "remove_dir" not in path.read_text(encoding="utf-8")


def test_file_only_main_remains_uncapped(tmp_path, monkeypatch):
    reason = "r" * (TEST_LIMIT + 1)
    repo = directory_repo(
        tmp_path, f'[[remove]]\nfile="research/one.md"\nreason="{reason}"\n'
    )
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)
    assert (
        main(
            ["--target", str(repo), "--config", str(write_answers_file(tmp_path, DEST))]
        )
        == 0
    )
    assert (repo / receipt.RECEIPT_REL).stat().st_size > TEST_LIMIT
    assert not (repo / "research/one.md").exists()
    assert (repo / "research/sub/two.md").is_file()


def phase_target(tmp_path: Path, padding: str = "small") -> Path:
    """Every optional receipt phase uses small, portable physical filenames."""
    from .conftest import _git

    argv = ", ".join(receipt.toml_string(arg) for arg in (sys.executable, "-c", "pass"))
    rules = (
        '[rules]\nextra_exclude_files=["generated.txt", "reset.txt"]\n'
        '[[remove]]\ndir="research"\nreason="r"\n'
        '[[edit]]\nfile="README.md"\nexpect="potato"\n'
        f"command=[{argv}, {receipt.toml_string(padding)}]\n"
        '[[regenerate]]\nfile="generated.txt"\n'
        f"command=[{argv}, {receipt.toml_string(padding)}]\n"
        '[[reset]]\nfile="reset.txt"\nstub="stable reset\\n"\n'
        '[[clean]]\npaths=["build-artifacts", "dist-artifacts"]\n'
    )
    repo = directory_repo(tmp_path, rules)
    (repo / "generated.txt").write_text("stable generated\n", encoding="utf-8")
    (repo / "reset.txt").write_text("old reset\n", encoding="utf-8")
    receipt.write_receipt(
        repo,
        DEST,
        SOURCE,
        ApplyReport(),
        removals=[("retired.md", "retained history")],
    )
    _git(repo, "remote", "set-url", "origin", "https://github.com/potatolabs/other.git")
    _commit(repo)
    return repo


def test_extra_phase_receipt_rows_cross_budget_before_reset_or_commands(
    tmp_path, monkeypatch, capsys
):
    repo = phase_target(tmp_path, padding="payload" * 100)
    before = snapshot(repo)
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", 2500)

    result = main(
        [
            "--target",
            str(repo),
            "--config",
            str(write_answers_file(tmp_path, DEST)),
            "--force",
            "--accept-origin-mismatch",
        ]
    )

    assert result == 2
    assert "directory receipt byte limit" in capsys.readouterr().err
    assert snapshot(repo) == before


def test_extra_phase_receipt_rows_success_control(tmp_path, monkeypatch):
    import template_press.rebrand.cli as cli

    preflight_rows = []
    writer_rows = []
    original_preflight = cli.preflight_receipt
    original_write = cli.write_receipt

    def observe_preflight(source, dest, **kwargs):
        result = original_preflight(source, dest, **kwargs)
        kwargs.pop("renames")
        preflight_rows.append((source, dest, kwargs))
        return result

    def observe_write(target, source, dest, report, **kwargs):
        writer_rows.append((source, dest, kwargs))
        return original_write(target, source, dest, report, **kwargs)

    monkeypatch.setattr(cli, "preflight_receipt", observe_preflight)
    monkeypatch.setattr(cli, "write_receipt", observe_write)
    repo = phase_target(tmp_path)
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", 4096)
    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(write_answers_file(tmp_path, DEST)),
                "--force",
                "--accept-origin-mismatch",
            ]
        )
        == 0
    )
    parsed = tomllib.loads((repo / receipt.RECEIPT_REL).read_text(encoding="utf-8"))[
        "press"
    ]
    # Main and direct apply both budget every field passed to the final writer.
    assert len(preflight_rows) == 2
    assert len(writer_rows) == 1
    assert all(rows == writer_rows[0] for rows in preflight_rows)
    assert parsed["platform"] == sys.platform
    assert parsed["origin_named_destination"] == ["owner"]
    assert parsed["origin_mismatch_accepted"] == {"repo_name": "other"}
    assert parsed["from"] == SOURCE.as_dict_prompted()
    assert parsed["to"] == DEST.as_dict_prompted()
    assert parsed["counts"]["reset"] == 1
    assert parsed["counts"]["edited"] == 1
    assert parsed["counts"]["regenerated"] == 1
    assert parsed["edit"] == [
        {
            "file": "README.md",
            "argv": [sys.executable, "-c", "pass", "small"],
            "expect": "potato",
        }
    ]
    assert parsed["regenerate"] == [
        {"file": "generated.txt", "argv": [sys.executable, "-c", "pass", "small"]}
    ]
    assert parsed["reset"] == [{"file": "reset.txt"}]
    assert {"file": "retired.md", "reason": "retained history"} in parsed["remove"]
    assert parsed["clean"] == [{"paths": ["build-artifacts", "dist-artifacts"]}]
    assert parsed["exempt"] == [
        {
            "file": "generated.txt",
            "reason": "regenerated by declared command; validated by the "
            "press's post-command scan (hermetic verify skips it)",
        },
        {
            "file": "reset.txt",
            "reason": "reset to the declared stub (scanned at plan time)",
        },
    ]


@pytest.mark.parametrize(
    "field",
    [
        "source",
        "dest",
        "platform",
        "origin",
        "clean",
        "legacy",
        "edit",
        "regen",
        "reset",
        "exempt",
    ],
)
def test_complete_preflight_accounts_for_every_serialized_field(
    tmp_path, monkeypatch, field
):
    from dataclasses import replace

    from template_press.rebrand.identity import ValidationError

    from .test_remove_dir_receipt import history_row

    row = history_row()
    kwargs = {
        "removals": [("research/demo.md", "template research")],
        "remove_dirs": [row],
    }
    source, dest = SOURCE, DEST
    # Unicode and escaping require counting the actual TOML UTF-8 output.
    long_text = 'é"' * 500
    if field == "source":
        source = replace(source, author=long_text)
    elif field == "dest":
        dest = replace(dest, author=long_text)
    elif field == "platform":
        kwargs["platform"] = long_text
    elif field == "origin":
        kwargs["origin"] = receipt.OriginDecision(
            named_destination=("owner",), mismatch_accepted=(("repo_name", long_text),)
        )
    elif field == "clean":
        kwargs["clean"] = [(long_text,)]
    elif field == "legacy":
        kwargs["removals"].append(("old.md", long_text))
    elif field == "edit":
        kwargs["edits"] = [("README.md", ("tool", long_text), long_text)]
    elif field == "regen":
        kwargs["regenerations"] = [("generated.txt", ("tool", long_text))]
    elif field == "reset":
        kwargs["resets"] = [long_text]
    else:
        kwargs["exempt"] = [("generated.txt", long_text)]
    path = receipt.write_receipt(tmp_path, source, dest, ApplyReport(), **kwargs)
    assert path.stat().st_size > TEST_LIMIT
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", TEST_LIMIT)
    with pytest.raises(ValidationError, match="directory receipt byte limit"):
        receipt.preflight_receipt(source, dest, **kwargs)
    # Preflight has no target write; existing complete output is untouched.
    assert path.stat().st_size > TEST_LIMIT


def test_preflight_count_widths_cover_maximum_representable_list_lengths(tmp_path):
    from .test_remove_dir_receipt import history_row

    class MaximumLengthList(list):
        def __len__(self):
            return sys.maxsize

    report = ApplyReport(
        replaced=MaximumLengthList(),
        renamed=MaximumLengthList(),
        skipped=MaximumLengthList(),
        regenerated=MaximumLengthList(),
        reset=MaximumLengthList(),
        removed=MaximumLengthList(),
        edited=MaximumLengthList(),
    )
    kwargs = {
        "removals": [("research/demo.md", "template research")],
        "remove_dirs": [history_row()],
    }
    output = receipt.write_receipt(tmp_path, SOURCE, DEST, report, **kwargs)
    budget = receipt.preflight_receipt(SOURCE, DEST, **kwargs)
    assert output.stat().st_size == budget
    parsed = tomllib.loads(output.read_text(encoding="utf-8"))["press"]
    assert set(parsed["counts"].values()) == {sys.maxsize}
    assert len(parsed["counts"]) == 7
    assert len(parsed["completed_at"].encode("utf-8")) == 25


@pytest.mark.parametrize(
    "renames",
    [{}, {"archive": "a"}, {"src/demo_widget": "src/potato_launcher"}],
    ids=["none", "shortening", "unrelated-native-like"],
)
def test_no_possible_current_path_growth_adds_no_budget(renames):
    from .test_remove_dir_receipt import history_row

    kwargs = {
        "removals": [("research/demo.md", "template research")],
        "remove_dirs": [history_row()],
    }
    baseline = receipt.preflight_receipt(SOURCE, DEST, **kwargs)
    assert (
        receipt.preflight_receipt(SOURCE, DEST, renames=renames, **kwargs) == baseline
    )


def test_skipped_shortening_budget_covers_long_intermediate_coordinates(tmp_path):
    from dataclasses import replace

    from template_press.rebrand.removal_types import RemovalPlan
    from template_press.rebrand.remove import translate_removal_plan

    from .test_remove_dir_receipt import history_row

    row = history_row()
    row = replace(
        row,
        current_dir="research",
        members=(replace(row.members[0], current_file="research/demo.md"),),
    )
    long_root = 'extended-é"' * 40
    renames = {"research": long_root, long_root: "r"}
    kwargs = {
        "removals": [("research/demo.md", "template research")],
        "remove_dirs": [row],
    }
    budget = receipt.preflight_receipt(SOURCE, DEST, renames=renames, **kwargs)
    output_sizes = []
    for index, executed in enumerate(({}, renames, {"research": long_root})):
        translated = translate_removal_plan(
            RemovalPlan(retained_history=(row,)), executed
        )
        output = receipt.write_receipt(
            tmp_path / str(index),
            SOURCE,
            DEST,
            ApplyReport(),
            removals=kwargs["removals"],
            remove_dirs=translated.retained_history,
        )
        output_sizes.append(output.stat().st_size)
        assert output.stat().st_size <= budget
    assert output_sizes[2] > max(output_sizes[:2])


@pytest.mark.parametrize("direct", [False, True], ids=["main", "direct-plan"])
def test_inactive_directory_history_also_budgets_all_planned_phases(
    tmp_path, monkeypatch, capsys, direct
):
    from template_press.rebrand.removal_types import DirectoryRemoval

    repo = phase_target(tmp_path, padding="payload" * 100)
    rules_path = repo / "press/press-rules.toml"
    rules_path.write_text(
        rules_path.read_text().replace('[[remove]]\ndir="research"\nreason="r"\n', ""),
        encoding="utf-8",
    )
    receipt.write_receipt(
        repo,
        DEST,
        SOURCE,
        ApplyReport(),
        remove_dirs=[DirectoryRemoval("retired-dir", "retired-dir", "retained", ())],
    )
    _commit(repo)
    before = snapshot(repo)
    rules = load_rules(repo)
    assert not rules.remove_dirs
    prior = receipt.read_receipt(repo)
    removal_plan = plan_removals(repo, rules, source=SOURCE, receipt_text=prior)
    assert not removal_plan.directories
    assert len(removal_plan.retained_history) == 1
    monkeypatch.setattr(receipt, "REMOVE_HISTORY_MAX_BYTES", 2500)
    if direct:
        from template_press.rebrand.regen import plan_edits, plan_regenerate_commands
        from template_press.rebrand.reset import preflight_reset_targets

        plan = build_plan(repo, SOURCE, DEST, rules)
        edit_plans, edit_errors = plan_edits(
            repo, rules.edit, renamed=frozenset(plan.renames)
        )
        regen_plans, regen_errors = plan_regenerate_commands(
            repo, rules.regenerate, renamed=frozenset(plan.renames)
        )
        reset_previews, reset_errors = preflight_reset_targets(
            repo,
            rules,
            source=SOURCE,
            dest=DEST,
            renames=plan.renames,
            table=plan.table,
        )
        assert edit_errors == regen_errors == reset_errors == []
        outcome = _press(
            repo,
            SOURCE,
            DEST,
            rules,
            regen_plans,
            [(preview.rule, preview.stub_text) for preview in reset_previews],
            edit_plans=edit_plans,
            removal_plan=removal_plan,
            table=plan.table,
        )
        assert outcome.env_error is not None
        assert "directory receipt byte limit" in outcome.env_error
        assert "nothing applied" in capsys.readouterr().err
    else:
        assert (
            main(
                [
                    "--target",
                    str(repo),
                    "--config",
                    str(write_answers_file(tmp_path, DEST)),
                    "--force",
                    "--accept-origin-mismatch",
                ]
            )
            == 2
        )
        assert "directory receipt byte limit" in capsys.readouterr().err
    assert snapshot(repo) == before


def retained_path_with_bytes(prefix: str, size: int) -> str:
    """Build absent history text without creating a long filesystem path."""
    path = prefix
    while len((path + "/final.md").encode("utf-8")) + 181 <= size:
        path += "/" + "q" * 180
    path += "/final.md"
    return path + "q" * (size - len(path.encode("utf-8")))


def rename_shape_target(tmp_path: Path, occupied: bool, member_bytes: int = 4080):
    from dataclasses import replace

    from template_press.rebrand.removal_types import DirectoryRemoval, RemovalMember

    from .test_verify_cli import make_pressable

    # Twenty-character components keep the physical fixture portable. Only the
    # absent retained-history string approaches the real 4096-byte field cap.
    source = replace(SOURCE, app_name="old", author="m" * 20)
    dest = replace(DEST, app_name="a" * 20, author="x")
    repo = make_pressable(tmp_path, identity=source.as_dict_prompted())
    root = f"old/{source.author}"
    (repo / root).mkdir(parents=True)
    (repo / root / "grow-seed.txt").write_text("stable\n", encoding="utf-8")
    if occupied:
        (repo / "old/x").mkdir()
        (repo / "old/x/occupied-seed.txt").write_text("occupied\n", encoding="utf-8")
    (repo / "press/press-rules.toml").write_text(
        f'[rules]\nverify_ignore=["{source.author}"]\n'
        '[[replace]]\npattern="{author}"\npaths=true\ncontent=false\n'
        'reason="rename author folder"\n',
        encoding="utf-8",
    )
    member = retained_path_with_bytes(root, member_bytes)
    assert len(member.encode("utf-8")) == member_bytes
    row = DirectoryRemoval(
        root,
        root,
        "retained",
        (RemovalMember(member, member, "retained", root, True),),
    )
    receipt.write_receipt(
        repo,
        dest,
        source,
        ApplyReport(),
        removals=[(member, "retained")],
        remove_dirs=[row],
    )
    _commit(repo)
    return repo, source, dest, row


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
@pytest.mark.parametrize("occupied", [True, False], ids=["occupied", "no-destination"])
def test_main_current_path_shape_refuses_before_any_write(
    tmp_path, capsys, occupied, dry_run
):
    from template_press.rebrand.pathing import translate_path

    repo, source, dest, row = rename_shape_target(tmp_path, occupied)
    plan = build_plan(repo, source, dest, load_rules(repo))
    path = row.members[0].current_file
    # The full projection fits. A stable occupied destination makes the
    # executor leave the 4097-byte intermediate coordinate in the receipt.
    # With no destination the same bound intentionally refuses conservatively.
    assert len(translate_path(path, plan.renames).encode("utf-8")) == 4078
    assert len(translate_path(path, {"old": dest.app_name}).encode("utf-8")) == 4097
    before = snapshot(repo)
    args = [
        "--target",
        str(repo),
        "--config",
        str(write_answers_file(tmp_path, dest)),
        "--force",
    ]
    if dry_run:
        args.append("--dry-run")

    assert main(args) == 2

    stderr = capsys.readouterr().err
    assert "directory text byte limit 4096 exceeded" in stderr
    assert "PARTIALLY" not in stderr
    assert snapshot(repo) == before


@pytest.mark.parametrize("supplied_table", [False, True], ids=["no-table", "table"])
def test_direct_current_path_shape_refuses_before_any_write(
    tmp_path, capsys, supplied_table
):
    repo, source, dest, _row = rename_shape_target(tmp_path, occupied=True)
    rules = load_rules(repo)
    removal_plan = plan_removals(
        repo, rules, source=source, receipt_text=receipt.read_receipt(repo)
    )
    assert not removal_plan.directories
    assert len(removal_plan.retained_history) == 1
    plan = build_plan(repo, source, dest, removal_rules_view(rules, removal_plan))
    before = snapshot(repo)

    outcome = _press(
        repo,
        source,
        dest,
        rules,
        [],
        [],
        removal_plan=removal_plan,
        table=plan.table if supplied_table else None,
    )

    assert outcome.env_error is not None
    assert "directory text byte limit 4096 exceeded" in outcome.env_error
    assert "nothing applied" in capsys.readouterr().err
    assert outcome.renamed == []
    assert outcome.regenerated == []
    assert snapshot(repo) == before


@pytest.mark.parametrize("occupied", [False, True], ids=["no-destination", "occupied"])
def test_current_path_shape_at_limit_succeeds(tmp_path, occupied):
    repo, source, dest, row = rename_shape_target(tmp_path, occupied, member_bytes=4079)

    assert (
        main(
            [
                "--target",
                str(repo),
                "--config",
                str(write_answers_file(tmp_path, dest)),
                "--force",
            ]
        )
        == 0
    )

    text = receipt.read_receipt(repo)
    history = receipt.directory_history_from_receipt(text, dest)
    assert len(history) == 1
    current = history[0].members[0].current_file
    expected_root = f"{dest.app_name}/{source.author if occupied else dest.author}"
    assert (
        current == expected_root + row.members[0].current_file[len(row.current_dir) :]
    )
    assert len(current.encode("utf-8")) == (4096 if occupied else 4077)
    assert (repo / expected_root / "grow-seed.txt").read_text() == "stable\n"
    if occupied:
        assert (
            repo / dest.app_name / "x/occupied-seed.txt"
        ).read_text() == "occupied\n"


def preflight_current_path(
    path: str, renames: dict[str, str], field: str = "current_file"
):
    from template_press.rebrand.removal_types import DirectoryRemoval, RemovalMember

    if field == "current_dir":
        row = DirectoryRemoval("retired", path, "retained", ())
        removals = []
    else:
        row = DirectoryRemoval(
            "retired",
            path.split("/")[0],
            "retained",
            (RemovalMember("retired/gone.md", path, "retained", "retired", True),),
        )
        removals = [("retired/gone.md", "retained")]
    return receipt.preflight_receipt(
        SOURCE, DEST, removals=removals, remove_dirs=[row], renames=renames
    )


@pytest.mark.parametrize("field", ["current_dir", "current_file"])
@pytest.mark.parametrize("initial_bytes", [4094, 4095], ids=["at-limit", "over-limit"])
def test_current_path_field_limit_counts_raw_utf8(field, initial_bytes):
    from template_press.rebrand.identity import ValidationError

    path = retained_path_with_bytes("x", initial_bytes)
    # Replacing one ASCII byte with a three-byte character adds two raw bytes.
    if initial_bytes == 4094:
        assert preflight_current_path(path, {"x": "€"}, field) is not None
    else:
        with pytest.raises(ValidationError, match="directory text byte limit 4096"):
            preflight_current_path(path, {"x": "€"}, field)


def test_current_path_field_limit_ignores_many_unrelated_sibling_renames():
    path = retained_path_with_bytes("old/" + "m" * 20, 4079)
    renames = {"old": "a" * 20, "a" * 20 + "/" + "m" * 20: "a" * 20 + "/x"}
    assert preflight_current_path(path, renames) is not None
    renames.update({f"side-{i}/s": f"side-{i}/" + "z" * 100 for i in range(500)})
    # The path's reachable component widths still total exactly 4096 bytes.
    # A per-field global max-delta times rename-count guard wrongly refuses.
    assert preflight_current_path(path, renames) is not None


@pytest.mark.parametrize("width", [9, 10], ids=["at-limit", "over-limit"])
def test_current_path_field_limit_follows_component_cycles_and_transitive_growth(width):
    from template_press.rebrand.identity import ValidationError
    from template_press.rebrand.pathing import translate_path

    path = retained_path_with_bytes("old/to-change", 4090)
    expanded = "a" * width
    renames = {
        "old": "x",
        "x/to-change": expanded + "/to-change",
        expanded + "/unrelated": "old/unrelated",
    }
    # Full path translation converges despite the conservative component graph
    # containing old -> x -> expanded -> old. The growth follows a shortening.
    assert len(translate_path(path, renames).encode("utf-8")) == 4087 + width
    if width == 9:
        assert preflight_current_path(path, renames) is not None
    else:
        with pytest.raises(ValidationError, match="directory text byte limit 4096"):
            preflight_current_path(path, renames)


@pytest.mark.parametrize("initial_bytes", [4076, 4077], ids=["at-limit", "over-limit"])
def test_current_path_field_limit_bounds_arbitrary_depth_changing_maps(initial_bytes):
    from template_press.rebrand.identity import ValidationError

    path = retained_path_with_bytes("old", initial_bytes)
    renames = {"old": "deep/expanded", "deep/expanded": "x"}
    # This non-compiler mapping takes a conservative 2 * 10 raw-byte fallback.
    if initial_bytes == 4076:
        assert preflight_current_path(path, renames) is not None
    else:
        with pytest.raises(ValidationError, match="directory text byte limit 4096"):
            preflight_current_path(path, renames)


@pytest.mark.parametrize("depth_change", [False, True])
def test_current_path_field_limit_adds_nothing_without_an_initial_prefix(depth_change):
    path = retained_path_with_bytes("safe/x", 4096)
    renames = {"other/x": "other/" + "z" * 100}
    if depth_change:
        renames["unrelated"] = "extra/depth/" + "y" * 100
    assert preflight_current_path(path, renames) is not None


def test_current_path_field_limit_adds_nothing_when_no_prefix_can_grow():
    root = "a/" + "m" * 20
    path = retained_path_with_bytes(root, 4096)
    # Component maxima would overcharge this width-neutral prefix exchange.
    # Every whole-prefix substitution is non-growing, so the field still fits.
    renames = {root: "a" * 20 + "/x"}
    assert len(next(iter(renames.values()))) == len(root)
    assert preflight_current_path(path, renames) is not None
