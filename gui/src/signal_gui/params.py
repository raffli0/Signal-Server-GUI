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
    # Ericsson (-pm 9) maps its environment variant differently from the other
    # empirical models (ericsson.cc: 1=Rural, 2=Suburban, anything else=Urban),
    # so translate the GUI's Urban/Suburban/Rural (1/2/3) accordingly.
    pe = params.get("context_pe")
    if params.get("model_pm") == 9 and pe:
        pe = {3: 1, 2: 2}.get(pe, 0)  # Rural->1, Suburban->2, Urban->0
    _opt(args, "-pe", pe)
    if params.get("knife_edge"):
        args.append("-ked")
    _opt(args, "-rel", params.get("reliability"))
    _opt(args, "-cl", params.get("climate_zone"))

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
    _opt(args, "-res", params.get("resolution"))
    _opt(args, "-R", params.get("radius"))
    _opt(args, "-color", params.get("color_file"))
    if params.get("dbm_color"):
        args.append("-dbm")
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

    lines = [
        "[run] ============ Parameter efektif ============",
        f"[run] Engine    : {engine_name} ({engine_exe})",
        f"[run] Model     : {model_label(params.get('model_pm'))}"
        + (f" | context {ctx_label} (-pe {ctx})" if ctx_label else "")
        + f" | reliability {params.get('reliability', 50)}%",
        f"[run] Tx        : ({params.get('tx_lat')}, {params.get('tx_lon')})"
        f" tinggi {params.get('tx_height')} m AGL",
        f"[run] Rx        : tinggi {params.get('rx_height')} m"
        f" | gain {params.get('rx_gain_dbd')} dBd"
        f" | threshold {params.get('rx_threshold_dbm')} dBm",
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
    ]
    if params.get("antenna_basename"):
        lines.append(
            f"[run] Antena    : {params['antenna_basename']}"
            f" | pol {params.get('polarization')}"
            f" | azimuth {params.get('azimuth_deg')}"
            f" | downtilt {params.get('downtilt_deg')}")
    lines.append("[run] Argv      : " + " ".join(argv))
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
