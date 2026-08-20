"""Standalone launcher for PyInstaller.

PyInstaller runs the entry script as ``__main__`` (no package context), so the
relative imports inside ``signal_gui/__main__.py`` would fail.  This thin
non-package script just delegates to the real ``main()`` while keeping
``signal_gui`` on ``sys.path`` (PyInstaller collects it as a top-level package).
"""

from signal_gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
