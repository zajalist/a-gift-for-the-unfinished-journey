"""Recover the owned transient body for game-showflag captures; no asset edits."""
from pathlib import Path
import argparse
import hashlib
import json

import prepare_dawn_pose_capture as capture

PREFIX = 'DawnBodyVisibilityRestore:'
HLOD = '/Game/level/Saskarta_WP.Saskarta_WP:PersistentLevel.Saskarta_WP_HLODLayer_Merged_91ba2f6c7320dcbe.StaticMeshComponent_49'


def prepare(out):
    assert not out.exists(), 'Preserve capture evidence'
    out.mkdir(parents=True)
    images = out / 'images'; images.mkdir()
    begin = capture.OWNED + capture.check_pose(capture.cases()[3]) + f'''
tags=[str(t) for t in cap.tags]
assert not any(t.startswith(('DawnCaptureHidden:','DawnCaptureShowFlagsRestore:',{PREFIX!r})) for t in tags),'Restore previous comparisons first'
assert mesh.is_visible(),'Owned mesh must initially be visible'
flags=[[str(f.get_editor_property('show_flag_name')),bool(f.get_editor_property('enabled'))] for f in c.get_editor_property('show_flag_settings')]
assert c.get_editor_property('primitive_render_mode')==unreal.SceneCapturePrimitiveRenderMode.PRM_LEGACY_SCENE_CAPTURE
found=[v for v in unreal.ObjectIterator(unreal.PrimitiveComponent) if v.get_world()==world and v.get_path_name()=={HLOD!r}]
assert len(found)==1 and found[0].get_class().get_name()=='StaticMeshComponent','Exact observed HLOD required'
receipt={PREFIX!r}+json.dumps(dict(editor_only=bool(body.get_editor_property('is_editor_only_actor')),flags=flags),separators=(',',':'))
assert len(receipt)<900,'Bounded restore metadata'
cap.set_editor_property('tags',tags+[receipt])
body.set_editor_property('is_editor_only_actor',False)
# Actor editor-only status is cached in the primitive proxy. Visibility toggles
# mark its render state dirty, so the next editor tick rebuilds that proxy.
mesh.set_visibility(False,False);mesh.set_visibility(True,False)
c.clear_hidden_components();c.hide_component(found[0])
settings=[unreal.EngineShowFlagsSetting(show_flag_name=name,enabled=enabled) for name,enabled in flags if name!='NaniteMeshes']
settings.append(unreal.EngineShowFlagsSetting(show_flag_name='NaniteMeshes',enabled=False))
c.set_editor_property('show_flag_settings',settings)
print('DAWN_BODY_GAME_VISIBLE '+json.dumps(dict(editor_only=body.get_editor_property('is_editor_only_actor'),hidden_hlod={HLOD!r},nanite_view=False,saved=False)))
'''
    active = capture.OWNED + f'''
assert sum(str(t).startswith({PREFIX!r}) for t in cap.tags)==1,'Owned restoration receipt required'
assert not body.get_editor_property('is_editor_only_actor') and mesh.is_visible(),'Game-visible owned body required'
flags={{str(f.get_editor_property('show_flag_name')):bool(f.get_editor_property('enabled')) for f in c.get_editor_property('show_flag_settings')}}
assert flags.get('NaniteMeshes') is False,'Keep the conventional Landscape comparison'
'''
    codes = {'00_enable_body.py': begin}
    for prefix, row in [('10_standing_back', capture.cases()[3]), ('30_final', capture.cases()[2])]:
        check = active + capture.check_pose(row)
        codes[prefix+'_pump.py'] = check + "c.capture_scene()\nprint('DAWN_VISIBLE_BODY_PUMP')\n"
        codes[prefix+'_export.py'] = check + f"unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),{images.as_posix()!r},{(row['name']+'.png')!r})\nprint('DAWN_VISIBLE_BODY_EXPORTED {images.as_posix()}/{row['name']}.png')\n"
    # Reuse the installed-pose selection verbatim; this changes only the owned
    # body/camera and evaluates the already verified production animation.
    codes['20_final_pose.py'] = (capture.ROOT/'Saved/Verification/dawn_pose_capture_20261001_v2/30_final_pose.py').read_text()
    codes['90_restore.py'] = capture.OWNED + f'''
tags=[str(t) for t in cap.tags];receipts=[t[len({PREFIX!r}):] for t in tags if t.startswith({PREFIX!r})]
assert len(receipts)<=1,'Ambiguous body visibility restoration'
if receipts:
 previous=json.loads(receipts[0])
 c.clear_hidden_components()
 c.set_editor_property('show_flag_settings',[unreal.EngineShowFlagsSetting(show_flag_name=name,enabled=enabled) for name,enabled in previous['flags']])
 body.set_editor_property('is_editor_only_actor',previous['editor_only'])
 mesh.set_visibility(False,False);mesh.set_visibility(True,False)
 cap.set_editor_property('tags',[t for t in tags if not t.startswith({PREFIX!r})])
 print('DAWN_BODY_VISIBILITY_RESTORED '+json.dumps(previous))
else:print('DAWN_BODY_VISIBILITY_ALREADY_RESTORED')
'''
    manifest = dict(status='prepared_not_run', order='00_enable_body; allow editor tick;10_standing_back_pump twice then export;20_final_pose;30_final_pump twice then export;90_restore; owned99_cleanup when finished',
        scope='Only owned transient body editor-only flag and SceneCapture hidden/flag settings. No production actor, geometry, material, CVar, asset or world save.',
        evidence=['SceneCaptureComponent.cpp169 initializes ESFIM_Game', 'PrimitiveSceneProxy.cpp520 caches owner editor-only in DrawInAnyEditMode', 'PrimitiveSceneProxy.cpp1525-1533 excludes that proxy from Game views', 'SceneComponent.cpp3588-3630 visibility dirties render state'],scripts={})
    for name, code in codes.items():
        capture.ground.checked(code)
        path = out/name; path.write_text(code,encoding='utf-8')
        manifest['scripts'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('DAWN_BODY_VISIBILITY_FIX_READY',out)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
