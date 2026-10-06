"""Ambience 2: a stronger storm layer, per-zone nature beds and stingers along the road, and a real Geiger counter.

Every sound here is cut from a real Freesound recording (CC0 preferred, CC-BY credited), then processed
(loop crossfades, filtering, distance reverb, gust swells, granular scatter). Nothing is synthesised
except the placement of events in time. There is no music: no instruments, no melodic drones.

    python Tools/Audio/make_ambience_v2.py              # fetch (cached), build, write WAVs, manifest, credits, demo
    python Tools/Audio/make_ambience_v2.py --measure    # print loudness/peak/seam of the files already written
    python Tools/Audio/make_ambience_v2.py --md         # print the placement table (road metre -> UE world cm)

Output: Saved/GameAudio/Ambience2/<Asset>.wav, manifest.json and _demo_road.wav (a 60 s drive).
Import target in Unreal: /Game/SaskartaGaea/Audio/Ambience2. Placement plan:
.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-AMBIENCE2-brief.md.

Formats (48 kHz, 16-bit PCM):
  AMB_*_Loop   beds: stereo seamless loops (60-110 s), integrated loudness -24..-20 LUFS
               spots: mono seamless loops for 3D emitters, -24 LUFS
  SFX_*        one-shots peaking at -6 dBFS (mono for 3D stingers; stereo for 2D storm gusts/thunder)
  SFX_Geiger_* real Eberline E-120 clicks; the clicks share one gain so their natural variation survives
               (the loudest peaks at -6 dBFS); the rate loops reuse those clicks at their own level.

Loops are seamless: a stretch of the source is equal-power crossfaded tail-into-head (freesound_fetch.make_loop);
every later process on a loop is circular (FFT filtering, periodic gust envelopes, np.roll decorrelation,
wrap-around grain placement), so the seam stays continuous.
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np
import pyloudnorm
import soundfile
from scipy.signal import butter, fftconvolve, sosfilt, sosfiltfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

ROOT = fs.ROOT
OUT = ROOT / "Saved" / "GameAudio" / "Ambience2"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Ambience2"
SR = fs.SR
ONESHOT_PEAK_DB = -6.0
METER = pyloudnorm.Meter(SR)

# --------------------------------------------------------------------------- Freesound metadata (cached)

_hits = {}


def hit_for(sound_id):
    """Sound metadata; CC0 or CC-BY only. Cached on disk so a rebuild makes no API calls."""
    if sound_id in _hits:
        return _hits[sound_id]
    cache = fs.CACHE / f"meta_{sound_id}.json"
    if cache.exists():
        h = json.loads(cache.read_text(encoding="utf-8"))
    else:
        h = fs._get(f"/sounds/{sound_id}/", {"fields": fs.FIELDS})
        fs.CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(h), encoding="utf-8")
    lic = h["license"]
    assert "publicdomain/zero" in lic or "/licenses/by/" in lic, f"{sound_id} ({h['name']!r}) licence not allowed: {lic}"
    _hits[sound_id] = h
    return h


def lic_short(h):
    return "CC0" if "publicdomain/zero" in h["license"] else "CC-BY " + h["license"].rstrip("/").rsplit("/", 1)[-1]


_audio = {}


def src(sound_id):
    if sound_id not in _audio:
        _audio[sound_id] = fs.fetch(hit_for(sound_id))
    return _audio[sound_id]


# --------------------------------------------------------------------------- DSP helpers


def mono(x):
    return x.mean(axis=1).astype(np.float32) if x.ndim == 2 else x.astype(np.float32)


def butter_filt(x, lo=None, hi=None, order=2):
    """Zero-phase Butterworth (for one-shots)."""
    if lo:
        x = sosfiltfilt(butter(order, lo, "hp", fs=SR, output="sos"), x, axis=0)
    if hi:
        x = sosfiltfilt(butter(order, hi, "lp", fs=SR, output="sos"), x, axis=0)
    return x.astype(np.float32)


def cfilt(x, lo=None, hi=None, order=2, shelf=None):
    """Circular zero-phase Butterworth magnitude via FFT: keeps a loop seamless.
    shelf=(freq_hz, gain_db) adds a gentle low-shelf."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    h = np.ones_like(f)
    if hi:
        h *= 1.0 / np.sqrt(1.0 + (f / hi) ** (2 * order))
    if lo:
        h *= 1.0 / np.sqrt(1.0 + (lo / np.maximum(f, 1e-3)) ** (2 * order))
    if shelf:
        fc, g = shelf
        h *= 1.0 + (10 ** (g / 20.0) - 1.0) / (1.0 + (f / fc) ** 2)
    X = np.fft.rfft(x, axis=0)
    X *= h[:, None] if x.ndim == 2 else h
    return np.fft.irfft(X, n=n, axis=0).astype(np.float32)


def varispeed(x, ratio):
    """Tape-style speed change (ratio < 1 = slower and lower)."""
    n = len(x)
    pos = np.arange(0, n - 1, ratio)
    if x.ndim == 2:
        return np.stack([np.interp(pos, np.arange(n), x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)
    return np.interp(pos, np.arange(n), x).astype(np.float32)


def reverb_ir(rt60, seed, pre_s=0.015, hi=6000.0):
    rng = np.random.default_rng(seed)
    n = int((rt60 * 1.1 + pre_s) * SR)
    t = np.arange(n) / SR
    h = rng.standard_normal(n) * 10 ** (-3.0 * t / rt60)
    h[: int(pre_s * SR)] = 0.0
    h = sosfilt(butter(1, hi, "lp", fs=SR, output="sos"), h)
    return (h / np.sqrt(np.sum(h ** 2))).astype(np.float32)


def verb(x, rt60, wet, seed=1, hi=6000.0):
    """Adds a reverb tail (the output is longer by the tail). Mono in, mono out."""
    h = reverb_ir(rt60, seed, hi=hi)
    x = mono(x)
    y = fftconvolve(x, h)[: len(x) + len(h)]
    dry = np.concatenate([x, np.zeros(len(y) - len(x), np.float32)])
    return (dry + wet * y * 0.35).astype(np.float32)


def distant(x, lp=3500.0, hp=120.0, rt60=1.6, wet=0.6, seed=1):
    """Far away: air absorption (low-pass), no close low end, more room."""
    return verb(butter_filt(mono(x), hp, lp), rt60, wet, seed=seed, hi=lp)


def fade(x, fin, fout):
    return fs.fade(x, fin, fout)


def swell(x, attack_frac=0.4, release_frac=0.45):
    """Raised-cosine swell envelope over the whole clip (a gust breathing in and out)."""
    n = len(x)
    a, r = max(1, int(n * attack_frac)), max(1, int(n * release_frac))
    env = np.ones(n, np.float32)
    env[:a] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a))
    env[-r:] = np.minimum(env[-r:], 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r)))
    return x * (env[:, None] if x.ndim == 2 else env)


def peak_norm(x, db=ONESHOT_PEAK_DB):
    return fs.normalize(x, db).astype(np.float32)


def lufs(x):
    return float(METER.integrated_loudness(x.astype(np.float64)))


def lufs_norm(x, target):
    g = 10 ** ((target - lufs(x)) / 20.0)
    y = x * g
    peak = np.abs(y).max()
    if peak > 10 ** (-1.0 / 20):  # keep 1 dB of headroom: soft-knee the rare gust peak rather than clip
        k = 10 ** (-1.0 / 20)
        y = np.where(np.abs(y) > 0.7 * k, np.sign(y) * (0.7 * k + 0.3 * k * np.tanh((np.abs(y) - 0.7 * k) / (0.3 * k))), y)
    return y.astype(np.float32)


def env_db(m, win_s=0.01):
    w = max(1, int(win_s * SR))
    cs = np.concatenate([[0.0], np.cumsum(m.astype(np.float64) ** 2)])
    i = np.arange(len(m))
    a, b = np.clip(i - w // 2, 0, len(m)), np.clip(i + w - w // 2, 0, len(m))
    e = np.sqrt((cs[b] - cs[a]) / w + 1e-12)
    return 20 * np.log10(e)


def find_events(x, n, max_s, min_s=0.03, thr_db=-24.0, tail_db=-42.0, gap_s=0.15, pre_s=0.01, lo_s=0.0, hi_s=None):
    """The n strongest discrete events (onset over thr_db re the loudest, tail kept down to tail_db)."""
    lo, hi = int(lo_s * SR), int((hi_s * SR) if hi_s else len(x))
    xs = x[lo:hi]
    m = mono(xs)
    e = env_db(m)
    top = e.max()
    act = (e > top + thr_db).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], act, [0]])))
    regions = []
    for s, t in zip(edges[::2], edges[1::2]):
        if regions and s - regions[-1][1] < gap_s * SR:
            regions[-1][1] = t
        else:
            regions.append([s, t])
    evs = []
    step = int(0.005 * SR)
    for s, t in regions:
        if t - s < min_s * SR:
            continue
        lim = min(len(m), s + int(max_s * SR))
        end = min(t, lim)
        while end < lim and e[end] > top + tail_db:
            end += step
        end = min(end, lim)
        a = max(0, s - int(pre_s * SR))
        evs.append((a, end, float(e[s:t].max())))
    evs.sort(key=lambda v: -v[2])
    chosen = sorted(evs[:n])
    out = [(xs[a:b].copy(), (lo + a) / SR, (lo + b) / SR) for a, b, _ in chosen]
    if len(out) < n:
        # Dense textures (a flapping flag, rain on leaves) merge into one region: fall back to the loudest
        # well-separated short windows of the same stretch.
        out = peak_windows(xs, n, pre_s=max(pre_s, 0.1 * max_s), post_s=0.8 * max_s, min_gap_s=1.5 * max_s)
        out = [(s, a + lo / SR, b + lo / SR) for s, a, b in out]
    return out


def peak_windows(x, n, pre_s, post_s, min_gap_s, lo_s=0.0, hi_s=None):
    """n windows around the loudest, well-separated 0.5 s energy peaks (thunder rolls, gusts)."""
    m = mono(x)
    hi = int(hi_s * SR) if hi_s else len(m)
    lo = int(lo_s * SR)
    hop, win = int(0.1 * SR), int(0.5 * SR)
    starts = np.arange(lo + int(pre_s * SR), max(lo + int(pre_s * SR) + 1, hi - int(post_s * SR) - win), hop)
    cs = np.concatenate([[0.0], np.cumsum(m.astype(np.float64) ** 2)])
    energy = cs[np.minimum(starts + win, len(m))] - cs[starts]
    order = np.argsort(-energy)
    gap = min_gap_s
    for _ in range(8):
        chosen = []
        for i in order:
            p = int(starts[i])
            if all(abs(p - c) >= gap * SR for c in chosen):
                chosen.append(p)
            if len(chosen) == n:
                break
        if len(chosen) == n:
            break
        gap /= 1.5
    out = []
    for p in sorted(chosen):
        a, b = max(0, p - int(pre_s * SR)), min(len(x), p + int(post_s * SR))
        out.append((x[a:b].copy(), a / SR, b / SR))
    return out


def steadiest_start(x, length_s, lo_s=0.0, hi_s=None, quiet=False):
    """Start (s) of the flattest length_s stretch within [lo_s, hi_s] (least 1-s level spread)."""
    m = mono(x)
    hi = int((hi_s or len(m) / SR) * SR)
    blocks = np.array([fs.rms_db(m[k:k + SR]) for k in range(int(lo_s * SR), max(int(lo_s * SR) + 1, hi - SR), SR)])
    n = int(length_s)
    if len(blocks) <= n:
        return lo_s
    best, best_k = 1e9, 0
    for k in range(0, len(blocks) - n):
        w = blocks[k:k + n]
        score = w.std() + (0.15 * w.mean() if quiet else -0.1 * w.mean())
        if score < best:
            best, best_k = score, k
    return lo_s + best_k


def build_loop(x, want_s, xf_s=3.0, start_s=None, lo_s=0.0, hi_s=None, quiet=False, floor_s=60.0):
    """Seamless loop of want_s from the source (tiled whole-number times up to floor_s if the source is short)."""
    total = (hi_s or len(x) / SR) - lo_s
    want = min(want_s, total - xf_s - 0.5)
    if start_s is None:
        start_s = steadiest_start(x, want + xf_s, lo_s, hi_s, quiet)
    a = int(start_s * SR)
    seg = x[a:a + int((want + xf_s) * SR)]
    loop = fs.make_loop(seg, xf_s)
    reps = 1
    while len(loop) * reps < floor_s * SR:
        reps += 1
    note = f"{start_s:.1f}-{start_s + want + xf_s:.1f} s of source, {xf_s:.0f} s crossfade" + (f", tiled x{reps}" if reps > 1 else "")
    return np.concatenate([loop] * reps).astype(np.float32), note


def periodic_env(n, seed, kmin=3, kmax=14, sharp=2.2):
    """0..1 random-looking swell curve that is exactly periodic over n samples (seam-safe)."""
    rng = np.random.default_rng(seed)
    ctrl = 2000
    t = np.arange(ctrl) / ctrl
    g = np.zeros(ctrl)
    for k in range(kmin, kmax + 1):
        g += rng.uniform(0.3, 1.0) / k ** 0.7 * np.sin(2 * np.pi * k * t + rng.uniform(0, 2 * np.pi))
    g = (g - g.min()) / (g.max() - g.min())
    g = g ** sharp
    return np.interp(np.arange(n) / n * ctrl, np.arange(ctrl + 1), np.concatenate([g, g[:1]])).astype(np.float32)


def gust_swells(loop, seed, depth=0.45, band=(250.0, 3000.0), boost_db=6.0, kmin=3, kmax=12):
    """Build gusts into a wind loop: slow level swells plus a brighter band that opens on each swell."""
    env = periodic_env(len(loop), seed, kmin, kmax)
    e = env[:, None] if loop.ndim == 2 else env
    bright = cfilt(loop, band[0], band[1])
    return (loop * (1.0 - depth + 2 * depth * e) + (10 ** (boost_db / 20) - 1) * bright * e).astype(np.float32)


def to_stereo_decorrelated(loop):
    """Mono loop -> stereo by pairing it with itself half a loop later (still seamless)."""
    m = mono(loop)
    return np.stack([m, np.roll(m, len(m) // 2)], axis=1)


def scatter_circular(n_out, grains, seed, count, gain_db=(-6, 0), stereo=True, env=None):
    """Place `count` grains (random picks from `grains`) at random times on a circular timeline of n_out."""
    rng = np.random.default_rng(seed)
    buf = np.zeros((n_out, 2) if stereo else n_out, np.float32)
    for _ in range(count):
        g = mono(grains[rng.integers(len(grains))])
        t = int(rng.uniform(0, n_out))
        gain = 10 ** (rng.uniform(*gain_db) / 20)
        if env is not None:
            gain *= 0.25 + 0.75 * env[t]
        idx = (t + np.arange(len(g))) % n_out
        if stereo:
            pan = rng.uniform(-0.8, 0.8)
            lg, rg = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
            np.add.at(buf[:, 0], idx, g * gain * lg)
            np.add.at(buf[:, 1], idx, g * gain * rg)
        else:
            np.add.at(buf, idx, g * gain)
    return buf


# --------------------------------------------------------------------------- asset registry

ASSETS = []  # dicts: name, audio, zone, type, loop, volume_db, interval_s, pool, use, sources


def add(name, audio, zone, kind, sources, use, volume_db=0.0, interval_s=None, pool=None, loop=None, lufs_target=None, extra=None):
    """Register an asset. sources: list of (sound_id, note). Beds/spots are LUFS-normalised, one-shots peak-normalised."""
    loop = kind in ("bed", "spot") if loop is None else loop
    if kind == "bed":
        audio = lufs_norm(audio if audio.ndim == 2 else to_stereo_decorrelated(audio), lufs_target or -22.0)
    elif kind == "spot":
        audio = lufs_norm(mono(audio), lufs_target or -24.0)
    elif kind == "oneshot":
        audio = peak_norm(audio)
    ASSETS.append(dict(name=name, audio=audio, zone=zone, type=kind, loop=loop, volume_db=volume_db,
                       interval_s=interval_s, pool=pool, use=use, sources=sources, extra=extra or {}))
    return audio


def oneshot(x, fin=0.005, fout=0.08, to_mono=True):
    x = mono(x) if to_mono else x
    return fade(x, fin, min(fout, len(x) / SR * 0.4))


# --------------------------------------------------------------------------- 1. storm layer


def build_storm():
    Z = "Storm"
    # Three wind beds that layer: breeze (moderate mountain wind), strong (stormy night), gale (Tramontane in the
    # stones of a summit). Loudness rises -24 / -22 / -20 LUFS so an equal-power crossfade by StormIntensity
    # also rises in level.
    for name, sid, want, seed, lufs_t, depth, boost, window, use in [
        ("AMB_Storm_WindBreeze_Loop", 725630, 80, 11, -24.0, 0.35, 4.0, (0, None),
         "Storm bed, low intensity (StormIntensity 0-0.45). Moderate mountain wind with slow swells."),
        ("AMB_Storm_WindStrong_Loop", 352720, 80, 12, -22.0, 0.45, 6.0, (0, None),
         "Storm bed, mid intensity (0.3-0.8). Strong gusting night wind."),
        ("AMB_Storm_WindGale_Loop", 759918, 85, 13, -20.0, 0.5, 7.0, (22, 152),
         "Storm bed, high intensity (0.65-1). Tramontane gale between summit stones (source cut before its 2:40 flag/voices)."),
    ]:
        x = src(sid)
        loop, note = build_loop(x, want, 3.0, lo_s=window[0], hi_s=window[1])
        loop = cfilt(loop, 30.0, None)
        loop = gust_swells(loop, seed, depth=depth, boost_db=boost)
        add(name, loop, Z, "bed", [(sid, note + f"; gust swells built in (depth {depth}, +{boost:.0f} dB 250-3000 Hz band)")], use,
            volume_db=0.0, lufs_target=lufs_t)

    # Gust one-shots: pressure swells from three real wind recordings.
    gusts = []
    for sid, n, lo, hi in [(454092, 4, 0, None), (352720, 3, 0, None), (759918, 3, 22, 152)]:
        for seg, a, b in peak_windows(src(sid), n, pre_s=3.0, post_s=3.5, min_gap_s=9.0, lo_s=lo, hi_s=hi):
            gusts.append((sid, seg, a, b))
    for k, (sid, seg, a, b) in enumerate(gusts, 1):
        y = swell(butter_filt(seg, 40, None), 0.45, 0.5)
        add(f"SFX_Storm_Gust_{k:02d}", y, Z, "oneshot", [(sid, f"{a:.1f}-{b:.1f} s, raised-cosine swell")],
            "2D gust swell on the gust timer (20-90 s, faster with StormIntensity); layers over the wind beds.",
            volume_db=-4.0, interval_s=[20, 90], pool="Storm_Gust")

    # Sand/grit hiss: A = a real Saharan dust storm high-passed to its grit; B = sand pouring on metal, scattered
    # as a granular texture, as the grit hitting the carrier's hull.
    x = src(627055)
    loop, note = build_loop(x, 80, 3.0)
    loop = to_stereo_decorrelated(cfilt(loop, 1200.0, 12000.0))
    loop = gust_swells(loop, 21, depth=0.4, band=(2000, 9000), boost_db=5.0)
    add("AMB_Storm_SandHiss_Loop", loop, Z, "bed", [(627055, note + ", high-passed 1.2 kHz to the grit, decorrelated stereo")],
        "2D grit hiss layer, scaled by StormIntensity^2 (only audible in the dust walls).", volume_db=-6.0, lufs_target=-24.0)

    grains = []
    for sid in (199358, 199359, 199363):
        m = mono(src(sid))
        for seg, _, _ in peak_windows(m, 4, 0.4, 2.2, 2.0):
            grains.append(fade(seg, 0.2, 0.8))
    n_out = int(72 * SR)
    env = periodic_env(n_out, 22, 3, 10)
    texture = scatter_circular(n_out, grains, 23, 70, (-9, 0), True, env)
    texture = cfilt(texture, 700.0, 14000.0)
    add("AMB_Storm_SandOnMetal_Loop", texture, Z, "bed",
        [(199358, "grains 0.4 s pre / 2.2 s post loudest pours"), (199359, "grains"), (199363, "grains")],
        "2D (carrier-attached) sand spraying the hull: 70 grains on a circular 72 s timeline, gust-shaped.",
        volume_db=-8.0, lufs_target=-24.0)

    sprays = []
    for sid in (199362, 199363, 199397, 199330, 199329, 199359):
        seg, a, b = peak_windows(src(sid), 1, 0.6, 2.4, 1.0)[0]
        sprays.append((sid, seg, a, b))
    for k, (sid, seg, a, b) in enumerate(sprays, 1):
        y = swell(butter_filt(mono(seg), 500, 14000), 0.2, 0.55)
        add(f"SFX_Storm_SandSpray_{k:02d}", y, Z, "oneshot", [(sid, f"{a:.1f}-{b:.1f} s, band 500 Hz-14 kHz")],
            "Grit burst on the carrier hull, fired with a gust (50%) and in dust walls; attach to the carrier, mono.",
            volume_db=-8.0, interval_s=[8, 30], pool="Storm_Sand")

    # Thunder: distant rolls with long tails (lightning with a strike >= 2.5 km) and close cracks (< 2.5 km).
    k = 0
    for sid, n in [(577317, 3), (576963, 2), (567728, 2), (577315, 1)]:
        for seg, a, b in peak_windows(src(sid), n, pre_s=3.0, post_s=15.0, min_gap_s=14.0):
            k += 1
            y = fade(butter_filt(seg, 25, 7000), 1.2, 5.0)
            add(f"SFX_Storm_ThunderDistant_{k:02d}", y, Z, "oneshot", [(sid, f"{a:.1f}-{b:.1f} s, 18 s roll with tail")],
                "2D distant dry thunder, played by the ambience director distance/343 s after OnLightningStrike (>= 2.5 km).",
                volume_db=-6.0, pool="Storm_ThunderDistant")
    for k, sid in enumerate((505113, 534023, 717909), 1):
        seg, a, b = peak_windows(src(sid), 1, pre_s=0.6, post_s=11.0, min_gap_s=5.0)[0]
        y = fade(butter_filt(seg, 25, None), 0.3, 3.0)
        add(f"SFX_Storm_ThunderClose_{k:02d}", y, Z, "oneshot", [(sid, f"{a:.1f}-{b:.1f} s, crack and roll")],
            "2D close crack (< 2.5 km strike), after distance/343 s.", volume_db=-3.0, pool="Storm_ThunderClose")

    # Whistling wind: through rocks (a 2D layer on the climb) and through ruins (a mono spot at structures).
    loop, note = build_loop(src(145777), 80, 3.0)
    add("AMB_Storm_WhistleRocks_Loop", cfilt(loop, 150.0, 10000.0), Z, "bed",
        [(145777, note + ", 150 Hz-10 kHz")], "2D whistle layer on the exposed climb, scaled by StormIntensity.",
        volume_db=-8.0, lufs_target=-24.0)
    loop, note = build_loop(src(454355), 60, 3.0)
    add("AMB_Storm_WhistleRuins_Loop", cfilt(loop, 120.0, 8000.0), Z, "spot",
        [(454355, note + ", 120 Hz-8 kHz")], "3D wind whistling through ruins (Numbered Stop arch, waystation walls).",
        volume_db=-6.0)

    # Debris one-shots (mono, 3D: the director drops them 15-60 m around the carrier).
    debris = [
        ("StoneSkitter", [(734669, 2, 2.5), (668605, 2, 3.0)], (80, None), "Small stones skittering across rock.", [30, 90], -8.0, None),
        ("BranchSnap", [(354103, 1, 2.0), (354102, 1, 1.5), (734627, 2, 1.6)], (60, None), "A dry branch snapping in a gust (valley/basin only).", [40, 120], -10.0, None),
        ("TinRattle", [(631929, 2, 2.5), (631931, 1, 2.5), (406384, 1, 3.0)], (60, 14000), "A loose tin sheet rattling (basin structures, waystation).", [30, 80], -10.0, None),
    ]
    for thing, picks, band, use, interval, vol, _ in debris:
        k = 0
        for sid, n, max_s in picks:
            for seg, a, b in find_events(src(sid), n, max_s, thr_db=-18, tail_db=-40, gap_s=0.35):
                k += 1
                y = oneshot(butter_filt(mono(seg), band[0], band[1]), 0.004, 0.25)
                add(f"SFX_Storm_{thing}_{k:02d}", y, Z, "oneshot", [(sid, f"{a:.2f}-{b:.2f} s")], use,
                    volume_db=vol, interval_s=interval, pool=f"Storm_{thing}")
    # Distant rockfall: far, low-passed, roomy.
    rf = [(60085, peak_windows(src(60085), 1, 1.0, 9.0, 5.0)[0], 1.0),
          (841522, peak_windows(src(841522), 1, 1.5, 9.0, 5.0)[0], 1.0),
          (668605, (src(668605), 0.0, len(src(668605)) / SR), 0.6)]
    for k, (sid, (seg, a, b), speed) in enumerate(rf, 1):
        s = varispeed(mono(seg), speed) if speed != 1.0 else mono(seg)
        y = oneshot(distant(s, lp=2200, hp=60, rt60=2.4, wet=0.8, seed=30 + k), 0.2, 2.5)
        add(f"SFX_Storm_RockfallDistant_{k:02d}", y, Z, "oneshot",
            [(sid, f"{a:.1f}-{b:.1f} s" + (f", varispeed x{speed}" if speed != 1 else "") + ", low-passed 2.2 kHz, 2.4 s room")],
            "Distant rockfall from the valley walls, 150-400 m off the road (basin walls, foot, climb).",
            volume_db=-8.0, interval_s=[120, 300], pool="Storm_Rockfall")


# --------------------------------------------------------------------------- 2. zones


def events_to_pool(zone, thing, picks, use, interval, vol, pool, process, n_default=1, max_s=3.0, thr_db=-20, **kw):
    k = 0
    for pick in picks:
        sid, n = pick[0], pick[1]
        opts = dict(max_s=max_s, thr_db=thr_db, tail_db=-42, gap_s=0.3)
        opts.update(kw)
        if len(pick) > 2:
            opts.update(pick[2])
        for seg, a, b in find_events(src(sid), n, **opts):
            k += 1
            y = process(seg, k)
            add(f"SFX_{zone}_{thing}_{k:02d}", y, zone, "oneshot", [(sid, f"{a:.2f}-{b:.2f} s")], use,
                volume_db=vol, interval_s=interval, pool=pool)


def build_valley():
    Z = "Valley"
    loop, note = build_loop(src(146436), 85, 3.0)
    loop = gust_swells(cfilt(loop, 60, 16000), 41, depth=0.3, band=(1500, 9000), boost_db=4.0)
    add("AMB_Valley_DryGrass_Loop", loop, Z, "bed", [(146436, note + ", swells on the 1.5-9 kHz rustle")],
        "2D valley floor and ridge: wind in dry grass.", volume_db=-2.0, lufs_target=-22.0)

    # Sparse hardy insects: a close grasshopper buzz, band-limited and gated into bursts with long lulls.
    x = mono(src(264505))
    loop, note = build_loop(x, 80, 2.0)
    loop = cfilt(loop, 2500, 9000)
    gate = periodic_env(len(loop), 42, 6, 22, sharp=5.0)
    gate = np.clip((gate - 0.18) / 0.5, 0, 1)
    loop = to_stereo_decorrelated(loop * gate)
    add("AMB_Valley_Insects_Loop", loop, Z, "bed",
        [(264505, note + ", 2.5-9 kHz, periodic gate: bursts with long lulls")],
        "2D sparse insects; volume = (1 - StormIntensity/0.7), so they only come up in lulls and on the calmer stretches.",
        volume_db=-10.0, lufs_target=-24.0)

    corvids = [(512781, 1), (512780, 1), (856322, 1), (856323, 1), (844570, 1), (70192, 1)]
    events_to_pool(Z, "Crow", corvids, "A distant crow or raven, 150-400 m off the road (few, sparse).", [45, 140], -8.0,
                   "Valley_Birds", lambda s, k: oneshot(distant(s, lp=4500, hp=250, rt60=1.8, wet=0.55, seed=50 + k), 0.01, 0.8),
                   max_s=4.0, thr_db=-26, gap_s=0.6)
    events_to_pool(Z, "Insect", [(264505, 2, dict(lo_s=90.0))], "A single close insect burst in a lull.", [20, 60], -14.0,
                   "Valley_Insects", lambda s, k: oneshot(swell(butter_filt(mono(s), 2500, 9000), 0.15, 0.4), 0.02, 0.2),
                   max_s=2.5, thr_db=-10, gap_s=0.5)


def build_waiting_water():
    Z = "WaitingWater"
    loop, note = build_loop(mono(src(637977)), 68, 3.0)
    add("AMB_WaitingWater_Trickle_Loop", cfilt(loop, 150, 9000), Z, "spot", [(637977, note)],
        "3D a last trickle in the channel under the road (WATER OPTION: see the brief, the storyline says no water here).",
        volume_db=-8.0)
    loop, note = build_loop(mono(src(166324)), 46, 2.0)
    add("AMB_WaitingWater_SluiceDrip_Loop", cfilt(loop, 200, 12000), Z, "spot", [(166324, note)],
        "3D drips from the raised sluice gate onto metal (WATER OPTION).", volume_db=-10.0)
    events_to_pool(Z, "Drip", [(628404, 2)], "A single drip in the channel (WATER OPTION).", [6, 18], -12.0, "WaitingWater_Water",
                   lambda s, k: oneshot(verb(butter_filt(mono(s), 200, None), 0.7, 0.3, 60 + k), 0.002, 0.3), max_s=1.2, thr_db=-12)
    events_to_pool(Z, "WetStone", [(682165, 1), (544708, 1)], "A stone knocking in wet gravel (WATER OPTION).", [20, 50], -12.0,
                   "WaitingWater_Water", lambda s, k: oneshot(butter_filt(mono(s), 150, None), 0.003, 0.2), max_s=1.5, thr_db=-14)
    events_to_pool(Z, "Frog", [(744309, 1), (428536, 1)], "One frog, very sparse (WATER OPTION).", [90, 240], -14.0,
                   "WaitingWater_Water", lambda s, k: oneshot(distant(s, lp=6000, hp=150, rt60=0.9, wet=0.35, seed=70 + k), 0.005, 0.3),
                   max_s=2.0, thr_db=-16)
    events_to_pool(Z, "GateCreak", [(759692, 2)], "The raised sluice gate creaking in the wind (DRY-SAFE: default).", [25, 70], -10.0,
                   "WaitingWater_Dry", lambda s, k: oneshot(butter_filt(mono(s), 120, 9000), 0.02, 0.4), max_s=3.5, thr_db=-18)


def build_heron_pools():
    Z = "HeronPools"
    loop, note = build_loop(src(361915), 66, 3.0)
    add("AMB_HeronPools_Reeds_Loop", cfilt(loop, 100, 14000), Z, "bed", [(361915, note)],
        "Local stereo reed bed at the Numbered Stop (2D with a small radius, like ATT_2D_S).", volume_db=-6.0, lufs_target=-24.0)
    loop, note = build_loop(mono(src(457956)), 50, 3.0)
    add("AMB_HeronPools_Lapping_Loop", cfilt(loop, 120, 2500), Z, "spot", [(457956, note + ", low-passed 2.5 kHz: faint")],
        "3D faint water lapping in the last of the pools (WATER OPTION).", volume_db=-12.0)
    events_to_pool(Z, "Heron", [(65264, 2), (645157, 2)], "A single distant grey heron call now and then.", [70, 200], -10.0,
                   "HeronPools_Birds", lambda s, k: oneshot(distant(s, lp=5000, hp=200, rt60=2.0, wet=0.6, seed=80 + k), 0.01, 0.8),
                   max_s=3.0, thr_db=-18, gap_s=0.5)
    events_to_pool(Z, "Plop", [(682165, 2, dict(lo_s=3.0))], "Something small dropping into the water.", [25, 70], -14.0,
                   "HeronPools_Water", lambda s, k: oneshot(distant(s, lp=5000, hp=150, rt60=0.8, wet=0.3, seed=90 + k), 0.003, 0.25),
                   max_s=1.2, thr_db=-14)


def build_platform():
    Z = "Platform"
    loop, note = build_loop(mono(src(360633)), 80, 3.0)
    add("AMB_Platform_StructureWind_Loop", cfilt(loop, 80, 12000), Z, "spot", [(360633, note + " (rigging rattle and whistle)")],
        "3D wind through the platform's metal structure.", volume_db=-4.0)
    grains = [fade(s, 0.3, 1.0) for s, _, _ in peak_windows(mono(src(172411)), 6, 1.0, 3.0, 4.0)]
    n_out = int(64 * SR)
    tex = scatter_circular(n_out, grains, 101, 14, (-10, 0), stereo=False)
    tex = cfilt(tex, 60, 7000) + 0.25 * cfilt(build_loop(mono(src(360633)), 64, 3.0, floor_s=0)[0][:n_out], 80, 3000)
    add("AMB_Platform_MetalCreak_Loop", tex, Z, "spot", [(172411, "14 slow creak grains, circular 64 s"), (360633, "a -12 dB wind floor")],
        "3D slow metal creaks from the platform frame.", volume_db=-6.0)
    events_to_pool(Z, "SignClank", [(462582, 2), (759692, 1, dict(lo_s=4.0))], "A loose sign clanking in a gust.", [12, 40], -8.0,
                   "Platform_Metal", lambda s, k: oneshot(butter_filt(mono(s), 100, 12000), 0.003, 0.3), max_s=2.5, thr_db=-14)
    events_to_pool(Z, "MetalCreak", [(172408, 1), (508280, 1), (172411, 1)], "A single metal groan from the structure.", [15, 45], -8.0,
                   "Platform_Metal", lambda s, k: oneshot(verb(butter_filt(mono(s), 80, 8000), 1.2, 0.3, 110 + k), 0.02, 0.6),
                   max_s=3.5, thr_db=-16)


def build_cistern():
    Z = "Cistern"
    loop, note = build_loop(mono(src(454353)), 60, 3.0)
    add("AMB_Cistern_HollowWind_Loop", cfilt(loop, 50, 2500), Z, "spot", [(454353, note + ", low-passed 2.5 kHz")],
        "3D hollow, resonant wind in the cistern's mouth.", volume_db=-4.0)
    loop, note = build_loop(mono(src(628404)), 80, 3.0)
    add("AMB_Cistern_DarkDrip_Loop", cfilt(loop, 120, 10000), Z, "spot", [(628404, note)],
        "3D dripping in the dark at the bottom of the cistern.", volume_db=-10.0)
    events_to_pool(Z, "StoneEcho", [(734669, 2, dict(lo_s=0.0)), (863892, 1)], "A small stone falling and echoing in the cistern.",
                   [30, 90], -10.0, "Cistern_Stones",
                   lambda s, k: oneshot(verb(butter_filt(mono(s), 100, 7000), 2.6, 0.9, 120 + k, hi=4000), 0.003, 1.5),
                   max_s=1.5, thr_db=-14)
    events_to_pool(Z, "Drip", [(628404, 3, dict(lo_s=85.0))], "A drip in the dark.", [8, 25], -12.0, "Cistern_Drips",
                   lambda s, k: oneshot(verb(butter_filt(mono(s), 150, None), 1.8, 0.6, 130 + k, hi=5000), 0.002, 1.0),
                   max_s=1.0, thr_db=-12)


def build_waystation():
    Z = "Waystation"
    loop, note = build_loop(mono(src(546870)), 85, 3.0)
    add("AMB_Waystation_WindGaps_Loop", cfilt(loop, 60, 9000), Z, "spot", [(546870, note)],
        "3D wind through the gaps of the lean-to.", volume_db=-4.0)
    loop, note = build_loop(mono(src(641208)), 45, 3.0)
    add("AMB_Waystation_CradleHum_Loop", cfilt(loop, 40, 1800), Z, "spot", [(641208, note + ", 40 Hz-1.8 kHz")],
        "3D the faint electrical hum of the dead cradle (small radius; mains hum, not a drone).", volume_db=-14.0)
    events_to_pool(Z, "DoorCreak", [(455754, 1), (455753, 1), (840331, 1), (764798, 1)], "An old door creaking on its hinge.",
                   [25, 70], -8.0, "Waystation_Wood", lambda s, k: oneshot(butter_filt(mono(s), 80, 10000), 0.02, 0.4),
                   max_s=4.0, thr_db=-20, gap_s=0.4)
    events_to_pool(Z, "TarpFlap", [(451958, 2)], "The tarp roof snapping in a gust.", [15, 45], -8.0, "Waystation_Cloth",
                   lambda s, k: oneshot(butter_filt(mono(s), 90, 12000), 0.005, 0.3), max_s=1.5, thr_db=-8)


def build_climb():
    Z = "Climb"
    loop, note = build_loop(src(157193), 85, 3.0)
    loop = gust_swells(cfilt(loop, 180, 12000), 141, depth=0.4, band=(800, 6000), boost_db=5.0)
    add("AMB_Climb_HighWind_Loop", loop, Z, "bed", [(157193, note + ", high-passed 180 Hz: thin and cold")],
        "2D high cold wind on the Long Stair and the Knees.", volume_db=-2.0, lufs_target=-22.0)
    loop, note = build_loop(mono(src(434079)), 80, 3.0)
    add("AMB_Climb_BannerFlap_Loop", cfilt(loop, 90, 14000), Z, "spot",
        [(434079, note + " (a flag on the old fortress of Belluard)")], "3D torn banner cloth flapping (V7 flag, the Knees).",
        volume_db=-6.0)
    loop, note = build_loop(mono(src(454352)), 60, 3.0)
    add("AMB_Climb_StoneMoan_Loop", cfilt(loop, 50, 1800), Z, "spot", [(454352, note + ", low-passed 1.8 kHz")],
        "3D stone-wind moan in the rock cuts of the switchbacks.", volume_db=-8.0)
    events_to_pool(Z, "BannerSnap", [(572258, 3)], "A banner snapping hard in a gust.", [10, 30], -8.0, "Climb_Cloth",
                   lambda s, k: oneshot(butter_filt(mono(s), 90, 12000), 0.004, 0.3), max_s=1.2, thr_db=-6)
    events_to_pool(Z, "StoneFall", [(668605, 2, dict(lo_s=6.0)), (863892, 1, dict(lo_s=4.0))], "A few stones falling somewhere below.",
                   [40, 120], -10.0, "Climb_Stones",
                   lambda s, k: oneshot(distant(s, lp=3000, hp=100, rt60=2.0, wet=0.7, seed=150 + k), 0.01, 1.2),
                   max_s=2.5, thr_db=-16)


def build_cloud():
    Z = "Cloud"
    loop, note = build_loop(src(657001), 85, 3.0)
    loop = gust_swells(cfilt(loop, 40, 900, order=3), 161, depth=0.35, band=(200, 900), boost_db=4.0)
    add("AMB_Cloud_MuffledWind_Loop", loop, Z, "bed", [(657001, note + ", low-passed 900 Hz: muffled and close")],
        "2D inside the cloud: muffled, damp, close wind.", volume_db=-2.0, lufs_target=-22.0)
    loop, note = build_loop(src(446254), 70, 3.0)
    add("AMB_Cloud_Droplets_Loop", cfilt(loop, 200, 12000), Z, "bed", [(446254, note)],
        "2D droplets falling out of the cloud onto stone and the carrier.", volume_db=-8.0, lufs_target=-24.0)
    events_to_pool(Z, "Droplet", [(836411, 3)], "A single fat droplet close by.", [4, 14], -12.0, "Cloud_Drops",
                   lambda s, k: oneshot(butter_filt(mono(s), 300, None), 0.002, 0.1), max_s=0.5, thr_db=-8)
    whispers = peak_windows(src(657001), 3, 2.0, 3.0, 12.0)
    for k, (seg, a, b) in enumerate(whispers, 1):
        y = swell(butter_filt(mono(seg), 150, 1400), 0.45, 0.5)
        add(f"SFX_Cloud_Whisper_{k:02d}", y, Z, "oneshot", [(657001, f"{a:.1f}-{b:.1f} s, 150-1400 Hz swell")],
            "A close whispering breath of wind passing the carrier.", volume_db=-10.0, interval_s=[18, 45], pool="Cloud_Wind")


def build_above():
    Z = "Above"
    x = src(725630)
    # A different, quieter stretch of the breeze source, thinned to air (the payoff: calm).
    loop, note = build_loop(x, 80, 4.0, quiet=True, lo_s=60)
    loop = cfilt(loop, 350, 9000)
    add("AMB_Above_ThinAir_Loop", loop, Z, "bed", [(725630, note + ", 350 Hz-9 kHz: thin high air")],
        "2D above the clouds: near silence, thin air. Play low.", volume_db=-10.0, lufs_target=-24.0)
    for k, (seg, a, b) in enumerate(peak_windows(src(759918), 6, 5.0, 6.0, 12.0, lo_s=22, hi_s=152), 1):
        y = swell(butter_filt(seg, 60, 3500), 0.5, 0.5)
        add(f"SFX_Above_WideWind_{k:02d}", y, Z, "oneshot", [(759918, f"{a:.1f}-{b:.1f} s, low-passed 3.5 kHz, 11 s swell")],
            "2D an occasional wide, calm wind passing over the summit.", volume_db=-10.0, interval_s=[25, 60], pool="Above_Wind")
        ASSETS[-1]["audio"] = peak_norm(fade(ASSETS[-1]["audio"], 0.01, 0.01))


# --------------------------------------------------------------------------- 3. Geiger counter (real Eberline E-120)

GEIGER_RATES = [(1, 30.0), (5, 20.0), (20, 12.0), (80, 10.0)]


def build_geiger():
    Z = "Geiger"
    x = mono(src(555922))  # background clicks from an Eberline E-120, far apart
    x = butter_filt(x, 60, None)
    evs = find_events(x, 400, max_s=0.04, min_s=0.0005, thr_db=-22, tail_db=-45, gap_s=0.03, pre_s=0.002)
    peaks = np.array([np.abs(s).max() for s, _, _ in evs])
    order = np.argsort(-peaks)
    top = order[: max(16, int(len(order) * 0.6))]
    picks = sorted(top[np.linspace(0, len(top) - 1, 16).astype(int)])
    clicks = [fade(evs[i][0], 0.0005, 0.01) for i in picks]
    gain = 10 ** (ONESHOT_PEAK_DB / 20) / max(np.abs(c).max() for c in clicks)
    clicks = [c * gain for c in clicks]
    for k, (c, i) in enumerate(zip(clicks, picks), 1):
        _, a, b = evs[i]
        ASSETS.append(dict(name=f"SFX_Geiger_Click_{k:02d}", audio=c.astype(np.float32), zone=Z, type="oneshot", loop=False,
                           volume_db=-6.0, interval_s=None, pool="Geiger_Click",
                           use="One real Geiger click; the director fires these on a Poisson timer at the Dose rate (preferred).",
                           sources=[(555922, f"{a:.3f}-{b:.3f} s; set shares one gain (loudest -6 dBFS)")], extra={}))

    # The recording's own noise floor between clicks, looped, at its natural level under the clicks.
    m = x * gain
    e = env_db(m, 0.02)
    quiet = m[e < np.percentile(e, 40)]
    rng = np.random.default_rng(555)
    for rate, length in GEIGER_RATES:
        n = int(length * SR)
        buf = fs.make_loop(quiet[: n + SR], 1.0).astype(np.float32) * 0.6  # exactly n samples, seamless
        t, dead = 0.0, 0.0015
        times = []
        while True:
            t += rng.exponential(1.0 / rate)
            if t >= length:
                break
            if times and t - times[-1] < dead:
                continue
            times.append(t)
        for tt in times:
            c = clicks[rng.integers(len(clicks))] * 10 ** (rng.uniform(-2.5, 0) / 20)
            idx = (int(tt * SR) + np.arange(len(c))) % n
            np.add.at(buf, idx, c)
        ASSETS.append(dict(name=f"SFX_Geiger_Rate_{rate}_Loop", audio=np.clip(buf, -0.98, 0.98).astype(np.float32), zone=Z, type="spot",
                           loop=True, volume_db=-6.0, interval_s=None, pool=None,
                           use=f"Fallback loop at ~{rate} counts/s (Poisson, 1.5 ms dead time, circular so seamless). Same click level as the one-shots.",
                           sources=[(555922, f"{len(times)} real clicks on a circular {length:.0f} s timeline over the recording's own noise floor")],
                           extra={"rate_cps": rate}))

    # Device handling: a rotary switch on/off and the real dosimeter chirp (Pripyat).
    sw = find_events(src(512502), 2, max_s=0.5, thr_db=-20, gap_s=0.15)
    if len(sw) < 2:
        sw = [find_events(src(556633), 1, 0.5)[0], find_events(src(556634), 1, 0.5)[0]]
        sw_ids = (556633, 556634)
    else:
        sw_ids = (512502, 512502)
    for (seg, a, b), sid, name in zip(sw, sw_ids, ("SFX_Geiger_SwitchOn", "SFX_Geiger_SwitchOff")):
        y = oneshot(butter_filt(mono(seg), 150, None), 0.001, 0.05)
        add(name, y, Z, "oneshot", [(sid, f"{a:.2f}-{b:.2f} s")], "The counter's rotary switch (carrier boot / shutdown).",
            volume_db=-8.0, pool="Geiger_Device")
    for k, (seg, a, b) in enumerate(find_events(src(139039), 3, max_s=0.35, thr_db=-10, gap_s=0.08), 1):
        y = oneshot(butter_filt(mono(seg), 300, 12000), 0.003, 0.05)
        add(f"SFX_Geiger_AlarmChirp_{k:02d}", y, Z, "oneshot", [(139039, f"{a:.2f}-{b:.2f} s, a real dosimeter chirp")],
            "Subtle device chirp when Dose crosses a threshold upward (>= 6 cps), at most once per 20 s.",
            volume_db=-12.0, pool="Geiger_Device")


# --------------------------------------------------------------------------- manifest, credits, demo


def write_all():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for a in ASSETS:
        x = a["audio"]
        fs.write_wav(OUT / f"{a['name']}.wav", x)
        h0 = hit_for(a["sources"][0][0])
        notes = "; ".join(n for _, n in a["sources"][:1])
        fs.credit(a["name"], h0, notes=f"Ambience2 ({a['zone']}): {notes}")
        for sid, note in a["sources"][1:]:
            fs.credit(f"{a['name']}__{sid}", hit_for(sid), notes=f"Ambience2 layer in {a['name']}: {note}")
        loud = lufs(x) if len(x) > SR else None
        manifest.append(dict(
            file=f"{a['name']}.wav", asset=a["name"], ue_folder=UE_FOLDER, zone=a["zone"], type=a["type"], loop=a["loop"],
            channels=1 if x.ndim == 1 else x.shape[1], duration_s=round(len(x) / SR, 2),
            lufs=None if loud is None or not np.isfinite(loud) else round(float(loud), 1),
            peak_dbfs=round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 1),
            volume_db=a["volume_db"], volume=round(10 ** (a["volume_db"] / 20), 3),
            pool=a["pool"], interval_s=a["interval_s"], use=a["use"],
            sources=[dict(id=sid, author=hit_for(sid)["username"], licence=lic_short(hit_for(sid)), url=hit_for(sid)["url"], note=n)
                     for sid, n in a["sources"]],
            **a["extra"]))
    doc = dict(generator="Tools/Audio/make_ambience_v2.py", sample_rate=SR, bit_depth=16,
               loudness="beds -24..-20 LUFS integrated; spots -24 LUFS; one-shots peak -6 dBFS",
               brief=".superpowers/sdd/2026-09-26-saskarta-world-sprint/task-AMBIENCE2-brief.md",
               zones=ZONES, pools=pool_table(), placement=resolve_placement(), dose_cps=DOSE_CPS, files=manifest)
    (OUT / "manifest.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return manifest


def pool_table():
    pools = {}
    for a in ASSETS:
        if a["pool"]:
            p = pools.setdefault(a["pool"], dict(zone=a["zone"], files=[], interval_s=a["interval_s"], volume_db=a["volume_db"]))
            p["files"].append(a["name"])
    return pools


# Zones by road metre (look keys: Valley 0, Basin 2,300, Climb 3,800, InCloud 4,350, Above 4,550).
ZONES = [
    dict(zone="Valley", from_m=0, to_m=2020, xfade_m=150, beds=["AMB_Valley_DryGrass_Loop", "AMB_Valley_Insects_Loop"],
         pools=["Valley_Birds", "Valley_Insects", "Storm_BranchSnap", "Storm_StoneSkitter"], note="Includes the ridge (1,550-2,020): grass -4 dB, insects off after 1,700."),
    dict(zone="Basin", from_m=2020, to_m=2810, xfade_m=150, beds=[],
         pools=["Storm_TinRattle", "Storm_Rockfall", "Storm_StoneSkitter"], note="Storm beds carry it; spots: Heron Pools 2,480, Platform 2,560-2,620."),
    dict(zone="Foot", from_m=2810, to_m=3490, xfade_m=150, beds=[],
         pools=["Storm_Rockfall", "Storm_StoneSkitter"], note="Spots: Cistern 3,050, Waystation 3,400."),
    dict(zone="Climb", from_m=3490, to_m=4200, xfade_m=150, beds=["AMB_Climb_HighWind_Loop", "AMB_Storm_WhistleRocks_Loop"],
         pools=["Climb_Cloth", "Climb_Stones", "Storm_Rockfall"], note="The Long Stair and the Knees (B12 3,600, B13 4,015). No story radio."),
    dict(zone="Cloud", from_m=4200, to_m=4480, xfade_m=120, beds=["AMB_Cloud_MuffledWind_Loop", "AMB_Cloud_Droplets_Loop"],
         pools=["Cloud_Drops", "Cloud_Wind"], note="Look key InCloud 4,350."),
    dict(zone="Above", from_m=4480, to_m=5010, xfade_m=120, beds=["AMB_Above_ThinAir_Loop"],
         pools=["Above_Wind"], note="Look key Above 4,550: StormIntensity 0. The payoff: near silence."),
]

# Dose (Geiger counts/s) by road metre: the storyline's geiger_cps curve plus the site bumps asked for in AMBIENCE2.
DOSE_CPS = [[0, 0.5], [1550, 0.5], [1560, 0.6], [2150, 0.6], [2600, 10], [2810, 3], [2830, 2], [2990, 2], [3050, 4],
            [3110, 2], [3340, 1.5], [3400, 3], [3460, 1.2], [3490, 1], [3500, 0.8], [4200, 0.8], [4480, 0.3], [4700, 0.3],
            [4790, 4], [4990, 8], [5009.2, 8]]

# Spot emitters: label, asset, road m, lateral m (+ right of travel), height m, inner radius m, falloff m, volume dB, note
PLACEMENT = [
    ("A2_WW_Trickle", "AMB_WaitingWater_Trickle_Loop", 1220, -6, 0.5, 4, 40, -8, "WATER OPTION (off by default): dry channel under the road"),
    ("A2_WW_SluiceDrip", "AMB_WaitingWater_SluiceDrip_Loop", 1222, 4, 1.2, 3, 30, -10, "WATER OPTION: at the raised gate posts"),
    ("A2_WW_GateCreak", "SFX_WaitingWater_GateCreak_*", 1222, 4, 2.0, 5, 60, -10, "DRY-SAFE pool emitter at the gate posts (director timer)"),
    ("A2_HP_Reeds", "AMB_HeronPools_Reeds_Loop", 2470, -25, 1.0, 15, 80, -6, "Reeds by the Numbered Stop; stereo, non-spatialised inside 15 m"),
    ("A2_HP_Lapping", "AMB_HeronPools_Lapping_Loop", 2475, -30, 0.3, 6, 45, -12, "WATER OPTION: the last of the pools"),
    ("A2_PF_StructureWind", "AMB_Platform_StructureWind_Loop", 2600, 18, 3.0, 10, 70, -4, "Platform frame, right of the road"),
    ("A2_PF_MetalCreak", "AMB_Platform_MetalCreak_Loop", 2590, 20, 4.0, 6, 55, -6, "Platform canopy"),
    ("A2_PF_Ruins", "AMB_Storm_WhistleRuins_Loop", 2540, 10, 3.0, 6, 50, -6, "The broken arch at the Numbered Stop"),
    ("A2_CI_HollowWind", "AMB_Cistern_HollowWind_Loop", 3050, 15, -1.0, 5, 45, -4, "Cistern mouth, right 15 m"),
    ("A2_CI_DarkDrip", "AMB_Cistern_DarkDrip_Loop", 3052, 17, -3.0, 3, 30, -10, "Cistern bottom"),
    ("A2_WS_WindGaps", "AMB_Waystation_WindGaps_Loop", 3400, -10, 2.0, 5, 45, -4, "Lean-to walls, left at the bend"),
    ("A2_WS_CradleHum", "AMB_Waystation_CradleHum_Loop", 3400, -8, 0.8, 2, 18, -14, "The dead cradle"),
    ("A2_WS_Ruins", "AMB_Storm_WhistleRuins_Loop", 3405, -12, 2.5, 5, 40, -8, "Waystation gaps"),
    ("A2_CL_BannerV7", "AMB_Climb_BannerFlap_Loop", 3395, -6, 6.0, 6, 60, -6, "The V7 flag above the bend"),
    ("A2_CL_BannerKnees", "AMB_Climb_BannerFlap_Loop", 3600, 8, 4.0, 6, 55, -8, "A torn banner at the Knees (B12)"),
    ("A2_CL_StoneMoanA", "AMB_Climb_StoneMoan_Loop", 3750, 12, 3.0, 8, 70, -8, "Rock cut on the Long Stair"),
    ("A2_CL_StoneMoanB", "AMB_Climb_StoneMoan_Loop", 4015, -10, 3.0, 8, 70, -8, "Rock cut at the second fault (B13)"),
    ("A2_CL_Crest", "AMB_Climb_BannerFlap_Loop", 4150, 10, 5.0, 6, 55, -8, "The crest below the cloud (no fortress site exists in story-events.json; nearest crest)"),
]


def resolve_placement():
    import place_ambience as pa
    samples = pa.load_samples()
    out = []
    for label, asset, m, lat, h, r, fo, vol, note in PLACEMENT:
        x, y, z, yaw = pa.at_metre(samples, m)
        rad = math.radians(yaw)
        x += -math.sin(rad) * lat * 100.0
        y += math.cos(rad) * lat * 100.0
        out.append(dict(label=label, asset=asset, road_m=m, lateral_m=lat, x=round(x), y=round(y), z=round(z + h * 100),
                        inner_radius_m=r, falloff_m=fo, volume_db=vol, note=note))
    return out


def build_demo():
    """60 s drive: valley -> Waiting Water -> basin/platform -> gust + lightning -> climb -> cloud -> Above."""
    A = {a["name"]: a["audio"] for a in ASSETS}
    n = int(60 * SR)
    mix = np.zeros((n, 2), np.float32)

    def st(x):
        return x if x.ndim == 2 else np.stack([x, x], axis=1)

    def bed(name, t0, t1, db, fin=3.0, fout=3.0, offset_s=0.0):
        x = st(A[name])
        a, b = int(t0 * SR), int(t1 * SR)
        idx = (np.arange(b - a) + int(offset_s * SR)) % len(x)
        seg = x[idx] * 10 ** (db / 20)
        env = np.ones(b - a, np.float32)
        fi, fo = int(fin * SR), int(fout * SR)
        if fi:
            env[:fi] = np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
        if fo:
            env[-fo:] *= np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
        mix[a:b] += seg * env[:, None]

    def shot(name, t, db, pan=0.0):
        x = A[name]
        a = int(t * SR)
        if x.ndim == 1:
            lg, rg = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
            x = np.stack([x * lg, x * rg], axis=1) * math.sqrt(2)
        b = min(n, a + len(x))
        mix[a:b] += x[: b - a] * 10 ** (db / 20)

    def geiger(t0, t1, rate_fn, db=-16.0, seed=7, pan=-0.35):
        rng = np.random.default_rng(seed)
        t = t0
        while True:
            t += rng.exponential(1.0 / max(rate_fn(t), 0.05))
            if t >= t1:
                break
            shot(f"SFX_Geiger_Click_{rng.integers(1, 17):02d}", t, db + rng.uniform(-2.5, 0), pan)

    # Storm beds by "intensity" over time.
    bed("AMB_Storm_WindBreeze_Loop", 0, 14, -10, 0.5, 4)
    bed("AMB_Storm_WindStrong_Loop", 8, 30, -11, 4, 3, 10)
    bed("AMB_Storm_WindGale_Loop", 26, 40, -10, 3, 4, 20)
    bed("AMB_Storm_SandHiss_Loop", 22, 38, -16, 4, 4)
    bed("AMB_Storm_SandOnMetal_Loop", 27, 37, -18, 2, 3)
    # Valley.
    bed("AMB_Valley_DryGrass_Loop", 0, 18, -8, 0.5, 4)
    bed("AMB_Valley_Insects_Loop", 0, 12, -16, 0.5, 3, 12)
    shot("SFX_Valley_Crow_03", 4.5, -12, 0.6)
    shot("SFX_Valley_Crow_05", 7.8, -14, 0.55)
    # Waiting Water pass (water option, to judge).
    bed("AMB_WaitingWater_Trickle_Loop", 10, 18, -12, 3, 3)
    bed("AMB_WaitingWater_SluiceDrip_Loop", 11, 18, -14, 3, 3)
    shot("SFX_WaitingWater_GateCreak_01", 13.0, -12, 0.4)
    shot("SFX_WaitingWater_Frog_01", 15.2, -16, -0.5)
    # Heron Pools and the platform.
    bed("AMB_HeronPools_Reeds_Loop", 17, 24, -10, 2, 2)
    shot("SFX_HeronPools_Heron_01", 19.0, -12, -0.6)
    bed("AMB_Platform_StructureWind_Loop", 21, 30, -10, 2, 3)
    bed("AMB_Platform_MetalCreak_Loop", 22, 30, -12, 2, 3)
    shot("SFX_Platform_SignClank_01", 24.0, -10, 0.5)
    shot("SFX_Storm_TinRattle_01", 26.5, -12, -0.4)
    # Gust + lightning.
    shot("SFX_Storm_Gust_02", 28.0, -6)
    shot("SFX_Storm_SandSpray_02", 29.0, -10, 0.2)
    shot("SFX_Storm_ThunderClose_01", 31.0, -6)
    shot("SFX_Storm_Gust_05", 33.5, -7)
    shot("SFX_Storm_ThunderDistant_02", 35.0, -8)
    shot("SFX_Storm_RockfallDistant_01", 36.0, -14, -0.6)
    # Climb.
    bed("AMB_Climb_HighWind_Loop", 36, 47, -9, 3, 3)
    bed("AMB_Storm_WhistleRocks_Loop", 37, 46, -16, 3, 3)
    bed("AMB_Climb_BannerFlap_Loop", 38, 44, -12, 2, 2)
    shot("SFX_Climb_BannerSnap_01", 40.5, -12, 0.4)
    shot("SFX_Climb_StoneFall_02", 42.5, -14, -0.5)
    # Cloud.
    bed("AMB_Cloud_MuffledWind_Loop", 44, 54, -9, 3, 3)
    bed("AMB_Cloud_Droplets_Loop", 45, 54, -14, 2, 3)
    shot("SFX_Cloud_Droplet_01", 47.0, -16, 0.3)
    shot("SFX_Cloud_Whisper_02", 48.5, -12)
    shot("SFX_Cloud_Droplet_03", 50.2, -16, -0.3)
    # Above.
    bed("AMB_Above_ThinAir_Loop", 51, 60, -16, 4, 3)
    shot("SFX_Above_WideWind_03", 53.0, -14)

    # Geiger: the carrier's counter follows Dose; spikes in the gust/dust wall; near silence Above.
    def rate(t):
        if t < 10:
            return 0.5
        if t < 20:
            return 0.7
        if t < 28:
            return 0.7 + (t - 20) / 8 * 9.3
        if t < 36:
            return 25.0 if 28 <= t < 34 else 10.0
        if t < 44:
            return 1.0
        if t < 52:
            return 0.8
        return 0.2
    shot("SFX_Geiger_SwitchOn", 0.6, -14, -0.35)
    geiger(1.0, 59.0, rate)
    shot("SFX_Geiger_AlarmChirp_01", 26.0, -16, -0.35)

    mix = cfilt(mix, 20, None)
    mix = fade(mix, 0.3, 3.0)
    mix = lufs_norm(mix, -20.0)
    fs.write_wav(OUT / "_demo_road.wav", mix)
    return lufs(mix), 20 * np.log10(np.abs(mix).max())


def measure():
    doc = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    by_zone = {}
    for e in doc["files"]:
        x, _ = soundfile.read(str(OUT / e["file"]), dtype="float32")
        seam = ""
        if e["loop"]:
            k = int(0.05 * SR)
            m = mono(x)
            a, b = fs.rms_db(m[-k:]), fs.rms_db(m[:k])
            seam = f" seam {abs(a - b):.2f} dB"
        lf = lufs(x) if len(x) > SR else float("nan")
        print(f"{e['asset']:40s} {e['type']:7s} ch{e['channels']} {len(x) / SR:6.1f}s  {lf:6.1f} LUFS  peak {20 * np.log10(np.abs(x).max()):6.1f}{seam}")
        by_zone.setdefault(e["zone"], {}).setdefault(e["type"], 0)
        by_zone[e["zone"]][e["type"]] += 1
    print()
    for z, t in by_zone.items():
        print(f"{z:14s} " + ", ".join(f"{v} {k}" for k, v in t.items()))
    print(f"{len(doc['files'])} files")


def print_md():
    for p in resolve_placement():
        print(f"| `{p['label']}` | `{p['asset']}` | {p['road_m']} m, {p['lateral_m']:+d} m | ({p['x']}, {p['y']}, {p['z']}) | "
              f"{p['inner_radius_m']} m + {p['falloff_m']} m | {p['volume_db']} dB | {p['note']} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()
    if args.measure:
        return measure()
    if args.md:
        return print_md()
    for build in (build_storm, build_valley, build_waiting_water, build_heron_pools, build_platform, build_cistern,
                  build_waystation, build_climb, build_cloud, build_above, build_geiger):
        before = len(ASSETS)
        build()
        print(f"{build.__name__}: {len(ASSETS) - before} files")
    write_all()
    demo_lufs, demo_peak = build_demo()
    print(f"demo: {demo_lufs:.1f} LUFS, peak {demo_peak:.1f} dBFS -> {OUT / '_demo_road.wav'}")
    measure()


if __name__ == "__main__":
    main()
