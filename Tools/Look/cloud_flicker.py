"""Volumetric-cloud flicker from a static camera: captures and the metric (task ATMOS).

    python Tools/Look/cloud_flicker.py capture <tag> [--view sky_1050] [--frames 3] [--gap-s 0.5] [--settle-s 6]
    python Tools/Look/cloud_flicker.py measure <tag>

"capture" puts a temporary SceneCapture2D (final colour LDR, persistent view state, so the cloud
volumetric render target keeps its temporal history exactly as a game view does) on one of
capture_look.py's views, lets it render every frame for --settle-s, then exports --frames PNGs
--gap-s apart into Saved/Screenshots/Atmos/<tag>_<i>.png without moving the camera, and removes
the actor. It never starts PIE. Wrap it in Tools/GameFlow/editor_gate.py acquire/release.

"measure" splits every consecutive frame difference (cloud region only) into two parts:
  flicker  mean absolute difference (0..255 luma) of the HIGH-pass images (frame minus its
           BLUR_PX box blur): pixel-scale grain that changes from frame to frame. This is what the
           user sees as shimmering, noisy cloud edges. Lower is better.
  drift    mean absolute difference of the LOW-pass (box-blurred) images: the cloud field itself
           moving with the wind. It must stay above zero (the clouds still drift slowly).
  raw      the plain mean absolute luma difference (the brief's frame-difference metric).
The cloud region is the part of the frame above CLOUD_BOTTOM_FRAC of its height (sky_1050 looks
up at +25 deg: sky and clouds only above it).
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_DIR = ROOT / "Saved" / "Screenshots" / "Atmos"
LABEL = "Atmos_TempCapture"
CLOUD_BOTTOM_FRAC = 0.85
BLUR_PX = 9
REC709 = np.array([0.2126, 0.7152, 0.0722])


# ----------------------------------------------------------------------------- metric (pure)

def luma255(path_or_rgb):
    rgb = path_or_rgb
    if not isinstance(rgb, np.ndarray):
        rgb = np.asarray(Image.open(path_or_rgb).convert("RGB"), dtype=np.float64)
    return rgb @ REC709


def box_blur(img, k=BLUR_PX):
    """Separable box blur with edge padding (k odd)."""
    r = k // 2
    p = np.pad(img, r, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = img.shape
    s = c[k:k + h, k:k + w] - c[0:h, k:k + w] - c[k:k + h, 0:w] + c[0:h, 0:w]
    return s / (k * k)


def split_difference(la, lb, mask, k=BLUR_PX):
    """(raw, flicker, drift) mean absolute differences in mask, 0..255."""
    ba, bb = box_blur(la, k), box_blur(lb, k)
    raw = np.abs(la - lb)[mask].mean()
    flicker = np.abs((la - ba) - (lb - bb))[mask].mean()
    drift = np.abs(ba - bb)[mask].mean()
    return float(raw), float(flicker), float(drift)


def cloud_mask(h, w, bottom_frac=CLOUD_BOTTOM_FRAC):
    m = np.zeros((h, w), dtype=bool)
    m[: int(round(h * bottom_frac)), :] = True
    return m


def frame_paths(tag, out_dir=OUT_DIR):
    return sorted(pathlib.Path(out_dir).glob(f"{tag}_[0-9].png"))


def measure(tag, out_dir=OUT_DIR):
    paths = frame_paths(tag, out_dir)
    if len(paths) < 2:
        raise SystemExit(f"need at least 2 frames for {tag} in {out_dir}")
    lumas = [luma255(p) for p in paths]
    mask = cloud_mask(*lumas[0].shape)
    pairs = [split_difference(lumas[i], lumas[i + 1], mask) for i in range(len(lumas) - 1)]
    mean = lambda i: round(sum(p[i] for p in pairs) / len(pairs), 3)
    return {"tag": tag, "frames": [p.name for p in paths], "pixels": int(mask.sum()),
            "pairs": [[round(v, 3) for v in p] for p in pairs],
            "raw": mean(0), "flicker": mean(1), "drift": mean(2),
            "cloud_luma_mean": round(float(np.mean([l[mask].mean() for l in lumas])) / 255.0, 4)}


# ----------------------------------------------------------------------------- editor captures

EXPORT_KEEP = """
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

CLEANUP = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        eas.destroy_actor(a)
        print('removed the capture actor')
"""


def _sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


def capture(tag, view="sky_1050", frames=3, gap_s=0.5, settle_s=6.0, width=1920, height=1080, out_dir=OUT_DIR):
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    import capture_look as cl
    from apply_look import python_run, check_banned

    def run(script):
        ok, out, err = python_run(check_banned(script))
        if not ok:
            raise SystemExit(f"python_run failed: {err}")
        return out.strip()

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_paths(tag, out_dir):
        old.unlink()
    x, y, zs, pitch, yaw = cl.view_pose(view)
    setup = _sub(cl.CAM_SCRIPT, X=repr(x), Y=repr(y), ZS=repr(zs), EYE=repr(cl.EYE_CM), P=repr(pitch),
                 YAW=repr(yaw), FOV=repr(cl.HFOV), W=width, H=height, SRC="SCS_FINAL_COLOR_LDR", OFF="[]",
                 LABEL=LABEL)
    run(setup)
    # The background editor redraws a capture-every-frame SceneCapture only a few times a second;
    # pump explicit captures so the cloud history is warm before the first export.
    end = time.monotonic() + settle_s
    while time.monotonic() < end:
        run(_sub(PUMP, LABEL=LABEL))
    stamps = []
    t0 = time.monotonic()
    for i in range(frames):
        target = t0 + i * gap_s
        while time.monotonic() < target:
            time.sleep(0.01)
        stamps.append(round(time.monotonic() - t0, 3))
        run(_sub(EXPORT_KEEP, LABEL=LABEL, DIR=out_dir.as_posix(), NAME=f"{tag}_{i}.png"))
    run(_sub(CLEANUP, LABEL=LABEL))
    return {"tag": tag, "view": view, "export_at_s": stamps}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["capture", "measure"])
    ap.add_argument("tag")
    ap.add_argument("--view", default="sky_1050")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--gap-s", type=float, default=0.5)
    ap.add_argument("--settle-s", type=float, default=6.0)
    a = ap.parse_args(argv)
    if a.step == "capture":
        print(json.dumps(capture(a.tag, a.view, a.frames, a.gap_s, a.settle_s)))
    else:
        print(json.dumps(measure(a.tag), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
