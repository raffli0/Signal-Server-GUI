"""Automated Packaging Script for Windows (Standalone One-Dir Bundle).

Packages Signal-Server-GUI into a standalone, portable Windows application
with embedded Python, PySide6, compiled Signal-Server C++ engines, and GDAL tools.

Usage (on Windows or CI):
    python scripts/package_windows.py
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def package():
    print(f"=== Packaging Signal-Server-GUI for Windows ===")
    print(f"Repository Root: {ROOT}")

    # Check for pyinstaller
    try:
        import PyInstaller
        print(f"Found PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    dist_dir = os.path.join(ROOT, "dist")
    build_dir = os.path.join(ROOT, "build_pyinstaller")
    entry_point = os.path.join(ROOT, "gui", "packaging", "launcher.py")

    # Assets & Data to bundle
    resources_src = os.path.join(ROOT, "gui", "src", "signal_gui", "resources")
    antennas_src = os.path.join(ROOT, "gui", "data", "antennas")
    palettes_src = os.path.join(ROOT, "gui", "data", "palettes")
    color_src = os.path.join(ROOT, "Signal-Server", "color")
    bin_src = os.path.join(ROOT, "bin")

    sep = ";" if sys.platform == "win32" else ":"

    datas = [
        f"{resources_src}{sep}signal_gui/resources",
    ]
    if os.path.isdir(antennas_src):
        datas.append(f"{antennas_src}{sep}gui/data/antennas")
    if os.path.isdir(palettes_src):
        datas.append(f"{palettes_src}{sep}gui/data/palettes")
    if os.path.isdir(color_src):
        datas.append(f"{color_src}{sep}Signal-Server/color")
    if os.path.isdir(bin_src):
        datas.append(f"{bin_src}{sep}bin")

    hidden_imports = [
        "signal_gui",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtPrintSupport",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "numpy",
        "scipy",
        "PIL",
        "PIL.Image",
        "pyproj",
        "mgrs",
    ]
    try:
        import osgeo
        hidden_imports.extend(["osgeo", "osgeo.gdal"])
    except ImportError:
        pass

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=SignalServerGUI",
        "--noconfirm",
        "--windowed",
        f"--paths={os.path.join(ROOT, 'gui', 'src')}",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    cmd.append(entry_point)

    print("Running PyInstaller command:")
    print(" ".join(cmd))
    subprocess.check_call(cmd)

    target_app = os.path.join(dist_dir, "SignalServerGUI")
    print(f"\n[SUCCESS] Standalone Windows application built successfully at:\n{target_app}\n")
    print("To distribute to end-users:")
    print("1. Users can run 'SignalServerGUI.exe' directly without installing Python or dependencies.")
    print("2. Compile 'scripts/installer.iss' with Inno Setup to create a single 'SignalServerGUI-Setup.exe' installer.")


if __name__ == "__main__":
    package()
