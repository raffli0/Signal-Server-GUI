"""Tests for Radio Mobile TXT import/export (rm_import)."""

import numpy as np
from PIL import Image

from signal_gui import rm_import

# Trimmed from a real Radio Mobile export (tab-separated, lon has a leading
# space, margins can be negative below the threshold).
SAMPLE_TXT = (
    "Range\t40.0dB\t-107.0dBm\n"
    "Fixed unit\t1\tgcs\t-06.83282\t 107.38730\t491.0\n"
    "Mobile unit\t2\tdrone\t-07.14406\t 106.54141\t1976.0\n"
    "Latitude\tLongitude\tRx(dB)\tBest unit\n"
    "-06.16252\t 106.42056\t-022.5\t1\n"
    "-06.16252\t 106.43217\t 010.2\t1\n"
    "-06.16252\t 106.44380\t 037.9\t1\n"
    "-06.17405\t 106.42056\t-023.5\t1\n"
    "-06.17405\t 106.43217\t 011.4\t1\n"
    "-06.17405\t 106.44380\t 038.8\t1\n"
)


def _write_sample(tmp_path):
    p = tmp_path / "rm_export.txt"
    p.write_text(SAMPLE_TXT, encoding="utf-8")
    return str(p)


def test_parse_rm_export(tmp_path):
    data = rm_import.parse_rm_export(_write_sample(tmp_path))
    assert data["threshold_dbm"] == -107.0
    assert data["range_db"] == 40.0
    assert data["fixed"] == {
        "idx": 1, "name": "gcs",
        "lat": -6.83282, "lon": 107.38730, "alt_m": 491.0,
    }
    assert data["mobile"]["name"] == "drone"
    assert len(data["points"]) == 6
    # Margins are stored verbatim (threshold-relative), including negatives.
    assert (-6.17405, 106.42056, -23.5) in [
        (round(a, 5), round(b, 5), c) for a, b, c in data["points"]]
    n, e, s, w = data["bbox"]
    assert abs(n - (-6.16252 + 0.005765)) < 1e-5
    assert abs(s - (-6.17405 - 0.005765)) < 1e-5
    assert e > 106.44380 > w


def test_parse_rejects_non_rm_file(tmp_path):
    p = tmp_path / "other.txt"
    p.write_text("hello world\nnothing here\n", encoding="utf-8")
    try:
        rm_import.parse_rm_export(str(p))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_render_grid_png_band_and_transparency(tmp_path):
    thr, rng = -107.0, 40.0
    pts = [
        (-6.16, 106.42, -5.0),   # below threshold -> transparent
        (-6.16, 106.43, 32.0),   # exactly the 2nd ramp band -> yellow
        (-6.16, 106.44, 40.0),   # top of range -> strongest colour (red)
        (-6.17, 106.42, 40.0),
        (-6.17, 106.43, 32.0),
        (-6.17, 106.44, 40.0),
    ]
    out = tmp_path / "grid.png"
    rm_import.render_grid_png(pts, thr, thr + rng, str(out))
    img = np.asarray(Image.open(out).convert("RGBA"))
    assert img.shape[:2] == (2, 3)
    # Strongest cell is the exact top-of-ramp colour.
    assert tuple(img[0, 2]) == (255, 50, 90, 255)
    # Sub-threshold cell fully transparent.
    assert tuple(img[0, 0]) == (0, 0, 0, 0)
    # Cell on band 2 lands exactly on its ramp colour.
    assert tuple(int(v) for v in img[0, 1][:3]) == (255, 220, 100)
    assert img[0, 1, 3] == 255


def test_write_then_parse_roundtrip(tmp_path):
    raster = tmp_path / "cov_raster.txt"
    raster.write_text(
        "-06.90000  107.60000  -80\n"
        "-06.80000  107.70000  -130\n"
        "-07.00000  107.50000  -60\n",
        encoding="utf-8")
    out = tmp_path / "rm.txt"
    rm_import.write_rm_export(
        str(out), str(raster), threshold_dbm=-100.0,
        tx_name="gcs", tx_lat=-6.83, tx_lon=107.38, tx_amsl=491.0,
        rx_name="drone", rx_lat=-7.14, rx_lon=106.54, rx_amsl=1976.0)

    raw = out.read_text(encoding="utf-8")
    assert "Range\t40.0dB\t-100.0dBm" in raw.splitlines()[0]
    # Margin column, RM style: -80 dBm over -100 threshold -> "00020.0".
    assert "\t00020.0\t1" in raw and "\t-0030.0\t1" in raw and "\t00040.0\t1" in raw

    data = rm_import.parse_rm_export(str(out))
    assert data["threshold_dbm"] == -100.0
    got = {(round(la, 5), round(lo, 5)): m for la, lo, m in data["points"]}
    assert abs(got[(-6.9, 107.6)] - 20.0) < 0.05
    assert abs(got[(-6.8, 107.7)] - (-30.0)) < 0.05
    assert abs(got[(-7.0, 107.5)] - 40.0) < 0.05
