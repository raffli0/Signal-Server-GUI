"""Unit tests for Two-Ray Ground Reflection Multipath & Interference calculation."""

import math
import pytest
from signal_gui import two_ray


def test_two_ray_calculation_constructive_and_destructive():
    freq_mhz = 1200.0
    tx_amsl = 100.0
    rx_amsl = 100.0
    dkm = 5.0
    elev = [4, 1000.0, 50.0, 50.0, 50.0, 50.0, 50.0]

    # Coherent Interference mode
    res_interf = two_ray.calculate_two_ray(
        f_mhz=freq_mhz,
        tx_amsl_m=tx_amsl,
        rx_amsl_m=rx_amsl,
        dkm=dkm,
        pol=1,
        eps_dielect=15.0,
        sgm_conductivity=0.005,
        elev=elev,
        n_samples=4,
        coherent_interference=True,
        surface_roughness_m=0.0
    )

    assert res_interf.fspl_db > 100.0
    assert res_interf.gamma_mag > 0.0
    assert 0.0 <= res_interf.phase_diff_deg <= 360.0
    assert abs(res_interf.path_loss_db - res_interf.fspl_db) <= 40.0

    # Incoherent mode
    res_incoherent = two_ray.calculate_two_ray(
        f_mhz=freq_mhz,
        tx_amsl_m=tx_amsl,
        rx_amsl_m=rx_amsl,
        dkm=dkm,
        pol=1,
        eps_dielect=15.0,
        sgm_conductivity=0.005,
        elev=elev,
        n_samples=4,
        coherent_interference=False,
        surface_roughness_m=0.0
    )

    assert res_incoherent.path_loss_db <= res_incoherent.fspl_db
