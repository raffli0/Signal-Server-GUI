"""Tests for Radio Link parsing/reconstruction (link_parse)."""

import math

import pytest

from signal_gui import link_parse
from signal_gui.rm_style import load_sdf_tile


def _make_sdf(dir_path, value_base=600):
    """3x3 tile covering lat -7..-6.9 / lon 107.5..107.6, written into dir."""
    dir_path.mkdir(parents=True, exist_ok=True)
    # Header: max_west, min_north, min_west, max_north -- then rows S->N.
    lines = ["252.500000", "-7.000000", "252.400000", "-6.900000"]
    for r in range(3):                       # row 0 = south
        lines.append(" ".join(str(value_base + c * 25 + r * 15)
                              for c in range(3)))
    (dir_path / "t.sdf").write_text("\n".join(lines) + "\n")
    return str(dir_path)


REPORT = """Signal-Server Point-To-Point Report

Transmitter site: gcs
	2.685 miles, 27.340 degrees grid from receiver.

Antenna height: 30.00 meters AGL / 750.00 meters AMSL

Receiver site: drone
	4.430 miles, 207.340 degrees grid from transmitter.

Antenna height: 100.00 meters AGL / 700.00 meters AMSL

Distance to drone: 4.43 kilometers
Azimuth to drone: 207.34 degrees grid

Free space path loss: 104.50 dB
Computed path loss: 103.80 dB
Attenuation due to terrain shielding: -0.70 dB
Signal power level at drone: -58.82 dBm
"""


def _engine_files(base, curv, f60):
    open(base + ".txt", "w").write(REPORT)
    open(base + "_curvature", "w").write(
        "".join(f"{d:.3f} {v:.3f}\n" for d, v in zip([0, 1, 2, 3, 4], curv)))
    open(base + "_fresnel60", "w").write(
        "".join(f"{d:.3f} {v:.3f}\n" for d, v in zip([0, 1, 2, 3, 4], f60)))
    # Engine's _profile only carries sub-set LOS-piercing points; prove we no
    # longer depend on it by writing an intentionally useless single record.
    open(base + "_profile", "w").write("4.000 0.000")


def test_parse_reconstructs_terrain_from_sdf(tmp_path):
    sdf = _make_sdf(tmp_path / "sdf")
    base = str(tmp_path / "lnk")
    # Engine order is TX -> RX: starts at the TX tip (750), ends at RX (700).
    los_txrx = [750.0, 737.5, 725.0, 712.5, 700.0]
    f60_txrx = [0.0, -10.0, -14.0, -10.0, 0.0]
    _engine_files(base, [-v for v in los_txrx], f60_txrx)

    link = link_parse.parse_link_output(
        base, -100.0, sdf_dir=sdf,
        tx_latlon=(-6.92, 107.58), rx_latlon=(-6.95, 107.55))

    assert link["distance_km"] == pytest.approx(4.43)
    assert link["azimuth_deg"] == pytest.approx(207.34)
    assert link["rx_power_dbm"] == pytest.approx(-58.82)
    assert link["fade_margin_db"] == pytest.approx(41.18)

    prof = link["profile"]
    assert len(prof["distance_km"]) == 6
    assert prof["distance_km"][-1] == pytest.approx(4.43)
    # Series was flipped to RX -> TX and anchored on both antenna tips.
    assert prof["los_m"][0] == pytest.approx(700.0)
    assert prof["los_m"][-1] == pytest.approx(750.0)
    assert prof["terrain_m"][0] == pytest.approx(700.0)
    assert prof["terrain_m"][-1] == pytest.approx(750.0)
    # Ground inside the low tile stays below the Fresnel lower boundary.
    assert not link["obstructed"]
    assert link["worst_clearance_m"] > 0


def test_parse_detects_obstruction(tmp_path):
    sdf = _make_sdf(tmp_path / "sdf", value_base=900)
    base = str(tmp_path / "lnk")
    los_txrx = [750.0, 737.5, 725.0, 712.5, 700.0]
    f60_txrx = [0.0, -10.0, -14.0, -10.0, 0.0]
    _engine_files(base, [-v for v in los_txrx], f60_txrx)

    link = link_parse.parse_link_output(
        base, -100.0, sdf_dir=sdf,
        tx_latlon=(-6.92, 107.58), rx_latlon=(-6.95, 107.55))
    assert link["obstructed"]
    assert link["worst_clearance_m"] < 0


def test_requires_terrain_source(tmp_path):
    base = str(tmp_path / "lnk")
    los = [700.0] * 3
    _engine_files(base, [-v for v in los], [0.0, -5.0, 0.0])
    with pytest.raises(RuntimeError):
        link_parse.parse_link_output(base, -100.0)


def _make_asc(dir_path, value_base=600):
    """Tiny ESRI ASCII grid covering the same window as _make_sdf."""
    dir_path.mkdir(parents=True, exist_ok=True)
    asc = dir_path / "demnas.asc"
    # 3x3 cells of 0.05 deg starting at (-7.0, 107.5): rows go north->south.
    rows = "\n".join(
        " ".join(str(value_base + c * 25) for c in range(3))
        for _ in range(3))
    asc.write_text(
        "ncols         3\n"
        "nrows         3\n"
        "xllcorner     107.5\n"
        "yllcorner     -7.0\n"
        "cellsize      0.05\n"
        "NODATA_value  -9999\n"
        f"{rows}\n")
    return str(asc)


def test_parse_reconstructs_terrain_from_lidar_asc(tmp_path):
    asc = _make_asc(tmp_path / "lidar")
    base = str(tmp_path / "lnk")
    los_txrx = [750.0, 737.5, 725.0, 712.5, 700.0]
    _engine_files(base, [-v for v in los_txrx],
                  [0.0, -10.0, -14.0, -10.0, 0.0])

    link = link_parse.parse_link_output(
        base, -100.0, asc_file=asc,
        tx_latlon=(-6.92, 107.58), rx_latlon=(-6.95, 107.55))

    prof = link["profile"]
    assert len(prof["distance_km"]) == 6
    assert prof["terrain_m"][0] == pytest.approx(700.0)
    assert prof["terrain_m"][-1] == pytest.approx(750.0)
    assert not link["obstructed"]


def test_geo_helpers_roundtrip():
    brg = link_parse._initial_bearing(-6.95, 107.55, -6.92, 107.58)
    lat, lon = link_parse._destination_point(-6.95, 107.55, brg, 4.43)
    assert abs(lat - (-6.92)) < 0.01
    assert abs(lon - 107.58) < 0.01
