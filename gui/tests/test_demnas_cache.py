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
