"""Radio Mobile style helpers: colour-palette parsing, .dcf generation and
RM-style picture rendering (hypsometric terrain + hillshade + coverage +
site symbols + range circles).

Radio Mobile ships its palettes as ``colors*.dat`` text files (see
``<repo>/rmwcore``): a ``Color File`` header line, two setting lines, the
ascending elevation thresholds, one 24-bit hex RGB colour per band and a
trailing flag.  ``generate_dcf`` converts such a palette into the plain-text
``"<level>: <r>, <g>, <b>"`` format Signal-Server consumes through
``LoadSignalColors`` (``inputs.cc``), so the engine paints coverage with the
exact Radio Mobile colours.
"""

from __future__ import annotations

import math
import os
import re
from typing import Iterable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from ._bundle import app_root

RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "resources")
RM_RESOURCES_DIR = os.path.join(RESOURCES_DIR, "rm")

_HEX_COLOR_RE = re.compile(r"^([0-9A-Fa-f]{6})$")
_DCF_LINE_RE = re.compile(r"^\s*([-+]?\d+)\s*:\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*,\s*([-+]?\d+)")

DEFAULT_TOP_DBM = -60
DEFAULT_BOTTOM_DBM = -120

# Canonical coverage colour ramp (strongest -> weakest), used for the engine
# colour table so the displayed coverage follows a clear red -> yellow -> green
# -> greenish-blue -> cyan -> blue scale instead of Radio Mobile's white->blue
# (a white centre reads as a hole over a light OSM basemap).
COVERAGE_RAMP = (
    (255, 0, 0),      # red            (strongest signal)
    (255, 255, 0),    # yellow
    (0, 200, 0),      # green
    (0, 200, 200),    # greenish-blue (teal)
    (0, 255, 255),    # cyan
    (0, 100, 255),    # blue           (weakest signal)
)

# Visual-compositing tunables for the RM-style coverage overlay.
# SHADE_MIN: minimum brightness multiplier where the hillshade is darkest, so
# signal colours on lee slopes fall to that fraction instead of pure black.
SHADE_MIN = 0.45
# EDGE_FADE_DB: width (dB) of the gradual alpha fade applied to the weakest
# (outermost) coverage band so the plot melts into the terrain instead of
# ending in a hard disk edge.
EDGE_FADE_DB = 10.0
ALPHA_MIN = 0.2
SMOOTH_SIGMA_PX = 0.75  # Gaussian edge AA (in 2x supersample space)


# ---------------------------------------------------------------------------
# Palette parsing / generation
# ---------------------------------------------------------------------------

class RmPalette:
    """A Radio Mobile ``colors*.dat`` palette."""

    def __init__(self, name: str, thresholds: list[float],
                 colors: list[tuple[int, int, int]]):
        self.name = name
        self.thresholds = thresholds          # ascending band boundaries
        self.colors = colors                  # one RGB tuple per band

    def __eq__(self, other) -> bool:  # pragma: no cover - convenience
        return (isinstance(other, RmPalette)
                and self.thresholds == other.thresholds
                and self.colors == other.colors)

    def hypso_rgb(self, elev: np.ndarray) -> np.ndarray:
        """Map an elevation grid onto the palette -> uint8 HxWx3 array."""
        thr = np.asarray(self.thresholds, dtype=np.float64)
        lut = np.asarray(self.colors, dtype=np.uint8)
        idx = np.searchsorted(thr, elev.astype(np.float64), side="right")
        idx = np.clip(idx, 0, len(lut) - 1)
        return lut[idx]

    def bands_descending(self, top_dbm: float = DEFAULT_TOP_DBM,
                         bottom_dbm: float = DEFAULT_BOTTOM_DBM
                         ) -> list[tuple[float, tuple[int, int, int]]]:
        """Palette as (level, rgb) bands, strongest signal first.

        The first colour is the strongest band (red, the saturated Tx centre)
        and the last the weakest (blue).
        """
        n = len(self.colors)
        span = top_dbm - bottom_dbm
        return [
            (top_dbm - span * i / max(1, n - 1), color)
            for i, color in enumerate(self.colors)
        ]


def parse_colors_dat(path: str) -> RmPalette:
    """Parse a Radio Mobile ``colors*.dat`` file.

    Layout (CRLF text): ``Color File`` header, two numeric setting lines,
    the ascending band thresholds, twelve hex RGB colours, one trailing
    numeric flag.  The two leading numbers are settings, not thresholds.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    colors: list[tuple[int, int, int]] = []
    numbers: list[float] = []
    for ln in lines:
        m = _HEX_COLOR_RE.match(ln)
        if m:
            h = m.group(1)
            colors.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        elif colors:
            break  # trailing flag line after the colour block
        else:
            try:
                numbers.append(float(ln))
            except ValueError:
                continue  # header text like "Color File"
    # Skip the two leading setting lines; the rest are band thresholds.
    thresholds = numbers[2:] if len(numbers) > 2 else numbers
    if not colors:
        raise ValueError(f"No RGB colours found in {path}")
    return RmPalette(os.path.basename(path), thresholds, colors)


def palette_to_dcf_text(palette: Optional[RmPalette] = None,
                        top_dbm: float = DEFAULT_TOP_DBM,
                        bottom_dbm: float = DEFAULT_BOTTOM_DBM) -> str:
    """Render palette bands as Signal-Server .scf/.dcf lines (strongest first).

    Format must satisfy ``sscanf("%d: %d, %d, %d")`` in ``LoadSignalColors``.
    Uses the canonical :data:`COVERAGE_RAMP` (red -> yellow -> green ->
    greenish-blue -> cyan -> blue) so the strongest signal is red, not white.
    ``palette`` is accepted for API compatibility but ignored.
    """
    colors = [tuple(c) for c in COVERAGE_RAMP]
    out = []
    n = len(colors)
    for i, (r, g, b) in enumerate(colors):
        level = top_dbm - (top_dbm - bottom_dbm) * i / max(1, n - 1)
        out.append(f"{int(round(level)):4d}: {int(r):3d}, {int(g):3d}, {int(b):3d}")
    return "\n".join(out) + "\n"


def parse_dcf_levels(text: str) -> list[tuple[int, tuple[int, int, int]]]:
    """Parse ``level: r, g, b`` lines (file order preserved)."""
    bands = []
    for ln in text.splitlines():
        ln = ln.split(";", 1)[0]
        m = _DCF_LINE_RE.match(ln)
        if m:
            bands.append((int(m.group(1)),
                          (int(m.group(2)), int(m.group(3)), int(m.group(4)))))
    return bands


def default_dat_path(root: Optional[str] = None) -> Optional[str]:
    """Locate an RM ``colors.dat``: workspace ``rmwcore/`` then bundled copy."""
    candidates = []
    if root:
        candidates.append(os.path.join(root, "rmwcore", "colors.dat"))
    try:
        candidates.append(os.path.join(app_root(), "rmwcore", "colors.dat"))
    except Exception:  # pragma: no cover - packaging edge cases
        pass
    candidates.append(os.path.join(RM_RESOURCES_DIR, "colors.dat"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def ensure_palette_dcf(dest: str, dat_path: Optional[str] = None,
                       root: Optional[str] = None,
                       top_dbm: float = DEFAULT_TOP_DBM,
                       bottom_dbm: float = DEFAULT_BOTTOM_DBM) -> str:
    """Generate a Signal-Server colour table from an RM palette.

    Returns the path written. Raises when no source palette exists.
    """
    src = dat_path or default_dat_path(root)
    if not src:
        raise FileNotFoundError(
            "No Radio Mobile colors*.dat found (looked in rmwcore/ and "
            "bundled resources)")
    palette = parse_colors_dat(src)
    text = palette_to_dcf_text(palette, top_dbm=top_dbm, bottom_dbm=bottom_dbm)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    return dest


# ---------------------------------------------------------------------------
# Terrain: SDF / ASC loading + hillshade + hypsometric tinting
# ---------------------------------------------------------------------------

class SdfTile:
    __slots__ = ("south", "north", "west", "east", "data")

    def __init__(self, south: float, north: float, west: float, east: float,
                 data: np.ndarray):
        self.south, self.north = south, north
        self.west, self.east = west, east
        self.data = data


def _west_deg(lon_east: float) -> float:
    """Convert eastern longitude (degrees) to SPLAT's 0..360 west domain."""
    return (360.0 - lon_east) % 360.0 if lon_east >= 0 else -lon_east


def load_sdf_tile(path: str) -> SdfTile:
    """Read one uncompressed .sdf tile (header + one integer per line).

    Header order matches ``LoadSDF_SDF``: max_west, min_north (south),
    min_west, max_north (north). Data rows run south->north (row 0 =
    ``min_north``, verified against raw SRTM .hgt ground truth),
    columns west->east; elevations are metres.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        max_west = float(fh.readline())
        min_north = float(fh.readline())
        min_west = float(fh.readline())
        max_north = float(fh.readline())
        raw = np.asarray(fh.read().split(), dtype=np.float32)
    n = int(round(math.sqrt(raw.size)))
    if n * n != raw.size:
        raise ValueError(f"{path}: {raw.size} samples is not square")
    data = raw.reshape(n, n)
    if min_west > 180:  # 0..360 west domain -> eastern longitudes
        west, east = 360.0 - min_west, 360.0 - max_west
    else:
        west, east = -min_west, -max_west
    return SdfTile(min_north, max_north, min(west, east), max(west, east), data)


def load_sdf_tiles(sdf_dir: str, hd: bool = False) -> list[SdfTile]:
    tiles = []
    for name in sorted(os.listdir(sdf_dir)):
        if not name.endswith("-hd.sdf" if hd else ".sdf"):
            continue
        if hd and (not name.endswith("-hd.sdf")):
            continue
        if not hd and name.endswith("-hd.sdf"):
            continue
        try:
            tiles.append(load_sdf_tile(os.path.join(sdf_dir, name)))
        except (OSError, ValueError):
            continue
    return tiles


class ElevationSource:
    """Samples elevation (metres) from SDF tiles or an ESRI ASCII grid."""

    def __init__(self, sdf_dir: Optional[str] = None, hd: bool = False,
                 asc_file: Optional[str] = None):
        self.tiles: list[SdfTile] = []
        if sdf_dir:
            self.tiles = load_sdf_tiles(sdf_dir, hd=hd)
        elif asc_file:
            self.tiles = [load_asc_tile(asc_file)]

    @property
    def available(self) -> bool:
        return bool(self.tiles)

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Bilinear elevation sample; NaN outside covered terrain."""
        out = np.full(lat.shape, np.nan, dtype=np.float64)
        for t in self.tiles:
            inside = ((lat >= t.south) & (lat <= t.north)
                      & (lon >= t.west) & (lon <= t.east) & np.isnan(out))
            if not inside.any():
                continue
            rows, cols = t.data.shape
            frow = (lat[inside] - t.south) / (t.north - t.south) * (rows - 1)
            fcol = (lon[inside] - t.west) / (t.east - t.west) * (cols - 1)
            vals = ndimage.map_coordinates(
                t.data.astype(np.float64), np.vstack([frow, fcol]),
                order=1, mode="nearest")
            out[inside] = vals
        return out


def _looks_like_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def load_asc_tile(path: str) -> SdfTile:
    """Minimal ESRI ASCII (.asc) reader for the engine's LIDAR export."""
    header: dict[str, float] = {}
    tokens: list[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            parts = ln.split()
            if (len(parts) == 2 and parts[0].replace("_", "").isalpha()
                    and _looks_like_float(parts[1])):
                header[parts[0].lower()] = float(parts[1])
            else:
                tokens.extend(parts)
    data = np.asarray(tokens, dtype=np.float32).reshape(
        int(header["nrows"]), int(header["ncols"]))
    # ESRI ASCII raster rows are written North -> South (row 0 = North).
    # SdfTile and ElevationSource expect rows running South -> North (row 0 = South / yllcorner).
    data = np.flipud(data)
    cell = header["cellsize"]
    xll, yll = header["xllcorner"], header["yllcorner"]
    return SdfTile(yll, yll + cell * data.shape[0], xll,
                   xll + cell * data.shape[1], data)


def hillshade(elev: np.ndarray, cellsize_m: float,
              azimuth_deg: float = 315.0, altitude_deg: float = 45.0
              ) -> np.ndarray:
    """Horn-method hillshade -> 0..1 brightness (NaN-safe)."""
    z = np.where(np.isnan(elev), 0.0, elev)
    dzdy, dzdx = np.gradient(z, cellsize_m)
    normal = np.dstack((-dzdx, -dzdy, np.ones_like(z)))
    norm = np.linalg.norm(normal, axis=2)
    az, alt = math.radians(azimuth_deg), math.radians(altitude_deg)
    light = np.array([
        math.cos(alt) * math.sin(az),
        math.cos(alt) * -math.cos(az),
        math.sin(alt),
    ])
    shade = (normal @ light) / np.maximum(norm, 1e-12)
    return np.clip(shade, 0.0, 1.0)


def decode_coverage_field(rgba: np.ndarray,
                          bands: list[tuple[int, tuple[int, int, int]]]
                          ) -> np.ndarray:
    """Map an obaque coverage PNG back to a per-pixel dBm field.

    Each non-transparent pixel is matched to the nearest palette band colour;
    the pixel value becomes that band's dBm level. Pixels whose colour is far
    from every band (e.g. opaque black "blocked" holes) and transparent pixels
    become NaN, so they can be left transparent in the final composite.
    """
    rgb = rgba[..., :3].astype(np.int32)
    amask = rgba[..., 3] > 0
    if not bands:
        return np.full(rgb.shape[:2], np.nan, dtype=np.float64)
    levels = np.array([lvl for lvl, _ in bands], dtype=np.float64)
    cols = np.array([c for _, c in bands], dtype=np.int32)
    flat = rgb.reshape(-1, 3)
    d = np.linalg.norm(flat[:, None, :] - cols[None, :, :], axis=2)
    best = np.argmin(d, axis=1)
    mind = d[np.arange(flat.shape[0]), best]
    out = np.full(flat.shape[0], np.nan, dtype=np.float64)
    valid = (mind < 80) & amask.reshape(-1)
    out[valid] = levels[best[valid]]
    return out.reshape(rgb.shape[:2])


def colormap_piecewise(levels: np.ndarray, colors: np.ndarray,
                       values: np.ndarray) -> np.ndarray:
    """Piecewise-linear interpolate band colours across dBm levels.

    ``levels`` / ``colors`` are the palette bands (any order); ``values`` is the
    field to colour. Unlike the engine's discrete LUT this yields smooth
    gradients *between* bands (the "bilinear" look).
    """
    idx = np.argsort(levels)
    lv = levels[idx]
    cv = colors[idx]
    out = np.empty(values.shape + (3,), dtype=np.float64)
    for c in range(3):
        out[..., c] = np.interp(values, lv, cv[:, c],
                                left=cv[0, c], right=cv[-1, c])
    return out


def _shade_grid(elev: np.ndarray, cellsize_m: float) -> np.ndarray:
    """Hillshade brightness (0..1) for a (possibly supersampled) elev grid."""
    return hillshade(elev, cellsize_m)


# ---------------------------------------------------------------------------
# Picture composition
# ---------------------------------------------------------------------------

def _symbol_path(name: str) -> Optional[str]:
    p = os.path.join(RM_RESOURCES_DIR, name)
    return p if os.path.exists(p) else None


def _paste_symbol(canvas: Image.Image, symbol: Image.Image, cx: int, cy: int,
                  height: int, label: Optional[str]) -> None:
    scale = height / symbol.height
    img = symbol.convert("RGBA").resize(
        (max(1, int(symbol.width * scale)), height), Image.LANCZOS)
    canvas.alpha_composite(img, (cx - img.width // 2, cy - img.height // 2))
    if label:
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        tw = draw.textlength(label, font=font)
        ty = cy + height // 2 + 2
        draw.rectangle([cx - tw / 2 - 2, ty - 1, cx + tw / 2 + 2,
                        ty + font.size + 1], fill=(255, 255, 255, 170))
        draw.text((cx - tw / 2, ty), label, fill=(0, 0, 0), font=font)


def _range_circle_pts(tlat: float, tlon: float, radius_km: float,
                      lats: np.ndarray, lons: np.ndarray, steps: int = 240):
    ang = np.linspace(0.0, 2.0 * math.pi, steps)
    dlat = radius_km * np.cos(ang) / 110.574
    dlon = radius_km * np.sin(ang) / (111.320 * max(0.01, math.cos(
        math.radians(tlat))))
    la, lo = tlat + dlat, tlon + dlon

    def px(arr_lat, arr_lon):
        col = (arr_lon - lons[0]) / (lons[-1] - lons[0]) * (lons.size - 1)
        row = (lats[0] - arr_lat) / (lats[0] - lats[-1]) * (lats.size - 1)
        return np.clip(col, 0, lons.size - 1), np.clip(row, 0, lats.size - 1)

    return px(la, lo)


def render_rm_picture(out_png: str, bbox, *,
                      coverage_png: Optional[str] = None,
                      palette: Optional[RmPalette] = None,
                      coverage_bands: Optional[
                          list[tuple[int, tuple[int, int, int]]]] = None,
                      sdf_dir: Optional[str] = None,
                      hd: bool = False,
                      asc_file: Optional[str] = None,
                       sites: Optional[list[dict]] = None,
                       ranges_km: Iterable[float] = (),
                       width: int = 1200,
                       title: Optional[str] = None,
                       legend: bool = True,
                       elev_source: Optional[ElevationSource] = None,
                       threshold_dbm: Optional[float] = None) -> str:
    """Compose a Radio Mobile-style picture and save it as PNG.

    ``bbox`` is ``(north, east, south, west)`` decimal degrees. Layers,
    bottom-up: hypsometric terrain tinted from ``palette`` with hillshade
    relief, semi-transparent coverage overlay, range circles around the
    Tx site, antenna/dot symbols with labels, optional dBm legend strip.

    Missing terrain degrades gracefully to a neutral backdrop so a broken
    DEM never blocks the export.
    """
    n, e, s, w = (float(v) for v in bbox)
    mid_lat = math.radians((n + s) / 2.0)
    W = max(64, int(width))
    H = max(64, int(round(W * (n - s) / max(1e-9, (e - w)) * math.cos(mid_lat))))

    lons = np.linspace(w, e, W)
    lats = np.linspace(n, s, H)
    lat_g, lon_g = np.meshgrid(lats, lons, indexing="ij")

    # --- terrain layer -----------------------------------------------------
    shade = None
    src = elev_source or ElevationSource(sdf_dir=sdf_dir, hd=hd,
                                         asc_file=asc_file)
    if src.available:
        elev = src.sample(lat_g, lon_g)
        cell_m = ((n - s) * 111320.0) / H
        shade = hillshade(elev, cell_m)
        if palette is not None:
            filled = np.where(np.isnan(elev), 0.0, elev)
            rgb = palette.hypso_rgb(filled).astype(np.float64)
        else:
            base = np.where(np.isnan(elev), 235.0,
                            245.0 - 90.0 * _norm01(elev))
            rgb = np.dstack([base] * 3)
        rgb *= (0.45 + 0.55 * shade)[..., None]
        rgb[np.isnan(elev)] = 225.0  # uncovered terrain: flat light grey
        terrain = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB")
    else:
        terrain = Image.new("RGB", (W, H), (226, 230, 234))

    canvas = terrain.convert("RGBA")

    # --- coverage overlay ----------------------------------------------------
    if coverage_png and os.path.exists(coverage_png):
        # Resize the coverage into canvas space first so its decoded field
        # aligns pixel-for-pixel with the terrain hillshade grid.
        cov_rgba = np.array(
            Image.open(coverage_png).convert("RGBA").resize((W, H),
                                                            Image.LANCZOS))
        bands = list(coverage_bands or [])
        if bands and shade is not None:
            field = decode_coverage_field(cov_rgba, bands)
            if not np.all(np.isnan(field)):
                levels = np.array([lvl for lvl, _ in bands], dtype=np.float64)
                colors = np.array([c for _, c in bands], dtype=np.float64)
                # Supersample x2 for bilinear band blending + smooth AA.
                f2 = ndimage.zoom(field, 2, order=1)
                sh2 = ndimage.zoom(shade, 2, order=1)
                sig = colormap_piecewise(levels, colors, f2)
                shade_f = SHADE_MIN + (1.0 - SHADE_MIN) * sh2
                sig = sig * shade_f[..., None]
                sig = np.nan_to_num(sig)
                base = np.where(np.isnan(f2), 0.0, 1.0)
                if threshold_dbm is not None:
                    a = (f2 - float(threshold_dbm)) / EDGE_FADE_DB
                    a = np.clip(a, ALPHA_MIN, 1.0)
                    base = base * a
                alpha = ndimage.gaussian_filter(base, SMOOTH_SIGMA_PX)
                alpha = np.nan_to_num(alpha)
                alpha = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
                layer = Image.fromarray(
                    np.dstack([sig.clip(0, 255).astype(np.uint8), alpha]),
                    "RGBA")
                layer = layer.resize((W, H), Image.LANCZOS)
                canvas.alpha_composite(layer)
            else:
                canvas.alpha_composite(Image.fromarray(cov_rgba, "RGBA"))
        else:
            canvas.alpha_composite(Image.fromarray(cov_rgba, "RGBA"))

    draw = ImageDraw.Draw(canvas)

    # --- range circles -------------------------------------------------------
    tx = next((st for st in (sites or []) if st.get("kind") == "tx"), None)
    if tx:
        for r_km in ranges_km:
            if not r_km or r_km <= 0:
                continue
            col, row = _range_circle_pts(tx["lat"], tx["lon"], float(r_km),
                                         lats, lons)
            pts = list(zip(col.tolist(), row.tolist()))
            pts.append(pts[0])
            draw.line(pts, fill=(20, 20, 20, 255), width=2)

    # --- site symbols --------------------------------------------------------
    def to_px(lat, lon):
        col = (lon - w) / (e - w) * (W - 1)
        row = (n - lat) / (n - s) * (H - 1)
        return int(round(col)), int(round(row))

    for st in sites or []:
        cx, cy = to_px(st["lat"], st["lon"])
        if st.get("kind") == "tx":
            sym_path = _symbol_path("antenna_pin.png")
            height = 30
        else:
            sym_path = _symbol_path("dot_g.png")
            height = 18
        sym = Image.open(sym_path) if sym_path else None
        if sym is None:  # fallback: coloured disc
            sym = Image.new("RGBA", (16, 16), (0,) * 4)
            d = ImageDraw.Draw(sym)
            fill = (212, 180, 0, 255) if st.get("kind") == "tx" else (60, 200, 60, 255)
            d.ellipse([2, 2, 14, 14], fill=fill, outline=(0, 0, 0, 255))
        _paste_symbol(canvas, sym, cx, cy, height, st.get("label"))

    # --- legend strip ----------------------------------------------------------
    if legend and coverage_bands:
        pad = 8
        lh = 16
        lw = 74
        total_h = pad * 2 + lh * len(coverage_bands)
        strip = Image.new("RGBA", (lw, total_h), (250, 250, 250, 216))
        sd = ImageDraw.Draw(strip)
        font = ImageFont.load_default()
        for i, (level, color) in enumerate(coverage_bands):
            y0 = pad + i * lh
            sd.rectangle([4, y0, 26, y0 + lh - 3], fill=tuple(color) + (255,),
                         outline=(60, 60, 60, 255))
            sd.text((31, y0 + 1), f"{level} dBm", fill=(20, 20, 20, 255),
                    font=font)
        full = Image.new("RGBA", (canvas.width + lw + 6,
                                  max(canvas.height, total_h)),
                         (255, 255, 255, 255))
        full.alpha_composite(canvas, (0, 0))
        full.alpha_composite(strip, (canvas.width + 6, 0))
        canvas = full
    elif canvas.width != W or canvas.height != H:
        pass

    if title:
        d = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        d.text((6, 4), title, fill=(15, 15, 15, 220), font=font)

    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    canvas.convert("RGB").save(out_png, "PNG")
    return out_png


def _norm01(a: np.ndarray) -> np.ndarray:
    lo, hi = np.nanmin(a), np.nanmax(a)
    if hi <= lo:
        return np.zeros_like(a)
    return (a - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# High-level wiring helpers
# ---------------------------------------------------------------------------

def rm_sites_from_params(p: dict) -> list[dict]:
    """Build the site symbol list (Tx antenna + optional Rx dot)."""
    sites = []
    if p.get("tx_lat") is not None and p.get("tx_lon") is not None:
        sites.append({"kind": "tx", "lat": float(p["tx_lat"]),
                      "lon": float(p["tx_lon"]),
                      "label": p.get("tx_name") or "Tx"})
    if p.get("rx_lat") is not None and p.get("rx_lon") is not None:
        sites.append({"kind": "rx", "lat": float(p["rx_lat"]),
                      "lon": float(p["rx_lon"]),
                      "label": p.get("rx_name") or "Rx"})
    return sites


def render_for_run(out_png: str, bbox, params: dict, coverage_png: str,
                   palette: Optional[RmPalette] = None) -> str:
    """Render the RM-style picture for a finished engine run."""
    bands = None
    color_file = params.get("_rm_color_file") or params.get("color_file")
    if color_file and os.path.exists(color_file):
        try:
            with open(color_file, "r", encoding="utf-8", errors="replace") as fh:
                bands = parse_dcf_levels(fh.read())
        except OSError:
            bands = None
    return render_rm_picture(
        out_png, bbox,
        coverage_png=coverage_png,
        palette=palette,
        coverage_bands=bands,
        sdf_dir=params.get("sdf_dir"),
        hd=params.get("engine") == "HD",
        asc_file=params.get("lidar_file"),
        sites=rm_sites_from_params(params),
        ranges_km=[params["radius"]] if params.get("radius") else (),
        title=f"{params.get('tx_name') or 'Tx'} -> "
              f"{params.get('frequency_mhz', '')} MHz".strip(),
        threshold_dbm=params.get("rx_threshold_dbm"),
    )
