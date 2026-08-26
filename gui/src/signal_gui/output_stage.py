"""Output staging: PPM -> PNG and KML GroundOverlay generation.

Signal-Server emits a ``.ppm`` coverage image and prints the bounding box on
stdout as ``Area boundaries: N | E | S | W``. We convert the PPM to a
transparent PNG and write a ``doc.kml`` GroundOverlay (LatLonBox) so the
result can be shown in the GUI map and exported to Google Earth.
"""

from __future__ import annotations

import math
import os
import re
from typing import Optional

import numpy as np
from PIL import Image
from scipy import ndimage


_BBOX_RE = re.compile(r"Area boundaries:\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)")

# SPLAT stores longitude as west-positive [0, 360). Convert to east-positive.
def _splat_west_to_east(w: float) -> float:
    return (360.0 - w) if w > 180 else -w

# Reject extents that are clearly degenerate or world-scale (the "stretched
# across the whole map" symptom): a sane coverage is well under this.
_MAX_SPAN_DEG = 10.0

def _sane(bbox) -> bool:
    if bbox is None:
        return False
    n, e, s, w = bbox
    if not all(math.isfinite(v) for v in (n, e, s, w)):
        return False
    if n <= s or e <= w:
        return False
    if (n - s) > _MAX_SPAN_DEG or (e - w) > _MAX_SPAN_DEG:
        return False
    return True


def _bbox_from_params(params: Optional[dict]) -> Optional[tuple]:
    """Compute the coverage extent from run params: a circle of ``radius`` km
    centred on the Tx. This is what the engine's crop box approximates, so it
    is the correct fallback when the engine's stdout bbox is unavailable.
    """
    if not params:
        return None
    try:
        lat = float(params["tx_lat"])
        lon = float(params["tx_lon"])
    except (KeyError, TypeError, ValueError):
        return None
    radius_km = float(params.get("radius") or 0) or 30.0
    if radius_km <= 0:
        radius_km = 30.0
    dlat = radius_km / 111.0
    coslat = math.cos(math.radians(lat))
    dlon = radius_km / (111.32 * coslat) if coslat else radius_km / 111.32
    return (lat + dlat, lon + dlon, lat - dlat, lon - dlon)

_DEFAULT_STRONGEST_COLOR = (255, 0, 0)

_PALETTE_RE = re.compile(r"^\s*[+-]?\d+\s*:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def parse_strongest_color(color_file: Optional[str]) -> tuple[int, int, int]:
    """Return the first (strongest) palette entry of an .scf/.dcf/.lcf file."""
    candidates = []
    if color_file and os.path.exists(color_file):
        candidates.append(color_file)
    bundled = os.path.join(os.path.dirname(__file__), "resources", "radiomobile.dcf")
    if os.path.exists(bundled):
        candidates.append(bundled)
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.split(";", 1)[0]
                    m = _PALETTE_RE.match(line)
                    if m:
                        return (min(255, max(0, int(m.group(1)))),
                                min(255, max(0, int(m.group(2)))),
                                min(255, max(0, int(m.group(3)))))
        except OSError:
            continue
    return _DEFAULT_STRONGEST_COLOR


def ppm_to_png(ppm_path: str, png_path: Optional[str] = None,
               color_file: Optional[str] = None) -> str:
    """Convert a PPM coverage image to a transparent PNG.

    Background removal must NOT be a global colour key (the old ImageMagick
    ``-transparent white``): pixels carrying signal stronger than the top
    palette band fall outside every band in Signal-Server's painter
    (outputs.cc) and are drawn as greyscale/white terrain colours right
    around the Tx, producing a hole in the middle of the coverage. Instead:

    1. Grey-ish pixels connected to the image border are background
       (terrain/greyscale backdrop + legend strip) -> alpha 0.
    2. Grey-ish islands fully enclosed by coverage colours are out-of-range
       strong-signal pixels (the saturated Tx core, drawn grey/white by the
       engine because they exceed the top band). They are recoloured to the
       strongest palette entry so the core shows as the strongest colour (red)
       instead of a white hole over a light OSM basemap.
    """
    if png_path is None:
        png_path = os.path.splitext(ppm_path)[0] + ".png"
    rgb = np.asarray(Image.open(ppm_path).convert("RGB")).copy()
    grey = (rgb[..., 0] == rgb[..., 1]) & (rgb[..., 1] == rgb[..., 2])

    labels, _n = ndimage.label(grey)
    border = np.unique(np.concatenate((
        labels[0, :], labels[-1, :],
        labels[:, 0], labels[:, -1],
    )))
    border = border[border != 0]
    if border.size:
        background = np.isin(labels, border)
    else:
        background = np.zeros(grey.shape, dtype=bool)

    strongest = parse_strongest_color(color_file)
    enclosed_grey = grey & ~background
    lum = 0.299 * strongest[0] + 0.587 * strongest[1] + 0.114 * strongest[2]
    if lum < 200:
        # Recolour the saturated Tx core (drawn grey/white by the engine) to the
        # strongest palette band (red), so it stays covered instead of a white hole.
        rgb[enclosed_grey] = strongest

    alpha = np.where(background, 0, 255).astype(np.uint8)
    rgba = np.dstack((rgb.astype(np.uint8), alpha))
    Image.fromarray(rgba, "RGBA").save(png_path)
    return png_path


def mask_png_sector(png_path: str, bbox, tx_lat: float, tx_lon: float,
                    start_deg: float, end_deg: float) -> str:
    """Keep only the bearing wedge ``start..end`` (deg from North) of a PNG.

    The engine always computes the full 360-degree circle; this post-process
    zeroes the alpha of pixels whose great-circle initial bearing from the Tx
    falls outside ``[start, end]`` (``start > end`` wraps over North, e.g.
    300..60 keeps the northern lobe). ``bbox`` is (N, E, S, W) matching the
    overlay extent so pixel centres map linearly to coordinates.
    """
    img = np.asarray(Image.open(png_path).convert("RGBA")).copy()
    h, w = img.shape[:2]
    if w == 0 or h == 0:
        return png_path
    n, e, s, wst = (float(v) for v in bbox)

    ys = (np.arange(h) + 0.5) / h
    xs = (np.arange(w) + 0.5) / w
    lat = n - ys * (n - s)                       # row 0 = north edge
    lon = wst + xs * (e - wst)                   # col 0 = west edge
    lat2 = lat[:, None]
    lon2 = lon[None, :]

    phi1 = math.radians(float(tx_lat))
    phi2 = np.radians(lat2)
    dlon = np.radians(lon2 - float(tx_lon))
    y = np.sin(dlon) * np.cos(phi2)
    x = (np.cos(phi1) * np.sin(phi2)
         - np.sin(phi1) * np.cos(phi2) * np.cos(dlon))
    brg = np.degrees(np.arctan2(y, x)) % 360.0

    keep = ((brg >= start_deg) & (brg <= end_deg)) if start_deg <= end_deg \
        else ((brg >= start_deg) | (brg <= end_deg))
    # Tx cell itself always stays visible.
    keep = keep | (((lat2 - float(tx_lat)) ** 2 + (lon2 - float(tx_lon)) ** 2)
                   <= max((n - s) / h, (e - wst) / w) ** 2)

    img[..., 3] = np.where(keep, img[..., 3], 0).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(png_path)
    return png_path



def parse_engine_bbox_raw(stdout_text: str):
    """Return the engine's ``Area boundaries`` tuple verbatim, or ``None``.

    Unlike :func:`parse_bbox` this performs **no** sanity checks and **no**
    params-based fallback -- callers use it to judge whether the engine itself
    produced trustworthy geometry (the threaded-LIDAR pizza race prints
    world-scale-longitude garbage here).
    """
    m = _BBOX_RE.search(stdout_text or "")
    if not m:
        return None
    try:
        return tuple(float(x) for x in m.groups())
    except ValueError:
        return None


def parse_bbox(stdout_text: str, params: Optional[dict] = None):
    """Extract (N, E, S, W) decimal degrees from Signal-Server stdout.

    Priority:
      1. The engine's authoritative ``Area boundaries`` line (matches the
         actual PPM extent).
      2. The run parameters (a ``radius`` km circle around the Tx) -- used when
         the engine errored but still wrote a PPM, so its bbox line is absent.
         This keeps the overlay correctly sized instead of falling back to the
         oversized DEM/tile region (which made results "stretch" over the map).
      3. The ``Loading topo data for boundaries`` line, only as a last resort
         and with proper west-positive -> east longitude conversion.
    """
    m = _BBOX_RE.search(stdout_text or "")
    if m:
        bbox = tuple(float(x) for x in m.groups())
        if _sane(bbox):
            return bbox
        # Present but insane (e.g. world-scale): prefer the params extent.

    from_params = _bbox_from_params(params)
    if from_params is not None:
        return from_params

    alt = re.search(
        r"Loading topo data for boundaries:\s*\(([-\d.]+)N,\s*([-\d.]+)W\)\s*to\s*\(([-\d.]+)N,\s*([-\d.]+)W\)",
        stdout_text or "",
    )
    if alt:
        n1, w1, n2, w2 = (float(x) for x in alt.groups())
        e1, e2 = _splat_west_to_east(w1), _splat_west_to_east(w2)
        bbox = (max(n1, n2), max(e1, e2), min(n1, n2), min(e1, e2))
        if _sane(bbox):
            return bbox
    return None


def raster_txt_contains(
    raster_txt: str, lat: float, lon: float, tol: float = 0.02
) -> bool:
    """True if the engine's raster dump spans (lat, lon) within ``tol`` degrees.

    Streams the file so huge rasters stay cheap to validate. Rows are
    ``lat<TAB>lon<TAB>value`` (Signal-Server ``-rastertxt`` format).
    """
    n = s = e = w = None
    try:
        with open(raster_txt, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    la, lo = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                n = la if n is None else max(n, la)
                s = la if s is None else min(s, la)
                e = lo if e is None else max(e, lo)
                w = lo if w is None else min(w, lo)
    except OSError:
        return True  # unreadable -> extent unverifiable, do not fail the run
    if n is None:
        # No parsable rows: extent unverifiable -- do not fail the run on it.
        return True
    return (s - tol) <= lat <= (n + tol) and (w - tol) <= lon <= (e + tol)


def build_kml(png_name: str, bbox, title: str = "Coverage") -> str:
    """Build a doc.kml string with a GroundOverlay over ``bbox`` = (N, E, S, W)."""
    n, e, s, w = bbox
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Folder>
    <name>{title}</name>
    <GroundOverlay>
      <name>{title}</name>
      <Icon>
        <href>{png_name}</href>
      </Icon>
      <LatLonBox>
        <north>{n}</north>
        <south>{s}</south>
        <east>{e}</east>
        <west>{w}</west>
        <rotation>0</rotation>
      </LatLonBox>
    </GroundOverlay>
  </Folder>
</kml>
"""


def stage_output(ppm_path: str, stdout_text: str, title: str = "Coverage",
                 tx_coords: Optional[tuple[float, float]] = None,
                 color_file: Optional[str] = None,
                 params: Optional[dict] = None) -> dict:
    """Convert PPM and write sidecar PNG + KML. Returns paths/bbox."""
    png_path = ppm_to_png(ppm_path, color_file=color_file)
    bbox = parse_bbox(stdout_text, params=params)
    kml_path = os.path.splitext(ppm_path)[0] + ".kml"
    if bbox is not None:
        png_name = os.path.basename(png_path)
        with open(kml_path, "w", encoding="utf-8") as fh:
            fh.write(build_kml(png_name, bbox, title))
    return {"ppm": ppm_path, "png": png_path, "kml": kml_path, "bbox": bbox}
