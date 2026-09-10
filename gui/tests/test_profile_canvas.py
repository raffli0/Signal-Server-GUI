"""Tests for CloudRFProfileCanvas offscreen caching, brown terrain, and Fresnel styling."""

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from signal_gui.cloudrf_profile_panel import (
    CloudRFProfileCanvas, CloudRFPathProfilePanel, compute_terrain_contour_colors
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_profile():
    return {
        "distance_km": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        "terrain_m": [100.0, 120.0, 140.0, 115.0, 105.0, 110.0],
        "los_m": [150.0, 150.0, 150.0, 150.0, 150.0, 150.0],
        "fresnel_lower_m": [150.0, 140.0, 135.0, 137.0, 142.0, 150.0],
        "fresnel_upper_m": [150.0, 160.0, 165.0, 163.0, 158.0, 150.0],
    }


def test_profile_canvas_bg_caching(qapp, sample_profile):
    canvas = CloudRFProfileCanvas()
    canvas.resize(600, 300)
    canvas.set_data(sample_profile)

    assert canvas._bg_cache is None

    # First paint event builds background cache
    b = canvas._get_canvas_bounds()
    assert b is not None
    canvas._render_background_cache(b)
    assert canvas._bg_cache is not None
    assert canvas._bg_cache.size() == canvas.size()

    # Resizing invalidates cache via resizeEvent or size mismatch in paintEvent
    from PySide6.QtGui import QResizeEvent
    canvas.resizeEvent(QResizeEvent(QSize(700, 350), QSize(600, 300)))
    assert canvas._bg_cache is None

    # set_data invalidates cache
    canvas.resize(600, 300)
    canvas._render_background_cache(canvas._get_canvas_bounds())
    assert canvas._bg_cache is not None
    canvas.set_data(sample_profile)
    assert canvas._bg_cache is None


def test_profile_canvas_cursor_tracking(qapp, sample_profile):
    canvas = CloudRFProfileCanvas()
    canvas.resize(600, 300)
    canvas.set_data(sample_profile)

    emitted = []
    canvas.cursor_tracked_2d.connect(lambda *args: emitted.append(args))
    left_emitted = []
    canvas.cursor_left.connect(lambda: left_emitted.append(True))

    # Track at middle of canvas
    canvas._track_at_screen_pos(300, 150)
    assert len(emitted) == 1
    # Arguments: (dist_km, cursor_amsl, cursor_agl, ground_amsl, los_amsl, rx_est_dbm, fspl_db)
    assert 0.0 <= emitted[0][0] <= 5.0

    # Leave event emits cursor_left
    canvas.leaveEvent(None)
    assert len(left_emitted) == 1
    assert canvas._active_idx is None


def test_cloudrf_panel_throttling_and_reset(qapp, sample_profile):
    panel = CloudRFPathProfilePanel()
    panel.resize(700, 350)
    panel.update_link_results({
        "distance_km": 5.0,
        "azimuth_deg": 45.0,
        "model": "ITM",
        "total_loss_db": 98.5,
        "rx_power_dbm": -68.4,
        "obstructed": False,
        "profile": sample_profile
    }, {
        "frequency_mhz": 868.0,
        "tx_lat": -6.2,
        "tx_lon": 106.8,
        "rx_lat": -6.22,
        "rx_lon": 106.84,
        "tx_height_m": 15.0,
        "rx_height_m": 12.0
    })

    assert "-68.4" in panel.lbl_signal_callout.text()

    # Simulate hover signal
    panel._on_cursor_tracked_2d(2.5, 160.0, 40.0, 120.0, 150.0, -55.0, 90.0)
    assert "-55.0" in panel.lbl_signal_callout.text()

    # Cursor left resets to default received power
    panel._on_cursor_left()
    assert "-68.4" in panel.lbl_signal_callout.text()


def test_compute_terrain_contour_colors():
    dists = [0.0, 1.0, 2.0, 3.0, 4.0]
    los = [150.0, 150.0, 150.0, 150.0, 150.0]
    f_lower = [140.0, 140.0, 140.0, 140.0, 140.0]

    # Test 1: Clear terrain -> Green
    terrain_clear = [50.0, 50.0, 50.0, 50.0, 50.0]
    cols = compute_terrain_contour_colors(dists, terrain_clear, los, f_lower)
    assert len(cols) == len(dists) - 1
    assert all(c == QColor("#22C55E") for c in cols)

    # Test 2: Penetrating LOS -> Red
    terrain_obs = [50.0, 160.0, 50.0, 50.0, 50.0]
    cols_obs = compute_terrain_contour_colors(dists, terrain_obs, los, f_lower)
    assert cols_obs[0] == QColor("#EF4444")
    assert cols_obs[1] == QColor("#EF4444")

    # Test 3: Penetrating 60% Fresnel -> Yellow
    terrain_fres = [50.0, 145.0, 50.0, 50.0, 50.0]
    cols_fres = compute_terrain_contour_colors(dists, terrain_fres, los, f_lower)
    assert cols_fres[0] == QColor("#EAB308")

    # Test 4: Valley in deep shadow behind mountain -> Red
    # Mountain at d=1.0 with height 130m, deep valley at d=2.0 with height 10m
    terrain_shadow = [80.0, 130.0, 10.0, 10.0, 80.0]
    cols_shadow = compute_terrain_contour_colors(dists, terrain_shadow, los, f_lower)
    assert cols_shadow[1] == QColor("#EF4444")  # in shadow of mountain

