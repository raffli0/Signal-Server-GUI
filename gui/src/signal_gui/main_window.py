"""Main application window: sidebar form + map + terminal + controls matching CloudRF UI."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QProgressBar, QLabel, QFileDialog, QInputDialog, QMessageBox,
    QScrollArea, QApplication, QFrame, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, QTimer, QObject, QEvent, Signal
from PySide6.QtGui import QShortcut, QKeySequence

from . import backend, params as params_mod, output_stage, rm_import
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
from .radio_link_window import RadioLinkWindow
from .cloudrf_profile_panel import CloudRFPathProfilePanel


class MainWindow(QMainWindow):
    #: Ground-elevation lookup finished: ("tx"|"rx", elev_m_or_None).
    amsl_ready = Signal(str, object)

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
        self.radio_link_win: Optional[RadioLinkWindow] = None
        self._pending = None
        self._worker = None
        self._last_result = None
        self._pick_no_fly = False
        self._amsl_timer = QTimer(self)
        self._amsl_timer.setSingleShot(True)
        self._amsl_timer.setInterval(600)
        self._amsl_timer.timeout.connect(self._fetch_ground_elevations)
        self._build_ui()
        self.amsl_ready.connect(self.form.set_ground_elevation)
        self._apply_global_theme()

    def _detect_root(self) -> str:
        from ._bundle import app_root
        return app_root()

    def _set_status(self, text: str) -> None:
        """Set the status label; full text kept as tooltip since long messages
        are visually clipped (the label ignores its text-width hint)."""
        self.status.setText(text)
        self.status.setToolTip(text)

    # ------------------------------------------------------------------ loading overlay
    _SPINNER_FRAMES = "⣾⣽⣻⢿⡿⣟⣯⣷"

    def _build_loading_overlay(self) -> None:
        """Semi-transparent loading card centred over the map pane."""
        self._load_overlay = QWidget(self._right_pane)
        self._load_overlay.setStyleSheet(
            "QWidget { background: rgba(8, 10, 14, 150); }")
        ov = QVBoxLayout(self._load_overlay)
        ov.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setFixedWidth(360)
        card.setStyleSheet("""
            QFrame { background: #14171B; border: 1px solid #2D3339;
                     border-radius: 8px; }
        """)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 18, 20, 16)
        cv.setSpacing(8)

        self._spinner_lbl = QLabel(self._SPINNER_FRAMES[0])
        self._spinner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner_lbl.setStyleSheet(
            "color:#3182CE; font-size:28px; border:none; background:transparent;")
        cv.addWidget(self._spinner_lbl)

        self._stage_lbl = QLabel("Menyiapkan...")
        self._stage_lbl.setWordWrap(True)
        self._stage_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage_lbl.setStyleSheet(
            "color:#E2E8F0; font-size:12px; font-weight:600; "
            "border:none; background:transparent;")
        cv.addWidget(self._stage_lbl)

        self._pct_lbl = QLabel("")
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_lbl.setStyleSheet(
            "color:#3182CE; font-size:11px; font-weight:600; "
            "border:none; background:transparent;")
        cv.addWidget(self._pct_lbl)

        self._elapsed_lbl = QLabel("Elapsed: 00:00")
        self._elapsed_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._elapsed_lbl.setStyleSheet(
            "color:#718096; font-size:10px; border:none; background:transparent;")
        cv.addWidget(self._elapsed_lbl)

        self._cancel_btn = QPushButton("Batalkan")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setStyleSheet("""
            QPushButton { background:#2D3748; color:#FC8181;
                          border:1px solid #4A5568; border-radius:4px;
                          padding:5px 12px; font-size:11px; font-weight:600; }
            QPushButton:hover { background:#4A5568; }
        """)
        self._cancel_btn.clicked.connect(self.stop)
        cv.addWidget(self._cancel_btn, 0, Qt.AlignmentFlag.AlignCenter)

        ov.addWidget(card)
        self._load_overlay.hide()

        # Spinner animation.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(120)
        self._spin_frame = 0
        self._spinner_timer.timeout.connect(self._tick_spinner)

        # Elapsed-time ticker.
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._run_start = None

    def _tick_spinner(self) -> None:
        self._spin_frame = (self._spin_frame + 1) % len(self._SPINNER_FRAMES)
        self._spinner_lbl.setText(self._SPINNER_FRAMES[self._spin_frame])

    def _tick_elapsed(self) -> None:
        if self._run_start is not None:
            secs = int(time.monotonic() - self._run_start)
            self._elapsed_lbl.setText(f"Elapsed: {secs // 60:02d}:{secs % 60:02d}")

    def _show_loading(self, stage: str = "") -> None:
        self._stage_lbl.setText(stage or "Menyiapkan...")
        self._pct_lbl.setText("")
        self._run_start = time.monotonic()
        self._elapsed_lbl.setText("Elapsed: 00:00")
        self._load_overlay.setGeometry(self._right_pane.rect())
        self._load_overlay.raise_()
        self._load_overlay.show()
        self._spinner_timer.start()
        self._elapsed_timer.start()

    def _hide_loading(self) -> None:
        self._spinner_timer.stop()
        self._elapsed_timer.stop()
        self._run_start = None
        self._load_overlay.hide()

    def _set_stage(self, text: str) -> None:
        """Stage line on the overlay; long lines (full argv) are trimmed."""
        text = text.strip()
        if len(text) > 90:
            text = text[:87] + "..."
        self._stage_lbl.setText(text or "Memproses...")

    def _on_engine_percent(self, pct: int) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self._pct_lbl.setText(f"Processing coverage — {pct}%")

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

        # Terminal Log widget inside Left Sidebar Bottom
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumHeight(130)
        self.terminal.installEventFilter(_wheel_guard)
        self.terminal.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0E1013;
                color: #CBD5E0;
                border: none;
                font-family: Consolas, Monaco, monospace;
                font-size: 10px;
                padding: 4px;
            }
        """)

        # Collapsible Console Card
        term_card = QFrame()
        term_card.setStyleSheet("QFrame { background-color: #14171A; border: 1px solid #23272B; border-radius: 4px; }")
        term_v = QVBoxLayout(term_card)
        term_v.setContentsMargins(6, 2, 6, 4)
        term_v.setSpacing(2)

        term_hdr = QHBoxLayout()
        term_lbl = QLabel("LOG CONSOLE")
        term_lbl.setStyleSheet("color: #718096; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;")
        btn_clear_log = QPushButton("Clear")
        btn_clear_log.setStyleSheet("QPushButton { background: transparent; color: #A0AEC0; border: none; font-size: 10px; } QPushButton:hover { color: #FC8181; }")
        btn_clear_log.clicked.connect(self.terminal.clear)
        btn_toggle_log = QPushButton("▾")
        btn_toggle_log.setStyleSheet("QPushButton { background: transparent; color: #A0AEC0; border: none; font-size: 11px; font-weight: bold; } QPushButton:hover { color: #FFFFFF; }")
        
        def _toggle_term():
            vis = not self.terminal.isVisible()
            self.terminal.setVisible(vis)
            btn_toggle_log.setText("▾" if vis else "▸")

        btn_toggle_log.clicked.connect(_toggle_term)
        term_hdr.addWidget(term_lbl)
        term_hdr.addStretch()
        term_hdr.addWidget(btn_clear_log)
        term_hdr.addWidget(btn_toggle_log)
        term_v.addLayout(term_hdr)
        term_v.addWidget(self.terminal)

        sidebar_container = QWidget()
        sidebar_container.setStyleSheet("background-color: #1B1E22;")
        sb_layout = QVBoxLayout(sidebar_container)
        sb_layout.setContentsMargins(4, 4, 4, 4)
        sb_layout.setSpacing(4)
        sb_layout.addWidget(left_scroll, 1)
        sb_layout.addWidget(self.form.action_footer)  # STICKY ACTION FOOTER
        sb_layout.addWidget(term_card)

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
        # Ignore the text's width hint: long messages (e.g. the full engine
        # argv) must never force the right pane wider and squeeze the sidebar.
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # Vertical Splitter: Map View on Top + Integrated CloudRF Path Profile Panel on Bottom
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.addWidget(self.map)

        self.path_profile_panel = CloudRFPathProfilePanel(self)
        self.path_profile_panel.setVisible(False)
        self.path_profile_panel.close_requested.connect(self._hide_link_panel)
        self.path_profile_panel.map_point_tracked.connect(self._on_link_point_tracked)
        self.path_profile_panel.export_kmz_requested.connect(self._export_link_kmz)
        self.path_profile_panel.export_png_requested.connect(self._export_link_png)
        self.right_splitter.addWidget(self.path_profile_panel)
        self.right_splitter.setStretchFactor(0, 55)
        self.right_splitter.setStretchFactor(1, 45)

        rl.addWidget(self.right_splitter, 1)
        self._right_pane = right

        # Loading overlay (shown over the map during propagation runs).
        self._build_loading_overlay()

        rl.addWidget(self.status)
        rl.addWidget(self.progress)

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
        self.header.toggle_sidebar_requested.connect(self._toggle_sidebar)
        self._shortcut_sidebar = QShortcut(QKeySequence("Ctrl+B"), self)
        self._shortcut_sidebar.activated.connect(self._toggle_sidebar)
        self.form.start_requested.connect(self.start)
        self.form.pick_requested.connect(self.map.arm)
        self.form.export_requested.connect(self.export_model)
        self.header.save_profile_requested.connect(self.save_profile)
        self.header.load_profile_requested.connect(self.load_profile)
        self.header.import_rm_requested.connect(self._import_rm_data)
        self.header.radio_link_requested.connect(lambda: self.start(link=True))
        self.header.line_itm_requested.connect(self.start_line_itm)
        self.header.clear_cache_requested.connect(self.clear_cache)
        self.map.picked.connect(self._on_picked)
        self.form.tx_changed.connect(self._on_tx_coord_changed)
        self.form.rx_changed.connect(self._on_rx_coord_changed)
        self.form.tx_name.textChanged.connect(
            lambda: self.map.set_site_labels(tx=self.form.tx_name.text().strip() or None))
        self.form.rx_name.textChanged.connect(
            lambda: self.map.set_site_labels(rx=self.form.rx_name.text().strip() or None))
        self.form.export_dem_requested.connect(self.export_dem_tif)
        self.form.demnas_dir_picked.connect(self._update_demnas_live)
        self.form.demnas_live.toggled.connect(self._update_demnas_live)
        # DEM source changes affect where elevations are sampled from.
        self.form.demnas_dir_picked.connect(self._schedule_amsl)
        self.form.dem_source.currentIndexChanged.connect(lambda _: self._schedule_amsl())
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

    def _toggle_sidebar(self) -> None:
        """Toggle left sidebar visibility smoothly with state persistence."""
        visible = not self._sidebar.isVisible()
        self._sidebar.setVisible(visible)
        if visible:
            cur_w = self.width()
            sb_w = max(340, min(int(cur_w * 0.32), 480))
            self._splitter.setSizes([sb_w, cur_w - sb_w])
        else:
            self._splitter.setSizes([0, self.width()])
        self.map.invalidate_size()

    # ------------------------------------------------------------------ AMSL lookup
    def _demnas_folder_for_lookup(self) -> str | None:
        # Elevation hints are display-only, so any usable local DEMNAS mosaic
        # is preferred over the network regardless of the terrain-source mode
        # (fast, offline, and avoids DNS stalls blocking app shutdown).
        folder = self.form.demnas_dir.text().strip()
        if folder and os.path.isdir(folder):
            return folder
        return None

    def _schedule_amsl(self) -> None:
        """Debounce a background ground-elevation lookup for Tx/Rx labels."""
        self._amsl_timer.start()

    def _fetch_ground_elevations(self) -> None:
        import threading

        from . import dem_convert as dc

        demnas_folder = self._demnas_folder_for_lookup()
        for role, coord in (("tx", self.form.tx_coord.get()),
                            ("rx", self.form.rx_coord.get())):
            try:
                lat, lon = float(coord[0]), float(coord[1])
            except (TypeError, ValueError):
                continue

            def work(role=role, lat=lat, lon=lon):
                try:
                    elev = dc.ground_elevation(
                        lat, lon,
                        demnas_folder=demnas_folder, cache_dir=self.cache_dir,
                    )
                except Exception:  # noqa: BLE001 - hint only
                    elev = None
                self.amsl_ready.emit(role, elev)

            # Daemon thread: an unreachable elevation API must never keep the
            # application alive at shutdown.
            threading.Thread(target=work, daemon=True,
                             name=f"elev-{role}").start()

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
        """Keep the sidebar a sensible fraction of the window at every size.

        Both a minimum and maximum are enforced so the form stays usable and the
        map never collapses. The splitter handle is moved explicitly (via
        ``setSizes``) because ``setMaximumWidth`` alone does not reposition it,
        so the change is visible without a window resize.
        """
        avail = self._splitter.width()
        if avail <= 0:
            return
        # Map always keeps a usable minimum; sidebar is the remainder, clamped.
        map_min = 360
        # Sidebar minimum shrinks on very small windows so the map survives.
        side_min = min(260, max(200, avail - 320))
        # Smaller windows give the sidebar a larger share so inputs stay usable.
        if avail < 900:
            frac = 0.42
        elif avail < 1400:
            frac = 0.34
        else:
            frac = 0.28
        side = int(avail * frac)
        side = max(side_min, min(side, avail - map_min, 460))
        self._sidebar.setMinimumWidth(side_min)
        self._sidebar.setMaximumWidth(side)
        cur = self._splitter.sizes()
        if len(cur) == 2 and (cur[0] > side or cur[0] < side_min):
            # Only move the handle when the sidebar leaves the allowed band, so a
            # user's manual drag inside the band is preserved on resize.
            self._splitter.setSizes([side, max(0, avail - side)])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Layout is realised now; apply the responsive width for the first paint.
        self._apply_responsive_width()

    def _on_splitter_moved(self, *_args) -> None:
        # Re-layout Leaflet after the container size changes (no window resize).
        self._resize_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_width()
        self._resize_timer.start()
        if getattr(self, "_load_overlay", None) is not None and \
                self._load_overlay.isVisible():
            self._load_overlay.setGeometry(self._right_pane.rect())


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
            # Target terrain cell size for the offline conversion, derived
            # from the DEM resolution setting (arc-seconds / metres -> degrees).
            # 3"~90 m, 1"~30 m, 15 m. The actual cell size is clamped to the
            # source resolution and a maximum cell count in dem_convert.
            res = int(p.get("dem_resolution", 3))
            dem_cellsize = {3: 3.0 / 3600.0,
                            1: 1.0 / 3600.0,
                            15: 15.0 / 111320.0}.get(res)
            # Step halus 1/4 DEM: 30m -> 7.5m agar engine tidak loncat 100m
            if p.get("dem_fine_step"):
                dem_cellsize = dem_cellsize / 4.0 if dem_cellsize else None
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
                "dem_cellsize": dem_cellsize, "cache_dir": self.cache_dir,
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
            self._set_status("HD engine requires 30 m DEM; using 30 m.")
        # LIDAR + 360 seg + ppd 6000 = SIGSEGV (-11) race OOM. Cap LIDAR ke 60 seg aman.
        if p.get("engine") == "LIDAR" and int(p.get("plot_segments", 360)) > 120:
            p["plot_segments"] = 60
            self._set_status("LIDAR: segments 360→60 (hindari crash -11, ppd tinggi)")
            self.terminal.appendPlainText("[fix] LIDAR segments capped 60 untuk hindari SIGSEGV thread race (ppd 6000)")
        self._run_with(p, self._dem_spec(p))

    def _bearing_deg(self, lat1, lon1, lat2, lon2) -> float:
        import math
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        y = math.sin(dlon) * math.cos(phi2)
        x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def start_line_itm(self) -> None:
        """Propagasi warna ITM hanya garis lurus Tx→Rx (azimuth sempit)."""
        try:
            p = self.form.collect()
        except Exception as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        if p.get("rx_lat") is None or p.get("rx_lon") is None:
            QMessageBox.warning(self, "Input error", "Set Rx lat/lon dulu untuk garis Tx→Rx.")
            return
        # Paksa ITM
        p["model_pm"] = 1
        p["engine"] = "Standard"
        # Radius = jarak Tx-Rx + 2km margin (garis saja, tidak full area)
        dist = self._link_distance_km(p)
        p["radius"] = math.ceil(dist) + 2
        p["max_dist_km"] = dist  # Cut off precisely at the Rx station (Radio Mobile style)
        # Azimuth sempit 0.9° sesuai request 0.1-1° tapi di-center ke bearing Rx
        brg = self._bearing_deg(p["tx_lat"], p["tx_lon"], p["rx_lat"], p["rx_lon"])
        # User minta 0.1-1 → lebar 0.9°, pakai ±0.45° di sekitar bearing
        # Untuk garis benar-benar tipis, pakai lebar 1.5° agar tetap terlihat beberapa px
        half = 0.75  # 1.5° total
        start = (brg - half) % 360
        end = (brg + half) % 360
        # Handle wrap: mask_png_sector sudah handle start>end
        if start < 0.1: start = 0.1
        if end < 0.1: end = 0.1
        p["az_mask_enabled"] = True
        p["az_mask_start_deg"] = round(start, 2)
        p["az_mask_end_deg"] = round(end, 2)
        # Sinkronkan UI spinbox agar user lihat
        try:
            self.form.az_mask.setChecked(True)
            self.form.az_start.setValue(p["az_mask_start_deg"])
            self.form.az_end.setValue(p["az_mask_end_deg"])
            self.form.model.setCurrentIndex(self.form.model.findData(1))
        except Exception:
            pass
        self._set_status(f"Garis ITM Tx→Rx bearing {brg:.1f}° azimuth {start:.1f}°→{end:.1f}° ({dist:.2f}km)")
        self.terminal.appendPlainText(f"[line] ITM garis lurus Tx→Rx {dist:.2f}km bearing {brg:.1f}° mask {start:.2f}-{end:.2f}")
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

        # JANGAN purge sebelum run — biar log tidak spam [cache] dibersihkan
        # dan biar run sebelumnya tetap bisa di-export. Purge hanya AFTER run
        # (keep=run_dir aktif) di _on_finished. Komentar baris ini hilangkan
        # spam 3 item 13.4MB setiap start.
        # self._purge_render_cache()

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
        self._worker.progress.connect(self._set_status)
        self._worker.progress.connect(self._set_stage)
        self._worker.percent.connect(self._on_engine_percent)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.need_tile_code.connect(self._on_need_tile)
        self._worker.start()
        self.progress.setRange(0, 0)  # indeterminate until engine reports %
        self.progress.setVisible(True)
        self.form.btn_run.setEnabled(False)
        self._set_status("Running calculation engine...")
        self._show_loading("Menyiapkan data & menjalankan engine...")

    def _on_finished(self, ok: bool, stdout: str, result: dict) -> None:
        self.progress.setVisible(False)
        self._hide_loading()
        self.form.btn_run.setEnabled(True)
        run_dir = (os.path.dirname(self._pending[2])
                   if self._pending else None)
        if ok and result.get("link"):
            p = self._pending[0] if self._pending else {}
            tx = (float(p.get("tx_lat")), float(p.get("tx_lon")))
            rx = (float(p.get("rx_lat")), float(p.get("rx_lon")))
            self.map.mark_tx_saved(*tx)
            self._show_link_panel(result["link"], tx, rx)
            # Render selesai -> paksa bersihkan cache (kecuali run aktif).
            self._purge_render_cache(keep=run_dir)
            return
        # Area coverage (clear any previous link result)
        self.map.clear_link()
        self.path_profile_panel.setVisible(False)
        if ok and result.get("bbox"):
            p = self._pending[0] if self._pending else {}
            bbox = result["bbox"]
            if p.get("az_mask_enabled") and \
                    p.get("tx_lat") is not None and p.get("tx_lon") is not None:
                try:
                    output_stage.mask_png_sector(
                        result["png"], bbox,
                        float(p["tx_lat"]), float(p["tx_lon"]),
                        float(p.get("az_mask_start_deg", 0.1)),
                        float(p.get("az_mask_end_deg", 360.0)),
                        max_dist_km=p.get("max_dist_km"))
                except Exception as exc:  # noqa: BLE001 - cosmetic layer
                    self._set_status(f"Peringatan: mask azimuth gagal ({exc})")
            # show_coverage embeds the PNG as base64; after this the file is
            # consumed and the cache around it is fair game.
            self.map.show_coverage(result["png"], bbox, self.form.color_path.text())
            if p.get("tx_lat") is not None and p.get("tx_lon") is not None:
                self.map.mark_tx_saved(float(p["tx_lat"]), float(p["tx_lon"]))
            self._last_result = result
            self._set_status("Done. Coverage shown on map.")
            if result.get("kml"):
                self._set_status(f"Done. KML: {result['kml']}")
            if result.get("rm_png"):
                self._show_rm_preview(result["rm_png"])
            # Render selesai -> paksa bersihkan semua sisa render lama
            # (run dir aktif dipertahankan agar export tetap berfungsi).
            self._purge_render_cache(keep=run_dir)
        else:
            self._last_result = None
            self._set_status("Finished with no coverage.")
            self._purge_render_cache()

    def _show_link_panel(self, link: dict, tx: tuple, rx: tuple) -> None:
        p = self._pending[0] if self._pending else self.form.collect()
        obs = link.get("obstructed", False)
        fm = link.get("fade_margin_db")
        if obs or (fm is not None and fm < -3):
            link_color = "#FF0000"
        elif fm is not None and fm < 3:
            link_color = "#FFFF00"
        else:
            link_color = "#00E600"
        self.map.draw_link(tx[0], tx[1], rx[0], rx[1], color=link_color)
        self._last_result = {"link": link}
        self._set_status("Done. Radio link computed.")

        # Show Integrated Cloud-RF Path Profile Panel directly on the right pane!
        self.path_profile_panel.update_link_results(link, p)
        self.path_profile_panel.setVisible(True)
        h = self._right_pane.height()
        if h > 300:
            self.right_splitter.setSizes([int(h * 0.52), int(h * 0.48)])

    def _hide_link_panel(self) -> None:
        self.path_profile_panel.setVisible(False)
        self.map.clear_link()

    def _export_link_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Path Profile PNG", "path_profile.png", "PNG Image (*.png)"
        )
        if not path:
            return
        pix = self.path_profile_panel.canvas.grab()
        pix.save(path)
        self._set_status(f"Path profile image saved: {path}")

    def _export_link_kmz(self) -> None:
        self.export_requested.emit("KMZ")

    def _on_link_point_tracked(self, lat: float, lon: float, dist_km: float, amsl_m: float, agl_m: float, ground_m: float) -> None:
        """Update interactive tracking marker on the map as the user moves cursor on profile (2D drone altitude)."""
        self.map.set_link_cursor(lat, lon, dist_km, amsl_m, agl_m, ground_m)

    def _swap_tx_rx_link(self) -> None:
        """Swap Tx and Rx coordinates, antenna heights, and re-run link."""
        try:
            tx_lat = self.form.tx_lat.value()
            tx_lon = self.form.tx_lon.value()
            tx_h = self.form.tx_height.value()

            rx_lat = self.form.rx_lat.value()
            rx_lon = self.form.rx_lon.value()
            rx_h = self.form.rx_height.value()

            self.form.tx_lat.setValue(rx_lat)
            self.form.tx_lon.setValue(rx_lon)
            self.form.tx_height.setValue(rx_h)

            self.form.rx_lat.setValue(tx_lat)
            self.form.rx_lon.setValue(tx_lon)
            self.form.rx_height.setValue(tx_h)

            self.map.set_tx(rx_lat, rx_lon, fly=False)
            self.map.set_rx(tx_lat, tx_lon, fly=False)

            self.start(link=True)
        except Exception as exc:
            self._set_status(f"Swap error: {exc}")

    def _on_link_recompute(self, updated_params: dict) -> None:
        """Handle real-time antenna height stepping from the Radio Link window."""
        try:
            if "tx_height" in updated_params:
                self.form.tx_height.setValue(updated_params["tx_height"])
            if "rx_height" in updated_params:
                self.form.rx_height.setValue(updated_params["rx_height"])
            self.start(link=True)
        except Exception as exc:
            self._set_status(f"Recompute error: {exc}")

    def _show_rm_preview(self, rm_png: str) -> None:
        """Non-modal preview of the Radio Mobile-style picture."""
        from PySide6.QtGui import QPixmap

        dlg = QDialog(self)
        dlg.setWindowTitle("Gambar gaya Radio Mobile")
        v = QVBoxLayout(dlg)
        img = QLabel()
        pix = QPixmap(rm_png)
        if not pix.isNull():
            avail = int(QApplication.primaryScreen().availableGeometry()
                        .height() * 0.7) if QApplication.primaryScreen() else 700
            img.setPixmap(pix.scaledToHeight(avail, Qt.TransformationMode.SmoothTransformation))
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(img)
        row = QHBoxLayout()
        hint = QLabel(os.path.basename(rm_png))
        hint.setStyleSheet("color:#718096; font-size:10px;")
        row.addWidget(hint, 1)
        btn_close = QPushButton("Tutup")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_close)
        v.addLayout(row)
        self._set_status(f"PNG RM-style siap: {rm_png}")
        dlg.show()

    def _on_error(self, msg: str) -> None:
        self.progress.setVisible(False)
        self._hide_loading()
        self.form.btn_run.setEnabled(True)
        self.terminal.appendPlainText(f"ERROR: {msg}")
        self._set_status("Error")

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
        self._set_status(f"{role.upper()} set: {lat:.5f}, {lon:.5f}")

    def _on_tx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.tx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_tx(lat, lon, fly=False)
        self._set_status(f"Tx set: {lat:.5f}, {lon:.5f}")
        self._update_demnas_live()
        self._schedule_amsl()

    def _on_rx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.rx_coord.get()
        except (ValueError, TypeError):
            return
        self.map.set_rx(lat, lon, fly=False)
        self._schedule_amsl()

    # ------------------------------------------------------------------ profile
    def _import_rm_data(self) -> None:
        """Load a Radio Mobile coverage-data TXT export onto the map.

        The file's ``Rx(dB)`` column is a margin above its threshold, so the
        colour span follows the header (threshold .. threshold + Range) and the
        Tx pin is restored from the ``Fixed unit`` line.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Radio Mobile data", "",
            "Radio Mobile TXT (*.txt);;All files (*)")
        if not path:
            return
        try:
            data = rm_import.parse_rm_export(path)
        except Exception as exc:  # noqa: BLE001 - surface any parse problem
            QMessageBox.warning(
                self, "Import Radio Mobile", f"Gagal memuat file:\n{exc}")
            return
        vmin = float(data["threshold_dbm"])
        vmax = vmin + float(data["range_db"])
        png = os.path.join(self.cache_dir,
                           f"rm_import_{datetime.now().strftime('%H%M%S%f')}.png")
        try:
            rm_import.render_grid_png(data["points"], vmin, vmax, png)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Import Radio Mobile", f"Gagal merender grid:\n{exc}")
            return
        self.map.show_coverage(png, data["bbox"])
        fixed = data.get("fixed")
        if fixed:
            self.map.set_tx(fixed["lat"], fixed["lon"], fly=False)
        self._set_status(
            f"RM import: {len(data['points'])} titik "
            f"({vmin:.0f}…{vmax:.0f} dBm) — {os.path.basename(path)}")

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
            self._set_status(f"Profile saved: {os.path.basename(path)}")

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
        self._set_status(f"Profile loaded: {os.path.basename(path)}")

    def stop(self) -> None:
        if self._worker:
            self._worker.terminate()
            self._worker.wait()
        self.progress.setVisible(False)
        self._hide_loading()
        self.form.btn_run.setEnabled(True)
        self._set_status("Stopped")

    def clear_propagation(self) -> None:
        """Clear computed propagation data: coverage overlay, log, and status."""
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        self.map.clear_coverage()
        self.terminal.clear()
        self.progress.setVisible(False)
        self._hide_loading()
        self.form.btn_run.setEnabled(True)
        self._set_status("Ready")

    def _purge_render_cache(self, keep: Optional[str] = None) -> None:
        """Force-delete the render cache (``.../gui/cache/dem``) contents.

        Runs automatically before and after every render so the GUI can never
        show leftover images from an earlier run: stale ``siggui_*`` run
        directories, downloaded DEM tiles, VRT/LIDAR/SDF products -- everything
        is removed. ``keep`` (the active run directory) survives so the files
        still referenced by the GUI (coverage PNG/KML, raster TXT for export)
        remain valid until the next run purges them.
        """
        keep_abs = os.path.abspath(keep) if keep else None
        try:
            entries = list(os.scandir(self.cache_dir))
        except OSError:
            entries = []
        freed = 0
        removed = 0
        for entry in entries:
            try:
                if keep_abs and os.path.abspath(entry.path) == keep_abs:
                    continue
                # Do NOT delete DEM caches (lidar, vrt, demnas, srtm, etc.) during automatic purge!
                # Only delete stale siggui_* run folders and temporary files.
                if entry.is_dir(follow_symlinks=False):
                    if not entry.name.startswith("siggui_"):
                        continue
                    freed += _dir_size(entry.path)
                    shutil.rmtree(entry.path)
                else:
                    freed += entry.stat(follow_symlinks=False).st_size
                    os.remove(entry.path)
                removed += 1
            except OSError as exc:
                self.terminal.appendPlainText(
                    f"[cache] gagal hapus {entry.name}: {exc}")
        os.makedirs(self.cache_dir, exist_ok=True)
        if removed:
            self.terminal.appendPlainText(
                f"[cache] dibersihkan paksa: {removed} item "
                f"({_human_size(freed)}) dari {self.cache_dir}")

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
        self._set_status("Cache cleared")
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
            self._set_status(f"Exported KML: {path}")
        elif fmt == "TXT (Raster)":
            raster = result.get("raster_txt")
            if not raster or not os.path.exists(raster):
                QMessageBox.warning(
                    self, "Export",
                    "Raster TXT tidak tersedia. Aktifkan 'Save raster data "
                    "(TXT)' di bagian Output lalu jalankan ulang propagasi.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Raster TXT", base + "_raster.txt", "TXT (*.txt)")
            if not path:
                return
            self._export_raster_txt(result, path)
            self._set_status(f"Exported TXT: {path}")
        elif fmt == "PNG":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PNG", base + ".png", "PNG (*.png)")
            if not path:
                return
            shutil.copyfile(png, path)
            self._set_status(f"Exported PNG: {path}")
        elif fmt == "PNG (RM-style)":
            self._export_rm_png(result, base)
        else:
            QMessageBox.information(
                self, "Export",
                f"'{fmt}' export is not available from the current engine output.\n"
                "Use KMZ or PNG.")
            return
        if fmt in ("KMZ", "KMZ (3D)"):
            self._set_status(f"Exported {fmt}: {path}")

    def _export_rm_png(self, result: dict, base: str) -> None:
        """Export a full Radio Mobile-style picture + automatic KML sidecar."""
        bbox = result.get("bbox")
        if bbox is None:
            QMessageBox.warning(self, "Export", "No bounding box available for RM-style PNG.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG (RM-style)", base + "_rm.png", "PNG (*.png)")
        if not path:
            return
        from . import rm_style

        p = (self._pending[0] if self._pending else {}) or {}
        try:
            rm_style.render_for_run(
                path, bbox, p, coverage_png=result["png"])
        except Exception as exc:  # noqa: BLE001 - surface to the user
            QMessageBox.warning(self, "Export", f"Render RM-style gagal:\n{exc}")
            return
        sidecar = os.path.splitext(path)[0] + ".kml"
        with open(sidecar, "w", encoding="utf-8") as fh:
            fh.write(output_stage.build_kml(
                os.path.basename(path), bbox, base))
        self._set_status(f"Exported PNG (RM-style): {path} (+ {os.path.basename(sidecar)})")

    def _export_raster_txt(self, result: dict, path: str) -> None:
        """Wrap the engine's raw raster dump in a Radio-Mobile-compatible file.

        Formatting lives in :func:`rm_import.write_rm_export`.  Antenna heights
        are AMSL (ground elevation + AGL input), matching how Radio Mobile
        reports site heights, and the ``Rx(dB)`` column stores the margin above
        the run threshold -- the same convention RM itself exports.
        """
        from . import dem_convert as dc

        p = (self._pending[0] if self._pending else {}) or {}

        def _f(v, default=0.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        tx_name = p.get("tx_name") or "Tx"
        rx_name = p.get("rx_name") or "Rx"
        rx_lat = p.get("rx_lat")
        rx_lon = p.get("rx_lon")

        # Ground elevation (AMSL) lookup: local DEMNAS folder when offline mode
        # is active, otherwise the web fallback inside ground_elevation().
        demnas_folder = None
        if p.get("dem_source") == "offline":
            folder = p.get("demnas_dir")
            if folder and os.path.isdir(folder):
                demnas_folder = folder

        def amsl(lat, lon, agl):
            elev = dc.ground_elevation(
                _f(lat), _f(lon),
                demnas_folder=demnas_folder, cache_dir=self.cache_dir,
            )
            return _f(agl) + (elev if elev is not None else 0.0)

        thr = _f(p.get("rx_threshold_dbm"), -100)
        rm_import.write_rm_export(
            path, result["raster_txt"], threshold_dbm=thr,
            tx_name=tx_name, tx_lat=_f(p.get("tx_lat")), tx_lon=_f(p.get("tx_lon")),
            tx_amsl=amsl(p.get("tx_lat"), p.get("tx_lon"), p.get("tx_height")),
            rx_name=rx_name, rx_lat=_f(rx_lat), rx_lon=_f(rx_lon),
            rx_amsl=amsl(rx_lat, rx_lon, p.get("rx_height")))

    def export_dem_tif(self) -> None:
        """Export DEM clip ter-potong untuk QGIS + validasi lubang hitam di Tx."""
        try:
            p = self.form.collect()
        except Exception as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        folder = p.get("demnas_dir")
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Export DEM", "Pilih folder DEMNAS (.tif) dulu.")
            return
        tx_lat, tx_lon = p.get("tx_lat"), p.get("tx_lon")
        if tx_lat is None or tx_lon is None:
            QMessageBox.warning(self, "Export DEM", "Koordinat Tx belum valid.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export DEM .tif (QGIS)", "dem_clip.tif", "GeoTIFF (*.tif)")
        if not path:
            return
        try:
            from . import dem_convert as dc
            vrt = dc._demnas_vrt(folder, self.cache_dir)
            dc._assert_covers(vrt, float(tx_lat), float(tx_lon))
            elev = dc._sample_elevation(vrt, float(tx_lat), float(tx_lon))
            # export clip sekitar Tx ± radius (atau 2km default untuk cek lubang)
            radius_km = float(p.get("radius", 2) or 2)
            lat_deg = min(0.05, radius_km / 111.0)
            lon_deg = radius_km / (111.32 * max(0.01, math.cos(math.radians(float(tx_lat)))))
            import shutil, subprocess
            cmd = ["gdalwarp", "-t_srs", "EPSG:4326",
                   "-te", str(float(tx_lon)-lon_deg), str(float(tx_lat)-lat_deg),
                   str(float(tx_lon)+lon_deg), str(float(tx_lat)+lat_deg),
                   "-tr", "0.00027", "0.00027", "-r", "bilinear", vrt, path]
            subprocess.run(cmd, check=True)
            msg = f"DEM diekspor ke {path}\nElevasi Tx: {elev} m"
            if elev is None or elev == 0:
                msg += "\n⚠️ LUBANG HITAM: elev 0/void di Tx → 100% masalah preprocessing! Cek QGIS."
                self.terminal.appendPlainText(f"[DEM] Tx void/0 di ({tx_lat},{tx_lon}) → {path}")
            else:
                msg += "\n✅ Tidak ada lubang di Tx → cek engine step/azimuth."
            QMessageBox.information(self, "Export DEM", msg)
            self._set_status(f"DEM exported: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export DEM", f"Gagal: {exc}")

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


