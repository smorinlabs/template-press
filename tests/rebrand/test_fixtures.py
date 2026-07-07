from pathlib import Path


def test_src_target_shape(src_target: Path):
    assert (src_target / ".git").is_dir()
    assert (src_target / "src" / "demo_widget" / "cli.py").is_file()
    assert "Compress" in (src_target / "README.md").read_text(encoding="utf-8")


def test_flat_target_shape(flat_target: Path):
    assert (flat_target / "demo_widget" / "cli.py").is_file()
    assert not (flat_target / "src").exists()
