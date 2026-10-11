#!/usr/bin/env python3

import os
import sys

import numpy as np
from scipy.ndimage import median_filter
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "py"))
from tikzplot import Figure
from spectrum import AVERAGES, averaged, db, faxis

#- Create a time vector
N = 2**12
#t = np.linspace(0,N,N+1)
t = np.arange(0,N)
#- Create the "continuous time" signal
fbin = 47
fm1 = 1/N*213
f1 = 1/128 - 1/N
#f1 = fbin
fd = fm1
#- 0.7 of full scale: a true 1-bit loop overloads at full-scale input
#- Fixed seed, so `make plots` reproduces the committed figure
#- rather than a new noise realisation every time. The noise is
#- meant to look like noise, not to be any particular noise.
np.random.seed(15)
x_s = 0.7*np.sin(2*np.pi*f1*t) + 1/2**15*np.random.randn(N)

#----------------------------------------------
#- Model an ADC
#----------------------------------------------

## Sample
#- Sampling frequency is 1/nfs of the time vector
nfs = 4
u = x_s[0::nfs]

bits = 1

def quantize(v,bits):
    #- 2**bits levels reaching +/-1, so bits=1 is a genuine two-level
    #- quantizer. Without the clamp the "1-bit" output takes more than two
    #- values whenever the integrator runs past full scale.
    levels = 2**bits
    if(levels == 2):
        return 1.0 if v >= 0 else -1.0
    step = 2/(levels-1)
    return float(np.clip(np.round(v/step)*step,-1,1))

def lsb(bits):
    """Quantizer step: 2**bits levels spanning -1 to +1."""
    return 2/(2**bits-1)

y_sn = np.array([quantize(v,bits) for v in u])

dither = 1
M = len(u)
y_sd = np.zeros(M)
x = np.zeros(M)
for n in range(1,M):
    x[n] = x[n-1] + (u[n]-y_sd[n-1])
    #- dither = 1 gives the dither the same power as the quantization
    #- noise, step**2/12, so its standard deviation is step/sqrt(12)
    y_sd[n] = quantize(x[n] + dither*np.random.randn()*lsb(bits)/np.sqrt(12),bits)

#- Remove the first samples to get rid of the initial
# settling
y_sd = y_sd[2:]

#----------------------------------------------
# Plot spectrum
#----------------------------------------------
#- Window, averaging and normalization live in py/spectrum.py, shared
#- with q.py and osr.py so every spectrum in the chapter is computed the
#- same way.
def run(bits, dither, seed=15):
    """Re-run the modulator for one (bits, dither) pair."""
    np.random.seed(seed)
    x_s = 0.7*np.sin(2*np.pi*f1*t) + 1/2**15*np.random.randn(N)
    u = x_s[0::nfs]
    y_sn = np.array([quantize(v, bits) for v in u])

    M = len(u)
    y_sd = np.zeros(M)
    x = np.zeros(M)
    for n in range(1, M):
        x[n] = x[n-1] + (u[n] - y_sd[n-1])
        y_sd[n] = quantize(x[n] + dither*np.random.randn()*lsb(bits)/np.sqrt(12), bits)
    return x_s, u, y_sn, y_sd[2:]


X_s, u, Y_sn, Y_sdn = averaged(lambda seed: run(bits, dither, seed), seed=15)

plt.subplot(1,4,1)
plt.plot(faxis(X_s),db(X_s),color="black",linewidth=0.7)
plt.grid(True)
plt.xlabel("f / fs\nContinuous time, continuous value")
plt.ylabel("Frequency Domain [dB20]")
plt.ylim(-160,0)
plt.subplot(1,4,2)
plt.plot(faxis(u),db(u),color="black",linewidth=0.7)
plt.grid(True)
plt.xlabel("f / fs\nDiscrete time, continuous value")
plt.ylim(-160,0)
plt.subplot(1,4,3)
plt.plot(faxis(Y_sn),db(Y_sn),color="black",linewidth=0.7)
plt.grid(True)
plt.xlabel("f / fs\nDiscrete time, Discrete value")
plt.text(0.25,-10,str(bits) + "-bit")

plt.ylim(-160,0)
plt.subplot(1,4,4)
plt.plot(faxis(Y_sdn),db(Y_sdn),color="black",linewidth=0.7)
plt.grid(True)
plt.xlabel("f / fs\nNoise-shaped")
plt.text(0.1,-150,"dither=" + str(dither))
plt.ylim(-160,0)

fig = plt.gcf()
fig.set_size_inches(12, 7)
plt.tight_layout()
plt.savefig(f"l6_sd_d{dither}_b{bits}.pdf")


plt.figure()

NN = int(len(Y_sdn)/2)
Y_sdn_short = Y_sdn[NN:]
x_sdn_short = np.arange(0,NN)/NN/2
plt.semilogx(x_sdn_short,db(Y_sdn[int(len(Y_sdn)/2):]),color="black")
plt.xlabel("Normalized frequency")
plt.ylabel("Magnitude [dB20]")
plt.grid(True)

plt.savefig(f"l6_sdlog_d{dither}_b{bits}.pdf")

#- The same panels as TikZ, so the plots match the schematics. The
#- three variants the lecture uses are emitted in one run, so `make
#- plots` reproduces every committed figure.
def tikz(bits, dither, log_too):
    X_s, U, Y_sn, Y_sdn = averaged(lambda seed: run(bits, dither, seed),
                                   seed=15)

    dither_note = "with dither" if dither else "no dither"
    tfig = Figure(f"""A first order sigma-delta modulator, {bits}-bit, {dither_note}.

Four spectra: continuous, sampled, quantized without shaping, and then
the modulator output, each power-averaged over {AVERAGES} noise
realisations. The last panel is the one to look at. The noise is
not smaller in total - it cannot be - it has been pushed away from zero
frequency, which is where the signal is.""", columns=4)

    panels = ((X_s, "Continuous time, continuous value", None),
              (U, "Discrete time, continuous value", None),
              (Y_sn, "Discrete time, discrete value", f"{bits}-bit"),
              (Y_sdn, "Noise-shaped", f"dither = {dither}"))
    for i, (spec, name, note) in enumerate(panels):
        ax = tfig.axes(xlabel="$f/f_s$", title=name,
                       ylabel="Magnitude [dB20]" if i == 0 else None,
                       ylim=(-160, 0), width=3.5, height=4.6)
        ax.plot(faxis(spec), db(spec), colour="black")
        if note:
            #- bottom left, since the noise-shaped trace lives at the top
            ax.annotate(-0.47, -155, note, anchor="south west")
    tfig.save(f"l6_sd_d{dither}_b{bits}")

    if not log_too:
        return
    #- and the log-frequency view, where first order shaping is a line
    NN = len(Y_sdn)//2
    xs = np.arange(0, NN)/NN/2
    lfig = Figure(f"""The same {bits}-bit modulator output on a log frequency axis.

Only the positive frequencies are shown. First order shaping is a
straight 20 dB per decade rise on this axis, which is far easier to
recognise than the curve it makes on a linear one.""")
    ax = lfig.axes(xlabel="Normalized frequency", ylabel="Magnitude [dB20]",
                   xlog=True, width=10.0, height=6.0)
    ax.plot(xs[1:], db(Y_sdn[NN:])[1:], colour="black")
    lfig.save(f"l6_sdlog_d{dither}_b{bits}")


#- The dither levels for the overlay, as power relative to the quantization
#- noise. -12 dB costs little SNDR and leaves the tones; 0 dB mostly removes
#- them; +12 dB removes them and buries the shaping.
DITHER_DB = (-12, 0, 12)


def overlay(bits):
    """Modulator output for no dither and each DITHER_DB, overlaid."""
    cases = [(0, "no dither", "black")]
    colours = ("blue", "red", "orange")
    for rel, colour in zip(DITHER_DB, colours):
        label = f"dither {rel:+d} dB" if rel else "dither 0 dB (equal power)"
        cases.append((10**(rel/20), label, colour))

    ofig = Figure(f"""The {bits}-bit modulator output for several dither levels.

Dither power is given relative to the quantization noise power,
step^2/12. Only positive frequencies, on a log axis, so the noise
shaping is a straight line and the tones stand out above it. Without
dither the noise is a set of tones, not a floor. At -12 dB the tones are
still there; at 0 dB, equal power, they are mostly gone and what is
left is the shaped floor. At +12 dB they are gone and the floor has
risen over the whole band.""")
    ax = ofig.axes(xlabel="Normalized frequency", ylabel="Magnitude [dB20]",
                   xlog=True, ylim=(-100, 0), width=10.0, height=6.0,
                   legend_pos="south east")
    for dither, label, colour in cases:
        Y = averaged(lambda seed: run(bits, dither, seed), seed=15)[3]
        NN = len(Y)//2
        xs = np.arange(0, NN)/NN/2
        ax.plot(xs[1:], db(Y[NN:])[1:], colour=colour, label=label,
                style="thin")
    ofig.save(f"l6_sd_dither_b{bits}")


#- The level sweep uses its own, longer record with the input near zero
#- frequency, so the band at a high oversampling ratio holds enough bins
#- to measure in. The figures above use too short a record for that.
SWEEP_L = 2**18
SWEEP_BIN = 37
SWEEP_OSR = 1024
SWEEP_DB = np.arange(-80, 1, 4)


def run_long(bits, amplitude, dither, seed):
    """The same modulator on SWEEP_L samples of a sine at bin SWEEP_BIN."""
    np.random.seed(seed)
    n = np.arange(SWEEP_L)
    #- plain lists and floats, since this loop runs 2**18 times per call
    u = (amplitude*np.sin(2*np.pi*SWEEP_BIN/SWEEP_L*n)).tolist()
    d = (dither*np.random.randn(SWEEP_L)*lsb(bits)/np.sqrt(12)).tolist()
    y = [0.0]*SWEEP_L
    x = 0.0
    for i in range(1, SWEEP_L):
        x = x + (u[i] - y[i-1])
        y[i] = quantize(x + d[i], bits)
    return [np.array(y)]


def inband(Y, osr):
    """In-band SNDR and SFDR in dB, from the positive half of a spectrum.

    The signal is the five bins around SWEEP_BIN; the first three bins
    are left out, since the Hann window spreads DC into them. Every
    other bin in the band counts, harmonics included, so this is SNDR.
    """
    NN = len(Y)//2
    P = np.abs(Y[NN:])**2
    k = SWEEP_BIN
    band = np.zeros(NN, bool)
    band[3:NN//osr] = True
    band[k-2:k+3] = False
    sig = P[k-2:k+3].sum()
    return (10*np.log10(sig/P[band].sum()),
            10*np.log10(P[k]/P[band].max()))


def level_sweep(bits):
    """In-band SNDR and SFDR against input level, with and without dither."""
    cases = ((0, "no dither", "black"),
             (10**(-12/20), "$-12$ dB dither", "blue"),
             (1, "0 dB dither", "red"))
    results = []
    for dither, _, _ in cases:
        #- without dither every seed gives the same record
        avg = AVERAGES if dither else 1
        results.append(np.array([
            inband(averaged(lambda seed: run_long(bits, 10**(l/20), dither,
                                                  seed),
                            seed=15, averages=avg)[0], SWEEP_OSR)
            for l in SWEEP_DB]))
    #- first order SQNR for a sine of amplitude A against step**2/12
    #- noise. Not 6.02*bits + 1.76, which assumes 2**bits steps across
    #- full scale; these levels have 2**bits - 1 steps, so for one bit
    #- the step is the whole range and the textbook form is 6 dB high.
    full = 10*np.log10(0.5/(lsb(bits)**2/12))
    est = full - 5.17 + 30*np.log10(SWEEP_OSR) + SWEEP_DB

    lfig = Figure(f"""In-band SNDR and SFDR of the {bits}-bit modulator against input level, OSR = {SWEEP_OSR}.

A longer record than the spectra above, {SWEEP_L} samples with the input
at bin {SWEEP_BIN}, so the band holds enough bins to measure in. Dither
power is relative to the quantization noise power, step^2/12. The
dashed line is the first order SQNR for the actual step. Without
dither the loop tracks it near full scale, where a large input dithers the loop by
itself, and falls away from it as the input shrinks, until below about
-68 dBFS the output is a limit cycle that does not see the input at
all. With equal-power dither the SNDR follows the estimate about 4 dB
below it, and below -40 dBFS the SFDR is 18 to 35 dB
better. Dither is what makes the white-noise model true; near
full scale it costs SNDR.""", columns=2)
    for col, title in enumerate(("In-band SNDR", "In-band SFDR")):
        ax = lfig.axes(xlabel="Input amplitude [dBFS]", title=title,
                       ylabel="[dB]" if col == 0 else None,
                       ylim=(-40, 100), width=6.0, height=5.5,
                       legend_pos="south east")
        for (dither, label, colour), res in zip(cases, results):
            ax.plot(SWEEP_DB, res[:, col], colour=colour,
                    label=label if col == 0 else None, decimate=False)
        if col == 0:
            ax.plot(SWEEP_DB, est, colour="black", label="SQNR estimate",
                    style="thick, dashed", decimate=False)
    lfig.save(f"l6_sd_sfdr_b{bits}")
    return results, est


tikz(1, 0, log_too=False)
tikz(1, 1, log_too=False)
overlay(1)
_res, _est = level_sweep(1)
for i, lvl in enumerate(SWEEP_DB):
    print("sweep: %+3d dBFS  est %5.1f  " % (lvl, _est[i]) + "  ".join(
        "SNDR %5.1f SFDR %5.1f" % tuple(r[i]) for r in _res))
tikz(5, 1, log_too=True)
