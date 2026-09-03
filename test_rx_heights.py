import math

def sim_tworay(ht, hr, f_mhz, d_km):
    c = 299792458.0
    wavelength = c / (f_mhz * 1e6)
    k = 2 * math.pi / wavelength
    d = d_km * 1000.0
    r1 = math.sqrt(d**2 + (hr - ht)**2)
    r2 = math.sqrt(d**2 + (hr + ht)**2)
    delta_r = r2 - r1
    
    psi = math.atan2(ht + hr, d)
    eps_r = 15.0
    sigma = 0.005
    eps_imag = (18000.0 * sigma) / f_mhz
    eta = complex(eps_r, -eps_imag)
    sin_psi = math.sin(psi)
    cos_psi = math.cos(psi)
    sqrt_term = (eta - cos_psi**2)**0.5
    gamma = (eta * sin_psi - sqrt_term) / (eta * sin_psi + sqrt_term)
    
    a = (4.0/3.0) * 6371000.0
    d1 = d * (ht / (ht + hr))
    d2 = d - d1
    D = 1.0 / math.sqrt(1.0 + (2.0 * d1 * d2) / (a * d * max(1e-4, sin_psi)))
    gamma_eff = min(1.0, abs(gamma) * D)
    phase_diff = k * delta_r + math.atan2(gamma.imag, gamma.real)
    
    F_sq = 1.0 + gamma_eff**2 + 2.0 * gamma_eff * math.cos(phase_diff)
    F_sq = max(2.5e-3, min(4.0, F_sq))
    
    fspl = 32.44 + 20*math.log10(f_mhz) + 20*math.log10(d_km)
    loss = fspl - 10*math.log10(F_sq)
    return loss, 10*math.log10(F_sq)

print("--- Testing Rx = 2.0m AGL (Ground Mobile) at 1200 MHz ---")
for d in [1, 5, 10, 20, 30, 40, 50]:
    loss, gain = sim_tworay(50.0, 2.0, 1200.0, d)
    print(f"Dist {d:2d} km: TwoRay Gain = {gain:+5.1f} dB, Total Loss = {loss:5.1f} dB")

print("\n--- Testing Rx = 1500.0m AGL (Drone) at 1200 MHz ---")
for d in [1, 5, 10, 20, 30, 40, 50]:
    loss, gain = sim_tworay(50.0, 1500.0, 1200.0, d)
    print(f"Dist {d:2d} km: TwoRay Gain = {gain:+5.1f} dB, Total Loss = {loss:5.1f} dB")
