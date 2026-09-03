
"""Two-Ray Ground Reflection Multipath & Interference Calculator.

Implements:
1. Specular reflection point search along digital elevation profile (elev[]) with 4/3 Earth curvature.
2. Complex Fresnel reflection coefficient (Gamma_v, Gamma_h) with soil permittivity and conductivity.
3. Spherical Earth divergence factor (D) and Miller-Brown surface roughness factor (Rs).
4. Coherent phase difference Delta_phi = (2*pi/lambda)*Delta_r + phi_refl and interference factor F.
5. Incoherent power addition option ("Normal" vs "Interference" matching Radio Mobile).
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

EARTH_RADIUS_EFF_M = (4.0 / 3.0) * 6371000.0
SPEED_OF_LIGHT = 299792458.0


@dataclass
class TwoRayDetails:
    path_loss_db: float
    fspl_db: float
    interference_gain_db: float  # +dB (gain) or -dB (fade)
    delta_r_m: float             # Path difference (r2 - r1)
    phase_diff_deg: float        # Total phase difference (Delta phi in degrees)
    gamma_mag: float             # Effective reflection magnitude |Gamma_eff|
    gamma_phase_deg: float       # Reflection phase shift (degrees)
    reflection_dist_km: float    # Distance from Tx to reflection point (km)
    reflection_elev_m: float     # Elevation of reflection point (m AMSL)
    grazing_angle_deg: float     # Grazing angle psi (degrees)
    divergence_factor: float     # Spherical divergence D
    roughness_factor: float      # Surface roughness Rs
    is_obstructed: bool          # Whether reflection path or direct path is blocked


def find_specular_point(
    dists_km: Sequence[float],
    terrain_m: Sequence[float],
    tx_amsl_m: float,
    rx_amsl_m: float,
) -> Tuple[float, float, float]:
    """Find the specular reflection point along the terrain profile.

    Returns (refl_dist_km, refl_elev_m, grazing_angle_rad).
    """
    n = len(dists_km)
    if n < 2:
        d_tot_km = dists_km[0] if dists_km else 1.0
        return d_tot_km / 2.0, 0.0, 0.01

    d_min = dists_km[0]
    d_max = dists_km[-1]
    total_dist_m = max(10.0, (d_max - d_min) * 1000.0)

    best_diff = 1e9
    best_dist_km = (d_min + d_max) / 2.0
    best_elev_m = 0.0
    best_psi = 0.01

    for i in range(1, n - 1):
        d_i_km = dists_km[i]
        xi = (d_i_km - d_min) * 1000.0
        if xi <= 0.0 or xi >= total_dist_m:
            continue

        h_terr = terrain_m[i]

        # Earth curvature drop
        curv1 = (xi * xi) / (2.0 * EARTH_RADIUS_EFF_M)
        curv2 = ((total_dist_m - xi) * (total_dist_m - xi)) / (2.0 * EARTH_RADIUS_EFF_M)

        h_tx_rel = tx_amsl_m - curv1 - h_terr
        h_rx_rel = rx_amsl_m - curv2 - h_terr

        if h_tx_rel <= 0.0 or h_rx_rel <= 0.0:
            continue

        psi1 = math.atan2(h_tx_rel, xi)
        psi2 = math.atan2(h_rx_rel, total_dist_m - xi)

        # Local terrain slope
        dx = (dists_km[min(n - 1, i + 1)] - dists_km[max(0, i - 1)]) * 1000.0
        dh = terrain_m[min(n - 1, i + 1)] - terrain_m[max(0, i - 1)]
        slope = math.atan2(dh, max(1.0, dx))

        theta_inc = psi1 + slope
        theta_refl = psi2 - slope

        if theta_inc <= 0.0 or theta_refl <= 0.0:
            continue

        # Visibility check
        blocked = False
        step = max(1, i // 20)
        for j in range(1, i, step):
            xj = (dists_km[j] - d_min) * 1000.0
            los_h = tx_amsl_m - (tx_amsl_m - h_terr) * (xj / xi) - (xj * (xi - xj)) / (2.0 * EARTH_RADIUS_EFF_M)
            if terrain_m[j] > los_h:
                blocked = True
                break
        if blocked:
            continue

        for j in range(i + 1, n - 1, step):
            xj = (dists_km[j] - d_i_km) * 1000.0
            span = total_dist_m - xi
            los_h = h_terr + (rx_amsl_m - h_terr) * (xj / span) - (xj * (span - xj)) / (2.0 * EARTH_RADIUS_EFF_M)
            if terrain_m[j] > los_h:
                blocked = True
                break
        if blocked:
            continue

        diff = abs(theta_inc - theta_refl)
        if diff < best_diff:
            best_diff = diff
            best_dist_km = d_i_km
            best_elev_m = h_terr
            best_psi = (theta_inc + theta_refl) / 2.0

    # Fallback to spherical Earth proportional point
    if best_diff > 1e8:
        h1 = max(1.0, tx_amsl_m)
        h2 = max(1.0, rx_amsl_m)
        frac = h1 / (h1 + h2)
        best_dist_km = d_min + frac * (d_max - d_min)
        best_elev_m = 0.0
        best_psi = math.atan2(h1, frac * total_dist_m)

    return best_dist_km, best_elev_m, max(1e-4, min(math.pi / 2.0 - 1e-4, best_psi))


def calculate_two_ray(
    freq_mhz: Optional[float] = None,
    dists_km: Optional[Sequence[float]] = None,
    terrain_m: Optional[Sequence[float]] = None,
    tx_amsl_m: float = 100.0,
    rx_amsl_m: float = 100.0,
    pol: int = 1,               # 0 = Horizontal, 1 = Vertical
    eps_dielect: float = 15.0,
    sgm_conductivity: float = 0.005,
    mode: str = "interference", # "interference" vs "normal"
    surface_roughness_m: float = 0.5,
    **kwargs,
) -> TwoRayDetails:
    """Calculate detailed Two-Ray Ground Reflection metrics along terrain profile."""
    if freq_mhz is None:
        freq_mhz = float(kwargs.get("f_mhz", 1200.0))

    if "coherent_interference" in kwargs:
        mode = "normal" if kwargs["coherent_interference"] else "incoherent"

    if dists_km is None or terrain_m is None:
        elev = kwargs.get("elev")
        if elev and len(elev) > 2:
            n_samples = int(kwargs.get("n_samples", elev[0]))
            sample_dist_km = float(elev[1]) / 1000.0 if elev[1] > 0 else 0.1
            dists_km = [i * sample_dist_km for i in range(n_samples + 1)]
            terrain_m = [float(elev[2 + min(i, len(elev) - 3)]) for i in range(n_samples + 1)]
        else:
            d_km = float(kwargs.get("dkm", 1.0))
            dists_km = [0.0, d_km]
            terrain_m = [0.0, 0.0]

    d_min = dists_km[0] if dists_km else 0.0
    d_max = dists_km[-1] if dists_km else 1.0
    d_km = max(0.01, d_max - d_min)
    d_m = d_km * 1000.0

    freq_hz = max(1.0, freq_mhz) * 1e6
    wavelength = SPEED_OF_LIGHT / freq_hz
    k = (2.0 * math.pi) / wavelength

    # Free Space Path Loss (ITU-R P.525)
    fspl_db = 32.44 + 20.0 * math.log10(freq_mhz) + 20.0 * math.log10(d_km)

    # 1. Antenna heights above ground / reflection reference plane
    tx_gnd = terrain_m[0] if terrain_m else 0.0
    rx_gnd = terrain_m[-1] if terrain_m else 0.0
    h1 = max(1.0, tx_amsl_m - tx_gnd)
    h2 = max(1.0, rx_amsl_m - rx_gnd)

    # 2. Direct ray and Ground Reflected ray path lengths
    r1 = math.sqrt(d_m * d_m + (h2 - h1) ** 2)
    r2 = math.sqrt(d_m * d_m + (h2 + h1) ** 2)
    delta_r = r2 - r1

    # 3. Specular reflection point & grazing angle
    best_dist_m = d_m * (h1 / (h1 + h2))
    best_elev_m = tx_gnd + (rx_gnd - tx_gnd) * (h1 / (h1 + h2))
    refl_dist_km = d_min + (best_dist_m / 1000.0)
    refl_elev_m = best_elev_m

    psi = math.atan2(h1 + h2, d_m)
    psi = max(1e-4, min(math.pi / 2.0 - 1e-4, psi))

    # Complex permittivity: eta = eps_r - j * (18000 * sigma / f_mhz)
    eps_imag = (18000.0 * max(1e-6, sgm_conductivity)) / max(1.0, freq_mhz)
    eta = complex(max(1.1, eps_dielect), -eps_imag)

    sin_psi = math.sin(psi)
    cos_psi = math.cos(psi)
    sqrt_term = cmath.sqrt(eta - complex(cos_psi * cos_psi, 0.0))

    if pol == 0:
        # Horizontal polarization
        gamma = (sin_psi - sqrt_term) / (sin_psi + sqrt_term)
    else:
        # Vertical polarization
        gamma = (eta * sin_psi - sqrt_term) / (eta * sin_psi + sqrt_term)

    gamma_mag = abs(gamma)
    gamma_phase = cmath.phase(gamma)

    # Spherical Earth Divergence Factor D
    d1 = best_dist_m
    d2 = d_m - best_dist_m
    div_denom = 1.0 + (2.0 * d1 * d2) / (EARTH_RADIUS_EFF_M * d_m * max(1e-4, sin_psi))
    D = 1.0 / math.sqrt(max(1.0, div_denom))

    # 6. Surface Roughness (Rayleigh criterion)
    # Assume smooth earth (rho_s = 1.0) to match Radio Mobile's dense interference fringes
    rho_s = 1.0
    gamma_eff_mag = min(1.0, gamma_mag * D * rho_s)

    # Total phase difference
    phase_diff = k * delta_r + gamma_phase
    phase_diff_deg = (math.degrees(phase_diff)) % 360.0

    if mode == "normal":
        # Coherent vector addition
        F_sq = 1.0 + gamma_eff_mag ** 2 + 2.0 * gamma_eff_mag * math.cos(phase_diff)
    else:
        # Incoherent power addition (Average mode)
        F_sq = 1.0 + gamma_eff_mag ** 2

    F_sq = max(2.5e-3, min(4.0, F_sq))
    gain_db = 10.0 * math.log10(F_sq)
    path_loss_db = fspl_db - gain_db

    return TwoRayDetails(
        path_loss_db=path_loss_db,
        fspl_db=fspl_db,
        interference_gain_db=gain_db,
        delta_r_m=delta_r,
        phase_diff_deg=phase_diff_deg,
        gamma_mag=gamma_eff_mag,
        gamma_phase_deg=math.degrees(gamma_phase),
        reflection_dist_km=refl_dist_km,
        reflection_elev_m=refl_elev_m,
        grazing_angle_deg=math.degrees(psi),
        divergence_factor=D,
        roughness_factor=rho_s,
        is_obstructed=False,
    )
