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
    ring_px = img[ring]
    # DEM-shaded green: hue preserved (r=b=0), brightness follows
    # (255 * dem_grey) / 255 -- i.e. the local DEM greyscale itself
    ring = (dist > 2) & (dist <= 8)
    ring_px = img[ring]
    assert (ring_px[..., 3] == 255).all()
    assert not (img[hole][..., 3] == 0).any(), "Tx center must not stay transparent"


def test_enclosed_hole_uses_color_file(tmp_path):
    w, h = 15, 15
    blue = (0, 148, 255)

    magenta = (142, 63, 255)
    arr = np.full((h, w, 3), 200, dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - 7) ** 2 + (yy - 7) ** 2)
    arr[dist <= 6] = blue
    arr[dist <= 1] = (255, 255, 255)               # saturated white core
    ppm = tmp_path / "pal.ppm"
    _write_ppm(str(ppm), arr)
    scf = tmp_path / "custom.scf"
    scf.write_text("128: 142, 63, 255\n59: 0, 208, 0\n")

    png_path = output_stage.ppm_to_png(str(ppm), color_file=str(scf))
    img = np.asarray(Image.open(png_path).convert("RGBA"))

    assert (img[7, 7][..., :3] == magenta).all()   # pure-white shade -> exact band
    assert img[7, 7][..., 3] == 255   # core stays fully opaque (no alpha hacks)
    assert (img[0, 0][..., 3] == 0).all()


def test_core_recolour_keeps_relief_texture(tmp_path):
    """Two grey shades inside the saturated core must map to two DIFFERENT
    modulated colours via Warna_Final = (solid * dem_grey) / 255, not one
    flat fill."""
    w, h = 21, 21
    green = (0, 255, 0)
    arr = np.full((h, w, 3), 200, dtype=np.uint8)          # mid relief
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - 10) ** 2 + (yy - 10) ** 2)
    arr[dist <= 8] = green                                  # coverage band
    arr[(dist <= 6) & (dist > 2)] = 150                     # inner relief
    arr[dist <= 2] = 255                                    # saturated tip
    ppm = tmp_path / "tex.ppm"
    _write_ppm(str(ppm), arr)

    png_path = output_stage.ppm_to_png(str(ppm))            # bundled red-top dcf
    img = np.asarray(Image.open(png_path).convert("RGBA"))

    c150 = tuple(int(v) for v in img[10, 5][:3])   # dist=5 -> inner grey 150
    c_tip = tuple(int(v) for v in img[10, 10][:3]) # dist=0 -> white 255

    assert c150 != c_tip                       # relief texture preserved
    assert abs(c150[0] - 255 * (150 / 255)) <= 1   # (255 * 150) / 255 = 150
    assert c_tip[0] == 255                     # saturated shade in red family


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


def test_make_flat_transparent_png(tmp_path):
    # Create an image with hillshade variations (contour) and transparent background
    w, h = 20, 20
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    
    # Palette green: (100, 255, 100)
    # Simulate hillshaded variations:
    # slope 1: (70, 180, 70)
    # slope 2: (50, 128, 50)
    # slope 3: (90, 230, 90)
    arr[2:8, 2:8, :3] = (70, 180, 70)
    arr[2:8, 2:8, 3] = 255
    arr[8:14, 2:8, :3] = (50, 128, 50)
    arr[8:14, 2:8, 3] = 255
    arr[14:18, 2:8, :3] = (90, 230, 90)
    arr[14:18, 2:8, 3] = 255

    src_png = tmp_path / "shaded_cov.png"
    Image.fromarray(arr, "RGBA").save(src_png)

    out_png = tmp_path / "flat_trans_cov.png"
    res = output_stage.make_flat_transparent_png(str(src_png), str(out_png), opacity=0.75, relief_weight=0.0)
    assert os.path.exists(res)

    res_img = Image.open(out_png)
    res_arr = np.array(res_img)

    # 1. Background must stay 100% transparent
    assert (res_arr[0, :, 3] == 0).all()
    assert (res_arr[:, 0, 3] == 0).all()

    # 2. Pure flat color (relief_weight = 0.0) -> exactly single palette green
    cov_pixels = res_arr[2:18, 2:8]
    unique_colors = np.unique(cov_pixels[..., :3].reshape(-1, 3), axis=0)
    assert len(unique_colors) == 1, f"Expected 1 flat color, got {len(unique_colors)}"
    assert tuple(unique_colors[0]) == (100, 255, 100)

    # 3. Alpha must be transparent at 75% (191)
    assert (cov_pixels[..., 3] == 191).all()

    # 4. Subtle contour test (relief_weight = 0.30)
    out_subtle = tmp_path / "subtle_cov.png"
    output_stage.make_flat_transparent_png(str(src_png), str(out_subtle), opacity=0.75, relief_weight=0.30)
    subtle_img = Image.open(out_subtle)
    subtle_arr = np.array(subtle_img)
    subtle_cov = subtle_arr[2:18, 2:8]
    # In subtle contour, min green should NOT drop below 180 (soft, gentle shadow, not dark)
    assert subtle_cov[..., 1].min() >= 180
    assert subtle_cov[..., 1].max() <= 255
    assert (subtle_cov[..., 3] == 191).all()


def test_build_kml_opacity():
    kml_trans = output_stage.build_kml("cov.png", (52.1, -1.7, 51.5, -2.6), "Test", opacity=0.75)
    assert "<color>bfffffff</color>" in kml_trans
    assert "<viewBoundScale>0.75</viewBoundScale>" in kml_trans

    kml_none = output_stage.build_kml("cov.png", (52.1, -1.7, 51.5, -2.6), "Test", opacity=None)
    assert "<color>" not in kml_none


def test_export_kmz_flat_transparent(tmp_path):
    import zipfile

    w, h = 10, 10
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[2:8, 2:8, :3] = (50, 128, 50)  # Shaded green
    arr[2:8, 2:8, 3] = 255

    src_png = str(tmp_path / "coverage.png")
    Image.fromarray(arr, "RGBA").save(src_png)

    kmz_path = str(tmp_path / "test_out.kmz")
    bbox = (-6.0, 107.0, -7.0, 106.0)

    output_stage.export_kmz(kmz_path, src_png, bbox, "test_out", flat=True, opacity=0.75, relief_weight=0.30)

    assert os.path.exists(kmz_path)
    with zipfile.ZipFile(kmz_path) as z:
        names = z.namelist()
        assert "doc.kml" in names
        assert any(n.endswith(".png") for n in names)
        with z.open("doc.kml") as f:
            kml_content = f.read().decode("utf-8")
            assert "<GroundOverlay>" in kml_content
            assert "<color>bfffffff</color>" in kml_content
        
        png_arc = [n for n in names if n.endswith(".png")][0]
        with z.open(png_arc) as pf:
            im = Image.open(pf)
            im_arr = np.array(im)
            assert (im_arr[0, 0, 3] == 0)  # transparent background
            assert (im_arr[4, 4, 3] == 191)  # 75% transparent coverage
            # Subtle contour: green component stays bright (>180) and not harsh
            assert im_arr[4, 4, 1] >= 180


