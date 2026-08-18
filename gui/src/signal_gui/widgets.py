"""Sidebar parameter form for the Signal-Server GUI with CloudRF Dark Accordion UI.

Collects all simulation inputs and exposes ``collect()`` -> canonical dict and
``load()`` to restore a saved profile. Field names match ``params.build_argv``.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QComboBox, QCheckBox, QPushButton, QFileDialog, QPlainTextEdit, QStackedWidget,
    QHBoxLayout, QLabel, QSpinBox, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Signal, Qt

from . import params as params_mod
from . import coords
from .icons import pixmap as _pixmap

_SECTION_ICON = {
    "tx": "tower", "signal": "wifi", "feeder": "database", "antenna": "antenna",
    "rx": "radio", "model": "share", "env": "leaf", "output": "layers",
}


def _browse(parent, caption: str, filter_: str, save: bool = False) -> Optional[str]:
    dlg = QFileDialog(parent, caption, "", filter_)
    if save:
        if dlg.exec() and dlg.selectedFiles():
            return dlg.selectedFiles()[0]
    else:
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        if dlg.exec() and dlg.selectedFiles():
            return dlg.selectedFiles()[0]
    return None


def _make_info_btn(tooltip: str) -> QPushButton:
    """Create a circular '?' info button."""
    btn = QPushButton("?")
    btn.setToolTip(tooltip)
    btn.setFixedSize(18, 18)
    btn.setStyleSheet("""
        QPushButton {
            background-color: #373E47;
            color: #A0AEC0;
            border: none;
            border-radius: 9px;
            font-size: 11px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #4A5568;
            color: #FFFFFF;
        }
    """)
    return btn


class CollapsibleSection(QFrame):
    """Collapsible Dark Accordion Section for CloudRF Sidebar."""

    def __init__(self, key: str, icon_name: str, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.expanded = expanded
        self.setObjectName(f"section_{key}")
        self.setStyleSheet("""
            QFrame#section_{key} {{
                background-color: #23272B;
                border: 1px solid #1E2226;
                border-radius: 4px;
                margin-bottom: 3px;
            }}
        """.format(key=key))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar
        self.header = QFrame()
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setStyleSheet("""
            QFrame {
                background-color: %s;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QFrame:hover {
                background-color: #343A40;
            }
        """ % ("#343A40" if expanded else "#2B3036"))

        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(4, 2, 4, 2)
        h_layout.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_pixmap(icon_name, 15, "#CBD5E0"))
        icon_lbl.setStyleSheet("margin: 0 2px;")

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #E2E8F0; font-size: 13px; font-weight: 600;")

        self.arrow_lbl = QLabel("v" if expanded else "<")
        self.arrow_lbl.setStyleSheet("color: #A0AEC0; font-weight: bold; font-size: 12px;")

        h_layout.addWidget(icon_lbl)
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()
        h_layout.addWidget(self.arrow_lbl)

        main_layout.addWidget(self.header)

        # Content widget
        self.content = QWidget()
        self.content.setVisible(expanded)
        self.content_layout = QFormLayout(self.content)
        self.content_layout.setContentsMargins(10, 8, 10, 10)
        self.content_layout.setSpacing(8)
        self.content_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        main_layout.addWidget(self.content)

        self.header.mousePressEvent = self._toggle

    def _toggle(self, event=None):
        self.set_expanded(not self.expanded)

    def set_expanded(self, exp: bool):
        self.expanded = exp
        self.content.setVisible(exp)
        self.arrow_lbl.setText("v" if exp else "<")
        self.header.setStyleSheet("""
            QFrame {
                background-color: %s;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QFrame:hover { background-color: #343A40; }
        """ % ("#343A40" if exp else "#2B3036"))


class SiteCoordWidget(QWidget):
    """Coordinate entry supporting DD, DMS and MGRS formats."""

    changed = Signal()  # emitted whenever any coordinate field is edited

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.fmt = QComboBox()
        self.fmt.addItems(["Decimal (DD)", "DMS", "MGRS"])
        self.fmt.setStyleSheet("""
            QComboBox {
                background: #1B1E22;
                color: #CBD5E0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 3px;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.fmt)

        self.stack = QStackedWidget()

        # DD
        dd = QWidget()
        dl = QFormLayout(dd)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        self.dd_lat = QLineEdit(); self.dd_lon = QLineEdit()
        for w in (self.dd_lat, self.dd_lon):
            w.setStyleSheet("background: #1B1E22; color: #E2E8F0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 11px;")
        dl.addRow("Lat", self.dd_lat); dl.addRow("Lon", self.dd_lon)
        self.stack.addWidget(dd)

        # DMS
        dms = QWidget()
        dl2 = QFormLayout(dms)
        dl2.setContentsMargins(0, 0, 0, 0)
        dl2.setSpacing(4)
        self.dms_lat = QLineEdit(); self.dms_lat_hemi = QComboBox()
        self.dms_lat_hemi.addItems(["N", "S"])
        self.dms_lon = QLineEdit(); self.dms_lon_hemi = QComboBox()
        self.dms_lon_hemi.addItems(["E", "W"])
        for w in (self.dms_lat, self.dms_lon):
            w.setStyleSheet("background: #1B1E22; color: #E2E8F0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 11px;")
        for w in (self.dms_lat_hemi, self.dms_lon_hemi):
            w.setStyleSheet("background: #1B1E22; color: #CBD5E0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 11px;")
        dl2.addRow("Lat dms", self.dms_lat); dl2.addRow("Hemi", self.dms_lat_hemi)
        dl2.addRow("Lon dms", self.dms_lon); dl2.addRow("Hemi", self.dms_lon_hemi)
        self.stack.addWidget(dms)

        # MGRS
        mgrs = QWidget()
        ml = QFormLayout(mgrs)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(4)
        self.mgrs = QLineEdit()
        self.mgrs.setStyleSheet("background: #1B1E22; color: #E2E8F0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 11px;")
        ml.addRow("MGRS", self.mgrs)
        self.stack.addWidget(mgrs)

        layout.addWidget(self.stack)
        self.fmt.currentIndexChanged.connect(self.stack.setCurrentIndex)
        for _w in (self.dd_lat, self.dd_lon, self.dms_lat, self.dms_lon, self.mgrs):
            _w.textChanged.connect(lambda: self.changed.emit())
        self.dms_lat_hemi.currentTextChanged.connect(lambda: self.changed.emit())
        self.dms_lon_hemi.currentTextChanged.connect(lambda: self.changed.emit())

    def get(self):
        idx = self.fmt.currentIndex()
        if idx == 0:
            return (float(self.dd_lat.text()), float(self.dd_lon.text()))
        if idx == 1:
            lat = coords.parse_dms(self.dms_lat.text() + self.dms_lat_hemi.currentText())
            lon = coords.parse_dms(self.dms_lon.text() + self.dms_lon_hemi.currentText())
            return (lat, lon)
        return coords.mgrs_to_latlon(self.mgrs.text())

    def set(self, lat: Optional[float], lon: Optional[float]) -> None:
        if lat is None or lon is None:
            return
        self.dd_lat.setText(f"{lat:.6f}")
        self.dd_lon.setText(f"{lon:.6f}")


class ParameterForm(QWidget):
    erp_changed = Signal(float)
    pick_requested = Signal(str)  # "tx" or "rx"
    tx_changed = Signal()         # tx coordinate edited in the form
    rx_changed = Signal()         # rx coordinate edited in the form
    start_requested = Signal()
    stop_requested = Signal()
    export_requested = Signal(str)  # selected export format (e.g. "KMZ")

    def __init__(self, signal_server_root: str = "", parent=None):
        super().__init__(parent)
        self.ss_root = signal_server_root
        self.sections: dict[str, CollapsibleSection] = {}
        self.is_locked = False
        self._build()

    def _icon(self, name: str, size: int = 16, color: str = "#CBD5E0"):
        """Build an icon from the embedded SVG set for use on buttons."""
        from PySide6.QtGui import QIcon
        return QIcon(_pixmap(name, size, color))

    def _add_row_with_info(self, form_layout: QFormLayout, label_text: str, widget: QWidget, tooltip: str = ""):
        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(6)
        row_l.addWidget(widget, 1)
        if tooltip:
            info_btn = _make_info_btn(tooltip)
            row_l.addWidget(info_btn)
        
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #CBD5E0; font-size: 11px; font-weight: 500;")
        form_layout.addRow(lbl, row_w)

    def _section(self, key: str, icon: str, title: str, expanded: bool = False) -> QFormLayout:
        sec = CollapsibleSection(key, icon, title, expanded=expanded, parent=self)
        self.layout.addWidget(sec)
        self.sections[key] = sec
        return sec.content_layout

    def toggle_section(self, key: str):
        if key in self.sections:
            sec = self.sections[key]
            sec.set_expanded(not sec.expanded)

    def _build(self) -> None:
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(4)

        # Combo / SpinBox dark input stylesheet
        input_ss = """
            QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
                background-color: #1B1E22;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1B1E22;
                color: #E2E8F0;
                selection-background-color: #3182CE;
            }
        """
        btn_ss = """
            QPushButton {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4A5568; }
        """
        self.setStyleSheet(input_ss)

        # -- 1. Site / Tx
        fl = self._section("tx", _SECTION_ICON["tx"], "Site / Tx", expanded=False)
        self.units = QComboBox(); self.units.addItems(["Metric", "Imperial"])
        self._add_row_with_info(fl, "Units", self.units, "Unit system (Metric / Imperial)")
        self.tx_coord = SiteCoordWidget()
        self.tx_coord.set(51.849, -2.2299)
        fl.addRow(QLabel("Coordinates"), self.tx_coord)
        self.btn_pick_tx = QPushButton("Pick on map (Tx)")
        self.btn_pick_tx.setStyleSheet(btn_ss)
        self.btn_pick_tx.clicked.connect(lambda: self.pick_requested.emit("tx"))
        fl.addRow(self.btn_pick_tx)
        self.tx_height = QDoubleSpinBox(); self.tx_height.setRange(0, 10000); self.tx_height.setValue(30)
        self._add_row_with_info(fl, "Height (m)", self.tx_height, "Transmitter antenna height above ground")
        self.frequency = QDoubleSpinBox(); self.frequency.setRange(0.1, 100000); self.frequency.setValue(900)
        self._add_row_with_info(fl, "Frequency (MHz)", self.frequency, "Operating frequency in MHz")
        self.dem_res = QComboBox(); self.dem_res.addItems(["90 m (dem3)", "30 m (dem1)", "15 m TIF"])
        self._add_row_with_info(fl, "Auto DEM resolution", self.dem_res, "Elevation data resolution")

        # -- 2. Signal
        fl = self._section("signal", _SECTION_ICON["signal"], "'T' Signal", expanded=False)
        self.rf_power = QDoubleSpinBox(); self.rf_power.setRange(0, 1e7); self.rf_power.setValue(100)
        self._add_row_with_info(fl, "RF power (W)", self.rf_power, "Transmitter power output in Watts")
        self.tx_gain = QDoubleSpinBox(); self.tx_gain.setRange(-50, 50); self.tx_gain.setValue(10)
        self._add_row_with_info(fl, "Tx gain (dBi)", self.tx_gain, "Transmitter antenna gain in dBi")

        # -- 3. Feeder
        fl = self._section("feeder", _SECTION_ICON["feeder"], "Feeder", expanded=False)
        self.cable_loss = QDoubleSpinBox(); self.cable_loss.setRange(0, 50); self.cable_loss.setValue(0)
        self._add_row_with_info(fl, "Cable loss (dB)", self.cable_loss, "Transmission line / cable loss")
        self.erp_label = QLabel("ERP: - W"); self.erp_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        self.eirp_label = QLabel("EIRP: - dBm"); self.eirp_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        fl.addRow(self.erp_label); fl.addRow(self.eirp_label)
        for w in (self.rf_power, self.tx_gain, self.cable_loss):
            w.valueChanged.connect(self._update_erp)

        # -- 4. Antenna
        fl = self._section("antenna", _SECTION_ICON["antenna"], "Antenna", expanded=False)
        self.ant_btn = QPushButton("Select pattern (.az/.el)...")
        self.ant_btn.setStyleSheet(btn_ss)
        self.ant_path = QLabel("")
        self.ant_path.setStyleSheet("color: #A0AEC0; font-size: 10px;")
        self.ant_btn.clicked.connect(self._pick_antenna)
        fl.addRow(self.ant_btn, self.ant_path)
        self.pol = QComboBox(); self.pol.addItems(["vertical", "horizontal"])
        self._add_row_with_info(fl, "Polarisation", self.pol, "Antenna polarization")
        self.azimuth = QDoubleSpinBox(); self.azimuth.setRange(0, 359); self.azimuth.setValue(0)
        self._add_row_with_info(fl, "Azimuth (deg)", self.azimuth, "Antenna orientation / azimuth angle")
        self.downtilt = QDoubleSpinBox(); self.downtilt.setRange(-10, 90); self.downtilt.setValue(0)
        self._add_row_with_info(fl, "Downtilt (deg)", self.downtilt, "Electrical / mechanical downtilt angle")
        self.downtilt_dir = QDoubleSpinBox(); self.downtilt_dir.setRange(0, 359); self.downtilt_dir.setValue(0)
        self._add_row_with_info(fl, "Downtilt dir (deg)", self.downtilt_dir, "Downtilt direction angle")

        # -- 5. Mobile / Rx
        fl = self._section("rx", _SECTION_ICON["rx"], "Mobile / Rx", expanded=False)
        self.rx_coord = SiteCoordWidget()
        self.rx_coord.set(51.75, -2.10)
        fl.addRow(QLabel("Coordinates"), self.rx_coord)
        self.tx_coord.changed.connect(self.tx_changed)
        self.rx_coord.changed.connect(self.rx_changed)
        self.btn_pick_rx = QPushButton("Pick on map (Rx)")
        self.btn_pick_rx.setStyleSheet(btn_ss)
        self.btn_pick_rx.clicked.connect(lambda: self.pick_requested.emit("rx"))
        fl.addRow(self.btn_pick_rx)
        self.rx_height = QDoubleSpinBox(); self.rx_height.setRange(0, 10000); self.rx_height.setValue(1.5)
        self._add_row_with_info(fl, "Height (m)", self.rx_height, "Receiver height above ground")
        self.rx_gain = QDoubleSpinBox(); self.rx_gain.setRange(-50, 50); self.rx_gain.setValue(0)
        self._add_row_with_info(fl, "Rx gain (dBd)", self.rx_gain, "Receiver antenna gain in dBd")
        self.rx_thr = QDoubleSpinBox(); self.rx_thr.setRange(-200, 100); self.rx_thr.setValue(-110)
        self._add_row_with_info(fl, "Rx threshold (dBm)", self.rx_thr, "Minimum required signal threshold")

        # -- 6. Model (EXPANDED BY DEFAULT, EXACTLY MATCHING CLOUDRF SCREENSHOT!)
        fl = self._section("model", _SECTION_ICON["model"], "Model", expanded=True)
        self.model = QComboBox()
        for label, val in params_mod.MODELS:
            display_label = "Okumura-Hata (0.15-1.5GHz)" if val == 3 else label
            self.model.addItem(display_label, val)
        # Default to Okumura-Hata matching CloudRF
        idx = self.model.findData(3)
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self._add_row_with_info(fl, "Model", self.model, "Radio propagation model choice")

        self.reliability = QComboBox()
        self.reliability.addItems(["50%", "80%", "90%", "95%", "99%"])
        self._add_row_with_info(fl, "Reliability", self.reliability, "ITM statistical time/location reliability")

        self.context = QComboBox()
        self.context.addItems(["Average / Mixed", "Urban", "Suburban", "Rural"])
        self._add_row_with_info(fl, "Context", self.context, "Propagation environment classification")

        self.diffraction = QComboBox()
        self.diffraction.addItems(["Off (LOS)", "Knife-edge (KED)", "Deygout"])
        self._add_row_with_info(fl, "Diffraction", self.diffraction, "Diffraction loss routine")

        # Hidden fields for backward compatibility
        self.knife = QCheckBox("Knife-edge diffraction (-ked)")
        self.knife.setVisible(False)

        # -- 7. Environment
        fl = self._section("env", _SECTION_ICON["env"], "Environment", expanded=False)
        self.climate = QComboBox()
        self.climate.addItem("(default)", 0)
        for v, label in params_mod.CLIMATE_ZONES:
            self.climate.addItem(f"{v}: {label}", v)
        self._add_row_with_info(fl, "Radio climate", self.climate, "Radio climate zone")
        self.clutter_btn = QPushButton("Select clutter (.clt)...")
        self.clutter_btn.setStyleSheet(btn_ss)
        self.clutter_path = QLabel("")
        self.clutter_path.setStyleSheet("color: #A0AEC0; font-size: 10px;")
        self.clutter_btn.clicked.connect(lambda: self._pick(self.clutter_path, "Clutter (*.clt)"))
        fl.addRow(self.clutter_btn, self.clutter_path)
        self.gc = QDoubleSpinBox(); self.gc.setRange(0, 1000); self.gc.setValue(0)
        self._add_row_with_info(fl, "Ground clutter (m)", self.gc, "Clutter height in meters")
        self.obstacles = QPlainTextEdit(); self.obstacles.setPlaceholderText("lat,lon,height per line (-udt)")
        self.obstacles.setMaximumHeight(60)
        self.obstacles.setStyleSheet("background: #1B1E22; color: #E2E8F0; border: 1px solid #3F474F; font-size: 11px;")
        fl.addRow("Obstacles", self.obstacles)

        # -- 8. Output / Engine
        fl = self._section("output", _SECTION_ICON["output"], "Output", expanded=False)
        self.engine = QComboBox(); self.engine.addItems(list(params_mod.ENGINES.keys()))
        self._add_row_with_info(fl, "Engine", self.engine, "Signal-Server engine build")
        self.terrain = QComboBox(); self.terrain.addItems(["SDF (terrain)", "LIDAR (.asc)"])
        self._add_row_with_info(fl, "Terrain source", self.terrain, "Elevation data source format")
        self.sdf_btn = QPushButton("SDF directory...")
        self.sdf_btn.setStyleSheet(btn_ss)
        self.sdf_path = QLabel("")
        self.sdf_path.setStyleSheet("color: #A0AEC0; font-size: 10px;")
        self.sdf_btn.clicked.connect(self._pick_dir)
        fl.addRow(self.sdf_btn, self.sdf_path)
        self.lidar_btn = QPushButton("LIDAR file...")
        self.lidar_btn.setStyleSheet(btn_ss)
        self.lidar_path = QLabel("")
        self.lidar_path.setStyleSheet("color: #A0AEC0; font-size: 10px;")
        self.lidar_btn.clicked.connect(lambda: self._pick(self.lidar_path, "LIDAR (*.asc)"))
        fl.addRow(self.lidar_btn, self.lidar_path)
        self.resolution = QComboBox()
        for r in params_mod.RESOLUTIONS:
            self.resolution.addItem(str(r), r)
        self.resolution.setCurrentText("1200")
        self._add_row_with_info(fl, "Resolution", self.resolution, "Tile pixel resolution")
        self.radius = QDoubleSpinBox(); self.radius.setRange(0.1, 10000); self.radius.setValue(30)
        self._add_row_with_info(fl, "Radius (km)", self.radius, "Plot coverage radius in km")
        self.color_btn = QPushButton("Color table...")
        self.color_btn.setStyleSheet(btn_ss)
        self.color_path = QLabel("")
        self.color_path.setStyleSheet("color: #A0AEC0; font-size: 10px;")
        default_color = os.path.join(self.ss_root, "color", "rainbow.dcf") if self.ss_root else ""
        if default_color and os.path.exists(default_color):
            self.color_path.setText(default_color)
        self.color_btn.clicked.connect(lambda: self._pick(self.color_path, "Color (*.dcf *.scf)"))
        fl.addRow(self.color_btn, self.color_path)
        self.dbm_color = QCheckBox("dBm colour scale")
        self.dbm_color.setChecked(True)
        self.dbm_color.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl.addRow(self.dbm_color)

        self._update_erp()

        # Action Buttons row (Lock + Green Run)
        btn_box = QWidget()
        btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(4, 10, 4, 10)
        btn_layout.setSpacing(10)

        self.btn_lock = QPushButton()
        self.btn_lock.setIcon(self._icon("lock", 18, "#FFFFFF"))
        self.btn_lock.setToolTip("Lock Form Inputs")
        self.btn_lock.setFixedSize(40, 40)
        self.btn_lock.setStyleSheet("""
            QPushButton {
                background-color: #0088CC;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #00A3E0; }
        """)
        self.btn_lock.clicked.connect(self._toggle_lock)

        self.btn_run = QPushButton()
        self.btn_run.setIcon(self._icon("play", 18, "#FFFFFF"))
        self.btn_run.setToolTip("Calculate / Run Propagation Plot")
        self.btn_run.setFixedHeight(40)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #2ECC71;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 20px;
            }
            QPushButton:hover { background-color: #27AE60; }
            QPushButton:disabled { background-color: #555; }
        """)
        self.btn_run.clicked.connect(lambda: self.start_requested.emit())

        btn_layout.addWidget(self.btn_lock)
        btn_layout.addWidget(self.btn_run, 1)
        self.layout.addWidget(btn_box)

        # Output / Export Model Box
        export_box = QFrame()
        export_box.setStyleSheet("""
            QFrame {
                background-color: #1E2226;
                border: 1px solid #2D3339;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        export_layout = QVBoxLayout(export_box)
        export_layout.setContentsMargins(6, 4, 6, 6)
        export_layout.setSpacing(6)

        exp_lbl = QLabel("A (MODELS)")
        exp_lbl.setStyleSheet("color: #CBD5E0; font-size: 11px; font-weight: bold; font-family: monospace;")
        exp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        export_layout.addWidget(exp_lbl)

        row_exp = QHBoxLayout()
        row_exp.setSpacing(6)
        self.export_fmt = QComboBox()
        self.export_fmt.addItems(["KMZ", "PNG", "GeoTIFF", "KMZ (3D)", "SHP"])
        self.export_fmt.setStyleSheet("""
            QComboBox {
                background: #121417;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 11px;
            }
        """)

        self.btn_export = QPushButton()
        self.btn_export.setIcon(self._icon("download", 14, "#E2E8F0"))
        self.btn_export.setToolTip("Download Model Output")
        self.btn_export.setFixedSize(30, 26)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #3182CE; }
        """)
        self.btn_export.clicked.connect(
            lambda: self.export_requested.emit(self.export_fmt.currentText()))

        row_exp.addWidget(self.export_fmt, 1)
        row_exp.addWidget(self.btn_export)
        export_layout.addLayout(row_exp)

        self.layout.addWidget(export_box)

    def _toggle_lock(self):
        self.is_locked = not self.is_locked
        self.btn_lock.setStyleSheet("""
            QPushButton {
                background-color: %s;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-size: 18px;
            }
        """ % ("#E53E3E" if self.is_locked else "#0088CC"))
        self.setEnabled(not self.is_locked)
        # Keep lock button interactive
        self.btn_lock.setEnabled(True)

    def _pick(self, label: QLabel, filter_: str) -> None:
        p = _browse(self, "Select file", filter_)
        if p:
            label.setText(p)

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select SDF directory")
        if d:
            self.sdf_path.setText(d)

    def _pick_antenna(self) -> None:
        p = _browse(self, "Select antenna pattern", "Antenna (*.az *.el)")
        if p:
            base, _ = os.path.splitext(p)
            self.ant_path.setText(base)

    def _update_erp(self) -> None:
        erp = params_mod.compute_erp(
            self.rf_power.value(), self.tx_gain.value(), self.cable_loss.value()
        )
        eirp = params_mod.eirp_dbm(erp)
        self.erp_label.setText(f"ERP: {erp:.3f} W")
        self.eirp_label.setText(f"EIRP: {eirp:.2f} dBm")
        self.erp_changed.emit(erp)

    # ------------------------------------------------------------------ data
    def collect(self) -> dict:
        tx_lat, tx_lon = self.tx_coord.get()
        rx_lat, rx_lon = self.rx_coord.get()
        
        # Determine model integer
        model_val = self.model.currentData()
        if model_val is None:
            model_val = 3  # Default Okumura-Hata
            
        rel_str = self.reliability.currentText().replace("%", "")
        rel_val = int(rel_str) if rel_str.isdigit() else 50

        ctx_str = self.context.currentText()
        context_pe = 1 if "Urban" in ctx_str else (2 if "Suburban" in ctx_str else 3)
        
        diff_str = self.diffraction.currentText()
        knife_edge = "Knife-edge" in diff_str or self.knife.isChecked()

        climate = self.climate.currentData() or None
        dem_res_map = {0: 3, 1: 1, 2: 15}
        units = "metric" if self.units.currentText() == "Metric" else "imperial"

        d = {
            "tx_lat": tx_lat, "tx_lon": tx_lon,
            "tx_height": self.tx_height.value(),
            "frequency_mhz": self.frequency.value(),
            "rf_power_w": self.rf_power.value(),
            "tx_gain_dbi": self.tx_gain.value(),
            "cable_loss_db": self.cable_loss.value(),
            "antenna_basename": self.ant_path.text() or None,
            "polarization": self.pol.currentText(),
            "azimuth_deg": self.azimuth.value(),
            "downtilt_deg": self.downtilt.value(),
            "downtilt_dir_deg": self.downtilt_dir.value(),
            "rx_lat": rx_lat, "rx_lon": rx_lon,
            "rx_height": self.rx_height.value(),
            "rx_gain_dbd": self.rx_gain.value(),
            "rx_threshold_dbm": self.rx_thr.value(),
            "model_pm": model_val,
            "reliability": rel_val,
            "context_pe": context_pe,
            "knife_edge": knife_edge,
            "climate_zone": climate,
            "clutter_file": self.clutter_path.text() or None,
            "ground_clutter": self.gc.value(),
            "obstacles": list(params_mod.iter_obstacles(self.obstacles.toPlainText())),
            "engine": self.engine.currentText(),
            "terrain_source": "lidar" if self.terrain.currentText().startswith("LIDAR") else "sdf",
            "sdf_dir": self.sdf_path.text() or None,
            "lidar_file": self.lidar_path.text() or None,
            "resolution": self.resolution.currentData(),
            "radius": self.radius.value(),
            "color_file": self.color_path.text() or None,
            "dbm_color": self.dbm_color.isChecked(),
            "units": units,
            "dem_resolution": dem_res_map[self.dem_res.currentIndex()],
        }
        return d


