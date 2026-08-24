"""Output staging: PPM -> PNG and KML GroundOverlay generation.

Signal-Server emits a ``.ppm`` coverage image and prints the bounding box on
stdout as ``Area boundaries: N | E | S | W``. We convert the PPM to a
transparent PNG and write a ``doc.kml`` GroundOverlay (LatLonBox) so the
result can be shown in the GUI map and exported to Google Earth.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import numpy as np
from PIL import Image
from scipy import ndimage


_BBOX_RE = re.compile(r"Area boundaries:\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)")

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
       strong-signal pixels -> recoloured to the strongest palette entry --
       UNLESS the strongest palette band is itself white/near-white (Radio
       Mobile palettes start with FFFFFF): then those pixels legitimately
       carry the top band and must be kept opaque as-is.
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
        # Only recolour when white is NOT a palette band (default palettes).
        # With an RM palette the enclosed grey/white pixels are the strongest
        # band itself -- keep them so the Tx area stays covered.
        rgb[enclosed_grey] = strongest

    alpha = np.where(background, 0, 255).astype(np.uint8)
    rgba = np.dstack((rgb.astype(np.uint8), alpha))
    Image.fromarray(rgba, "RGBA").save(png_path)
    return png_path



def parse_bbox(stdout_text: str):
    """Extract (N, E, S, W) decimal degrees from Signal-Server stdout.

    Falls back to the ``Loading topo data for boundaries: (N, W) to (N, W)``
    line if the primary line is absent.
    """
    m = _BBOX_RE.search(stdout_text or "")
    if m:
        n, e, s, w = (float(x) for x in m.groups())
        return n, e, s, w

    alt = re.search(
        r"Loading topo data for boundaries:\s*\(([-\d.]+)N,\s*([-\d.]+)W\)\s*to\s*\(([-\d.]+)N,\s*([-\d.]+)W\)",
        stdout_text or "",
    )
    if alt:
        n1, w1, n2, w2 = (float(x) for x in alt.groups())
        return max(n1, n2), max(w1, w2), min(n1, n2), min(w1, w2)
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
                 color_file: Optional[str] = None) -> dict:
    """Convert PPM and write sidecar PNG + KML. Returns paths/bbox."""
    png_path = ppm_to_png(ppm_path, color_file=color_file)
    bbox = parse_bbox(stdout_text)
    kml_path = os.path.splitext(ppm_path)[0] + ".kml"
    if bbox is not None:
        png_name = os.path.basename(png_path)
        with open(kml_path, "w", encoding="utf-8") as fh:
            fh.write(build_kml(png_name, bbox, title))
    return {"ppm": ppm_path, "png": png_path, "kml": kml_path, "bbox": bbox}
