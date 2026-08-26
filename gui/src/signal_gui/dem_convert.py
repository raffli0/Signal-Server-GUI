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

import math
import os
import re
import json
import hashlib
import shutil
import subprocess
import urllib.request
import urllib.error
import zipfile
from typing import Optional

import numpy as np


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


def _query_demsearch(
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float, resolution: int
) -> list:
    """Query imagico.de's dem_json backend; return the raw item list."""
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
    if not isinstance(data, list):
        raise DemResolveError("DEM search returned an unexpected response")
    return data


def _ranked_tiles_for_bbox(
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float, resolution: int
) -> list[str]:
    """Return Viewfinder regional tile codes whose region covers the bbox
    *centre*, ordered most-specific (smallest area) first.

    Picking the most specific tile avoids grabbing a huge continent tile that,
    once downloaded, does not actually contain the 1-degree SRTM cell covering
    the transmitter -- which previously produced degenerate (line-shaped)
    coverage. ``DemResolveError`` is raised when nothing matches.
    """
    data = _query_demsearch(lat_lo, lat_hi, lon_lo, lon_hi, resolution)
    frag = f"/dem{resolution}/"
    center_lat = (lat_lo + lat_hi) / 2.0
    center_lon = (lon_lo + lon_hi) / 2.0

    def _area(it):
        try:
            return (float(it["lon_end"]) - float(it["lon_start"])) * (
                float(it["lat_end"]) - float(it["lat_start"])
            )
        except (KeyError, ValueError, TypeError):
            return float("inf")

    candidates = []
    for item in data:
        link = item.get("link", "")
        if str(item.get("type")) != "2" or frag not in link:
            continue
        try:
            ls, le = float(item["lon_start"]), float(item["lon_end"])
            bs, be = float(item["lat_start"]), float(item["lat_end"])
        except (KeyError, ValueError, TypeError):
            continue
        if ls <= center_lon <= le and bs <= center_lat <= be:
            candidates.append(item)
    if not candidates:  # fallback: any Viewfinder multi-tile
        for item in data:
            if str(item.get("type")) == "2" and "viewfinderpanoramas.org" in item.get("link", ""):
                candidates.append(item)
    if not candidates:
        raise DemResolveError("No Viewfinder DEM tile covers this location")
    candidates.sort(key=_area)
    out = []
    for item in candidates:
        name = item.get("name", "")
        code = name[:-4] if name.endswith(".zip") else name
        if code and code not in out:
            out.append(code)
    return out


def resolve_regional_tile_bbox(
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float, resolution: int = 3
) -> str:
    """Resolve a bounding box to the best Viewfinder regional tile code.

    Uses imagico.de's ``dem_json.php`` backend (the same one the interactive
    search map calls). Returns the most specific multi-tile (``type == 2``)
    whose region covers the bbox centre. Raises ``DemResolveError`` if nothing
    matches, so the caller can fall back to a manual tile code.
    """
    return _ranked_tiles_for_bbox(lat_lo, lat_hi, lon_lo, lon_hi, resolution)[0]


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


def _normalize_sdf_names(sdf_dir: str) -> None:
    """Rename any ``a:b:c:d.sdf`` produced by some ``srtm2sdf`` builds to the
    ``a_b_c_d.sdf`` form the engine actually looks up.

    The engine computes the region name with underscores (e.g.
    ``-7_-6_252_253``); a few ``srtm2sdf`` binaries emit colons instead, which
    the engine then fails to find (falling back to sea-level terrain). This
    keeps the two consistent. Idempotent.
    """
    for f in os.listdir(sdf_dir):
        if ":" in f and f.endswith(".sdf"):
            os.rename(os.path.join(sdf_dir, f),
                      os.path.join(sdf_dir, f.replace(":", "_")))


# --------------------------------------------------------------------------
# Cache-integrity guards. A run killed mid-conversion used to leave truncated
# .hgt/.sdf artifacts that were happily reused forever -- the classic cause of
# "hasil kadang bagus kadang hancur / radial terpotong seperti pizza".
# --------------------------------------------------------------------------

def hgt_valid(path: str, tile_size: int = 1201) -> bool:
    """True when ``path`` is a complete big-endian int16 SRTM height grid."""
    try:
        expected = 2 * tile_size * tile_size
        return os.path.getsize(path) == expected
    except OSError:
        return False


def sdf_valid(path: str) -> bool:
    """True when an ``.sdf`` looks structurally complete.

    SPLAT text SDF layout: four float header lines, then a rectangular block
    of integer elevations (>= 2 rows x >= 2 columns). We require the data
    block to be rectangular and non-degenerate; a file killed mid-write is
    virtually always short or ragged, which this catches without knowing the
    nominal grid size.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = [fh.readline() for _ in range(4)]
            if any(not ln.strip() for ln in head):
                return False
            for ln in head:
                try:
                    float(ln.split()[0])
                except (ValueError, IndexError):
                    return False
            first = fh.readline()
            if not first.strip():
                return False
            cols = len(first.split())
            if cols < 2:
                return False
            rows = 1
            for ln in fh:
                if not ln.strip():
                    continue
                if len(ln.split()) != cols:
                    return False
                rows += 1
                if rows > 10_000_000:      # runaway guard
                    return False
            return rows >= 2
    except OSError:
        return False


def hgt_void_pct(path: str, low: int = -1000, high: int = 32000) -> float:
    """Percentage of sentinel/void cells in a ``.hgt`` (big-endian int16)."""
    import numpy as np
    a = np.fromfile(path, dtype=">i2")
    if a.size == 0:
        return 100.0
    return float(((a <= low) | (a >= high)).mean() * 100.0)


def evaluate_void(pct: float) -> tuple[str, str]:
    """Classify a void percentage against the shared ASC thresholds.

    Returns ``(level, message)`` with level ``"ok" | "warn" | "reject"``.
    """
    if pct > MAX_ASC_NODATA_PCT:
        return "reject", (
            f"{pct:.1f}% terrain VOID/NODATA pada tile hasil konversi "
            f"(batas {MAX_ASC_NODATA_PCT:.0f}%). Radial yang menembus zona "
            f"void akan terpotong (pola 'pizza'). Tambahkan tile DEMNAS atau "
            f"perkecil radius.")
    if pct > WARN_ASC_NODATA_PCT:
        return "warn", (
            f"{pct:.1f}% terrain VOID/NODATA pada tile ({WARN_ASC_NODATA_PCT:.0f}%"
            f"-{MAX_ASC_NODATA_PCT:.0f}%). Coverage di zona itu mungkin tidak "
            f"akurat.")
    return "ok", ""


def convert_hgt_to_sdf(srtm2sdf_exe: str, hgt_path: str, sdf_dir: str) -> Optional[str]:
    """Convert one ``.hgt`` into ``sdf_dir``, replacing any previous output.

    ``srtm2sdf`` names the output by its north/west bounds (e.g.
    ``5_6_102_103.sdf``), not the ``.hgt`` basename. Conversion runs inside a
    throw-away directory so a half-written result can never land in the cache:
    the produced file is validated and then moved into place atomically. This
    also heals caches poisoned by earlier interrupted runs (the tool skips
    conversion when its output already exists).
    """
    import tempfile

    os.makedirs(sdf_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".srtm2sdf_", dir=sdf_dir) as td:
        proc = subprocess.run([srtm2sdf_exe, os.path.abspath(hgt_path)],
                              cwd=td, capture_output=True)
        _normalize_sdf_names(td)
        produced = [f for f in os.listdir(td) if f.endswith(".sdf")]
        if not produced:
            raise DemResolveError(
                f"srtm2sdf tidak menghasilkan .sdf untuk {os.path.basename(hgt_path)}"
                f" (exit {proc.returncode})."
            )
        src = os.path.join(td, produced[0])
        if not sdf_valid(src):
            raise DemResolveError(
                f".sdf hasil konversi tidak valid/terpotong untuk "
                f"{os.path.basename(hgt_path)}."
            )
        dst = os.path.join(sdf_dir, produced[0])
        os.replace(src, dst)
    return dst


def prepare_region(
    tile_code: str,
    resolution: int,
    cache_dir: str,
    srtm2sdf_exe: str,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
) -> str:
    """Download + extract + convert a regional tile; returns the SDF cache dir.

    The converted ``.sdf`` tiles live in ``cache/dem/sdf/<tile_code>/`` so a
    wrongly-resolved tile cannot pollute the terrain used for another location.
    """
    zip_dir = _cache_sub(cache_dir, "zip")
    raw_dir = _cache_sub(cache_dir, os.path.join("raw", tile_code))
    sdf_dir = _cache_sub(cache_dir, os.path.join("sdf", tile_code))

    zip_path = download_tile_zip(tile_code, resolution, zip_dir)
    hgt_files = extract_hgt(zip_path, raw_dir)
    if not hgt_files:
        raise DemResolveError(f"No .hgt files found in tile {tile_code}")
    for hgt in hgt_files:
        convert_hgt_to_sdf(srtm2sdf_exe, hgt, sdf_dir)
    if center_lat is not None and center_lon is not None:
        if not hgt_covers_center(raw_dir, center_lat, center_lon):
            raise DemResolveError(
                f"Tile {tile_code} does not cover the transmitter location "
                f"({center_lat:.4f}, {center_lon:.4f})"
            )
    return sdf_dir


_HGT_NAME_RE = re.compile(r"^([NS])(\d{2})([EW])(\d{3})\.hgt$", re.IGNORECASE)


def _hgt_bounds(name: str) -> Optional[tuple[float, float, float, float]]:
    """Return (lat_lo, lat_hi, lon_lo, lon_hi) for a standard SRTM ``.hgt`` name.

    e.g. ``S06E107.hgt`` -> (-7, -6, 107, 108). The tile number is the
    south/west edge; the cell spans 1 degree north/east of it.
    """
    m = _HGT_NAME_RE.match(name)
    if not m:
        return None
    ns, lat_s, ew, lon_s = m.groups()
    lat = int(lat_s)
    lon = int(lon_s)
    if ns.upper() == "S":
        lat_lo, lat_hi = -lat - 1, -lat
    else:
        lat_lo, lat_hi = lat, lat + 1
    if ew.upper() == "W":
        lon_lo, lon_hi = -lon - 1, -lon
    else:
        lon_lo, lon_hi = lon, lon + 1
    return lat_lo, lat_hi, lon_lo, lon_hi


def hgt_covers_center(raw_dir: str, lat: float, lon: float) -> bool:
    """True if any ``.hgt`` under ``raw_dir`` (standard SRTM naming) covers (lat, lon)."""
    if not os.path.isdir(raw_dir):
        return False
    for root, _dirs, files in os.walk(raw_dir):
        for f in files:
            if not f.lower().endswith(".hgt"):
                continue
            b = _hgt_bounds(f)
            if not b:
                continue
            s, n, w, e = b
            if w <= lon <= e and s <= lat <= n:
                return True
    return False


def ensure_dem_for_area(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    resolution: int,
    cache_dir: str,
    srtm2sdf_exe: str,
    engine: str = "Standard",
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
) -> str:
    """Ensure DEM ``.sdf`` files exist for a bounding box; returns the SDF dir.

    Resolves the regional tile automatically (or raises ``DemResolveError`` so
    the GUI can ask the user to paste the tile code). When a centre coordinate
    is supplied we verify the prepared terrain actually covers it -- a resolver
    can return a tile that, once downloaded, omits the 1-degree cell holding
    the transmitter, which previously produced a degenerate (line-shaped)
    coverage. In that case we try the next best candidate before giving up.
    """
    ranked = _ranked_tiles_for_bbox(lat_lo, lat_hi, lon_lo, lon_hi, resolution)
    last_err: Optional[Exception] = None
    for code in ranked:
        try:
            sdf_dir = prepare_region(
                code, resolution, cache_dir, srtm2sdf_exe,
                center_lat=center_lat, center_lon=center_lon,
            )
        except DemResolveError as exc:
            last_err = exc
            continue
        return sdf_dir
    raise DemResolveError(
        str(last_err) if last_err else "No Viewfinder DEM tile covers this location"
    )


# ---------------------------------------------------------------------------
# Offline DEM source: local DEMNAS GeoTIFF
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    """Run a GDAL subprocess, raising DemResolveError with stderr on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DemResolveError(f"GDAL tool not found: {cmd[0]} ({exc})")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip().splitlines()[-5:]
        raise DemResolveError(
            f"GDAL step failed: {' '.join(cmd)}\n" + "\n".join(stderr)
        )


def _gdal_extent(tif_path: str) -> tuple[float, float, float, float]:
    """Return the (minx, miny, maxx, maxy) WGS84 extent of a raster."""
    out = subprocess.run(
        ["gdalinfo", "-json", tif_path], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise DemResolveError(f"gdalinfo failed for {tif_path}")
    info = json.loads(out.stdout)
    if "wgs84Extent" in info:
        coords = info["wgs84Extent"]["coordinates"][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        return min(xs), min(ys), max(xs), max(ys)
    cc = info.get("cornerCoordinates", {})
    ll = cc.get("lowerLeft")
    ur = cc.get("upperRight")
    if ll and ur:
        return ll[0], ll[1], ur[0], ur[1]
    raise DemResolveError(f"Cannot read extent of {tif_path}")


def _collect_demnas_tifs(folder: str) -> list[str]:
    """Return every DEMNAS ``.tif``/``.tiff`` tile under ``folder`` (recursive)."""
    found: list[str] = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            low = f.lower()
            if low.endswith(".tif") or low.endswith(".tiff"):
                found.append(os.path.join(root, f))
    return sorted(found)


def _demnas_folder_signature(folder: str) -> str:
    """Stable hash of a DEMNAS folder's ``.tif`` contents (recursive).

    Keyed by the folder's absolute location plus the sorted list of tiles and
    their size and mtime, so adding, removing, or replacing a tile — or moving
    the whole folder to a different path — invalidates the cached VRT/SDF
    (instead of the folder *path* alone, which never changes when a new tile is
    dropped into an existing folder).
    """
    parts: list[str] = [os.path.realpath(folder)]
    for root, _dirs, files in os.walk(folder):
        for f in files:
            low = f.lower()
            if low.endswith(".tif") or low.endswith(".tiff"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, folder)
                try:
                    st = os.stat(p)
                    parts.append(f"{rel}:{st.st_size}:{int(st.st_mtime)}")
                except OSError:
                    parts.append(rel)
    if len(parts) < 2:
        raise DemResolveError(
            f"Folder DEMNAS '{folder}' tidak berisi file .tif/.tiff."
        )
    parts.sort()
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:10]


def _demnas_vrt(folder: str, cache_dir: str) -> str:
    """Merge all DEMNAS ``.tif`` tiles in ``folder`` into one cached VRT.

    The VRT is keyed by the folder's location plus its contents (tile list +
    size + mtime) so adding, removing, or replacing a ``.tif`` — or moving the
    folder — invalidates the stale virtual mosaic. ``gdalwarp`` only reads the
    tiles covering the requested clip window, so the VRT itself stays cheap to
    rebuild.
    """
    key = _demnas_folder_signature(folder)
    vrt_dir = _cache_sub(cache_dir, "demnas_vrt")
    vrt = os.path.join(vrt_dir, f"{key}.vrt")
    if os.path.exists(vrt) and os.path.getsize(vrt) > 0:
        if _vrt_sources_exist(vrt):
            return vrt
        # Stale VRT: its source tiles were moved/deleted — rebuild below.
        try:
            os.remove(vrt)
        except OSError:
            pass
    tifs = _collect_demnas_tifs(folder)
    if not tifs:
        raise DemResolveError(
            f"Folder DEMNAS '{folder}' tidak berisi file .tif/.tiff."
        )
    lst = os.path.join(vrt_dir, f"{key}.txt")
    with open(lst, "w") as fh:
        fh.write("\n".join(tifs))
    # Force WGS84 so downstream sampling (gdallocationinfo -wgs84) and any
    # per-tile reprojection are unambiguous; DEMNAS tiles are always EPSG:4326.
    tmp_vrt = vrt + f".tmp{os.getpid()}"
    _run(["gdalbuildvrt", "-a_srs", "EPSG:4326",
          "-input_file_list", lst, tmp_vrt])
    os.replace(tmp_vrt, vrt)
    return vrt


def _vrt_sources_exist(vrt: str) -> bool:
    """True if every ``SourceFilename`` referenced by a cached VRT still exists."""
    try:
        with open(vrt, "r", encoding="utf-8") as fh:
            txt = fh.read()
    except OSError:
        return False
    for m in re.findall(r"<SourceFilename[^>]*>([^<]+)</SourceFilename>", txt):
        if not os.path.exists(m):
            return False
    return True


def _sample_elevation(vrt: str, lat: float, lon: float) -> Optional[float]:
    """Sample the DEMNAS elevation (m) at (lat, lon); None if void/nodata."""
    out = subprocess.run(
        ["gdallocationinfo", "-valonly", "-wgs84", vrt, str(lon), str(lat)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    txt = out.stdout.strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _assert_covers(vrt: str, lat: float, lon: float) -> None:
    """Raise if the DEMNAS mosaic does not span the point (lat, lon)."""
    minx, miny, maxx, maxy = _gdal_extent(vrt)
    eps = 1e-3
    if not (minx - eps <= lon <= maxx + eps
            and miny - eps <= lat <= maxy + eps):
        raise DemResolveError(
            f"DEMNAS tidak mencakup lokasi ({lat:.4f}, {lon:.4f}). "
            f"Pastikan folder DEMNAS mencakup area ini (mis. seluruh "
            f"Indonesia)."
        )


def _assert_covers_bbox(
    vrt: str,
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float,
) -> None:
    """Raise if the DEMNAS mosaic omits any corner or the centre of a run bbox.

    A mosaic that only spans the Tx point is not enough: Signal-Server computes
    the whole coverage circle over loaded terrain, so a partial DEM silently
    shifts/limits the computed area (the "coverage 150 km away" bug).
    """
    minx, miny, maxx, maxy = _gdal_extent(vrt)
    eps = 1e-3
    clat = (lat_lo + lat_hi) / 2.0
    clon = (lon_lo + lon_hi) / 2.0
    probes = [
        ("Sudut barat-daya", lat_lo, lon_lo),
        ("Sudut barat-laut", lat_hi, lon_lo),
        ("Sudut timur-daya", lat_lo, lon_hi),
        ("Sudut timur-laut", lat_hi, lon_hi),
        ("Pusat area", clat, clon),
    ]
    missing = [
        f"{label} ({la:.4f}, {lo:.4f})"
        for label, la, lo in probes
        if not (minx - eps <= lo <= maxx + eps
                and miny - eps <= la <= maxy + eps)
    ]
    if missing:
        raise DemResolveError(
            "DEMNAS tidak mencakup seluruh area yang diminta "
            f"({lat_lo:.4f}..{lat_hi:.4f}, {lon_lo:.4f}..{lon_hi:.4f}). "
            f"Tidak tercakup: {', '.join(missing)}. Tambahkan tile DEMNAS "
            f"untuk area tersebut ke folder."
        )


# ---------------------------------------------------------------------------
# SPLAT .sdf header parsing (terrain coverage verification)
# ---------------------------------------------------------------------------

def sdf_bounds(path: str) -> Optional[tuple[float, float, float, float]]:
    """Parse an SPLAT ``.sdf`` header into (lat_lo, lat_hi, lon_lo, lon_hi).

    The SDF text header holds four numbers, one per line: ``max_west``,
    ``min_north``, ``min_west``, ``max_north`` -- all in SPLAT's
    west-positive longitude convention (0..360). East-longitude range is
    therefore ``[360 - max_west, 360 - min_west]``.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            vals = [fh.readline().split() for _ in range(4)]
        floats = []
        for parts in vals:
            if not parts:
                return None
            floats.append(float(parts[0]))
        max_west, min_north, min_west, max_north = floats
    except (OSError, ValueError):
        return None

    def w2e(w: float) -> float:
        w %= 360.0
        e = 360.0 - w
        if e >= 180.0:
            e -= 360.0
        return e

    lon_lo = w2e(max_west)
    lon_hi = w2e(min_west)
    if lon_lo > lon_hi:  # antimeridian wrap
        lon_lo, lon_hi = lon_hi, lon_lo
    return min(min_north, max_north), max(min_north, max_north), lon_lo, lon_hi


def sdf_dir_boxes(sdf_dir: str, hd: bool = False):
    """Return [(lat_lo, lat_hi, lon_lo, lon_hi), ...] for every matching .sdf."""
    boxes = []
    try:
        names = os.listdir(sdf_dir)
    except OSError:
        return boxes
    for f in sorted(names):
        if not f.endswith(".sdf"):
            continue
        is_hd = f.endswith("-hd.sdf")
        if hd != is_hd:
            continue
        b = sdf_bounds(os.path.join(sdf_dir, f))
        if b:
            boxes.append(b)
    return boxes


def sdf_point_covered(boxes, lat: float, lon: float, tol: float = 1e-6) -> bool:
    """True if (lat, lon) falls inside any of ``sdf_bounds``-style boxes."""
    for s, n, w, e in boxes:
        # Compare longitudes modulo 360 so antimeridian tiles behave.
        dlon = (lon - w) % 360.0
        span = (e - w) % 360.0 or 360.0
        if s - tol <= lat <= n + tol and dlon <= span + tol:
            return True
    return False


def sdf_missing_corners(boxes, lat_lo, lat_hi, lon_lo, lon_hi):
    """Return labels of bbox probe points not covered by any SDF box."""
    probes = [
        ("SW", lat_lo, lon_lo), ("NW", lat_hi, lon_lo),
        ("SE", lat_lo, lon_hi), ("NE", lat_hi, lon_hi),
        ("C", (lat_lo + lat_hi) / 2.0, (lon_lo + lon_hi) / 2.0),
    ]
    missing = [name for name, la, lo in probes if not sdf_point_covered(boxes, la, lo)]
    return missing


# ---------------------------------------------------------------------------
# Ground elevation lookup (AMSL) for Radio-Mobile-compatible reporting
# ---------------------------------------------------------------------------

_DEFAULT_ELEV_CACHE_DIR = os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "siggui_elev_cache"
)


def _openmeteo_elevation(lat: float, lon: float, timeout: float = 5.0) -> Optional[float]:
    """Sample ground elevation via the Open-Meteo elevation API; None on failure.

    Used when no local DEMNAS folder is available (online mode / best effort).
    Never raises.
    """
    url = (
        "https://api.open-meteo.com/v1/elevation"
        f"?latitude={lat:.6f}&longitude={lon:.6f}"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elev = (data or {}).get("elevation") or []
        if elev:
            return float(elev[0])
    except (OSError, ValueError, KeyError):
        pass
    return None


def ground_elevation(
    lat: float,
    lon: float,
    demnas_folder: Optional[str] = None,
    cache_dir: Optional[str] = None,
    timeout: float = 5.0,
) -> Optional[float]:
    """Ground elevation (m AMSL) at (lat, lon): local DEMNAS first, then web.

    Returns None when both sources fail (callers must degrade gracefully).
    """
    if demnas_folder and os.path.isdir(demnas_folder):
        try:
            if _collect_demnas_tifs(demnas_folder):
                vrt = _demnas_vrt(demnas_folder, cache_dir or _DEFAULT_ELEV_CACHE_DIR)
                val = _sample_elevation(vrt, lat, lon)
                if val is not None:
                    return val
        except Exception:  # noqa: BLE001 - elevation lookup must never break a run
            pass
    return _openmeteo_elevation(lat, lon, timeout=timeout)


def demnas_folder_to_sdf(
    folder: str,
    cache_dir: str,
    srtm2sdf_exe: Optional[str],
    engine: str,
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    warn_cb=None,
) -> str:
    """Convert a local DEMNAS folder (``.tif`` tiles) to SPLAT ``.sdf``.

    All tiles are merged into a VRT, reprojected to EPSG:4326, clipped to an
    integer-degree aligned bounding box covering the run area, split into
    1-degree SRTM ``.hgt`` tiles, and each is run through ``srtm2sdf``. Results
    accumulate in ``cache/dem/sdf/demnas`` (or ``demnas_hd``) keyed by the
    folder, so a region is processed only once. Coverage of the transmitter
    is verified against the mosaic before conversion.

    Reused artifacts are integrity-checked first and regenerated when they are
    truncated; every write lands atomically so an interrupted run can no
    longer poison later runs. ``warn_cb(message)`` receives NODATA warnings.
    """
    if not srtm2sdf_exe or not os.path.exists(srtm2sdf_exe):
        raise DemResolveError(
            f"srtm2sdf binary not found ({srtm2sdf_exe}); cannot build "
            f"offline SDF terrain."
        )
    vrt = _demnas_vrt(folder, cache_dir)
    if center_lat is not None and center_lon is not None:
        _assert_covers(vrt, center_lat, center_lon)
    hd = engine == "HD"
    tile_size = 3601 if hd else 1201
    res_deg = 1.0 / (tile_size - 1)
    # Namespace the cache by the folder's *contents* (not its path) so dropping
    # a new .tif into an existing folder rebuilds the .sdf tiles instead of
    # reusing a stale mosaic.
    key = _demnas_folder_signature(folder)
    base = f"demnas_hd_{key}" if hd else f"demnas_{key}"
    raw_dir = _cache_sub(cache_dir, os.path.join("raw", base))
    sdf_dir = _cache_sub(cache_dir, os.path.join("sdf", base))

    # Expand to integer-degree aligned bounds so every produced .hgt is a full
    # 1-degree tile (the SRTMHGT driver requires exact dimensions).
    ilat_lo = math.floor(lat_lo)
    ilat_hi = math.ceil(lat_hi)
    ilon_lo = math.floor(lon_lo)
    ilon_hi = math.ceil(lon_hi)

    clipped = os.path.join(raw_dir, "clip.tif")
    tmp_clip = clipped + f".tmp{os.getpid()}"
    _run([
        "gdalwarp", "-t_srs", "EPSG:4326",
        "-te", str(ilon_lo), str(ilat_lo), str(ilon_hi), str(ilat_hi),
        "-tr", str(res_deg), str(res_deg), "-r", "bilinear", "-overwrite",
        vrt, tmp_clip,
    ])
    os.replace(tmp_clip, clipped)

    # Split into 1-degree SRTM .hgt tiles, one per cell, named by the
    # south-west corner (standard SRTM convention, e.g. S07E107.hgt).
    hgt_files: list[str] = []
    for ilat in range(ilat_lo, ilat_hi):
        for ilon in range(ilon_lo, ilon_hi):
            ns = "S" if ilat < 0 else "N"
            ew = "W" if ilon < 0 else "E"
            name = f"{ns}{abs(ilat):02d}{ew}{abs(ilon):03d}.hgt"
            out_hgt = os.path.join(raw_dir, name)
            if os.path.exists(out_hgt) and hgt_valid(out_hgt, tile_size):
                hgt_files.append(out_hgt)
                continue
            # (Re)build inside a temp dir with the exact SRTM name the driver
            # requires, then move into place so a kill mid-translate cannot
            # cache a truncated tile.
            import tempfile
            os.makedirs(raw_dir, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".hgt_",
                                             dir=raw_dir) as td:
                tmp_hgt = os.path.join(td, name)
                _run([
                    "gdal_translate", "-of", "SRTMHGT",
                    "-outsize", str(tile_size), str(tile_size),
                    "-projwin", str(ilon), str(ilat + 1), str(ilon + 1),
                    str(ilat), clipped, tmp_hgt,
                ])
                if not os.path.exists(tmp_hgt):
                    continue
                if not hgt_valid(tmp_hgt, tile_size):
                    raise DemResolveError(
                        f"Tile .hgt {name} terpotong/invalid setelah "
                        f"konversi (ukuran tak sesuai grid {tile_size}).")
                os.replace(tmp_hgt, out_hgt)
            if os.path.exists(out_hgt):
                hgt_files.append(out_hgt)
    if not hgt_files:
        raise DemResolveError(
            "Gagal mengonversi DEMNAS menjadi .hgt (periksa CRS/proyeksi "
            "file)."
        )
    worst_void = 0.0
    worst_tile = ""
    for hgt in sorted(hgt_files):
        pct = hgt_void_pct(hgt)
        if pct > worst_void:
            worst_void, worst_tile = pct, os.path.basename(hgt)
        convert_hgt_to_sdf(srtm2sdf_exe, hgt, sdf_dir)
    level, msg = evaluate_void(worst_void)
    if level == "reject":
        raise DemResolveError(f"{msg} (tile terparah: {worst_tile})")
    if level == "warn" and warn_cb:
        warn_cb(f"{msg} (tile terparah: {worst_tile})")
    return sdf_dir


def _asc_cellsize(
    span: float,
    native: float,
    target: Optional[float],
    max_cells: int,
    ppd: int = 1200,
) -> float:
    """Pick the LIDAR ``.asc`` cell size (degrees) for a run bounding box.

    Starts from the requested ``target`` (from the DEM resolution setting),
    falling back to the legacy ``span/ppd`` behaviour when unspecified, then
    clamps so that:

    * the grid is never finer than the source data (``native``), and
    * the total cell count stays under ``max_cells`` (bounds file size and
      engine load time — the .asc is plain text).
    """
    if target and target > 0:
        cellsize = float(target)
    else:
        cellsize = span / float(max(1, ppd)) if ppd else (1.0 / 1200.0)
    if native and native > 0:
        cellsize = max(cellsize, native)
    if span > 0 and max_cells > 0:
        cellsize = max(cellsize, span / math.sqrt(max_cells))
    return cellsize


# Terrain sanity limits for the generated LIDAR grid. A grid that is mostly
# NODATA or has (almost) no relief makes Signal-Server compute over fake
# flat/painted terrain — the classic "coverage bulet halus" result.
# Above MAX_ASC_NODATA_PCT the run is rejected (terrain is more fake than real,
# e.g. a 150 km radius at a DEMNAS folder that stops ~1 deg short). Between
# WARN_ASC_NODATA_PCT and MAX it runs with a warning (partial-edge terrain).
MAX_ASC_NODATA_PCT = 20.0
WARN_ASC_NODATA_PCT = 5.0
MIN_ASC_RELIEF_M = 20.0


def _asc_stats(int_arr: "np.ndarray", nodata_value: int, cellsize: float
               ) -> dict:
    """Summary statistics of the generated LIDAR grid (before writing)."""
    nod = int_arr == nodata_value
    valid = int_arr[~nod]
    if valid.size:
        p5, p95 = np.percentile(valid, 5), np.percentile(valid, 95)
        vmin, vmax = int(valid.min()), int(valid.max())
        relief = float(p95 - p5)
    else:
        vmin = vmax = None
        relief = 0.0
    return {
        "cellsize_deg": round(float(cellsize), 9),
        "cellsize_m": round(float(cellsize) * 111320.0, 1),
        "nrows": int(int_arr.shape[0]),
        "ncols": int(int_arr.shape[1]),
        "nodata_pct": round(100.0 * float(nod.mean()), 2),
        "min_m": vmin,
        "max_m": vmax,
        "relief_p5p95_m": round(relief, 1),
        "ppd": round(1.0 / cellsize) if cellsize > 0 else 0,
    }


def demnas_folder_to_asc(
    folder: str,
    cache_dir: str,
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float,
    ppd: int = 1200,
    target_cellsize: Optional[float] = None,
    max_cells: int = 6_000_000,
) -> tuple[str, dict]:
    """Convert a local DEMNAS folder (``.tif`` tiles) to a LIDAR ``.asc``.

    The tiles are merged into a VRT, reprojected to EPSG:4326 and clipped to
    the run bounding box, then resampled to the requested ``target_cellsize``
    (degrees; from the DEM resolution setting). When unspecified, the legacy
    ``span/ppd`` heuristic applies. The cell size is clamped to the source
    resolution and by ``max_cells`` so the file stays loadable. The ASCII grid
    is written manually (not via ``gdal_translate -of AAIGrid``) because
    Signal-Server's LIDAR loader parses the header with a strict ``fscanf``
    that expects an *integer* ``NODATA_value``; GDAL emits it as a float.

    Returns ``(asc_path, stats)``. Raises :class:`DemResolveError` when the
    produced grid is unusable terrain: mostly NODATA (DEMNAS folder does not
    cover the requested bbox) or practically flat (relief below
    ``MIN_ASC_RELIEF_M``) — both make the engine compute a fake, perfectly
    round coverage.
    """
    from osgeo import gdal  # local import; only needed here
    import numpy as np

    vrt = _demnas_vrt(folder, cache_dir)

    span = max(lon_hi - lon_lo, lat_hi - lat_lo)
    ds_vrt = gdal.Open(vrt)
    native = abs(ds_vrt.GetGeoTransform()[1]) if ds_vrt is not None else None
    ds_vrt = None
    cellsize_deg = _asc_cellsize(span, native or 0.0, target_cellsize,
                                 max_cells, ppd)

    out_dir = _cache_sub(cache_dir, "lidar")
    clipped = os.path.join(out_dir, "clip.tif")
    _run([
        "gdalwarp", "-t_srs", "EPSG:4326",
        "-te", str(lon_lo), str(lat_lo), str(lon_hi), str(lat_hi),
        "-tr", str(cellsize_deg), str(cellsize_deg), "-r", "bilinear", "-overwrite",
        vrt, clipped,
    ])

    ds = gdal.Open(clipped)
    if ds is None:
        raise DemResolveError(f"Tidak dapat membuka hasil clip: {clipped}")
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    arr = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    ds = None

    height, width = arr.shape
    xll = gt[0]
    yll = gt[3] + height * gt[5]  # gt[5] is negative (north-up)
    cellsize = gt[1]
    NODATA = -9999

    # Vectorised: non-finite / nodata -> NODATA, else rounded integer metres.
    valid = np.isfinite(arr)
    if nodata is not None:
        valid = valid & (arr != nodata)
    int_arr = np.full(arr.shape, NODATA, dtype=np.int32)
    int_arr[valid] = np.round(arr[valid]).astype(np.int32)

    stats = _asc_stats(int_arr, NODATA, cellsize)

    if stats["nodata_pct"] > MAX_ASC_NODATA_PCT:
        raise DemResolveError(
            f"Terrain LIDAR tidak valid: {stats['nodata_pct']}% piksel "
            f"NODATA (maksimum {MAX_ASC_NODATA_PCT}%). Folder DEMNAS tidak "
            f"mencakup seluruh area run — coverage akan dihitung di atas "
            f"terrain palsu. Perkecil radius atau tambahkan tile DEMNAS."
        )
    if stats["relief_p5p95_m"] < MIN_ASC_RELIEF_M:
        raise DemResolveError(
            f"Terrain LIDAR hampir datar (relief {stats['relief_p5p95_m']} m "
            f"< {MIN_ASC_RELIEF_M} m, elevasi {stats['min_m']}..{stats['max_m']} "
            f"m). Coverage di area ini tidak akan menunjukkan kontur/ "
            f"bayangan gunung. Periksa sumber DEMNAS."
        )

    asc = os.path.join(out_dir, "demnas.asc")
    tmp_asc = asc + f".tmp{os.getpid()}"
    with open(tmp_asc, "w") as fh:
        fh.write(f"ncols        {width}\n")
        fh.write(f"nrows        {height}\n")
        fh.write(f"xllcorner    {xll:.10f}\n")
        fh.write(f"yllcorner    {yll:.10f}\n")
        fh.write(f"cellsize     {cellsize:.10f}\n")
        fh.write(f"NODATA_value {NODATA}\n")
        np.savetxt(fh, int_arr, fmt="%d")
    os.replace(tmp_asc, asc)

    import hashlib
    h = hashlib.sha256()
    with open(asc, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    stats["sha256"] = h.hexdigest()[:16]
    stats["path"] = asc
    stats["nodata_warning"] = (
        WARN_ASC_NODATA_PCT <= stats["nodata_pct"] <= MAX_ASC_NODATA_PCT
    )
    return asc, stats


def which_srtm2sdf(variant: str = "Standard") -> Optional[str]:
    """Locate the built srtm2sdf / srtm2sdf-hd binary."""
    name = "srtm2sdf-hd" if variant == "HD" else "srtm2sdf"
    from ._bundle import app_root, exe as _exe
    repo = app_root()
    # repo/gui/src/signal_gui/params.py -> walk up to Signal-Server
    candidates = [
        os.path.join(repo, "Signal-Server", "utils", "sdf", "usgs2sdf", "build", _exe(name)),
        os.path.join(repo, "Signal-Server", "utils", "sdf", "usgs2sdf", _exe(name)),
        shutil.which(_exe(name)),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None
