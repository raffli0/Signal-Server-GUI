"""Tests for the azimuth-sector display mask (output_stage.mask_png_sector)."""

import numpy as np
from PIL import Image

from signal_gui import output_stage


def _make_png(tmp_path, name="cov.png", n=20):
    """n x n fully-opaque red square spanning lat 0..1 / lon 100..101."""
    arr = np.zeros((n, n, 4), dtype=np.uint8)
    arr[..., :3] = (255, 0, 0)
    arr[..., 3] = 255
    p = tmp_path / name
    Image.fromarray(arr, "RGBA").save(p)
    return str(p)


def _alphas(path):
    return np.asarray(Image.open(path).convert("RGBA"))[..., 3]


BBOX = (1.0, 101.0, 0.0, 100.0)


def test_full_sector_keeps_everything(tmp_path):
    p = _make_png(tmp_path)
    output_stage.mask_png_sector(p, BBOX, 0.5, 100.5, 0.1, 360.0)
    assert (_alphas(p) == 255).all()


def test_east_west_split(tmp_path):
    # Tx at the centre; the eastern half survives, west edge is blanked.
    p = _make_png(tmp_path)
    output_stage.mask_png_sector(p, BBOX, 0.5, 100.5, 45.0, 135.0)
    a = _alphas(p)
    assert not a[:, 0].any()                       # due-west edge masked
    assert a[9:11, 14:].all()                      # due-east core kept


def test_wrap_over_north(tmp_path):
    # Sector 300..60 wraps across North: north edge stays, south edge goes.
    p = _make_png(tmp_path)
    output_stage.mask_png_sector(p, BBOX, 0.5, 100.5, 300.0, 60.0)
    a = _alphas(p)
    assert a[:2].all()                             # due-north band kept
    assert not a[-2:, 5:-5].any()                  # due-south band masked


def test_tx_cell_survives_tiny_sector(tmp_path):
    p = _make_png(tmp_path)
    output_stage.mask_png_sector(p, BBOX, 0.5, 100.5, 10.0, 20.0)
    a = _alphas(p)
    # The pixel containing the Tx is never blanked.
    row = int((1.0 - 0.5) / 1.0 * 20)
    col = int((100.5 - 100.0) / 1.0 * 20)
    assert a[row, col] == 255
