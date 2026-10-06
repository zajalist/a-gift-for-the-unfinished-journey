"""Build the title cinematic (Task L3, reshot in Task TITLE): LS_Saskarta_Title, a 40 s looping
Level Sequence of four 10 s shots that drives the existing TitleCam (a possessable, so the level
still has exactly one CineCameraActor): its transform, its lens (focal length, focus distance,
aperture on the camera component's child binding), a fade track that dips through black at every
cut and at the loop point, and the flat WindOffset track through MPC_Saskarta_Sky (Task SKY).
Also places the level actor that plays it, TitleCam's placed pose, and the dock's streaming source.

    python Tools/Look/build_title_sequence.py check       # offline: framing of every shot key, no editor
    python Tools/Look/build_title_sequence.py build       # create/update LS_Saskarta_Title (saves it)
    python Tools/Look/build_title_sequence.py place       # TitleSequencePlayer (LevelSequenceActor)
    python Tools/Look/build_title_sequence.py camera      # TitleCam's placed pose = shot 1's first frame
    python Tools/Look/build_title_sequence.py streaming   # TitleDockStreamingSource at the dock
    python Tools/Look/build_title_sequence.py captures [--shots name ...]   # one key frame per shot
    python Tools/Look/build_title_sequence.py read        # print the sequence's current state
    python Tools/Look/build_title_sequence.py wind        # re-key only the WindOffset track, then save
    python Tools/Look/build_title_sequence.py all         # check, build, place, camera, streaming, captures

User brief (Task TITLE): "the cinematic camera is ugly not cinematic whatsoever we dont see anything
loaded". The shots (SHOTS below) are authored offline against the Gaea heightmap and the road
spline (Tools/Story/build_road_profile.py): each key is a road-relative anchor plus the screen
position of the High Voice beacon's crown, and aim() solves the rotation that puts it there.
"check" projects the crown, the summit and point 0 through every key, reports the horizon line
and how much road is in frame, and fails if the crown (and its vertical beam) could cross the
title text (TITLE_BOX_NDC). Composition rules: the crown on the right third, the horizon low,
foreground / road / mountain layered in depth, the long lens for compression, slow moves only.

Readiness: TitleCam's placed pose is shot 1's first frame, and PC_Saskarta.PollIntro holds the
studio intro until USaskartaReadiness (Task L7) reports everything ready at that camera (World
Partition streaming complete, PCG idle, no pending PSOs, textures and grass settled) or
IntroMaxTime passes. All four shots are within ~150 m, so one streamed area serves the loop.

PC_Saskarta.BeginTitle looks up the `TitleSequencePlayer` level actor (a LevelSequenceActor, not
spatially loaded, autoplay off) and plays it looping; if that actor is missing, TitleCam's placed
pose (shot 1's first frame) is the fallback view.

Runs through Hayba python_run (5 s per call, banned words checked). Wrap in
Tools/GameFlow/editor_gate.py acquire/release. `build` saves the sequence; `place`, `camera` and
`streaming` save only their own actor packages.
"""
import argparse
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))

from apply_look import python_run, check_banned  # noqa: E402
from build_road_profile import SPLINE_POINTS_CM, Terrain, Road, HEIGHTMAP, SUMMIT_HINT_CM  # noqa: E402

SEQ_FOLDER = "/Game/SaskartaGaea/GameFlow/Cinematics"
SEQ_NAME = "LS_Saskarta_Title"
SEQ_FULL = f"{SEQ_FOLDER}/{SEQ_NAME}"
CAM_LABEL = "TitleCam"
PLAYER_LABEL = "TitleSequencePlayer"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"

DURATION_S = 40.0
FPS = 30
TICKS_PER_S = 24000  # LevelSequence tick resolution (confirmed live: get_tick_resolution())
ASPECT = 16.0 / 9.0
SENSOR_W_MM = 23.76  # TitleCam's filmback (CineCamera default 16:9 DSLR); 35 mm = 37.5 deg hfov
HFOV_DEG = 37.5      # the placed TitleCam's own lens (Task L2); the shots below key their own

# Task TITLE (user: "the cinematic camera is ugly not cinematic whatsoever"): four shots of
# SHOT_S seconds, cut under a dip through black (CUT_FADE_S each side, Sequencer fade track).
# The 40 s loop length and the flat WindOffset track (Task SKY) are unchanged.
SHOT_S = 10.0
CUT_FADE_S = 1.25

# Every shot sits on one hill (about 90 m around map position 507000, 282000 cm), the only rise
# near the road that stands above the valley fog sea (its top is at -195 m; the Valley fog's top
# is near -230 m) while still seeing the summit and the beacon (1.5 deg and 0.7 deg clear over
# the ridges). From here the frame layers the hill's grass (foreground), the fog sea with the road
# running into it 100 m below (midground, spline points 34-30), and the mountain rising out of the
# fog with the road's switchbacks climbing to the High Voice (background, 2.6-2.9 km).
# One small cluster means World Partition streams one area for the whole loop and no cut lands on
# unloaded ground. The dock, 2.2 km away, stays loaded through TitleDockStreamingSource (see
# STREAM_SOURCE), so Start never waits on it.
# anchor = ("xy", x cm, y cm, metres above the terrain) or (road m from the dock, metres right of
# the centreline, metres above the terrain, metres forward); ndc = where the beacon's crown sits on
# screen (x -1 left .. +1 right, y -1 bottom .. +1 top). The name and subtitle live at x < 0.10,
# y 0.06-0.56, so the crown (and its vertical beam) is kept at x >= 0.28 in every key.
SHOTS = [
    # 1. In the hill's grass, 24 mm, slow push: fog sea below, the mountain on the right third.
    {"name": "hill_grass", "lens_mm": 24.0, "aperture": 8.0,
     "start": ("xy", 507000, 284000, 0.9), "end": ("xy", 506650, 284300, 1.0),
     "ndc_start": (0.34, 0.42), "ndc_end": (0.31, 0.42)},
    # 2. Crane up from the grass, 35 mm: the fog sea opens below as the camera rises 13 m.
    {"name": "crane", "lens_mm": 35.0, "aperture": 8.0,
     "start": ("xy", 509000, 281000, 1.2), "end": ("xy", 509000, 281000, 14.0),
     "ndc_start": (0.34, 0.34), "ndc_end": (0.34, 0.42)},
    # 3. Long lens, 85 mm, slow pan: the road's last switchbacks and the High Voice, compressed.
    {"name": "long_lens", "lens_mm": 85.0, "aperture": 11.0,
     "start": ("xy", 508500, 272500, 3.0), "end": ("xy", 508500, 272500, 3.0),
     "ndc_start": (0.42, 0.12), "ndc_end": (0.32, 0.12)},
    # 4. Low on the ridge, 20 mm, slow truck: the slope as a dark foreground wedge, the whole view.
    {"name": "ridge_low", "lens_mm": 20.0, "aperture": 5.6,
     "start": ("xy", 505000, 288500, 0.5), "end": ("xy", 504700, 288900, 0.6),
     "ndc_start": (0.34, 0.45), "ndc_end": (0.32, 0.45)},
]
TITLE_BOX_NDC = (-0.92, 0.10, 0.06, 0.56)  # x0, x1, y0, y1 of the name (two lines) and subtitle, measured at 1920x1080
BEACON_MIN_X = 0.28

# Task SKY (user: "the sky has too much speed and variation in the main title screen"): the ramp
# is held flat. M_Saskarta_Cloud adds WindOffset to both the wind direction and the time term and
# then multiplies them, so the noise moves by (wind + WindOffset) * (engine time / 3.9 s + WindOffset).
# L3's ramp (0 -> 3 over 40 s) therefore sped the clouds up 1x -> 5x -> 9x across the loop (and far
# more late in a session, where engine time is large), then snapped back at every loop. The
# gentle drift now comes from the material's own time term alone, slowed in MI_Saskarta_Cloud
# (apply_look.CLOUD_WIND_CONTROLS). The track stays, keyed flat, so the sequence still owns the value.
WIND_OFFSET_START = 0.0
WIND_OFFSET_END = 0.0

BEACON_ACTOR_CM = (298079.6, 483050.0, 10818.7)  # HighVoice (Task L2 report)
BEACON_CROWN_OFFSET_Z_CM = 4300.0                 # crown centre, +43 m (Task L2 report)


def _terrain():
    global _TERRAIN
    if _TERRAIN is None:
        _TERRAIN = Terrain(HEIGHTMAP)
    return _TERRAIN


_TERRAIN = None


def targets():
    """point0 (the road's destination / the beacon's site), the beacon's crown centre, and the
    mountain's summit -- world cm."""
    terrain = _terrain()
    sx, sy, sz_m = terrain.peak_near(*SUMMIT_HINT_CM)
    summit = (float(sx), float(sy), sz_m * 100.0)
    point0 = tuple(float(v) for v in SPLINE_POINTS_CM[0])
    beacon = (BEACON_ACTOR_CM[0], BEACON_ACTOR_CM[1], BEACON_ACTOR_CM[2] + BEACON_CROWN_OFFSET_Z_CM)
    return {"point0": point0, "beacon": beacon, "summit": summit}


def _bearing(frm, to):
    return math.degrees(math.atan2(to[1] - frm[1], to[0] - frm[0]))


def _elevation(frm, to):
    return math.degrees(math.atan2(to[2] - frm[2], math.hypot(to[0] - frm[0], to[1] - frm[1])))


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


# ----------------------------------------------------------------------------- lens and projection

def hfov_deg(lens_mm):
    """Horizontal FOV of TitleCam's filmback (the CineCamera default 16:9 DSLR, 23.76 mm wide):
    35 mm gives the 37.5 deg that Task L2 read off the placed camera."""
    return 2.0 * math.degrees(math.atan(SENSOR_W_MM / 2.0 / lens_mm))


def vfov_deg(lens_mm):
    return 2.0 * math.degrees(math.atan(SENSOR_W_MM / ASPECT / 2.0 / lens_mm))


def _basis(pitch, yaw):
    """UE camera basis (left-handed, Z up): forward, right, up for a roll-free rotator."""
    p, y = math.radians(pitch), math.radians(yaw)
    f = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
    r = (-math.sin(y), math.cos(y), 0.0)
    u = (-math.sin(p) * math.cos(y), -math.sin(p) * math.sin(y), math.cos(p))
    return f, r, u


def project(pos, pitch, yaw, lens_mm, point):
    """Screen position of a world point: NDC x (-1 left .. +1 right), y (-1 bottom .. +1 top),
    and the depth along the view (cm; <= 0 means behind the camera)."""
    f, r, u = _basis(pitch, yaw)
    v = tuple(point[i] - pos[i] for i in range(3))
    depth = sum(v[i] * f[i] for i in range(3))
    if depth <= 0:
        return None, None, depth
    x = sum(v[i] * r[i] for i in range(3)) / depth / math.tan(math.radians(hfov_deg(lens_mm) / 2))
    y = sum(v[i] * u[i] for i in range(3)) / depth / math.tan(math.radians(vfov_deg(lens_mm) / 2))
    return x, y, depth


def aim(pos, point, lens_mm, ndc):
    """Pitch and yaw that put `point` at screen position `ndc` (x, y) for this lens (a few
    Newton steps from the direct bearing; converges to < 1e-6 NDC)."""
    yaw, pitch = _bearing(pos, point), _elevation(pos, point)
    for _ in range(30):
        x, y, _ = project(pos, pitch, yaw, lens_mm, point)
        ex, ey = x - ndc[0], y - ndc[1]
        if abs(ex) < 1e-7 and abs(ey) < 1e-7:
            break
        # d(ndc)/d(angle) is about 1 / tan(fov/2) per radian near the axis.
        yaw += math.degrees(ex * math.tan(math.radians(hfov_deg(lens_mm) / 2)))
        pitch += math.degrees(ey * math.tan(math.radians(vfov_deg(lens_mm) / 2)))
    return pitch, yaw


def horizon_y(pitch, lens_mm):
    """Screen y of the camera-height horizon (a level ray): -tan(pitch) / tan(vfov/2)."""
    return -math.tan(math.radians(pitch)) / math.tan(math.radians(vfov_deg(lens_mm) / 2))


# ----------------------------------------------------------------------------- the shots

_ROAD = None


def _road():
    global _ROAD
    if _ROAD is None:
        _ROAD = Road(SPLINE_POINTS_CM)
    return _ROAD


def road_frame(s_m):
    """Road position (cm, xy) at walk distance s from the dock, and its unit heading and
    right-hand perpendicular in UE space."""
    road = _road()
    xy = road.xy(s_m)
    a, b = road.xy(max(s_m - 5.0, 0.0)), road.xy(s_m + 5.0)
    hx, hy = float(b[0] - a[0]), float(b[1] - a[1])
    n = math.hypot(hx, hy)
    hx, hy = hx / n, hy / n
    return (float(xy[0]), float(xy[1])), (hx, hy), (-hy, hx)


def anchor_pos(*anchor):
    """World position (cm) of a shot anchor. ("xy", x_cm, y_cm, height_m): a map position,
    `height_m` above the Gaea terrain. (s_m, lateral_m, height_m[, forward_m]): road distance s,
    `lateral_m` to the right of the centreline (negative = left), `forward_m` along the heading."""
    if anchor[0] == "xy":
        _, x, y, height_m = anchor
        return (float(x), float(y), float(_terrain().height(x, y)) * 100.0 + height_m * 100.0)
    s_m, lateral_m, height_m = anchor[:3]
    forward_m = anchor[3] if len(anchor) > 3 else 0.0
    (x, y), (hx, hy), (px, py) = road_frame(s_m)
    x += px * lateral_m * 100.0 + hx * forward_m * 100.0
    y += py * lateral_m * 100.0 + hy * forward_m * 100.0
    z = float(_terrain().height(x, y)) * 100.0 + height_m * 100.0
    return (x, y, z)


def shot_keys():
    """Every shot as (name, t0, t1, lens_mm, focus_cm, (start pos, pitch, yaw), (end pos, pitch,
    yaw)). Rotations are solved so the beacon's crown sits at each key's authored NDC."""
    beacon = targets()["beacon"]
    out = []
    for i, sh in enumerate(SHOTS):
        t0, t1 = i * SHOT_S, (i + 1) * SHOT_S
        keys = []
        for anchor, ndc in ((sh["start"], sh["ndc_start"]), (sh["end"], sh["ndc_end"])):
            pos = anchor_pos(*anchor)
            pitch, yaw = aim(pos, beacon, sh["lens_mm"], ndc)
            keys.append((pos, pitch, yaw))
        focus = sh.get("focus_m")
        focus_cm = focus * 100.0 if focus else math.dist(keys[0][0], beacon)
        out.append((sh["name"], t0, t1, sh["lens_mm"], focus_cm, keys[0], keys[1]))
    return out


def keyframes():
    """Flat (t, pos, (pitch, yaw)) list of every authored key, in time order (the shot starts
    and ends; a cut sits between one shot's end and the next shot's start)."""
    out = []
    for name, t0, t1, lens, focus, (p0, pi0, y0), (p1, pi1, y1) in shot_keys():
        out.append((t0, p0, (pi0, y0)))
        out.append((t1, p1, (pi1, y1)))
    return out


def shot_at(t):
    t = min(max(t, 0.0), DURATION_S - 1e-6)
    return shot_keys()[min(int(t // SHOT_S), len(SHOTS) - 1)]


def pose_at(t):
    """Camera pose at sequence time t: linear within the shot (the Sequencer keys are linear
    inside a shot and held across the cut)."""
    name, t0, t1, lens, focus, (p0, pi0, y0), (p1, pi1, y1) = shot_at(t)
    f = (min(max(t, t0), t1) - t0) / (t1 - t0)
    pos = tuple(p0[i] + (p1[i] - p0[i]) * f for i in range(3))
    return pos, (pi0 + (pi1 - pi0) * f, y0 + (y1 - y0) * f)


def lens_at(t):
    return shot_at(t)[3]


def fade_keys():
    """(t, fade amount) keys for the Sequencer fade track: in from black at t=0, a dip to black
    at each cut, out to black at the loop end (so the loop point is itself a cut)."""
    keys = [(0.0, 1.0), (CUT_FADE_S, 0.0)]
    for i in range(1, len(SHOTS)):
        tc = i * SHOT_S
        keys += [(tc - CUT_FADE_S, 0.0), (tc, 1.0), (tc + CUT_FADE_S, 0.0)]
    keys += [(DURATION_S - CUT_FADE_S, 0.0), (DURATION_S, 1.0)]
    return keys


# ----------------------------------------------------------------------------- check (offline)

def check():
    """Offline framing report for every shot key: the crown, summit and point 0 on screen, the
    horizon line, how much road is in frame, and the crown/beam against the title block."""
    tg = targets()
    road = _road()
    ok = True
    for name, t0, t1, lens, focus, k0, k1 in shot_keys():
        print(f"== {name}: t {t0:.0f}-{t1:.0f} s, {lens:.0f} mm (hfov {hfov_deg(lens):.1f}, "
              f"vfov {vfov_deg(lens):.1f}), focus {focus / 100:.0f} m")
        for label, (pos, pitch, yaw) in (("start", k0), ("end", k1)):
            print(f"   {label}: pos ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f}) pitch {pitch:.2f} yaw {yaw:.2f}"
                  f"  horizon y {horizon_y(pitch, lens):+.2f}")
            for tname, pt in tg.items():
                x, y, d = project(pos, pitch, yaw, lens, pt)
                inside = x is not None and abs(x) <= 1 and abs(y) <= 1
                print(f"      {tname:7s} ndc ({x:+.2f}, {y:+.2f})  {d / 100:.0f} m  {'in' if inside else 'OUT'}"
                      if x is not None else f"      {tname:7s} behind the camera")
            bx, by, _ = project(pos, pitch, yaw, lens, tg["beacon"])
            sx, sy, _ = project(pos, pitch, yaw, lens, tg["summit"])
            x0, x1, y0, y1 = TITLE_BOX_NDC
            beam_hits = x0 <= bx <= x1 and by < y1
            key_ok = bx >= BEACON_MIN_X and abs(bx) <= 0.95 and abs(by) <= 0.9 and not beam_hits
            ok = ok and key_ok
            on = 0
            for s in range(0, int(road.length), 10):
                xy = road.xy(s)
                z = float(_terrain().height(xy[0], xy[1])) * 100.0
                rx, ry, _ = project(pos, pitch, yaw, lens, (float(xy[0]), float(xy[1]), z))
                on += rx is not None and abs(rx) <= 1 and abs(ry) <= 1
            print(f"      road in frame: {on * 10} m;  crown clear of the title: "
                  f"{'yes' if not beam_hits else 'NO'}  {'OK' if key_ok else 'FAIL'}")
    fk = fade_keys()
    print("fade keys", [(round(t, 2), v) for t, v in fk])
    print("ALL SHOTS FRAMED" if ok else "SOME SHOTS FAIL")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- editor transport

def run(script, label):
    ok, out, err = python_run(check_banned(script))
    print(f"--- {label}: {'ok' if ok else 'FAILED'}")
    if out.strip():
        print(out.rstrip())
    if not ok:
        print(err, file=sys.stderr)
        raise SystemExit(1)
    return out


SETUP = """
import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
E = unreal.EditorAssetLibrary
full = '__SEQFULL__'
if E.does_asset_exist(full):
    seq = unreal.load_asset(full)
else:
    seq = AT.create_asset('__SEQNAME__', '__SEQFOLDER__', unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
seq.set_display_rate(unreal.FrameRate(__FPS__, 1))
seq.set_playback_start_seconds(0.0)
seq.set_playback_end_seconds(__DURATION__)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cam = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__CAMLABEL__':
        cam = a
print('cam_found', cam is not None)
binding = None
for b in seq.get_bindings():
    if str(b.get_display_name()) == '__CAMLABEL__':
        binding = b
if binding is None:
    binding = seq.add_possessable(cam)
print('binding', str(binding.get_display_name()))
tform = None
for t in binding.get_tracks():
    if t.get_class().get_name() == 'MovieScene3DTransformTrack':
        tform = t
if tform is None:
    tform = binding.add_track(unreal.MovieScene3DTransformTrack)
for s in list(tform.get_sections()):
    tform.remove_section(s)
tsection = tform.add_section()
tsection.set_range_seconds(0.0, __DURATION__)
print('transform_section_ready', tsection.get_class().get_name())
"""

# Keys go in at tick resolution (24000/s). L3's first version passed tick numbers with the
# default DISPLAY_RATE unit, so its keys sat at 16,000 s and 32,000 s: the 40 s loop showed only
# 0.25 % of the push (about 2 cm) and the title camera was effectively static.
TRANSFORM_KEYS = """
import unreal
seq = unreal.load_asset('__SEQFULL__')
binding = None
for b in seq.get_bindings():
    if str(b.get_display_name()) == '__CAMLABEL__':
        binding = b
tform = None
for t in binding.get_tracks():
    if t.get_class().get_name() == 'MovieScene3DTransformTrack':
        tform = t
section = tform.get_sections()[0]
channels = section.get_all_channels()
print('n_channels', len(channels), str([str(c.get_name()) for c in channels]))
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
MODES = {'linear': unreal.MovieSceneKeyInterpolation.LINEAR, 'constant': unreal.MovieSceneKeyInterpolation.CONSTANT}
KEYS = __KEYS__
for tick, values, mode in KEYS:
    fn = unreal.FrameNumber(int(tick))
    for i, value in enumerate(values):
        channels[i].add_key(fn, float(value), 0.0, TR, MODES[mode])
print('keys_added', sum(c.get_num_keys() for c in channels))
"""

# The lens rides on the camera component's own binding (a child possessable of TitleCam):
# focal length, manual focus distance and aperture, one constant key per shot.
LENS_TRACKS = """
import unreal
seq = unreal.load_asset('__SEQFULL__')
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cam = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__CAMLABEL__':
        cam = a
comp = cam.get_cine_camera_component()
parent = None
child = None
for b in seq.get_bindings():
    if str(b.get_display_name()) == '__CAMLABEL__':
        parent = b
for b in parent.get_child_possessables():
    child = b
if child is None:
    child = seq.add_possessable(comp)
    if not child.get_parent().is_valid():
        child.set_parent(parent)
for tr in list(child.get_tracks()):
    child.remove_track(tr)
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
C = unreal.MovieSceneKeyInterpolation.CONSTANT
KEYS = __LENSKEYS__
for prop, path, idx in (('CurrentFocalLength', 'CurrentFocalLength', 1), ('ManualFocusDistance', 'FocusSettings.ManualFocusDistance', 2), ('CurrentAperture', 'CurrentAperture', 3)):
    tr = child.add_track(unreal.MovieSceneFloatTrack)
    tr.set_property_name_and_path(prop, path)
    sec = tr.add_section()
    sec.set_range_seconds(0.0, __DURATION__)
    ch = sec.get_all_channels()[0]
    for k in KEYS:
        ch.add_key(unreal.FrameNumber(int(k[0])), float(k[idx]), 0.0, TR, C)
    print('lens track', prop, ch.get_num_keys())
print('child binding', str(child.get_display_name()), 'parent', str(child.get_parent().get_display_name()), 'children of TitleCam', len(parent.get_child_possessables()))
"""

# A dip through black at every cut and at the loop point (Sequencer fade track; UMG draws on top,
# so the title text stays up through the dips).
FADE_TRACK = """
import unreal
seq = unreal.load_asset('__SEQFULL__')
for t in list(seq.get_tracks()):
    if t.get_class().get_name() == 'MovieSceneFadeTrack':
        seq.remove_track(t)
tr = seq.add_track(unreal.MovieSceneFadeTrack)
sec = tr.add_section()
sec.set_range_seconds(0.0, __DURATION__)
ch = sec.get_all_channels()[0]
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
L = unreal.MovieSceneKeyInterpolation.LINEAR
for tick, v in __FADEKEYS__:
    ch.add_key(unreal.FrameNumber(int(tick)), float(v), 0.0, TR, L)
print('fade keys', ch.get_num_keys())
"""

MPC_TRACK = """
import unreal
seq = unreal.load_asset('__SEQFULL__')
track = None
for t in seq.get_tracks():
    if t.get_class().get_name() == 'MovieSceneMaterialParameterCollectionTrack':
        track = t
if track is None:
    track = seq.add_track(unreal.MovieSceneMaterialParameterCollectionTrack)
mpc = unreal.load_asset('__MPC__')
track.set_editor_property('MPC', mpc)
for s in list(track.get_sections()):
    track.remove_section(s)
section = track.add_section()
section.set_range_seconds(0.0, __DURATION__)
section.add_scalar_parameter_key('WindOffset', unreal.FrameNumber(0), __WSTART__)
section.add_scalar_parameter_key('WindOffset', unreal.FrameNumber(__ENDTICK__), __WEND__)
print('mpc', str(track.get_editor_property('MPC').get_name()), 'keys', section.get_all_channels()[0].get_num_keys())
"""

SAVE = """
import unreal
ok = unreal.EditorAssetLibrary.save_asset('__SEQFULL__', only_if_is_dirty=False)
print('saved', ok)
"""

READ = """
import unreal
seq = unreal.load_asset('__SEQFULL__')
print('playback', seq.get_playback_start_seconds(), seq.get_playback_end_seconds(), 'fps', str(seq.get_display_rate()))
for b in seq.get_bindings():
    print('binding', str(b.get_display_name()), 'tracks', len(b.get_tracks()))
    for t in b.get_tracks():
        for s in t.get_sections():
            for c in s.get_all_channels():
                print('   channel', str(c.get_name()), 'keys', c.get_num_keys())
for t in seq.get_tracks():
    print('master_track', t.get_class().get_name())
    for s in t.get_sections():
        for c in s.get_all_channels():
            print('   channel', str(c.get_name()), 'keys', c.get_num_keys())
"""

PLACE = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
a = None
for x in eas.get_all_level_actors():
    if x.get_actor_label() == '__PLAYERLABEL__':
        a = x
if a is None:
    a = eas.spawn_actor_from_class(unreal.LevelSequenceActor, unreal.Vector(0.0, 0.0, 0.0))
    a.set_actor_label('__PLAYERLABEL__')
seq = unreal.load_asset('__SEQFULL__')
a.set_editor_property('level_sequence_asset', seq)
a.set_editor_property('is_spatially_loaded', False)
settings = a.get_editor_property('playback_settings')
settings.set_editor_property('auto_play', False)
a.set_editor_property('playback_settings', settings)
print('placed', a.get_actor_label(), 'sequence', str(a.get_editor_property('level_sequence_asset').get_name()), 'spatial', a.get_editor_property('is_spatially_loaded'), a.get_package().get_name())
"""

PLACE_SAVE = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
a = None
for x in eas.get_all_level_actors():
    if x.get_actor_label() == '__PLAYERLABEL__':
        a = x
ok = unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package()], False)
print('saved_actor_package', a.get_package().get_name(), ok)
"""


# TitleCam's placed pose = the first frame of shot 1, so the intro's readiness check
# (PC_Saskarta.PollIntro, at the CineCameraActor's location) and the no-sequence fallback both
# look at the loop's own first view. Manual focus, so the keyed focus distance is used.
CAMERA_POSE = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cam = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__CAMLABEL__':
        cam = a
cam.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__), False, True)
comp = cam.get_cine_camera_component()
comp.set_editor_property('constrain_aspect_ratio', False)
comp.set_editor_property('current_focal_length', __LENS__)
comp.set_editor_property('current_aperture', __APERTURE__)
fs = comp.get_editor_property('focus_settings')
fs.set_editor_property('focus_method', unreal.CameraFocusMethod.MANUAL)
fs.set_editor_property('manual_focus_distance', __FOCUS__)
comp.set_editor_property('focus_settings', fs)
print('titlecam', str(cam.get_actor_location()), str(cam.get_actor_rotation()), 'lens', comp.get_editor_property('current_focal_length'), 'hfov', round(comp.get_horizontal_field_of_view(), 2), 'package', cam.get_package().get_name())
"""

# World Partition streams around the player's view, which is the title camera during the title.
# The shots sit about 2.7 km from the dock where the carrier waits, so this always-loaded
# TargetPoint carries a WorldPartitionStreamingSourceComponent that keeps the dock streamed
# while the title plays; Start then cuts to loaded ground instead of waiting on it.
STREAM_SOURCE = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
a = None
for x in eas.get_all_level_actors():
    if x.get_actor_label() == '__SRCLABEL__':
        a = x
if a is None:
    a = eas.spawn_actor_from_class(unreal.TargetPoint, unreal.Vector(__X__, __Y__, __Z__))
    a.set_actor_label('__SRCLABEL__')
a.set_actor_location(unreal.Vector(__X__, __Y__, __Z__), False, True)
a.set_editor_property('is_spatially_loaded', False)
a.set_folder_path('Cinematics')
src = a.get_component_by_class(unreal.WorldPartitionStreamingSourceComponent)
if src is None:
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sds.k2_gather_subobject_data_for_instance(a)
    params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=unreal.WorldPartitionStreamingSourceComponent, blueprint_context=None)
    res = sds.add_new_subobject(params)
    print('add component', str(res[1]))
    src = a.get_component_by_class(unreal.WorldPartitionStreamingSourceComponent)
print('source', a.get_actor_label(), str(a.get_actor_location()), 'component', src is not None, 'enabled', src.get_editor_property('default_visualizer_loading_range') if src else None, 'spatial', a.get_editor_property('is_spatially_loaded'), a.get_package().get_name())
"""

SAVE_ACTORS = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = []
for x in eas.get_all_level_actors():
    if x.get_actor_label() in __LABELS__:
        pk.append(x.get_package())
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pk, False)
print('saved', ok, [p.get_name() for p in pk])
"""

SRC_LABEL = "TitleDockStreamingSource"


def sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


def transform_keys():
    """(tick, 9 channel values, interpolation) for the transform track: each shot's start key is
    linear to its end key; the end key sits one tick before the next shot and is held (constant),
    so the camera never interpolates across a cut."""
    keys = []
    for name, t0, t1, lens, focus, (p0, pi0, y0), (p1, pi1, y1) in shot_keys():
        keys.append((round(t0 * TICKS_PER_S), (p0[0], p0[1], p0[2], 0.0, pi0, y0, 1.0, 1.0, 1.0), "linear"))
        keys.append((round(t1 * TICKS_PER_S) - 1, (p1[0], p1[1], p1[2], 0.0, pi1, y1, 1.0, 1.0, 1.0), "constant"))
    return keys


def lens_keys():
    """(tick, focal length mm, manual focus distance cm, aperture) at each shot start."""
    return [(round(t0 * TICKS_PER_S), lens, focus, SHOTS[i].get("aperture", 8.0))
            for i, (name, t0, t1, lens, focus, k0, k1) in enumerate(shot_keys())]


def build():
    run(sub(SETUP, SEQFULL=SEQ_FULL, SEQNAME=SEQ_NAME, SEQFOLDER=SEQ_FOLDER, FPS=FPS,
            DURATION=DURATION_S, CAMLABEL=CAM_LABEL), "setup")
    run(sub(TRANSFORM_KEYS, SEQFULL=SEQ_FULL, CAMLABEL=CAM_LABEL, KEYS=repr(transform_keys())), "transform keys")
    run(sub(LENS_TRACKS, SEQFULL=SEQ_FULL, CAMLABEL=CAM_LABEL, DURATION=DURATION_S,
            LENSKEYS=repr(lens_keys())), "lens tracks")
    run(sub(FADE_TRACK, SEQFULL=SEQ_FULL, DURATION=DURATION_S,
            FADEKEYS=repr([(round(tt * TICKS_PER_S), v) for tt, v in fade_keys()])), "fade track")
    run(sub(MPC_TRACK, SEQFULL=SEQ_FULL, MPC=MPC, DURATION=DURATION_S,
            WSTART=WIND_OFFSET_START, WEND=WIND_OFFSET_END,
            ENDTICK=round(DURATION_S * TICKS_PER_S)), "MPC WindOffset track")
    run(sub(SAVE, SEQFULL=SEQ_FULL), "save sequence")


def wind():
    """Re-key only the MPC WindOffset track (the camera's transform keys are left untouched)."""
    run(sub(MPC_TRACK, SEQFULL=SEQ_FULL, MPC=MPC, DURATION=DURATION_S,
            WSTART=WIND_OFFSET_START, WEND=WIND_OFFSET_END,
            ENDTICK=round(DURATION_S * TICKS_PER_S)), "MPC WindOffset track")
    run(sub(SAVE, SEQFULL=SEQ_FULL), "save sequence")


def place():
    run(sub(PLACE, PLAYERLABEL=PLAYER_LABEL, SEQFULL=SEQ_FULL), "place TitleSequencePlayer")
    run(sub(PLACE_SAVE, PLAYERLABEL=PLAYER_LABEL), "save TitleSequencePlayer's package")


def read():
    run(sub(READ, SEQFULL=SEQ_FULL), "read")


def camera():
    """Move TitleCam's placed pose and lens to shot 1's first frame, then save its package."""
    name, t0, t1, lens, focus, (pos, pitch, yaw), k1 = shot_keys()[0]
    run(sub(CAMERA_POSE, CAMLABEL=CAM_LABEL, X=pos[0], Y=pos[1], Z=pos[2], P=pitch, YAW=yaw,
            LENS=lens, APERTURE=SHOTS[0].get("aperture", 8.0), FOCUS=focus), "TitleCam pose")
    run(sub(SAVE_ACTORS, LABELS=repr([CAM_LABEL])), "save TitleCam")


def streaming():
    """Place (or update) the dock's streaming source and save its package."""
    point54 = tuple(float(v) for v in SPLINE_POINTS_CM[54])
    run(sub(STREAM_SOURCE, SRCLABEL=SRC_LABEL, X=point54[0], Y=point54[1], Z=point54[2] + 200.0),
        "dock streaming source")
    run(sub(SAVE_ACTORS, LABELS=repr([SRC_LABEL])), "save streaming source")


# ----------------------------------------------------------------------------- captures

CAM_SCRIPT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
cap = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        cap = a
if cap is None:
    cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(__X__, __Y__, __Z__))
    cap.set_actor_label('__LABEL__')
cap.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__), False, False)
c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
rt = unreal.RenderingLibrary.create_render_target2d(w, __W__, __H__, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
c.set_editor_property('texture_target', rt)
c.set_editor_property('fov_angle', __FOV__)
c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
c.set_editor_property('always_persist_rendering_state', True)
hidden = []
if __HIDEHLOD__:
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() == 'WorldPartitionHLOD':
            o, e = a.get_actor_bounds(False)
            near = abs(o.x - __X__) <= e.x and abs(o.y - __Y__) <= e.y
            far = any(abs(o.x - px) <= e.x and abs(o.y - py) <= e.y for px, py in __KEEPXY__)
            if near and not far:
                hidden.append(a)
                c.hide_actor_components(a, False)
c.set_editor_property('capture_every_frame', True)
print('capture actor ready at', __X__, __Y__, __Z__, 'hidden HLOD actors', str([a.get_actor_label() for a in hidden]))
"""

EXPORT_SCRIPT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        c = a.get_component_by_class(unreal.SceneCaptureComponent2D)
        c.set_editor_property('capture_every_frame', False)
        c.capture_scene()
        unreal.RenderingLibrary.export_render_target(w, c.get_editor_property('texture_target'), '__DIR__', '__NAME__')
        eas.destroy_actor(a)
        print('exported and removed the capture actor')
"""

CAPTURE_LABEL = "TITLE_TempCapture"


def captures(out_dir=None, settle_s=5.0, width=1920, height=1080, which=None, hide_hlod=False):
    """One key frame per shot (the shot's midpoint), rendered with the shot's own lens through a
    temporary SceneCapture2D (removed afterwards; nothing is saved).

    hide_hlod: hide, in the capture only, the HLOD actors whose cell contains the camera (unless
    the same cell also holds the summit, the beacon or point 0). In the
    editor the always-loaded Merged HLOD layer stays drawn over actors loaded one by one (it sits a
    few metres above the real ground here), which PIE replaces with the streamed cells; the
    landscape proxies and PCG tiles around the shots must be loaded first (4 proxies at most)."""
    import time
    out_dir = pathlib.Path(out_dir or (ROOT / "Saved" / "Screenshots" / "Title"))
    # HLOD cells that also hold the mountain or the beacon stay drawn: PIE keeps those as HLOD
    # from here (they are far outside the loading range).
    keep = [(v[0], v[1]) for v in targets().values()]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (name, t0, t1, lens, focus, k0, k1) in enumerate(shot_keys()):
        if which and name not in which:
            continue
        t = (t0 + t1) / 2.0
        pos, (pitch, yaw) = pose_at(t)
        run(sub(CAM_SCRIPT, LABEL=CAPTURE_LABEL, X=pos[0], Y=pos[1], Z=pos[2], P=pitch, YAW=yaw,
                W=width, H=height, FOV=hfov_deg(lens), HIDEHLOD=bool(hide_hlod), KEEPXY=keep), f"camera {name} t={t:.0f}s")
        time.sleep(settle_s)
        fname = f"title_{i + 1}_{name}{'_nearhlodhidden' if hide_hlod else ''}.png"
        run(sub(EXPORT_SCRIPT, LABEL=CAPTURE_LABEL, DIR=out_dir.as_posix(), NAME=fname), f"export {name}")
        p = out_dir / fname
        if not p.exists():
            raise SystemExit(f"export failed: {p} missing")
        print(p, "pose", tuple(round(v, 1) for v in pos), "pitch", round(pitch, 2), "yaw", round(yaw, 2),
              "lens", lens)
        paths.append(p)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", "build", "place", "camera", "streaming", "captures",
                                     "read", "wind", "all"])
    ap.add_argument("--shots", nargs="*", help="captures: only these shot names")
    ap.add_argument("--hide-near-hlod", action="store_true",
                    help="captures: hide the HLOD cell the camera stands in (see captures())")
    a = ap.parse_args(argv)
    if a.step in ("check", "all"):
        rc = check()
        if a.step == "check" or rc:
            return rc
    if a.step in ("build", "all"):
        build()
    if a.step in ("place", "all"):
        place()
    if a.step in ("camera", "all"):
        camera()
    if a.step in ("streaming", "all"):
        streaming()
    if a.step in ("captures", "all"):
        captures(which=a.shots, hide_hlod=a.hide_near_hlod)
    if a.step == "read":
        read()
    if a.step == "wind":
        wind()
    return 0


if __name__ == "__main__":
    sys.exit(main())
