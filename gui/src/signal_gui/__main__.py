"""Entry point for the Signal-Server PySide6 GUI."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    # Make QtWebEngine happy under some environments. By default we raise
    # Chromium's log threshold to FATAL so the harmless
    # "Message N rejected by interface blink.mojom.Widget" ERROR noise (emitted
    # on resize / view teardown) is filtered out. Set the env var to override,
    # e.g. QTWEBENGINE_CHROMIUM_FLAGS="--log-level=0" to see full logs.
    if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS") is None:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--log-level=3"
    app = QApplication(sys.argv)
    app.setApplicationName("RF Propagation GUI")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
