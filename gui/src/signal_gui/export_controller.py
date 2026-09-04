"""Export operations for Radio Link, Area Coverage, and Elevation DEMs.

Extracts export logic from MainWindow for modularity, clean code, and testability.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
from typing import Any, Callable, Dict, Optional

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from . import output_stage, rm_import
from .link_kml import export_radio_link_kml, export_radio_link_kmz

logger = logging.getLogger("signal_gui.export")


def export_link_png(
    parent: QWidget,
    canvas: Any,
    status_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Export the path profile canvas as a PNG."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export Path Profile PNG", "path_profile.png", "PNG Image (*.png)"
    )
    if not path:
        return None
    pix = canvas.grab()
    pix.save(path)
    if status_callback:
        status_callback(f"Path profile image saved: {path}")
    return path


def export_link_kml(
    parent: QWidget,
    result: Optional[dict],
    params: Optional[dict],
    status_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Export radio link data as KML (Radio Mobile format)."""
    result = result or {}
    link = result.get("link")
    if not link:
        QMessageBox.warning(parent, "No Link Data", "No Radio Link data available to export.")
        return None

    p = result.get("params") or params or {}
    tx_name = str(p.get("tx_site_name") or p.get("tx_name") or "Base")
    rx_name = str(p.get("rx_site_name") or p.get("rx_name") or "Mobile")
    default_fn = f"{tx_name}_{rx_name}_link.kml".replace(" ", "_")

    fn, _ = QFileDialog.getSaveFileName(
        parent,
        "Export Radio Link KML (Radio Mobile Format)",
        default_fn,
        "KML Files (*.kml);;KMZ Files (*.kmz);;All Files (*)",
    )
    if not fn:
        return None

    try:
        if fn.lower().endswith(".kmz"):
            export_radio_link_kmz(fn, p, link, num_points=501)
            if status_callback:
                status_callback(f"Exported Radio Link KMZ: {fn}")
            QMessageBox.information(parent, "KMZ Exported", f"Successfully exported Radio Link KMZ to:\n{fn}")
        else:
            if not fn.lower().endswith(".kml"):
                fn += ".kml"
            export_radio_link_kml(fn, p, link, num_points=501, copy_icon=True)
            if status_callback:
                status_callback(f"Exported Radio Link KML: {fn}")
            QMessageBox.information(parent, "KML Exported", f"Successfully exported Radio Link KML to:\n{fn}")
        return fn
    except Exception as exc:
        logger.warning("Export link KML failed: %s", exc, exc_info=True)
        if status_callback:
            status_callback(f"Export error: {exc}")
        QMessageBox.critical(parent, "Export Error", f"Failed to export Radio Link:\n{exc}")
        return None


def export_link_kmz(
    parent: QWidget,
    result: Optional[dict],
    params: Optional[dict],
    status_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Export radio link data as KMZ (Google Earth format)."""
    result = result or {}
    link = result.get("link")
    if not link:
        QMessageBox.warning(parent, "No Link Data", "No Radio Link data available to export.")
        return None

    p = result.get("params") or params or {}
    tx_name = str(p.get("tx_site_name") or p.get("tx_name") or "Base")
    rx_name = str(p.get("rx_site_name") or p.get("rx_name") or "Mobile")
    default_fn = f"{tx_name}_{rx_name}_link.kmz".replace(" ", "_")

    fn, _ = QFileDialog.getSaveFileName(
        parent,
        "Export Radio Link (Google Earth)",
        default_fn,
        "KMZ Files (*.kmz);;KML Files (*.kml);;All Files (*)",
    )
    if not fn:
        return None

    try:
        if fn.lower().endswith(".kml"):
            export_radio_link_kml(fn, p, link, num_points=501, copy_icon=True)
            if status_callback:
                status_callback(f"Exported Radio Link KML: {fn}")
            QMessageBox.information(parent, "KML Exported", f"Successfully exported Radio Link KML to:\n{fn}")
        else:
            if not fn.lower().endswith(".kmz"):
                fn += ".kmz"
            export_radio_link_kmz(fn, p, link, num_points=501)
            if status_callback:
                status_callback(f"Exported Radio Link KMZ: {fn}")
            QMessageBox.information(parent, "KMZ Exported", f"Successfully exported Radio Link KMZ to:\n{fn}")
        return fn
    except Exception as exc:
        logger.warning("Export link KMZ failed: %s", exc, exc_info=True)
        if status_callback:
            status_callback(f"Export error: {exc}")
        QMessageBox.critical(parent, "Export Error", f"Failed to export Radio Link:\n{exc}")
        return None


def export_coverage_kmz(
    parent: QWidget,
    result: dict,
    png: str,
    bbox: Any,
    path: str,
    base: str,
    color_file: Optional[str] = None,
    relief_weight: float = 0.30,
) -> None:
    """Build a KMZ (zipped KML GroundOverlay + PNG image)."""
    try:
        output_stage.export_kmz(
            path,
            png,
            bbox,
            base,
            result=result,
            flat=(relief_weight < 1.0),
            color_file=color_file,
            opacity=0.75,
            relief_weight=relief_weight,
        )
    except Exception as exc:
        logger.warning("Export KMZ failed: %s", exc, exc_info=True)
        QMessageBox.warning(parent, "Export KMZ", f"Gagal mengekspor KMZ:\n{exc}")


def export_coverage_rm_png(
    parent: QWidget,
    result: dict,
    params: dict,
    base: str,
    status_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Export a full Radio Mobile-style picture + automatic KML sidecar."""
    bbox = result.get("bbox")
    if bbox is None:
        QMessageBox.warning(parent, "Export", "No bounding box available for RM-style PNG.")
        return None
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export PNG (RM-style)", base + "_rm.png", "PNG (*.png)"
    )
    if not path:
        return None
    from . import rm_style

    p = params or {}
    try:
        rm_style.render_for_run(path, bbox, p, coverage_png=result["png"])
    except Exception as exc:
        logger.warning("Render RM-style failed: %s", exc, exc_info=True)
        QMessageBox.warning(parent, "Export", f"Render RM-style gagal:\n{exc}")
        return None
    sidecar = os.path.splitext(path)[0] + ".kml"
    with open(sidecar, "w", encoding="utf-8") as fh:
        fh.write(output_stage.build_kml(os.path.basename(path), bbox, base))
    if status_callback:
        status_callback(f"Exported PNG (RM-style): {path} (+ {os.path.basename(sidecar)})")
    return path


def export_raster_txt(
    result: dict,
    params: dict,
    path: str,
    cache_dir: str,
) -> None:
    """Wrap the engine's raw raster dump in a Radio-Mobile-compatible file."""
    from . import dem_convert as dc

    p = params or {}

    def _f(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    tx_name = p.get("tx_name") or "Tx"
    rx_name = p.get("rx_name") or "Rx"
    rx_lat = p.get("rx_lat")
    rx_lon = p.get("rx_lon")

    demnas_folder = None
    if p.get("dem_source") == "offline":
        folder = p.get("demnas_dir")
        if folder and os.path.isdir(folder):
            demnas_folder = folder

    def amsl(lat, lon, agl):
        elev = dc.ground_elevation(
            _f(lat), _f(lon),
            demnas_folder=demnas_folder, cache_dir=cache_dir,
        )
        return _f(agl) + (elev if elev is not None else 0.0)

    thr = _f(p.get("rx_threshold_dbm"), -100)
    rm_import.write_rm_export(
        path,
        result["raster_txt"],
        threshold_dbm=thr,
        tx_name=tx_name,
        tx_lat=_f(p.get("tx_lat")),
        tx_lon=_f(p.get("tx_lon")),
        tx_amsl=amsl(p.get("tx_lat"), p.get("tx_lon"), p.get("tx_height")),
        rx_name=rx_name,
        rx_lat=_f(rx_lat),
        rx_lon=_f(rx_lon),
        rx_amsl=amsl(rx_lat, rx_lon, p.get("rx_height")),
    )


def export_dem_tif(
    parent: QWidget,
    params: dict,
    cache_dir: str,
    status_callback: Optional[Callable[[str], None]] = None,
    terminal: Optional[Any] = None,
) -> Optional[str]:
    """Export DEM clip for QGIS + validate ground elevation at Tx."""
    folder = params.get("demnas_dir")
    if not folder or not os.path.isdir(folder):
        QMessageBox.warning(parent, "Export DEM", "Pilih folder DEMNAS (.tif) dulu.")
        return None
    tx_lat, tx_lon = params.get("tx_lat"), params.get("tx_lon")
    if tx_lat is None or tx_lon is None:
        QMessageBox.warning(parent, "Export DEM", "Koordinat Tx belum valid.")
        return None
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export DEM .tif (QGIS)", "dem_clip.tif", "GeoTIFF (*.tif)"
    )
    if not path:
        return None
    try:
        from . import dem_convert as dc
        vrt = dc._demnas_vrt(folder, cache_dir)
        dc._assert_covers(vrt, float(tx_lat), float(tx_lon))
        elev = dc._sample_elevation(vrt, float(tx_lat), float(tx_lon))
        radius_km = float(params.get("radius", 2) or 2)
        lat_deg = min(0.05, radius_km / 111.0)
        lon_deg = radius_km / (111.32 * max(0.01, math.cos(math.radians(float(tx_lat)))))
        cmd = [
            "gdalwarp", "-t_srs", "EPSG:4326",
            "-te", str(float(tx_lon) - lon_deg), str(float(tx_lat) - lat_deg),
            str(float(tx_lon) + lon_deg), str(float(tx_lat) + lat_deg),
            "-tr", "0.00027", "0.00027", "-r", "bilinear", vrt, path,
        ]
        subprocess.run(cmd, check=True)
        msg = f"DEM diekspor ke {path}\nElevasi Tx: {elev} m"
        if elev is None or elev == 0:
            msg += "\n⚠️ LUBANG HITAM: elev 0/void di Tx → 100% masalah preprocessing! Cek QGIS."
            if terminal:
                terminal.appendPlainText(f"[DEM] Tx void/0 di ({tx_lat},{tx_lon}) → {path}")
        else:
            msg += "\n✅ Tidak ada lubang di Tx → cek engine step/azimuth."
        QMessageBox.information(parent, "Export DEM", msg)
        if status_callback:
            status_callback(f"DEM exported: {path}")
        return path
    except Exception as exc:
        logger.warning("Export DEM failed: %s", exc, exc_info=True)
        QMessageBox.warning(parent, "Export DEM", f"Gagal: {exc}")
        return None


def export_model(
    parent: QWidget,
    fmt: str,
    result: Optional[dict],
    params: Optional[dict],
    cache_dir: str,
    color_file: Optional[str] = None,
    contour_mode_idx: int = 0,
    status_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Dispatch export operation based on format string."""
    fmt = (fmt or "").strip()

    if result and result.get("link") and (not result.get("png") or fmt in ("KML", "KMZ")):
        if fmt == "KML":
            export_link_kml(parent, result, params, status_callback)
        else:
            export_link_kmz(parent, result, params, status_callback)
        return

    if not result or not result.get("png") or not os.path.exists(result["png"]):
        QMessageBox.warning(parent, "Export", "Run a propagation calculation first.")
        return
    png = result["png"]
    bbox = result.get("bbox")
    base = os.path.splitext(os.path.basename(png))[0]

    if fmt in ("KMZ", "KMZ (3D)"):
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export KMZ", base + ".kmz", "KMZ (*.kmz)"
        )
        if not path:
            return
        if fmt == "KMZ (3D)":
            relief_weight = 1.0
        elif contour_mode_idx == 1:
            relief_weight = 0.0  # Flat murni
        elif contour_mode_idx == 2:
            relief_weight = 1.0  # Kontur tebal
        else:
            relief_weight = 0.30  # Kontur halus

        export_coverage_kmz(
            parent, result, png, bbox, path, base,
            color_file=color_file, relief_weight=relief_weight,
        )
        if status_callback:
            status_callback(f"Exported {fmt}: {path}")
    elif fmt == "KML":
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export KML", base + ".kml", "KML (*.kml)"
        )
        if not path:
            return
        out_dir = os.path.dirname(path)
        kml_png_name = base + "_cov.png"
        kml_png_path = os.path.join(out_dir, kml_png_name)
        relief_weight = 0.0 if contour_mode_idx == 1 else (1.0 if contour_mode_idx == 2 else 0.30)

        if relief_weight < 1.0:
            output_stage.make_flat_transparent_png(
                png, kml_png_path, color_file=color_file, opacity=0.75,
                relief_weight=relief_weight,
            )
        else:
            shutil.copyfile(png, kml_png_path)

        kml_text = output_stage.build_kml(kml_png_name, bbox, base, opacity=0.75)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(kml_text)
        if status_callback:
            status_callback(f"Exported KML: {path}")
    elif fmt == "TXT (Raster)":
        raster = result.get("raster_txt")
        if not raster or not os.path.exists(raster):
            QMessageBox.warning(
                parent, "Export",
                "Raster TXT tidak tersedia. Aktifkan 'Save raster data "
                "(TXT)' di bagian Output lalu jalankan ulang propagasi."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export Raster TXT", base + "_raster.txt", "TXT (*.txt)"
        )
        if not path:
            return
        export_raster_txt(result, params or {}, path, cache_dir)
        if status_callback:
            status_callback(f"Exported TXT: {path}")
    elif fmt == "PNG":
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export PNG", base + ".png", "PNG (*.png)"
        )
        if not path:
            return
        shutil.copyfile(png, path)
        if status_callback:
            status_callback(f"Exported PNG: {path}")
    elif fmt == "PNG (RM-style)":
        export_coverage_rm_png(parent, result, params or {}, base, status_callback)
    else:
        QMessageBox.information(
            parent, "Export",
            f"'{fmt}' export is not available from the current engine output.\n"
            "Use KMZ or PNG."
        )
