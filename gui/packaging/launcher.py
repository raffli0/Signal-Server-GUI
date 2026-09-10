"""Standalone launcher for PyInstaller.

PyInstaller runs the entry script as ``__main__`` (no package context), so the
relative imports inside ``signal_gui/__main__.py`` would fail.  This thin
non-package script just delegates to the real ``main()`` while keeping
``signal_gui`` on ``sys.path`` (PyInstaller collects it as a top-level package).
"""

import os
import sys

# Dynamic Patch Loading:
# If a 'patch' folder or 'signal_gui' folder exists in the application root,
# prioritize it at sys.path[0] so lightweight GUI patches take effect immediately!
if getattr(sys, "frozen", False):
    app_dir = os.path.dirname(os.path.abspath(sys.executable))
    patch_dir = os.path.join(app_dir, "patch")
    if os.path.isdir(patch_dir):
        sys.path.insert(0, patch_dir)
    if os.path.isdir(os.path.join(app_dir, "signal_gui")):
        sys.path.insert(0, app_dir)

from signal_gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
