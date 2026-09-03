
#include "two_ray.hh"
#include "fspl.hh"
#include <algorithm>
#include <cmath>
#include <complex>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const double EARTH_RADIUS_EFF_M = (4.0 / 3.0) * 6371000.0;
static const double SPEED_OF_LIGHT = 299792458.0;

TwoRayResult CalculateTwoRay(
    double f_mhz,
    double tx_amsl_m,
    double rx_amsl_m,
    double dkm,
    int pol,
    double eps_dielect,
    double sgm_conductivity,
    const double *elev,
    int n_samples,
    bool coherent_interference,
    double surface_roughness_m
) {
    (void)surface_roughness_m;
    TwoRayResult res;
    double d_m = std::max(10.0, dkm * 1000.0);
    double f_hz = std::max(1.0, f_mhz) * 1e6;
    double lambda = SPEED_OF_LIGHT / f_hz;
    double k = (2.0 * M_PI) / lambda;

    double fspl = FSPLpathLoss(f_mhz, dkm, false);
    res.fspl_db = fspl;
    res.is_obstructed = false;

    // Search for the specular reflection point on the terrain
    double best_diff = 1e9;
    int best_i = -1;
    double best_h1 = 0;
    double best_h2 = 0;
    double best_d1 = 0;
    double best_d2 = 0;
    double best_h_terr = 0;
    
    double sample_dist = (elev != nullptr && n_samples > 0) ? elev[1] : (d_m / 2.0);

    if (elev != nullptr && n_samples > 1) {
        for (int i = 1; i < n_samples; i++) {
            double d1 = i * sample_dist;
            double d2 = d_m - d1;
            double earth_bulge = (d1 * d2) / (2.0 * EARTH_RADIUS_EFF_M);
            double h_terr = elev[2 + i] + earth_bulge;
            double h1_i = tx_amsl_m - h_terr;
            double h2_i = rx_amsl_m - h_terr;
            
            if (h1_i <= 0 || h2_i <= 0) continue;
            
            double theta1 = atan2(h1_i, d1);
            double theta2 = atan2(h2_i, d2);
            double diff = std::abs(theta1 - theta2);
            if (diff < best_diff) {
                best_diff = diff;
                best_i = i;
                best_h1 = h1_i;
                best_h2 = h2_i;
                best_d1 = d1;
                best_d2 = d2;
                best_h_terr = elev[2 + i];
            }
        }
    }

    if (best_i == -1) {
        // Fallback to smooth earth if no valid reflection point found
        double tx_gnd = (elev != nullptr && n_samples > 0) ? elev[2] : 0.0;
        double rx_gnd = (elev != nullptr && n_samples > 0) ? elev[n_samples + 2] : 0.0;
        double h1 = tx_amsl_m - tx_gnd;
        double h2 = rx_amsl_m - rx_gnd;
        h1 = std::max(1.0, h1);
        h2 = std::max(1.0, h2);
        best_d1 = d_m * (h1 / (h1 + h2));
        best_d2 = d_m - best_d1;
        double earth_bulge = (best_d1 * best_d2) / (2.0 * EARTH_RADIUS_EFF_M);
        best_h1 = std::max(1.0, h1 - (best_d1 * best_d1) / (2.0 * EARTH_RADIUS_EFF_M));
        best_h2 = std::max(1.0, h2 - (best_d2 * best_d2) / (2.0 * EARTH_RADIUS_EFF_M));
        best_h_terr = tx_gnd + (rx_gnd - tx_gnd) * (best_d1 / d_m);
    }

    res.reflection_dist_km = best_d1 / 1000.0;
    res.reflection_elev_m = best_h_terr;

    // Path lengths
    double r_direct = sqrt(d_m * d_m + (tx_amsl_m - rx_amsl_m) * (tx_amsl_m - rx_amsl_m));
    double r_reflect = sqrt(best_d1 * best_d1 + best_h1 * best_h1) + sqrt(best_d2 * best_d2 + best_h2 * best_h2);
    double delta_r = r_reflect - r_direct;
    res.delta_r_m = delta_r;

    // Grazing angle
    double psi = atan2(best_h1, best_d1); // equal to atan2(best_h2, best_d2)
    psi = std::max(1e-4, std::min(M_PI / 2.0 - 1e-4, psi));
    res.grazing_angle_deg = psi * (180.0 / M_PI);

    // Fresnel Reflection Coefficient
    double eps_r = (eps_dielect > 1.0) ? eps_dielect : 15.0;
    double sigma = (sgm_conductivity > 0.0) ? sgm_conductivity : 0.005;
    double eps_imag = (18000.0 * sigma) / std::max(1.0, f_mhz);
    std::complex<double> eta(eps_r, -eps_imag);

    double sin_psi = sin(psi);
    double cos_psi = cos(psi);
    std::complex<double> sqrt_term = std::sqrt(eta - std::complex<double>(cos_psi * cos_psi, 0.0));

    std::complex<double> gamma;
    if (pol == 0) {
        gamma = (sin_psi - sqrt_term) / (sin_psi + sqrt_term); // Horizontal
    } else {
        gamma = (eta * sin_psi - sqrt_term) / (eta * sin_psi + sqrt_term); // Vertical
    }

    double gamma_mag = std::abs(gamma);
    double gamma_phase = std::arg(gamma);

    // Divergence Factor D
    double div_denom = 1.0 + (2.0 * best_d1 * best_d2) / (EARTH_RADIUS_EFF_M * d_m * std::max(1e-4, sin_psi));
    double D = 1.0 / sqrt(std::max(1.0, div_denom));

    double gamma_eff_mag = std::min(1.0, gamma_mag * D);
    res.gamma_mag = gamma_eff_mag;
    res.gamma_phase_deg = gamma_phase * (180.0 / M_PI);

    // Phase difference & Interference
    double phase_diff = k * delta_r + gamma_phase;
    res.phase_diff_deg = fmod(phase_diff * (180.0 / M_PI), 360.0);
    if (res.phase_diff_deg < 0.0) res.phase_diff_deg += 360.0;

    double F_sq;
    if (coherent_interference) {
        F_sq = 1.0 + gamma_eff_mag * gamma_eff_mag + 2.0 * gamma_eff_mag * cos(phase_diff);
    } else {
        F_sq = 1.0 + gamma_eff_mag * gamma_eff_mag;
    }

    // Numerical bounds
    F_sq = std::max(2.5e-3, std::min(4.0, F_sq));

    res.path_loss_db = fspl - 10.0 * log10(F_sq);

    return res;
}

double TwoRayGroundLoss(
    double f_mhz,
    double tx_amsl_m,
    double rx_amsl_m,
    double dkm,
    int pol,
    double eps_dielect,
    double sgm_conductivity,
    const double *elev,
    int n_samples,
    double sample_dist_m,
    double *out_refl_dist_km,
    double *out_refl_elev_m
) {
    (void)sample_dist_m;
    TwoRayResult res = CalculateTwoRay(
        f_mhz, tx_amsl_m, rx_amsl_m, dkm, pol,
        eps_dielect, sgm_conductivity, elev, n_samples,
        true, 0.5
    );

    if (out_refl_dist_km != nullptr) *out_refl_dist_km = res.reflection_dist_km;
    if (out_refl_elev_m != nullptr) *out_refl_elev_m = res.reflection_elev_m;

    return res.path_loss_db;
}
