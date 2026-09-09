"""Unit tests for export_controller module."""

import os
from unittest.mock import MagicMock, patch

from signal_gui import export_controller


def test_export_link_kml_no_link(tmp_path):
    mock_parent = MagicMock()
    with patch("signal_gui.export_controller.QMessageBox.warning") as mock_warn:
        res = export_controller.export_link_kml(mock_parent, {}, {})
        assert res is None
        mock_warn.assert_called_once()


def test_export_link_kmz_no_link(tmp_path):
    mock_parent = MagicMock()
    with patch("signal_gui.export_controller.QMessageBox.warning") as mock_warn:
        res = export_controller.export_link_kmz(mock_parent, {}, {})
        assert res is None
        mock_warn.assert_called_once()


def test_export_model_no_result():
    mock_parent = MagicMock()
    with patch("signal_gui.export_controller.QMessageBox.warning") as mock_warn:
        export_controller.export_model(mock_parent, "KMZ", None, {}, "/tmp")
        mock_warn.assert_called_once()
        args, _ = mock_warn.call_args
        assert "Belum ada hasil kalkulasi cakupan" in args[2]


def test_export_model_with_link_does_not_export_link(tmp_path):
    mock_parent = MagicMock()
    link_only_result = {
        "link": {"obstructed": False, "fade_margin_db": 10.0},
        "params": {"tx_lat": -6.2, "tx_lon": 106.8, "rx_lat": -6.3, "rx_lon": 106.9},
    }
    with patch("signal_gui.export_controller.QMessageBox.warning") as mock_warn, \
         patch("signal_gui.export_controller.export_link_kmz") as mock_link_kmz:
        export_controller.export_model(mock_parent, "KMZ", link_only_result, {}, str(tmp_path))
        # Should warn that no coverage exists and NOT call export_link_kmz
        mock_warn.assert_called_once()
        mock_link_kmz.assert_not_called()


def test_export_model_coverage_success(tmp_path):
    mock_parent = MagicMock()
    png_file = tmp_path / "coverage.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    coverage_result = {
        "png": str(png_file),
        "bbox": (-7.0, -6.8, 107.5, 107.7),
        "params": {"color_file": "rainbow.pal"},
    }
    out_kmz = str(tmp_path / "out.kmz")
    with patch("signal_gui.export_controller.QFileDialog.getSaveFileName", return_value=(out_kmz, "KMZ (*.kmz)")), \
         patch("signal_gui.export_controller.export_coverage_kmz") as mock_cov_kmz:
        export_controller.export_model(mock_parent, "KMZ", coverage_result, {}, str(tmp_path))
        mock_cov_kmz.assert_called_once()



def test_export_raster_txt(tmp_path):
    raw_raster = tmp_path / "raw.txt"
    raw_raster.write_text("0.0\t0.0\t-80.0\n", encoding="utf-8")
    out_txt = str(tmp_path / "rm_out.txt")

    result = {"raster_txt": str(raw_raster)}
    params = {
        "tx_name": "Site_A",
        "rx_name": "Site_B",
        "tx_lat": -6.2,
        "tx_lon": 106.8,
        "tx_height": 30.0,
        "rx_lat": -6.3,
        "rx_lon": 106.9,
        "rx_height": 10.0,
        "rx_threshold_dbm": -90.0,
    }

    with patch("signal_gui.dem_convert.ground_elevation", return_value=100.0):
        export_controller.export_raster_txt(result, params, out_txt, str(tmp_path))

    assert os.path.isfile(out_txt)
    content = open(out_txt, "r", encoding="utf-8").read()
    assert "Site_A" in content
    assert "Site_B" in content
    assert "Fixed unit" in content


def test_main_window_export_coverage_preserved_after_link(tmp_path):
    from signal_gui.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    win.cache_dir = str(tmp_path)
    win._pending = None
    win._last_result = None
    win._last_coverage_result = None
    win._last_link_result = None
    win._set_status = MagicMock()

    # 1. Simulate coverage calculation completed
    png_file = tmp_path / "coverage.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    coverage_result = {
        "png": str(png_file),
        "bbox": (-7.0, -6.8, 107.5, 107.7),
        "params": {"color_file": "rainbow.pal"},
    }
    win._last_coverage_result = coverage_result
    win._last_result = coverage_result

    # 2. Simulate user computing/opening radio link
    win.map = MagicMock()
    win.path_profile_panel = MagicMock()
    win.right_splitter = MagicMock()
    win._right_pane = MagicMock()
    win._right_pane.height.return_value = 500
    win.form = MagicMock()
    win.form.collect.return_value = {"tx_lat": -6.2, "tx_lon": 106.8}
    win.form.kmz_contour_mode = MagicMock()
    win.form.kmz_contour_mode.currentIndex.return_value = 0
    win.form.color_path = MagicMock()
    win.form.color_path.text.return_value = "rainbow.pal"

    link_data = {"obstructed": False, "fade_margin_db": 5.0}
    win._show_link_panel(link_data, (-6.2, 106.8), (-6.3, 106.9))

    # Coverage result must still be intact
    assert win._last_coverage_result == coverage_result
    assert win._last_link_result == {"link": link_data, "params": {"tx_lat": -6.2, "tx_lon": 106.8}}

    # 3. Trigger sidebar export_model - must forward coverage_result, NOT link
    with patch("signal_gui.export_controller.export_model") as mock_exp_model:
        win.export_model("KMZ")
        mock_exp_model.assert_called_once()
        _, kwargs = mock_exp_model.call_args
        assert kwargs["result"] == coverage_result
        assert "link" not in kwargs["result"]

    # 4. Hide link panel
    win._hide_link_panel()
    win.path_profile_panel.setVisible.assert_called_with(False)

    # 5. Trigger sidebar export_model again when link panel is closed - still exports coverage
    with patch("signal_gui.export_controller.export_model") as mock_exp_model:
        win.export_model("KMZ")
        mock_exp_model.assert_called_once()
        _, kwargs = mock_exp_model.call_args
        assert kwargs["result"] == coverage_result


def test_export_model_recovers_from_map_when_png_missing(tmp_path):
    mock_parent = MagicMock()
    # Fake map coverage data URI: base64 of 4 bytes
    fake_b64 = "data:image/png;base64,iVBORw0KGgo="
    mock_parent.map._coverage = (fake_b64, [-7.0, 107.0, -6.5, 107.5])

    out_kmz = str(tmp_path / "out.kmz")
    with patch("signal_gui.export_controller.QFileDialog.getSaveFileName", return_value=(out_kmz, "KMZ (*.kmz)")), \
         patch("signal_gui.export_controller.export_coverage_kmz") as mock_cov_kmz:
        # Pass None as result -> should recover from map
        export_controller.export_model(mock_parent, "KMZ", None, {}, str(tmp_path))
        mock_cov_kmz.assert_called_once()


def test_on_finished_link_failure_does_not_clear_coverage(tmp_path):
    from signal_gui.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    win.cache_dir = str(tmp_path)
    win.progress = MagicMock()
    win._hide_loading = MagicMock()
    win.form = MagicMock()
    win.terminal = MagicMock()
    win.map = MagicMock()
    win.path_profile_panel = MagicMock()
    win._set_status = MagicMock()

    # Pre-existing coverage result
    cov_result = {"png": str(tmp_path / "cov.png"), "bbox": (-7.0, -6.5, 107.0, 107.5)}
    win._last_coverage_result = cov_result
    win._last_result = cov_result

    # Pending was a Radio Link run (path_profile = True)
    win._pending = ({"path_profile": True, "tx_lat": -6.2, "tx_lon": 106.8}, None, str(tmp_path / "run" / "cov"), None, None)

    # Radio Link run fails (ok = False, result = {})
    win._on_finished(False, "error", {})

    # Coverage result MUST still be intact!
    assert win._last_coverage_result == cov_result


