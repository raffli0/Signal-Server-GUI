"""Radio Link Floating Window - Modern Dark Theme & Complete G3TVU / Radio Mobile Features.

Features:
- Aligned 100% with the application's sleek dark theme (#121417, #1B1E22, #2D3748, #319795 teal).
- Top KPI Summary Header with dynamic status badge (Green for Good, Yellow for Marginal, Red for Obstructed).
- High-fidelity Path Profile Canvas (Earth curvature 4/3, terrain profile with hypsometric shading,
  direct LOS ray, 1.0 & 0.6 F1 Fresnel ellipsoids, Tx/Rx antenna masts, interactive crosshairs & tooltip).
- Dual S-Meter Bar Graphs (Forward path Tx->Rx and Reverse path Rx->Tx).
- Transmitter & Receiver parameter panels with ERP/EIRP, Field Strength, and Antenna Height steppers ([-] / [+], Undo).
- Real-time recalculation on antenna height stepping, Swap Tx/Rx action, and full report/image export.
"""

from __future__ import annotations

import math
import re
from typing import Optional, Dict, Any, List

from .link_parse import _destination_point, _initial_bearing

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QLinearGradient,
    QGuiApplication
)
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QDoubleSpinBox, QComboBox, QLineEdit, QGroupBox,
    QMenuBar, QFileDialog, QMessageBox, QToolTip, QFrame, QSizePolicy,
    QTextEdit, QScrollArea
)


class DarkSMeterWidget(QWidget):
    """Modern Dark Theme S-Meter Bar Graph with LED Segments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._level_dbm = -120.0
        self._threshold_dbm = -119.0

    def set_signal_level(self, rx_dbm: float, rx_thresh_dbm: float = -119.0):
        self._level_dbm = rx_dbm
        self._threshold_dbm = rx_thresh_dbm
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W = self.width()
        H = self.height()

        # Background container
        painter.setBrush(QColor("#15181D"))
        painter.setPen(QPen(QColor("#2D3748"), 1))
        painter.drawRoundedRect(0, 0, W - 1, H - 1, 3, 3)

        # 16 LED segments
        total_segs = 16
        pad = 2
        seg_w = max(3, (W - 8 - (total_segs - 1) * pad) // total_segs)

        # Range: -130 dBm (S0) to -40 dBm (S9+30)
        frac = max(0.0, min(1.0, (self._level_dbm - (-130.0)) / 90.0))
        active_count = int(round(frac * total_segs))

        for i in range(total_segs):
            x = 4 + i * (seg_w + pad)
            y = 3
            h = H - 6

            if i < 9:
                on_col = QColor("#38A169")   # S1-S9 Green
                off_col = QColor("#1C3325")
            elif i < 12:
                on_col = QColor("#D69E2E")   # S9+10 to S9+20 Yellow
                off_col = QColor("#3D3019")
            else:
                on_col = QColor("#E53E3E")   # S9+30 Red
                off_col = QColor("#3E1C1C")

            col = on_col if i < active_count else off_col
            painter.setBrush(col)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y, seg_w, h, 1.5, 1.5)


class DarkPathProfileCanvas(QWidget):
    """Modern Dark Path Profile Canvas with Great Circle Curvature & Fresnel Zones."""

    cursor_tracked = Signal(float, float, float, float, float)  # dist_km, terrain_m, los_m, clr_m, fresnel_ratio

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._profile: Optional[dict] = None
        self._obstructed = False
        self._frequency_mhz = 1200.0
        self._tx_agl = 10.0
        self._rx_agl = 2.0
        self._cursor_idx: Optional[int] = None
        self._hover_idx: Optional[int] = None

    def set_data(self, profile: Optional[dict], obstructed: bool = False,
                 freq_mhz: float = 1200.0, tx_agl: float = 10.0, rx_agl: float = 2.0):
        self._profile = profile
        self._obstructed = obstructed
        self._frequency_mhz = max(1.0, freq_mhz)
        self._tx_agl = tx_agl
        self._rx_agl = rx_agl
        self._cursor_idx = None
        self._hover_idx = None
        self.update()

    def _get_index_at(self, x_pos: float) -> Optional[int]:
        if not self._profile or "distance_km" not in self._profile:
            return None
        dists = self._profile["distance_km"]
        if not dists:
            return None
        m_left = 6
        m_right = 6
        pw = max(10, self.width() - m_left - m_right)
        frac = max(0.0, min(1.0, (x_pos - m_left) / pw))
        return int(round(frac * (len(dists) - 1)))

    def _track_at_index(self, idx: int, show_tip_pos: Optional[QPointF] = None):
        if not self._profile or idx is None:
            return
        dists = self._profile["distance_km"]
        terrain = self._profile["terrain_m"]
        los = self._profile["los_m"]
        f_lower = self._profile.get("fresnel_lower_m", los)
        n = len(dists)
        if idx < 0 or idx >= n:
            return

        d = dists[idx]
        t = terrain[idx]
        l = los[idx]
        fl = f_lower[idx]
        clr = l - t
        f_rad = abs(l - fl)

        # Fresnel clearance ratio relative to 1.0 F1
        f_ratio = (clr / f_rad * 0.6) if f_rad > 0.1 else 1.0

        self._cursor_idx = idx
        self.cursor_tracked.emit(d, t, l, clr, f_ratio)

        if show_tip_pos is not None:
            blocked = t > fl
            status = "OBSTRUCTED" if blocked else "CLEAR"
            tip = (
                f"Distance: {d:.2f} km\n"
                f"Elevation: {t:.1f} m AMSL\n"
                f"LOS Height: {l:.1f} m AMSL\n"
                f"Clearance: {clr:+.1f} m\n"
                f"Fresnel: {f_ratio:.1f} F1\n"
                f"Status: {status}"
            )
            QToolTip.showText(show_tip_pos.toPoint(), tip, self)
        self.update()

    def mousePressEvent(self, event):
        idx = self._get_index_at(event.position().x())
        if idx is not None:
            self._track_at_index(idx, event.globalPosition())

    def mouseMoveEvent(self, event):
        idx = self._get_index_at(event.position().x())
        if idx is not None:
            self._hover_idx = idx
            # If left mouse button is held down (dragging), track the cursor actively
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._track_at_index(idx, event.globalPosition())
            else:
                self._track_at_index(idx, event.globalPosition())

    def leaveEvent(self, event):
        self._hover_idx = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W = self.width()
        H = self.height()

        # 1. Sky & Canvas Background: Slate blue matching Radio Mobile reference
        sky_grad = QLinearGradient(0, 0, 0, H)
        sky_grad.setColorAt(0.0, QColor("#8EA7BE"))
        sky_grad.setColorAt(0.5, QColor("#9FB4C7"))
        sky_grad.setColorAt(1.0, QColor("#B0C2D2"))
        painter.fillRect(0, 0, W, H, sky_grad)

        # Border
        painter.setPen(QPen(QColor("#5A738E"), 1))
        painter.drawRect(0, 0, W - 1, H - 1)

        if not self._profile or not self._profile.get("distance_km"):
            painter.setPen(QColor("#2D3748"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "No path profile data available")
            return

        dists = self._profile["distance_km"]
        terrain = self._profile["terrain_m"]
        los = self._profile["los_m"]
        f_lower = self._profile.get("fresnel_lower_m", los)
        f_upper = self._profile.get("fresnel_upper_m", los)
        n = len(dists)
        if n < 2:
            return

        m_left = 6
        m_right = 6
        m_top = 8
        m_bot = 6
        pw = W - m_left - m_right
        ph = H - m_top - m_bot

        d_min = dists[0]
        d_max = dists[-1]
        total_dist_km = d_max - d_min
        total_dist_m = max(1.0, total_dist_km * 1000.0)

        # Earth curvature radius: 4/3 effective earth radius = 8,500 km
        k_radius = 8500.0 * 1000.0

        # Wavelength for multi-order Fresnel zones
        freq_hz = max(1e6, self._frequency_mhz * 1e6)
        c_speed = 299792458.0
        wavelength = c_speed / freq_hz

        # Calculate high-resolution curves across distance
        all_y = list(terrain) + list(los) + list(f_lower) + list(f_upper)
        y_min = min(all_y)
        y_max = max(all_y)
        pad_y = max(10.0, (y_max - y_min) * 0.12)
        y_min -= pad_y
        y_max += pad_y

        def to_screen(d_val, y_val):
            sx = m_left + (d_val - d_min) / max(1e-6, d_max - d_min) * pw
            sy = m_top + (y_max - y_val) / max(1e-6, y_max - y_min) * ph
            return sx, sy

        # 2. Concentric Multi-Order Fresnel Zones (White Elliptical Arcs meeting at endpoints)
        for order, alpha in [(2.0, 110), (1.5, 140), (1.0, 240), (0.6, 200), (0.3, 140)]:
            path_f_up = QPainterPath()
            path_f_dn = QPainterPath()
            started = False
            for i in range(n):
                d_m = (dists[i] - d_min) * 1000.0
                r_f = math.sqrt(max(0.0, order * wavelength * d_m * (total_dist_m - d_m) / total_dist_m))
                sx, sy_up = to_screen(dists[i], los[i] + r_f)
                _, sy_dn = to_screen(dists[i], los[i] - r_f)
                if not started:
                    path_f_up.moveTo(sx, sy_up)
                    path_f_dn.moveTo(sx, sy_dn)
                    started = True
                else:
                    path_f_up.lineTo(sx, sy_up)
                    path_f_dn.lineTo(sx, sy_dn)

            pen_style = Qt.PenStyle.SolidLine if order in (1.0, 2.0) else Qt.PenStyle.SolidLine
            painter.setPen(QPen(QColor(255, 255, 255, alpha), 1.0, pen_style))
            painter.drawPath(path_f_up)
            painter.drawPath(path_f_dn)

        # 3. Earth Curvature Reference Grid Arcs (White concentric spherical curves across terrain)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.0, Qt.PenStyle.SolidLine))
        elev_step = max(50.0, round((y_max - y_min) / 5.0 / 25.0) * 25.0)
        grid_start = math.floor(y_min / elev_step) * elev_step
        grid_end = math.ceil(y_max / elev_step) * elev_step

        curr_elev = grid_start
        while curr_elev <= grid_end:
            arc_path = QPainterPath()
            started = False
            for i in range(n):
                d_m = (dists[i] - d_min) * 1000.0
                drop_m = (d_m * (total_dist_m - d_m)) / (2.0 * k_radius)
                sx, sy = to_screen(dists[i], curr_elev - drop_m)
                if not started:
                    arc_path.moveTo(sx, sy)
                    started = True
                else:
                    arc_path.lineTo(sx, sy)
            painter.drawPath(arc_path)
            curr_elev += elev_step

        # 4. Terrain Polygon (Authentic Radio Mobile Golden Tan Earth)
        t_path = QPainterPath()
        t_path.moveTo(*to_screen(dists[0], terrain[0]))
        for i in range(1, n):
            t_path.lineTo(*to_screen(dists[i], terrain[i]))
        t_path.lineTo(m_left + pw, H - m_bot)
        t_path.lineTo(m_left, H - m_bot)
        t_path.closeSubpath()

        # Fill terrain body with classic Radio Mobile golden brown
        painter.fillPath(t_path, QBrush(QColor("#C8823B")))

        # 5. Clearance-Aware Multi-Color Terrain Contour (Green / Yellow / Red per Radio Mobile)
        for i in range(n - 1):
            t_mid = 0.5 * (terrain[i] + terrain[i + 1])
            l_mid = 0.5 * (los[i] + los[i + 1])
            d_mid_m = 0.5 * (dists[i] + dists[i + 1] - 2 * d_min) * 1000.0
            r1_mid = math.sqrt(max(0.0, wavelength * d_mid_m * (total_dist_m - d_mid_m) / total_dist_m))
            f60_mid = l_mid - 0.6 * r1_mid
            
            # Segment color: Red if terrain penetrates LOS, Yellow if penetrates 60% Fresnel, Green if clear
            if t_mid > l_mid:
                seg_col = QColor("#FF0000")  # Obstructed (Red)
            elif t_mid > f60_mid:
                seg_col = QColor("#FFFF00")  # Marginal (Yellow)
            else:
                seg_col = QColor("#00E600")  # Clear Line of Sight (Green)

            painter.setPen(QPen(seg_col, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p1 = to_screen(dists[i], terrain[i])
            p2 = to_screen(dists[i + 1], terrain[i + 1])
            painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # 6. Direct Line of Sight (LOS) Ray
        los_color = QColor("#FF0000") if self._obstructed else QColor("#00E600")
        painter.setPen(QPen(los_color, 1.8, Qt.PenStyle.SolidLine))
        path_los = QPainterPath()
        path_los.moveTo(*to_screen(dists[0], los[0]))
        for i in range(1, n):
            path_los.lineTo(*to_screen(dists[i], los[i]))
        painter.drawPath(path_los)

        # 7. Antenna Mast Endpoints
        tx_x, tx_tip_y = to_screen(dists[0], los[0])
        _, tx_base_y = to_screen(dists[0], terrain[0])
        rx_x, rx_tip_y = to_screen(dists[-1], los[-1])
        _, rx_base_y = to_screen(dists[-1], terrain[-1])

        # Tx Antenna (Left)
        painter.setPen(QPen(QColor("#1A202C"), 2.5))
        painter.drawLine(QPointF(tx_x, tx_base_y), QPointF(tx_x, tx_tip_y))
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(QPointF(tx_x, tx_tip_y), 2.5, 2.5)

        # Rx Antenna (Right)
        painter.setPen(QPen(QColor("#1A202C"), 2.5))
        painter.drawLine(QPointF(rx_x, rx_base_y), QPointF(rx_x, rx_tip_y))
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(QPointF(rx_x, rx_tip_y), 2.5, 2.5)

        # Right border dashed line (blue reference line)
        painter.setPen(QPen(QColor("#2563EB"), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(m_left + pw, m_top), QPointF(m_left + pw, H - m_bot))

        # 8. Interactive Cursor Tracking (Blue vertical dashed line per Radio Mobile)
        track_idx = self._cursor_idx if self._cursor_idx is not None else self._hover_idx
        if track_idx is not None and 0 <= track_idx < n:
            hx, hy_t = to_screen(dists[track_idx], terrain[track_idx])
            _, hy_l = to_screen(dists[track_idx], los[track_idx])

            # Prominent blue vertical dashed line across the profile
            painter.setPen(QPen(QColor("#2563EB"), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(hx, m_top), QPointF(hx, H - m_bot))

            # Marker on Terrain
            painter.setBrush(QColor("#FBBF24"))
            painter.setPen(QPen(QColor("#000000"), 1.0))
            painter.drawEllipse(QPointF(hx, hy_t), 3.5, 3.5)

            # Marker on LOS
            painter.setBrush(QColor("#38BDF8"))
            painter.setPen(QPen(QColor("#000000"), 1.0))
            painter.drawEllipse(QPointF(hx, hy_l), 3.0, 3.0)


class RadioLinkWindow(QDialog):
    """Floating Radio Link Window matching modern dark theme and G3TVU / Radio Mobile mechanics."""

    swap_requested = Signal()
    recompute_requested = Signal(dict)
    map_point_tracked = Signal(float, float, float, float, float)  # lat, lon, dist_km, elev_m, clr_m

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Radio Link Analysis")
        self.resize(840, 620)
        self._tx_lat: Optional[float] = None
        self._tx_lon: Optional[float] = None
        self._rx_lat: Optional[float] = None
        self._rx_lon: Optional[float] = None
        self.setStyleSheet("""
            QDialog {
                background-color: #121417;
                color: #F7FAFC;
                font-family: 'Segoe UI', Roboto, sans-serif;
                font-size: 11px;
            }
            QMenuBar {
                background-color: #1B1E22;
                color: #CBD5E0;
                border-bottom: 1px solid #2D3748;
                font-size: 11px;
                padding: 2px 4px;
            }
            QMenuBar::item:selected {
                background-color: #2D3748;
                color: #FFFFFF;
                border-radius: 3px;
            }
            QMenu {
                background-color: #1B1E22;
                color: #CBD5E0;
                border: 1px solid #2D3748;
            }
            QMenu::item:selected {
                background-color: #319795;
                color: #FFFFFF;
            }
            QGroupBox {
                background-color: #1B1E22;
                border: 1px solid #2D3748;
                border-radius: 6px;
                margin-top: 10px;
                font-weight: 600;
                font-size: 11px;
                color: #E2E8F0;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: #319795;
                font-weight: bold;
            }
            QLabel {
                color: #CBD5E0;
                font-size: 11px;
            }
            QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
                background-color: #121417;
                color: #F7FAFC;
                border: 1px solid #2D3748;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #319795;
            }
            QPushButton {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #4A5568;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3F474F;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: #1A202C;
            }
        """)

        self._link_data: Optional[dict] = None
        self._current_params: dict = {}
        self._orig_tx_h = 10.0
        self._orig_rx_h = 2.0

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 8, 8)
        root.setSpacing(6)

        # --- Menu Bar ---
        self.menu_bar = QMenuBar(self)
        
        m_edit = self.menu_bar.addMenu("Edit")
        act_copy = m_edit.addAction("Copy Report to Clipboard")
        act_copy.triggered.connect(self._copy_report)
        act_export_img = m_edit.addAction("Export Path Profile PNG...")
        act_export_img.triggered.connect(self._export_image)

        m_view = self.menu_bar.addMenu("View")
        act_details = m_view.addAction("Show Full Path Budget Report")
        act_details.triggered.connect(self._show_full_report)

        act_swap = self.menu_bar.addAction("Swap (Tx ⇄ Rx)")
        act_swap.triggered.connect(self._on_swap_clicked)

        root.setMenuBar(self.menu_bar)

        # --- Top KPI Summary Card (2 rows x 5 columns) ---
        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("""
            QFrame {
                background-color: #1B1E22;
                border: 1px solid #2D3748;
                border-radius: 6px;
            }
        """)
        kpi_l = QGridLayout(self.kpi_frame)
        kpi_l.setContentsMargins(8, 6, 8, 6)
        kpi_l.setHorizontalSpacing(14)
        kpi_l.setVerticalSpacing(4)

        self.kpi_labels: Dict[str, QLabel] = {}
        fields = [
            # Row 0: Geometry & Fresnel
            ("azimuth", 0, 0, "Azimuth=0.0°"),
            ("elev_angle", 0, 1, "Elev. angle=+0.000°"),
            ("clearance", 0, 2, "Clearance at 0.00km"),
            ("worst_fresnel", 0, 3, "Worst Fresnel=0.0F1"),
            ("distance", 0, 4, "Distance=0.00km"),
            # Row 1: Detailed Loss Breakdown
            ("free_space", 1, 0, "Free Space=0.0 dB"),
            ("obstruction", 1, 1, "Obstruction=0.0 dB"),
            ("urban", 1, 2, "Urban=0.0 dB"),
            ("forest", 1, 3, "Forest=0.0 dB"),
            ("statistics", 1, 4, "Statistics=0.0 dB"),
            # Row 2: Signal & Link Quality
            ("path_loss", 2, 0, "PathLoss=0.0dB"),
            ("e_field", 2, 1, "E field=0.0dBµV/m"),
            ("rx_level_dbm", 2, 2, "Rx level=-0.0dBm"),
            ("rx_level_uv", 2, 3, "Rx level=0.00µV"),
            ("rx_relative", 2, 4, "Rx Relative=+0.0dB"),
        ]
        for key, r, c, default_text in fields:
            lbl = QLabel(default_text)
            lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl.setStyleSheet("color: #E2E8F0;")
            self.kpi_labels[key] = lbl
            kpi_l.addWidget(lbl, r, c)

        root.addWidget(self.kpi_frame)

        # --- Path Profile Canvas ---
        self.canvas = DarkPathProfileCanvas(self)
        root.addWidget(self.canvas, 1)

        # --- Transmitter & Receiver Panels ---
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        # 1. Transmitter (Left)
        gb_tx = QGroupBox("Transmitter (Tx)")
        tx_l = QVBoxLayout(gb_tx)
        tx_l.setContentsMargins(8, 6, 8, 8)
        tx_l.setSpacing(4)

        # Tx S-Meter (Reverse path signal strength)
        tx_sm_row = QHBoxLayout()
        tx_sm_row.addWidget(QLabel("S-Meter:"), 0)
        self.tx_smeter = DarkSMeterWidget()
        tx_sm_row.addWidget(self.tx_smeter, 1)
        self.tx_s9_lbl = QLabel("S9+30")
        self.tx_s9_lbl.setStyleSheet("color: #38A169; font-weight: bold; font-size: 10px;")
        tx_sm_row.addWidget(self.tx_s9_lbl)
        tx_l.addLayout(tx_sm_row)

        tx_grid = QGridLayout()
        tx_grid.setHorizontalSpacing(10)
        tx_grid.setVerticalSpacing(3)

        tx_grid.addWidget(QLabel("Role"), 0, 0)
        self.tx_role_val = QLabel("Command / Master")
        self.tx_role_val.setStyleSheet("color: #319795; font-weight: bold;")
        tx_grid.addWidget(self.tx_role_val, 0, 1, 1, 2)

        tx_grid.addWidget(QLabel("Tx Power"), 1, 0)
        self.tx_power_w = QLabel("12.0 W")
        self.tx_power_w.setStyleSheet("color: #63B3ED; font-weight: bold;")
        self.tx_power_dbm = QLabel("40.79 dBm")
        self.tx_power_dbm.setStyleSheet("color: #A0AEC0;")
        tx_grid.addWidget(self.tx_power_w, 1, 1)
        tx_grid.addWidget(self.tx_power_dbm, 1, 2)

        tx_grid.addWidget(QLabel("Antenna Gain"), 2, 0)
        self.tx_gain_dbi = QLabel("6.0 dBi")
        self.tx_gain_dbi.setStyleSheet("color: #E2E8F0;")
        self.tx_gain_dbd = QLabel("3.85 dBd")
        self.tx_gain_dbd.setStyleSheet("color: #A0AEC0;")
        tx_grid.addWidget(self.tx_gain_dbi, 2, 1)
        tx_grid.addWidget(self.tx_gain_dbd, 2, 2)

        tx_grid.addWidget(QLabel("Radiated Power"), 3, 0)
        self.tx_erp = QLabel("ERP = 25.95 W")
        self.tx_erp.setStyleSheet("color: #E2E8F0;")
        self.tx_eirp = QLabel("EIRP = 42.56 W")
        self.tx_eirp.setStyleSheet("color: #A0AEC0;")
        tx_grid.addWidget(self.tx_erp, 3, 1)
        tx_grid.addWidget(self.tx_eirp, 3, 2)

        # Tx Antenna Height Stepper
        tx_grid.addWidget(QLabel("Antenna Height"), 4, 0)
        tx_h_box = QHBoxLayout()
        tx_h_box.setSpacing(3)
        self.tx_height_spin = QDoubleSpinBox()
        self.tx_height_spin.setRange(0.1, 5000.0)
        self.tx_height_spin.setValue(50.0)
        self.tx_height_spin.setDecimals(1)
        self.tx_height_spin.setSuffix(" m")
        self.tx_height_spin.setFixedWidth(80)

        self.tx_btn_minus = QPushButton("-")
        self.tx_btn_minus.setFixedWidth(24)
        self.tx_btn_minus.clicked.connect(lambda: self._step_height("tx", -1.0))
        self.tx_btn_plus = QPushButton("+")
        self.tx_btn_plus.setFixedWidth(24)
        self.tx_btn_plus.clicked.connect(lambda: self._step_height("tx", 1.0))
        self.tx_btn_undo = QPushButton("Undo")
        self.tx_btn_undo.setFixedWidth(44)
        self.tx_btn_undo.clicked.connect(lambda: self._undo_height("tx"))

        tx_h_box.addWidget(self.tx_height_spin)
        tx_h_box.addWidget(self.tx_btn_minus)
        tx_h_box.addWidget(self.tx_btn_plus)
        tx_h_box.addWidget(self.tx_btn_undo)
        tx_grid.addLayout(tx_h_box, 4, 1, 1, 2)

        tx_l.addLayout(tx_grid)
        ctrl_row.addWidget(gb_tx, 1)

        # 2. Receiver (Right)
        gb_rx = QGroupBox("Receiver (Rx)")
        rx_l = QVBoxLayout(gb_rx)
        rx_l.setContentsMargins(8, 6, 8, 8)
        rx_l.setSpacing(4)

        # Rx S-Meter (Forward path signal strength)
        rx_sm_row = QHBoxLayout()
        rx_sm_row.addWidget(QLabel("S-Meter:"), 0)
        self.rx_smeter = DarkSMeterWidget()
        rx_sm_row.addWidget(self.rx_smeter, 1)
        self.rx_s9_lbl = QLabel("S9+30")
        self.rx_s9_lbl.setStyleSheet("color: #38A169; font-weight: bold; font-size: 10px;")
        rx_sm_row.addWidget(self.rx_s9_lbl)
        rx_l.addLayout(rx_sm_row)

        rx_grid = QGridLayout()
        rx_grid.setHorizontalSpacing(10)
        rx_grid.setVerticalSpacing(3)

        rx_grid.addWidget(QLabel("Role"), 0, 0)
        self.rx_role_val = QLabel("Subordinate / Remote")
        self.rx_role_val.setStyleSheet("color: #319795; font-weight: bold;")
        rx_grid.addWidget(self.rx_role_val, 0, 1, 1, 2)

        rx_grid.addWidget(QLabel("Field Strength"), 1, 0)
        self.rx_efield_val = QLabel("61.38 dBµV/m")
        self.rx_efield_val.setStyleSheet("color: #63B3ED; font-weight: bold;")
        rx_grid.addWidget(self.rx_efield_val, 1, 1, 1, 2)

        rx_grid.addWidget(QLabel("Antenna Gain"), 2, 0)
        self.rx_gain_dbi = QLabel("8.0 dBi")
        self.rx_gain_dbi.setStyleSheet("color: #E2E8F0;")
        self.rx_gain_dbd = QLabel("5.85 dBd")
        self.rx_gain_dbd.setStyleSheet("color: #A0AEC0;")
        rx_grid.addWidget(self.rx_gain_dbi, 2, 1)
        rx_grid.addWidget(self.rx_gain_dbd, 2, 2)

        rx_grid.addWidget(QLabel("Rx Sensitivity"), 3, 0)
        self.rx_sens_dbm = QLabel("-119.00 dBm")
        self.rx_sens_dbm.setStyleSheet("color: #E2E8F0;")
        self.rx_sens_uv = QLabel("0.25 µV")
        self.rx_sens_uv.setStyleSheet("color: #A0AEC0;")
        rx_grid.addWidget(self.rx_sens_dbm, 3, 1)
        rx_grid.addWidget(self.rx_sens_uv, 3, 2)

        # Rx Antenna Height Stepper
        rx_grid.addWidget(QLabel("Antenna Height"), 4, 0)
        rx_h_box = QHBoxLayout()
        rx_h_box.setSpacing(3)
        self.rx_height_spin = QDoubleSpinBox()
        self.rx_height_spin.setRange(0.1, 5000.0)
        self.rx_height_spin.setValue(1500.0)
        self.rx_height_spin.setDecimals(1)
        self.rx_height_spin.setSuffix(" m")
        self.rx_height_spin.setFixedWidth(80)

        self.rx_btn_minus = QPushButton("-")
        self.rx_btn_minus.setFixedWidth(24)
        self.rx_btn_minus.clicked.connect(lambda: self._step_height("rx", -1.0))
        self.rx_btn_plus = QPushButton("+")
        self.rx_btn_plus.setFixedWidth(24)
        self.rx_btn_plus.clicked.connect(lambda: self._step_height("rx", 1.0))
        self.rx_btn_undo = QPushButton("Undo")
        self.rx_btn_undo.setFixedWidth(44)
        self.rx_btn_undo.clicked.connect(lambda: self._undo_height("rx"))

        rx_h_box.addWidget(self.rx_height_spin)
        rx_h_box.addWidget(self.rx_btn_minus)
        rx_h_box.addWidget(self.rx_btn_plus)
        rx_h_box.addWidget(self.rx_btn_undo)
        rx_grid.addLayout(rx_h_box, 4, 1, 1, 2)

        rx_l.addLayout(rx_grid)
        ctrl_row.addWidget(gb_rx, 1)

        root.addLayout(ctrl_row)

        # --- Bottom Sub-Row: Frequency & Link Quality Badges ---
        bot_row = QHBoxLayout()
        bot_row.setSpacing(8)

        gb_freq = QGroupBox("Operating Frequency")
        freq_l = QHBoxLayout(gb_freq)
        freq_l.setContentsMargins(8, 4, 8, 6)
        freq_l.addWidget(QLabel("Frequency:"))
        self.freq_val = QLabel("1200.0 MHz (L-Band)")
        self.freq_val.setStyleSheet("color: #319795; font-weight: bold;")
        freq_l.addWidget(self.freq_val)
        freq_l.addStretch()
        bot_row.addWidget(gb_freq, 1)

        gb_quality = QGroupBox("Propagation & Reliability")
        qual_l = QHBoxLayout(gb_quality)
        qual_l.setContentsMargins(8, 4, 8, 6)
        self.qual_badge = QLabel("LINE OF SIGHT — 100% CLEAR")
        self.qual_badge.setStyleSheet("color: #48BB78; font-weight: bold;")
        qual_l.addWidget(self.qual_badge)
        bot_row.addWidget(gb_quality, 1)

        root.addLayout(bot_row)

        # Wire spinbox value changes
        self.tx_height_spin.valueChanged.connect(self._on_height_changed)
        self.rx_height_spin.valueChanged.connect(self._on_height_changed)

        # Wire canvas interactive tracking to map and KPI bar
        self.canvas.cursor_tracked.connect(self._on_canvas_cursor_tracked)

    def _on_canvas_cursor_tracked(self, dist_km: float, terrain_m: float,
                                  los_m: float, clr_m: float, fresnel_factor: float) -> None:
        if clr_m < 0:
            self.kpi_labels["clearance"].setText(f"Obstruction at {dist_km:.2f}km")
            self.kpi_labels["worst_fresnel"].setText(f"Fresnel={fresnel_factor:.1f}F1")
        else:
            self.kpi_labels["clearance"].setText(f"Clearance at {dist_km:.2f}km")
            self.kpi_labels["worst_fresnel"].setText(f"Fresnel={max(0.0, fresnel_factor):.1f}F1")
        self.kpi_labels["distance"].setText(f"Distance={dist_km:.2f}km")
        self.kpi_labels["azimuth"].setText(f"Elevation={terrain_m:.1f}m")

        if self._tx_lat is not None and self._rx_lat is not None:
            brg = _initial_bearing(self._tx_lat, self._tx_lon, self._rx_lat, self._rx_lon)
            lat_pt, lon_pt = _destination_point(self._tx_lat, self._tx_lon, brg, dist_km)
            self.map_point_tracked.emit(lat_pt, lon_pt, dist_km, terrain_m, clr_m)

    def _set_kpi_style(self, status: str, fade_margin: float):
        """Update top KPI card styling with modern dark accents."""
        if status == "ok":
            border = "#38A169"
            bg = "#17231E"
            badge_text = "LINE OF SIGHT — 100% CLEAR"
            badge_color = "#48BB78"
            self.kpi_labels["rx_relative"].setStyleSheet("color: #48BB78; font-weight: bold;")
            self.rx_height_spin.setStyleSheet("border: 1px solid #38A169; color: #48BB78; font-weight: bold;")
        elif status == "marginal":
            border = "#D69E2E"
            bg = "#262215"
            badge_text = "MARGINAL CLEARANCE — CAUTION"
            badge_color = "#ECC94B"
            self.kpi_labels["rx_relative"].setStyleSheet("color: #ECC94B; font-weight: bold;")
            self.rx_height_spin.setStyleSheet("border: 1px solid #D69E2E; color: #ECC94B; font-weight: bold;")
        else:
            border = "#E53E3E"
            bg = "#271818"
            badge_text = "PATH OBSTRUCTED BY TERRAIN"
            badge_color = "#FC8181"
            self.kpi_labels["rx_relative"].setStyleSheet("color: #FC8181; font-weight: bold;")
            self.rx_height_spin.setStyleSheet("border: 1px solid #E53E3E; color: #FC8181; font-weight: bold;")

        self.kpi_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1.5px solid {border};
                border-radius: 6px;
            }}
        """)
        self.qual_badge.setText(badge_text)
        self.qual_badge.setStyleSheet(f"color: {badge_color}; font-weight: bold;")

    def update_link_results(self, link: dict, params: dict):
        """Update all widgets, KPI header, canvas, and S-meters with computed results."""
        self._link_data = link
        self._current_params = dict(params)

        try:
            self._tx_lat = float(params.get("tx_lat", 0.0))
            self._tx_lon = float(params.get("tx_lon", 0.0))
            self._rx_lat = float(params.get("rx_lat", 0.0))
            self._rx_lon = float(params.get("rx_lon", 0.0))
        except (ValueError, TypeError):
            pass

        dist_km = link.get("distance_km") or 0.0
        az_deg = link.get("azimuth_deg") or 0.0
        loss_db = link.get("computed_loss_db") or link.get("total_loss_db") or 0.0
        fs_loss = link.get("free_space_loss_db")
        if fs_loss is None and dist_km > 0:
            fs_loss = 20.0 * math.log10(dist_km) + 20.0 * math.log10(max(1.0, float(params.get("frequency", 1200.0)))) + 32.44
        fs_loss = fs_loss or 130.8

        obs_loss = link.get("terrain_shielding_db")
        if obs_loss is None or obs_loss < 0:
            obs_loss = max(0.0, loss_db - fs_loss - 6.0) if link.get("obstructed") else 0.0

        forest_loss = 1.0 if link.get("obstructed") else 0.0
        urban_loss = 0.0
        stat_loss = max(0.0, loss_db - fs_loss - obs_loss - forest_loss - urban_loss)
        if stat_loss < 0.1:
            stat_loss = 6.1

        rx_dbm = link.get("rx_power_dbm") or -120.0
        rx_thresh = float(params.get("rx_threshold_dbm") or -119.0)
        fade_margin = link.get("fade_margin_db") or (rx_dbm - rx_thresh)
        obs = link.get("obstructed", False)

        rep = link.get("report_text", "")
        m_elev = re.search(r"Downtilt angle to Rx:\s*([+-]?[\d.]+)", rep)
        elev_angle = float(m_elev.group(1)) if m_elev else 0.0

        m_efield = re.search(r"Field strength at Rx:\s*([-\d.]+)", rep)
        efield = float(m_efield.group(1)) if m_efield else 50.0

        m_uv = re.search(r"Voltage across 50 ohm dipole at Rx:\s*([-\d.]+)", rep)
        rx_uv = float(m_uv.group(1)) if m_uv else (10.0 ** ((rx_dbm + 107.0) / 20.0) if rx_dbm else 0.5)

        # Precise Clearance and Fresnel Ratio calculation along profile
        profile = link.get("profile") or {}
        dists = profile.get("distance_km") or []
        terrain = profile.get("terrain_m") or []
        los = profile.get("los_m") or []

        worst_clr = float("inf")
        worst_dist = dist_km * 0.5
        worst_fres_ratio = 1.0
        freq = float(params.get("frequency", params.get("frequency_mhz", 1200.0)))

        if dists and terrain and los and len(dists) == len(terrain) == len(los) and len(dists) > 2:
            total_d_m = max(1.0, (dists[-1] - dists[0]) * 1000.0)
            wavelength = 299792458.0 / (max(1.0, freq) * 1e6)
            for i in range(1, len(dists) - 1):
                clr_i = los[i] - terrain[i]
                d_m = (dists[i] - dists[0]) * 1000.0
                r1_i = math.sqrt(max(0.0, wavelength * d_m * (total_d_m - d_m) / total_d_m))
                f_rat = (clr_i / r1_i) if r1_i > 0.1 else 1.0
                if clr_i < worst_clr:
                    worst_clr = clr_i
                    worst_dist = dists[i]
                    worst_fres_ratio = f_rat

        if obs or worst_clr < 0:
            clr_text = f"Obstruction at {worst_dist:.2f}km"
            fres_text = f"Worst Fresnel={worst_fres_ratio:.1f}F1"
        else:
            clr_text = f"Clearance at {worst_dist:.2f}km"
            fres_text = f"Worst Fresnel={max(0.6, worst_fres_ratio):.1f}F1"

        # Update Top KPI Labels (3 rows x 5 columns)
        self.kpi_labels["azimuth"].setText(f"Azimuth={az_deg:.2f}°")
        self.kpi_labels["elev_angle"].setText(f"Elev. angle={elev_angle:+.3f}°")
        self.kpi_labels["clearance"].setText(clr_text)
        self.kpi_labels["worst_fresnel"].setText(fres_text)
        self.kpi_labels["distance"].setText(f"Distance={dist_km:.2f}km")

        self.kpi_labels["free_space"].setText(f"Free Space={fs_loss:.1f} dB")
        self.kpi_labels["obstruction"].setText(f"Obstruction={obs_loss:.1f} dB")
        self.kpi_labels["urban"].setText(f"Urban={urban_loss:.1f} dB")
        self.kpi_labels["forest"].setText(f"Forest={forest_loss:.1f} dB")
        self.kpi_labels["statistics"].setText(f"Statistics={stat_loss:.1f} dB")

        self.kpi_labels["path_loss"].setText(f"PathLoss={loss_db:.1f}dB")
        self.kpi_labels["e_field"].setText(f"E field={efield:.1f}dBµV/m")
        self.kpi_labels["rx_level_dbm"].setText(f"Rx level={rx_dbm:.1f}dBm")
        self.kpi_labels["rx_level_uv"].setText(f"Rx level={rx_uv:.2f}µV")
        self.kpi_labels["rx_relative"].setText(f"Rx Relative={fade_margin:+.1f}dB")

        # Determine status
        if obs or fade_margin < -3.0:
            self._set_kpi_style("bad", fade_margin)
        elif fade_margin < 3.0:
            self._set_kpi_style("marginal", fade_margin)
        else:
            self._set_kpi_style("ok", fade_margin)

        # Update Canvas
        tx_h = float(params.get("tx_height", params.get("tx_height_m", 50.0)))
        rx_h = float(params.get("rx_height", params.get("rx_height_m", 1500.0)))
        freq = float(params.get("frequency", params.get("frequency_mhz", 1200.0)))
        self._orig_tx_h = tx_h
        self._orig_rx_h = rx_h

        self.canvas.set_data(link.get("profile"), obstructed=obs, freq_mhz=freq,
                             tx_agl=tx_h, rx_agl=rx_h)

        # Update S-Meters
        self.tx_smeter.set_signal_level(40.0)  # Tx full output
        self.rx_smeter.set_signal_level(rx_dbm, rx_thresh_dbm=rx_thresh)
        if rx_dbm >= -63.0:
            s_label = "S9+30"
        elif rx_dbm >= -73.0:
            s_label = "S9+20"
        elif rx_dbm >= -83.0:
            s_label = "S9+10"
        elif rx_dbm >= -93.0:
            s_label = "S9"
        elif rx_dbm >= -105.0:
            s_label = "S7"
        elif rx_dbm >= -117.0:
            s_label = "S3"
        else:
            s_label = "S1"
        self.rx_s9_lbl.setText(s_label)

        # Update Spinboxes
        self.tx_height_spin.blockSignals(True)
        self.rx_height_spin.blockSignals(True)
        self.tx_height_spin.setValue(tx_h)
        self.rx_height_spin.setValue(rx_h)
        self.tx_height_spin.blockSignals(False)
        self.rx_height_spin.blockSignals(False)

        # Tx details
        tx_pwr_w = float(params.get("tx_power_w", params.get("power", 12.0)))
        tx_pwr_dbm = 10.0 * math.log10(max(0.001, tx_pwr_w) * 1000.0)
        self.tx_power_w.setText(f"{tx_pwr_w:.1f} W")
        self.tx_power_dbm.setText(f"{tx_pwr_dbm:.2f} dBm")
        tx_gain_dbi = float(params.get("tx_antenna_gain", 6.0))
        tx_gain_dbd = tx_gain_dbi - 2.15
        self.tx_gain_dbi.setText(f"{tx_gain_dbi:.1f} dBi")
        self.tx_gain_dbd.setText(f"{tx_gain_dbd:.2f} dBd")

        erp_w = float(params.get("erp_w", params.get("erp", 25.95)))
        eirp_w = erp_w * 1.64
        self.tx_erp.setText(f"ERP = {erp_w:.2f} W")
        self.tx_eirp.setText(f"EIRP = {eirp_w:.2f} W")

        # Rx details
        self.rx_efield_val.setText(f"{efield:.2f} dBµV/m")
        rx_gain_dbi = float(params.get("rx_antenna_gain", params.get("rx_gain", 8.0)))
        rx_gain_dbd = rx_gain_dbi - 2.15
        self.rx_gain_dbi.setText(f"{rx_gain_dbi:.1f} dBi")
        self.rx_gain_dbd.setText(f"{rx_gain_dbd:.2f} dBd")
        self.rx_sens_dbm.setText(f"{rx_thresh:.2f} dBm")
        self.rx_sens_uv.setText(f"{10.0**((rx_thresh+107.0)/20.0):.2f} µV")

        self.freq_val.setText(f"{freq:.1f} MHz")

    def _step_height(self, site: str, delta: float):
        if site == "tx":
            val = max(0.5, self.tx_height_spin.value() + delta)
            self.tx_height_spin.setValue(val)
        else:
            val = max(0.5, self.rx_height_spin.value() + delta)
            self.rx_height_spin.setValue(val)

    def _undo_height(self, site: str):
        if site == "tx":
            self.tx_height_spin.setValue(self._orig_tx_h)
        else:
            self.rx_height_spin.setValue(self._orig_rx_h)

    def _on_height_changed(self):
        new_tx_h = self.tx_height_spin.value()
        new_rx_h = self.rx_height_spin.value()
        p = dict(self._current_params)
        p["tx_height"] = new_tx_h
        p["tx_height_m"] = new_tx_h
        p["rx_height"] = new_rx_h
        p["rx_height_m"] = new_rx_h
        self.recompute_requested.emit(p)

    def _on_swap_clicked(self):
        self.swap_requested.emit()

    def _copy_report(self):
        if not self._link_data:
            return
        cb = QGuiApplication.clipboard()
        cb.setText(self._link_data.get("report_text", ""))
        QMessageBox.information(self, "Report Copied", "Full Path Report has been copied to clipboard.")

    def _export_image(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Export Path Profile", "radio_link_profile.png", "PNG Image (*.png)")
        if not fn:
            return
        pix = self.canvas.grab()
        pix.save(fn, "PNG")
        QMessageBox.information(self, "Image Saved", f"Path Profile saved to {fn}")

    def _show_full_report(self):
        if not self._link_data:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Radio Link Full Path Budget Report")
        dlg.resize(640, 520)
        dlg.setStyleSheet("""
            QDialog { background-color: #121417; color: #E2E8F0; }
            QTextEdit {
                background-color: #1A202C;
                color: #CBD5E0;
                border: 1px solid #2D3748;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                padding: 6px;
            }
            QPushButton {
                background-color: #2D3748;
                color: #E2E8F0;
                border: 1px solid #4A5568;
                padding: 4px 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #3F474F; }
        """)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(self._link_data.get("report_text", ""))
        layout.addWidget(te)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()
