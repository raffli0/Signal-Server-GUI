"""Parse Signal-Server point-to-point (Radio Link / PPA) output files.

In PPA mode Signal-Server writes (given output basename ``base``):

* ``base.txt``            -- human-readable path report (budget).
* ``base_profile``        -- 2 columns: distance, clearance (terrain - LOS).
* ``base_curvature``      -- 2 columns: distance, (terrain - LOS) - terrain
                             which equals ``-(LOS elevation)``.
* ``base_fresnel60``      -- 2 columns: distance, 60% first-Fresnel-zone radius
                             (negative, i.e. below the LOS line).
* ``base_fresnel``        -- full Fresnel radius (negative).
* ``base_reference`` / ``base_clutter`` -- auxiliary series.

From these we reconstruct, for a Radio-Mobile-style profile chart:

* ``terrain``  = profile - curvature   (ground elevation, metres)
* ``los``      = -curvature            (line-of-sight line, metres)
* ``fresnel_lower`` = los - |fresnel60|
* ``fresnel_upper`` = los + |fresnel60|

Obstruction happens where ``terrain > fresnel_lower`` (ground enters the
Fresnel zone).
"""

from __future__ import annotations

import os
import re
from typing import Optional


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


def _parse_float(report: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, report)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, IndexError):
            return None
    return None


def parse_link_output(base: str, rx_threshold_dbm: Optional[float] = None) -> dict:
    """Parse a PPA run rooted at ``base`` (the engine ``-o`` value).

    Returns a dict with the budget fields and the reconstructed profile.
    Raises ``FileNotFoundError``/``RuntimeError`` if essential files are
    missing (so the caller can surface an engine failure).
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
    rx_power = _parse_float(report, r"Signal power level at .*?:\s*([-\d.]+)\s*dBm")

    m = re.search(r"Propagation model:\s*(.+)", report)
    model = m.group(1).strip() if m else None

    # Antenna AMSL used to repair the (degenerate) TX endpoint of the series.
    tx_amsl = _parse_float(report, r"Transmitter site.*?Antenna height:.*?/ ([\d.]+) meters AMSL",)
    rx_amsl = _parse_float(report, r"Receiver site.*?Antenna height:.*?/ ([\d.]+) meters AMSL",)

    # --- profile series --------------------------------------------------
    dist_p, profile = _read_series(base + "_profile")
    _, curvature = _read_series(base + "_curvature")
    _, fresnel60 = _read_series(base + "_fresnel60")

    n = min(len(dist_p), len(curvature))
    if n == 0:
        raise RuntimeError("Link profile series are empty; engine may have failed.")

    terrain = [profile[i] - curvature[i] for i in range(n)]
    los = [-curvature[i] for i in range(n)]
    fres_lower = []
    fres_upper = []
    clearance = []
    obstructed = False
    worst_clearance = float("inf")
    for i in range(n):
        f60 = abs(fresnel60[i]) if i < len(fresnel60) else 0.0
        fl = los[i] - f60
        fu = los[i] + f60
        fres_lower.append(fl)
        fres_upper.append(fu)
        # clearance above the Fresnel lower boundary
        clr = terrain[i] - fl
        clearance.append(clr)
        if clr < 0:
            obstructed = True
        if clr < worst_clearance:
            worst_clearance = clr

    # Repair the TX endpoint (engine writes 0 for the last sample).
    if tx_amsl is not None and n > 0:
        terrain[-1] = tx_amsl
        los[-1] = tx_amsl
    if rx_amsl is not None and n > 0:
        # RX endpoint already includes the antenna tip via the spike.
        terrain[0] = rx_amsl
        los[0] = rx_amsl

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
        "worst_clearance_m": (None if worst_clearance == float("inf") else worst_clearance),
        "profile": {
            "distance_km": dist_p[:n],
            "terrain_m": terrain,
            "los_m": los,
            "fresnel_lower_m": fres_lower,
            "fresnel_upper_m": fres_upper,
        },
    }
