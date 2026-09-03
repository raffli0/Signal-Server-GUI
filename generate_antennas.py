import math
import os

os.makedirs("gui/data/antennas", exist_ok=True)
os.makedirs("Signal-Server/antenna", exist_ok=True)

def generate_omni(gain_dbi=8.0, name="omni_8dbi"):
    # Determine number of collinear elements for the given gain
    # Dipole is 2.15 dBi. Each doubling of elements adds ~3 dB.
    # 8 dBi -> ~6 elements
    if gain_dbi <= 2.2:
        n_elements = 1
        d_spacing = 0.5
    elif gain_dbi <= 6.0:
        n_elements = 3
        d_spacing = 0.75
    elif gain_dbi <= 9.0:
        n_elements = 6
        d_spacing = 0.75
    else: # 10-12 dBi
        n_elements = 10
        d_spacing = 0.75

    def elevation_pattern_gain(theta_deg):
        # theta_deg: 0 at horizon, +90 up, -90 down
        theta_rad = math.radians(theta_deg)
        sin_t = math.sin(theta_rad)
        cos_t = math.cos(theta_rad)
        
        # Element pattern (half-wave dipole)
        if abs(cos_t) < 1e-6:
            e_elem = 0.0
        else:
            e_elem = math.cos((math.pi / 2.0) * sin_t) / cos_t
            
        # Array factor
        if n_elements == 1:
            af = 1.0
        else:
            psi = (2.0 * math.pi * d_spacing) * sin_t
            if abs(psi) < 1e-6:
                af = 1.0
            else:
                denom = n_elements * math.sin(psi / 2.0)
                if abs(denom) < 1e-6:
                    af = 1.0
                else:
                    af = math.sin(n_elements * psi / 2.0) / denom
        
        total_e = abs(e_elem * af)
        total_e = max(1e-4, min(1.0, total_e))
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
            # map el 0..359 to angle -90..+90
            # in Radio Mobile .ant: 0 is horizon, 90 is zenith, 270 is nadir, 180 is rear horizon
            # let's map standard elevation:
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
        # Line 1: <mechanical_downtilt> <tilt_azimuth>
        # Lines 2+: <el_deg> <amplitude 0.0-1.0> from -10 to +90 (or +10 to -90)
        el_path = f"{folder}/{name}.el"
        with open(el_path, "w") as f:
            f.write("0.0\t0.0\n")
            for el in range(-10, 91):
                amp = elevation_pattern_gain(el)
                f.write(f"{el}\t{amp:0.4f}\n")

    print(f"Generated {name} (.ant, .az, .el)")

generate_omni(gain_dbi=8.0, name="omni_8dbi")
generate_omni(gain_dbi=2.15, name="dipole")
generate_omni(gain_dbi=6.0, name="omni_6dbi")
generate_omni(gain_dbi=12.0, name="omni_12dbi")
