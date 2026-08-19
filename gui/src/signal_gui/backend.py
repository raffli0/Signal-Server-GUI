"""Backend: runs Signal-Server (and optional DEM prep) off the GUI thread.

Uses a QThread + subprocess so the UI stays responsive and stdout can be
streamed to the terminal pane. DEM preparation (Viewfinder download + srtm2sdf
conversion) happens inside the same worker before launching the engine.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import params as params_mod
from . import output_stage
from . import dem_convert
from .dem_convert import DemResolveError


def find_engines(root: Optional[str] = None) -> dict:
    """Locate the built Signal-Server binaries.

    ``root`` is the RF-Propagation workspace containing ``Signal-Server``.
    Falls back to common build locations and PATH.
    """
    if root is None:
        here = os.path.dirname(os.path.abspath(__file__))
        # .../gui/src/signal_gui -> .../RF-Propagation
        root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    ss = os.path.join(root, "Signal-Server")
    out = {}
    for key, name in (
        ("signalserver", "signalserver"),
        ("signalserverHD", "signalserverHD"),
        ("signalserverLIDAR", "signalserverLIDAR"),
    ):
        cands = [
            os.path.join(ss, "build", name),
            os.path.join(ss, "src", "build", name),
            os.path.join(ss, name),
            name,
        ]
        for c in cands:
            if c and (os.path.exists(c) or c == name):
                if os.path.exists(c):
                    out[key] = c
                    break
                out[key] = name  # rely on PATH
                break
    for key, name in (("srtm2sdf", "srtm2sdf"), ("srtm2sdf-hd", "srtm2sdf-hd")):
        cands = [
            os.path.join(ss, "utils", "sdf", "usgs2sdf", "build", name),
            os.path.join(ss, "utils", "sdf", "usgs2sdf", name),
            name,
        ]
        for c in cands:
            if c and (os.path.exists(c) or c == name):
                if os.path.exists(c):
                    out[key] = c
                    break
                out[key] = name
                break
    return out


class RunWorker(QThread):
    output_line = Signal(str)
    progress = Signal(str)
    finished = Signal(bool, str, dict)
    error_occurred = Signal(str)
    need_tile_code = Signal(float, float, int)

    def __init__(
        self,
        engine_exe: str,
        output_basename: str,
        parameters: dict,
        dem_spec: Optional[dict] = None,
        srtm2sdf_exe: Optional[str] = None,
        parent: Optional[QThread] = None,
    ):
        super().__init__(parent)
        self.engine_exe = engine_exe
        self.output_basename = output_basename
        self.parameters = parameters
        self.dem_spec = dem_spec
        self.srtm2sdf_exe = srtm2sdf_exe

    def _prepare_dem(self, p: dict) -> None:
        spec = self.dem_spec
        if not spec:
            return
        engine = p.get("engine", "Standard")
        sdf_exe = self.srtm2sdf_exe or dem_convert.which_srtm2sdf(
            "HD" if engine == "HD" else "Standard"
        )
        clat = float(p.get("tx_lat") if p.get("tx_lat") is not None else (spec["lat_lo"] + spec["lat_hi"]) / 2.0)
        clon = float(p.get("tx_lon") if p.get("tx_lon") is not None else (spec["lon_lo"] + spec["lon_hi"]) / 2.0)
        if "tile_code" in spec:
            self.progress.emit(f"Preparing DEM tile {spec['tile_code']} ...")
            sdf_dir = dem_convert.prepare_region(
                spec["tile_code"], spec["resolution"], spec["cache_dir"], sdf_exe,
                center_lat=clat, center_lon=clon,
            )
        else:
            self.progress.emit("Resolving DEM tile (Viewfinder) ...")
            try:
                sdf_dir = dem_convert.ensure_dem_for_area(
                    spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"],
                    spec["resolution"], spec["cache_dir"], sdf_exe, engine,
                    center_lat=clat, center_lon=clon,
                )
            except DemResolveError as exc:
                self.need_tile_code.emit(clat, clon, spec["resolution"])
                raise
        p["sdf_dir"] = sdf_dir
        # The engine segfaults (SIGSEGV) in its "sea-level" fallback when the
        # required SDF terrain is missing. Refuse to launch if the matching
        # SDF variant is absent (HD needs "-hd" tiles, others need plain ones),
        # or if the terrain does not actually cover the transmitter.
        self._require_sdf_variant(p, sdf_dir)

    def _require_sdf_variant(self, p: dict, sdf_dir: str) -> None:
        if not os.path.isdir(sdf_dir):
            raise RuntimeError(f"DEM directory missing: {sdf_dir}")
        hd = p.get("engine") == "HD"
        try:
            names = os.listdir(sdf_dir)
        except OSError as exc:
            raise RuntimeError(f"Cannot read DEM directory {sdf_dir}: {exc}")
        have = any(
            (f.endswith("-hd.sdf") if hd else (f.endswith(".sdf") and not f.endswith("-hd.sdf")))
            for f in names
        )
        if not have:
            kind = "HD (-hd)" if hd else "standard"
            raise RuntimeError(
                f"No {kind} SDF terrain tiles found in {sdf_dir}. The "
                f"{p.get('engine')} engine would crash (SIGSEGV) on missing terrain. "
                f"Use a DEM resolution that matches the engine "
                f"(HD engine requires 30 m; Standard/LIDAR use 90 m)."
            )
        # Make sure the terrain we have actually covers the transmitter, not just
        # any tile in the (per-tile) cache dir. Launching on terrain that omits
        # the Tx cell yields a degenerate, line-shaped coverage. The SDF filenames
        # use an opaque encoding, so we verify against the source .hgt files.
        tx_lat = p.get("tx_lat")
        tx_lon = p.get("tx_lon")
        if tx_lat is not None and tx_lon is not None:
            raw_dir = os.path.join(
                os.path.dirname(os.path.dirname(sdf_dir)), "raw", os.path.basename(sdf_dir)
            )
            if not dem_convert.hgt_covers_center(raw_dir, float(tx_lat), float(tx_lon)):
                raise RuntimeError(
                    f"Prepared DEM in {sdf_dir} does not cover the transmitter "
                    f"({tx_lat}, {tx_lon}). Pick the correct DEM tile for this location."
                )

    def run(self) -> None:  # noqa: D401
        p = dict(self.parameters)
        try:
            self._prepare_dem(p)
            argv = params_mod.build_argv(
                p, engine_exe=self.engine_exe, output_basename=self.output_basename
            )
            self.progress.emit("Running Signal-Server: " + " ".join(argv))
            # Suppress LeakSanitizer post-run reports: the Signal-Server binary
            # is built with -fsanitize=address which includes LSan. LSan fires
            # AFTER the engine writes its output files and causes exit code 1,
            # even though the computation succeeded. We must not edit the engine
            # source, so we disable the leak detector at runtime instead.
            run_env = dict(os.environ)
            run_env.setdefault("ASAN_OPTIONS", "detect_leaks=0")
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=run_env,
            )
            stdout_text = []
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                stdout_text.append(line)
                self.output_line.emit(line)
            proc.wait()
            ppm = self.output_basename + ".ppm"
            output_exists = os.path.exists(ppm)
            if proc.returncode != 0 and not output_exists:
                # Fatal: engine failed AND produced no output
                self.error_occurred.emit(
                    f"Signal-Server exited with code {proc.returncode}"
                )
                return
            if not output_exists:
                self.error_occurred.emit(
                    f"Engine finished but coverage file not found: {ppm}"
                )
                return
            tx_coords = None
            if p.get("lat") is not None and p.get("lon") is not None:
                try:
                    tx_coords = (float(p["lat"]), float(p["lon"]))
                except (ValueError, TypeError):
                    pass
            result = output_stage.stage_output(
                ppm, "\n".join(stdout_text), title="Signal-Server Coverage", tx_coords=tx_coords
            )
            self.finished.emit(True, "\n".join(stdout_text), result)
        except DemResolveError:
            # forwarded via need_tile_code already; nothing else to do
            return
        except Exception as exc:  # pragma: no cover - surface all failures
            self.error_occurred.emit(str(exc))
