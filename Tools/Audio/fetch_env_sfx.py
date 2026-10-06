"""Replace the synthesized environment SFX with CC0 Freesound recordings, and add a few new ones.

Every pick is pinned by Freesound id in PICKS below, with the exact region used and up to three
alternates. To swap a bad pick, change its `id` (and region) to one of the alternates and re-run.

    python Tools/Audio/fetch_env_sfx.py            # fetch, process, write WAVs + manifest, credit
    python Tools/Audio/fetch_env_sfx.py --only SFX_Spot_Drip_Loop SFX_Chain_Rattle_02
    python Tools/Audio/fetch_env_sfx.py --no-credit   # dry run: WAVs + report, credits untouched

Output: Saved/GameAudio/Recorded/Environment/<Asset>.wav, manifest.json and _analysis.json.
Replacements keep the synth asset names exactly, so the Unreal import overwrites them in place.
The radio / static / transmission sounds are NOT replaced; they stay synthesized
(Tools/Audio/make_env_sfx.py).

Processing (all through Tools/Audio/freesound_fetch.py, which decodes the HQ OGG preview to 48 kHz):
- spot loops: region -> optional high-pass -> make_loop (2.0 s equal-power crossfade) -> -12 dBFS peak, stereo
- both: optional mains-hum notch after the high-pass (see `notch` below)
- one-shots: region -> optional high-pass -> mono -> trim_silence -> 5 ms fades (a longer fade-out only
  where the region is cut while the sound is still going) -> -3 dBFS peak

Sound metadata is cached in Saved/GameAudio/_freesound_cache/meta/<id>.json, so a re-run needs
no API calls for sounds it has seen; unknown ids cost one rate-limited call each.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from scipy.signal import butter, iirnotch, lfilter, sosfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

SR = fs.SR
OUT = fs.ROOT / "Saved" / "GameAudio" / "Recorded" / "Environment"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Environment"
META = fs.CACHE / "meta"
LOOP_XFADE_S = 2.0
LOOP_PEAK_DB = -12.0
ONESHOT_PEAK_DB = -3.0

# kind: "loop" | "oneshot". region: (start_s, end_s) in the source; None = whole file.
# For loops, `search` lets the script slide the window inside that range to find the start whose
# head and tail match best in level (quietest seam); `length` is the window length before the
# crossfade (the loop comes out LOOP_XFADE_S shorter).
# hp: high-pass cutoff in Hz (wind rumble removal), or 0.
# notch: mains frequency (50 or 60) whose first six harmonics are notched out, where the hum check
# found a narrow mains peak standing 15+ dB above its neighbours.
PICKS = [
    # ---------------------------------------------------------------- spot loops (replacements)
    dict(asset="SFX_Spot_WaterTrickle_Loop", kind="loop", replaces=True, id=677826, search=(4, 84), length=32.0, hp=60,
         alts=[363120, 637977, 615249],
         use="Thin water falling from two broken pipes onto stone: the break in a channel, pipe or gutter."),
    dict(asset="SFX_Spot_Drip_Loop", kind="loop", replaces=True, id=402929, search=(18, 60), length=38.0, hp=60,
         alts=[343742, 628404, 609161],
         use="Irregular drops in a small ice cave with natural cave reverb: cistern, culvert, gallery, cellar."),
    dict(asset="SFX_Spot_ClothFlutter_Loop", kind="loop", replaces=True, id=569539, search=(2, 64), length=30.0, hp=80, notch=60,
         alts=[330638, 451958, 569537],
         use="Light synthetic tent fabric flapping in heavy wind: torn tarp, awning, camp shelter."),
    dict(asset="SFX_Spot_Insects_Loop", kind="loop", replaces=True, id=198277, search=(0, 29), length=28.8, hp=150, notch=50,
         alts=[715679, 478207, 430587],
         use="Grasshoppers and small insects in a sunny meadow: warm stone walls, dry verges."),
    dict(asset="SFX_Spot_ReedRustle_Loop", kind="loop", replaces=True, id=844604, search=(0, 65), length=32.0, hp=80,
         alts=[843069, 613960, 573208],
         use="Wind hissing through a reed bed (faint shore wash under it): valley wet ground, reservoir margins."),
    dict(asset="SFX_Spot_PipeWind_Loop", kind="loop", replaces=True, id=414146, search=(60, 179), length=34.0, hp=100,
         alts=[145777, 262604, 527775],
         use="Wind whistling in a pipe, with gusts and a faint wood creak: open end of a broken pipe run."),
    # ---------------------------------------------------------------- spot loops (new)
    dict(asset="SFX_Spot_Flag_Rope_Loop", kind="loop", replaces=False, id=610985, search=(1, 88), length=32.0, hp=80,
         alts=[216907, 640689, 159734],
         use="An empty flagpole in wind: the halyard and clasp knocking the mast. Settlement and camp poles."),
    # 236978 ("Stream Running Over Rocks 1") was the first choice but carries a steady 240 Hz tone
    # (0.02 Hz wide, about -26 dB of the total): machinery or electrics nearby, so it is only an alternate.
    dict(asset="SFX_Spot_Stream_Loop", kind="loop", replaces=False, id=275627, search=(2, 109), length=34.0, hp=60,
         alts=[376192, 572464, 236978],
         use="A small stream running steadily over stones: mountain-foot and switchback gullies."),
    # ---------------------------------------------------------------- one-shots (replacements)
    dict(asset="SFX_SheetMetal_Bang_01", kind="oneshot", replaces=True, id=108673, region=(7.5, 10.6), hp=40,
         alts=[416561, 263620, 392241], use="Rusted tin plate knocked, then rattling."),
    dict(asset="SFX_SheetMetal_Bang_02", kind="oneshot", replaces=True, id=416561, region=(8.1, 11.9), hp=40,
         alts=[108673, 263620, 392241], use="Corrugated iron sheet shaking against its frame."),
    dict(asset="SFX_SheetMetal_Bang_03", kind="oneshot", replaces=True, id=416561, region=(0.6, 4.6), hp=40,
         alts=[108673, 263620, 392241], use="Corrugated iron sheet shaking (a different gesture, 4 s earlier)."),
    dict(asset="SFX_Chain_Rattle_01", kind="oneshot", replaces=True, id=452576, region=(0.0, 2.6), hp=60,
         alts=[452577, 401621, 533081], use="Thick chain rattling against metal."),
    dict(asset="SFX_Chain_Rattle_02", kind="oneshot", replaces=True, id=637351, region=(1.7, 4.7), hp=60, notch=60,
         alts=[401621, 452577, 533081], use="Light chain rattle."),
    dict(asset="SFX_Chain_Rattle_03", kind="oneshot", replaces=True, id=332838, region=(2.3, 5.2), hp=120,
         alts=[401621, 533081, 452577], use="Chain hanging from a fence, clanking in wind."),
    dict(asset="SFX_Wood_Creak_01", kind="oneshot", replaces=True, id=590149, region=None, hp=60,
         alts=[590153, 590148, 455757], use="Door creak (slow)."),
    dict(asset="SFX_Wood_Creak_02", kind="oneshot", replaces=True, id=590153, region=None, hp=60,
         alts=[590149, 590148, 455757], use="Door creak (short)."),
    dict(asset="SFX_Wood_Creak_03", kind="oneshot", replaces=True, id=452104, region=(5.5, 8.4), hp=40,
         alts=[452105, 397620, 455756], use="Deep timber groan (beam, walkway)."),
    dict(asset="SFX_Wood_Creak_04", kind="oneshot", replaces=True, id=397620, region=(3.2, 5.2), hp=40,
         alts=[452104, 452105, 478667], use="Timber creak, ship-mast character (pulley frame, beam)."),
    dict(asset="SFX_Pulley_Squeak_01", kind="oneshot", replaces=True, id=559469, region=(1.0, 3.2), hp=100,
         alts=[786898, 700700, 861827], use="Small rusty wheel turning a little."),
    dict(asset="SFX_Pulley_Squeak_02", kind="oneshot", replaces=True, id=438350, region=(19.6, 23.4), hp=100, notch=60,
         alts=[394222, 585410, 170614], use="Big wooden pulley creaking round (old optical-film recording; hum filtered)."),
    dict(asset="SFX_Stone_Settle_01", kind="oneshot", replaces=True, id=488660, region=(0.0, 1.4), hp=40,
         alts=[437357, 567251, 567250], use="A small rock tumbles a step."),
    dict(asset="SFX_Stone_Settle_02", kind="oneshot", replaces=True, id=488660, region=(2.35, 4.08), hp=40,
         alts=[437357, 567251, 567250], use="A small rock rolls down stone steps (a separate take in the same file)."),
    dict(asset="SFX_Stone_Settle_03", kind="oneshot", replaces=True, id=437357, region=(9.0, 10.8), hp=60,
         alts=[488660, 567251, 567250], use="Loose stones shifting in an old wall."),
    dict(asset="SFX_Gravel_Trickle_01", kind="oneshot", replaces=True, id=500638, region=(2.2, 9.5), hp=60,
         alts=[34175, 326304, 569743], use="A real small rockslide on a mountain face: pops and clicks cascading."),
    dict(asset="SFX_Gravel_Trickle_02", kind="oneshot", replaces=True, id=569736, region=None, hp=60,
         alts=[569743, 34175, 326304], use="Small gravel and dirt debris falling."),
    dict(asset="SFX_Gravel_Trickle_03", kind="oneshot", replaces=True, id=569737, region=None, hp=60,
         alts=[569743, 34175, 326304], use="Fine gravel and dirt trickling (a separate take)."),
    dict(asset="SFX_Reed_Push_01", kind="oneshot", replaces=True, id=559082, region=(6.9, 8.4), hp=80,
         alts=[575455, 594774, 767220], use="Normal pace: a body pushing through high grass."),
    dict(asset="SFX_Reed_Push_02", kind="oneshot", replaces=True, id=575455, region=(86.5, 91.0), hp=100,
         alts=[559082, 594774, 347557], use="Slower and fuller: moving through tall dry grass."),
    dict(asset="SFX_Reed_Push_03", kind="oneshot", replaces=True, id=559082, region=(1.7, 2.9), hp=80,
         alts=[575455, 594774, 767220], use="Quick pass through high grass (a separate pass in the same file)."),
    dict(asset="SFX_Reed_Push_04", kind="oneshot", replaces=True, id=575455, region=(29.5, 34.5), hp=100,
         alts=[559082, 767220, 594774], use="Slow and careful: easing through tall dry grass."),
    # ---------------------------------------------------------------- one-shots (new)
    dict(asset="SFX_Door_Swing_Creak_01", kind="oneshot", replaces=False, id=455756, region=(28.9, 32.6), hp=40,
         alts=[455757, 861827, 455324], use="An old wooden door swinging slowly on its hinges."),
    dict(asset="SFX_Door_Swing_Creak_02", kind="oneshot", replaces=False, id=455319, region=None, hp=40, notch=60,
         alts=[455324, 455757, 861827], use="A heavy door groaning through a long slow swing."),
    dict(asset="SFX_Glass_Shard_Settle_01", kind="oneshot", replaces=False, id=802591, region=(0.95, 2.4), hp=150,
         alts=[221529, 156579, 221536], use="Small glass plates and shards clinking as they shift."),
    dict(asset="SFX_Glass_Shard_Settle_02", kind="oneshot", replaces=False, id=221536, region=None, hp=150,
         alts=[221529, 802591, 156579], use="Broken glass shards sliding and settling."),
]


def hit_by_id(sound_id):
    """Freesound metadata for one sound, from the local cache or one rate-limited API call."""
    META.mkdir(parents=True, exist_ok=True)
    path = META / f"{sound_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    hit = fs._get(f"/sounds/{sound_id}/", {"fields": fs.FIELDS})
    path.write_text(json.dumps(hit), encoding="utf-8")
    return hit


def licence_ok(hit):
    lic = hit["license"].lower()
    return "publicdomain/zero" in lic or "creative commons 0" in lic


def highpass(x, hz):
    if not hz:
        return x
    sos = butter(2, hz, btype="highpass", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def notch_mains(x, base):
    """Remove narrow mains hum: notch base*1..6 (Q 30) where below Nyquist."""
    if not base:
        return x
    for k in range(1, 7):
        b, a = iirnotch(base * k, 30.0, fs=SR)
        x = lfilter(b, a, x, axis=0)
    return x.astype(np.float32)


def hum_prominence(x):
    """Largest narrow peak at a 50/60 Hz harmonic (to 480 Hz), in dB above the neighbouring spectrum."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2 + 1e-20
    f = np.fft.rfftfreq(len(m), 1 / SR)
    worst = (0.0, 0)
    for base in (50, 60):
        for k in range(1, 9):
            f0 = base * k
            peak = spec[(f > f0 - 1.5) & (f < f0 + 1.5)].max()
            near = np.median(spec[((f > f0 - 12) & (f < f0 - 4)) | ((f > f0 + 4) & (f < f0 + 12))])
            worst = max(worst, (round(float(10 * np.log10(peak / near)), 1), f0))
    return worst


def measure(x):
    """Loudness, spectral flatness (100 Hz-8 kHz), clipping, and mains-hum / low-frequency checks."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    n = min(len(m), 30 * SR)
    spec = np.abs(np.fft.rfft(m[:n] * np.hanning(n))) ** 2 + 1e-20
    f = np.fft.rfftfreq(n, 1 / SR)

    def band(lo, hi):
        return float(np.sum(spec[(f >= lo) & (f < hi)]))

    sel = (f > 100) & (f < 8000)
    flat = float(np.exp(np.mean(np.log(spec[sel]))) / np.mean(spec[sel]))
    total = band(20, 20000)
    # Hum: energy in the 50/60 Hz and 100/120 Hz bins relative to the surrounding band.
    hum = max(band(49, 51) / (band(40, 60) + 1e-20), band(59, 61) / (band(50, 70) + 1e-20),
              band(99, 101) / (band(90, 110) + 1e-20), band(119, 121) / (band(110, 130) + 1e-20))
    return {
        "rms_db": round(float(fs.rms_db(x)), 1),
        "peak_db": round(float(20 * np.log10(np.max(np.abs(x)) + 1e-12)), 1),
        "clip_pct": round(float(np.mean(np.abs(x) > 0.985) * 100), 4),
        "flatness": round(flat, 3),
        "low_below_120hz_pct": round(band(20, 120) / total * 100, 1),
        "hum_ratio": round(hum, 2),
        "centroid_hz": int(np.sum(f * spec) / np.sum(spec)),
        "mains_peak_db_at_hz": hum_prominence(x),
    }


def best_loop_start(x, search, length):
    """Start time in `search` whose window has the best-matched head and tail (level and spectrum)."""
    lo, hi = search
    hi = min(hi, len(x) / SR) - length
    if hi <= lo:
        return max(0.0, min(lo, len(x) / SR - length))
    xf = int(LOOP_XFADE_S * SR)
    best, best_t = None, lo
    for t in np.arange(lo, hi + 1e-6, 0.5):
        a = int(t * SR)
        w = x[a: a + int(length * SR)]
        head, tail = w[:xf], w[-xf:]
        lvl = abs(fs.rms_db(head) - fs.rms_db(tail))
        hs = np.abs(np.fft.rfft(head.mean(axis=1)))[:4000]
        ts = np.abs(np.fft.rfft(tail.mean(axis=1)))[:4000]
        spec = 1 - np.corrcoef(np.log(hs + 1e-9), np.log(ts + 1e-9))[0, 1]
        # also avoid windows with a big transient that would repeat audibly every cycle
        blocks = w[: len(w) // (SR // 4) * (SR // 4)].reshape(-1, SR // 4, 2)
        env = 20 * np.log10(np.sqrt(np.mean(blocks ** 2, axis=(1, 2))) + 1e-9)
        spike = max(0.0, float(env.max() - np.median(env)) - 10.0)
        score = lvl + 4 * spec + 0.5 * spike
        if best is None or score < best:
            best, best_t = score, float(t)
    return best_t


def seam_report(loop):
    """Level jump across the wrap point (last 50 ms vs first 50 ms), in dB."""
    n = int(0.05 * SR)
    return round(abs(float(fs.rms_db(loop[-n:]) - fs.rms_db(loop[:n]))), 2)


def process_loop(p, audio):
    start = best_loop_start(audio, p["search"], p["length"])
    seg = audio[int(start * SR): int((start + p["length"]) * SR)]
    seg = notch_mains(highpass(seg, p.get("hp", 0)), p.get("notch", 0))
    loop = fs.make_loop(seg, LOOP_XFADE_S)
    return fs.normalize(loop, LOOP_PEAK_DB), (round(start, 2), round(start + p["length"], 2))


def process_oneshot(p, audio):
    a, b = p["region"] if p.get("region") else (0.0, len(audio) / SR)
    seg = audio[int(a * SR): int(b * SR)]
    seg = notch_mains(highpass(seg, p.get("hp", 0)), p.get("notch", 0))
    mono = seg.mean(axis=1)
    mono = fs.trim_silence(mono, threshold_db=-45.0, pad_s=0.01)
    # If the region was cut while the sound is still going, a 5 ms fade-out clicks off audibly;
    # give it a short natural release instead. Otherwise the standard 5 ms fades.
    tail = mono[-int(0.05 * SR):]
    still_going = fs.rms_db(tail) > fs.rms_db(mono) - 12
    out_fade = min(0.25, len(mono) / SR * 0.1) if still_going else 0.005
    mono = fs.fade(mono, 0.005, max(0.005, out_fade))
    return fs.normalize(mono, ONESHOT_PEAK_DB), (round(a, 2), round(b, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="asset names to (re)build")
    ap.add_argument("--no-credit", action="store_true", help="do not touch freesound_credits.json / CREDITS.md")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path, analysis_path = OUT / "manifest.json", OUT / "_analysis.json"
    manifest = {e["asset"]: e for e in json.loads(manifest_path.read_text(encoding="utf-8"))} if manifest_path.exists() else {}
    analysis = json.loads(analysis_path.read_text(encoding="utf-8")) if analysis_path.exists() else {}

    picks = [p for p in PICKS if not args.only or p["asset"] in args.only]
    for p in picks:
        hit = hit_by_id(p["id"])
        if not licence_ok(hit):
            raise SystemExit(f"{p['asset']}: {p['id']} is not CC0 ({hit['license']}); pick a CC0 alternate")
        audio = fs.fetch(hit)
        src = measure(audio)
        out, used = (process_loop if p["kind"] == "loop" else process_oneshot)(p, audio)
        fs.write_wav(OUT / f"{p['asset']}.wav", out)
        res = measure(out)
        info = {"freesound_id": p["id"], "source_name": hit["name"], "region_s": used, "highpass_hz": p.get("hp", 0),
                "duration_s": round(len(out) / SR, 2), "source": src, "result": res}
        if p["kind"] == "loop":
            info["seam_jump_db"] = seam_report(out)
        analysis[p["asset"]] = info
        manifest[p["asset"]] = {
            "asset": p["asset"], "file": f"{p['asset']}.wav", "ue_folder": UE_FOLDER, "loop": p["kind"] == "loop",
            "replaces_synth": p["replaces"], "freesound_id": p["id"], "use": p["use"],
        }
        warn = []
        if src["clip_pct"] > 0.01:
            warn.append(f"source clips {src['clip_pct']}%")
        if res["mains_peak_db_at_hz"][0] > 15:
            warn.append(f"mains-like peak {res['mains_peak_db_at_hz'][0]} dB at {res['mains_peak_db_at_hz'][1]} Hz")
        print(f"{p['asset']:<28} {p['id']:>7} {used} -> {info['duration_s']:5.1f}s rms {res['rms_db']:6.1f} flat {res['flatness']:.3f} "
              f"low {res['low_below_120hz_pct']:4.1f}% hum {res['hum_ratio']:.2f}"
              + (f" seam {info['seam_jump_db']} dB" if p["kind"] == "loop" else "") + (f"  WARN {'; '.join(warn)}" if warn else ""))
        if not args.no_credit:
            region = f"{used[0]}-{used[1]} s" if p["kind"] == "oneshot" and p.get("region") else (
                f"{used[0]}-{used[1]} s, looped ({LOOP_XFADE_S} s crossfade)" if p["kind"] == "loop" else "whole file")
            notes = region + (f", high-pass {p['hp']} Hz" if p.get("hp") else "") + (
                f", {p['notch']} Hz hum notched" if p.get("notch") else "")
            fs.credit(p["asset"], hit, alternates=[hit_by_id(a) for a in p["alts"][:3]], notes=notes)

    ordered = [manifest[k] for k in sorted(manifest)]
    manifest_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"\n{len(picks)} sounds -> {OUT}")


if __name__ == "__main__":
    main()
