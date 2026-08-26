"""Radio Mobile coverage-data (.txt) import/export + grid rendering.

Import: parse Radio Mobile's own TXT export -- a ``Range`` header line,
``Fixed unit`` / ``Mobile unit`` site lines and a grid of
``Latitude  Longitude  Rx(dB)  Best unit`` rows -- and render it to a
transparent RGBA PNG using :data:`rm_style.COVERAGE_RAMP`, ready to be shown
by ``MapView.show_coverage`` exactly like an engine-produced overlay.

Export: produce the same layout from the engine's raster dump
(``lat lon dbm`` triplets) so results stay interoperable with Radio Mobile in
both directions.

Column semantics (Radio Mobile convention, verified against a real export):
the ``Rx(dB)`` column holds a *margin above the file's threshold*, i.e.
absolute dBm = threshold + value.  Rows below the threshold (negative margin)
are still listed; only values >= 0 fall inside the colour span
(threshold .. threshold + Range).
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Optional

import numpy as np
from PIL import Image

_UNIT_RE = re.compile(
    r"(Fixed|Mobile)\s+unit\s+(-?\d+)\s+(.*?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"Range\s+(-?\d+(?:\.\d+)?)\s*dB\s+(-?\d+(?:\.\d+)?)\s*dBm", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


# --------------------------------------------------------------------------- parse
def _site(line: str) -> Optional[dict]:
    m = _UNIT_RE.match(line)
    if not m:
        return None
    kind, idx, name, lat, lon, alt = m.groups()
    return {
        "kind": kind.lower(),          # "fixed" | "mobile"
        "idx": int(idx),
        "name": name.strip() or kind,
        "lat": float(lat),
        "lon": float(lon),
        "alt_m": float(alt),
    }


def _half_step(vals: list[float]) -> float:
    """Half of the mean spacing between sorted unique coordinates."""
    diffs = [b - a for a, b in zip(vals, vals[1:]) if (b - a) > 1e-9]
    return (sum(diffs) / len(diffs)) / 2.0 if diffs else 0.0


def parse_rm_export(path: str) -> dict:
    """Parse a Radio Mobile TXT export.

    Returns ``{"threshold_dbm", "range_db", "fixed", "mobile", "points", "bbox"}``
    where ``points`` are ``(lat, lon, margin_db)`` triples (margin above the
    threshold, exactly as stored in the file) and ``bbox`` is ``(N, E, S, W)``
    expanded half a grid step beyond the outermost points so that pixel
    centres align with the sample positions on the map.
    """
    threshold_dbm: Optional[float] = None
    range_db = 40.0
    fixed = mobile = None
    points: list[tuple[float, float, float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith("range"):
                m = _RANGE_RE.search(line)
                if m:
                    range_db, threshold_dbm = float(m.group(1)), float(m.group(2))
                continue
            site = _site(line)
            if site is not None:
                if site.pop("kind") == "fixed":
                    fixed = site
                else:
                    mobile = site
                continue
            if low.startswith("latitude"):
                continue  # column header row
            parts = line.split()
            if len(parts) < 3:
                continue
            nums = _NUM_RE.fullmatch(parts[0]), _NUM_RE.fullmatch(parts[1])
            if not all(nums):
                continue
            try:
                lat, lon, val = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            points.append((lat, lon, val))

    if threshold_dbm is None:
        raise ValueError("Header 'Range' tidak ditemukan -- bukan export Radio Mobile?")
    if not points:
        raise ValueError("Tidak ada baris data koordinat di dalam file.")

    lats = sorted({p[0] for p in points})
    lons = sorted({p[1] for p in points})
    hs_lat, hs_lon = _half_step(lats), _half_step(lons)
    bbox = (
        max(lats) + hs_lat, max(lons) + hs_lon,
        min(lats) - hs_lat, min(lons) - hs_lon,
    )
    return {
        "threshold_dbm": threshold_dbm,
        "range_db": range_db,
        "fixed": fixed,
        "mobile": mobile,
        "points": points,
        "bbox": bbox,
    }


# --------------------------------------------------------------------------- render
def render_grid_png(points: Iterable[tuple[float, float, float]],
                    vmin_dbm: float, vmax_dbm: float, out_png: str,
                    ramp: Optional[list[tuple[int, int, int]]] = None) -> str:
    """Render imported grid points to a transparent PNG coverage overlay.

    ``points`` carry margins as parsed from the file; they are converted to
    absolute dBm (``vmin_dbm`` must already be the absolute threshold).
    Pixels whose dBm falls below ``vmin_dbm`` become fully transparent;
    values inside ``[vmin, vmax]`` are linearly interpolated across ``ramp``
    (strongest colour first, matching the engine colour table).
    """
    from . import rm_style

    ramp = list(ramp or rm_style.COVERAGE_RAMP)
    pts = list(points)
    if not pts:
        raise ValueError("Tidak ada titik untuk dirender.")

    lats = sorted({p[0] for p in pts}, reverse=True)   # north (row 0) -> south
    lons = sorted({p[1] for p in pts})                 # west (col 0) -> east
    lat_ix = {v: i for i, v in enumerate(lats)}
    lon_ix = {v: i for i, v in enumerate(lons)}
    h, w = len(lats), len(lons)

    dbm = np.full((h, w), np.nan, dtype=np.float64)
    for lat, lon, margin in pts:
        r, c = lat_ix[lat], lon_ix[lon]
        dbm[r, c] = vmin_dbm + margin                  # margin -> absolute dBm

    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    known = ~np.isnan(dbm)
    visible = known & (dbm >= vmin_dbm)
    rgba[..., 3] = np.where(visible, 255, 0).astype(np.uint8)

    cols = np.asarray(ramp, dtype=np.float64)
    # Position of each cell on the 0(strong)..1(weak) axis, clipped to [0,1].
    t = np.clip((vmax_dbm - dbm) / max(1e-9, vmax_dbm - vmin_dbm), 0.0, 1.0)
    pos = t * (len(ramp) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(ramp) - 1)
    frac = pos - lo
    for ch in range(3):
        chan = cols[lo, ch] * (1.0 - frac) + cols[hi, ch] * frac
        rgba[..., ch] = np.where(visible, chan, 0).astype(np.uint8)

    Image.fromarray(rgba, "RGBA").save(out_png)
    return out_png


# --------------------------------------------------------------------------- export
def _fmt_lat(v: float) -> str:
    return f"{v:09.5f}"


def _fmt_lon(v: float) -> str:
    return f"{v:10.5f}"


def write_rm_export(out_path: str, src_raster_txt: str, *,
                    threshold_dbm: float,
                    tx_name: str, tx_lat: float, tx_lon: float, tx_amsl: float,
                    rx_name: str, rx_lat: float, rx_lon: float, rx_amsl: float,
                    range_db: float = 40.0) -> str:
    """Write a Radio-Mobile-compatible TXT from an engine raster dump.

    Layout mirrors Radio Mobile's own export::

        Range   <range>dB  <threshold>dBm
        Fixed unit  <idx>  <name>  <lat>  <lon>  <antenna AMSL>
        Mobile unit <idx>  <name>  <lat>  <lon>  <antenna AMSL>
        Latitude  Longitude  Rx(dB)  Best unit
        <lat>  <lon>  <margin-over-threshold>  1

    The data column stores the margin above ``threshold_dbm`` (absolute dBm
    minus threshold), matching how Radio Mobile populates its exports.
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(src_raster_txt, "r", encoding="utf-8") as src, \
            open(out_path, "w", encoding="utf-8") as out:
        out.write(f"Range\t{range_db:.1f}dB\t{threshold_dbm:.1f}dBm\n")
        out.write(f"Fixed unit\t1\t{tx_name}\t{_fmt_lat(tx_lat)}\t{_fmt_lon(tx_lon)}"
                  f"\t{float(tx_amsl):.1f}\n")
        out.write(f"Mobile unit\t2\t{rx_name}\t{_fmt_lat(rx_lat)}\t{_fmt_lon(rx_lon)}"
                  f"\t{float(rx_amsl):.1f}\n")
        out.write("Latitude\tLongitude\tRx(dB)\tBest unit\n")
        for line in src:
            parts = line.split()
            if len(parts) != 3:
                continue
            try:
                lat, lon, dbm = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            margin = dbm - threshold_dbm
            out.write(f"{_fmt_lat(lat)}\t{_fmt_lon(lon)}\t{margin:07.1f}\t1\n")
    return out_path
