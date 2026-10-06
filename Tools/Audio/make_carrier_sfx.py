#!/usr/bin/env python3
"""Synthesise the five placeholder carrier SFX for the Saskarta game flow.

Writes 48 kHz mono 16-bit PCM WAVs to <project>/Saved/GameFlowAudio/. Uses numpy only,
with a fixed seed per sound, so every run writes byte-identical files. A later step
imports them into /Game/SaskartaGaea/GameFlow/Audio/ with Hayba ``asset_import``;
this script never touches Unreal.

    python Tools/Audio/make_carrier_sfx.py            # generate, then run the check
    python Tools/Audio/make_carrier_sfx.py --check    # re-read existing files, check only
    python Tools/Audio/make_carrier_sfx.py --out DIR  # write somewhere else

Every sound is peak-normalised to -3 dBFS, has its DC removed, and gets raised-cosine
fades on both edges (5 ms; the 50 ms boot tick uses the 3 ms its spec asks for), so its
first and last samples are exactly zero. The check exits with status 1 on any failure.
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

SR = 48_000
PEAK_DBFS = -3.0
EDGE_FADE_S = 0.005
PCM_SCALE = 32767.0  # float -> int16 when writing
FULL_SCALE = 32768.0  # 0 dBFS reference when measuring

# --check limits
DURATION_TOL_S = 0.005
PEAK_RANGE_DBFS = (-3.5, -2.5)
MIN_RMS_DBFS = -40.0
MAX_DC_PERCENT = 1.0
MAX_EDGE_LSB = 16  # first/last sample must be (near) silent

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameFlowAudio"


# --------------------------------------------------------------------------- helpers

def _time(duration: float) -> np.ndarray:
    return np.arange(int(round(duration * SR))) / SR


def _ramp_between(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 before ``start``, 1 after ``end``, raised cosine in between."""
    u = np.clip((t - start) / (end - start), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def _edge_fades(n: int, fade_s: float) -> np.ndarray:
    """Gain curve with raised-cosine fades on both edges; first and last values are 0."""
    k = min(int(round(fade_s * SR)), n // 2)
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    gain = np.ones(n)
    gain[:k] *= ramp
    gain[n - k:] *= ramp[::-1]
    return gain


def _phase(freq: np.ndarray) -> np.ndarray:
    """Phase (radians) of an oscillator with per-sample frequency; starts at 0 so sweeps stay continuous."""
    return 2.0 * np.pi * (np.cumsum(freq) - freq[0]) / SR


def _soft_step(octaves: np.ndarray, centre: float, width: float) -> np.ndarray:
    u = np.clip((octaves - centre) / width + 0.5, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def _band(x: np.ndarray, lo: float | None = None, hi: float | None = None,
          width_oct: float = 0.5) -> np.ndarray:
    """Zero-phase band limit with soft edges (raised cosine over ``width_oct`` octaves).

    Zero-padded to at least twice the length, so the filter never wraps the end of the
    signal back onto its start.
    """
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    spectrum = np.fft.rfft(x, nfft)
    octaves = np.log2(np.maximum(np.fft.rfftfreq(nfft, 1.0 / SR), 1e-6))
    mask = np.ones_like(octaves)
    if lo:
        mask *= _soft_step(octaves, np.log2(lo), width_oct)
    if hi:
        mask *= 1.0 - _soft_step(octaves, np.log2(hi), width_oct)
    return np.fft.irfft(spectrum * mask, nfft)[:n]


def _norm(x: np.ndarray) -> np.ndarray:
    return x / np.max(np.abs(x))


def _decay_from(t: np.ndarray, start: float, attack: float, tau: float) -> np.ndarray:
    """Envelope: silent before ``start``, raised-cosine attack, then exponential decay."""
    return _ramp_between(t, start, start + attack) * np.exp(-np.maximum(t - start, 0.0) / tau)


# ---------------------------------------------------------------------------- sounds

def static(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Gated band-limited noise over a 50 Hz mains buzz, both rising in level."""
    t = _time(duration)
    n = len(t)
    hiss = _norm(_band(rng.standard_normal(n), lo=600.0, hi=7000.0))

    # Random gate: 4-30 ms segments, more often open (and loud) as the fault builds.
    gate = np.empty(n)
    i = 0
    while i < n:
        seg = max(1, int(rng.uniform(0.004, 0.030) * SR))
        p_open = 0.35 + 0.6 * (i / n)
        gate[i:i + seg] = rng.uniform(0.55, 1.0) if rng.random() < p_open else rng.uniform(0.04, 0.15)
        i += seg
    kernel = np.hanning(int(0.0015 * SR))  # 1.5 ms smoothing so the gate itself never clicks
    gate = np.convolve(gate, kernel / kernel.sum(), mode="same")

    # Mains buzz: 50 Hz, odd harmonics stronger, lightly saturated.
    mains = 2.0 * np.pi * 50.0 * t
    buzz = sum((1.0 if k % 2 else 0.45) / k * np.sin(k * mains + rng.uniform(0.0, 2.0 * np.pi))
               for k in range(1, 13))
    buzz = _norm(np.tanh(1.8 * _norm(buzz)))

    rise = 0.12 + 0.88 * (t / duration) ** 1.6
    return (0.8 * hiss * gate + 0.4 * buzz * (0.55 + 0.45 * gate)) * rise


def power_down(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Whine falling exponentially 1200 -> 80 Hz, cut by a contact click just before the end."""
    t = _time(duration)
    t_click = duration - 0.028  # click decays well before the final 5 ms fade
    u = np.clip(t / t_click, 0.0, 1.0)
    ph = _phase(1200.0 * (80.0 / 1200.0) ** u)
    whine = np.sin(ph) + 0.30 * np.sin(2.0 * ph) + 0.12 * np.sin(3.0 * ph)
    whine *= (1.0 - 0.5 * u) * (1.0 - _ramp_between(t, t_click - 0.004, t_click))

    burst = _band(rng.standard_normal(len(t)), lo=1500.0, hi=9000.0)
    click = _norm(burst * _decay_from(t, t_click, 0.0002, 0.0012))
    return whine + 1.1 * click


def contactor(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Relay clunk: sharp filtered transient (+ contact bounce), 90 -> 60 Hz thump, two ring partials."""
    t = _time(duration)
    t0 = 0.006  # after the 5 ms fade-in, so the fade never blunts the transient
    d = np.maximum(t - t0, 0.0)

    crack = _band(rng.standard_normal(len(t)), lo=1200.0, hi=10000.0)
    crack_env = _decay_from(t, t0, 0.0002, 0.0025) + 0.35 * _decay_from(t, t0 + 0.009, 0.0002, 0.0018)
    transient = _norm(crack * crack_env)

    thump_freq = np.where(t >= t0, 60.0 + 30.0 * np.exp(-d / 0.030), 0.0)
    thump = np.sin(_phase(thump_freq)) * _decay_from(t, t0, 0.0015, 0.055)

    # Inharmonic partials (ratio ~2.31), each a +/-1.3 Hz detuned pair so the ring shimmers.
    ring = np.zeros_like(t)
    for freq, tau, gain in ((1187.0, 0.070, 0.22), (2741.0, 0.045, 0.14)):
        pair = 0.5 * (np.sin(2.0 * np.pi * (freq - 1.3) * d) + np.sin(2.0 * np.pi * (freq + 1.3) * d))
        ring += gain * pair * _decay_from(t, t0, 0.0005, tau)

    return 0.9 * transient + thump + ring


def boot_tick(rng: np.random.Generator, duration: float) -> np.ndarray:
    """~1.8 kHz blip with a tiny downward chirp on the attack."""
    t = _time(duration)
    ph = _phase(1800.0 + 60.0 * np.exp(-t / 0.004))
    return (np.sin(ph) + 0.12 * np.sin(2.0 * ph)) * np.exp(-t / 0.022)


def power_on(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Hum rising 60 -> 180 Hz with harmonics, plus a faint high whine fading in."""
    t = _time(duration)
    release_s = 0.07
    u = t / duration
    glide = np.clip(t / (duration - release_s), 0.0, 1.0)  # reaches 180 Hz before the release starts
    ph = _phase(60.0 * 3.0 ** (glide ** 1.2))  # exponential glide, lingering low at the start
    hum = sum(g * np.sin(k * ph) for k, g in ((1, 1.0), (2, 0.55), (3, 0.42), (4, 0.22), (5, 0.16), (6, 0.08)))
    hum = _norm(np.tanh(1.4 * _norm(hum)))
    swell = (1.0 - np.exp(-t / 0.10)) * (0.6 + 0.4 * u)
    whine = 0.07 * u ** 2 * np.sin(_phase(6500.0 * (9000.0 / 6500.0) ** u))
    release = 1.0 - _ramp_between(t, duration - release_s, duration)
    return (hum * swell + whine) * release


@dataclass(frozen=True)
class Sound:
    name: str
    duration: float
    seed: int
    make: Callable[[np.random.Generator, float], np.ndarray]
    fade_s: float = EDGE_FADE_S

    @property
    def filename(self) -> str:
        return f"{self.name}.wav"


SOUNDS = (
    Sound("SFX_Carrier_Static", 0.80, 5101, static),
    Sound("SFX_Carrier_PowerDown", 0.35, 5102, power_down),
    Sound("SFX_Carrier_Contactor", 0.25, 5103, contactor),
    Sound("SFX_Carrier_BootTick", 0.05, 5104, boot_tick, fade_s=0.003),
    Sound("SFX_Carrier_PowerOn", 0.60, 5105, power_on),
)


# ------------------------------------------------------------------------ generation

def finalise(x: np.ndarray, fade_s: float) -> np.ndarray:
    """Edge fades, DC removal, -3 dBFS peak normalisation, int16 quantisation."""
    gain = _edge_fades(len(x), fade_s)
    x = x * gain
    x = x - gain * (x.sum() / gain.sum())  # zero mean, and the edges stay exactly 0
    x = x * (10.0 ** (PEAK_DBFS / 20.0) / np.max(np.abs(x)))
    return np.round(x * PCM_SCALE).astype("<i2")


def render(sound: Sound) -> np.ndarray:
    rng = np.random.default_rng(sound.seed)
    return finalise(sound.make(rng, sound.duration), sound.fade_s)


def write_wav(path: Path, pcm: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sound in SOUNDS:
        pcm = render(sound)
        path = out_dir / sound.filename
        write_wav(path, pcm)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        print(f"wrote {path}  ({len(pcm)} samples, sha256 {digest})")


# ----------------------------------------------------------------------------- check

def _db(value: float) -> float:
    return 20.0 * np.log10(value) if value > 0 else float("-inf")


def check_file(sound: Sound, path: Path) -> tuple[list[str], str]:
    """Returns (problems, one-line measurement summary)."""
    if not path.is_file():
        return ["file missing"], "-"
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames, comptype = wav.getnframes(), wav.getcomptype()
        raw = wav.readframes(frames)

    problems = []
    if rate != SR:
        problems.append(f"rate {rate} != {SR}")
    if channels != 1:
        problems.append(f"{channels} channels, expected mono")
    if width != 2:
        problems.append(f"{8 * width}-bit, expected 16-bit")
    if comptype != "NONE":
        problems.append(f"compression {comptype}, expected PCM")
    if width != 2 or channels != 1 or frames == 0:
        if frames == 0:
            problems.append("no audio frames")
        return problems, f"{rate} Hz, {channels} ch, {8 * width}-bit, {frames} frames"

    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if len(pcm) != frames:
        problems.append(f"truncated: {len(pcm)} of {frames} frames")

    duration = len(pcm) / rate
    peak_db = _db(np.max(np.abs(pcm)) / FULL_SCALE)
    rms_db = _db(np.sqrt(np.mean(pcm ** 2)) / FULL_SCALE)
    dc_pct = abs(np.mean(pcm)) / FULL_SCALE * 100.0
    first, last = int(abs(pcm[0])), int(abs(pcm[-1]))

    if abs(duration - sound.duration) > DURATION_TOL_S:
        problems.append(f"duration {duration * 1000:.1f} ms, spec {sound.duration * 1000:.0f} ms +/- 5")
    if not PEAK_RANGE_DBFS[0] <= peak_db <= PEAK_RANGE_DBFS[1]:
        problems.append(f"peak {peak_db:.2f} dBFS outside {PEAK_RANGE_DBFS}")
    if not rms_db > MIN_RMS_DBFS:
        problems.append(f"RMS {rms_db:.2f} dBFS, not above {MIN_RMS_DBFS} (silent?)")
    if dc_pct > MAX_DC_PERCENT:
        problems.append(f"DC offset {dc_pct:.3f}% > {MAX_DC_PERCENT}%")
    if first > MAX_EDGE_LSB or last > MAX_EDGE_LSB:
        problems.append(f"edges not silent (first {first}, last {last} LSB)")

    summary = (f"{rate} Hz  {channels} ch  {8 * width}-bit  "
               f"{duration * 1000:6.1f} ms (spec {sound.duration * 1000:4.0f})  "
               f"peak {peak_db:6.2f} dBFS  rms {rms_db:6.2f} dBFS  dc {dc_pct:.4f}%  edges {first}/{last}")
    return problems, summary


def check(out_dir: Path) -> bool:
    print(f"check {out_dir}")
    failed = 0
    for sound in SOUNDS:
        problems, summary = check_file(sound, out_dir / sound.filename)
        print(f"  {'PASS' if not problems else 'FAIL'}  {sound.filename:<26} {summary}")
        for problem in problems:
            print(f"        - {problem}")
        failed += bool(problems)
    print(f"check: {len(SOUNDS) - failed}/{len(SOUNDS)} files pass"
          f" (48 kHz mono 16-bit, duration +/-5 ms, peak -3.5..-2.5 dBFS, RMS > -40 dBFS,"
          f" |DC| <= 1%, silent edges)")
    return failed == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only re-read and check the existing files")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)
    if not args.check:
        generate(args.out)
    return 0 if check(args.out) else 1


if __name__ == "__main__":
    sys.exit(main())
