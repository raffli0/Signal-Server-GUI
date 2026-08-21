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
from PySide6.QtCore import Qt, QTimer, QObject, QEvent

from . import backend, params as params_mod
from .widgets import ParameterForm


def _dir_size(path: str) -> int:
    """Return total size in bytes of everything under ``path``."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total



def _human_size(num: int) -> str:
    """Format a byte count into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.0f} B"


def _cache_size(cache_dir: str) -> int:
    """Return total size in bytes of all entries under ``cache_dir``."""
    if not os.path.isdir(cache_dir):
        return 0
    total = 0
    for entry in os.scandir(cache_dir):
        try:
            if entry.is_dir(follow_symlinks=False):
                total += _dir_size(entry.path)
            elif entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


class _MouseWheelGuard(QObject):
    """Ignore mouse-wheel events unless the pointer is actually over the widget.

    Stops touchpad scroll/pinch gestures aimed at the map (or anywhere else)
    from accidentally scrolling or zooming sibling widgets such as the
    parameter panel or the terminal log.
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and not obj.underMouse():
            event.ignore()
            return True
        return False
from .map_view import MapView
from .profile_view import ProfileView
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
        self._pick_no_fly = False
        self._build_ui()
        self._apply_global_theme()

    def _detect_root(self) -> str:
        from ._bundle import app_root
        return app_root()

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
        _wheel_guard = _MouseWheelGuard(self)
        left_scroll.viewport().installEventFilter(_wheel_guard)

        # Terminal Log widget inside Left Sidebar Bottom (matching CloudRF UI screenshot!)
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumHeight(140)
        self.terminal.installEventFilter(_wheel_guard)
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

        # Radio Link result panel (hidden until a link is computed)
        self.link_panel = QWidget()
        self.link_panel.setStyleSheet("background:#0f1115; border-top:1px solid #23272e;")
        self.link_panel.setFixedHeight(330)
        lp = QVBoxLayout(self.link_panel)
        lp.setContentsMargins(8, 6, 8, 6)
        lp.setSpacing(4)
        self.link_summary = QLabel("")
        self.link_summary.setStyleSheet("color:#cbd5e0; font-size:11px;")
        self.link_summary.setWordWrap(True)
        lp.addWidget(self.link_summary)
        self.profile_view = ProfileView(self)
        lp.addWidget(self.profile_view, 1)
        self.link_details_btn = QPushButton("Details")
        self.link_details_btn.setCheckable(True)
        self.link_details_btn.setStyleSheet(
            "QPushButton{background:#2D3748;color:#E2E8F0;border:1px solid #3F474F;"
            "border-radius:3px;padding:3px 8px;font-size:10px;} "
            "QPushButton:checked{background:#4A5568;}")
        self.link_report = QPlainTextEdit()
        self.link_report.setReadOnly(True)
        self.link_report.setVisible(False)
        self.link_report.setStyleSheet(
            "background:#0b0d10; color:#9fb3c8; font-family:monospace; "
            "font-size:10px; border:1px solid #23272e;")
        self.link_details_btn.toggled.connect(
            lambda v: self.link_report.setVisible(v))
        lp.addWidget(self.link_details_btn)
        lp.addWidget(self.link_report)
        self.link_panel.setVisible(False)
        rl.addWidget(self.link_panel)

        rl.addWidget(self.status)

        # Horizontal Splitter between Left Sidebar & Right Map
        self._sidebar = sidebar_container
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(sidebar_container)
        split.addWidget(right)
        # Keep the sidebar clearly narrower than the map viewport by default;
        # its max width is recomputed responsively in _apply_responsive_width().
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        split.splitterMoved.connect(self._on_splitter_moved)
        central_layout.addWidget(split, 1)
        self._splitter = split

        # Debounced map re-layout after container resizes.
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self.map.invalidate_size)

        # Apply an initial responsive sidebar width.
        self._apply_responsive_width()

        self.setCentralWidget(central_w)

        # Wire up Form and Map Signals
        self.form.start_requested.connect(self.start)
        self.form.pick_requested.connect(self.map.arm)
        self.form.export_requested.connect(self.export_model)
        self.header.save_profile_requested.connect(self.save_profile)
        self.header.load_profile_requested.connect(self.load_profile)
        self.header.radio_link_requested.connect(lambda: self.start(link=True))
        self.header.clear_cache_requested.connect(self.clear_cache)
        self.map.picked.connect(self._on_picked)
        self.form.tx_changed.connect(self._on_tx_coord_changed)
        self.form.rx_changed.connect(self._on_rx_coord_changed)
        self.form.tx_name.textChanged.connect(
            lambda: self.map.set_site_labels(tx=self.form.tx_name.text().strip() or None))
        self.form.rx_name.textChanged.connect(
            lambda: self.map.set_site_labels(rx=self.form.rx_name.text().strip() or None))
        self.form.demnas_dir_picked.connect(self._update_demnas_live)
        self.form.demnas_live.toggled.connect(self._update_demnas_live)
        # Default DEMNAS folder (always wins on startup): first subdir of
        # <root>/gui/data named "demnas" in any letter case, else create one.
        self.demnas_default_dir = self._find_demnas_default()
        self.form.demnas_dir.setText(self.demnas_default_dir)
        self._update_demnas_live()

        # Place initial Tx/Rx markers from the default form values.
        self._on_tx_coord_changed()
        self._on_rx_coord_changed()
        # Open the map centered on the transmitter by default (not Rx).
        self.map._focus = self.map.tx_pos

    def _find_demnas_default(self) -> str:
        """Return the default DEMNAS folder: ``<root>/gui/data/<name>`` where
        ``<name>`` matches "demnas" case-insensitively; created if missing."""
        base = os.path.join(self.root, "gui", "data")
        os.makedirs(base, exist_ok=True)
        try:
            for entry in os.scandir(base):
                if entry.is_dir() and entry.name.lower() == "demnas":
                    return entry.path
        except OSError:
            pass
        fallback = os.path.join(base, "Demnas")
        os.makedirs(fallback, exist_ok=True)
        return fallback

    # ------------------------------------------------------------------ DEMNAS config
    def _update_demnas_live(self) -> None:
        """Live (toggleable) coverage indicator for the selected DEMNAS folder."""
        form = self.form
        if form.dem_source.currentIndex() != 1:
            form.set_demnas_status("idle", "DEMNAS: online aktif")
            return
        if not form.demnas_live.isChecked():
            form.set_demnas_status("idle", "DEMNAS: live check OFF")
            return
        folder = form.demnas_dir.text().strip()
        if not folder or not os.path.isdir(folder):
            form.set_demnas_status("idle", "DEMNAS: pilih folder")
            return
        tx = form.tx_coord.get()
        if not tx:
            form.set_demnas_status("idle", "DEMNAS: tunggu koordinat Tx")
            return
        try:
            from . import dem_convert as dc
            vrt = dc._demnas_vrt(folder, self.cache_dir)
            lat, lon = tx
            dc._assert_covers(vrt, lat, lon)
            elev = dc._sample_elevation(vrt, lat, lon)
            if elev is None:
                form.set_demnas_status(
                    "bad", f"DEMNAS: ✗ void di Tx ({lat:.3f}, {lon:.3f})"
                )
            else:
                form.set_demnas_status(
                    "ok", f"DEMNAS: ✓ Tx ({lat:.3f}, {lon:.3f}) elev {elev:.0f} m"
                )
        except Exception as exc:  # noqa: BLE001 - surface any gdal/IO issue as red
            form.set_demnas_status("bad", f"DEMNAS: ✗ {exc}")

    def _on_header_section_clicked(self, key: str):
        if key == "clear":
            self.clear_propagation()
        else:
            self.form.toggle_section(key)

    # ------------------------------------------------------------------ responsive
    def _apply_responsive_width(self) -> None:
        """Clamp the sidebar width to a fraction of the window on any size.

        The sidebar stays clearly narrower than the map but never so small that
        the form inputs overflow. The user can still drag the splitter.
        """
        w = self.width()
        side_max = max(240, min(380, int(w * 0.32)))
        self._sidebar.setMaximumWidth(side_max)
        # Keep the map comfortably larger than the sidebar on small screens.
        if w < 720:
            self._sidebar.setMaximumWidth(max(200, int(w * 0.45)))

    def _on_splitter_moved(self, *_args) -> None:
        # Re-layout Leaflet after the container size changes (no window resize).
        self._resize_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_width()
        self._resize_timer.start()


    def _link_bounds(self, p: dict):
        """Union bounding box (with margin) covering both Tx and Rx."""
        tx_lat, tx_lon = p["tx_lat"], p["tx_lon"]
        rx_lat, rx_lon = p["rx_lat"], p["rx_lon"]
        margin = 0.05
        return (
            min(tx_lat, rx_lat) - margin, max(tx_lat, rx_lat) + margin,
            min(tx_lon, rx_lon) - margin, max(tx_lon, rx_lon) + margin,
        )

    @staticmethod
    def _link_distance_km(p: dict) -> float:
        from math import (
            radians, sin, cos, asin, sqrt,
        )
        lat1, lon1 = radians(p["tx_lat"]), radians(p["tx_lon"])
        lat2, lon2 = radians(p["rx_lat"]), radians(p["rx_lon"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 6371.0 * 2 * asin(sqrt(a))

    def _dem_spec(self, p: dict) -> dict | None:
        # ---- Offline: local DEMNAS folder (no network) ----
        if p.get("dem_source") == "offline":
            folder = p.get("demnas_dir")
            if not folder or not os.path.isdir(folder):
                raise RuntimeError(
                    "Mode Offline membutuhkan folder DEMNAS (.tif). "
                    "Pilih folder di baris 'DEMNAS folder' (bagian Output)."
                )
            res = int(p.get("dem_resolution", 3))
            if res == 15:
                res = 3  # DEMNAS resolution is intrinsic; ignore Viewfinder setting
            engine = p.get("engine", "Standard")
            tx_lat, tx_lon = p["tx_lat"], p["tx_lon"]
            if p.get("path_profile"):
                lat_lo, lat_hi, lon_lo, lon_hi = self._link_bounds(p)
            else:
                radius_km = float(p.get("radius", 30))
                lat_deg = radius_km / 111.0
                lon_deg = radius_km / (111.32 * max(0.01, math.cos(math.radians(tx_lat))))
                lat_lo, lat_hi = tx_lat - lat_deg, tx_lat + lat_deg
                lon_lo, lon_hi = tx_lon - lon_deg, tx_lon + lon_deg
            mode = "demnas_lidar" if engine == "LIDAR" else "demnas_sdf"
            return {
                "mode": mode,
                "folder": folder,
                "engine": engine,
                "ppd": int(p.get("resolution", 1200)),
                "lat_lo": lat_lo, "lat_hi": lat_hi,
                "lon_lo": lon_lo, "lon_hi": lon_hi,
                "resolution": res, "cache_dir": self.cache_dir,
            }
        # ---- Online: Viewfinder SRTM (automatic download) ----
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
        if p.get("path_profile"):
            lat_lo, lat_hi, lon_lo, lon_hi = self._link_bounds(p)
        else:
            radius_km = float(p.get("radius", 30))
            lat_deg = radius_km / 111.0
            lon_deg = radius_km / (111.32 * max(0.01, math.cos(math.radians(tx_lat))))
            lat_lo, lat_hi = tx_lat - lat_deg, tx_lat + lat_deg
            lon_lo, lon_hi = tx_lon - lon_deg, tx_lon + lon_deg
        return {
            "auto": True,
            "lat_lo": lat_lo, "lat_hi": lat_hi,
            "lon_lo": lon_lo, "lon_hi": lon_hi,
            "resolution": res, "cache_dir": self.cache_dir,
        }

    def start(self, link: bool = False) -> None:
        try:
            p = self.form.collect()
        except Exception as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        if link:
            p["path_profile"] = True
        if p.get("path_profile"):
            if p.get("rx_lat") is None or p.get("rx_lon") is None:
                QMessageBox.warning(
                    self, "Input error",
                    "Radio Link mode requires a Receiver location. "
                    "Set Rx lat/lon in the Receiver section."
                )
                return
            # Ensure the engine's tile-loading radius covers the whole path.
            need = math.ceil(self._link_distance_km(p)) + 5
            if float(p.get("radius", 30)) < need:
                p["radius"] = need
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

        # A new run invalidates the previous run's saved-Tx indicator.
        self.map.clear_tx_saved()

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
        if ok and result.get("link"):
            p = self._pending[0] if self._pending else {}
            tx = (float(p.get("tx_lat")), float(p.get("tx_lon")))
            rx = (float(p.get("rx_lat")), float(p.get("rx_lon")))
            self.map.mark_tx_saved(*tx)
            self._show_link_panel(result["link"], tx, rx)
            return
        # Area coverage (clear any previous link result)
        self.map.clear_link()
        self.link_panel.setVisible(False)
        if ok and result.get("bbox"):
            self.map.show_coverage(result["png"], result["bbox"], self.form.color_path.text())
            p = self._pending[0] if self._pending else {}
            if p.get("tx_lat") is not None and p.get("tx_lon") is not None:
                self.map.mark_tx_saved(float(p["tx_lat"]), float(p["tx_lon"]))
            self._last_result = result
            self.status.setText("Done. Coverage shown on map.")
            if result.get("kml"):
                self.status.setText(f"Done. KML: {result['kml']}")
        else:
            self._last_result = None
            self.status.setText("Finished with no coverage.")

    def _show_link_panel(self, link: dict, tx: tuple, rx: tuple) -> None:
        self.link_panel.setVisible(True)
        self.map.draw_link(tx[0], tx[1], rx[0], rx[1])
        self._last_result = {"link": link}
        self.status.setText("Done. Radio link computed.")

        def _fmt(v, unit="", nd=2):
            if v is None:
                return "&mdash;"
            return f"{v:.{nd}f} {unit}"

        obs = link.get("obstructed", False)
        obs_html = ('<span style="color:#fc8181;font-weight:700;">OBSTRUCTED</span>'
                    if obs else
                    '<span style="color:#68d391;font-weight:700;">CLEAR</span>')
        fm = link.get("fade_margin_db")
        fm_html = _fmt(fm, "dB")
        if fm is not None:
            fm_html += ' <span style="color:%s;">(%s)</span>' % (
                "#68d391" if fm >= 0 else "#fc8181",
                "OK" if fm >= 0 else "FAIL",
            )
        rows = [
            ("Distance", _fmt(link.get("distance_km"), "km")),
            ("Azimuth", _fmt(link.get("azimuth_deg"), "&deg;")),
            ("Model", (link.get("model") or "&mdash;")),
            ("Free-space loss", _fmt(link.get("free_space_loss_db"), "dB")),
            ("Computed loss", _fmt(link.get("computed_loss_db"), "dB")),
            ("Terrain shielding", _fmt(link.get("terrain_shielding_db"), "dB")),
            ("Total loss", _fmt(link.get("total_loss_db"), "dB")),
            ("Rx power", _fmt(link.get("rx_power_dbm"), "dBm")),
            ("Fade margin", fm_html),
            ("Path", obs_html),
        ]
        self.link_summary.setText(
            "&nbsp;&nbsp;".join(f"<b>{k}:</b> {v}" for k, v in rows))
        self.profile_view.set_profile(link.get("profile"), obs)
        self.link_report.setPlainText(link.get("report_text", ""))

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
        # Picking on the map must not move/zoom the view: the clicked point is
        # already visible. The guard makes the tx_changed/rx_changed handlers
        # update markers without flyToSite (form coordinate sets emit synchronously).
        self._pick_no_fly = True
        try:
            if role == "tx":
                self.form.tx_coord.set(lat, lon)
            elif role == "rx":
                self.form.rx_coord.set(lat, lon)
            else:
                return
        finally:
            self._pick_no_fly = False
        self.status.setText(f"{role.upper()} set: {lat:.5f}, {lon:.5f}")

    def _on_tx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.tx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_tx(lat, lon, fly=not self._pick_no_fly)
        self.status.setText(f"Tx set: {lat:.5f}, {lon:.5f}")
        self._update_demnas_live()

    def _on_rx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.rx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_rx(lat, lon, fly=not self._pick_no_fly)

    # ------------------------------------------------------------------ profile
    def save_profile(self) -> None:
        """Serialize the current form + map view into a JSON profile file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "profile.json", "JSON (*.json)")
        if not path:
            return
        form = self.form.collect()

        def _write(map_state):
            profile = {"version": 1, "form": form, "map": map_state or {}}
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(profile, fh, indent=2)
            except OSError as exc:
                QMessageBox.warning(self, "Save Profile", f"Could not write file:\n{exc}")
                return
            self.status.setText(f"Profile saved: {os.path.basename(path)}")

        self.map.get_state(_write)

    def load_profile(self) -> None:
        """Restore form + map view state from a JSON profile file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                profile = json.load(fh)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Load Profile", f"Could not read profile:\n{exc}")
            return

        form = profile.get("form")
        if isinstance(form, dict):
            self.form.load(form)
            # Refresh map markers from the restored coordinates.
            self._on_tx_coord_changed()
            self._on_rx_coord_changed()
        self.map.apply_state(profile.get("map") or {})
        self.status.setText(f"Profile loaded: {os.path.basename(path)}")

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

    def clear_cache(self) -> None:
        """Delete all on-disk cache (downloaded DEM/SDF tiles, DEMNAS data, and
        temporary run directories) to free disk space.

        Only the *contents* of ``self.cache_dir`` (``.../gui/cache/dem``) are
        removed; the directory itself is recreated so the app keeps working.
        """
        if self._worker and self._worker.isRunning():
            QMessageBox.information(
                self, "Cache sibuk",
                "Sedang memproses simulasi. Tunggu hingga selesai sebelum "
                "menghapus cache.")
            return

        size_str = _human_size(_cache_size(self.cache_dir))
        reply = QMessageBox.question(
            self, "Hapus semua cache?",
            "Ini akan menghapus semua data cache (tile DEM/SDF, DEMNAS, "
            "direktori sementara) di:\n\n" + self.cache_dir +
            "\n\nTotal ukuran cache: " + size_str +
            "\n\nTindakan ini tidak dapat dibatalkan. Lanjutkan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        freed = 0
        removed = 0
        for entry in os.scandir(self.cache_dir):
            try:
                if entry.is_dir(follow_symlinks=False):
                    freed += _dir_size(entry.path)
                    shutil.rmtree(entry.path)
                else:
                    freed += entry.stat(follow_symlinks=False).st_size
                    os.remove(entry.path)
                removed += 1
            except OSError as exc:
                self.terminal.append(f"[cache] gagal hapus {entry.name}: {exc}")
        os.makedirs(self.cache_dir, exist_ok=True)

        size_str = _human_size(freed)
        msg = f"Cache dibersihkan: {removed} item ({size_str}) dihapus dari {self.cache_dir}"
        self.status.setText("Cache cleared")
        self.terminal.append("[cache] " + msg)

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
            self._export_kmz(result, png, bbox, path, base)
        elif fmt == "KML":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export KML", base + ".kml", "KML (*.kml)")
            if not path:
                return
            kml_path = result.get("kml")
            if kml_path and os.path.exists(kml_path):
                with open(kml_path, "r", encoding="utf-8") as fh:
                    kml_text = fh.read()
            elif bbox is not None:
                from . import output_stage
                kml_text = output_stage.build_kml(os.path.basename(png), bbox, base)
            else:
                QMessageBox.warning(self, "Export", "No bounding box available for KML.")
                return
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(kml_text)
            self.status.setText(f"Exported KML: {path}")
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

    def _export_kmz(self, result: dict, png: str, bbox, path: str, base: str) -> None:
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


