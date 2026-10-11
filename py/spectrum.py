"""One way to turn a record into a plotted spectrum, shared by the ADC
chapter's plot scripts (ex/q.py, ex/osr.py, ex/sd_1st.py), so every
spectrum in the chapter is computed the same way.

The method:

- Periodic Hann window, np.hanning(N+1) with the last sample dropped.
  It is exactly 0.5 - 0.5*cos(2*pi*n/N), a sum of three DFT basis
  vectors (bins 0 and +-1, weights 1/2, -1/4, -1/4), so a tone on an
  exact bin lands in three bins and leaks nothing anywhere else.
  np.hanning(N) is the symmetric window, which is not a combination of
  DFT basis vectors, and the same tone smears across every bin at about
  -45 dBc. Measured, not asserted (aic2023 issue #10).
- Two-sided, fftshift-ed, so 0 Hz is in the middle and the edges are
  +/- fs/2 of the record's own sample rate.
- Power-averaged over AVERAGES noise realisations. A single FFT of noise
  has bins that jump ~10 dB above the median and look like spurs. Real
  tones are the same in every run and survive the averaging; random
  peaks do not.
- Normalized so the largest bin is 0 dB.
"""

import numpy as np

AVERAGES = 16


def window(N):
    """Periodic Hann window of length N."""
    return np.hanning(N+1)[0:N]


def power(x):
    """Windowed, fftshift-ed power spectrum of one record, not normalized."""
    X = np.fft.fftshift(np.fft.fft(window(len(x))*x))
    return np.abs(X)**2


def faxis(X):
    """Frequency axis in f/fs for a spectrum of len(X) bins."""
    M = len(X)
    return (np.arange(0, M, 1) - M/2)/M


def averaged(make, seed=0, averages=AVERAGES):
    """Average the spectra of the records make(seed) returns.

    make(seed) runs one noise realisation and returns a list of records
    (signals at different points in the model). It is called with seed,
    seed+1, ... seed+averages-1. Returns one magnitude spectrum per
    record, each normalized to its own largest bin.
    """
    acc = None
    for k in range(averages):
        P = [power(np.asarray(x, dtype=float)) for x in make(seed + k)]
        acc = P if acc is None else [a + p for a, p in zip(acc, P)]
    out = []
    for a in acc:
        m = np.sqrt(a/averages)
        out.append(m/np.max(m))
    return out


def db(X):
    """Magnitude spectrum to dB20."""
    return 20*np.log10(np.abs(X))
