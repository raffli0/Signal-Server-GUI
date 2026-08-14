"""Coordinate parsing: decimal degrees, DMS, and MGRS -> (lat, lon)."""

from __future__ import annotations

import re

try:
    import mgrs
    _MGRS = mgrs.MGRS()
except Exception:  # pragma: no cover - mgrs is a hard dependency
    _MGRS = None


_DEG = "°"


def parse_decimal(text: str) -> float:
    return float(text.strip().replace(_DEG, ""))


def parse_dms(text: str) -> float:
    """Parse a DMS string such as '51 50 56 N', "51°50'56\\"N", '51:50:56N'."""
    text = text.strip().upper().replace("''", '"').replace("º", _DEG)
    hemi = 1.0
    if text.endswith(("N", "S", "E", "W")):
        hemi = -1.0 if text[-1] in ("S", "W") else 1.0
        text = text[:-1]
    # split on any non-numeric separator
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(nums) < 2:
        raise ValueError(f"Cannot parse DMS coordinate: {text!r}")
    d = float(nums[0])
    m = float(nums[1]) if len(nums) > 1 else 0.0
    s = float(nums[2]) if len(nums) > 2 else 0.0
    val = abs(d) + m / 60.0 + s / 3600.0
    return val * hemi


def mgrs_to_latlon(text: str):
    """Return (lat, lon) for an MGRS grid reference."""
    if _MGRS is None:
        raise RuntimeError("mgrs package not available")
    text = text.strip().upper().replace(" ", "")
    lat, lon = _MGRS.toLatLon(text)
    return float(lat), float(lon)


def to_decimal(text: str, fmt: str = "dd") -> float:
    """Parse a coordinate string in the given format ('dd'|'dms'|'mgrs')."""
    fmt = (fmt or "dd").lower()
    if fmt == "dms":
        return parse_dms(text)
    if fmt == "mgrs":
        # mgrs_to_latlon returns (lat, lon); this helper returns the scalar
        # passed by the caller, so raise if used for lat/lon directly.
        raise ValueError("Use mgrs_to_latlon() for MGRS references")
    return parse_decimal(text)


def parse_site(lat_text: str, lon_text: str, fmt: str = "dd"):
    """Parse a lat/lon pair in the chosen format -> (lat, lon)."""
    fmt = (fmt or "dd").lower()
    if fmt == "mgrs":
        return mgrs_to_latlon(lat_text)
    lat = parse_dms(lat_text) if fmt == "dms" else parse_decimal(lat_text)
    lon = parse_dms(lon_text) if fmt == "dms" else parse_decimal(lon_text)
    return lat, lon
