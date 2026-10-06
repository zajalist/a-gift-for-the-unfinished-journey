"""Title-sky motion and variation: reproducible captures and the two metrics (task SKY).

    python Tools/Look/sky_motion.py capture <tag> [--wind-end 3.0] [--settle-s 4]
    python Tools/Look/sky_motion.py measure <tag>
    python Tools/Look/sky_motion.py strip <tag>

"capture" renders the title cinematic's own camera (build_title_sequence.pose_at) at sequence
times t0 / t20 / t39, two frames 1 s apart at each, into Saved/Screenshots/Sky/<tag>_t<T>_<a|b>.png.
It never plays the sequence (and never starts PIE): the sequence keys only TitleCam's transform
and MPC_Saskarta_Sky.WindOffset, so the tool evaluates both itself. The captures are scheduled on
the wall clock (engine time in the editor world advances with it), so frame b is exactly 1 s after
frame a and t20 is 20 s after t0, the same as in the running title. WindOffset follows the
sequence's linear ramp WIND_OFFSET_START -> --wind-end over DURATION_S (defaults: the values in
build_title_sequence.py). Both frames of a pair use the pose at t, so the camera's own push does
not count as sky motion.

"measure" prints, as JSON:
  motion     mean absolute luma difference (0..255) between the two frames of each pair, sky region
             only; "motion_mean" averages t0/t20/t39. This is the brief's frame-difference metric.
  variation  across the three "a" frames: the spread (max - min) of the sky region's mean luma
             (0..1), the spread of its chroma-weighted mean hue (degrees), and the mean per-pixel
             luma standard deviation (0..1), which is how much the cloud pattern itself changes.

The sky region is the frame above SKY_BOTTOM_FRAC of its height (above the mountain's summit,
which sits just above the frame centre from the title camera), minus a column around the High
Voice beam, whose brightness is the beacon, not the sky.

Wrap every capture in Tools/GameFlow/editor_gate.py acquire/release.
"""
import argparse
import json
import math
import pathlib
import sys
import time

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_DIR = ROOT / "Saved" / "Screenshots" / "Sky"
TIMES = (0.0, 20.0, 39.0)
PAIR_GAP_S = 1.0
SKY_BOTTOM_FRAC = 0.40          # rows above 40% of the height: above the summit (about 46%)
BEAM_COLUMN_FRAC = (0.44, 0.50)  # the High Voice beam sits at x ~ 0.465 of the width
LABEL = "Sky_TempCapture"
PUMP_INTERVAL_S = 1.0  # Hayba accepts 16 connections and frees each a few seconds late
REC709 = np.array([0.2126, 0.7152, 0.0722])


# ----------------------------------------------------------------------------- metrics (pure)

def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def sky_mask(height, width, bottom_frac=SKY_BOTTOM_FRAC, beam=BEAM_COLUMN_FRAC):
    m = np.zeros((height, width), dtype=bool)
    m[: int(round(height * bottom_frac)), :] = True
    if beam:
        m[:, int(width * beam[0]): int(math.ceil(width * beam[1]))] = False
    return m


def luma255(rgb):
    return rgb @ REC709


def frame_difference(rgb_a, rgb_b, mask):
    """Mean absolute luma difference (0..255) inside mask."""
    return float(np.abs(luma255(rgb_a) - luma255(rgb_b))[mask].mean())


def mean_hue_deg(rgb, mask):
    """Chroma-weighted circular mean hue (degrees, 0..360) of the masked pixels, or None for grey."""
    px = rgb[mask] / 255.0
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    # opponent axes of the HSV hexcone: a = r - (g + b) / 2, b = sqrt(3)/2 (g - b)
    a = r - 0.5 * (g + b)
    bb = (math.sqrt(3) / 2.0) * (g - b)
    sa, sb = float(a.sum()), float(bb.sum())
    if abs(sa) < 1e-9 and abs(sb) < 1e-9:
        return None
    return math.degrees(math.atan2(sb, sa)) % 360.0


def hue_spread(hues):
    """Largest pairwise circular distance (degrees) between hues; None entries are skipped."""
    hs = [h for h in hues if h is not None]
    best = 0.0
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            d = abs(hs[i] - hs[j]) % 360.0
            best = max(best, min(d, 360.0 - d))
    return best


def variation(frames, mask):
    lumas = [luma255(f) / 255.0 for f in frames]
    means = [float(l[mask].mean()) for l in lumas]
    hues = [mean_hue_deg(f, mask) for f in frames]
    stack = np.stack([l[mask] for l in lumas])
    return {"luma_means": [round(v, 4) for v in means],
            "luma_spread": round(max(means) - min(means), 4),
            "hues_deg": [None if h is None else round(h, 2) for h in hues],
            "hue_spread_deg": round(hue_spread(hues), 2),
            "pixel_luma_std": round(float(stack.std(axis=0).mean()), 4)}


def pair_paths(tag, t, out_dir=OUT_DIR):
    return (pathlib.Path(out_dir) / f"{tag}_t{int(t)}_a.png", pathlib.Path(out_dir) / f"{tag}_t{int(t)}_b.png")


def measure(tag, out_dir=OUT_DIR):
    first = load_rgb(pair_paths(tag, TIMES[0], out_dir)[0])
    mask = sky_mask(*first.shape[:2])
    motion = {}
    frames = []
    for t in TIMES:
        pa, pb = pair_paths(tag, t, out_dir)
        a, b = load_rgb(pa), load_rgb(pb)
        motion[f"t{int(t)}"] = round(frame_difference(a, b, mask), 3)
        frames.append(a)
    return {"tag": tag, "sky_pixels": int(mask.sum()),
            "motion": motion, "motion_mean": round(sum(motion.values()) / len(motion), 3),
            "variation": variation(frames, mask)}


def strip(tag, out_dir=OUT_DIR, width=640):
    """t0 / t20 / t39 side by side (the 'a' frames), scaled to `width` each."""
    ims = [Image.open(pair_paths(tag, t, out_dir)[0]).convert("RGB") for t in TIMES]
    h = round(ims[0].height * width / ims[0].width)
    out = Image.new("RGB", (width * len(ims), h))
    for i, im in enumerate(ims):
        out.paste(im.resize((width, h)), (i * width, 0))
    path = pathlib.Path(out_dir) / f"{tag}_strip.png"
    out.save(path)
    return path


# ----------------------------------------------------------------------------- editor captures

def wind_offset_at(t, start, end, duration):
    t = min(max(t, 0.0), duration)
    return start + (end - start) * t / duration


SETUP = """
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
    c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
    rt = unreal.RenderingLibrary.create_render_target2d(w, __W__, __H__, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
    c.set_editor_property('texture_target', rt)
    c.set_editor_property('fov_angle', __FOV__)
    c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    c.set_editor_property('always_persist_rendering_state', True)
    c.set_editor_property('capture_every_frame', True)
cap.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__), False, False)
mpc = unreal.load_asset('__MPC__')
unreal.MaterialLibrary.set_scalar_parameter_value(w, mpc, 'WindOffset', __WO__)
print('pose set, WindOffset', __WO__)
"""

SET_WIND = """
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
unreal.MaterialLibrary.set_scalar_parameter_value(w, unreal.load_asset('__MPC__'), 'WindOffset', __WO__)
print('WindOffset', __WO__)
"""

EXPORT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        c = a.get_component_by_class(unreal.SceneCaptureComponent2D)
        c.capture_scene()
        unreal.RenderingLibrary.export_render_target(w, c.get_editor_property('texture_target'), '__DIR__', '__NAME__')
        print('exported __NAME__')
"""

PUMP = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        a.get_component_by_class(unreal.SceneCaptureComponent2D).capture_scene()
"""

CVAR_SET = """
import unreal
print('was', unreal.SystemLibrary.get_console_variable_int_value('r.VolumetricRenderTarget'))
unreal.SystemLibrary.execute_console_command(None, 'r.VolumetricRenderTarget __V__')
"""

CLEANUP = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        eas.destroy_actor(a)
        print('removed the capture actor')
unreal.MaterialLibrary.set_scalar_parameter_value(w, unreal.load_asset('__MPC__'), 'WindOffset', __WO__)
"""


def _sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


def capture(tag, wind_end=None, settle_s=4.0, width=1920, height=1080, out_dir=OUT_DIR):
    sys.path.insert(0, str(HERE))
    import build_title_sequence as bts
    from apply_look import python_run, check_banned

    def run(script):
        ok, out, err = python_run(check_banned(script))
        if not ok:
            raise SystemExit(f"python_run failed: {err}")
        return out.strip()

    start = bts.WIND_OFFSET_START
    end = bts.WIND_OFFSET_END if wind_end is None else wind_end
    dur = bts.DURATION_S
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = []

    def pose_script(t, wo):
        pos, (pitch, yaw) = bts.pose_at(t)
        return _sub(SETUP, LABEL=LABEL, X=pos[0], Y=pos[1], Z=pos[2], P=pitch, YAW=yaw, W=width,
                    H=height, FOV=bts.hfov_deg(bts.lens_at(t)), MPC=bts.MPC, WO=round(wo, 5))

    def wait_until(t_abs):
        # The editor does not redraw a capture-every-frame SceneCapture while its window is in the
        # background, so pump explicit captures meanwhile (clouds and Lumen keep their history).
        while t_abs - time.monotonic() > PUMP_INTERVAL_S:
            run(_sub(PUMP, LABEL=LABEL))
            time.sleep(PUMP_INTERVAL_S)
        d = t_abs - time.monotonic()
        if d > 0:
            time.sleep(d)

    # Full-resolution clouds without temporal reconstruction: the background editor ticks at a
    # few fps, too slow for the reconstruction to converge, so each capture must stand alone.
    was = run(_sub(CVAR_SET, V=0)).split()[-1]
    run(pose_script(TIMES[0], wind_offset_at(TIMES[0], start, end, dur)))
    wait_until(time.monotonic() + settle_s)
    t0 = time.monotonic()
    for t in TIMES:
        if t > TIMES[0]:
            wait_until(t0 + t - settle_s)
            run(pose_script(t, wind_offset_at(t - settle_s, start, end, dur)))
            wait_until(t0 + t - 0.5)
            run(_sub(SET_WIND, MPC=bts.MPC, WO=round(wind_offset_at(t, start, end, dur), 5)))
        pa, pb = pair_paths(tag, t, out_dir)
        wait_until(t0 + t)
        ta = time.monotonic() - t0
        run(_sub(EXPORT, LABEL=LABEL, DIR=out_dir.as_posix(), NAME=pa.name))
        run(_sub(SET_WIND, MPC=bts.MPC, WO=round(wind_offset_at(t + PAIR_GAP_S, start, end, dur), 5)))
        wait_until(t0 + t + PAIR_GAP_S)
        tb = time.monotonic() - t0
        run(_sub(EXPORT, LABEL=LABEL, DIR=out_dir.as_posix(), NAME=pb.name))
        log.append({"t": t, "a_at_s": round(ta, 2), "b_at_s": round(tb, 2)})
    run(_sub(CLEANUP, LABEL=LABEL, MPC=bts.MPC, WO=start))
    run(_sub(CVAR_SET, V=int(was)))
    return {"tag": tag, "wind_offset": [start, end], "schedule": log}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["capture", "measure", "strip"])
    ap.add_argument("tag")
    ap.add_argument("--wind-end", type=float, help="WindOffset at t=40 s (default: build_title_sequence)")
    ap.add_argument("--settle-s", type=float, default=4.0)
    a = ap.parse_args(argv)
    if a.step == "capture":
        print(json.dumps(capture(a.tag, a.wind_end, a.settle_s)))
    elif a.step == "measure":
        print(json.dumps(measure(a.tag), indent=1))
    else:
        print(strip(a.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
