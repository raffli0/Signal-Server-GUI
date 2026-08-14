"""DEM acquisition and conversion for the GUI.

Downloads Viewfinder Panoramas SRTM tiles (native HGT inside regional zips),
extracts them, and converts every ``.hgt`` to SPLAT ``.sdf`` via ``srtm2sdf``
(or ``srtm2sdf-hd`` for the HD engine). Results are cached locally so a
region is only processed once.

Tile resolution (verified working endpoints):
  3" (90m)  -> https://viewfinderpanoramas.org/dem3/<CODE>.zip
  1" (30m)  -> https://viewfinderpanoramas.org/dem1/<CODE>.zip
  15" (TIF) -> https://www.viewfinderpanoramas.org/DEM/TIF15/<CODE>.zip
"""

from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import urllib.request
import urllib.error
import zipfile
from typing import Optional


VIEWFINDER_BASE = {
    3: "https://viewfinderpanoramas.org/dem3",
    1: "https://viewfinderpanoramas.org/dem1",
    15: "https://www.viewfinderpanoramas.org/DEM/TIF15",
}

DEMSEARCH_URL = "https://www.imagico.de/map/demsearch.php"

# Raised when the regional tile code cannot be resolved automatically.
class DemResolveError(RuntimeError):
    pass


def _cache_sub(cache_dir: str, name: str) -> str:
    path = os.path.join(cache_dir, name)
    os.makedirs(path, exist_ok=True)
    return path


def resolve_regional_tile_bbox(
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float, resolution: int = 3
) -> str:
    """Resolve a bounding box to a Viewfinder regional tile code.

    Uses imagico.de's ``dem_json.php`` backend (the same one the interactive
    search map calls). It returns the Viewfinder multi-tile (``type == 2``)
    whose region covers the area. Raises ``DemResolveError`` if nothing
    matches, so the caller can fall back to a manual tile code.
    """
    if resolution not in VIEWFINDER_BASE:
        raise DemResolveError(f"Unsupported DEM resolution: {resolution}")
    q = (
        f"lon={lon_lo}&lat={lat_lo}&lonE={lon_hi}&latE={lat_hi}"
        f"&vf=1&srtm=1"
    )
    url = f"{DEMSEARCH_URL.replace('demsearch.php', 'dem_json.php')}?{q}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DemResolveError(f"DEM search request failed: {exc}")

    frag = f"/dem{resolution}/"
    center_lat = (lat_lo + lat_hi) / 2.0
    center_lon = (lon_lo + lon_hi) / 2.0
    candidates = []
    for item in data:
        link = item.get("link", "")
        if str(item.get("type")) == "2" and frag in link:
            candidates.append(item)
    if not candidates:  # fallback: any Viewfinder multi-tile
        for item in data:
            if str(item.get("type")) == "2" and "viewfinderpanoramas.org" in item.get("link", ""):
                candidates.append(item)
    if not candidates:
        raise DemResolveError("No Viewfinder DEM tile covers this location")

    best = None
    for item in candidates:
        try:
            ls, le = float(item["lon_start"]), float(item["lon_end"])
            bs, be = float(item["lat_start"]), float(item["lat_end"])
        except (KeyError, ValueError, TypeError):
            continue
        if ls <= center_lon <= le and bs <= center_lat <= be:
            best = item
            break
    if best is None:
        best = candidates[0]
    name = best.get("name", "")
    return name[:-4] if name.endswith(".zip") else name


def resolve_regional_tile(lat: float, lon: float, resolution: int = 3) -> str:
    """Convenience wrapper: resolve a single point."""
    return resolve_regional_tile_bbox(lat, lat, lon, lon, resolution)


def download_tile_zip(tile_code: str, resolution: int, dest_dir: str) -> str:
    """Download a regional DEM zip into ``dest_dir``; returns the zip path.

    ``tile_code`` may be a bare code (e.g. ``B48``) or a full Viewfinder URL
    (e.g. ``https://viewfinderpanoramas.org/dem3/B48.zip``).
    """
    if resolution not in VIEWFINDER_BASE:
        raise DemResolveError(f"Unsupported DEM resolution: {resolution}")
    if tile_code.startswith("http://") or tile_code.startswith("https://"):
        url = tile_code
        code = tile_code.rstrip("/").split("/")[-1].replace(".zip", "")
    else:
        url = f"{VIEWFINDER_BASE[resolution]}/{tile_code}.zip"
        code = tile_code
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, f"{code}.zip")
    if os.path.exists(zip_path) and os.path.getsize(zip_path) > 0:
        return zip_path
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise DemResolveError(f"Failed to download {url}: {exc}")
    with open(zip_path, "wb") as fh:
        fh.write(data)
    return zip_path


def extract_hgt(zip_path: str, extract_dir: str) -> list[str]:
    """Extract a Viewfinder zip; returns the list of ``.hgt`` file paths.

    A Viewfinder zip expands to a folder (e.g. ``B48``) containing many
    standard SRTM ``.hgt`` files (e.g. ``S05E102.hgt``).
    """
    os.makedirs(extract_dir, exist_ok=True)
    hgt_files: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(".hgt"):
                hgt_files.append(os.path.join(root, f))
    return sorted(hgt_files)


def convert_hgt_to_sdf(srtm2sdf_exe: str, hgt_path: str, sdf_dir: str) -> Optional[str]:
    """Convert one ``.hgt`` to ``.sdf`` in ``sdf_dir`` (skips if present).

    ``srtm2sdf`` names the output by its north/west bounds (e.g.
    ``5_6_102_103.sdf``), not the ``.hgt`` basename, so we detect the file
    that actually appears in ``sdf_dir``.
    """
    os.makedirs(sdf_dir, exist_ok=True)
    before = set(os.listdir(sdf_dir))
    subprocess.run([srtm2sdf_exe, hgt_path], cwd=sdf_dir,
                   check=True, capture_output=True)
    after = set(os.listdir(sdf_dir))
    new_sdf = sorted(f for f in (after - before) if f.endswith(".sdf"))
    if new_sdf:
        return os.path.join(sdf_dir, new_sdf[0])
    # Already converted (cache hit): nothing new appeared.
    return None


def prepare_region(
    tile_code: str,
    resolution: int,
    cache_dir: str,
    srtm2sdf_exe: str,
) -> str:
    """Download + extract + convert a regional tile; returns the SDF cache dir."""
    zip_dir = _cache_sub(cache_dir, "zip")
    raw_dir = _cache_sub(cache_dir, os.path.join("raw", tile_code))
    sdf_dir = _cache_sub(cache_dir, "sdf")

    zip_path = download_tile_zip(tile_code, resolution, zip_dir)
    hgt_files = extract_hgt(zip_path, raw_dir)
    if not hgt_files:
        raise DemResolveError(f"No .hgt files found in tile {tile_code}")
    for hgt in hgt_files:
        convert_hgt_to_sdf(srtm2sdf_exe, hgt, sdf_dir)
    return sdf_dir


def ensure_dem_for_area(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    resolution: int,
    cache_dir: str,
    srtm2sdf_exe: str,
    engine: str = "Standard",
) -> str:
    """Ensure DEM ``.sdf`` files exist for a bounding box; returns the SDF dir.

    Resolves the regional tile automatically (or raises ``DemResolveError`` so
    the GUI can ask the user to paste the tile code).
    """
    code = resolve_regional_tile_bbox(lat_lo, lat_hi, lon_lo, lon_hi, resolution)
    return prepare_region(code, resolution, cache_dir, srtm2sdf_exe)


def which_srtm2sdf(variant: str = "Standard") -> Optional[str]:
    """Locate the built srtm2sdf / srtm2sdf-hd binary."""
    name = "srtm2sdf-hd" if variant == "HD" else "srtm2sdf"
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    # repo/gui/src/signal_gui/params.py -> walk up to Signal-Server
    candidates = [
        os.path.join(repo, "Signal-Server", "utils", "sdf", "usgs2sdf", "build", name),
        os.path.join(repo, "Signal-Server", "utils", "sdf", "usgs2sdf", name),
        shutil.which(name),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None
