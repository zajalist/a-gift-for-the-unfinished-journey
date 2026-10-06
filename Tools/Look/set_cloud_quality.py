"""VolumetricCloud tracing quality on the level's cloud actor (task ATMOS: cloud flicker).

    python Tools/Look/set_cloud_quality.py read
    python Tools/Look/set_cloud_quality.py apply [--save]
    python Tools/Look/set_cloud_quality.py apply --view 1.0 --shadow 1.0 ...   # A/B values

Why: the volumetric render target (r.VolumetricRenderTarget.Mode 0) does not blend history. Each
frame it traces one pixel of every 2x2 block with a ray whose start is jittered by a per-frame blue
noise (StateFrameIndexMod8, VolumetricCloud.usf), and copies the other three from the reprojected
previous frame. So every visible cloud pixel is ONE noisy ray, replaced every 4 frames: the grain
the user saw shimmering. The only accumulation is the anti-aliasing pass afterwards. The noise of
one ray falls with its step count, so the fix is more view samples (and self-shadow samples) per
ray, not a different buffer scheme. The values below were chosen by the flicker metric
(cloud_flicker.py) and the GPU cost (gpu_budget.py); see LOOK.md, "Cloud flicker".

Only the cloud actor's own package is saved (with --save), and only when the values changed.
Wrap it in Tools/GameFlow/editor_gate.py acquire/release.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from apply_look import check_banned, python_run  # noqa: E402

# UVolumetricCloudComponent property (Python name) -> value. Engine defaults in the comments.
CLOUD_QUALITY = {
    "view_sample_count_scale": 2.0,                    # 1.0: 96 samples over 15 km
    "shadow_view_sample_count_scale": 2.0,             # 1.0: 10 self-shadow samples
    "reflection_view_sample_count_scale_value": 1.0,   # 1.0 (sky light capture; unchanged)
    "shadow_reflection_view_sample_count_scale_value": 1.0,
    "stop_tracing_transmittance_threshold": 0.005,     # 0.005
}

SCRIPT = """
import unreal
V = __VALUES__
SAVE = __SAVE__
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
hits = [a for a in eas.get_all_level_actors() if a.get_component_by_class(unreal.VolumetricCloudComponent)]
print('cloud actors ' + str(len(hits)))
changed = False
for a in hits:
    cc = a.get_component_by_class(unreal.VolumetricCloudComponent)
    for n in sorted(V):
        old = cc.get_editor_property(n)
        if V[n] is not None and abs(old - V[n]) > 1e-6:
            a.modify()
            cc.set_editor_property(n, V[n])
            changed = True
        print(a.get_actor_label() + ' ' + n + ' ' + str(old) + ' -> ' + str(cc.get_editor_property(n)))
    cc.mark_render_state_dirty()
    if SAVE and changed:
        print('saved ' + str(unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package()], False)))
"""


def script(values, save):
    return check_banned(SCRIPT.replace("__VALUES__", repr(values)).replace("__SAVE__", repr(bool(save))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["read", "apply"])
    ap.add_argument("--view", type=float)
    ap.add_argument("--shadow", type=float)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    if a.step == "read":
        values = {k: None for k in CLOUD_QUALITY}
    else:
        values = dict(CLOUD_QUALITY)
        if a.view is not None:
            values["view_sample_count_scale"] = a.view
        if a.shadow is not None:
            values["shadow_view_sample_count_scale"] = a.shadow
    ok, out, err = python_run(script(values, a.save and a.step == "apply"))
    print(out.rstrip())
    if not ok:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
