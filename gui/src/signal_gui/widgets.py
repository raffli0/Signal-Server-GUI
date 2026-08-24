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
from PySide6.QtGui import QWheelEvent

from . import params as params_mod
from . import coords
from .icons import pixmap as _pixmap


class FocusWheelSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores the mouse wheel unless it has keyboard focus.

    Prevents accidentally changing a value while scrolling the panel past a
    field that has the +/- stepper buttons.
    """

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def textFromValue(self, val: float) -> str:
        # Clean display: "1200.00" -> "1200", "1.50" -> "1.5", "0.10" -> "0.1".
        s = f"{val:.2f}".rstrip("0").rstrip(".")
        return s or "0"


_SECTION_ICON = {
    "tx": "tower", "signal": "wifi", "feeder": "database", "antenna": "antenna",
    "rx": "radio", "model": "share", "env": "leaf", "output": "layers",
}


def _browse(parent, caption: str, filter_: str, start_dir: Optional[str] = None, save: bool = False) -> Optional[str]:
    dlg = QFileDialog(parent, caption, start_dir or "", filter_)
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
    demnas_dir_picked = Signal()    # DEMNAS folder (re)selected, even if unchanged

    def __init__(self, signal_server_root: str = "", parent=None):
        super().__init__(parent)
        self.ss_root = signal_server_root
        self.sections: dict[str, CollapsibleSection] = {}
        self.is_locked = False
        self._ground_elev: dict[str, Optional[float]] = {"tx": None, "rx": None}
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

    def _sub_label(self, text: str) -> QLabel:
        """Small uppercase group divider used inside a merged section."""
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            "color: #718096; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.5px; padding-top: 6px; padding-bottom: 2px;"
        )
        return lbl

    def _add_gated_row(self, form_layout: QFormLayout, label_text: str,
                       widget: QWidget, tooltip: str = "", gate_key: str = None
                       ) -> QLabel:
        """Like ``_add_row_with_info`` but registers the row for model-gating.

        A small badge (hidden by default) is appended to the row; it shows why
        the control is irrelevant for the currently selected propagation model.
        """
        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(6)
        row_l.addWidget(widget, 1)
        badge = QLabel("")
        badge.setStyleSheet("color:#718096; font-size:10px; font-style:italic;")
        badge.setVisible(False)
        row_l.addWidget(badge)
        if tooltip:
            row_l.addWidget(_make_info_btn(tooltip))
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color:#CBD5E0; font-size:11px; font-weight:500;")
        form_layout.addRow(lbl, row_w)
        if gate_key:
            self._gated_rows.append((lbl, widget, badge, gate_key))
        return badge

    def _apply_model_gating(self) -> None:
        """Grey-out + badge the model-dependent controls per selected model.

        Uses :func:`params_mod.option_states_for_model` so the UI matches the
        engine's actual behaviour (a flag the model ignores is a silent no-op).
        """
        if not getattr(self, "_gated_rows", None):
            return
        model_val = self.model.currentData()
        states = params_mod.option_states_for_model(model_val)
        mname = params_mod.model_name(model_val)
        for lbl, widget, badge, key in self._gated_rows:
            state = states.get(key, params_mod.OPTION_NA)
            if state == params_mod.OPTION_ACTIVE:
                widget.setEnabled(True)
                lbl.setStyleSheet("color:#CBD5E0; font-size:11px; font-weight:500;")
                badge.setVisible(False)
                continue
            widget.setEnabled(False)
            lbl.setStyleSheet("color:#5A6573; font-size:11px; font-weight:500;")
            if state == params_mod.OPTION_BUILTIN:
                badge.setStyleSheet(
                    "color:#D69E2E; font-size:10px; font-style:italic;")
                badge.setText(f"sudah built-in di {mname}")
            else:
                badge.setStyleSheet(
                    "color:#718096; font-size:10px; font-style:italic;")
                badge.setText(f"tidak dipakai oleh {mname}")
            badge.setVisible(True)

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

        # -- 1. Site / Tx  (merged: site + signal + feeder + antenna)
        fl = self._section("tx", _SECTION_ICON["tx"], "Site / Tx", expanded=False)
        self.units = QComboBox(); self.units.addItems(["Metric", "Imperial"])
        self._add_row_with_info(fl, "Units", self.units, "Unit system (Metric / Imperial)")
        self.tx_name = QLineEdit()
        self.tx_name.setPlaceholderText("Site name (e.g. BTS-01)")
        self._add_row_with_info(fl, "Site name", self.tx_name, "Label for this transmitter site")
        self.tx_network = QLineEdit()
        self.tx_network.setPlaceholderText("Network (e.g. Telkomsel)")
        self._add_row_with_info(fl, "Network", self.tx_network, "Operator / network identifier")
        self.tx_coord = SiteCoordWidget()
        self.tx_coord.set(-6.916667, 107.6083)
        fl.addRow(QLabel("Coordinates"), self.tx_coord)
        self.btn_pick_tx = QPushButton("Pick on map (Tx)")
        self.btn_pick_tx.setStyleSheet(btn_ss)
        self.btn_pick_tx.clicked.connect(lambda: self.pick_requested.emit("tx"))
        fl.addRow(self.btn_pick_tx)
        self.tx_height = FocusWheelSpinBox(); self.tx_height.setRange(0, 10000); self.tx_height.setValue(1)
        self._add_row_with_info(fl, "Height AGL (m)", self.tx_height, "Transmitter antenna height above ground")
        self.tx_amsl = QLabel("Elevasi tanah: \u2014")
        self._style_amsl_label(self.tx_amsl)
        fl.addRow(self.tx_amsl)
        self.tx_height.valueChanged.connect(lambda _: self._refresh_amsl_labels())
        self.frequency = FocusWheelSpinBox(); self.frequency.setRange(0.1, 100000); self.frequency.setValue(900)
        self._add_row_with_info(fl, "Frequency (MHz)", self.frequency, "Operating frequency in MHz")
        self.dem_res = QComboBox(); self.dem_res.addItems(["90 m (dem3)", "30 m (dem1)", "15 m TIF"])
        self._add_row_with_info(
            fl, "Auto DEM resolution", self.dem_res,
            "Resolusi data elevasi. Mode Online: memilih produk Viewfinder "
            "(dem3≈90 m, dem1≈30 m, TIF15). Mode Offline DEMNAS: target "
            "resolusi konversi terrain LIDAR (3\"≈90 m, 1\"≈30 m, 15 m), "
            "otomatis dibatasi ukuran file maksimum. Tidak berpengaruh pada "
            "mode SDF (resolusi mengikuti varian engine).")

        # Signal
        fl.addRow(self._sub_label("Signal"))
        self.rf_power = FocusWheelSpinBox(); self.rf_power.setRange(0, 1e7); self.rf_power.setValue(1)
        self._add_row_with_info(fl, "RF power (Watt)", self.rf_power, "Transmitter power output in Watts")
        self.tx_gain = FocusWheelSpinBox(); self.tx_gain.setRange(-50, 50); self.tx_gain.setValue(10)
        self._add_row_with_info(fl, "Tx gain (dBi)", self.tx_gain, "Transmitter antenna gain in dBi")

        # Feeder
        fl.addRow(self._sub_label("Feeder"))
        self.cable_loss = FocusWheelSpinBox(); self.cable_loss.setRange(0, 50); self.cable_loss.setValue(0)
        self._add_row_with_info(fl, "Cable loss (dB)", self.cable_loss, "Transmission line / cable loss")
        self.erp_label = QLabel("ERP: - W"); self.erp_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        self.eirp_label = QLabel("EIRP: - dBm"); self.eirp_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        fl.addRow(self.erp_label); fl.addRow(self.eirp_label)
        for w in (self.rf_power, self.tx_gain, self.cable_loss):
            w.valueChanged.connect(self._update_erp)

        # Antenna
        fl.addRow(self._sub_label("Antenna"))
        self.ant_btn = QPushButton("Select pattern (.az/.el)...")
        self.ant_btn.setStyleSheet(btn_ss)
        self.ant_path = QLineEdit()
        self.ant_path.setReadOnly(True)
        self.ant_path.setPlaceholderText("No pattern selected")
        self.ant_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.ant_btn.clicked.connect(self._pick_antenna)
        fl.addRow(self.ant_btn, self.ant_path)
        self.pol = QComboBox(); self.pol.addItems(["vertical", "horizontal"])
        self._add_row_with_info(fl, "Polarisation", self.pol, "Antenna polarization")
        self.azimuth = FocusWheelSpinBox(); self.azimuth.setRange(0, 359); self.azimuth.setValue(0)
        self._add_row_with_info(fl, "Azimuth (deg)", self.azimuth, "Antenna orientation / azimuth angle")
        self.downtilt = FocusWheelSpinBox(); self.downtilt.setRange(-10, 90); self.downtilt.setValue(0)
        self._add_row_with_info(fl, "Downtilt (deg)", self.downtilt, "Electrical / mechanical downtilt angle")
        self.downtilt_dir = FocusWheelSpinBox(); self.downtilt_dir.setRange(0, 359); self.downtilt_dir.setValue(0)
        self._add_row_with_info(fl, "Downtilt dir (deg)", self.downtilt_dir, "Downtilt direction angle")

        # -- 2. Mobile / Rx
        fl = self._section("rx", _SECTION_ICON["rx"], "Mobile / Rx", expanded=False)
        self.rx_name = QLineEdit()
        self.rx_name.setPlaceholderText("Site name (e.g. UE-01)")
        self._add_row_with_info(fl, "Site name", self.rx_name, "Label for this receiver site")
        self.rx_coord = SiteCoordWidget()
        self.rx_coord.set(-6.834056, 107.738457)
        fl.addRow(QLabel("Coordinates"), self.rx_coord)
        self.tx_coord.changed.connect(self.tx_changed)
        self.rx_coord.changed.connect(self.rx_changed)
        self.btn_pick_rx = QPushButton("Pick on map (Rx)")
        self.btn_pick_rx.setStyleSheet(btn_ss)
        self.btn_pick_rx.clicked.connect(lambda: self.pick_requested.emit("rx"))
        fl.addRow(self.btn_pick_rx)
        self.rx_height = FocusWheelSpinBox(); self.rx_height.setRange(0, 10000); self.rx_height.setValue(1)
        self._add_row_with_info(fl, "Height AGL (m)", self.rx_height, "Receiver height above ground")
        self.rx_amsl = QLabel("Elevasi tanah: \u2014")
        self._style_amsl_label(self.rx_amsl)
        fl.addRow(self.rx_amsl)
        self.rx_height.valueChanged.connect(lambda _: self._refresh_amsl_labels())
        self.rx_gain = FocusWheelSpinBox(); self.rx_gain.setRange(-50, 50); self.rx_gain.setValue(0)
        self._add_row_with_info(fl, "Rx gain (dBd)", self.rx_gain, "Receiver antenna gain in dBd")
        self.rx_thr = FocusWheelSpinBox(); self.rx_thr.setRange(-200, 100); self.rx_thr.setValue(-100)
        self._add_row_with_info(fl, "Rx threshold (dBm)", self.rx_thr, "Minimum required signal threshold")

        # -- 3. Model (EXPANDED BY DEFAULT, EXACTLY MATCHING CLOUDRF SCREENSHOT!)
        fl = self._section("model", _SECTION_ICON["model"], "Model", expanded=True)
        self._gated_rows = []
        self.model = QComboBox()
        for label, val in params_mod.MODELS:
            display_label = "Okumura-Hata (0.15-1.5GHz)" if val == 3 else label
            self.model.addItem(display_label, val)
        # Default to Okumura-Hata matching CloudRF
        idx = self.model.findData(3)
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self._add_row_with_info(fl, "Model", self.model, "Radio propagation model choice")
        self.model.currentIndexChanged.connect(lambda *a: self._apply_model_gating())

        self.reliability = QComboBox()
        self.reliability.addItems(["50%", "80%", "90%", "95%", "99%"])
        self._add_gated_row(
            fl, "Reliability", self.reliability, "ITM statistical time/location "
            "reliability", gate_key="reliability")

        self.context = QComboBox()
        self.context.addItems(["Urban", "Suburban", "Rural"])
        self.context.setCurrentText("Rural")
        self._add_gated_row(
            fl, "Context", self.context,
            "Propagation environment classification. Only used by empirical "
            "models (Hata, ECC33, SUI, COST231-Hata, Ericsson); ignored by "
            "ITM, LOS, FSPL, ITWOM, Plane Earth, Egli and Soil.",
            gate_key="context")

        self.diffraction = QComboBox()
        self.diffraction.addItems(["Off (LOS)", "Knife-edge (KED)"])
        self._add_gated_row(
            fl, "Diffraction", self.diffraction,
            "Knife-edge diffraction (-ked) adds terrain diffraction loss for "
            "empirical models. ITM/ITWOM already include diffraction built-in.",
            gate_key="diffraction")

        # Hidden fields for backward compatibility
        self.knife = QCheckBox("Knife-edge diffraction (-ked)")
        self.knife.setVisible(False)

        # -- 4. Environment
        fl = self._section("env", _SECTION_ICON["env"], "Environment", expanded=False)
        self.climate = QComboBox()
        self.climate.addItem("(default)", 0)
        for v, label in params_mod.CLIMATE_ZONES:
            self.climate.addItem(f"{v}: {label}", v)
        self._add_gated_row(
            fl, "Radio climate", self.climate,
            "Radio climate zone (ITM/ITWOM only)", gate_key="climate")
        self.clutter_btn = QPushButton("Select clutter (.clt)...")
        self.clutter_btn.setStyleSheet(btn_ss)
        self.clutter_path = QLineEdit()
        self.clutter_path.setReadOnly(True)
        self.clutter_path.setPlaceholderText("No clutter file")
        self.clutter_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.clutter_btn.clicked.connect(lambda: self._pick(self.clutter_path, "Clutter (*.clt)"))
        fl.addRow(self.clutter_btn, self.clutter_path)
        self.gc = FocusWheelSpinBox(); self.gc.setRange(0, 1000); self.gc.setValue(0)
        self._add_row_with_info(fl, "Ground clutter (m)", self.gc, "Clutter height in meters")
        self.obstacles = QPlainTextEdit(); self.obstacles.setPlaceholderText("lat,lon,height per line (-udt)")
        self.obstacles.setMaximumHeight(60)
        self.obstacles.setStyleSheet("background: #1B1E22; color: #E2E8F0; border: 1px solid #3F474F; font-size: 11px;")
        fl.addRow("Obstacles", self.obstacles)

        # -- 5. Output / Engine
        fl = self._section("output", _SECTION_ICON["output"], "Output", expanded=False)
        self.engine = QComboBox(); self.engine.addItems(list(params_mod.ENGINES.keys()))
        self.engine.setCurrentText("LIDAR")
        self._add_row_with_info(fl, "Engine", self.engine, "Signal-Server engine build")
        self.dem_source = QComboBox()
        self.dem_source.addItems(["Online – Viewfinder SRTM", "Offline – DEMNAS (.tif)"])
        self.dem_source.setCurrentIndex(1)
        self._add_row_with_info(
            fl, "DEM source", self.dem_source,
            "Sumber elevasi: Online (unduh Viewfinder SRTM) atau Offline (file DEMNAS .tif lokal, tanpa internet)")
        demnas_row = QWidget()
        dv = QVBoxLayout(demnas_row)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(4)
        demnas_top = QHBoxLayout()
        demnas_top.setContentsMargins(0, 0, 0, 0)
        demnas_top.setSpacing(6)
        self.demnas_btn = QPushButton("DEMNAS folder...")
        self.demnas_btn.setStyleSheet(btn_ss)
        self.demnas_dir = QLineEdit()
        self.demnas_dir.setReadOnly(True)
        self.demnas_dir.setPlaceholderText("Pilih folder DEMNAS (.tif)")
        self.demnas_dir.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.demnas_btn.clicked.connect(self._pick_demnas_folder)
        demnas_top.addWidget(self.demnas_btn)
        demnas_top.addWidget(self.demnas_dir, 1)
        self.demnas_live = QCheckBox("Live check")
        self.demnas_live.setChecked(True)
        self.demnas_live.setStyleSheet("color: #CBD5E0; font-size: 10px;")
        demnas_top.addWidget(self.demnas_live)
        dv.addLayout(demnas_top)
        self.demnas_status = QLabel("DEMNAS: –")
        self.demnas_status.setStyleSheet("color: #718096; font-size: 10px; padding: 2px 0;")
        dv.addWidget(self.demnas_status)
        demnas_lbl = QLabel("DEMNAS folder")
        demnas_lbl.setStyleSheet("color: #CBD5E0; font-size: 11px; font-weight: 500;")
        fl.addRow(demnas_lbl, demnas_row)
        self.dem_source.currentTextChanged.connect(self._update_demnas_visibility)
        self._update_demnas_visibility()
        self.terrain = QComboBox(); self.terrain.addItems(["SDF (terrain)", "LIDAR (.asc)"])
        self.terrain.setCurrentIndex(1)
        self._add_row_with_info(fl, "Terrain source", self.terrain, "Elevation data source format (SDF = engine sama dgn online; LIDAR = engine LIDAR)")
        self.sdf_btn = QPushButton("SDF directory...")
        self.sdf_btn.setStyleSheet(btn_ss)
        self.sdf_path = QLineEdit()
        self.sdf_path.setReadOnly(True)
        self.sdf_path.setPlaceholderText("No SDF directory")
        self.sdf_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.sdf_btn.clicked.connect(self._pick_dir)
        fl.addRow(self.sdf_btn, self.sdf_path)
        self.lidar_btn = QPushButton("LIDAR file...")
        self.lidar_btn.setStyleSheet(btn_ss)
        self.lidar_path = QLineEdit()
        self.lidar_path.setReadOnly(True)
        self.lidar_path.setPlaceholderText("No LIDAR file")
        self.lidar_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.lidar_btn.clicked.connect(lambda: self._pick(self.lidar_path, "LIDAR (*.asc)"))
        fl.addRow(self.lidar_btn, self.lidar_path)
        self.resolution = QComboBox()
        for r in params_mod.RESOLUTIONS:
            self.resolution.addItem(str(r), r)
        self.resolution.setCurrentText("1200")
        self._add_row_with_info(fl, "Resolution", self.resolution, "Tile pixel resolution")
        self.radius = FocusWheelSpinBox(); self.radius.setRange(0.1, 10000); self.radius.setValue(2)
        self._add_row_with_info(fl, "Radius (km)", self.radius, "Plot coverage radius in km")
        self.plot_quality = QComboBox()
        self.plot_quality.addItem("Final (resolusi penuh)", "final")
        self.plot_quality.addItem("Draft (2× cepat)", "draft")
        self.plot_quality.setCurrentIndex(0)
        self.plot_quality.setStyleSheet(self.resolution.styleSheet())
        self._add_row_with_info(fl, "Kualitas plot", self.plot_quality,
                                "Draft membagi 2 resolusi piksel (≈4× lebih cepat) untuk pratinjau")
        self.color_btn = QPushButton("Color table...")
        self.color_btn.setStyleSheet(btn_ss)
        self.color_path = QLineEdit()
        self.color_path.setReadOnly(True)
        self.color_path.setPlaceholderText("Default: radiomobile.dcf")
        self.color_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        # Radio Mobile palette by default; bundled copy as fallback when the
        # Signal-Server tree (ss_root) is not available (packaged builds).
        default_color = ""
        if self.ss_root:
            default_color = os.path.join(self.ss_root, "color", "radiomobile.dcf")
        if not default_color or not os.path.exists(default_color):
            default_color = os.path.join(
                os.path.dirname(__file__), "resources", "radiomobile.dcf")
        if os.path.exists(default_color):
            self.color_path.setText(default_color)
        self._color_user_chosen = False
        self.color_btn.clicked.connect(self._pick_color)
        fl.addRow(self.color_btn, self.color_path)
        self.dbm_color = QCheckBox("dBm colour scale")
        self.dbm_color.setChecked(True)
        self.dbm_color.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl.addRow(self.dbm_color)
        self.raster_txt = QCheckBox("Save raster data (TXT)")
        self.raster_txt.setChecked(False)
        self.raster_txt.setToolTip(
            "Engine menulis <output>_raster.txt berisi lat/lon/Rx(dBm) per "
            "pixel — bisa dibandingkan dengan Radio Mobile.")
        self.raster_txt.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl.addRow(self.raster_txt)
        self.rm_style = QCheckBox("Palet & render gaya Radio Mobile")
        self.rm_style.setChecked(False)
        self.rm_style.setToolTip(
            "Pakai palet otomatis dari rmwcore/colors*.dat (Radio Mobile) "
            "untuk engine, lalu hasilkan gambar gaya Radio Mobile "
            "(terrain hypsometrik + hillshade + coverage + simbol site + "
            "range circle). Palet kustom yang dipilih manual tetap diutamakan.")
        self.rm_style.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl.addRow(self.rm_style)

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
        self.export_fmt.addItems(["KMZ", "KML", "PNG", "PNG (RM-style)", "TXT (Raster)", "GeoTIFF", "KMZ (3D)", "SHP"])
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

        # Apply model-dependent disabling/badges now that all rows exist.
        self._apply_model_gating()

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

    def _pick(self, label: QLabel, filter_: str, start_dir: Optional[str] = None) -> None:
        p = _browse(self, "Select file", filter_, start_dir)
        if p:
            label.setText(p)

    def _pick_color(self) -> None:
        p = _browse(
            self, "Select color table", "Color (*.dcf *.scf *.dat)",
            os.path.join(self.ss_root, "color") if self.ss_root else None)
        if p:
            self.color_path.setText(p)
            if not p.lower().endswith(".dat"):
                self._color_user_chosen = True

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select SDF directory")
        if d:
            self.sdf_path.setText(d)

    def _pick_antenna(self) -> None:
        p = _browse(self, "Select antenna pattern", "Antenna (*.az *.el)")
        if p:
            base, _ = os.path.splitext(p)
            self.ant_path.setText(base)

    def _update_demnas_visibility(self) -> None:
        offline = self.dem_source.currentIndex() == 1
        self.demnas_btn.setVisible(offline)
        self.demnas_dir.setVisible(offline)
        self.demnas_live.setVisible(offline)
        self.demnas_status.setVisible(offline)
        if not offline:
            self.set_demnas_status("idle", "DEMNAS: online aktif")

    def _pick_demnas_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Pilih folder DEMNAS", self.demnas_dir.text() or os.path.expanduser("~")
        )
        if folder:
            self.demnas_dir.setText(folder)
            self.demnas_dir_picked.emit()

    def set_demnas_status(self, state: str, text: str) -> None:
        colors = {"ok": "#2ECC71", "bad": "#E53E3E", "idle": "#718096"}
        self.demnas_status.setStyleSheet(
            f"color: {colors.get(state, '#718096')}; font-size: 10px; padding: 2px 0;"
        )
        self.demnas_status.setText(text)

    # ------------------------------------------------------------------ AMSL info
    def _style_amsl_label(self, lbl: QLabel) -> None:
        lbl.setStyleSheet(
            "color: #718096; font-size: 10px; padding: 0 0 2px 2px;"
        )

    def _refresh_amsl_labels(self) -> None:
        """Re-render the AMSL hint labels from the cached ground elevations."""
        for role, lbl in (("tx", self.tx_amsl), ("rx", self.rx_amsl)):
            elev = self._ground_elev.get(role)
            height = getattr(self, f"{role}_height").value()
            if elev is None:
                lbl.setText("Elevasi tanah: \u2014")
            else:
                lbl.setText(
                    f"Elevasi tanah {elev:.0f} m \u00b7 antena AMSL "
                    f"{elev + height:.0f} m"
                )

    def set_ground_elevation(self, role: str, elev) -> None:
        """Store a looked-up ground elevation (m AMSL or None) and refresh."""
        if role not in ("tx", "rx"):
            return
        self._ground_elev[role] = float(elev) if elev is not None else None
        self._refresh_amsl_labels()

    def ground_elevations(self) -> dict:
        """Cached {'tx': elev|None, 'rx': elev|None} from the last lookup."""
        return dict(self._ground_elev)

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
            "tx_name": self.tx_name.text().strip() or None,
            "tx_network": self.tx_network.text().strip() or None,
            "rx_name": self.rx_name.text().strip() or None,
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
            "dem_source": "offline" if self.dem_source.currentIndex() == 1 else "online",
            "demnas_dir": self.demnas_dir.text().strip() or None,
            "terrain_source": "lidar" if self.terrain.currentText().startswith("LIDAR") else "sdf",
            "sdf_dir": self.sdf_path.text() or None,
            "lidar_file": self.lidar_path.text() or None,
            "resolution": self.resolution.currentData(),
            "radius": self.radius.value(),
            "plot_quality": self.plot_quality.currentData(),
            "color_file": self.color_path.text() or None,
            "color_file_user": getattr(self, "_color_user_chosen", False),
            "dbm_color": self.dbm_color.isChecked(),
            "raster_txt": self.raster_txt.isChecked(),
            "rm_style": self.rm_style.isChecked(),
            "units": units,
            "dem_resolution": dem_res_map[self.dem_res.currentIndex()],
        }
        return d

    def load(self, d: dict) -> None:
        """Restore all form fields from a previously saved ``collect()`` dict."""
        if not isinstance(d, dict):
            return
        # Site / Tx
        self.units.setCurrentText("Metric" if d.get("units", "metric") == "metric" else "Imperial")
        self.tx_name.setText(d.get("tx_name") or "")
        self.tx_network.setText(d.get("tx_network") or "")
        self.tx_coord.set(d.get("tx_lat"), d.get("tx_lon"))
        self.tx_height.setValue(float(d.get("tx_height", 1)))
        self.frequency.setValue(float(d.get("frequency_mhz", 900)))
        dem_rev = {3: 0, 1: 1, 15: 2}
        self.dem_res.setCurrentIndex(dem_rev.get(int(d.get("dem_resolution", 1)), 0))
        # Signal
        self.rf_power.setValue(float(d.get("rf_power_w", 1)))
        self.tx_gain.setValue(float(d.get("tx_gain_dbi", 10)))
        # Feeder
        self.cable_loss.setValue(float(d.get("cable_loss_db", 0)))
        self._update_erp()
        # Antenna
        self.ant_path.setText(d.get("antenna_basename") or "")
        self.pol.setCurrentText(d.get("polarization", "vertical"))
        self.azimuth.setValue(float(d.get("azimuth_deg", 0)))
        self.downtilt.setValue(float(d.get("downtilt_deg", 0)))
        self.downtilt_dir.setValue(float(d.get("downtilt_dir_deg", 0)))
        # Mobile / Rx
        self.rx_name.setText(d.get("rx_name") or "")
        self.rx_coord.set(d.get("rx_lat"), d.get("rx_lon"))
        self.rx_height.setValue(float(d.get("rx_height", 1.5)))
        self.rx_gain.setValue(float(d.get("rx_gain_dbd", 0)))
        self.rx_thr.setValue(float(d.get("rx_threshold_dbm", -100)))
        # Model
        model_idx = self.model.findData(int(d.get("model_pm", 3)))
        if model_idx >= 0:
            self.model.setCurrentIndex(model_idx)
        self.reliability.setCurrentText(f"{int(d.get('reliability', 50))}%")
        ctx_map = {1: "Urban", 2: "Suburban", 3: "Rural"}
        self.context.setCurrentText(ctx_map.get(int(d.get("context_pe", 3)), "Rural"))
        self.diffraction.setCurrentText("Knife-edge (KED)" if d.get("knife_edge") else "Off (LOS)")
        # Environment
        climate = d.get("climate_zone")
        if climate is not None:
            self.climate.setCurrentData(climate)
        self.clutter_path.setText(d.get("clutter_file") or "")
        self.gc.setValue(float(d.get("ground_clutter", 0)))
        self.obstacles.setPlainText("\n".join(str(o) for o in d.get("obstacles", [])))
        # Output / Engine
        self.engine.setCurrentText(d.get("engine", "LIDAR"))
        self.dem_source.setCurrentIndex(1 if d.get("dem_source", "offline") == "offline" else 0)
        self.demnas_dir.setText(d.get("demnas_dir") or "")
        self._update_demnas_visibility()
        self.terrain.setCurrentIndex(1 if d.get("terrain_source", "lidar") == "lidar" else 0)
        self.sdf_path.setText(d.get("sdf_dir") or "")
        self.lidar_path.setText(d.get("lidar_file") or "")
        res = d.get("resolution", 1200)
        res_idx = self.resolution.findData(res)
        if res_idx >= 0:
            self.resolution.setCurrentIndex(res_idx)
        self.radius.setValue(float(d.get("radius", 30)))
        q = d.get("plot_quality", "final")
        qi = self.plot_quality.findData(q)
        if qi >= 0:
            self.plot_quality.setCurrentIndex(qi)
        self.color_path.setText(d.get("color_file") or "")
        self.dbm_color.setChecked(bool(d.get("dbm_color", True)))
        self.raster_txt.setChecked(bool(d.get("raster_txt", False)))
        self.rm_style.setChecked(bool(d.get("rm_style", False)))
        # Re-apply model-dependent disabling/badges for the loaded model.
        self._apply_model_gating()


