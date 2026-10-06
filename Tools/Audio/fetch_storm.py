"""Storm, wind and radiation soundscape for Saskarta, from CC0 Freesound recordings (spec section 6).

Every pick is a pinned Freesound id with ranked alternates, so a bad pick is a one-line swap: move
an alternate id into `id` in LOOPS/ONESHOTS/SINGLES below and rerun.

    python Tools/Audio/fetch_storm.py            # fetch (cached), process, write WAVs + manifest, credit, print metrics
    python Tools/Audio/fetch_storm.py --measure  # only print metrics of the files already written

Output: Saved/GameAudio/Recorded/Storm/<Asset>.wav plus manifest.json, and a credit entry per asset
in Tools/Audio/freesound_credits.json / CREDITS.md (via freesound_fetch.credit). Import target in
Unreal: /Game/SaskartaGaea/Audio/Storm. See STORM.md for the StormIntensity mapping and the
lightning/thunder timing that drives these assets in play.

Formats (spec section 6 / task L6):
  beds (AMB_*)       stereo, seamless loop (fs.make_loop), 60-120 s, peak -14 dBFS
  one-shots (SFX_*)  the source's own channel count, 5 ms+ fades, peak -3 dBFS

Loops shorter than 60 s at the source are tiled (their own seam repeated) up to the 60 s floor;
seamlessness is unaffected because a tile boundary IS the same crossfaced seam.

One-shot GROUPS (gusts, thunders, sparks, ...) are cut from a single longer recording of many
such events: `top_segments` ranks fixed-length windows by RMS, keeps the N loudest that are at
least `min_gap_s` apart (relaxing the gap, then falling back to even spacing, so a group always
yields exactly N files even on an unfamiliar recording).

NO MUSIC, NO PEOPLE. Every source is wind, storm, industrial hum/arc, a Geiger counter or a siren,
per BANNED_TAGS in freesound_fetch.py.
"""
import json
import pathlib
import sys

import numpy as np
import soundfile
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

ROOT = fs.ROOT
OUT = ROOT / "Saved" / "GameAudio" / "Recorded" / "Storm"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Storm"
SR = fs.SR

# --------------------------------------------------------------------------- picks
# id: the pick; alts: next-best alternates (ranked, all CC0, checked at run time).

LOOPS = {
    "AMB_Storm_WindHeavy_Loop": dict(
        id=521736, alts=[454092, 565140, 735350],
        use="Wind bed for storm keys (Valley, Basin, Climb); the loudest 2D wind layer, volume scales with StormIntensity."),
    "AMB_Storm_WindRuins_Loop": dict(
        id=840366, alts=[475654, 325186, 324641],
        use="Spatial wind-in-ruins layer at the settlement and waterworks; adds a howl/moan character distinct from the open-field bed."),
    "AMB_Storm_WindHighAlt_Loop": dict(
        id=156414, alts=[160469, 157193, 725630],
        use="2D thin, cold high-altitude wind for the Climb and In-the-cloud keys; replaces the open-field wind above the tree line."),
    "AMB_Storm_GritDebris_Loop": dict(
        id=438877, alts=[136440, 172934, 675886],
        use="2D blowing grit/sand/debris layer, mixed low under the wind beds in the driest, most exposed switchback stretches."),
    "AMB_Storm_Distant_Loop": dict(
        id=584946, alts=[273805, 158691, 158692],
        use="2D far storm rumble bed, always-on low layer under the discrete thunder one-shots; rises with StormIntensity."),
    "AMB_Storm_DryStatic_Loop": dict(
        id=732771, alts=[675757, 210989, 869132],
        use="2D dry-storm static-charge hum: the eerie charged-air buzz before a strike, in the storm keys just ahead of a lightning timer firing."),
    "AMB_Storm_FacilityHum_Loop": dict(
        id=803970, alts=[817225, 259194, 530200],
        use="Spatial distant ruined-facility hum at the waterworks and basin: a dead machine still drawing a trickle of power."),
    "AMB_Storm_PowerlineBuzz_Loop": dict(
        id=805619, alts=[222676, 760860, 347046],
        use="Spatial power-line buzz near the old transmission run; layers with FacilityHum close to the works."),
}

# n: how many one-shots to cut from the one source recording; seg_len_s/min_gap_s: top_segments args.
ONESHOTS = {
    "SFX_Storm_Gust_Heavy": dict(
        id=565140, alts=[454358, 454092, 836590], n=6, seg_len_s=2.0, min_gap_s=3.0,
        use="Random heavy gusts over storm keys, 20-90 s timer scaled by StormIntensity (see STORM.md)."),
    "SFX_Storm_Edge_Whistle": dict(
        id=862594, alts=[521736, 643515], n=3, seg_len_s=3.0, min_gap_s=4.0,
        use="Wind whistling over a taut edge (wires, the carrier's frame); layered with gusts in high-wind keys."),
    "SFX_Storm_Tarp_Snap": dict(
        id=154794, alts=[146272, 701647, 541088], n=3, seg_len_s=0.6, min_gap_s=1.0,
        use="A loose tarp/fabric snap at the settlement and waterworks ruins, on the same gust timer as Gust_Heavy."),
    "SFX_Thunder_Close": dict(
        id=243614, alts=[505113, 392485, 534023], n=4, seg_len_s=2.5, min_gap_s=3.0,
        use="Close thunder (strike distance < 2.5 km): fired by the lighting director's lightning timer, delay = distance/343 s."),
    "SFX_Thunder_Rolling": dict(
        id=573669, alts=[577317, 567728, 576963], n=4, seg_len_s=4.0, min_gap_s=5.0,
        use="Rolling/distant thunder (strike distance >= 2.5 km): same lightning timer, longer and softer than Close."),
    "SFX_Lightning_Crack": dict(
        id=392485, alts=[840628, 536901, 474387], n=3, seg_len_s=0.8, min_gap_s=1.5,
        use="Sharp crack synced to the flash itself (the LightningFlash pulse on MPC_Saskarta_Sky), before the Close/Rolling thunder arrives."),
    "SFX_Geiger_Spike": dict(
        id=555926, alts=[555933, 555930, 555931], n=4, seg_len_s=0.25, min_gap_s=0.5,
        use="A single hot click, layered over the storyline's SFX_Geiger_Low/Medium/High loops near the waterworks and basin."),
    "SFX_Electrical_Arc": dict(
        id=522690, alts=[393822, 393823, 867585], n=4, seg_len_s=0.5, min_gap_s=1.0,
        use="A failing-infrastructure arc/spark, spatial one-shot near the works and the power-line buzz bed, occasional random timer."),
    "SFX_Metal_Tick": dict(
        id=522119, alts=[132340, 466308, 94398], n=4, seg_len_s=0.35, min_gap_s=0.7,
        use="A single tick of metal cooling/settling at the ruined facility, slow random timer, layered with FacilityHum."),
    "SFX_Dosimeter_Chirp": dict(
        id=72561, alts=[262855, 262861], n=2, seg_len_s=0.3, min_gap_s=1.0,
        use="The carrier's own dosimeter instrument chirp, 2D, driven by the storyline's Geiger ramp rather than StormIntensity."),
}

SINGLES = {
    "SFX_Siren_Distant": dict(
        id=438696, alts=[479898],
        use="Rare one-shot: a distant civil-defence siren winding down. Mechanical, not music; fired at most once per session per STORM.md."),
}

# --------------------------------------------------------------------------- DSP helpers


def hp(x, f, order=2):
    return sosfiltfilt(butter(order, f, "hp", fs=SR, output="sos"), x, axis=0).astype(np.float32)


def lp(x, f, order=2):
    return sosfiltfilt(butter(order, f, "lp", fs=SR, output="sos"), x, axis=0).astype(np.float32)


def steadiest_window(m, length_s, skip_s=2.0):
    """Start sample of the flattest stretch of `length_s` seconds (least 1-s-block level variance)."""
    blocks = np.array([fs.rms_db(m[k:k + SR]) for k in range(0, max(1, len(m) - SR), SR)])
    n = max(1, int(length_s))
    if len(blocks) <= n:
        return 0
    best, best_k = 1e9, int(min(skip_s, max(0, len(blocks) - n - 1)))
    for k in range(int(skip_s), len(blocks) - n):
        w = blocks[k:k + n]
        score = w.std() - 0.2 * w.mean()
        if score < best:
            best, best_k = score, k
    return best_k * SR


def tile_to_floor(loop, floor_s=60.0):
    """Repeat a seamless loop whole-number times until it reaches floor_s (a tile boundary IS the seam)."""
    n = len(loop)
    if n >= floor_s * SR:
        return loop
    reps = int(np.ceil(floor_s * SR / n))
    return np.concatenate([loop] * reps)


def build_loop(x, want_s=90.0, crossfade_s=3.0):
    m = x.mean(axis=1) if x.ndim == 2 else x
    n = int(min(want_s, max(10.0, len(x) / SR - 2 * crossfade_s)) * SR)
    n = min(n, len(x) - int(2 * crossfade_s * SR))
    n = max(n, min(len(x), int(SR * 8)))
    a = steadiest_window(m, n / SR)
    seg = x[a:a + n]
    loop = fs.make_loop(seg, crossfade_s)
    tiled = tile_to_floor(loop, 60.0)
    reps = len(tiled) // len(loop)
    note = f"{a / SR:.1f}-{(a + n) / SR:.1f} s of source, {crossfade_s}s crossfade" + (f", tiled x{reps}" if reps > 1 else "")
    return fs.normalize(tiled, -14).astype(np.float32), note


def top_segments(x, n, seg_len_s, min_gap_s):
    """The n loudest, best-separated seg_len_s windows; relaxes the gap, then falls back to even spacing."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    win = max(1, int(seg_len_s * SR))
    hop = max(1, int(min(0.05, seg_len_s / 4) * SR))
    csum = np.concatenate([[0.0], np.cumsum(m.astype(np.float64) ** 2)])
    idx = np.arange(0, max(1, len(m) - win), hop)
    sums = csum[np.minimum(idx + win, len(m))] - csum[idx]
    scores = np.sqrt(sums / win)
    order = np.argsort(-scores)
    gap, chosen = min_gap_s, []
    for _ in range(10):
        chosen = []
        min_gap_samp = int(gap * SR)
        for i in order:
            pos = int(idx[i])
            if all(abs(pos - c) >= min_gap_samp for c in chosen):
                chosen.append(pos)
            if len(chosen) == n:
                break
        if len(chosen) == n:
            break
        gap = max(gap / 1.6, 0.05)
    if len(chosen) < n:
        chosen = [int(p) for p in np.linspace(0, max(0, len(m) - win), n)]
    chosen.sort()
    out = []
    for pos in chosen:
        b = min(len(x), pos + win)
        seg = x[pos:b].copy()
        seg = fs.fade(seg, min(0.01, seg_len_s * 0.05), min(0.1, seg_len_s * 0.3))
        out.append((fs.normalize(seg, -3).astype(np.float32), f"{pos / SR:.2f}-{b / SR:.2f} s, rms {fs.rms_db(seg):.1f} dB"))
    return out


def single_shot(x, max_len_s=20.0):
    trimmed = fs.trim_silence(x, threshold_db=-45.0, pad_s=0.05)
    n = min(len(trimmed), int(max_len_s * SR))
    seg = fs.fade(trimmed[:n], 0.02, 0.6)
    return fs.normalize(seg, -3).astype(np.float32), f"{n / SR:.1f} s, trimmed to -45 dB, distant (low-passed)"


# --------------------------------------------------------------------------- metadata / credits

_hit_cache = {}


def hit_for(sound_id):
    if sound_id not in _hit_cache:
        h = fs._get(f"/sounds/{sound_id}/", {"fields": fs.FIELDS})
        assert "publicdomain/zero" in h["license"], f"{sound_id} ({h['name']!r}) is not CC0: {h['license']}"
        _hit_cache[sound_id] = h
    return _hit_cache[sound_id]


# --------------------------------------------------------------------------- main


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []

    for name, spec in LOOPS.items():
        hit, alts = hit_for(spec["id"]), [hit_for(a) for a in spec["alts"]]
        x = fs.fetch(hit)
        audio, note = build_loop(x)
        fs.write_wav(OUT / f"{name}.wav", audio)
        fs.credit(name, hit, alternates=alts, notes=note)
        manifest.append(dict(asset=name, file=f"{name}.wav", ue_folder=UE_FOLDER, loop=True,
                              replaces_synth=False, freesound_id=hit["id"], use=spec["use"]))
        print(name, hit["id"], note)

    for group, spec in ONESHOTS.items():
        hit, alts = hit_for(spec["id"]), [hit_for(a) for a in spec["alts"]]
        x = fs.fetch(hit)
        segs = top_segments(x, spec["n"], spec["seg_len_s"], spec["min_gap_s"])
        for k, (audio, note) in enumerate(segs, 1):
            name = f"{group}_{k:02d}"
            fs.write_wav(OUT / f"{name}.wav", audio)
            fs.credit(name, hit, alternates=alts, notes=note)
            manifest.append(dict(asset=name, file=f"{name}.wav", ue_folder=UE_FOLDER, loop=False,
                                  replaces_synth=False, freesound_id=hit["id"], use=spec["use"]))
            print(name, hit["id"], note)

    for name, spec in SINGLES.items():
        hit, alts = hit_for(spec["id"]), [hit_for(a) for a in spec["alts"]]
        x = fs.fetch(hit)
        audio, note = single_shot(lp(x, 3500, 2))
        fs.write_wav(OUT / f"{name}.wav", audio)
        fs.credit(name, hit, alternates=alts, notes=note)
        manifest.append(dict(asset=name, file=f"{name}.wav", ue_folder=UE_FOLDER, loop=False,
                              replaces_synth=False, freesound_id=hit["id"], use=spec["use"]))
        print(name, hit["id"], note)

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    report()


def measure(x):
    m = x.mean(axis=1) if x.ndim == 2 else x
    return dict(dur_s=round(len(m) / SR, 2), ch=1 if x.ndim == 1 else x.shape[1],
                peak_db=round(20 * np.log10(np.abs(x).max() + 1e-12), 2), rms_db=round(fs.rms_db(m), 1),
                clip_frac=float(np.mean(np.abs(x) >= 0.999)))


def seam(x):
    k = int(0.05 * SR)
    blocks = np.array([fs.rms_db(x[i:i + k]) for i in range(0, len(x) - k + 1, k)])
    steps = np.abs(np.diff(np.concatenate([blocks, blocks[:1]])))
    return dict(seam_level_gap_db=round(float(steps[-1]), 2))


def report():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    for e in manifest:
        x, _ = soundfile.read(str(OUT / e["file"]), dtype="float32")
        r = measure(x)
        if e["loop"]:
            r.update(seam(x))
        print(e["asset"], e["freesound_id"], r)
    print(f"\n{len(manifest)} files: {sum(1 for e in manifest if e['loop'])} loops, "
          f"{sum(1 for e in manifest if not e['loop'])} one-shots.")


if __name__ == "__main__":
    report() if "--measure" in sys.argv else main()
