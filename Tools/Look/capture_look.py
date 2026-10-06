"""Reproducible look captures along the road, through the editor's level viewport.

    python Tools/Look/capture_look.py <view> <out.png> [--width 1920 --height 1080]
    python Tools/Look/capture_look.py --list

Views are named road positions (walk metres from spline point 54, the carrier dock, toward
point 0, the summit), looking along the road with ground, sky and clouds in frame:
    road_200, road_1050, road_2300, road_4700  (eye 2.5 m above the spline, pitch +4 deg)
    sky_1050                                     (same place, pitch +25 deg, sky and clouds only)
    title                                        (TitleCam's own pose and field of view; a record
                                                  only: its far mountain is not representative)

These are the reference framings for judging the look (ruling R13). Far views of the mountain
are NOT representative in the editor (World Partition renders it as a floating slab with most
tiles unloaded); judge those only after the user's Build HLODs.

The editor usually sits behind other windows, where its level viewport is not redrawn and a
viewport grab comes back black. So it spawns a temporary SceneCapture2D (final colour LDR, which
applies the level's post-process volumes and manual exposure), captures every frame for a few
seconds so Lumen, clouds and fog converge, exports the PNG and destroys the actor again. During the
capture it snapshots real-time skylights as static captures, then restores their original settings.
Wrap it in Tools/GameFlow/editor_gate.py acquire/release. After the capture, run
Tools/Look/measure_look.py on the PNG.
"""
import argparse
import ast
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))

from apply_look import python_run, check_banned  # noqa: E402

EYE_CM = 250.0
LABEL = "Look_TempCapture"  # spawned per capture and destroyed after export
HFOV = 70.0
SOURCES = {"final": "SCS_FINAL_COLOR_LDR", "basecolor": "SCS_BASE_COLOR", "normal": "SCS_NORMAL", "hdr": "SCS_SCENE_COLOR_HDR"}
VIEWS = {  # name: (road metres, pitch deg)
    "road_200": (200.0, 4.0),
    "road_1050": (1050.0, 4.0),
    "road_2300": (2300.0, 4.0),
    "road_4700": (4700.0, 2.0),
    "sky_1050": (1050.0, 25.0),
    "spawn": (0.0, 4.0),
    # FOG2 road stretches (the look at each is apply_look.py --road <m>)
    "road_1000": (1000.0, 2.0),
    "road_2300f": (2300.0, 2.0),
    "cistern": (2950.0, 2.0),
    "climb": (3800.0, 2.0),  # the carrier dock / PlayerStart (task MTNVIEW); aim with --yaw -176.6 at the summit
    # FOG3B: one view at each look key's own road metre that the views above miss (docs/look/APPLY_STORM_LOOK.md)
    "ridge_1500": (1500.0, 2.0),
    "basin_2150": (2150.0, 2.0),
    "basin_2700": (2700.0, 2.0),
    "stair_3650": (3650.0, 2.0),
    "incloud_4350": (4350.0, 2.0),
}

CAM_SCRIPT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
x, y, zs = __X__, __Y__, __ZS__
h = unreal.SystemLibrary.line_trace_single(w, unreal.Vector(x, y, zs + 50000.0), unreal.Vector(x, y, zs - 50000.0), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [], unreal.DrawDebugTrace.NONE, True)
gz = zs
t = h.to_tuple() if h else (False,)
if t[0]:
    gz = t[4].z
cap = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        cap = a
if cap is None:
    cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(x, y, gz + __EYE__))
    cap.set_actor_label('__LABEL__')
cap.set_actor_location_and_rotation(unreal.Vector(x, y, gz + __EYE__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__), False, False)
c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
rt = unreal.RenderingLibrary.create_render_target2d(w, __W__, __H__, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
c.set_editor_property('texture_target', rt)
c.set_editor_property('fov_angle', __FOV__)
c.set_editor_property('capture_source', unreal.SceneCaptureSource.__SRC__)
c.set_editor_property('show_flag_settings', [unreal.EngineShowFlagsSetting(show_flag_name=n, enabled=e) for n, e in __OFF__])
c.set_editor_property('always_persist_rendering_state', True)
c.set_editor_property('capture_every_frame', True)
# UE disables Lumen in scene captures after applying level volumes. Match the
# game's lighting explicitly so a shadowed road is not judged without its GI.
pp = c.get_editor_property('post_process_settings')
pp.set_editor_property('override_dynamic_global_illumination_method', True)
pp.set_editor_property('dynamic_global_illumination_method', unreal.DynamicGlobalIlluminationMethod.LUMEN)
pp.set_editor_property('override_reflection_method', True)
pp.set_editor_property('reflection_method', unreal.ReflectionMethod.LUMEN)
c.set_editor_property('post_process_settings', pp)
print('ground_hit', t[0], 'ground_z', round(gz, 1), 'spline_z', zs)
"""

# FOG2: a background editor does not redraw capture_every_frame, so the settle pumps capture_scene() about
# once a second (LOOK2 found the RVT and the fog history otherwise stay blurry / unconverged).
PUMP_SCRIPT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__LABEL__':
        a.get_component_by_class(unreal.SceneCaptureComponent2D).capture_scene()
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

# Realtime skylight capture and an editor SceneCapture can contend for the scene's
# captured-sky lighting. Temporarily make each realtime sky static and queue one
# scene recapture for these reference images; the original flags are restored by
# run_capture_scripts even when capture setup or export fails.
SKY_PREPARE_SCRIPT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
states, skies = [], []
for a in eas.get_all_level_actors():
    c = a.get_component_by_class(unreal.SkyLightComponent)
    if c is None:
        continue
    was_realtime = bool(c.get_editor_property("real_time_capture"))
    states.append((a.get_actor_label(), was_realtime))
    skies.append((c, was_realtime))
# Report every original flag before the first mutation. If a later engine call fails,
# the host still has enough information to restore every skylight in its finally block.
print("SKY_STATE " + repr(states))
for c, was_realtime in skies:
    if was_realtime:
        c.set_real_time_capture(False)
        c.recapture_sky()
'''

SKY_RESTORE_SCRIPT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
states = __STATES__
by_label = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
restored, missing = [], []
for label, was_realtime in states:
    a = by_label.get(label)
    c = a.get_component_by_class(unreal.SkyLightComponent) if a else None
    if c is None:
        missing.append(label)
        continue
    c.set_real_time_capture(was_realtime)
    restored.append(label)
print("SKY_RESTORE restored=" + str(restored) + " missing=" + str(missing))
if missing:
    raise RuntimeError("could not restore skylights " + str(missing))
'''

CLEANUP_CAPTURE_SCRIPT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
removed = []
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__LABEL__":
        eas.destroy_actor(a)
        removed.append(a.get_actor_label())
print("CAPTURE_CLEANUP removed=" + str(removed))
'''


TITLE_READ = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == 'TitleCam':
        l = a.get_actor_location()
        r = a.get_actor_rotation()
        f = a.get_cine_camera_component().get_editor_property('field_of_view')
        print('POSE', l.x, l.y, l.z, r.pitch, r.yaw, f)
"""


def title_pose():
    ok, out, err = python_run(check_banned(TITLE_READ))
    for line in out.splitlines():
        if line.startswith("POSE"):
            return [float(v) for v in line.split()[1:]]
    raise SystemExit(f"TitleCam not found: {err}")


def view_pose(name):
    from build_road_profile import SPLINE_POINTS_CM, Road
    s, pitch = VIEWS[name]
    road = Road(SPLINE_POINTS_CM)
    p = road.xy(s)
    q = road.xy(min(s + 60.0, road.length))
    yaw = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    return float(p[0]), float(p[1]), float(road.spline_z_m(s) * 100.0), pitch, yaw


def _sky_states(stdout):
    for line in stdout.splitlines():
        if line.startswith("SKY_STATE "):
            value = ast.literal_eval(line[len("SKY_STATE "):])
            if not isinstance(value, list):
                raise ValueError("invalid skylight state from editor")
            return value
    raise ValueError("editor did not report the original skylight state")


def run_capture_scripts(setup_script, pump_script, export_script, settle_s, pump_enabled, capture_label=LABEL):
    """Capture while using a static skylight snapshot, restoring all temporary editor state."""
    import time

    outputs = []
    states = None
    ok, err = False, ""
    try:
        prep_ok, prep_out, prep_err = python_run(check_banned(SKY_PREPARE_SCRIPT))
        outputs.append(prep_out.strip())
        try:
            states = _sky_states(prep_out)
        except (ValueError, SyntaxError):
            if prep_ok:
                raise
        if not prep_ok:
            err = prep_err or "skylight preparation failed"
        else:
            setup_ok, setup_out, setup_err = python_run(check_banned(setup_script))
            outputs.append(setup_out.strip())
            if not setup_ok:
                err = setup_err or "capture setup failed"
            else:
                end = time.time() + settle_s
                while time.time() < end:
                    time.sleep(min(1.0, max(0.0, end - time.time())))
                    if pump_enabled:
                        pump_ok, pump_out, pump_err = python_run(check_banned(pump_script))
                        if pump_out.strip():
                            outputs.append(pump_out.strip())
                        if not pump_ok:
                            err = pump_err or "capture pump failed"
                            break
                if not err:
                    export_ok, export_out, export_err = python_run(check_banned(export_script))
                    outputs.append(export_out.strip())
                    ok = export_ok
                    if not export_ok:
                        err = export_err or "capture export failed"
    except Exception as exc:
        err = str(exc)
    finally:
        if states is not None:
            # These are separate calls so capture cleanup cannot prevent restoring the game sky.
            try:
                cleanup_ok, cleanup_out, cleanup_err = python_run(
                    check_banned(CLEANUP_CAPTURE_SCRIPT.replace("__LABEL__", capture_label)))
                outputs.append(cleanup_out.strip())
                if not cleanup_ok:
                    ok = False
                if not cleanup_ok and not err:
                    err = cleanup_err or "capture cleanup failed"
            except Exception as exc:
                if not err:
                    err = f"capture cleanup failed: {exc}"
            try:
                restore = SKY_RESTORE_SCRIPT.replace("__STATES__", repr(states))
                restore_ok, restore_out, restore_err = python_run(check_banned(restore))
                outputs.append(restore_out.strip())
                if not restore_ok:
                    ok = False
                    err = err or restore_err or "skylight restoration failed"
            except Exception as exc:
                ok = False
                err = err or f"skylight restoration failed: {exc}"
    return ok, "\n".join(line for line in outputs if line), err


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("view", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-pump", dest="pump", action="store_false", help="do not call capture_scene() each second of the settle")
    ap.add_argument("--settle-s", type=float, default=4.0, help="seconds of per-frame capture before export")
    ap.add_argument("--yaw", type=float, help="override the view's yaw (deg), e.g. aim the title position at the beacon")
    ap.add_argument("--pitch", type=float, help="override the view's pitch (deg)")
    ap.add_argument("--eye", type=float, help="override the eye height above the ground (cm)")
    ap.add_argument("--fov", type=float, help="override the horizontal field of view (deg); the carrier camera is 90 at eye 120 cm")
    ap.add_argument("--at", type=float, nargs=2, metavar=("X", "Y"), help="override the view's position (world cm)")
    ap.add_argument("--source", choices=sorted(SOURCES), default="final",
                    help="final (the look, default); basecolor or normal (GBuffer: lighting- and "
                         "exposure-independent, for checking what the ground material draws); hdr (scene colour before exposure)")
    ap.add_argument("--show-off", nargs="*", default=[], metavar="FLAG",
                    help="engine show flags to set on the capture only: NAME turns it off, NAME=1 on "
                         "(e.g. SkyLighting DirectionalLights LightingOnlyOverride=1)")
    a = ap.parse_args(argv)
    if a.list or not a.view:
        print("title", "(TitleCam pose, read from the level)")
        for n in VIEWS:
            print(n, [round(v, 1) for v in view_pose(n)])
        return 0
    if a.view == "title":
        x, y, zs, pitch, yaw, fov = title_pose()
        # keep TitleCam's own height: no ground trace
        script = chr(10).join("t = (False,)" if ln.startswith("h = ") else ln
                              for ln in CAM_SCRIPT.splitlines() if not ln.startswith("t = h."))
        eye = 0.0
    else:
        x, y, zs, pitch, yaw = view_pose(a.view)
        script, eye, fov = CAM_SCRIPT, EYE_CM, HFOV
    if a.at:
        x, y = a.at
    if a.yaw is not None:
        yaw = a.yaw
    if a.pitch is not None:
        pitch = a.pitch
    if a.eye is not None:
        eye = a.eye
    if a.fov is not None:
        fov = a.fov
    script = (script.replace("__X__", repr(x)).replace("__Y__", repr(y)).replace("__ZS__", repr(zs))
              .replace("__EYE__", repr(eye)).replace("__P__", repr(pitch)).replace("__YAW__", repr(yaw))
              .replace("__FOV__", repr(fov)).replace("__LABEL__", LABEL)
              .replace("__W__", str(a.width)).replace("__H__", str(a.height))
              .replace("__SRC__", SOURCES[a.source]).replace("__OFF__", repr([(f.split("=")[0], f.endswith("=1")) for f in a.show_off])))
    pump = check_banned(PUMP_SCRIPT.replace("__LABEL__", LABEL))
    outp = pathlib.Path(a.out).resolve()
    outp.parent.mkdir(parents=True, exist_ok=True)
    ex = (EXPORT_SCRIPT.replace("__LABEL__", LABEL).replace("__DIR__", outp.parent.as_posix())
          .replace("__NAME__", outp.name))
    ok, out, err = run_capture_scripts(script, pump, ex, a.settle_s, a.pump)
    print(out.strip())
    if not ok or not outp.exists():
        print("capture failed:", err, file=sys.stderr)
        return 1
    print(outp, "pose", [round(v, 1) for v in (x, y, zs, pitch, yaw)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
