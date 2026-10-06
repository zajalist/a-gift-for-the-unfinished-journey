#!/usr/bin/env python3
"""Build the carrier's vehicle sound set: motor, wheels, servos, suspension, strain, states, hatch.

The carrier is a small, old, overloaded electric robot car (131 x 160 x 105 cm, 25 cm wheels,
500 cm/s top speed) towing a capsule trailer on a drawbar, over dirt, gravel and broken slabs.

Writes 48 kHz mono 16-bit WAVs to <project>/Saved/GameAudio/CarrierVehicle/, plus
``_demo_drive.wav`` (a ~32 s contact-sheet drive using the same layer rules the MetaSound
brief gives) and ``manifest.json``. It never touches Unreal; the editor lane imports the
files into /Game/SaskartaGaea/Audio/Carrier/ (see task-CARRIERSFX-brief.md).

Sources:
- procedural (numpy/scipy, fixed seeds): the motor loops, strain loop, servos, mast ticks,
  knee grind, relays and spool-ups, synthetic thumps and rumbles;
- Freesound CC0 recordings (HQ previews, via freesound_fetch.py; the key stays in
  Saved/freesound.key): wheel textures, metal creaks, clunks, rattles, hiss, hinge, latch.
  Each asset that uses one is credited in freesound_credits.json / CREDITS.md.

    python Tools/Audio/make_carrier_vehicle_sfx.py           # build everything, then check
    python Tools/Audio/make_carrier_vehicle_sfx.py --check   # re-measure the existing files
    python Tools/Audio/make_carrier_vehicle_sfx.py --only Motor  # build names containing "Motor"

Levels: loops -20 LUFS integrated (true peak kept under -1 dBFS); one-shots peak -3 dBFS.
Procedural loops are built periodic (every oscillator has a whole number of cycles in the
loop, every noise is filtered circularly), so their wrap is sample-continuous. Recorded loops
use an equal-power tail-into-head crossfade.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

import numpy as np
import pyloudnorm
import soundfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

SR = 48_000
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved" / "GameAudio" / "CarrierVehicle"
LOOP_LUFS = -20.0
LOOP_MAX_PEAK_DB = -1.0
ONESHOT_PEAK_DB = -3.0
TWO_PI = 2.0 * np.pi

# Drivetrain. Wheel circumference 2*pi*25 cm = 157.08 cm. Two-stage reduction 13:52 then
# 12:60 = 20:1, so stage-1 mesh = 13 x motor rev, stage-2 mesh = 3 x motor rev, and one
# wheel rev = motor rev / 20. Motor: 4 pole pairs (2 f_e = order 8), 36 stator slots.
WHEEL_CIRC_CM = TWO_PI * 25.0
GEAR = 20
LOOP_T = 8.0  # procedural motor loops are 8 s; all tonal content is periodic in 8 s


def motor_rps(speed_cm_s: float) -> float:
    return speed_cm_s / WHEEL_CIRC_CM * GEAR


# ------------------------------------------------------------------------------ helpers

def tvec(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR))) / SR


def db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) + 1e-12


def unit(x: np.ndarray) -> np.ndarray:
    """Scale to unit RMS."""
    return x / rms(x)


def smoothstep(e0: float, e1: float, x):
    u = np.clip((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def ramp(t: np.ndarray, a: float, b: float) -> np.ndarray:
    """0 before a, 1 after b, raised cosine between."""
    u = np.clip((t - a) / max(b - a, 1e-9), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def decay(t: np.ndarray, t0: float, attack: float, tau: float) -> np.ndarray:
    return ramp(t, t0, t0 + attack) * np.exp(-np.maximum(t - t0, 0.0) / tau)


def _soft(octs: np.ndarray, centre: float, width: float) -> np.ndarray:
    u = np.clip((octs - centre) / width + 0.5, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def band(x: np.ndarray, lo: float | None = None, hi: float | None = None,
         circular: bool = False, width_oct: float = 0.4, peak: tuple[float, float, float] | None = None) -> np.ndarray:
    """Zero-phase FFT band limit with raised-cosine skirts. ``circular`` filters the buffer as one
    period (the result loops seamlessly); otherwise it is zero-padded so nothing wraps.
    ``peak`` = (freq, q_oct, gain_db) adds a smooth bell."""
    n = len(x)
    nfft = n if circular else 1 << int(np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(x, nfft)
    octs = np.log2(np.maximum(np.fft.rfftfreq(nfft, 1.0 / SR), 1e-6))
    mask = np.ones_like(octs)
    if lo:
        mask *= _soft(octs, np.log2(lo), width_oct)
    if hi:
        mask *= 1.0 - _soft(octs, np.log2(hi), width_oct)
    if peak:
        f, w, g = peak
        mask *= db(g * np.exp(-0.5 * ((octs - np.log2(f)) / w) ** 2))
    return np.fft.irfft(spec * mask, nfft)[:n]


def noise(rng: np.random.Generator, n: int, lo=None, hi=None, circular=True, **kw) -> np.ndarray:
    return unit(band(rng.standard_normal(n), lo, hi, circular=circular, **kw))


def periodic_phase(freq: np.ndarray, multiple: int = 1) -> np.ndarray:
    """Phase (rad) of an oscillator with per-sample frequency, nudged so the buffer holds a whole
    number of cycles (a multiple of ``multiple``): the next sample after the end is phase 0 again."""
    cyc = freq.sum() / SR
    target = max(multiple, round(cyc / multiple) * multiple)
    freq = freq * (target / cyc)
    return TWO_PI * (np.cumsum(freq) - freq[0]) / SR


def free_phase(freq: np.ndarray) -> np.ndarray:
    return TWO_PI * (np.cumsum(freq) - freq[0]) / SR


def periodic_wobble(rng: np.random.Generator, n: int, T: float, cycles=(1, 2, 3, 5), depth=1.0) -> np.ndarray:
    """Slow zero-mean wander made of sines with whole cycle counts in T (so it loops)."""
    t = np.arange(n) / SR
    w = sum(rng.uniform(0.5, 1.0) / c ** 0.5 * np.sin(TWO_PI * c * t / T + rng.uniform(0, TWO_PI)) for c in cycles)
    return depth * w / np.max(np.abs(w))


def place(buf: np.ndarray, sig: np.ndarray, t0: float, gain: float = 1.0, circular: bool = False) -> None:
    i = int(round(t0 * SR))
    if circular:
        idx = (i + np.arange(len(sig))) % len(buf)
        np.add.at(buf, idx, gain * sig)
        return
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    s0 = max(0, -i)
    buf[max(i, 0):j] += gain * sig[s0:j - i]


def varispeed(x: np.ndarray, ratio: float) -> np.ndarray:
    """Tape-style pitch/speed change: ratio > 1 is higher and shorter."""
    if abs(ratio - 1.0) < 1e-6:
        return x.copy()
    fr = Fraction(ratio).limit_denominator(120)
    return resample_poly(x, fr.denominator, fr.numerator).astype(np.float64)


def edge_fade(x: np.ndarray, fin: float = 0.004, fout: float = 0.02) -> np.ndarray:
    x = x.copy()
    for k, sl in ((int(fin * SR), slice(None)), (int(fout * SR), slice(None, None, -1))):
        if k > 1:
            x[sl][:k] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    x[0] = 0.0
    x[-1] = 0.0
    return x


def peak_norm(x: np.ndarray, peak_db: float = ONESHOT_PEAK_DB) -> np.ndarray:
    return x * (db(peak_db) / (np.max(np.abs(x)) + 1e-12))


_METER = pyloudnorm.Meter(SR)


def lufs(x: np.ndarray) -> float:
    if len(x) < SR:  # the meter needs >= 400 ms blocks; tile short files
        x = np.tile(x, int(np.ceil(SR / len(x))) + 1)
    return float(_METER.integrated_loudness(x))


def true_peak_db(x: np.ndarray) -> float:
    up = resample_poly(x, 4, 1)
    return 20.0 * np.log10(np.max(np.abs(up)) + 1e-12)


def loop_norm(x: np.ndarray) -> np.ndarray:
    """-20 LUFS. Where that would push the 4x-oversampled (true) peak over -1 dBFS, a smooth
    look-around gain envelope (computed circularly, so the loop point is untouched) pulls only
    those transients down; loudness and limiting are iterated so both targets hold."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    x = x - x.mean()
    ceiling = db(LOOP_MAX_PEAK_DB - 0.2)
    for _ in range(4):
        x = x * db(LOOP_LUFS - lufs(x))
        up = np.abs(resample_poly(np.concatenate([x[-64:], x, x[:64]]), 4, 1))
        tp = up.reshape(-1, 4).max(axis=1)[64:-64]
        if tp.max() <= ceiling:
            break
        need = np.minimum(1.0, ceiling / np.maximum(tp, 1e-9))
        k = int(0.004 * SR)
        gain = -maximum_filter1d(-need, 2 * k + 1, mode="wrap")      # hold the lowest gain +/- 4 ms
        gain = uniform_filter1d(gain, 2 * k + 1, mode="wrap")         # then smooth it (no clicks)
        gain = np.minimum(gain, -maximum_filter1d(-gain, 2 * k + 1, mode="wrap"))
        x = x * gain
    return x


def onsets(x: np.ndarray, rel_db: float = -18.0, hold: float = 0.08, win: float = 0.002) -> list[float]:
    """Onset times (s) where a short RMS envelope rises through (peak + rel_db)."""
    k = max(1, int(win * SR))
    env = np.sqrt(np.convolve(x * x, np.ones(k) / k, "same"))
    thr = env.max() * db(rel_db)
    above = env > thr
    out, last = [], -1e9
    for i in np.nonzero(above[1:] & ~above[:-1])[0]:
        if (i - last) / SR > hold:
            out.append(i / SR)
            last = i
    return out


def seg(x: np.ndarray, start: float, dur: float) -> np.ndarray:
    a = int(round(start * SR))
    return x[a:a + int(round(dur * SR))].astype(np.float64)


def steadiest(x: np.ndarray, lo: float, hi: float, dur: float, step: float = 0.5) -> float:
    """Start (s) of the ``dur`` window in [lo, hi] with the steadiest 100 ms RMS (least std in dB)."""
    k = int(0.1 * SR)
    frames = x[: len(x) // k * k].reshape(-1, k)
    lev = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
    best, best_s = lo, 1e9
    s = lo
    while s + dur <= hi:
        v = lev[int(s / 0.1): int((s + dur) / 0.1)]
        sd = float(np.std(v)) + 0.3 * float(np.max(v) - np.percentile(v, 95))
        if sd < best_s:
            best, best_s = s, sd
        s += step
    return best


# ------------------------------------------------------------------------------ freesound

@dataclass(frozen=True)
class Rec:
    id: int
    what: str


RECS = {
    "gravel_tires": Rec(251662, "tyres on a gravel road"),
    "dirt_tires": Rec(685231, "front wheel on a gravel-dirt road, close"),
    "trolley_gravel": Rec(764617, "trolley wheels on gravel"),
    "bike_dirt": Rec(218301, "bike tyre on a dirt road"),
    "suitcase_street": Rec(468517, "suitcase rolled over street paving"),
    "truck_squeaks": Rec(508277, "old truck metal squeaks and creaks"),
    "truck_door_impact": Rec(508275, "old truck door impact"),
    "truck_hinge_impact": Rec(508273, "old truck hinge squeak and heavy impact"),
    "creak_slow": Rec(172411, "slow creaking metal"),
    "lid_rattle": Rec(625602, "metal box loose-lid impacts"),
    "chain": Rec(643863, "chain being picked up"),
    "steam": Rec(398077, "steam/pressure hiss"),
    "groan": Rec(496836, "heavy metal bunker-door groan"),
    "latch": Rec(481789, "metallic latch release"),
    "gate_clunk": Rec(399449, "iron cemetery gate latch clunk"),
}
_rec_cache: dict[str, tuple[dict, np.ndarray]] = {}


def hit_meta(rec_id: int) -> dict:
    """Freesound metadata, cached next to the audio cache (no key is stored in it)."""
    path = fs.CACHE / f"{rec_id}.meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    fs.CACHE.mkdir(parents=True, exist_ok=True)
    meta = fs._get(f"/sounds/{rec_id}/", {"fields": fs.FIELDS})
    path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def rec(key: str) -> np.ndarray:
    if key not in _rec_cache:
        meta = hit_meta(RECS[key].id)
        lic = meta["license"]
        if "publicdomain/zero" not in lic and "/by/" not in lic:
            raise SystemExit(f"{key}: licence {lic} is neither CC0 nor CC-BY")
        _rec_cache[key] = (meta, fs.fetch(meta, 1)[:, 0].astype(np.float64))
    return _rec_cache[key][1]


CREDITS: dict[str, list[tuple[str, str]]] = {}  # asset -> [(rec key, how it is used)]


def uses(asset: str, key: str, how: str) -> None:
    CREDITS.setdefault(asset, [])
    if (key, how) not in CREDITS[asset]:
        CREDITS[asset].append((key, how))


def write_credits() -> None:
    for asset, items in CREDITS.items():
        for i, (key, how) in enumerate(items):
            name = asset if i == 0 else f"{asset}__{key}"
            fs.credit(name, _rec_cache[key][0], notes=how)


# ------------------------------------------------------------------------------ motor voice

def motor_voice(rng: np.random.Generator, ph: np.ndarray, rps: np.ndarray, *, circular: bool,
                load: float = 0.3, mix: dict | None = None) -> np.ndarray:
    """A worn two-stage-geared electric drive motor, from the rotor phase ``ph`` (rad).

    Components, all locked to the rotor so they track speed together: magnetic hum (orders 4,
    8, 16, 24), stator-slot whine (36 and its +/-8 sidebands), stage-1 gear mesh (13, 26, 39)
    with once-per-rev eccentricity, stage-2 mesh (3, 6), bearing rattle (high noise pulsed at
    order 3 plus loose ticks), a current-ripple rasp, and a low chassis rumble per wheel rev.
    """
    n = len(ph)
    m = {"el": 0.0, "slot": -9.0, "mesh1": -3.0, "mesh2": -10.0, "rattle": -24.0, "rasp": -21.0,
         "rumble": -13.0, **(mix or {})}
    nyq_guard = 16000.0

    def harm(orders):
        out = np.zeros(n)
        for k, g in orders:
            if np.max(rps) * k < nyq_guard:
                out += g * np.sin(k * ph + rng.uniform(0, TWO_PI))
        return out

    ecc = 1.0 + 0.22 * np.sin(ph + rng.uniform(0, TWO_PI))            # bent motor shaft
    wheel = 1.0 + 0.12 * np.sin(ph / GEAR + rng.uniform(0, TWO_PI))    # out-of-round wheel
    el = unit(harm([(4, 0.3), (8, 1.0), (16, 0.35 + 0.3 * load), (24, 0.12 + 0.2 * load)]))
    slot = unit(harm([(36, 1.0), (28, 0.35), (44, 0.35)]))
    mesh1 = unit(harm([(13, 1.0), (26, 0.38), (39, 0.12)]) * ecc)
    mesh2 = unit(harm([(3, 1.0), (6, 0.4)]) * wheel)

    pulse = (0.5 + 0.5 * np.sin(3 * ph)) ** 8
    rattle = noise(rng, n, 2500, 7500, circular) * (0.25 + pulse)
    ticks = np.zeros(n)
    tick = noise(rng, int(0.0015 * SR), 2500, 9000, circular=False) * np.exp(-np.arange(int(0.0015 * SR)) / (0.0004 * SR))
    for _ in range(int(n / SR * np.mean(rps) * 0.6)):
        place(ticks, tick, rng.uniform(0, n / SR), rng.uniform(0.3, 1.0), circular=circular)
    rattle = unit(rattle + 0.6 * unit(ticks + 1e-9 * rng.standard_normal(n)))
    rasp = unit(noise(rng, n, 700, 3200, circular) * (0.3 + (0.5 + 0.5 * np.sin(8 * ph)) ** 4))
    rumble = unit(noise(rng, n, 30, 160, circular) * wheel)

    tonal = db(m["el"]) * el + db(m["slot"]) * slot + db(m["mesh1"]) * mesh1 + db(m["mesh2"]) * mesh2
    drive = 0.7 + 1.6 * load
    tonal = np.tanh(drive * tonal / 3.0) * 3.0 / drive  # load saturates the hum (odd harmonics)
    return tonal + db(m["rattle"]) * rattle + db(m["rasp"]) * rasp + db(m["rumble"]) * rumble


def motor_loop(rng: np.random.Generator, speed_ref: float, load: float, mix: dict,
               hiccups: int = 2, wander: float = 0.009) -> tuple[np.ndarray, float]:
    """Periodic 8 s motor loop at ``speed_ref`` cm/s. Returns (signal, exact reference speed)."""
    n = int(LOOP_T * SR)
    t = np.arange(n) / SR
    w = periodic_wobble(rng, n, LOOP_T, (1, 2, 3, 5, 7), wander)
    amp = 1.0 + 0.05 * periodic_wobble(rng, n, LOOP_T, (1, 3, 4))
    for _ in range(hiccups):  # a worn winding/commutation hiccup: rpm and level dip for ~60 ms
        tc = rng.uniform(0.5, LOOP_T - 0.5)
        g = np.exp(-0.5 * ((t - tc) / 0.025) ** 2)
        w -= rng.uniform(0.02, 0.035) * g
        amp *= 1.0 - rng.uniform(0.2, 0.35) * g
    rps = motor_rps(speed_ref) * (1.0 + w)
    ph = periodic_phase(rps, multiple=GEAR)
    exact_rps = (ph[-1] + (ph[-1] - ph[-2])) / TWO_PI / LOOP_T
    x = motor_voice(rng, ph, rps, circular=True, load=load, mix=mix) * amp
    return x, exact_rps / GEAR * WHEEL_CIRC_CM


def controller_bed(rng: np.random.Generator, n: int, circular: bool = True, whine_hz: float = 1875.0) -> np.ndarray:
    """Motor-controller / electronics bed: DC-DC buzz, a fluttering coil whine, and a tired
    cooling fan with a ticking bearing. Frequencies are multiples of 1/8 Hz (loopable)."""
    t = np.arange(n) / SR
    T = n / SR
    buzz = sum((1.0 if k % 2 else 0.5) / k ** 0.9 * np.sin(TWO_PI * 100.0 * k * t + rng.uniform(0, TWO_PI)) for k in range(1, 14))
    buzz = unit(np.tanh(1.5 * unit(buzz)))
    flutter = periodic_wobble(rng, n, T, (2, 3, 7, 11), 0.004)
    coil = unit(np.sin(periodic_phase(whine_hz * (1 + flutter))) + 0.25 * np.sin(periodic_phase(2 * whine_hz * (1 + flutter))))
    coil *= 1.0 + 0.3 * periodic_wobble(rng, n, T, (1, 2, 5))
    fan_rps = 36.0 * (1.0 + periodic_wobble(rng, n, T, (1, 2), 0.02))
    fph = periodic_phase(fan_rps, multiple=1)
    fan_tone = unit(np.sin(7 * fph) + 0.4 * np.sin(14 * fph + 1.0))
    fan_air = noise(rng, n, 250, 1800, circular) * (1.0 + 0.4 * np.sin(7 * fph))
    fan_ticks = np.zeros(n)
    tk = noise(rng, int(0.002 * SR), 2000, 8000, circular=False) * np.exp(-np.arange(int(0.002 * SR)) / (0.0005 * SR))
    for _ in range(int(T * 3)):  # dry fan bearing: an irregular tick a few times a second
        place(fan_ticks, tk, rng.uniform(0, T), rng.uniform(0.3, 1.0), circular=circular)
    return (buzz + db(-9) * coil + db(-12) * fan_tone + db(-16) * unit(fan_air)
            + db(-24) * unit(fan_ticks + 1e-9 * rng.standard_normal(n)))


# ------------------------------------------------------------------------------ sounds: motor

MOTOR_REF = {}  # name -> exact reference speed (cm/s), for the brief


def s_motor_idle(rng):
    n = int(LOOP_T * SR)
    return controller_bed(rng, n)


def s_motor_low(rng):
    x, ref = motor_loop(rng, 160.0, 0.35, {"rumble": -12.0})
    MOTOR_REF["SFX_Carrier_Motor_Low_Loop"] = ref
    return x + db(-14) * controller_bed(rng, len(x))


def s_motor_high(rng):
    x, ref = motor_loop(rng, 400.0, 0.3, {"mesh1": -1.5, "slot": -7.0, "rattle": -20.0, "rumble": -15.0})
    MOTOR_REF["SFX_Carrier_Motor_High_Loop"] = ref
    return x + db(-18) * controller_bed(rng, len(x))


def s_motor_strain(rng):
    """Overloaded on a climb: bogged rpm, heavy magnetic hum, current limiter pulsing (1.25 Hz),
    a load groan and a louder rattle."""
    n = int(LOOP_T * SR)
    t = np.arange(n) / SR
    pulses = np.zeros(n)
    for c in range(10):  # current-limit pulses, slightly irregular but periodic in 8 s
        tc = (c + 0.5 + rng.uniform(-0.15, 0.15)) * LOOP_T / 10
        for k in (-1, 0, 1):
            pulses += np.exp(-0.5 * ((t - tc - k * LOOP_T) / 0.09) ** 2)
    w = periodic_wobble(rng, n, LOOP_T, (1, 2, 3, 5), 0.012) - 0.05 * (pulses - pulses.mean())
    rps = motor_rps(120.0) * (1.0 + w)
    ph = periodic_phase(rps, multiple=GEAR)
    x = motor_voice(rng, ph, rps, circular=True, load=1.0,
                    mix={"el": 3.0, "mesh1": -2.0, "mesh2": -6.0, "rasp": -12.0, "rattle": -16.0, "rumble": -6.0})
    MOTOR_REF["SFX_Carrier_Motor_Strain_Loop"] = (ph[-1] + ph[-1] - ph[-2]) / TWO_PI / LOOP_T / GEAR * WHEEL_CIRC_CM
    groan = noise(rng, n, 110, 520, True, peak=(240.0, 0.4, 6.0)) * (0.4 + pulses)
    whine_bend = np.sin(periodic_phase(1400.0 * (1.0 - 0.04 * pulses), 1))  # stressed gear whine bends
    return x * (1.0 - 0.4 * pulses) + db(-9) * unit(groan) + db(-20) * unit(whine_bend) * (0.3 + pulses)


# ------------------------------------------------------------------------------ sounds: wheels

def _rumble(rng, n, lo=35.0, hi=150.0):
    return noise(rng, n, lo, hi, True) * (1.0 + 0.25 * periodic_wobble(rng, n, n / SR, (3, 5, 8)))


def _thump(rng, f0=70.0, dur=0.25, knock=True):
    t = tvec(dur)
    x = np.sin(free_phase(f0 * (1.0 + 0.6 * np.exp(-t / 0.02)))) * decay(t, 0.0, 0.002, 0.06)
    if knock:
        x += 0.6 * noise(rng, len(t), 350, 1500, circular=False) * decay(t, 0.0, 0.0005, 0.018)
        x += 0.25 * noise(rng, len(t), 1500, 5000, circular=False) * decay(t, 0.0, 0.0002, 0.004)
    return x


def _recorded_loop(asset, key, lo, hi, dur, ratio, hp, lp=None, xfade=2.0, how=""):
    src = rec(key)
    start = steadiest(src, lo, hi, dur)
    x = varispeed(seg(src, start, dur), ratio)
    x = band(x, hp, lp)
    uses(asset, key, how or f"{start:.1f}-{start + dur:.1f} s, varispeed x{ratio}, band {hp}-{lp or 'open'} Hz, {xfade} s loop crossfade")
    return fs.make_loop(x, xfade).astype(np.float64)


def s_wheels_dirt(rng):
    a = "SFX_Carrier_Wheels_Dirt_Loop"
    x = _recorded_loop(a, "dirt_tires", 40.0, 102.0, 22.0, 0.9, 110, 7000)
    return unit(x) + db(-5) * _rumble(rng, len(x))


def s_wheels_gravel(rng):
    a = "SFX_Carrier_Wheels_Gravel_Loop"
    x = _recorded_loop(a, "gravel_tires", 0.8, 19.8, 17.0, 0.9, 110, None, xfade=1.5)
    return unit(x) + db(-7) * _rumble(rng, len(x), 40, 170)


def _slab_joints(rng, n, gap=(0.5, 0.8), axle_s=0.36, f0=62.0, gain=1.0):
    buf = np.zeros(n)
    t = rng.uniform(0, 0.3)
    while t < n / SR:
        g = rng.uniform(0.5, 1.0) * gain
        place(buf, _thump(rng, f0 * rng.uniform(0.9, 1.15)), t, g, circular=True)                  # front axle
        place(buf, _thump(rng, f0 * rng.uniform(0.9, 1.15)), t + axle_s, g * rng.uniform(0.6, 0.9), circular=True)  # rear
        t += rng.uniform(*gap)
    return buf


def s_wheels_slabs(rng):
    a = "SFX_Carrier_Wheels_Slabs_Loop"
    x = _recorded_loop(a, "suitcase_street", 5.0, 39.0, 24.0, 0.78, 70, 6000)
    joints = _slab_joints(rng, len(x))
    return unit(x) + db(-3) * unit(joints) + db(-9) * _rumble(rng, len(x))


def s_trailer_dirt(rng):
    return unit(_recorded_loop("SFX_Carrier_Trailer_Wheels_Dirt_Loop", "bike_dirt", 1.6, 23.2, 19.0, 1.0, 180, 9000, xfade=1.5))


def s_trailer_gravel(rng):
    return unit(_recorded_loop("SFX_Carrier_Trailer_Wheels_Gravel_Loop", "trolley_gravel", 0.3, 13.2, 12.4, 1.04, 160, None, xfade=1.2))


def s_trailer_slabs(rng):
    x = _recorded_loop("SFX_Carrier_Trailer_Wheels_Slabs_Loop", "suitcase_street", 41.0, 88.0, 20.0, 1.0, 160, 9000)
    joints = _slab_joints(rng, len(x), gap=(0.55, 0.85), axle_s=0.0, f0=110.0, gain=0.6)
    return unit(x) + db(-8) * unit(joints)


# ------------------------------------------------------------------------------ sounds: servos, mast

def _servo(rng, dur, f_start, f_end, stop_ticks=1, gear=9.0):
    """Small geared DC servo: buzzy motor tone ramping up, gear whine, backlash tick(s) at stop."""
    t = tvec(dur)
    run = dur - 0.05
    prof = f_start + (f_end - f_start) * smoothstep(0.0, 0.35 * run, t) - 0.25 * f_end * smoothstep(0.75 * run, run, t)
    ph = free_phase(prof * (1.0 + 0.01 * np.sin(TWO_PI * 23 * t)))
    tone = sum((1.0 / k) * np.sin(k * ph) * (1.0 if k % 2 else 0.6) for k in range(1, 18) if k * f_end < 18000)
    whine = np.sin(gear * ph) + 0.3 * np.sin(2 * gear * ph)
    brush = noise(rng, len(t), 2000, 9000, circular=False) * (0.5 + 0.5 * np.sin(2 * ph)) ** 6
    env = ramp(t, 0.0, 0.018) * (1.0 - ramp(t, run - 0.03, run))
    x = (unit(tone) + db(-8) * unit(whine) + db(-18) * unit(brush)) * env
    for i in range(stop_ticks):
        tk = noise(rng, int(0.02 * SR), 1200, 7000, circular=False) * np.exp(-np.arange(int(0.02 * SR)) / (0.002 * SR))
        place(x, 3.0 * tk, run - 0.005 + i * rng.uniform(0.018, 0.03), rng.uniform(0.6, 1.0))
    return x


def s_steer(rng, side, i):
    # Turning out (left) the rack pushes against the worn joint: slower start, double tick.
    # Returning (right) is lighter and quicker. The labels follow the carrier's real steer.
    dur = [0.32, 0.45, 0.58][i]
    if side == "L":
        return _servo(rng, dur, 90.0 + 10 * i, 205.0 + 12 * i, stop_ticks=2, gear=9.0)
    return _servo(rng, dur, 120.0 + 10 * i, 240.0 + 10 * i, stop_ticks=1, gear=11.0)


def s_mast_tick(rng, i):
    """Mast/eye stepper: a short train of ticks with a faint step tone."""
    steps, rate = [(3, 38.0), (5, 52.0), (7, 64.0), (9, 44.0)][i]
    dur = steps / rate + 0.1
    t = tvec(dur)
    x = np.zeros(len(t))
    tk_t = tvec(0.012)
    for s in range(steps):
        body = sum(g * np.sin(TWO_PI * f * rng.uniform(0.97, 1.03) * tk_t) * np.exp(-tk_t / tau)
                   for f, g, tau in ((2950.0, 1.0, 0.0022), (5200.0, 0.6, 0.0012), (1400.0, 0.35, 0.004)))
        place(x, body, 0.004 + s / rate + rng.uniform(-0.002, 0.002), rng.uniform(0.7, 1.0) * (0.8 if s % 2 else 1.0))
    step_tone = np.sin(TWO_PI * 880.0 * t) * ramp(t, 0.0, 0.01) * (1.0 - ramp(t, steps / rate, steps / rate + 0.02))
    return x + 0.08 * step_tone


# ------------------------------------------------------------------------------ sounds: suspension, creak, drawbar

def _hits(key, rel_db=-16.0, hold=0.25):
    x = rec(key)
    return x, onsets(x, rel_db, hold)


def s_clunk(rng, i):
    a = f"SFX_Carrier_Suspension_Clunk_{i + 1:02d}"
    if i < 5:
        x, on = _hits("lid_rattle")
        pick = [0, 3, 6, 9, 12][i]
        ratio = [0.55, 0.62, 0.5, 0.68, 0.58][i]
        src = seg(x, on[pick] - 0.004, 0.55)
        uses(a, "lid_rattle", f"impact {pick + 1} at {on[pick]:.2f} s, varispeed x{ratio}, low-passed, over a synthetic thump")
    elif i < 7:
        x = rec("truck_door_impact")
        t0 = [0.90, 1.42][i - 5]
        ratio = [0.8, 0.72][i - 5]
        src = seg(x, t0, 0.6)
        uses(a, "truck_door_impact", f"impact at {t0:.2f} s, varispeed x{ratio}, over a synthetic thump")
    else:
        x = rec("truck_hinge_impact")
        on = [o for o in onsets(x, -10.0, 0.3) if o > 7.0][0]
        ratio = 0.85
        src = seg(x, on - 0.01, 0.7)
        uses(a, "truck_hinge_impact", f"heavy impact at {on:.2f} s, varispeed x{ratio}, over a synthetic thump")
    y = band(varispeed(src, ratio), 60, 5500)
    y = edge_fade(y, 0.002, 0.08)
    thump = _thump(rng, rng.uniform(62, 95), 0.35)
    spring = np.sin(TWO_PI * rng.uniform(150, 210) * tvec(0.35)) * decay(tvec(0.35), 0.01, 0.005, 0.09)
    out = np.zeros(max(len(y), len(thump)) + 100)
    place(out, unit(y), 0.0)
    place(out, unit(thump), 0.0, db(-2))
    place(out, unit(spring), 0.0, db(-16))
    return out


def s_chassis_creak(rng):
    """12 s of sparse chassis creaks (placed circularly so the loop is seamless)."""
    a = "SFX_Carrier_Chassis_Creak_Loop"
    n = int(12.0 * SR)
    buf = np.zeros(n)
    sq = rec("truck_squeaks")
    on_sq = onsets(sq, -14.0, 0.4)
    slow = rec("creak_slow")
    on_slow = [o for o in onsets(slow, -20.0, 0.5) if 17.0 < o < 29.0]
    uses(a, "truck_squeaks", f"{min(len(on_sq), 7)} creak gestures, varispeed x0.72-0.85, low-passed at 5 kHz")
    uses(a, "creak_slow", f"{min(len(on_slow), 3)} short creaks from 17-29 s, varispeed x0.6")
    t = 0.3
    order = rng.permutation(len(on_sq))[:7]
    for k in order:
        c = band(varispeed(seg(sq, on_sq[k] - 0.01, 0.6), rng.uniform(0.72, 0.85)), 90, 5000)
        place(buf, edge_fade(c, 0.003, 0.15), t, rng.uniform(0.5, 1.0), circular=True)
        t += rng.uniform(1.1, 2.0)
    for k in on_slow[:3]:
        c = band(varispeed(seg(slow, k, 0.9), 0.6), 90, 4000)
        place(buf, edge_fade(unit(c), 0.02, 0.3) * 0.15, rng.uniform(0, 12.0), 1.0, circular=True)
    return buf + db(-40) * noise(rng, n, 200, 3000, True)


def _chain_clinks():
    x = rec("chain")
    return x, [o for o in onsets(x, -24.0, 0.06) if o < 4.2]


def s_drawbar_rattle(rng):
    """8 s loose-coupler rattle: pin knocks, chain clinks and lid rattles, bunched irregularly."""
    a = "SFX_Carrier_Drawbar_Rattle_Loop"
    n = int(8.0 * SR)
    buf = np.zeros(n)
    ch, on_ch = _chain_clinks()
    lid, on_lid = _hits("lid_rattle")
    uses(a, "chain", f"{len(on_ch)} clinks from the first 4.2 s, varispeed x0.8-1.0")
    uses(a, "lid_rattle", "loose-lid impacts, varispeed x1.1-1.4, first 120 ms only")
    t = 0.0
    while t < 8.0:
        burst = rng.integers(1, 4)
        for b in range(burst):
            tb = t + b * rng.uniform(0.03, 0.07)
            if rng.random() < 0.55:
                k = on_ch[rng.integers(len(on_ch))]
                c = varispeed(seg(ch, k - 0.003, 0.18), rng.uniform(0.8, 1.0))
            else:
                k = on_lid[rng.integers(len(on_lid))]
                c = varispeed(seg(lid, k - 0.002, 0.14), rng.uniform(1.1, 1.4))
            c = edge_fade(band(c, 250, 9000), 0.001, 0.04)
            place(buf, unit(c), tb, rng.uniform(0.35, 1.0), circular=True)
        t += rng.uniform(0.12, 0.45)
    pin = np.zeros(n)
    for k in range(int(8.0 * 2.5)):  # the drawbar pin knocking in its eye, low and dull
        place(pin, _thump(rng, rng.uniform(120, 170), 0.12), rng.uniform(0, 8.0), rng.uniform(0.3, 1.0), circular=True)
    return unit(buf) + db(-8) * unit(pin)


def s_drawbar_clank(rng, i):
    a = f"SFX_Carrier_Drawbar_Clank_{i + 1:02d}"
    out = np.zeros(int(0.9 * SR))
    if i in (0, 2):
        g = rec("gate_clunk")
        on = onsets(g, -6.0, 0.2)[0]
        ratio = [0.85, 0.75][i // 2]
        c = band(varispeed(seg(g, on - 0.005, 0.55), ratio), 80, 8000)
        uses(a, "gate_clunk", f"latch clunk at {on:.2f} s, varispeed x{ratio}")
    else:
        lid, on_lid = _hits("lid_rattle")
        pick = [1, 7][i // 2]
        ratio = [0.9, 0.78][i // 2]
        c = band(varispeed(seg(lid, on_lid[pick] - 0.003, 0.5), ratio), 90, 8000)
        uses(a, "lid_rattle", f"impact {pick + 1}, varispeed x{ratio}")
    place(out, unit(edge_fade(c, 0.002, 0.1)), 0.0)
    ch, on_ch = _chain_clinks()
    for k in range(2 + i % 2):  # the coupler chain settling after the knock
        j = on_ch[rng.integers(len(on_ch))]
        place(out, unit(edge_fade(band(seg(ch, j - 0.002, 0.15), 300, 9000), 0.001, 0.04)),
              0.06 + k * rng.uniform(0.05, 0.11), db(-9))
    uses(a, "chain", "2-3 clinks as the coupler chain settles")
    place(out, unit(_thump(rng, 110, 0.25)), 0.0, db(-6))
    return out


# ------------------------------------------------------------------------------ sounds: knee grind

def s_knee_grind(rng, i):
    """The failing left knee actuator: a strained motor that stalls and restarts, stripped teeth
    skipping (clicks through metal resonances), a scrape, a final clunk."""
    dur = [0.9, 1.2, 1.5, 1.1][i]
    t = tvec(dur)
    n = len(t)
    gate = np.zeros(n)
    tt = 0.0
    segs = []
    while tt < dur - 0.25:
        on = rng.uniform(0.07, 0.2)
        segs.append((tt, tt + on))
        gate += ramp(t, tt, tt + 0.008) * (1.0 - ramp(t, tt + on - 0.01, tt + on))
        tt += on + rng.uniform(0.03, 0.09)
    f = 130.0 * (1.0 + 0.08 * np.sin(TWO_PI * 5.5 * t)) * (0.85 + 0.15 * gate)
    ph = free_phase(f)
    motor = sum((1.0 / k) * np.sin(k * ph) for k in range(1, 30) if k * 160 < 16000)
    whine = np.sin(7 * ph)
    teeth = np.zeros(n)
    modes = [(1720.0, 0.022), (2930.0, 0.015), (4310.0, 0.01), (870.0, 0.03)]
    kt = tvec(0.06)
    ring = sum(np.sin(TWO_PI * fm * rng.uniform(0.98, 1.02) * kt) * np.exp(-kt / tau) for fm, tau in modes)
    for a0, a1 in segs:  # skipping teeth at 22-45 per second while it strains
        tk = a0 + 0.01
        rate = rng.uniform(22, 45)
        while tk < a1:
            place(teeth, ring * rng.uniform(0.4, 1.0), tk)
            tk += rng.exponential(1.0 / rate) + 0.008
    scrape = noise(rng, n, 400, 2600, circular=False) * gate * (0.5 + 0.5 * np.abs(np.sin(TWO_PI * 17 * t)))
    x = (unit(np.tanh(1.5 * unit(motor))) * gate * db(-4) + db(-12) * unit(whine) * gate
         + unit(teeth) * db(-2) + db(-9) * unit(scrape))
    place(x, 2.0 * unit(_thump(rng, 85, 0.3)), segs[-1][1] + 0.02, 1.0)
    return x


# ------------------------------------------------------------------------------ sounds: relays, states

def relay_click(rng, bright=1.0, dur=0.08):
    t = tvec(dur)
    crack = noise(rng, len(t), 1500, 10000, circular=False) * (decay(t, 0.001, 0.0002, 0.0012)
                                                              + 0.4 * decay(t, 0.0045, 0.0002, 0.0008))
    ring = sum(g * np.sin(TWO_PI * f * t) * decay(t, 0.001, 0.0005, tau) for f, g, tau in ((2350.0 * bright, 0.25, 0.012), (4100.0 * bright, 0.15, 0.006)))
    body = np.sin(TWO_PI * 180.0 * t) * decay(t, 0.001, 0.001, 0.01)
    return 1.2 * unit(crack) * 0.3 + ring + 0.3 * body


def contactor(rng, dur=0.3):
    import make_carrier_sfx as mcs  # the contactor clunk from the placeholder set
    return mcs.contactor(rng, dur)


def boot_tick(rng):
    import make_carrier_sfx as mcs
    return mcs.boot_tick(rng, 0.05)


def spool(rng, t: np.ndarray, rps: np.ndarray, level: np.ndarray, load=0.25) -> np.ndarray:
    """A non-looping motor from an rps curve (0 = stopped)."""
    ph = free_phase(rps)
    x = motor_voice(rng, ph, np.maximum(rps, 1e-3), circular=False, load=load)
    return x * level * smoothstep(0.3, 6.0, rps)


def pwm_chirp(t, f0, f1, t0, t1, level_env):
    f = f0 + (f1 - f0) * ramp(t, t0, t1)
    return np.sin(free_phase(f)) * level_env


def s_state_start(rng):
    """Power-on at the Start anim (2.5 s): relays, contactor, controller whine, a test spool of the
    drive motor, then the idle bed rising so it hands over to the idle loop."""
    dur = 2.6
    t = tvec(dur)
    x = np.zeros(len(t))
    for tc, b in ((0.05, 1.0), (0.2, 1.1), (0.29, 0.92)):
        place(x, relay_click(rng, b), tc, db(-9))
    place(x, unit(contactor(rng)), 0.42, db(-7))
    for tc in (0.62, 0.7, 0.86):
        place(x, unit(boot_tick(rng)), tc, db(-14))
    x += db(-22) * pwm_chirp(t, 700.0, 1875.0, 0.5, 1.3, ramp(t, 0.48, 0.6))
    rps = 22.0 * ramp(t, 0.8, 1.45) * (1.0 - ramp(t, 1.55, 2.25))
    x += db(-5) * spool(rng, t, rps, 1.0 / 3.0 + 0 * t, load=0.4)
    bed = controller_bed(rng, len(t), circular=False)
    x += db(-12) * unit(bed) * ramp(t, 1.0, 2.2)
    return x * (1.0 - ramp(t, dur - 0.04, dur))


def s_state_startstop(rng):
    """Stopping from speed (StartStop anim): soft regen whirr down, a brief low brake squeak,
    the body rocks on its springs, the trailer shoves the drawbar, a creak, a rattle settles."""
    dur = 2.0
    t = tvec(dur)
    x = np.zeros(len(t))
    rps = motor_rps(160.0) * (1.0 - ramp(t, 0.0, 0.55))
    x += db(-8) * spool(rng, t, rps, 1 / 3 + 0 * t, load=0.6)
    sq_f = 980.0 * (1.0 + 0.012 * np.sin(TWO_PI * 7.0 * t)) * (1.0 - 0.06 * ramp(t, 0.15, 0.55))
    sq_env = ramp(t, 0.12, 0.3) * (1.0 - ramp(t, 0.42, 0.6))
    squeal = (np.sin(free_phase(sq_f)) + 0.3 * np.sin(free_phase(2.01 * sq_f))) * (0.7 + 0.3 * noise(rng, len(t), 3, 30, circular=False))
    x += db(-24) * squeal * sq_env + db(-26) * noise(rng, len(t), 1500, 5000, circular=False) * sq_env
    place(x, unit(s_clunk(rng, 5)), 0.55, db(-4))
    place(x, unit(s_drawbar_clank(rng, 1)), 0.72, db(-5))
    uses("SFX_Carrier_State_StartStop", "truck_door_impact", "the body rock: the Suspension_Clunk_06 build")
    uses("SFX_Carrier_State_StartStop", "lid_rattle", "the trailer shove: the Drawbar_Clank_02 build")
    uses("SFX_Carrier_State_StartStop", "chain", "three chain clinks as the coupler settles")
    sq = rec("truck_squeaks")
    k = onsets(sq, -14.0, 0.4)[2]
    uses("SFX_Carrier_State_StartStop", "truck_squeaks", f"one creak gesture at {k:.2f} s, varispeed x0.75")
    place(x, unit(band(edge_fade(varispeed(seg(sq, k - 0.01, 0.6), 0.75), 0.003, 0.15), 90, 5000)), 0.95, db(-12))
    ch, on_ch = _chain_clinks()
    for j, tc in enumerate((1.05, 1.18, 1.36)):
        c = seg(ch, on_ch[(j * 3) % len(on_ch)] - 0.002, 0.15)
        place(x, unit(edge_fade(band(c, 300, 9000), 0.001, 0.04)), tc, db(-15 - 3 * j))
    return x * (1.0 - ramp(t, dur - 0.05, dur))


def s_state_shutdown(rng):
    """Power-down at the Shutdown anim (5 s): relays drop out, the controller whine and hum fall,
    a last rotor spin-down, the main contactor opens, capacitors bleed, the chassis settles."""
    dur = 3.8
    t = tvec(dur)
    x = np.zeros(len(t))
    bed = controller_bed(rng, len(t), circular=False)
    fall = 1.0 - ramp(t, 0.1, 1.6)
    x += db(-12) * unit(band(bed, 40, 12000)) * fall
    x += db(-20) * pwm_chirp(t, 1875.0, 260.0, 0.15, 1.7, ramp(t, 0.0, 0.05) * (1.0 - ramp(t, 1.2, 1.75)))
    rps = 14.0 * (1.0 - ramp(t, 0.25, 1.9))
    x += db(-7) * spool(rng, t, rps, 1 / 3 + 0 * t, load=0.1)
    for tc, b in ((0.18, 1.0), (1.35, 0.9), (1.43, 1.05)):
        place(x, relay_click(rng, b), tc, db(-9))
    place(x, unit(contactor(rng)), 1.95, db(-6))
    x += db(-34) * pwm_chirp(t, 9000.0, 5200.0, 2.0, 3.3, ramp(t, 1.97, 2.05) * (1.0 - ramp(t, 2.4, 3.3)))  # cap bleed
    sq = rec("truck_squeaks")
    k = onsets(sq, -14.0, 0.4)[4]
    uses("SFX_Carrier_State_Shutdown", "truck_squeaks", f"one creak gesture at {k:.2f} s, varispeed x0.7, as the body settles")
    place(x, unit(band(edge_fade(varispeed(seg(sq, k - 0.01, 0.7), 0.7), 0.003, 0.2), 90, 4500)), 2.45, db(-14))
    place(x, unit(_thump(rng, 70.0, 0.3)), 2.55, db(-12))
    return x * (1.0 - ramp(t, dur - 0.05, dur))


def s_state_reboot(rng):
    """Emergency reboot: the drive is cut hard mid-hum with a contactor bang and an arc, dead
    silence with capacitor ticks, then relay chatter, boot ticks, whine, a test spool, idle bed."""
    dur = 4.2
    t = tvec(dur)
    x = np.zeros(len(t))
    cut = 0.18
    run = 1.0 - (t >= cut)
    rps = motor_rps(220.0) + 0 * t
    x += db(2) * spool(rng, t, rps, 1 / 3 + 0 * t, load=0.5) * run * ramp(t, 0.0, 0.03)
    x += db(-6) * unit(controller_bed(rng, len(t), circular=False)) * run * ramp(t, 0.0, 0.03)
    place(x, unit(contactor(rng, 0.35)), cut - 0.004, db(-5))
    arc = noise(rng, int(0.09 * SR), 900, 11000, circular=False)
    gate = (rng.random(len(arc)) < 0.02).astype(float)
    gate = np.convolve(gate, np.hanning(60), "same")
    place(x, unit(arc * gate * np.exp(-tvec(0.09) / 0.03)), cut, db(-6))
    for tc in (0.55, 0.9):
        place(x, relay_click(rng, 1.4, 0.03), tc, db(-26))
    for tc, b in ((1.30, 1.0), (1.34, 1.08), (1.41, 0.95), (1.47, 1.1), (1.62, 1.0)):
        place(x, relay_click(rng, b), tc, db(-10))
    place(x, unit(contactor(rng)), 1.8, db(-8))
    for tc in (2.0, 2.08, 2.16, 2.40):
        place(x, unit(boot_tick(rng)), tc, db(-13))
    x += db(-22) * pwm_chirp(t, 600.0, 1875.0, 1.9, 2.6, ramp(t, 1.85, 1.95))
    rps2 = 20.0 * ramp(t, 2.3, 2.9) * (1.0 - ramp(t, 3.0, 3.7))
    x += db(1) * spool(rng, t, rps2, 1 / 3 + 0 * t, load=0.4)
    x += db(-7) * unit(controller_bed(rng, len(t), circular=False)) * ramp(t, 2.6, 3.6)
    return x * (1.0 - ramp(t, dur - 0.05, dur))


# ------------------------------------------------------------------------------ sounds: hatch

def s_hatch_lock(rng):
    a = "SFX_Carrier_Hatch_LockRelease"
    dur = 1.0
    t = tvec(dur)
    x = np.zeros(len(t))
    sol = relay_click(rng, 0.75, 0.12) + 0.8 * np.sin(TWO_PI * 95.0 * tvec(0.12)) * decay(tvec(0.12), 0.0, 0.001, 0.025)
    place(x, unit(sol), 0.03, db(-3))  # the lock solenoid pulls
    lat = rec("latch")
    uses(a, "latch", "whole sound, varispeed x0.8, low-passed at 9 kHz")
    place(x, unit(band(edge_fade(varispeed(lat, 0.8), 0.003, 0.05), 80, 9000)), 0.02, 1.0)
    st = rec("steam")
    uses(a, "steam", "0.9-1.5 s of the hiss as a short seal-pressure release, high-passed")
    puff = band(seg(st, 0.9, 0.6), 1200, 12000) * ramp(tvec(0.6), 0.0, 0.03) * np.exp(-tvec(0.6) / 0.15)
    place(x, unit(puff), 0.24, db(-14))
    place(x, unit(_thump(rng, 120.0, 0.2)), 0.26, db(-10))
    return x * (1.0 - ramp(t, dur - 0.05, dur))


def s_hatch_open(rng):
    a = "SFX_Carrier_Hatch_Open"
    dur = 4.8
    t = tvec(dur)
    x = np.zeros(len(t))
    st = rec("steam")
    hiss = band(varispeed(seg(st, 0.55, 2.4), 0.9), 350, 11000)
    henv = ramp(tvec(len(hiss) / SR), 0.0, 0.06) * (1.0 - ramp(tvec(len(hiss) / SR), 1.2, len(hiss) / SR))
    place(x, unit(hiss * henv), 0.0, db(-6))
    uses(a, "steam", "0.55-2.95 s, varispeed x0.9, the hydraulic ram venting as it pushes")
    gr = rec("groan")
    hinge = band(varispeed(seg(gr, 3.3, 4.6), 0.85), 45, 7000)
    uses(a, "groan", "3.3-7.9 s, varispeed x0.85, the heavy hinge swinging")
    place(x, unit(edge_fade(hinge, 0.15, 0.6)), 0.25, db(-2))
    ram = noise(rng, len(t), 60, 260, circular=False) * ramp(t, 0.2, 0.6) * (1.0 - ramp(t, 3.6, 4.1))
    x += db(-14) * ram  # the ram body, low
    lid, on_lid = _hits("lid_rattle")
    stop = band(varispeed(seg(lid, on_lid[4] - 0.003, 0.5), 0.5), 50, 4000)
    uses(a, "lid_rattle", "impact 5, varispeed x0.5, the hatch hitting its end stop")
    place(x, unit(edge_fade(stop, 0.002, 0.15)), 4.05, db(-3))
    place(x, unit(_thump(rng, 60.0, 0.4)), 4.05, db(-3))
    return x * (1.0 - ramp(t, dur - 0.05, dur))


# ------------------------------------------------------------------------------ catalogue

@dataclass
class Sound:
    name: str
    make: Callable[[np.random.Generator], np.ndarray]
    seed: int
    loop: bool = False
    group: str = ""
    note: str = ""
    procedural: bool = True
    meta: dict = field(default_factory=dict)


def _catalogue() -> list[Sound]:
    S = []
    add = S.append
    add(Sound("SFX_Carrier_Motor_Idle_Loop", s_motor_idle, 7001, True, "motor", "controller buzz, coil whine, tired fan"))
    add(Sound("SFX_Carrier_Motor_Low_Loop", s_motor_low, 7002, True, "motor", "drive motor at ~157 cm/s"))
    add(Sound("SFX_Carrier_Motor_High_Loop", s_motor_high, 7003, True, "motor", "drive motor at ~393 cm/s"))
    add(Sound("SFX_Carrier_Motor_Strain_Loop", s_motor_strain, 7004, True, "strain", "overloaded climb at ~118 cm/s"))
    for nm, fn, sd in (("Dirt", s_wheels_dirt, 7010), ("Gravel", s_wheels_gravel, 7011), ("Slabs", s_wheels_slabs, 7012)):
        add(Sound(f"SFX_Carrier_Wheels_{nm}_Loop", fn, sd, True, "wheels", procedural=False))
    for nm, fn, sd in (("Dirt", s_trailer_dirt, 7015), ("Gravel", s_trailer_gravel, 7016), ("Slabs", s_trailer_slabs, 7017)):
        add(Sound(f"SFX_Carrier_Trailer_Wheels_{nm}_Loop", fn, sd, True, "trailer", procedural=False,
                  note="" if nm == "Slabs" else "recording only"))
    for side in ("L", "R"):
        for i in range(3):
            add(Sound(f"SFX_Carrier_Steer_Servo_{side}_{i + 1:02d}", (lambda s, i: lambda r: s_steer(r, s, i))(side, i),
                      7020 + i + (10 if side == "R" else 0), group="steer"))
    for i in range(8):
        add(Sound(f"SFX_Carrier_Suspension_Clunk_{i + 1:02d}", (lambda i: lambda r: s_clunk(r, i))(i), 7040 + i,
                  group="suspension", procedural=False))
    add(Sound("SFX_Carrier_Chassis_Creak_Loop", s_chassis_creak, 7050, True, "suspension", procedural=False))
    add(Sound("SFX_Carrier_Drawbar_Rattle_Loop", s_drawbar_rattle, 7051, True, "trailer", procedural=False))
    for i in range(4):
        add(Sound(f"SFX_Carrier_Drawbar_Clank_{i + 1:02d}", (lambda i: lambda r: s_drawbar_clank(r, i))(i), 7052 + i,
                  group="trailer", procedural=False))
    for i in range(4):
        add(Sound(f"SFX_Carrier_Knee_Grind_{i + 1:02d}", (lambda i: lambda r: s_knee_grind(r, i))(i), 7060 + i, group="strain"))
    add(Sound("SFX_Carrier_State_Start", s_state_start, 7070, group="state"))
    add(Sound("SFX_Carrier_State_StartStop", s_state_startstop, 7071, group="state", procedural=False))
    add(Sound("SFX_Carrier_State_Shutdown", s_state_shutdown, 7072, group="state", procedural=False))
    add(Sound("SFX_Carrier_State_EmergencyReboot", s_state_reboot, 7073, group="state"))
    for i in range(4):
        add(Sound(f"SFX_Carrier_Mast_Tick_{i + 1:02d}", (lambda i: lambda r: s_mast_tick(r, i))(i), 7080 + i, group="mast"))
    add(Sound("SFX_Carrier_Hatch_LockRelease", s_hatch_lock, 7090, group="hatch", procedural=False))
    add(Sound("SFX_Carrier_Hatch_Open", s_hatch_open, 7091, group="hatch", procedural=False))
    return S


CATALOGUE = _catalogue()


def finish(sound: Sound, x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if sound.loop:
        return loop_norm(x)
    x = band(x, 20.0, None, width_oct=0.6)  # remove DC and sub-audio drift
    x = edge_fade(x, 0.002, 0.03)
    return peak_norm(x)


def write(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(path), np.clip(x, -1.0, 1.0), SR, subtype="PCM_16")


def measure(path: Path, loop: bool) -> dict:
    x, sr = soundfile.read(str(path), dtype="float64")
    info = {"sr": sr, "channels": 1 if x.ndim == 1 else x.shape[1], "dur_s": round(len(x) / sr, 3),
            "lufs": round(lufs(x), 1), "peak_db": round(20 * np.log10(np.max(np.abs(x)) + 1e-12), 2),
            "true_peak_db": round(true_peak_db(x), 2)}
    if loop:  # seam: the wrap step vs the typical sample step, and the level either side of it
        d = np.abs(np.diff(x))
        info["seam_step_ratio"] = round(float(abs(x[0] - x[-1]) / (np.percentile(d, 99.9) + 1e-12)), 3)
        w = int(0.25 * sr)
        info["seam_level_jump_db"] = round(20 * np.log10(rms(x[:w]) / rms(x[-w:])), 2)
    else:
        info["edges"] = [round(float(abs(x[0])), 5), round(float(abs(x[-1])), 5)]
    return info


def check_info(sound: Sound, info: dict) -> list[str]:
    p = []
    if info["sr"] != SR or info["channels"] != 1:
        p.append(f"{info['sr']} Hz x {info['channels']} ch")
    if sound.loop:
        if abs(info["lufs"] - LOOP_LUFS) > 0.6:
            p.append(f"loudness {info['lufs']} LUFS")
        if info["true_peak_db"] > LOOP_MAX_PEAK_DB + 0.3:
            p.append(f"true peak {info['true_peak_db']} dBFS")
        if info["seam_step_ratio"] > 1.0:
            p.append(f"loop seam step {info['seam_step_ratio']} x the 99.9th-percentile step")
        if abs(info["seam_level_jump_db"]) > 6.0:
            p.append(f"loop seam level jump {info['seam_level_jump_db']} dB")
    else:
        if abs(info["peak_db"] - ONESHOT_PEAK_DB) > 0.3:
            p.append(f"peak {info['peak_db']} dBFS")
        if max(info["edges"]) > 0.002:
            p.append(f"edges not silent {info['edges']}")
    return p


# ------------------------------------------------------------------------------ demo + layer rules

# The layer rules below are the ones task-CARRIERSFX-brief.md gives the MetaSound. Keep them in sync.
LAYER_DB = {  # SoundWave-level trims, applied on top of the -20 LUFS / -3 dBFS masters
    "idle": -12.0, "low": 0.0, "high": 0.0, "strain": 0.0,
    "wheels": -6.0, "trailer": -13.0, "creak": -14.0, "rattle": -14.0,
    "clunk": -2.0, "clank": -7.0, "steer": -11.0, "mast": -15.0, "knee": -3.0, "state": -4.0,
}
SURFACE_ROUGH = (0.45, 0.75, 1.0)  # dirt, gravel, slabs


def layer_gains(speed, throttle, strain_w, surface_w):
    """Per-sample gains/pitches from control curves (numpy arrays). surface_w: (3, n) weights."""
    ref_low = MOTOR_REF.get("SFX_Carrier_Motor_Low_Loop", 157.1)
    ref_high = MOTOR_REF.get("SFX_Carrier_Motor_High_Loop", 392.7)
    ref_str = MOTOR_REF.get("SFX_Carrier_Motor_Strain_Loop", 117.8)
    load = (0.75 + 0.25 * throttle) * (0.45 + 0.55 * smoothstep(0, 500, speed))  # louder with load and rpm
    g = {
        "idle": (1.0 - 0.5 * smoothstep(0, 150, speed)) * db(LAYER_DB["idle"]),
        "low": smoothstep(3, 60, speed) * (1 - smoothstep(210, 310, speed)) * load * db(-4 * strain_w),
        "high": smoothstep(210, 310, speed) * load * db(-4 * strain_w),
        "strain": strain_w,
        "wheels": smoothstep(2, 90, speed) * (0.55 + 0.45 * speed / 500) * db(LAYER_DB["wheels"]),
        "trailer": smoothstep(2, 90, speed) * (0.55 + 0.45 * speed / 500) * db(LAYER_DB["trailer"]),
    }
    rough = sum(surface_w[i] * SURFACE_ROUGH[i] for i in range(3))
    g["creak"] = (rough * smoothstep(20, 250, speed) + 0.6 * strain_w) * db(LAYER_DB["creak"])
    g["rattle"] = rough * smoothstep(30, 320, speed) * db(LAYER_DB["rattle"])
    p = {
        "idle": 1.0 + 0.03 * throttle,
        "low": np.clip(speed / ref_low, 0.3, 2.0),
        "high": np.clip(speed / ref_high, 0.5, 1.3),
        "strain": np.clip(speed / ref_str, 0.6, 1.5),
        "wheels": 0.8 + 0.4 * speed / 500,
        "trailer": 0.85 + 0.45 * speed / 500,
        "creak": 1.0 + 0 * speed,
        "rattle": 0.9 + 0.2 * speed / 500,
    }
    return g, p


def loop_play(x: np.ndarray, rate: np.ndarray, start: float = 0.0) -> np.ndarray:
    pos = (start * len(x) + np.cumsum(rate)) % len(x)
    i0 = np.floor(pos).astype(int)
    fr = pos - i0
    return x[i0] * (1 - fr) + x[(i0 + 1) % len(x)] * fr


def _curve(t, keys):
    kt, kv = zip(*keys)
    return np.interp(t, kt, kv)


def smooth_ctrl(x, tau):
    """One-pole smoothing like MetaSound's Interp To (tau in s)."""
    a = 1.0 - np.exp(-1.0 / (tau * SR))
    y = np.empty_like(x)
    acc = x[0]
    for i in range(0, len(x), 480):  # control rate 100 Hz, then held
        blk = x[i:i + 480]
        acc += (blk.mean() - acc) * (1.0 - (1.0 - a) ** len(blk))
        y[i:i + 480] = acc
    return y


def demo(files: dict[str, np.ndarray], rng: np.random.Generator) -> tuple[np.ndarray, list[str]]:
    dur = 32.0
    t = tvec(dur)
    n = len(t)
    speed = _curve(t, [(0, 0), (3.0, 0), (5.0, 120), (9.0, 430), (16.0, 430), (19.0, 230), (21.5, 165), (23.5, 175),
                       (25.3, 320), (26.0, 320), (27.0, 30), (27.25, 0), (dur, 0)])
    speed = smooth_ctrl(speed, 0.15)
    throttle = _curve(t, [(0, 0), (3.0, 0), (3.1, 1), (9.0, 1), (9.5, 0.45), (15.8, 0.45), (16.2, 1), (26.0, 1), (26.05, 0), (dur, 0)])
    slope = _curve(t, [(0, 0), (16.0, 1.0), (17.5, 14.0), (22.8, 16.0), (23.6, 2.0), (dur, 2.0)])
    strain_b = (slope > 12.0).astype(float)
    strain_w = smooth_ctrl(strain_b, 0.25)
    surf = np.full(n, 1)                           # gravel
    surf[(t >= 16.0) & (t < 23.6)] = 0             # climb on packed dirt
    surf[t >= 23.6] = 2                            # crest onto broken slabs
    surface_w = np.stack([smooth_ctrl((surf == k).astype(float), 0.12) for k in range(3)])
    power = ramp(t, 1.6, 2.4) * (1.0 - ramp(t, 28.35, 28.9))
    g, p = layer_gains(speed, throttle, strain_w, surface_w)
    mix = np.zeros(n)
    rate = lambda pitch: pitch  # noqa: E731 (playback rate = pitch ratio)
    mix += power * g["idle"] * loop_play(files["SFX_Carrier_Motor_Idle_Loop"], rate(p["idle"]))
    for key, name in (("low", "SFX_Carrier_Motor_Low_Loop"), ("high", "SFX_Carrier_Motor_High_Loop"),
                      ("strain", "SFX_Carrier_Motor_Strain_Loop")):
        mix += g[key] * db(LAYER_DB[key]) * loop_play(files[name], rate(p[key]), rng.random())
    for k, nm in enumerate(("Dirt", "Gravel", "Slabs")):
        mix += surface_w[k] * g["wheels"] * loop_play(files[f"SFX_Carrier_Wheels_{nm}_Loop"], p["wheels"], rng.random())
        mix += surface_w[k] * g["trailer"] * loop_play(files[f"SFX_Carrier_Trailer_Wheels_{nm}_Loop"], p["trailer"], rng.random())
    mix += g["creak"] * loop_play(files["SFX_Carrier_Chassis_Creak_Loop"], p["creak"], rng.random())
    mix += g["rattle"] * loop_play(files["SFX_Carrier_Drawbar_Rattle_Loop"], p["rattle"], rng.random())
    events = [
        (0.35, "SFX_Carrier_State_Start", "state"),
        (4.2, "SFX_Carrier_Mast_Tick_02", "mast"), (4.7, "SFX_Carrier_Mast_Tick_03", "mast"),
        (6.4, "SFX_Carrier_Steer_Servo_L_02", "steer"), (7.6, "SFX_Carrier_Steer_Servo_R_01", "steer"),
        (12.3, "SFX_Carrier_Suspension_Clunk_03", "clunk"),
        (12.3 + 330 / 430, "SFX_Carrier_Drawbar_Clank_02", "clank"),   # the trailer reaches the bump
        (13.6, "SFX_Carrier_Suspension_Clunk_06", "clunk"),
        (14.2, "SFX_Carrier_Steer_Servo_R_02", "steer"),
        (18.4, "SFX_Carrier_Knee_Grind_02", "knee"), (20.2, "SFX_Carrier_Steer_Servo_L_03", "steer"),
        (21.3, "SFX_Carrier_Knee_Grind_03", "knee"),
        (23.9, "SFX_Carrier_Suspension_Clunk_01", "clunk"), (23.9 + 330 / 200, "SFX_Carrier_Drawbar_Clank_04", "clank"),
        (26.9, "SFX_Carrier_State_StartStop", "state"),
        (28.3, "SFX_Carrier_State_Shutdown", "state"),
    ]
    for tc, name, grp in events:
        place(mix, files[name], tc, db(LAYER_DB[grp]))
    mix = mix * db(-18.0 - lufs(mix))
    if np.max(np.abs(mix)) > db(-1.0):
        mix = mix * db(-1.0) / np.max(np.abs(mix))
    lines = [f"{tc:5.2f} s  {name}" for tc, name, _ in events]
    return edge_fade(mix, 0.01, 0.3), lines


# ------------------------------------------------------------------------------ main

def build(only: str | None) -> dict[str, np.ndarray]:
    files: dict[str, np.ndarray] = {}
    manifest = {}
    for s in CATALOGUE:
        path = OUT / f"{s.name}.wav"
        if only and only not in s.name:
            if path.exists():
                files[s.name] = soundfile.read(str(path), dtype="float64")[0]
            continue
        x = finish(s, s.make(np.random.default_rng(s.seed)))
        write(path, x)
        files[s.name] = x
        print(f"wrote {s.name}.wav  {len(x) / SR:5.2f} s")
    for s in CATALOGUE:
        path = OUT / f"{s.name}.wav"
        info = measure(path, s.loop)
        manifest[s.name] = {"loop": s.loop, "group": s.group, "source": "procedural" if not CREDITS.get(s.name)
                            else "Freesound (processed)" if s.note == "recording only" else "procedural + Freesound", "note": s.note, **info,
                            "freesound": [RECS[k].id for k, _ in CREDITS.get(s.name, [])]}
        if s.name in MOTOR_REF:
            manifest[s.name]["ref_speed_cm_s"] = round(MOTOR_REF[s.name], 2)
    if not only:
        mix, lines = demo(files, np.random.default_rng(7999))
        write(OUT / "_demo_drive.wav", mix)
        (OUT / "_demo_drive.txt").write_text(
            "Contact-sheet drive (mono, -18 LUFS): start, accelerate on gravel, cruise, a bump at 12.3 s, a steep\n"
            "dirt climb 16-23.5 s with strain and the knee, crest onto slabs, stop at 27 s, shutdown at 28.3 s.\n\n"
            + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote _demo_drive.wav  {len(mix) / SR:.1f} s")
        write_credits()
        (OUT / "manifest.json").write_text(json.dumps({"layer_db": LAYER_DB, "files": manifest}, indent=1),
                                           encoding="utf-8", newline="\n")
    return files


def check() -> bool:
    ok = 0
    for s in CATALOGUE:
        path = OUT / f"{s.name}.wav"
        if not path.exists():
            print(f"  FAIL {s.name}: missing")
            continue
        info = measure(path, s.loop)
        prob = check_info(s, info)
        ok += not prob
        extra = (f"seam step {info['seam_step_ratio']:.2f}, jump {info['seam_level_jump_db']:+.1f} dB" if s.loop
                 else f"edges {info['edges']}")
        print(f"  {'PASS' if not prob else 'FAIL'} {s.name:<42} {info['dur_s']:6.2f} s  {info['lufs']:6.1f} LUFS  "
              f"peak {info['peak_db']:6.2f}  tp {info['true_peak_db']:6.2f}  {extra}")
        for q in prob:
            print(f"        - {q}")
    print(f"check: {ok}/{len(CATALOGUE)} pass (48 kHz mono; loops -20 LUFS, true peak <= -1 dBFS, seamless wrap;"
          f" one-shots peak -3 dBFS, silent edges)")
    return ok == len(CATALOGUE)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only measure the existing files")
    ap.add_argument("--only", help="rebuild only sounds whose name contains this (no demo, no credits)")
    a = ap.parse_args(argv)
    if not a.check:
        build(a.only)
    return 0 if check() else 1


if __name__ == "__main__":
    sys.exit(main())
