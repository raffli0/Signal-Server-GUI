import math
import numpy as np

# Simulate a 100km path from Tx (50m AGL, 487m AMSL) to Rx (1500m AGL, 1980m AMSL)
# at f = 1200 MHz
f_mhz = 1200.0
c = 299792458.0
wavelength = c / (f_mhz * 1e6)
k = 2 * math.pi / wavelength

ht = 50.0   # 50m AGL
hr = 1500.0 # 1500m AGL

distances_km = np.linspace(1.0, 100.0, 1200) # 1200 pixels

# Standard Two-Ray model
results = []
for d_km in distances_km:
    d = d_km * 1000.0
    r1 = math.sqrt(d**2 + (hr - ht)**2)
    r2 = math.sqrt(d**2 + (hr + ht)**2)
    delta_r = r2 - r1
    
    # Grazing angle
    psi = math.atan2(ht + hr, d)
    
    # Fresnel reflection (approx -1 for grazing angles)
    # Real eps=15, sigma=0.005
    eps_r = 15.0
    sigma = 0.005
    eps_imag = (18000.0 * sigma) / f_mhz
    eta = complex(eps_r, -eps_imag)
    sin_psi = math.sin(psi)
    cos_psi = math.cos(psi)
    sqrt_term = (eta - cos_psi**2)**0.5
    gamma = (eta * sin_psi - sqrt_term) / (eta * sin_psi + sqrt_term)
    
    gamma_mag = abs(gamma)
    gamma_phase = math.atan2(gamma.imag, gamma.real)
    
    # Divergence
    # D = 1 / sqrt(1 + 2*d1*d2 / (a * d * sin(psi)))
    a = (4.0/3.0) * 6371000.0
    d1 = d * (ht / (ht + hr))
    d2 = d - d1
    D = 1.0 / math.sqrt(1.0 + (2.0 * d1 * d2) / (a * d * max(1e-4, sin_psi)))
    
    gamma_eff = min(1.0, gamma_mag * D)
    
    phase_diff = k * delta_r + gamma_phase
    
    F_sq = 1.0 + gamma_eff**2 + 2.0 * gamma_eff * math.cos(phase_diff)
    F_sq = max(1e-3, min(4.0, F_sq))
    
    fspl = 32.44 + 20*math.log10(f_mhz) + 20*math.log10(d_km)
    loss = fspl - 10*math.log10(F_sq)
    
    # Rx power for 12W, 8dBi Tx, 8dBi Rx
    tx_dbm = 10*math.log10(12 * 1000)
    rx_dbm = tx_dbm + 8.0 + 8.0 - loss
    results.append((d_km, rx_dbm, 10*math.log10(F_sq)))

print("Sample results (first 10 and last 10):")
print(f"Dist 1km: Rx dBm = {results[0][1]:.1f}, F_gain = {results[0][2]:.1f} dB")
print(f"Dist 10km: Rx dBm = {results[119][1]:.1f}, F_gain = {results[119][2]:.1f} dB")
print(f"Dist 50km: Rx dBm = {results[599][1]:.1f}, F_gain = {results[599][2]:.1f} dB")
print(f"Dist 100km: Rx dBm = {results[1199][1]:.1f}, F_gain = {results[1199][2]:.1f} dB")

# Check number of nulls/peaks between 10km and 100km
f_gains = [r[2] for r in results[120:]]
peaks = sum(1 for i in range(1, len(f_gains)-1) if f_gains[i] > f_gains[i-1] and f_gains[i] > f_gains[i+1])
print(f"Total interference cycles (peaks) between 10km and 100km: {peaks}")
