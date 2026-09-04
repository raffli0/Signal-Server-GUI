"""Top header bar for CloudRF-style Signal GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from .icons import icon as svg_icon
from .theme import (
    ACCENT_CYAN,
    BG_CARD,
    BG_PANEL,
    BORDER_DEFAULT,
    BORDER_LIGHT,
    COLOR_WARNING,
    PRIMARY_BLUE,
    PRIMARY_HOVER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class CloudRFHeader(QFrame):
    """Header bar with branding, action controls, and quick-access tools."""

    toggle_sidebar_requested = Signal()
    section_clicked = Signal(str)  # Emits key of section to expand/scroll to
    save_profile_requested = Signal()
    load_profile_requested = Signal()
    import_rm_requested = Signal()
    radio_link_requested = Signal()
    line_itm_requested = Signal()
    clear_cache_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CloudRFHeader")
        self.setFixedHeight(44)
        self.setStyleSheet(
            f"background-color: {BG_PANEL}; border-bottom: 1px solid #282C31;"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        # 1. Logo & Brand
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(8)

        # Sidebar Toggle Hamburger Button
        self.btn_toggle_sidebar = QPushButton("☰")
        self.btn_toggle_sidebar.setToolTip("Sembunyikan / Tampilkan Sidebar (Ctrl+B)")
        self.btn_toggle_sidebar.setFixedSize(28, 28)
        self.btn_toggle_sidebar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_sidebar.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD};
                color: {TEXT_SECONDARY};
                font-size: 14px;
                font-weight: bold;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {ACCENT_CYAN};
                color: #FFFFFF;
                border-color: {PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background: #2B6CB0;
            }}
        """)
        self.btn_toggle_sidebar.clicked.connect(lambda: self.toggle_sidebar_requested.emit())
        brand_layout.addWidget(self.btn_toggle_sidebar)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(svg_icon("wifi", 18, "#38BDF8").pixmap(18, 18))
        logo_lbl.setStyleSheet("padding: 0 2px;")

        title_lbl = QLabel("RF Propagation")
        title_lbl.setStyleSheet("""
            font-weight: 700;
            font-size: 16px;
            color: #FFFFFF;
            font-family: 'Segoe UI', system-ui, sans-serif;
            letter-spacing: 0.5px;
        """)

        brand_layout.addWidget(logo_lbl)
        brand_layout.addWidget(title_lbl)
        layout.addLayout(brand_layout)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet(f"color: {BORDER_DEFAULT};")
        layout.addWidget(sep1)

        # Profile Save / Load (JSON)
        self.btn_save_profile = QPushButton()
        self.btn_save_profile.setIcon(svg_icon("download", 14, TEXT_PRIMARY))
        self.btn_save_profile.setText(" Save")
        self.btn_save_profile.setToolTip("Save profile (JSON)")
        self.btn_save_profile.setFixedHeight(26)
        self.btn_save_profile.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }}
            QPushButton:hover {{ background: {PRIMARY_BLUE}; color: #FFFFFF; }}
        """)
        self.btn_save_profile.clicked.connect(lambda: self.save_profile_requested.emit())
        layout.addWidget(self.btn_save_profile)

        self.btn_load_profile = QPushButton()
        self.btn_load_profile.setIcon(svg_icon("upload", 14, TEXT_PRIMARY))
        self.btn_load_profile.setText(" Load")
        self.btn_load_profile.setToolTip("Load profile (JSON)")
        self.btn_load_profile.setFixedHeight(26)
        self.btn_load_profile.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }}
            QPushButton:hover {{ background: {PRIMARY_BLUE}; color: #FFFFFF; }}
        """)
        self.btn_load_profile.clicked.connect(lambda: self.load_profile_requested.emit())
        layout.addWidget(self.btn_load_profile)

        # Radio Link (point-to-point) — runs a Tx->Rx link analysis directly
        sep_rl = QFrame()
        sep_rl.setFrameShape(QFrame.Shape.VLine)
        sep_rl.setStyleSheet(f"color: {BORDER_DEFAULT};")
        layout.addWidget(sep_rl)

        self.btn_radio_link = QPushButton()
        self.btn_radio_link.setIcon(svg_icon("radio", 14, "#FFFFFF"))
        self.btn_radio_link.setText(" Radio Link")
        self.btn_radio_link.setToolTip("Compute a point-to-point Radio Link (Tx -> Rx) analysis")
        self.btn_radio_link.setFixedHeight(26)
        self.btn_radio_link.setStyleSheet(f"""
            QPushButton {{
                background: {PRIMARY_BLUE};
                color: #FFFFFF;
                border: 1px solid #2B6CB0;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: {PRIMARY_HOVER}; color: #FFFFFF; }}
            QPushButton:pressed {{ background: #1A365D; }}
        """)
        self.btn_radio_link.clicked.connect(lambda: self.radio_link_requested.emit())
        layout.addWidget(self.btn_radio_link)

        self.btn_line_itm = QPushButton()
        self.btn_line_itm.setIcon(svg_icon("share", 14, "#FBD38D"))
        self.btn_line_itm.setText(" Garis ITM")
        self.btn_line_itm.setToolTip("Propagasi warna ITM hanya garis lurus Tx→Rx (azimuth sempit 0.1°-1°)")
        self.btn_line_itm.setFixedHeight(26)
        self.btn_line_itm.setStyleSheet("""
            QPushButton {
                background: #744210;
                color: #FBD38D;
                border: 1px solid #975A16;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }
            QPushButton:hover { background: #975A16; color: #FFFFFF; }
            QPushButton:pressed { background: #5C3A0A; }
        """)
        self.btn_line_itm.clicked.connect(lambda: self.line_itm_requested.emit())
        layout.addWidget(self.btn_line_itm)

        # Spacer to push right elements
        layout.addStretch()

        # Clear propagation result button (clears coverage overlay / log / status)
        clear_btn = QPushButton()
        clear_btn.setIcon(svg_icon("trash", 14, "#F6AD55"))
        clear_btn.setText(" Clear")
        clear_btn.setToolTip("Clear propagation results from the map")
        clear_btn.setFixedHeight(26)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD};
                color: #F6AD55;
                border: 1px solid {BORDER_LIGHT};
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }}
            QPushButton:hover {{ background: #C05621; color: #FFFFFF; }}
        """)
        clear_btn.clicked.connect(lambda: self.section_clicked.emit("clear"))
        layout.addWidget(clear_btn)

        # Clear all on-disk cache (downloaded DEM/SDF tiles + temp run dirs)
        cache_btn = QPushButton()
        cache_btn.setIcon(svg_icon("database", 14, "#F6AD55"))
        cache_btn.setText(" Cache")
        cache_btn.setToolTip("Hapus semua cache DEM/SDF — bebaskan ruang disk")
        cache_btn.setFixedHeight(26)
        cache_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD};
                color: #F6AD55;
                border: 1px solid {BORDER_LIGHT};
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }}
            QPushButton:hover {{ background: #C05621; color: #FFFFFF; }}
        """)
        cache_btn.clicked.connect(lambda: self.clear_cache_requested.emit())
        layout.addWidget(cache_btn)

        fs_btn = QPushButton()
        fs_btn.setIcon(svg_icon("maximize", 13, TEXT_SECONDARY))
        fs_btn.setToolTip("Toggle Fullscreen")
        fs_btn.setFixedSize(26, 26)
        fs_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; }}
            QPushButton:hover {{ background: {BG_CARD}; border-radius: 4px; }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        layout.addWidget(fs_btn)

    def _toggle_fullscreen(self) -> None:
        win = self.window()
        if win:
            if win.isFullScreen():
                win.showNormal()
            else:
                win.showFullScreen()
