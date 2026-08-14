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
    """Convert a PPM coverage image to a transparent PNG via ImageMagick."""
    if png_path is None:
        png_path = os.path.splitext(ppm_path)[0] + ".png"
    convert = find_convert()
    cmd = [convert, ppm_path, "-transparent", "white", png_path]
    subprocess.run(cmd, check=True, capture_output=True)
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


def fill_center_hole(png_path: str, bbox: tuple[float, float, float, float], tx_lat: float, tx_lon: float) -> None:
    """Fills the transparent center hole of the coverage PNG at the Tx location."""
    from PIL import Image
    
    if not os.path.exists(png_path):
        return
        
    try:
        img = Image.open(png_path).convert("RGBA")
        width, height = img.size
        
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
            
        # Search for a nearby colored pixel to copy its color
        replacement_color = None
        for r in range(1, 15):
            found_color = False
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    nx, ny = tx_x + dx, tx_y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        r_val, g_val, b_val, a_val = img.getpixel((nx, ny))
                        if a_val > 0:
                            replacement_color = (r_val, g_val, b_val, a_val)
                            found_color = True
                            break
                if found_color:
                    break
            if found_color:
                break
                
        if replacement_color is None:
            return
            
        # Fill all transparent pixels in a small radius around the Tx
        pixels = img.load()
        fill_radius = 6
        for dx in range(-fill_radius, fill_radius + 1):
            for dy in range(-fill_radius, fill_radius + 1):
                if dx*dx + dy*dy <= fill_radius*fill_radius:
                    nx, ny = tx_x + dx, tx_y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        _, _, _, a_val = pixels[nx, ny]
                        if a_val == 0:
                            pixels[nx, ny] = replacement_color
                            
        img.save(png_path)
    except Exception as exc:
        print(f"Error filling center hole: {exc}")


def stage_output(ppm_path: str, stdout_text: str, title: str = "Coverage", tx_coords: Optional[tuple[float, float]] = None) -> dict:
    """Convert PPM and write sidecar PNG + KML. Returns paths/bbox."""
    png_path = ppm_to_png(ppm_path)
    bbox = parse_bbox(stdout_text)
    if bbox is not None and tx_coords is not None:
        fill_center_hole(png_path, bbox, tx_coords[0], tx_coords[1])
    kml_path = os.path.splitext(ppm_path)[0] + ".kml"
    if bbox is not None:
        png_name = os.path.basename(png_path)
        with open(kml_path, "w", encoding="utf-8") as fh:
            fh.write(build_kml(png_name, bbox, title))
    return {"ppm": ppm_path, "png": png_path, "kml": kml_path, "bbox": bbox}
