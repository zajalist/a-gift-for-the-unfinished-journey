#!/usr/bin/env python3
"""The Low Voice's back room: a quiet room tone loop and six small room one-shots.

The host broadcasts from the quiet back room of a small valley post office, at night, during a storm.
Everything is built from Freesound recordings (CC0 where possible, CC-BY credited) plus processing.

Writes to <project>/Saved/GameAudio/Radio/ (48 kHz 16-bit):

    SFX_Station_RoomTone_Loop           stereo, 75 s seamless loop, -30 LUFS integrated
        (a.k.a. AMB_Radio_StudioRoom_Night_Loop; the story data asks for SFX_Station_RoomTone_Loop)
        - room ambience: a quiet kitchen at night (kyles, CC0)
        - a very low valve-amp hum, 100/150 Hz (Aldergrove_Studio, CC-BY)
        - the storm outside, muffled through wall and window: wind howling at a window (lastraindrop, CC0)
        - 3 soft window rattles (Profispiesser, CC0), 2 kettle-cooling ticks (from Manim8's kettle, CC0),
          1 chair creak (Greg_Surr, CC0), all rare and quiet
    SFX_Station_Room_PaperRustle_01     mono, peak -12 dBFS
    SFX_Station_Room_MugDown_01         mono, peak -12 dBFS
    SFX_Station_Room_ChairCreak_01      mono, peak -12 dBFS
    SFX_Station_Room_KettleClick_01     mono, peak -12 dBFS
    SFX_Station_Room_SwitchClick_01     mono, peak -12 dBFS
    SFX_Station_Room_MatchStrike_01     mono, peak -12 dBFS

No voices, no music, no tones (the hum is a recorded mains/valve hum, kept ~30 dB under the room).
Bed layers are looped with an equal-power crossfade to exactly the loop length, then filtered circularly
(FFT), and events are placed modulo the loop length, so the loop is seamless by construction.

    python Tools/Audio/make_station_room.py          # fetch (cached), build, write, credit, manifest, check
    python Tools/Audio/make_station_room.py --check  # only check the files already written

Offline only: never touches Unreal. Import target: /Game/SaskartaGaea/Audio/Station/ (see docs/story/station.json).
"""
import json
import pathlib
import sys

import numpy as np
import pyloudnorm
import soundfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402

SR = fs.SR
ROOT = fs.ROOT
OUT = ROOT / "Saved" / "GameAudio" / "Radio"
MANIFEST = OUT / "manifest.json"
UE_FOLDER = "/Game/SaskartaGaea/Audio/Station"
LOOP_NAME = "SFX_Station_RoomTone_Loop"
LOOP_ALIAS = "AMB_Radio_StudioRoom_Night_Loop"
LOOP_S = 75.0
LOOP_LUFS = -30.0
SHOT_PEAK = -12.0

SRC = {
    "room": 635728,      # kyles: room tone medium apartment kitchen night quiet (CC0)
    "hum": 437622,       # Aldergrove_Studio: Mesa_Tremoverb_tube-hum (CC-BY)
    "storm": 716989,     # lastraindrop: winter wild wind howled through the windows (CC0)
    "rattle": 583058,    # Profispiesser: wood window door rattle, wind, far (CC0)
    "creak_bed": 590157,  # Greg_Surr: Creaking Wood 9 (CC0)
    "paper": 181774,     # keweldog: rustling paper (CC0)
    "mug": 513775,       # lartti: putting coffee mug to table (CC0)
    "chair": 590158,     # Greg_Surr: Creaking Wood 8 (CC0)
    "kettle": 469124,    # Manim8: Kettle_Switch_On (CC0)
    "switch": 348222,    # tbrook: Switch Light 01 (CC0)
    "match": 423811,     # scalywhale: Match strike 03 (CC0)
}
_hits = {}


def hit(key):
    if key not in _hits:
        _hits[key] = fs._get(f"/sounds/{SRC[key]}/", {"fields": fs.FIELDS})
    return _hits[key]


def db(x):
    return 10 ** (x / 20)


def cfilt(x, lo=None, hi=None, order=2):
    """Circular (FFT) Butterworth-shaped band filter; keeps a loop seamless."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.ones_like(f)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * order))
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** (2 * order))
    X = np.fft.rfft(x, axis=0)
    return np.fft.irfft(X * (g[:, None] if x.ndim == 2 else g), n, axis=0).astype(np.float32)


def detone(x, width_hz=12.0, over_db=8.0):
    """Circular spectral clamp: flatten steady narrow tones (fridge hum, whines) down to the local noise floor."""
    from scipy.ndimage import uniform_filter1d
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    mag = np.abs(X) + 1e-12
    lm = np.log(mag if X.ndim == 1 else mag.mean(1))
    floor = uniform_filter1d(lm, max(3, int(width_hz * n / SR)), mode="nearest")
    excess = lm - floor - over_db / 20 * np.log(10)
    g = np.exp(-np.maximum(excess, 0.0))
    return np.fft.irfft(X * (g[:, None] if X.ndim == 2 else g), n, axis=0).astype(np.float32)


def env_db(m, win):
    k = len(m) // win
    return 20 * np.log10(np.sqrt((m[: k * win].reshape(k, win) ** 2).mean(1)) + 1e-9)


def steadiest(x, seg_s, win_s=0.25, avoid_loud=True):
    """Start sample of the seg_s stretch with the smallest level spread (and, optionally, no loud events)."""
    m = x.mean(1) if x.ndim == 2 else x
    win = int(win_s * SR)
    e = env_db(m, win)
    w = int(seg_s / win_s)
    best, best_i = 1e9, 0
    for i in range(0, len(e) - w, 2):
        s = e[i:i + w]
        score = s.std() + (0.5 * max(0.0, s.max() - np.median(e) - 6) if avoid_loud else 0)
        if score < best:
            best, best_i = score, i
    return best_i * win


def loop_to(x, n, xfade_s):
    """Exactly n samples, seamless: take n + crossfade and fold the tail into the head."""
    need = n + int(xfade_s * SR)
    if len(x) < need:
        reps = int(np.ceil(need / len(x))) + 1
        x = np.concatenate([x] * reps)
    return fs.make_loop(x[:need], xfade_s)


def add_wrapped(bed, clip, at):
    n = len(bed)
    a = int(at * SR) % n
    c = clip if clip.ndim == 2 else np.stack([clip, clip], 1)
    end = a + len(c)
    if end <= n:
        bed[a:end] += c
    else:
        bed[a:] += c[: n - a]
        bed[: end - n] += c[n - a:]


def pan(clip, p):
    """Mono clip to stereo, p in [-1, 1], equal power."""
    th = (p + 1) * np.pi / 4
    return np.stack([clip * np.cos(th), clip * np.sin(th)], 1).astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def cut(x, a_s, b_s, fi=0.003, fo=0.03):
    y = x[int(a_s * SR): int(b_s * SR)]
    return fs.fade(y, fi, fo)


def events_from(x, thresh_rel_db=-18, min_gap_s=1.5, pre_s=0.05, post_s=1.2):
    """Transient events: (start, end) in samples around envelope peaks above median + thresh."""
    m = x.mean(1) if x.ndim == 2 else x
    win = int(0.02 * SR)
    e = env_db(m, win)
    lim = e.max() + thresh_rel_db
    out, last = [], -1e9
    for i in np.nonzero(e > lim)[0]:
        if (i - last) * 0.02 > min_gap_s:
            out.append((max(0, int(i * win - pre_s * SR)), min(len(m), int(i * win + post_s * SR))))
        last = i
    return out


# ------------------------------------------------------------------ loop
def build_loop():
    rng = np.random.default_rng(2026_09_28)
    n = int(LOOP_S * SR)
    notes = {}

    # room ambience (stereo), the quietest steady stretch, looped with a 4 s crossfade
    room_src = fs.fetch(hit("room"))
    s = steadiest(room_src, LOOP_S + 5)
    room = detone(cfilt(loop_to(room_src[s:], n, 4.0), 35, 9000))
    room /= rms(room)
    notes["room"] = f"from {s / SR:.1f} s, {LOOP_S + 4:.0f} s looped (4 s crossfade), 35 Hz-9 kHz, steady tones (fridge hum) flattened"

    # valve hum (mono source): steadiest 12 s, looped (1.5 s crossfades), 60-400 Hz, slightly widened
    hum_src = fs.fetch(hit("hum"), channels=1)[:, 0]
    s = steadiest(hum_src, 12, avoid_loud=False)
    hum_seg = hum_src[s: s + 12 * SR]
    hum = cfilt(loop_to(hum_seg, n, 1.5), 60, 400, order=3)
    hum = hum / rms(hum)
    hum = np.stack([hum, np.roll(hum, int(0.0007 * SR))], 1)
    notes["hum"] = f"steadiest 12 s from {s / SR:.1f} s, repeated with 1.5 s crossfades, 60-400 Hz, -30 dB under the room"

    # storm outside: wind howling at a window, a moderate stretch, muffled (through wall and glass)
    storm_src = fs.fetch(hit("storm"))
    m = storm_src.mean(1)
    e = env_db(m, SR // 4)
    w = int((LOOP_S + 6) * 4)
    # a stretch with movement but without the very loudest gusts: median level near the file median, capped max
    best, bi = 1e9, 0
    med = np.median(e)
    for i in range(0, len(e) - w, 4):
        seg = e[i:i + w]
        score = abs(np.median(seg) - med) + 0.6 * max(0.0, seg.max() - (med + 12)) + (0 if seg.std() > 2.5 else 3)
        if score < best:
            best, bi = score, i
    s = bi * (SR // 4)
    storm = loop_to(storm_src[s:], n, 6.0)
    muffled = cfilt(storm, 40, 650, order=2)                      # the wall
    glass = cfilt(storm, 900, 2600, order=2) * db(-20)             # a little through the window pane
    storm = detone(muffled + glass)
    storm /= rms(storm)
    notes["storm"] = f"from {s / SR:.1f} s, {LOOP_S + 6:.0f} s looped (6 s crossfade), low-passed at 650 Hz plus a -20 dB 0.9-2.6 kHz window-pane band"

    bed = room * db(0) + storm * db(-1.5) + hum * db(-30)

    # rare events: 3 window rattles, 2 kettle-cooling ticks, 1 chair creak
    rat_src = fs.fetch(hit("rattle"))
    evs = events_from(rat_src, -14, 2.0, 0.05, 1.0)
    rng.shuffle(evs)
    rattles = []
    for (a, b) in evs[:3]:
        c = fs.fade(rat_src[a:b].mean(1), 0.01, 0.3)
        c = cfilt(c, 80, 2200, order=2)
        rattles.append(c / (np.abs(c).max() + 1e-9))
    notes["rattle"] = f"{len(rattles)} rattle hits cut from the file, 80 Hz-2.2 kHz, placed at ~10 dB over the bed rms peak-wise"

    kettle = fs.fetch(hit("kettle"), channels=1)[:, 0]
    tick = cut(kettle, 1.12, 1.22, 0.001, 0.05)                    # the small after-tick of the switch
    tick = cfilt(tick, 1500, 7000, order=2)
    tick /= np.abs(tick).max() + 1e-9
    tick2 = cfilt(cut(kettle, 0.795, 0.86, 0.001, 0.04), 2000, 8000, order=2)
    tick2 /= np.abs(tick2).max() + 1e-9
    notes["kettle_ticks"] = "two small metallic ticks cut from the switch recording (0.80 s and 1.12 s), high-passed"

    creak = fs.fetch(hit("creak_bed"), channels=1)[:, 0]
    creak = fs.fade(creak[int(0.25 * SR): int(1.9 * SR)], 0.05, 0.3)
    creak = cfilt(creak, 120, 5000, order=2)
    creak /= np.abs(creak).max() + 1e-9
    notes["creak"] = "0.25-1.9 s of the creak, 120 Hz-5 kHz"

    bed_peak_ref = rms(bed)
    placements = []
    for at, c, g, p, what in [
        (7.3, rattles[0], 7.0, -0.35, "window rattle"),
        (23.8, tick, -3.0, 0.4, "kettle tick"),
        (31.5, rattles[1 % len(rattles)], 4.0, -0.45, "window rattle"),
        (44.2, creak, 3.0, 0.2, "chair creak"),
        (57.6, tick2, -5.0, 0.4, "kettle tick"),
        (66.9, rattles[2 % len(rattles)], 5.5, -0.3, "window rattle (across the seam)"),
    ]:
        add_wrapped(bed, pan(c * bed_peak_ref * db(g), p), at)
        placements.append({"at_s": at, "what": what, "gain_db_vs_bed_rms": g, "pan": p})

    meter = pyloudnorm.Meter(SR)
    # measure over two passes of the loop so the integrated value represents the looping bed
    lufs = meter.integrated_loudness(np.concatenate([bed, bed]))
    bed = bed * db(LOOP_LUFS - lufs)
    return bed.astype(np.float32), notes, placements


# ------------------------------------------------------------------ one-shots
def build_shots():
    shots = {}

    def mono(key):
        return fs.fetch(hit(key), channels=1)[:, 0]

    x = mono("paper")
    shots["SFX_Station_Room_PaperRustle_01"] = (cfilt(cut(x, 0.36, 2.9, 0.01, 0.25), 120), "paper",
        "0.36-2.9 s, high-passed 120 Hz", "The host shuffles a page (between segments, before a letter).")
    x = mono("mug")
    shots["SFX_Station_Room_MugDown_01"] = (cfilt(cut(x, 0.68, 1.3, 0.003, 0.12), 60), "mug",
        "0.68-1.3 s (the set-down and its ring), high-passed 60 Hz", "A mug set down on the desk.")
    x = mono("chair")
    shots["SFX_Station_Room_ChairCreak_01"] = (cfilt(cut(x, 0.0, 2.3, 0.02, 0.3), 80), "chair",
        "0-2.3 s, high-passed 80 Hz", "The host's wooden chair creaks (leaning back).")
    x = mono("kettle")
    shots["SFX_Station_Room_KettleClick_01"] = (cfilt(cut(x, 0.76, 1.45, 0.002, 0.1), 80), "kettle",
        "0.76-1.45 s (the click and its after-tick), high-passed 80 Hz", "The kettle switch clicks off.")
    x = mono("switch")
    shots["SFX_Station_Room_SwitchClick_01"] = (cfilt(fs.trim_silence(x, -60, 0.005), 60), "switch",
        "whole click, silence trimmed, high-passed 60 Hz", "A switch on the old desk equipment.")
    x = mono("match")
    shots["SFX_Station_Room_MatchStrike_01"] = (cfilt(cut(x, 0.0, 1.4, 0.004, 0.2), 80), "match",
        "whole strike and flare (1.4 s), high-passed 80 Hz", "A match struck (a candle or the stove when the power flickers).")
    return {k: (fs.fade(fs.normalize(v[0], SHOT_PEAK), 0.002, 0.02), *v[1:]) for k, v in shots.items()}


# ------------------------------------------------------------------ check
def check():
    meter = pyloudnorm.Meter(SR)
    ok = True
    x, sr = soundfile.read(str(OUT / f"{LOOP_NAME}.wav"), dtype="float32")
    assert sr == SR and x.ndim == 2 and x.shape[1] == 2, (sr, x.shape)
    d = len(x) / SR
    lufs = meter.integrated_loudness(np.concatenate([x, x]))
    pk = 20 * np.log10(np.abs(x).max())
    # seam: sample jump across the wrap vs typical sample-to-sample step
    jump = np.abs(x[0] - x[-1]).max()
    step = np.percentile(np.abs(np.diff(x, axis=0)).max(1), 99.9)
    seam_rms = abs(fs.rms_db(x[:SR // 2]) - fs.rms_db(x[-SR // 2:]))
    good = 60 <= d <= 90 and abs(lufs - LOOP_LUFS) < 0.5 and pk < -3 and jump <= step
    ok &= good
    print(f"{'ok ' if good else 'BAD'} {LOOP_NAME}: {d:.1f} s, {lufs:.2f} LUFS, peak {pk:.1f} dBFS, seam jump {jump:.5f} (p99.9 step {step:.5f}), seam level gap {seam_rms:.2f} dB")
    for name in SHOT_NAMES:
        y, sr = soundfile.read(str(OUT / f"{name}.wav"), dtype="float32")
        pk = 20 * np.log10(np.abs(y).max())
        good = sr == SR and y.ndim == 1 and abs(pk - SHOT_PEAK) < 0.2
        ok &= good
        print(f"{'ok ' if good else 'BAD'} {name}: {len(y) / SR:.2f} s, peak {pk:.2f} dBFS")
    return ok


SHOT_NAMES = ["SFX_Station_Room_PaperRustle_01", "SFX_Station_Room_MugDown_01", "SFX_Station_Room_ChairCreak_01",
              "SFX_Station_Room_KettleClick_01", "SFX_Station_Room_SwitchClick_01", "SFX_Station_Room_MatchStrike_01"]


def main():
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    loop, notes, placements = build_loop()
    fs.write_wav(OUT / f"{LOOP_NAME}.wav", loop)
    shots = build_shots()
    for name, (x, *_rest) in shots.items():
        fs.write_wav(OUT / f"{name}.wav", x)

    # credits (one entry per asset and source; the loop's secondary layers get their own keys)
    fs.credit(LOOP_NAME, hit("room"), notes=f"room layer: {notes['room']}")
    fs.credit(f"{LOOP_NAME} (hum)", hit("hum"), notes=f"hum layer: {notes['hum']}")
    fs.credit(f"{LOOP_NAME} (storm)", hit("storm"), notes=f"storm layer: {notes['storm']}")
    fs.credit(f"{LOOP_NAME} (rattles)", hit("rattle"), notes=notes["rattle"])
    fs.credit(f"{LOOP_NAME} (kettle ticks)", hit("kettle"), notes=notes["kettle_ticks"])
    fs.credit(f"{LOOP_NAME} (chair creak)", hit("creak_bed"), notes=notes["creak"])
    for name, (_x, key, note, _use) in shots.items():
        fs.credit(name, hit(key), notes=note)

    # manifest: add/replace these entries in the radio manifest's sound list
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mine = set([LOOP_NAME] + SHOT_NAMES)
    sounds = [s for s in man["sounds"] if s["id"] not in mine]

    def src(key, note):
        h = hit(key)
        lic = "CC0" if "zero" in h["license"] else "CC-BY 4.0" if "/by/4" in h["license"] else "CC-BY" if "/by/" in h["license"] else h["license"]
        return f"freesound {h['id']} ({h['username']}, {lic}): {note}"

    meter = pyloudnorm.Meter(SR)
    sounds.append({
        "id": LOOP_NAME, "aliases": [LOOP_ALIAS], "type": "bed", "loop": True, "channels": 2,
        "suggested_use": "The Low Voice's back room (a small valley post office at night, in a storm): room tone under the host, through the radio chain. Last-resort bed between segments (docs/story/station.json room_tone_asset).",
        "suggested_volume": 1.0,
        "file": f"{LOOP_NAME}.wav", "ue_folder": UE_FOLDER, "ue_path": f"{UE_FOLDER}/{LOOP_NAME}.{LOOP_NAME}",
        "generator": "Tools/Audio/make_station_room.py",
        "duration_s": round(len(loop) / SR, 2), "lufs": round(float(meter.integrated_loudness(np.concatenate([loop, loop]))), 2),
        "peak_dbfs": round(float(20 * np.log10(np.abs(loop).max())), 2),
        "events": placements,
        "sources": [src("room", notes["room"]), src("hum", notes["hum"]), src("storm", notes["storm"]),
                    src("rattle", notes["rattle"]), src("kettle", notes["kettle_ticks"]), src("creak_bed", notes["creak"])],
    })
    for name, (x, key, note, use) in shots.items():
        sounds.append({
            "id": name, "type": "oneshot", "loop": False, "channels": 1, "suggested_use": use, "suggested_volume": 0.8,
            "file": f"{name}.wav", "ue_folder": UE_FOLDER, "ue_path": f"{UE_FOLDER}/{name}.{name}",
            "generator": "Tools/Audio/make_station_room.py",
            "duration_s": round(len(x) / SR, 2), "peak_dbfs": SHOT_PEAK, "sources": [src(key, note)],
        })
    man["sounds"] = sounds
    MANIFEST.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
