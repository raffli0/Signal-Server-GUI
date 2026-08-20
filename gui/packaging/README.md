# Packaging the GUI as a Windows `.exe`

The GUI (`signal_gui`) is a PySide6/QtWebEngine app. To ship a standalone
Windows executable you need to bundle **three** things that are *not* in git:

1. The Python app + Qt (via PyInstaller).
2. The compiled **Signal-Server C++ engine** binaries (`signalserver.exe`,
   `srtm2sdf.exe`, …). These must be built on Windows.
3. (Optional) A pre-populated DEM cache so the first run works offline.

The PyInstaller spec freezes the Python side; the engine binaries are built
separately and dropped into `packaging/engine/` before building.

---

## 1. Build the C++ engine on Windows

Requirements: **Visual Studio (MSVC)** or **MinGW-w64**, **CMake ≥ 3.5**,
**ImageMagick** (`convert` on PATH), and the zlib/bzip2 dev libs.

```bat
cd Signal-Server
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

This produces `Signal-Server\build\signalserver.exe` (and friends). Also build
the DEM converter:

```bat
cd Signal-Server\utils\sdf\usgs2sdf
cmake -S . -B build
cmake --build build --config Release
```

### Place the binaries for packaging

Copy the engine executables into this `packaging/` tree (git-ignored):

```
packaging/engine/signalserver.exe
packaging/engine/signalserverHD.exe
packaging/engine/signalserverLIDAR.exe
packaging/engine/usgs2sdf/srtm2sdf.exe      (or packaging/engine/srtm2sdf.exe)
```

The spec copies them into the bundle at the exact locations the Python code
expects (`Signal-Server/build/...`, `Signal-Server/utils/sdf/usgs2sdf/build/...`).

---

## 2. Install the packaging toolchain

In your Windows Python environment:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pyinstaller
```

> `pyinstaller` is also listed in `packaging/requirements.txt`.

---

## 3. Build the `.exe`

Run PyInstaller from the **`gui/`** directory (so the spec's relative paths
resolve):

```bat
cd gui
pyinstaller packaging\signal_gui.spec
```

Output lands in `gui/dist/RFPropagationGUI/` — a folder containing
`RFPropagationGUI.exe` plus the engine binaries, Qt DLLs and bundled data.
Copy that whole folder to the target machine; no Python install required.

> Use the **--onedir** layout (the spec default). QtWebEngine is large and a
> one-file build extracts hundreds of MB to a temp dir on every launch and can
> have trouble locating its subprocess/resources. The `gui/cache/dem` folder is
> created inside the bundle at runtime and must stay writable, so keep the
> folder on a normal disk (not a read-only/network location).

---

## 4. DEM cache (optional, for offline use)

By default the app downloads SRTM tiles into `gui/cache/dem` on first use
(needs internet). To pre-bake it, copy your existing `gui/cache` from a machine
that has already downloaded the tiles into the bundle folder after install.

---

## Notes / troubleshooting

* **Blank map / `L is not defined`** — that was a dev-only QtWebEngine setting
  bug (now fixed in `map_view.py`). It does not affect the frozen build, which
  enables `LocalContentCanAccessFileUrls`.
* If Windows Defender / SmartScreen blocks the exe, it's an unsigned build —
  distribute with a code-signing cert or instruct users to allow it.
* The engine runs as a subprocess; if `signalserver.exe` is missing you'll see
  "engine not found" in the GUI log. Verify the files landed in
  `dist\RFPropagationGUI\Signal-Server\build\`.
