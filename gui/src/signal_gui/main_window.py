"""Main application window: sidebar form + map + terminal + controls matching CloudRF UI."""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QProgressBar, QLabel, QFileDialog, QInputDialog, QMessageBox,
    QScrollArea, QApplication, QFrame, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, QTimer, QObject, QEvent, Signal, QByteArray
from PySide6.QtGui import QShortcut, QKeySequence

from . import backend, params as params_mod, output_stage, rm_import
from .widgets import ParameterForm

logger = logging.getLogger("signal_gui.main_window")


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
from .cloudrf_profile_panel import CloudRFPathProfilePanel


class MainWindow(QMainWindow):
    #: Ground-elevation lookup finished: ("tx"|"rx", elev_m_or_None).
    amsl_ready = Signal(str, object)
    demnas_status_ready = Signal(str, str)

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
        from ._bundle import cache_root
        self.cache_dir = cache_root()
        os.makedirs(self.cache_dir, exist_ok=True)
        self._pending = None
        self._worker = None
        self._last_result = None
        self._last_coverage_result = None
        self._last_link_result = None
        self._pick_no_fly = False
        self.points_locked = False
        self._amsl_timer = QTimer(self)
        self._amsl_timer.setSingleShot(True)
        self._amsl_timer.setInterval(600)
        self._amsl_timer.timeout.connect(self._fetch_ground_elevations)
        self._demnas_live_timer = QTimer(self)
        self._demnas_live_timer.setSingleShot(True)
        self._demnas_live_timer.setInterval(350)
        self._demnas_live_timer.timeout.connect(self._update_demnas_live)
        self._build_ui()
        self.amsl_ready.connect(self.form.set_ground_elevation)
        self.demnas_status_ready.connect(self.form.set_demnas_status)
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
            QToolTip {
                background-color: #1E2226;
                color: #FFFFFF;
                border: 1px solid #4A5568;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
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
        self.terminal.setMaximumHeight(100)
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
        self.btn_toggle_log = QPushButton("▾")
        self.btn_toggle_log.setStyleSheet("QPushButton { background: transparent; color: #A0AEC0; border: none; font-size: 11px; font-weight: bold; } QPushButton:hover { color: #FFFFFF; }")
        
        def _toggle_term():
            vis = not self.terminal.isVisible()
            self.terminal.setVisible(vis)
            self.btn_toggle_log.setText("▾" if vis else "▸")

        self.btn_toggle_log.clicked.connect(_toggle_term)
        term_hdr.addWidget(term_lbl)
        term_hdr.addStretch()
        term_hdr.addWidget(btn_clear_log)
        term_hdr.addWidget(self.btn_toggle_log)
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
        self.path_profile_panel.export_kml_requested.connect(self._export_link_kml)
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
        # Keep the sidebar at a comfortable width while the map expands to fill;
        # its default width is computed responsively in _apply_responsive_width().
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.splitterMoved.connect(self._on_splitter_moved)
        central_layout.addWidget(split, 1)
        self._splitter = split

        self._saved_sidebar_width: int | None = None
        self._saved_splitter_state: QByteArray | None = None

        # Debounced map re-layout after container resizes.
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self.map.invalidate_size)

        # Apply an initial responsive sidebar width.
        self._apply_responsive_width()
        self._saved_splitter_state = self._splitter.saveState()

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
        self.form.transparent_holes_toggled.connect(self.map.set_transparent_holes)
        self.form.contour_mode_changed.connect(self.map.set_contour_mode)
        # Wire up Lock and Swap Signals across Form, Map, and Radio Link Panel
        self.form.swap_requested.connect(self._swap_tx_rx_link)
        self.form.lock_toggled.connect(self.toggle_points_locked)
        self.map.swap_requested.connect(self._swap_tx_rx_link)
        self.map.lock_toggled.connect(self.toggle_points_locked)
        self.path_profile_panel.swap_requested.connect(self._swap_tx_rx_link)
        self.path_profile_panel.lock_toggled.connect(self.toggle_points_locked)
        # DEM source changes affect where elevations are sampled from.
        self.form.demnas_dir_picked.connect(self._schedule_amsl)
        self.demnas_default_dir = self._find_demnas_default()
        self.srtm_default_dir = self._find_srtm_default()
        self.form.dem_source.currentIndexChanged.connect(self._on_dem_source_changed)
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
        if not visible:
            # Closing sidebar: remember current state and width before hiding
            if hasattr(self, "_splitter"):
                self._saved_splitter_state = self._splitter.saveState()
                sizes = self._splitter.sizes()
                if sizes and sizes[0] > 0:
                    self._saved_sidebar_width = sizes[0]
            self._sidebar.setVisible(False)
        else:
            # Opening sidebar: restore exact saved state
            self._sidebar.setVisible(True)
            if getattr(self, "_saved_splitter_state", None) is not None:
                self._splitter.restoreState(self._saved_splitter_state)
            elif self._saved_sidebar_width is not None and self._saved_sidebar_width > 0:
                sizes = self._splitter.sizes()
                avail = sum(sizes) if sizes else self._splitter.width()
                if avail <= 0:
                    avail = self.width()
                sb_w = self._saved_sidebar_width
                self._splitter.setSizes([sb_w, max(0, avail - sb_w)])
            else:
                self._apply_responsive_width()
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
        for role, widget in (("tx", self.form.tx_coord),
                             ("rx", self.form.rx_coord)):
            try:
                coord = widget.get()
                if not coord or coord[0] is None or coord[1] is None:
                    continue
                lat, lon = float(coord[0]), float(coord[1])
            except (TypeError, ValueError, Exception):
                continue

            def work(role=role, lat=lat, lon=lon):
                try:
                    elev = dc.ground_elevation(
                        lat, lon,
                        demnas_folder=demnas_folder, cache_dir=self.cache_dir,
                    )
                except Exception as exc:  # noqa: BLE001 - hint only
                    logger.debug("Ground elevation hint lookup exception: %s", exc)
                    elev = None
                self.amsl_ready.emit(role, elev)

            # Daemon thread: an unreachable elevation API must never keep the
            # application alive at shutdown.
            threading.Thread(target=work, daemon=True,
                             name=f"elev-{role}").start()

    @staticmethod
    def _has_dem_files(folder: str, ext=(".tif", ".tiff", ".hgt")) -> bool:
        try:
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(ext):
                        return True
        except OSError:
            pass
        return False

    def _find_demnas_default(self) -> str:
        """Return the default DEMNAS folder if it contains raster tiles, else empty."""
        base = os.path.join(self.root, "gui", "data")
        if not os.path.isdir(base):
            return ""
        for preferred in ("Demnas", "demnas", "DEMNAS"):
            p = os.path.join(base, preferred)
            if os.path.isdir(p) and self._has_dem_files(p):
                return p
        try:
            for entry in os.scandir(base):
                if entry.is_dir() and "demnas" in entry.name.lower() and self._has_dem_files(entry.path):
                    return entry.path
        except OSError:
            pass
        return ""

    def _find_srtm_default(self) -> str:
        """Return the default SRTM folder if it contains .hgt tiles, else empty."""
        base = os.path.join(self.root, "gui", "data")
        if not os.path.isdir(base):
            return ""
        for preferred in ("SRTM3", "srtm3", "SRTM", "srtm"):
            p = os.path.join(base, preferred)
            if os.path.isdir(p) and self._has_dem_files(p, ext=(".hgt",)):
                return p
        try:
            for entry in os.scandir(base):
                if entry.is_dir() and "srtm" in entry.name.lower() and self._has_dem_files(entry.path, ext=(".hgt",)):
                    return entry.path
        except OSError:
            pass
        return ""

    def _on_dem_source_changed(self, idx: int) -> None:
        cur_dir = self.form.demnas_dir.text().strip()
        if idx == 2:  # Offline SRTM
            if not cur_dir or cur_dir == self.demnas_default_dir:
                self.form.demnas_dir.setText(self.srtm_default_dir)
        elif idx == 1:  # Offline DEMNAS
            if not cur_dir or cur_dir == self.srtm_default_dir:
                self.form.demnas_dir.setText(self.demnas_default_dir)
        self._schedule_amsl()
        self._update_demnas_live()

    # ------------------------------------------------------------------ DEMNAS/SRTM config
    def _schedule_demnas_live(self) -> None:
        """Debounce the live DEMNAS coverage check so typing remains smooth."""
        self._demnas_live_timer.start()

    def _update_demnas_live(self) -> None:
        """Live (toggleable) coverage indicator for the selected DEMNAS/SRTM folder."""
        form = self.form
        idx = form.dem_source.currentIndex()
        if idx not in (1, 2):
            form.set_demnas_status("idle", "DEM: online aktif")
            return
        tag = "SRTM" if idx == 2 else "DEMNAS"
        if not form.demnas_live.isChecked():
            form.set_demnas_status("idle", f"{tag}: live check OFF")
            return
        folder = form.demnas_dir.text().strip()
        if not folder or not os.path.isdir(folder):
            form.set_demnas_status("idle", f"{tag}: pilih folder")
            return
        try:
            tx = form.tx_coord.get()
        except (ValueError, TypeError):
            tx = None
        if not tx or tx[0] is None or tx[1] is None:
            form.set_demnas_status("idle", f"{tag}: tunggu koordinat Tx")
            return

        lat, lon = tx
        cache_dir = self.cache_dir
        self._demnas_live_gen = getattr(self, "_demnas_live_gen", 0) + 1
        cur_gen = self._demnas_live_gen

        def work():
            try:
                from . import dem_convert as dc
                vrt = dc._demnas_vrt(folder, cache_dir)
                dc._assert_covers(vrt, lat, lon)
                elev = dc._sample_elevation(vrt, lat, lon)
                if getattr(self, "_demnas_live_gen", 0) != cur_gen:
                    return
                try:
                    if elev is None:
                        self.demnas_status_ready.emit(
                            "bad", f"{tag}: ✗ void di Tx ({lat:.3f}, {lon:.3f})"
                        )
                    else:
                        self.demnas_status_ready.emit(
                            "ok", f"{tag}: ✓ Tx ({lat:.3f}, {lon:.3f}) elev {elev:.0f} m"
                        )
                except RuntimeError:
                    pass
            except Exception as exc:  # noqa: BLE001 - surface any gdal/IO issue as red
                if getattr(self, "_demnas_live_gen", 0) != cur_gen:
                    return
                try:
                    self.demnas_status_ready.emit("bad", f"{tag}: ✗ {exc}")
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True, name=f"demnas-live-{cur_gen}").start()

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
        ``setSizes``) while ``setMaximumWidth`` provides a flexible ceiling,
        preserving the user's manual dragging freedom.
        """
        if not hasattr(self, "_sidebar") or not self._sidebar.isVisible():
            return
        cur = self._splitter.sizes()
        avail = sum(cur) if cur else self._splitter.width()
        if avail <= 0:
            return
        # Map always keeps a usable minimum; sidebar is the remainder, clamped.
        map_min = 400
        side_min = 420
        # If available space is tight (e.g. very small screen), adjust side_min to avoid collapsing map
        if avail - map_min < side_min:
            side_min = max(280, avail - map_min)
        side_max = min(680, max(side_min, avail - map_min))

        # Comfortable width: ParameterForm needs ~430-440px to display without horizontal scrolling.
        if avail < 900:
            target = min(side_max, max(side_min, int(avail * 0.45)))
        elif avail < 1440:  # covers 1366x768 screens
            target = 440
        elif avail < 1920:  # covers 1920x1080 screens
            target = 460
        else:  # 2K / 4K
            target = 480

        side = max(side_min, min(target, side_max))

        self._sidebar.setMinimumWidth(side_min)
        self._sidebar.setMaximumWidth(side_max)

        cur = self._splitter.sizes()
        if self._saved_sidebar_width is None:
            target_side = side
            self._splitter.setSizes([target_side, max(0, avail - target_side)])
            self._saved_sidebar_width = target_side
        elif len(cur) == 2 and (cur[0] > side_max or cur[0] < side_min or cur[0] == 0):
            target_side = self._saved_sidebar_width if (side_min <= self._saved_sidebar_width <= side_max) else side
            self._splitter.setSizes([target_side, max(0, avail - target_side)])
            self._saved_sidebar_width = target_side
        elif len(cur) == 2 and cur[0] > 0:
            self._saved_sidebar_width = cur[0]
        self._saved_splitter_state = self._splitter.saveState()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Layout is realised now; apply the responsive width for the first paint.
        self._apply_responsive_width()
        self._saved_splitter_state = self._splitter.saveState()
        # On compact / 768p laptop screens, collapse the bottom log console by default
        # to maximize vertical real estate for the parameter form.
        if self.height() <= 800 and hasattr(self, "terminal") and hasattr(self, "btn_toggle_log"):
            self.terminal.setVisible(False)
            self.btn_toggle_log.setText("▸")

    def _on_splitter_moved(self, *_args) -> None:
        if hasattr(self, "_sidebar") and self._sidebar.isVisible():
            sizes = self._splitter.sizes()
            if sizes and sizes[0] > 0:
                self._saved_sidebar_width = sizes[0]
                self._saved_splitter_state = self._splitter.saveState()
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
        # ---- Offline: local DEMNAS / SRTM folder (no network) ----
        if p.get("dem_source") == "offline":
            folder = p.get("demnas_dir")
            if not folder or not os.path.isdir(folder):
                kind = "SRTM (.hgt)" if p.get("dem_kind") == "srtm" else "DEMNAS (.tif)"
                raise RuntimeError(
                    f"Mode Offline membutuhkan folder {kind}. "
                    "Pilih folder di baris 'DEMNAS / SRTM folder' (bagian Terrain & DEM Source)."
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
        if p.get("tx_lat") is None or p.get("tx_lon") is None:
            QMessageBox.warning(
                self, "Input error",
                "Koordinat Transmitter (Tx) tidak valid atau belum lengkap."
            )
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
        if p.get("tx_lat") is None or p.get("tx_lon") is None:
            QMessageBox.warning(self, "Input error", "Koordinat Transmitter (Tx) tidak valid atau belum lengkap.")
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
        is_link_run = bool(
            (self._pending and self._pending[0] and self._pending[0].get("path_profile"))
            or (result and result.get("link"))
        )

        if is_link_run:
            if ok and result.get("link"):
                p = self._pending[0] if self._pending else {}
                tx = (float(p.get("tx_lat")), float(p.get("tx_lon")))
                rx = (float(p.get("rx_lat")), float(p.get("rx_lon")))
                self.map.mark_tx_saved(*tx)
                self._show_link_panel(result["link"], tx, rx)
                # Render selesai -> bersihkan cache tanpa menghapus run aktif & coverage aktif
                self._purge_render_cache(keep=run_dir)
            else:
                self._set_status("Kalkulasi radio link selesai tanpa hasil.")
                self._purge_render_cache(keep=run_dir)
            return

        # Area coverage (clear any previous link result)
        self.map.clear_link()
        self.path_profile_panel.setVisible(False)
        if ok and result.get("bbox"):
            p = self._pending[0] if self._pending else {}
            bbox = result["bbox"]
            if p.get("tx_lat") is not None and p.get("tx_lon") is not None:
                try:
                    max_r = float(p.get("radius") or 100.0)
                    start_deg = float(p.get("az_mask_start_deg", 0.0)) if p.get("az_mask_enabled") else 0.0
                    end_deg = float(p.get("az_mask_end_deg", 360.0)) if p.get("az_mask_enabled") else 360.0
                    output_stage.mask_png_sector(
                        result["png"], bbox,
                        float(p["tx_lat"]), float(p["tx_lon"]),
                        start_deg, end_deg,
                        max_dist_km=max_r)
                except Exception as exc:  # noqa: BLE001 - cosmetic layer
                    logger.warning("Mask sector failed: %s", exc)
                    self._set_status(f"Peringatan: mask radius/azimuth gagal ({exc})")
            # show_coverage embeds the PNG as base64; after this the file is
            # consumed and the cache around it is fair game.
            c_mode = self.form.kmz_contour_mode.currentIndex() if hasattr(self.form, "kmz_contour_mode") else 0
            self.map.show_coverage(result["png"], bbox, self.form.color_path.text(), contour_mode=c_mode)
            if p.get("tx_lat") is not None and p.get("tx_lon") is not None:
                self.map.mark_tx_saved(float(p["tx_lat"]), float(p["tx_lon"]))
            self._last_result = result
            self._last_coverage_result = result
            self._set_status("Done. Coverage shown on map.")
            if result.get("kml"):
                self._set_status(f"Done. KML: {result['kml']}")
            # Render selesai -> paksa bersihkan semua sisa render lama
            # (run dir aktif dipertahankan agar export tetap berfungsi).
            self._purge_render_cache(keep=run_dir)
        else:
            self._last_result = None
            self._last_coverage_result = None
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
        self._last_link_result = {"link": link, "params": p}
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
        from . import export_controller
        export_controller.export_link_png(self, self.path_profile_panel.canvas, self._set_status)

    def _export_link_kml(self) -> None:
        from . import export_controller
        link_res = self._last_link_result or (self._last_result if (self._last_result and self._last_result.get("link")) else None)
        p = (link_res.get("params") if link_res and isinstance(link_res.get("params"), dict) else None) or (self._pending[0] if getattr(self, "_pending", None) else (self.form.collect() if hasattr(self, "form") else {}))
        export_controller.export_link_kml(self, link_res, p, self._set_status)

    def _export_link_kmz(self) -> None:
        from . import export_controller
        link_res = self._last_link_result or (self._last_result if (self._last_result and self._last_result.get("link")) else None)
        p = (link_res.get("params") if link_res and isinstance(link_res.get("params"), dict) else None) or (self._pending[0] if getattr(self, "_pending", None) else (self.form.collect() if hasattr(self, "form") else {}))
        export_controller.export_link_kmz(self, link_res, p, self._set_status)

    def _on_link_point_tracked(self, lat: float, lon: float, dist_km: float, amsl_m: float, agl_m: float, ground_m: float) -> None:
        """Update interactive tracking marker on the map as the user moves cursor on profile (2D drone altitude)."""
        self.map.set_link_cursor(lat, lon, dist_km, amsl_m, agl_m, ground_m)

    def toggle_points_locked(self, locked: Optional[bool] = None) -> None:
        """Synchronize Tx & Rx points locked state across Form, Map, and Radio Link Panel."""
        if locked is None:
            self.points_locked = not getattr(self, "points_locked", False)
        else:
            self.points_locked = bool(locked)

        if hasattr(self, "form"):
            self.form.set_points_locked(self.points_locked)
        if hasattr(self, "map"):
            self.map.set_points_locked(self.points_locked)
        if hasattr(self, "path_profile_panel"):
            self.path_profile_panel.set_points_locked(self.points_locked)

        if self.points_locked:
            self._set_status("Titik Tx & Rx dikunci (Aman dari klik peta)")
        else:
            self._set_status("Titik Tx & Rx dibuka kuncinya")

    def _swap_tx_rx_link(self) -> None:
        """Swap Tx and Rx coordinates, antenna heights, names, gains, losses, power, and re-run link if active."""
        try:
            tx_lat, tx_lon = self.form.tx_coord.get()
            rx_lat, rx_lon = self.form.rx_coord.get()
            if tx_lat is None or tx_lon is None or rx_lat is None or rx_lon is None:
                self._set_status("Swap gagal: Koordinat Tx atau Rx tidak valid")
                return

            tx_name = self.form.tx_name.text()
            rx_name = self.form.rx_name.text()
            tx_h = self.form.tx_height.value()
            rx_h = self.form.rx_height.value()
            tx_g = self.form.tx_gain.value()
            rx_g = self.form.rx_gain.value()
            tx_loss = self.form.cable_loss.value()
            rx_loss = self.form.rx_cable_loss.value()
            tx_p = self.form.rf_power.value()
            rx_p = self.form.rx_power.value()
            tx_thr = self.form.tx_thr.value()
            rx_thr = self.form.rx_thr.value()

            # Temporarily unlock form coordinates if locked so programmatic swap succeeds
            was_locked = getattr(self, "points_locked", False)
            if was_locked:
                self.form.tx_coord.setEnabled(True)
                self.form.rx_coord.setEnabled(True)

            self._pick_no_fly = True
            try:
                self.form.tx_coord.set(rx_lat, rx_lon)
                self.form.rx_coord.set(tx_lat, tx_lon)
            finally:
                self._pick_no_fly = False

            if was_locked:
                self.form.tx_coord.setEnabled(False)
                self.form.rx_coord.setEnabled(False)

            self.form.tx_name.setText(rx_name)
            self.form.rx_name.setText(tx_name)
            self.form.tx_height.setValue(rx_h)
            self.form.rx_height.setValue(tx_h)
            self.form.tx_gain.setValue(rx_g)
            self.form.rx_gain.setValue(tx_g)
            self.form.cable_loss.setValue(rx_loss)
            self.form.rx_cable_loss.setValue(tx_loss)
            self.form.rf_power.setValue(rx_p)
            self.form.rx_power.setValue(tx_p)
            self.form.tx_thr.setValue(rx_thr)
            self.form.rx_thr.setValue(tx_thr)

            # Update map markers and site labels
            self.map.set_tx(rx_lat, rx_lon, fly=False)
            self.map.set_rx(tx_lat, tx_lon, fly=False)
            self.map.set_site_labels(tx=rx_name.strip() or None, rx=tx_name.strip() or None)

            self._schedule_amsl()
            self._schedule_demnas_live()

            tx_disp = rx_name or f"{rx_lat:.4f},{rx_lon:.4f}"
            rx_disp = tx_name or f"{tx_lat:.4f},{tx_lon:.4f}"
            self._set_status(f"Tx & Rx ditukar: Tx({tx_disp}) ⇄ Rx({rx_disp})")

            # If Radio Link panel is currently visible, re-run link in reverse direction immediately
            if getattr(self, "path_profile_panel", None) and self.path_profile_panel.isVisible():
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
        if getattr(self, "points_locked", False):
            self._set_status("Titik Tx & Rx terkunci (Buka kunci untuk memindahkan titik)")
            return
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
            if lat is None or lon is None:
                return
        except (ValueError, TypeError):
            return
        self.map.set_tx(lat, lon, fly=False)
        self._set_status(f"Tx set: {lat:.5f}, {lon:.5f}")
        self._schedule_demnas_live()
        self._schedule_amsl()

    def _on_rx_coord_changed(self) -> None:
        try:
            lat, lon = self.form.rx_coord.get()
            if lat is None or lon is None:
                return
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
            logger.warning("Import Radio Mobile parse failed: %s", exc)
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
            logger.warning("Import Radio Mobile render grid failed: %s", exc)
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
        self._last_result = None
        self._last_coverage_result = None
        self._last_link_result = None
        self._set_status("Ready")

    def _purge_render_cache(self, keep: Optional[Any] = None) -> None:
        """Force-delete the render cache (``.../gui/cache/dem``) contents.

        Runs automatically before and after every render so the GUI can never
        show leftover images from an earlier run. Keeps active run directory
        AND the directory containing active coverage result so that exports
        (KMZ, KML, PNG, raster TXT) remain valid.
        """
        keep_dirs: set[str] = set()
        if keep:
            if isinstance(keep, str):
                keep_dirs.add(os.path.abspath(keep))
            else:
                try:
                    for k in keep:
                        if k:
                            keep_dirs.add(os.path.abspath(k))
                except TypeError:
                    pass

        # CRITICAL: Always preserve the directory of the active coverage result!
        if getattr(self, "_last_coverage_result", None) and self._last_coverage_result.get("png"):
            cov_png = self._last_coverage_result["png"]
            cov_dir = os.path.dirname(cov_png)
            if os.path.isdir(cov_dir):
                keep_dirs.add(os.path.abspath(cov_dir))

        try:
            entries = list(os.scandir(self.cache_dir))
        except OSError:
            entries = []
        freed = 0
        removed = 0
        for entry in entries:
            try:
                if os.path.abspath(entry.path) in keep_dirs:
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

    def export_model(self, fmt: str) -> None:
        """Export the last propagation result in the chosen format."""
        from . import export_controller

        # Always use coverage result for sidebar export
        res = self._last_coverage_result or (self._last_result if (self._last_result and self._last_result.get("png")) else None)

        # Fallback: if map is showing coverage but in-memory dict/file was purged
        if (not res or not res.get("png") or not os.path.exists(res["png"])) and hasattr(self, "map") and getattr(self.map, "_coverage", None):
            try:
                data_uri, bbox_coords = self.map._coverage
                if data_uri and data_uri.startswith("data:image/png;base64,"):
                    b64_data = data_uri.split(",", 1)[1]
                    rec_dir = os.path.join(self.cache_dir, "active_coverage")
                    os.makedirs(rec_dir, exist_ok=True)
                    rec_png = os.path.join(rec_dir, "coverage.png")
                    with open(rec_png, "wb") as f:
                        f.write(base64.b64decode(b64_data))
                    s, w, n, e = bbox_coords
                    p_form = self.form.collect() if hasattr(self, "form") else {}
                    res = {
                        "png": rec_png,
                        "bbox": (n, e, s, w),
                        "params": p_form,
                    }
                    self._last_coverage_result = res
                    self._last_result = res
            except Exception as exc:
                logger.warning("Failed to recover coverage from map: %s", exc)

        color_file = None
        if res and isinstance(res.get("params"), dict):
            color_file = res["params"].get("color_file")
        if not color_file and hasattr(self, "form") and hasattr(self.form, "color_path"):
            color_file = self.form.color_path.text().strip() or None

        mode_idx = 0
        if hasattr(self, "form") and hasattr(self.form, "kmz_contour_mode"):
            mode_idx = self.form.kmz_contour_mode.currentIndex()

        params = (res.get("params") if res and isinstance(res.get("params"), dict) else None) or (self._pending[0] if getattr(self, "_pending", None) else None)
        if not params and hasattr(self, "form"):
            try:
                params = self.form.collect()
            except Exception:
                params = {}

        export_controller.export_model(
            self,
            fmt=fmt,
            result=res,
            params=params,
            cache_dir=self.cache_dir,
            color_file=color_file,
            contour_mode_idx=mode_idx,
            status_callback=self._set_status,
        )

    def _export_rm_png(self, result: dict, base: str) -> None:
        """Export a full Radio Mobile-style picture + automatic KML sidecar."""
        from . import export_controller
        p = (self._pending[0] if self._pending else {}) or {}
        export_controller.export_coverage_rm_png(self, result, p, base, self._set_status)

    def _export_raster_txt(self, result: dict, path: str) -> None:
        """Wrap the engine's raw raster dump in a Radio-Mobile-compatible file."""
        from . import export_controller
        p = (self._pending[0] if self._pending else {}) or {}
        export_controller.export_raster_txt(result, p, path, self.cache_dir)

    def export_dem_tif(self) -> None:
        """Export DEM clip ter-potong untuk QGIS + validasi lubang hitam di Tx."""
        try:
            p = self.form.collect()
        except Exception as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        from . import export_controller
        export_controller.export_dem_tif(self, p, self.cache_dir, self._set_status, self.terminal)

    def _export_kmz(self, result: dict, png: str, bbox, path: str, base: str,
                    flat: bool = True, relief_weight: float = 0.30) -> None:
        """Build a KMZ (zipped KML GroundOverlay + PNG image)."""
        from . import export_controller
        color_file = None
        if result and isinstance(result.get("params"), dict):
            color_file = result["params"].get("color_file")
        if not color_file and hasattr(self, "form") and hasattr(self.form, "color_path"):
            color_file = self.form.color_path.text().strip() or None

        export_controller.export_coverage_kmz(
            self, result, png, bbox, path, base,
            color_file=color_file, relief_weight=relief_weight,
        )


