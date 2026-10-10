#!/usr/bin/env python3
"""Simulate a third-order Leapfrog control-bounded ADC and vendor the
spectrum into ex/data/.

The simulation needs cbadc (pip install cbadc), the control-bounded
ADC toolbox from ETH Zurich and NTNU, which nothing else in this repo
does. So it is split from the plot, the same way ex/fetch_data.py
splits the SPICE data from the scripts that draw it: this script runs
cbadc and writes plain CSV, ex/leapfrog_psd.py reads the CSV and needs
only numpy. Run this one only when the design below changes:

    python3 ex/leapfrog_sim.py

The design is cbadc's own Leapfrog parametrisation for 10 bits in an
8 MHz band with N = 3 integrators, which lands at an OSR of about 15.
A 0.5 amplitude tone near 500 kHz is the input, placed exactly on an
FFT bin so it needs no leakage correction; the batch estimator recovers
u(t) from the three control signals. The spectrum is one Hann-windowed
FFT over 2^16 samples, scaled so a full-scale sine reads 0 dB. The
simulation is noiseless and deterministic, so it reproduces exactly.
Only 100 kHz to 100 MHz is written, which is what the figure shows.
"""

import csv
import os

import numpy as np
import cbadc

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

N, ENOB, BW = 3, 10, 8e6
AMP = 0.5
SIZE = 1 << 16

af = cbadc.synthesis.get_leap_frog(ENOB=ENOB, N=N, BW=BW)
analog, control = af.analog_system, af.digital_control
T = control.clock.T
FIN = round(500e3 * T * SIZE) / (T * SIZE)   # coherent: on a bin

#- The estimator bandwidth parameter: the analog gain at the band edge
eta2 = np.linalg.norm(
    analog.transfer_function_matrix(np.array([2 * np.pi * BW])).flatten()) ** 2
K1 = K2 = 1 << 9

sim = cbadc.simulator.FullSimulator(
    analog, control, [cbadc.analog_signal.Sinusoidal(AMP, FIN)])
est = cbadc.digital_estimator.BatchEstimator(analog, control, eta2, K1, K2)
est(sim)
u_hat = np.array([next(est) for _ in range(SIZE + K1 + K2)])[K1 + K2:, 0]

#- Hann window, single sided, full-scale sine at 0 dB
w = np.hanning(SIZE)
X = np.fft.rfft(u_hat * w)
f = np.fft.rfftfreq(SIZE, T)
psd = np.abs(X) ** 2 / (np.sum(w) / 2) ** 2
keep = (f >= 1e5) & (f <= 1e8)
f, psd = f[keep], psd[keep]

#- Noise transfer function seen at the estimate, summed over the controls
ntf = est.noise_transfer_function(2 * np.pi * f)
ntf_db = 20 * np.log10(np.linalg.norm(ntf[0], axis=0))

with open(os.path.join(DATA, "leapfrog_psd.csv"), "w", newline="") as fo:
    wr = csv.writer(fo)
    wr.writerow(["f", "psd_db", "ntf_db"])
    for fi, p, n in zip(f, psd, ntf_db):
        wr.writerow([f"{fi:.6g}", f"{10 * np.log10(p):.2f}", f"{n:.2f}"])

print(f"fs = {1 / T / 1e6:.1f} MHz, OSR = {1 / T / (2 * BW):.1f}, "
      f"fin = {FIN / 1e3:.1f} kHz, wrote {len(f)} points")
