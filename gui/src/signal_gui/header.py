"""Top header bar for CloudRF-style Signal GUI."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Signal, Qt

from .icons import icon as svg_icon

_ICON_FOR = {
    "tx": "tower", "signal": "wifi", "feeder": "database", "antenna": "antenna",
    "rx": "radio", "model": "share", "env": "leaf", "output": "layers",
    "clear": "trash",
}
_ICON_COLOR = "#CBD5E0"


class CloudRFHeader(QFrame):
    """Header bar with CloudRF branding, preset bar, section icons, and version tags."""

    section_clicked = Signal(str)  # Emits key of section to expand/scroll to
    save_profile_requested = Signal()
    load_profile_requested = Signal()
    radio_link_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CloudRFHeader")
        self.setFixedHeight(44)
        self.setStyleSheet("background-color: #1b1e22; border-bottom: 1px solid #282c31;")
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        # 1. Logo & Brand
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(6)

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
        sep1.setStyleSheet("color: #373D44;")
        layout.addWidget(sep1)

        # 2. Preset Select Dropdown Pill
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(4)
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Custom - sband snr 20m",
            "LTE 1800MHz - Standard",
            "5G NR 3.5GHz - Dense Urban",
            "FM Broadcast 100MHz",
            "WiFi 2.4GHz - Indoor/Outdoor"
        ])
        self.preset_combo.setToolTip("Preset configuration")
        self.preset_combo.setStyleSheet("""
            QComboBox {
                background: #121417;
                color: #A0AEC0;
                border: 1px solid #33383F;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #121417;
                color: #E2E8F0;
                selection-background-color: #3182CE;
            }
        """)

        btn_dl = QPushButton()
        btn_dl.setIcon(svg_icon("download", 14, "#A0AEC0"))
        btn_dl.setToolTip("Download / Export Preset")
        btn_dl.setFixedSize(24, 24)
        btn_dl.setStyleSheet("""
            QPushButton {
                background: #25282C;
                color: #A0AEC0;
                border: 1px solid #33383F;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover { background: #3182CE; }
        """)

        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(btn_dl)
        layout.addLayout(preset_layout)

        # Separator line
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #373D44;")
        layout.addWidget(sep2)

        # 3. Center Section Icons
        icons = [
            ("tx", "Site / Tx"),
            ("rx", "Mobile / Rx"),
            ("model", "Model"),
            ("env", "Environment"),
            ("output", "Output"),
            ("clear", "Clear Propagation"),
        ]

        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(3)
        for key, tooltip in icons:
            btn = QPushButton()
            btn.setIcon(svg_icon(_ICON_FOR[key], 15, _ICON_COLOR))
            btn.setToolTip(tooltip)
            btn.setFixedSize(28, 28)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #CBD5E0;
                    border: none;
                    border-radius: 4px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: #2D3748;
                }
                QPushButton:pressed {
                    background: #3182CE;
                }
            """)
            btn.clicked.connect(lambda _, k=key: self.section_clicked.emit(k))
            icons_layout.addWidget(btn)

        layout.addLayout(icons_layout)

        # Separator line
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("color: #373D44;")
        layout.addWidget(sep3)

        # Profile Save / Load (JSON)
        self.btn_save_profile = QPushButton()
        self.btn_save_profile.setIcon(svg_icon("download", 14, "#E2E8F0"))
        self.btn_save_profile.setText(" Save")
        self.btn_save_profile.setToolTip("Save profile (JSON)")
        self.btn_save_profile.setFixedHeight(26)
        self.btn_save_profile.setStyleSheet("""
            QPushButton {
                background: #2D3748;
                color: #E2E8F0;
                border: 1px solid #4A5568;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }
            QPushButton:hover { background: #3182CE; color: #FFFFFF; }
        """)
        self.btn_save_profile.clicked.connect(lambda: self.save_profile_requested.emit())
        layout.addWidget(self.btn_save_profile)

        self.btn_load_profile = QPushButton()
        self.btn_load_profile.setIcon(svg_icon("upload", 14, "#E2E8F0"))
        self.btn_load_profile.setText(" Load")
        self.btn_load_profile.setToolTip("Load profile (JSON)")
        self.btn_load_profile.setFixedHeight(26)
        self.btn_load_profile.setStyleSheet("""
            QPushButton {
                background: #2D3748;
                color: #E2E8F0;
                border: 1px solid #4A5568;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }
            QPushButton:hover { background: #3182CE; color: #FFFFFF; }
        """)
        self.btn_load_profile.clicked.connect(lambda: self.load_profile_requested.emit())
        layout.addWidget(self.btn_load_profile)

        # Radio Link (point-to-point) — runs a Tx->Rx link analysis directly
        sep_rl = QFrame()
        sep_rl.setFrameShape(QFrame.Shape.VLine)
        sep_rl.setStyleSheet("color: #373D44;")
        layout.addWidget(sep_rl)

        self.btn_radio_link = QPushButton()
        self.btn_radio_link.setIcon(svg_icon("radio", 14, "#FFFFFF"))
        self.btn_radio_link.setText(" Radio Link")
        self.btn_radio_link.setToolTip("Compute a point-to-point Radio Link (Tx -> Rx) analysis")
        self.btn_radio_link.setFixedHeight(26)
        self.btn_radio_link.setStyleSheet("""
            QPushButton {
                background: #3182CE;
                color: #FFFFFF;
                border: 1px solid #2B6CB0;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }
            QPushButton:hover { background: #2B6CB0; color: #FFFFFF; }
            QPushButton:pressed { background: #1A365D; }
        """)
        self.btn_radio_link.clicked.connect(lambda: self.radio_link_requested.emit())
        layout.addWidget(self.btn_radio_link)

        # Spacer to push right elements
        layout.addStretch()

        # # 4. Right Status & User Icons
        # ver_lbl = QLabel("API 3.8.1 UI 3.8.2")
        # ver_lbl.setStyleSheet("color: #718096; font-size: 11px; font-weight: 500;")
        # layout.addWidget(ver_lbl)

        # Clear propagation result button (clears coverage overlay / log / status)
        clear_btn = QPushButton()
        clear_btn.setIcon(svg_icon("trash", 14, "#F6AD55"))
        clear_btn.setText(" Clear")
        clear_btn.setToolTip("Clear propagation results from the map")
        clear_btn.setFixedHeight(26)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #2D3748;
                color: #F6AD55;
                border: 1px solid #4A5568;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 8px;
            }
            QPushButton:hover { background: #C05621; color: #FFFFFF; }
        """)
        clear_btn.clicked.connect(lambda: self.section_clicked.emit("clear"))
        layout.addWidget(clear_btn)

        # user_btn = QPushButton()
        # user_btn.setIcon(svg_icon("user", 14, _ICON_COLOR))
        # user_btn.setToolTip("User Profile")
        # user_btn.setFixedSize(26, 26)
        # user_btn.setStyleSheet("""
        #     QPushButton { background: transparent; border: none; }
        #     QPushButton:hover { background: #2D3748; border-radius: 4px; }
        # """)
        # layout.addWidget(user_btn)

        # help_btn = QPushButton()
        # help_btn.setIcon(svg_icon("help", 14, _ICON_COLOR))
        # help_btn.setToolTip("Help & Docs")
        # help_btn.setFixedSize(26, 26)
        # help_btn.setStyleSheet("""
        #     QPushButton { background: transparent; border: none; }
        #     QPushButton:hover { background: #2D3748; border-radius: 4px; }
        # """)
        # layout.addWidget(help_btn)

        fs_btn = QPushButton()
        fs_btn.setIcon(svg_icon("maximize", 13, _ICON_COLOR))
        fs_btn.setToolTip("Toggle Fullscreen")
        fs_btn.setFixedSize(26, 26)
        fs_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: #2D3748; border-radius: 4px; }
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        layout.addWidget(fs_btn)

    def _toggle_fullscreen(self):
        win = self.window()
        if win:
            if win.isFullScreen():
                win.showNormal()
            else:
                win.showFullScreen()
