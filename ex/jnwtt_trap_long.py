#!/usr/bin/env python3
"""Two hours of one trap: the GR06 burst, recorded to the end.

jnwtt_trap.py drew the dwell times from the first half hour, while the
recording was still running. The full record is two hours of GR06 alone
at about 31 degrees C, sampled every 10 ms, and is long enough for three
things one trap should do:

  - stay in each state for an exponentially distributed time
  - give a Lorentzian spectrum, with the plateau and corner Machlup's
    formula predicts from the dwell times and the step alone
  - give an amplitude distribution of two Gaussians, not one

Nothing is fitted. Every dashed line is computed from the measured
levels, residual and mean dwell times in jnwtt_trap_long_stats.csv.

Data: ex/data/jnwtt_trap_long_*.csv, reduced by fetch_data.py."""

import csv
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "py"))
from tikzplot import Figure

DATA = Path(__file__).resolve().parent / "data"


def rows(name):
    with open(DATA / name) as fh:
        return list(csv.DictReader(fh))


st = {k: float(v) for k, v in rows("jnwtt_trap_long_stats.csv")[0].items()}
mean = (st["mean0_s"], st["mean1_s"])
step = st["level1_k"] - st["level0_k"]
minutes = st["record_s"] / 60

#- the dwell times
d = rows("jnwtt_trap_long_dwell.csv")
fig = Figure(
    f"""Dwell times of the GR06 trap over {minutes:.0f} minutes at about
{st['temp_c']:.0f} degrees C, as a survival curve: the fraction of
visits that lasted longer than t. A memoryless two-state process gives
an exponential, a straight line on this axis; the dashed lines are
exponentials with the measured means, not fits.""")
ax = fig.axes(xlabel="Dwell time $t$ [s]",
              ylabel="Fraction of visits longer than $t$",
              ylog=True, xlim=(0, 25), ylim=(3e-4, 1.2))
for state, colour, name in ((0, "blue", "high reading"),
                            (1, "red", "low reading")):
    dw = sorted(float(x["dwell_s"]) for x in d if int(x["state"]) == state)
    n = len(dw)
    ax.plot(dw, [1 - i / n for i in range(n)], colour=colour,
            style="only marks, mark=*, mark size=0.7pt", decimate=False,
            label=f"{name}: {n} visits, mean {mean[state]:.1f} s")
#- after the marks, so the legend entries stay on the marks
for m, colour in zip(mean, ("blue", "red")):
    ax.plot([0, 25], [1, math.exp(-25 / m)], colour=colour,
            style="thick, dashed", decimate=False)
fig.save("jnwtt_trap_long_dwell")

#- the spectrum: Machlup, with the measured step and dwell times
rate = 1 / mean[0] + 1 / mean[1]
corner = rate / (2 * math.pi)


def machlup(f):
    return 4 * step**2 / ((mean[0] + mean[1])
                          * (rate**2 + (2 * math.pi * f)**2))


p = rows("jnwtt_trap_long_psd.csv")
f = [float(x["f_hz"]) for x in p]
fig = Figure(
    f"""Spectrum of the GR06 reading over {minutes:.0f} minutes, as
measured: only a straight line is removed from each segment, so the
slow temperature drift rises below about 30 mHz. The dashed line is
Machlup's Lorentzian for a {abs(step) * 1e3:.0f} mK step with mean dwell
times of {mean[0]:.1f} s and {mean[1]:.1f} s, not a fit: flat below
{corner:.2f} Hz, falling as 1/f^2 above. Above 1 Hz the reading has more
than the trap, short visits the detector misses and the sensor's own
noise.""")
ax = fig.axes(xlabel="Frequency [Hz]", ylabel="PSD [K$^2$/Hz]",
              xlog=True, ylog=True, xlim=(1e-3, 50), ylim=(1e-4, 3),
              legend_pos="south west")
ax.plot(f, [float(x["psd_k2_hz"]) for x in p], colour="red",
        label="GR06, measured", decimate=False)
fl = [10**(-3 + i * 0.05) for i in range(76)]
ax.plot(fl, [machlup(v) for v in fl], colour="black",
        style="thick, dashed", decimate=False,
        label=f"one trap, predicted: corner {corner:.2f} Hz")
fig.save("jnwtt_trap_long_psd")

#- the amplitude distribution: two Gaussians, weighted by time in each
h = rows("jnwtt_trap_long_hist.csv")
xs = [float(x["x_k"]) for x in h]
share = (mean[0] / (mean[0] + mean[1]), mean[1] / (mean[0] + mean[1]))
sig = st["resid_rms_k"]


def gauss(x, mu, w):
    return w * math.exp(-0.5 * ((x - mu) / sig)**2) / (sig * math.sqrt(2 * math.pi))


fig = Figure(
    f"""Distribution of the GR06 reading over {minutes:.0f} minutes,
against its slow baseline. Ordinary noise would give one Gaussian. One
trap gives two, {abs(step) * 1e3:.0f} mK apart, weighted by the time
spent in each state ({share[0] * 100:.0f} and {share[1] * 100:.0f} %),
each as wide as the {sig * 1e3:.0f} mK noise inside a state. The dashed
line is that sum, not a fit.""")
ax = fig.axes(xlabel="Reading minus baseline [K]",
              ylabel="Probability density [1/K]",
              xlim=(-1.4, 0.8), ylim=(0, 2.0), legend_pos="north west")
ax.plot(xs, [float(x["density_per_k"]) for x in h], colour="red",
        style="thick, const plot mark mid", decimate=False,
        label="GR06, measured")
xl = [-1.4 + i * 0.01 for i in range(221)]
ax.plot(xl, [gauss(v, st["level0_k"], share[0])
             + gauss(v, st["level1_k"], share[1]) for v in xl],
        colour="black", style="thick, dashed", decimate=False,
        label="two levels, predicted")
fig.save("jnwtt_trap_long_hist")
