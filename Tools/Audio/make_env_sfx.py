#!/usr/bin/env python3
"""Synthesise the Saskarta environment SFX: spot loops, ruin one-shots, radio and ending.

Offline only (numpy + scipy, matplotlib for the contact sheet). Never touches Unreal.
Writes 48 kHz 16-bit PCM WAVs, a manifest and a spectrogram contact sheet to
<project>/Saved/GameAudio/Environment/. Every sound has a fixed seed, so every run
writes the same files.

    python Tools/Audio/make_env_sfx.py            # generate, then run the check
    python Tools/Audio/make_env_sfx.py --check    # re-read existing files, check only
    python Tools/Audio/make_env_sfx.py --out DIR  # write somewhere else

NO MUSIC. Everything here is filtered noise, modal impacts, stick-slip pulse trains and
granular crackle. The only tonal parts are mains hum (50 Hz family), a low unsteady pipe
whistle, friction squeals, a crow-like call and brief heterodyne squeaks in the dial
sweep; the --check tonal test measures and limits them (see TONAL_* below).

Formats
  one-shots  mono,   peak -3 dBFS,  5 ms raised-cosine edge fades, zero DC
  loops      stereo, peak -12 dBFS, decorrelated channels, seamless wrap

How loops are made seamless
  Each loop is rendered with 2.5 s of pre-roll (so filters and reverb tails are already
  running) plus a 1.5 s overhang past the loop end. The overhang is equal-power
  crossfaded onto the head, so the last sample runs straight on into the first. Event
  onsets (drips, flaps, ticks, grains) are kept out of 0.30 s before to 0.10 s after the
  wrap, so the 50 ms either side of the seam holds only bed and earlier tails and the
  seam RMS test compares like with like.

--check (exit status 1 on any failure), per file
  format      48000 Hz, 16-bit PCM, mono (one-shot) or stereo (loop)
  duration    within +/-5 ms of spec
  peak        one-shot -3.5..-2.5 dBFS, loop -12.5..-11.5 dBFS
  non-silent  loudest 100 ms RMS at least (peak - 30 dB); whole-file RMS > -60 dBFS
  DC          |mean| <= 0.1 % FS per channel
  edges       one-shots: first and last sample <= 16 LSB
  loops       seam RMS: last 50 ms vs first 50 ms within 3 dB, each channel
              seam jump: |x[0] - x[-1]| <= the 99.9th percentile of |x[i+1] - x[i]| inside
              the file (the wrap is no bigger a step than the top 0.1 % of ordinary steps)
              stereo: |corr(L, R)| < 0.9
  tonal       per 1 s window: 20 frames of 8192 samples (Hann, hop 2048); take the
              per-bin MEDIAN over time (only sustained energy survives), divide by a
              31-bin (~180 Hz) running median across frequency, and report the largest
              ratio between 150 Hz and 8 kHz in dB (melodic pitch lives below ~4.2 kHz;
              bins > 60 dB under the window's strongest bin are ignored as empty). Limit TONAL_MAX_DB = 9 dB. Calibration (6 s tests):
              band noise alone scores 5.8; a 440 Hz sine 20 dB under 200-8k noise RMS
              scores 12.8; a C-major triad 25 dB under it, 9.0. Rationale: at 440 Hz a
              critical band is ~17 bins, so +9 dB per bin puts a tone at about -3 dB
              relative to the noise in its critical band, i.e. just above masking: the
              test fails any tone a listener would hear as a pitch over the bed. Windows
              more than 35 dB below the file's loudest window are skipped (decay tails).
              Exceptions, declared per sound with a reason:
                hum    bins within 15 Hz of a 50 Hz multiple up to 1 kHz are ignored
                       (mains fundamental and its transformer harmonics)
                brief  up to 2 consecutive windows may exceed, and at most 20 % of
                       loop windows (friction squeals, whistles, the crow call, and
                       metal/relay impact rings, which the median test sees as tonal
                       because the one-shot around them is otherwise silent)
                hum+brief  both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from scipy import signal as sps
from scipy.ndimage import median_filter

SR = 48_000
PCM_SCALE = 32767.0
FULL_SCALE = 32768.0
ONESHOT_PEAK_DBFS = -3.0
LOOP_PEAK_DBFS = -12.0
EDGE_FADE_S = 0.005
LOOP_PREROLL_S = 2.5
LOOP_XFADE_S = 1.5
SEAM_KEEPOUT_S = (0.30, 0.10)  # no event onsets from 0.30 s before to 0.10 s after the wrap
SEAM_KEEPOUT_SHORT_S = (0.15, 0.06)  # for dense, short events (bubbles, grains): smaller hole

DURATION_TOL_S = 0.005
PEAK_TOL_DB = 0.5
LOUDEST_WINDOW_BELOW_PEAK_DB = 30.0
MIN_FILE_RMS_DBFS = -60.0
MAX_DC_PERCENT = 0.1
MAX_EDGE_LSB = 16
SEAM_RMS_TOL_DB = 3.0
SEAM_WINDOW_S = 0.05
SEAM_JUMP_PERCENTILE = 99.9
MAX_STEREO_CORR = 0.9
TONAL_MAX_DB = 9.0
TONAL_FLOOR_DB = 60.0  # bins this far under the window's strongest bin are ignored (empty band)
TONAL_MIN_HZ = 150.0
TONAL_MAX_HZ = 8000.0  # melodic pitch lives below ~4.2 kHz (top of a piano); 8 kHz covers overtones
HUM_MASK_HZ = 15.0  # +/- around each 50 Hz multiple (the Hann main lobe of an 8192 frame is ~12 Hz)
TONAL_SKIP_BELOW_LOUDEST_DB = 35.0
BRIEF_MAX_CONSECUTIVE = 2
BRIEF_MAX_FRACTION = 0.20

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameAudio" / "Environment"


# =========================================================================== DSP helpers

def tvec(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _sos(x, kind, f, order=2):
    return sps.sosfilt(sps.butter(order, f, btype=kind, fs=SR, output="sos"), x, axis=-1)


def lp(x, f, order=2):
    return _sos(x, "lowpass", f, order)


def hp(x, f, order=2):
    return _sos(x, "highpass", f, order)


def bp(x, lo, hi, order=2):
    hi = min(hi, 0.45 * SR)
    return _sos(x, "bandpass", [lo, hi], order)


def resonator(x, f, q):
    """RBJ constant-0-dB-peak band-pass biquad."""
    w0 = 2.0 * np.pi * f / SR
    alpha = np.sin(w0) / (2.0 * q)
    b = np.array([alpha, 0.0, -alpha])
    a = np.array([1.0 + alpha, -2.0 * np.cos(w0), 1.0 - alpha])
    return sps.lfilter(b / a[0], a / a[0], x)


def one_pole_smooth(x, tau):
    k = np.exp(-1.0 / (tau * SR))
    return sps.lfilter([1.0 - k], [1.0, -k], x)


def ctrl(rng, n, rate):
    """Smooth random control signal (Catmull-Rom through N(0,1) points at ``rate`` Hz)."""
    m = int(n / SR * rate) + 5
    p = rng.standard_normal(m)
    pos = np.arange(n) / SR * rate
    i = np.floor(pos).astype(int)
    u = pos - i
    p0, p1, p2, p3 = p[i], p[i + 1], p[i + 2], p[i + 3]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def gust(rng, n, slow=0.18, fast=0.7, base=0.55, depth=0.3):
    return np.clip(base + depth * ctrl(rng, n, slow) + 0.5 * depth * ctrl(rng, n, fast), 0.08, 1.2)


def pink(rng, n):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    spec /= np.sqrt(np.maximum(f, 20.0))
    x = np.fft.irfft(spec, n)
    return x / np.std(x)


def fft_band(x, lo=None, hi=None, width_oct=0.4):
    """Zero-phase soft-edged band limit (zero padded, no wrap)."""
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(x, nfft)
    octv = np.log2(np.maximum(np.fft.rfftfreq(nfft, 1.0 / SR), 1e-6))

    def step(c):
        u = np.clip((octv - np.log2(c)) / width_oct + 0.5, 0.0, 1.0)
        return 0.5 - 0.5 * np.cos(np.pi * u)

    mask = np.ones_like(octv)
    if lo:
        mask *= step(lo)
    if hi:
        mask *= 1.0 - step(hi)
    return np.fft.irfft(spec * mask, nfft)[:n]


def add(buf, x, i):
    i = int(i)
    if i >= len(buf) or i + len(x) <= 0:
        return
    s0 = max(0, -i)
    e = min(len(x), len(buf) - i)
    buf[i + s0:i + e] += x[s0:e]


def pan(p):
    a = (np.clip(p, -1, 1) + 1.0) * np.pi / 4.0
    return np.cos(a), np.sin(a)


def thin(rng, dur, rmax, rate_fn, seam=None, t0=0.0, keep=SEAM_KEEPOUT_S):
    k = rng.poisson(rmax * (dur - t0))
    ts = np.sort(rng.uniform(t0, dur, k))
    ts = ts[rng.random(k) < rate_fn(ts) / rmax]
    return clear(ts, seam, keep)


def near_seam(ts, seam, keep=SEAM_KEEPOUT_S):
    return seam is not None and -keep[0] < ts - seam < keep[1]


def clear(ts, seam, keep=SEAM_KEEPOUT_S):
    ts = np.asarray(ts, dtype=float)
    if seam is None:
        return ts
    d = ts - seam
    return ts[(d <= -keep[0]) | (d >= keep[1])]


def env_sample(rng, env, count):
    p = env / env.sum()
    idx = rng.choice(len(env), size=count, p=p)
    return np.sort(idx + rng.uniform(0, 1, count)) / SR


def burst(rng, dur, lo, hi, tau, attack=0.0002):
    n = max(8, int(dur * SR))
    t = tvec(n)
    x = bp(rng.standard_normal(n), lo, hi)
    return x * np.exp(-t / tau) * (1.0 - np.exp(-t / attack))


def bubble(f0, tau, rise, amp=1.0):
    n = int(tau * 7 * SR) + 1
    t = tvec(n)
    f = f0 * (1.0 + rise * (1.0 - np.exp(-t / (tau * 1.5))))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return amp * np.sin(ph) * np.exp(-t / tau) * (1.0 - np.exp(-t / 0.0004))


def modal(rng, freqs, taus, amps, dur, attack=0.0003):
    freqs = np.asarray(freqs, float)
    ok = freqs < 0.45 * SR
    freqs, taus, amps = freqs[ok], np.asarray(taus, float)[ok], np.asarray(amps, float)[ok]
    n = int(dur * SR)
    t = tvec(n)
    ph = rng.uniform(0, 2 * np.pi, len(freqs))[:, None]
    y = (amps[:, None] * np.sin(2 * np.pi * freqs[:, None] * t + ph)
         * np.exp(-t / taus[:, None])).sum(axis=0)
    return y * (1.0 - np.exp(-t / attack))


def make_ir(rng, rt60, predelay=0.01, hf_ratio=0.45, split=1800.0):
    n = int(rt60 * 1.1 * SR)
    t = tvec(n)
    noise = rng.standard_normal(n)
    lo = lp(noise, split)
    hi = noise - lo
    ir = lo * 10 ** (-3 * t / rt60) + hi * 10 ** (-3 * t / (rt60 * hf_ratio))
    ir *= 1.0 - np.exp(-t / 0.004)
    ir = np.concatenate([np.zeros(int(predelay * SR)), ir])
    return ir / np.sqrt(np.sum(ir ** 2))


def reverb(x, ir):
    return sps.fftconvolve(x, ir)[:len(x)]


def grain_kernels(rng, centres, dur=0.006):
    ks = []
    for c in centres:
        k = burst(rng, dur, c / 1.6, c * 1.6, rng.uniform(0.0006, 0.0015))
        ks.append(k / np.max(np.abs(k)))
    return ks


def granular(rng, n, times, amps, kernels):
    """Sparse impulses (one kernel group per grain) convolved with short noise kernels."""
    out = np.zeros(n)
    group = rng.integers(0, len(kernels), len(times))
    idx = (np.asarray(times) * SR).astype(int)
    for g, k in enumerate(kernels):
        imp = np.zeros(n)
        sel = (group == g) & (idx < n)
        np.add.at(imp, idx[sel], np.asarray(amps)[sel])
        out += sps.fftconvolve(imp, k)[:n]
    return out


def mains_hum(rng, t):
    """50 Hz mains transformer hum: 100 Hz magnetostriction dominant, soft buzz, all 50 Hz multiples."""
    ph = 2 * np.pi * 50.0 * t
    h = sum(a * np.sin(k * ph + rng.uniform(0, 2 * np.pi))
            for k, a in ((1, 0.55), (2, 1.0), (3, 0.3), (4, 0.42), (6, 0.2), (8, 0.09)))
    buzz = lp(np.tanh(4.0 * np.sin(2 * ph + rng.uniform(0, 6))), 450, order=4) * 0.35
    floor = 0.03 * bp(pink(rng, len(t)), 100, 6000)  # cabinet/fan air so upper lines sit in noise
    return lp(h + buzz, 900, order=8) + floor


def relay_clunk(rng, size=1.0, dur=0.5):
    """Contactor: sharp crack + bounce, a 60-90 Hz armature thump, two short inharmonic rings."""
    n = int(dur * SR)
    t = tvec(n)
    crack = bp(rng.standard_normal(n), 1200, 10000)
    cenv = np.exp(-t / 0.0025) + 0.35 * np.exp(-np.maximum(t - 0.009 * size, 0) / 0.0018) * (t >= 0.009 * size)
    crack = crack / np.max(np.abs(crack)) * cenv * (1.0 - np.exp(-t / 0.0002))
    fth = 55.0 / size ** 0.3 + 35.0 * np.exp(-t / 0.03)
    thump = np.sin(2 * np.pi * np.cumsum(fth) / SR) * np.exp(-t / (0.05 * size)) * (1 - np.exp(-t / 0.0015))
    body = lp(rng.standard_normal(n), 400) * np.exp(-t / (0.03 * size))
    body /= np.max(np.abs(body)) + 1e-12
    f1 = rng.uniform(1050, 1350) / size ** 0.4
    ring = modal(rng, [f1, f1 * 2.31, f1 * 3.93], [0.028, 0.018, 0.01], [0.22, 0.13, 0.06], dur)
    return 0.9 * crack + thump + 0.45 * body * size + ring


# =========================================================================== spot loops
# signature: make(rng, n, meta) -> (2, n) float; meta.seam = wrap point in seconds

def loop_water_trickle(rng, n, m):
    dur = n / SR
    t = tvec(n)
    flow = np.clip(0.75 + 0.18 * ctrl(rng, n, 0.45) + 0.08 * ctrl(rng, n, 2.3), 0.35, 1.2)
    out = np.zeros((2, n))
    for c in range(2):
        bed = bp(rng.standard_normal(n), 1200, 7500)
        out[c] += 0.2 * bed * flow * (1 + 0.1 * ctrl(rng, n, 5.0))
        out[c] += 0.08 * lp(rng.standard_normal(n), 500) * flow
    rmax = 95.0
    for ts in thin(rng, dur, rmax, lambda x: rmax * np.interp(x, t, flow) / 1.2, m.seam, keep=SEAM_KEEPOUT_SHORT_S):
        f0 = float(np.clip(np.exp(rng.normal(np.log(1900), 0.35)), 700, 5000))
        tau = rng.uniform(0.003, 0.013) * (1900 / f0) ** 0.5
        b = bubble(f0, tau, rng.uniform(0.05, 0.35), 0.22 * np.exp(rng.normal(0, 0.55)))
        gl, gr = pan(rng.uniform(-0.5, 0.5))
        i = int(ts * SR)
        add(out[0], gl * b, i)
        add(out[1], gr * b, i + int(rng.integers(0, 20)))
    for ts in thin(rng, dur, 1.6, lambda x: 1.6 * np.ones_like(x), m.seam):
        b = bubble(rng.uniform(420, 800), rng.uniform(0.018, 0.035), rng.uniform(0.2, 0.5), 0.45)
        s = burst(rng, 0.02, 2000, 8000, 0.004) * 0.25
        b[:len(s)] += s
        gl, gr = pan(rng.uniform(-0.3, 0.3))
        add(out[0], gl * b, int(ts * SR))
        add(out[1], gr * b, int(ts * SR) + 7)
    return hp(out, 180)


def loop_drip(rng, n, m):
    dur = n / SR
    dry = np.zeros((2, n))
    sources = [(2.3, 1350.0, "puddle", -0.45), (3.7, 2150.0, "puddle", 0.35),
               (5.3, 980.0, "puddle", 0.05), (7.9, 0.0, "stone", 0.6)]
    for period, f, kind, p in sources:
        ts = rng.uniform(0, period)
        while ts < dur:
            if not near_seam(ts, m.seam, keep=(1.4, 0.1)) and rng.random() > 0.12:  # tails decay before the wrap
                amp = rng.uniform(0.5, 1.0)
                if kind == "puddle":
                    x = np.zeros(int(0.35 * SR))
                    x[:int(0.004 * SR)] += burst(rng, 0.004, 2000, 9000, 0.0004)[:int(0.004 * SR)] * 0.3
                    b = bubble(f * rng.uniform(0.82, 1.2), rng.uniform(0.012, 0.03), rng.uniform(0.25, 0.8))
                    add(x, b, 40)
                    if rng.random() < 0.5:
                        add(x, bubble(f * rng.uniform(1.3, 1.8), 0.012, 0.4, 0.3), int(rng.uniform(0.03, 0.07) * SR))
                else:
                    x = burst(rng, 0.03, 1500, 8000, 0.0012)
                    for _ in range(int(rng.integers(3, 7))):
                        add(x, burst(rng, 0.004, 3000, 10000, 0.0005) * rng.uniform(0.1, 0.3),
                            int(rng.uniform(0.002, 0.016) * SR))
                gl, gr = pan(p + rng.normal(0, 0.05))
                i = int(ts * SR)
                add(dry[0], amp * gl * x, i)
                add(dry[1], amp * gr * x, i + int(rng.integers(0, 12)))
            if rng.random() < 0.1:
                ts += rng.uniform(0.25, 0.5)
            else:
                ts += period * rng.uniform(0.85, 1.15)
    out = np.zeros((2, n))
    for c in range(2):
        wet = reverb(dry[c], make_ir(rng, 1.9, predelay=0.014 + 0.003 * c, hf_ratio=0.4))
        room = (0.012 * lp(rng.standard_normal(n), 250) + 0.003 * bp(rng.standard_normal(n), 300, 2000)
                + 0.0015 * bp(rng.standard_normal(n), 2000, 10000))  # air moving through the chamber mouth
        out[c] = 0.55 * dry[c] + 0.9 * wet + room
    return hp(out, 60)


def loop_cloth_flutter(rng, n, m):
    t = tvec(n)
    w = gust(rng, n, slow=0.18, fast=0.7)
    rate = 3.0 + 13.0 * w
    phase = np.cumsum(rate) / SR
    idx = np.nonzero(np.diff(np.floor(phase)))[0]
    out = np.zeros((2, n))
    for i in idx:
        ti = t[i] + rng.normal(0, 0.006)
        if near_seam(ti, m.seam) or (w[i] < 0.25 and rng.random() < 0.5):
            continue
        a = w[i] ** 1.8 * rng.uniform(0.4, 1.0)
        c = rng.uniform(400, 2500)
        x = burst(rng, 0.05, c / 2, c * 2.2, rng.uniform(0.006, 0.018), attack=rng.uniform(0.0005, 0.002))
        if w[i] > 0.75 and rng.random() < 0.35:
            add(x, burst(rng, 0.012, 1500, 9000, 0.0025) * 1.4, 0)
        gl, gr = pan(0.1 + rng.normal(0, 0.15))
        add(out[0], a * gl * x, int(ti * SR))
        add(out[1], a * gr * x, int(ti * SR) + int(rng.integers(0, 15)))
    flut = 0.8 + 0.2 * np.abs(np.sin(np.pi * phase))
    for c in range(2):
        out[c] += 0.08 * bp(rng.standard_normal(n), 600, 5000) * (0.15 + w ** 2) * flut
        out[c] += 0.25 * lp(rng.standard_normal(n), 400) * w
    return hp(out, 50)


def loop_pipe_wind(rng, n, m):
    w = gust(rng, n, slow=0.12, fast=0.5, base=0.5, depth=0.25)
    out = np.zeros((2, n))
    for c in range(2):
        out[c] = 0.35 * lp(rng.standard_normal(n), 600) * w + 0.05 * bp(rng.standard_normal(n), 800, 3500) * w ** 2
    # the whistle: narrowband noise (+/-5 Hz) heterodyned onto a wandering centre, only in gust peaks
    wg = np.clip(0.5 + 0.35 * ctrl(rng, n, 0.35), 0, 1.2)
    f = 228.0 + 34.0 * (wg - 0.5) + 6.0 * ctrl(rng, n, 0.9) + 2.5 * ctrl(rng, n, 6.0)
    ph = 2 * np.pi * np.cumsum(f) / SR

    def narrow():
        z = lp(rng.standard_normal(n), 5.0) + 1j * lp(rng.standard_normal(n), 5.0)
        return z / np.std(z)

    amp = np.clip((wg - 0.62) / 0.3, 0, 1) ** 1.6 * (0.75 + 0.25 * ctrl(rng, n, 2.0))
    whistle = np.real(narrow() * np.exp(1j * ph)) + 0.22 * np.real(narrow() * np.exp(1j * 2.37 * ph))
    whistle *= 0.09 * amp
    out[0] += 0.8 * whistle
    out[1] += 0.62 * whistle
    for c in range(2):
        out[c] += 0.04 * bp(rng.standard_normal(n), 1000, 4000) * wg ** 2  # edge turbulence
    return hp(out, 35)


def _tick(rng, f, tau):
    n = int(tau * 8 * SR) + 16
    t = tvec(n)
    s = np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * np.exp(-t / tau)
    click = np.diff(rng.standard_normal(n + 1)) * np.exp(-t / 0.0003) * 0.4
    return (s + click) * (1 - np.exp(-t / 0.0001))


def loop_insects(rng, n, m):
    dur = n / SR
    out = np.zeros((2, n))
    for c in range(2):
        out[c] += 0.004 * bp(rng.standard_normal(n), 2500, 9000) + 0.01 * lp(rng.standard_normal(n), 300)
    for _ in range(5):
        f_k, tau_k = rng.uniform(3500, 8500), rng.uniform(0.0005, 0.0012)
        gl, gr = pan(rng.uniform(-0.8, 0.8))
        level = rng.uniform(0.3, 1.0)
        ts = rng.uniform(0, 3)
        while ts < dur:
            style = rng.choice(3, p=[0.5, 0.3, 0.2])
            count, sp = [(int(rng.integers(3, 13)), rng.uniform(0.03, 0.08)),
                         (int(rng.integers(6, 21)), rng.uniform(0.006, 0.014)), (1, 0.0)][style]
            tt = ts
            for _k in range(count):
                if not near_seam(tt, m.seam):
                    x = _tick(rng, f_k * rng.uniform(0.9, 1.1), tau_k * rng.uniform(0.7, 1.3))
                    x *= level * rng.uniform(0.5, 1.0) * 0.5
                    add(out[0], gl * x, int(tt * SR))
                    add(out[1], gr * x, int(tt * SR) + int(rng.integers(0, 10)))
                tt += sp * rng.uniform(0.7, 1.3)
            ts = tt + rng.exponential(4.0)
    return hp(out, 80)


def loop_reed_rustle(rng, n, m):
    dur = n / SR
    t = tvec(n)
    w = gust(rng, n, slow=0.2, fast=0.9)
    kernels = grain_kernels(rng, [1800, 3000, 4500, 6500])
    out = np.zeros((2, n))
    for c in range(2):
        rmax = 60 + 1400 * 1.2 ** 2.5
        ts = thin(rng, dur, rmax, lambda x: 60 + 1400 * np.interp(x, t, w) ** 2.5, m.seam, keep=SEAM_KEEPOUT_SHORT_S)
        amps = np.exp(rng.normal(0, 0.6, len(ts))) * 0.05
        out[c] += granular(rng, n, ts, amps, kernels)
        sm = one_pole_smooth(w, 0.15)
        out[c] += 0.12 * sm ** 2 * (0.5 * bp(rng.standard_normal(n), 500, 2500)
                                    + 0.5 * sm * bp(rng.standard_normal(n), 2500, 7000))
        out[c] += 0.05 * lp(rng.standard_normal(n), 250) * w
        for tk in thin(rng, dur, 3.0, lambda x: 0.3 + 2.0 * np.minimum(np.interp(x, t, w), 1.2) ** 2 / 1.45, m.seam):
            f = rng.uniform(350, 900)
            k = modal(rng, [f, f * 2.7], [rng.uniform(0.005, 0.012), 0.004], [1.0, 0.4], 0.08)
            add(out[c], 0.12 * rng.uniform(0.4, 1.0) * k, int(tk * SR))
    return hp(out, 60)


def loop_radio_static_bed(rng, n, m):
    dur = n / SR
    fade = 0.8 + 0.18 * ctrl(rng, n, 0.12) - 0.2 * np.clip(ctrl(rng, n, 0.05), 0, None)
    fade = np.clip(fade, 0.35, 1.1)
    common = pink(rng, n)
    out = np.zeros((2, n))
    for c in range(2):
        out[c] = bp(0.75 * common + 0.66 * pink(rng, n), 280, 3400, order=4) * 0.35 * fade
    for ts in thin(rng, dur, 2.5, lambda x: 2.5 * np.ones_like(x), m.seam):
        k = 1 if rng.random() > 0.3 else int(rng.integers(2, 6))
        tt = ts
        for _ in range(k):
            x = burst(rng, 0.008, 200, 3000, rng.uniform(0.001, 0.002)) * min(np.exp(rng.normal(0, 0.6)), 2.5) * 0.35
            i = int(tt * SR)
            add(out[0], x, i)
            add(out[1], 0.9 * x, i)
            tt += rng.uniform(0.005, 0.04)
    return lp(hp(out, 150), 3200)


# =========================================================================== one-shots
# signature: make(rng, n, meta) -> (n,) float; meta.var = 0-based variation index

def os_sheet_metal(rng, n, m):
    t = tvec(n)
    P = [dict(scale=1.0, hits=[(0.10, 1.0), (0.31, 0.45), (0.43, 0.18)], chatter=False),
         dict(scale=0.8, hits=[(0.08, 1.0), (0.19, 0.6)], chatter=True),
         dict(scale=1.25, hits=[(0.14, 0.8), (0.27, 1.0), (0.52, 0.3), (0.60, 0.12)], chatter=False)][m.var]
    mm, nn = np.meshgrid(np.arange(1, 10), np.arange(1, 10))
    freqs = (21.0 * P["scale"] * (mm ** 2 + 1.6 * nn ** 2)).ravel() * rng.uniform(0.97, 1.03, mm.size)
    freqs = freqs[(freqs > 70) & (freqs < 7000)]
    freqs = rng.choice(freqs, size=min(40, len(freqs)), replace=False)
    taus = np.clip(0.35 * (400.0 / freqs) ** 0.6, 0.02, 0.5) * rng.uniform(0.7, 1.3, len(freqs))
    frame_f = np.array([1870.0, 2990.0, 4410.0]) * rng.uniform(0.9, 1.1)
    y = np.zeros(n)
    t_first = P["hits"][0][0]
    for th, s in P["hits"]:
        rest = (n - int(th * SR)) / SR
        amps = rng.rayleigh(1.0, len(freqs)) * (freqs / 300.0) ** -0.3 * 0.12
        hit = modal(rng, freqs, taus, amps, rest)
        hit += 0.8 * np.pad(burst(rng, 0.02, 900, 9000, 0.0012), (0, max(0, len(hit) - 960)))[:len(hit)]
        hit += modal(rng, frame_f, [0.12, 0.09, 0.06], [0.15, 0.1, 0.06], rest)
        th_n = min(len(hit), int(0.2 * SR))
        hit[:th_n] += 0.6 * burst(rng, 0.2, 30, 200, 0.025)[:th_n] / 0.3
        add(y, s * hit, int(th * SR))
    d = np.maximum(t - t_first, 0)
    wob = lp(rng.standard_normal(n), 180) * (0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(6, 9) * d))
    y += 3.0 * wob * np.exp(-d / 0.35) * (t > t_first)
    sw = np.clip(1 - np.abs(t - t_first + 0.04) / 0.05, 0, 1)
    y += 0.4 * bp(rng.standard_normal(n), 150, 1200) * sw
    if P["chatter"]:
        tc = P["hits"][1][0] + 0.03
        for k in range(int(rng.integers(5, 10))):
            add(y, 0.15 * 0.8 ** k * burst(rng, 0.02, 700, 7000, 0.002), int(tc * SR))
            tc += rng.uniform(0.012, 0.03)
    return y


def os_chain_rattle(rng, n, m):
    t = tvec(n)
    dur = n / SR
    if m.var == 0:
        env = np.exp(-0.5 * ((t - 0.25) / 0.18) ** 2) + 0.3 * np.exp(-np.maximum(t - 0.25, 0) / 0.3) * (t > 0.25)
        count, fb = 45, 2600.0
    elif m.var == 1:
        env = np.exp(-0.5 * ((t - 0.22) / 0.1) ** 2) + 0.8 * np.exp(-0.5 * ((t - 0.95) / 0.14) ** 2)
        count, fb = 70, 2100.0
    else:
        env = np.exp(-np.maximum(t - 0.05, 0) / 0.3) * (t > 0.05)
        count, fb = 40, 3200.0
    env *= t < dur - 0.25
    y = np.zeros(n)
    for ts in env_sample(rng, env, count):
        f = fb * rng.uniform(0.85, 1.15)
        k = modal(rng, [f, f * 2.76, f * 5.4], np.array([0.04, 0.02, 0.01]) * rng.uniform(0.6, 1.4),
                  [1.0, 0.45, 0.12], 0.2)
        k[:96] += burst(rng, 0.002, 2000, 10000, 0.0005)[:96] * 0.6
        add(y, k * np.exp(rng.normal(0, 0.5)) * 0.3, int(ts * SR))
    for ts in env_sample(rng, env, 2 + m.var % 2):
        f = rng.uniform(560, 700)
        k = modal(rng, [f, f * 2.4, f * 4.2], [0.12, 0.07, 0.04], [1.0, 0.6, 0.3], 0.4)
        k += 0.6 * burst(rng, 0.4, 60, 400, 0.02)
        add(y, 0.5 * k, int(ts * SR))
    return y


def os_wood_creak(rng, n, m):
    t = tvec(n)
    dur = n / SR
    base, glide, scale, jit = [(95, 0.6, 1.0, 0.14), (140, -0.5, 1.2, 0.16),
                               (28, 0.2, 0.6, 0.12), (42, 0.0, 0.75, 0.18)][m.var]
    u = t / dur
    contour = glide * np.sin(np.pi * u) if m.var != 1 else glide * u + 0.7 * u ** 2
    rate = base * 2.0 ** (contour + 0.12 * ctrl(rng, n, 25) + 0.06 * ctrl(rng, n, 8))
    press = np.clip(0.55 + 0.35 * ctrl(rng, n, 2.5 if m.var != 3 else 5.0), 0, 1.1)
    press *= np.sin(np.pi * np.clip((t - 0.03) / (dur - 0.12), 0, 1)) ** 0.5
    phase = np.cumsum(rate) / SR
    idx = np.nonzero(np.diff(np.floor(phase)))[0]
    exc = np.zeros(n)
    for i in idx:
        if press[i] < 0.25 or rng.random() < 0.1:
            continue
        j = int(i + rng.normal(0, jit * SR / rate[i] * 0.5))
        if 0 <= j < n - 1:
            exc[j] += press[i] * rng.uniform(0.4, 1.0)
            exc[j + 1] -= 0.3 * press[i]
    exc += 0.02 * rng.standard_normal(n) * one_pole_smooth(np.abs(exc) > 0, 0.02)
    fr = np.array([190, 430, 760, 1250, 2100, 3300]) * scale * rng.uniform(0.93, 1.07, 6)
    q = [5, 6, 7, 7, 6, 5]
    g = [1.0, 0.9, 0.7, 0.5, 0.35, 0.2]
    y = sum(gi * resonator(exc, fi, qi) for fi, qi, gi in zip(fr, q, g))
    dens = one_pole_smooth(np.abs(exc), 0.03)
    y += 0.8 * bp(rng.standard_normal(n), 900, 4000) * dens / (dens.max() + 1e-9) * 0.05
    if m.var >= 2:
        y += 1.2 * resonator(exc, 110 * scale, 3)
    return lp(y, 6000)  # timber soaks up the top end


def os_pulley_squeak(rng, n, m):
    t = tvec(n)
    chirps = [[(0.08, 0.28, 1350, 1500), (0.50, 0.22, 1420, 1280), (0.86, 0.12, 1300, 1380)],
              [(0.10, 0.45, 720, 820), (0.75, 0.40, 800, 690)]][m.var]
    y = np.zeros(n)
    over = np.zeros(n)
    for t0, ln, fa, fb in chirps:
        k = int(ln * SR)
        tl = tvec(k)
        f = fa * (fb / fa) ** (tl / ln) * (1 + 0.015 * ctrl(rng, k, 30) + 0.006 * ctrl(rng, k, 90))
        ph = 2 * np.pi * np.cumsum(f) / SR
        wave_ = sum(a * np.sin(h * ph + rng.uniform(0, 6))
                    for h, a in enumerate([1, 0.5, 0.35, 0.2, 0.12, 0.08], start=1))
        e = np.clip(tl / rng.uniform(0.02, 0.04), 0, 1) * np.clip((ln - tl) / rng.uniform(0.03, 0.06), 0, 1)
        e *= np.clip(0.7 + 0.3 * ctrl(rng, k, 40), 0.2, 1.2)
        s = wave_ * e + 0.3 * bp(rng.standard_normal(k), fa * 2, min(fa * 6, 20000)) * e
        add(y, 0.3 * s, int(t0 * SR))
        add(over, e, int(t0 * SR))
    ov = one_pole_smooth(over, 0.08)
    y += 0.25 * lp(rng.standard_normal(n), 350) * (0.3 + ov)
    return y * np.clip(t / 0.02, 0, 1)


def _stone_knock(rng, size):
    freqs = np.sort(rng.uniform(300, 3200, 12)) / size
    k = modal(rng, freqs, rng.uniform(0.002, 0.008, 12) * size, rng.uniform(0.3, 1.0, 12), 0.15)
    k[:1440] += 0.8 * lp(burst(rng, 0.03, 400, 6000, 0.001), 3500)[:1440]
    k[:4800] += 0.9 * size * burst(rng, 0.1, 40, 250, 0.015)[:4800] / 0.2
    return k


def _grit(rng, y, t0, t1, count, amp):
    for ts in rng.uniform(t0, t1, count):
        add(y, burst(rng, 0.004, 1500, 7000, 0.0005) * amp * rng.uniform(0.3, 1), int(ts * SR))


def os_stone_settle(rng, n, m):
    t = tvec(n)
    y = np.zeros(n)
    if m.var == 0:
        _grit(rng, y, 0.05, 0.2, 25, 0.15)
        add(y, _stone_knock(rng, 1.0), int(0.22 * SR))
        for i, ts in enumerate(np.sort(rng.uniform(0.3, 0.6, 4))):
            add(y, _tick(rng, rng.uniform(2500, 5000), 0.001) * 0.2 * 0.7 ** i, int(ts * SR))
    elif m.var == 1:
        add(y, 0.7 * _stone_knock(rng, 0.8), int(0.08 * SR))
        _grit(rng, y, 0.1, 0.3, 15, 0.1)
        add(y, _stone_knock(rng, 1.2), int(0.31 * SR))
    else:
        e = np.clip((t - 0.05) / 0.1, 0, 1) * np.clip((0.5 - t) / 0.1, 0, 1)
        y += 0.12 * bp(rng.standard_normal(n), 700, 3500) * e * np.clip(0.5 + 0.5 * ctrl(rng, n, 40), 0, 1.5)
        _grit(rng, y, 0.05, 0.5, 60, 0.12)
        add(y, 0.8 * _stone_knock(rng, 0.7), int(0.55 * SR))
        for i, ts in enumerate(np.sort(rng.uniform(0.6, 1.0, 8))):
            add(y, _tick(rng, rng.uniform(2000, 5000), 0.0012) * 0.25 * 0.8 ** i, int(ts * SR))
    return y


def os_gravel_trickle(rng, n, m):
    t = tvec(n)
    dur = n / SR
    peak, count = [(0.6, 260), (1.1, 360), (0.35, 180)][m.var]
    (flo, fhi), p_big = [((2500, 7500), 0.15), ((1800, 5500), 0.28), ((3500, 9000), 0.07)][m.var]
    env = (t / peak) ** 2 * np.exp(2 * (1 - t / peak)) * (1 + 0.4 * ctrl(rng, n, 6))
    env = np.clip(env, 0, None) * (t < dur - 0.15)
    y = np.zeros(n)
    for ts in env_sample(rng, env, count):
        i = int(ts * SR)
        if rng.random() > p_big:
            f = rng.uniform(flo, fhi)
            k = modal(rng, [f, f * rng.uniform(1.5, 2.3)], [rng.uniform(0.001, 0.004), 0.001], [1, 0.4], 0.03)
            add(y, k * 0.2 * np.exp(rng.normal(0, 0.5)), i)
        else:
            f = rng.uniform(900, 2200)
            iv, a = rng.uniform(0.04, 0.08), 0.5
            for _ in range(int(rng.integers(2, 5))):
                k = modal(rng, [f, f * 2.3, f * 3.9], [rng.uniform(0.004, 0.01), 0.004, 0.002], [1, 0.5, 0.3], 0.06)
                add(y, a * k, i)
                i += int(iv * SR)
                iv *= 0.6
                a *= 0.5
    sm = one_pole_smooth(env, 0.05)
    sm /= sm.max()
    y += 0.08 * bp(rng.standard_normal(n), 2500, 9000) * sm + 0.15 * lp(rng.standard_normal(n), 250) * sm
    return y


def os_reed_push(rng, n, m):
    t = tvec(n)
    dur = n / SR
    speed, slaps, bright0 = [(1.0, 3, 1.0), (0.7, 4, 0.9), (1.4, 2, 1.1), (0.5, 1, 0.6)][m.var]
    a = 0.12 / speed
    env = np.where(t < a, (t / a) ** 1.5, np.exp(-(t - a) / (0.28 / speed)))
    env *= np.clip((dur - t) / 0.08, 0, 1)
    bright = np.clip((0.3 + 0.7 * env) * bright0, 0, 1)
    low = bp(rng.standard_normal(n), 500, 1600)
    high = bp(rng.standard_normal(n), 1600, 6500)
    y = 0.25 * (low * (1 - 0.5 * bright) + high * bright) * env * (1 + 0.3 * ctrl(rng, n, 25))
    kern = grain_kernels(rng, [2200, 3500, 5200, 7000])
    ts = thin(rng, dur, 2000.0, lambda x: 2000.0 * np.interp(x, t, env) ** 1.5)
    y += granular(rng, n, ts, np.exp(rng.normal(0, 0.6, len(ts))) * 0.06 * bright0, kern)
    for ts in np.sort(rng.uniform(a * 0.6, min(dur - 0.15, a + 0.4 / speed), slaps)):
        s = burst(rng, 0.05, 1200, 6000, rng.uniform(0.004, 0.01)) * rng.uniform(0.4, 0.8)
        f = rng.uniform(300, 700)
        s[:1920] += 0.3 * modal(rng, [f, f * 2.7], [0.008, 0.004], [1, 0.4], 0.04)
        add(y, s, int(ts * SR))
    return y


def os_crow_distant(rng, n, m):
    t = tvec(n)
    calls = [[(0.10, 0.34), (0.62, 0.30)], [(0.08, 0.28), (0.52, 0.30), (0.98, 0.26)],
             [(0.12, 0.46), (0.80, 0.22)]][m.var]
    f_mean = [540.0, 600.0, 500.0][m.var]
    dry = np.zeros(n)
    for t0, ln in calls:
        k = int(ln * SR)
        tl = tvec(k)
        u = tl / ln
        f0 = f_mean * (1.08 - 0.22 * u + 0.12 * np.sin(np.pi * u)) * (1 + 0.05 * ctrl(rng, k, 70))
        ph = np.cumsum(f0) / SR
        idx = np.nonzero(np.diff(np.floor(ph)))[0]
        exc = np.zeros(k)
        exc[idx] = np.where(np.arange(len(idx)) % 2, 0.6, 1.0) * rng.uniform(0.7, 1.0, len(idx))
        exc += 0.15 * hp(rng.standard_normal(k), 1000)
        voiced = sum(g * resonator(exc, F * rng.uniform(0.95, 1.05), q)
                     for F, q, g in ((1150, 6, 1.0), (1850, 7, 0.8), (2900, 8, 0.5), (4100, 8, 0.25)))
        e = np.clip(tl / 0.025, 0, 1) * np.clip((ln - tl) / 0.06, 0, 1) * (1 + 0.25 * ctrl(rng, k, 30))
        add(dry, voiced * e, int(t0 * SR))
    dry = hp(lp(dry, 2800), 500)
    wet = reverb(dry, make_ir(rng, 1.4, predelay=0.03, hf_ratio=0.35))
    return 0.5 * dry + 0.6 * wet / (np.std(wet) / np.std(dry) + 1e-9) * 0.6


def os_radio_tune_sweep(rng, n, m):
    t = tvec(n)
    level = 0.6 + 0.25 * ctrl(rng, n, 6)
    y = np.zeros(n)
    duck = np.ones(n)
    for tk in np.array([0.35, 0.8, 1.15]) + rng.uniform(-0.04, 0.04, 3):
        wk = np.exp(-0.5 * ((t - tk) / 0.05) ** 2)
        duck *= 1 - 0.5 * wk
        y += 0.9 * bp(rng.standard_normal(n), 300, 2800) * np.clip(0.5 + 0.5 * ctrl(rng, n, 7), 0, 1.5) * wk
        f = 40 + 2600 * np.abs(t - tk) / 0.12
        y += 0.12 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-0.5 * ((t - tk) / 0.035) ** 2)
    y += bp(pink(rng, n), 250, 3800, order=4) * 0.5 * level * duck
    y += 0.02 * bp(rng.standard_normal(n), 2000, 6000)
    return y * np.clip(t / 0.03, 0, 1) * np.clip((t[-1] - t) / 0.08, 0, 1)


def os_transmitter_powerup(rng, n, m):
    t = tvec(n)
    dur = n / SR
    relays = [0.20, 0.85, 1.45, 2.15, 2.85, 3.60, 4.40]
    target = np.zeros(n)
    for k, tk in enumerate(relays):
        target += (t >= tk) * (0.5 + 0.15 * k)
    lvl = one_pole_smooth(target, 0.35)
    lvl /= lvl.max()
    y = 0.5 * mains_hum(rng, t) * lvl
    ts = thin(rng, dur, 250.0, lambda x: 250.0 * np.interp(x, t, lvl) ** 2)
    y += granular(rng, n, ts, np.exp(rng.normal(0, 0.5, len(ts))) * 0.08, grain_kernels(rng, [3000, 5000, 7500]))
    y += 0.03 * bp(rng.standard_normal(n), 3000, 9000) * lvl
    y += 0.04 * bp(pink(rng, n), 150, 7000)  # equipment room air, present before the first relay
    for k, tk in enumerate(relays):
        add(y, relay_clunk(rng, size=[0.8, 1.0, 0.9, 1.1, 0.85, 1.2, 1.4][k]) * 0.9, int(tk * SR))
    return y * np.clip((dur - t) / 0.25, 0, 1)


def _band_bank(x, edges):
    return [fft_band(x, lo, hi, width_oct=0.3) for lo, hi in zip(edges[:-1], edges[1:])]


def os_transmission_beam(rng, n, m):
    t = tvec(n)
    dur = n / SR
    edges = np.geomspace(80, 14000, 15)
    centres = np.sqrt(edges[:-1] * edges[1:])
    bands = _band_bank(rng.standard_normal(n), edges)
    rise = np.clip((t - 0.2) / 1.2, 0, 1)
    c = np.log2(500) + (np.log2(3200) - np.log2(500)) * (0.5 - 0.5 * np.cos(np.pi * rise)) + 0.3 * ctrl(rng, n, 0.8)
    y = sum(b * (np.exp(-0.5 * ((np.log2(fc) - c) / 0.9) ** 2) + 0.15) for b, fc in zip(bands, centres))
    env = np.clip(t / 0.12, 0, 1) * np.where(t < 2.6, 1.0, np.exp(-(t - 2.6) / 0.4))
    y = y / np.std(y) * 0.3 * env
    y += (lp(rng.standard_normal(n), 120) * 6 + 0.5 * np.sin(2 * np.pi * 42 * t)) * np.exp(-t / 0.2)
    ts = thin(rng, dur, 560.0, lambda x: 60 + 500 * np.interp(x, t, env))
    y += granular(rng, n, ts, np.exp(rng.normal(0, 0.6, len(ts))) * 0.12, grain_kernels(rng, [3500, 5500, 8000]))
    for ts in env_sample(rng, env, 8):
        add(y, burst(rng, 0.03, 800, 5000, 0.006) * 0.6 * rng.uniform(0.5, 1), int(ts * SR))
    return y * np.clip((dur - t) / 0.1, 0, 1)


def os_cloud_open(rng, n, m):
    t = tvec(n)
    dur = n / SR
    edges = np.geomspace(40, 16000, 15)
    centres = np.sqrt(edges[:-1] * edges[1:])
    bands = _band_bank(rng.standard_normal(n), edges)
    s = np.clip((t - 1.0) / 2.6, 0, 1)
    s = 0.5 - 0.5 * np.cos(np.pi * s)
    g = 0.7 + 0.3 * ctrl(rng, n, 0.9)
    gc = 2 ** (np.log2(3000) - (np.log2(3000) - np.log2(600)) * np.clip((t - 1.9) / 1.0, 0, 1))
    gp = 0.6 * np.exp(-0.5 * ((t - 2.4) / 0.5) ** 2)
    flick = 1 + 0.25 * s * ctrl(rng, n, 3)
    y = np.zeros(n)
    for b, fc in zip(bands, centres):
        if fc < 500:
            gain = (1 - 0.85 * s) * 1.6
        elif fc < 2000:
            gain = 0.8 - 0.4 * s
        else:
            gain = (0.35 + 1.4 * s * (1 - s)) * flick
        gain = gain * g + gp * np.exp(-0.5 * ((np.log2(fc) - np.log2(gc)) / 0.8) ** 2)
        y += b * gain * (fc / 400) ** -0.25
    y *= (1 - 0.55 * s)
    return y * np.clip(t / 0.15, 0, 1) * np.clip((dur - t) / 0.4, 0, 1)


def os_transmission_complete(rng, n, m):
    t = tvec(n)
    tc = 0.75
    gate = np.where(t < tc, 1.0, np.exp(-(t - tc) / 0.022))
    y = 0.5 * mains_hum(rng, t) * gate * np.clip(t / 0.05, 0, 1)
    y += 0.03 * bp(rng.standard_normal(n), 3000, 9000) * np.where(t < tc, 1.0, np.exp(-(t - tc) / 0.01))
    k = relay_clunk(rng, size=1.8, dur=0.8)
    k += 0.8 * burst(rng, 0.8, 40, 300, 0.04) / 0.25
    k[int(0.011 * SR):] += 0.3 * relay_clunk(rng, size=1.2, dur=0.8)[:len(k) - int(0.011 * SR)]
    clunk = np.zeros(n)
    add(clunk, k, int(tc * SR))
    y += clunk + 0.35 * reverb(clunk, make_ir(rng, 1.1, predelay=0.008)) * 3
    return y


# =========================================================================== registry

@dataclass(frozen=True)
class Meta:
    var: int = 0
    seam: float | None = None


@dataclass(frozen=True)
class Sound:
    id: str
    duration: float
    seed: int
    make: Callable
    category: str
    use: str
    atten_m: float | None
    loop: bool = False
    var: int = 0
    variations_of: str | None = None
    tonal: str | None = None  # None, "hum", "brief" or "hum+brief"
    tonal_reason: str = ""

    @property
    def file(self) -> str:
        return f"{self.id}.wav"


def _vars(base, durs, seed, make, category, use, atten, tonal=None, reason=""):
    return [Sound(f"{base}_{i + 1:02d}", d, seed + i, make, category, use, atten, var=i,
                  variations_of=base, tonal=tonal, tonal_reason=reason) for i, d in enumerate(durs)]


SOUNDS: list[Sound] = [
    Sound("SFX_Spot_WaterTrickle_Loop", 30.0, 7101, loop_water_trickle, "spot_loop",
          "Thin trickle from a broken channel or cracked pipe; waterworks and settlement gutters.", 12.0, True),
    Sound("SFX_Spot_Drip_Loop", 36.0, 7102, loop_drip, "spot_loop",
          "Irregular drips in a stone chamber with its own reverb; cisterns, culverts, reservoir galleries.", 15.0, True,
          tonal="brief", tonal_reason="a single drop's bubble plink ringing in the chamber reverb (< 1 s, new pitch each drop)"),
    Sound("SFX_Spot_ClothFlutter_Loop", 28.0, 7103, loop_cloth_flutter, "spot_loop",
          "Torn banner or tarp flapping in wind; settlement frames, abandoned camps.", 15.0, True),
    Sound("SFX_Spot_PipeWind_Loop", 32.0, 7104, loop_pipe_wind, "spot_loop",
          "Wind across a broken ceramic pipe mouth, low unsteady whistle in gusts; settlement pipe runs.", 20.0, True,
          tonal="brief", tonal_reason="pipe edge-tone whistle, only in gust peaks, wandering 210-260 Hz"),
    Sound("SFX_Spot_Insects_Loop", 30.0, 7105, loop_insects, "spot_loop",
          "Sparse dry insect ticks in grass; valley verges and warm stone walls.", 10.0, True),
    Sound("SFX_Spot_ReedRustle_Loop", 30.0, 7106, loop_reed_rustle, "spot_loop",
          "A stand of tall reeds moving in wind; valley wet ground, reservoir margins.", 18.0, True),
    Sound("SFX_Radio_Static_Bed_Loop", 24.0, 7107, loop_radio_static_bed, "radio",
          "Soft AM static bed under the idle radio lines (2D or attached to the capsule radio).", None, True),
    *_vars("SFX_SheetMetal_Bang", [1.6, 1.4, 1.9], 7201, os_sheet_metal, "ruin_oneshot",
           "Loose roof or wall sheet flapping into its frame; settlement sheds and transfer yards.", 35.0,
           tonal="brief", reason="metal plate modal ring, decays in < 1 s"),
    *_vars("SFX_Chain_Rattle", [1.3, 1.8, 1.1], 7211, os_chain_rattle, "ruin_oneshot",
           "Hanging chain knocked by wind; pulley gantries and transfer yards.", 20.0,
           tonal="brief", reason="small link modal rings, each < 60 ms"),
    *_vars("SFX_Wood_Creak", [1.8, 2.2, 2.6, 2.0], 7221, os_wood_creak, "ruin_oneshot",
           "01-02 door creaks, 03-04 beam groans; timber sheds, pulley frames, walkways.", 18.0,
           tonal="brief", reason="stick-slip pulse train with jittered rate"),
    *_vars("SFX_Pulley_Squeak", [1.1, 1.5], 7231, os_pulley_squeak, "ruin_oneshot",
           "Seized pulley wheel turning a little in wind; settlement pulley towers.", 25.0,
           tonal="brief", reason="axle friction squeal, chirps < 0.5 s"),
    *_vars("SFX_Stone_Settle", [0.9, 1.0, 1.2], 7241, os_stone_settle, "ruin_oneshot",
           "Small stone shifting and settling; any ruin wall, road cuttings, waterworks steps.", 15.0),
    *_vars("SFX_Gravel_Trickle", [2.6, 3.2, 2.2], 7251, os_gravel_trickle, "ruin_oneshot",
           "Loose gravel sliding down a slope; road cuttings, spoil heaps, reservoir banks.", 25.0),
    *_vars("SFX_Reed_Push", [0.9, 1.2, 0.7, 1.3], 7261, os_reed_push, "foliage_push",
           "Player body pushing through tall reeds or grass (foliage-push system); 04 is the slow careful push.", 8.0),
    *_vars("SFX_Crow_Distant", [1.4, 1.6, 1.4], 7271, os_crow_distant, "wildlife",
           "Distant crow-like caw, very sparse, valley and settlement only.", 120.0,
           tonal="brief", reason="animal call (voiced), < 0.5 s per caw"),
    Sound("SFX_Radio_Tune_Sweep", 1.5, 7301, os_radio_tune_sweep, "radio",
          "Dial sweep through static before a radio line (2D).", None,
          tonal="brief", tonal_reason="heterodyne zero-beat squeaks < 80 ms each"),
    Sound("SFX_Transmitter_PowerUp", 6.0, 7302, os_transmitter_powerup, "ending",
          "Summit: relays closing in sequence, mains hum swelling; hand off to AMB_Transmitter_Electrical.", 40.0,
          tonal="hum+brief", tonal_reason="50 Hz mains transformer hum, constant pitch; relay contact rings < 0.1 s"),
    Sound("SFX_Transmission_Beam", 4.0, 7303, os_transmission_beam, "ending",
          "Summit: the transmission itself, airy high-energy whoosh with crackle.", 80.0),
    Sound("SFX_Cloud_Open", 5.0, 7304, os_cloud_open, "ending",
          "Cloud band: the wind shifting and thinning as the cloud parts (2D or large radius).", 150.0),
    Sound("SFX_Transmission_Complete", 3.0, 7305, os_transmission_complete, "ending",
          "Summit: heavy relay clunk, hum cuts to silence; the end of the transmission.", 40.0,
          tonal="hum+brief", tonal_reason="50 Hz mains hum before the cut; relay contact ring < 0.1 s"),
]


# =========================================================================== render

def _fades(n, fade_s):
    k = min(int(round(fade_s * SR)), n // 2)
    r = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    g = np.ones(n)
    g[:k] *= r
    g[n - k:] *= r[::-1]
    return g


def finalise_oneshot(x):
    x = hp(x, 25)
    g = _fades(len(x), EDGE_FADE_S)
    x = x * g
    x = x - g * (x.sum() / g.sum())
    x = x * (10 ** (ONESHOT_PEAK_DBFS / 20) / np.max(np.abs(x)))
    return np.round(x * PCM_SCALE).astype("<i2")


def finalise_loop(x, pre, L, X):
    x = hp(x, 25)
    body = x[:, pre:pre + L].copy()
    tail = x[:, pre + L:pre + L + X]
    u = (np.arange(X) + 0.5) / X
    body[:, :X] = body[:, :X] * np.sin(0.5 * np.pi * u) + tail * np.cos(0.5 * np.pi * u)
    body -= body.mean(axis=1, keepdims=True)
    body *= 10 ** (LOOP_PEAK_DBFS / 20) / np.max(np.abs(body))
    return np.round(body * PCM_SCALE).astype("<i2")


def render(s: Sound) -> np.ndarray:
    rng = np.random.default_rng(s.seed)
    if s.loop:
        pre, L, X = int(LOOP_PREROLL_S * SR), int(round(s.duration * SR)), int(LOOP_XFADE_S * SR)
        x = s.make(rng, pre + L + X, Meta(seam=(pre + L) / SR))
        return finalise_loop(x, pre, L, X)
    return finalise_oneshot(s.make(rng, int(round(s.duration * SR)), Meta(var=s.var)))


def write_wav(path: Path, pcm: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    ch = 1 if pcm.ndim == 1 else pcm.shape[0]
    data = pcm if pcm.ndim == 1 else pcm.T.reshape(-1)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.ascontiguousarray(data).astype("<i2").tobytes())
    os.replace(tmp, path)


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        ch, width, rate, frames, comp = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes(), w.getcomptype()
        raw = w.readframes(frames)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, ch).T if width == 2 else None
    return x, ch, width, rate, comp


def write_manifest(out: Path) -> None:
    rows = [dict(id=s.id, file=s.file, category=s.category, loop=s.loop, duration_s=s.duration,
                 variations_of=s.variations_of, use=s.use, suggested_attenuation_m=s.atten_m)
            for s in SOUNDS]
    (out / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def generate(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for s in SOUNDS:
        pcm = render(s)
        write_wav(out / s.file, pcm)
        print(f"wrote {s.file}")
    write_manifest(out)
    print(f"wrote {out / 'manifest.json'}")


# =========================================================================== check

def db(v):
    return 20 * np.log10(v) if v > 0 else -np.inf


def tonal_profile(x, exception):
    """Per 1 s window: (prominence dB, frequency Hz) or None if the window was skipped."""
    win, seg, hop = SR, 8192, 2048
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    starts = list(range(0, len(x) - win + 1, win))
    if starts[-1] + win < len(x):
        starts.append(len(x) - win)
    rms = [np.sqrt(np.mean(x[s:s + win] ** 2)) for s in starts]
    loud = max(rms)
    f = np.fft.rfftfreq(seg, 1 / SR)
    keep = (f > TONAL_MIN_HZ) & (f < TONAL_MAX_HZ)
    if exception and "hum" in exception:
        near = np.abs(f - 50 * np.round(f / 50)) <= HUM_MASK_HZ
        keep &= ~(near & (f <= 1000))
    hann = np.hanning(seg)
    res = []
    for s, r in zip(starts, rms):
        if r <= 0 or db(r / loud) < -TONAL_SKIP_BELOW_LOUDEST_DB:
            res.append(None)
            continue
        w = x[s:s + win]
        fr = np.stack([w[i:i + seg] * hann for i in range(0, win - seg + 1, hop)])
        P = np.median(np.abs(np.fft.rfft(fr, axis=1)) ** 2, axis=0)
        tiny = 1e-12 * P.max() + 1e-20
        prom = 10 * np.log10((P + tiny) / (median_filter(P, size=31, mode="nearest") + tiny))
        live = keep & (P > P.max() * 10 ** (-TONAL_FLOOR_DB / 10))
        k = np.argmax(np.where(live, prom, -np.inf))
        res.append((prom[k], f[k]))
    return res


def check_file(s: Sound, path: Path):
    if not path.is_file():
        return ["missing"], {}
    x, ch, width, rate, comp = read_wav(path)
    p = []
    want_ch = 2 if s.loop else 1
    if rate != SR:
        p.append(f"rate {rate}")
    if width != 2:
        p.append(f"{8 * width}-bit")
    if comp != "NONE":
        p.append(f"compression {comp}")
    if ch != want_ch:
        p.append(f"{ch} ch, want {want_ch}")
    if x is None or x.shape[1] == 0:
        return p + ["no audio"], {}
    n = x.shape[1]
    r = {"dur": n / rate}
    if abs(n / rate - s.duration) > DURATION_TOL_S:
        p.append(f"duration {n / rate:.3f}s != {s.duration}")
    peak_target = LOOP_PEAK_DBFS if s.loop else ONESHOT_PEAK_DBFS
    r["peak"] = db(np.max(np.abs(x)) / FULL_SCALE)
    if abs(r["peak"] - peak_target) > PEAK_TOL_DB:
        p.append(f"peak {r['peak']:.2f} dBFS")
    mono = x.mean(axis=0)
    r["rms"] = db(np.sqrt(np.mean(x ** 2)) / FULL_SCALE)
    w100 = int(0.1 * SR)
    loud = max(np.sqrt(np.mean(mono[i:i + w100] ** 2)) for i in range(0, max(1, n - w100 + 1), w100 // 2))
    r["loud100"] = db(loud / FULL_SCALE)
    if r["loud100"] < peak_target - LOUDEST_WINDOW_BELOW_PEAK_DB or r["rms"] < MIN_FILE_RMS_DBFS:
        p.append(f"too quiet (loudest 100 ms {r['loud100']:.1f}, rms {r['rms']:.1f})")
    dc = np.max(np.abs(x.mean(axis=1))) / FULL_SCALE * 100
    if dc > MAX_DC_PERCENT:
        p.append(f"DC {dc:.3f}%")
    if s.loop:
        k = int(SEAM_WINDOW_S * SR)
        rd, jr = [], []
        for c in range(x.shape[0]):
            a, b = x[c, -k:], x[c, :k]
            rd.append(abs(db(np.sqrt(np.mean(a ** 2))) - db(np.sqrt(np.mean(b ** 2)))))
            jump = abs(x[c, 0] - x[c, -1])
            lim = np.percentile(np.abs(np.diff(x[c])), SEAM_JUMP_PERCENTILE)
            jr.append(jump / max(lim, 1.0))
        r["seam_db"], r["seam_jump"] = max(rd), max(jr)
        if r["seam_db"] > SEAM_RMS_TOL_DB:
            p.append(f"seam RMS diff {r['seam_db']:.2f} dB")
        if r["seam_jump"] > 1.0:
            p.append(f"seam jump {r['seam_jump']:.2f}x p99.9 step")
        if x.shape[0] == 2:
            r["corr"] = float(np.corrcoef(x[0], x[1])[0, 1])
            if abs(r["corr"]) >= MAX_STEREO_CORR:
                p.append(f"L/R corr {r['corr']:.2f}")
    else:
        if abs(x[0, 0]) > MAX_EDGE_LSB or abs(x[0, -1]) > MAX_EDGE_LSB:
            p.append("edges not silent")
    prof = tonal_profile(mono, s.tonal)
    vals = [v for v in prof if v is not None]
    over = [v is not None and v[0] > TONAL_MAX_DB for v in prof]
    best = max(vals, key=lambda v: v[0]) if vals else (0.0, 0.0)
    r["tonal"], r["tonal_hz"], r["tonal_over"], r["tonal_n"] = best[0], best[1], sum(over), len(prof)
    if any(over):
        run = mx = 0
        for o in over:
            run = run + 1 if o else 0
            mx = max(mx, run)
        ok = (bool(s.tonal) and "brief" in s.tonal and mx <= BRIEF_MAX_CONSECUTIVE
              and (not s.loop or sum(over) / len(over) <= BRIEF_MAX_FRACTION))
        if not ok:
            p.append(f"tonal {best[0]:.1f} dB at {best[1]:.0f} Hz in {sum(over)}/{len(over)} windows")
    return p, r


def spectrogram_sheet(out: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.mlab
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        print(f"contact sheet skipped: matplotlib unavailable ({e})")
        return
    cols = 6
    rows = int(np.ceil(len(SOUNDS) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.2, rows * 2.6), dpi=80)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, s in zip(axes.ravel(), SOUNDS):
        path = out / s.file
        if not path.is_file():
            continue
        x = read_wav(path)[0].mean(axis=0) / FULL_SCALE
        ax.axis("on")
        spec, _, _ = matplotlib.mlab.specgram(x + 1e-9, NFFT=1024, Fs=SR, noverlap=768)
        top = 10 * np.log10(spec.max() + 1e-30)
        ax.specgram(x + 1e-9, NFFT=1024, Fs=SR, noverlap=768, cmap="magma", vmin=top - 80, vmax=top)
        ax.set_ylim(0, 16000)
        ax.set_title(f"{s.id}{' (L)' if s.loop else ''}", fontsize=8)
        ax.tick_params(labelsize=6)
    fig.suptitle("Saskarta environment SFX: spectrograms, 0-16 kHz, each tile 80 dB below its own peak", fontsize=12)
    fig.tight_layout()
    fig.savefig(out / "_spectrograms.png")
    plt.close(fig)
    print(f"wrote {out / '_spectrograms.png'}")


def check(out: Path) -> bool:
    print(f"check {out}")
    print(f"  {'':4}  {'file':<34} {'ch':>2} {'dur s':>6} {'peak':>6} {'rms':>6} {'seam dB':>7} "
          f"{'jump':>5} {'corr':>5} {'tonal dB @ Hz':>15} {'over':>5} exc")
    failed = 0
    for s in SOUNDS:
        p, r = check_file(s, out / s.file)
        if not r:
            print(f"  FAIL  {s.file:<34} {'; '.join(p)}")
            failed += 1
            continue
        seam = f"{r['seam_db']:7.2f} {r['seam_jump']:5.2f} {r['corr']:5.2f}" if s.loop else f"{'-':>7} {'-':>5} {'-':>5}"
        print(f"  {'PASS' if not p else 'FAIL'}  {s.file:<34} {2 if s.loop else 1:>2} {r['dur']:6.2f} "
              f"{r['peak']:6.2f} {r['rms']:6.1f} {seam} {r['tonal']:6.1f} @ {r['tonal_hz']:6.0f} "
              f"{r['tonal_over']:>2}/{r['tonal_n']:<2} {s.tonal or ''}")
        for q in p:
            print(f"        - {q}")
        failed += bool(p)
    print(f"check: {len(SOUNDS) - failed}/{len(SOUNDS)} pass  (jump = seam step / p99.9 step, must be <= 1;"
          f" tonal limit {TONAL_MAX_DB} dB, 150 Hz-8 kHz)")
    return failed == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only re-read and check the existing files")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if not args.check:
        generate(args.out)
    ok = check(args.out)
    spectrogram_sheet(args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
