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
    _normalize_sdf_names(sdf_dir)
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


def demnas_tif_to_sdf(
    tif_path: str,
    cache_dir: str,
    srtm2sdf_exe: Optional[str],
    engine: str,
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
) -> str:
    """Convert a local DEMNAS ``.tif`` to SPLAT ``.sdf`` for offline use.

    The ``.tif`` is reprojected to EPSG:4326, clipped to an integer-degree
    aligned bounding box covering the run area, split into 1-degree SRTM
    ``.hgt`` tiles, and each is run through ``srtm2sdf``. Results accumulate
    in ``cache/dem/sdf/demnas`` (or ``demnas_hd``) so a region is processed
    only once. Coverage of the transmitter is guaranteed by construction
    (we clip from the source), provided the source actually spans it.
    """
    if not srtm2sdf_exe or not os.path.exists(srtm2sdf_exe):
        raise DemResolveError(
            f"srtm2sdf binary not found ({srtm2sdf_exe}); cannot build "
            f"offline SDF terrain."
        )
    hd = engine == "HD"
    tile_size = 3601 if hd else 1201
    res_deg = 1.0 / (tile_size - 1)
    # Namespace the cache by the source file so swapping DEMNAS files never
    # reuses stale .sdf tiles produced from a different dataset.
    key = hashlib.md5(os.path.abspath(tif_path).encode("utf-8")).hexdigest()[:10]
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
    _run([
        "gdalwarp", "-t_srs", "EPSG:4326",
        "-te", str(ilon_lo), str(ilat_lo), str(ilon_hi), str(ilat_hi),
        "-tr", str(res_deg), str(res_deg), "-r", "bilinear", "-overwrite",
        tif_path, clipped,
    ])

    # Split into 1-degree SRTM .hgt tiles, one per cell, named by the
    # south-west corner (standard SRTM convention, e.g. S07E107.hgt).
    hgt_files: list[str] = []
    for ilat in range(ilat_lo, ilat_hi):
        for ilon in range(ilon_lo, ilon_hi):
            ns = "S" if ilat < 0 else "N"
            ew = "W" if ilon < 0 else "E"
            name = f"{ns}{abs(ilat):02d}{ew}{abs(ilon):03d}.hgt"
            out_hgt = os.path.join(raw_dir, name)
            if os.path.exists(out_hgt):
                hgt_files.append(out_hgt)
                continue
            _run([
                "gdal_translate", "-of", "SRTMHGT",
                "-outsize", str(tile_size), str(tile_size),
                "-projwin", str(ilon), str(ilat + 1), str(ilon + 1), str(ilat),
                clipped, out_hgt,
            ])
            if os.path.exists(out_hgt):
                hgt_files.append(out_hgt)
    if not hgt_files:
        raise DemResolveError(
            "Gagal mengonversi DEMNAS .tif menjadi .hgt (periksa CRS/proyeksi "
            "file)."
        )
    for hgt in sorted(hgt_files):
        convert_hgt_to_sdf(srtm2sdf_exe, hgt, sdf_dir)

    if center_lat is not None and center_lon is not None:
        minx, miny, maxx, maxy = _gdal_extent(tif_path)
        eps = 1e-3
        if not (minx - eps <= center_lon <= maxx + eps
                and miny - eps <= center_lat <= maxy + eps):
            raise DemResolveError(
                f"DEMNAS .tif tidak mencakup lokasi ({center_lat:.4f}, "
                f"{center_lon:.4f}). Pastikan file DEMNAS mencakup area ini "
                f"(mis. seluruh Indonesia)."
            )
    return sdf_dir


def demnas_tif_to_asc(
    tif_path: str,
    cache_dir: str,
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float,
    ppd: int = 1200,
) -> str:
    """Convert a local DEMNAS ``.tif`` to a SPLAT LIDAR ``.asc`` (offline).

    The ``.tif`` is reprojected to EPSG:4326 and clipped to the run bounding
    box, resampled to roughly the engine's pixels-per-tile (``ppd``) so the
    file stays small and fast to load (the engine resamples to its own output
    grid anyway). The ASCII grid is written manually (not via
    ``gdal_translate -of AAIGrid``) because Signal-Server's LIDAR loader
    (``tile_load_lidar``) parses the header with a strict ``fscanf`` that
    expects an *integer* ``NODATA_value``; GDAL emits it as a float (e.g.
    ``-3.402823e+38`` for DEMNAS voids) which makes the parse fail.
    """
    from osgeo import gdal  # local import; only needed here
    import numpy as np

    # Resample so the grid is ~ppd cells across the (larger) span. This bounds
    # the file size regardless of how fine the source DEMNAS DEM actually is.
    span = max(lon_hi - lon_lo, lat_hi - lat_lo)
    cellsize_deg = span / float(max(1, ppd)) if ppd else (1.0 / 1200.0)

    out_dir = _cache_sub(cache_dir, "lidar")
    clipped = os.path.join(out_dir, "clip.tif")
    _run([
        "gdalwarp", "-t_srs", "EPSG:4326",
        "-te", str(lon_lo), str(lat_lo), str(lon_hi), str(lat_hi),
        "-tr", str(cellsize_deg), str(cellsize_deg), "-r", "bilinear", "-overwrite",
        tif_path, clipped,
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

    asc = os.path.join(out_dir, "demnas.asc")
    with open(asc, "w") as fh:
        fh.write(f"ncols        {width}\n")
        fh.write(f"nrows        {height}\n")
        fh.write(f"xllcorner    {xll:.10f}\n")
        fh.write(f"yllcorner    {yll:.10f}\n")
        fh.write(f"cellsize     {cellsize:.10f}\n")
        fh.write(f"NODATA_value {NODATA}\n")
        np.savetxt(fh, int_arr, fmt="%d")
    return asc


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
