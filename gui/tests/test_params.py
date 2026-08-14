import math

from signal_gui import params


def test_compute_erp_basic():
    # 100 W, 0 dB net gain (10 dBi - 2.15 - 7.85 loss? use zero loss)
    erp = params.compute_erp(100, 2.15, 0.0)
    assert abs(erp - 100.0) < 1e-6


def test_compute_erp_gain_and_loss():
    erp = params.compute_erp(100, 12.15, 3.0)
    # gain 10 dB -> x10, loss 3 dB -> /10^(0.3) = /1.99526 => ~501.187 W
    assert abs(erp - 100 * 10 / (10 ** 0.3)) < 1e-6


def test_eirp_dbm():
    assert abs(params.eirp_dbm(100) - (10 * math.log10(100000) + 2.14)) < 1e-6


def test_build_argv_flags():
    p = {
        "tx_lat": 51.849, "tx_lon": -2.2299, "tx_height": 30,
        "frequency_mhz": 900, "erp_w": 100.0,
        "antenna_basename": "/x/DB413-B", "polarization": "horizontal",
        "azimuth_deg": 45, "model_pm": 7, "context_pe": 3,
        "knife_edge": True, "reliability": 50,
        "terrain_source": "sdf", "sdf_dir": "/data",
        "resolution": 1200, "radius": 30, "color_file": "/c/rainbow.dcf",
        "dbm_color": True, "units": "metric", "engine": "Standard",
    }
    argv = params.build_argv(p, engine_exe="/bin/signalserver", output_basename="/tmp/o")
    assert argv[0] == "/bin/signalserver"
    assert "-lat" in argv and "-lon" in argv
    assert "-erp" in argv and argv[argv.index("-erp") + 1] == "100.0"
    assert "-hp" in argv
    assert "-pm" in argv and argv[argv.index("-pm") + 1] == "7"
    assert "-pe" in argv and argv[argv.index("-pe") + 1] == "3"
    assert "-ked" in argv
    assert "-sdf" in argv and argv[argv.index("-sdf") + 1] == "/data"
    assert "-m" in argv
    assert "-dbm" in argv
    assert argv[-2:] == ["-o", "/tmp/o"]


def test_build_argv_lidar():
    p = {"engine": "LIDAR", "lidar_file": "/d/sk.asc", "tx_lat": 1, "tx_lon": 1}
    argv = params.build_argv(p, engine_exe="signalserverLIDAR", output_basename="/tmp/o")
    assert "-lid" in argv and "/d/sk.asc" in argv
    assert "-sdf" not in argv


def test_iter_obstacles():
    items = list(params.iter_obstacles("51.8,-2.2,10\n52.0,-2.0,20\n\n"))
    assert items == ["51.8,-2.2,10", "52.0,-2.0,20"]
