import os

import pytest

from signal_gui import backend, params, output_stage


@pytest.mark.integration
def test_engine_pipeline_on_sample_data(tmp_path):
    engines = backend.find_engines()
    exe = engines.get("signalserver")
    if not exe or not os.path.exists(exe):
        pytest.skip("signalserver binary not built")

    ss_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(exe))))
    # ss_root/Signal-Server/data
    data_dir = os.path.join(ss_root, "Signal-Server", "data")
    color = os.path.join(ss_root, "Signal-Server", "color", "rainbow.dcf")
    if not os.path.isdir(data_dir):
        pytest.skip("sample SDF data not present")

    out_base = str(tmp_path / "covout")
    p = {
        "tx_lat": 51.849, "tx_lon": -2.2299, "tx_height": 25,
        "frequency_mhz": 900, "erp_w": 100.0,
        "model_pm": 7, "context_pe": 3,
        "terrain_source": "sdf", "sdf_dir": data_dir,
        "resolution": 1200, "radius": 30,
        "color_file": color, "dbm_color": True,
        "units": "metric", "engine": "Standard",
    }
    argv = params.build_argv(p, engine_exe=exe, output_basename=out_base)
    import subprocess
    res = subprocess.run(argv, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    ppm = out_base + ".ppm"
    assert os.path.exists(ppm)
    staged = output_stage.stage_output(ppm, res.stdout, title="Test")
    assert os.path.exists(staged["png"])
    assert staged["bbox"] is not None
    assert os.path.exists(staged["kml"])
