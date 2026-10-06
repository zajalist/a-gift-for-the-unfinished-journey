"""The carrier's scan pulse sound (LANE5, CIN_01 scan wave): a sonar-like ping with a falling sweep and a tail.

    python Tools/Audio/make_scan_ping.py      # -> Saved/Audio/Scan/SFX_Carrier_ScanPing.wav, SFX_Carrier_ScanPing_Long.wav

Ping: 1.45 kHz sine with a slight downward glide, 4 ms attack, 1.1 s exponential decay, a soft 2nd partial;
sweep: band-passed noise gliding 6 -> 1.2 kHz over 0.7 s (the wave leaving); tail: a 1.6 s synthetic
early-reflection/diffuse tail (the valley answering). The long variant (the long-range pulse) is lower, longer.
Peak -3 dBFS, 48 kHz stereo 16-bit.
"""
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

SR = 48000
OUT = Path(__file__).resolve().parents[2] / "Saved/Audio/Scan"


def ping(f0=1450.0, decay=1.1, sweep=(6000, 1200), dur=2.6, seed=3):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 * (1.0 - 0.04 * (1 - np.exp(-t / 0.3)))
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = np.minimum(t / 0.004, 1.0) * np.exp(-t / (decay / 4.6))
    tone = (np.sin(ph) + 0.25 * np.sin(2.01 * ph)) * env
    noise = rng.normal(0, 1, n)
    out = np.zeros(n)
    blk = 1024
    for i in range(0, n, blk):  # time-varying band-pass (the sweep)
        tt = i / SR
        fc = sweep[0] * (sweep[1] / sweep[0]) ** min(tt / 0.7, 1.0)
        sos = signal.butter(2, [fc * 0.7, min(fc * 1.3, SR / 2 - 100)], btype="bandpass", fs=SR, output="sos")
        out[i:i + blk] = signal.sosfilt(sos, noise[i:i + blk])
    sw = out * np.exp(-t / 0.25) * np.minimum(t / 0.01, 1.0) * 0.35
    dry = tone + sw
    ir_t = np.arange(int(1.6 * SR)) / SR
    irs = []
    for s in (11, 12):
        ir = np.random.default_rng(s).normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.35)
        ir[:int(0.03 * SR)] = 0
        irs.append(signal.sosfilt(signal.butter(2, 4000, fs=SR, output="sos"), ir))
    wet = [signal.fftconvolve(dry, ir)[:n] for ir in irs]
    y = np.stack([dry + 0.08 * wet[0], dry + 0.08 * wet[1]], axis=1)
    return y / np.max(np.abs(y)) * 10 ** (-3 / 20)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    sf.write(OUT / "SFX_Carrier_ScanPing.wav", ping().astype(np.float32), SR, subtype="PCM_16")
    sf.write(OUT / "SFX_Carrier_ScanPing_Long.wav", ping(f0=980.0, decay=2.2, sweep=(4500, 500), dur=3.6, seed=5).astype(np.float32), SR, subtype="PCM_16")
    print("wrote", OUT)
