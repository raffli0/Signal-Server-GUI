"""Path resolution that works both in development and when frozen (.exe).

When packaged with PyInstaller (``--onedir``), the application no longer lives
inside the ``RF-Propagation/gui/src/signal_gui`` source tree, so every
``__file__``-based guess about the repo layout breaks.  This module centralises
that logic:

* In development the "app root" is the RF-Propagation workspace (three levels
  above this file), exactly as the rest of the code already assumes.
* When frozen the "app root" is the directory that contains the executable /
  the extracted bundle (``sys._MEIPASS`` for one-file, the program folder for
  one-dir).  The PyInstaller spec mirrors the repo layout inside that folder
  (``Signal-Server/build/...``, ``gui/cache/dem``), so the existing engine /
  cache lookup code keeps working unchanged.
"""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return getattr(sys, "frozen", False)


def exe(name: str) -> str:
    """Return ``name`` with a ``.exe`` suffix appended when on Windows.

    Lets the same path/candidate lists work on both Linux and Windows frozen
    builds (where the engine binaries are ``signalserver.exe`` etc.).
    """
    if os.name == "nt" and not name.lower().endswith(".exe"):
        return name + ".exe"
    return name


def bundle_dir() -> str:
    """Directory that holds the bundled application data.

    For a one-dir build this is the folder containing the executable.  For a
    one-file build PyInstaller extracts everything to ``sys._MEIPASS``.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def app_root() -> str:
    """The "repo root" the rest of the code expects.

    Development layout::

        <root>/gui/src/signal_gui/__init__.py   ->   <root>

    Frozen layout: the bundle folder *is* the root, so engine data placed at
    ``<bundle>/Signal-Server/...`` is found exactly as in development.
    """
    if is_frozen():
        return bundle_dir()
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def cache_root() -> str:
    """Return a writable cache directory for DEM tiles and temporary files.

    In development, uses <repo>/gui/cache/dem.
    When frozen, uses %LOCALAPPDATA%/SignalServerGUI/cache/dem (Windows) or
    ~/.cache/SignalServerGUI/cache/dem (Linux) so that the user never encounters
    permission issues or space constraints in application installation directories.
    """
    if is_frozen():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = os.path.join(local_app_data, "SignalServerGUI", "cache", "dem")
            os.makedirs(base, exist_ok=True)
            return base
        home = os.path.expanduser("~")
        base = os.path.join(home, ".cache", "SignalServerGUI", "cache", "dem")
        os.makedirs(base, exist_ok=True)
        return base
    return os.path.join(app_root(), "gui", "cache", "dem")


def setup_environment() -> None:
    """Prepend bundled engine and GDAL tools directories to PATH and set GDAL/PROJ data."""
    root = app_root()
    prepend_paths = [
        os.path.join(root, "bin"),
        os.path.join(root, "bin", "gdal"),
        os.path.join(root, "gdal"),
        os.path.join(root, "Signal-Server", "build"),
    ]
    cur_path = os.environ.get("PATH", "")
    for p in prepend_paths:
        if os.path.isdir(p) and p not in cur_path:
            cur_path = p + os.pathsep + cur_path
    os.environ["PATH"] = cur_path

    # Set GDAL_DATA and PROJ_LIB so GDAL and PROJ find datum/ellipsoid files
    for gdir in [os.path.join(root, "bin", "gdal_data"), os.path.join(root, "gdal_data")]:
        if os.path.isdir(gdir):
            os.environ["GDAL_DATA"] = gdir
            break
    for pdir in [os.path.join(root, "bin", "proj"), os.path.join(root, "proj")]:
        if os.path.isdir(pdir):
            os.environ["PROJ_LIB"] = pdir
            break
