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
