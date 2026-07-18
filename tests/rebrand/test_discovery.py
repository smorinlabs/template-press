import subprocess
from pathlib import Path

from template_press.rebrand.discovery import discover, mismatches

from .conftest import SOURCE


def test_discover_src_layout(src_target: Path):
    found = discover(src_target)
    assert found.package_name == "demo_widget"
    assert found.app_name == "press"
    assert found.owner == "demolabs"
    assert found.repo_name == "demo-widget"
    assert found.author == "Demo Author"
    assert found.email == "demo@example.com"
    assert found.layout == "src"


def test_discover_flat_layout(flat_target: Path):
    assert discover(flat_target).layout == "flat"


def test_discover_tolerates_missing_origin(src_target: Path):
    # S603, S607: git binary is hardcoded (not from untrusted input)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(src_target), "remote", "remove", "origin"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    found = discover(src_target)
    assert found.owner is None and found.repo_name is None
    assert found.package_name == "demo_widget"  # rest still discovered


def test_mismatches_empty_when_source_matches(src_target: Path):
    assert mismatches(SOURCE, discover(src_target)) == []


def test_mismatches_reported_loudly(src_target: Path):
    wrong = SOURCE.__class__(
        **{**SOURCE.as_dict_prompted(), "package_name": "other_pkg"}
    )
    msgs = mismatches(wrong, discover(src_target))
    assert any("package_name" in m and "other_pkg" in m for m in msgs)


def test_declared_package_without_package_dir_is_a_mismatch(
    src_target: Path, guarded_rmtree
):
    # Containment-checked delete (Task 0.5, G1): assert the path is under the
    # tmp target before rmtree, instead of a raw shutil.rmtree.
    guarded_rmtree(src_target / "src", src_target)
    msgs = mismatches(SOURCE, discover(src_target))
    assert any("layout" in m for m in msgs)
