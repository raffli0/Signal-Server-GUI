"""Visual Color Palette Manager for Signal-Server GUI.

Provides interactive palette creation (Range & Custom, RGB/HSL interpolation),
live vertical preview strips, preset & user palette gallery ("My Colours"),
and .dcf serialization/deserialization.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import icons


# Regex for parsing DCF lines: e.g. " -70: 255, 128, 0"
_DCF_LINE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


@dataclass
class ColorBand:
    """A single threshold level with its RGB color."""
    level: float
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        r, g, b = self.rgb
        return f"#{r:02X}{g:02X}{b:02X}"

    @property
    def text_color(self) -> str:
        """High-contrast label color (black or white) based on relative luminance."""
        r, g, b = self.rgb
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#1A202C" if lum > 140 else "#FFFFFF"


@dataclass
class ColorPalette:
    """Representation of an RF coverage color table."""
    name: str
    unit: str = "dBm"  # "dBm", "dBµv", "%"
    bands: list[ColorBand] = field(default_factory=list)
    file_path: Optional[str] = None
    is_builtin: bool = False

    @property
    def display_name(self) -> str:
        return self.name


def parse_dcf_file(path: str) -> Optional[ColorPalette]:
    """Parse a .dcf file into a ColorPalette object."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    bands: list[ColorBand] = []
    unit = "dBm"
    name = os.path.splitext(os.path.basename(path))[0]

    for line in lines:
        line_clean = line.split(";", 1)[0].strip()
        m = _DCF_LINE_RE.match(line_clean)
        if m:
            lvl = float(m.group(1))
            r = min(255, max(0, int(m.group(2))))
            g = min(255, max(0, int(m.group(3))))
            b = min(255, max(0, int(m.group(4))))
            bands.append(ColorBand(level=lvl, rgb=(r, g, b)))
        elif "dbuv" in line.lower() or "dbµv" in line.lower():
            unit = "dBµv"
        elif "%" in line:
            unit = "%"

    if not bands:
        return None

    return ColorPalette(name=name, unit=unit, bands=bands, file_path=path, is_builtin=False)


def save_palette_to_dcf(palette: ColorPalette, dest_path: str) -> str:
    """Save ColorPalette to disk in Signal-Server .dcf format."""
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(f"; Signal-Server Color Palette: {palette.name}\n")
        f.write(f"; Unit: {palette.unit}\n")
        f.write("; Format: level: R, G, B\n")
        for band in palette.bands:
            # Format nicely aligned e.g. " -70: 255, 128, 0"
            lvl_int = int(band.level) if band.level.is_integer() else band.level
            f.write(f"{lvl_int:+4}: {band.rgb[0]:3d}, {band.rgb[1]:3d}, {band.rgb[2]:3d}\n")
    palette.file_path = dest_path
    return dest_path


def interpolate_palette(
    top_val: float,
    steps: int,
    step_size: float,
    top_color: QColor,
    bottom_color: QColor,
    mode: str = "HSL",
    unit: str = "dBm",
) -> list[ColorBand]:
    """Generate color bands using HSL or RGB interpolation from top to bottom."""
    steps = max(2, min(50, steps))
    bands: list[ColorBand] = []

    # Get color parameters
    r1, g1, b1 = top_color.red(), top_color.green(), top_color.blue()
    r2, g2, b2 = bottom_color.red(), bottom_color.green(), bottom_color.blue()

    h1, s1, l1, _ = top_color.getHslF()
    h2, s2, l2, _ = bottom_color.getHslF()
    if h1 < 0:
        h1 = 0.0
    if h2 < 0:
        h2 = 0.0

    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 0.0
        level = top_val - (i * step_size)

        if mode == "HSL":
            # For standard rainbow (e.g. Red hue 0° -> Blue hue 240°):
            # If top is red (0) and bottom is blue (~0.666), interpolate directly
            h = h1 + t * (h2 - h1)
            s = s1 + t * (s2 - s1)
            l = l1 + t * (l2 - l1)
            c = QColor.fromHslF(max(0.0, min(1.0, h)), max(0.0, min(1.0, s)), max(0.0, min(1.0, l)))
            bands.append(ColorBand(level=round(level, 2), rgb=(c.red(), c.green(), c.blue())))
        else:
            # Linear RGB interpolation
            r = int(round(r1 + t * (r2 - r1)))
            g = int(round(g1 + t * (g2 - g1)))
            b = int(round(b1 + t * (b2 - b1)))
            bands.append(ColorBand(level=round(level, 2), rgb=(min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))))

    return bands


def get_standard_presets() -> list[ColorPalette]:
    """Return standard templates matching the reference UI."""
    return [
        ColorPalette(
            name="5G",
            unit="dBm",
            is_builtin=True,
            bands=[
                ColorBand(-70, (46, 204, 113)),   # Green
                ColorBand(-80, (241, 196, 15)),   # Yellow
                ColorBand(-90, (231, 76, 60)),    # Red
            ],
        ),
        ColorPalette(
            name="BASIC",
            unit="dBm",
            is_builtin=True,
            bands=[
                ColorBand(-65, (46, 204, 113)),   # Green
                ColorBand(-80, (241, 196, 15)),   # Yellow
                ColorBand(-95, (231, 76, 60)),    # Red
            ],
        ),
        ColorPalette(
            name="BSA1",
            unit="%",
            is_builtin=True,
            bands=[
                ColorBand(100, (46, 204, 113)),
                ColorBand(90, (92, 214, 92)),
                ColorBand(80, (140, 222, 70)),
                ColorBand(70, (185, 230, 50)),
                ColorBand(60, (235, 228, 40)),
                ColorBand(50, (245, 190, 30)),
                ColorBand(40, (245, 150, 25)),
                ColorBand(30, (240, 110, 25)),
                ColorBand(20, (235, 75, 30)),
                ColorBand(10, (225, 45, 30)),
                ColorBand(0, (200, 20, 20)),
            ],
        ),
        ColorPalette(
            name="CUSTOM",
            unit="dBm",
            is_builtin=True,
            bands=[
                ColorBand(0, (255, 206, 0)),
                ColorBand(-10, (52, 152, 219)),
                ColorBand(-20, (26, 188, 156)),
                ColorBand(-30, (243, 156, 18)),
                ColorBand(-40, (241, 196, 15)),
                ColorBand(-50, (231, 76, 60)),
                ColorBand(-60, (155, 89, 182)),
                ColorBand(-70, (210, 180, 140)),
                ColorBand(-80, (189, 195, 199)),
                ColorBand(-90, (99, 110, 114)),
                ColorBand(-100, (120, 224, 60)),
            ],
        ),
        ColorPalette(
            name="FS",
            unit="dBµv",
            is_builtin=True,
            bands=[
                ColorBand(80, (160, 205, 255)),
                ColorBand(75, (170, 200, 245)),
                ColorBand(70, (180, 195, 235)),
                ColorBand(65, (190, 190, 225)),
                ColorBand(60, (200, 185, 215)),
                ColorBand(55, (210, 180, 205)),
                ColorBand(50, (220, 175, 195)),
                ColorBand(45, (230, 170, 185)),
                ColorBand(40, (235, 160, 175)),
                ColorBand(35, (240, 150, 160)),
                ColorBand(30, (245, 140, 145)),
                ColorBand(25, (250, 130, 130)),
                ColorBand(20, (252, 115, 115)),
                ColorBand(15, (255, 95, 95)),
                ColorBand(10, (255, 75, 75)),
                ColorBand(5, (255, 50, 50)),
                ColorBand(0, (240, 20, 20)),
            ],
        ),
    ]


def get_user_palettes_dir() -> str:
    """Return directory where custom user palettes are stored."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pal_dir = os.path.join(base_dir, "data", "palettes")
    os.makedirs(pal_dir, exist_ok=True)
    return pal_dir


def _get_hidden_palettes_file() -> str:
    return os.path.join(get_user_palettes_dir(), ".hidden_palettes.json")


def load_hidden_palettes() -> set[str]:
    p = _get_hidden_palettes_file()
    if os.path.exists(p):
        try:
            import json
            with open(p, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_hidden_palettes(names: set[str]) -> None:
    p = _get_hidden_palettes_file()
    try:
        import json
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(list(names), f)
    except Exception:
        pass


def discover_all_palettes(signal_server_root: str = "", include_hidden: bool = False) -> list[ColorPalette]:
    """Scan and return all palettes: presets, bundled, and user-created."""
    discovered: list[ColorPalette] = []
    seen_names: set[str] = set()
    hidden_names = set() if include_hidden else load_hidden_palettes()

    # 1. Standard Built-in presets
    for p in get_standard_presets():
        if p.name.upper() not in hidden_names:
            discovered.append(p)
            seen_names.add(p.name.upper())

    # 2. User palettes directory
    user_dir = get_user_palettes_dir()
    if os.path.isdir(user_dir):
        for fname in sorted(os.listdir(user_dir)):
            if fname.lower().endswith(".dcf"):
                full = os.path.join(user_dir, fname)
                pal = parse_dcf_file(full)
                if pal and pal.name.upper() not in seen_names and pal.name.upper() not in hidden_names:
                    pal.is_builtin = False
                    discovered.append(pal)
                    seen_names.add(pal.name.upper())

    # 3. Existing repository color directories
    search_dirs = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"),
        os.path.join(os.path.dirname(__file__), "resources"),
    ]
    if signal_server_root:
        search_dirs.append(os.path.join(signal_server_root, "color"))

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.lower().endswith(".dcf"):
                full = os.path.join(d, fname)
                pal = parse_dcf_file(full)
                if pal and pal.name.upper() not in seen_names and pal.name.upper() not in hidden_names:
                    pal.is_builtin = True
                    discovered.append(pal)
                    seen_names.add(pal.name.upper())

    return discovered


# =============================================================================
# -- UI Components
# =============================================================================

class ColorStripWidget(QFrame):
    """A vertical strip displaying a unit header badge and a stack of colored level blocks."""

    band_clicked = Signal(int)  # Emitted when a band is clicked (in custom mode)

    def __init__(self, unit: str = "dBm", bands: list[ColorBand] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.unit = unit
        self.bands: list[ColorBand] = list(bands or [])
        self.interactive = False  # If true, clicking a band emits band_clicked
        self.setFixedWidth(56)
        self.setStyleSheet("""
            ColorStripWidget {
                background: #181B1E;
                border: 1px solid #374151;
                border-radius: 4px;
            }
        """)

    def set_palette(self, unit: str, bands: list[ColorBand], interactive: bool = False) -> None:
        self.unit = unit
        self.bands = list(bands)
        self.interactive = interactive
        self.update()

    def mousePressEvent(self, event) -> None:
        if self.interactive and self.bands:
            y = event.position().y() if hasattr(event, "position") else event.y()
            header_h = 24
            if y > header_h:
                avail_h = self.height() - header_h - 4
                band_h = avail_h / len(self.bands)
                idx = int((y - header_h) / band_h)
                if 0 <= idx < len(self.bands):
                    self.band_clicked.emit(idx)
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#181B1E"))

        # Header Badge (Unit)
        header_h = 24
        painter.fillRect(2, 2, w - 4, header_h - 2, QColor("#2D3748"))
        painter.setPen(QColor("#CBD5E0"))
        f = QFont("Inter", 9, QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(0, 0, w, header_h, Qt.AlignmentFlag.AlignCenter, self.unit)

        if not self.bands:
            return

        # Stacked blocks
        y_start = header_h + 2
        avail_h = h - y_start - 3
        n = len(self.bands)
        band_h = avail_h / n

        font_label = QFont("Inter", 8, QFont.Weight.DemiBold)
        painter.setFont(font_label)

        for i, band in enumerate(self.bands):
            by = y_start + (i * band_h)
            bh = (y_start + ((i + 1) * band_h)) - by
            r, g, b = band.rgb
            painter.fillRect(2, int(by), w - 4, int(bh), QColor(r, g, b))

            # Threshold text
            painter.setPen(QColor(band.text_color))
            lvl_str = f"{int(band.level)}" if band.level.is_integer() else f"{band.level:.1f}"
            painter.drawText(2, int(by), w - 4, int(bh), Qt.AlignmentFlag.AlignCenter, lvl_str)

        # Outer border
        painter.setPen(QColor("#374151"))
        painter.drawRect(0, 0, w - 1, h - 1)


class PaletteCardWidget(QFrame):
    """A card in the "My Colours" gallery displaying a palette, its name, strip, and actions."""

    selected = Signal(ColorPalette)
    deleted = Signal(ColorPalette)
    edit_requested = Signal(ColorPalette)

    def __init__(self, palette: ColorPalette, is_active: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette = palette
        self.is_active = is_active
        self.setFixedWidth(74)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build()
        self.update_style()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Title / Name
        self.title_lbl = QLabel(self.palette.name)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet("color: #E2E8F0; font-size: 11px; font-weight: 700;")
        layout.addWidget(self.title_lbl)

        # Color strip
        self.strip = ColorStripWidget(unit=self.palette.unit, bands=self.palette.bands)
        self.strip.setMinimumHeight(240)
        layout.addWidget(self.strip, 1, Qt.AlignmentFlag.AlignHCenter)

        # Action row (Trash icon button on every palette card, matching reference image)
        bottom_box = QHBoxLayout()
        bottom_box.setContentsMargins(0, 2, 0, 0)
        bottom_box.setSpacing(2)

        self.del_btn = QPushButton()
        self.del_btn.setIcon(QIcon(icons.pixmap("trash", 14, "#CBD5E0")))
        self.del_btn.setToolTip(f"Hapus palet '{self.palette.name}'")
        self.del_btn.setFixedSize(28, 26)
        self.del_btn.setStyleSheet("""
            QPushButton {
                background-color: #23272B;
                border: 1px solid #3F474F;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #E53E3E;
                border-color: #FC8181;
            }
            QPushButton:pressed {
                background-color: #C53030;
            }
        """)
        self.del_btn.clicked.connect(lambda: self.deleted.emit(self.palette))
        bottom_box.addWidget(self.del_btn, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(bottom_box)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.palette)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.edit_requested.emit(self.palette)
        super().mouseDoubleClickEvent(event)

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self.update_style()

    def update_style(self) -> None:
        if self.is_active:
            self.setStyleSheet("""
                PaletteCardWidget {
                    background-color: #1A2838;
                    border: 2px solid #3182CE;
                    border-radius: 6px;
                }
            """)
            self.title_lbl.setStyleSheet("color: #63B3ED; font-size: 11px; font-weight: 700;")
        else:
            self.setStyleSheet("""
                PaletteCardWidget {
                    background-color: #1E2226;
                    border: 1px solid #3F474F;
                    border-radius: 6px;
                }
                PaletteCardWidget:hover {
                    background-color: #262C32;
                    border-color: #4A5568;
                }
            """)
            self.title_lbl.setStyleSheet("color: #E2E8F0; font-size: 11px; font-weight: 700;")


class ColorManagerDialog(QDialog):
    """Full-featured visual Color Palette Manager matching the reference UI."""

    palette_applied = Signal(str)  # Emitted with the selected .dcf file path

    def __init__(self, current_color_file: str = "", signal_server_root: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Color Palette Manager – Signal Coverage")
        self.setMinimumSize(880, 520)
        self.resize(920, 560)
        self.ss_root = signal_server_root
        self.current_color_file = current_color_file

        self.all_palettes: list[ColorPalette] = []
        self.selected_palette: Optional[ColorPalette] = None
        self.custom_bands: list[ColorBand] = []

        # Current editor parameters
        self.top_color = QColor("#FF0000")      # Red
        self.bottom_color = QColor("#0066FF")   # Blue

        self._build_ui()
        self._load_palettes()
        self._select_by_file(current_color_file)
        self._on_inputs_changed()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #14171A;
                color: #E2E8F0;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #CBD5E0;
                font-size: 11px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #1B1E22;
                color: #E2E8F0;
                border: 1px solid #3F474F;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border: 1px solid #3182CE;
            }
            QRadioButton {
                color: #CBD5E0;
                font-size: 11px;
                spacing: 5px;
            }
            QRadioButton::indicator {
                width: 13px;
                height: 13px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #2D3748;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #DD6B20;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #E2E8F0;
                border: 1px solid #718096;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QScrollBar:horizontal {
                background: #14171A;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background: #374151;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #4B5563;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 14)
        main_layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("palette", 22, "#3182CE"))
        header_layout.addWidget(icon_lbl)
        title_lbl = QLabel("Color Palette Manager")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch(1)
        main_layout.addLayout(header_layout)

        # Middle Content Area (Two Columns: Create | My Colours)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # =====================================================================
        # Column 1: CREATE Panel
        # =====================================================================
        left_box = QVBoxLayout()
        left_box.setSpacing(8)

        create_title = QLabel("Create")
        create_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF; margin-bottom: 2px;")
        left_box.addWidget(create_title)

        create_container = QHBoxLayout()
        create_container.setSpacing(12)

        # Form Box
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #1E2226;
                border: 1px solid #3F474F;
                border-radius: 6px;
            }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setSpacing(10)

        # Row 1: Name
        row_name = QHBoxLayout()
        lbl_name = QLabel("Name")
        lbl_name.setFixedWidth(50)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Nama palet...")
        self.edit_name.setText("MyPalette")
        row_name.addWidget(lbl_name)
        row_name.addWidget(self.edit_name)
        form_layout.addLayout(row_name)

        # Row 2: Top & Unit
        row_top = QHBoxLayout()
        lbl_top = QLabel("Top")
        lbl_top.setFixedWidth(50)
        self.spin_top = QDoubleSpinBox()
        self.spin_top.setRange(-200, 200)
        self.spin_top.setDecimals(0)
        self.spin_top.setValue(0)
        self.spin_top.valueChanged.connect(self._on_inputs_changed)

        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["dBm", "dBµv", "%"])
        self.combo_unit.currentTextChanged.connect(self._on_inputs_changed)

        row_top.addWidget(lbl_top)
        row_top.addWidget(self.spin_top)
        row_top.addWidget(self.combo_unit)
        form_layout.addLayout(row_top)

        # Row 3: Steps (Slider)
        row_steps = QHBoxLayout()
        lbl_steps = QLabel("Steps")
        lbl_steps.setFixedWidth(50)
        self.slider_steps = QSlider(Qt.Orientation.Horizontal)
        self.slider_steps.setRange(2, 30)
        self.slider_steps.setValue(11)
        self.lbl_step_count = QLabel("11")
        self.lbl_step_count.setFixedWidth(24)
        self.lbl_step_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider_steps.valueChanged.connect(self._on_slider_changed)

        row_steps.addWidget(lbl_steps)
        row_steps.addWidget(self.slider_steps)
        row_steps.addWidget(self.lbl_step_count)
        form_layout.addLayout(row_steps)

        # Row 4: Step size
        row_step_size = QHBoxLayout()
        lbl_step_size = QLabel("Step size")
        lbl_step_size.setFixedWidth(50)
        self.spin_step_size = QDoubleSpinBox()
        self.spin_step_size.setRange(0.5, 50.0)
        self.spin_step_size.setValue(10.0)
        self.spin_step_size.setSuffix(" dB")
        self.spin_step_size.valueChanged.connect(self._on_inputs_changed)

        row_step_size.addWidget(lbl_step_size)
        row_step_size.addWidget(self.spin_step_size)
        form_layout.addLayout(row_step_size)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #3F474F;")
        form_layout.addWidget(div)

        # Row 5: Mode (Range vs Custom)
        row_mode = QHBoxLayout()
        self.radio_range = QRadioButton("Range")
        self.radio_custom = QRadioButton("Custom")
        self.radio_range.setChecked(True)
        self.btn_grp_mode = QButtonGroup(self)
        self.btn_grp_mode.addButton(self.radio_range)
        self.btn_grp_mode.addButton(self.radio_custom)
        self.radio_range.toggled.connect(self._on_mode_toggled)

        row_mode.addWidget(self.radio_range)
        row_mode.addWidget(self.radio_custom)
        row_mode.addStretch(1)
        form_layout.addLayout(row_mode)

        # Row 6: Color Pickers (Top & Bottom swatches)
        self.range_widget = QWidget()
        range_layout = QVBoxLayout(self.range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(8)

        row_swatches = QHBoxLayout()
        lbl_top_c = QLabel("Top")
        self.btn_top_color = QPushButton()
        self.btn_top_color.setFixedSize(50, 24)
        self.btn_top_color.clicked.connect(self._pick_top_color)

        lbl_bot_c = QLabel("Bottom")
        self.btn_bot_color = QPushButton()
        self.btn_bot_color.setFixedSize(50, 24)
        self.btn_bot_color.clicked.connect(self._pick_bottom_color)

        self._update_color_buttons()

        row_swatches.addWidget(lbl_top_c)
        row_swatches.addWidget(self.btn_top_color)
        row_swatches.addSpacing(10)
        row_swatches.addWidget(lbl_bot_c)
        row_swatches.addWidget(self.btn_bot_color)
        row_swatches.addStretch(1)
        range_layout.addLayout(row_swatches)

        # Row 7: Interpolation (RGB vs HSL)
        row_interp = QHBoxLayout()
        self.radio_rgb = QRadioButton("RGB")
        self.radio_hsl = QRadioButton("HSL")
        self.radio_hsl.setChecked(True)
        self.btn_grp_interp = QButtonGroup(self)
        self.btn_grp_interp.addButton(self.radio_rgb)
        self.btn_grp_interp.addButton(self.radio_hsl)
        self.radio_hsl.toggled.connect(self._on_inputs_changed)

        row_interp.addWidget(self.radio_rgb)
        row_interp.addWidget(self.radio_hsl)
        row_interp.addStretch(1)
        range_layout.addLayout(row_interp)

        form_layout.addWidget(self.range_widget)

        # Custom Hint
        self.lbl_custom_hint = QLabel("💡 Klik pada bar warna di preview untuk memilih warna per-step.")
        self.lbl_custom_hint.setStyleSheet("color: #ECC94B; font-size: 10px;")
        self.lbl_custom_hint.setVisible(False)
        form_layout.addWidget(self.lbl_custom_hint)

        form_layout.addStretch(1)

        # Save Button
        self.btn_save = QPushButton("Save to My Colours")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2B6CB0;
                color: #FFFFFF;
                font-weight: 600;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #3182CE; }
        """)
        self.btn_save.clicked.connect(self._save_custom_palette)
        form_layout.addWidget(self.btn_save, 0, Qt.AlignmentFlag.AlignRight)

        create_container.addWidget(form_frame, 1)

        # Live Preview Strip (Beside Create Form)
        self.preview_strip = ColorStripWidget(unit="dBm")
        self.preview_strip.setMinimumHeight(320)
        self.preview_strip.band_clicked.connect(self._on_preview_band_clicked)
        create_container.addWidget(self.preview_strip, 0)

        left_box.addLayout(create_container)
        content_layout.addLayout(left_box, 1)

        # Divider between Create and My Colours
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setStyleSheet("color: #2D3748;")
        content_layout.addWidget(v_line)

        # =====================================================================
        # Column 2: MY COLOURS Panel
        # =====================================================================
        right_box = QVBoxLayout()
        right_box.setSpacing(8)

        right_header = QHBoxLayout()
        my_colours_title = QLabel("My Colours")
        my_colours_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        right_header.addWidget(my_colours_title)
        right_header.addStretch(1)

        self.btn_delete_selected = QPushButton(" Hapus")
        self.btn_delete_selected.setIcon(QIcon(icons.pixmap("trash", 13, "#CBD5E0")))
        self.btn_delete_selected.setToolTip("Hapus palet yang sedang dipilih dari My Colours")
        self.btn_delete_selected.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                color: #CBD5E0;
                border: 1px solid #4A5568;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E53E3E;
                color: #FFFFFF;
                border-color: #FC8181;
            }
        """)
        self.btn_delete_selected.clicked.connect(lambda: self._on_palette_deleted(self.selected_palette))
        right_header.addWidget(self.btn_delete_selected)

        self.btn_restore_presets = QPushButton("Pulihkan Preset")
        self.btn_restore_presets.setToolTip("Pulihkan preset bawaan yang pernah dihapus")
        self.btn_restore_presets.setStyleSheet("""
            QPushButton {
                background-color: #1A202C;
                color: #A0AEC0;
                border: 1px dashed #4A5568;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #63B3ED;
                border-color: #3182CE;
            }
        """)
        self.btn_restore_presets.clicked.connect(self._restore_presets)
        right_header.addWidget(self.btn_restore_presets)

        right_box.addLayout(right_header)

        # Scroll Area for palette cards
        self.scroll_cards = QScrollArea()
        self.scroll_cards.setWidgetResizable(True)
        self.scroll_cards.setStyleSheet("""
            QScrollArea {
                background: #181B1E;
                border: 1px solid #2D3748;
                border-radius: 6px;
            }
        """)
        self.cards_content = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_content)
        self.cards_layout.setContentsMargins(10, 10, 10, 10)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scroll_cards.setWidget(self.cards_content)

        right_box.addWidget(self.scroll_cards, 1)
        content_layout.addLayout(right_box, 1)

        main_layout.addLayout(content_layout, 1)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 4)

        self.lbl_status = QLabel("Pilih atau buat palet warna untuk digunakan.")
        self.lbl_status.setStyleSheet("color: #A0AEC0; font-size: 11px;")
        bottom_bar.addWidget(self.lbl_status, 1)

        btn_cancel = QPushButton("Batal")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #2D3748;
                color: #CBD5E0;
                border: 1px solid #4A5568;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4A5568; }
        """)
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        self.btn_apply = QPushButton("Gunakan Palet Ini (Apply)")
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #3182CE;
                color: #FFFFFF;
                font-weight: 700;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #2B6CB0; }
        """)
        self.btn_apply.clicked.connect(self._apply_palette)
        bottom_bar.addWidget(self.btn_apply)

        main_layout.addLayout(bottom_bar)

    # -------------------------------------------------------------------------
    # Event Handlers & Helpers
    # -------------------------------------------------------------------------

    def _on_slider_changed(self, value: int) -> None:
        self.lbl_step_count.setText(str(value))
        self._on_inputs_changed()

    def _on_mode_toggled(self) -> None:
        is_range = self.radio_range.isChecked()
        self.range_widget.setVisible(is_range)
        self.lbl_custom_hint.setVisible(not is_range)
        self.preview_strip.interactive = not is_range

    def _update_color_buttons(self) -> None:
        self.btn_top_color.setStyleSheet(
            f"background-color: {self.top_color.name()}; border: 1px solid #CBD5E0; border-radius: 3px;"
        )
        self.btn_bot_color.setStyleSheet(
            f"background-color: {self.bottom_color.name()}; border: 1px solid #CBD5E0; border-radius: 3px;"
        )

    def _pick_top_color(self) -> None:
        c = QColorDialog.getColor(self.top_color, self, "Pilih Warna Top (Terkuat)")
        if c.isValid():
            self.top_color = c
            self._update_color_buttons()
            self._on_inputs_changed()

    def _pick_bottom_color(self) -> None:
        c = QColorDialog.getColor(self.bottom_color, self, "Pilih Warna Bottom (Terlemah)")
        if c.isValid():
            self.bottom_color = c
            self._update_color_buttons()
            self._on_inputs_changed()

    def _on_preview_band_clicked(self, index: int) -> None:
        if 0 <= index < len(self.custom_bands):
            b = self.custom_bands[index]
            cur = QColor(b.rgb[0], b.rgb[1], b.rgb[2])
            c = QColorDialog.getColor(cur, self, f"Ubah Warna Level {b.level}")
            if c.isValid():
                self.custom_bands[index] = ColorBand(b.level, (c.red(), c.green(), c.blue()))
                self.preview_strip.set_palette(self.combo_unit.currentText(), self.custom_bands, interactive=True)

    def _on_inputs_changed(self) -> None:
        top_val = self.spin_top.value()
        steps = self.slider_steps.value()
        step_size = self.spin_step_size.value()
        unit = self.combo_unit.currentText()
        mode = "HSL" if self.radio_hsl.isChecked() else "RGB"

        # Suffix handling
        if unit == "%":
            self.spin_step_size.setSuffix(" %")
        elif unit == "dBµv":
            self.spin_step_size.setSuffix(" dBµv")
        else:
            self.spin_step_size.setSuffix(" dB")

        if self.radio_range.isChecked():
            self.custom_bands = interpolate_palette(
                top_val=top_val,
                steps=steps,
                step_size=step_size,
                top_color=self.top_color,
                bottom_color=self.bottom_color,
                mode=mode,
                unit=unit,
            )

        self.preview_strip.set_palette(unit, self.custom_bands, interactive=self.radio_custom.isChecked())

    def _load_palettes(self) -> None:
        # Clear existing cards
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._hidden_palette_names = load_hidden_palettes()
        self.all_palettes = discover_all_palettes(self.ss_root)
        self.card_widgets: list[PaletteCardWidget] = []

        for p in self.all_palettes:
            card = PaletteCardWidget(p)
            card.selected.connect(self._on_palette_selected)
            card.deleted.connect(self._on_palette_deleted)
            card.edit_requested.connect(self._on_palette_edit_requested)
            self.cards_layout.addWidget(card)
            self.card_widgets.append(card)

        if hasattr(self, "btn_restore_presets"):
            self.btn_restore_presets.setVisible(bool(self._hidden_palette_names))
        if hasattr(self, "btn_delete_selected"):
            self.btn_delete_selected.setEnabled(bool(self.all_palettes))

    def _select_by_file(self, color_file: str) -> None:
        if not color_file:
            if self.all_palettes:
                self._on_palette_selected(self.all_palettes[0])
            return

        base = os.path.splitext(os.path.basename(color_file))[0].upper()
        for p in self.all_palettes:
            if (p.file_path and os.path.abspath(p.file_path) == os.path.abspath(color_file)) or (p.name.upper() == base):
                self._on_palette_selected(p)
                return

        # If not found, parse directly
        parsed = parse_dcf_file(color_file)
        if parsed:
            self.all_palettes.append(parsed)
            card = PaletteCardWidget(parsed)
            card.selected.connect(self._on_palette_selected)
            card.deleted.connect(self._on_palette_deleted)
            card.edit_requested.connect(self._on_palette_edit_requested)
            self.cards_layout.addWidget(card)
            self.card_widgets.append(card)
            self._on_palette_selected(parsed)

    def _on_palette_selected(self, palette: ColorPalette) -> None:
        self.selected_palette = palette
        for card in self.card_widgets:
            card.set_active(card.palette.name == palette.name)

        min_lvl = min((b.level for b in palette.bands), default=0)
        max_lvl = max((b.level for b in palette.bands), default=0)
        self.lbl_status.setText(
            f"Terpilih: <b>{palette.name}</b> ({palette.unit}: {max_lvl} hingga {min_lvl}) "
            f"[{'Bawaan' if palette.is_builtin else 'Kustom'}]"
        )

    def _on_palette_edit_requested(self, palette: ColorPalette) -> None:
        """Load selected palette into Create editor for quick adjustment."""
        self.edit_name.setText(f"{palette.name}_copy")
        idx = self.combo_unit.findText(palette.unit)
        if idx >= 0:
            self.combo_unit.setCurrentIndex(idx)

        if len(palette.bands) >= 2:
            self.spin_top.setValue(palette.bands[0].level)
            steps = len(palette.bands)
            self.slider_steps.setValue(steps)
            step_size = abs(palette.bands[1].level - palette.bands[0].level)
            self.spin_step_size.setValue(step_size)

            # Top & Bottom colors
            r1, g1, b1 = palette.bands[0].rgb
            self.top_color = QColor(r1, g1, b1)
            r2, g2, b2 = palette.bands[-1].rgb
            self.bottom_color = QColor(r2, g2, b2)
            self._update_color_buttons()

            self.custom_bands = list(palette.bands)
            self.radio_custom.setChecked(True)
            self._on_inputs_changed()

    def _restore_presets(self) -> None:
        """Restore any hidden or deleted standard presets."""
        self._hidden_palette_names.clear()
        save_hidden_palettes(self._hidden_palette_names)
        self.btn_restore_presets.setVisible(False)
        self._load_palettes()
        if self.all_palettes:
            self._on_palette_selected(self.all_palettes[0])
        QMessageBox.information(self, "Preset Dipulihkan", "Seluruh preset standar bawaan telah berhasil dipulihkan.")

    def _on_palette_deleted(self, palette: Optional[ColorPalette]) -> None:
        if not palette:
            return
        res = QMessageBox.question(
            self,
            "Konfirmasi Hapus",
            f"Apakah Anda yakin ingin menghapus palet '{palette.name}' dari daftar My Colours?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            if palette.file_path and os.path.exists(palette.file_path):
                try:
                    os.remove(palette.file_path)
                except OSError as err:
                    QMessageBox.warning(self, "Gagal Menghapus", str(err))
                    return

            self._hidden_palette_names.add(palette.name.upper())
            save_hidden_palettes(self._hidden_palette_names)

            self._load_palettes()
            if self.all_palettes:
                self._on_palette_selected(self.all_palettes[0])
            else:
                self.selected_palette = None
                self.lbl_status.setText("Tidak ada palet di My Colours.")

    def _save_custom_palette(self) -> None:
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Nama Kosong", "Silakan masukkan nama untuk palet warna.")
            return

        # Sanitize filename
        safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
        if not safe_name:
            safe_name = "custom_palette"

        dest_dir = get_user_palettes_dir()
        dest_file = os.path.join(dest_dir, f"{safe_name}.dcf")

        unit = self.combo_unit.currentText()
        new_palette = ColorPalette(
            name=safe_name,
            unit=unit,
            bands=list(self.custom_bands),
            file_path=dest_file,
            is_builtin=False,
        )

        try:
            save_palette_to_dcf(new_palette, dest_file)
        except OSError as err:
            QMessageBox.critical(self, "Gagal Menyimpan", f"Gagal menulis berkas palet: {err}")
            return

        self._load_palettes()
        self._select_by_file(dest_file)
        QMessageBox.information(
            self,
            "Palet Disimpan",
            f"Palet '{safe_name}' berhasil disimpan dan ditambahkan ke koleksi My Colours!"
        )

    def _apply_palette(self) -> None:
        if not self.selected_palette:
            QMessageBox.warning(self, "Belum Memilih", "Pilih palet warna terlebih dahulu.")
            return

        # If it's a built-in without a file on disk yet, save it to user palettes dir
        path = self.selected_palette.file_path
        if not path or not os.path.exists(path):
            dest_dir = get_user_palettes_dir()
            safe_name = "".join(c for c in self.selected_palette.name if c.isalnum() or c in ("-", "_"))
            path = os.path.join(dest_dir, f"{safe_name}.dcf")
            save_palette_to_dcf(self.selected_palette, path)

        self.palette_applied.emit(path)
        self.accept()
