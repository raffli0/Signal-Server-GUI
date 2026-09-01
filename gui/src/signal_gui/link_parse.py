"""Parse Signal-Server point-to-point (Radio Link / PPA) output files.

In PPA mode Signal-Server writes (given output basename ``base``):

* ``base.txt``       -- human-readable path report (budget).
* ``base_curvature`` -- per-sample ``distance  -(LOS height)`` metres; the LOS
                        line drawn between the two antenna tips.
* ``base_fresnel60`` -- ``distance  -radius`` of the 60 % first Fresnel zone
                        (negative = below the LOS line).
* ``base_profile``   -- ONLY the samples where terrain rises above the LOS
                        line (``terrain - LOS``, positive entries, no trailing
                        newline on the final record).  It is therefore *not*
                        usable as the ground profile -- we reconstruct the true
                        terrain by sampling the SDF tiles along the arc instead
                        (:class:`rm_style.ElevationSource`).
* ``base_reference`` / ``base_clutter`` -- auxiliary series (unused).

Budget fields come straight from the report text; ``Rx(dBm)`` is only printed
by the engine when ERP > 0, which our argv always provides.
"""

from __future__ import annotations

import math
import os
import re
from typing import Optional

import numpy as np

_EARTH_R_KM = 6371.0


def _read_series(path: str):
    """Read a 2-column ``distance value`` text file. Returns (xs, ys)."""
    xs, ys = [], []
    if not os.path.exists(path):
        return xs, ys
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                xs.append(float(parts[0]))
                ys.append(float(parts[1]))
            except ValueError:
                continue
    return xs, ys


def _parse_float(report: str, pattern: str,
                 flags: int = 0) -> Optional[float]:
    m = re.search(pattern, report, flags)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, IndexError):
            return None
    return None


def _destination_point(lat: float, lon: float, bearing_deg: float,
                       dist_km: float) -> tuple[float, float]:
    """Great-circle destination point (initial bearing, spherical Earth)."""
    delta = dist_km / _EARTH_R_KM
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta)
                     + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2))
    return math.degrees(phi2), (math.degrees(lam2) + 540.0) % 360.0 - 180.0


def _initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(dlon))
    return math.degrees(math.atan2(y, x)) % 360.0


def _sample_terrain(sdf_dir: Optional[str], hd: bool,
                    tx: tuple[float, float], rx: tuple[float, float],
                    dists_km: list[float],
                    asc_file: Optional[str] = None) -> list[float]:
    """Ground elevation (m AMSL) along the TX -> RX arc at ``dists_km`` (d=0 at TX)."""
    from .rm_style import ElevationSource

    brg = _initial_bearing(tx[0], tx[1], rx[0], rx[1])
    pts = [_destination_point(tx[0], tx[1], brg, max(0.0, d)) for d in dists_km]
    lats = np.array([p[0] for p in pts])
    lons = np.array([p[1] for p in pts])
    if sdf_dir:
        src = ElevationSource(sdf_dir=sdf_dir, hd=hd)
    else:
        src = ElevationSource(asc_file=asc_file)
    terr = src.sample(lats, lons)
    # Bridge uncovered samples (DEM gaps) so the chart stays continuous.
    if np.isnan(terr).any():
        good = np.isfinite(terr)
        if good.any():
            terr = np.interp(np.arange(len(terr)), np.flatnonzero(good),
                             terr[good])
        else:
            terr = np.zeros_like(terr)
    return [float(v) for v in terr]


def parse_link_output(base: str, rx_threshold_dbm: Optional[float] = None,
                      *, sdf_dir: Optional[str] = None, hd: bool = False,
                      asc_file: Optional[str] = None,
                      tx_latlon: Optional[tuple[float, float]] = None,
                      rx_latlon: Optional[tuple[float, float]] = None) -> dict:
    """Parse a PPA run rooted at ``base`` (the engine ``-o`` value).

    The ground profile is reconstructed by sampling terrain along the arc --
    SDF tiles (``sdf_dir``) or the LIDAR ``.asc`` export (``asc_file``,
    offline DEMNAS mode). Without either source the function raises so the
    caller can surface why the chart cannot be drawn.
    """
    report_path = base + ".txt"
    if not os.path.exists(report_path):
        raise FileNotFoundError(f"Link report not produced: {report_path}")

    with open(report_path, "r", encoding="utf-8", errors="ignore") as fh:
        report = fh.read()

    # --- budget numbers ---------------------------------------------------
    distance_km = _parse_float(report, r"Distance to .*?:\s*([-\d.]+)\s*kilometers")
    if distance_km is None:
        distance_km = _parse_float(report, r"Distance to .*?:\s*([-\d.]+)\s*miles")
        if distance_km is not None:
            distance_km *= 1.609344
    azimuth_deg = _parse_float(report, r"Azimuth to .*?:\s*([-\d.]+)\s*degrees")
    free_space_loss = _parse_float(report, r"Free space path loss:\s*([-\d.]+)\s*dB")
    computed_loss = _parse_float(report, r"Computed path loss:\s*([-\d.]+)\s*dB")
    terrain_shielding = _parse_float(
        report, r"Attenuation due to terrain shielding:\s*([-\d.]+)\s*dB"
    )
    total_loss = _parse_float(
        report, r"Total path loss including .*?antenna pattern:\s*([-\d.]+)\s*dB"
    )
    if total_loss is None:
        total_loss = computed_loss
    rx_power = _parse_float(report, r"Signal power level at .*?:\s*([-+\d.]+)\s*dBm")

    m = re.search(r"Propagation model:\s*(.+)", report)
    model = m.group(1).strip() if m else None

    tx_amsl = _parse_float(
        report, r"Transmitter site.*?Antenna height:.*?/\s*([\d.]+)\s*meters AMSL",
        re.S)
    rx_amsl = _parse_float(
        report, r"Receiver site.*?Antenna height:.*?/\s*([\d.]+)\s*meters AMSL",
        re.S)

    # --- geometry grid: curvature carries every sample --------------------
    dist_c, curvature = _read_series(base + "_curvature")
    _, fresnel60 = _read_series(base + "_fresnel60")
    n = min(len(dist_c), len(fresnel60)) if fresnel60 else len(dist_c)
    if n == 0:
        raise RuntimeError("Link profile series are empty; engine may have failed.")

    total_d = distance_km if distance_km is not None else dist_c[-1]
    # Dists always increases from 0.0 (TX at left) to total_d (RX at right)
    dists = [float(v) for v in np.linspace(0.0, total_d, n)]
    los = [-curvature[i] for i in range(n)]
    f60 = fresnel60[:n]

    # Signal-Server emits the series destination (RX) -> source (TX).
    # We want Left = TX (d=0) to Right = RX (d=total_d).
    starts_at_rx = True
    if tx_amsl is not None and rx_amsl is not None:
        starts_at_rx = abs(los[0] - rx_amsl) < abs(los[0] - tx_amsl)
    if starts_at_rx:
        los.reverse()
        f60.reverse()

    # Anchor endpoints on antenna tips (TX at 0, RX at -1)
    if tx_amsl is not None:
        los[0] = tx_amsl
    if rx_amsl is not None:
        los[-1] = rx_amsl

    # --- true ground profile along TX -> RX arc ---
    if (sdf_dir or asc_file) and tx_latlon and rx_latlon:
        terrain = _sample_terrain(sdf_dir, hd, tx_latlon, rx_latlon, dists,
                                  asc_file=asc_file)
    else:
        raise RuntimeError(
            "Terrain tidak tersedia untuk rekonstruksi profil link "
            "(butuh SDF atau LIDAR .asc).")

    fres_lower, fres_upper, clearance = [], [], []
    obstructed = False
    worst_clearance = float("inf")
    # Interior samples only: at the endpoints the antenna tips anchor the LOS,
    # so clearance is zero there by definition and would mask the real minimum.
    for i in range(n):
        f60v = abs(f60[i])
        fl = los[i] - f60v
        fu = los[i] + f60v
        fres_lower.append(fl)
        fres_upper.append(fu)
        # Path is blocked where the ground rises into the first Fresnel zone;
        # positive clearance = the zone stays free of terrain.
        clr = fl - terrain[i]
        clearance.append(clr)
        if 0 < i < n - 1:
            if clr < 0:
                obstructed = True
            if clr < worst_clearance:
                worst_clearance = clr

    fade_margin = None
    if rx_power is not None and rx_threshold_dbm is not None:
        fade_margin = rx_power - float(rx_threshold_dbm)

    return {
        "report_text": report,
        "distance_km": distance_km,
        "azimuth_deg": azimuth_deg,
        "model": model,
        "free_space_loss_db": free_space_loss,
        "computed_loss_db": computed_loss,
        "terrain_shielding_db": terrain_shielding,
        "total_loss_db": total_loss,
        "rx_power_dbm": rx_power,
        "rx_threshold_dbm": rx_threshold_dbm,
        "fade_margin_db": fade_margin,
        "obstructed": obstructed,
        "worst_clearance_m": (None if worst_clearance == float("inf")
                              else worst_clearance),        "profile": {
            "distance_km": dists,
            "terrain_m": terrain,
            "los_m": los,
            "fresnel_lower_m": fres_lower,
            "fresnel_upper_m": fres_upper,
        },
    }
