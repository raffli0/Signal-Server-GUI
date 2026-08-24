"""DEMNAS offline cache must invalidate when the folder's .tif contents change.

Regression test for the bug where dropping a new .tif into an existing folder
was ignored because the cache was keyed by folder *path* only.
"""

import os

import numpy as np
import pytest
from osgeo import gdal, osr

from signal_gui import dem_convert as dc
from signal_gui.dem_convert import DemResolveError


def _make_tif(path, lat0, lat1, lon0, lon1, elev):
    nx = ny = 40
    arr = np.full((ny, nx), float(elev), dtype=np.float32)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    gt = [lon0, (lon1 - lon0) / nx, 0, lat1, 0, -(lat1 - lat0) / ny]
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(arr)
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.FlushCache()
    ds = None


@pytest.fixture
def demnas_folder(tmp_path):
    folder = tmp_path / "demnas"
    folder.mkdir()
    # Tile A covers lat [-7.0,-6.9] lon [107.5,107.6]
    _make_tif(str(folder / "A.tif"), -7.0, -6.9, 107.5, 107.6, 500.0)
    return folder


def _make_gradient_tif(path, lat0, lat1, lon0, lon1, base, slope):
    nx = ny = 40
    grad = np.linspace(base, base + slope, ny, dtype=np.float32)[:, None]
    arr = np.repeat(grad, nx, axis=1)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    gt = [lon0, (lon1 - lon0) / nx, 0, lat1, 0, -(lat1 - lat0) / ny]
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(arr)
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.FlushCache()
    ds = None


@pytest.fixture
def demnas_gradient_folder(tmp_path):
    folder = tmp_path / "demnas"
    folder.mkdir()
    # Tile with real relief (500 -> 1500 m) so the flat-terrain guard passes.
    _make_gradient_tif(str(folder / "A.tif"), -7.0, -6.9, 107.5, 107.6, 500.0, 1000.0)
    return folder


def test_signature_changes_when_tile_added(demnas_folder):
    sig1 = dc._demnas_folder_signature(str(demnas_folder))
    # adding a new tile must change the cache signature
    _make_tif(str(demnas_folder / "B.tif"), -6.9, -6.8, 107.6, 107.7, 800.0)
    sig2 = dc._demnas_folder_signature(str(demnas_folder))
    assert sig1 != sig2


def test_signature_stable_for_unchanged_contents(demnas_folder):
    a = dc._demnas_folder_signature(str(demnas_folder))
    b = dc._demnas_folder_signature(str(demnas_folder))
    assert a == b


def test_vrt_rebuilds_and_covers_new_tile(tmp_path, demnas_folder):
    cache = str(tmp_path / "cache")
    # Before adding B: only tile A exists -> B's area is NOT covered.
    vrt1 = dc._demnas_vrt(str(demnas_folder), cache)
    assert dc._sample_elevation(vrt1, -6.95, 107.55) is not None  # inside A
    with pytest.raises(DemResolveError):
        dc._assert_covers(vrt1, -6.85, 107.65)  # inside B-only area

    # Add tile B -> signature changes -> VRT rebuilt to include it.
    _make_tif(str(demnas_folder / "B.tif"), -6.9, -6.8, 107.6, 107.7, 800.0)
    vrt2 = dc._demnas_vrt(str(demnas_folder), cache)
    assert vrt2 != vrt1
    # Now the new area is covered and samples real elevation.
    dc._assert_covers(vrt2, -6.85, 107.65)
    assert dc._sample_elevation(vrt2, -6.85, 107.65) is not None


def test_demnas_folder_to_asc_returns_path_and_stats(tmp_path, demnas_gradient_folder):
    cache = str(tmp_path / "cache")
    # bbox fully inside tile A -> full coverage, real relief
    asc, stats = dc.demnas_folder_to_asc(
        str(demnas_gradient_folder), cache,
        -6.98, -6.92, 107.52, 107.58,
        ppd=1200, target_cellsize=3.0 / 3600.0,
    )
    assert asc.endswith(".asc") and os.path.exists(asc)
    assert stats["nodata_pct"] == 0.0
    assert stats["relief_p5p95_m"] > 20.0
    # fixture DEM native resolution is 0.0025 deg -> ppd 400 (engine never
    # upsamples), so just assert a sane positive resolution + integrity.
    assert stats["ppd"] > 0
    assert len(stats["sha256"]) == 16


def test_demnas_folder_to_asc_rejects_flat(tmp_path, demnas_folder):
    cache = str(tmp_path / "cache")
    # tile A is flat at 500 m -> relief guard fires
    with pytest.raises(DemResolveError):
        dc.demnas_folder_to_asc(
            str(demnas_folder), cache,
            -6.98, -6.92, 107.52, 107.58,
            ppd=1200, target_cellsize=3.0 / 3600.0,
        )


def test_demnas_folder_to_asc_rejects_partial_coverage(tmp_path, demnas_gradient_folder):
    cache = str(tmp_path / "cache")
    # bbox mostly outside the single small tile -> >20% NODATA -> rejected
    with pytest.raises(DemResolveError) as exc:
        dc.demnas_folder_to_asc(
            str(demnas_gradient_folder), cache,
            -7.05, -6.85, 107.45, 107.65,  # tile only covers a corner
            ppd=1200, target_cellsize=3.0 / 3600.0,
        )
    assert "NODATA" in str(exc.value)


def test_demnas_folder_to_asc_cellsize_clamp_for_large_radius():
    # A large bbox with a fine target resolution must be clamped by max_cells
    # so the .asc stays loadable (ppd drops below the requested 1200).
    cellsize = dc._asc_cellsize(
        span=5.0, native=0.0, target=3.0 / 3600.0, max_cells=6_000_000, ppd=1200
    )
    assert cellsize > 3.0 / 3600.0  # clamped coarser than requested
    assert round(1.0 / cellsize) < 1200  # effective ppd dropped

