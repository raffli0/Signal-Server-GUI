"""Entry point for the Signal-Server PySide6 GUI."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from ._bundle import setup_environment
from .main_window import MainWindow


def main() -> int:
    setup_environment()
    try:
        from osgeo import gdal
        gdal.UseExceptions()
    except Exception:
        pass
    # Make QtWebEngine happy under some environments. By default we raise
    # Chromium's log threshold to FATAL so the harmless
    # "Message N rejected by interface blink.mojom.Widget" ERROR noise (emitted
    # on resize / view teardown) is filtered out. Set the env var to override,
    # e.g. QTWEBENGINE_CHROMIUM_FLAGS="--log-level=0" to see full logs.
    if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS") is None:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--log-level=3"
    app = QApplication(sys.argv)
    app.setApplicationName("RF Propagation GUI")
    from PySide6.QtGui import QPalette, QColor
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1E2226"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QToolTip {
            background-color: #1E2226;
            color: #FFFFFF;
            border: 1px solid #4A5568;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 11px;
        }
    """)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
