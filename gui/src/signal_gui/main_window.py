"""Main application window: sidebar form + map + terminal + controls matching CloudRF UI."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QProgressBar, QLabel, QFileDialog, QInputDialog, QMessageBox,
    QScrollArea, QApplication, QFrame
)
from PySide6.QtCore import Qt

from . import backend, params as params_mod
from .widgets import ParameterForm
from .map_view import MapView
from .header import CloudRFHeader


class MainWindow(QMainWindow):
    def __init__(self, root: str = ""):
        super().__init__()
        self.setWindowTitle("RF Propagation / Signal-Server GUI")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(int(avail.width() * 0.95), int(avail.height() * 0.92))
        else:
            self.resize(1280, 800)
        self.setMinimumSize(950, 650)
        self.root = root or self._detect_root()
        self.engines = backend.find_engines(self.root)
        self.cache_dir = os.path.join(self.root, "gui", "cache", "dem")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._pending = None
        self._worker = None
        self._last_result = None
        self._build_ui()
        self._apply_global_theme()

    def _detect_root(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(os.path.dirname(os.path.dirname(here)))

    def _apply_global_theme(self):
        """Apply sleek dark theme matching CloudRF."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121417;
            }
            QSplitter::handle {
                background-color: #1B1E22;
                width: 3px;
            }
            QScrollBar:vertical {
                background: #121417;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #2D3748;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4A5568;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        ss_dir = os.path.join(self.root, "Signal-Server") if self.root else ""

        # Top Header Bar
        self.header = CloudRFHeader(self)
        self.header.section_clicked.connect(self._on_header_section_clicked)

        # Main Central Container
        central_w = QWidget()
        central_layout = QVBoxLayout(central_w)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.header)

        # Left Sidebar (Scrollable ParameterForm + Embedded Log Terminal)
        self.form = ParameterForm(signal_server_root=ss_dir, parent=self)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(self.form)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1B1E22; }")

        # Terminal Log widget inside Left Sidebar Bottom (matching CloudRF UI screenshot!)
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumHeight(140)
        self.terminal.setStyleSheet("""
            QPlainTextEdit {
                background-color: #121417;
                color: #CBD5E0;
                border: 1px solid #23272B;
                border-radius: 4px;
                font-family: Consolas, Monaco, monospace;
                font-size: 10px;
                padding: 6px;
            }
        """)
        sidebar_container = QWidget()
        sidebar_container.setStyleSheet("background-color: #1B1E22;")
        sb_layout = QVBoxLayout(sidebar_container)
        sb_layout.setContentsMargins(4, 4, 4, 4)
        sb_layout.setSpacing(4)
        sb_layout.addWidget(left_scroll, 1)
        sb_layout.addWidget(self.terminal)

        # Right Area (Full Map View)
        self.map = MapView(self)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("QProgressBar { background: #1A202C; border: none; } QProgressBar::chunk { background: #3182CE; }")
        self.progress.setVisible(False)
        self.status = QLabel("Ready")
        self.status.setStyleSheet("color: #A0AEC0; font-size: 10px; padding: 2px 8px; background: #121417;")

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.map, 1)
        rl.addWidget(self.status)

        # Horizontal Splitter between Left Sidebar & Right Map
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(sidebar_container)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        central_layout.addWidget(split, 1)

        self.setCentralWidget(central_w)

        # Wire up Form and Map Signals
        self.form.start_requested.connect(self.start)
        self.form.pick_requested.connect(self.map.arm)
        self.form.export_requested.connect(self.export_model)
        self.map.picked.connect(self._on_picked)
        self.form.tx_changed.connect(self._on_tx_coord_changed)
        self.form.rx_changed.connect(self._on_rx_coord_changed)

        # Place initial Tx/Rx markers from the default form values.
        self._on_tx_coord_changed()
        self._on_rx_coord_changed()

    def _on_header_section_clicked(self, key: str):
        if key == "clear":
            self.clear_propagation()
        else:
            self.form.toggle_section(key)


    def _dem_spec(self, p: dict) -> dict | None:
        if p.get("terrain_source") == "lidar" or p.get("sdf_dir"):
            return None
        res = int(p.get("dem_resolution", 3))
        if res == 15:
            raise RuntimeError(
                "15\" TIF DEM requires GDAL conversion (not yet supported). "
                "Choose 90 m or 30 m for automatic download."
            )
        if p.get("engine") == "HD" and res != 1:
            res = 1
        tx_lat, tx_lon = p["tx_lat"], p["tx_lon"]
        radius_km = float(p.get("radius", 30))
        lat_deg = radius_km / 111.0
        lon_deg = radius_km / (111.32 * max(0.01, math.cos(math.radians(tx_lat))))
        return {
            "auto": True,
            "lat_lo": tx_lat - lat_deg, "lat_hi": tx_lat + lat_deg,
            "lon_lo": tx_lon - lon_deg, "lon_hi": tx_lon + lon_deg,
            "resolution": res, "cache_dir": self.cache_dir,
        }

    def start(self) -> None:
        try:
            p = self.form.collect()
        except Exception as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        pm = int(p.get("model_pm", 3))
        if p.get("engine") == "HD" and int(p.get("dem_resolution", 3)) != 1:
            self.status.setText("HD engine requires 30 m DEM; using 30 m.")
        self._run_with(p, self._dem_spec(p))

    def _run_with(self, p: dict, dem_spec: dict | None) -> None:
        engine_key = params_mod.ENGINES[p["engine"]]
        engine_exe = self.engines.get(engine_key)
        if not engine_exe or not os.path.exists(engine_exe):
            QMessageBox.critical(self, "Engine missing",
                                 f"Engine binary not found: {engine_key}\n"
                                 f"(looked via backend.find_engines at {self.root})")
            return
        sdf_exe = self.engines.get("srtm2sdf-hd" if p["engine"] == "HD" else "srtm2sdf")

        run_dir = tempfile.mkdtemp(prefix="siggui_", dir=self.cache_dir)
        out_base = os.path.join(run_dir, "coverage")

        self._pending = (p, dem_spec, out_base, engine_exe, sdf_exe)
        self._launch()

    def _launch(self) -> None:
        p, dem_spec, out_base, engine_exe, sdf_exe = self._pending
        self._worker = backend.RunWorker(
            engine_exe, out_base, p, dem_spec=dem_spec, srtm2sdf_exe=sdf_exe
        )
        self._worker.output_line.connect(self.terminal.appendPlainText)
        self._worker.progress.connect(self.status.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.need_tile_code.connect(self._on_need_tile)
        self._worker.start()
        self.progress.setVisible(True)
        self.form.btn_run.setEnabled(False)
        self.status.setText("Running calculation engine...")

    def _on_finished(self, ok: bool, stdout: str, result: dict) -> None:
        self.progress.setVisible(False)
        self.form.btn_run.setEnabled(True)
        if ok and result.get("bbox"):
            self.map.show_coverage(result["png"], result["bbox"])
            self._last_result = result
            self.status.setText("Done. Coverage shown on map.")
            if result.get("kml"):
                self.status.setText(f"Done. KML: {result['kml']}")
        else:
            self._last_result = None
            self.status.setText("Finished with no coverage.")

    def _on_error(self, msg: str) -> None:
        self.progress.setVisible(False)
        self.form.btn_run.setEnabled(True)
        self.terminal.appendPlainText(f"ERROR: {msg}")
        self.status.setText("Error")

    def _on_need_tile(self, lat: float, lon: float, res: int) -> None:
        code, ok = QInputDialog.getText(
            self, "DEM tile code required",
            f"Automatic DEM resolution failed for ({lat:.4f}, {lon:.4f}).\n"
            f"Enter the Viewfinder Panoramas tile code (e.g. B48 for dem{res}), "
            f"or open https://viewfinderpanoramas.org to find it:",
        )
        if not ok or not code.strip():
            self._on_error("DEM download cancelled (no tile code).")
            return
        p, _dem, out_base, engine_exe, sdf_exe = self._pending
        dem_spec = {"tile_code": code.strip(), "resolution": res,
                    "cache_dir": self.cache_dir}
        self._pending = (p, dem_spec, out_base, engine_exe, sdf_exe)
        self._launch()

    def _on_picked(self, role: str, lat: float, lon: float) -> None:
        if role == "tx":
            self.form.tx_coord.set(lat, lon)
            self.map.set_tx(lat, lon)
        elif role == "rx":
            self.form.rx_coord.set(lat, lon)
            self.map.set_rx(lat, lon)
        else:
            return
        self.status.setText(f"{role.upper()} set: {lat:.5f}, {lon:.5f}")

    def _on_tx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.tx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_tx(lat, lon)
        self.status.setText(f"Tx set: {lat:.5f}, {lon:.5f}")

    def _on_rx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.rx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_rx(lat, lon)

    def stop(self) -> None:
        if self._worker:
            self._worker.terminate()
            self._worker.wait()
        self.progress.setVisible(False)
        self.form.btn_run.setEnabled(True)
        self.status.setText("Stopped")

    def clear_propagation(self) -> None:
        """Clear computed propagation data: coverage overlay, log, and status."""
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        self.map.clear_coverage()
        self.terminal.clear()
        self.progress.setVisible(False)
        self.form.btn_run.setEnabled(True)
        self.status.setText("Ready")

    # ------------------------------------------------------------------ export
    def export_model(self, fmt: str) -> None:
        """Export the last propagation result in the chosen format."""
        result = getattr(self, "_last_result", None)
        if not result or not result.get("png") or not os.path.exists(result["png"]):
            QMessageBox.warning(self, "Export", "Run a propagation calculation first.")
            return

        fmt = (fmt or "").strip()
        png = result["png"]
        bbox = result.get("bbox")
        base = os.path.splitext(os.path.basename(png))[0]

        if fmt in ("KMZ", "KMZ (3D)"):
            path, _ = QFileDialog.getSaveFileName(
                self, "Export KMZ", base + ".kmz", "KMZ (*.kmz)")
            if not path:
                return
            self._export_kmz(result, png, bbox, path)
        elif fmt == "PNG":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PNG", base + ".png", "PNG (*.png)")
            if not path:
                return
            shutil.copyfile(png, path)
            self.status.setText(f"Exported PNG: {path}")
        else:
            QMessageBox.information(
                self, "Export",
                f"'{fmt}' export is not available from the current engine output.\n"
                "Use KMZ or PNG.")
            return
        if fmt in ("KMZ", "KMZ (3D)"):
            self.status.setText(f"Exported {fmt}: {path}")

    def _export_kmz(self, result: dict, png: str, bbox, path: str) -> None:
        """Build a KMZ (zipped KML GroundOverlay + PNG image)."""
        import zipfile

        from . import output_stage

        kml_path = result.get("kml")
        png_name = os.path.basename(png)
        if kml_path and os.path.exists(kml_path):
            with open(kml_path, "r", encoding="utf-8") as fh:
                kml_text = fh.read()
        elif bbox is not None:
            kml_text = output_stage.build_kml(png_name, bbox, base)
        else:
            QMessageBox.warning(self, "Export", "No bounding box available for KML.")
            return

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(png, arcname=png_name)
            z.writestr("doc.kml", kml_text)


