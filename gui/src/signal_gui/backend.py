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
from . import link_parse
from .dem_convert import DemResolveError
from ._bundle import app_root, exe as _exe


def find_engines(root: Optional[str] = None) -> dict:
    """Locate the built Signal-Server binaries.

    ``root`` is the RF-Propagation workspace containing ``Signal-Server``.
    Falls back to common build locations and PATH.
    """
    if root is None:
        from ._bundle import app_root
        root = app_root()
    ss = os.path.join(root, "Signal-Server")
    out = {}
    for key, name in (
        ("signalserver", "signalserver"),
        ("signalserverHD", "signalserverHD"),
        ("signalserverLIDAR", "signalserverLIDAR"),
    ):
        cands = [
            os.path.join(ss, "build", _exe(name)),
            os.path.join(ss, "src", "build", _exe(name)),
            os.path.join(ss, _exe(name)),
            _exe(name),
        ]
        for c in cands:
            if c and (os.path.exists(c) or c == _exe(name)):
                if os.path.exists(c):
                    out[key] = c
                    break
                out[key] = _exe(name)  # rely on PATH
                break
    for key, name in (("srtm2sdf", "srtm2sdf"), ("srtm2sdf-hd", "srtm2sdf-hd")):
        cands = [
            os.path.join(ss, "utils", "sdf", "usgs2sdf", "build", _exe(name)),
            os.path.join(ss, "utils", "sdf", "usgs2sdf", _exe(name)),
            _exe(name),
        ]
        for c in cands:
            if c and (os.path.exists(c) or c == _exe(name)):
                if os.path.exists(c):
                    out[key] = c
                    break
                out[key] = _exe(name)
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
        mode = spec.get("mode", "auto")
        if mode == "demnas_sdf":
            self.progress.emit("Menyiapkan DEMNAS (folder) -> SDF (offline) ...")
            vrt = dem_convert._demnas_vrt(spec["folder"], spec["cache_dir"])
            dem_convert._assert_covers(vrt, clat, clon)
            self._log_demnas_elevation(vrt, clat, clon)
            sdf_dir = dem_convert.demnas_folder_to_sdf(
                spec["folder"], spec["cache_dir"], sdf_exe, engine,
                spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"],
                center_lat=clat, center_lon=clon,
            )
            p["sdf_dir"] = sdf_dir
            p["_demnas"] = True
            p["_demnas_mode"] = "demnas_sdf"
            # The engine segfaults (SIGSEGV) in its "sea-level" fallback when the
            # required SDF terrain is missing. Refuse to launch if the matching
            # SDF variant is absent (HD needs "-hd" tiles, others need plain ones),
            # or if the terrain does not actually cover the transmitter.
            self._require_sdf_variant(p, sdf_dir)
            return
        if mode == "demnas_lidar":
            self.progress.emit("Menyiapkan DEMNAS (folder) -> LIDAR .asc (offline) ...")
            vrt = dem_convert._demnas_vrt(spec["folder"], spec["cache_dir"])
            dem_convert._assert_covers(vrt, clat, clon)
            self._log_demnas_elevation(vrt, clat, clon)
            asc = dem_convert.demnas_folder_to_asc(
                spec["folder"], spec["cache_dir"],
                spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"],
                ppd=spec.get("ppd", 1200),
                target_cellsize=spec.get("dem_cellsize"),
            )
            p["lidar_file"] = asc
            p["terrain_source"] = "lidar"
            p["_demnas"] = True
            p["_demnas_mode"] = "demnas_lidar"
            return
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

    def _log_demnas_elevation(self, vrt: str, lat: float, lon: float) -> None:
        """Log the DEMNAS elevation at the transmitter so the run is auditable."""
        elev = dem_convert._sample_elevation(vrt, lat, lon)
        if elev is None:
            self.progress.emit(
                f"PERINGATAN: DEMNAS void di Tx ({lat:.4f}, {lon:.4f}); "
                f"engine akan pakai sea-level."
            )
        else:
            self.progress.emit(
                f"Elevasi Tx (DEMNAS): {elev:.1f} m  |  lokasi ({lat:.4f}, {lon:.4f})"
            )

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
        # (Offline DEMNAS terrain is clipped from the source by construction, so
        # this per-tile check is skipped for that mode.)
        if p.get("_demnas"):
            return
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
            for line in params_mod.format_run_summary(p, argv, self.engine_exe):
                self.output_line.emit(line)
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
            # --- Radio Link (point-to-point) mode ---
            if p.get("path_profile"):
                report_file = self.output_basename + ".txt"
                if not os.path.exists(report_file):
                    if proc.returncode != 0:
                        self.error_occurred.emit(
                            f"Signal-Server exited with code {proc.returncode}"
                        )
                    else:
                        self.error_occurred.emit(
                            "Engine finished but link report not found."
                        )
                    return
                try:
                    link = link_parse.parse_link_output(
                        self.output_basename, p.get("rx_threshold_dbm")
                    )
                except Exception as exc:  # pragma: no cover
                    self.error_occurred.emit(f"Failed to parse link output: {exc}")
                    return
                self.finished.emit(True, "\n".join(stdout_text), {"link": link})
                return

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
                ppm, "\n".join(stdout_text), title="Signal-Server Coverage",
                tx_coords=tx_coords, color_file=p.get("color_file")
            )
            raster_txt = ppm[:-4] + "_raster.txt"
            if os.path.exists(raster_txt):
                result["raster_txt"] = raster_txt
            self.finished.emit(True, "\n".join(stdout_text), result)
        except DemResolveError:
            # forwarded via need_tile_code already; nothing else to do
            return
        except Exception as exc:  # pragma: no cover - surface all failures
            self.error_occurred.emit(str(exc))
