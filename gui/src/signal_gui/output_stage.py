"""Output staging: PPM -> PNG (ImageMagick) and KML GroundOverlay generation.

Signal-Server emits a ``.ppm`` coverage image and prints the bounding box on
stdout as ``Area boundaries: N | E | S | W``. We convert the PPM to a
transparent PNG and write a ``doc.kml`` GroundOverlay (LatLonBox) so the
result can be shown in the GUI map and exported to Google Earth.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional


_BBOX_RE = re.compile(r"Area boundaries:\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)")


def find_convert() -> str:
    for exe in ("convert", "magick"):
        path = shutil.which(exe)
        if path:
            return path
    raise RuntimeError("ImageMagick 'convert' not found on PATH")


def ppm_to_png(ppm_path: str, png_path: Optional[str] = None) -> str:
    """Convert a PPM coverage image to a transparent PNG via ImageMagick.

    Uses the Lanczos filter to preserve smooth signal-strength gradients and
    avoid harsh color-banding artefacts in the final PNG overlay.
    """
    if png_path is None:
        png_path = os.path.splitext(ppm_path)[0] + ".png"
    convert = find_convert()
    # -filter Lanczos: high-quality sinc-based resampling keeps colour gradients
    # smooth without the blocky quantisation you get with the default filter.
    # -transparent white: make the Signal-Server background colour fully transparent.
    cmd = [convert, ppm_path, "-filter", "Lanczos", "-transparent", "white", png_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ImageMagick conversion failed: {result.stderr.decode(errors='replace')}"
        )
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


def _strongest_band_rgb(color_file: Optional[str]) -> Optional[tuple]:
    """Return the RGB of the strongest band (first entry) of a colour file."""
    if not color_file:
        return None
    path = color_file if os.path.exists(color_file) else None
    if not path:
        # Fall back to the bundled Radio Mobile palette.
        bundled = os.path.join(os.path.dirname(__file__), "resources", "radiomobile.dcf")
        path = bundled if os.path.exists(bundled) else None
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = re.match(r"\s*([+-]?\d+)\s*:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", line)
                if m:
                    return (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    except OSError:
        pass
    return None


def fill_center_hole(png_path: str, bbox: tuple[float, float, float, float],
                     tx_lat: float, tx_lon: float,
                     color_file: Optional[str] = None) -> None:
    """Fill the transparent hole the engine leaves around the Tx location.

    Signal-Server writes white/greyscale terrain (no palette colour) for cells
    right around the transmitter; PPM->PNG conversion turns white into alpha 0,
    leaving a see-through hole at the centre of the coverage. The hole is
    closed by flood-filling the *contiguous* transparent region touching the
    Tx pixel with the strongest-band colour of the active palette (capped to a
    fraction of the image so a pathological overlay can never be swallowed).
    """
    from PIL import Image

    if not os.path.exists(png_path):
        return

    try:
        img = Image.open(png_path).convert("RGBA")
        width, height = img.size
        if width == 0 or height == 0:
            return

        n, e, s, w = bbox
        lon_span = e - w
        lat_span = n - s
        if lon_span == 0 or lat_span == 0:
            return

        x_pct = (tx_lon - w) / lon_span
        y_pct = (n - tx_lat) / lat_span

        tx_x = int(x_pct * width)
        tx_y = int(y_pct * height)

        if not (0 <= tx_x < width and 0 <= tx_y < height):
            return

        pixels = img.load()
        if pixels[tx_x, tx_y][3] != 0:
            return  # Tx pixel already coloured — no hole here.

        fill_rgb = _strongest_band_rgb(color_file)
        if fill_rgb is None:
            # Fallback: copy the nearest opaque pixel's colour.
            fill_rgb = None
            for r in range(1, max(width, height)):
                found = False
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        nx, ny = tx_x + dx, tx_y + dy
                        if 0 <= nx < width and 0 <= ny < height \
                                and pixels[nx, ny][3] > 0:
                            pr, pg, pb, _ = pixels[nx, ny]
                            fill_rgb = (pr, pg, pb)
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            if fill_rgb is None:
                return

        # Flood-fill the transparent blob connected to the Tx pixel.
        max_fill = max(1, int(width * height * 0.05))  # safety cap: 5% of image
        filled = 0
        stack = [(tx_x, tx_y)]
        seen = {(tx_x, tx_y)}
        while stack and filled < max_fill:
            x, y = stack.pop()
            if not (0 <= x < width and 0 <= y < height):
                continue
            if pixels[x, y][3] != 0:
                continue
            pixels[x, y] = (*fill_rgb, 255)
            filled += 1
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))

        img.save(png_path)
    except Exception as exc:
        print(f"Error filling center hole: {exc}")


def stage_output(ppm_path: str, stdout_text: str, title: str = "Coverage",
                 tx_coords: Optional[tuple[float, float]] = None,
                 color_file: Optional[str] = None) -> dict:
    """Convert PPM and write sidecar PNG + KML. Returns paths/bbox."""
    png_path = ppm_to_png(ppm_path)
    bbox = parse_bbox(stdout_text)
    if bbox is not None and tx_coords is not None:
        fill_center_hole(png_path, bbox, tx_coords[0], tx_coords[1],
                         color_file=color_file)
    kml_path = os.path.splitext(ppm_path)[0] + ".kml"
    if bbox is not None:
        png_name = os.path.basename(png_path)
        with open(kml_path, "w", encoding="utf-8") as fh:
            fh.write(build_kml(png_name, bbox, title))
    return {"ppm": ppm_path, "png": png_path, "kml": kml_path, "bbox": bbox}
