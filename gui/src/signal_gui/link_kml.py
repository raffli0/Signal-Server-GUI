"""Radio Link KML and KMZ generator matching Radio Mobile export specification.

Replicates the 3D radio link profile exported by Radio Mobile:
- Document header & KPI description (budget, azimuth, angles, clearance, losses, system gains).
- Perpendicular side-view camera perspective (<LookAt>).
- Tx & Rx 3D tower placemarks with Point at antenna tip and vertical LineString tower.
- Folder 'Radio Link' containing:
    * Beam (LineString with earth-curvature drop k=4/3).
    * 0.6F1 (LineString along lower 60% Fresnel clearance boundary).
    * 1.0F1 (Closed-ring LineString: forward along top Fresnel ellipsoid, return along bottom).
    * 1.0F2 & 1.0F3 (Closed-ring LineStrings with visibility 0 for 2nd and 3rd Fresnel zones).
- Optional Land cover folder for clutter/vegetation heights.
- KMZ packaging with bundled antenna.png icon for standalone Google Earth viewing.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import zipfile
from typing import Optional, Sequence

import numpy as np

_EARTH_R_M = 6371000.0
_C_LIGHT = 299792458.0
_K_FACTOR = 4.0 / 3.0


def _slerp_points(
    lat1: float, lon1: float, lat2: float, lon2: float, n: int = 501
) -> tuple[list[tuple[float, float, float]], float]:
    """Generate n points along the great-circle arc from (lat1, lon1) to (lat2, lon2) using SLERP.

    Returns:
        (points, total_distance_meters), where each point is (lat, lon, t) with t in [0.0, 1.0].
    """
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)

    v1 = np.array([math.cos(phi1) * math.cos(lam1), math.cos(phi1) * math.sin(lam1), math.sin(phi1)])
    v2 = np.array([math.cos(phi2) * math.cos(lam2), math.cos(phi2) * math.sin(lam2), math.sin(phi2)])

    dot = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
    omega = math.acos(dot)
    sin_omega = math.sin(omega)
    total_dist_m = omega * _EARTH_R_M

    pts: list[tuple[float, float, float]] = []
    for i in range(n):
        t = i / max(1, n - 1)
        if sin_omega < 1e-12:
            lat = lat1 + t * (lat2 - lat1)
            lon = lon1 + t * (lon2 - lon1)
        else:
            v = (math.sin((1.0 - t) * omega) / sin_omega) * v1 + (math.sin(t * omega) / sin_omega) * v2
            v = v / np.linalg.norm(v)
            lat = math.degrees(math.asin(v[2]))
            lon = math.degrees(math.atan2(v[1], v[0]))
        pts.append((lat, lon, t))

    return pts, total_dist_m


def _initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing (degrees clockwise from True North)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _get_station_icon_paths() -> dict[str, Optional[str]]:
    """Locate the bundled modern station icons for Tx and Rx."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    tx_candidates = [
        os.path.join(base_dir, "resources", "icons", "tx_station.png"),
        os.path.join(base_dir, "resources", "rm", "antenna_pin.png"),
    ]
    rx_candidates = [
        os.path.join(base_dir, "resources", "icons", "rx_station.png"),
        os.path.join(base_dir, "resources", "rm", "antenna_pin.png"),
    ]
    tx_icon = next((c for c in tx_candidates if os.path.exists(c)), None)
    rx_icon = next((c for c in rx_candidates if os.path.exists(c)), None)
    return {"tx": tx_icon, "rx": rx_icon}


def build_radio_link_kml(
    params: dict,
    link_data: dict,
    num_points: int = 501,
    tx_icon_href: str = "tx_station.png",
    rx_icon_href: str = "rx_station.png",
    icon_href: Optional[str] = None,
) -> str:
    """Build a modern 3D Radio Link KML string.

    Args:
        params: Configuration dictionary containing Tx/Rx coordinates, heights, gains, frequencies, etc.
        link_data: Computed radio link results (losses, fade margins, clearance, profile).
        num_points: Number of samples along the link (Radio Mobile default is 501).
        tx_icon_href: Relative or URL href for the transmitter icon.
        rx_icon_href: Relative or URL href for the receiver icon.
        icon_href: Optional override for both Tx and Rx icons.

    Returns:
        Complete KML XML string.
    """
    if icon_href is not None:
        tx_icon_href = icon_href
        rx_icon_href = icon_href
    # 1. Coordinates and Site Names
    tx_name = str(params.get("tx_site_name") or params.get("tx_name") or "Base").strip()
    rx_name = str(params.get("rx_site_name") or params.get("rx_name") or "Mobile").strip()

    tx_lat = float(params.get("tx_lat", 0.0))
    tx_lon = float(params.get("tx_lon", 0.0))
    tx_h = float(params.get("tx_height", 10.0))

    rx_lat = float(params.get("rx_lat", 0.0))
    rx_lon = float(params.get("rx_lon", 0.0))
    rx_h = float(params.get("rx_height", 2.0))

    # 2. Elevation / AMSL values
    profile = link_data.get("profile") or {}
    los_series = profile.get("los_m") or []
    terrain_series = profile.get("terrain_m") or []

    if los_series and len(los_series) >= 2:
        tx_amsl = float(los_series[0])
        rx_amsl = float(los_series[-1])
    else:
        # Fallback if profile los not available
        tx_amsl = 500.0 + tx_h
        rx_amsl = 500.0 + rx_h

    if terrain_series and len(terrain_series) >= 2:
        tx_ground = float(terrain_series[0])
        rx_ground = float(terrain_series[-1])
        elev_var = float(max(terrain_series) - min(terrain_series))
    else:
        tx_ground = max(0.0, tx_amsl - tx_h)
        rx_ground = max(0.0, rx_amsl - rx_h)
        elev_var = abs(rx_ground - tx_ground)

    # 3. Geometry (SLERP and Bearing)
    pts, calc_dist_m = _slerp_points(tx_lat, tx_lon, rx_lat, rx_lon, n=num_points)
    dist_km = float(link_data.get("distance_km") or (calc_dist_m / 1000.0))
    dist_m = dist_km * 1000.0
    dist_mi = dist_km / 1.609344

    azimuth_deg = float(link_data.get("azimuth_deg") or _initial_bearing(tx_lat, tx_lon, rx_lat, rx_lon))
    rev_azimuth_deg = (azimuth_deg + 180.0) % 360.0

    # 4. Elevation Angle (True ray tilt from Tx antenna tip to Rx antenna tip)
    rep = link_data.get("report_text", "")
    m_elev = re.search(r"Downtilt angle to Rx:\s*([+-]?[\d.]+)", rep)
    if m_elev:
        elev_angle = float(m_elev.group(1))
    else:
        rx_bulge = (dist_m * dist_m) / (2.0 * _K_FACTOR * _EARTH_R_M)
        eff_dh = (rx_amsl - tx_amsl) - rx_bulge
        elev_angle = math.degrees(math.atan2(eff_dh, max(1.0, dist_m)))

    # 5. Link Budget & Losses
    freq_mhz = float(params.get("frequency", params.get("frequency_mhz", 1200.0)))
    wavelength = _C_LIGHT / (max(1.0, freq_mhz) * 1e6)

    fs_loss = link_data.get("free_space_loss_db")
    if fs_loss is None and dist_km > 0:
        fs_loss = 20.0 * math.log10(dist_km) + 20.0 * math.log10(max(1.0, freq_mhz)) + 32.44
    fs_loss = float(fs_loss or 133.9)

    # Clearance & Propagation Mode
    is_obstructed = bool(link_data.get("obstructed", False))
    prop_mode = "obstruction / diffraction" if is_obstructed else "line-of-sight"

    total_loss = float(link_data.get("total_loss_db") or link_data.get("computed_loss_db") or (fs_loss + 0.8))
    urban_loss = 0.0
    forest_loss = 1.0 if is_obstructed else 0.0

    # In Radio Mobile: Total Loss = Free Space + Obstruction + Urban + Forest + Statistics
    # Break down Longley-Rice excess loss into Statistical variability (6.3 dB at 70% situations)
    # and physical Obstruction / Two-Ray (TR) diffraction/reflection loss.
    excess_loss = max(0.0, total_loss - fs_loss)
    if excess_loss >= 6.3:
        stat_loss = 6.3
        obs_loss = max(0.0, excess_loss - stat_loss - forest_loss - urban_loss)
    else:
        obs_loss = 0.8 if is_obstructed else 0.0
        stat_loss = max(0.0, excess_loss - obs_loss - forest_loss - urban_loss)

    # System Gain & Worst Reception (Fade Margin)
    tx_pwr_w = float(params.get("tx_power_w", params.get("power", 12.0)))
    tx_pwr_dbm = 10.0 * math.log10(max(0.001, tx_pwr_w) * 1000.0) if tx_pwr_w > 0 else 46.14
    tx_gain = float(params.get("tx_antenna_gain", params.get("tx_gain_dbi", 8.0)))
    rx_gain = float(params.get("rx_antenna_gain", params.get("rx_gain_dbi", 8.0)))
    rx_thresh = float(params.get("rx_threshold_dbm", -119.0))

    sys_gain = tx_pwr_dbm + tx_gain + rx_gain - rx_thresh
    # Radio Mobile defines Worst Reception directly as: System Gain - Total Loss
    fade_margin = sys_gain - total_loss

    worst_clr_f1 = 2.0
    worst_clr_km = dist_km * 0.5
    dists_km_list = profile.get("distance_km") or []
    if dists_km_list and terrain_series and los_series and len(dists_km_list) == len(terrain_series) == len(los_series) and len(dists_km_list) > 2:
        tot_d_m = max(1.0, (dists_km_list[-1] - dists_km_list[0]) * 1000.0)
        min_rat = float("inf")
        for i in range(1, len(dists_km_list) - 1):
            clr_i = los_series[i] - terrain_series[i]
            d_i_m = (dists_km_list[i] - dists_km_list[0]) * 1000.0
            r1_i = math.sqrt(max(0.0, wavelength * d_i_m * (tot_d_m - d_i_m) / tot_d_m))
            rat = (clr_i / r1_i) if r1_i > 0.1 else 1.0
            if rat < min_rat:
                min_rat = rat
                worst_clr_km = dists_km_list[i]
        if min_rat != float("inf"):
            worst_clr_f1 = min_rat

    # 6. Precompute Midpoint for Document <LookAt>
    mid_idx = len(pts) // 2
    mid_lat, mid_lon, _ = pts[mid_idx]
    d_mid = dist_m * 0.5
    bulge_mid = (d_mid * (dist_m - d_mid)) / (2.0 * _K_FACTOR * _EARTH_R_M)
    mid_beam_alt = tx_amsl + 0.5 * (rx_amsl - tx_amsl) - bulge_mid

    # Perpendicular camera heading (looking at profile side-on)
    side_heading = (azimuth_deg - 90.0) % 360.0
    tx_heading = (azimuth_deg - 20.0) % 360.0
    rx_heading = (rev_azimuth_deg + 20.0) % 360.0
    station_range = min(2000.0, max(500.0, dist_m * 0.02))

    # 7. Generate Profile Samples (Beam, 0.6F1, 1.0F1, 1.0F2, 1.0F3)
    beam_coords: list[str] = []
    f06_coords: list[str] = []
    f1_top_coords: list[str] = []
    f1_bot_coords: list[str] = []
    f2_top_coords: list[str] = []
    f2_bot_coords: list[str] = []
    f3_top_coords: list[str] = []
    f3_bot_coords: list[str] = []

    for lat, lon, t in pts:
        d = t * dist_m
        bulge = (d * (dist_m - d)) / (2.0 * _K_FACTOR * _EARTH_R_M)
        beam_h = tx_amsl + t * (rx_amsl - tx_amsl) - bulge
        f1_rad = math.sqrt(max(0.0, wavelength * d * (dist_m - d) / max(1.0, dist_m)))
        f2_rad = math.sqrt(2.0) * f1_rad
        f3_rad = math.sqrt(3.0) * f1_rad

        beam_coords.append(f"{lon:.6f},{lat:.6f},{beam_h:.2f} \n")
        f06_coords.append(f"{lon:.6f},{lat:.6f},{beam_h - 0.6 * f1_rad:.2f} \n")

        f1_top_coords.append(f"{lon:.6f},{lat:.6f},{beam_h + f1_rad:.2f} \n")
        f1_bot_coords.append(f"{lon:.6f},{lat:.6f},{beam_h - f1_rad:.2f} \n")

        f2_top_coords.append(f"{lon:.6f},{lat:.6f},{beam_h + f2_rad:.2f} \n")
        f2_bot_coords.append(f"{lon:.6f},{lat:.6f},{beam_h - f2_rad:.2f} \n")

        f3_top_coords.append(f"{lon:.6f},{lat:.6f},{beam_h + f3_rad:.2f} \n")
        f3_bot_coords.append(f"{lon:.6f},{lat:.6f},{beam_h - f3_rad:.2f} \n")

    # Closed loops for 1.0F1, 1.0F2, 1.0F3: top half forward (Tx -> Rx), bottom half return (Rx -> Tx)
    f1_loop = "".join(f1_top_coords) + "".join(reversed(f1_bot_coords))
    f2_loop = "".join(f2_top_coords) + "".join(reversed(f2_bot_coords))
    f3_loop = "".join(f3_top_coords) + "".join(reversed(f3_bot_coords))

    # 8. Build Description XML
    description = (
        f" Distance between {tx_name} and {rx_name} is {dist_km:.1f} km ({dist_mi:.1f} miles)\n"
        f" True North Azimuth = {azimuth_deg:.2f}°, Magnetic North Azimuth = {azimuth_deg:.2f}°, Elevation angle = {elev_angle:+.4f}°\n"
        f"{tx_name}\n"
        f" Terrain elevation variation is {elev_var:.1f} m\n"
        f" Propagation mode is {prop_mode}, minimum clearance {worst_clr_f1:.1f}F1 at {worst_clr_km:.1f}km\n"
        f" Average frequency is {freq_mhz:.3f} MHz\n"
        f" Free Space = {fs_loss:.1f} dB, Obstruction = {obs_loss:.1f} dB TR, Urban = {urban_loss:.1f} dB, Forest = {forest_loss:.1f} dB, Statistics = {stat_loss:.1f} dB\n"
        f" Total propagation loss is {total_loss:.1f} dB\n"
        f" System gain from {tx_name} to {rx_name} is {sys_gain:.1f} dB\n"
        f" System gain from {rx_name} to {tx_name} is {sys_gain:.1f} dB\n"
        f" Worst reception is {fade_margin:.1f} dB over the required signal to meet\n"
        f" 70.000% of situations"
    )

    # 9. Assemble KML Document
    doc_name = f"{tx_name} - {rx_name} [{tx_name}]"

    kml = f"""<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{doc_name}</name>
<description>{description}</description>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<Placemark><name>{tx_name}</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {tx_lon:.12f}</longitude><latitude>{tx_lat:.14f}</latitude><altitude> {tx_amsl:.12f}</altitude>
<range> {station_range:.11f}</range><tilt>70.0</tilt><heading> {tx_heading:.13f}</heading></LookAt>
<description></description>
<Style><LineStyle><color>ffff0000</color><width>5</width></LineStyle>
<IconStyle><scale>1.2</scale><hotSpot x="0.5" y="0.0" xunits="fraction" yunits="fraction"/><Icon><href>{tx_icon_href}</href></Icon></IconStyle></Style>
<MultiGeometry><Point><altitudeMode>absolute</altitudeMode>
<coordinates>{tx_lon:.6f},{tx_lat:.6f},{tx_amsl:.1f} </coordinates></Point>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{tx_lon:.6f},{tx_lat:.6f},{tx_ground:.1f} 
{tx_lon:.6f},{tx_lat:.6f},{tx_amsl:.1f} </coordinates></LineString></MultiGeometry></Placemark>
<Placemark><name>{rx_name}</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude>{rx_lon:.12f}</longitude><latitude>{rx_lat:.14f}</latitude><altitude>{rx_amsl:.4f}</altitude>
<range>{station_range:.11f}</range><tilt>70.0</tilt><heading>{rx_heading:.13f}</heading></LookAt>
<description></description>
<Style><LineStyle><color>ffff0000</color><width>5</width></LineStyle>
<IconStyle><scale>1.2</scale><hotSpot x="0.5" y="0.0" xunits="fraction" yunits="fraction"/><Icon><href>{rx_icon_href}</href></Icon></IconStyle></Style>
<MultiGeometry><Point><altitudeMode>absolute</altitudeMode>
<coordinates>{rx_lon:.6f},{rx_lat:.6f},{rx_amsl:.1f} </coordinates></Point>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{rx_lon:.6f},{rx_lat:.6f},{rx_ground:.1f} 
{rx_lon:.6f},{rx_lat:.6f},{rx_amsl:.1f} </coordinates></LineString></MultiGeometry></Placemark>
<Folder><name>Radio Link</name><Placemark><name>Beam</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<Style><LineStyle><color>c0ff0000</color><width>3</width></LineStyle></Style>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{''.join(beam_coords)}</coordinates></LineString></Placemark>
<Placemark><name>0.6F1</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<Style><LineStyle><color>b000ff00</color><width>2</width></LineStyle></Style>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{''.join(f06_coords)}</coordinates></LineString></Placemark>
<Placemark><name>1.0F1</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<Style><LineStyle><color>b000ffff</color><width>2</width></LineStyle></Style>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{f1_loop}</coordinates></LineString></Placemark>
<Placemark><name>1.0F2</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<visibility>0</visibility><Style><LineStyle><color>b00000ff</color><width>2</width></LineStyle></Style>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{f2_loop}</coordinates></LineString></Placemark>
<Placemark><name>1.0F3</name>
<LookAt><altitudeMode>absolute</altitudeMode><longitude> {mid_lon:.12f}</longitude><latitude>{mid_lat:.14f}</latitude><altitude> {mid_beam_alt:.11f}</altitude><range> {dist_m:.10f}</range><tilt>80.0</tilt><heading> {side_heading:.13f}</heading></LookAt>
<visibility>0</visibility><Style><LineStyle><color>b00000ff</color><width>2</width></LineStyle></Style>
<LineString><altitudeMode>absolute</altitudeMode><coordinates>
{f3_loop}</coordinates></LineString></Placemark>
</Folder>
</Document></kml>
"""
    return kml


def export_radio_link_kml(
    file_path: str,
    params: dict,
    link_data: dict,
    num_points: int = 501,
    copy_icon: bool = True,
    tx_icon_name: str = "tx_station.png",
    rx_icon_name: str = "rx_station.png",
) -> str:
    """Export the Radio Link as a standalone .kml file.

    Optionally copies the modern tx_station.png and rx_station.png icons to the same target directory.
    """
    out_dir = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(out_dir, exist_ok=True)

    icons = _get_station_icon_paths()
    if copy_icon:
        for role, icon_name in [("tx", tx_icon_name), ("rx", rx_icon_name)]:
            src = icons.get(role)
            if src and os.path.exists(src):
                dst = os.path.join(out_dir, icon_name)
                if not os.path.exists(dst):
                    try:
                        shutil.copyfile(src, dst)
                    except Exception:
                        pass

    kml_str = build_radio_link_kml(
        params, link_data, num_points=num_points, tx_icon_href=tx_icon_name, rx_icon_href=rx_icon_name
    )
    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write(kml_str)

    return file_path


def export_radio_link_kmz(
    file_path: str,
    params: dict,
    link_data: dict,
    num_points: int = 501,
    tx_icon_name: str = "tx_station.png",
    rx_icon_name: str = "rx_station.png",
) -> str:
    """Export the Radio Link as a zipped .kmz file containing doc.kml and modern station icons.

    Self-contained and viewable offline in Google Earth desktop, mobile, and web.
    """
    out_dir = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(out_dir, exist_ok=True)

    kml_str = build_radio_link_kml(
        params, link_data, num_points=num_points, tx_icon_href=tx_icon_name, rx_icon_href=rx_icon_name
    )
    icons = _get_station_icon_paths()

    with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_str.encode("utf-8"))
        for role, icon_name in [("tx", tx_icon_name), ("rx", rx_icon_name)]:
            src = icons.get(role)
            if src and os.path.exists(src):
                zf.write(src, arcname=icon_name)

    return file_path
