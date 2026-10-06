"""The fire card's sound, round 2: three clearly different takes on SFX_Intro_FireBurn to pick from.

The user rejected v1 (make_intro_fire.py: a close paper-burn bed + fireplace pops + ember hiss). It
read as a mundane, noisy campfire. These three avoid a continuous paper/fireplace bed, de-noise
and low-pass every bed, and follow the NEW card timing (from the card's first frame):

    0.0 - 12.0 s  the calligraphy is lit (ignite + hold)
   12.0 - 20.0 s  burn-away (8 s)
   20.0 - 21.5 s  tail into digital silence

    A "Cinematic ignition"  match strike + soft whump at 0 s; a warm low fire breath with very sparse
                            crackles; at 12 s a rising roar with a deep noise sub swell peaking at 17 s,
                            collapsing into a few bright ember tinkles and a long airy tail.
    B "Intimate ember"      a wood-wick candle in a silent room: delicate, sparse, close crackles and
                            tiny ember ticks; at 12 s the crackle accelerates under a gentle air rush,
                            then silence.
    C "Mythic/ritual"       a slowly breathing, pitched-down flame texture with a granular "shimmer"
                            of pitched-down flame grains; at 12 s it inhales (reversed flame), then
                            releases as a burst of embers, fading into wind-like air.

No music, no tonal drones, no instruments, no voice. Every layer is a processed Freesound recording
(all CC0); the processing (filters, granulation, reversal, noise-tail reverb) is synthetic.

Writes to Saved/GameAudio/Intro/alt/ (48 kHz stereo 16-bit):
    SFX_Intro_Fire_A.wav, _B.wav, _C.wav   21.5 s, -20 LUFS integrated, true peak <= -3 dBTP
    SFX_Intro_Fire_compare.wav              6 s of each (11-17 s: the reveal) with 1 s gaps
    manifest.json                           timeline, sources, loudness, spectral balance

    python Tools/Audio/make_intro_fire_v2.py            # fetch (cached), build, write, credit, measure
    python Tools/Audio/make_intro_fire_v2.py --measure  # only measure the files already written
"""
import json
import pathlib
import sys

import numpy as np
from scipy.signal import istft, resample_poly, stft, welch, fftconvolve, find_peaks

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402
from make_intro_fire import (db, filt, limiter_gain, lufs, measure, meta, smooth_step,  # noqa: E402
                             tame, true_peak_db)

SR = fs.SR
OUT = fs.ROOT / "Saved" / "GameAudio" / "Intro" / "alt"
PREFIX = "SFX_Intro_Fire"

REVEAL_S = 12.0    # PC_Saskarta calls RevealIntro; the burn-away starts
BURN_S = 8.0       # PC_Saskarta.RevealBurnTime (new)
TAIL_S = 1.5
DUR_S = REVEAL_S + BURN_S + TAIL_S
N = int(round(DUR_S * SR))
T = np.arange(N) / SR

TARGET_LUFS = -20.0
PEAK_DB = -3.0
SEED = 20260928
COMPARE = (11.0, 17.0)   # the 6 s of each variant in the compare file

# role -> Freesound id (all CC0)
SOURCES = {
    "match": 423811,        # scalywhale, "Match strike 03"
    "whump": 637533,        # kyles, "flame burst ignite bbq barbecue.flac"
    "lit": 186374,          # samararaine, "Bonfire Being Lit"
    "body": 483323,         # craigsmith, "R30-09-Fires Burns Wood and Metal Crackling.wav"
    "massive": 387924,      # Aegersum, "Fire -massive no cracking.wav"
    "campfire": 681366,     # SKrafft, "Campfire (Position 1)"
    "whoosh": 244926,       # hnhnh, "fire-whoosh.wav"
    "burst": 592572,        # magnuswaker, "Flame Burst"
    "candle": 680474,       # roisin.gleeson, "Candle double wood wick flame stereo 01.wav"
    "candle2": 680475,      # roisin.gleeson, "Candle double wood wick flame stereo 02.wav"
    "matches": 437547,      # Leandri140029, "Matches burning_01.WAV"
    "air": 454363,          # kyles, "wind medium brisk breeze through stiff dry co..."
    "flames": 813328,       # NickTayloe, "Crackling Flames (loop)"
    "flicker": 784382,
    "explosion": 855898,    # qubodup, "Fire Explosion"      # loganzsound, "Flame Crackle and Flicker 91% isopropyl Alcohol burning 02"
    "wind": 830335,         # thisusernameis..., "Trees in Wind, Soft Sea Currents, Pink Noise"
}
_audio = {}


def src(role):
    if role not in _audio:
        h = meta(SOURCES[role])
        assert "publicdomain/zero" in h["license"], f"{h['id']} is not CC0: {h['license']}"
        _audio[role] = (h, fs.fetch(h))
    return _audio[role][1]


# ---------------------------------------------------------------- helpers
def seg(x, start_s, dur_s):
    a = int(start_s * SR)
    out = x[a:a + int(dur_s * SR)]
    assert len(out) == int(dur_s * SR), (start_s, dur_s, len(x) / SR)
    return out


def place(dst, clip, at_s, gain=1.0, pan=0.0):
    """Add a mono or stereo clip at at_s (constant-power pan for mono)."""
    a = int(round(at_s * SR))
    if a >= len(dst):
        return
    if a < 0:
        clip, a = clip[-a:], 0
    clip = clip[: len(dst) - a]
    if clip.ndim == 1:
        th = (pan + 1) * np.pi / 4
        clip = np.stack([clip * np.cos(th), clip * np.sin(th)], axis=1) * np.sqrt(2)
    dst[a:a + len(clip)] += clip * gain


def mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def unit(x):
    """Scale to RMS 1 (over the non-silent part) so layers can be set in dB."""
    m = np.abs(mono(x))
    live = m > m.max() * 1e-3
    return (x / (np.sqrt(np.mean(np.square(mono(x)[live]))) + 1e-12)).astype(np.float32)


def varispeed(x, ratio):
    """Play at `ratio` x speed (0.5 = an octave down, twice as long)."""
    up, down = int(round(1000 / ratio)), 1000
    g = np.gcd(up, down)
    return resample_poly(x, up // g, down // g, axis=0).astype(np.float32)


def denoise(x, reduce_db=14.0, floor_pct=12, nper=2048):
    """Spectral de-noise: per-bin noise estimated as a low percentile of the magnitude over time,
    subtracted with a soft mask (limited to reduce_db). Takes the mic/preamp hiss off quiet beds."""
    chans = x if x.ndim == 2 else x[:, None]
    out = []
    for c in range(chans.shape[1]):
        f, t, Z = stft(chans[:, c], SR, nperseg=nper, noverlap=nper * 3 // 4)
        mag = np.abs(Z)
        noise = np.percentile(mag, floor_pct, axis=1, keepdims=True) * 1.5
        gain = np.clip(1.0 - (noise / (mag + 1e-12)) ** 2, db(-reduce_db), 1.0)
        # smooth the mask in time a little (no musical-noise chirps)
        k = np.ones(5) / 5
        gain = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, gain)
        _, y = istft(Z * gain, SR, nperseg=nper, noverlap=nper * 3 // 4)
        out.append(y[: len(chans)])
    y = np.stack(out, axis=1).astype(np.float32)
    if len(y) < len(chans):
        y = np.pad(y, ((0, len(chans) - len(y)), (0, 0)))
    return y if x.ndim == 2 else y[:, 0]


def noise_reverb(x, decay_s, lp_hz, wet_db, rng, predelay_s=0.02):
    """Stereo tail from exponentially decaying, low-passed noise (a plain, non-tonal room/air)."""
    n = int(decay_s * 1.6 * SR)
    t = np.arange(n) / SR
    env = np.exp(-6.9 * t / decay_s)
    ir = np.stack([rng.standard_normal(n) * env, rng.standard_normal(n) * env], axis=1)
    ir = filt(ir, "lowpass", lp_hz, 2)
    ir[: int(predelay_s * SR)] = 0
    ir /= np.sqrt(np.sum(ir ** 2, axis=0, keepdims=True))
    m = mono(x)
    wet = np.stack([fftconvolve(m, ir[:, 0])[: len(m)], fftconvolve(m, ir[:, 1])[: len(m)]], axis=1)
    return (wet * db(wet_db)).astype(np.float32)


def extract_grains(x, max_n, post_s, decay_s, hp=None, lp=None, min_gap_s=0.1, rel=5.0, clean=0.55):
    """Isolated crackles/pops cut at envelope peaks; each is decayed, faded and peak-normalised (mono)."""
    m = mono(x)
    if hp:
        m = filt(m, "highpass", hp, 2)
    if lp:
        m = filt(m, "lowpass", lp, 4)
    env = filt(np.abs(m)[:, None], "lowpass", 400.0, 2)[:, 0]
    floor = np.median(np.abs(env))
    peaks, props = find_peaks(env, height=floor * rel, distance=int(min_gap_s * SR), prominence=floor * rel * 0.6)
    grains, pre, post = [], int(0.003 * SR), int(post_s * SR)
    for p in peaks[np.argsort(-props["peak_heights"])]:
        a, b = p - pre, p + post
        if a < 0 or b > len(m):
            continue
        g = m[a:b].copy()
        if np.abs(g[int(0.03 * SR):]).max() > clean * np.abs(g).max():
            continue
        g = fs.fade(g * np.exp(-np.arange(len(g)) / (decay_s * SR)), 0.0015, 0.02)
        grains.append((g / (np.abs(g).max() + 1e-9)).astype(np.float32))
        if len(grains) >= max_n:
            break
    assert len(grains) >= 8, f"only {len(grains)} clean grains"
    return grains


def scatter(grains, times, levels_db, rng, pan_width=0.5, pitch=(0.92, 1.1)):
    out = np.zeros((N, 2), np.float32)
    log = []
    for t, lv in zip(times, levels_db):
        g = grains[rng.integers(len(grains))]
        r = float(rng.uniform(*pitch))
        g = varispeed(g, r) if abs(r - 1) > 0.01 else g
        pan = float(rng.uniform(-pan_width, pan_width))
        place(out, g, t, db(lv), pan)
        log.append(dict(t=round(float(t), 3), level_db=round(float(lv), 1), pan=round(pan, 2), pitch=round(r, 2)))
    return out, log


def event_times(rng, rate_fn, t0, t1, jitter=(0.5, 1.5), min_gap=0.04):
    """Jittered times from a rate curve (events per second)."""
    ts, t = [], t0
    while t < t1:
        ts.append(t)
        t += max(min_gap, rng.uniform(*jitter) / max(rate_fn(t), 1e-3))
    return ts


def wobble(rng, rate_hz, depth_db):
    k = int(DUR_S * rate_hz) + 3
    curve = np.interp(T * rate_hz, np.arange(k), rng.uniform(-1, 1, k))
    curve = filt(curve[:, None], "lowpass", rate_hz * 1.5, 2)[:, 0]
    return db(depth_db * curve / (np.abs(curve).max() + 1e-9)).astype(np.float32)


def sweep_lowpass(x, cut_curve, bands=(250, 500, 900, 1600, 2800, 5000)):
    """Time-varying low-pass: crossfade between fixed low-passes by cut_curve (Hz, per sample)."""
    xs = [filt(x, "lowpass", b, 4) for b in bands]
    pos = np.interp(np.log(np.clip(cut_curve, bands[0], bands[-1])), np.log(bands), np.arange(len(bands)))
    out = np.zeros_like(x)
    for i, y in enumerate(xs):
        w = np.clip(1 - np.abs(pos - i), 0, 1)
        out += y * (w[:, None] if x.ndim == 2 else w)
    return out


def stereo(x):
    return np.stack([x, x], axis=1) if x.ndim == 1 else x


def granular_cloud(x, rng, density, grain_s, pitch, dur_s, spread=0.8):
    """Pitched-down flame grains (Hann-windowed, random source position and pitch, random pan)."""
    m = mono(x)
    out = np.zeros((int(dur_s * SR), 2), np.float32)
    n_grains = int(density * dur_s)
    for _ in range(n_grains):
        L = int(rng.uniform(*grain_s) * SR)
        r = rng.uniform(*pitch)
        need = int(L * r) + 2
        a = rng.integers(0, len(m) - need)
        g = np.interp(np.arange(L) * r, np.arange(need), m[a:a + need]).astype(np.float32)
        g *= np.hanning(L).astype(np.float32)
        th = (rng.uniform(-spread, spread) + 1) * np.pi / 4
        at = rng.integers(0, len(out) - L)
        out[at:at + L, 0] += g * np.cos(th)
        out[at:at + L, 1] += g * np.sin(th)
    return out


# ---------------------------------------------------------------- A: cinematic ignition
def build_a(rng):
    L = {}
    # ignition: a soft match strike, then the flame catching with a low whump
    m = filt(filt(mono(src("match")), "highpass", 300.0, 2), "lowpass", 7000.0, 4)
    m = tame(fs.fade(m, 0.002, 0.4), 10.0, window_s=0.08)
    ign = np.zeros((N, 2), np.float32)
    place(ign, unit(m), 0.05, db(-6.0), -0.1)
    w = filt(filt(mono(src("whump")), "highpass", 45.0, 2), "lowpass", 2500.0, 4)
    place(ign, fs.fade(unit(w), 0.01, 0.35), 0.42, db(-3.0), 0.0)
    lit = filt(filt(mono(src("lit"))[int(0.9 * SR):], "highpass", 35.0, 2), "lowpass", 900.0, 4)
    place(ign, fs.fade(unit(lit), 0.05, 1.8), 0.45, db(-6.0), 0.05)
    ign += noise_reverb(ign, 1.4, 3000.0, -12.0, rng)
    L["ignition"] = ign

    # the hold: warm low fire breath (fireplace rumble, low-passed, de-noised, slowly breathing)
    breath = denoise(filt(filt(seg(src("body"), 6.0, DUR_S), "highpass", 70.0, 2), "lowpass", 800.0, 4), 12.0)
    breath = tame(breath, 6.0, window_s=0.3)                                        # a breath, not crackle
    env = (smooth_step(T, 0.4, 2.8) * db(-6.0 * (1 - smooth_step(T, 11.0, 12.5)))   # sits low under the hold
           * (1 - smooth_step(T, 17.2, 19.0)) * wobble(rng, 0.3, 2.5))
    L["breath"] = unit(breath) * env[:, None]

    # very sparse crackles from the campfire (woody, low-passed)
    cf = src("campfire")
    grains = extract_grains(cf, 40, 0.18, 0.045, hp=250.0, lp=6000.0, min_gap_s=0.15)
    rate = lambda t: 0.28 if t < REVEAL_S else 0.28 + 3.0 * smooth_step(t, 12.0, 16.5) * (1 - smooth_step(t, 16.8, 17.8))
    times = event_times(rng, rate, 1.9, 17.8)
    lv = [(-16.0 + rng.uniform(-5, 3)) + (5.0 * smooth_step(t, 12, 16.5)) for t in times]
    L["crackle"], crackle_log = scatter(grains, times, lv, rng, 0.45)

    # 12 s: the burn front catches: a rising roar (rumble opening up + slowed fire whoosh + slowed flame burst)
    r = src("massive")
    roar = np.zeros((N, 2), np.float32)
    place(roar, fs.fade(unit(filt(seg(r, 9.0, 8.0), "highpass", 40.0, 2)), 0.3, 0.3), 11.6)
    cut = 300.0 + 2600.0 * smooth_step(T, 12.0, 16.8) ** 1.5
    roar = sweep_lowpass(roar, cut)
    renv = smooth_step(T, 12.0, 16.9) ** 1.6 * (1 - smooth_step(T, 17.0, 18.3))
    roar = roar * renv[:, None]
    wh = varispeed(filt(src("whoosh"), "lowpass", 3500.0, 4), 0.72)          # peak 2.25 s -> 3.1 s
    place(roar, fs.fade(unit(wh), 0.8, 0.9), 16.95 - 3.1, db(-4.0))
    bu = varispeed(filt(src("burst"), "lowpass", 3000.0, 4), 0.8)            # peak 0.35 s -> 0.44 s
    place(roar, fs.fade(unit(bu), 0.01, 1.5), 16.6 - 0.44, db(-5.0))
    L["roar"] = roar

    # deep sub swell: the rumble an octave+ down, 25-110 Hz band (noise, not a tone), peaking at 17 s
    sub = varispeed(mono(seg(r, 2.0, 5.5)), 0.5)
    sub = filt(filt(sub, "highpass", 25.0, 2), "lowpass", 110.0, 4)
    senv = np.zeros(N, np.float32)
    senv[:] = smooth_step(T, 12.3, 17.0) ** 2 * (1 - smooth_step(T, 17.0, 19.2))
    subl = np.zeros((N, 2), np.float32)
    place(subl, fs.fade(unit(sub), 0.2, 0.5), 11.8)
    L["sub"] = subl * senv[:, None]

    # collapse: a few bright ember tinkles (small crackles, high-passed, pitched up) in a soft space
    tg = extract_grains(cf, 30, 0.08, 0.018, hp=2500.0, lp=11000.0, min_gap_s=0.1)
    ttimes = [17.55, 17.9, 18.12, 18.6, 18.95, 19.5, 20.25]
    tl = [-6.0, -9.0, -11.0, -10.0, -14.0, -16.0, -20.0]
    tink, tink_log = scatter(tg, ttimes, tl, rng, 0.7, pitch=(1.25, 1.6))
    L["tinkles"] = tink + noise_reverb(tink, 1.8, 7000.0, -8.0, rng)

    # the long airy tail: soft wind, band-passed, rising as the roar collapses, gone by 21.3 s
    air = filt(filt(seg(src("air"), 10.0, DUR_S), "highpass", 180.0, 2), "lowpass", 3000.0, 4)
    aenv = smooth_step(T, 16.6, 18.2) * (1 - smooth_step(T, 18.6, 21.3))
    L["air"] = unit(denoise(air, 10.0)) * aenv[:, None]

    mixdb = {"ignition": -4.0, "breath": -4.0, "crackle": 13.0, "roar": 0.0, "sub": -2.0, "tinkles": 11.0, "air": -14.0}
    return L, mixdb, dict(crackles=crackle_log, tinkles=tink_log)


# ---------------------------------------------------------------- B: intimate ember
def build_b(rng):
    L = {}
    c = src("candle")
    bed = denoise(filt(filt(seg(c, 2.0, DUR_S), "highpass", 140.0, 2), "lowpass", 7500.0, 4), 16.0)
    bed = tame(bed, 9.0, window_s=0.2)
    side = (bed[:, 0] - bed[:, 1]) * 0.5
    bed = np.stack([mono(bed) + side * 0.6, mono(bed) - side * 0.6], axis=1)   # keep it close and narrow
    env = smooth_step(T, 0.0, 1.6) * (1 + (db(3.0) - 1) * smooth_step(T, 12.0, 16.0)) * (1 - smooth_step(T, 17.5, 19.8))
    L["flame"] = unit(bed) * env[:, None]

    # delicate crackles + tiny ember ticks from both candle takes and a burning match
    g1 = extract_grains(c, 40, 0.10, 0.025, hp=500.0, lp=10000.0, min_gap_s=0.08)
    g2 = extract_grains(src("candle2"), 30, 0.10, 0.025, hp=500.0, lp=10000.0, min_gap_s=0.08)
    grains = g1 + g2
    ticks = [varispeed(g[: int(0.03 * SR)], 1.5) for g in grains]
    ticks = [fs.fade(filt(t, "highpass", 2000.0, 2), 0.0005, 0.008) for t in ticks]

    def rate(t):
        if t < REVEAL_S:
            return 0.9
        return 0.9 + 9.0 * smooth_step(t, 12.0, 17.0) ** 2 * (1 - smooth_step(t, 17.3, 18.8))
    times = event_times(rng, rate, 0.9, 19.0, min_gap=0.03)
    lv = [rng.uniform(-18, -6) + 2.0 * smooth_step(t, 12, 17) - 12.0 * smooth_step(t, 17.5, 19.0) for t in times]
    L["crackle"], log = scatter(grains, times, lv, rng, 0.35)
    tt = event_times(rng, lambda t: 0.5 if t < 12 else 0.5 + 4 * smooth_step(t, 13, 17) * (1 - smooth_step(t, 17.5, 18.8)), 2.3, 19.0)
    L["ticks"], tlog = scatter(ticks, tt, [rng.uniform(-20, -10) for _ in tt], rng, 0.6, pitch=(1.0, 1.3))

    # the reveal: the burning match flares in (the catch), and a gentle air rush
    mt = filt(filt(mono(src("matches")), "highpass", 250.0, 2), "lowpass", 8000.0, 4)
    mt = tame(denoise(mt, 14.0), 9.0, window_s=0.1)
    catch = np.zeros((N, 2), np.float32)
    place(catch, fs.fade(unit(mt[int(0.8 * SR):]), 0.05, 1.5), 12.0, 1.0, 0.1)
    L["catch"] = catch
    air = filt(filt(seg(src("air"), 36.0, DUR_S), "highpass", 150.0, 2), "lowpass", 2000.0, 4)
    aenv = smooth_step(T, 12.5, 17.2) * (1 - smooth_step(T, 17.4, 19.9))
    L["air"] = unit(denoise(air, 10.0)) * aenv[:, None]
    L["room"] = noise_reverb(L["crackle"] + L["ticks"], 0.6, 6000.0, -16.0, rng, 0.008)

    mixdb = {"flame": -16.0, "crackle": 16.0, "ticks": 10.0, "catch": -15.0, "air": -12.0, "room": 16.0}
    return L, mixdb, dict(crackles=log, ticks=tlog)


# ---------------------------------------------------------------- C: mythic / ritual
def build_c(rng):
    L = {}
    # the flame: crackling flames pitched down (0.62x), low-passed and de-noised, slowly breathing (~5.5 s)
    f = varispeed(src("flames"), 0.62)
    tex = denoise(filt(filt(seg(f, 5.0, DUR_S), "highpass", 50.0, 2), "lowpass", 2600.0, 4), 10.0)
    tex = tame(tex, 8.0, window_s=0.3)
    breathe = db(4.0 * np.sin(2 * np.pi * T / 5.5 - np.pi / 2))
    inhale = 1 - 0.93 * smooth_step(T, 12.4, 14.0)                 # drawn in as the inhale builds
    env = smooth_step(T, 0.0, 3.2) * breathe * inhale * wobble(rng, 0.4, 1.0)
    L["flame"] = unit(tex) * env[:, None]

    # shimmer: a granular cloud of pitched-down alcohol-flame flicker grains (random pitch = no tone)
    fl = denoise(filt(src("flicker"), "highpass", 600.0, 2), 14.0)
    cloud = granular_cloud(fl, rng, 90, (0.05, 0.16), (0.45, 0.75), DUR_S, 0.9)
    cloud = filt(filt(cloud, "highpass", 700.0, 2), "lowpass", 5500.0, 4)
    senv = smooth_step(T, 1.0, 5.0) * db(3.0 * np.sin(2 * np.pi * T / 5.5)) * (1 - 0.7 * smooth_step(T, 12.0, 14.0)) \
        * (1 - smooth_step(T, 14.3, 15.0))
    L["shimmer"] = unit(cloud) * senv[:, None]

    # 12 s: the inhale, a reversed fire whoosh + reversed flame burst, swelling into 14.4 s
    inh = np.zeros((N, 2), np.float32)
    wr = varispeed(filt(src("whoosh"), "lowpass", 4000.0, 4), 0.6)[::-1]
    wr = wr[: int(np.argmax(np.abs(mono(wr))) + 0.02 * SR)]            # up to its (reversed) peak
    place(inh, fs.fade(unit(wr), 1.2, 0.02), 14.4 - len(wr) / SR, db(-2.0))
    br = varispeed(filt(src("burst"), "lowpass", 5000.0, 4), 0.7)[::-1]
    br = br[: int(np.argmax(np.abs(mono(br))) + 0.02 * SR)]
    place(inh, fs.fade(unit(br), 0.6, 0.02), 14.4 - len(br) / SR, db(-6.0))
    rf = filt(filt(varispeed(src("flames"), 0.8)[int(2.0 * SR):int(4.6 * SR)][::-1], "highpass", 300.0, 2), "lowpass", 4500.0, 4)
    rise = (np.linspace(0.0, 1.0, len(rf)) ** 3)[:, None]                     # reversed flame, swelling to the cut
    place(inh, fs.fade(unit(rf) * rise, 0.02, 0.015), 14.4 - len(rf) / SR, db(-3.0))
    ienv = smooth_step(T, 11.6, 12.4)
    L["inhale"] = filt(inh, "highpass", 160.0, 2) * ienv[:, None]           # airy, drawn in (not a sub swell)

    # 14.4 s: the release, a flame burst forward and a spray of embers (dense -> sparse, rising pitch)
    rel = np.zeros((N, 2), np.float32)
    bu = varispeed(filt(filt(src("burst"), "highpass", 70.0, 2), "lowpass", 4000.0, 4), 0.75)
    place(rel, fs.fade(unit(bu[int(0.25 * SR):]), 0.004, 2.0), 14.36, db(-4.0))
    ex = varispeed(filt(filt(src("explosion"), "highpass", 90.0, 2), "lowpass", 5000.0, 4), 0.8)
    place(rel, fs.fade(unit(ex), 0.004, 0.8), 14.38, db(-3.0))
    rel += noise_reverb(rel, 2.2, 2500.0, -10.0, rng)
    L["release"] = rel
    cg = extract_grains(src("campfire"), 40, 0.09, 0.02, hp=1500.0, lp=10000.0, min_gap_s=0.08)
    et = event_times(rng, lambda t: 22.0 * np.exp(-(t - 14.4) / 1.1) + 0.6, 14.42, 19.2, min_gap=0.012)
    elv = [rng.uniform(-14, -5) - 9.0 * smooth_step(t, 14.5, 19.0) for t in et]
    emb, elog = scatter(cg, et, elv, rng, 0.9, pitch=(1.0, 1.5))
    L["embers"] = emb + noise_reverb(emb, 1.6, 8000.0, -9.0, rng)

    # into wind-like air
    wd = filt(filt(seg(src("wind"), 30.0, 8.0), "highpass", 120.0, 2), "lowpass", 2200.0, 4)
    wind = np.zeros((N, 2), np.float32)
    place(wind, unit(denoise(wd, 10.0)), 14.0)
    wenv = smooth_step(T, 14.4, 16.2) * (1 - smooth_step(T, 17.8, 21.3))
    air = filt(filt(seg(src("air"), 20.0, DUR_S), "highpass", 160.0, 2), "lowpass", 1800.0, 4)
    L["wind"] = (wind * 0.8 + unit(denoise(air, 10.0)) * 0.6) * wenv[:, None]

    mixdb = {"flame": -3.0, "shimmer": -13.0, "inhale": 2.0, "release": 3.0, "embers": 16.0, "wind": -8.0}
    return L, mixdb, dict(embers=elog)


# ---------------------------------------------------------------- mix / master
def master(layers, mixdb):
    """Sum layers at their dB (relative to layer RMS in its active part), trim to -20 LUFS, limit, fade."""
    mix = np.zeros((N, 2), np.float32)
    for k, x in layers.items():
        mix += stereo(x)[:N] * db(mixdb[k])
    mix = filt(mix, "highpass", 22.0, 2)      # nothing below the sub band
    for _ in range(4):
        mix = mix * db(TARGET_LUFS - lufs(mix))
        mix = mix * limiter_gain(mix, PEAK_DB - 0.4)[:, None]
    # clean ends: 10 ms in; out over the last 0.5 s to exact digital silence for the final 0.1 s
    fade = np.minimum(smooth_step(T, 0.0, 0.01), 1.0 - smooth_step(T, DUR_S - 0.6, DUR_S - 0.1))
    mix = mix * fade[:, None]
    # gate the tail: once the (50 ms smoothed) level stays under -75 dBFS to the end, make it exact zero
    env = filt(np.abs(mix).max(axis=1)[:, None], "lowpass", 20.0, 2)[:, 0]
    loud = np.nonzero(env > db(-75.0))[0]
    cut = int(loud[-1]) + 1 if len(loud) else 0
    ramp = np.ones(N, np.float32)
    k = int(0.05 * SR)
    ramp[cut:] = 0.0
    ramp[max(0, cut - k):cut] = np.linspace(1.0, 0.0, cut - max(0, cut - k))
    return (mix * ramp[:, None]).astype(np.float32)


def spectral_balance(x):
    f, P = welch(mono(x), SR, nperseg=8192)
    tot = P.sum()
    band = {k: round(float(10 * np.log10(P[(f >= a) & (f < b)].sum() / tot + 1e-20)), 1)
            for k, (a, b) in {"<100": (0, 100), "100-500": (100, 500), "500-2k": (500, 2000), "2-6k": (2000, 6000), ">6k": (6000, 24000)}.items()}
    # tonality check: the strongest narrow peak above a 1/3-octave-ish median of the long-term spectrum
    ps = 10 * np.log10(P + 1e-20)
    sel = (f > 40) & (f < 12000)
    med = np.array([np.median(ps[max(0, i - 25): i + 25]) for i in range(len(ps))])
    band["max_tonal_peak_db"] = round(float((ps - med)[sel].max()), 1)
    band["centroid_hz"] = int((f * P).sum() / tot)
    return band


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names = {"A": build_a, "B": build_b, "C": build_c}
    files = {k: OUT / f"{PREFIX}_{k}.wav" for k in names}
    logs = {}
    if "--measure" not in sys.argv:
        for k, fn in names.items():
            rng = np.random.default_rng(SEED + ord(k))
            layers, mixdb, logs[k] = fn(rng)
            for name in layers:
                x = stereo(layers[name])[:N] * db(mixdb[name])
                lv = lufs(x) if np.abs(x).max() > 0 else -99
                print(f"  {k}.{name:9} {lv:6.1f} LUFS  peak {20*np.log10(np.abs(x).max()+1e-12):6.1f} dB (pre-master)")
            fs.write_wav(files[k], master(layers, mixdb))
            print(f"built {files[k].name}")
        # compare: 6 s of each (the reveal, 11-17 s) with 1 s gaps
        parts = []
        a, b = int(COMPARE[0] * SR), int(COMPARE[1] * SR)
        import soundfile
        for k in names:
            x, _ = soundfile.read(str(files[k]), dtype="float32")
            c = x[a:b].copy()
            ramp = np.minimum(1, np.minimum(np.arange(len(c)), np.arange(len(c))[::-1]) / (0.25 * SR))[:, None]
            parts += [c * ramp, np.zeros((SR, 2), np.float32)]
        fs.write_wav(OUT / f"{PREFIX}_compare.wav", np.concatenate(parts[:-1]))
        credit()
    import soundfile
    metrics = {}
    for k, p in list(files.items()) + [("compare", OUT / f"{PREFIX}_compare.wav")]:
        m = measure(p)
        x, _ = soundfile.read(str(p), dtype="float32")
        m["spectrum"] = spectral_balance(x)
        m["first_10ms_abs_max"] = float(np.abs(x[: int(0.01 * SR)]).max())
        metrics[k] = m
        print(f"{m['file']:30} {m['dur_s']:6.2f} s  I {m['lufs_ffmpeg']:6.1f} LUFS  LRA {m['lra']:4.1f}  TP {m['true_peak_db']} dBTP  "
              f"end {m['end_abs_max']:.1e}  {m['spectrum']}")
    manifest = dict(
        variants={"A": "Cinematic ignition", "B": "Intimate ember", "C": "Mythic/ritual"},
        sample_rate=SR, channels=2, duration_s=DUR_S,
        timeline=dict(lit=[0.0, REVEAL_S], burn_away=[REVEAL_S, REVEAL_S + BURN_S], tail=[REVEAL_S + BURN_S, DUR_S]),
        start="the fire card's first frame (WBP_Saskarta_Intro.PlayIntro, same frame as IgniteStart)",
        compare=dict(file=f"{PREFIX}_compare.wav", excerpt_s=list(COMPARE), order=["A", "B", "C"], gap_s=1.0),
        metrics=metrics, events=logs or None,
        sources={k: dict(id=v, url=f"https://freesound.org/s/{v}/", license="CC0") for k, v in SOURCES.items()},
    )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")


USES = {
    "A": {"match": "0.05 s, HP 300 / LP 7k, transients tamed", "whump": "0.42 s, LP 2.5 kHz, the flame catching",
          "lit": "from 0.9 s, LP 900 Hz, the low body of the ignition", "body": "warm low breath under the hold (HP 70 / LP 800 Hz, de-noised, transients tamed)",
          "massive": "the 12 s roar (swept LP 300 Hz -> 2.9 kHz) and the sub swell (half speed, 25-110 Hz band, peak 17 s)",
          "campfire": "sparse crackle grains (HP 250 / LP 6k); ember tinkles at 17.5-20.3 s (HP 2.5k, pitched up 1.25-1.6x)",
          "whoosh": "0.72x speed, peak at 16.95 s under the roar", "burst": "0.8x speed, peak at 16.6 s",
          "air": "the airy tail, 180 Hz-3 kHz, 16.6 -> 21.3 s"},
    "B": {"candle": "close flame bed (HP 140 / LP 7.5k, de-noised 16 dB) + crackle and tick grains",
          "candle2": "more crackle grains", "matches": "the catch at 12.0 s (de-noised, LP 8k)",
          "air": "gentle air rush 12.5 -> 17.2 -> 19.9 s, 150 Hz-2 kHz"},
    "C": {"flames": "0.62x pitched-down flame texture, LP 2.6 kHz, breathing on a 5.5 s cycle; 2.6 s reversed at 0.8x as the swelling inhale",
          "flicker": "granular shimmer: 50-160 ms grains, 0.45-0.75x pitch, 700 Hz-5.5 kHz",
          "whoosh": "reversed at 0.6x, HP 160 Hz: the inhale into 14.4 s", "burst": "reversed (inhale) and forward (release at 14.36 s)", "explosion": "0.8x, HP 90 / LP 5k, the body of the release at 14.38 s",
          "campfire": "ember spray grains after the release (HP 1.5k, pitched up to 1.5x)",
          "wind": "wind-like air from 14.4 s (30-38 s of the source), HP 120 / LP 2.2 kHz", "air": "second air layer under the wind"},
}


def credit():
    # drop this script's old entries first (a swapped source must not stay credited)
    data = json.loads(fs.CREDITS_JSON.read_text(encoding="utf-8"))
    data = {k: e for k, e in data.items() if not k.startswith(f"{PREFIX}_")}   # v1's SFX_Intro_FireBurn_* stay
    fs.CREDITS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    for v, roles in USES.items():
        for role, note in roles.items():
            h, _ = _audio.get(role) or (meta(SOURCES[role]), None)
            fs.credit(f"{PREFIX}_{v}__{role}", h, notes=f"intro fire card, variant {v}: {note}")


if __name__ == "__main__":
    main()
