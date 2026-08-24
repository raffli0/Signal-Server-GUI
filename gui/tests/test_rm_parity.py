"""Radio-Mobile parity & DEM coverage verification tests."""

import os

import pytest

from signal_gui import dem_convert as dc
from signal_gui import output_stage
from signal_gui import params as params_mod

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "Signal-Server", "data")


# --------------------------------------------------------------------------- SDF parsing

def _any_sdf():
    for f in sorted(os.listdir(DATA)):
        if f.endswith(".sdf") and not f.endswith("-hd.sdf"):
            return os.path.join(DATA, f)
    pytest.skip("no sample .sdf in Signal-Server/data")


def test_sdf_bounds_roundtrip():
    path = _any_sdf()
    b = dc.sdf_bounds(path)
    assert b is not None
    lat_lo, lat_hi, lon_lo, lon_hi = b
    assert -90 <= lat_lo < lat_hi <= 90
    assert -180 <= lon_lo < lon_hi <= 180


def test_sdf_point_covered_and_missing():
    boxes = [(-7.0, -6.0, 107.0, 108.0)]
    assert dc.sdf_point_covered(boxes, -6.5, 107.5)
    assert dc.sdf_point_covered(boxes, -7.0, 108.0)   # edges included
    assert not dc.sdf_point_covered(boxes, -5.9, 107.5)
    # antimeridian: tile spanning 179E..-179E
    wrap = [(0.0, 1.0, 179.0, -179.0)]
    assert dc.sdf_point_covered(wrap, 0.5, 179.5)
    assert dc.sdf_point_covered(wrap, 0.5, -179.5)
    assert not dc.sdf_point_covered(wrap, 0.5, 100.0)


def test_sdf_missing_corners_reports_gaps():
    boxes = [(-7.0, -6.0, 107.0, 108.0)]
    missing = dc.sdf_missing_corners(boxes, -6.5, -6.2, 107.2, 107.8)
    assert missing == []
    missing = dc.sdf_missing_corners(boxes, -8.2, -6.5, 106.4, 108.4)
    assert set(missing) == {"SW", "NW", "SE", "NE", "C"}


def test_sdf_dir_boxes_filters_hd_variant(tmp_path):
    src = _any_sdf()
    (tmp_path / "a.sdf").write_text(open(src).read(64))
    (tmp_path / "b-hd.sdf").write_text("junk")
    assert len(dc.sdf_dir_boxes(str(tmp_path), hd=False)) == 1
    assert len(dc.sdf_dir_boxes(str(tmp_path), hd=True)) == 0


# --------------------------------------------------------------------------- raster checks

def test_raster_txt_contains(tmp_path):
    p = tmp_path / "cov_raster.txt"
    p.write_text("-8.18\t107.05\t-199\n-5.48\t108.74\t-35\n")
    assert output_stage.raster_txt_contains(str(p), -6.83, 107.39)
    assert not output_stage.raster_txt_contains(str(p), 10.0, 10.0)


def test_raster_txt_contains_unreadable_is_true_noop(tmp_path):
    # A missing file must not crash the post-run guard; treat as unverifiable.
    assert output_stage.raster_txt_contains(str(tmp_path / "none.txt"), 0.0, 0.0)


# --------------------------------------------------------------------------- argv / summary parity

def test_dbm_forced_when_raster_txt_enabled():
    argv = params_mod.build_argv(
        {"raster_txt": True, "engine": "Standard"},
        engine_exe="signalserver", output_basename="cov",
    )
    assert "-dbm" in argv


def test_dbm_not_forced_without_raster_or_color():
    argv = params_mod.build_argv(
        {"engine": "Standard"}, engine_exe="signalserver", output_basename="cov",
    )
    assert "-dbm" not in argv


def test_run_summary_shows_amsl_when_elevation_known():
    lines = params_mod.format_run_summary(
        {"_tx_ground_elev": 441.0, "_rx_ground_elev": None,
         "tx_height": 50, "rx_height": 1500},
        ["x"], "signalserver",
    )
    tx = next(l for l in lines if l.startswith("[run] Tx"))
    rx = next(l for l in lines if l.startswith("[run] Rx"))
    assert "491 m AMSL" in tx
    assert "AMSL" not in rx.split("tinggi")[1].split("|")[0]
