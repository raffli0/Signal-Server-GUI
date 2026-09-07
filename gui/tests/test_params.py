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


def test_compute_erp_rm_compat():
    # Base: 41.1 W, 8 dBi Tx gain, 0.5 dB cable loss
    # EIRP = 41.1 * 10^((8 - 0.5) / 10) = 41.1 * 10^0.75 = 231.14 W
    # RM ERP = 231.14 / 1.64 = 140.94 W (~141 W, 51.49 dBm)
    erp = params.compute_erp(41.1, 8.0, 0.5, rm_compat=True)
    assert 140.5 < erp < 141.5


def test_eirp_dbm():
    assert abs(params.eirp_dbm(100) - (10 * math.log10(100000) + 2.14)) < 1e-6


def test_dbm_dbuv_roundtrip():
    # 50 Ω system: dBµV = dBm + 107.  -100 dBm == +7 dBµV.
    assert abs(params.dbm_to_dbuv(-100.0) - 7.0) < 1e-9
    assert abs(params.dbuv_to_dbm(7.0) - (-100.0)) < 1e-9
    for dbm in (-120, -100, -73.5, 0, 30):
        assert abs(params.dbuv_to_dbm(params.dbm_to_dbuv(dbm)) - dbm) < 1e-9


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
    # FSPL (pm 7) consumes none of the model-specific flags; they are dropped.
    assert "-pe" not in argv
    assert "-ked" not in argv
    assert "-rel" not in argv
    assert "-cl" not in argv
    assert "-sdf" in argv and argv[argv.index("-sdf") + 1] == "/data"
    assert "-m" in argv
    assert "-dbm" in argv
    assert argv[-2:] == ["-o", "/tmp/o"]


def test_build_argv_itm_drops_context_keeps_climate_reliability():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "model_pm": 1, "context_pe": 3, "knife_edge": True,
        "reliability": 80, "climate_zone": 5,
        "terrain_source": "sdf", "sdf_dir": "/data", "radius": 30,
        "engine": "Standard", "units": "metric",
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    # ITM uses climate + reliability, but ignores context; -ked is a no-op.
    assert "-cl" in argv and "-rel" in argv
    assert "-pe" not in argv
    assert "-ked" not in argv


def test_build_argv_empirical_keeps_context_drops_climate():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "model_pm": 3, "context_pe": 2, "knife_edge": True,
        "terrain_source": "sdf", "sdf_dir": "/data", "radius": 30,
        "engine": "Standard", "units": "metric",
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    assert "-pe" in argv and argv[argv.index("-pe") + 1] == "2"
    assert "-cl" not in argv
    assert "-ked" in argv  # empirical models consume -ked


def test_build_argv_segments_passthrough():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "model_pm": 1, "terrain_source": "sdf",
        "sdf_dir": "/data", "radius": 30, "engine": "Standard",
        "units": "metric", "plot_segments": 16,
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    assert "-segments" in argv and argv[argv.index("-segments") + 1] == "16"


def test_option_states_for_model():
    itm = params.option_states_for_model(1)
    assert itm["climate"] == params.OPTION_ACTIVE
    assert itm["reliability"] == params.OPTION_ACTIVE
    assert itm["context"] == params.OPTION_NA
    assert itm["diffraction"] == params.OPTION_BUILTIN
    fspl = params.option_states_for_model(7)
    assert all(v == params.OPTION_NA for v in fspl.values())
    emp = params.option_states_for_model(3)
    assert emp["context"] == params.OPTION_ACTIVE
    assert emp["diffraction"] == params.OPTION_ACTIVE


def test_auto_segments_bounds():
    seg = params.auto_segments()
    assert seg >= 4 and seg % 2 == 0 and seg <= 254


def test_build_argv_draft_halves_resolution_and_segments():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "model_pm": 1, "terrain_source": "sdf",
        "sdf_dir": "/data", "radius": 30, "engine": "Standard",
        "units": "metric", "resolution": 1200, "plot_quality": "draft",
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    assert "-res" in argv
    assert argv[argv.index("-res") + 1] == "600"    # 1200 -> 600 for draft (halves pixels per degree)
    assert "-segments" in argv                        # always set now
    assert int(argv[argv.index("-segments") + 1]) >= 4


def test_build_argv_lidar():
    p = {"engine": "LIDAR", "lidar_file": "/d/sk.asc", "tx_lat": 1, "tx_lon": 1}
    argv = params.build_argv(p, engine_exe="signalserverLIDAR", output_basename="/tmp/o")
    assert "-lid" in argv and "/d/sk.asc" in argv
    assert "-sdf" not in argv


def test_iter_obstacles():
    items = list(params.iter_obstacles("51.8,-2.2,10\n52.0,-2.0,20\n\n"))
    assert items == ["51.8,-2.2,10", "52.0,-2.0,20"]


def test_build_argv_rx_gain_dbi():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "rx_gain_dbi": 6.0, "rx_height": 1500.0,
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    assert "-rxg" in argv
    assert argv[argv.index("-rxg") + 1] == "6.0"


def test_build_argv_rx_cable_loss():
    p = {
        "tx_lat": 1, "tx_lon": 1, "tx_height": 30, "frequency_mhz": 900,
        "erp_w": 10.0, "rx_gain_dbi": 6.0, "rx_cable_loss_db": 0.5, "rx_height": 1500.0,
    }
    argv = params.build_argv(p, engine_exe="signalserver", output_basename="/tmp/o")
    assert "-rxg" in argv
    assert argv[argv.index("-rxg") + 1] == "5.5"
