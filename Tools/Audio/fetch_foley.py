"""Recorded foley for Saskarta: replaces or layers the weakest synthesized foley with CC0 Freesound recordings.

Writes 48 kHz 16-bit WAVs to Saved/GameAudio/Recorded/Foley/ plus manifest.json. Every asset name matches the
synthesized asset it supersedes (Saved/GameAudio/Foley/, made by make_foley_sfx.py), so re-importing into
/Game/SaskartaGaea/Audio/Foley overwrites the SoundWave in place and keeps every reference.

    python Tools/Audio/fetch_foley.py            # fetch (cached), process, write WAVs + manifest, credit, print metrics
    python Tools/Audio/fetch_foley.py --measure  # only print metrics of the files already written

REPLACED (recording only)
    SFX_Cloth_Rustle_01..03            jacket movement gestures, mono one-shots
    SFX_Capsule_Tow_Gravel_Loop        30 s stereo loop, heavy case dragged/rolled on a gravel road
    SFX_Capsule_Tow_Dirt_Loop          30 s stereo loop, stone slab dragged over park dirt, pulls chained
    SFX_WalkingAid_Tap_Gravel_01..04   cane tip on a gravel path, mono one-shots
    SFX_WalkingAid_Tap_Stone_01..04    cane tip on asphalt (hard stone-like surface), mono one-shots
LAYERED (recording + the existing synth file, same length, peak -3 dBFS)
    SFX_Carrier_Collapse               + falling metal/stone debris crash, main hit on the 0.50 s body slam
    SFX_Capsule_Scrape_Failing         + kettlebell dragged on concrete/stone, shaped by the synth envelope
    SFX_Capsule_Hatch_Open             + heavy bunker-door hinge groan, 0.40-1.50 s, before the 1.55 s stop

Swapping a bad pick: change the id in PICKS (the alternates are logged in freesound_credits.json) and rerun.
"""
import json
import pathlib
import sys

import numpy as np
import soundfile
from scipy.ndimage import binary_closing, find_objects, label
from scipy.signal import butter, find_peaks, iirnotch, sosfiltfilt, filtfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

ROOT = fs.ROOT
OUT = ROOT / "Saved" / "GameAudio" / "Recorded" / "Foley"
SYNTH = ROOT / "Saved" / "GameAudio" / "Foley"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Foley"
SR = fs.SR
RNG = np.random.default_rng(7)

# group -> query that finds it, chosen Freesound id, next-best alternates (ids, all CC0).
PICKS = {
    "cloth": dict(query=("jacket movement", 0.3, 30), id=555307, alt=[19291, 128233, 641383]),
    "tow_gravel": dict(query=("dragging gravel", 5, 120), id=766006, alt=[764617, 268909, 543701]),
    "tow_dirt": dict(query=("dragging heavy", 5, 180), id=738784, alt=[813533, 380699, 392008]),
    "tap_gravel": dict(query=("white cane", 0.2, 90), id=715321, alt=[769994, 739192, 157887]),
    "tap_stone": dict(query=("white cane", 0.2, 90), id=157887, alt=[739192, 769994, 715321]),
    "collapse": dict(query=("metal debris crash heavy", 0.5, 15), id=703247, alt=[675461, 675462, 703248]),
    "scrape": dict(query=("metal scrape concrete", 1, 30), id=545544, alt=[164673, 383794, 488901]),
    "hinge": dict(query=("rusty hinge", 0.5, 20), id=496836, alt=[81268, 483163, 426320]),
}

_search_cache = {}
_hit_cache = {}


def hit_for(sound_id, query=None):
    """Metadata for one sound: taken from a (cached) search when possible, else one /sounds/<id>/ call."""
    if sound_id in _hit_cache:
        return _hit_cache[sound_id]
    if query and query not in _search_cache:
        _search_cache[query] = fs.search(query[0], min_dur=query[1], max_dur=query[2], page_size=30)
    for hits in _search_cache.values():
        for h in hits:
            _hit_cache.setdefault(h["id"], h)
    if sound_id not in _hit_cache:
        _hit_cache[sound_id] = fs._get(f"/sounds/{sound_id}/", {"fields": fs.FIELDS})
    h = _hit_cache[sound_id]
    assert "publicdomain/zero" in h["license"], f"{sound_id} is not CC0: {h['license']}"
    return h


def pick(group):
    p = PICKS[group]
    hit = hit_for(p["id"], p["query"])
    alts = [hit_for(a, p["query"]) for a in p["alt"]]
    return hit, alts, fs.fetch(hit)


# ---------------------------------------------------------------- DSP helpers
def mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def hp(x, f, order=4):
    return sosfiltfilt(butter(order, f, "hp", fs=SR, output="sos"), x, axis=0)


def lp(x, f, order=4):
    return sosfiltfilt(butter(order, f, "lp", fs=SR, output="sos"), x, axis=0)


def notch(x, f0, q=12.0):
    b, a = iirnotch(f0, q, fs=SR)
    return filtfilt(b, a, x, axis=0)


def env_db(x, win_s=0.02, hp_hz=None):
    m = mono(x)
    if hp_hz:
        m = hp(m, hp_hz)
    w = max(1, int(win_s * SR))
    e = np.sqrt(np.convolve(m ** 2, np.ones(w) / w, "same"))
    return 20 * np.log10(e + 1e-9)


def onsets(x, hp_hz=1500, min_gap_s=0.25, rel_db=-18):
    """Sharp transients: returns [(sample, level_db, centroid_hz, decay20_s, rise_db)]."""
    e = env_db(x, 0.005, hp_hz)
    pk, _ = find_peaks(e, height=e.max() + rel_db, distance=int(min_gap_s * SR), prominence=10)
    m = mono(x)
    out = []
    for p in pk:
        seg = m[max(0, p - int(0.02 * SR)): p + int(0.3 * SR)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        f = np.fft.rfftfreq(len(seg), 1 / SR)
        k = p
        while k < len(e) - 1 and e[k] > e[p] - 20 and k - p < SR:
            k += 1
        pre = e[max(0, p - int(0.08 * SR)): max(1, p - int(0.02 * SR))].mean()
        out.append((int(p), float(e[p]), float((spec * f).sum() / spec.sum()), (k - p) / SR, float(e[p] - pre)))
    return out


def regions(mask, close_s=0.0):
    """(start, end) sample ranges where mask is true, gaps shorter than close_s bridged."""
    if close_s > 0:
        mask = binary_closing(mask, structure=np.ones(int(close_s * SR), bool))
    lab, _ = label(mask)
    return [(sl[0].start, sl[0].stop) for sl in find_objects(lab)]


def one_shot(x, start, next_start, max_len_s):
    """Cut from 10 ms before an onset to max_len (or 25 ms before the next event), 5 ms fade in, soft tail, -3 dBFS.

    The tail is not silence-trimmed: these taps decay in 20-50 ms into the location's air, which is kept.
    """
    a = max(0, start - int(0.01 * SR))
    b = min(len(x), a + int(max_len_s * SR))
    if next_start is not None:
        b = min(b, next_start - int(0.025 * SR))
    seg = hp(mono(x[a:b]), 40)
    seg = fs.fade(seg, 0.005, 0.005)
    tail = max(int(0.06 * SR), len(seg) // 4)
    seg[-tail:] *= np.linspace(1, 0, tail) ** 0.5
    return fs.normalize(seg, -3).astype(np.float32)


def to_stereo(mid, side, side_gain):
    side = hp(side, 100) * side_gain
    return np.stack([mid + side, mid - side], axis=1)


def match_len(x, n):
    return x[:n] if len(x) >= n else np.concatenate([x, np.zeros((n - len(x),) + x.shape[1:], x.dtype)])


def read_synth(name):
    x, sr = soundfile.read(str(SYNTH / f"{name}.wav"), dtype="float32")
    assert sr == SR, (name, sr)
    return x


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


# ---------------------------------------------------------------- builders
def build_cloth(x):
    """Three smooth jacket gestures, 0.35-0.9 s, lowest crest factor (no throws or impacts)."""
    m = hp(mono(x), 60)
    e = env_db(m, 0.02)
    cands = []
    for a, b in regions(e > e.max() - 30, 0.08):
        dur = (b - a) / SR
        if 0.35 <= dur <= 0.9:
            seg = m[a:b]
            crest = 20 * np.log10(np.abs(seg).max() / rms(seg))
            cands.append((crest - 0.3 * fs.rms_db(seg), a, b, crest))
    cands.sort()
    chosen = sorted(cands[:3], key=lambda c: c[1])
    outs = []
    for _, a, b, crest in chosen:
        seg = m[max(0, a - int(0.02 * SR)): b + int(0.05 * SR)]
        outs.append((fs.normalize(fs.fade(seg, 0.005, 0.03), -3).astype(np.float32), f"{a / SR:.2f}-{b / SR:.2f} s, crest {crest:.1f} dB"))
    assert len(outs) == 3, f"only {len(outs)} cloth gestures found"
    return outs


def build_taps(x, lo_s, hi_s, min_centroid, max_decay_s, max_len_s):
    ons = onsets(x)
    starts = [o[0] for o in ons]
    good = [(o, starts[k + 1] if k + 1 < len(starts) else None) for k, o in enumerate(ons)
            if lo_s * SR <= o[0] <= hi_s * SR and o[2] >= min_centroid and o[3] <= max_decay_s]
    good.sort(key=lambda g: -(g[0][4] + g[0][1]))  # sharpest and loudest first
    chosen = sorted(good[:4], key=lambda g: g[0][0])
    assert len(chosen) == 4, f"only {len(chosen)} taps found"
    return [(one_shot(x, o[0], nxt, max_len_s), f"onset {o[0] / SR:.2f} s, centroid {o[2]:.0f} Hz, decay {o[3] * 1000:.0f} ms")
            for o, nxt in chosen]


def steadiest_window(m, length_s, skip_s=3.0):
    blocks = np.array([fs.rms_db(m[k:k + SR]) for k in range(0, len(m) - SR, SR)])
    n = int(length_s)
    best, best_k = 1e9, int(skip_s)
    for k in range(int(skip_s), len(blocks) - n):
        w = blocks[k:k + n]
        score = w.std() - 0.2 * w.mean()
        if score < best:
            best, best_k = score, k
    return best_k * SR


def build_tow_gravel(x):
    m = hp(mono(x), 30)
    n = int(32.5 * SR)
    a = steadiest_window(m, 33)
    b = (a + int(41 * SR)) % (len(m) - n)  # different stretch of the same road for stereo width
    st = to_stereo(m[a:a + n], m[b:b + n], 1.0)
    loop = fs.make_loop(st, 2.5)
    return fs.normalize(loop, -12).astype(np.float32), f"{a / SR:.1f}-{(a + n) / SR:.1f} s (+side from {b / SR:.1f} s)"


def build_tow_dirt(x):
    """The source is pull-pause-pull; keep only the pulls and chain them into one continuous drag."""
    x = hp(x, 30)
    e = env_db(x, 0.05)
    bursts = [(max(0, i - int(0.15 * SR)), min(len(x), j + int(0.15 * SR)))
              for i, j in regions(e > e.max() - 18, 0.1) if (j - i) / SR >= 0.6]
    assert len(bursts) >= 4, f"only {len(bursts)} drag pulls found"
    xf = int(0.3 * SR)
    t = np.linspace(0, np.pi / 2, xf, dtype=np.float32)[:, None]
    out = x[bursts[0][0]:bursts[0][1]].copy()
    order, last = [], 0
    while len(out) < int(32.5 * SR):
        k = int(RNG.integers(len(bursts)))
        if k == last and len(bursts) > 1:
            continue
        last = k
        order.append(k)
        seg = x[bursts[k][0]:bursts[k][1]]
        seg = seg * (rms(out[-xf:]) / max(rms(seg[:xf]), 1e-9)) ** 0.5  # halve the level step at each join
        out = np.concatenate([out[:-xf], out[-xf:] * np.cos(t) + seg[:xf] * np.sin(t), seg[xf:]])
    out = lp(out[: int(32.5 * SR)], 5000, 2)  # dirt: duller than the gravel loop
    loop = fs.make_loop(out, 2.5)
    return fs.normalize(loop, -12).astype(np.float32), f"{len(bursts)} pulls chained ({len(order)} joins), lowpass 5 kHz"


def layer(synth, rec, rel_db):
    """Scale the recording to rel_db against the synth RMS (over the recording's active part), sum, -3 dBFS."""
    act = np.abs(rec) > np.abs(rec).max() * 0.05
    g = rms(synth) / max(rms(rec[act]) if act.any() else rms(rec), 1e-9) * 10 ** (rel_db / 20)
    mix = synth + rec * g
    return fs.normalize(fs.fade(mix, 0.005, 0.005), -3).astype(np.float32)


def build_collapse(x):
    synth = read_synth("SFX_Carrier_Collapse")
    m = hp(notch(mono(x), 50), 30)  # 50 Hz mains peak (+10 dB) in the source
    hit = int(np.argmax(env_db(m, 0.005, 800)[: int(1.5 * SR)]))
    shift = int(0.50 * SR) - hit  # main crash onto the synth's body slam
    rec = np.zeros(len(synth), np.float32)
    src = m[max(0, -shift):]
    rec[max(0, shift): max(0, shift) + len(src)] = src[: len(rec) - max(0, shift)]
    rec = fs.fade(rec, 0.005, 0.4)
    return layer(synth, rec, -2), f"crash peak {hit / SR:.2f} s moved to 0.50 s, 50 Hz notch, -2 dB vs synth"


def build_scrape(x):
    synth = read_synth("SFX_Capsule_Scrape_Failing")
    m = hp(mono(x), 60)
    n = len(synth)
    blocks = np.array([fs.rms_db(m[k:k + SR // 4]) for k in range(0, len(m) - SR // 4, SR // 4)])
    w = n // (SR // 4)
    best = max(range(len(blocks) - w), key=lambda k: blocks[k:k + w].min())  # continuous drag, no gaps
    rec = m[best * SR // 4: best * SR // 4 + n].astype(np.float32)
    es = np.sqrt(np.convolve(synth ** 2, np.ones(int(0.03 * SR)) / int(0.03 * SR), "same"))
    rec = rec * (es / es.max()) ** 0.8  # follow the synth's stick-slip, sag and 1.2 s drop-out
    rec = fs.fade(rec, 0.02, 0.2)
    return layer(synth, rec, -3), f"{best / 4:.2f}-{best / 4 + n / SR:.2f} s, shaped by the synth envelope, -3 dB vs synth"


def build_hatch(x):
    synth = read_synth("SFX_Capsule_Hatch_Open")
    m = hp(mono(x), 80)
    n = int(1.1 * SR)
    blocks = [rms(m[k:k + n]) for k in range(0, len(m) - n, SR // 20)]
    a = int(np.argmax(blocks)) * (SR // 20)
    seg = m[a:a + n].astype(np.float32)
    seg = fs.fade(seg, 0.08, 0.15)
    rec = np.zeros(len(synth), np.float32)
    rec[int(0.40 * SR): int(0.40 * SR) + n] = seg
    return layer(synth, rec, -4), f"groan {a / SR:.2f}-{(a + n) / SR:.2f} s placed at 0.40-1.50 s, -4 dB vs synth"


# ---------------------------------------------------------------- measurement
def measure(x):
    m = mono(x)
    n = 4096
    fr = m[: len(m) // n * n].reshape(-1, n) * np.hanning(n) if len(m) >= n else np.pad(m, (0, n - len(m)))[None] * np.hanning(n)
    s = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
    flat = float(np.median(np.exp(np.mean(np.log(s), axis=1)) / np.mean(s, axis=1)))
    big = 16384
    m2 = np.pad(m, (0, max(0, big - len(m))))
    p = (np.abs(np.fft.rfft(m2[: len(m2) // big * big].reshape(-1, big) * np.hanning(big), axis=1)) ** 2).mean(0) + 1e-12
    f = np.fft.rfftfreq(big, 1 / SR)

    def peak(f0):
        b = (f > f0 - 4) & (f < f0 + 4)
        nb = ((f > f0 - 25) & (f < f0 - 8)) | ((f > f0 + 8) & (f < f0 + 25))
        return 10 * np.log10(p[b].max() / np.median(p[nb]))

    r = dict(dur_s=round(len(m) / SR, 3), ch=1 if x.ndim == 1 else x.shape[1], peak_db=round(20 * np.log10(np.abs(x).max() + 1e-12), 2),
             rms_db=round(fs.rms_db(m), 1), flatness=round(flat, 4), clip_frac=float(np.mean(np.abs(x) >= 0.999)),
             hum_peak_db=round(max(peak(50), peak(60), peak(100), peak(120)), 1))
    if x.ndim == 2 and x.shape[1] == 2:
        r["lr_corr"] = round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 2)
    return r


def seam(x):
    """Loop check: level gap between the last and first 50 ms, and the sample jump at the wrap."""
    k = int(0.05 * SR)
    blocks = np.array([fs.rms_db(x[i:i + k]) for i in range(0, len(x) - k + 1, k)])
    steps = np.abs(np.diff(np.concatenate([blocks, blocks[:1]])))  # last step is the wrap
    return dict(seam_level_gap_db=round(float(steps[-1]), 2), seam_gap_percentile=round(float(np.mean(steps < steps[-1]) * 100)),
                wrap_jump=round(float(np.max(np.abs(x[0] - x[-1]))), 4), level_1s_std_db=round(float(np.std(
                    [fs.rms_db(x[i:i + SR]) for i in range(0, len(x) - SR + 1, SR)])), 2))


# ---------------------------------------------------------------- main
USE = {
    "SFX_Cloth_Rustle": "Human clothing movement in the ending walk (jacket rustle).",
    "SFX_Capsule_Tow_Gravel_Loop": "Towed capsule on gravel or the old road; loop, pitch/volume by speed.",
    "SFX_Capsule_Tow_Dirt_Loop": "Towed capsule on dirt or grass; loop, pitch/volume by speed.",
    "SFX_WalkingAid_Tap_Gravel": "Ending walk: walking-aid tip into gravel (hero sound).",
    "SFX_WalkingAid_Tap_Stone": "Ending walk: walking-aid tip on stone (hero sound).",
    "SFX_Carrier_Collapse": "Final carrier collapse; synth layer kept, recorded metal/stone crash on the 0.50 s body slam.",
    "SFX_Capsule_Scrape_Failing": "Failing carrier drags the capsule; synth kept, recorded metal-on-stone scrape follows its envelope.",
    "SFX_Capsule_Hatch_Open": "Capsule hatch opens; synth kept (seal, gasket, stop at 1.55 s), recorded heavy hinge groan 0.40-1.50 s.",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []  # (asset, audio, hit, alts, loop, notes)

    hit, alts, x = pick("cloth")
    for k, (a, note) in enumerate(build_cloth(x), 1):
        results.append((f"SFX_Cloth_Rustle_{k:02d}", a, hit, alts, False, note))
    hit, alts, x = pick("tow_gravel")
    a, note = build_tow_gravel(x)
    results.append(("SFX_Capsule_Tow_Gravel_Loop", a, hit, alts, True, note))
    hit, alts, x = pick("tow_dirt")
    a, note = build_tow_dirt(x)
    results.append(("SFX_Capsule_Tow_Dirt_Loop", a, hit, alts, True, note))
    hit, alts, x = pick("tap_gravel")
    for k, (a, note) in enumerate(build_taps(x, 0, 30, 1400, 0.09, 0.40), 1):
        results.append((f"SFX_WalkingAid_Tap_Gravel_{k:02d}", a, hit, alts, False, note))
    hit, alts, x = pick("tap_stone")
    for k, (a, note) in enumerate(build_taps(x, 33, 58, 1800, 0.05, 0.20), 1):  # 33-58 s is the asphalt pass; ticks decay in ~8 ms
        results.append((f"SFX_WalkingAid_Tap_Stone_{k:02d}", a, hit, alts, False, note))
    for group, name, fn in (("collapse", "SFX_Carrier_Collapse", build_collapse),
                            ("scrape", "SFX_Capsule_Scrape_Failing", build_scrape),
                            ("hinge", "SFX_Capsule_Hatch_Open", build_hatch)):
        hit, alts, x = pick(group)
        a, note = fn(x)
        results.append((name, a, hit, alts, False, "LAYER over synth: " + note))

    manifest = []
    for name, a, hit, alts, loop, note in results:
        fs.write_wav(OUT / f"{name}.wav", a)
        fs.credit(name, hit, alternates=alts, notes=note)
        base = name.rstrip("0123456789").rstrip("_")
        manifest.append(dict(asset=name, file=f"{name}.wav", ue_folder=UE_FOLDER, loop=loop, replaces_synth=True,
                             freesound_id=hit["id"], use=USE.get(name, USE.get(base, ""))))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    report()


def report():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    for e in manifest:
        x, _ = soundfile.read(str(OUT / e["file"]), dtype="float32")
        r = measure(x)
        if e["loop"]:
            r.update(seam(x))
        print(e["asset"], e["freesound_id"], r)


if __name__ == "__main__":
    report() if "--measure" in sys.argv else main()
