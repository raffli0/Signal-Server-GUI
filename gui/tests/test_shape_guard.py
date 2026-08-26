import pytest
"""Fake-terrain smoke detector (output_stage.analyze_coverage_shape)."""

import numpy as np
from PIL import Image

from signal_gui import output_stage

BBOX = (0.5, 0.5, -0.5, -0.5)          # N, E, S, W (1x1 deg)
TX = (0.0, 0.0)


def _save(tmp_path, arr, name="cov.png"):
    p = tmp_path / name
    Image.fromarray(arr, "RGBA").save(p)
    return str(p)


def _canvas(n=400):
    a = np.zeros((n, n, 4), dtype=np.uint8)
    return a


def test_perfect_circle_is_flagged_as_smooth(tmp_path):
    n = 400
    a = _canvas(n)
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.sqrt((xx - n / 2) ** 2 + (yy - n / 2) ** 2)
    a[r <= n * 0.4] = (255, 0, 0, 255)
    png = _save(tmp_path, a)

    s = output_stage.analyze_coverage_shape(png, BBOX, *TX)
    assert s["fill_az_pct"] == pytest.approx(100.0)
    assert s["edge_rel_std"] < 0.01            # smooth -> flagged


def test_ragged_terrain_edge_is_not_flagged(tmp_path):
    rng = np.random.default_rng(7)
    n = 400
    a = _canvas(n)
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.sqrt((xx - n / 2) ** 2 + (yy - n / 2) ** 2)
    ang = np.arctan2(yy - n / 2, xx - n / 2)
    edge = n * 0.4 * (
        1.0 + 0.30 * np.sin(3 * ang) + 0.20 * np.sin(7 * ang + 1.1)
        + 0.10 * rng.uniform(-1, 1, ang.shape))
    a[r <= edge] = (255, 0, 0, 255)
    png = _save(tmp_path, a)

    s = output_stage.analyze_coverage_shape(png, BBOX, *TX)
    assert s["edge_rel_std"] > 0.10            # clearly ragged


