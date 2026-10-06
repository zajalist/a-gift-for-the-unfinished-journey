#!/usr/bin/env python3
"""Age the author's recorded takes: an old, failing radio baked into the WAV (the user, 2026-09-29:
"add extra effects on top of my voice to make it sound older and broken radio esque").

    python Tools/Audio/age_voice.py                 # every take in Saved/RadioRecordings/author_mp3 (by id)
    python Tools/Audio/age_voice.py SHOW_A1_01 ...  # only these ids
    python Tools/Audio/age_voice.py --restore       # put the clean takes back into selected/

Every run decodes the author's clean take (Saved/RadioRecordings/author_mp3/<id>.mp3, 48 kHz mono via ffmpeg),
so re-running never stacks the effect and a newer recording is picked up. The aged take overwrites
selected/<id>.wav, which the importers (Tools/Audio/import_game_audio.py) read; --restore writes the plain
decode instead. A doubled extension (X.mp3.mp3) is read as id X. The station's in-engine chain
(Tools/Audio/station_chain.py) still runs on top at playback and is not changed.

Chain (deterministic per id):
  1. tape wow (0.55 Hz) and flutter (6.5 Hz): a slowly varying read delay, about +-0.35 % pitch;
  2. old-set band: high-pass 320 Hz, low-pass 3.2 kHz, a resonant speaker bump at 1.4 kHz;
  3. valve/driver saturation (tanh) and a light 10-bit crush of the detail;
  4. a slow fade in and out of the signal (the carrier drifting, 0.12-0.3 Hz, down to about -5 dB);
  5. broken reception: a dropout every 3-7 s (40-180 ms down to 8-30 %), each with a crackle burst;
  6. a floor of band-limited hiss, sparse pops and a faint 50 Hz mains hum.
The result is loudness-normalised (-16 LUFS; room murmurs -20) and peak-limited to -1 dBFS.
"""
from __future__ import annotations

import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / "Saved" / "RadioRecordings"
SELECTED = REC / "selected"
AUTHOR = REC / "author_mp3"


def author_takes() -> dict[str, Path]:
    return {p.name.split(".")[0]: p for p in sorted(AUTHOR.glob("*.mp3"))}


def decode(mp3: Path) -> tuple[np.ndarray, int]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64), 48000


def sos_filter(x, sos):
    return signal.sosfilt(sos, x)


def age(x: np.ndarray, sr: int, seed: int, target_lufs: float = -16.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    t = np.arange(n) / sr
    ref_rms = np.sqrt(np.mean(x ** 2)) + 1e-9

    # 1. wow and flutter: read position wanders by a few ms
    ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)
    delay = 0.0026 * np.sin(2 * np.pi * 0.55 * t + ph1) + 0.00012 * np.sin(2 * np.pi * 6.5 * t + ph2)
    pos = np.clip(np.arange(n) - (delay + 0.003) * sr, 0, n - 1)
    y = np.interp(pos, np.arange(n), x)

    # 2. old-set band and speaker bump
    y = sos_filter(y, signal.butter(3, 320, "highpass", fs=sr, output="sos"))
    y = sos_filter(y, signal.butter(5, 3200, "lowpass", fs=sr, output="sos"))
    b, a = signal.iirpeak(1400, 1.6, fs=sr)
    y = y + 0.6 * signal.lfilter(b, a, y)

    # 3. saturation and a light crush
    y = y / (np.max(np.abs(y)) + 1e-9)
    y = np.tanh(2.2 * y) / np.tanh(2.2)
    y = np.round(y * 512) / 512

    # 4. slow carrier drift
    f1, f2 = rng.uniform(0.12, 0.3, 2)
    drift = 1.0 - 0.22 * (0.5 + 0.5 * np.sin(2 * np.pi * f1 * t + ph1)) * (0.5 + 0.5 * np.sin(2 * np.pi * f2 * t))
    y = y * drift

    # 5. dropouts with crackle bursts
    gain = np.ones(n)
    burst = np.zeros(n)
    at = rng.uniform(1.2, 3.0)
    while at < t[-1] - 0.3:
        s = int(at * sr)
        ln = int(rng.uniform(0.04, 0.18) * sr)
        depth = rng.uniform(0.08, 0.3)
        ramp = min(int(0.006 * sr), ln // 3)
        env = np.full(ln, depth)
        env[:ramp] = np.linspace(1, depth, ramp)
        env[-ramp:] = np.linspace(depth, 1, ramp)
        gain[s:s + ln] = env[:len(gain[s:s + ln])]
        bl = min(ln + int(0.05 * sr), n - s)
        crack = rng.normal(0, 1, bl) * (rng.random(bl) < 0.08)
        burst[s:s + bl] += crack * rng.uniform(0.05, 0.12)
        at += rng.uniform(3.0, 7.0)
    y = y * gain

    # 6. hiss, pops and hum
    hiss = sos_filter(rng.normal(0, 1, n), signal.butter(2, [900, 6000], "bandpass", fs=sr, output="sos"))
    hiss = hiss / (np.sqrt(np.mean(hiss ** 2)) + 1e-9) * 0.018 * (1.0 + 0.4 * (1.0 - drift))
    pops = np.zeros(n)
    k = rng.random(n) < (1.6 / sr)
    pops[k] = rng.choice([-1, 1], k.sum()) * rng.uniform(0.1, 0.35, k.sum())
    pops = sos_filter(pops, signal.butter(2, 2500, "lowpass", fs=sr, output="sos"))
    hum = 0.004 * (np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 150 * t))
    burst = sos_filter(burst, signal.butter(2, [600, 5000], "bandpass", fs=sr, output="sos"))
    y = y + hiss + pops + hum + burst

    # Loudness, not the clean take's RMS (the author, 2026-09-29: "you can't hear my voice loudly enough"): the takes
    # sat at -21..-27 LUFS against the -18 LUFS placeholders the mix was balanced on. Normalise to TARGET_LUFS, then a
    # smoothed peak limiter at -1 dBFS (so a loud peak no longer pulls the whole take down).
    y = y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * ref_rms
    return level(y, sr, target_lufs)


TARGET_LUFS = -16.0       # the host and the archive: 2 dB over the placeholders, above the music
ROOM_TARGET_LUFS = -20.0  # FILL_ROOM murmurs stay under the talk


def level(y: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    import pyloudnorm
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    loud = pyloudnorm.Meter(sr).integrated_loudness(y.astype(np.float64))
    if np.isfinite(loud):
        y = y * 10 ** ((target_lufs - loud) / 20)
    lim = 10 ** (-1 / 20)
    g = np.minimum(1.0, lim / (np.abs(y) + 1e-9))
    w = max(1, int(sr * 0.005))
    g = uniform_filter1d(minimum_filter1d(g, size=2 * w + 1), size=w)
    return np.clip(y * g, -lim, lim).astype(np.float32)


# The pillar readings (INSCR_*) are the carrier's scanner, not the radio (the author, 2026-09-29: "more robotic for
# the inscriptions and different, remove noise"): denoised, pitched down about 3 semitones, a phase-flattened copy
# over the dry voice, a small inharmonic frequency shift and a metallic comb; no hiss, crackle, dropouts or fades.
SCANNER_CHAIN = (
    "[0:a]aformat=sample_rates=48000:channel_layouts=mono,afftdn=nf=-30,highpass=f=90,rubberband=pitch=0.84,"
    "asplit=2[a][b];"
    "[a]afftfilt=real='hypot(re,im)*cos(0)':imag='hypot(re,im)*sin(0)':win_size=1024:overlap=0.75,volume=0.6[r];"
    "[b]volume=0.6[d];"
    "[r][d]amix=inputs=2:normalize=0,afreqshift=shift=-18,aecho=0.8:0.45:3|7:0.25|0.15,lowpass=f=8000,"
    "apad=pad_dur=0.3,loudnorm=I=-18:TP=-1.5:LRA=11"
)


def scanner(mp3: Path, out: Path) -> float:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-filter_complex", SCANNER_CHAIN,
                    "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out)], check=True)
    return sf.info(str(out)).duration


def main(argv: list[str]) -> int:
    restore = "--restore" in argv
    ids = [a for a in argv if not a.startswith("--")]
    takes = author_takes()
    bad = 0
    for gid in ids or list(takes):
        if gid not in takes:
            print(f"{gid}: MISSING author take")
            bad += 1
            continue
        if gid.startswith("INSCR_") and not restore:
            print(f"{gid}: scanner {scanner(takes[gid], SELECTED / f'{gid}.wav'):.2f} s")
            continue
        x, sr = decode(takes[gid])
        target = ROOM_TARGET_LUFS if gid.startswith("FILL_ROOM") else TARGET_LUFS
        y = x.astype(np.float32) if restore else age(x, sr, zlib.crc32(gid.encode()), target)
        sf.write(SELECTED / f"{gid}.wav", y, sr, subtype="PCM_16")
        print(f"{gid}: {'restored' if restore else 'aged'} {len(y) / sr:.2f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
