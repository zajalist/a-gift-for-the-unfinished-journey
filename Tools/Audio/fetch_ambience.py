#!/usr/bin/env python3
"""Moody ambience for Saskarta from Freesound CC0 recordings (replaces the synthesised beds).

Offline only; never touches Unreal. Every pick below is a pinned Freesound id with three
ranked alternates, so a bad pick is a one-line swap: move an alternate id into `id`.

    python Tools/Audio/fetch_ambience.py              # fetch, measure, process, write all
    python Tools/Audio/fetch_ambience.py --audition   # measure every pick AND its alternates, write nothing
    python Tools/Audio/fetch_ambience.py --only AMB_Cloud_Wind SFX_Raven_Distant

Output: Saved/GameAudio/Recorded/Ambience/<Asset>.wav plus manifest.json, and a
credit entry per asset in Tools/Audio/freesound_credits.json / CREDITS.md (via
freesound_fetch.credit). Import target in Unreal: /Game/SaskartaGaea/Audio/Ambience.
Replacements keep the synthesised asset names exactly, so the import overwrites in place.

NO MUSIC. Every source is wind, water, rain, thunder, reeds, insects, birds, stone or
metal. Processing is filtering, resampling (pitch-down for size and distance) and a
synthetic exponential-noise room tail; nothing tonal is added.

Formats (see the task rules in Tools/Audio/AMBIENCE_MIX.md)
  beds       stereo, 60-120 s, peak -14 dBFS, seamless (fs.make_loop, 2 s crossfade)
  spot loops stereo, 20-40 s,  peak -12 dBFS, seamless (fs.make_loop, 1.5 s crossfade)
  one-shots  mono (stereo where width matters), trimmed, 5 ms fades, peak -3 dBFS

Measurements printed per file (numpy): RMS dBFS, peak dBFS, spectral flatness (0 = tonal,
1 = white), clipped-sample count in the source, mains-hum prominence (largest peak at
50/60 Hz and harmonics over the median of +/-10 Hz, dB), sustained-tone windows above
150 Hz (as in make_ambience.py: >12 dB over the local median), and the seam RMS gap.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from scipy import signal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

SR = fs.SR
OUT = fs.ROOT / "Saved" / "GameAudio" / "Recorded" / "Ambience"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Ambience"
META_CACHE = fs.CACHE / "meta.json"
RNG = np.random.default_rng(7)

# --------------------------------------------------------------------------- DSP helpers


def mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def stereo(x):
    return np.stack([x, x], axis=1) if x.ndim == 1 else x


def sos_filter(x, kind, freq, order=4):
    sos = signal.butter(order, freq, btype=kind, fs=SR, output="sos")
    return signal.sosfiltfilt(sos, x, axis=0).astype(np.float32)


def hp(x, f, order=4):
    return sos_filter(x, "highpass", f, order)


def lp(x, f, order=4):
    return sos_filter(x, "lowpass", f, order)


def pitch(x, ratio):
    """Resample so the result plays `ratio` times the original pitch (0.7 = slower, lower, bigger)."""
    from fractions import Fraction
    fr = Fraction(ratio).limit_denominator(40)
    return signal.resample_poly(x, fr.denominator, fr.numerator, axis=0).astype(np.float32)


def room_tail(x, rt60=2.5, wet=0.35, damp_hz=2500.0, seed=1):
    """Convolve with a decaying-noise impulse (no tone), low-passed so the tail darkens with distance."""
    rng = np.random.default_rng(seed)
    n = int(rt60 * SR)
    t = np.arange(n) / SR
    chans = x.shape[1] if x.ndim == 2 else 1
    ir = rng.standard_normal((n, chans)).astype(np.float32) * np.exp(-6.9 * t / rt60)[:, None].astype(np.float32)
    ir = lp(ir, damp_hz, 2)
    ir /= np.sqrt(np.sum(ir ** 2, axis=0, keepdims=True)) + 1e-12
    xx = x if x.ndim == 2 else x[:, None]
    pad = np.concatenate([xx, np.zeros((n, xx.shape[1]), np.float32)])
    w = np.stack([signal.fftconvolve(pad[:, c], ir[:, c], mode="full")[: len(pad)] for c in range(xx.shape[1])], axis=1)
    dry_rms, wet_rms = np.sqrt(np.mean(pad ** 2)) + 1e-12, np.sqrt(np.mean(w ** 2)) + 1e-12
    out = (1 - wet) * pad + wet * w * (dry_rms / wet_rms)
    return out if x.ndim == 2 else out[:, 0]


def env_db(x, win_s=0.05):
    m = mono(x)
    n = int(win_s * SR)
    k = len(m) // n
    return 20 * np.log10(np.sqrt(np.mean(np.square(m[: k * n].reshape(k, n)), axis=1)) + 1e-9)


def pseudo_stereo(m, offset_s=17.0):
    """Mono bed -> decorrelated stereo: R is the same recording offset in time (no wrap, so no splice)."""
    k = min(int(offset_s * SR), len(m) // 4)
    return np.stack([m[:-k], m[k:]], axis=1)


# --------------------------------------------------------------------------- measurement


def hum_db(x):
    m = mono(x)
    f, p = signal.welch(m, SR, nperseg=min(len(m), SR * 2))
    best = 0.0
    for f0 in (50.0, 60.0):
        for h in (1, 2, 3):
            fc = f0 * h
            band = (f > fc - 10) & (f < fc + 10)
            at = (f > fc - 1.0) & (f < fc + 1.0)
            if band.any() and at.any():
                best = max(best, 10 * np.log10(p[at].max() / (np.median(p[band]) + 1e-20)))
    return best


def tonal_windows(x, limit_db=12.0):
    """Count 1 s windows whose strongest sustained peak above 150 Hz stands > limit over its +/-200 Hz median."""
    m = mono(x)
    hits, total, worst = 0, 0, 0.0
    for s in range(0, len(m) - SR, SR):
        seg = m[s: s + SR]
        if np.sqrt(np.mean(seg ** 2)) < 1e-5:
            continue
        f, t, z = signal.stft(seg, SR, nperseg=8192, noverlap=6144)
        spec = np.median(np.abs(z) ** 2, axis=1)
        sel = (f > 150) & (f < 8000)
        i = np.argmax(np.where(sel, spec, 0))
        nb = (f > f[i] - 200) & (f < f[i] + 200)
        ratio = 10 * np.log10(spec[i] / (np.median(spec[nb]) + 1e-20))
        worst = max(worst, ratio)
        hits += ratio > limit_db
        total += 1
    return hits, total, worst


def flatness(x):
    m = mono(x)
    f, p = signal.welch(m, SR, nperseg=4096)
    sel = (f > 40) & (f < 16000)
    p = p[sel] + 1e-20
    return float(np.exp(np.mean(np.log(p))) / np.mean(p))


def measure(x, label=""):
    peak = 20 * np.log10(np.max(np.abs(x)) + 1e-12)
    clip = int(np.sum(np.abs(x) > 0.999))
    th, tt, tw = tonal_windows(x)
    e = env_db(x, 1.0)
    return {
        "label": label, "dur_s": round(len(x) / SR, 1), "rms_db": round(float(fs.rms_db(x)), 1), "peak_db": round(float(peak), 1),
        "flatness": round(flatness(x), 3), "clipped": clip, "hum_db": round(float(hum_db(x)), 1),
        "tonal": f"{th}/{tt} (max {tw:.1f} dB)", "dyn_db": round(float(np.percentile(e, 95) - np.percentile(e, 10)), 1),
    }


def fmt(m):
    return (f"{m['label']:<34} {m['dur_s']:6.1f}s rms {m['rms_db']:6.1f} pk {m['peak_db']:5.1f} flat {m['flatness']:.3f} "
            f"clip {m['clipped']:<4} hum {m['hum_db']:4.1f} dB tonal {m['tonal']:<18} dyn {m['dyn_db']:4.1f} dB")


# --------------------------------------------------------------------------- segment choice


def best_loop_window(x, length_s, xfade_s, step_s=2.0, skip_s=2.0):
    """Choose the source window whose head and tail match in level and spectrum and that has no clipping."""
    n = int((length_s + xfade_s) * SR)
    if len(x) <= n + 2 * int(skip_s * SR):
        return 0 if len(x) <= n else (len(x) - n) // 2
    e = env_db(x, 0.5)
    best, best_s = None, 0
    for s in range(int(skip_s * SR), len(x) - n - int(skip_s * SR), int(step_s * SR)):
        a, b = s // (SR // 2), (s + n) // (SR // 2)
        seg_e = e[a:b]
        head, tail = seg_e[: int(2 * xfade_s)], seg_e[-int(2 * xfade_s):]
        score = abs(np.mean(head) - np.mean(tail)) + 0.15 * np.std(seg_e)
        if np.any(np.abs(x[s: s + n]) > 0.999):
            score += 20
        if best is None or score < best:
            best, best_s = score, s
    return best_s


def events(x, count, min_gap_s, win=0.25):
    """Loudest `count` peaks of the smoothed envelope, at least min_gap_s apart (sample indices)."""
    e = env_db(x, win)
    order = np.argsort(e)[::-1]
    picked = []
    for i in order:
        if all(abs(i - j) * win >= min_gap_s for j in picked):
            picked.append(i)
        if len(picked) == count:
            break
    return sorted(int(i * win * SR) for i in picked)


def cut(x, centre, pre_s, post_s):
    a = max(0, centre - int(pre_s * SR))
    return x[a: centre + int(post_s * SR)]


# --------------------------------------------------------------------------- per-asset builders


def bed(length_s, xfade_s=2.0, peak=-14.0, pre=None, post=None, mono_src_stereo=False):
    """Loop builder: choose a window, optional pre-processing, seamless loop, normalise."""
    def build(src, hit):
        x = pre(src) if pre else src
        if mono_src_stereo or (x.ndim == 2 and np.corrcoef(x[:, 0], x[:, 1])[0, 1] > 0.995):
            x = pseudo_stereo(mono(x))
        s = best_loop_window(x, length_s, xfade_s)
        seg = x[s: s + int((length_s + xfade_s) * SR)]
        seg = post(seg) if post else seg
        seg = hp(seg, 20, 2)  # filter BEFORE looping: filtfilt edge effects after make_loop would break the wrap
        loop = fs.make_loop(seg, xfade_s)
        return [fs.normalize(loop, peak)], f"source {s / SR:.1f}-{(s + len(seg)) / SR:.1f} s"
    return build


def oneshots(count, pre_s, post_s, min_gap_s, proc=None, keep_stereo=False, trim_db=-42.0, fade_in=0.005, fade_out=0.005, region=None):
    """region=(start_s, end_s) limits the event search, e.g. to keep a gust out of a bed cut from the same recording."""
    def build(src, hit):
        x = src if keep_stereo else mono(src)
        off = 0
        if region:
            off = int(region[0] * SR)
            x = x[off: int(region[1] * SR)]
        outs, where = [], []
        for c in events(x, count, min_gap_s):
            seg = cut(x, c, pre_s, post_s)
            seg = proc(seg) if proc else seg
            seg = fs.trim_silence(seg, trim_db)
            seg = fs.fade(hp(seg, 25, 2), fade_in, fade_out)
            outs.append(fs.normalize(seg, -3.0))
            where.append(f"{(c + off) / SR:.1f} s")
        return outs, "events at " + ", ".join(where)
    return build


def distant_bird(seg):
    seg = hp(seg, 300, 2)
    seg = lp(seg, 3200, 2)
    return room_tail(seg, rt60=1.8, wet=0.4, damp_hz=2200, seed=11)


def distant_groan(ratio):
    def proc(seg):
        seg = pitch(seg, ratio)
        seg = lp(seg, 1800, 2)
        return room_tail(seg, rt60=3.5, wet=0.5, damp_hz=1500, seed=23)
    return proc


def reed_marsh(src_reeds, src_insects):
    reeds = hp(src_reeds, 120, 2)
    ins = hp(stereo(src_insects), 1500, 2)
    n = min(len(reeds), len(ins))
    ins = ins[:n] * (10 ** (-14 / 20)) * (np.sqrt(np.mean(reeds[:n] ** 2)) / (np.sqrt(np.mean(ins[:n] ** 2)) + 1e-12))
    return reeds[:n] + ins


# --------------------------------------------------------------------------- picks
# id: the pick; alts: next best three (ranked). Every id here is CC0 (checked at run time).

PICKS = [
    # ---- replacements of the synthesised beds (names kept exactly)
    dict(asset="AMB_Valley_Wind", id=202961, alts=[454362, 217506, 215853], replaces=True, loop=True,
         build=bed(95, pre=lambda x: lp(hp(x, 30, 2), 11000, 2)),
         use="2D base bed, road 0-2,810 m: strong, gusty wind over an open field and bushes (New Mexico plains), dark and wide."),
    dict(asset="AMB_Valley_Life", id=796193, alts=[574397, 492178, 81791], replaces=True, loop=True,
         build=bed(110),
         use="2D layer over Valley_Wind in the lowlands (0-1,700 m): soft desert-countryside wind, a few far birds and insects, long gaps."),
    dict(asset="AMB_Settlement_Creaks", id=830460, alts=[147863, 870882, 554651], replaces=True, loop=True,
         build=bed(80),
         use="Spatial at the Numbered Stop (V5, 2,540-2,620 m): wind with intermittent low knocks and creaks of loose wooden panels."),
    dict(asset="AMB_Infrastructure", id=810139, alts=[177958, 516566, 870748], replaces=True, loop=True,
         build=bed(90),
         use="Spatial in the works by the platform (2,540-2,620 m) and the dry cistern (3,050 m, -6 dB): an abandoned plant, drips, air, distant settling."),
    dict(asset="AMB_Cloud_Wind", id=473815, alts=[144153, 861757, 574558], replaces=True, loop=True,
         build=bed(90, pre=lambda x: lp(hp(x, 30, 2), 750, 4)),
         use="2D, the cloud layer on the Climb (3,540-4,250 m): wind in a mountain snow storm, low-passed to 750 Hz so it is dense, damp and muffled."),
    dict(asset="AMB_Summit_Wind", id=454092, alts=[725630, 160469, 779944], replaces=True, loop=True,
         build=bed(90, pre=lambda x: hp(x, 160, 2)),
         use="2D, above the cloud to the road end (4,250-5,009 m): Alpine wind with heavy gusts, high-passed at 160 Hz so it reads thin, high and cold."),
    # ---- new beds and spot loops
    dict(asset="AMB_Mountain_Rumble", id=438856, alts=[861757, 852881, 574558], replaces=False, loop=True,
         build=bed(100, pre=lambda x: lp(pitch(x, 0.75), 260, 4)),
         use="2D sub-low layer from the Mountain Foot to the cloud (2,810-4,250 m), and under the Ridge: distant wind rumble pitched down 0.75x and low-passed at 260 Hz, the mountain breathing."),
    dict(asset="AMB_Ruins_Wind_Moan", id=567356, alts=[265538, 202518, 438866], replaces=False, loop=True,
         build=bed(34, xfade_s=1.5, peak=-12.0, pre=lambda x: lp(x, 6000, 2)),
         use="Spatial spot loop at broken structures (V5 gutted buildings, the works, the cistern walls, the hut): cold gusty wind moaning and whistling through a gap in an opening."),
    dict(asset="AMB_Reed_Marsh", id=559483, alts=[844604, 513736, 250815], secondary=(235907, [235906, 361915]), replaces=False, loop=True,
         build=None,  # built in build_reed_marsh: reeds plus a sparse insect layer 14 dB under
         use="Spatial spot loop at the Waiting Water channel (1,220 m) along the PCG reeds: reeds clattering in wind with a faint night-insect layer. No water in it (storyline rule)."),
    dict(asset="AMB_Cloud_Drizzle", id=200273, alts=[200271, 523391, 584268], replaces=False, loop=True,
         build=bed(80, mono_src_stereo=True, pre=lambda x: lp(hp(x, 200, 2), 7000, 2)),
         use="2D layer inside the cloud (3,540-4,250 m) under Cloud_Wind: fine light rain on open rural ground, made stereo by time offset."),
    dict(asset="AMB_Thunder_Far_Loop", id=717890, alts=[717845, 361401, 572443], replaces=False, loop=True,
         build=bed(110, pre=lambda x: lp(x, 1400, 4)),
         use="2D, sparse, very distant dry rolling thunder: Basin, Mountain Foot and the Shoulder, low in the mix."),
    # ---- one-shots
    dict(asset="SFX_Thunder_Distant", count=3, id=717845, alts=[717890, 572443, 361401], replaces=False, loop=False,
         build=oneshots(3, 2.0, 11.0, 15.0, proc=lambda s: lp(s, 1600, 4), keep_stereo=True, trim_db=-40, fade_in=0.05, fade_out=0.5),
         use="Very distant dry thunder rolls; random 60-180 s timers over the Basin to the Shoulder. Stereo kept for the roll's width."),
    dict(asset="SFX_Raven_Distant_01", id=849152, alts=[758707, 651186, 723570], replaces=False, loop=False,
         build=oneshots(1, 0.3, 1.6, 2.0, proc=distant_bird),
         use="Distant raven, replaces SFX_Crow_Distant_*: Valley and Ridge, spatialised 150-400 m off the road on 40-120 s timers."),
    dict(asset="SFX_Raven_Distant_02", id=758707, alts=[651186, 723570, 849152], replaces=False, loop=False,
         build=oneshots(1, 0.3, 1.6, 2.0, proc=distant_bird),
         use="Distant raven, variation 2."),
    dict(asset="SFX_Raven_Distant_03", id=651186, alts=[723570, 849152, 758707], replaces=False, loop=False,
         build=oneshots(1, 0.3, 1.6, 2.0, proc=distant_bird),
         use="Distant raven, variation 3."),
    dict(asset="SFX_Metal_Groan_Distant_01", id=172411, alts=[496836, 556714, 453333], replaces=False, loop=False,
         build=oneshots(1, 1.5, 5.0, 2.0, proc=distant_groan(0.8), fade_in=0.05, fade_out=0.3),
         use="A large structure groaning far off; the works (2,540-2,620 m) and the mast (4,790-5,009 m), 60-200 s timers, spatialised 80-300 m away."),
    dict(asset="SFX_Metal_Groan_Distant_02", id=496836, alts=[556714, 453333, 172411], replaces=False, loop=False,
         build=oneshots(1, 1.0, 5.0, 2.0, proc=distant_groan(0.6), fade_in=0.05, fade_out=0.3),
         use="Large structure groan, variation 2 (heavy bunker door hinge pitched down 0.6x)."),
    dict(asset="SFX_Metal_Groan_Distant_03", id=556714, alts=[453333, 172411, 496836], replaces=False, loop=False,
         build=oneshots(1, 1.0, 4.0, 2.0, proc=distant_groan(0.55), fade_in=0.05, fade_out=0.3),
         use="Large structure groan, variation 3 (bending steel pitched down 0.55x)."),
    dict(asset="SFX_Wind_Gust_Heavy", id=202961, alts=[454092, 81794, 577339], replaces=True, loop=False,
         build=oneshots(1, 3.0, 3.0, 5.0, keep_stereo=True, trim_db=-30, fade_in=0.8, fade_out=1.2, region=(131, 180)),  # AMB_Valley_Wind uses 32-129 s
         use="One heavy gust (the strongest in the valley-wind field recording, stereo); Ridge crest, Shoulder, random 20-90 s timers."),
    dict(asset="SFX_Rockfall_Distant", id=500638, alts=[389303, 655368, 668606], replaces=True, loop=False,
         build=oneshots(1, 1.0, 9.0, 2.0, proc=lambda s: room_tail(lp(s, 5000, 2), rt60=2.2, wet=0.3, damp_hz=2000, seed=5), fade_in=0.01, fade_out=0.4),
         use="A real rock slide on a mountain face, distant; Basin walls and Mountain Foot slopes, 300-600 m off the road."),
]


# --------------------------------------------------------------------------- metadata (one API call for every id)


def metadata(ids):
    cache = json.loads(META_CACHE.read_text(encoding="utf-8")) if META_CACHE.exists() else {}
    need = sorted({i for i in ids if str(i) not in cache})
    for k in range(0, len(need), 100):
        chunk = need[k: k + 100]
        data = fs._get("/search/text/", {"query": "", "filter": "id:(" + " OR ".join(map(str, chunk)) + ")",
                                         "fields": fs.FIELDS, "page_size": 150})
        for h in data["results"]:
            cache[str(h["id"])] = h
    META_CACHE.parent.mkdir(parents=True, exist_ok=True)
    META_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    missing = [i for i in ids if str(i) not in cache]
    if missing:
        raise SystemExit(f"no metadata for {missing}")
    return {int(k): v for k, v in cache.items()}


def check_licence(h):
    if "publicdomain/zero" not in h["license"]:
        raise SystemExit(f"{h['id']} {h['name']!r} is not CC0 ({h['license']}); credit it as CC-BY or swap it")
    bad = set(t.lower() for t in h["tags"]) & fs.BANNED_TAGS
    if bad:
        raise SystemExit(f"{h['id']} {h['name']!r} has banned tags {bad}")


def names_for(p):
    if p.get("count"):
        return [f"{p['asset']}_{i + 1:02d}" for i in range(p["count"])]
    return [p["asset"]]


def build_reed_marsh(p, meta):
    reeds = fs.fetch(meta[p["id"]])
    ins = fs.fetch(meta[p["secondary"][0]])
    mix = reed_marsh(reeds, ins)
    return bed(34, xfade_s=1.5, peak=-12.0)(mix, None)


def run(only=None, audition=False):
    ids = [p["id"] for p in PICKS] + [a for p in PICKS for a in p["alts"]]
    ids += [p["secondary"][0] for p in PICKS if "secondary" in p] + [a for p in PICKS if "secondary" in p for a in p["secondary"][1]]
    meta = metadata(ids)
    manifest_path = OUT / "manifest.json"
    manifest = {e["asset"]: e for e in json.loads(manifest_path.read_text(encoding="utf-8"))} if manifest_path.exists() else {}
    for p in PICKS:
        if only and p["asset"] not in only and not any(n in only for n in names_for(p)):
            continue
        h = meta[p["id"]]
        check_licence(h)
        print(f"\n== {p['asset']}  <- {h['id']} {h['name'][:60]!r} ({h['username']})")
        src = fs.fetch(h)
        print("   src  " + fmt(measure(src, str(h["id"]))))
        if audition:
            for a in p["alts"]:
                try:
                    print("   alt  " + fmt(measure(fs.fetch(meta[a]), f"{a} {meta[a]['name'][:22]}")))
                except Exception as exc:  # a dead preview must not stop the audition
                    print(f"   alt  {a} failed: {exc}")
            continue
        outs, where = build_reed_marsh(p, meta) if p["asset"] == "AMB_Reed_Marsh" else p["build"](src, h)
        for name, x in zip(names_for(p), outs):
            path = OUT / f"{name}.wav"
            fs.write_wav(path, x)
            m = measure(x, name)
            line = fmt(m)
            if p["loop"]:
                seam = abs(fs.rms_db(x[-2400:]) - fs.rms_db(x[:2400]))
                line += f" seam {seam:.2f} dB"
            print("   out  " + line)
            notes = (f"{where}; out {m['dur_s']} s, rms {m['rms_db']} dBFS, flatness {m['flatness']}, hum {m['hum_db']} dB, tonal {m['tonal']}")
            if "secondary" in p:
                sec = meta[p["secondary"][0]]
                notes += f"; insect layer -14 dB from freesound {sec['id']} '{sec['name']}' by {sec['username']} (CC0)"
            fs.credit(name, h, alternates=[meta[a] for a in p["alts"]], notes=notes)
            manifest[name] = {"asset": name, "file": f"{name}.wav", "ue_folder": UE_FOLDER, "loop": p["loop"],
                              "replaces_synth": p["replaces"], "freesound_id": h["id"], "use": p["use"]}
        if "secondary" in p:
            sec = meta[p["secondary"][0]]
            check_licence(sec)
            fs.credit(p["asset"] + "__insects", sec, alternates=[meta[a] for a in p["secondary"][1]],
                      notes=f"insect layer mixed -14 dB under the reeds in {p['asset']}")
    if not audition:
        order = [n for p in PICKS for n in names_for(p)]
        rows = [manifest[n] for n in order if n in manifest] + [v for k, v in manifest.items() if k not in order]
        OUT.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {len(rows)} manifest rows to {manifest_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--audition", action="store_true", help="measure picks and alternates, write nothing")
    ap.add_argument("--only", nargs="*", help="asset names (or one-shot family names) to build")
    args = ap.parse_args()
    run(set(args.only) if args.only else None, args.audition)
