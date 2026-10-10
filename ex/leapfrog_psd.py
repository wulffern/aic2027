#!/usr/bin/env python3
"""Spectrum of a third-order Leapfrog control-bounded ADC.

The estimate u_hat(t) of a 500 kHz tone, recovered by the batch
estimator from the three control signals, plotted as a power spectral
density together with the noise transfer function. The NTF is shifted
down onto the noise floor so the two can be compared by shape: the
noise rises with frequency through the band, the complex conjugate
zero pair puts a notch near 6 MHz, and above the band edge the shaped
noise peaks and then falls off.

The data comes from a cbadc simulation, vendored into
ex/data/leapfrog_psd.csv by ex/leapfrog_sim.py, so this script needs
only numpy."""

import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py"))
from tikzplot import Figure

with open(os.path.join(HERE, "data", "leapfrog_psd.csv")) as fi:
    rows = list(csv.reader(fi))[1:]
f, psd, ntf = (np.array([float(r[i]) for r in rows]) for i in range(3))

#- Line the NTF up with the noise floor between 1 and 5 MHz, clear of the tone
band = (f > 1e6) & (f < 5e6)
ntf = ntf + np.median(psd[band] - ntf[band])

#- tikzplot decimates in equal columns of the data index, which on a log
#  axis spends every column on the top decade. Take the min/max envelope
#  in log-spaced columns instead, so the low decades keep their bins.
def log_envelope(x, y, columns=600):
    edges = np.geomspace(x[0], x[-1] * 1.000001, columns + 1)
    col = np.searchsorted(edges, x, side="right") - 1
    xs, ys = [], []
    for c in np.unique(col):
        i = np.flatnonzero(col == c)
        for k in sorted({i[np.argmin(y[i])], i[np.argmax(y[i])]}):
            xs.append(x[k])
            ys.append(y[k])
    return xs, ys


fig = Figure("""Power spectral density of the estimated input u_hat(t) of a
third-order Leapfrog control-bounded ADC (cbadc simulation, 10 bit target
in an 8 MHz band, OSR about 15), with a 500 kHz tone at -6 dBFS, from a
Hann-windowed FFT over 2^16 samples, plotted in black from 100 kHz to
100 MHz on a log frequency axis. The noise transfer
function, in red, is shifted onto the noise floor: the noise rises
through the band, a notch sits near 6 MHz from the complex conjugate
zero pair, and the shaped noise peaks just above the 8 MHz band edge
before falling off.""")
ax = fig.axes(xlabel="Frequency [Hz]", ylabel="PSD [dBFS]", xlog=True,
              xlim=(1e5, 1e8), ylim=(-180, 0), legend_pos="north east")
ax.plot(*log_envelope(f, psd), colour="black", style="thin",
        label="$\\hat{u}(t)$", decimate=False)
ax.plot(*log_envelope(f, ntf), colour="red", style="thick", label="NTF",
        decimate=False)
fig.save("l06_leapfrog_psd")
