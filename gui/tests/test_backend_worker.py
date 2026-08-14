import os

from PySide6.QtCore import QCoreApplication, QTimer

from signal_gui import backend, params


def test_run_worker_end_to_end(tmp_path):
    engines = backend.find_engines()
    exe = engines.get("signalserver")
    if not exe or not os.path.exists(exe):
        import pytest
        pytest.skip("signalserver binary not built")

    ss_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(exe))))
    data_dir = os.path.join(ss_root, "Signal-Server", "data")
    color = os.path.join(ss_root, "Signal-Server", "color", "rainbow.dcf")
    if not os.path.isdir(data_dir):
        import pytest
        pytest.skip("sample SDF data not present")

    app = QCoreApplication([])
    out_base = str(tmp_path / "cov")
    p = {
        "tx_lat": 51.849, "tx_lon": -2.2299, "tx_height": 25,
        "frequency_mhz": 900, "erp_w": 100.0, "model_pm": 7, "context_pe": 3,
        "terrain_source": "sdf", "sdf_dir": data_dir,
        "resolution": 1200, "radius": 30, "color_file": color,
        "dbm_color": True, "units": "metric", "engine": "Standard",
    }
    worker = backend.RunWorker(exe, out_base, p, dem_spec=None, srtm2sdf_exe=None)
    state = {}
    worker.finished.connect(lambda ok, out, res: state.update(ok=ok, res=res))
    worker.error_occurred.connect(lambda m: state.update(error=m))
    worker.start()

    # Run the event loop until the worker finishes (safety timeout).
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(60000)
    app.exec()

    assert "error" not in state, state.get("error")
    assert state.get("ok") is True
    assert os.path.exists(state["res"]["png"])
    assert state["res"]["bbox"] is not None
