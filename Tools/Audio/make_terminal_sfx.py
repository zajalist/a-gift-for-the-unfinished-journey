#!/usr/bin/env python3
"""Synthesise the retro boot-terminal SFX for the carrier's boot and reboot screens.

Writes 48 kHz mono 16-bit PCM WAVs and a manifest.json to
<project>/Saved/GameAudio/Terminal/. numpy only, one fixed seed per sound, so every run
writes byte-identical files. A later step imports them into
/Game/SaskartaGaea/Audio/Terminal/ (see the manifest); this script never touches Unreal.

    python Tools/Audio/make_terminal_sfx.py            # generate, then run the check
    python Tools/Audio/make_terminal_sfx.py --check    # re-read existing files, check only
    python Tools/Audio/make_terminal_sfx.py --out DIR  # write somewhere else

No music. Every tone here has a physical source: the PC-speaker style system beep
(one short 1 kHz square beep, SFX_Term_OK_Blip, the only beep), the CRT's 15.7 kHz
line-output (flyback) transformer whine, mains hum at 50 Hz and its harmonics, a fan's
blade-pass hum and a drive's stepper buzz.

Where each sound plays is in Tools/GameFlow/RETRO_BOOT.md (section Sound) and in the
manifest's "plays" field.

--check (exit status 1 on any failure), per file:
  format      48000 Hz, 16-bit PCM, mono
  duration    within +/-5 ms of the table below
  peak        one-shots -3.5..-2.5 dBFS, the loop -12.5..-11.5 dBFS
  DC          |mean| <= 0.5 % FS
  edges       one-shots: first and last sample <= 16 LSB
  loop seam   RMS of the last 50 ms vs the first 50 ms within 3 dB, and the wrap step
              |x[0] - x[-1]| no bigger than the 99.9th percentile step inside the file
  beep        SFX_Term_OK_Blip: strongest spectral peak between 900 and 1200 Hz, and the
              beep is shorter than 0.15 s
  flyback     SFX_Term_CRT_PowerOn: a narrow peak at 15.73 kHz at least 20 dB over the
              neighbouring 14-15.2 kHz band, and quiet: the 15.4-16.1 kHz band is at least
              15 dB under the whole-file RMS, and its last 0.3 s is 10 dB under its first 1 s
  bursts      SFX_Term_Teletype_Burst_*: 0.2..0.6 s with 6 or more distinct strikes
  determinism the file on disk equals a fresh render, byte for byte
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

SR = 48_000
PCM_SCALE = 32767.0
FULL_SCALE = 32768.0
EDGE_FADE_S = 0.003
ONESHOT_PEAK_DBFS = -3.0
LOOP_PEAK_DBFS = -12.0

DURATION_TOL_S = 0.005
ONESHOT_PEAK_RANGE = (-3.5, -2.5)
LOOP_PEAK_RANGE = (-12.5, -11.5)
MAX_DC_PERCENT = 0.5
MAX_EDGE_LSB = 16

UE_FOLDER = "/Game/SaskartaGaea/Audio/Terminal"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameAudio" / "Terminal"


# --------------------------------------------------------------------------- helpers

def tvec(n: int) -> np.ndarray:
    return np.arange(n) / SR


def nsamp(seconds: float) -> int:
    return int(round(seconds * SR))


def fft_filter(x: np.ndarray, lo: float | None = None, hi: float | None = None, order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth-magnitude band filter in the frequency domain.

    Circular, which is what the loop wants (the seam stays continuous); one-shots pad
    first so their tails do not wrap around.
    """
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    gain = np.ones_like(f)
    if lo is not None:
        with np.errstate(divide="ignore"):
            gain *= 1.0 / np.sqrt(1.0 + (lo / np.maximum(f, 1e-9)) ** (2 * order))
    if hi is not None:
        gain *= 1.0 / np.sqrt(1.0 + (f / hi) ** (2 * order))
    return np.fft.irfft(spec * gain, len(x))


def band(x: np.ndarray, lo: float | None = None, hi: float | None = None, order: int = 2) -> np.ndarray:
    pad = np.zeros(len(x) + nsamp(0.05))
    pad[: len(x)] = x
    return fft_filter(pad, lo, hi, order)[: len(x)]


def modal(freqs, taus, amps, dur: float, attack: float = 0.0003, phase_rng: np.random.Generator | None = None) -> np.ndarray:
    """Sum of exponentially decaying sines: a struck object's ring."""
    t = tvec(nsamp(dur))
    out = np.zeros_like(t)
    for i, (f, tau, a) in enumerate(zip(freqs, taus, amps)):
        ph = 0.0 if phase_rng is None else phase_rng.uniform(0, 2 * np.pi)
        out += a * np.sin(2 * np.pi * f * t + ph) * np.exp(-t / tau)
    ramp = np.clip(t / attack, 0.0, 1.0)
    return out * ramp


def noise_burst(rng: np.random.Generator, dur: float, lo: float, hi: float, tau: float) -> np.ndarray:
    n = nsamp(dur)
    t = tvec(n)
    return band(rng.standard_normal(n), lo, hi, 2) * np.exp(-t / tau)


def add_at(buf: np.ndarray, x: np.ndarray, t0: float, gain: float = 1.0) -> None:
    i = nsamp(t0)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(x))
    buf[i:j] += gain * x[: j - i]


def env_ramp(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 before start, 1 after end, raised cosine in between."""
    u = np.clip((t - start) / max(end - start, 1e-9), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def edge_fades(n: int, fade_s: float) -> np.ndarray:
    k = min(nsamp(fade_s), n // 2)
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    g = np.ones(n)
    g[:k] *= ramp
    g[n - k:] *= ramp[::-1]
    return g


# --------------------------------------------------------------------------- sources

def key_click(rng: np.random.Generator, body_hz: float, shell_hz: float, weight: float = 1.0,
              release: bool = True) -> np.ndarray:
    """One mechanical key: the tick of the switch, the plastic shell ring, the bottom-out
    thump, and a smaller release click."""
    dur = 0.11
    out = np.zeros(nsamp(dur))
    tick = noise_burst(rng, 0.006, 2500, 12000, 0.0008)
    shell = modal([shell_hz, shell_hz * 1.53, shell_hz * 2.31], [0.006, 0.004, 0.0025],
                  [0.5, 0.3, 0.15], 0.05, phase_rng=rng)
    thump = modal([body_hz, body_hz * 1.9], [0.009, 0.005], [0.8 * weight, 0.25 * weight], 0.05, attack=0.0008)
    add_at(out, tick, 0.0, 1.0)
    add_at(out, shell, 0.0005, 0.9)
    add_at(out, thump, 0.001, 0.9)
    if release:
        rel_t = rng.uniform(0.045, 0.07)
        add_at(out, noise_burst(rng, 0.004, 3000, 12000, 0.0006), rel_t, 0.35)
        add_at(out, modal([shell_hz * 1.1], [0.004], [0.3], 0.03, phase_rng=rng), rel_t, 0.5)
    return out


def print_strike(rng: np.random.Generator) -> np.ndarray:
    """A teleprinter strike: key/relay tick plus a small metallic type-bar ring."""
    k = key_click(rng, rng.uniform(170, 260), rng.uniform(1700, 2600), rng.uniform(0.5, 1.0), release=False)
    ring = modal([rng.uniform(4200, 5600), rng.uniform(6800, 7900)], [0.003, 0.002], [0.25, 0.12], 0.02, phase_rng=rng)
    add_at(k, ring, 0.0003, rng.uniform(0.6, 1.0))
    return k[: nsamp(0.06)]


# --------------------------------------------------------------------------- sounds

def teletype_burst(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Dense key / relay chatter for one typed line: ~55 strikes a second with jitter,
    one or two short stalls (the typewriter's pauses), over a faint print-motor bed."""
    n = nsamp(duration)
    out = np.zeros(n)
    t = tvec(n)
    onset = 0.004
    stalls = sorted(rng.uniform(0.12, duration - 0.12, size=int(rng.integers(1, 3))))
    while onset < duration - 0.05:
        amp = rng.uniform(0.55, 1.0)
        add_at(out, print_strike(rng), onset, amp)
        step = rng.uniform(0.013, 0.024)
        if stalls and onset > stalls[0]:
            step += rng.uniform(0.05, 0.075)
            stalls.pop(0)
        onset += step
    motor = band(rng.standard_normal(n), 90, 700, 2) * (0.6 + 0.4 * np.sin(2 * np.pi * 31 * t + rng.uniform(0, 6.3)))
    motor *= env_ramp(t, 0.0, 0.03) * (1.0 - env_ramp(t, duration - 0.06, duration))
    return out + 0.05 * motor / (np.max(np.abs(motor)) + 1e-9)


def single_key(rng: np.random.Generator, duration: float) -> np.ndarray:
    out = np.zeros(nsamp(duration))
    add_at(out, key_click(rng, rng.uniform(150, 240), rng.uniform(1500, 2800), rng.uniform(0.8, 1.1)), 0.002)
    return out


def line_feed(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Platen ratchet (three fast metallic clicks) and the carriage thunk."""
    n = nsamp(duration)
    out = np.zeros(n)
    t = tvec(n)
    for i, t0 in enumerate([0.003, 0.024, 0.044]):
        add_at(out, noise_burst(rng, 0.004, 3000, 12000, 0.0007), t0, 0.6)
        add_at(out, modal([3400 + 250 * i, 5200], [0.004, 0.0025], [0.5, 0.2], 0.03, phase_rng=rng), t0, 0.8)
    add_at(out, modal([105, 190, 610], [0.045, 0.02, 0.008], [1.0, 0.4, 0.25], 0.25, attack=0.001), 0.068, 1.0)
    add_at(out, noise_burst(rng, 0.008, 800, 6000, 0.0015), 0.068, 0.7)
    whirr = band(rng.standard_normal(n), 400, 2500, 2) * env_ramp(t, 0.01, 0.03) * np.exp(-np.maximum(t - 0.03, 0) / 0.05)
    return out + 0.12 * whirr


def ok_blip(rng: np.random.Generator, duration: float) -> np.ndarray:
    """PC-speaker style system beep: a 1 kHz square wave (odd harmonics), 0.1 s, soft edges.
    This is the only beep in the terminal set and it plays once per boot."""
    n = nsamp(duration)
    t = tvec(n)
    f0 = 1000.0
    sq = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 3, 5, 7))
    gate = env_ramp(t, 0.0, 0.002) * (1.0 - env_ramp(t, 0.094, 0.102))
    return band(sq * gate, None, 6500, 2)


def drive_seek(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Floppy / tape drive: head-load solenoid clack, spindle motor whirr spinning up and
    down, three stepper seeks (buzzy step trains), a few single steps, head unload."""
    n = nsamp(duration)
    t = tvec(n)
    out = np.zeros(n)

    def clack(t0, g):
        add_at(out, noise_burst(rng, 0.006, 1200, 9000, 0.0012), t0, 0.8 * g)
        add_at(out, modal([118, 240, 2200], [0.03, 0.012, 0.006], [0.9, 0.35, 0.3], 0.12, attack=0.0008, phase_rng=rng), t0, g)

    def steps(t0, count, period, g):
        for i in range(count):
            s = modal([rng.uniform(380, 460), rng.uniform(1600, 2400)], [0.004, 0.002], [0.7, 0.4], 0.02, phase_rng=rng)
            s += noise_burst(rng, 0.02, 1500, 8000, 0.0006) * 0.4
            add_at(out, s, t0 + i * period + rng.uniform(-0.0004, 0.0004), g * rng.uniform(0.8, 1.0))

    clack(0.01, 1.0)
    steps(0.14, 38, 0.0068, 0.55)
    steps(0.60, 14, 0.0075, 0.5)
    for t0 in (0.86, 0.93, 1.01):
        steps(t0, 1, 0.01, 0.6)
    steps(1.08, 26, 0.0062, 0.55)
    clack(1.40, 0.7)

    spin = env_ramp(t, 0.02, 0.28) * (1.0 - env_ramp(t, 1.30, 1.49))
    whirr = band(rng.standard_normal(n), 180, 1400, 2) * (0.75 + 0.25 * np.sin(2 * np.pi * 5.0 * t))
    freq = 142.0 + 8.0 * env_ramp(t, 0.02, 0.28)  # brushless spindle motor buzz, rising to speed
    phase = 2 * np.pi * np.cumsum(freq) / SR
    buzz = 0.5 * np.sin(phase) + 0.25 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase)
    motor = spin * (0.07 * whirr / (np.max(np.abs(whirr)) + 1e-9) + 0.035 * buzz)
    return out + motor


def crt_power_on(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Degauss thunk (a mains-frequency surge through the degauss coil, the shadow mask
    ringing) and a relay click, then the quiet 15.73 kHz line-output whine, fading."""
    n = nsamp(duration)
    t = tvec(n)
    out = np.zeros(n)
    add_at(out, noise_burst(rng, 0.008, 1500, 10000, 0.0012), 0.0, 0.5)  # power relay
    surge = np.exp(-np.maximum(t - 0.02, 0) / 0.32) * env_ramp(t, 0.015, 0.03)
    hum = sum(a * np.sin(2 * np.pi * 50.0 * k * t) for k, a in ((1, 1.0), (2, 0.55), (3, 0.35), (4, 0.18), (6, 0.1)))
    buzz = np.tanh(3.0 * np.sin(2 * np.pi * 100.0 * t)) * 0.25  # coil magnetostriction buzz
    add_at(out, (hum + buzz) * surge, 0.0, 0.9)
    add_at(out, modal([88, 176, 263, 530], [0.25, 0.12, 0.08, 0.03], [1.0, 0.45, 0.25, 0.12], 1.2, attack=0.004), 0.02, 0.8)
    add_at(out, noise_burst(rng, 0.4, 2000, 9000, 0.09) * 0.25, 0.06)  # static charging the glass
    whine_env = env_ramp(t, 0.08, 0.25) * (1.0 - env_ramp(t, 0.9, duration - 0.01))
    whine = np.sin(2 * np.pi * 15734.0 * t + 0.4 * np.sin(2 * np.pi * 0.7 * t)) * whine_env
    base = out / (np.max(np.abs(out)) + 1e-9)
    return base + 0.035 * whine  # about -29 dB under the thunk's peak


def crt_power_off(rng: np.random.Generator, duration: float) -> np.ndarray:
    """The collapse zap: a snap, the line-output whine diving as the raster collapses,
    a crackle of static and a low thump."""
    n = nsamp(duration)
    t = tvec(n)
    out = np.zeros(n)
    add_at(out, noise_burst(rng, 0.01, 2000, 14000, 0.0015), 0.0, 0.9)
    f = 15734.0 * np.exp(-t / 0.018) + 900.0 * np.exp(-t / 0.06) + 60.0
    dive = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.05)
    out += 0.45 * dive
    zap = rng.standard_normal(n) * np.exp(-t / 0.035)
    centre_lo = band(zap, 600, 4000, 2)
    out += 0.5 * centre_lo / (np.max(np.abs(centre_lo)) + 1e-9)
    add_at(out, modal([62, 124], [0.06, 0.03], [1.0, 0.3], 0.3, attack=0.002), 0.004, 0.8)
    crackle = np.zeros(n)
    for c in rng.uniform(0.03, duration - 0.05, size=18):
        add_at(crackle, noise_burst(rng, 0.004, 2500, 12000, 0.0006), c, rng.uniform(0.1, 0.35) * np.exp(-c / 0.18))
    return out + crackle


def fan_hum_loop(rng: np.random.Generator, duration: float) -> np.ndarray:
    """Cooling fan and power supply, a seamless 20 s loop: circular band noise for the air,
    the fan's blade-pass hum wandering slightly, mains hum at 50 Hz with transformer
    harmonics. Every periodic part has a whole number of cycles in the loop."""
    n = nsamp(duration)
    t = tvec(n)
    air = fft_filter(rng.standard_normal(n), 70, 2400, 1)
    air = fft_filter(air, None, 5000, 3)
    air /= np.max(np.abs(air))
    wob = 1.0 + 0.08 * np.sin(2 * np.pi * (3 / duration) * t) + 0.05 * np.sin(2 * np.pi * (7 / duration) * t + 1.0)
    bp_f0 = 294.0  # 7 blades at 42 rev/s
    bp_phase = 2 * np.pi * bp_f0 * t + 1.5 * np.sin(2 * np.pi * (2 / duration) * t)  # slow speed wander, periodic
    blade = 0.6 * np.sin(bp_phase) + 0.2 * np.sin(2 * bp_phase + 0.3)
    mains = sum(a * np.sin(2 * np.pi * 50.0 * k * t + k) for k, a in ((1, 0.35), (2, 1.0), (3, 0.3), (4, 0.25), (6, 0.12)))
    return 0.8 * air * wob + 0.10 * blade + 0.12 * mains


@dataclass(frozen=True)
class Sound:
    name: str
    duration: float
    seed: int
    make: Callable[[np.random.Generator, float], np.ndarray]
    plays: str
    loop: bool = False
    volume: float = 1.0

    @property
    def filename(self) -> str:
        return self.name + ".wav"


SOUNDS: list[Sound] = [
    Sound("SFX_Term_Teletype_Burst_01", 0.36, 7101, teletype_burst,
          "BPC_CarrierVision.BootLineStep, typed line 1 (index 0). Reboot never uses it.", volume=0.7),
    Sound("SFX_Term_Teletype_Burst_02", 0.60, 7102, teletype_burst,
          "BPC_CarrierVision.BootLineStep, typed line 2 (index 1).", volume=0.7),
    Sound("SFX_Term_Teletype_Burst_03", 0.58, 7103, teletype_burst,
          "BPC_CarrierVision.BootLineStep, typed line 3 (index 2): first boot and reboot.", volume=0.7),
    Sound("SFX_Term_Teletype_Burst_04", 0.42, 7104, teletype_burst,
          "BPC_CarrierVision.BootLineStep, typed line 4 (index 3): first boot and reboot.", volume=0.7),
] + [
    Sound(f"SFX_Term_Key_{i:02d}", 0.12, 7200 + i, single_key,
          f"WBP_Saskarta_BootLog.ShowStatus: the status stamp on terminal row {i - 1}.", volume=0.6)
    for i in range(1, 7)
] + [
    Sound("SFX_Term_LineFeed", 0.35, 7301, line_feed,
          "WBP_Saskarta_BootLog.BeginTerminal (header printed) and PrintLine (a replayed log line printed at once).", volume=0.6),
    Sound("SFX_Term_OK_Blip", 0.12, 7401, ok_blip,
          "WBP_Saskarta_BootLog.MemoryDone: the memory test's [ OK ]. First boot only; the one beep in the set.", volume=0.35),
    Sound("SFX_Term_Drive_Seek", 1.50, 7501, drive_seek,
          "BPC_CarrierVision.PlayBoot, both kinds: the core image loading while the terminal comes up.", volume=0.55),
    Sound("SFX_Term_CRT_PowerOn", 2.20, 7601, crt_power_on,
          "BPC_CarrierVision.PlayBoot, both kinds: the terminal tube switching on at blackout.", volume=0.8),
    Sound("SFX_Term_CRT_PowerOff", 0.50, 7701, crt_power_off,
          "BPC_CarrierVision.PowerOn: the terminal tube collapses as the carrier's vision takes over.", volume=0.7),
    Sound("SFX_Term_Fan_Hum_Loop", 20.0, 7801, fan_hum_loop,
          "BPC_CarrierVision.PlayBoot SpawnSound2D into TermHum; StopHum fades it out at PowerOn. Import with looping on.",
          loop=True, volume=0.5),
]


# --------------------------------------------------------------------------- render / write

def render(sound: Sound) -> np.ndarray:
    rng = np.random.default_rng(sound.seed)
    x = np.asarray(sound.make(rng, sound.duration), dtype=np.float64)
    x = x[: nsamp(sound.duration)]
    if len(x) < nsamp(sound.duration):
        x = np.pad(x, (0, nsamp(sound.duration) - len(x)))
    x = x - np.mean(x)
    if not sound.loop:
        x = x * edge_fades(len(x), EDGE_FADE_S)
    peak_db = LOOP_PEAK_DBFS if sound.loop else ONESHOT_PEAK_DBFS
    x = x / (np.max(np.abs(x)) + 1e-12) * 10 ** (peak_db / 20)
    return np.round(x * PCM_SCALE).astype(np.int16)


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.astype("<i2").tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(path), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return data, rate, ch, width


def manifest(out_dir: Path) -> dict:
    entries = []
    for s in SOUNDS:
        path = out_dir / s.filename
        entries.append({
            "id": s.name,
            "file": s.filename,
            "ue_path": f"{UE_FOLDER}/{s.name}.{s.name}",
            "duration_s": s.duration,
            "loop": s.loop,
            "channels": 1,
            "suggested_volume": s.volume,
            "plays": s.plays,
            "seed": s.seed,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        })
    return {
        "ue_folder": UE_FOLDER,
        "generator": "Tools/Audio/make_terminal_sfx.py",
        "design": "Tools/GameFlow/RETRO_BOOT.md",
        "sample_rate": SR,
        "bit_depth": 16,
        "sounds": entries,
    }


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in SOUNDS:
        write_wav(out_dir / s.filename, render(s))
        print(f"wrote {s.filename}")
    (out_dir / "manifest.json").write_text(json.dumps(manifest(out_dir), indent=2) + "\n", encoding="utf-8")
    print("wrote manifest.json")


# --------------------------------------------------------------------------- check

def db(v: float) -> float:
    return 20 * np.log10(max(v, 1e-12))


def band_rms(x: np.ndarray, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    m = (f >= lo) & (f < hi)
    return float(np.sqrt(spec[m].sum() / max(len(x), 1)))


def check_file(s: Sound, path: Path) -> list[str]:
    errs = []
    if not path.exists():
        return [f"{s.filename}: missing"]
    pcm, rate, ch, width = read_wav(path)
    if (rate, ch, width) != (SR, 1, 2):
        errs.append(f"format {rate} Hz, {ch} ch, {8 * width} bit")
    x = pcm.astype(np.float64) / FULL_SCALE
    dur = len(x) / SR
    if abs(dur - s.duration) > DURATION_TOL_S:
        errs.append(f"duration {dur:.3f} s, want {s.duration}")
    peak = db(np.max(np.abs(x)))
    lo, hi = LOOP_PEAK_RANGE if s.loop else ONESHOT_PEAK_RANGE
    if not lo <= peak <= hi:
        errs.append(f"peak {peak:.2f} dBFS outside {lo}..{hi}")
    dc = abs(np.mean(x)) * 100
    if dc > MAX_DC_PERCENT:
        errs.append(f"DC {dc:.3f} %")
    if not s.loop and (abs(int(pcm[0])) > MAX_EDGE_LSB or abs(int(pcm[-1])) > MAX_EDGE_LSB):
        errs.append(f"edges {pcm[0]} / {pcm[-1]} LSB")
    if s.loop:
        k = nsamp(0.05)
        r0, r1 = np.sqrt(np.mean(x[:k] ** 2)), np.sqrt(np.mean(x[-k:] ** 2))
        if abs(db(r0) - db(r1)) > 3.0:
            errs.append(f"loop seam RMS {db(r0):.1f} vs {db(r1):.1f} dB")
        jump = abs(x[0] - x[-1])
        p999 = np.percentile(np.abs(np.diff(x)), 99.9)
        if jump > p999:
            errs.append(f"loop wrap step {jump:.5f} > p99.9 step {p999:.5f}")
    if s.name == "SFX_Term_OK_Blip":
        spec = np.abs(np.fft.rfft(x, 1 << 16))
        f = np.fft.rfftfreq(1 << 16, 1 / SR)
        fpk = f[np.argmax(spec)]
        if not 900 <= fpk <= 1200:
            errs.append(f"beep peak at {fpk:.0f} Hz, want 900..1200")
        on = np.nonzero(np.abs(x) > 0.05 * np.max(np.abs(x)))[0]
        if (on[-1] - on[0]) / SR >= 0.15:
            errs.append(f"beep lasts {(on[-1] - on[0]) / SR:.3f} s")
    if s.name == "SFX_Term_CRT_PowerOn":
        seg = x[nsamp(0.3): nsamp(0.9)]
        whine = band_rms(seg, 15600, 15870)
        side = band_rms(seg, 14000, 15200) * np.sqrt(270 / 1200)  # same bandwidth
        if db(whine) - db(side) < 20:
            errs.append(f"flyback peak only {db(whine) - db(side):.1f} dB over its neighbours")
        whole = np.sqrt(np.mean(x ** 2))
        hp = band(x, 15400, 16100, 4)
        if db(np.sqrt(np.mean(hp ** 2))) - db(whole) > -15:
            errs.append(f"flyback too loud: {db(np.sqrt(np.mean(hp ** 2))) - db(whole):.1f} dB vs file RMS")
        head = np.sqrt(np.mean(hp[: nsamp(1.0)] ** 2))
        tail = np.sqrt(np.mean(hp[-nsamp(0.3):] ** 2))
        if db(tail) - db(head) > -10:
            errs.append(f"flyback does not fade: tail {db(tail) - db(head):.1f} dB vs first second")
    if s.name.startswith("SFX_Term_Teletype_Burst"):
        if not 0.2 <= s.duration <= 0.6:
            errs.append(f"burst length {s.duration} outside 0.2..0.6 s")
        env = np.abs(x)
        frame = nsamp(0.004)
        e = env[: len(env) // frame * frame].reshape(-1, frame).max(axis=1)
        peaks = np.sum((e[1:-1] > e[:-2]) & (e[1:-1] >= e[2:]) & (e[1:-1] > 0.25 * e.max()))
        if peaks < 6:
            errs.append(f"only {peaks} strikes")
    fresh = render(s)
    if not np.array_equal(fresh, pcm):
        errs.append("differs from a fresh render (not deterministic)")
    return [f"{s.filename}: {e}" for e in errs]


def check(out_dir: Path) -> bool:
    ok = True
    for s in SOUNDS:
        errs = check_file(s, out_dir / s.filename)
        if errs:
            ok = False
            for e in errs:
                print("FAIL", e)
        else:
            pcm, *_ = read_wav(out_dir / s.filename)
            x = pcm / FULL_SCALE
            print(f"ok   {s.filename:34s} {len(x) / SR:6.3f} s  peak {db(np.max(np.abs(x))):6.2f} dBFS  "
                  f"rms {db(np.sqrt(np.mean(x ** 2))):6.1f} dBFS")
    mpath = out_dir / "manifest.json"
    if not mpath.exists():
        print("FAIL manifest.json missing")
        ok = False
    else:
        m = json.loads(mpath.read_text(encoding="utf-8"))
        if m.get("ue_folder") != UE_FOLDER or len(m.get("sounds", [])) != len(SOUNDS):
            print("FAIL manifest.json out of date")
            ok = False
        for e in m.get("sounds", []):
            p = out_dir / e["file"]
            if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
                print(f"FAIL manifest hash of {e['file']} is stale")
                ok = False
    print("check passed" if ok else "check FAILED")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only re-read and check the existing files")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    args = parser.parse_args(argv)
    if not args.check:
        generate(args.out)
    return 0 if check(args.out) else 1


if __name__ == "__main__":
    sys.exit(main())
