"""Entry point for the Signal-Server PySide6 GUI."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    # Make QtWebEngine happy under some environments.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))
    app = QApplication(sys.argv)
    app.setApplicationName("RF Propagation GUI")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
