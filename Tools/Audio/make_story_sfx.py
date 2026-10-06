#!/usr/bin/env python3
"""Build the three story-runner one-shots that play logged "not imported yet": the crest gust, the
archive tape click and the carrier's boot servo.

    python Tools/Audio/make_story_sfx.py           # build all three, write manifest + credits, check
    python Tools/Audio/make_story_sfx.py --check   # re-measure the existing files only (no network)

Who plays them (docs/story/story-events.json, all `PlaySfx`, 2D through UGameplayStatics::PlaySound2D):
- SFX_CrestGust:        CIN_06_ROAD_AHEAD at 0.3 s and CIN_06F_CREST_FORT at 4.3 s (B06, the ridge crest).
- SFX_TapeClick:        B02_ARCHIVE_OPENS ("tape click; archive hiss") and CIN_PO01_LOW_VOICE at 0.4 s.
- SFX_Carrier_ServoUp:  CIN_01_DIRECTIVE at 1.0 s, the "eyes open" tilt of the boot POV.

Output: Saved/GameAudio/Story/<Asset>.wav (48 kHz, 16-bit PCM), manifest.json (the import list) and
_spectrograms.png. The editor lane imports them with
    python Tools/Audio/import_game_audio.py story     # -> /Game/SaskartaGaea/Audio/Story/<Asset>
The runner finds a sound by asset name anywhere under /Game/SaskartaGaea/Audio, so no data change is needed.

Sources:
- SFX_CrestGust: Freesound 474894 "Braddons Lookout Wind Gusts #1" (guyburns, CC0), stereo, one gust at
  9.2-17.2 s (before the distant crows at 20 s), high-passed at 110 Hz against blimp rumble, with a 7 dB
  raised-cosine swell on top of its own rise so it reads as one gust.
- SFX_TapeClick: Freesound 635655 "reel to reel tape machine play and stop buttons mechanism" (kyles, CC0),
  the play press and the transport starting (0.0-1.95 s), plus a synthesized tape-hiss swell under the
  run-up (the "archive hiss"), its RMS 36 dB under the key's peak.
- SFX_Carrier_ServoUp: procedural, built from make_carrier_vehicle_sfx.py's helpers (relay click, geared
  DC servo tone, stepper ticks, controller bed), so it sits with SFX_Carrier_Steer_Servo_*.

No music: the only pitched parts are the servo's motor and gear whine, which are physically caused.
Levels: the gust peaks at -3 dBFS but is held to -18 LUFS at most (a 2D stinger over the ambience); the tape
click peaks at -6 dBFS like the radio knob set; the servo peaks at -3 dBFS like the carrier servos.
The Freesound key stays in Saved/freesound.key (read by freesound_fetch.py, never printed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402
import make_carrier_vehicle_sfx as mv  # noqa: E402

SR = fs.SR
ROOT = fs.ROOT
OUT = ROOT / "Saved" / "GameAudio" / "Story"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Story"
GUST_MAX_LUFS = -18.0
HISS_DB = -36.0  # tape-hiss RMS under the tape key's peak
GUST_SWELL_DB = 7.0  # extra swell depth on the crest gust

# asset -> (channels, peak dBFS target, duration range s, where it plays, what it is)
SPEC = {
    "SFX_CrestGust": (2, -3.0, (6.0, 9.0), "CIN_06_ROAD_AHEAD 0.3 s; CIN_06F_CREST_FORT 4.3 s",
                      "One mountain gust at the ridge crest: rises over ~1.5 s, holds, falls away (the air opens)."),
    "SFX_TapeClick": (1, -6.0, (1.4, 2.4), "B02_ARCHIVE_OPENS; CIN_PO01_LOW_VOICE 0.4 s",
                      "A reel-to-reel play key goes down, the transport engages and the tape hiss swells in."),
    "SFX_Carrier_ServoUp": (1, -3.0, (2.0, 2.8), "CIN_01_DIRECTIVE 1.0 s",
                            "The carrier's eye/neck servo powers up: relay, a sticky start, the tilt run, "
                            "a backlash stop, then the focus stepper."),
}
SOURCES = {
    "SFX_CrestGust": dict(id=474894, region=(9.2, 17.2), hp=110.0),
    "SFX_TapeClick": dict(id=635655, region=(0.0, 1.95), hp=50.0),
}


# ------------------------------------------------------------------------------ helpers

def highpass(x: np.ndarray, hz: float, order: int = 3) -> np.ndarray:
    sos = butter(order, hz, btype="highpass", fs=SR, output="sos")
    return sosfiltfilt(sos, x, axis=0)


def raised(n: int) -> np.ndarray:
    """0 -> 1 raised-cosine ramp of n samples."""
    return 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / max(n, 1))


def shape(x: np.ndarray, fade_in_s: float, fade_out_s: float) -> np.ndarray:
    x = x.copy()
    a, b = int(fade_in_s * SR), int(fade_out_s * SR)
    env = np.ones(len(x))
    env[:a] = raised(a)
    env[len(x) - b:] = raised(b)[::-1]
    env[0] = env[-1] = 0.0
    return x * (env[:, None] if x.ndim == 2 else env)


def lufs(x: np.ndarray) -> float:
    return mv.lufs(x if x.ndim == 1 else x)


def source(asset: str) -> tuple[dict, np.ndarray]:
    """The source region (float64, mono or stereo as SPEC asks), licence-checked."""
    s = SOURCES[asset]
    meta = mv.hit_meta(s["id"])
    lic = meta["license"]
    if "publicdomain/zero" not in lic and "/by/" not in lic:
        raise SystemExit(f"{asset}: {s['id']} licence {lic} is neither CC0 nor CC-BY")
    channels = SPEC[asset][0]
    audio = fs.fetch(meta, channels).astype(np.float64)
    a, b = s["region"]
    seg = audio[int(a * SR): int(b * SR)]
    return meta, seg[:, 0] if channels == 1 else seg


# ------------------------------------------------------------------------------ the three sounds

def crest_gust() -> tuple[np.ndarray, dict]:
    meta, x = source("SFX_CrestGust")
    x = highpass(x, SOURCES["SFX_CrestGust"]["hp"])
    # Accent the single gesture: -GUST_SWELL_DB at the ends, 0 dB at 3.7 s (raised cosine), on top of
    # the recording's own ~8 dB rise, so it reads as one gust rather than a stretch of wind.
    t = mv.tvec(len(x) / SR)
    swell = np.sin(np.pi * np.clip(t / 7.4, 0.0, 1.0)) ** 2
    x = x * mv.db(-GUST_SWELL_DB * (1.0 - swell))[:, None]
    x = shape(x, 0.5, 2.4)
    x = mv.peak_norm(x, SPEC["SFX_CrestGust"][1])
    over = lufs(x) - GUST_MAX_LUFS
    if over > 0:
        x = x * mv.db(-over)
    return x, meta


def tape_click(rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    meta, x = source("SFX_TapeClick")
    x = highpass(x, SOURCES["SFX_TapeClick"]["hp"])
    # The key lands at ~0.15 s; start 10 ms before it.
    env = np.abs(x)
    onset = int(np.argmax(env > env.max() * mv.db(-30)))
    x = x[max(0, onset - int(0.01 * SR)):]
    t = mv.tvec(len(x) / SR)
    # Tape hiss: steady broadband with a faint flutter, swelling in as the transport engages and dying
    # away with the run-up. Its RMS sits HISS_DB under the key's sample peak: a bed, not a second event.
    hiss = mv.noise(rng, len(x), 1800.0, 11000.0, circular=False)
    hiss *= 1.0 + 0.04 * np.sin(2 * np.pi * 5.7 * t)
    hiss_env = mv.ramp(t, 0.06, 0.32) * (1.0 - mv.ramp(t, 1.05, t[-1]))
    x = x / np.max(np.abs(x)) + mv.db(HISS_DB) * hiss * hiss_env
    x = shape(x, 0.005, 0.12)
    return mv.peak_norm(x, SPEC["SFX_TapeClick"][1]), meta


def servo_up(rng: np.random.Generator) -> np.ndarray:
    """Relay; the tilt servo sticks twice, breaks free and runs up; slows onto its stop with a backlash
    double tick and a small knock; then the eye's focus stepper."""
    dur = 2.35
    t = mv.tvec(dur)
    n = len(t)
    bursts = ((0.10, 0.165), (0.22, 0.295))
    run0, run1 = 0.34, 1.84
    f = 58.0 + 127.0 * mv.smoothstep(run0, 0.82, t) - 38.0 * mv.smoothstep(1.52, run1, t)
    f = np.where(t < run0, 52.0 + 10.0 * mv.smoothstep(0.1, 0.3, t), f)
    f = f * (1.0 + 0.03 * np.sin(2 * np.pi * 3.1 * t) + 0.01 * np.sin(2 * np.pi * 23.0 * t))  # worn gear, per-rev
    gate = sum(mv.ramp(t, a, a + 0.008) * (1.0 - mv.ramp(t, b - 0.012, b)) * 0.7 for a, b in bursts)
    gate = gate + mv.ramp(t, run0, run0 + 0.02) * (1.0 - mv.ramp(t, run1 - 0.03, run1)) * (0.8 + 0.2 * mv.ramp(t, run0, 0.9)) \
        * (1.0 + 0.12 * np.sin(2 * np.pi * 3.1 * t))  # the same worn gear loads the motor once per rev
    ph = mv.free_phase(f)
    tone = sum((1.0 / k) * np.sin(k * ph) * (1.0 if k % 2 else 0.6) for k in range(1, 18) if k * 185.0 < 18000)
    whine = np.sin(10 * ph) + 0.3 * np.sin(20 * ph)
    brush = mv.noise(rng, n, 2000, 9000, circular=False) * (0.5 + 0.5 * np.sin(2 * ph)) ** 6
    stick = sum(mv.ramp(t, a, a + 0.005) * (1.0 - mv.ramp(t, b - 0.01, b)) for a, b in bursts)
    grind = mv.noise(rng, n, 300, 2500, circular=False) * (stick + 0.25 * mv.ramp(t, run0, run0 + 0.05) * (1.0 - mv.ramp(t, 0.55, 0.7)))
    x = (mv.unit(np.tanh(1.3 * mv.unit(tone))) + mv.db(-9) * mv.unit(whine) + mv.db(-18) * mv.unit(brush)) * gate
    x += mv.db(-14) * grind
    mv.place(x, mv.unit(mv.relay_click(rng, 1.0)), 0.02, mv.db(-6))
    for i, tk in enumerate((run1 - 0.004, run1 + 0.021)):
        k = int(0.02 * SR)
        tick = mv.noise(rng, k, 1200, 7000, circular=False) * np.exp(-np.arange(k) / (0.002 * SR))
        mv.place(x, 3.0 * tick, tk, (1.0, 0.65)[i])
    mv.place(x, mv.unit(mv._thump(rng, 95.0, 0.2)), run1 + 0.002, mv.db(-8))
    mv.place(x, mv.unit(mv.s_mast_tick(rng, 1)), 1.98, mv.db(-9))
    bed = mv.controller_bed(rng, n, circular=False)
    x += mv.db(-30) * mv.unit(bed) * mv.ramp(t, 0.05, 0.4) * (1.0 - mv.ramp(t, 1.95, 2.3))
    x = mv.edge_fade(x, 0.004, 0.03)
    return mv.peak_norm(x, SPEC["SFX_Carrier_ServoUp"][1])


# ------------------------------------------------------------------------------ checks and output

def measure(path: Path) -> dict:
    info = soundfile.info(str(path))
    x, sr = soundfile.read(str(path), dtype="float64")
    return {
        "sr": sr, "subtype": info.subtype, "channels": info.channels, "duration_s": round(len(x) / sr, 3),
        "peak_dbfs": round(20 * np.log10(np.max(np.abs(x)) + 1e-12), 2),
        "lufs": round(lufs(x), 1),
        "edge": float(max(np.max(np.abs(x[:1])), np.max(np.abs(x[-1:])))),
        "lr_corr": round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 3) if x.ndim == 2 else None,
    }


def check() -> list[str]:
    problems = []
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8")) if (OUT / "manifest.json").exists() else []
    listed = {e["asset"] for e in manifest}
    for asset, (ch, peak, (lo, hi), _, _) in SPEC.items():
        p = OUT / f"{asset}.wav"
        if not p.exists():
            problems.append(f"{asset}: missing {p}")
            continue
        m = measure(p)
        print(f"{asset:<22} {m['channels']}ch {m['duration_s']:5.2f}s peak {m['peak_dbfs']:6.2f} dBFS "
              f"{m['lufs']:6.1f} LUFS" + (f" L/R corr {m['lr_corr']}" if m["lr_corr"] is not None else ""))
        if m["sr"] != SR or m["subtype"] != "PCM_16":
            problems.append(f"{asset}: {m['sr']} Hz {m['subtype']}, want 48000 PCM_16")
        if m["channels"] != ch:
            problems.append(f"{asset}: {m['channels']} channels, want {ch}")
        if not lo <= m["duration_s"] <= hi:
            problems.append(f"{asset}: {m['duration_s']} s outside {lo}-{hi} s")
        if m["peak_dbfs"] > peak + 0.05:
            problems.append(f"{asset}: peak {m['peak_dbfs']} dBFS over {peak}")
        if asset == "SFX_CrestGust" and m["lufs"] > GUST_MAX_LUFS + 0.3:
            problems.append(f"{asset}: {m['lufs']} LUFS over {GUST_MAX_LUFS}")
        if m["edge"] > 1e-3:
            problems.append(f"{asset}: starts or ends off zero ({m['edge']:.4f}); a click")
        if asset not in listed:
            problems.append(f"{asset}: not in manifest.json")
    return problems


def spectrograms(paths: list[Path]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(paths), 1, figsize=(10, 2.6 * len(paths)))
    for ax, p in zip(np.atleast_1d(axes), paths):
        x, sr = soundfile.read(str(p), dtype="float64")
        m = x.mean(axis=1) if x.ndim == 2 else x
        ax.specgram(m, NFFT=2048, Fs=sr, noverlap=1536, cmap="magma", vmin=-130)
        ax.set_ylim(0, 16000)
        ax.set_title(p.stem, fontsize=9)
        ax.set_ylabel("Hz")
    fig.tight_layout()
    fig.savefig(OUT / "_spectrograms.png", dpi=80)
    plt.close(fig)


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260928)
    gust, gust_meta = crest_gust()
    click, click_meta = tape_click(rng)
    servo = servo_up(np.random.default_rng(20260929))
    out = {"SFX_CrestGust": gust, "SFX_TapeClick": click, "SFX_Carrier_ServoUp": servo}
    for asset, x in out.items():
        fs.write_wav(OUT / f"{asset}.wav", x)
    g, c = SOURCES["SFX_CrestGust"], SOURCES["SFX_TapeClick"]
    fs.credit("SFX_CrestGust", gust_meta,
              notes=f"story one-shot: {g['region'][0]}-{g['region'][1]} s, high-pass {g['hp']:.0f} Hz, "
                    f"+{GUST_SWELL_DB:.0f} dB raised-cosine swell, 0.5/2.4 s fades, held to {GUST_MAX_LUFS:.0f} LUFS")
    fs.credit("SFX_TapeClick", click_meta,
              notes=f"story one-shot: the play press, {c['region'][0]}-{c['region'][1]} s, high-pass {c['hp']:.0f} Hz, "
                    f"plus a synthesized tape-hiss swell {-HISS_DB:.0f} dB under the key")
    sources = {"SFX_CrestGust": gust_meta, "SFX_TapeClick": click_meta}
    manifest = []
    for asset in sorted(out):
        ch, peak, _, cue, use = SPEC[asset]
        m = measure(OUT / f"{asset}.wav")
        meta = sources.get(asset)
        manifest.append({
            "asset": asset, "file": f"{asset}.wav", "ue_folder": UE_FOLDER, "loop": False, "channels": ch,
            "duration_s": m["duration_s"], "peak_dbfs": m["peak_dbfs"], "lufs": m["lufs"], "plays_in": cue, "use": use,
            "source": ({"freesound_id": meta["id"], "author": meta["username"], "url": meta["url"],
                        "licence": "CC0" if "publicdomain/zero" in meta["license"] else meta["license"]}
                       if meta else "procedural (make_story_sfx.py servo_up, make_carrier_vehicle_sfx.py helpers)"),
        })
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    spectrograms([OUT / f"{a}.wav" for a in sorted(out)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only measure the existing files")
    a = ap.parse_args(argv)
    if not a.check:
        build()
    problems = check()
    for p in problems:
        print("PROBLEM", p)
    print(f"{len(SPEC)} sounds in {OUT}: " + ("ok" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
