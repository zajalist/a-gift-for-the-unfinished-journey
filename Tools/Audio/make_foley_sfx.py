#!/usr/bin/env python3
"""Synthesise the Saskarta carrier / human / UI foley set (no music, physically motivated only).

Writes 48 kHz 16-bit PCM WAVs, a manifest and a spectrogram contact sheet to
<project>/Saved/GameAudio/Foley/. numpy + scipy (+ matplotlib for the sheet). Every
sound has a fixed seed, so reruns are byte-identical. Never touches Unreal.

    python Tools/Audio/make_foley_sfx.py            # generate, manifest, sheet, then check
    python Tools/Audio/make_foley_sfx.py --check    # re-read existing files and check only
    python Tools/Audio/make_foley_sfx.py --out DIR  # write somewhere else

One-shots: mono, peak -3 dBFS, 5 ms raised-cosine fades, DC removed.
Loops: stereo (channels built from independent noise/event streams, only the lowest
rumble partly shared), peak -12 dBFS, seamless: the render runs LOOP_XFADE_S (+ a 0.5 s
search margin) past the loop length; the cut point is chosen in 5 ms steps inside that
margin so the 50 ms levels either side of the seam match, and the overhang is then
equal-power crossfaded into the head, so sample N-1 flows straight into sample 0.

--check limits (all documented here, printed per file):
  format      48000 Hz, 16-bit, mono one-shot / stereo loop
  duration    within +-5 ms of the spec
  peak        one-shot -3.5..-2.5 dBFS, loop -12.5..-11.5 dBFS
  non-silent  RMS above -50 dBFS
  DC          |mean| below 0.5 % of full scale
  edges       one-shot first/last sample within 16 LSB of zero
  seam        loop: RMS of last 50 ms vs first 50 ms within 3 dB, and the wrap-around
              step |x[0] - x[-1]| no larger than the 99.9th percentile of the loop's
              own sample-to-sample steps (floor 64 LSB), i.e. the seam is no rougher
              than an ordinary sample inside the loop
  no-music    STFT, 125 ms Hann frames, 62.5 ms hop. Per frame and bin, prominence =
              level minus the median level over +-200 Hz (51 bins). A bin counts as a
              sustained tone only if it stays prominent (+-1 bin drift allowed) for
              0.5 s (8 consecutive hops). Per 1 s window the strongest sustained
              prominence above 150 Hz must stay under TONAL_LIMIT_DB (18 dB). Below
              150 Hz (mains hum, body resonances) is exempt; anything shorter than
              0.5 s (impacts, clicks, a servo whirr, a brief whistle) is exempt by
              construction and shows as "brief".
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, median_filter

SR = 48_000
ONESHOT_PEAK_DBFS = -3.0
LOOP_PEAK_DBFS = -12.0
EDGE_FADE_S = 0.005
LOOP_XFADE_S = 1.0
LOOP_SEARCH_S = 0.5  # the cut point is chosen inside this extra render so head/tail levels match
PCM_SCALE = 32767.0
FULL_SCALE = 32768.0

DURATION_TOL_S = 0.005
ONESHOT_PEAK_RANGE = (-3.5, -2.5)
LOOP_PEAK_RANGE = (-12.5, -11.5)
MIN_RMS_DBFS = -50.0
MAX_DC_PERCENT = 0.5
MAX_EDGE_LSB = 16
SEAM_RMS_DB = 3.0
SEAM_WINDOW_S = 0.05
SEAM_FLOOR_LSB = 64

TONAL_FRAME_S = 0.125
TONAL_HOP_S = 0.0625
TONAL_SUSTAIN_S = 0.5
TONAL_FMIN = 150.0
TONAL_FMAX = 16_000.0
TONAL_MEDIAN_BINS = 51
TONAL_LIMIT_DB = 18.0

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameAudio" / "Foley"


# --------------------------------------------------------------------------- DSP helpers

def n_of(d: float) -> int:
    return int(round(d * SR))


def tvec(d: float) -> np.ndarray:
    return np.arange(n_of(d)) / SR


def _sos(x, kind, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype=kind, fs=SR, output="sos"), x)


def lp(x, f, o=2):
    return _sos(x, "lowpass", f, o)


def hp(x, f, o=2):
    return _sos(x, "highpass", f, o)


def bp(x, lo, hi, o=2):
    return _sos(x, "bandpass", [lo, hi], o)


def one_pole_lp(x, fc):
    a = np.exp(-2.0 * np.pi * fc / SR)
    return signal.lfilter([1.0 - a], [1.0, -a], x)


def norm(x):
    p = np.max(np.abs(x))
    return x / p if p > 0 else x


def lfo(rng, n, fc):
    """Smooth random modulator, zero mean, unit std (never periodic)."""
    x = one_pole_lp(one_pole_lp(rng.standard_normal(n + n_of(2.0)), fc), fc)[n_of(2.0):]
    return (x - x.mean()) / (x.std() + 1e-12)


def ramp(t, start, end):
    u = np.clip((t - start) / max(end - start, 1e-9), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def place(buf, x, t0, gain=1.0):
    i = n_of(t0)
    if i >= len(buf):
        return buf
    if i < 0:
        x, i = x[-i:], 0
    m = min(len(x), len(buf) - i)
    buf[i:i + m] += gain * x[:m]
    return buf


def modal(rng, freqs, t60s, amps, dur, attack=0.0004):
    t = tvec(dur)
    out = np.zeros_like(t)
    for f, d, a in zip(freqs, t60s, amps):
        if f < 0.45 * SR:
            out += a * np.exp(-6.91 * t / d) * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    k = max(1, n_of(attack))
    out[:k] *= np.linspace(0, 1, k)
    return out


PLATE_RATIOS = np.array([1.0, 1.53, 2.08, 2.61, 3.17, 3.72, 4.39, 5.03, 5.81, 6.62, 7.40, 8.33])
BEAM_RATIOS = np.array([1.0, 2.756, 5.404, 8.933])  # free-free bar (tube / staff)


def metal_hit(rng, f0, t60, dur, n=10, hardness=7000.0, tilt=0.7, strike=0.5):
    r = PLATE_RATIOS[:n] * rng.uniform(0.97, 1.03, n)
    r[0] = 1.0
    t60s = t60 * r ** -0.6 * rng.uniform(0.75, 1.25, n)
    amps = r ** -tilt * rng.uniform(0.35, 1.0, n)
    m = norm(modal(rng, f0 * r, t60s, amps, dur))
    t = tvec(dur)
    s = norm(lp(rng.standard_normal(len(t)) * np.exp(-t / 0.0012), hardness))
    return norm(m + strike * s)


def stone_hit(rng, lo, hi, dur, n=24, t60=(0.008, 0.04), noise=0.6):
    f = np.exp(rng.uniform(np.log(lo), np.log(hi), n))
    m = norm(modal(rng, f, rng.uniform(*t60, n), rng.uniform(0.2, 1.0, n), dur))
    t = tvec(dur)
    s = norm(bp(rng.standard_normal(len(t)), lo, min(hi, 0.45 * SR)) * np.exp(-t / 0.003))
    return norm(m + noise * s)


def thud(rng, f_start, f_end, tau, dur, noise=0.4):
    t = tvec(dur)
    f = f_end + (f_start - f_end) * np.exp(-t / 0.03)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau)
    nz = norm(lp(rng.standard_normal(len(t)), 260)) * np.exp(-t / (0.5 * tau))
    x = norm(s + noise * nz)
    k = n_of(0.002)
    x[:k] *= np.linspace(0, 1, k)
    return x


def servo(rng, fcurve, env, tone_mix=0.35):
    """Gear-mesh motor whirr: a few mesh harmonics + mesh-rate-modulated gear noise + brush hiss."""
    n = len(fcurve)
    f = fcurve * (1 + 0.012 * lfo(rng, n, 25))
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(ph) + 0.5 * np.sin(2 * ph + 1.3) + 0.3 * np.sin(3 * ph + 0.4) + 0.15 * np.sin(5 * ph + 2.0)
    gear = lp(bp(rng.standard_normal(n), 400, 2800), 4000) * (1 + 0.9 * np.sin(ph))
    brush = bp(rng.standard_normal(n), 3000, 8000) * 0.08
    body = lp(rng.standard_normal(n), 400) * 0.5  # housing / gearbox body noise
    return (tone_mix * norm(tone) + (1 - tone_mix) * norm(gear + brush + body)) * env


def hiss(rng, dur, lo, hi, tau, attack=0.003):
    t = tvec(dur)
    return norm(bp(rng.standard_normal(len(t)), lo, hi) * np.exp(-t / tau) * ramp(t, 0, attack))


def grains(rng, dur, rate, f_lo, f_hi, tau_lo, tau_hi, avoid=()):
    """Granular crackle: Poisson-timed tiny damped two-partial grains. rate: scalar or per-sample array."""
    n = n_of(dur)
    out = np.zeros(n + n_of(0.06))
    rate_arr = np.broadcast_to(np.asarray(rate, dtype=float), (n,))
    rmax = float(rate_arr.max())
    times = rng.uniform(0, dur, rng.poisson(rmax * dur))
    keep = rng.uniform(0, 1, len(times)) < rate_arr[np.minimum((times * SR).astype(int), n - 1)] / max(rmax, 1e-9)
    for t0 in np.sort(times[keep]):
        if any(a <= t0 <= b for a, b in avoid):
            continue
        f = np.exp(rng.uniform(np.log(f_lo), np.log(f_hi)))
        tau = rng.uniform(tau_lo, tau_hi)
        L = int(tau * 6 * SR) + 1
        tt = np.arange(L) / SR
        g = rng.lognormal(0, 0.6) * np.exp(-tt / tau) * (
            np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * f * rng.uniform(1.3, 2.4) * tt))
        i = int(t0 * SR)
        out[i:i + L] += g[: len(out) - i]
    return out[:n]


def reverb(rng, x, rt60, wet, damp=4000.0, predelay=0.012):
    t = tvec(rt60 * 1.1)
    ir = lp(rng.standard_normal(len(t)), damp) * np.exp(-6.91 * t / rt60)
    ir[: n_of(predelay)] = 0
    ir /= np.sqrt(np.sum(ir ** 2))
    return x + wet * norm(signal.fftconvolve(x, ir)[: len(x)]) * np.max(np.abs(x))


def rng_for(seed):
    return np.random.default_rng(seed)


# --------------------------------------------------------------------------- CARRIER

STEP_THUMP_S = 0.15  # every servo step lands its hydraulic thump 150 ms after the file starts


def step_servo(i):
    rng = rng_for(100 + i)
    dur = [0.30, 0.36, 0.28, 0.40, 0.26, 0.34][i]
    t = tvec(dur)
    th = STEP_THUMP_S
    f0 = [260, 340, 300, 230, 410, 370][i] * rng.uniform(0.96, 1.04)
    rise = 1 - np.exp(-t / rng.uniform(0.03, 0.06))
    sag = np.where(t > th, np.exp(-(t - th) / 0.05), 1.0)
    fcurve = f0 * (0.5 + 0.5 * rise) * (0.55 + 0.45 * sag)
    env = ramp(t, 0, 0.015) * np.where(t > th, np.exp(-(t - th) / rng.uniform(0.025, 0.07)), 1.0)
    x = rng.uniform(0.35, 0.7) * servo(rng, fcurve, env, tone_mix=rng.uniform(0.15, 0.4))
    x = place(x, thud(rng, rng.uniform(75, 115), rng.uniform(36, 50), rng.uniform(0.04, 0.08), dur - th), th,
              rng.uniform(0.85, 1.0))
    if i % 3 != 2:  # valve bleed after the stroke on most variations
        x = place(x, hiss(rng, 0.1, 1800, 7000, rng.uniform(0.015, 0.035)), th + rng.uniform(0.01, 0.05),
                  rng.uniform(0.08, 0.22))
    x = place(x, metal_hit(rng, rng.uniform(1400, 2600), 0.02, 0.06, n=5), 0.004, rng.uniform(0.06, 0.18))
    if i in (1, 4):  # linkage knock right at contact
        x = place(x, metal_hit(rng, rng.uniform(500, 800), 0.05, 0.12, n=6), th + 0.004, 0.25)
    return x


def foot_plate(i):
    rng = rng_for(200 + i)
    dur = 0.35
    f0 = [310, 385, 262, 430][i]
    x = metal_hit(rng, f0, rng.uniform(0.10, 0.18), dur, hardness=[6000, 9000, 4500, 8000][i], tilt=0.6)
    x = x * (0.35 + 0.65 * np.exp(-tvec(dur) / 0.04))  # extra damping: plate is under load
    x += 0.8 * thud(rng, rng.uniform(95, 130), rng.uniform(50, 65), 0.05, dur)
    x += 0.25 * norm(grains(rng, dur, 900 * np.exp(-tvec(dur) / 0.03), 1500, 6000, 0.001, 0.004))
    if i in (1, 3):  # plate rocks and taps a second time
        x = place(x, metal_hit(rng, f0 * 1.07, 0.06, 0.2), rng.uniform(0.03, 0.05), 0.35)
    return x


def loop_stereo(builder, seed, dur):
    """Build each channel from its own rng; builder(rng, render_dur, shared) returns one channel."""
    full = dur + LOOP_XFADE_S + LOOP_SEARCH_S
    shared_rng = rng_for(seed)
    shared = {"rumble": lp(shared_rng.standard_normal(n_of(full) + n_of(1.0)), 110, 2)[n_of(1.0):],
              "mod": lfo(shared_rng, n_of(full), 0.4)}
    return np.stack([builder(rng_for(seed * 10 + c), full, shared, dur) for c in (1, 2)])


def seam_avoid(dur, pad=0.15):
    return ((0.0, pad), (dur - pad, dur + pad))


def _servo_idle(rng, full, shared, dur):
    n = n_of(full)
    t = np.arange(n) / SR
    hum = (np.sin(2 * np.pi * 50 * t + rng.uniform(0, 6)) + 0.6 * np.sin(2 * np.pi * 100 * t + 1.1)) \
        * (1 + 0.15 * lfo(rng, n, 0.2))
    air = norm(lp(rng.standard_normal(n), 1400)) * (1 + 0.3 * lfo(rng, n, 0.15))
    hold = norm(bp(rng.standard_normal(n), 2000, 5500)) * (0.6 + 0.4 * np.clip(lfo(rng, n, 0.3), -1, 1))
    x = 0.12 * norm(hum) + 0.35 * air + 0.07 * hold
    avoid = seam_avoid(dur)
    tc = rng.uniform(0.3, 1.6)
    while tc < full - 0.3:  # micro-corrections: brief, random pitch servo nudges
        if not any(a <= tc <= b + 0.2 for a, b in avoid):
            d = rng.uniform(0.06, 0.16)
            tt = tvec(d)
            f = rng.uniform(180, 420) * (1 + 0.3 * tt / d)
            x = place(x, servo(rng, f, np.sin(np.pi * tt / d) ** 2, 0.2), tc, rng.uniform(0.25, 0.45))
        if rng.random() < 0.4 and not any(a <= tc + 0.4 <= b for a, b in avoid):
            x = place(x, metal_hit(rng, rng.uniform(1800, 3200), 0.03, 0.08, n=5), tc + 0.4, rng.uniform(0.08, 0.18))
        tc += rng.uniform(1.4, 3.8)
    return x


def servo_idle_loop():
    return loop_stereo(_servo_idle, 300, 20.0)


def _tow(rng, full, shared, dur, surface):
    n = n_of(full)
    gravel = surface == "gravel"
    rum = 0.45 * norm(shared["rumble"]) + 0.55 * norm(lp(rng.standard_normal(n), 110 if gravel else 85))
    rum *= 1 + 0.3 * (0.6 * shared["mod"] + 0.4 * lfo(rng, n, 0.5))
    x = (0.55 if gravel else 0.7) * norm(rum)
    if gravel:
        grind = norm(bp(rng.standard_normal(n), 250, 900)) * (1 + 0.5 * lfo(rng, n, 8))
        rate = 330 * np.clip(1 + 0.35 * lfo(rng, n, 0.6), 0.3, 2.0)
        crunch = norm(grains(rng, full, rate, 1200, 6500, 0.0015, 0.006))
        x += 0.12 * grind + 0.45 * crunch
        pop_rate, pop_band, pop_gain = 1.6, (1500, 4200), 0.55
    else:
        drag = norm(bp(rng.standard_normal(n), 150, 650)) * np.clip(1 + 0.35 * lfo(rng, n, 1.5), 0.2, 3)
        rate = 70 * np.clip(1 + 0.4 * lfo(rng, n, 0.5), 0.2, 2.0)
        crumbs = norm(grains(rng, full, rate, 600, 2600, 0.003, 0.012))
        x += 0.35 * drag + 0.25 * crumbs
        pop_rate, pop_band, pop_gain = 0.6, (900, 2400), 0.3
    avoid = seam_avoid(dur)
    for t0 in rng.uniform(0, full - 0.2, rng.poisson(pop_rate * full)):
        if any(a <= t0 <= b for a, b in avoid):
            continue
        if gravel and rng.random() < 0.8:
            ev = stone_hit(rng, *pop_band, 0.12, n=6, t60=(0.01, 0.04))
        else:  # clod / chassis knock
            ev = thud(rng, rng.uniform(120, 200), rng.uniform(70, 110), rng.uniform(0.02, 0.05), 0.15, noise=0.8)
        x = place(x, ev, t0, pop_gain * rng.uniform(0.3, 1.0))
    return x


def tow_gravel_loop():
    return loop_stereo(lambda r, f, s, d: _tow(r, f, s, d, "gravel"), 400, 30.0)


def tow_dirt_loop():
    return loop_stereo(lambda r, f, s, d: _tow(r, f, s, d, "dirt"), 500, 30.0)


def capsule_scrape_failing():
    rng = rng_for(600)
    dur = 3.0
    n = n_of(dur)
    t = tvec(dur)
    # irregular surges: drags, catches, drops out, lurches again, gives up
    surge = ramp(t, 0.0, 0.25) * (1 - 0.85 * (ramp(t, 1.05, 1.15) - ramp(t, 1.35, 1.55))) * (1 - ramp(t, 2.45, 2.95))
    surge *= np.clip(1 + 0.4 * lfo(rng, n, 2.5), 0.2, 2.0)
    # stick-slip pulses at jittered, never-periodic intervals
    ss = np.zeros(n)
    tc = 0.0
    while tc < dur:
        ss = place(ss, np.exp(-tvec(0.03) / rng.uniform(0.004, 0.012)), tc, rng.uniform(0.3, 1.0))
        tc += rng.uniform(0.008, 0.045)
    exc = bp(rng.standard_normal(n), 300, 5000) * (0.4 + ss) * surge
    ir = metal_hit(rng, 410, 0.05, 0.12, n=8, strike=0.0)
    ring = norm(signal.fftconvolve(exc, ir)[:n])
    grit = norm(grains(rng, dur, 700 * surge / surge.max(), 1500, 7000, 0.001, 0.004))
    low = norm(lp(rng.standard_normal(n), 180)) * surge
    # starving motor: sagging pitch with dropouts
    f = 300 * (1 - 0.4 * t / dur) * (1 + 0.05 * lfo(rng, n, 4))
    gate = (lfo(rng, n, 6) > -0.2).astype(float)
    gate = one_pole_lp(gate, 40)
    motor = servo(rng, f, gate * (1 - ramp(t, 2.2, 2.9)) * ramp(t, 0, 0.05), 0.25)
    x = 0.45 * norm(exc) + 0.35 * ring + 0.3 * grit + 0.4 * low + 0.22 * motor
    return reverb(rng, x, 0.5, 0.15)


def carrier_collapse():
    rng = rng_for(700)
    dur = 2.5
    t = tvec(dur)
    x = np.zeros(len(t))
    # joints give out: servos wind down, frame groans
    d = 0.3
    tt = tvec(d)
    x = place(x, servo(rng, 60 + 360 * np.exp(-tt / 0.08), np.exp(-tt / 0.1) * ramp(tt, 0, 0.01), 0.3), 0.0, 0.35)
    x = place(x, norm(bp(rng.standard_normal(n_of(d)), 90, 400)) * np.sin(np.pi * tt / d), 0.0, 0.25)
    # knee hits stone
    x = place(x, metal_hit(rng, 140, 0.35, 1.2, hardness=5000), 0.22, 0.7)
    x = place(x, stone_hit(rng, 700, 5000, 0.3), 0.22, 0.5)
    x = place(x, thud(rng, 70, 38, 0.12, 0.6), 0.22, 0.8)
    # body slams down
    x = place(x, metal_hit(rng, 95, 0.5, 1.6, hardness=4000), 0.50, 1.0)
    x = place(x, metal_hit(rng, 232, 0.3, 1.0, hardness=6000), 0.507, 0.6)
    x = place(x, stone_hit(rng, 400, 4000, 0.4, n=30), 0.50, 0.7)
    x = place(x, thud(rng, 60, 28, 0.16, 0.9), 0.50, 1.0)
    x = place(x, grains(rng, 0.8, 1500 * np.exp(-tvec(0.8) / 0.15), 1500, 7000, 0.001, 0.005), 0.5, 0.25)
    # tow bar jolts against the capsule hitch
    x = place(x, metal_hit(rng, 262, 0.2, 0.6), 0.86, 0.45)
    x = place(x, thud(rng, 110, 60, 0.05, 0.3), 0.86, 0.3)
    # settling: a loose part bounces (shortening intervals), a panel rattles, grit trickles
    tb, gap, amp = 1.02, 0.2, 0.35
    while gap > 0.012 and tb < 2.3:
        x = place(x, metal_hit(rng, rng.uniform(950, 1350), 0.08, 0.25, n=8), tb, amp)
        tb += gap
        gap *= 0.72
        amp *= 0.8
    for tr in np.sort(rng.uniform(1.1, 1.8, 7)):
        x = place(x, metal_hit(rng, rng.uniform(420, 560), 0.05, 0.2, n=6), tr, rng.uniform(0.05, 0.15))
    x = place(x, grains(rng, 1.3, 220 * np.exp(-tvec(1.3) / 0.5), 1200, 6000, 0.001, 0.004), 1.0, 0.12)
    x = place(x, metal_hit(rng, 118, 0.3, 0.5, hardness=2500), 1.95, 0.25)
    return reverb(rng, x, 0.8, 0.25)


def carrier_dock_clamp():
    rng = rng_for(800)
    dur = 1.0
    x = np.zeros(n_of(dur))
    d = 0.36
    tt = tvec(d)
    f = 170 + 90 * np.sin(np.pi * tt / d * 0.9)
    x = place(x, servo(rng, f, ramp(tt, 0, 0.03) * (1 - ramp(tt, 0.3, 0.36)), 0.3), 0.0, 0.4)
    x = place(x, metal_hit(rng, 210, 0.25, 0.6, hardness=6000), 0.33, 0.9)
    x = place(x, metal_hit(rng, 251, 0.2, 0.5, hardness=6000), 0.342, 0.7)
    x = place(x, thud(rng, 85, 48, 0.07, 0.4), 0.33, 0.8)
    for tc in (0.40, 0.455):
        x = place(x, metal_hit(rng, rng.uniform(1700, 2000), 0.03, 0.08, n=6), tc, 0.3)
    x = place(x, hiss(rng, 0.3, 1500, 6000, 0.08), 0.5, 0.25)
    x = place(x, thud(rng, 140, 80, 0.03, 0.15, noise=0.9), 0.5, 0.2)
    return reverb(rng, x, 0.35, 0.15)


def carrier_reconnect():
    rng = rng_for(900)
    dur = 1.2
    x = np.zeros(n_of(dur))
    tc = 0.02
    for gap in (0.07, 0.05, 0.09, 0.04, 0.06, 0.0):
        x = place(x, metal_hit(rng, rng.uniform(2200, 3500), 0.02, 0.05, n=6, strike=0.9), tc, rng.uniform(0.35, 0.55))
        if rng.random() < 0.5:  # contact bounce
            x = place(x, metal_hit(rng, rng.uniform(2200, 3500), 0.012, 0.03, n=4), tc + 0.003, 0.15)
        tc += gap
    tt = tvec(0.22)
    x = place(x, (np.sin(2 * np.pi * 100 * tt) + 0.4 * np.sign(np.sin(2 * np.pi * 100 * tt))) * np.sin(np.pi * tt / 0.22) ** 2,
              0.34, 0.08)  # coil energise buzz, 100 Hz (below the tonal band)
    d = 0.72
    tt = tvec(d)
    f = 40 + 480 * (1 - np.exp(-tt / 0.22))
    env = ramp(tt, 0, 0.25) * (1 - ramp(tt, 0.5, 0.72))
    x = place(x, servo(rng, f, env, 0.3), 0.45, 0.45)
    x = place(x, metal_hit(rng, 1900, 0.03, 0.08, n=6), 1.12, 0.3)
    return x


# --------------------------------------------------------------------------- HUMAN

def aid_tap_stone(i):
    rng = rng_for(1000 + i)
    dur = 0.35
    x = norm(stone_hit(rng, 1500, 7000, dur, n=18, t60=(0.006, 0.025), noise=[0.5, 0.8, 0.4, 0.7][i]))
    x += 0.5 * metal_hit(rng, [1850, 2300, 2050, 2600][i], 0.04, dur, n=6)
    f0 = [520, 610, 470, 680][i]
    x += 0.3 * norm(modal(rng, f0 * BEAM_RATIOS, [0.09, 0.05, 0.03, 0.02], [1, 0.6, 0.35, 0.2], dur))
    x += 0.15 * thud(rng, 260, 180, 0.02, dur)
    if i == 1:  # tip skids after the tap
        x = place(x, hiss(rng, 0.08, 2000, 8000, 0.03, attack=0.02), 0.03, 0.2)
    if i == 3:  # double tap (bounce)
        x = place(x, stone_hit(rng, 1800, 7000, 0.1, n=10, t60=(0.005, 0.015)), 0.045, 0.3)
    return x


def aid_tap_gravel(i):
    rng = rng_for(1100 + i)
    dur = 0.4
    t = tvec(dur)
    x = 0.8 * thud(rng, rng.uniform(190, 260), rng.uniform(120, 160), 0.025, dur, noise=0.8)
    burst = [0.06, 0.09, 0.05, 0.12][i]
    x += 0.7 * norm(grains(rng, dur, 2200 * np.exp(-t / burst) * ramp(t, 0, 0.004), 1200, 6500, 0.001, 0.005))
    x += 0.12 * norm(modal(rng, [560, 540, 600, 500][i] * BEAM_RATIOS, [0.05, 0.03, 0.02, 0.01], [1, .5, .3, .2], dur))
    for _ in range(i % 3):  # a couple of displaced pebbles settling
        x = place(x, stone_hit(rng, 2000, 6000, 0.05, n=5, t60=(0.005, 0.015)), rng.uniform(0.12, 0.3), 0.25)
    return x


def cloth_rustle(i):
    rng = rng_for(1200 + i)
    dur = [0.55, 0.75, 0.45][i]
    t = tvec(dur)
    n = len(t)
    env = np.zeros(n)
    for c, w, a in [[(0.18, 0.3, 1.0)], [(0.15, 0.25, 0.8), (0.45, 0.35, 1.0)], [(0.2, 0.25, 1.0)]][i]:
        env += a * np.exp(-0.5 * ((t - c) / (w / 4)) ** 2)
    env *= np.clip(1 + 0.5 * lfo(rng, n, 20), 0.1, 3)
    swish = norm(bp(rng.standard_normal(n), 900, 7000)) * env
    body = norm(bp(rng.standard_normal(n), 250, 1200)) * env
    crackle = norm(grains(rng, dur, 1200 * env / env.max(), 2500, 9000, 0.0003, 0.0012))
    return 0.6 * swish + 0.3 * body + 0.35 * crackle


def capsule_hatch_open():
    rng = rng_for(1300)
    dur = 2.0
    n = n_of(dur)
    t = tvec(dur)
    x = np.zeros(n)
    x = place(x, hiss(rng, 0.4, 900, 9000, 0.07, attack=0.002), 0.0, 0.7)  # seal pressure equalises
    x = place(x, thud(rng, 130, 60, 0.03, 0.2), 0.0, 0.5)
    tp = tvec(0.1)
    x = place(x, grains(rng, 0.1, 2500 * np.sin(np.pi * tp / 0.1), 1500, 7000, 0.0005, 0.002), 0.1, 0.25)  # gasket peel
    # hinge creak: stick-slip pulse train with jittered spacing through a few body resonances
    pulses = np.zeros(n)
    tc = 0.22
    while tc < 1.45:
        pulses[n_of(tc)] += rng.uniform(0.5, 1.0)
        rate = 22 + 30 * ramp(np.array([tc]), 0.22, 1.2)[0] + 6 * rng.standard_normal()
        tc += (1.0 / max(rate, 12)) * rng.uniform(0.8, 1.2)
    creak = sum(g * bp(pulses, fc * 0.9, fc * 1.1) for fc, g in ((620, 1.0), (1150, 0.7), (1900, 0.5), (2800, 0.3)))
    creak = norm(creak) * ramp(t, 0.2, 0.35) * (1 - ramp(t, 1.3, 1.48)) * (0.7 + 0.3 * lfo(rng, n, 3))
    swing = norm(bp(rng.standard_normal(n), 120, 600)) * np.exp(-0.5 * ((t - 0.95) / 0.3) ** 2)
    x += 0.45 * creak + 0.3 * swing
    x = place(x, metal_hit(rng, 172, 0.3, 0.45, hardness=5000), 1.55, 0.9)  # swings onto its stop
    x = place(x, thud(rng, 75, 45, 0.08, 0.45), 1.55, 0.8)
    for tr, g in ((1.63, 0.2), (1.69, 0.1)):
        x = place(x, metal_hit(rng, rng.uniform(700, 900), 0.05, 0.15, n=6), tr, g)
    return reverb(rng, x, 0.6, 0.2)


# --------------------------------------------------------------------------- UI

def ui_hover():
    rng = rng_for(1400)
    dur = 0.06
    x = metal_hit(rng, 3100, 0.012, dur, n=6, strike=0.8)
    return place(x, metal_hit(rng, 4300, 0.006, 0.02, n=4), 0.004, 0.35)


def ui_confirm():
    rng = rng_for(1500)
    dur = 0.45
    x = np.zeros(n_of(dur))
    x = place(x, metal_hit(rng, 900, 0.04, 0.15, n=8, strike=1.0), 0.0, 1.0)
    x = place(x, thud(rng, 200, 150, 0.015, 0.08, noise=0.6), 0.0, 0.6)
    x = place(x, metal_hit(rng, 1250, 0.02, 0.06, n=6), 0.006, 0.35)  # armature bounce
    d = 0.28
    tt = tvec(d)
    f = 150 + 260 * np.sin(np.pi * np.clip(tt / (0.7 * d), 0, 1) * 0.5)
    x = place(x, servo(rng, f, ramp(tt, 0, 0.02) * (1 - ramp(tt, 0.2, 0.28)), 0.3), 0.06, 0.35)
    return place(x, metal_hit(rng, 2400, 0.015, 0.04, n=5), 0.36, 0.25)


# --------------------------------------------------------------------------- catalogue

@dataclass
class Spec:
    id: str
    category: str
    duration: float
    make: Callable[[], np.ndarray]
    use: str
    atten_m: float
    loop: bool = False
    variations_of: str | None = None

    @property
    def filename(self) -> str:
        return f"{self.id}.wav"


def _vars(base, count, fn, category, durations, use, atten):
    return [Spec(f"{base}_{k + 1:02d}", category, durations[k], (lambda k=k: fn(k)), use, atten, variations_of=base)
            for k in range(count)]


SPECS: list[Spec] = [
    *_vars("SFX_Carrier_Step_Servo", 6, step_servo, "carrier", [0.30, 0.36, 0.28, 0.40, 0.26, 0.34],
           "Leg servo whirr + hydraulic thump; layered over the recorded surface footstep (thump at 150 ms).", 25),
    *_vars("SFX_Carrier_FootPlate", 4, foot_plate, "carrier", [0.35] * 4,
           "Metal foot-plate contact clank, on hard surfaces, layered with the step.", 25),
    Spec("SFX_Carrier_Servo_Idle_Loop", "carrier", 20.0, servo_idle_loop,
         "Standing idle: mains hum, cooling air, holding hiss, occasional servo micro-corrections. Play quiet.", 10, True),
    Spec("SFX_Capsule_Tow_Gravel_Loop", "carrier", 30.0, tow_gravel_loop,
         "Towed capsule rolling on gravel/old road; volume and pitch scaled by walking speed.", 35, True),
    Spec("SFX_Capsule_Tow_Dirt_Loop", "carrier", 30.0, tow_dirt_loop,
         "Towed capsule dragging over dirt/grass; volume and pitch scaled by walking speed.", 30, True),
    Spec("SFX_Capsule_Scrape_Failing", "carrier", 3.0, capsule_scrape_failing,
         "Failing final carrier: capsule grinding on stone, starving motor.", 40),
    Spec("SFX_Carrier_Collapse", "carrier", 2.5, carrier_collapse,
         "Last carrier falls onto stone: servos die, knee and body impacts, tow bar jolt, settling rattle.", 60),
    Spec("SFX_Carrier_Dock_Clamp", "carrier", 1.0, carrier_dock_clamp,
         "Carrier exchange: cradle clamp drives shut, pawls click, hydraulic lock bleeds.", 30),
    Spec("SFX_Carrier_Reconnect", "carrier", 1.2, carrier_reconnect,
         "Control handed to the next carrier: relay chain, coil buzz, servo spin-up.", 25),
    *_vars("SFX_WalkingAid_Tap_Stone", 4, aid_tap_stone, "human", [0.35] * 4,
           "Ending walk: walking-aid ferrule tip on stone / paving.", 15),
    *_vars("SFX_WalkingAid_Tap_Gravel", 4, aid_tap_gravel, "human", [0.4] * 4,
           "Ending walk: walking-aid tip into gravel.", 15),
    *_vars("SFX_Cloth_Rustle", 3, cloth_rustle, "human", [0.55, 0.75, 0.45],
           "Body/clothing movement for the human (placeholder, see weak list).", 8),
    Spec("SFX_Capsule_Hatch_Open", "human", 2.0, capsule_hatch_open,
         "Heavy capsule hatch: seal release, hinge creak, swings onto its stop (after SFX_Capsule_Latch).", 30),
    Spec("SFX_UI_Hover", "ui", 0.06, ui_hover, "Title menu hover: tiny relay tick (2D).", 0),
    Spec("SFX_UI_Confirm", "ui", 0.45, ui_confirm, "Title menu confirm: contactor clack + short servo (2D).", 0),
]


# --------------------------------------------------------------------------- render / write

def edge_fades(n, fade_s=EDGE_FADE_S):
    k = min(n_of(fade_s), n // 2)
    r = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    g = np.ones(n)
    g[:k] *= r
    g[n - k:] *= r[::-1]
    return g


def finish_oneshot(x, dur):
    n = n_of(dur)
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    x = hp(x, 25)
    x = x - x.mean()
    x = x * edge_fades(n)
    return x / np.max(np.abs(x)) * 10 ** (ONESHOT_PEAK_DBFS / 20)


def finish_loop(y, dur):
    n, k = n_of(dur), n_of(LOOP_XFADE_S)
    y = np.stack([hp(c, 25) for c in y])
    u = np.arange(k) / k
    fin, fout = np.sin(0.5 * np.pi * u), np.cos(0.5 * np.pi * u)
    w = n_of(SEAM_WINDOW_S)

    def seam_mismatch(s):
        head = y[:, s:s + w] * fin[:w] + y[:, s + n:s + n + w] * fout[:w]
        tail = y[:, s + n - w:s + n]
        return max(abs(db(np.sqrt(np.mean(h ** 2))) - db(np.sqrt(np.mean(tl ** 2)))) for h, tl in zip(head, tail))

    s = min(range(0, n_of(LOOP_SEARCH_S), n_of(0.005)), key=seam_mismatch)
    y = y[:, s:]
    out = y[:, :n].copy()
    out[:, :k] = y[:, :k] * fin + y[:, n:n + k] * fout
    out -= out.mean(axis=1, keepdims=True)
    return out / np.max(np.abs(out)) * 10 ** (LOOP_PEAK_DBFS / 20)


def render(spec: Spec) -> np.ndarray:
    raw = spec.make()
    return finish_loop(raw, spec.duration) if spec.loop else finish_oneshot(raw, spec.duration)


def write_wav(path: Path, x: np.ndarray) -> None:
    x = np.atleast_2d(x)
    pcm = np.clip(np.round(x * PCM_SCALE), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[0])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.T.tobytes())


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, ch).T.astype(float) / FULL_SCALE
    return ch, sw, sr, data


def write_manifest(out: Path) -> None:
    rows = [{"id": s.id, "file": s.filename, "category": s.category, "loop": s.loop,
             "duration_s": s.duration, "variations_of": s.variations_of, "use": s.use,
             "suggested_attenuation_m": s.atten_m} for s in SPECS]
    (out / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def contact_sheet(out: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing, no contact sheet")
        return
    cols = 4
    rows = -(-len(SPECS) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.2, rows * 2.4))
    for ax, s in zip(axes.flat, SPECS):
        _, _, _, d = read_wav(out / s.filename)
        mono = d.mean(axis=0)
        if s.loop:
            mono = mono[: n_of(8.0)]  # first 8 s of a loop is enough to read it
        with np.errstate(divide="ignore"):
            ax.specgram(mono + 1e-7, NFFT=1024, Fs=SR, noverlap=768, cmap="magma", vmin=-130, vmax=-30)
        ax.set_ylim(0, 16000)
        ax.set_title(f"{s.id}  ({s.duration:g} s{' loop, first 8 s' if s.loop else ''})", fontsize=7)
        ax.tick_params(labelsize=6)
    for ax in list(axes.flat)[len(SPECS):]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / "_spectrograms.png", dpi=110)
    plt.close(fig)


def generate(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for s in SPECS:
        write_wav(out / s.filename, render(s))
        print(f"wrote {s.filename}")
    write_manifest(out)
    contact_sheet(out)


# --------------------------------------------------------------------------- check

def db(v):
    return 20 * np.log10(max(v, 1e-12))


def sustained_tonality(x):
    """Worst sustained (>= 0.5 s) spectral-peak prominence above 150 Hz, per 1 s window.

    Returns None when the file is too short to hold a 0.5 s tone, else (worst_db, worst_hz, per_window_list)."""
    fl, hop = n_of(TONAL_FRAME_S), n_of(TONAL_HOP_S)
    K = int(round(TONAL_SUSTAIN_S / TONAL_HOP_S))
    if len(x) < fl + (K - 1) * hop:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, fl)[::hop]
    spec = np.abs(np.fft.rfft(frames * np.hanning(fl), axis=1))
    freqs = np.fft.rfftfreq(fl, 1 / SR)
    sdb = 20 * np.log10(spec + 1e-9)
    prom = sdb - median_filter(sdb, size=(1, TONAL_MEDIAN_BINS), mode="nearest")
    rms_db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-20)
    prom[rms_db < rms_db.max() - 45] = 0.0
    prom = maximum_filter1d(prom, 3, axis=1)
    band = (freqs >= TONAL_FMIN) & (freqs <= TONAL_FMAX)
    prom, bf = prom[:, band], freqs[band]
    sus = np.lib.stride_tricks.sliding_window_view(prom, K, axis=0).min(axis=-1)  # (runs, bins)
    best_bin = sus.argmax(axis=1)
    best = sus[np.arange(len(sus)), best_bin]
    win = (np.arange(len(sus)) * TONAL_HOP_S).astype(int)
    per_window = [float(best[win == w].max()) for w in np.unique(win)]
    j = int(best.argmax())
    return float(best[j]), float(bf[best_bin[j]]), per_window


def check_file(s: Spec, path: Path):
    if not path.exists():
        return ["missing"], ""
    ch, sw, sr, d = read_wav(path)
    p = []
    want_ch = 2 if s.loop else 1
    if (ch, sw, sr) != (want_ch, 2, SR):
        p.append(f"format {ch}ch/{sw * 8}bit/{sr}Hz")
    dur = d.shape[1] / sr
    if abs(dur - s.duration) > DURATION_TOL_S:
        p.append(f"duration {dur:.3f}")
    peak = db(np.max(np.abs(d)))
    lo, hi = LOOP_PEAK_RANGE if s.loop else ONESHOT_PEAK_RANGE
    if not lo <= peak <= hi:
        p.append(f"peak {peak:.2f}")
    rms = db(np.sqrt(np.mean(d ** 2)))
    if rms < MIN_RMS_DBFS:
        p.append(f"silent {rms:.1f}")
    dc = 100 * np.max(np.abs(d.mean(axis=1)))
    if dc > MAX_DC_PERCENT:
        p.append(f"DC {dc:.2f}%")
    if s.loop:
        w = n_of(SEAM_WINDOW_S)
        seam_db = max(abs(db(np.sqrt(np.mean(c[-w:] ** 2))) - db(np.sqrt(np.mean(c[:w] ** 2)))) for c in d)
        jumps = [(abs(c[0] - c[-1]) * FULL_SCALE,
                  max(np.percentile(np.abs(np.diff(c)), 99.9) * FULL_SCALE, SEAM_FLOOR_LSB)) for c in d]
        jump_ok = all(j <= lim for j, lim in jumps)
        edge = f"seam {seam_db:4.2f}dB jump {max(j for j, _ in jumps):5.0f}/{min(l for _, l in jumps):4.0f}LSB"
        if seam_db > SEAM_RMS_DB:
            p.append(f"seam RMS {seam_db:.2f} dB")
        if not jump_ok:
            p.append("seam jump")
        corr = float(np.corrcoef(d[0], d[1])[0, 1])
        edge += f" corr {corr:+.2f}"
    else:
        e = max(abs(d[0, 0]), abs(d[0, -1])) * FULL_SCALE
        edge = f"edges {e:.0f}LSB"
        if e > MAX_EDGE_LSB:
            p.append(f"edge {e:.0f} LSB")
    tonal = [sustained_tonality(c) for c in d]
    if tonal[0] is None:
        ton = "brief"
    else:
        worst = max(tonal, key=lambda r: r[0])
        ton = f"{worst[0]:5.1f}dB@{worst[1]:5.0f}Hz"
        if worst[0] >= TONAL_LIMIT_DB:
            p.append(f"tonal {worst[0]:.1f} dB at {worst[1]:.0f} Hz")
    summary = f"{ch}ch {dur:6.3f}s pk {peak:6.2f} rms {rms:6.1f} dc {dc:4.2f}% {edge:<44} tonal {ton}"
    return p, summary


def check(out: Path) -> bool:
    print(f"\ncheck {out}  (tonal limit {TONAL_LIMIT_DB} dB sustained >= {TONAL_SUSTAIN_S} s above {TONAL_FMIN:.0f} Hz)")
    failed = 0
    for s in SPECS:
        problems, summary = check_file(s, out / s.filename)
        status = "ok  " if not problems else "FAIL"
        failed += bool(problems)
        print(f"{status} {s.id:<32} {summary}" + (f"  <- {'; '.join(problems)}" if problems else ""))
    for extra in ("manifest.json", "_spectrograms.png"):
        if not (out / extra).exists():
            print(f"FAIL {extra} missing")
            failed += 1
    print(f"check: {len(SPECS) - failed}/{len(SPECS)} files pass")
    return failed == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only re-read and check existing files")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    if not a.check:
        generate(a.out)
    return 0 if check(a.out) else 1


if __name__ == "__main__":
    sys.exit(main())
