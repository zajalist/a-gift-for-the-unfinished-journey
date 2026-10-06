"""REJECTED (v1, kept for reference; output now goes to Saved/GameAudio/Intro/_rejected/). See make_intro_fire_v2.py.

The fire card's sound: SFX_Intro_FireBurn, a 26 s layered cue built from CC0 Freesound recordings.

The start sequence's fire card (WBP_Saskarta_Intro) runs 12 s with the calligraphy lit (ignite
0-4 s, subtitle 2.5 s, hold) and then a 12 s burn-away (PC_Saskarta.RevealBurnTime). This cue
follows that timeline from the card's first frame, plus a 2 s tail of silence-bound embers:

    0.0 -  4.0 s  ignition: a small low breath, the paper bed fades in
    4.0 - 12.0 s  hold: close, soft paper/parchment burning bed, sparse wood/ember pops
   12.0 - 24.0 s  burn-away: the bed grows a little, pops get denser, a low warm fire breath
                  swells to about 18.5 s and dies with the burn front; a faint ember hiss
                  rises from 16 s and fades with the last glow
   24.0 - 26.0 s  tail: the last hiss and a final tick fade to digital silence

No music, no tonal drones, no synthesis: every layer is a filtered, enveloped recording.

Writes to Saved/GameAudio/Intro/_rejected/ (48 kHz stereo 16-bit):
    SFX_Intro_FireBurn.wav          the mix: -20 LUFS integrated, true peak <= -3 dBFS
    SFX_Intro_FireBurn_Bed.wav      stems, at their level in the mix (the four stems sum to the mix)
    SFX_Intro_FireBurn_Pops.wav
    SFX_Intro_FireBurn_Whoosh.wav
    SFX_Intro_FireBurn_Hiss.wav
    manifest.json                   timeline, pop times/levels/pans, loudness, sources

    python Tools/Audio/make_intro_fire.py            # fetch (cached), build, write, credit, measure
    python Tools/Audio/make_intro_fire.py --measure  # only measure the files already written

Swapping a bad source: change the id in SOURCES (all CC0) and rerun; the seed keeps pops stable.
"""
import json
import pathlib
import subprocess
import sys

import numpy as np
import pyloudnorm
import soundfile
from scipy.signal import butter, find_peaks, resample_poly, sosfiltfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

SR = fs.SR
OUT = fs.ROOT / "Saved" / "GameAudio" / "Intro" / "_rejected"   # v1 was rejected by the user; see make_intro_fire_v2.py
NAME = "SFX_Intro_FireBurn"
STEMS = ("Bed", "Pops", "Whoosh", "Hiss")

HOLD_S = 12.0      # calligraphy lit (ignite + hold); Reveal is called at about this time
BURN_S = 12.0      # PC_Saskarta.RevealBurnTime
TAIL_S = 2.0
DUR_S = HOLD_S + BURN_S + TAIL_S
N = int(DUR_S * SR)
T = np.arange(N) / SR

TARGET_LUFS = -20.0
PEAK_DB = -3.0     # true-peak ceiling (4x oversampled)
SEED = 20260927

# role -> Freesound id (all CC0), with next-best alternates for the credits file.
SOURCES = {
    "bed": dict(id=528662, alt=[461075, 446801]),          # Soonus, "Paper Burn.wav" (64.8 s)
    "bed2": dict(id=461075, alt=[446801]),                  # 15GKovacovaJul, "1.10_burning-paper.wav"
    "pops": dict(id=707262, alt=[382616, 496130]),         # Sadiquecat, "Fireplace wood crackling" (96 kHz)
    "whoosh": dict(id=242721, alt=[363091]),                # sergeeo, "burning air"
    "roar": dict(id=496130, alt=[382616, 610766]),         # petebuchwald, "Fireplace for Six Minutes (Stereo)"
    "hiss": dict(id=563764, alt=[86342, 870180]),          # florianreichel, "bonfire flames sizzling"
}


# ---------------------------------------------------------------- helpers
def filt(x, kind, freq, order=4):
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def seg(x, start_s, dur_s):
    a = int(start_s * SR)
    out = x[a:a + int(dur_s * SR)]
    assert len(out) == int(dur_s * SR), (start_s, dur_s, len(x) / SR)
    return out


def smooth_step(t, t0, t1):
    """0 before t0, 1 after t1, raised-cosine in between (works for t1 < t0 as a fall)."""
    u = np.clip((t - t0) / (t1 - t0), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def db(v):
    return 10 ** (v / 20)


def place(dst, clip, at_s, gain=1.0, pan=0.0):
    """Add a mono or stereo clip at at_s with constant-power pan (-1 left .. +1 right)."""
    a = int(at_s * SR)
    if a >= len(dst):
        return
    clip = clip[: len(dst) - a]
    if clip.ndim == 1:
        th = (pan + 1) * np.pi / 4
        clip = np.stack([clip * np.cos(th), clip * np.sin(th)], axis=1) * np.sqrt(2)
    dst[a:a + len(clip)] += clip * gain


def slow_wobble(rng, rate_hz, depth_db):
    """Smoothed random gain curve (+-depth_db), for the breathing of a fire."""
    k = int(DUR_S * rate_hz) + 3
    pts = rng.uniform(-1, 1, k)
    curve = np.interp(T * rate_hz, np.arange(k), pts)
    curve = filt(curve[:, None], "lowpass", rate_hz * 1.5, order=2)[:, 0]
    return db(depth_db * curve / (np.max(np.abs(curve)) + 1e-9)).astype(np.float32)


def tame(x, over_db, window_s=0.05, release_s=0.03):
    """Soften transients: pull any peak more than over_db above the local RMS back towards it.
    Keeps the crackle texture, removes the spiky, harsh clicks a close mic gives paper and sizzle."""
    p = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    w = int(window_s * SR)
    c = np.concatenate([[0.0], np.cumsum(p.astype(np.float64) ** 2)])
    lo = np.clip(np.arange(len(p)) - w // 2, 0, len(p))
    hi = np.clip(np.arange(len(p)) + w // 2, 0, len(p))
    rms = np.sqrt((c[hi] - c[lo]) / np.maximum(hi - lo, 1)) + 1e-9   # centred moving RMS
    need = np.minimum(1.0, rms * db(over_db) / (p + 1e-12))
    la = int(0.002 * SR)
    mins = np.lib.stride_tricks.sliding_window_view(np.concatenate([np.ones(la), need, np.ones(la)]), 2 * la + 1).min(axis=1)
    g = np.empty_like(mins)
    a_rel, cur = np.exp(-1.0 / (release_s * SR)), 1.0
    for i, v in enumerate(mins):
        cur = v if v < cur else v + (cur - v) * a_rel
        g[i] = cur
    return (x * (g[:, None] if x.ndim == 2 else g)).astype(np.float32)


def true_peak_db(x):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.max(np.abs(up)) + 1e-12)


def lufs(x):
    return pyloudnorm.Meter(SR).integrated_loudness(x.astype(np.float64))


def meta(sid):
    """Freesound metadata for one sound, cached next to the audio cache (saves API calls on reruns)."""
    path = fs.CACHE / f"{sid}.meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    h = fs._get(f"/sounds/{sid}/", {"fields": fs.FIELDS})
    fs.CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(h), encoding="utf-8")
    return h


def source(role):
    h = meta(SOURCES[role]["id"])
    assert "publicdomain/zero" in h["license"], f"{h['id']} is not CC0: {h['license']}"
    return h, fs.fetch(h)


# ---------------------------------------------------------------- layers
def make_bed(rng):
    """Close paper burning: one take as the centre, a second window as a narrow side signal."""
    _, x = source("bed")
    m = x.mean(axis=1)
    m = filt(m, "highpass", 110.0, 2)
    m = filt(m, "lowpass", 6500.0, 4)                      # soft and close, no glassy top
    m = tame(m, 8.0, window_s=0.25)
    mid = seg(m, 3.0, DUR_S)
    side = filt(seg(m, 33.0, DUR_S), "highpass", 900.0, 2) * 0.35
    bed = np.stack([mid + side, mid - side], axis=1)

    # second paper take, laid over the burn front (13-23 s), softer and a little right of centre
    _, y = source("bed2")
    y = filt(filt(y.mean(axis=1), "highpass", 150.0, 2), "lowpass", 7500.0, 4)
    y = fs.fade(tame(fs.trim_silence(y, -45.0), 8.0, window_s=0.25), 0.8, 1.5)
    y = y / (np.sqrt(np.mean(y ** 2)) + 1e-9) * np.sqrt(np.mean(mid ** 2)) * db(-5.0)
    place(bed, y, 13.2, 1.0, 0.25)

    env = (smooth_step(T, 0.15, 2.4)                                # lights with the ignite ramp
           * (1.0 + (db(2.5) - 1.0) * smooth_step(T, 12.0, 16.0))  # the burn front adds fuel
           * (1.0 - smooth_step(T, 20.0, 24.6))                     # consumed by the end of the burn
           * slow_wobble(rng, 0.35, 1.5))
    return (bed * env[:, None]).astype(np.float32)


def pop_grains():
    """Isolated wood/ember pops cut from a close fireplace recording."""
    _, x = source("pops")
    x = filt(x, "highpass", 250.0, 2)
    x = filt(x, "lowpass", 7000.0, 4)                       # keep them woody, not glassy
    m = np.abs(x).max(axis=1)
    env = filt(m[:, None], "lowpass", 400.0, 2)[:, 0]
    floor = np.median(env)
    peaks, props = find_peaks(env, height=floor * 5.0, distance=int(0.12 * SR), prominence=floor * 3.0)
    grains = []
    pre, post = int(0.004 * SR), int(0.22 * SR)
    for p in peaks[np.argsort(-props["peak_heights"])]:
        a, b = p - pre, p + post
        if a < 0 or b > len(x):
            continue
        g = x[a:b].copy()
        # reject grains with a second strong hit inside (we want single, natural pops)
        tail = np.abs(g[int(0.03 * SR):]).max()
        if tail > 0.55 * np.abs(g).max():
            continue
        decay = np.exp(-np.arange(len(g)) / (0.06 * SR))[:, None]
        g = fs.fade(g * decay, 0.002, 0.03)
        grains.append((g / (np.abs(g).max() + 1e-9)).astype(np.float32))
        if len(grains) >= 40:
            break
    assert len(grains) >= 12, f"only {len(grains)} clean pops found"
    return grains


def make_pops(rng):
    grains = pop_grains()
    out = np.zeros((N, 2), np.float32)
    # Jittered times from a rate curve (pops per second): sparse while lit, busier on the burn front.
    # A jittered gap (0.55-1.45 x the mean) keeps it natural without Poisson clumps or long holes.
    def rate(t):
        if t < HOLD_S:
            return 0.5
        if t < 20.0:
            return 0.5 + 0.35 * smooth_step(t, 12.0, 16.0)
        return 0.85 * (1.0 - smooth_step(t, 20.0, 24.0)) + 0.15
    events, t = [], 1.6
    while t < 24.0:
        events.append(t)
        t += max(0.35, rng.uniform(0.55, 1.45) / rate(t))
    events.append(24.9)                                     # one last small tick in the tail
    log = []
    for i, t in enumerate(events):
        big = i in (4, len(events) // 2)                    # two fuller wood cracks, one in each half
        level = rng.uniform(-6.0, -1.0) if big else rng.uniform(-19.0, -8.0)
        if t > 22.5:
            level -= 6.0 * smooth_step(t, 22.5, 25.0)
        pan = float(rng.uniform(-0.45, 0.45))
        g = grains[rng.integers(len(grains))]
        # small random pitch/size change so no pop repeats exactly
        if rng.random() < 0.5:
            g = resample_poly(g, 10, int(rng.integers(9, 12)), axis=0).astype(np.float32)
        place(out, g, t, db(level), pan)
        log.append(dict(t=round(float(t), 3), level_db=round(float(level), 1), pan=round(pan, 2), big=bool(big)))
    return out, log


def make_whoosh(rng):
    """Low warm fire breath: a slowed 'burning air' gust over a low-passed fireplace roar."""
    _, x = source("whoosh")
    x = filt(filt(x, "highpass", 60.0, 2), "lowpass", 1400.0, 4)
    slow = resample_poly(x, 4, 3, axis=0).astype(np.float32)   # 4/3 longer, a fourth lower: warmer
    slow = fs.fade(slow, 0.5, 1.5)
    out = np.zeros((N, 2), np.float32)
    place(out, slow, 12.0, 1.0)                                # the burn front catches (~11.3 s long)
    ign = fs.fade(filt(seg(x, 1.0, 3.2), "lowpass", 900.0, 2), 0.4, 1.8)
    place(out, ign, 0.1, db(-9.0))                             # the small first breath of ignition

    _, r = source("roar")
    r = filt(filt(seg(r, 120.0, DUR_S), "highpass", 45.0, 2), "lowpass", 550.0, 4)
    r = r / (np.sqrt(np.mean(r ** 2)) + 1e-9) * np.sqrt(np.mean(slow ** 2)) * db(-4.0)
    swell = smooth_step(T, 12.0, 18.5) * (1.0 - smooth_step(T, 18.5, 24.2))
    out += r * (swell * slow_wobble(rng, 0.25, 2.5))[:, None]
    shape = np.maximum(smooth_step(T, 0.0, 0.6) * (1.0 - smooth_step(T, 3.0, 4.2)), swell)
    return (out * np.maximum(shape, 0.0)[:, None]).astype(np.float32)


def make_hiss(rng):
    """Faint ember sizzle rising as the calligraphy turns to ash, fading with the last glow."""
    _, x = source("hiss")
    x = filt(filt(x, "highpass", 2500.0, 4), "lowpass", 9500.0, 4)
    h = tame(seg(x, 12.0, DUR_S), 10.0)
    env = smooth_step(T, 16.0, 21.5) * (1.0 - smooth_step(T, 23.0, 25.8))
    return (h * (env * slow_wobble(rng, 0.5, 2.0))[:, None]).astype(np.float32)


# ---------------------------------------------------------------- mix
# Relative stem levels (dB, loudness-matched before the master gain): the bed carries the cue,
# pops sit on top, the breath is felt more than heard, the hiss is faint.
STEM_DB = {"Bed": 0.0, "Pops": -9.0, "Whoosh": -3.0, "Hiss": -14.0}


def limiter_gain(x, ceiling_db, attack_s=0.003, release_s=0.12):
    """Look-ahead peak limiter gain curve (the same curve is applied to every stem)."""
    peak = np.abs(resample_poly(x, 4, 1, axis=0)).max(axis=1)[::4][: len(x)]
    need = np.minimum(1.0, db(ceiling_db) / (peak + 1e-12))
    # look-ahead minimum, then smooth release
    la = int(attack_s * SR)
    padded = np.concatenate([need, np.ones(la)])
    mins = np.lib.stride_tricks.sliding_window_view(padded, la + 1).min(axis=1)[: len(x)]
    g = np.empty_like(mins)
    a_rel = np.exp(-1.0 / (release_s * SR))
    cur = 1.0
    for i, v in enumerate(mins):
        cur = v if v < cur else v + (cur - v) * a_rel
        g[i] = cur
    return g.astype(np.float32)


def build():
    rng = np.random.default_rng(SEED)
    stems = {"Bed": make_bed(rng)}
    stems["Pops"], pop_log = make_pops(rng)
    stems["Whoosh"] = make_whoosh(rng)
    stems["Hiss"] = make_hiss(rng)

    # loudness-match every stem to the bed, then offset (integrated gating ignores their silent parts)
    ref = lufs(stems["Bed"])
    for k in STEMS[1:]:
        stems[k] = stems[k] * db(ref - lufs(stems[k]) + STEM_DB[k])
    mix = sum(stems[k] for k in STEMS)
    g = db(TARGET_LUFS - lufs(mix))
    stems = {k: v * g for k, v in stems.items()}
    mix = mix * g
    lim = limiter_gain(mix, PEAK_DB - 0.3)
    total = np.ones(N, np.float32)
    for _ in range(3):   # the limiter lowers loudness slightly: re-trim and re-limit
        stems = {k: v * lim[:, None] for k, v in stems.items()}
        total *= lim
        mix = sum(stems[k] for k in STEMS)
        g = db(TARGET_LUFS - lufs(mix))
        stems = {k: v * g for k, v in stems.items()}
        mix = mix * g
        lim = limiter_gain(mix, PEAK_DB - 0.3)
    stems = {k: v * lim[:, None] for k, v in stems.items()}
    total *= lim
    print(f"limiter: max gain reduction {-20 * np.log10(total.min()):.1f} dB, "
          f"{np.mean(total < db(-1.0)) * 100:.1f} % of samples reduced by more than 1 dB")

    # clean ends: 10 ms in (it starts from silence anyway), last 0.6 s to exact silence
    fade = np.minimum(smooth_step(T, 0.0, 0.01), 1.0 - smooth_step(T, DUR_S - 0.6, DUR_S))
    stems = {k: (v * fade[:, None]).astype(np.float32) for k, v in stems.items()}
    mix = sum(stems[k] for k in STEMS)
    return mix, stems, pop_log


def measure(path):
    x, sr = soundfile.read(str(path), dtype="float32")
    assert sr == SR
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true+sample",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = r[r.rfind("Summary:"):]

    def grab(label):
        line = next(l for l in summary.splitlines() if l.strip().startswith(label))
        return float(line.split(":")[1].split()[0])
    return dict(file=path.name, dur_s=round(len(x) / SR, 3), channels=x.shape[1] if x.ndim == 2 else 1,
                lufs_pyloudnorm=round(float(lufs(x)), 2), lufs_ffmpeg=grab("I:"), lra=grab("LRA:"),
                true_peak_db=grab("Peak:") if "True peak" in summary else None,
                sample_peak_db=round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 2),
                end_abs_max=float(np.abs(x[-int(0.05 * SR):]).max()))


def main():
    files = [OUT / f"{NAME}.wav"] + [OUT / f"{NAME}_{k}.wav" for k in STEMS]
    if "--measure" not in sys.argv:
        mix, stems, pop_log = build()
        fs.write_wav(files[0], mix)
        for k in STEMS:
            fs.write_wav(OUT / f"{NAME}_{k}.wav", stems[k])
        for role, key in (("bed", "Bed"), ("bed2", "Bed__paper2"), ("pops", "Pops"), ("whoosh", "Whoosh"),
                          ("roar", "Whoosh__roar"), ("hiss", "Hiss")):
            hit, _ = source(role)
            alts = [meta(a) for a in SOURCES[role]["alt"][:2]]
            notes = {
                "bed": "fire card: paper bed, HP 110 Hz / LP 6.5 kHz, transients tamed to +8 dB over the 250 ms RMS, 3.0-29.0 s centre + 33-59 s side",
                "bed2": "fire card: second paper take at 13.2 s under the burn front, -5 dB",
                "pops": "fire card: ~40 isolated pops cut from it (HP 250 / LP 7k), placed on a seeded jittered rate curve",
                "whoosh": "fire card: slowed 4/3, LP 1.4 kHz; burn-front breath at 12 s + ignition breath at 0.1 s",
                "roar": "fire card: 120-146 s, LP 550 Hz, swells 12 -> 18.5 -> 24.2 s under the breath",
                "hiss": "fire card: 12-38 s, band 2.5-9.5 kHz, rises 16 -> 21.5 s, gone by 25.8 s",
            }[role]
            fs.credit(f"{NAME}_{key}", hit, alternates=alts, notes=notes)
    else:
        pop_log = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["pops"]
    metrics = [measure(p) for p in files]
    for m in metrics:
        print(f"{m['file']:34} {m['dur_s']:6.2f} s  I {m['lufs_ffmpeg']:6.1f} LUFS  LRA {m['lra']:4.1f}  "
              f"TP {m['true_peak_db']} dBTP  SP {m['sample_peak_db']} dBFS  end {m['end_abs_max']:.1e}")
    manifest = dict(
        cue=NAME, sample_rate=SR, channels=2, duration_s=DUR_S,
        timeline=dict(ignite=[0.0, 4.0], hold=[4.0, HOLD_S], burn_away=[HOLD_S, HOLD_S + BURN_S], tail=[HOLD_S + BURN_S, DUR_S]),
        start="the fire card's first frame (WBP_Saskarta_Intro.PlayIntro, same frame as IgniteStart)",
        stems="each stem is at its level in the mix; the four stems sum to the mix",
        pops=pop_log, metrics=metrics,
        sources={k: dict(id=v["id"], url=f"https://freesound.org/s/{v['id']}/", license="CC0") for k, v in SOURCES.items()},
    )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
