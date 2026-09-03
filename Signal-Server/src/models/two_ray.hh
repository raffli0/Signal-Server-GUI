#ifndef _TWO_RAY_HH_
#define _TWO_RAY_HH_

#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <complex>

/**
 * Result structure containing detailed Two-Ray parameters for diagnostics and display.
 */
struct TwoRayResult {
    double path_loss_db;
    double fspl_db;
    double delta_r_m;
    double phase_diff_deg;
    double gamma_mag;
    double gamma_phase_deg;
    double reflection_dist_km;
    double reflection_elev_m;
    double grazing_angle_deg;
    bool is_obstructed;
};

/**
 * Detailed Two-Ray Ground Reflection Calculation with terrain profile scanning.
 */
TwoRayResult CalculateTwoRay(
    double f_mhz,
    double tx_amsl_m,
    double rx_amsl_m,
    double dkm,
    int pol,                 // 0 = Horizontal, 1 = Vertical
    double eps_dielect,      // e.g. 15.0 for average ground, 80 for water
    double sgm_conductivity, // e.g. 0.005 S/m
    const double *elev,      // array: elev[0]=n_pts-1, elev[1]=step_m, elev[2..]=sample_m
    int n_samples,
    bool coherent_interference = true,
    double surface_roughness_m = 0.5
);

/**
 * Fast scalar interface for the Signal-Server engine model dispatcher (los.cc).
 */
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
);

#endif /* _TWO_RAY_HH_ */
