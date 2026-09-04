import math
import os

os.makedirs("gui/data/antennas", exist_ok=True)
os.makedirs("Signal-Server/antenna", exist_ok=True)

def generate_omni(gain_dbi=8.0, name="omni_8dbi"):
    def elevation_pattern_gain(theta_deg):
        # theta_deg: 0 at horizon, +90 up (zenith), -90 down (nadir)
        theta_rad = math.radians(abs(theta_deg))
        # Beamwidth exponent p calibrated to physical dipole / collinear roll-off:
        # Dipole (2.15 dBi): p = 1.0 (cos theta)
        # 6 dBi: p = 1.64
        # 8 dBi: p = 1.98 (~2.0, cos^2 theta)
        # 12 dBi: p = 2.64
        # This roll-off ensures that FSPL(d) + L_pattern(theta) monotonically increases
        # with distance, eliminating artificial signal dips/donuts in the near-field
        # for elevated receivers (e.g. UAV / drone at 1500m AGL).
        p = 1.0 + (gain_dbi - 2.15) / 6.0
        cos_val = math.cos(theta_rad)
        beam = cos_val ** p
        
        # Real-world base station omni antennas have structural leakage and
        # null-fill so zenith attenuation does not exceed -12 dB (0.25 amplitude).
        total_e = max(0.25, min(1.0, beam))
        return total_e

    # 1. Generate .ant file (Radio Mobile format)
    # Lines 1-360: Azimuth 0-359 deg in dB
    # Lines 361-720: Elevation 0-359 deg in dB
    ant_path = f"gui/data/antennas/{name}.ant"
    with open(ant_path, "w") as f:
        # Azimuth: omni is 0 dB all around
        for az in range(360):
            f.write("0.0\n")
        # Elevation: 0 to 359 deg
        for el in range(360):
            if el <= 90:
                ang = el
            elif el <= 270:
                ang = 180 - el
            else:
                ang = el - 360
            amp = elevation_pattern_gain(ang)
            db_val = 20.0 * math.log10(amp)
            f.write(f"{db_val:0.2f}\n")

    # 2. Generate .az file (Signal-Server format)
    # Line 1: azimuth offset (0)
    # Lines 2+: <az_deg> <amplitude 0.0-1.0>
    for folder in ["gui/data/antennas", "Signal-Server/antenna"]:
        az_path = f"{folder}/{name}.az"
        with open(az_path, "w") as f:
            f.write("0\n")
            for az in range(361):
                f.write(f"{az}\t1.0000\n")

        # 3. Generate .el file (Signal-Server format)
        # Directly write data points from -10 to +90 degrees without dummy header
        el_path = f"{folder}/{name}.el"
        with open(el_path, "w") as f:
            for el in range(-10, 91):
                amp = elevation_pattern_gain(el)
                f.write(f"{el}\t{amp:0.4f}\n")

    print(f"Generated {name} (.ant, .az, .el)")

generate_omni(gain_dbi=8.0, name="omni_8dbi")
generate_omni(gain_dbi=2.15, name="dipole")
generate_omni(gain_dbi=6.0, name="omni_6dbi")
generate_omni(gain_dbi=12.0, name="omni_12dbi")
