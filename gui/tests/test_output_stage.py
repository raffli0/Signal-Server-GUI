import os

import numpy as np
from PIL import Image

from signal_gui import output_stage


SAMPLE_STDOUT = (
    "Loading topo data for boundaries: (51.579372N, 1.794542W) to (52.118628N, 2.665258W)\n"
    "Area boundaries:52.118628 | -1.793233 | 51.579372 | -2.666567 \n"
    "[100%] Processing 3386/3382 points\n"
)


def test_parse_bbox():
    bbox = output_stage.parse_bbox(SAMPLE_STDOUT)
    assert bbox == (52.118628, -1.793233, 51.579372, -2.666567)


def test_parse_bbox_falls_back_to_params_when_engine_line_missing():
    # Engine errored but still wrote a PPM; no "Area boundaries" line printed.
    stdout = "Loading topo data for boundaries: (51.5N, 1.7W) to (52.1N, 2.6W)\n"
    params = {"tx_lat": -6.9, "tx_lon": 107.6, "radius": 50}
    bbox = output_stage.parse_bbox(stdout, params=params)
    # Params-based circle, NOT the (larger) DEM tile region.
    assert bbox is not None
    n, e, s, w = bbox
    assert abs(((n + s) / 2) - (-6.9)) < 1e-6
    assert abs(((e + w) / 2) - 107.6) < 1e-6
    # 50 km radius -> ~0.45 deg half-span, nowhere near "entire map".
    assert (n - s) < 2.0 and (e - w) < 2.0


def test_parse_bbox_insane_engine_line_uses_params():
    # A world-scale "Area boundaries" line must not be trusted.
    stdout = "Area boundaries:90.0 | 180.0 | -90.0 | -180.0 \n"
    params = {"tx_lat": -6.9, "tx_lon": 107.6, "radius": 30}
    bbox = output_stage.parse_bbox(stdout, params=params)
    assert bbox is not None
    assert (bbox[0] - bbox[2]) < 2.0


def test_parse_bbox_returns_none_when_no_source():
    assert output_stage.parse_bbox("nothing useful", params=None) is None



def test_build_kml():
    kml = output_stage.build_kml("cov.png", (52.1, -1.7, 51.5, -2.6), "Test")
    assert "<GroundOverlay>" in kml
    assert "<north>52.1</north>" in kml
    assert "<href>cov.png</href>" in kml


def _write_ppm(path, arr):
    arr = np.asarray(arr, dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, format="PPM")


def test_ppm_all_white_becomes_transparent(tmp_path):
    ppm = tmp_path / "t1.ppm"
    _write_ppm(str(ppm), np.full((3, 4, 3), 255, dtype=np.uint8))
    out = output_stage.stage_output(str(ppm), SAMPLE_STDOUT, title="Test")
    assert os.path.exists(out["png"])
    assert os.path.exists(out["kml"])
    assert out["bbox"] == (52.118628, -1.793233, 51.579372, -2.666567)
    img = np.asarray(Image.open(out["png"]).convert("RGBA"))
    assert img.shape[:2] == (3, 4)
    assert (img[..., 3] == 0).all()


def test_tx_center_hole_is_filled(tmp_path):
    w, h = 21, 21
    grey_val = 137
    red = (255, 0, 0)
    green = (0, 255, 0)
    arr = np.full((h, w, 3), grey_val, dtype=np.uint8)
    cx, cy = 10, 10
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    arr[dist <= 8] = green
    hole = dist <= 2
    arr[hole] = 255
    ppm = tmp_path / "hole.ppm"
    _write_ppm(str(ppm), arr)

    png_path = output_stage.ppm_to_png(str(ppm))
    img = np.asarray(Image.open(png_path).convert("RGBA"))

    assert (img[0, :, 3] == 0).all()
    assert (img[-1, :, 3] == 0).all()
    assert (img[:, 0, 3] == 0).all()
    assert (img[:, -1, 3] == 0).all()

    ring = (dist > 2) & (dist <= 8)
    assert (img[ring][..., :3] == green).all()
    assert (img[ring][..., 3] == 255).all()

    assert not (img[hole][..., 3] == 0).any(), "Tx center must not stay transparent"


def test_enclosed_hole_uses_color_file(tmp_path):
    w, h = 15, 15
    blue = (0, 148, 255)
    white = (30, 30, 30)
    magenta = (142, 63, 255)
    arr = np.full((h, w, 3), 200, dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - 7) ** 2 + (yy - 7) ** 2)
    arr[dist <= 6] = blue
    arr[dist <= 1] = white
    ppm = tmp_path / "pal.ppm"
    _write_ppm(str(ppm), arr)
    scf = tmp_path / "custom.scf"
    scf.write_text("128: 142, 63, 255\n59: 0, 208, 0\n")

    png_path = output_stage.ppm_to_png(str(ppm), color_file=str(scf))
    img = np.asarray(Image.open(png_path).convert("RGBA"))

    assert (img[7, 7][..., :3] == magenta).all()
    assert img[7, 7][..., 3] == 255
    assert (img[0, 0][..., 3] == 0).all()


def test_parse_strongest_color_fallback():
    fallback = output_stage.parse_strongest_color(None)
    assert len(fallback) == 3 and all(0 <= c <= 255 for c in fallback)
    assert output_stage.parse_strongest_color("/nonexistent/file.scf") == fallback


def test_extract_hgt(tmp_path):
    from signal_gui import dem_convert
    import zipfile
    zpath = tmp_path / "B48.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("B48/S05E102.hgt", b"\x00\x01\x02\x03")
    hgts = dem_convert.extract_hgt(str(zpath), str(tmp_path / "raw"))
    assert any(f.endswith("S05E102.hgt") for f in hgts)
