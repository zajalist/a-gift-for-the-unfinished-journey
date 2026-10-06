"""Stage the existing SceneCapture final-LDR route; root executes each bounded phase."""
from pathlib import Path
import argparse
import ast
import json
import math
from prepare_ground_contact_loading import HEAD

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/GroundContactSurvey/capture'
LABEL = 'GroundContact_VerificationCapture'
TAG = 'Saskarta.GroundContactVerification'

SETUP = HEAD + '''
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
captures = [a for a in unreal.ObjectIterator(unreal.SceneCapture2D) if a.get_world() == world]
if any(a.get_actor_label() == '__LABEL__' for a in captures):
    raise RuntimeError('Owned capture already exists; cleanup or reuse it explicitly')
__FRAME__
cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, location, rotation, True)
if cap is None:
    raise RuntimeError('Temporary SceneCapture spawn failed')
cap.set_actor_label('__LABEL__')
cap.set_editor_property('tags', ['__TAG__'])
cap.set_editor_property('is_editor_only_actor', True)
sky_comps = []
restore_tags = ['__TAG__']
for a in actors:
    s = a.get_component_by_class(unreal.SkyLightComponent)
    if s is not None and s.get_editor_property('real_time_capture'):
        sky_comps.append(s)
        restore_tags.append('GroundCaptureSkyRestore:' + s.get_path_name())
cap.set_editor_property('tags', restore_tags)
c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
rt = unreal.RenderingLibrary.create_render_target2d(world,1280,720,unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
c.set_editor_property('texture_target',rt)
c.set_editor_property('fov_angle',__FOV__)
c.set_editor_property('capture_source',unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
c.set_editor_property('always_persist_rendering_state',True)
c.set_editor_property('capture_every_frame',False)
c.set_editor_property('capture_on_movement',False)
pp = c.get_editor_property('post_process_settings')
pp.set_editor_property('override_dynamic_global_illumination_method',True)
pp.set_editor_property('dynamic_global_illumination_method',unreal.DynamicGlobalIlluminationMethod.LUMEN)
pp.set_editor_property('override_reflection_method',True)
pp.set_editor_property('reflection_method',unreal.ReflectionMethod.LUMEN)
c.set_editor_property('post_process_settings',pp)
for s in sky_comps:
    s.set_real_time_capture(False)
    s.recapture_sky()
c.capture_scene()
print('GROUND_CAPTURE_SETUP '+json.dumps({'actor':cap.get_path_name(),'location':xyz(location),
      'rotation':str(rotation),'fov':__FOV__,'size':[1280,720],'sky_restore_tags':restore_tags[1:],
      'saved':False},separators=(',',':')))
'''

OWNED = HEAD + '''
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
matches = [a for a in unreal.ObjectIterator(unreal.SceneCapture2D)
           if a.get_world() == world and a.get_actor_label() == '__LABEL__']
if len(matches)!=1 or '__TAG__' not in [str(t) for t in matches[0].tags]:
    raise RuntimeError('Exactly one owned temporary capture required')
cap = matches[0]
c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
'''

PUMP = OWNED + '''
c.capture_scene()
print('GROUND_CAPTURE_PUMP '+cap.get_path_name())
'''

EXPORT = OWNED + '''
unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),'__DIRECTORY__','__NAME__.png')
print('GROUND_CAPTURE_EXPORTED __DIRECTORY__/__NAME__.png')
'''

CLEANUP = OWNED + '''
restore = [str(t).split('GroundCaptureSkyRestore:',1)[1] for t in cap.tags if str(t).startswith('GroundCaptureSkyRestore:')]
restored = []
for s in unreal.ObjectIterator(unreal.SkyLightComponent):
    if s.get_world() == world and s.get_path_name() in restore:
        s.set_real_time_capture(True)
        restored.append(s.get_path_name())
if set(restored)!=set(restore):
    raise RuntimeError('A captured skylight is not loaded; preserve helper until flags can be restored')
removed = eas.destroy_actor(cap)
if not removed:
    raise RuntimeError('Owned temporary capture cleanup failed')
print('GROUND_CAPTURE_CLEANUP '+json.dumps({'removed':bool(removed),'restored_skylights':restored,'saved':False}))
'''


def checked(body):
    ast.parse(body)
    for word in ('try', 'getattr', 'import time', 'open(', 'save_asset', 'save_packages', '.replace('):
        if word in body:
            raise ValueError('Unexpected capture policy token ' + word)
    return body


def summit_frame(preset='human_summit_vista'):
    """Representative Human drone vista from authored summit staging, not a recorded user pose."""
    post = json.loads((ROOT / 'Tools/Cinematics/probe_ending.json').read_text())['radio_post']
    floor, rest = post['collapse'], post['drone_rest']
    if preset in ('summit_basin','summit_sun'):
        frame='location = unreal.Vector(*'+repr([rest[0],rest[1],rest[2]+220])+')\n'
        if preset=='summit_basin':
            # S26_Tripo documents the outward seated vista as east from the collar.
            frame+='rotation = unreal.Rotator(pitch=-7.0,yaw=0.0,roll=0.0)\n'
        else:
            frame+='''suns = [a for a in actors if a.get_class().get_name()=='DirectionalLight'
        and a.get_component_by_class(unreal.DirectionalLightComponent).get_editor_property('atmosphere_sun_light')]
if len(suns)!=1:
    raise RuntimeError('Exactly one live atmosphere sun required for the disk preservation view')
rotation = unreal.MathLibrary.find_look_at_rotation(location, location-suns[0].get_actor_forward_vector()*10000.0)
'''
        return frame,75.0
    # Look along the authored final-drone/collapse bearing, out across the basin.
    yaw = math.atan2(floor[1]-rest[1], floor[0]-rest[0])
    focus = [floor[0], floor[1], floor[2]+92.0+40.0]
    # UpdateHumanEscort uses (-420,60,-424*tan(pitch)), 75-degree lens.
    # Omit hover drift for deterministic before/after comparison.
    eye = [focus[0]-420*math.cos(yaw)-60*math.sin(yaw),
           focus[1]-420*math.sin(yaw)+60*math.cos(yaw),
           focus[2]-424*math.tan(math.radians(-7.0))]
    frame = 'location = unreal.Vector(*' + repr(eye) + ')\n'
    frame += 'rotation = unreal.MathLibrary.find_look_at_rotation(location, unreal.Vector(*' + repr(focus) + '))\n'
    return frame, 75.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', default='descent_cart_scene')
    ap.add_argument('--target', default='SD_L06_DescentCarts_001', help='Exact actor label; empty string uses the current viewport pose')
    ap.add_argument('--preset', choices=['human_summit_vista','summit_basin','summit_sun'], help='Authored summit vista or current atmosphere sun direction; overrides target')
    args = ap.parse_args()
    if not args.name.replace('_','').isalnum():
        raise ValueError('Use a simple output name')
    fov = 60.0
    if args.preset:
        frame, fov = summit_frame(args.preset)
    elif args.target:
        frame = '''targets = [a for a in actors if a.get_actor_label() == __TARGET__]
if len(targets)!=1:
    raise RuntimeError('Capture target must resolve once in the loaded world')
centre, extent = targets[0].get_actor_bounds(False)
location = centre + unreal.Vector(450,-600,260)
rotation = unreal.MathLibrary.find_look_at_rotation(location,centre)
'''.replace('__TARGET__',repr(args.target))
    else:
        frame = 'location, rotation = es.get_level_viewport_camera_info()\n'
    directory = (ROOT / 'Saved/Verification/playtest_feedback_20261001').as_posix()
    bodies = [('setup',SETUP.replace('__FRAME__',frame)),('pump',PUMP),('export',EXPORT),('cleanup',CLEANUP)]
    OUT.mkdir(parents=True,exist_ok=True)
    for phase,body in bodies:
        body=body.replace('__LABEL__',LABEL).replace('__TAG__',TAG).replace('__DIRECTORY__',directory).replace('__NAME__',args.name).replace('__FOV__',str(fov))
        path=OUT/(args.name+'_'+phase+'.py');path.write_text(checked(body),encoding='utf-8');print(path)


if __name__ == '__main__':
    main()
