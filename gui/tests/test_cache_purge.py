"""Unit tests for the forced post-render cache purge (_purge_render_cache)."""

import os

from signal_gui.main_window import MainWindow


class _FakeTerminal:
    def __init__(self):
        self.lines = []

    def appendPlainText(self, line):
        self.lines.append(line)


def _bare_window(cache_dir):
    """MainWindow instance without running Qt (skips __init__)."""
    win = MainWindow.__new__(MainWindow)
    win.cache_dir = cache_dir
    win.terminal = _FakeTerminal()
    win._pending = None
    return win


def test_purge_keeps_active_run_only(tmp_path):
    stale = tmp_path / "siggui_old"
    stale.mkdir()
    (stale / "coverage.png").write_bytes(b"x")
    tiles = tmp_path / "raw" / "S07E106.hgt"
    tiles.parent.mkdir()
    tiles.write_bytes(b"y")
    active = tmp_path / "siggui_now"
    active.mkdir()
    (active / "coverage.png").write_bytes(b"z")

    win = _bare_window(str(tmp_path))
    win._purge_render_cache(keep=str(active))

    assert not stale.exists()          # sisa render lama -> hilang
    assert (tmp_path / "raw").exists()   # tile DEM dipertahankan (tidak dihapus otomatis)
    assert (active / "coverage.png").exists()  # run aktif dipertahankan
    assert any("[cache]" in ln for ln in win.terminal.lines)


def test_purge_without_keep_removes_everything(tmp_path):
    for name in ("siggui_a", "siggui_b"):
        d = tmp_path / name
        d.mkdir()
        (d / "coverage.png").write_bytes(name.encode())
    (tmp_path / "loose.txt").write_text("junk")

    win = _bare_window(str(tmp_path))
    win._purge_render_cache()

    assert not list(tmp_path.iterdir())
    assert os.path.isdir(win.cache_dir)  # folder dibuat ulang, tetap usable


def test_purge_missing_cache_dir_is_safe(tmp_path):
    win = _bare_window(str(tmp_path / "does_not_exist"))
    win._purge_render_cache()
    assert os.path.isdir(win.cache_dir)


def test_purge_preserves_active_coverage_dir(tmp_path):
    stale = tmp_path / "siggui_old"
    stale.mkdir()
    (stale / "coverage.png").write_bytes(b"old")

    cov_dir = tmp_path / "siggui_coverage"
    cov_dir.mkdir()
    cov_png = cov_dir / "coverage.png"
    cov_png.write_bytes(b"coverage")

    link_dir = tmp_path / "siggui_link"
    link_dir.mkdir()
    (link_dir / "link_report.txt").write_bytes(b"link")

    win = _bare_window(str(tmp_path))
    win._last_coverage_result = {"png": str(cov_png), "bbox": (1, 2, 3, 4)}

    # When radio link finishes and purges with keep=link_dir
    win._purge_render_cache(keep=str(link_dir))

    assert not stale.exists()                      # Stale folder deleted
    assert (cov_dir / "coverage.png").exists()     # Coverage folder preserved!
    assert (link_dir / "link_report.txt").exists() # Active link folder preserved!

