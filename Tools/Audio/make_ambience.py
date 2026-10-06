#!/usr/bin/env python3
"""Synthesise Saskarta's looping ambience beds, Geiger loops and environmental one-shots.

Everything here is environmental sound. There is no music anywhere: no instruments,
melodies, pads, drones or chords. The only steady tones are physically motivated
(mains hum below 150 Hz, a wind edge-tone whistle) and they sit low in the mix; the
``--check`` pass measures every loop for sustained tonal content and fails a bed that
has any (see ``TONAL_*`` below).

Writes 48 kHz stereo 16-bit PCM WAVs to <project>/Saved/GameAudio/Ambience/. Uses numpy
only, with a fixed seed per sound, so every run writes byte-identical files. It never
touches Unreal.

    python Tools/Audio/make_ambience.py                 # generate everything, then check
    python Tools/Audio/make_ambience.py --check         # re-read the existing files, check only
    python Tools/Audio/make_ambience.py --only AMB_Cloud_Wind SFX_Geiger_High
    python Tools/Audio/make_ambience.py --out DIR       # write somewhere else

How a loop is made seamless
  * Noise layers (wind, rustle, room tone, hiss) are rendered linearly for
    ``preroll + loop + crossfade`` seconds. The preroll is thrown away (filters and gust
    envelopes are warmed up), then the extra ``crossfade`` seconds past the loop end are
    equal-power crossfaded over the head of the loop. The last sample of the loop is
    followed, across the wrap, by exactly the sample that followed it in the linear
    render, so the seam is continuous.
  * Discrete events (knocks, caws, drips, clicks...) are placed on a circular timeline:
    an event or reverb tail that runs past the end wraps onto the start, and their
    reverb is a circular convolution. They never pass through the crossfade, so an event
    near the seam is neither doubled nor dimmed.
  * Steady tones (mains hum) are synthesised at frequencies that complete a whole number
    of cycles in the loop, so they are exactly periodic and need no crossfade.
  * The finished loop gets a circular 20 Hz high-pass (DC bin zeroed), then is rotated
    so the file boundary sits at its most stationary 10 ms-aligned point (the way an
    editor picks a cut). Rotating a seamless loop keeps it seamless.

Levels: AMB_* beds are peak-normalised to -12 dBFS, every SFX_* file (Geiger loops
included; they are transient-only) to -3 dBFS. TPDF dither on quantisation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SR = 48_000
CTRL_RATE = 200  # Hz; gust and swell envelopes are drawn at this rate, then interpolated
PCM_SCALE = 32767.0  # float -> int16 when writing
FULL_SCALE = 32768.0  # 0 dBFS reference when measuring
BED_PEAK_DBFS = -12.0
SFX_PEAK_DBFS = -3.0
EDGE_FADE_S = 0.005
PREROLL_S = 2.0
BED_XFADE_S = 4.0
GEIGER_XFADE_S = 1.0

# --check limits
DURATION_TOL_S = 0.005
PEAK_TOL_DB = 0.5
MIN_RMS_DBFS = -60.0
MAX_DC_PERCENT = 0.05
MAX_EDGE_LSB = 16  # one-shots: first/last sample (near) silent
SEAM_WINDOW_S = 0.050
SEAM_RMS_TOL_DB = 3.0
SEAM_STEP_PERCENTILE = 99.0  # seam step must be no bigger than this percentile of all steps
SEAM_STEP_FLOOR_LSB = 16

# Tonality ("could this read as music?") check, run on every loop.
# Per non-overlapping 1 s window: Welch power spectrum (4096-point Hann, hop 2048,
# ~11.7 Hz bins, both channels averaged). For each bin in 150 Hz..16 kHz, prominence =
# bin power / median power of the bins within +/-17 bins (+/-200 Hz) around it. The
# window's figure is the largest prominence, in dB. The median is local rather than
# global because wind is steeply low-passed: against a global median every bed would
# "peak" at its lowest frequencies, which measures colour, not tone. Averaged noise
# reaches about 5-7 dB by chance; a steady sine 20 dB under broadband noise reaches
# ~20 dB (the check prints this calibration). A window counts as tonal above 12 dB.
# A loop fails if its tonal windows run longer than 3 s in a row (brief whistles, a
# caw, a knock's ring are allowed) or make up more than 10% of it. Mains hum below
# 150 Hz is outside the measured band by design.
TONAL_FFT = 4096
TONAL_HOP = 2048
TONAL_MIN_HZ = 150.0
TONAL_MAX_HZ = 16_000.0
TONAL_HALF_BINS = 17
TONAL_LIMIT_DB = 12.0
TONAL_MAX_RUN_S = 3
TONAL_MAX_FRACTION = 0.10

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameAudio" / "Ambience"


# ------------------------------------------------------------------ basic helpers

def _time(duration: float) -> np.ndarray:
    return np.arange(int(round(duration * SR))) / SR


def _pow2(n: int) -> int:
    return 1 << int(np.ceil(np.log2(max(n, 2))))


def _ramp(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 before ``start``, 1 after ``end``, raised cosine in between."""
    u = np.clip((t - start) / max(end - start, 1e-9), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def set_rms(x: np.ndarray, db: float) -> np.ndarray:
    return x * (10.0 ** (db / 20.0) / max(_rms(x), 1e-12))


def set_peak(x: np.ndarray, db: float) -> np.ndarray:
    return x * (10.0 ** (db / 20.0) / max(float(np.max(np.abs(x))), 1e-12))


def _unit(x: np.ndarray) -> np.ndarray:
    """Peak-normalise an event to 1.0, so a ``place`` gain is the event's peak level."""
    return x / max(float(np.max(np.abs(x))), 1e-12)


def _phase(freq: np.ndarray) -> np.ndarray:
    """Phase (radians) of an oscillator with per-sample frequency, starting at 0."""
    return 2.0 * np.pi * (np.cumsum(freq) - freq[0]) / SR


def stereo_noise(rng: np.random.Generator, n: int, corr: float) -> np.ndarray:
    """White noise, shape (2, n), with inter-channel correlation ``corr`` (width control)."""
    common = rng.standard_normal(n)
    g, h = np.sqrt(corr), np.sqrt(1.0 - corr)
    return np.stack([g * common + h * rng.standard_normal(n), g * common + h * rng.standard_normal(n)])


# ------------------------------------------------------------------------ filters
# RBJ-cookbook biquads and one-pole sections. Applied in the frequency domain: the
# response B(z)/A(z) is evaluated on the FFT grid. With ``circular=False`` the signal is
# zero-padded so that equals running the recursion over the signal from rest (the tail
# past the end is dropped); with ``circular=True`` it is the steady-state response to
# the signal repeated forever, which is what a loop needs.

Section = tuple[np.ndarray, np.ndarray]
_Z_CACHE: dict[int, np.ndarray] = {}


def _zinv(nfft: int) -> np.ndarray:
    z = _Z_CACHE.get(nfft)
    if z is None:
        if len(_Z_CACHE) >= 4:
            _Z_CACHE.pop(next(iter(_Z_CACHE)))
        z = np.exp(-2j * np.pi * np.fft.rfftfreq(nfft))
        _Z_CACHE[nfft] = z
    return z


def biquad(kind: str, f0: float, q: float = 0.7071, gain_db: float = 0.0) -> Section:
    w0 = 2.0 * np.pi * min(f0, 0.45 * SR) / SR
    c, s = np.cos(w0), np.sin(w0)
    alpha = s / (2.0 * q)
    a = [1.0 + alpha, -2.0 * c, 1.0 - alpha]
    if kind == "lowpass":
        b = [(1.0 - c) / 2.0, 1.0 - c, (1.0 - c) / 2.0]
    elif kind == "highpass":
        b = [(1.0 + c) / 2.0, -(1.0 + c), (1.0 + c) / 2.0]
    elif kind == "bandpass":  # 0 dB peak gain
        b = [alpha, 0.0, -alpha]
    elif kind == "peak":
        big_a = 10.0 ** (gain_db / 40.0)
        b = [1.0 + alpha * big_a, -2.0 * c, 1.0 - alpha * big_a]
        a = [1.0 + alpha / big_a, -2.0 * c, 1.0 - alpha / big_a]
    else:
        raise ValueError(kind)
    b_arr, a_arr = np.array(b), np.array(a)
    return b_arr / a_arr[0], a_arr / a_arr[0]


def one_pole_lowpass(fc: float) -> Section:
    p = np.exp(-2.0 * np.pi * fc / SR)
    return np.array([1.0 - p]), np.array([1.0, -p])


def one_pole_highpass(fc: float) -> Section:
    p = np.exp(-2.0 * np.pi * fc / SR)
    return np.array([(1.0 + p) / 2.0, -(1.0 + p) / 2.0]), np.array([1.0, -p])


def response(sections: tuple[Section, ...], nfft: int) -> np.ndarray:
    z = _zinv(nfft)
    h = np.ones_like(z)
    for b, a in sections:
        h *= np.polyval(b[::-1], z) / np.polyval(a[::-1], z)
    return h


def filt(x: np.ndarray, *sections: Section, circular: bool = False) -> np.ndarray:
    n = x.shape[-1]
    nfft = n if circular else _pow2(n + SR // 2)
    return np.fft.irfft(np.fft.rfft(x, nfft) * response(sections, nfft), nfft)[..., :n]


def band(x: np.ndarray, lo: float, hi: float, q: float = 0.7071) -> np.ndarray:
    return filt(x, biquad("highpass", lo, q), biquad("lowpass", hi, q))


def smooth(x: np.ndarray, fc: float, rate: float = CTRL_RATE) -> np.ndarray:
    """Zero-phase one-pole low-pass (forward + backward recursion) for control signals."""
    p = float(np.exp(-2.0 * np.pi * fc / rate))
    y = np.asarray(x, dtype=np.float64)
    for _ in range(2):
        out = np.empty_like(y)
        acc = float(y[0])
        for i, v in enumerate(y):
            acc = (1.0 - p) * v + p * acc
            out[i] = acc
        y = out[::-1]
    return y


# ------------------------------------------------------------ envelopes and space

def ctrl_len(n: int) -> int:
    return int(np.ceil(n / SR * CTRL_RATE)) + 2


def to_audio(ctrl: np.ndarray, n: int, delay_s: float = 0.0) -> np.ndarray:
    return np.interp(np.arange(n) / SR - delay_s, np.arange(len(ctrl)) / CTRL_RATE, ctrl)


def stereo_env(ctrl: np.ndarray, n: int, delay_s: float) -> np.ndarray:
    """A gust reaches the right ear ``delay_s`` later than the left: cheap, natural width."""
    return np.stack([to_audio(ctrl, n), to_audio(ctrl, n, delay_s)])


def gust_curve(rng: np.random.Generator, n: int, *, base: float, wander: float, rate: float,
               amp: tuple[float, float], attack: tuple[float, float], decay: tuple[float, float],
               wander_fc: float = 0.03, flutter: float = 0.04) -> np.ndarray:
    """Wind intensity 0..1 at control rate: slow wander + Poisson gusts + light turbulence."""
    m = ctrl_len(n)
    t = np.arange(m) / CTRL_RATE
    slow = smooth(rng.standard_normal(m), wander_fc)
    g = base + wander * slow / max(float(np.max(np.abs(slow))), 1e-9)
    for _ in range(rng.poisson(rate * (t[-1] + 8.0))):
        t0, a, d = rng.uniform(-8.0, t[-1]), rng.uniform(*attack), rng.uniform(*decay)
        u = t - t0
        rise = np.where(u < 0.0, 0.0, np.where(u < a, 0.5 - 0.5 * np.cos(np.pi * np.clip(u / a, 0, 1)), 1.0))
        fall = np.where(u < a, 1.0, np.exp(-np.maximum(u - a, 0.0) / d))
        g = g + rng.uniform(*amp) * rise * fall
    turb = smooth(rng.standard_normal(m), 1.2)
    g = g + flutter * turb / max(float(np.max(np.abs(turb))), 1e-9)
    return np.tanh(1.25 * np.maximum(g, 0.0))


def reverb_ir(rng: np.random.Generator, rt60: float, predelay: float = 0.02,
              hf_ratio: float = 0.45, early: int = 6) -> np.ndarray:
    """Synthetic stereo impulse: sparse early taps + exponentially decaying noise whose highs
    die ``hf_ratio`` times faster than its lows (air/surface damping). Energy-normalised."""
    m = int((predelay + 1.1 * rt60) * SR)
    t = np.arange(m) / SR
    after = np.maximum(t - predelay, 0.0)
    ir = np.zeros((2, m))
    for ch in range(2):
        noise = rng.standard_normal(m)
        lo = filt(noise, one_pole_lowpass(1200.0))
        tail = 2.0 * lo * 10.0 ** (-3.0 * after / rt60) + (noise - lo) * 10.0 ** (-3.0 * after / (rt60 * hf_ratio))
        tail *= _ramp(t, predelay, predelay + 0.04)
        peak = float(np.max(np.abs(tail)))
        for _ in range(early):
            k = int(rng.uniform(0.3 * predelay + 0.002, predelay + 0.06) * SR)
            tail[k] += rng.choice((-1.0, 1.0)) * rng.uniform(0.3, 0.8) * peak
        ir[ch] = tail / np.sqrt(np.sum(tail ** 2))
    return ir


def convolve(x: np.ndarray, ir: np.ndarray, circular: bool) -> np.ndarray:
    n = x.shape[-1]
    nfft = n if circular else _pow2(n + ir.shape[-1])
    if circular and ir.shape[-1] > n:
        raise ValueError("impulse longer than the loop")
    return np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[..., :n]


def reverb(x: np.ndarray, ir: np.ndarray, wet: float, dry: float = 1.0, circular: bool = False) -> np.ndarray:
    return dry * x + wet * convolve(x, ir, circular)


def place(buf: np.ndarray, sig: np.ndarray, t_s: float, gain: float = 1.0, pan: float = 0.0,
          circular: bool = True) -> None:
    """Add a mono (panned: equal power + up to 0.6 ms interaural delay) or stereo event."""
    sig = np.asarray(sig, dtype=np.float64) * gain
    if sig.ndim == 1:
        th = (np.clip(pan, -1.0, 1.0) + 1.0) * np.pi / 4.0
        itd = int(round(abs(pan) * 0.0006 * SR))
        st = np.zeros((2, len(sig) + itd))
        far, near = (0, 1) if pan >= 0 else (1, 0)
        gains = (np.cos(th), np.sin(th))
        st[far, itd:] = sig * gains[far]
        st[near, :len(sig)] = sig * gains[near]
        sig = st
    n, m = buf.shape[1], sig.shape[1]
    start = int(round(t_s * SR))
    if circular:
        buf[:, (start + np.arange(m)) % n] += sig
    else:
        a, b = max(start, 0), min(start + m, n)
        if b > a:
            buf[:, a:b] += sig[:, a - start:b - start]


def periodic_sine(n: int, freq: float, phase: float = 0.0) -> np.ndarray:
    """Sine at the nearest frequency that fits a whole number of cycles into ``n`` samples."""
    k = max(1, int(round(freq * n / SR)))
    return np.sin(2.0 * np.pi * k * np.arange(n) / n + phase)


def irregular_times(rng: np.random.Generator, total_s: float, lo: float, hi: float) -> list[float]:
    """Event times on a circle of ``total_s`` with gaps drawn from [lo, hi] (wrap gap too)."""
    start = rng.uniform(0.0, hi)
    times, t = [], start
    while t < start + total_s - lo:
        times.append(t % total_s)
        t += rng.uniform(lo, hi)
    return times


def spaced_times(rng: np.random.Generator, total_s: float, count: int, min_gap: float,
                 weight: Callable[[float], float] | None = None) -> list[float]:
    """``count`` times on a circle at least ``min_gap`` apart, optionally weighted by ``weight``."""
    times: list[float] = []
    for _ in range(20_000):
        if len(times) == count:
            break
        t = rng.uniform(0.0, total_s)
        if weight is not None and rng.random() > weight(t):
            continue
        if all(min(abs(t - u), total_s - abs(t - u)) >= min_gap for u in times):
            times.append(t)
    return sorted(times)


# --------------------------------------------------------------------- wind parts

def wind_layer(rng: np.random.Generator, n: int, inten: np.ndarray, f_lo: float, f_hi: float, *,
               q: float = 2.0, corr: float = 0.3, bands: int = 12, sigma_oct: float = 0.45,
               amp_pow: float = 1.5, floor: float = 0.15) -> np.ndarray:
    """Moving-resonance wind: noise through a bank of fixed band-passes whose mix follows a
    centre frequency that rises with intensity (faster air, higher howl), times a level
    that rises with intensity. ``inten`` is (2, n) in 0..1."""
    white = stereo_noise(rng, n, corr)
    nfft = _pow2(n + SR // 2)
    spec = np.fft.rfft(white, nfft)
    del white
    lfc = np.log2(f_lo) + inten * np.log2(f_hi / f_lo)
    out = np.zeros((2, n))
    wsum = np.zeros((2, n))
    for c in np.geomspace(f_lo / 1.4, f_hi * 1.4, bands):
        sig = np.fft.irfft(spec * response((biquad("bandpass", c, q),), nfft), nfft)[:, :n]
        w = np.exp(-0.5 * ((np.log2(c) - lfc) / sigma_oct) ** 2)
        out += sig * w / np.sqrt(c / 200.0)  # constant-Q bands: undo the +3 dB/oct of white noise
        wsum += w * w
    out /= np.sqrt(wsum + 1e-9)
    return out * (floor + inten) ** amp_pow


def rustle(rng: np.random.Generator, n: int, inten: np.ndarray, lo: float = 2200.0, hi: float = 8000.0,
           tick_rate: float = 250.0) -> np.ndarray:
    """Dry grass/reed rustle: bright noise with fast random flutter plus a scatter of tiny
    blade ticks, both riding the gusts (roughly intensity squared/cubed)."""
    hiss = band(stereo_noise(rng, n, 0.1), lo, hi)
    m = ctrl_len(n)
    flut = np.stack([smooth(rng.standard_normal(m), 14.0) for _ in range(2)])
    flut = np.abs(flut) / np.max(np.abs(flut))
    flut_a = np.stack([to_audio(f, n) for f in flut])
    hiss *= inten ** 2.2 * (0.25 + flut_a ** 1.5)
    dens = tick_rate * inten ** 3 / SR
    ticks = (rng.random((2, n)) < dens) * rng.standard_normal((2, n))
    ticks = band(ticks, lo * 1.3, hi * 1.1)
    return set_rms(hiss, 0.0) + set_rms(ticks, -4.0)


def rumble(rng: np.random.Generator, n: int, inten: np.ndarray, fc: float = 80.0, corr: float = 0.6) -> np.ndarray:
    low = filt(stereo_noise(rng, n, corr), one_pole_lowpass(fc * 0.8), biquad("lowpass", fc, 0.7))
    return low * (0.3 + inten) ** 1.2


def narrow_noise(rng: np.random.Generator, n: int, freq: np.ndarray, bw: float) -> np.ndarray:
    """Noise ~``bw`` Hz wide centred on a moving ``freq`` (complex baseband, shifted up)."""
    base = filt(rng.standard_normal(n), one_pole_lowpass(bw / 2.0), one_pole_lowpass(bw / 2.0)) \
        + 1j * filt(rng.standard_normal(n), one_pole_lowpass(bw / 2.0), one_pole_lowpass(bw / 2.0))
    return np.real(base * np.exp(1j * _phase(freq)))


# -------------------------------------------------------------------- event sounds

def _impulse_ring(t: np.ndarray, modes: list[tuple[float, float, float]], rng: np.random.Generator) -> np.ndarray:
    return sum(g * np.sin(2.0 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau) for f, tau, g in modes)


def metal_knock(rng: np.random.Generator) -> np.ndarray:
    """Loose corrugated sheet knocking against a post, heard from far away."""
    t = _time(0.5)
    f = rng.uniform(170.0, 260.0)
    modes = [(f * r * rng.uniform(0.97, 1.03), tau, g) for r, tau, g in
             ((1.0, 0.09, 1.0), (2.32, 0.06, 0.6), (4.17, 0.035, 0.35), (6.63, 0.02, 0.2))]
    ring = _impulse_ring(t, modes, rng) * _ramp(t, 0.0, 0.001)
    hit = band(rng.standard_normal(len(t)), 300.0, 4000.0) * np.exp(-t / 0.004)
    rattle = np.roll(hit, int(rng.uniform(0.02, 0.045) * SR)) * 0.35
    sig = ring + 1.4 * (hit + rattle) / np.max(np.abs(hit))
    return _unit(filt(sig, one_pole_lowpass(1800.0), biquad("lowpass", 2600.0)))


def caw(rng: np.random.Generator, f0: float, dur: float) -> np.ndarray:
    """One harsh crow-like caw: jittery buzzy source + breath noise through beak/throat
    formants, saturated. Rough and noisy on purpose; no clean pitch."""
    t = _time(dur)
    n = len(t)
    u = t / dur
    m = int(dur * 300) + 2
    jit = np.interp(np.arange(n) / SR, np.arange(m) / 300.0, rng.standard_normal(m))
    f = f0 * (1.0 + 0.10 * np.sin(np.pi * u) - 0.16 * u) * (1.0 + 0.05 * jit)
    ph = _phase(f) / (2.0 * np.pi)
    saw = 2.0 * (ph - np.floor(ph)) - 1.0
    pulse = np.exp(-((ph - np.round(ph)) ** 2) / 0.02)
    breath = rng.standard_normal(n) * (0.35 + 0.65 * pulse)
    rough = 1.0 + 0.6 * np.sin(2.0 * np.pi * rng.uniform(55, 80) * t)
    src = (0.55 * saw + 0.9 * breath) * rough
    body = (filt(src, biquad("bandpass", rng.uniform(1050, 1250), 3.5))
            + 0.8 * filt(src, biquad("bandpass", rng.uniform(1750, 2000), 4.0))
            + 0.4 * filt(src, biquad("bandpass", rng.uniform(2700, 3100), 4.0)))
    env = _ramp(t, 0.0, 0.025) * (1.0 - _ramp(t, dur - 0.09, dur)) * (1.0 - 0.25 * u)
    sig = np.tanh(2.5 * body / np.max(np.abs(body)) * env)
    return _unit(filt(sig, one_pole_lowpass(3500.0)))  # distance


def insect_ticks(rng: np.random.Generator) -> np.ndarray:
    """A short irregular cluster of tiny dry ticks from one small insect."""
    k = int(rng.integers(2, 8))
    gaps = rng.uniform(0.05, 0.3, k)
    times = np.concatenate([[0.0], np.cumsum(gaps[:-1])])
    t = _time(times[-1] + 0.02)
    out = np.zeros(len(t))
    f = rng.uniform(4200.0, 7200.0)
    tt = _time(0.006)
    for ti in times:
        tick = np.sin(2 * np.pi * f * rng.uniform(0.98, 1.02) * tt) * np.exp(-tt / rng.uniform(0.0006, 0.0012))
        tick += 0.4 * rng.standard_normal(len(tt)) * np.exp(-tt / 0.0003)
        i = int(ti * SR)
        out[i:i + len(tt)] += tick[:len(out) - i] * rng.uniform(0.4, 1.0)
    return _unit(out)


def creak(rng: np.random.Generator, dur: float, low: bool) -> np.ndarray:
    """Wood stick-slip creak: irregular friction pulses (rate wandering 25-90 Hz) exciting
    the resonances of a beam (``low``) or a door/plank."""
    t = _time(dur)
    n = len(t)
    env = _ramp(t, 0.0, 0.2 * dur) * (1.0 - _ramp(t, 0.65 * dur, dur))
    r0 = rng.uniform(25.0, 55.0) if low else rng.uniform(45.0, 90.0)
    glide = rng.uniform(-0.35, 0.35)
    exc = np.zeros(n)
    tp = rng.uniform(0.0, 0.01)
    while tp < dur:
        i = int(tp * SR)
        exc[i] += env[i] * rng.uniform(0.4, 1.0)
        rate = r0 * (1.0 + glide * tp / dur) * (1.0 + 0.2 * np.sin(2 * np.pi * 0.7 * tp))
        tp += max(1.0 / rate * (1.0 + 0.22 * rng.standard_normal()), 0.002)
    exc += 0.05 * rng.standard_normal(n) * env
    f1 = rng.uniform(300, 420) if low else rng.uniform(450, 600)
    body = (filt(exc, biquad("bandpass", f1, 5.0))
            + 0.7 * filt(exc, biquad("bandpass", f1 * rng.uniform(2.3, 2.7), 6.0))
            + 0.4 * filt(exc, biquad("bandpass", f1 * rng.uniform(4.6, 5.4), 7.0)))
    return _unit(body)


def wood_knock(rng: np.random.Generator, f: float) -> np.ndarray:
    """Hollow wooden block (a pulley sheave, a shutter) struck once."""
    t = _time(0.25)
    exc = rng.standard_normal(len(t)) * np.exp(-t / 0.0008)
    body = (filt(exc, biquad("bandpass", f * rng.uniform(0.95, 1.05), 7.0))
            + 0.6 * filt(exc, biquad("bandpass", f * rng.uniform(2.9, 3.4), 6.0))
            + 0.35 * filt(exc, biquad("bandpass", f * rng.uniform(7.0, 8.0), 4.0)))
    return _unit(body / max(float(np.max(np.abs(body))), 1e-12) + 0.15 * exc / max(float(np.max(np.abs(exc))), 1e-12))


def drip(rng: np.random.Generator, f0: float) -> np.ndarray:
    """Water drop into a puddle: tiny impact + a bubble 'plip' whose pitch sweeps up."""
    t = _time(0.08)
    tau = rng.uniform(0.008, 0.016)
    f = f0 * rng.uniform(0.9, 1.1) * (1.0 + rng.uniform(0.7, 1.3) * t / 0.03)
    plip = np.sin(_phase(f)) * np.exp(-t / tau) * _ramp(t, 0.0, 0.0006)
    hit = rng.standard_normal(len(t)) * np.exp(-t / 0.0005)
    return _unit(plip + 0.25 * band(hit, 1500.0, 9000.0))


def shutter_burst(rng: np.random.Generator) -> np.ndarray:
    """A loose shutter tapping its frame 2-5 times as a gust catches it."""
    k = int(rng.integers(2, 6))
    times = np.concatenate([[0.0], np.cumsum(rng.uniform(0.08, 0.22, k - 1))])
    out = np.zeros(int((times[-1] + 0.3) * SR))
    for j, ti in enumerate(times):
        tap = wood_knock(rng, rng.uniform(220.0, 260.0)) * rng.uniform(0.6, 1.0) * 0.8 ** j
        i = int(ti * SR)
        out[i:i + len(tap)] += tap[:len(out) - i]
    return _unit(out)


def stone_settle(rng: np.random.Generator) -> np.ndarray:
    """Distant settling masonry: a low thud and a brief crumble of grit."""
    t = _time(2.0)
    n = len(t)
    thud = filt(rng.standard_normal(n), biquad("lowpass", 120.0, 0.8)) * np.exp(-t / 0.08) * _ramp(t, 0, 0.004)
    grit = np.zeros(n)
    for _ in range(int(rng.integers(20, 60))):
        ti = 0.05 + rng.exponential(0.35)
        if ti > 1.6:
            continue
        i = int(ti * SR)
        m = int(rng.uniform(0.002, 0.012) * SR)
        grit[i:i + m] += rng.standard_normal(m) * np.exp(-np.arange(m) / (m / 3)) * rng.uniform(0.1, 1.0) * np.exp(-ti / 0.5)
    grit = band(grit, 250.0, 2200.0)
    sig = set_peak(thud, 0.0) + 0.6 * set_peak(grit, 0.0)
    return _unit(filt(sig, one_pole_lowpass(1400.0)))


def metal_tick(rng: np.random.Generator) -> np.ndarray:
    """Thermal contraction tick in a steel member: sharp click plus a tiny inharmonic ring.
    The ring is kept to a few ms so the hall reverb does not stretch it into a pitched tail."""
    t = _time(0.05)
    click = rng.standard_normal(len(t)) * np.exp(-t / 0.0003)
    modes = [(rng.uniform(2500, 7000), rng.uniform(0.0015, 0.004), rng.uniform(0.1, 0.3)) for _ in range(3)]
    return _unit(click / np.max(np.abs(click)) + _impulse_ring(t, modes, rng))


def gravel_skitter(rng: np.random.Generator) -> np.ndarray:
    """A small trickle of gravel skittering down a rock face."""
    dur = rng.uniform(0.4, 1.0)
    out = np.zeros(int((dur + 0.05) * SR))
    for _ in range(int(rng.integers(20, 70))):
        ti = min(rng.exponential(dur / 3.0), dur)
        m = int(rng.uniform(0.0004, 0.0018) * SR)
        g = rng.uniform(0.2, 1.0) * np.exp(-ti / (dur / 2.0))
        grain = rng.standard_normal(m) * np.exp(-np.arange(m) / (m / 3)) * g
        grain = filt(grain, biquad("bandpass", rng.uniform(1500, 7000), 1.5))
        i = int(ti * SR)
        out[i:i + m] += grain[:len(out) - i]
    return _unit(out)


def relay_tick(rng: np.random.Generator, bright: float) -> np.ndarray:
    """Relay armature: sharp clack, short metal ring, tiny thump, one contact bounce."""
    t = _time(0.05)
    trans = band(rng.standard_normal(len(t)), 1500.0, 12000.0) * np.exp(-t / 0.0006)
    ring = _impulse_ring(t, [(bright * rng.uniform(0.97, 1.03), 0.003, 0.35)], rng)
    thump = np.sin(2 * np.pi * 180.0 * t) * np.exp(-t / 0.006) * 0.3
    sig = trans / np.max(np.abs(trans)) + ring + thump
    return _unit(sig + 0.35 * np.roll(sig, int(rng.uniform(0.003, 0.006) * SR)) * (t > 0.003))


def arc_crackle(rng: np.random.Generator) -> np.ndarray:
    """Faint arcing: sputtering crackle plus sizzle that re-strikes every mains half-cycle."""
    dur = rng.uniform(0.3, 1.6)
    t = _time(dur)
    n = len(t)
    env = np.zeros(n)
    for _ in range(int(rng.integers(1, 4))):
        c, w = rng.uniform(0.1, 0.9) * dur, rng.uniform(0.05, 0.3)
        env += np.exp(-0.5 * ((t - c) / w) ** 2) * rng.uniform(0.4, 1.0)
    env = np.clip(env, 0, 1) * _ramp(t, 0, 0.01) * (1 - _ramp(t, dur - 0.02, dur))
    dens = 1200.0 * env ** 2 / SR
    imp = (rng.random(n) < dens) * rng.standard_normal(n) * rng.exponential(1.0, n)
    crackle = band(imp, 1800.0, 9000.0)
    sizzle = band(rng.standard_normal(n), 3000.0, 8000.0) * np.abs(np.sin(2 * np.pi * 50.0 * t)) ** 6 * env
    return _unit(set_peak(crackle, 0.0) + 0.25 * set_peak(sizzle, 0.0))


# ---------------------------------------------------------------------- geiger

GEIGER_BODY = ((3150.0, 0.00032, 0.55), (5900.0, 0.00018, 0.25))  # (Hz, decay s, gain): one device


def geiger_click(rng: np.random.Generator) -> np.ndarray:
    """One G-M pulse through the counter's little speaker: a ~1-2 ms broadband tick with a
    tiny resonant body (fixed per device) and slight random level variation."""
    t = _time(0.003)
    tick = rng.standard_normal(len(t)) * np.exp(-t / 0.00015)
    tick[0] += 3.0
    tick[1] -= 1.5
    body = sum(g * np.sin(2 * np.pi * f * rng.uniform(0.99, 1.01) * t) * np.exp(-t / tau) for f, tau, g in GEIGER_BODY)
    level = 10.0 ** (np.clip(rng.normal(0.0, 1.2), -3.0, 3.0) / 20.0)
    return (0.5 * tick + 3.0 * body) * level


def _geiger_train(rng: np.random.Generator, buf: np.ndarray, times: list[float], p_double: Callable[[float], float],
                  circular: bool) -> None:
    last = -1.0
    for ti in times:
        if ti - last < 0.0002:  # G-M dead time
            continue
        last = ti
        place(buf, geiger_click(rng), ti, pan=0.0, circular=circular)
        if rng.random() < p_double(ti):
            place(buf, geiger_click(rng) * rng.uniform(0.6, 0.9), ti + rng.uniform(0.002, 0.006), circular=circular)


def geiger_hiss(rng: np.random.Generator, n: int) -> np.ndarray:
    """The counter's own faint amplifier hiss between clicks (keeps the loop from digital silence)."""
    return band(stereo_noise(rng, n, 0.8), 200.0, 9000.0)


# ------------------------------------------------------------------------ loops

@dataclass(frozen=True)
class LoopFrame:
    n: int      # loop length in samples
    xfade: int  # crossfade length
    pre: int    # warm-up samples discarded from the linear stems

    @property
    def total(self) -> int:
        return self.pre + self.n + self.xfade

    @property
    def seconds(self) -> float:
        return self.n / SR


LoopMaker = Callable[[np.random.Generator, LoopFrame], tuple[np.ndarray, np.ndarray]]


def amb_valley_wind(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L = fr.total
    g = gust_curve(rng, L, base=0.28, wander=0.12, rate=1 / 9, amp=(0.25, 0.7), attack=(1.2, 3.5), decay=(2.5, 7.0))
    inten = stereo_env(g, L, 0.12)
    lin = (set_rms(wind_layer(rng, L, inten, 110.0, 520.0, q=2.2, corr=0.35, amp_pow=1.6), -20.0)
           + set_rms(rumble(rng, L, inten, 85.0), -26.0)
           + set_rms(rustle(rng, L, inten), -33.0))
    dry = np.zeros((2, fr.n))
    for t0 in spaced_times(rng, fr.seconds, 4, 14.0):
        pan = rng.uniform(-0.8, 0.8)
        place(dry, metal_knock(rng), t0, 10 ** (rng.uniform(-23, -19) / 20), pan)
        if rng.random() < 0.6:  # the sheet swings back
            place(dry, metal_knock(rng), t0 + rng.uniform(0.35, 0.9), 10 ** (rng.uniform(-27, -23) / 20), pan)
    circ = reverb(dry, reverb_ir(rng, 2.6, predelay=0.05, hf_ratio=0.35), wet=0.8, dry=0.5, circular=True)
    return lin, circ


def amb_valley_life(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L = fr.total
    g = gust_curve(rng, L, base=0.15, wander=0.08, rate=1 / 16, amp=(0.1, 0.3), attack=(2.0, 4.0), decay=(3.0, 8.0))
    inten = stereo_env(g, L, 0.1)
    lin = (set_rms(wind_layer(rng, L, inten, 120.0, 380.0, q=1.8, corr=0.3, bands=10, amp_pow=1.2, floor=0.3), -46.0)
           + set_rms(rustle(rng, L, inten, tick_rate=120.0), -60.0))
    birds = np.zeros((2, fr.n))
    for t0 in spaced_times(rng, fr.seconds, 4, 15.0):
        f0, pan = rng.uniform(430.0, 560.0), rng.uniform(-0.85, 0.85)
        t = t0
        for j in range(int(rng.choice([1, 2, 2, 3, 3, 4]))):
            place(birds, caw(rng, f0 * rng.uniform(0.94, 1.04), rng.uniform(0.22, 0.4)), t,
                  10 ** ((rng.uniform(-26, -22) - 1.5 * j) / 20), pan)
            t += rng.uniform(0.5, 0.85)
    bugs = np.zeros((2, fr.n))
    for t0 in irregular_times(rng, fr.seconds, 7.0, 18.0):
        place(bugs, insect_ticks(rng), t0, 10 ** (rng.uniform(-40, -34) / 20), rng.uniform(-0.9, 0.9))
    circ = (reverb(birds, reverb_ir(rng, 2.8, predelay=0.06, hf_ratio=0.35), wet=0.9, dry=0.6, circular=True)
            + reverb(bugs, reverb_ir(rng, 0.6, predelay=0.01), wet=0.2, circular=True))
    return lin, circ


def amb_settlement_creaks(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L = fr.total
    g = gust_curve(rng, L, base=0.2, wander=0.1, rate=1 / 10, amp=(0.15, 0.45), attack=(1.5, 3.5), decay=(3.0, 7.0))
    inten = stereo_env(g, L, 0.1)
    lin = (set_rms(wind_layer(rng, L, inten, 140.0, 480.0, q=2.0, corr=0.35, amp_pow=1.6), -32.0)
           + set_rms(rumble(rng, L, inten, 80.0), -39.0)
           + set_rms(rustle(rng, L, inten, tick_rate=150.0), -47.0))

    def gusty(t: float) -> float:  # events favour gusts: weight by intensity at that moment
        return float(g[min(int((fr.pre / SR + t) * CTRL_RATE), len(g) - 1)]) ** 2

    dry = np.zeros((2, fr.n))
    for t0 in spaced_times(rng, fr.seconds, 9, 4.0, gusty):
        low = rng.random() < 0.5
        place(dry, creak(rng, rng.uniform(0.5, 1.8), low), t0, 10 ** (rng.uniform(-30, -23) / 20),
              rng.uniform(-0.3, 0.1) if low else rng.uniform(0.2, 0.8))
    for t0 in irregular_times(rng, fr.seconds, 2.8, 8.5):  # rope and pulley, one fixed spot
        pan = 0.35 + rng.uniform(-0.05, 0.05)
        place(dry, wood_knock(rng, rng.uniform(180.0, 210.0)), t0, 10 ** (rng.uniform(-29, -25) / 20), pan)
        if rng.random() < 0.3:
            place(dry, wood_knock(rng, 195.0), t0 + rng.uniform(0.18, 0.3), 10 ** (rng.uniform(-36, -32) / 20), pan)
    for t0 in irregular_times(rng, fr.seconds, 1.2, 4.5):  # one puddle under a broken gutter
        place(dry, drip(rng, 1500.0), t0, 10 ** (rng.uniform(-40, -34) / 20), -0.5)
    peaks = spaced_times(rng, fr.seconds, 6, 6.0, lambda t: gusty(t) ** 2)
    for t0 in peaks:
        place(dry, shutter_burst(rng), t0, 10 ** (rng.uniform(-30, -25) / 20), -0.25)
    circ = reverb(dry, reverb_ir(rng, 0.9, predelay=0.015), wet=0.35, circular=True)
    return lin, circ


def amb_infrastructure(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L, N = fr.total, fr.n
    g = gust_curve(rng, L, base=0.2, wander=0.1, rate=1 / 15, amp=(0.1, 0.3), attack=(2.0, 5.0), decay=(4.0, 9.0))
    inten = stereo_env(g, L, 0.2)
    lin = (set_rms(rumble(rng, L, inten * 0.3, 70.0, corr=0.4), -42.0)
           + set_rms(wind_layer(rng, L, inten, 120.0, 300.0, q=2.5, corr=0.2, bands=10, amp_pow=1.3), -45.0))

    # Mains hum from two unsynchronised pumps/transformers: 50.0 and 50.2 Hz (plus their
    # 100 Hz), beating every 5 s, well under the room tone. Whole cycles per loop, so exactly periodic.
    swell = 0.8 + 0.2 * periodic_sine(N, 1.0 / fr.seconds * 3, rng.uniform(0, 6.3))
    hum_l = (periodic_sine(N, 50.0) + 0.8 * periodic_sine(N, 50.2, 1.0)
             + 0.5 * periodic_sine(N, 100.0, 0.3) + 0.4 * periodic_sine(N, 100.4, 2.0)) * swell
    hum_r = (periodic_sine(N, 50.0, 0.4) + 0.8 * periodic_sine(N, 50.2, 1.9)
             + 0.5 * periodic_sine(N, 100.0, 1.1) + 0.4 * periodic_sine(N, 100.4, 0.2)) * swell
    hum = set_rms(np.stack([hum_l, hum_r]), -42.0)

    drips = np.zeros((2, N))
    for f0, pan, lo, hi in ((1300.0, -0.6, 2.5, 7.0), (2100.0, 0.4, 4.0, 11.0), (1700.0, 0.1, 6.0, 16.0)):
        for t0 in irregular_times(rng, fr.seconds, lo, hi):
            place(drips, drip(rng, f0), t0, 10 ** (rng.uniform(-26, -20) / 20), pan + rng.uniform(-0.05, 0.05))
    stones = np.zeros((2, N))
    for t0 in spaced_times(rng, fr.seconds, 3, 18.0):
        place(stones, stone_settle(rng), t0, 10 ** (rng.uniform(-24, -19) / 20), rng.uniform(-0.9, 0.9))
    ticks = np.zeros((2, N))
    for t0 in irregular_times(rng, fr.seconds, 4.0, 13.0):
        pan = rng.uniform(-0.8, 0.8)
        t = t0
        for _ in range(int(rng.choice([1, 1, 2, 3, 4]))):
            place(ticks, metal_tick(rng), t, 10 ** (rng.uniform(-32, -25) / 20), pan)
            t += rng.uniform(0.3, 1.8)
    hall = reverb_ir(rng, 4.5, predelay=0.045, hf_ratio=0.4)
    circ = (reverb(drips, hall, wet=1.1, dry=0.45, circular=True)
            + reverb(stones, hall, wet=1.2, dry=0.3, circular=True)
            + reverb(ticks, hall, wet=0.5, dry=0.7, circular=True)
            + hum)
    return lin, circ


def amb_cloud_wind(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L = fr.total
    g = gust_curve(rng, L, base=0.45, wander=0.2, rate=1 / 14, amp=(0.1, 0.3), attack=(3.0, 6.0), decay=(5.0, 10.0),
                   wander_fc=0.02, flutter=0.02)
    inten = stereo_env(g, L, 0.25)
    wind = wind_layer(rng, L, inten, 90.0, 260.0, q=1.4, corr=0.15, bands=10, amp_pow=1.0, floor=0.5)
    wind = filt(wind, biquad("lowpass", 700.0, 0.6), one_pole_lowpass(1200.0))  # muffled
    mist = band(stereo_noise(rng, L, 0.05), 1500.0, 5000.0) * (0.6 + 0.4 * inten)
    lin = (set_rms(wind, -20.0) + set_rms(rumble(rng, L, inten, 60.0, corr=0.3), -22.0) + set_rms(mist, -44.0))
    return lin, np.zeros((2, fr.n))


def amb_summit_wind(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L = fr.total
    g = gust_curve(rng, L, base=0.3, wander=0.15, rate=1 / 7, amp=(0.25, 0.75), attack=(0.6, 2.0), decay=(1.5, 5.0),
                   flutter=0.06)
    inten = stereo_env(g, L, 0.08)
    thin = filt(wind_layer(rng, L, inten, 300.0, 1500.0, q=2.5, corr=0.3, amp_pow=1.8, floor=0.1),
                biquad("highpass", 180.0, 0.7))
    hiss = band(stereo_noise(rng, L, 0.2), 1500.0, 7000.0) * inten ** 2
    # Edge tone off a rock lip: ~45 Hz-wide noise band around 900-1150 Hz, only when the
    # gust is strong enough to excite it. Kept low.
    ia = to_audio(g, L)
    wander = to_audio(smooth(rng.standard_normal(len(g)), 0.15), L)
    freq = 900.0 * (1.0 + 0.25 * ia) * (1.0 + 0.03 * wander / max(np.max(np.abs(wander)), 1e-9))
    wh = narrow_noise(rng, L, freq, 45.0) * np.maximum(ia - 0.45, 0.0) ** 1.5
    whistle = np.stack([wh, np.roll(wh, int(0.0004 * SR))])
    lin = (set_rms(thin, -20.0) + set_rms(hiss, -29.0) + set_rms(rumble(rng, L, inten, 70.0), -34.0)
           + set_rms(whistle, -34.0))
    dry = np.zeros((2, fr.n))
    for t0 in spaced_times(rng, fr.seconds, 6, 7.0):
        place(dry, gravel_skitter(rng), t0, 10 ** (rng.uniform(-25, -20) / 20), rng.uniform(-0.9, 0.9))
    circ = reverb(dry, reverb_ir(rng, 0.8, predelay=0.02, hf_ratio=0.5), wet=0.3, circular=True)
    return lin, circ


def amb_transmitter_electrical(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
    L, N = fr.total, fr.n
    # Transformer: 100 Hz magnetostriction hum over a weak 50 Hz, a second unit at 100.25 Hz
    # beating against it; faint 200 Hz. Whole cycles per loop.
    hum = np.stack([
        0.35 * periodic_sine(N, 50.0, p) + periodic_sine(N, 100.0, p + 0.2)
        + 0.3 * periodic_sine(N, 100.25, p + 1.7) + 0.03 * periodic_sine(N, 200.0, p + 0.9)
        for p in (0.0, 0.5)])
    hum = set_rms(hum, -39.0)
    # Corona buzz: broadband hiss pulsing at 100 Hz. The 100 Hz pulse fits whole cycles
    # into preroll, loop and crossfade alike, so the crossfaded ends line up in phase.
    tl = np.arange(L) / SR
    corona = band(stereo_noise(rng, L, 0.6), 2000.0, 9000.0) * (0.3 + np.abs(np.sin(2 * np.pi * 50.0 * tl)) ** 4)
    g = gust_curve(rng, L, base=0.25, wander=0.1, rate=1 / 9, amp=(0.2, 0.5), attack=(0.8, 2.0), decay=(1.5, 4.0))
    inten = stereo_env(g, L, 0.1)
    outside = filt(wind_layer(rng, L, inten, 300.0, 1200.0, q=2.5, amp_pow=1.8, bands=10), biquad("highpass", 200.0))
    hiss = band(stereo_noise(rng, L, 0.4), 300.0, 12000.0)
    lin = set_rms(corona, -46.0) + set_rms(outside, -37.0) + set_rms(hiss, -54.0)

    dry = np.zeros((2, N))
    relays = [(rng.uniform(2200, 3500), rng.uniform(-0.6, 0.6)) for _ in range(3)]
    for t0 in irregular_times(rng, fr.seconds, 3.0, 9.0):
        bright, pan = relays[int(rng.integers(0, 3))]
        place(dry, relay_tick(rng, bright), t0, 10 ** (rng.uniform(-24, -20) / 20), pan)
        place(dry, relay_tick(rng, bright), t0 + rng.uniform(0.4, 3.0), 10 ** (rng.uniform(-28, -24) / 20), pan)
    for t0 in spaced_times(rng, fr.seconds, 5, 7.0):
        place(dry, arc_crackle(rng), t0, 10 ** (rng.uniform(-34, -28) / 20), rng.uniform(-0.5, 0.5))
    circ = reverb(dry, reverb_ir(rng, 0.6, predelay=0.008, hf_ratio=0.6), wet=0.4, circular=True) + hum
    return lin, circ


def geiger_loop(rate: float, p_double: float) -> LoopMaker:
    def make(rng: np.random.Generator, fr: LoopFrame) -> tuple[np.ndarray, np.ndarray]:
        circ = np.zeros((2, fr.n))
        count = int(rng.poisson(rate * fr.seconds))
        times = sorted(rng.uniform(0.0, fr.seconds, count))
        _geiger_train(rng, circ, times, lambda _t: p_double, circular=True)
        lin = geiger_hiss(rng, fr.total) * (np.max(np.abs(geiger_click(np.random.default_rng(1)))) * 10 ** (-72 / 20))
        return lin, circ
    return make


# ------------------------------------------------------------------- one-shots

def sfx_geiger_burst(rng: np.random.Generator, n: int) -> np.ndarray:
    """2 s: walking into a hotspot. Rate climbs 4 -> ~80 cps by 1.1 s, holds briefly, then
    settles toward the SFX_Geiger_High rate (15 cps) so it can hand over to that loop."""
    d = n / SR

    def rate(t: float) -> float:
        if t < 1.1:
            return 4.0 + 76.0 * (t / 1.1) ** 1.3
        if t < 1.4:
            return 80.0
        return 15.0 + 65.0 * np.exp(-(t - 1.4) / 0.2)

    lam = 80.0  # thinning: candidates at the peak rate, kept with probability rate/lam
    cand = np.sort(rng.uniform(0.0, d, int(rng.poisson(lam * d))))
    times = [t for t in cand if rng.random() < rate(t) / lam]
    buf = np.zeros((2, n))
    _geiger_train(rng, buf, times, lambda t: 0.02 + 0.06 * min(t / 1.1, 1.0), circular=False)
    buf += geiger_hiss(rng, n) * (np.max(np.abs(buf)) * 10 ** (-69 / 20))
    return buf


def sfx_radio_static_in(rng: np.random.Generator, n: int) -> np.ndarray:
    """0.4 s: squelch opens with a click, static rushes in with crackle and a heterodyne
    sweeping down as the receiver locks, then settles to a low hiss for the voice."""
    t = np.arange(n) / SR
    noise = filt(stereo_noise(rng, n, 0.85), biquad("highpass", 350.0), biquad("lowpass", 3600.0),
                 biquad("peak", 1800.0, 1.0, 4.0))
    level = _ramp(t, 0.012, 0.016) * (1.0 - 0.75 * _ramp(t, 0.06, 0.33)) * (1.0 - _ramp(t, 0.33, 0.39))
    crackle = band((rng.random(n) < 180.0 / SR) * rng.standard_normal(n), 1000.0, 5000.0) * level
    open_click = band(rng.standard_normal(n), 1000.0, 4000.0) * np.exp(-np.maximum(t - 0.012, 0) / 0.0015) * (t >= 0.012)
    sweep_f = 2400.0 * (260.0 / 2400.0) ** _ramp(t, 0.04, 0.30)
    het = np.sin(_phase(sweep_f)) * _ramp(t, 0.03, 0.06) * (1.0 - _ramp(t, 0.24, 0.32)) * (0.8 + 0.2 * np.sin(2 * np.pi * 23.0 * t))
    sig = set_peak(noise * level, -6.0) + set_peak(crackle, -10.0) + set_peak(open_click, -4.0) + 0.12 * het
    return np.tanh(2.2 * sig) / 2.2


def sfx_radio_static_out(rng: np.random.Generator, n: int) -> np.ndarray:
    """0.4 s: carrier drops, static swells with crackle, the squelch tail 'kssht' and cut."""
    t = np.arange(n) / SR
    noise = filt(stereo_noise(rng, n, 0.85), biquad("highpass", 350.0), biquad("lowpass", 3600.0),
                 biquad("peak", 1800.0, 1.0, 4.0))
    bright = filt(stereo_noise(rng, n, 0.85), biquad("highpass", 1800.0), biquad("lowpass", 6500.0))
    cut = 0.29
    level = (0.3 + 0.7 * _ramp(t, 0.05, 0.14)) * (1.0 - _ramp(t, cut - 0.0015, cut))
    tail = _ramp(t, 0.255, 0.262) * (1.0 - _ramp(t, cut - 0.0015, cut))
    crackle = band((rng.random(n) < 260.0 / SR) * rng.standard_normal(n), 1000.0, 5000.0) * _ramp(t, 0.05, 0.1) * (t < cut)
    click = band(rng.standard_normal(n), 800.0, 3500.0) * np.exp(-np.maximum(t - cut, 0) / 0.001) * (t >= cut)
    sig = (set_peak(noise * level, -6.0) + set_peak(bright * tail, -7.0) + set_peak(crackle, -10.0)
           + set_peak(click, -14.0))
    return np.tanh(2.2 * sig) / 2.2


def sfx_carrier_joint_strain(rng: np.random.Generator, n: int) -> np.ndarray:
    """0.8 s: a failing joint under load. Gear-mesh grind with slipping teeth, stick-slip
    creak of stressed metal and a servo motor bogging down, all mechanical."""
    t = np.arange(n) / SR
    d = n / SR
    env = _ramp(t, 0.0, 0.08) * (1.0 - _ramp(t, 0.62, 0.78)) * (0.8 + 0.2 * np.sin(2 * np.pi * 3.1 * t))
    exc = np.zeros(n)
    tp = 0.0
    while tp < d:
        i = int(tp * SR)
        slip = rng.random() < 0.06
        exc[i] += env[i] * (rng.uniform(1.5, 2.5) if slip else rng.uniform(0.3, 1.0))
        tp += (0.004 if slip else 1.0 / (48.0 * (1.0 + 0.25 * np.sin(2 * np.pi * 1.3 * tp)))) * (1 + 0.25 * rng.standard_normal())
        tp = max(tp, i / SR + 0.002)
    housing = sum(g * filt(exc, biquad("bandpass", f, q)) for f, q, g in
                  ((1150.0, 7.0, 1.0), (2350.0, 8.0, 0.7), (3650.0, 9.0, 0.5), (5200.0, 6.0, 0.3)))
    grit = band(rng.standard_normal(n), 800.0, 5000.0) * filt(np.abs(exc), one_pole_lowpass(120.0)) * 8.0
    # Servo gear-train whine bogging down under the load; noisy and kept well under the grind.
    motor_f = 380.0 - 90.0 * _ramp(t, 0.05, 0.6) + 8.0 * np.sin(2 * np.pi * 5.0 * t)
    ph = _phase(motor_f)
    motor = np.tanh(1.5 * sum(np.sin(k * ph) / k for k in range(1, 5))) * env
    motor = filt(motor, biquad("highpass", 250.0)) * (0.7 + 0.3 * band(rng.standard_normal(n), 20.0, 200.0) / 3.0)
    slip = np.zeros(n)
    tp = 0.05
    while tp < 0.7:
        slip[int(tp * SR)] += rng.uniform(0.5, 1.0)
        tp += 1.0 / rng.uniform(14.0, 22.0)
    creak_sig = filt(slip, biquad("bandpass", 420.0, 6.0)) + 0.6 * filt(slip, biquad("bandpass", 980.0, 7.0))
    mono = set_peak(housing, 0.0) + 0.6 * set_peak(grit, 0.0) + 0.1 * motor + 0.5 * set_peak(creak_sig * env, 0.0)
    out = np.zeros((2, n))
    place(out, mono, 0.0, pan=0.15, circular=False)
    return out + 0.05 * band(stereo_noise(rng, n, 0.2), 2000.0, 8000.0) * env


def sfx_capsule_latch(rng: np.random.Generator, n: int) -> np.ndarray:
    """0.5 s: pawl click, heavy latch clank (thump + short inharmonic ring), a pneumatic
    hiss as the seal lets go, one rattle bounce; small enclosed room."""
    t = np.arange(n) / SR
    pre = band(rng.standard_normal(n), 2500.0, 10000.0) * np.exp(-np.maximum(t - 0.008, 0) / 0.0008) * (t >= 0.008)
    t0 = 0.035
    after = np.maximum(t - t0, 0.0)
    on = (t >= t0) * _ramp(t, t0, t0 + 0.0008)
    thump = np.sin(_phase(60.0 + 30.0 * np.exp(-after / 0.03))) * np.exp(-after / 0.06) * on
    ring = sum(g * np.sin(2 * np.pi * f * after) * np.exp(-after / tau) for f, tau, g in
               ((310.0, 0.05, 0.35), (781.0, 0.035, 0.3), (1463.0, 0.02, 0.25), (2351.0, 0.012, 0.2))) * on
    crack = band(rng.standard_normal(n), 800.0, 8000.0) * np.exp(-after / 0.003) * on
    hiss = band(rng.standard_normal(n), 2000.0, 7000.0) * np.exp(-np.maximum(t - 0.05, 0) / 0.1) * _ramp(t, 0.045, 0.055)
    bounce = np.roll(crack, int(0.055 * SR)) * 0.35
    mono = (set_peak(pre, -10.0) + set_peak(thump, 0.0) + ring + set_peak(crack, -3.0) + set_peak(hiss, -14.0)
            + bounce * 10 ** (-3 / 20) / max(np.max(np.abs(crack)), 1e-9))
    st = np.stack([mono, mono])
    return reverb(st, reverb_ir(rng, 0.35, predelay=0.004, hf_ratio=0.6), wet=0.3)


def sfx_rockfall_distant(rng: np.random.Generator, n: int) -> np.ndarray:
    """3 s: a rock slide across the valley. Impacts swell and thin out over ~1.8 s under a
    low rumble; distance low-pass, valley reverb and a late echo off the far wall."""
    t = np.arange(n) / SR
    dens_env = _ramp(t, 0.0, 0.3) * np.exp(-np.maximum(t - 0.9, 0) / 0.35)
    dry = np.zeros((2, n))
    for _ in range(int(rng.integers(130, 170))):
        ti = rng.uniform(0.0, 1.9)
        if rng.random() > dens_env[int(ti * SR)]:
            continue
        size = rng.random() ** 2
        m = int((0.01 + 0.08 * size) * SR)
        tt = np.arange(m) / SR
        hit = rng.standard_normal(m) * np.exp(-tt / (0.003 + 0.02 * size))
        hit = filt(hit, biquad("lowpass", 2500.0 - 2000.0 * size, 0.8))
        place(dry, hit, ti, rng.uniform(0.3, 1.0) * (0.4 + size), rng.uniform(-0.5, 0.3), circular=False)
    rum = filt(stereo_noise(rng, n, 0.6), one_pole_lowpass(60.0), biquad("lowpass", 90.0)) * dens_env
    mix = set_peak(dry, 0.0) + set_peak(rum, -4.0)
    mix = filt(mix, one_pole_lowpass(1600.0), biquad("lowpass", 2200.0))
    wet = reverb(mix, reverb_ir(rng, 2.2, predelay=0.06, hf_ratio=0.35), wet=1.0, dry=0.6)
    echo = np.zeros_like(wet)
    k = int(0.36 * SR)
    echo[:, k:] = filt(wet, one_pole_lowpass(900.0))[::-1, :-k] * 10 ** (-9 / 20)
    return (wet + echo) * (1.0 - _ramp(t, 2.3, 3.0))


def sfx_wind_gust_heavy(rng: np.random.Generator, n: int) -> np.ndarray:
    """4 s: one heavy gust building, buffeting and passing, drifting left to right."""
    t = np.arange(n) / SR
    m = ctrl_len(n)
    tc = np.arange(m) / CTRL_RATE
    turb = smooth(rng.standard_normal(m), 3.0)
    ctrl = 0.08 + 0.92 * _ramp(tc, 0.2, 1.7) * (1.0 - _ramp(tc, 1.9, 3.9)) + 0.08 * turb / np.max(np.abs(turb))
    ctrl = np.clip(ctrl, 0.0, 1.0)
    inten = stereo_env(ctrl, n, 0.15)
    wind = wind_layer(rng, n, inten, 130.0, 950.0, q=2.0, corr=0.4, amp_pow=2.0, floor=0.05)
    buf_env = to_audio(np.abs(smooth(rng.standard_normal(m), 14.0)), n)
    buffet = filt(stereo_noise(rng, n, 0.7), biquad("highpass", 25.0), biquad("lowpass", 80.0)) * inten ** 3 * (0.4 + buf_env / np.max(buf_env))
    whoosh = band(stereo_noise(rng, n, 0.3), 1500.0, 6000.0) * inten ** 2.5
    mix = set_rms(wind, -18.0) + set_rms(buffet, -22.0) + set_rms(whoosh, -30.0)
    drift = _ramp(t, 0.0, 4.0)
    return mix * np.stack([np.cos(np.pi / 4 * (0.6 + 0.8 * drift)), np.sin(np.pi / 4 * (0.6 + 0.8 * drift))]) * np.sqrt(2)


# ------------------------------------------------------------------------- spec

@dataclass(frozen=True)
class Sound:
    name: str
    kind: str        # "bed" (AMB loop), "loop" (SFX loop) or "oneshot"
    duration: float
    seed: int
    make: Callable
    purpose: str
    cps: float = 0.0  # Geiger loops: nominal counts per second (checked)
    p_double: float = 0.0

    @property
    def filename(self) -> str:
        return f"{self.name}.wav"

    @property
    def looped(self) -> bool:
        return self.kind in ("bed", "loop")

    @property
    def peak_dbfs(self) -> float:
        return BED_PEAK_DBFS if self.kind == "bed" else SFX_PEAK_DBFS


def _geiger(name: str, seed: int, cps: float, p_double: float, purpose: str) -> Sound:
    return Sound(name, "loop", 30.0, seed, geiger_loop(cps, p_double), purpose, cps, p_double)


SOUNDS = (
    Sound("AMB_Valley_Wind", "bed", 90.0, 7101, amb_valley_wind, "low gusty wind, grass/reed rustle, rare far metal knock"),
    Sound("AMB_Valley_Life", "bed", 90.0, 7102, amb_valley_life, "sparse distant caws and insect ticks over faint air"),
    Sound("AMB_Settlement_Creaks", "bed", 75.0, 7103, amb_settlement_creaks, "light wind, wood creaks, pulley knock, drips, shutter"),
    Sound("AMB_Infrastructure", "bed", 80.0, 7104, amb_infrastructure, "reservoir drips + long tails, settling stone, mains hum, cooling ticks"),
    Sound("AMB_Cloud_Wind", "bed", 60.0, 7105, amb_cloud_wind, "dense, close, muffled wet wind with no detail"),
    Sound("AMB_Summit_Wind", "bed", 75.0, 7106, amb_summit_wind, "thin high wind, faint rock-edge whistle, gravel skitter"),
    Sound("AMB_Transmitter_Electrical", "bed", 60.0, 7107, amb_transmitter_electrical, "transformer hum, relay ticks, faint arcing"),
    _geiger("SFX_Geiger_Low", 7201, 0.5, 0.0, "background count, ~0.5 cps"),
    _geiger("SFX_Geiger_Medium", 7202, 3.0, 0.01, "elevated count, ~3 cps"),
    _geiger("SFX_Geiger_High", 7203, 15.0, 0.05, "hot count, ~15 cps with occasional doubles"),
    Sound("SFX_Geiger_Burst", "oneshot", 2.0, 7204, sfx_geiger_burst, "rising burst walking into a hotspot"),
    Sound("SFX_Radio_Static_In", "oneshot", 0.4, 7301, sfx_radio_static_in, "squelch open / tune in before a radio line"),
    Sound("SFX_Radio_Static_Out", "oneshot", 0.4, 7302, sfx_radio_static_out, "squelch tail after a radio line"),
    Sound("SFX_Carrier_Joint_Strain", "oneshot", 0.8, 7303, sfx_carrier_joint_strain, "failing joint servo strain/grind"),
    Sound("SFX_Capsule_Latch", "oneshot", 0.5, 7304, sfx_capsule_latch, "heavy latch release"),
    Sound("SFX_Rockfall_Distant", "oneshot", 3.0, 7305, sfx_rockfall_distant, "distant rock slide with reverb"),
    Sound("SFX_Wind_Gust_Heavy", "oneshot", 4.0, 7306, sfx_wind_gust_heavy, "one heavy gust"),
)


# ------------------------------------------------------------------ finishing

def crossfade_loop(x: np.ndarray, n: int, xfade: int) -> np.ndarray:
    """Equal-power crossfade of the ``xfade`` samples past ``n`` over the loop head."""
    u = (np.arange(xfade) + 0.5) / xfade
    out = x[:, :n].copy()
    out[:, :xfade] = x[:, :xfade] * np.sin(0.5 * np.pi * u) + x[:, n:n + xfade] * np.cos(0.5 * np.pi * u)
    return out


def _window_db(y: np.ndarray, w: int, hop: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per candidate cut k (every ``hop`` samples) on the circular loop: RMS dB of the ``w``
    samples before and after k, per channel."""
    n = y.shape[1]
    ext = np.concatenate([y[:, -w:], y, y[:, :w]], axis=1)
    cs = np.concatenate([np.zeros((2, 1)), np.cumsum(ext ** 2, axis=1)], axis=1)
    k = np.arange(0, n, hop)
    before = (cs[:, k + w] - cs[:, k]) / w
    after = (cs[:, k + 2 * w] - cs[:, k + w]) / w
    return k, 10 * np.log10(before + 1e-20), 10 * np.log10(after + 1e-20)


def best_rotation(y: np.ndarray) -> int:
    """Pick the cut where the 50 ms either side match best in level, preferring quiet
    moments (between events) -- where an editor would cut."""
    k, db_b, db_a = _window_db(y, int(SEAM_WINDOW_S * SR), SR // 100)
    level = np.maximum(db_b, db_a).max(axis=0)
    score = np.abs(db_b - db_a).max(axis=0) + 0.15 * np.maximum(level - np.percentile(level, 25), 0.0)
    return int(k[np.argmin(score)])


def _quantise(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    tpdf = rng.random(x.shape) - rng.random(x.shape)
    return np.clip(np.round(x * PCM_SCALE + tpdf), -32768, 32767).astype("<i2")


def render(sound: Sound) -> np.ndarray:
    rng = np.random.default_rng(sound.seed)
    dither = np.random.default_rng(sound.seed + 100_000)
    target = 10.0 ** (sound.peak_dbfs / 20.0)
    if sound.looped:
        xf = GEIGER_XFADE_S if sound.kind == "loop" else BED_XFADE_S
        fr = LoopFrame(int(round(sound.duration * SR)), int(xf * SR), int(PREROLL_S * SR))
        lin, circ = sound.make(rng, fr)
        y = crossfade_loop(lin[:, fr.pre:], fr.n, fr.xfade) + circ
        spec = np.fft.rfft(y) * response((biquad("highpass", 20.0),), fr.n)
        spec[:, 0] = 0.0
        y = np.fft.irfft(spec, fr.n)
        y = np.roll(y, -best_rotation(y), axis=1)
    else:
        n = int(round(sound.duration * SR))
        y = filt(sound.make(rng, n), biquad("highpass", 20.0))
        k = int(EDGE_FADE_S * SR)
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
        gain = np.ones(n)
        gain[:k] *= ramp
        gain[n - k:] *= ramp[::-1]
        y = y * gain
        y = y - gain * (y.sum(axis=1, keepdims=True) / gain.sum())  # zero mean, edges stay 0
    y = y * (target / np.max(np.abs(y)))
    return _quantise(y, dither)


def write_wav(path: Path, pcm: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(np.ascontiguousarray(pcm.T).tobytes())
    os.replace(tmp, path)


def generate(out_dir: Path, sounds: tuple[Sound, ...]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sound in sounds:
        pcm = render(sound)
        path = out_dir / sound.filename
        write_wav(path, pcm)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        print(f"wrote {path}  ({pcm.shape[1]} frames, sha256 {digest})", flush=True)


# ------------------------------------------------------------------------ check

def _db(value: float) -> float:
    return 20.0 * np.log10(value) if value > 0 else float("-inf")


def tonal_profile(x: np.ndarray) -> list[tuple[float, float]]:
    """(prominence dB, frequency Hz) of the strongest spectral peak per 1 s window; see TONAL_*."""
    han = np.hanning(TONAL_FFT)
    freqs = np.fft.rfftfreq(TONAL_FFT, 1.0 / SR)
    lo = int(np.searchsorted(freqs, TONAL_MIN_HZ, side="right"))
    hi = int(np.searchsorted(freqs, TONAL_MAX_HZ))
    h = TONAL_HALF_BINS
    out = []
    for w in range(x.shape[1] // SR):
        seg = x[:, w * SR:(w + 1) * SR]
        frames = sliding_window_view(seg, TONAL_FFT, axis=-1)[:, ::TONAL_HOP]
        p = np.mean(np.abs(np.fft.rfft(frames * han, axis=-1)) ** 2, axis=(0, 1))
        med = np.median(sliding_window_view(np.pad(p, h, mode="reflect"), 2 * h + 1)[lo:hi], axis=-1)
        prom = 10.0 * np.log10(p[lo:hi] / np.maximum(med, 1e-30))
        i = int(np.argmax(prom))
        out.append((float(prom[i]), float(freqs[lo + i])))
    return out


def tonal_calibration() -> str:
    """Prominence of noise alone, and of a 1 kHz sine at several levels relative to the noise RMS."""
    rng = np.random.default_rng(1)
    noise = filt(rng.standard_normal((2, SR)), one_pole_lowpass(2000.0))
    tone = np.sin(2 * np.pi * 1000.0 * np.arange(SR) / SR)
    parts = [f"noise alone {tonal_profile(noise)[0][0]:.1f} dB"]
    for rel in (-30.0, -20.0, -10.0):
        parts.append(f"sine {rel:+.0f} dB re noise {tonal_profile(noise + set_rms(tone, _db(_rms(noise)) + rel))[0][0]:.1f} dB")
    return "calibration (1 kHz sine in low-passed noise): " + ", ".join(parts)


def count_clicks(x: np.ndarray) -> int:
    a = np.abs(x).mean(axis=0)
    idx = np.flatnonzero(a > 0.25 * a.max())
    if idx.size == 0:
        return 0
    return int(1 + np.count_nonzero(np.diff(idx) > int(0.0015 * SR)))


def check_file(sound: Sound, path: Path) -> tuple[list[str], list[str]]:
    """Returns (problems, report lines)."""
    if not path.is_file():
        return ["file missing"], []
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames, comptype = wav.getnframes(), wav.getcomptype()
        raw = wav.readframes(frames)
    problems = []
    if rate != SR:
        problems.append(f"rate {rate} != {SR}")
    if channels != 2:
        problems.append(f"{channels} channels, expected stereo")
    if width != 2:
        problems.append(f"{8 * width}-bit, expected 16-bit")
    if comptype != "NONE":
        problems.append(f"compression {comptype}, expected PCM")
    if problems or frames == 0:
        return problems or ["no audio frames"], []

    x = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 2).T
    n = x.shape[1]
    duration = n / rate
    peak_db = _db(np.max(np.abs(x)) / FULL_SCALE)
    rms_db = _db(_rms(x) / FULL_SCALE)
    dc_pct = float(np.max(np.abs(x.mean(axis=1)))) / FULL_SCALE * 100.0
    lines = [f"{duration:6.2f} s (spec {sound.duration:g})  peak {peak_db:6.2f} dBFS (target {sound.peak_dbfs:g})"
             f"  rms {rms_db:6.1f} dBFS  dc {dc_pct:.4f}%"]

    if abs(duration - sound.duration) > DURATION_TOL_S:
        problems.append(f"duration {duration:.3f} s, spec {sound.duration} s")
    if abs(peak_db - sound.peak_dbfs) > PEAK_TOL_DB:
        problems.append(f"peak {peak_db:.2f} dBFS not within {PEAK_TOL_DB} dB of {sound.peak_dbfs}")
    if not rms_db > MIN_RMS_DBFS:
        problems.append(f"RMS {rms_db:.1f} dBFS, not above {MIN_RMS_DBFS} (silent?)")
    if dc_pct > MAX_DC_PERCENT:
        problems.append(f"DC offset {dc_pct:.4f}% > {MAX_DC_PERCENT}%")

    if not sound.looped:
        edges = int(np.max(np.abs(x[:, [0, -1]])))
        lines[0] += f"  edges {edges} LSB"
        if edges > MAX_EDGE_LSB:
            problems.append(f"edges not silent ({edges} LSB)")
    else:
        w = int(SEAM_WINDOW_S * SR)
        head = 10 * np.log10(np.mean(x[:, :w] ** 2, axis=1) + 1e-12)
        tail = 10 * np.log10(np.mean(x[:, -w:] ** 2, axis=1) + 1e-12)
        seam_db = float(np.max(np.abs(head - tail)))
        step = np.abs(x[:, 0] - x[:, -1])
        steps = np.abs(np.diff(x, axis=1))
        limit = np.maximum(np.percentile(steps, SEAM_STEP_PERCENTILE, axis=1), SEAM_STEP_FLOOR_LSB)
        lines.append(f"seam: last/first 50 ms RMS differ {seam_db:.2f} dB (limit {SEAM_RMS_TOL_DB});"
                     f" wrap step L/R {step[0]:.0f}/{step[1]:.0f} LSB (limit p{SEAM_STEP_PERCENTILE:g} step"
                     f" {limit[0]:.0f}/{limit[1]:.0f})")
        if seam_db > SEAM_RMS_TOL_DB:
            problems.append(f"seam RMS mismatch {seam_db:.2f} dB")
        if np.any(step > limit):
            problems.append(f"seam discontinuity {step.max():.0f} LSB > {limit.min():.0f}")

        prof = tonal_profile(x / FULL_SCALE)
        proms = np.array([p for p, _ in prof])
        over = proms > TONAL_LIMIT_DB
        run = best = 0
        for flag in np.concatenate([over, over]):  # twice round, so a run across the seam counts whole
            run = run + 1 if flag else 0
            best = max(best, run)
        best = min(best, len(over))
        top = int(np.argmax(proms))
        frac = float(over.mean())
        lines.append(f"tonal: max {proms.max():5.1f} dB @ {prof[top][1]:6.0f} Hz (t={top} s), median {np.median(proms):4.1f} dB,"
                     f" windows > {TONAL_LIMIT_DB:g} dB: {int(over.sum())}/{len(over)}, longest run {best} s")
        if best > TONAL_MAX_RUN_S or frac > TONAL_MAX_FRACTION:
            problems.append(f"sustained tonal content (run {best} s, {100 * frac:.0f}% of windows)")

        if sound.cps:
            clicks = count_clicks(x)
            expected = sound.cps * sound.duration * (1.0 + sound.p_double)
            tol = 4.0 * np.sqrt(expected) + 2.0
            lines.append(f"geiger: {clicks} clicks = {clicks / duration:.2f} cps (nominal {sound.cps:g};"
                         f" expected {expected:.0f} +/- {tol:.0f} incl. doubles)")
            if abs(clicks - expected) > tol:
                problems.append(f"click count {clicks} outside {expected:.0f} +/- {tol:.0f}")
    return problems, lines


def check(out_dir: Path, sounds: tuple[Sound, ...]) -> bool:
    print(f"check {out_dir}")
    print(f"  tonal detector {tonal_calibration()}; window limit {TONAL_LIMIT_DB:g} dB,"
          f" fail if run > {TONAL_MAX_RUN_S} s or > {100 * TONAL_MAX_FRACTION:.0f}% of windows")
    failed = 0
    for sound in sounds:
        problems, lines = check_file(sound, out_dir / sound.filename)
        print(f"  {'PASS' if not problems else 'FAIL'}  {sound.filename}")
        for line in lines:
            print(f"        {line}")
        for problem in problems:
            print(f"        ! {problem}")
        failed += bool(problems)
    print(f"check: {len(sounds) - failed}/{len(sounds)} files pass (48 kHz stereo 16-bit PCM, duration +/-5 ms,"
          f" peak within {PEAK_TOL_DB} dB of target, RMS > {MIN_RMS_DBFS:g} dBFS, |DC| <= {MAX_DC_PERCENT}%;"
          f" loops: seam RMS <= {SEAM_RMS_TOL_DB:g} dB, wrap step <= p{SEAM_STEP_PERCENTILE:g}, no sustained tone;"
          f" one-shots: silent edges)")
    return failed == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only re-read and check the existing files")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="limit to these sound names")
    args = parser.parse_args(argv)
    sounds = SOUNDS
    if args.only:
        unknown = set(args.only) - {s.name for s in SOUNDS}
        if unknown:
            parser.error(f"unknown sound(s): {', '.join(sorted(unknown))}")
        sounds = tuple(s for s in SOUNDS if s.name in args.only)
    if not args.check:
        generate(args.out, sounds)
    return 0 if check(args.out, sounds) else 1


if __name__ == "__main__":
    sys.exit(main())
