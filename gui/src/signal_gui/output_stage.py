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
               color_file: Optional[str] = None,
               transparent_holes: bool = True) -> str:
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
       engine because they exceed the top band). They are DEM-shaded per
       pixel with the strongest palette entry:

           Warna_Final = (Warna_Solid_Palet * Nilai_Greyscale_DEM) / 255

       so the core shows the strongest colour (red) textured by the terrain,
       not one flat solid fill and not a white hole over a light OSM basemap.

    3. When ``transparent_holes=True`` (default), any unpainted terrain shadow /
       obstruction holes enclosed inside the coverage are made fully transparent
       so the map/satellite basemap is cleanly visible underneath without
       white or grey blinding blotches.
    """
    if png_path is None:
        png_path = os.path.splitext(ppm_path)[0] + ".png"
    rgb = np.asarray(Image.open(ppm_path).convert("RGB")).copy()
    strongest = parse_strongest_color(color_file)
    lum = 0.299 * strongest[0] + 0.587 * strongest[1] + 0.114 * strongest[2]

    # Background pixels in Signal-Server are either greyscale terrain (R=G=B)
    # or sea-level water (0, 0, 170).
    grey = (rgb[..., 0] == rgb[..., 1]) & (rgb[..., 1] == rgb[..., 2])
    # White holes (unshaded terrain / tebing) are uncovered only if white is NOT
    # the top coverage band in the palette.
    white_hole = ((rgb[..., 0] >= 240) & (rgb[..., 1] >= 240) & (rgb[..., 2] >= 240)) if (lum < 200) else np.zeros(rgb.shape[:2], dtype=bool)
    sea = (rgb[..., 0] == 0) & (rgb[..., 1] == 0) & (rgb[..., 2] == 170)
    uncovered = grey | white_hole | sea

    labels, _n = ndimage.label(uncovered)
    border = np.unique(np.concatenate((
        labels[0, :], labels[-1, :],
        labels[:, 0], labels[:, -1],
    )))
    border = border[border != 0]
    if border.size:
        background = np.isin(labels, border)
    else:
        background = np.zeros(rgb.shape[:2], dtype=bool)

    enclosed_grey = grey & ~background

    # Restrict Tx core recolouring strictly to the transmitter site center (within <= 6 pixels).
    # Mountain shadows, crevices, and valleys distant from Tx are genuine terrain obstructions,
    # NOT the Tx core, and must NEVER be painted red!
    h, w = rgb.shape[:2]
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    is_center = ((yy - cy)**2 + (xx - cx)**2) <= 36
    tx_core_hole = enclosed_grey & is_center

    # For saturated Tx core (drawn grey by engine when signal exceeds top band):
    # recolour using the strongest palette color times the local DEM relief.
    is_recoloured = np.zeros(rgb.shape[:2], dtype=bool)
    if lum < 200 and np.any(tx_core_hole):
        dem_local = rgb[..., 0].astype(np.float64) / 255.0
        dem_local = np.clip(dem_local, 0.15, 1.0)
        for ch in range(3):
            chan = strongest[ch] * dem_local
            rgb[..., ch][tx_core_hole] = chan[tx_core_hole].astype(np.uint8)
        is_recoloured = tx_core_hole
    elif lum >= 200:
        # White is the top band in this palette: center white/grey is valid coverage!
        is_recoloured = tx_core_hole

    # rgb in PPM ALREADY contains the true per-pixel 3D terrain hillshade
    # from TerrainHillshade(). Keep it directly without flat border inpainting.
    if transparent_holes:
        alpha = np.where(uncovered & ~is_recoloured, 0, 255).astype(np.uint8)
    else:
        alpha = np.where(background, 0, 255).astype(np.uint8)
    rgba = np.dstack((rgb.astype(np.uint8), alpha)).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(png_path)
    return png_path


def mask_png_sector(png_path: str, bbox, tx_lat: float, tx_lon: float,
                    start_deg: float, end_deg: float,
                    max_dist_km: Optional[float] = None) -> str:
    """Keep only the bearing wedge ``start..end`` (deg from North) of a PNG.

    The engine always computes the full 360-degree circle; this post-process
    zeroes the alpha of pixels whose great-circle initial bearing from the Tx
    falls outside ``[start, end]`` (``start > end`` wraps over North, e.g.
    300..60 keeps the northern lobe). If ``max_dist_km`` is provided, cleanly
    cuts off the beam at that radius (matching Radio Mobile's neat Rx endpoint).
    ``bbox`` is (N, E, S, W) matching the overlay extent so pixel centres map linearly.
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

    # Clean radial cutoff at Rx station distance (matching Radio Mobile)
    if max_dist_km is not None and float(max_dist_km) > 0:
        dlat_rad = np.radians(lat2 - float(tx_lat))
        dlon_rad = np.radians(lon2 - float(tx_lon))
        a_dist = np.sin(dlat_rad / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlon_rad / 2.0)**2
        c_dist = 2.0 * np.arcsin(np.clip(np.sqrt(a_dist), 0.0, 1.0))
        dist_km_grid = 6371.0 * c_dist
        keep = keep & (dist_km_grid <= float(max_dist_km))

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


def make_flat_transparent_png(src_png_path_or_arr,
                              out_png_path: Optional[str] = None,
                              color_file: Optional[str] = None,
                              opacity: float = 0.75,
                              relief_weight: float = 0.30) -> str:
    """Convert a coverage image to a clean, transparent PNG for Google Earth KMZ/KML export.

    - When ``relief_weight > 0`` (default 0.30), retains a subtle, smooth 3D terrain
      contour texture without heavy or dark harsh shadows (kontur tidak terlalu tebal).
    - When ``relief_weight == 0``, outputs completely flat solid palette colors.
    - Sets background and terrain holes to 100% transparent (alpha = 0).
    - Sets coverage signal pixels to semi-transparent (default 75% opacity,
      alpha = 191) so underlying satellite imagery, terrain, and roads
      show cleanly in Google Earth.
    """
    if isinstance(src_png_path_or_arr, np.ndarray):
        arr = src_png_path_or_arr.copy()
        if out_png_path is None:
            raise ValueError("out_png_path required when passing numpy array")
    else:
        if out_png_path is None:
            out_png_path = os.path.splitext(src_png_path_or_arr)[0] + "_flat_trans.png"
        img = Image.open(src_png_path_or_arr).convert("RGBA")
        arr = np.asarray(img).copy()

    h, w = arr.shape[:2]
    alpha = arr[..., 3]
    vis_mask = alpha > 0
    if not np.any(vis_mask):
        Image.fromarray(arr, "RGBA").save(out_png_path)
        return out_png_path

    # Parse palette bands from color_file or fallback to radiomobile.dcf
    pal_colors = None
    if color_file and os.path.exists(color_file):
        try:
            from . import rm_style
            with open(color_file, "r", encoding="utf-8", errors="replace") as fh:
                bands = rm_style.parse_dcf_levels(fh.read())
            if bands:
                pal_colors = np.array([c for _, c in bands], dtype=np.float32)
        except Exception:
            pass

    if pal_colors is None:
        try:
            from . import rm_style
            dcf_default = os.path.join(os.path.dirname(__file__), "resources", "radiomobile.dcf")
            if os.path.exists(dcf_default):
                with open(dcf_default, "r", encoding="utf-8", errors="replace") as fh:
                    bands = rm_style.parse_dcf_levels(fh.read())
                if bands:
                    pal_colors = np.array([c for _, c in bands], dtype=np.float32)
        except Exception:
            pass

    if pal_colors is None:
        # Fallback to standard 11-level RM palette
        pal_colors = np.array([
            (255, 50, 90),   # Red / Hot Pink (-60 dBm)
            (255, 100, 100), # Light Red
            (255, 220, 100), # Orange / Yellow
            (255, 255, 100), # Yellow
            (192, 255, 100), # Lime Green
            (100, 255, 100), # Green
            (100, 255, 192), # Mint / Seafoam
            (100, 255, 255), # Cyan
            (100, 220, 255), # Sky Blue
            (0, 38, 255),    # Deep Blue
            (128, 0, 128),   # Purple
        ], dtype=np.float32)

    vis_rgb = arr[vis_mask, :3].astype(np.float32)

    # Protect transmitter center site from being treated as hole
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    is_center = ((yy - cy)**2 + (xx - cx)**2) <= 36
    center_flat_vis = is_center[vis_mask]

    # Filter out unshaded grey background or white holes outside center
    is_grey = (vis_rgb[:, 0] == vis_rgb[:, 1]) & (vis_rgb[:, 1] == vis_rgb[:, 2])
    is_white = np.all(vis_rgb >= 240, axis=1)
    is_sea = (vis_rgb[:, 0] == 0) & (vis_rgb[:, 1] == 0) & (vis_rgb[:, 2] == 170)
    hole_submask = (is_grey | is_white | is_sea) & ~center_flat_vis

    # Chromaticity normalization to cancel out terrain multiplier (TerrainHillshade)
    max_c = np.maximum(np.max(vis_rgb, axis=1, keepdims=True), 1e-5)
    norm_rgb = (vis_rgb / max_c) * 255.0

    pal_max = np.maximum(np.max(pal_colors, axis=1, keepdims=True), 1.0)
    norm_pal = (pal_colors / pal_max) * 255.0

    dists = np.sum((norm_rgb[:, None, :] - norm_pal[None, :, :]) ** 2, axis=2)
    best_band = np.argmin(dists, axis=1)

    target_alpha = int(np.clip(opacity * 255.0, 1, 255))

    out_arr = np.zeros((h, w, 4), dtype=np.uint8)
    vis_indices = np.flatnonzero(vis_mask)
    valid_submask = ~hole_submask
    valid_indices = vis_indices[valid_submask]

    flat_rgb = pal_colors[best_band[valid_submask]]

    if relief_weight > 0:
        # Subtle 3D contour: soften hillshade so shadows are never too dark/thick
        flat_max = np.maximum(np.max(flat_rgb, axis=1, keepdims=True), 1.0)
        orig_shade = np.clip(max_c[valid_submask] / flat_max, 0.15, 1.0)
        subtle_shade = (1.0 - relief_weight) + relief_weight * orig_shade
        final_rgb = np.clip(flat_rgb * subtle_shade, 0, 255).astype(np.uint8)
    else:
        final_rgb = flat_rgb.astype(np.uint8)

    out_flat = out_arr.reshape(-1, 4)
    out_flat[valid_indices, :3] = final_rgb
    out_flat[valid_indices, 3] = target_alpha

    out_img = Image.fromarray(out_flat.reshape((h, w, 4)), "RGBA")
    out_img.save(out_png_path)
    return out_png_path


def build_kml(png_name: str, bbox, title: str = "Coverage", opacity: Optional[float] = 0.75) -> str:
    """Build a doc.kml string with a GroundOverlay over ``bbox`` = (N, E, S, W)."""
    n, e, s, w = bbox
    color_tag = ""
    if opacity is not None:
        alpha_hex = format(int(np.clip(opacity * 255.0, 0, 255)), "02x")
        color_tag = f"\n      <color>{alpha_hex}ffffff</color>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Folder>
    <name>{title}</name>
    <GroundOverlay>
      <name>{title}</name>{color_tag}
      <Icon>
        <href>{png_name}</href>
        <viewBoundScale>0.75</viewBoundScale>
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


def export_kmz(path: str, png: str, bbox, base: str,
               result: Optional[dict] = None,
               flat: bool = True,
               color_file: Optional[str] = None,
               opacity: float = 0.75,
               relief_weight: float = 0.30) -> str:
    """Build a KMZ (zipped KML GroundOverlay + PNG image).

    - When ``flat=True`` and ``relief_weight > 0`` (default 0.30), generates a
      subtle 3D terrain relief contour that is gentle and not too thick/dark.
    - When ``relief_weight == 0``, generates completely flat solid palette colors.
    - Transparent background (alpha = 0) and semi-transparent signal (default 75%).
    """
    import zipfile

    if flat:
        flat_png_name = base + "_flat.png"
        flat_png_path = os.path.join(os.path.dirname(png), flat_png_name)
        make_flat_transparent_png(
            png, flat_png_path, color_file=color_file, opacity=opacity,
            relief_weight=relief_weight,
        )
        export_png_path = flat_png_path if os.path.exists(flat_png_path) else png
        export_png_name = os.path.basename(export_png_path)
        kml_text = build_kml(export_png_name, bbox, base, opacity=opacity)
    else:
        export_png_path = png
        export_png_name = os.path.basename(png)
        kml_path = result.get("kml") if isinstance(result, dict) else None
        if kml_path and os.path.exists(kml_path):
            with open(kml_path, "r", encoding="utf-8") as fh:
                kml_text = fh.read()
        elif bbox is not None:
            kml_text = build_kml(export_png_name, bbox, base, opacity=opacity)
        else:
            raise ValueError("No bounding box available for KML.")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(export_png_path, arcname=export_png_name)
        z.writestr("doc.kml", kml_text)
    return path


def stage_output(ppm_path: str, stdout_text: str, title: str = "Coverage",
                 tx_coords: Optional[tuple[float, float]] = None,
                 color_file: Optional[str] = None,
                 params: Optional[dict] = None) -> dict:
    trans_holes = bool(params.get("transparent_holes", True)) if isinstance(params, dict) else True
    png_path = ppm_to_png(ppm_path, color_file=color_file, transparent_holes=trans_holes)
    bbox = parse_bbox(stdout_text, params=params)
    kml_path = os.path.splitext(ppm_path)[0] + ".kml"
    if bbox is not None:
        png_name = os.path.basename(png_path)
        with open(kml_path, "w", encoding="utf-8") as fh:
            fh.write(build_kml(png_name, bbox, title))

    res = {
        "ppm": ppm_path,
        "png": png_path,
        "kml": kml_path,
        "bbox": bbox,
        "color_file": color_file,
        "params": params,
    }

    # Render Radio Mobile-style 3D hillshade composite picture only if explicitly requested.
    # Export controller renders this on-demand when requested by the user, avoiding 7-8s blocking overhead.
    if bbox is not None and params and params.get("render_rm_picture") and (params.get("sdf_dir") or params.get("lidar_file")):
        try:
            from . import rm_style
            rm_out = os.path.splitext(ppm_path)[0] + "_rm.png"
            rm_style.render_for_run(rm_out, bbox, params, png_path)
            if os.path.exists(rm_out):
                res["rm_png"] = rm_out
        except Exception:
            pass

    return res


def analyze_coverage_shape(png_path: str, bbox,
                           tx_lat: float, tx_lon: float) -> dict:
    """Measure how "circle-like" a coverage overlay is around the Tx.

    Fake-terrain runs (engine falling back to sea-level/flat ground) produce a
    near-perfect circle, while real ITM over relief produces a ragged edge.
    Returns ``{"fill_az_pct", "edge_mean_px", "edge_rel_std"}`` where
    ``edge_rel_std`` is the coefficient of variation of the outermost filled
    radius over all azimuths that contain any coverage (0 % = perfect circle).
    """
    img = np.asarray(Image.open(png_path).convert("RGBA"))
    h, w = img.shape[:2]
    filled = img[..., 3] > 0
    n, e, s, wst = (float(v) for v in bbox)
    cx = (float(tx_lon) - wst) / (e - wst) * w
    cy = (n - float(tx_lat)) / (n - s) * h
    rmax = min(cx, cy, w - cx, h - cy)

    angles = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    radii = np.linspace(2.0, rmax * 0.999, 400)
    edge = np.zeros(angles.size)
    for i, a in enumerate(angles):
        xs = (cx + radii * np.cos(a)).astype(int)
        ys = (cy + radii * np.sin(a)).astype(int)
        ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        f = np.zeros(radii.size, dtype=bool)
        f[ok] = filled[ys[ok], xs[ok]]
        if f.any():
            edge[i] = radii[np.max(np.flatnonzero(f))]

    hit = edge > 0
    o = edge[hit]
    mean = float(o.mean()) if o.size else 0.0
    rel = float(o.std() / mean) if mean > 0 else 1.0
    return {
        "fill_az_pct": float(hit.mean() * 100.0),
        "edge_mean_px": mean,
        "edge_rel_std": rel,
    }
