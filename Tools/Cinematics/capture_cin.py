"""Still frames of a planned cinematic, without PIE and without opening Sequencer (LANE5).

    python Tools/Cinematics/capture_cin.py CIN_01_DIRECTIVE OUT_DIR 2.0 6.5 12.4 16.0 19.5 24.0 28.5 33.0

For each time t it evaluates the plan build_cinematics.py emitted the sequence from: the camera of the active
cut (keys interpolated linearly; a blending cut uses the incoming camera), its focal length, and the
MPC_Saskarta_Scan values at t (the scan pulse radius, focus, reticle). It then sets those MPC values in the
editor world, spawns a temporary SceneCapture2D at the camera pose (FOV from the focal length, the camera's
post-process blendables such as M_PP_SensorScan), lets it capture for a few seconds, exports the PNG and
destroys the actor. The MPC is reset to its defaults at the end. Same approach as Tools/Look/capture_look.py.
Far terrain is only as loaded as the editor's World Partition: judge the mountain after the user's HLOD build.
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "Look"))

import build_cinematics as bc  # noqa: E402
from apply_look import check_banned, python_run  # noqa: E402

LABEL = "Cin_TempCapture"

SETUP = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
KML = unreal.MaterialLibrary  # KismetMaterialLibrary in Python
mpc = unreal.load_asset('__MPC__')
for n, v in __SCALARS__:
    KML.set_scalar_parameter_value(w, mpc, n, v)
for n, v in __VECTORS__:
    KML.set_vector_parameter_value(w, mpc, n, unreal.LinearColor(v[0], v[1], v[2], 1.0))
cap = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        cap = a
if cap is None:
    cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(__X__, __Y__, __Z__))
    cap.set_actor_label('__LABEL__')
cap.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=__R__, pitch=__P__, yaw=__YAW__), False, False)
c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
rt = unreal.RenderingLibrary.create_render_target2d(w, __W__, __H__, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
c.set_editor_property('texture_target', rt)
c.set_editor_property('fov_angle', __FOV__)
c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
pp = c.get_editor_property('post_process_settings')
wb = pp.get_editor_property('weighted_blendables')
arr = []
for bl in __BLENDABLES__:
    it = unreal.WeightedBlendable()
    it.set_editor_property('weight', 1.0)
    it.set_editor_property('object', unreal.load_asset(bl))
    arr.append(it)
wb.set_editor_property('array', arr)
pp.set_editor_property('weighted_blendables', wb)
c.set_editor_property('post_process_settings', pp)
c.set_editor_property('post_process_blend_weight', 1.0)
c.set_editor_property('always_persist_rendering_state', True)
c.set_editor_property('capture_every_frame', True)
print('capture at', __T__)
"""

EXPORT = """
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
        print('exported', '__NAME__')
"""

RESET = """
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
KML = unreal.MaterialLibrary  # KismetMaterialLibrary in Python
mpc = unreal.load_asset('__MPC__')
for p in mpc.get_editor_property('scalar_parameters'):
    KML.set_scalar_parameter_value(w, mpc, p.get_editor_property('parameter_name'), p.get_editor_property('default_value'))
for p in mpc.get_editor_property('vector_parameters'):
    KML.set_vector_parameter_value(w, mpc, p.get_editor_property('parameter_name'), p.get_editor_property('default_value'))
print('mpc reset')
"""


def lerp_keys(keys, t):
    """keys: [(t, value)] (value a float or a tuple), piecewise linear, held at the ends."""
    keys = sorted(keys, key=lambda k: k[0])
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            if isinstance(v0, (tuple, list)):
                return tuple(a + (b - a) * f for a, b in zip(v0, v1))
            return v0 + (v1 - v0) * f
    return keys[-1][1]


def cam_at(plan, t):
    active = None
    for t0, t1, cam, _ease in bc.cut_sections(plan):
        if t0 <= t < t1:
            active = cam  # later sections win (a blending cut overlaps its predecessor)
    cam = next(c for c in plan["cams"] if c["name"] == active)
    ks = [(k[0], tuple(k[1:7])) for k in cam["keys"]]
    x, y, z, roll, pitch, yaw = lerp_keys(ks, t)
    # Road cinematics (frame "local") are keyed in the runner's road frame: turn the pose into world space
    # (until 2026-09-28 the local keys went to the capture as world coordinates, i.e. near the map origin).
    pose = bc.world_pose(plan, (t, x, y, z, roll, pitch, yaw, "linear"))
    hfov = math.degrees(2 * math.atan((bc.FILMBACK_W / 2.0) / cam["focal"]))
    return active, pose, hfov, cam.get("blendables", [])


def main(argv):
    cin, out = argv[0], Path(argv[1]).resolve()
    times = [float(x) for x in argv[2:]]
    plan = bc.PLANS[cin]()
    out.mkdir(parents=True, exist_ok=True)
    mpc = plan.get("mpc", {})
    for t in times:
        name, (x, y, z, r, p, yaw), fov, bls = cam_at(plan, t)
        sc = [(n, float(lerp_keys(k, t))) for n, k in mpc.get("scalars", {}).items() if k]
        vc = [(n, tuple(lerp_keys(k, t))) for n, k in mpc.get("vectors", {}).items() if k]
        s = SETUP
        for a, b in (("__MPC__", mpc.get("asset", "") + "." + mpc.get("asset", "x/x").split("/")[-1]), ("__SCALARS__", repr(sc)), ("__VECTORS__", repr(vc)),
                     ("__LABEL__", LABEL), ("__X__", repr(x)), ("__Y__", repr(y)), ("__Z__", repr(z)), ("__R__", repr(r)),
                     ("__P__", repr(p)), ("__YAW__", repr(yaw)), ("__W__", os.environ.get("CAP_W", "1280")), ("__H__", os.environ.get("CAP_H", "720")), ("__FOV__", repr(fov)),
                     ("__BLENDABLES__", repr(bls)), ("__T__", repr(t))):
            s = s.replace(a, b)
        ok, o, err = python_run(check_banned(s))
        print(o.strip(), name, round(fov, 1))
        if not ok:
            print("setup failed", err)
            return 1
        time.sleep(4.0)
        fn = f"{cin}_{t:05.1f}.png"
        ok, o, err = python_run(check_banned(EXPORT.replace("__LABEL__", LABEL).replace("__DIR__", out.as_posix()).replace("__NAME__", fn)))
        print(o.strip())
        if not ok:
            print("export failed", err)
            return 1
    if mpc:
        ok, o, err = python_run(check_banned(RESET.replace("__MPC__", mpc["asset"] + "." + mpc["asset"].split("/")[-1])))
        print(o.strip(), err or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
