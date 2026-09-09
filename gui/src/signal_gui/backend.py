"""Backend: runs Signal-Server (and optional DEM prep) off the GUI thread.

Uses a QThread + subprocess so the UI stays responsive and stdout can be
streamed to the terminal pane. DEM preparation (Viewfinder download + srtm2sdf
conversion) happens inside the same worker before launching the engine.
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import params as params_mod
from . import output_stage
from . import dem_convert
from . import link_parse
from .dem_convert import DemResolveError
from ._bundle import app_root, exe as _exe

logger = logging.getLogger("signal_gui.backend")


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
            os.path.join(root, "bin", _exe(name)),
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
            os.path.join(root, "bin", _exe(name)),
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
    percent = Signal(int)
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
            # The mosaic must also span the full run area, not just the Tx
            # point: a partial DEM makes the engine compute the coverage over
            # whatever terrain happens to be loaded instead.
            dem_convert._assert_covers_bbox(
                vrt, spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"]
            )
            self._log_demnas_elevation(vrt, clat, clon)
            sdf_dir = dem_convert.demnas_folder_to_sdf(
                spec["folder"], spec["cache_dir"], sdf_exe, engine,
                spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"],
                center_lat=clat, center_lon=clon,
                warn_cb=self.progress.emit,
            )
            p["sdf_dir"] = sdf_dir
            p["_demnas"] = True
            p["_demnas_mode"] = "demnas_sdf"
            # The engine segfaults (SIGSEGV) in its "sea-level" fallback when the
            # required SDF terrain is missing. Refuse to launch if the matching
            # SDF variant is absent (HD needs "-hd" tiles, others need plain ones),
            # or if the terrain does not actually cover the transmitter.
            self._require_sdf_variant(p, sdf_dir, spec)
            return
        if mode == "demnas_lidar":
            self.progress.emit("Menyiapkan DEMNAS (folder) -> LIDAR .asc (offline) ...")
            vrt = dem_convert._demnas_vrt(spec["folder"], spec["cache_dir"])
            dem_convert._assert_covers(vrt, clat, clon)
            dem_convert._assert_covers_bbox(
                vrt, spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"]
            )
            self._log_demnas_elevation(vrt, clat, clon)
            # downsampling OFF = max_cells 0 → paksa 30m (jaga bukit kecil)
            allow_down = bool(p.get("dem_downsample", False))
            asc, astats = dem_convert.demnas_folder_to_asc(
                spec["folder"], spec["cache_dir"],
                spec["lat_lo"], spec["lat_hi"], spec["lon_lo"], spec["lon_hi"],
                ppd=spec.get("ppd", 1200),
                target_cellsize=spec.get("dem_cellsize"),
                max_cells=(25_000_000 if allow_down else 0),
            )
            p["lidar_file"] = asc
            p["terrain_source"] = "lidar"
            p["_demnas"] = True
            p["_demnas_mode"] = "demnas_lidar"
            p["_dem_stats"] = astats
            # The LIDAR engine derives the plot resolution from the .asc
            # (ppd = rows/lat-span). When the 6M-cell clamp coarsened the
            # grid, the whole plot loses detail — tell the user.
            if astats["ppd"] < 1200:
                self.progress.emit(
                    f"PERINGATAN: resolusi terrain {astats['cellsize_m']:.0f} m "
                    f"(ppd {astats['ppd']} < 1200) karena area run besar "
                    f"(batas {astats['nrows']}x{astats['ncols']} sel). "
                    f"Perkecil radius untuk detail penuh."
                )
            if astats.get("nodata_warning"):
                self.progress.emit(
                    f"PERINGATAN: {astats['nodata_pct']}% terrain NODATA "
                    f"(folder DEMNAS tidak menutupi seluruh area). Coverage "
                    f"di zona itu dihitung di atas terrain palsu (halus/"
                    f"bulat). Tambahkan tile DEMNAS atau perkecil radius."
                )
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
        self._require_sdf_variant(p, sdf_dir, spec)

    def _log_demnas_elevation(self, vrt: str, lat: float, lon: float) -> None:
        """Log the DEMNAS elevation at the transmitter so the run is auditable."""
        elev = dem_convert._sample_elevation(vrt, lat, lon)
        if elev is None or elev == 0:
            self.progress.emit(
                f"⛔ LUBANG HITAM DEM di Tx ({lat:.4f}, {lon:.4f}) elev={elev} → 100% preprocessing (TODO #1/#2)!"
            )
            self.output_line.emit(f"[DEM] Black hole at Tx: elev={elev} m - periksa QGIS export .tif")
        elif elev < -900 or elev > 9000:
            self.progress.emit(f"PERINGATAN: DEMNAS void/nodata di Tx ({lat:.4f}, {lon:.4f}) elev={elev}; engine sea-level.")
        else:
            self.progress.emit(f"Elevasi Tx (DEMNAS): {elev:.1f} m  |  lokasi ({lat:.4f}, {lon:.4f}) → ✅ tidak ada lubang")

    def _require_sdf_variant(
        self, p: dict, sdf_dir: str, spec: Optional[dict] = None
    ) -> None:
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
        # Verify against the .sdf text headers themselves (max_west/min_north/
        # min_west/max_north), which works for every terrain source including
        # offline DEMNAS whose filenames are opaque. Launching on terrain that
        # omits the Tx cell makes the engine compute coverage over whatever
        # region *is* loaded -- producing a coverage plot far away from the Tx.
        boxes = dem_convert.sdf_dir_boxes(sdf_dir, hd=hd)
        tx_lat = p.get("tx_lat")
        tx_lon = p.get("tx_lon")
        if tx_lat is not None and tx_lon is not None and boxes \
                and not dem_convert.sdf_point_covered(boxes, float(tx_lat), float(tx_lon)):
            raise RuntimeError(
                f"Terrain SDF di {sdf_dir} tidak mencakup titik Tx "
                f"({tx_lat}, {tx_lon}). Hasil propagasi pasti salah -- "
                f"perbaiki sumber DEM agar mencakup lokasi ini."
            )
        # Warn when the loaded terrain omits parts of the requested run area.
        if spec is not None and boxes and all(
            k in spec for k in ("lat_lo", "lat_hi", "lon_lo", "lon_hi")
        ):
            missing = dem_convert.sdf_missing_corners(
                boxes, spec["lat_lo"], spec["lat_hi"],
                spec["lon_lo"], spec["lon_hi"],
            )
            if missing:
                self.progress.emit(
                    f"PERINGATAN: terrain SDF tidak mencakup sebagian area "
                    f"run ({', '.join(missing)}); hasil di bagian tersebut "
                    f"tidak valid. Perluas cakupan DEM atau kecilkan radius."
                )

    def _enrich_ground_elevations(self, p: dict) -> None:
        """Look up ground elevation (m AMSL) at Tx/Rx for RM-style reporting.

        Best effort: local DEMNAS mosaic first, then the Open-Meteo API. A
        failure only means the AMSL columns are omitted from reports.
        """
        # Display-only hint: prefer any usable local DEMNAS mosaic over the
        # network so run start is never delayed by an unreachable API.
        demnas_folder = None
        folder = p.get("demnas_dir")
        if folder and os.path.isdir(folder):
            demnas_folder = folder
        cache_dir = (self.dem_spec or {}).get("cache_dir")
        for role, key in (("tx", "tx_lat"), ("rx", "rx_lat")):
            lat, lon = p.get(key), p.get(f"{role}_lon")
            if lat is None or lon is None:
                continue
            elev = dem_convert.ground_elevation(
                float(lat), float(lon),
                demnas_folder=demnas_folder,
                cache_dir=cache_dir,
            )
            p[f"_{role}_ground_elev"] = elev

    def _write_manifest(self, p: dict) -> None:
        """Persist effective run parameters + DEM stats next to the outputs.

        The siggui_* run directories previously held only the ppm/kml, so two
        runs with different results could not be told apart afterwards. The
        manifest makes every run auditable (parameters, terrain resolution,
        relief, NODATA fraction).
        """
        import json

        run_dir = os.path.dirname(self.output_basename)
        try:
            # Record the processing strategy actually used (auditable + lets a
            # later run reproduce the same thread/quality settings).
            with open(os.path.join(run_dir, "params.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(p, fh, indent=2, default=str)
            dem = p.get("_dem_stats")
            if dem:
                with open(os.path.join(run_dir, "dem_stats.json"), "w",
                          encoding="utf-8") as fh:
                    json.dump(dem, fh, indent=2)
                self.progress.emit(
                    f"[dem] asc {dem['cellsize_m']:.0f} m (ppd {dem['ppd']}) "
                    f"relief {dem['min_m']}..{dem['max_m']} m · "
                    f"nodata {dem['nodata_pct']}%"
                )
        except (OSError, TypeError, ValueError):
            pass  # manifest is best-effort diagnostics

    def _run_engine(self, argv, run_env) -> tuple[int, list[str]]:
        """Run the engine once, streaming stdout to the terminal.

        Returns ``(returncode, stdout_lines)``.
        """
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=run_env, **kwargs
        )
        stdout_text: list[str] = []
        assert proc.stdout is not None
        pct_re = re.compile(r"\[\s*(\d{1,3})%\]")
        for line in proc.stdout:
            line = line.rstrip("\n")
            stdout_text.append(line)
            self.output_line.emit(line)
            m = pct_re.search(line)
            if m:
                self.percent.emit(min(100, int(m.group(1))))
        proc.wait()
        return proc.returncode, stdout_text

    @staticmethod
    def _bbox_plausible(bbox, p) -> bool:
        """False when the engine's ``Area boundaries`` are garbage.

        The threaded LIDAR plotter has a longitude-normalisation race
        (observed as exact +-1086-degree shifts on E/W plus dropped radials --
        the "pizza slice" pattern). Such runs must never be shown; they are
        retried instead.
        """
        if not bbox:
            return False
        try:
            n, e, s, w = (float(v) for v in bbox)
        except (TypeError, ValueError):
            return False
        if not all(-90.0 <= v <= 90.0 for v in (n, s)):
            return False
        if not all(-180.0 <= v <= 180.0 for v in (e, w)):
            return False
        if n <= s or e <= w:
            return False
        lat0 = float(p.get("tx_lat") if p.get("tx_lat") is not None
                     else (n + s) / 2.0)
        radius_km = float(p.get("radius") or 30) or 30.0
        dlat = radius_km / 111.0
        dlon = radius_km / (111.32 * max(0.01, math.cos(math.radians(lat0))))
        # Generous 4x margin: cropping/rounding may widen the box a little,
        # but never by an order of magnitude.
        return ((n - s) <= 4.0 * dlat + 1.0) and ((e - w) <= 4.0 * dlon + 1.0)

    @staticmethod
    def _next_segments(cur) -> int:
        """Halve the plot-segment count, floor 4 (engine needs even >2).

        The threaded-LIDAR longitude race only shows up at high segment
        counts (observed broken at 16, clean at 8/4), so stepping the ladder
        down between retries converges on a healthy configuration instead of
        repeating an identical failing run. Fix: pastikan genap (engine
        `segments %2==0` atau `%3==0`), jadi 30→14 bukan 15.
        """
        try:
            cur = int(cur)
        except (TypeError, ValueError):
            cur = 16
        nxt = cur // 2
        if nxt % 2 != 0:
            nxt -= 1
        return max(4, nxt)

    def run(self) -> None:  # noqa: D401
        p = dict(self.parameters)
        # Pin the effective segment count up-front so build_argv, the retry
        # ladder and the run manifest all agree on one number (otherwise the
        # auto fallback resolves lazily and retries report "None -> 8").
        if not p.get("plot_segments"):
            p["plot_segments"] = params_mod.auto_segments()
        try:
            self._enrich_ground_elevations(p)
            self._prepare_dem(p)
            self._write_manifest(p)
            argv = params_mod.build_argv(
                p, engine_exe=self.engine_exe, output_basename=self.output_basename
            )
            for line in params_mod.format_run_summary(p, argv, self.engine_exe):
                self.output_line.emit(line)
            self.output_line.emit(
                "[run] Renderer : multiply-blend + translucent-core v2")
            self.progress.emit("Running Signal-Server: " + " ".join(argv))
            # Suppress LeakSanitizer post-run reports: the Signal-Server binary
            # is built with -fsanitize=address which includes LSan. LSan fires
            # AFTER the engine writes its output files and causes exit code 1,
            # even though the computation succeeded. We must not edit the engine
            # source, so we disable the leak detector at runtime instead.
            run_env = dict(os.environ)
            run_env.setdefault("ASAN_OPTIONS", "detect_leaks=0")

            # --- Radio Link (point-to-point) mode ---
            if p.get("path_profile"):
                proc_returncode, stdout_text = self._run_engine(argv, run_env)
                report_file = self.output_basename + ".txt"
                if not os.path.exists(report_file):
                    if proc_returncode != 0:
                        self.error_occurred.emit(
                            f"Signal-Server exited with code {proc_returncode}"
                        )
                    else:
                        tail = "\n".join(stdout_text[-5:]) if stdout_text else ""
                        msg = "Engine finished but link report not found."
                        if tail:
                            msg += f"\nOutput engine:\n{tail}"
                        self.error_occurred.emit(msg)
                    return
                try:
                    link = link_parse.parse_link_output(
                        self.output_basename, p.get("rx_threshold_dbm"),
                        sdf_dir=p.get("sdf_dir"),
                        hd=(p.get("engine") == "HD"),
                        asc_file=p.get("lidar_file"),
                        tx_latlon=(p.get("tx_lat"), p.get("tx_lon")),
                        rx_latlon=(p.get("rx_lat"), p.get("rx_lon")),
                    )
                except Exception as exc:  # pragma: no cover
                    self.error_occurred.emit(f"Failed to parse link output: {exc}")
                    return
                self.finished.emit(True, "\n".join(stdout_text), {"link": link})
                return

            # --- Area coverage: the threaded LIDAR plotter occasionally
            # emits garbage boundaries and drops radials ("pizza slices").
            # Identical argv reproduces it intermittently, and the race only
            # triggers at high -segments counts (broken at 16, clean at 8/4),
            # so each retry halves the segment count as well.
            attempts = 4
            result = None
            stdout_text: list[str] = []
            cur_argv = argv
            for attempt in range(1, attempts + 1):
                proc_returncode, stdout_text = self._run_engine(cur_argv, run_env)
                ppm = self.output_basename + ".ppm"
                output_exists = os.path.exists(ppm)
                if proc_returncode != 0 and not output_exists:
                    self.error_occurred.emit(
                        f"Signal-Server exited with code {proc_returncode}"
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
                    tx_coords=tx_coords, color_file=p.get("color_file"), params=p
                )
                # Judge the ENGINE's raw boundaries, not the sanitised bbox:
                # parse_bbox silently substitutes a params-based extent when
                # the printed one is insane, which would otherwise make every
                # broken run look perfectly healthy here.
                raw_bbox = output_stage.parse_engine_bbox_raw(
                    "\n".join(stdout_text))
                judge = raw_bbox if raw_bbox is not None \
                    else result.get("bbox")
                if self._bbox_plausible(judge, p):
                    # Manifest should reflect the configuration that actually
                    # produced this output (may differ after a segments retry).
                    self._write_manifest(p)
                    # Fake-terrain smoke detector: a near-perfect circle over
                    # 100% of azimuths is the signature of the engine computing
                    # on flat/sea-level ground (real ITM over relief is ragged).
                    try:
                        if p.get("tx_lat") is not None and \
                                p.get("tx_lon") is not None:
                            shape = output_stage.analyze_coverage_shape(
                                result["png"], result["bbox"],
                                float(p["tx_lat"]), float(p["tx_lon"]))
                            if shape["fill_az_pct"] > 90.0 and \
                                    shape["edge_rel_std"] < 0.01:
                                warn = (
                                    "PERINGATAN bentuk: cakupan tampak "
                                    "LINGKARAN HALUS "
                                    f"(raggedness {shape['edge_rel_std']*100:.2f}%, "
                                    "terrain palsu/fallback?). Simpan folder "
                                    f"{os.path.basename(os.path.dirname(self.output_basename))}"
                                    " dan laporkan.")
                                self.progress.emit(warn)
                                self.output_line.emit(warn)
                    except Exception as exc:  # noqa: BLE001 - diagnostics only
                        logger.debug("Coverage diagnostic evaluation exception: %s", exc)
                    break
                if attempt < attempts:
                    old_seg = p.get("plot_segments")
                    new_seg = self._next_segments(old_seg)
                    self.percent.emit(0)
                    warn = (
                        "PERINGATAN: hasil engine tidak konsisten terdeteksi "
                        "(boundaries invalid / radial terpotong -- bug thread "
                        f"plot LIDAR). Turunkan Map segments "
                        f"{old_seg} -> {new_seg}, mencoba ulang "
                        f"{attempt}/{attempts - 1} ..."
                    )
                    # progress only feeds the status bar; mirror to the
                    # terminal so retries are auditable in saved logs.
                    self.progress.emit(warn)
                    self.output_line.emit(warn)
                    if new_seg != old_seg:
                        p["plot_segments"] = new_seg
                        cur_argv = params_mod.build_argv(
                            p, engine_exe=self.engine_exe,
                            output_basename=self.output_basename,
                        )
                    continue
                self.error_occurred.emit(
                    "Engine menghasilkan coverage rusak setelah "
                    f"{attempts} percobaan (race normalisasi longitude pada "
                    "plot thread LIDAR). Jalankan ulang, atau turunkan "
                    "'Map segments' secara manual.")
                return
            raster_txt = ppm[:-4] + "_raster.txt"
            if os.path.exists(raster_txt):
                # Sanity check: the dumped raster must actually enclose the Tx.
                # A raster that sits far away from the Tx means the engine
                # computed coverage over the wrong terrain (DEM mismatch).
                tx_lat = p.get("tx_lat")
                tx_lon = p.get("tx_lon")
                if tx_lat is not None and tx_lon is not None and \
                        not output_stage.raster_txt_contains(
                            raster_txt, float(tx_lat), float(tx_lon)):
                    self.error_occurred.emit(
                        "Hasil coverage TIDAK melingkupi titik Tx "
                        f"({tx_lat}, {tx_lon}). Kemungkinan terrain DEM tidak "
                        f"sesuai lokasi -- periksa sumber DEM dan "
                        f"jalankan ulang. (Lihat log 'Area boundaries'.)"
                    )
                    return
                result["raster_txt"] = raster_txt
            self.finished.emit(True, "\n".join(stdout_text), result)
        except DemResolveError as exc:
            # Surface the reason (missing DEM tiles, folder does not cover the
            # run bbox, or invalid LIDAR terrain). For the SDF/online path the
            # UI may also offer a tile download via need_tile_code, but the
            # user still needs to see why the run stopped.
            self.error_occurred.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - surface all failures
            self.error_occurred.emit(str(exc))
