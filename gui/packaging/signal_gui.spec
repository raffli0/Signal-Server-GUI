# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RF Propagation / Signal-Server GUI.

Builds a self-contained Windows ``.exe`` (--onedir) that bundles:

  * the PySide6 / QtWebEngine GUI,
  * the compiled Signal-Server engine binaries (signalserver.exe, srtm2sdf.exe,
    ...), and
  * the bundled leaflet resources + Signal-Server colour/antenna data.

Run from the ``gui/`` directory on Windows:

    pyinstaller packaging/signal_gui.spec

The frozen app resolves paths via ``signal_gui._bundle`` so it finds the
engine/data inside its own folder instead of a source checkout.

The C++ engine binaries are NOT compiled by this spec. Build them on Windows
first (see packaging/README.md) and drop the resulting ``.exe`` files into
``packaging/engine/`` (and ``packaging/engine/usgs2sdf/`` for srtm2sdf). They are
copied into the bundle at the locations the Python code already expects.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Spec file lives in gui/packaging; repo root is the parent's parent.
HERE = os.path.dirname(os.path.abspath(SPECPATH))          # .../gui
GUI_ROOT = os.path.dirname(HERE)                            # .../RF-Propagation
ENGINE_DIR = os.path.join(HERE, "packaging", "engine")

# ---- Engine binaries (built separately on Windows) --------------------------
datas = []
binaries = []

# Main propagation engines -> Signal-Server/build/
for _exe in ("signalserver.exe", "signalserverHD.exe", "signalserverLIDAR.exe"):
    _src = os.path.join(ENGINE_DIR, _exe)
    if os.path.exists(_src):
        datas.append((_src, os.path.join("Signal-Server", "build")))

# DEM converter -> Signal-Server/utils/sdf/usgs2sdf/build/
_usgs_src = os.path.join(ENGINE_DIR, "usgs2sdf", "srtm2sdf.exe")
if os.path.exists(_usgs_src):
    datas.append((_usgs_src, os.path.join("Signal-Server", "utils", "sdf", "usgs2sdf", "build")))
else:
    # Allow a flat layout where srtm2sdf.exe is placed directly in engine/.
    _usgs_src2 = os.path.join(ENGINE_DIR, "srtm2sdf.exe")
    if os.path.exists(_usgs_src2):
        datas.append((_usgs_src2, os.path.join("Signal-Server", "utils", "sdf", "usgs2sdf", "build")))

# ---- Signal-Server static data (colour files, antenna patterns, etc.) ------
_ss = os.path.join(GUI_ROOT, "Signal-Server")
for _sub in ("color", "antenna", "data"):
    _d = os.path.join(_ss, _sub)
    if os.path.isdir(_d):
        datas.append((_d, os.path.join("Signal-Server", _sub)))

# ---- Python package data (html templates + leaflet assets) ------------------
datas += collect_data_files("signal_gui", subdir="resources")

# ---- Hidden imports so QtWebEngine's hooks fire on Windows -----------------
hiddenimports = [
    "signal_gui",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
]
hiddenimports += collect_submodules("PySide6")

a = Analysis(
    [os.path.join(HERE, "packaging", "launcher.py")],
    pathex=[os.path.join(GUI_ROOT, "gui", "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest",
        "matplotlib", "scipy", "numpy",  # not used by the GUI
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RFPropagationGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RFPropagationGUI",
)
