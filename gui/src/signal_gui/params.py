"""Canonical parameter model and command-line builder for Signal-Server.

All field names here are the internal canonical keys produced by the GUI
widgets. ``build_argv`` turns a params dict into a Signal-Server argument
vector. Flag semantics were verified against Signal-Server ``src/main.cc``.
"""

from __future__ import annotations

import math
import os
from typing import Iterable


# ---------------------------------------------------------------------------
# Static option tables (verified against src/main.cc help text)
# ---------------------------------------------------------------------------

# -pm values: label -> integer
MODELS: list[tuple[str, int]] = [
    ("ITM (Longley-Rice)", 1),
    ("Line-of-Sight (LOS)", 2),
    ("Hata", 3),
    ("ECC33", 4),
    ("SUI", 5),
    ("COST-231 Hata", 6),
    ("Free Space (ITU-R P.525)", 7),
    ("ITWOM", 8),
    ("Ericsson", 9),
    ("Plane Earth", 10),
    ("Egli VHF/UHF", 11),
    ("Soil", 12),
]

# All models are supported and verified functional.
CRASHING_MODELS: set[int] = set()

# -cl radio climate zone: int -> label
CLIMATE_ZONES: list[tuple[int, str]] = [
    (1, "Equatorial"),
    (2, "Continental Subtropical"),
    (3, "Maritime Subtropical"),
    (4, "Desert"),
    (5, "Continental Temperate"),
    (6, "Maritime Temperate (land)"),
    (7, "Maritime Temperate (sea)"),
]

# -pe propagation environment / context: label -> int
CONTEXTS: list[tuple[str, int]] = [
    ("Urban", 1),
    ("Suburban", 2),
    ("Rural", 3),
]

# Per-option relevance for each propagation model. Verified against
# Signal-Server src/models/los.cc (ITM/ITWOM take radio_climate + conf + rel;
# Hata/ECC33/SUI/COST231/Ericsson take pmenv) and main.cc (``-ked`` help:
# "Already on for ITM"; los.cc:728 applies ked() only when prop_model > 1).
# States:
#   active   -- the model consumes the flag (send it).
#   na       -- the model ignores the flag (do not send; would be a no-op).
#   builtin  -- the feature is already part of the model; the flag is redundant.
OPTION_ACTIVE = "active"
OPTION_NA = "na"
OPTION_BUILTIN = "builtin"

MODEL_OPTION_STATES: dict[int, dict[str, str]] = {
    1:  {"reliability": OPTION_ACTIVE, "climate": OPTION_ACTIVE,
         "context": OPTION_NA, "diffraction": OPTION_BUILTIN},
    2:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_NA, "diffraction": OPTION_ACTIVE},
    3:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    4:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    5:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    6:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    7:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_NA, "diffraction": OPTION_NA},
    8:  {"reliability": OPTION_ACTIVE, "climate": OPTION_ACTIVE,
         "context": OPTION_NA, "diffraction": OPTION_BUILTIN},
    9:  {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    10: {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    11: {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
    12: {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_ACTIVE, "diffraction": OPTION_ACTIVE},
}


# Radio Mobile expresses RX thresholds in dBm or dBµV (50 Ω system); the engine
# only accepts dBm, so the GUI exposes both unit fields and converts here.
DBM_DBUV_OFFSET_50OHM = 107.0


def dbm_to_dbuv(dbm: float) -> float:
    """Convert a dBm RX threshold to dBµV (50 Ω reference)."""
    return float(dbm) + DBM_DBUV_OFFSET_50OHM


def dbuv_to_dbm(dbuv: float) -> float:
    """Convert a dBµV RX threshold to dBm (50 Ω reference)."""
    return float(dbuv) - DBM_DBUV_OFFSET_50OHM


def model_name(pm) -> str:
    """Human label for a propagation model id (falls back to ``pm N``)."""
    try:
        pm = int(pm)
    except (TypeError, ValueError):
        return str(pm)
    for label, val in MODELS:
        if val == pm:
            return label
    return f"pm {pm}"


def option_states_for_model(model_pm) -> dict[str, str]:
    """Relevance (active/na/builtin) of the model-dependent GUI options.

    Returns a dict with keys ``reliability``, ``climate``, ``context`` and
    ``diffraction``. Used both by ``build_argv`` (to drop no-op flags) and by
    the GUI (to grey-out irrelevant controls with an explanatory badge).
    """
    try:
        model_pm = int(model_pm)
    except (TypeError, ValueError):
        model_pm = 0
    return dict(MODEL_OPTION_STATES.get(
        model_pm,
        {"reliability": OPTION_NA, "climate": OPTION_NA,
         "context": OPTION_NA, "diffraction": OPTION_NA},
    ))


def auto_segments(max_segments: int = 360) -> int:
    """Engine plot-segment count for parallel processing.

    Signal-Server defaults to 4 segments (main.cc:1101), which underuses
    modern multi-core CPUs. Use ~2x logical cores, clamped to an even value
    ``>= 4``. Patched to allow 360° / 1° = 360 seg (int, not uint8_t) to
    hilangkan pola jari-jari interpolasi azimuth.
    """
    try:
        cores = os.cpu_count() or 4
    except Exception:  # pragma: no cover - pathological platforms
        cores = 4
    seg = min(max(4, 2 * cores), max_segments, 360)
    if seg % 2 != 0:
        seg += 1
    # harus kelipatan 2 atau 3 (los.cc:1248)
    if seg % 2 != 0 and seg % 3 != 0:
        seg += 1
    return seg

# Engine selection -> binary basename (chosen by argv[0] inside Signal-Server)
ENGINES: dict[str, str] = {
    "Standard": "signalserver",
    "HD": "signalserverHD",
    "LIDAR": "signalserverLIDAR",
}

# -res pixels-per-tile choices
RESOLUTIONS: list[int] = [300, 600, 1200, 3600]

# Viewfinder Panoramas DEM download endpoints (verified working URLs)
VIEWFINDER_BASE = {
    3: "https://viewfinderpanoramas.org/dem3",
    1: "https://viewfinderpanoramas.org/dem1",
    15: "https://www.viewfinderpanoramas.org/DEM/TIF15",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_erp(rf_power_w: float, tx_gain_dbi: float, cable_loss_db: float) -> float:
    """Effective Radiated Power in Watts.

    ERP_W = P_W * 10^((gain_dBi - 2.15) / 10) / 10^(loss_dB / 10)
    Signal-Server's ``-erp`` expects Watts (see src/main.cc:1826 log line).
    """
    if rf_power_w <= 0:
        return 0.0
    gain_factor = 10 ** ((tx_gain_dbi - 2.15) / 10.0)
    loss_factor = 10 ** (cable_loss_db / 10.0)
    return rf_power_w * gain_factor / loss_factor


def eirp_dbm(erp_w: float) -> float:
    """EIRP in dBm (ERP + 2.14 dB). Display only."""
    if erp_w <= 0:
        return float("-inf")
    return 10 * math.log10(erp_w * 1000.0) + 2.14


def _opt(args: list[str], flag: str, value) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            args.append(flag)
        return
    if isinstance(value, str) and value == "":
        return
    args.append(flag)
    args.append(str(value))


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------

def build_argv(
    params: dict,
    *,
    engine_exe: str,
    output_basename: str,
) -> list[str]:
    """Build the full argv (program included) for Signal-Server.

    ``params`` keys (all optional unless noted):
      tx_lat, tx_lon, tx_height, frequency_mhz, erp_w,
      rx_lat, rx_lon, rx_height, rx_gain_dbd, rx_threshold_dbm,
      antenna_basename, polarization ("vertical"|"horizontal"),
      azimuth_deg, downtilt_deg, downtilt_dir_deg,
      model_pm (int), reliability (int 1-99), context_pe (int 1-3),
      knife_edge (bool), climate_zone (int 1-7),
      clutter_file (path), ground_clutter (float), obstacles (list[str]),
      terrain_source ("sdf"|"lidar"), sdf_dir (path), lidar_file (path),
      engine ("Standard"|"HD"|"LIDAR"),
      resolution (int), radius (float), color_file (path), dbm_color (bool),
      units ("metric"|"imperial")
    """
    args: list[str] = [engine_exe]

    # --- Transmitter ---
    _opt(args, "-lat", params.get("tx_lat"))
    _opt(args, "-lon", params.get("tx_lon"))
    _opt(args, "-txh", params.get("tx_height"))
    _opt(args, "-f", params.get("frequency_mhz"))

    # --- ERP (Watts) ---
    erp = params.get("erp_w")
    if erp is None:
        erp = compute_erp(
            float(params.get("rf_power_w", 0) or 0),
            float(params.get("tx_gain_dbi", 0) or 0),
            float(params.get("cable_loss_db", 0) or 0),
        )
    if erp and erp > 0:
        args += ["-erp", str(erp)]

    # --- Antenna ---
    _opt(args, "-ant", params.get("antenna_basename"))
    if params.get("polarization") == "horizontal":
        args.append("-hp")
    _opt(args, "-rot", params.get("azimuth_deg"))
    _opt(args, "-dt", params.get("downtilt_deg"))
    _opt(args, "-dtdir", params.get("downtilt_dir_deg"))

    # --- Receiver ---
    # Passing the Rx LOCATION (-rla/-rlo) switches Signal-Server into
    # Path-Profile mode, which does NOT emit the area coverage .ppm this GUI
    # visualises. We therefore omit it for coverage plots (the Rx lat/lon is
    # only used as a map marker). Rx height/gain/threshold are still applied to
    # the area field calculation. Set ``path_profile`` to force a link analysis.
    if params.get("path_profile"):
        _opt(args, "-rla", params.get("rx_lat"))
        _opt(args, "-rlo", params.get("rx_lon"))
    _opt(args, "-rxh", params.get("rx_height"))
    _opt(args, "-rxg", params.get("rx_gain_dbd"))
    _opt(args, "-rt", params.get("rx_threshold_dbm"))

    # --- Model ---
    _opt(args, "-pm", params.get("model_pm"))
    # Drop flags the selected model does not consume (see MODEL_OPTION_STATES).
    # Sending them anyway is a silent no-op that pollutes the argv/log and
    # makes the run harder to reproduce; the GUI greys these out with a badge.
    states = option_states_for_model(params.get("model_pm"))
    pe = params.get("context_pe")
    if states["context"] == OPTION_ACTIVE:
        # Ericsson (-pm 9) maps its environment variant differently from the
        # other empirical models (ericsson.cc: 1=Rural, 2=Suburban, else=Urban).
        if params.get("model_pm") == 9 and pe:
            pe = {3: 1, 2: 2}.get(pe, 0)  # Rural->1, Suburban->2, Urban->0
        _opt(args, "-pe", pe)
    if states["diffraction"] == OPTION_ACTIVE and params.get("knife_edge"):
        args.append("-ked")
    if states["reliability"] == OPTION_ACTIVE:
        _opt(args, "-rel", params.get("reliability"))
    if states["climate"] == OPTION_ACTIVE:
        _opt(args, "-cl", params.get("climate_zone"))

    # Two-Ray Ground Reflection overlay mode (can be enabled for any propagation model)
    tworay = params.get("tworay") or params.get("two_rays") or params.get("use_two_rays")
    if tworay:
        mode = params.get("two_ray_mode", "interference").lower()
        if mode == "normal" or tworay == 1:
            args += ["-tworay", "1"]
        else:
            args += ["-tworay", "2"]

    # Processing parallelism (optimisation; engine defaults to 4 segments).
    # Always pass an explicit segment count so wide runs use all cores instead
    # of the engine's fixed 4-thread default.
    _opt(args, "-segments", params.get("plot_segments") or auto_segments())

    # --- Environment ---
    _opt(args, "-clt", params.get("clutter_file"))
    _opt(args, "-gc", params.get("ground_clutter"))
    for obs in params.get("obstacles") or []:
        if obs:
            args += ["-udt", obs]

    # --- Terrain source ---
    engine = params.get("engine", "Standard")
    if engine == "LIDAR":
        _opt(args, "-lid", params.get("lidar_file"))
    else:
        _opt(args, "-sdf", params.get("sdf_dir"))

    # --- Output ---
    # "Draft" quality halves the pixel resolution (4x fewer cells) for a fast
    # preview; "Final" keeps the user-selected resolution.
    res = int(params.get("resolution", 1200))
    if params.get("plot_quality") == "draft":
        res *= 2
    _opt(args, "-res", res)
    _opt(args, "-R", params.get("radius"))
    _opt(args, "-color", params.get("color_file"))
    # Radio Mobile parity: the raster TXT dump must be in dBm (like RM's own
    # export), which the engine only guarantees in -dbm mode. -dbm also switches
    # the PPM colour scale to dBm, keeping map and raster consistent.
    if params.get("dbm_color") or params.get("raster_txt"):
        args.append("-dbm")
    if params.get("raster_txt"):
        args.append("-rastertxt")
    if params.get("units") == "metric":
        args.append("-m")
    args += ["-o", output_basename]
    return args


def format_run_summary(params: dict, argv: list[str], engine_exe: str) -> list[str]:
    """Human-readable summary of the effective run parameters (one list entry
    per terminal line). Lets the user audit/replicate a run in other tools
    (e.g. Radio Mobile) with exactly the same inputs.
    """
    def model_label(pm) -> str:
        try:
            pm = int(pm)
        except (TypeError, ValueError):
            return str(pm)
        for label, val in MODELS:
            if val == pm:
                return f"{label} (-pm {pm})"
        return f"pm {pm}"

    ctx = params.get("context_pe")
    ctx_label = next((name for name, val in CONTEXTS if val == ctx), None)

    erp = params.get("erp_w")
    if erp is None:
        erp = compute_erp(
            float(params.get("rf_power_w", 0) or 0),
            float(params.get("tx_gain_dbi", 0) or 0),
            float(params.get("cable_loss_db", 0) or 0),
        )

    engine_name = os.path.basename(engine_exe or "signalserver")

    # DEM source actually used (post _prepare_dem: lidar_file/sdf_dir resolved).
    if params.get("_demnas"):
        dem = f"DEMNAS offline ({params.get('_demnas_mode', 'demnas')})"
        folder = params.get("demnas_dir")
        if folder:
            dem += f" folder={folder}"
        if params.get("lidar_file"):
            dem += f" -> {params['lidar_file']}"
        elif params.get("sdf_dir"):
            dem += f" -> {params['sdf_dir']}"
    elif params.get("lidar_file"):
        dem = f"LIDAR file {params['lidar_file']}"
    elif params.get("sdf_dir"):
        dem = f"SDF dir {params['sdf_dir']}"
    else:
        dem = "auto (Viewfinder SRTM download)"

    def amsl_txt(role: str) -> str:
        """'tinggi AGL x m (AMSL y m)' when ground elevation is known."""
        agl = params.get(f"{role}_height")
        elev = params.get(f"_{role}_ground_elev")
        if elev is None:
            return f"{agl} m AGL"
        try:
            return f"{agl} m AGL ({float(elev) + float(agl):.0f} m AMSL)"
        except (TypeError, ValueError):
            return f"{agl} m AGL"

    lines = [
        "[run] ============ Parameter efektif ============",
        f"[run] Engine    : {engine_name} ({engine_exe})",
        f"[run] Model     : {model_label(params.get('model_pm'))}"
        + (f" | context {ctx_label} (-pe {ctx})" if ctx_label else "")
        + f" | reliability {params.get('reliability', 50)}%",
        f"[run] Tx        : ({params.get('tx_lat')}, {params.get('tx_lon')})"
        f" tinggi {amsl_txt('tx')}",
        f"[run] Rx        : tinggi {amsl_txt('rx')}"
        f" | gain {params.get('rx_gain_dbd')} dBd"
        f" | threshold {params.get('rx_threshold_dbm')} dBm"
        + (f" ({dbm_to_dbuv(float(params.get('rx_threshold_dbm', 0)))}\u00b5V)"
           if params.get('rx_threshold_dbm') is not None else ""),
        f"[run] Tx Thr    : {params.get('tx_threshold_dbm')} dBm"
        + (f" ({dbm_to_dbuv(float(params.get('tx_threshold_dbm', 0)))}\u00b5V)"
           if params.get('tx_threshold_dbm') is not None else "")
        + " (metadata; -rt engine tetap pakai sisi Rx)",
        f"[run] ERP       : {erp:.2f} W"
        f" (power {params.get('rf_power_w')} W,"
        f" gain {params.get('tx_gain_dbi')} dBi,"
        f" loss {params.get('cable_loss_db')} dB)",
        f"[run] Frekuensi : {params.get('frequency_mhz')} MHz",
        f"[run] DEM       : {dem}",
        f"[run] Output    : res {params.get('resolution')}"
        f" | radius {params.get('radius')} km"
        f" | units {params.get('units', 'metric')}"
        f" | color {params.get('color_file') or '(engine default)'}"
        + (" | -dbm" if params.get("dbm_color") else ""),
        f"[run] Proses    : quality={params.get('plot_quality', 'final')}"
        f" | segments={params.get('plot_segments') or auto_segments()}",
    ]
    if params.get("antenna_basename"):
        lines.append(
            f"[run] Antena    : {params['antenna_basename']}"
            f" | pol {params.get('polarization')}"
            f" | azimuth {params.get('azimuth_deg')}"
            f" | downtilt {params.get('downtilt_deg')}")
    lines.append("[run] Argv      : " + " ".join(argv))
    # --- Smart gating notes: flag was dropped because the model ignores it ---
    states = option_states_for_model(params.get("model_pm"))
    mname = model_name(params.get("model_pm"))
    if states["diffraction"] != OPTION_ACTIVE:
        if states["diffraction"] == OPTION_BUILTIN:
            lines.append(f"[run] catatan: -ked dilewati (difraksi sudah "
                         f"built-in pada {mname})")
        else:
            lines.append(f"[run] catatan: -ked tidak berlaku untuk {mname}")
    for opt, flag, key in (("context", "-pe", "context_pe"),
                            ("reliability", "-rel", "reliability"),
                            ("climate", "-cl", "climate_zone")):
        if states[opt] == OPTION_NA and params.get(key) is not None:
            lines.append(f"[run] catatan: {flag} dilewati (tidak dipakai "
                         f"oleh {mname})")
    if params.get("plot_segments"):
        lines.append(f"[run] catatan: -segments {params['plot_segments']} "
                     "(paralelisme processing)")
    lines.append("[run] ===========================================")
    return lines


def iter_obstacles(text: str) -> Iterable[str]:
    """Parse a multi-line obstacles text into 'lat,lon,height' items.

    One item per non-empty line.
    """
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield line
