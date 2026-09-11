"""Sidebar parameter form for the Signal-Server GUI with CloudRF Dark Accordion UI.

Collects all simulation inputs and exposes ``collect()`` -> canonical dict and
``load()`` to restore a saved profile. Field names match ``params.build_argv``.
"""

from __future__ import annotations

import math
import os
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QComboBox, QCheckBox, QPushButton, QFileDialog, QPlainTextEdit, QStackedWidget,
    QHBoxLayout, QLabel, QSpinBox, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QTimer
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
        QToolTip {
            background-color: #1E2226;
            color: #FFFFFF;
            border: 1px solid #4A5568;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 11px;
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
                padding: 4px 8px;
            }
            QFrame:hover {
                background-color: #343A40;
            }
        """ % ("#343A40" if expanded else "#2B3036"))

        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(4, 2, 4, 2)
        h_layout.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_pixmap(icon_name, 14, "#CBD5E0"))
        icon_lbl.setStyleSheet("margin: 0 2px;")

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: 600;")

        self.arrow_lbl = QLabel("▾" if expanded else "▸")
        self.arrow_lbl.setStyleSheet("color: #A0AEC0; font-weight: bold; font-size: 11px;")

        h_layout.addWidget(icon_lbl)
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()
        h_layout.addWidget(self.arrow_lbl)

        main_layout.addWidget(self.header)

        # Content widget
        self.content = QWidget()
        self.content.setVisible(expanded)
        self.content_layout = QFormLayout(self.content)
        self.content_layout.setContentsMargins(6, 4, 6, 6)
        self.content_layout.setSpacing(4)
        self.content_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        main_layout.addWidget(self.content)

        self.header.mousePressEvent = self._toggle

    def _toggle(self, event=None):
        self.set_expanded(not self.expanded)

    def set_expanded(self, exp: bool):
        self.expanded = exp
        self.content.setVisible(exp)
        self.arrow_lbl.setText("▾" if exp else "▸")
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

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(250)
        self._debounce_timer.timeout.connect(self.changed.emit)

        for _w in (self.dd_lat, self.dd_lon, self.dms_lat, self.dms_lon, self.mgrs):
            _w.textChanged.connect(self._debounce_timer.start)
            _w.editingFinished.connect(self._on_editing_finished)
        self.dms_lat_hemi.currentTextChanged.connect(self._debounce_timer.start)
        self.dms_lon_hemi.currentTextChanged.connect(self._debounce_timer.start)
        self.fmt.currentIndexChanged.connect(self._debounce_timer.start)

    def _on_editing_finished(self) -> None:
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
            self.changed.emit()

    def get(self) -> tuple[Optional[float], Optional[float]]:
        idx = self.fmt.currentIndex()
        try:
            if idx == 0:
                lat_str = self.dd_lat.text().strip().replace(",", ".")
                lon_str = self.dd_lon.text().strip().replace(",", ".")
                if not lat_str or not lon_str:
                    return (None, None)
                return (float(lat_str), float(lon_str))
            if idx == 1:
                lat_str = self.dms_lat.text().strip()
                lon_str = self.dms_lon.text().strip()
                if not lat_str or not lon_str:
                    return (None, None)
                lat = coords.parse_dms(lat_str + self.dms_lat_hemi.currentText())
                lon = coords.parse_dms(lon_str + self.dms_lon_hemi.currentText())
                return (lat, lon)
            if idx == 2:
                mgrs_str = self.mgrs.text().strip()
                if not mgrs_str:
                    return (None, None)
                return coords.mgrs_to_latlon(mgrs_str)
        except Exception:
            return (None, None)
        return (None, None)

    def set(self, lat: Optional[float], lon: Optional[float]) -> None:
        if lat is None or lon is None:
            return
        self._debounce_timer.stop()
        self.dd_lat.blockSignals(True)
        self.dd_lon.blockSignals(True)
        self.dd_lat.setText(f"{lat:.6f}")
        self.dd_lon.setText(f"{lon:.6f}")
        self.dd_lat.blockSignals(False)
        self.dd_lon.blockSignals(False)
        self.changed.emit()


class ParameterForm(QWidget):
    erp_changed = Signal(float)
    pick_requested = Signal(str)  # "tx" or "rx"
    tx_changed = Signal()         # tx coordinate edited in the form
    rx_changed = Signal()         # rx coordinate edited in the form
    start_requested = Signal()
    stop_requested = Signal()
    export_requested = Signal(str)  # selected export format (e.g. "KMZ")
    export_dem_requested = Signal()
    demnas_dir_picked = Signal()    # DEMNAS folder (re)selected, even if unchanged
    transparent_holes_toggled = Signal(bool)
    contour_mode_changed = Signal(int)
    swap_requested = Signal()
    lock_toggled = Signal(bool)

    def __init__(self, signal_server_root: str = "", parent=None):
        super().__init__(parent)
        self.ss_root = signal_server_root
        self.sections: dict[str, CollapsibleSection] = {}
        self.is_locked = False
        self.points_locked = False
        # Guard for bidirectional dBm<->dBµV threshold synchronisation.
        self._thr_syncing = False
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
        lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 500;")
        form_layout.addRow(lbl, row_w)

    def _wire_threshold_pair(self, dbm_box: "FocusWheelSpinBox",
                             uv_box: "FocusWheelSpinBox") -> None:
        """Keep two RX-threshold spinboxes (dBm <-> dBµV) in sync, 50 Ω."""
        def on_dbm(v: float) -> None:
            if self._thr_syncing:
                return
            self._thr_syncing = True
            uv_box.blockSignals(True)
            uv_box.setValue(params_mod.dbm_to_dbuv(v))
            uv_box.blockSignals(False)
            self._thr_syncing = False

        def on_uv(v: float) -> None:
            if self._thr_syncing:
                return
            self._thr_syncing = True
            dbm_box.blockSignals(True)
            dbm_box.setValue(params_mod.dbuv_to_dbm(v))
            dbm_box.blockSignals(False)
            self._thr_syncing = False

        dbm_box.valueChanged.connect(on_dbm)
        uv_box.valueChanged.connect(on_uv)

    def _make_threshold_pair(self, dbm_default: float, dbm_range: tuple,
                             uv_range: tuple):
        """Build a [dBm | dBµV] dual-unit widget pair + container.

        Returns ``(dbm_box, uv_box, container)``; the container is what you pass
        to ``_add_row_with_info``.
        """
        dbm = FocusWheelSpinBox()
        dbm.setRange(*dbm_range)
        dbm.setValue(dbm_default)
        dbm.setSuffix(" dBm")
        uv = FocusWheelSpinBox()
        uv.setRange(*uv_range)
        uv.setValue(round(params_mod.dbm_to_dbuv(dbm_default)))
        uv.setSuffix(" dBµV")
        container = QWidget()
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(dbm, 1)
        hl.addWidget(uv, 1)
        self._wire_threshold_pair(dbm, uv)
        return dbm, uv, container

    def _sub_label(self, text: str, icon: str = "") -> QWidget:
        """Clear, elegant visual sub-group divider inside an accordion section."""
        if not icon:
            t_low = text.lower()
            if any(k in t_low for k in ("power", "feeder", "rf", "sensitivity")):
                icon = "radio"
            elif any(k in t_low for k in ("pattern", "antenna", "direction")):
                icon = "antenna"
            elif any(k in t_low for k in ("site", "location", "position", "frequency")):
                icon = "tower"

        wrapper = QWidget()
        w_layout = QHBoxLayout(wrapper)
        w_layout.setContentsMargins(0, 10, 0, 4)
        w_layout.setSpacing(6)

        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(_pixmap(icon, 12, "#63B3ED"))
            w_layout.addWidget(icon_lbl)

        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            "color: #90CDF4; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.8px;"
        )
        w_layout.addWidget(lbl)

        # Subtle horizontal divider line extending to the right
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #2D3748; border: none; max-height: 1px;")
        w_layout.addWidget(line, 1)

        return wrapper

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
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(3)

        # Combo / SpinBox dark input stylesheet
        input_ss = """
            QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
                background-color: #1B1E22;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 3px 5px;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1B1E22;
                color: #E2E8F0;
                selection-background-color: #3182CE;
            }
            QComboBox:disabled {
                background-color: #14171A;
                color: #A0AEC0;
                border: 1px solid #2D3748;
            }
        """
        btn_ss = """
            QPushButton {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4A5568; }
        """
        self.setStyleSheet(input_ss)

        # =========================================================================
        # -- 1. Transmitter (Tx)
        # =========================================================================
        fl_tx = self._section("tx", _SECTION_ICON["tx"], "Transmitter (Tx)", expanded=False)
        # Units kept headless for collect()/load() backward compatibility without showing in form
        self.units = QComboBox(); self.units.addItems(["Metric", "Imperial"]); self.units.setCurrentText("Metric")
        fl_tx.addRow(self._sub_label("Site Location & Frequency", "tower"))
        self.tx_name = QLineEdit()
        self.tx_name.setPlaceholderText("Site name (e.g. BTS-01)")
        self._add_row_with_info(fl_tx, "Site name", self.tx_name, "Label for this transmitter site")
        self.tx_network = QLineEdit()
        self.tx_network.setPlaceholderText("Network (e.g. Telkomsel)")
        self._add_row_with_info(fl_tx, "Network", self.tx_network, "Operator / network identifier")
        self.tx_coord = SiteCoordWidget()
        self.tx_coord.set(-6.916667, 107.6083)
        fl_tx.addRow(QLabel("Coordinates"), self.tx_coord)
        self.btn_pick_tx = QPushButton("Pick on map (Tx)")
        self.btn_pick_tx.setStyleSheet(btn_ss)
        self.btn_pick_tx.clicked.connect(lambda: self.pick_requested.emit("tx"))
        fl_tx.addRow(self.btn_pick_tx)
        self.tx_height = FocusWheelSpinBox(); self.tx_height.setRange(0, 10000); self.tx_height.setValue(1)
        self._add_row_with_info(fl_tx, "Antenna Height AGL (m)", self.tx_height, "Transmitter antenna height above ground")
        self.tx_amsl = QLabel("Elevasi tanah: \u2014")
        self._style_amsl_label(self.tx_amsl)
        fl_tx.addRow(self.tx_amsl)
        self.tx_height.valueChanged.connect(lambda _: self._refresh_amsl_labels())
        self.frequency = FocusWheelSpinBox(); self.frequency.setRange(0.1, 100000); self.frequency.setValue(900)
        self._add_row_with_info(fl_tx, "Frequency (MHz)", self.frequency, "Operating frequency in MHz")

        # Tx Signal & Feeder
        fl_tx.addRow(self._sub_label("RF Power & Feeder", "radio"))
        self.rf_power = FocusWheelSpinBox(); self.rf_power.setRange(0, 1e7); self.rf_power.setValue(1)
        self.tx_dbm_label = QLabel("≈ 30.0 dBm")
        self.tx_dbm_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        pw_row = QWidget()
        pw_hl = QHBoxLayout(pw_row)
        pw_hl.setContentsMargins(0, 0, 0, 0)
        pw_hl.setSpacing(8)
        pw_hl.addWidget(self.rf_power, 1)
        pw_hl.addWidget(self.tx_dbm_label)
        self._add_row_with_info(fl_tx, "Transmit power (Watt)", pw_row, "Transmitter power output in Watts")
        self.tx_gain = FocusWheelSpinBox(); self.tx_gain.setRange(-50, 50); self.tx_gain.setValue(10)
        self._add_row_with_info(fl_tx, "Antenna gain (dBi)", self.tx_gain, "Transmitter antenna gain in dBi")
        self.cable_loss = FocusWheelSpinBox(); self.cable_loss.setRange(0, 50); self.cable_loss.setValue(0)
        self._add_row_with_info(fl_tx, "Line loss (dB)", self.cable_loss, "Transmission line / cable loss")
        # Tx ERP / EIRP Live Calculation Pill Card
        erp_card = QFrame()
        erp_card.setStyleSheet("""
            QFrame {
                background-color: #181B20;
                border: 1px solid #282E38;
                border-radius: 4px;
            }
        """)
        erp_layout = QHBoxLayout(erp_card)
        erp_layout.setContentsMargins(8, 5, 8, 5)
        erp_layout.setSpacing(12)

        self.erp_label = QLabel("ERP: — W")
        self.erp_label.setStyleSheet("color: #38B2AC; font-size: 11px; font-weight: 600;")
        self.eirp_label = QLabel("EIRP: — W (— dBm)")
        self.eirp_label.setStyleSheet("color: #4299E1; font-size: 11px; font-weight: 600;")

        erp_layout.addWidget(self.erp_label)
        erp_layout.addStretch()
        erp_layout.addWidget(self.eirp_label)
        fl_tx.addRow(erp_card)

        self.tx_thr, self.tx_thr_uv, tx_thr_w = self._make_threshold_pair(
            -100, (-200, 100), (-100, 250))
        self._add_row_with_info(
            fl_tx, "Receiver threshold (unit ini)", tx_thr_w,
            "Ambang terima stasiun ini (dBm ⇄ dBµV). Disimpan di profil/manifest; "
            "engine hanya menerima satu -rt dari sisi Rx.")
        for w in (self.rf_power, self.tx_gain, self.cable_loss):
            w.valueChanged.connect(self._update_erp)

        # Tx Antenna Pattern & Direction
        fl_tx.addRow(self._sub_label("Antenna Pattern & Direction", "antenna"))
        self.ant_combo = QComboBox()
        self.ant_combo.setStyleSheet(input_ss)
        self.ant_btn = QPushButton()
        self.ant_btn.setIcon(self._icon("folder", 14, "#CBD5E0"))
        self.ant_btn.setToolTip("Cari / buka berkas pola antena kustom (*.ant, *.az, *.el)...")
        self.ant_btn.setFixedSize(28, 24)
        self.ant_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                border: 1px solid #3F474F;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3182CE;
                border-color: #4299E1;
            }
            QPushButton:pressed {
                background-color: #2B6CB0;
            }
        """)
        self.ant_btn.clicked.connect(self._pick_antenna)

        ant_row = QWidget()
        ant_l = QHBoxLayout(ant_row)
        ant_l.setContentsMargins(0, 0, 0, 0)
        ant_l.setSpacing(4)
        ant_l.addWidget(self.ant_combo, 1)
        ant_l.addWidget(self.ant_btn)

        self.ant_path = QLineEdit()
        self.ant_path.setVisible(False)
        self.ant_path.setText("")

        self._add_row_with_info(fl_tx, "Antenna pattern", ant_row, "Radiation pattern file (.az / .el) for horizontal & vertical directivity")
        self._populate_antenna_combo()
        self.ant_combo.currentIndexChanged.connect(self._on_antenna_combo_changed)
        self.ant_path.textChanged.connect(self._sync_antenna_combo)
        self.pol = QComboBox(); self.pol.addItems(["vertical", "horizontal"])
        self._add_row_with_info(fl_tx, "Polarisation", self.pol, "Antenna polarization")
        self.azimuth = FocusWheelSpinBox(); self.azimuth.setRange(0, 359); self.azimuth.setValue(0)
        self._add_row_with_info(fl_tx, "Azimuth (deg)", self.azimuth, "Antenna orientation / azimuth angle")
        self.downtilt = FocusWheelSpinBox(); self.downtilt.setRange(-10, 90); self.downtilt.setValue(0)
        self._add_row_with_info(fl_tx, "Downtilt (deg)", self.downtilt, "Electrical / mechanical downtilt angle")
        self.downtilt_dir = FocusWheelSpinBox(); self.downtilt_dir.setRange(0, 359); self.downtilt_dir.setValue(0)
        self._add_row_with_info(fl_tx, "Downtilt dir (deg)", self.downtilt_dir, "Downtilt direction angle")
        self.az_mask = QCheckBox("Limit to azimuth sector")
        self.az_mask.setChecked(False)
        fl_tx.addRow(self.az_mask)
        self.az_start = FocusWheelSpinBox()
        self.az_start.setRange(0.1, 360.0); self.az_start.setDecimals(1)
        self.az_start.setSingleStep(0.5); self.az_start.setValue(0.1)
        self.az_start.setEnabled(False)
        self._add_row_with_info(fl_tx, "Azimuth start (deg)", self.az_start,
                                "Start bearing of the sector (0.1-360, North=0)")
        self.az_end = FocusWheelSpinBox()
        self.az_end.setRange(0.1, 360.0); self.az_end.setDecimals(1)
        self.az_end.setSingleStep(0.5); self.az_end.setValue(360.0)
        self.az_end.setEnabled(False)
        self._add_row_with_info(fl_tx, "Azimuth end (deg)", self.az_end,
                                "End bearing of the sector (start>end wraps over North)")
        self.az_mask.toggled.connect(self.az_start.setEnabled)
        self.az_mask.toggled.connect(self.az_end.setEnabled)

        # =========================================================================
        # -- 2. Receiver (Rx)
        # =========================================================================
        fl_rx = self._section("rx", _SECTION_ICON["rx"], "Receiver (Rx)", expanded=False)
        fl_rx.addRow(self._sub_label("Receiver Site & Location", "tower"))
        self.rx_name = QLineEdit()
        self.rx_name.setPlaceholderText("Site name (e.g. UE-01)")
        self._add_row_with_info(fl_rx, "Site name", self.rx_name, "Label for this receiver site")
        self.rx_coord = SiteCoordWidget()
        self.rx_coord.set(-6.834056, 107.738457)
        fl_rx.addRow(QLabel("Coordinates"), self.rx_coord)
        self.tx_coord.changed.connect(self.tx_changed)
        self.rx_coord.changed.connect(self.rx_changed)
        self.btn_pick_rx = QPushButton("Pick on map (Rx)")
        self.btn_pick_rx.setStyleSheet(btn_ss)
        self.btn_pick_rx.clicked.connect(lambda: self.pick_requested.emit("rx"))
        fl_rx.addRow(self.btn_pick_rx)
        self.rx_height = FocusWheelSpinBox(); self.rx_height.setRange(0, 10000); self.rx_height.setValue(1)
        self._add_row_with_info(fl_rx, "Antenna Height AGL (m)", self.rx_height, "Receiver height above ground")
        self.rx_amsl = QLabel("Elevasi tanah: \u2014")
        self._style_amsl_label(self.rx_amsl)
        fl_rx.addRow(self.rx_amsl)
        self.rx_height.valueChanged.connect(lambda _: self._refresh_amsl_labels())
        # Rx Signal & Feeder
        fl_rx.addRow(self._sub_label("RF Power & Sensitivity", "radio"))
        self.rx_power = FocusWheelSpinBox(); self.rx_power.setRange(0, 1e7); self.rx_power.setValue(1)
        self.rx_dbm_label = QLabel("≈ 30.0 dBm")
        self.rx_dbm_label.setStyleSheet("color: #319795; font-size: 11px; font-weight: bold;")
        rx_pw_row = QWidget()
        rx_pw_hl = QHBoxLayout(rx_pw_row)
        rx_pw_hl.setContentsMargins(0, 0, 0, 0)
        rx_pw_hl.setSpacing(8)
        rx_pw_hl.addWidget(self.rx_power, 1)
        rx_pw_hl.addWidget(self.rx_dbm_label)
        self._add_row_with_info(fl_rx, "Transmit power (Watt)", rx_pw_row, "Receiver / talkback transmitter power output in Watts")

        self.rx_gain = FocusWheelSpinBox(); self.rx_gain.setRange(-50, 50); self.rx_gain.setValue(0)
        self._add_row_with_info(fl_rx, "Antenna gain (dBi)", self.rx_gain, "Receiver antenna gain in dBi")

        self.rx_cable_loss = FocusWheelSpinBox(); self.rx_cable_loss.setRange(0.0, 50.0); self.rx_cable_loss.setValue(0.5); self.rx_cable_loss.setSingleStep(0.1)
        self._add_row_with_info(fl_rx, "Line loss (dB)", self.rx_cable_loss, "Receiver transmission line / cable loss in dB (Radio Mobile: 0.5 dB)")

        # Rx ERP / EIRP Live Calculation Pill Card
        rx_erp_card = QFrame()
        rx_erp_card.setStyleSheet("""
            QFrame {
                background-color: #181B20;
                border: 1px solid #282E38;
                border-radius: 4px;
            }
        """)
        rx_erp_layout = QHBoxLayout(rx_erp_card)
        rx_erp_layout.setContentsMargins(8, 5, 8, 5)
        rx_erp_layout.setSpacing(12)

        self.rx_erp_label = QLabel("ERP: — W")
        self.rx_erp_label.setStyleSheet("color: #38B2AC; font-size: 11px; font-weight: 600;")
        self.rx_eirp_label = QLabel("EIRP: — W (— dBm)")
        self.rx_eirp_label.setStyleSheet("color: #4299E1; font-size: 11px; font-weight: 600;")

        rx_erp_layout.addWidget(self.rx_erp_label)
        rx_erp_layout.addStretch()
        rx_erp_layout.addWidget(self.rx_eirp_label)
        fl_rx.addRow(rx_erp_card)

        for w in (self.rx_power, self.rx_gain, self.rx_cable_loss):
            w.valueChanged.connect(self._update_rx_erp)

        self.rx_thr, self.rx_thr_uv, rx_thr_w = self._make_threshold_pair(
            -100, (-200, 100), (-100, 250))
        self._add_row_with_info(
            fl_rx, "Receiver threshold", rx_thr_w,
            "Minimum required signal threshold (dBm ⇄ dBµV). Ini yang dikirim "
            "ke engine sebagai -rt (RX relative = margin pada link report).")

        # =========================================================================
        # -- 3. Propagation Model (Default Expanded!)
        # =========================================================================
        fl_model = self._section("model", _SECTION_ICON["model"], "Propagation Model", expanded=True)
        self._gated_rows = []
        self.model = QComboBox()
        for label, val in params_mod.MODELS:
            display_label = "Okumura-Hata (0.15-1.5GHz)" if val == 3 else label
            self.model.addItem(display_label, val)
        idx = self.model.findData(3)
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self._add_row_with_info(fl_model, "Model", self.model, "Radio propagation model choice")
        self.model.currentIndexChanged.connect(lambda *a: self._apply_model_gating())

        self.context = QComboBox()
        self.context.addItems(["Urban", "Suburban", "Rural"])
        self.context.setCurrentText("Rural")
        self._add_gated_row(
            fl_model, "Context", self.context,
            "Propagation environment classification. Only used by empirical "
            "models (Hata, ECC33, SUI, COST231-Hata, Ericsson); ignored by "
            "ITM, LOS, FSPL, ITWOM, Plane Earth, Egli and Soil.",
            gate_key="context")

        self.reliability = QComboBox()
        self.reliability.addItems(["50%", "70%", "75%", "80%", "90%", "95%", "99%"])
        self._add_gated_row(
            fl_model, "Reliability", self.reliability, "ITM statistical time/location "
            "reliability", gate_key="reliability")

        self.diffraction = QComboBox()
        self.diffraction.addItems(["Off (LOS)", "Knife-edge (KED)"])
        self._add_gated_row(
            fl_model, "Diffraction", self.diffraction,
            "Knife-edge diffraction (-ked) adds terrain diffraction loss for "
            "empirical models. ITM/ITWOM already include diffraction built-in.",
            gate_key="diffraction")

        self.climate = QComboBox()
        self.climate.addItem("(default)", 0)
        for v, label in params_mod.CLIMATE_ZONES:
            self.climate.addItem(f"{v}: {label}", v)
        self._add_gated_row(
            fl_model, "Radio climate", self.climate,
            "Radio climate zone (ITM/ITWOM only)", gate_key="climate")

        self.two_rays = QComboBox()
        self.two_rays.addItem("Off", 0)
        self.two_rays.addItem("Normal (Coherent)", 1)
        self.two_rays.addItem("Average (Power addition)", 2)
        self._add_row_with_info(
            fl_model, "Two Rays (LOS)", self.two_rays,
            "Two-Ray Ground Reflection untuk Line-Of-Sight paths. "
            "Menghitung pantulan tanah (ground bounce ray) dan interferensi beda fase (multipath fading) "
            "pada model propagasi apapun saat jalur memiliki LOS.")

        self.knife = QCheckBox("Knife-edge diffraction (-ked)")
        self.knife.setVisible(False)

        # =========================================================================
        # -- 4. Terrain & DEM Source
        # =========================================================================
        fl_dem = self._section("env", _SECTION_ICON["env"], "Terrain & DEM Source", expanded=False)
        self.dem_source = QComboBox()
        self.dem_source.addItems([
            "Online – Viewfinder SRTM",
            "Offline – DEMNAS (.tif)",
            "Offline – SRTM3 / HGT (.hgt)",
        ])
        self.dem_source.setCurrentIndex(0)
        self._add_row_with_info(
            fl_dem, "DEM source", self.dem_source,
            "Sumber elevasi: Online (unduh Viewfinder SRTM) atau Offline (folder DEMNAS .tif / SRTM3 .hgt lokal, tanpa internet)")

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
        self.demnas_lbl = QLabel("DEMNAS folder")
        self.demnas_lbl.setStyleSheet("color: #CBD5E0; font-size: 11px; font-weight: 500;")
        fl_dem.addRow(self.demnas_lbl, demnas_row)
        self.dem_source.currentTextChanged.connect(self._update_demnas_visibility)
        self._update_demnas_visibility()

        self.terrain = QComboBox(); self.terrain.addItems(["SDF (terrain)", "LIDAR (.asc)"])
        self.terrain.setCurrentIndex(1)
        self._add_row_with_info(fl_dem, "Terrain format", self.terrain, "Elevation data source format (SDF = standard engine; LIDAR = LIDAR engine)")

        self.sdf_btn = QPushButton("SDF directory...")
        self.sdf_btn.setStyleSheet(btn_ss)
        self.sdf_path = QLineEdit()
        self.sdf_path.setReadOnly(True)
        self.sdf_path.setPlaceholderText("No SDF directory")
        self.sdf_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.sdf_btn.clicked.connect(self._pick_dir)
        fl_dem.addRow(self.sdf_btn, self.sdf_path)

        self.lidar_btn = QPushButton("LIDAR file...")
        self.lidar_btn.setStyleSheet(btn_ss)
        self.lidar_path = QLineEdit()
        self.lidar_path.setReadOnly(True)
        self.lidar_path.setPlaceholderText("No LIDAR file")
        self.lidar_path.setStyleSheet("background: #1B1E22; color: #A0AEC0; border: 1px solid #3F474F; border-radius: 3px; padding: 3px; font-size: 10px;")
        self.lidar_btn.clicked.connect(lambda: self._pick(self.lidar_path, "LIDAR (*.asc)"))
        fl_dem.addRow(self.lidar_btn, self.lidar_path)

        self.dem_res = QComboBox(); self.dem_res.addItems(["90 m (dem3)", "30 m (dem1)", "15 m TIF"])
        self.dem_res.setCurrentIndex(1)
        self._add_row_with_info(
            fl_dem, "DEM resolution", self.dem_res,
            "Resolusi data elevasi. Default 30m (SRTM1) agar detail kontur bukit terjaga.")

        self._dem_downsample = QCheckBox("Izinkan downsampling (hemat RAM)")
        self._dem_downsample.setChecked(False)
        self._dem_downsample.setStyleSheet("color:#CBD5E0; font-size:11px;")
        fl_dem.addRow(self._dem_downsample)

        self._dem_fine_step = QCheckBox("Step halus 1/4 DEM (7.5m)")
        self._dem_fine_step.setChecked(False)
        self._dem_fine_step.setStyleSheet("color:#CBD5E0; font-size:11px;")
        fl_dem.addRow(self._dem_fine_step)

        # Clutter & Obstacles (kept headless so collect/load and backend remain functional without error)
        self.clutter_path = QLineEdit()
        self.gc = FocusWheelSpinBox(); self.gc.setRange(0, 1000); self.gc.setValue(0)
        self.obstacles = QPlainTextEdit()

        self.btn_export_dem = QPushButton("Export DEM .tif untuk QGIS")
        self.btn_export_dem.setStyleSheet(btn_ss)
        self.btn_export_dem.setToolTip("Simpan clip DEMNAS/LIDAR ter-clip ke .tif untuk diinspeksi di QGIS")
        self.btn_export_dem.clicked.connect(lambda: self.export_dem_requested.emit())
        fl_dem.addRow(self.btn_export_dem)

        # =========================================================================
        # -- 5. Output & Visualization
        # =========================================================================
        fl_out = self._section("output", _SECTION_ICON["output"], "Output & Visualization", expanded=False)
        self.engine = QComboBox(); self.engine.addItems(list(params_mod.ENGINES.keys()))
        self.engine.setCurrentText("Standard")
        self._add_row_with_info(fl_out, "Engine", self.engine, "Signal-Server engine build (Standard/HD = SDF; LIDAR = .asc)")
        self.engine.currentTextChanged.connect(self._on_engine_changed)
        self._on_engine_changed(self.engine.currentText())

        self.radius = FocusWheelSpinBox(); self.radius.setRange(0.1, 10000); self.radius.setValue(2)
        self._add_row_with_info(fl_out, "Radius (km)", self.radius, "Plot coverage radius in km")

        self.resolution = QComboBox()
        for r in params_mod.RESOLUTIONS:
            self.resolution.addItem(str(r), r)
        self.resolution.setCurrentText("1200")
        self._add_row_with_info(fl_out, "Resolution", self.resolution, "Tile pixel resolution")

        self.plot_quality = QComboBox()
        self.plot_quality.addItem("Final (resolusi penuh)", "final")
        self.plot_quality.addItem("Draft (2× cepat)", "draft")
        self.plot_quality.setCurrentIndex(0)
        self._add_row_with_info(fl_out, "Plot quality", self.plot_quality,
                                "Draft membagi 2 resolusi piksel (≈4× lebih cepat) untuk pratinjau")

        self.map_segments = QSpinBox()
        self.map_segments.setRange(4, 360)
        self.map_segments.setSingleStep(2)
        self.map_segments.setValue(params_mod.auto_segments())
        self._add_row_with_info(fl_out, "Map segments", self.map_segments,
                                "Partisi multithreading engine (4–360). Rekomendasi: 16 (atau auto core CPU) untuk kecepatan optimal dan stabilitas tanpa race condition.")

        # Color table selection with fast dropdown and Visual Palette Manager
        self.color_combo = QComboBox()
        self.color_combo.setStyleSheet(input_ss)
        self.color_btn = QPushButton()
        self.color_btn.setIcon(self._icon("palette", 14, "#CBD5E0"))
        self.color_btn.setToolTip("Buka Color Palette Manager (Visual Create & My Colours)...")
        self.color_btn.setFixedSize(28, 24)
        self.color_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                border: 1px solid #3F474F;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3182CE;
                border-color: #4299E1;
            }
            QPushButton:pressed {
                background-color: #2B6CB0;
            }
        """)
        self.color_btn.clicked.connect(self._open_color_manager)

        self.color_folder_btn = QPushButton()
        self.color_folder_btn.setIcon(self._icon("folder", 14, "#CBD5E0"))
        self.color_folder_btn.setToolTip("Cari berkas skema warna (*.dcf, *.scf, *.dat) manual...")
        self.color_folder_btn.setFixedSize(28, 24)
        self.color_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                border: 1px solid #3F474F;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3182CE;
                border-color: #4299E1;
            }
            QPushButton:pressed {
                background-color: #2B6CB0;
            }
        """)
        self.color_folder_btn.clicked.connect(self._pick_color)

        color_row = QWidget()
        color_l = QHBoxLayout(color_row)
        color_l.setContentsMargins(0, 0, 0, 0)
        color_l.setSpacing(4)
        color_l.addWidget(self.color_combo, 1)
        color_l.addWidget(self.color_btn)
        color_l.addWidget(self.color_folder_btn)

        self.color_path = QLineEdit()
        self.color_path.setVisible(False)
        self.color_path.setReadOnly(True)
        default_color = os.path.join(
            os.path.dirname(__file__), "resources", "radiomobile.dcf")
        if not os.path.exists(default_color) and self.ss_root:
            default_color = os.path.join(self.ss_root, "color", "splat-classic.dcf")
        if os.path.exists(default_color):
            self.color_path.setText(default_color)
        self._color_user_chosen = False

        self._add_row_with_info(fl_out, "Color table", color_row, "Skema warna coverage (.dcf) atau buka Palette Manager visual")
        self.color_combo.currentIndexChanged.connect(self._on_color_combo_changed)
        self._populate_color_combo()
        if os.path.exists(default_color):
            self._sync_color_combo(default_color)

        self.dbm_color = QCheckBox("dBm colour scale")
        self.dbm_color.setChecked(True)
        self.dbm_color.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl_out.addRow(self.dbm_color)

        self.transparent_holes = QCheckBox("Transparankan area bolong putih (Transparent holes)")
        self.transparent_holes.setChecked(True)
        self.transparent_holes.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        self.transparent_holes.toggled.connect(self.transparent_holes_toggled.emit)
        fl_out.addRow(self.transparent_holes)

        self.kmz_contour_mode = QComboBox()
        self.kmz_contour_mode.addItems([
            "Kontur Halus / Tipis (Subtle, Tidak Tebal)",
            "Flat Murni (Tanpa Kontur)",
            "Kontur Penuh / Tebal (Original 3D)",
        ])
        self.kmz_contour_mode.setCurrentIndex(0)
        self.kmz_contour_mode.currentIndexChanged.connect(self.contour_mode_changed.emit)
        self.kmz_contour_mode.setStyleSheet("""
            QComboBox {
                background: #1E2226;
                color: #E2E8F0;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 11px;
            }
        """)
        self._add_row_with_info(
            fl_out, "Mode Kontur (Peta & Export)", self.kmz_contour_mode,
            "Gaya kontur relief 3D pada tampilan peta (berganti seketika secara realtime) dan ekspor KMZ/KML: "
            "Kontur Halus / Tipis (rekomendasi, kontur tetap terlihat lembut dan tidak terlalu tebal/gelap), "
            "Flat Murni (warna solid seragam tanpa kontur), atau Kontur Penuh/Tebal (Original 3D)."
        )

        self.raster_txt = QCheckBox("Save raster data (TXT)")
        self.raster_txt.setChecked(False)
        self.raster_txt.setStyleSheet("color: #CBD5E0; font-size: 11px;")
        fl_out.addRow(self.raster_txt)

        self._update_erp()
        self._update_rx_erp()

        # Build Sticky Action Footer widget
        self.action_footer = self._build_action_footer()

        # Apply model-dependent disabling/badges now that all rows exist.
        self._apply_model_gating()

    def _build_action_footer(self) -> QWidget:
        """Create the sticky action footer containing Run, Lock, and Export controls."""
        footer = QFrame()
        footer.setStyleSheet("""
            QFrame {
                background-color: #14171A;
                border: 1px solid #282D34;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(4, 4, 4, 4)
        fv.setSpacing(4)

        # Primary Action Row: Big Green Calculate Button
        row_run = QHBoxLayout()
        row_run.setSpacing(6)

        self.btn_run = QPushButton(" Run Coverage")
        self.btn_run.setIcon(self._icon("play", 15, "#FFFFFF"))
        self.btn_run.setToolTip("Calculate & Render RF Propagation Plot")
        self.btn_run.setFixedHeight(30)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:pressed { background-color: #047857; }
            QPushButton:disabled { background-color: #4B5563; }
        """)
        self.btn_run.clicked.connect(lambda: self.start_requested.emit())

        row_run.addWidget(self.btn_run, 1)
        fv.addLayout(row_run)

        # Export Format + Download Row
        row_exp = QHBoxLayout()
        row_exp.setSpacing(6)

        exp_icon_lbl = QLabel()
        exp_icon_lbl.setPixmap(_pixmap("layers", 13, "#94A3B8"))
        row_exp.addWidget(exp_icon_lbl)

        self.export_fmt = QComboBox()
        self.export_fmt.addItems(["KMZ", "KML", "PNG", "PNG (RM-style)", "TXT (Raster)", "GeoTIFF", "KMZ (3D)", "SHP"])
        self.export_fmt.setFixedHeight(26)
        self.export_fmt.setStyleSheet("""
            QComboBox {
                background: #1E2226;
                color: #E2E8F0;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }
        """)

        self.btn_export = QPushButton(" Export")
        self.btn_export.setIcon(self._icon("download", 12, "#E2E8F0"))
        self.btn_export.setToolTip("Export Coverage Layer in Selected Format")
        self.btn_export.setFixedHeight(26)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }
            QPushButton:hover { background-color: #2563EB; color: #FFFFFF; border-color: #3B82F6; }
        """)
        self.btn_export.clicked.connect(
            lambda: self.export_requested.emit(self.export_fmt.currentText()))

        row_exp.addWidget(self.export_fmt, 1)
        row_exp.addWidget(self.btn_export)
        fv.addLayout(row_exp)

        return footer

    def _toggle_lock(self):
        self.lock_toggled.emit(not self.points_locked)

    def set_points_locked(self, locked: bool) -> None:
        self.points_locked = bool(locked)
        self.is_locked = self.points_locked

        if self.points_locked:
            self.btn_pick_tx.setEnabled(False)
            self.btn_pick_rx.setEnabled(False)
            self.btn_pick_tx.setToolTip("Titik terkunci. Buka kunci di navbar terlebih dahulu.")
            self.btn_pick_rx.setToolTip("Titik terkunci. Buka kunci di navbar terlebih dahulu.")
            self.tx_coord.setEnabled(False)
            self.rx_coord.setEnabled(False)
        else:
            self.btn_pick_tx.setEnabled(True)
            self.btn_pick_rx.setEnabled(True)
            self.btn_pick_tx.setToolTip("")
            self.btn_pick_rx.setToolTip("")
            self.tx_coord.setEnabled(True)
            self.rx_coord.setEnabled(True)

    def _pick(self, label: QLabel, filter_: str, start_dir: Optional[str] = None) -> None:
        p = _browse(self, "Select file", filter_, start_dir)
        if p:
            label.setText(p)

    def _open_color_manager(self) -> None:
        """Open the visual Color Palette Manager dialog."""
        from .color_manager import ColorManagerDialog
        dlg = ColorManagerDialog(current_color_file=self.color_path.text(), signal_server_root=self.ss_root, parent=self)
        dlg.palette_applied.connect(self.set_color_file)
        dlg.exec()

    def _populate_color_combo(self) -> None:
        """Populate color scheme dropdown with discovered and standard palettes."""
        self.color_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            from . import color_manager
            palettes = color_manager.discover_all_palettes(self.ss_root)
            for p in palettes:
                self.color_combo.addItem(p.name, p.file_path or "")
            self.color_combo.addItem("Manage palettes...", "__manager__")
            self.color_combo.addItem("Custom file (*.dcf, *.dat)...", "__custom__")
        except Exception:
            pass
        finally:
            self.color_combo.blockSignals(False)

    def _on_color_combo_changed(self, idx: int) -> None:
        if idx < 0:
            return
        data = self.color_combo.itemData(idx)
        if data == "__manager__":
            self._open_color_manager()
            return
        if data == "__custom__":
            self._pick_color()
            return
        self.set_color_file(str(data or ""))

    def set_color_file(self, path: str | None) -> None:
        """Set the active color table path and synchronize dropdown."""
        p = (path or "").strip()
        self.color_path.setText(p)
        if p and not p.lower().endswith(".dat"):
            self._color_user_chosen = True
        self._sync_color_combo(p)

        # Auto-align RX threshold if palette minimum level is lower than current threshold
        if p and os.path.exists(p):
            try:
                from . import rm_style
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    bands = rm_style.parse_dcf_levels(fh.read())
                if bands:
                    min_lvl = min(lvl for lvl, _ in bands)
                    if self.rx_thr.value() > min_lvl:
                        self.rx_thr.setValue(float(min_lvl))
            except Exception:
                pass

    def _sync_color_combo(self, path: str | None) -> None:
        val = (path or "").strip()
        self.color_combo.blockSignals(True)
        try:
            if not val:
                return
            val_norm = os.path.normpath(val)
            val_base = os.path.splitext(os.path.basename(val))[0].lower()

            for i in range(self.color_combo.count()):
                d = self.color_combo.itemData(i)
                if d and d not in ("__manager__", "__custom__"):
                    d_str = str(d)
                    if d_str == val or os.path.normpath(d_str) == val_norm or \
                       os.path.splitext(os.path.basename(d_str))[0].lower() == val_base:
                        self.color_combo.setCurrentIndex(i)
                        return

            name = os.path.basename(val)
            label = f"Custom: {name}"
            insert_pos = max(0, self.color_combo.count() - 2)
            self.color_combo.insertItem(insert_pos, label, val)
            self.color_combo.setCurrentIndex(insert_pos)
        finally:
            self.color_combo.blockSignals(False)

    def _pick_color(self) -> None:
        start_dir = None
        if self.ss_root and os.path.isdir(os.path.join(self.ss_root, "color")):
            start_dir = os.path.join(self.ss_root, "color")
        else:
            bundled = os.path.join(os.path.dirname(__file__), "resources")
            if os.path.isdir(bundled):
                start_dir = bundled
        p = _browse(self, "Select color table", "Color (*.dcf *.scf *.dat)", start_dir)
        if p:
            self.set_color_file(p)
        else:
            self._sync_color_combo(self.color_path.text())

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select SDF directory")
        if d:
            self.sdf_path.setText(d)

    def _populate_antenna_combo(self) -> None:
        """Populate antenna dropdown with discovered and standard pattern files."""
        self.ant_combo.blockSignals(True)
        try:
            self.ant_combo.clear()
            self.ant_combo.addItem("None (Omnidirectional / Isotropic)", "")

            dirs: list[str] = []
            if self.ss_root:
                dirs.append(os.path.join(self.ss_root, "antenna"))
            try:
                from ._bundle import app_root
                root = app_root()
                dirs.extend([
                    os.path.join(root, "Signal-Server", "antenna"),
                    os.path.join(root, "gui", "data", "antennas"),
                ])
            except Exception:
                pass

            friendly = {
                "omni_8dbi": "Omni 8 dBi (Collinear)",
                "omni_6dbi": "Omni 6 dBi (Collinear)",
                "omni_12dbi": "Omni 12 dBi (High Gain)",
                "dipole": "Dipole (2.15 dBi)",
                "db413-b": "DB413-B (Directional / Sector)",
            }
            order = ["omni_8dbi", "omni_6dbi", "omni_12dbi", "dipole", "db413-b"]

            discovered: dict[str, tuple[str, str]] = {}
            for d in dirs:
                if not os.path.isdir(d):
                    continue
                for f in sorted(os.listdir(d)):
                    base, ext = os.path.splitext(f)
                    if ext.lower() in (".az", ".el", ".ant"):
                        key = base.lower()
                        if key not in discovered:
                            full_base = os.path.join(d, base)
                            if (os.path.exists(full_base + ".az") and os.path.exists(full_base + ".el")) or os.path.exists(full_base + ".ant"):
                                discovered[key] = (base, full_base)

            for k in order:
                if k in discovered:
                    base, full_base = discovered.pop(k)
                    label = friendly.get(k, base)
                    self.ant_combo.addItem(label, full_base)

            for k, (base, full_base) in sorted(discovered.items()):
                label = friendly.get(k, base.replace("_", " ").title())
                self.ant_combo.addItem(label, full_base)

            self.ant_combo.addItem("Custom file (*.ant, *.az, *.el)...", "__custom__")
            self.ant_combo.setCurrentIndex(0)
        finally:
            self.ant_combo.blockSignals(False)

    def _on_antenna_combo_changed(self, idx: int) -> None:
        if idx < 0:
            return
        data = self.ant_combo.itemData(idx)
        if data == "__custom__":
            self._pick_antenna()
            return
        self.ant_path.setText(str(data or ""))

    def set_antenna_basename(self, base: str | None) -> None:
        """Set the active antenna basename and synchronize the dropdown."""
        val = (base or "").strip()
        self.ant_path.setText(val)
        self._sync_antenna_combo(val)

    def _sync_antenna_combo(self, base: str | None) -> None:
        val = (base or "").strip()
        self.ant_combo.blockSignals(True)
        try:
            if not val:
                self.ant_combo.setCurrentIndex(0)
                return

            val_norm = os.path.normpath(val)
            val_base = os.path.splitext(os.path.basename(val))[0].lower()

            for i in range(self.ant_combo.count()):
                d = self.ant_combo.itemData(i)
                if d and d != "__custom__":
                    d_str = str(d)
                    if d_str == val or os.path.normpath(d_str) == val_norm or \
                       os.path.splitext(os.path.basename(d_str))[0].lower() == val_base:
                        self.ant_combo.setCurrentIndex(i)
                        return

            name = os.path.basename(val)
            label = f"Custom: {name}"
            insert_pos = max(1, self.ant_combo.count() - 1)
            self.ant_combo.insertItem(insert_pos, label, val)
            self.ant_combo.setCurrentIndex(insert_pos)
        finally:
            self.ant_combo.blockSignals(False)

    def _pick_antenna(self) -> None:
        p = _browse(self, "Select antenna pattern", "Antenna (*.az *.el *.ant);;Radio Mobile Antenna (*.ant);;All Files (*)")
        if p:
            base, ext = os.path.splitext(p)
            if ext.lower() == ".ant":
                az_path = base + ".az"
                el_path = base + ".el"
                if not (os.path.exists(az_path) and os.path.exists(el_path)):
                    try:
                        with open(p, "r") as ant_f:
                            lines = [float(l.strip()) for l in ant_f if l.strip()]
                        if len(lines) >= 360:
                            # Write .az
                            with open(az_path, "w") as az_f:
                                az_f.write("0\n")
                                for i in range(min(360, len(lines))):
                                    az_f.write(f"{i}\t{10**(lines[i]/20.0):0.4f}\n")
                            # Write .el
                            with open(el_path, "w") as el_f:
                                el_f.write("0.0\t0.0\n")
                                el_lines = lines[360:] if len(lines) >= 720 else lines
                                for el in range(-10, 91):
                                    idx = (el + 360) % 360 if len(el_lines) >= 360 else 0
                                    val = el_lines[idx] if idx < len(el_lines) else 0.0
                                    el_f.write(f"{el}\t{10**(val/20.0):0.4f}\n")
                    except Exception:
                        pass
            self.set_antenna_basename(base)
        else:
            self._sync_antenna_combo(self.ant_path.text())

    def _on_engine_changed(self, engine_name: str) -> None:
        """Lock terrain format to match engine, preventing invalid combinations."""
        engine_name = (engine_name or "").strip()
        self.terrain.blockSignals(True)
        try:
            if engine_name in ("Standard", "HD"):
                self.terrain.setCurrentIndex(0)  # "SDF (terrain)"
                self.terrain.setEnabled(False)
                self.terrain.setToolTip(f"Terkunci ke SDF (terrain) karena Engine '{engine_name}' menggunakan format SDF.")
                self.sdf_btn.setVisible(True)
                self.sdf_path.setVisible(True)
                self.lidar_btn.setVisible(False)
                self.lidar_path.setVisible(False)
            elif engine_name == "LIDAR":
                self.terrain.setCurrentIndex(1)  # "LIDAR (.asc)"
                self.terrain.setEnabled(False)
                self.terrain.setToolTip("Terkunci ke LIDAR (.asc) karena Engine 'LIDAR' menggunakan berkas .asc.")
                self.sdf_btn.setVisible(False)
                self.sdf_path.setVisible(False)
                self.lidar_btn.setVisible(True)
                self.lidar_path.setVisible(True)
        finally:
            self.terrain.blockSignals(False)

    def _update_demnas_visibility(self) -> None:
        idx = self.dem_source.currentIndex()
        offline = idx in (1, 2)
        self.demnas_btn.setVisible(offline)
        self.demnas_dir.setVisible(offline)
        self.demnas_live.setVisible(offline)
        self.demnas_status.setVisible(offline)
        if idx == 2:
            self.demnas_lbl.setText("SRTM folder")
            self.demnas_btn.setText("SRTM folder...")
            self.demnas_dir.setPlaceholderText("Pilih folder SRTM (.hgt)")
        elif idx == 1:
            self.demnas_lbl.setText("DEMNAS folder")
            self.demnas_btn.setText("DEMNAS folder...")
            self.demnas_dir.setPlaceholderText("Pilih folder DEMNAS (.tif)")
        else:
            self.demnas_lbl.setText("DEM folder")
            self.set_demnas_status("idle", "DEM: online aktif")

    def _pick_demnas_folder(self) -> None:
        idx = self.dem_source.currentIndex()
        title = "Pilih folder SRTM (.hgt)" if idx == 2 else "Pilih folder DEMNAS (.tif)"
        folder = QFileDialog.getExistingDirectory(
            self, title, self.demnas_dir.text() or os.path.expanduser("~")
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
        p_w = self.rf_power.value()
        gain = self.tx_gain.value()
        loss = self.cable_loss.value()
        erp = params_mod.compute_erp(p_w, gain, loss)
        eirp_w = params_mod.compute_eirp_w(p_w, gain, loss)
        eirp_dbm_val = 10 * math.log10(eirp_w * 1000.0) if eirp_w > 0 else float("-inf")
        erp_rm = eirp_w / 1.64 if eirp_w > 0 else 0.0
        self.erp_label.setText(f"ERP: {erp_rm:.2f} W ({erp:.3f} W)")
        self.eirp_label.setText(f"EIRP: {eirp_w:.2f} W ({eirp_dbm_val:.2f} dBm)")
        if p_w > 0:
            self.tx_dbm_label.setText(
                f"≈ {10 * math.log10(p_w * 1000):.1f} dBm")
        else:
            self.tx_dbm_label.setText("≈ — dBm")
        self.erp_changed.emit(erp)

    def _update_rx_erp(self) -> None:
        p_w = self.rx_power.value()
        gain = self.rx_gain.value()
        loss = self.rx_cable_loss.value()
        erp = params_mod.compute_erp(p_w, gain, loss)
        eirp_w = params_mod.compute_eirp_w(p_w, gain, loss)
        eirp_dbm_val = 10 * math.log10(eirp_w * 1000.0) if eirp_w > 0 else float("-inf")
        erp_rm = eirp_w / 1.64 if eirp_w > 0 else 0.0
        self.rx_erp_label.setText(f"ERP: {erp_rm:.2f} W ({erp:.3f} W)")
        self.rx_eirp_label.setText(f"EIRP: {eirp_w:.2f} W ({eirp_dbm_val:.2f} dBm)")
        if p_w > 0:
            self.rx_dbm_label.setText(
                f"≈ {10 * math.log10(p_w * 1000):.1f} dBm")
        else:
            self.rx_dbm_label.setText("≈ — dBm")

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
        units = "metric"
        if hasattr(self, "units"):
            units = "metric" if self.units.currentText() == "Metric" else "imperial"

        two_ray_val = self.two_rays.currentData()
        if two_ray_val is None:
            two_ray_val = 0
        two_ray_mode = "normal" if two_ray_val == 1 else ("average" if two_ray_val == 2 else "off")

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
            "az_mask_enabled": self.az_mask.isChecked(),
            "az_mask_start_deg": self.az_start.value(),
            "az_mask_end_deg": self.az_end.value(),
            "rx_lat": rx_lat, "rx_lon": rx_lon,
            "rx_height": self.rx_height.value(),
            "rx_power_w": self.rx_power.value(),
            "rx_gain_dbi": self.rx_gain.value(),
            "rx_gain_dbd": self.rx_gain.value() - 2.15,
            "rx_cable_loss_db": self.rx_cable_loss.value(),
            "rx_line_loss_db": self.rx_cable_loss.value(),
            "rx_threshold_dbm": self.rx_thr.value(),
            "tx_threshold_dbm": self.tx_thr.value(),
            "model_pm": model_val,
            "reliability": rel_val,
            "context_pe": context_pe,
            "knife_edge": knife_edge,
            "climate_zone": climate,
            "tworay": two_ray_val,
            "two_rays": bool(two_ray_val > 0),
            "two_ray_mode": two_ray_mode,
            "clutter_file": self.clutter_path.text() or None,
            "ground_clutter": self.gc.value(),
            "obstacles": list(params_mod.iter_obstacles(self.obstacles.toPlainText())),
            "engine": self.engine.currentText(),
            "dem_source": "offline" if self.dem_source.currentIndex() in (1, 2) else "online",
            "dem_kind": "srtm" if self.dem_source.currentIndex() == 2 else ("demnas" if self.dem_source.currentIndex() == 1 else "online"),
            "demnas_dir": self.demnas_dir.text().strip() or None,
            "terrain_source": "lidar" if self.terrain.currentText().startswith("LIDAR") else "sdf",
            "sdf_dir": self.sdf_path.text() or None,
            "lidar_file": self.lidar_path.text() or None,
            "resolution": self.resolution.currentData(),
            "radius": self.radius.value(),
            "plot_quality": self.plot_quality.currentData(),
            "plot_segments": int(self.map_segments.value()),
            "color_file": self.color_path.text() or None,
            "color_file_user": getattr(self, "_color_user_chosen", False),
            "dbm_color": self.dbm_color.isChecked(),
            "transparent_holes": self.transparent_holes.isChecked(),
            "kmz_contour_mode": self.kmz_contour_mode.currentIndex(),
            "kmz_flat": bool(self.kmz_contour_mode.currentIndex() == 1),
            "raster_txt": self.raster_txt.isChecked(),
            "units": units,
            "dem_resolution": dem_res_map[self.dem_res.currentIndex()],
            "dem_downsample": self._dem_downsample.isChecked(),
            "dem_fine_step": self._dem_fine_step.isChecked(),
        }
        return d

    def load(self, d: dict) -> None:
        """Restore all form fields from a previously saved ``collect()`` dict."""
        if not isinstance(d, dict):
            return
        # Site / Tx
        if hasattr(self, "units"):
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
        self.tx_thr.setValue(float(d.get("tx_threshold_dbm", -100)))
        self._update_erp()
        # Antenna
        self.set_antenna_basename(d.get("antenna_basename") or "")
        self.pol.setCurrentText(d.get("polarization", "vertical"))
        self.azimuth.setValue(float(d.get("azimuth_deg", 0)))
        self.downtilt.setValue(float(d.get("downtilt_deg", 0)))
        self.downtilt_dir.setValue(float(d.get("downtilt_dir_deg", 0)))
        self.az_mask.setChecked(bool(d.get("az_mask_enabled", False)))
        self.az_start.setValue(float(d.get("az_mask_start_deg", 0.1)))
        self.az_end.setValue(float(d.get("az_mask_end_deg", 360.0)))
        # Mobile / Rx
        self.rx_name.setText(d.get("rx_name") or "")
        self.rx_coord.set(d.get("rx_lat"), d.get("rx_lon"))
        self.rx_height.setValue(float(d.get("rx_height", 1.5)))
        self.rx_power.setValue(float(d.get("rx_power_w", 1.0)))
        if "rx_gain_dbi" in d:
            self.rx_gain.setValue(float(d.get("rx_gain_dbi", 0)))
        elif "rx_gain_dbd" in d:
            self.rx_gain.setValue(float(d.get("rx_gain_dbd", 0)) + 2.15)
        else:
            self.rx_gain.setValue(float(d.get("rx_gain", 0)))
        self.rx_thr.setValue(float(d.get("rx_threshold_dbm", -100)))
        self.rx_cable_loss.setValue(float(d.get("rx_cable_loss_db", d.get("rx_line_loss_db", 0.5))))
        self._update_rx_erp()
        # rx_thr_uv (and tx_thr_uv) are kept in sync via valueChanged.
        # Model
        model_idx = self.model.findData(int(d.get("model_pm", 3)))
        if model_idx >= 0:
            self.model.setCurrentIndex(model_idx)
        self.reliability.setCurrentText(f"{int(d.get('reliability', 50))}%")
        ctx_map = {1: "Urban", 2: "Suburban", 3: "Rural"}
        self.context.setCurrentText(ctx_map.get(int(d.get("context_pe", 3)), "Rural"))
        self.diffraction.setCurrentText("Knife-edge (KED)" if d.get("knife_edge") else "Off (LOS)")
        tw_val = d.get("tworay", 1 if d.get("two_rays") else 0)
        if isinstance(tw_val, bool):
            tw_val = 2 if tw_val else 0
        idx_tw = self.two_rays.findData(tw_val)
        if idx_tw >= 0:
            self.two_rays.setCurrentIndex(idx_tw)
        # Environment
        climate = d.get("climate_zone")
        if climate is not None:
            idx = self.climate.findData(climate)
            if idx < 0:                       # stale/unknown value -> default
                idx = 0
            self.climate.setCurrentIndex(idx)
        if hasattr(self, "clutter_path"):
            self.clutter_path.setText(d.get("clutter_file") or "")
        if hasattr(self, "gc"):
            self.gc.setValue(float(d.get("ground_clutter", 0)))
        if hasattr(self, "obstacles"):
            self.obstacles.setPlainText("\n".join(str(o) for o in d.get("obstacles", [])))
        # Output / Engine
        engine_name = d.get("engine", "Standard")
        self.engine.setCurrentText(engine_name)
        self._on_engine_changed(engine_name)
        if d.get("dem_kind") == "srtm" or d.get("dem_source") == "srtm":
            self.dem_source.setCurrentIndex(2)
        elif d.get("dem_source") == "offline":
            self.dem_source.setCurrentIndex(1)
        else:
            self.dem_source.setCurrentIndex(0)
        self.demnas_dir.setText(d.get("demnas_dir") or "")
        self._update_demnas_visibility()
        self.sdf_path.setText(d.get("sdf_dir") or "")
        self.lidar_path.setText(d.get("lidar_file") or "")
        res = d.get("resolution", 1200)
        res_idx = self.resolution.findData(res)
        if res_idx >= 0:
            self.resolution.setCurrentIndex(res_idx)
        self.radius.setValue(float(d.get("radius", 30)))
        if "plot_segments" in d:
            try:
                self.map_segments.setValue(int(d.get("plot_segments", params_mod.auto_segments())))
            except Exception:
                pass
        q = d.get("plot_quality", "final")
        qi = self.plot_quality.findData(q)
        if qi >= 0:
            self.plot_quality.setCurrentIndex(qi)
        self.set_color_file(d.get("color_file") or "")
        self.dbm_color.setChecked(bool(d.get("dbm_color", True)))
        self.transparent_holes.setChecked(bool(d.get("transparent_holes", True)))
        if hasattr(self, "kmz_contour_mode"):
            if "kmz_contour_mode" in d:
                self.kmz_contour_mode.setCurrentIndex(int(d["kmz_contour_mode"]))
            elif "kmz_flat" in d:
                self.kmz_contour_mode.setCurrentIndex(1 if d["kmz_flat"] else 0)
        self.raster_txt.setChecked(bool(d.get("raster_txt", False)))
        if hasattr(self, "_dem_downsample"):
            self._dem_downsample.setChecked(bool(d.get("dem_downsample", False)))
        if hasattr(self, "_dem_fine_step"):
            self._dem_fine_step.setChecked(bool(d.get("dem_fine_step", True)))
        # Re-apply model-dependent disabling/badges for the loaded model.
        self._apply_model_gating()


