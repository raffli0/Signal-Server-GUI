import re

py_file = "gui/src/signal_gui/two_ray.py"
with open(py_file, "r") as f:
    py_code = f.read()

new_py_code = """import math
from typing import Tuple

EARTH_RADIUS_EFF_M = (4.0 / 3.0) * 6371000.0
SPEED_OF_LIGHT = 299792458.0

class TwoRayDetails:
    def __init__(self):
        self.fspl_db = 0.0
        self.reflection_dist_km = 0.0
        self.reflection_elev_m = 0.0
        self.delta_r_m = 0.0
        self.grazing_angle_deg = 0.0
        self.gamma_mag = 0.0
        self.gamma_phase_deg = 0.0
        self.phase_diff_deg = 0.0
        self.path_loss_db = 0.0

def calculate_two_ray(
    f_mhz: float,
    tx_amsl_m: float,
    rx_amsl_m: float,
    dkm: float,
    pol: int,
    eps_dielect: float,
    sgm_conductivity: float,
    elev: list,
    n_samples: int,
    coherent_interference: bool,
    surface_roughness_m: float
) -> TwoRayDetails:
    res = TwoRayDetails()
    d_m = max(10.0, dkm * 1000.0)
    f_hz = max(1.0, f_mhz) * 1e6
    lambda_m = SPEED_OF_LIGHT / f_hz
    k = (2.0 * math.pi) / lambda_m

    res.fspl_db = 32.44 + 20 * math.log10(f_mhz) + 20 * math.log10(dkm)

    best_diff = 1e9
    best_i = -1
    best_h1 = 0
    best_h2 = 0
    best_d1 = 0
    best_d2 = 0
    best_h_terr = 0
    
    sample_dist = elev[1] if (elev and n_samples > 0) else (d_m / 2.0)

    if elev and n_samples > 1:
        for i in range(1, n_samples):
            d1 = i * sample_dist
            d2 = d_m - d1
            h_terr = elev[2 + i]
            h1_i = tx_amsl_m - h_terr
            h2_i = rx_amsl_m - h_terr
            if h1_i <= 0 or h2_i <= 0:
                continue
            
            theta1 = math.atan2(h1_i, d1)
            theta2 = math.atan2(h2_i, d2)
            diff = abs(theta1 - theta2)
            if diff < best_diff:
                best_diff = diff
                best_i = i
                best_h1 = h1_i
                best_h2 = h2_i
                best_d1 = d1
                best_d2 = d2
                best_h_terr = h_terr

    if best_i == -1:
        tx_gnd = elev[2] if elev else 0.0
        rx_gnd = elev[n_samples + 2] if (elev and len(elev) > n_samples + 2) else 0.0
        h1 = tx_amsl_m - tx_gnd
        h2 = rx_amsl_m - rx_gnd
        h1 = max(1.0, h1)
        h2 = max(1.0, h2)
        best_d1 = d_m * (h1 / (h1 + h2))
        best_d2 = d_m - best_d1
        best_h1 = h1
        best_h2 = h2
        best_h_terr = tx_gnd + (rx_gnd - tx_gnd) * (h1 / (h1 + h2))

    res.reflection_dist_km = best_d1 / 1000.0
    res.reflection_elev_m = best_h_terr

    r_direct = math.sqrt(d_m * d_m + (tx_amsl_m - rx_amsl_m)**2)
    r_reflect = math.sqrt(best_d1**2 + best_h1**2) + math.sqrt(best_d2**2 + best_h2**2)
    delta_r = r_reflect - r_direct
    res.delta_r_m = delta_r

    psi = math.atan2(best_h1, best_d1)
    psi = max(1e-4, min(math.pi / 2.0 - 1e-4, psi))
    res.grazing_angle_deg = psi * (180.0 / math.pi)

    eps_r = eps_dielect if eps_dielect > 1.0 else 15.0
    sigma = sgm_conductivity if sgm_conductivity > 0.0 else 0.005
    eps_imag = (18000.0 * sigma) / max(1.0, f_mhz)
    eta = complex(eps_r, -eps_imag)

    sin_psi = math.sin(psi)
    cos_psi = math.cos(psi)
    sqrt_term = (eta - complex(cos_psi * cos_psi, 0.0)) ** 0.5

    if pol == 0:
        gamma = (sin_psi - sqrt_term) / (sin_psi + sqrt_term)
    else:
        gamma = (eta * sin_psi - sqrt_term) / (eta * sin_psi + sqrt_term)

    gamma_mag = abs(gamma)
    gamma_phase = math.atan2(gamma.imag, gamma.real)

    div_denom = 1.0 + (2.0 * best_d1 * best_d2) / (EARTH_RADIUS_EFF_M * d_m * max(1e-4, sin_psi))
    D = 1.0 / math.sqrt(max(1.0, div_denom))

    gamma_eff_mag = min(1.0, gamma_mag * D)
    res.gamma_mag = gamma_eff_mag
    res.gamma_phase_deg = gamma_phase * (180.0 / math.pi)

    phase_diff = k * delta_r + gamma_phase
    res.phase_diff_deg = (phase_diff * (180.0 / math.pi)) % 360.0
    if res.phase_diff_deg < 0.0:
        res.phase_diff_deg += 360.0

    if coherent_interference:
        F_sq = 1.0 + gamma_eff_mag**2 + 2.0 * gamma_eff_mag * math.cos(phase_diff)
    else:
        F_sq = 1.0 + gamma_eff_mag**2

    F_sq = max(2.5e-3, min(4.0, F_sq))

    res.path_loss_db = res.fspl_db - 10.0 * math.log10(F_sq)
    return res
"""
with open(py_file, "w") as f:
    f.write(new_py_code)
print("Updated python script.")
