"""Unit tests for Radio Mobile style support (rm_style) + ppm white band."""

import os
import re

import numpy as np
from PIL import Image

from signal_gui import output_stage, rm_style


# A minimal but faithful colors*.dat replica (RM layout: header, 2 settings,
# thresholds, hex colours, trailing flag).
SAMPLE_DAT = "\r\n".join([
    "Color File",
    "0",
    "0",
    "100",
    "300",
    "600",
    "FFFFFF",
    "FF4040",
    "40FF40",
    "4040FF",
    "1",
]) + "\r\n"


def _write_dat(tmp_path, text=SAMPLE_DAT):
    p = tmp_path / "colors_test.dat"
    p.write_text(text, encoding="ascii")
    return str(p)


def test_parse_colors_dat(tmp_path):
    pal = rm_style.parse_colors_dat(_write_dat(tmp_path))
    assert pal.name == "colors_test.dat"
    assert len(pal.colors) == 4
    # Two leading setting lines are not thresholds.
    assert pal.thresholds == [100.0, 300.0, 600.0]
    assert pal.colors[0] == (255, 255, 255)
    assert pal.colors[-1] == (64, 64, 255)


def test_parse_real_rmwcore_palette():
    dat = rm_style.default_dat_path()
    if not dat:
        return  # resources stripped in this environment
    pal = rm_style.parse_colors_dat(dat)
    assert len(pal.colors) >= 10
    assert pal.thresholds == sorted(pal.thresholds)


def test_palette_to_dcf_matches_engine_format(tmp_path):
    pal = rm_style.parse_colors_dat(_write_dat(tmp_path))
    text = rm_style.palette_to_dcf_text(pal, top_dbm=-60, bottom_dbm=-120)
    lines = text.strip().splitlines()
    assert len(lines) == 4
    # sscanf("%d: %d, %d, %d") compatibility + strongest first.
    levels = []
    for ln in lines:
        m = re.match(r"\s*(-?\d+)\s*:\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)$", ln)
        assert m, ln
        levels.append(int(m.group(1)))
    assert levels[0] > levels[-1]
    bands = rm_style.parse_dcf_levels(text)
    # RM convention: first colour (white) = strongest band.
    assert bands[0][1] == (255, 255, 255)
    assert bands[-1][1] == (64, 64, 255)


def test_ensure_palette_dcf_writes_file(tmp_path):
    dest = tmp_path / "out" / "rm.dcf"
    got = rm_style.ensure_palette_dcf(str(dest), dat_path=_write_dat(tmp_path))
    assert os.path.exists(got)
    bands = rm_style.parse_dcf_levels(open(got).read())
    assert len(bands) == 4


def test_ppm_white_band_kept_opaque(tmp_path):
    """With an RM palette (white = strongest band) enclosed grey pixels are
    the top coverage band and must NOT be keyed out or recoloured."""
    w, h = 15, 15
    arr = np.full((h, w, 3), 137, dtype=np.uint8)          # grey background
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - 7) ** 2 + (yy - 7) ** 2)
    green = (0, 255, 0)
    arr[dist <= 6] = green
    arr[dist <= 2] = 255                                   # white top-band core
    ppm = tmp_path / "wb.ppm"
    Image.fromarray(arr, "RGB").save(str(ppm), format="PPM")

    scf = tmp_path / "rm.scf"
    scf.write_text("-60: 255, 255, 255\n-70: 0, 255, 0\n")

    png = output_stage.ppm_to_png(str(ppm), color_file=str(scf))
    img = np.asarray(Image.open(png).convert("RGBA"))
    assert (img[0, :, 3] == 0).all()                       # border -> transparent
    assert img[7, 7, 3] == 255                             # white core kept opaque
    assert tuple(img[7, 7][:3]) == (255, 255, 255)         # ...and not recoloured


def test_sdf_tile_load_and_sample(tmp_path):
    n_rows, n_cols = 8, 8
    data = np.arange(n_rows * n_cols, dtype=np.int32).reshape(n_rows, n_cols)
    # Tile covering lat -6..-5, lon 107..108 expressed in SPLAT west degrees.
    tile_lines = ["253.0", "-6.0", "252.0", "-5.0"]
    tile_lines += [str(v) for v in data.reshape(-1)]
    sdf = tmp_path / "-6_-5_252_253.sdf"
    sdf.write_text("\n".join(tile_lines) + "\n")

    src = rm_style.ElevationSource(sdf_dir=str(tmp_path))
    assert src.available
    # Exact grid node (row 2, col 2); rows run south->north like the engine's
    # own SDF writer, so row 2 sits above the southern edge by 2/7 degrees.
    step = 1.0 / 7.0
    lat = np.array([[-6.0 + 2 * step]])
    lon = np.array([[107.0 + 2 * step]])
    vals = src.sample(lat, lon)
    assert np.isfinite(vals).all()
    assert abs(vals[0, 0] - data[2, 2]) < 1e-3   # NW quadrant sample
    outside = src.sample(np.array([[-4.5]]), np.array([[107.5]]))
    assert np.isnan(outside).all()


def test_render_rm_picture_smoke(tmp_path):
    h, w = 32, 32
    elev = np.zeros((h, w))
    yy, xx = np.mgrid[0:h, 0:w]
    elev = 500 * np.exp(-((yy - 16) ** 2 + (xx - 20) ** 2) / 60.0)

    class _Src:
        def available(self):
            return True

        def sample(self, lat, lon):
            return elev

    pal = rm_style.RmPalette("t", [100.0, 400.0],
                             [(255, 255, 255), (255, 64, 64), (64, 255, 64)])
    cov = tmp_path / "cov.png"
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, :3] = (0, 200, 0)
    arr[..., 3] = 160
    Image.fromarray(arr, "RGBA").save(cov)

    out = tmp_path / "rm_pic.png"
    got = rm_style.render_rm_picture(
        str(out), (-6.0, 108.0, -6.2, 107.8),
        coverage_png=str(cov), palette=pal,
        coverage_bands=[(-60, (255, 255, 255)), (-120, (96, 96, 246))],
        sites=[{"kind": "tx", "lat": -6.05, "lon": 107.85, "label": "gcs"},
               {"kind": "rx", "lat": -6.15, "lon": 107.95, "label": "drone"}],
        ranges_km=[5.0], width=320,
        title="GCS <-> drone")
    assert os.path.exists(got)
    img = Image.open(got)
    assert img.size[0] > 320            # legend strip widens the canvas
    assert img.mode == "RGB"


def test_rm_sites_from_params():
    p = {"tx_lat": -6.9, "tx_lon": 107.6, "tx_name": "gcs",
         "rx_lat": -7.1, "rx_lon": 107.7}
    sites = rm_style.rm_sites_from_params(p)
    kinds = {s["kind"] for s in sites}
    assert kinds == {"tx", "rx"}


def test_decode_coverage_field():
    bands = [(-60, (255, 0, 0)), (-120, (0, 0, 255))]
    rgba = np.zeros((3, 3, 4), dtype=np.uint8)
    rgba[0, 0, :3] = (255, 0, 0)
    rgba[0, 0, 3] = 255            # red -> -60
    rgba[1, 1, :3] = (0, 0, 255)
    rgba[1, 1, 3] = 255            # blue -> -120
    rgba[2, 2, 3] = 0              # transparent -> NaN
    rgba[0, 2, :3] = (0, 0, 0)
    rgba[0, 2, 3] = 255            # opaque black (blocked hole) -> NaN
    field = rm_style.decode_coverage_field(rgba, bands)
    assert field[0, 0] == -60
    assert field[1, 1] == -120
    assert np.isnan(field[2, 2])
    assert np.isnan(field[0, 2])


def test_colormap_piecewise():
    levels = np.array([-120.0, -60.0])
    colors = np.array([[0, 0, 255], [255, 0, 0]], dtype=np.float64)
    rgb = rm_style.colormap_piecewise(levels, colors, np.array([-120.0, -90.0, -60.0]))
    assert rgb[0].tolist() == [0, 0, 255]
    assert rgb[2].tolist() == [255, 0, 0]
    assert abs(rgb[1, 0] - 127.5) < 2 and abs(rgb[1, 2] - 127.5) < 2


def _write_asc(tmp_path, n=16):
    txt = ["ncols %d" % n, "nrows %d" % n, "xllcorner 107.8",
           "yllcorner -6.2", "cellsize 0.0125", "NODATA_value -9999"]
    data = np.arange(n * n, dtype=np.int32).reshape(n, n)
    txt += [str(v) for v in data.reshape(-1)]
    p = tmp_path / "dem.asc"
    p.write_text("\n".join(txt) + "\n")
    return str(p)


def test_asc_with_nodata_value_parses(tmp_path):
    asc = _write_asc(tmp_path)
    src = rm_style.ElevationSource(asc_file=asc)
    assert src.available
    elev = src.sample(np.array([[-6.1]]), np.array([[107.9]]))
    assert np.isfinite(elev).all()


def test_render_rm_picture_shaded_bands(tmp_path):
    h, w = 32, 32
    asc = _write_asc(tmp_path)
    cov = tmp_path / "cov.png"
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    disk = (xx - 16) ** 2 + (yy - 16) ** 2 <= 100
    arr[disk, :3] = (96, 96, 246)   # matches bottom band colour
    arr[disk, 3] = 255
    Image.fromarray(arr, "RGBA").save(cov)

    out = tmp_path / "rm_shaded.png"
    got = rm_style.render_rm_picture(
        str(out), (-6.0, 108.0, -6.2, 107.8),
        coverage_png=str(cov),
        coverage_bands=[(-60, (255, 255, 255)), (-120, (96, 96, 246))],
        asc_file=asc, width=160, threshold_dbm=-100)
    assert os.path.exists(got)
    img = np.asarray(Image.open(got).convert("RGB"))
    base = np.asarray(Image.open(rm_style.render_rm_picture(
        str(tmp_path / "rm_base.png"), (-6.0, 108.0, -6.2, 107.8),
        asc_file=asc, width=160)).convert("RGB"))
    # Covered centre must be tinted by the bottom band, not flat terrain grey.
    h, w = img.shape[:2]
    centre = img[h // 2, w // 2]
    assert not np.allclose(centre, base[h // 2, w // 2], atol=15)
    # Hillshade makes the covered disk non-uniform (a flat fill would be
    # constant); its blue channel must vary across the disk.
    blue = img[..., 2].astype(np.int16)
    yy, xx = np.mgrid[0:h, 0:w]
    disk = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= (min(h, w) / 4) ** 2
    assert blue[disk].std() > 5
