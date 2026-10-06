"""Prepare the Low Voice songs for import (LANE5): the light archive filter + loudness to the station target.

    python Tools/Audio/prep_station_songs.py malak weli     # -> Saved/Audio/StationSongs/<id>.wav

station.json "songs": archive_filter = "light: band-pass 120 Hz-7 kHz, tape hiss at -48 dBFS, wow 0.1 %, no
ring-mod or crush"; loudness_target_lufs -18, true peak <= -1 dBTP. Stereo is kept; 48 kHz 16-bit out.
The runtime radio chain (band-limit, saturation, static bed, glitches) is applied on top, in the game.
"""
import sys
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "SourceArt/Audio/StationSongs"
OUT = ROOT / "Saved/Audio/StationSongs"
TARGET, PEAK_DB = -18.0, -1.0


def archive(x, sr, seed):
    rng = np.random.default_rng(seed)
    sos = signal.butter(2, [120, 7000], btype="bandpass", fs=sr, output="sos")
    y = signal.sosfiltfilt(sos, x, axis=0)
    # wow: 0.1 % pitch wobble at ~0.6 Hz (a slow varying resample)
    n = len(y)
    t = np.arange(n) / sr
    dev = 0.001 * np.sin(2 * np.pi * 0.6 * t + rng.uniform(0, 6.28))
    pos = np.clip(np.arange(n) + np.cumsum(dev), 0, n - 1)
    y = np.stack([np.interp(pos, np.arange(n), y[:, c]) for c in range(y.shape[1])], axis=1)
    return y


def main(ids):
    OUT.mkdir(parents=True, exist_ok=True)
    for i, sid in enumerate(ids):
        x, sr = sf.read(SRC / f"{sid}.wav", always_2d=True)
        y = archive(x, sr, i)
        meter = pyln.Meter(sr)
        y = pyln.normalize.loudness(y, meter.integrated_loudness(y), TARGET)
        hiss = np.random.default_rng(100 + i).normal(0, 1, y.shape)
        hiss = signal.sosfilt(signal.butter(2, [1500, 9000], btype="bandpass", fs=sr, output="sos"), hiss, axis=0)
        y = y + hiss / np.sqrt(np.mean(hiss ** 2)) * 10 ** (-48 / 20)
        # true peak (4x oversampled) to -1 dBTP with a soft limiter-style gain
        tp = np.max(np.abs(signal.resample_poly(y, 4, 1, axis=0)))
        lim = 10 ** (PEAK_DB / 20)
        if tp > lim:
            y = y * (lim / tp)
        lufs = meter.integrated_loudness(y)
        sf.write(OUT / f"{sid}.wav", y.astype(np.float32), sr, subtype="PCM_16")
        print(sid, f"{len(y) / sr:.1f} s", f"{lufs:.1f} LUFS", f"peak {20 * np.log10(np.max(np.abs(y))):.1f} dBFS")


if __name__ == "__main__":
    main(sys.argv[1:] or ["malak", "weli"])
