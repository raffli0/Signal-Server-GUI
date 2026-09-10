import os
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from signal_gui import map_view
from signal_gui.widgets import ParameterForm
from signal_gui.cloudrf_profile_panel import CloudRFPathProfilePanel
from signal_gui.main_window import MainWindow

TEMPLATE = os.path.join(os.path.dirname(map_view.__file__), "resources", "map.html")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _read_map_template():
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_map_html_has_lock_and_swap_tools():
    html = _read_map_template()
    assert 'id="btn-swap-tool"' in html
    assert 'id="btn-lock-tool"' in html
    assert "function setPointsLocked(locked)" in html
    assert "function toggleLock()" in html
    assert "function swapTxRx()" in html
    assert "if (window.__pointsLocked)" in html


def test_render_html_injects_points_locked():
    html_locked = map_view.render_html(_read_map_template(), None, [], "tx", points_locked=True)
    assert "window.__pointsLocked=true;" in html_locked

    html_unlocked = map_view.render_html(_read_map_template(), None, [], "tx", points_locked=False)
    assert "window.__pointsLocked=false;" in html_unlocked


def test_picker_page_navigation_interception(qapp):
    mv = map_view.MapView()
    page = mv.page()

    lock_emitted = []
    swap_emitted = []
    pick_emitted = []

    mv.lock_toggled.connect(lambda: lock_emitted.append(True))
    mv.swap_requested.connect(lambda: swap_emitted.append(True))
    mv.picked.connect(lambda role, lat, lon: pick_emitted.append((role, lat, lon)))

    # Test toggle_lock
    res_lock = page.acceptNavigationRequest(QUrl("app://toggle_lock"), None, True)
    assert res_lock is False
    assert len(lock_emitted) == 1

    # Test swap
    res_swap = page.acceptNavigationRequest(QUrl("app://swap"), None, True)
    assert res_swap is False
    assert len(swap_emitted) == 1

    # Test pick
    res_pick = page.acceptNavigationRequest(QUrl("app://pick?role=rx&lat=-6.123&lon=106.456"), None, True)
    assert res_pick is False
    assert len(pick_emitted) == 1
    assert pick_emitted[0] == ("rx", -6.123, 106.456)


def test_parameter_form_lock_state(qapp):
    form = ParameterForm()
    assert form.points_locked is False

    # Lock points
    form.set_points_locked(True)
    assert form.points_locked is True
    assert form.btn_pick_tx.isEnabled() is False
    assert form.btn_pick_rx.isEnabled() is False
    assert form.tx_coord.isEnabled() is False
    assert form.rx_coord.isEnabled() is False
    assert "Terkunci" in form.btn_lock_points.text()

    # Unlock points
    form.set_points_locked(False)
    assert form.points_locked is False
    assert form.btn_pick_tx.isEnabled() is True
    assert form.btn_pick_rx.isEnabled() is True
    assert form.tx_coord.isEnabled() is True
    assert form.rx_coord.isEnabled() is True
    assert "Kunci Titik" in form.btn_lock_points.text()


def test_profile_panel_lock_state(qapp):
    panel = CloudRFPathProfilePanel()
    assert panel.points_locked is False
    assert "Lock" in panel.btn_lock.text()

    panel.set_points_locked(True)
    assert panel.points_locked is True
    assert "Locked" in panel.btn_lock.text()

    panel.set_points_locked(False)
    assert panel.points_locked is False
    assert "Lock" in panel.btn_lock.text()


def test_main_window_toggle_points_locked_and_guard_pick(qapp, monkeypatch):
    win = MainWindow()

    # Initial state: unlocked
    assert win.points_locked is False
    win._on_picked("tx", -6.5, 107.5)
    lat, lon = win.form.tx_coord.get()
    assert abs(lat - (-6.5)) < 1e-5 and abs(lon - 107.5) < 1e-5

    # Toggle lock to True
    win.toggle_points_locked(True)
    assert win.points_locked is True
    assert win.form.points_locked is True
    assert win.map.points_locked is True
    assert win.path_profile_panel.points_locked is True

    # Attempt to pick while locked -> coordinates must NOT change
    win._on_picked("tx", -7.0, 108.0)
    lat_after, lon_after = win.form.tx_coord.get()
    assert abs(lat_after - (-6.5)) < 1e-5 and abs(lon_after - 107.5) < 1e-5

    # Unlock again
    win.toggle_points_locked(False)
    assert win.points_locked is False
    win._on_picked("tx", -7.0, 108.0)
    lat_unlocked, lon_unlocked = win.form.tx_coord.get()
    assert abs(lat_unlocked - (-7.0)) < 1e-5 and abs(lon_unlocked - 108.0) < 1e-5


def test_main_window_swap_tx_rx(qapp, monkeypatch):
    win = MainWindow()

    # Set distinct Tx and Rx values
    win.form.tx_coord.set(-6.111111, 106.111111)
    win.form.tx_name.setText("Site-Alpha")
    win.form.tx_height.setValue(45)
    win.form.tx_gain.setValue(18)
    win.form.cable_loss.setValue(1.5)
    win.form.rf_power.setValue(25)
    win.form.tx_thr.setValue(-95)

    win.form.rx_coord.set(-6.999999, 107.999999)
    win.form.rx_name.setText("Site-Bravo")
    win.form.rx_height.setValue(15)
    win.form.rx_gain.setValue(6)
    win.form.rx_cable_loss.setValue(0.5)
    win.form.rx_power.setValue(2)
    win.form.rx_thr.setValue(-105)

    # Perform swap
    win._swap_tx_rx_link()

    # Verify Tx now has Bravo's parameters
    new_tx_lat, new_tx_lon = win.form.tx_coord.get()
    assert abs(new_tx_lat - (-6.999999)) < 1e-5
    assert abs(new_tx_lon - 107.999999) < 1e-5
    assert win.form.tx_name.text() == "Site-Bravo"
    assert win.form.tx_height.value() == 15
    assert win.form.tx_gain.value() == 6
    assert win.form.cable_loss.value() == 0.5
    assert win.form.rf_power.value() == 2
    assert win.form.tx_thr.value() == -105

    # Verify Rx now has Alpha's parameters
    new_rx_lat, new_rx_lon = win.form.rx_coord.get()
    assert abs(new_rx_lat - (-6.111111)) < 1e-5
    assert abs(new_rx_lon - 106.111111) < 1e-5
    assert win.form.rx_name.text() == "Site-Alpha"
    assert win.form.rx_height.value() == 45
    assert win.form.rx_gain.value() == 18
    assert win.form.rx_cable_loss.value() == 1.5
    assert win.form.rx_power.value() == 25
    assert win.form.rx_thr.value() == -95

    # Verify map markers updated
    assert abs(win.map.tx_pos[0] - (-6.999999)) < 1e-5
    assert abs(win.map.rx_pos[0] - (-6.111111)) < 1e-5
