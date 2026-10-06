"""HUT_NIGHT_A1: the hut speaker's night from the top (storyline-first-light.md section 5, B22H_HUT_NIGHT).

    python Tools/Audio/mix_hut_night.py [--out Saved/Story/Audio/HUT_NIGHT_A1.wav] [--seed 1840]

Act I's backbone in station.json order (from SHOW_A1_01), the same takes the station plays
(Saved/RadioRecordings/selected/<id>.wav), back to back with 4-12 s of low static between them, through a small
speaker (a 300-3400 Hz band, a little saturation) at -14 dB. Mono 48 kHz 16-bit. Missing takes are skipped and named.
Import it as /Game/SaskartaGaea/Audio/Story/HUT_NIGHT_A1 with a spatial attenuation (inner 3 m, falloff 25 m);
CIN_24 cuts it mid-word with StopSfx at the hand. Nothing here is music.
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SEL = REPO / "Saved" / "RadioRecordings" / "selected"
SR = 48000
GAIN_DB = -14.0


def act1_ids() -> list[str]:
    st = json.loads((REPO / "docs" / "story" / "station.json").read_text(encoding="utf-8"))
    return list(st["show"]["acts"][0]["backbone"])


def read_mono(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    dt = {2: np.int16, 4: np.int32}.get(sw)
    if dt is None:          # 24-bit
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        x = np.where(x >= 1 << 23, x - (1 << 24), x).astype(np.float64) / (1 << 23)
    else:
        x = np.frombuffer(raw, dt).astype(np.float64) / float(np.iinfo(dt).max)
    x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        t = np.arange(int(len(x) * SR / sr)) * (sr / SR)
        x = np.interp(t, np.arange(len(x)), x)
    return x


def speaker(x: np.ndarray) -> np.ndarray:
    """A small speaker: 300-3400 Hz by FFT mask, soft saturation."""
    f = np.fft.rfft(x)
    hz = np.fft.rfftfreq(len(x), 1.0 / SR)
    f[(hz < 300.0) | (hz > 3400.0)] *= 0.05
    y = np.fft.irfft(f, len(x))
    return np.tanh(1.6 * y) / np.tanh(1.6)


def static(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.normal(0.0, 0.02, n) * (0.7 + 0.3 * np.sin(np.linspace(0, 9.0, n)) ** 2)


def mix(seed: int = 1840) -> tuple[np.ndarray, list[str], list[str]]:
    rng = np.random.default_rng(seed)
    parts, used, missing = [], [], []
    for lid in act1_ids():
        p = SEL / f"{lid}.wav"
        if not p.exists():
            missing.append(lid)
            continue
        if parts:
            parts.append(static(int(rng.uniform(4.0, 12.0) * SR), rng))
        parts.append(read_mono(p))
        used.append(lid)
    if not parts:
        return np.zeros(SR), used, missing
    y = speaker(np.concatenate(parts))
    return y * 10 ** (GAIN_DB / 20.0), used, missing


def main(argv: list[str]) -> int:
    out = REPO / "Saved" / "Story" / "Audio" / "HUT_NIGHT_A1.wav"
    seed = 1840
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    y, used, missing = mix(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"{out}: {len(y) / SR:.1f} s, {len(used)} takes" + (f"; missing {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
