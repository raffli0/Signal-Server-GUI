"""Cloud-RF Style Integrated Path Profile Panel with 2D Drone / Target Altitude Interaction.

Displays a point-to-point Radio Link Path Profile docked seamlessly below the map,
matching Cloud-RF layout, typography, 4-line link metrics, central big signal callout,
vibrant green terrain profile, Fresnel zone, LOS line, antenna masts, and 2D real-time drone tracking.
"""

from __future__ import annotations

import math
import time
from typing import Optional, Dict, Any, List

from .link_parse import _destination_point, _initial_bearing
from .icons import icon as svg_icon

import numpy as np

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QLinearGradient,
    QPolygonF, QFontMetrics, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolTip,
    QFrame, QSizePolicy, QFileDialog, QMessageBox
)


def compute_terrain_contour_colors(
    dists: list[float],
    terrain: list[float],
    los: list[float],
    f_lower: list[float],
) -> list[QColor]:
    """Compute Radio Mobile style clearance & shadow colors (Green/Yellow/Red) for terrain segments.

    Uses the bidirectional horizon (intervisibility) algorithm with 4/3 effective Earth curvature:
    - Green: Directly illuminated by Tx (or Rx) line-of-sight.
    - Yellow: Marginal diffraction boundary / transition edge or 60% Fresnel obstruction.
    - Red: Deep RF terrain shadow behind mountain ridges or direct LOS ray obstruction.
    """
    n = len(dists)
    if n < 2:
        return []

    d_arr = np.asarray(dists, dtype=np.float64) * 1000.0  # in meters
    t_arr = np.asarray(terrain, dtype=np.float64)
    l_arr = np.asarray(los, dtype=np.float64)
    fl_arr = np.asarray(f_lower, dtype=np.float64)

    tx_amsl = l_arr[0]
    rx_amsl = l_arr[-1]
    r_eff = 8500000.0  # 4/3 effective earth radius in meters

    col_red = QColor("#EF4444")     # Obstructed / Terrain shadow (Red)
    col_yellow = QColor("#EAB308")  # Marginal / 60% Fresnel / Diffraction (Yellow)
    col_green = QColor("#22C55E")   # Clear Line of Sight / Illuminated (Green)

    # 1. Forward horizon from Tx (observer at Tx antenna looking towards Rx)
    vis_tx = np.zeros(n, dtype=bool)
    diff_tx = np.zeros(n, dtype=np.float64)
    max_angle_tx = -1e9
    vis_tx[0] = True
    for i in range(1, n):
        cur_d = d_arr[i] - d_arr[0]
        if cur_d <= 0.0:
            vis_tx[i] = True
            continue
        # Elevation angle tangent taking 4/3 earth curvature into account
        angle = (t_arr[i] - tx_amsl) / cur_d - cur_d / (2.0 * r_eff)
        if angle >= max_angle_tx:
            vis_tx[i] = True
            diff_tx[i] = 0.0
            max_angle_tx = angle
        else:
            vis_tx[i] = False
            # Shadow depth: clearance below the ray cast by the horizon peak
            ray_h = tx_amsl + cur_d * max_angle_tx + (cur_d**2) / (2.0 * r_eff)
            diff_tx[i] = t_arr[i] - ray_h  # negative in shadow

    # 2. Backward horizon from Rx (observer at Rx antenna looking towards Tx)
    vis_rx = np.zeros(n, dtype=bool)
    diff_rx = np.zeros(n, dtype=np.float64)
    max_angle_rx = -1e9
    vis_rx[-1] = True
    for i in range(n - 2, -1, -1):
        cur_d = d_arr[-1] - d_arr[i]
        if cur_d <= 0.0:
            vis_rx[i] = True
            continue
        angle = (t_arr[i] - rx_amsl) / cur_d - cur_d / (2.0 * r_eff)
        if angle >= max_angle_rx:
            vis_rx[i] = True
            diff_rx[i] = 0.0
            max_angle_rx = angle
        else:
            vis_rx[i] = False
            ray_h = rx_amsl + cur_d * max_angle_rx + (cur_d**2) / (2.0 * r_eff)
            diff_rx[i] = t_arr[i] - ray_h

    # 3. Classify each segment between sample i and i+1
    colors: list[QColor] = []
    for i in range(n - 1):
        t_mid = 0.5 * (t_arr[i] + t_arr[i + 1])
        l_mid = 0.5 * (l_arr[i] + l_arr[i + 1])
        fl_mid = 0.5 * (fl_arr[i] + fl_arr[i + 1])

        # A. Direct link penetration between Tx and Rx:
        if t_mid >= l_mid or t_arr[i] >= l_arr[i] or t_arr[i + 1] >= l_arr[i + 1]:
            colors.append(col_red)
            continue
        if t_mid >= fl_mid or t_arr[i] >= fl_arr[i] or t_arr[i + 1] >= fl_arr[i + 1]:
            colors.append(col_yellow)
            continue

        # B. Intervisibility from Tx or Rx:
        vis_tx_seg = vis_tx[i] and vis_tx[i + 1]
        vis_rx_seg = vis_rx[i] and vis_rx[i + 1]
        one_vis = vis_tx[i] or vis_tx[i + 1] or vis_rx[i] or vis_rx[i + 1]

        if vis_tx_seg or vis_rx_seg:
            colors.append(col_green)
        elif one_vis:
            colors.append(col_yellow)
        else:
            max_diff = max(
                0.5 * (diff_tx[i] + diff_tx[i + 1]),
                0.5 * (diff_rx[i] + diff_rx[i + 1]),
            )
            if max_diff > -25.0:  # marginal transition zone within 25m of horizon ray
                colors.append(col_yellow)
            else:
                colors.append(col_red)

    return colors



class CloudRFProfileCanvas(QWidget):
    """High-fidelity Path Profile Canvas with 2D Drone Altitude Tracking and Offscreen Pixmap Caching."""

    cursor_tracked_2d = Signal(float, float, float, float, float, float, float)
    # (dist_km, cursor_amsl, cursor_agl, ground_amsl, los_amsl, rx_est_dbm, fspl_db)
    cursor_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._profile: Optional[dict] = None
        self._obstructed = False
        self._frequency_mhz = 868.0
        self._tx_lat = 0.0
        self._tx_lon = 0.0
        self._rx_lat = 0.0
        self._rx_lon = 0.0
        self._tx_agl = 10.0
        self._rx_agl = 10.0
        self._tx_eirp_dbm = 30.0
        self._rx_gain_dbi = 2.15

        self._active_pos: Optional[QPointF] = None
        self._active_idx: Optional[int] = None
        self._active_amsl: Optional[float] = None
        self._last_idx: Optional[int] = None
        self._last_amsl: Optional[float] = None
        self._bg_cache: Optional[QPixmap] = None

    def resizeEvent(self, event):
        self._bg_cache = None
        super().resizeEvent(event)

    def set_data(self, profile: Optional[dict], obstructed: bool = False,
                 freq_mhz: float = 868.0, tx_lat: float = 0.0, tx_lon: float = 0.0,
                 rx_lat: float = 0.0, rx_lon: float = 0.0, tx_agl: float = 10.0, rx_agl: float = 10.0,
                 tx_eirp_dbm: float = 30.0, rx_gain_dbi: float = 2.15):
        self._profile = profile
        self._obstructed = obstructed
        self._frequency_mhz = max(1.0, freq_mhz)
        self._tx_lat = tx_lat
        self._tx_lon = tx_lon
        self._rx_lat = rx_lat
        self._rx_lon = rx_lon
        self._tx_agl = tx_agl
        self._rx_agl = rx_agl
        self._tx_eirp_dbm = tx_eirp_dbm
        self._rx_gain_dbi = rx_gain_dbi

        self._active_pos = None
        self._active_idx = None
        self._active_amsl = None
        self._last_idx = None
        self._last_amsl = None
        self._bg_cache = None
        self.update()

    def _get_canvas_bounds(self):
        W = self.width()
        H = self.height()
        m_left = 55
        m_right = 30
        m_top = 25
        m_bot = 32
        pw = max(10, W - m_left - m_right)
        ph = max(10, H - m_top - m_bot)

        if not self._profile or not self._profile.get("distance_km"):
            return None

        dists = self._profile["distance_km"]
        terrain = self._profile["terrain_m"]
        los = self._profile["los_m"]
        f_lower = self._profile.get("fresnel_lower_m", los)
        f_upper = self._profile.get("fresnel_upper_m", los)

        d_min = dists[0]
        d_max = dists[-1]
        total_dist_km = max(0.01, d_max - d_min)

        all_y = list(terrain) + list(los) + list(f_lower) + list(f_upper)
        y_min = max(0, min(all_y) - 20)
        y_max = max(all_y) + 30
        y_span = max(10.0, y_max - y_min)

        return {
            "W": W, "H": H,
            "m_left": m_left, "m_right": m_right, "m_top": m_top, "m_bot": m_bot,
            "pw": pw, "ph": ph,
            "d_min": d_min, "d_max": d_max, "total_dist_km": total_dist_km,
            "y_min": y_min, "y_max": y_max, "y_span": y_span,
            "dists": dists, "terrain": terrain, "los": los,
            "f_lower": f_lower, "f_upper": f_upper
        }

    def _track_at_screen_pos(self, x_pos: float, y_pos: float):
        b = self._get_canvas_bounds()
        if not b:
            return
        dists = b["dists"]
        terrain = b["terrain"]
        los = b["los"]
        n = len(dists)
        if n < 2:
            return

        # 1. Horizontal Distance (X-axis)
        frac_x = max(0.0, min(1.0, (x_pos - b["m_left"]) / b["pw"]))
        idx = int(round(frac_x * (n - 1)))
        d = dists[idx]
        t = terrain[idx]
        l = los[idx]

        # 2. Vertical Altitude (Y-axis AMSL / Drone Flight Level)
        frac_y = (y_pos - b["m_top"]) / b["ph"]
        cursor_amsl = b["y_max"] - frac_y * b["y_span"]
        cursor_amsl = max(0.0, min(b["y_max"] + 150.0, cursor_amsl))
        cursor_agl = cursor_amsl - t

        # Avoid redundant sub-pixel recalculations
        if (self._last_idx == idx and
                self._last_amsl is not None and
                abs(cursor_amsl - self._last_amsl) < 0.6):
            return

        self._last_idx = idx
        self._last_amsl = cursor_amsl

        # 3. Dynamic RF Link from Tx Antenna tip to Drone
        tx_amsl = los[0]
        dh_km = (cursor_amsl - tx_amsl) / 1000.0
        d_3d_km = math.sqrt(d**2 + dh_km**2)
        freq = max(1.0, self._frequency_mhz)
        fspl = 20.0 * math.log10(max(0.001, d_3d_km)) + 20.0 * math.log10(freq) + 32.44

        # Estimated received power at drone antenna (+ receiver gain)
        rx_est = self._tx_eirp_dbm + self._rx_gain_dbi - fspl
        if cursor_amsl < t:
            rx_est -= 50.0  # Penetrating ground

        self._active_pos = QPointF(x_pos, y_pos)
        self._active_idx = idx
        self._active_amsl = cursor_amsl

        self.cursor_tracked_2d.emit(d, cursor_amsl, cursor_agl, t, l, rx_est, fspl)
        self.update()

    def mousePressEvent(self, event):
        self._track_at_screen_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event):
        self._track_at_screen_pos(event.position().x(), event.position().y())

    def leaveEvent(self, event):
        self._active_pos = None
        self._active_idx = None
        self._active_amsl = None
        self._last_idx = None
        self._last_amsl = None
        self.cursor_left.emit()
        self.update()

    def _render_background_cache(self, b: dict):
        """Render static background (axes, earth terrain, Fresnel outline, LOS, masts) into QPixmap."""
        W = self.width()
        H = self.height()
        if W <= 0 or H <= 0:
            return

        pixmap = QPixmap(self.size())
        pixmap.fill(QColor("#090B0E"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dists = b["dists"]
        terrain = b["terrain"]
        los = b["los"]
        f_lower = b["f_lower"]
        f_upper = b["f_upper"]
        n = len(dists)

        m_left = b["m_left"]
        m_right = b["m_right"]
        m_top = b["m_top"]
        m_bot = b["m_bot"]
        pw = b["pw"]
        ph = b["ph"]
        d_min = b["d_min"]
        total_dist_km = b["total_dist_km"]
        y_min = b["y_min"]
        y_max = b["y_max"]
        y_span = b["y_span"]

        def to_screen(d_val, y_val):
            sx = m_left + (d_val - d_min) / total_dist_km * pw
            sy = m_top + (y_max - y_val) / y_span * ph
            return sx, sy

        # 1. Gridlines & Axes
        pen_grid = QPen(QColor("#1A202C"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_grid)
        painter.setFont(QFont("Segoe UI", 8))

        # Y-axis ticks
        y_step = 50.0 if y_span <= 300 else (100.0 if y_span <= 800 else 250.0)
        curr_y = math.ceil(y_min / y_step) * y_step
        while curr_y <= y_max:
            _, sy = to_screen(d_min, curr_y)
            painter.setPen(pen_grid)
            painter.drawLine(int(m_left), int(sy), int(W - m_right), int(sy))
            painter.setPen(QColor("#A0AEC0"))
            painter.drawText(QRectF(0, sy - 8, m_left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{int(curr_y)}")
            curr_y += y_step

        # Y-axis label (m AMSL)
        painter.save()
        painter.translate(14, H / 2)
        painter.rotate(-90)
        painter.setPen(QColor("#718096"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(-60, -10, 120, 20), Qt.AlignmentFlag.AlignCenter, "m AMSL")
        painter.restore()

        # X-axis ticks
        num_x_ticks = max(5, min(15, int(pw / 65)))
        x_step = total_dist_km / num_x_ticks
        for i in range(num_x_ticks + 1):
            cur_d = d_min + i * x_step
            sx, _ = to_screen(cur_d, y_min)
            painter.setPen(pen_grid)
            painter.drawLine(int(sx), int(m_top), int(sx), int(H - m_bot))
            painter.setPen(QColor("#A0AEC0"))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QRectF(sx - 25, H - m_bot + 4, 50, 16), Qt.AlignmentFlag.AlignCenter, f"{cur_d:.2f}")

        # X-axis label
        painter.setPen(QColor("#718096"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(m_left + pw / 2 - 30, H - 16, 60, 14), Qt.AlignmentFlag.AlignCenter, "Km")

        # 2. Warm Earth Brown Terrain Body (Authentic Topographic Shading)
        base_y_screen = m_top + ph
        t_body = QPainterPath()
        p0_x, p0_y = to_screen(dists[0], terrain[0])
        t_body.moveTo(p0_x, base_y_screen)
        t_body.lineTo(p0_x, p0_y)
        for i in range(1, n):
            px, py = to_screen(dists[i], terrain[i])
            t_body.lineTo(px, py)
        pn_x, _ = to_screen(dists[-1], terrain[-1])
        t_body.lineTo(pn_x, base_y_screen)
        t_body.closeSubpath()

        # Rich brown earth gradient (lighter warm brown on ridges to deep dark brown at base)
        grad = QLinearGradient(0, m_top, 0, base_y_screen)
        grad.setColorAt(0.0, QColor("#6B4226"))  # Warm mountain sienna
        grad.setColorAt(0.35, QColor("#52331D")) # Rich earth brown
        grad.setColorAt(0.75, QColor("#361E10")) # Dark soil brown
        grad.setColorAt(1.0, QColor("#1D1009"))  # Deep subterranean base
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(t_body)

        # 2b. Terrain Surface Contour Line (Radio Mobile Multi-Color: Green / Yellow / Red)
        seg_colors = compute_terrain_contour_colors(dists, terrain, los, f_lower)
        for i in range(n - 1):
            x1, y1 = to_screen(dists[i], terrain[i])
            x2, y2 = to_screen(dists[i + 1], terrain[i + 1])
            col = seg_colors[i] if i < len(seg_colors) else QColor("#22C55E")

            painter.setPen(QPen(col, 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 3. Fresnel Zone (Crisp Sky Blue / Cyan Dashed Line - Strictly NO FILL, NO GREEN)
        pen_fres = QPen(QColor("#38BDF8"), 1.4, Qt.PenStyle.DashLine)
        painter.setPen(pen_fres)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        f_lower_path = QPainterPath()
        fx0, fy0 = to_screen(dists[0], f_lower[0])
        f_lower_path.moveTo(fx0, fy0)
        for i in range(1, n):
            fx, fy = to_screen(dists[i], f_lower[i])
            f_lower_path.lineTo(fx, fy)
        painter.drawPath(f_lower_path)

        f_upper_path = QPainterPath()
        fux0, fuy0 = to_screen(dists[0], f_upper[0])
        f_upper_path.moveTo(fux0, fuy0)
        for i in range(1, n):
            fux, fuy = to_screen(dists[i], f_upper[i])
            f_upper_path.lineTo(fux, fuy)
        painter.drawPath(f_upper_path)

        # 4. Line of Sight (LOS) Ray
        los_color = QColor("#EF4444") if self._obstructed else QColor("#22C55E")
        painter.setPen(QPen(los_color, 1.8))
        los_x1, los_y1 = to_screen(dists[0], los[0])
        los_x2, los_y2 = to_screen(dists[-1], los[-1])
        painter.drawLine(QPointF(los_x1, los_y1), QPointF(los_x2, los_y2))

        # 5. Transmitter (Tx) Mast & Label on Left
        tx_g_x, tx_g_y = to_screen(dists[0], terrain[0])
        tx_tip_x, tx_tip_y = to_screen(dists[0], los[0])
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(QPointF(tx_g_x, tx_g_y), QPointF(tx_tip_x, tx_tip_y))
        painter.setBrush(QColor("#F59E0B"))  # Orange Tx Tip
        painter.drawEllipse(QPointF(tx_tip_x, tx_tip_y), 4.0, 4.0)

        painter.setPen(QColor("#CBD5E0"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        tx_lbl = f"Tx: {self._tx_lat:.5f}, {self._tx_lon:.5f}\n{self._tx_agl:.0f} m AGL"
        painter.drawText(QRectF(tx_tip_x + 6, tx_tip_y - 12, 140, 26), Qt.AlignmentFlag.AlignLeft, tx_lbl)

        # 6. Receiver (Rx) Mast & Label on Right
        rx_g_x, rx_g_y = to_screen(dists[-1], terrain[-1])
        rx_tip_x, rx_tip_y = to_screen(dists[-1], los[-1])
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(QPointF(rx_g_x, rx_g_y), QPointF(rx_tip_x, rx_tip_y))
        painter.setBrush(QColor("#3182CE"))  # Blue Rx Tip
        painter.drawEllipse(QPointF(rx_tip_x, rx_tip_y), 4.0, 4.0)

        rx_lbl = f"Rx: {self._rx_lat:.5f}, {self._rx_lon:.5f}\n{self._rx_agl:.0f} m AGL"
        painter.drawText(QRectF(rx_tip_x - 146, rx_tip_y - 12, 140, 26), Qt.AlignmentFlag.AlignRight, rx_lbl)

        # 7. Bottom Right scale tag
        painter.setPen(QColor("#4A5568"))
        painter.drawRoundedRect(W - m_right - 70, H - m_bot - 20, 65, 16, 3, 3)
        painter.setPen(QColor("#718096"))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(W - m_right - 70, H - m_bot - 20, 65, 16), Qt.AlignmentFlag.AlignCenter, f"{total_dist_km:.2f} km")

        painter.end()
        self._bg_cache = pixmap

    def paintEvent(self, event):
        W = self.width()
        H = self.height()
        if W <= 0 or H <= 0:
            return

        painter = QPainter(self)
        b = self._get_canvas_bounds()
        if not b:
            painter.fillRect(0, 0, W, H, QColor("#090B0E"))
            painter.setPen(QColor("#718096"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "No path profile data computed yet")
            return

        # Check or build cached static background
        if self._bg_cache is None or self._bg_cache.size() != self.size():
            self._render_background_cache(b)

        if self._bg_cache is not None:
            painter.drawPixmap(0, 0, self._bg_cache)

        # Draw interactive hover layer
        if self._active_idx is not None and self._active_amsl is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._render_hover_overlay(painter, b)

    def _render_hover_overlay(self, painter: QPainter, b: dict):
        """Draw interactive crosshairs, slant beam, reticle, and floating HUD overlay."""
        W = b["W"]
        H = b["H"]
        m_left = b["m_left"]
        m_right = b["m_right"]
        m_top = b["m_top"]
        m_bot = b["m_bot"]
        pw = b["pw"]
        ph = b["ph"]
        d_min = b["d_min"]
        total_dist_km = b["total_dist_km"]
        y_max = b["y_max"]
        y_span = b["y_span"]

        dists = b["dists"]
        terrain = b["terrain"]
        los = b["los"]

        def to_screen(d_val, y_val):
            sx = m_left + (d_val - d_min) / total_dist_km * pw
            sy = m_top + (y_max - y_val) / y_span * ph
            return sx, sy

        idx = self._active_idx
        d = dists[idx]
        t = terrain[idx]
        l = los[idx]
        cursor_amsl = self._active_amsl
        cursor_agl = cursor_amsl - t

        # 3D slant range & FSPL
        tx_amsl = los[0]
        dh_km = (cursor_amsl - tx_amsl) / 1000.0
        d_3d_km = math.sqrt(d**2 + dh_km**2)
        freq = max(1.0, self._frequency_mhz)
        fspl = 20.0 * math.log10(max(0.001, d_3d_km)) + 20.0 * math.log10(freq) + 32.44
        rx_est = self._tx_eirp_dbm + self._rx_gain_dbi - fspl
        if cursor_amsl < t:
            rx_est -= 50.0

        # Screen coordinates
        cx, cy = to_screen(d, cursor_amsl)
        g_cx, g_cy = to_screen(d, t)
        tx_tip_x, tx_tip_y = to_screen(dists[0], los[0])

        # A. Slant Transmission Beam from Tx Antenna Tip to Drone
        beam_col = QColor("#38BDF8") if cursor_amsl >= t else QColor("#EF4444")
        painter.setPen(QPen(beam_col, 1.5, Qt.PenStyle.DashDotLine))
        painter.drawLine(QPointF(tx_tip_x, tx_tip_y), QPointF(cx, cy))

        # B. 2D Crosshair Guide Lines
        painter.setPen(QPen(QColor("#38BDF8"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(int(cx), int(m_top), int(cx), int(H - m_bot))
        painter.drawLine(int(m_left), int(cy), int(W - m_right), int(cy))

        # C. Y-axis & X-axis Coordinate Badges
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0284C7"))
        y_badge = QRectF(m_left - 48, cy - 8, 44, 16)
        painter.drawRoundedRect(y_badge, 3, 3)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(y_badge, Qt.AlignmentFlag.AlignCenter, f"{int(cursor_amsl)}m")

        x_badge = QRectF(cx - 24, H - m_bot + 2, 48, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0284C7"))
        painter.drawRoundedRect(x_badge, 3, 3)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(x_badge, Qt.AlignmentFlag.AlignCenter, f"{d:.2f}km")

        # D. Ground Projection Dot & Drone Reticle
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        painter.setBrush(QColor("#10B981"))
        painter.drawEllipse(QPointF(g_cx, g_cy), 3.5, 3.5)

        reticle_color = QColor("#38BDF8") if cursor_amsl >= t else QColor("#EF4444")
        painter.setPen(QPen(reticle_color, 1.8))
        painter.setBrush(QColor(56, 189, 248, 60))
        painter.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
        painter.setBrush(reticle_color)
        painter.drawEllipse(QPointF(cx, cy), 2.5, 2.5)

        drone_tag = f"🛸 {int(cursor_amsl)}m ({cursor_agl:+.0f}m AGL)"
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.setPen(QColor("#FFFFFF"))
        tag_x = cx + 9 if cx + 120 < W - m_right else cx - 110
        painter.drawText(QRectF(tag_x, cy - 18, 110, 16), Qt.AlignmentFlag.AlignLeft, drone_tag)

        # E. Floating HUD Card
        hud_w = 205.0
        hud_h = 110.0
        hud_margin = 14.0
        hud_x = cx + hud_margin if cx + hud_w + hud_margin < W - m_right else cx - hud_w - hud_margin
        hud_y = max(m_top + 4.0, min(H - m_bot - hud_h - 4.0, cy - 20.0))

        hud_rect = QRectF(hud_x, hud_y, hud_w, hud_h)
        painter.setPen(QPen(QColor("#38BDF8"), 1.2))
        painter.setBrush(QColor(15, 23, 42, 248))  # Dark Slate 97% opacity
        painter.drawRoundedRect(hud_rect, 6.0, 6.0)

        # HUD Header & Status
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(hud_x + 10, hud_y + 8, hud_w - 20, 16), Qt.AlignmentFlag.AlignLeft, f"Distance: {d:.2f} km")

        if cursor_amsl < t - 2.0:
            status_text = "UNDERGROUND"
            status_col = QColor("#EF4444")
        elif cursor_agl < 15.0:
            status_text = "LOW ALTITUDE"
            status_col = QColor("#F59E0B")
        else:
            status_text = "AIRBORNE"
            status_col = QColor("#38BDF8")

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.setPen(status_col)
        painter.drawText(QRectF(hud_x + hud_w - 85, hud_y + 9, 75, 14), Qt.AlignmentFlag.AlignRight, status_text)

        # HUD Metrics Lines
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(hud_x + 10, hud_y + 26, hud_w - 20, 14), Qt.AlignmentFlag.AlignLeft, f"Drone Alt: {cursor_amsl:.1f} m AMSL")

        agl_col = QColor("#38BDF8") if cursor_agl >= 0 else QColor("#EF4444")
        painter.setPen(agl_col)
        painter.drawText(QRectF(hud_x + 10, hud_y + 42, hud_w - 20, 14), Qt.AlignmentFlag.AlignLeft, f"Height AGL: {cursor_agl:+.1f} m AGL")

        painter.setPen(QColor("#94A3B8"))
        painter.drawText(QRectF(hud_x + 10, hud_y + 58, hud_w - 20, 14), Qt.AlignmentFlag.AlignLeft, f"Ground: {t:.1f} m | LOS: {l:.1f} m")

        rx_col = QColor("#4ADE80") if rx_est >= -85 else (QColor("#F59E0B") if rx_est >= -105 else QColor("#EF4444"))
        painter.setPen(rx_col)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(hud_x + 10, hud_y + 74, hud_w - 20, 14), Qt.AlignmentFlag.AlignLeft, f"Est Rx: {rx_est:.1f} dBm")

        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#93C5FD"))
        painter.drawText(QRectF(hud_x + 10, hud_y + 90, hud_w - 20, 14), Qt.AlignmentFlag.AlignLeft, f"FSPL: {fspl:.1f} dB | 3D: {d_3d_km:.2f} km")

        # Bottom Right scale tag
        painter.setPen(QColor("#4A5568"))
        painter.drawRoundedRect(W - m_right - 70, H - m_bot - 20, 65, 16, 3, 3)
        painter.setPen(QColor("#718096"))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(W - m_right - 70, H - m_bot - 20, 65, 16), Qt.AlignmentFlag.AlignCenter, f"{total_dist_km:.2f} km")


class CloudRFPathProfilePanel(QWidget):
    """Integrated Path Profile Panel matching the Cloud-RF UI layout with 2D Drone Interaction."""

    close_requested = Signal()
    map_point_tracked = Signal(float, float, float, float, float, float)
    # (lat, lon, dist_km, amsl_m, agl_m, ground_m)
    export_kmz_requested = Signal()
    export_kml_requested = Signal()
    export_png_requested = Signal()
    swap_requested = Signal()
    lock_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0E1216; border-top: 1px solid #23272B;")
        self._link_data: Optional[dict] = None
        self._params_data: Optional[dict] = None
        self._default_rx_dbm: float = -80.0
        self.points_locked: bool = False
        self._build_ui()

    def set_points_locked(self, locked: bool) -> None:
        self.points_locked = bool(locked)
        if hasattr(self, "btn_lock"):
            if self.points_locked:
                self.btn_lock.setText(" Locked")
                self.btn_lock.setIcon(svg_icon("lock", 12, "#FFFFFF"))
                self.btn_lock.setStyleSheet("""
                    QPushButton {
                        background-color: #DC2626;
                        color: #FFFFFF;
                        border: 1px solid #EF4444;
                        border-radius: 4px;
                        padding: 1px 8px;
                        font-size: 11px;
                        font-weight: 700;
                        height: 22px;
                    }
                    QPushButton:hover {
                        background-color: #B91C1C;
                        color: #FFFFFF;
                    }
                """)
                self.btn_lock.setToolTip("Titik Tx & Rx terkunci. Klik untuk membuka kunci.")
            else:
                self.btn_lock.setText(" Lock")
                self.btn_lock.setIcon(svg_icon("unlock", 12, "#CBD5E1"))
                self.btn_lock.setStyleSheet("""
                    QPushButton {
                        background-color: #1E293B;
                        color: #CBD5E1;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        padding: 1px 8px;
                        font-size: 11px;
                        font-weight: 600;
                        height: 22px;
                    }
                    QPushButton:hover {
                        background-color: #334155;
                        color: #FFFFFF;
                        border-color: #475569;
                    }
                """)
                self.btn_lock.setToolTip("Kunci titik Tx & Rx agar tidak berubah saat peta diklik")

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.setSpacing(4)

        # ---------------------------------------------------------------------
        # Top Header Container: Modern 2-Tier Dashboard
        # ---------------------------------------------------------------------
        header_widget = QFrame()
        header_widget.setObjectName("ProfileHeaderCard")
        header_widget.setStyleSheet("""
            QFrame#ProfileHeaderCard {
                background-color: #11151A;
                border: 1px solid #1E252E;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(10)

        # 1. Left: Signal Level & Verdict Card
        self.signal_card = QFrame()
        self.signal_card.setObjectName("SignalBadgeCard")
        self.signal_card.setFixedSize(125, 46)
        self.signal_card.setStyleSheet("""
            QFrame#SignalBadgeCard {
                background-color: #0D2318;
                border: 1px solid #22C55E66;
                border-radius: 6px;
            }
        """)
        sc_layout = QVBoxLayout(self.signal_card)
        sc_layout.setContentsMargins(4, 2, 4, 2)
        sc_layout.setSpacing(0)
        sc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_level_tag = QLabel("RX LEVEL")
        lbl_level_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_level_tag.setStyleSheet("color: #64748B; font-size: 8px; font-weight: 700; letter-spacing: 0.8px;")

        self.lbl_signal_val = QLabel("— dBm")
        self.lbl_signal_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_signal_val.setStyleSheet(
            "color: #22C55E; font-size: 14px; font-weight: 800; font-family: 'Segoe UI', system-ui, sans-serif;"
        )
        self.lbl_signal_callout = self.lbl_signal_val  # alias for backwards compatibility

        self.lbl_verdict = QLabel("● CLEAR LOS")
        self.lbl_verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_verdict.setStyleSheet(
            "color: #22C55E; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;"
        )

        sc_layout.addWidget(lbl_level_tag)
        sc_layout.addWidget(self.lbl_signal_val)
        sc_layout.addWidget(self.lbl_verdict)
        header_layout.addWidget(self.signal_card)

        # 2. Center/Right: 2-Tier Balanced Info Area
        info_area = QVBoxLayout()
        info_area.setContentsMargins(0, 0, 0, 0)
        info_area.setSpacing(3)

        # ---- Tier 1: Primary Metrics + Action Buttons ----
        tier1 = QHBoxLayout()
        tier1.setContentsMargins(0, 0, 0, 0)
        tier1.setSpacing(8)

        self.lbl_row1 = QLabel("Distance: — Km &nbsp;│&nbsp; Bearing: —° &nbsp;│&nbsp; Downtilt: —° &nbsp;│&nbsp; Freq: —MHz &nbsp;│&nbsp; Path loss: —dB")
        self.lbl_row1.setStyleSheet("color: #CBD5E1; font-size: 11px; font-family: 'Segoe UI', system-ui, sans-serif;")
        tier1.addWidget(self.lbl_row1, 1)

        # Action Buttons Toolbar
        actions_row = QHBoxLayout()
        actions_row.setSpacing(5)
        actions_row.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.btn_swap = QPushButton(" Swap")
        self.btn_swap.setIcon(svg_icon("swap", 12, "#93C5FD"))
        self.btn_swap.setToolTip("Tukar posisi Tx dan Rx (Swap arah link)")
        self.btn_swap.setFixedHeight(22)
        self.btn_swap.setStyleSheet("""
            QPushButton {
                background-color: #1A2744;
                color: #93C5FD;
                border: 1px solid #3B82F666;
                border-radius: 4px;
                padding: 1px 8px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #2563EB;
                color: #FFFFFF;
                border-color: #60A5FA;
            }
            QPushButton:pressed { background-color: #1D4ED8; }
        """)
        self.btn_swap.clicked.connect(lambda: self.swap_requested.emit())

        self.btn_lock = QPushButton(" Lock")
        self.btn_lock.setIcon(svg_icon("unlock", 12, "#CBD5E1"))
        self.btn_lock.setToolTip("Kunci / Buka kunci titik koordinat Tx dan Rx dari klik peta")
        self.btn_lock.setFixedHeight(22)
        self.btn_lock.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #CBD5E1;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 1px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #FFFFFF;
                border-color: #475569;
            }
        """)
        self.btn_lock.clicked.connect(lambda: self.lock_toggled.emit(not self.points_locked))

        def _action_btn(text, tooltip, cb):
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setFixedHeight(22)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1E293B;
                    color: #94A3B8;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 1px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #38BDF8;
                    border-color: #38BDF866;
                }
            """)
            btn.clicked.connect(cb)
            return btn

        btn_kml = _action_btn("KML", "Export Radio Link 3D KML (format Radio Mobile)", lambda: self.export_kml_requested.emit())
        btn_kmz = _action_btn("KMZ", "Export Radio Link 3D KMZ (paket Google Earth)", lambda: self.export_kmz_requested.emit())
        btn_png = _action_btn("PNG", "Export gambar Path Profile PNG", lambda: self.export_png_requested.emit())

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Tutup panel Radio Link Profile")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7F1D1D;
                color: #FCA5A5;
                border-color: #EF4444;
            }
        """)
        btn_close.clicked.connect(lambda: self.close_requested.emit())

        actions_row.addWidget(self.btn_swap)
        actions_row.addWidget(self.btn_lock)
        actions_row.addWidget(btn_kml)
        actions_row.addWidget(btn_kmz)
        actions_row.addWidget(btn_png)
        actions_row.addWidget(btn_close)
        tier1.addLayout(actions_row)
        info_area.addLayout(tier1)

        # ---- Tier 2: Secondary Specs + Legend ----
        tier2 = QHBoxLayout()
        tier2.setContentsMargins(0, 0, 0, 0)
        tier2.setSpacing(8)

        self.lbl_row2 = QLabel("Tx EIRP: — &nbsp;│&nbsp; Tx Ant: — &nbsp;│&nbsp; Rx Ant: — &nbsp;│&nbsp; Field: — &nbsp;│&nbsp; Model: —")
        self.lbl_row2.setStyleSheet("color: #94A3B8; font-size: 10px; font-family: 'Segoe UI', system-ui, sans-serif;")
        tier2.addWidget(self.lbl_row2, 1)

        # Aliases for backward compatibility
        self.lbl_line1 = self.lbl_row1
        self.lbl_line2 = QLabel()
        self.lbl_line2.setVisible(False)
        self.lbl_line3 = self.lbl_row2
        self.lbl_line4 = QLabel()
        self.lbl_line4.setVisible(False)

        # Legend Row
        legend_row = QHBoxLayout()
        legend_row.setSpacing(10)
        legend_row.setAlignment(Qt.AlignmentFlag.AlignRight)

        def _legend_item(sym, text, color):
            lbl = QLabel(f"<span style='color:{color}; font-weight:900;'>{sym}</span> <span style='color:#94A3B8; font-size:10px;'>{text}</span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            return lbl

        legend_row.addWidget(_legend_item("━", "LOS Bebas", "#22C55E"))
        legend_row.addWidget(_legend_item("━", "Marjinal (60% F1)", "#EAB308"))
        legend_row.addWidget(_legend_item("━", "Terhalang", "#EF4444"))
        legend_row.addWidget(_legend_item("┄", "Fresnel (1.0 F1)", "#38BDF8"))
        legend_row.addWidget(_legend_item("─", "Berkas LOS", "#22C55E"))
        tier2.addLayout(legend_row)
        info_area.addLayout(tier2)

        header_layout.addLayout(info_area, 1)
        main_layout.addWidget(header_widget)

        # ---------------------------------------------------------------------
        # Path Profile Canvas
        # ---------------------------------------------------------------------
        self._last_ipc_time = 0.0
        self.canvas = CloudRFProfileCanvas(self)
        self.canvas.cursor_tracked_2d.connect(self._on_cursor_tracked_2d)
        self.canvas.cursor_left.connect(self._on_cursor_left)
        main_layout.addWidget(self.canvas, 1)

    def update_link_results(self, link: dict, params: dict):
        self._link_data = link
        self._params_data = params

        dist_km = link.get("distance_km", 0.0)
        az_deg = link.get("azimuth_deg", 0.0)
        model = link.get("model", "ITM")
        loss_db = link.get("total_loss_db", link.get("computed_loss_db", 0.0))
        rx_dbm = link.get("rx_power_dbm", -80.0)
        self._default_rx_dbm = rx_dbm
        obstructed = link.get("obstructed", False)

        freq_mhz = float(params.get("frequency_mhz", 868.0))
        tx_lat = float(params.get("tx_lat", 0.0))
        tx_lon = float(params.get("tx_lon", 0.0))
        rx_lat = float(params.get("rx_lat", 0.0))
        rx_lon = float(params.get("rx_lon", 0.0))
        tx_agl = float(params.get("tx_height_m", params.get("tx_height", 10.0)))
        rx_agl = float(params.get("rx_height_m", params.get("rx_height", 10.0)))

        tx_gain_dbi = float(params.get("tx_gain_dbi", 2.15))
        tx_gain_dbd = tx_gain_dbi - 2.15
        if "rx_gain_dbi" in params:
            rx_gain_dbi = float(params["rx_gain_dbi"])
            rx_gain_dbd = rx_gain_dbi - 2.15
        else:
            rx_gain_dbd = float(params.get("rx_gain_dbd", 0.0))
            rx_gain_dbi = rx_gain_dbd + 2.15

        rf_w = float(params.get("rf_power_w", 1.0))
        tx_dbm = 10.0 * math.log10(rf_w * 1000.0) if rf_w > 0 else 0.0
        cable_loss = float(params.get("cable_loss_db", 0.0))
        erp_dbm = tx_dbm - cable_loss + tx_gain_dbd
        erp_w = 10.0 ** ((erp_dbm - 30.0) / 10.0)
        eirp_dbm = tx_dbm - cable_loss + tx_gain_dbi
        eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)

        # Downtilt angle approximation
        profile = link.get("profile", {})
        los = profile.get("los_m", [])
        if los and len(los) >= 2 and dist_km > 0.01:
            h_diff = los[-1] - los[0]
            downtilt = math.degrees(math.atan2(h_diff, dist_km * 1000.0))
        else:
            downtilt = 0.0

        # Field strength: E(dBuV/m) = 107 + Rx(dBm) - Grx(dBi) + 20*log10(freq_MHz) - 27.55
        field_str = max(0.0, 77.2 + rx_dbm + 20.0 * math.log10(max(1.0, freq_mhz)) - rx_gain_dbi)

        # Update Row 1: Primary Link & Propagation
        self.lbl_row1.setText(
            f"<span style='color:#64748B;'>Dist:</span> <b style='color:#FFFFFF;'>{dist_km:.2f} km</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Bearing:</span> <b style='color:#FFFFFF;'>{az_deg:.0f}°</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Tilt:</span> <b style='color:#FFFFFF;'>{downtilt:+.1f}°</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Freq:</span> <b style='color:#FFFFFF;'>{freq_mhz:.0f} MHz</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Path Loss:</span> <b style='color:#F59E0B;'>{loss_db:.1f} dB</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Field:</span> <b style='color:#38BDF8;'>{field_str:.1f} dBµV/m</b>"
        )

        # Update Row 2: RF Specs, Antennas & Model
        rx_cable_loss = float(params.get("rx_cable_loss_db", 0.0))
        rx_net_dbi = rx_gain_dbi - rx_cable_loss
        rx_spec_str = f"<b>{rx_gain_dbi:.1f} dBi</b>" + (f" (<span style='color:#64748B;'>net</span> <b>{rx_net_dbi:.1f}</b>)" if rx_cable_loss > 0 else "")
        self.lbl_row2.setText(
            f"<span style='color:#64748B;'>Tx EIRP:</span> <b style='color:#E2E8F0;'>{eirp_w:.2f}W ({eirp_dbm:.1f} dBm)</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Tx Ant:</span> <b style='color:#E2E8F0;'>{tx_gain_dbi:.1f} dBi</b> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Rx Ant:</span> <span style='color:#E2E8F0;'>{rx_spec_str}</span> &nbsp;"
            f"<span style='color:#334155;'>│</span>&nbsp; "
            f"<span style='color:#64748B;'>Model:</span> <b style='color:#CBD5E1;'>{model}</b>"
        )

        # Update Signal Badge & Verdict
        self._set_signal_badge(rx_dbm, obstructed=obstructed)

        # Send data to Canvas
        self.canvas.set_data(
            profile,
            obstructed=obstructed,
            freq_mhz=freq_mhz,
            tx_lat=tx_lat,
            tx_lon=tx_lon,
            rx_lat=rx_lat,
            rx_lon=rx_lon,
            tx_agl=tx_agl,
            rx_agl=rx_agl,
            tx_eirp_dbm=eirp_dbm,
            rx_gain_dbi=rx_gain_dbi
        )

    def _set_signal_badge(self, rx_dbm: float, obstructed: Optional[bool] = None):
        if obstructed is None:
            obstructed = getattr(self, "_last_obstructed", False)
        else:
            self._last_obstructed = obstructed

        if obstructed:
            sig_col = "#EF4444"
            verdict_text = "✕ OBSTRUCTED"
            card_border = "#EF444466"
            card_bg = "#2D1214"
        elif rx_dbm < -100:
            sig_col = "#EF4444"
            verdict_text = "▲ WEAK SIGNAL"
            card_border = "#EF444466"
            card_bg = "#2D1214"
        elif rx_dbm < -85:
            sig_col = "#F59E0B"
            verdict_text = "▲ MARGINAL"
            card_border = "#F59E0B66"
            card_bg = "#291F0E"
        else:
            sig_col = "#22C55E"
            verdict_text = "● CLEAR LOS"
            card_border = "#22C55E66"
            card_bg = "#0D2318"

        self.lbl_signal_val.setText(f"{rx_dbm:.1f} dBm")
        self.lbl_signal_val.setStyleSheet(
            f"color: {sig_col}; font-size: 15px; font-weight: 800; font-family: 'Segoe UI', system-ui, sans-serif;"
        )
        self.lbl_verdict.setText(verdict_text)
        self.lbl_verdict.setStyleSheet(
            f"color: {sig_col}; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;"
        )
        if hasattr(self, "signal_card"):
            self.signal_card.setStyleSheet(f"""
                QFrame#SignalBadgeCard {{
                    background-color: {card_bg};
                    border: 1px solid {card_border};
                    border-radius: 6px;
                }}
            """)

    def _on_cursor_left(self):
        """Restore default received power badge when cursor leaves profile canvas."""
        self._set_signal_badge(self._default_rx_dbm)

    def _on_cursor_tracked_2d(self, dist_km: float, cursor_amsl: float, cursor_agl: float,
                             ground_m: float, los_m: float, rx_est_dbm: float, fspl_db: float):
        if not self._params_data:
            return

        # Throttle Chromium WebEngine map IPC to max 30 FPS (33ms) to prevent UI stutter
        now = time.monotonic()
        if now - getattr(self, "_last_ipc_time", 0.0) >= 0.033:
            self._last_ipc_time = now
            try:
                tx_lat = float(self._params_data.get("tx_lat", 0.0))
                tx_lon = float(self._params_data.get("tx_lon", 0.0))
                rx_lat = float(self._params_data.get("rx_lat", 0.0))
                rx_lon = float(self._params_data.get("rx_lon", 0.0))
                az = _initial_bearing(tx_lat, tx_lon, rx_lat, rx_lon)
                lat, lon = _destination_point(tx_lat, tx_lon, az, dist_km)
                self.map_point_tracked.emit(lat, lon, dist_km, cursor_amsl, cursor_agl, ground_m)
            except Exception:
                pass

        self._set_signal_badge(rx_est_dbm)
