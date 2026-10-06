"""Compare conventional Landscape through one capture's NaniteMeshes flag only."""
from pathlib import Path
import argparse
import hashlib
import json
import prepare_dawn_pose_capture as capture

PREFIX='DawnCaptureShowFlagsRestore:'
COMMON=capture.OWNED+capture.check_pose(capture.cases()[3])+'''
assert not any(str(t).startswith('DawnCaptureHidden:') for t in cap.tags),'Restore owned component A/B first'
location=cap.get_actor_location()
assert max(abs(a-b) for a,b in zip(xyz(location),(298022.1275181769,482808.78355589515,11116.)))<.001,'Keep the paired standing-back camera'
'''


def prepare(out):
    assert not out.exists(),'Preserve previous comparison packets'
    out.mkdir(parents=True);images=out/'images';images.mkdir()
    switch=COMMON+f'''
tags=[str(t) for t in cap.tags]
assert not any(t.startswith({PREFIX!r}) for t in tags),'Restore the existing flag comparison first'
previous=[[str(flag.get_editor_property('show_flag_name')),bool(flag.get_editor_property('enabled'))] for flag in c.get_editor_property('show_flag_settings')]
assert not any(name=='NaniteMeshes' and not enabled for name,enabled in previous),'Baseline already hides Nanite'
receipt={PREFIX!r}+json.dumps(previous,separators=(',',':'))
assert len(receipt)<900,'Bounded flag restoration tag'
cap.set_editor_property('tags',tags+[receipt])
settings=[unreal.EngineShowFlagsSetting(show_flag_name=name,enabled=enabled) for name,enabled in previous if name!='NaniteMeshes']
settings.append(unreal.EngineShowFlagsSetting(show_flag_name='NaniteMeshes',enabled=False))
c.set_editor_property('show_flag_settings',settings)
print('DAWN_CAPTURE_NANITE_OFF '+json.dumps(dict(previous=previous,scope='Owned capture only; conventional Landscape fallback, no CVar change')))
'''
    active=COMMON+f'''
assert sum(str(t).startswith({PREFIX!r}) for t in cap.tags)==1,'Owned flag comparison required'
flags={{str(f.get_editor_property('show_flag_name')):bool(f.get_editor_property('enabled')) for f in c.get_editor_property('show_flag_settings')}}
assert flags.get('NaniteMeshes') is False,'Capture fallback flag not active'
'''
    restore=COMMON+f'''
tags=[str(t) for t in cap.tags];receipts=[t[len({PREFIX!r}):] for t in tags if t.startswith({PREFIX!r})]
assert len(receipts)<=1,'Ambiguous flag restoration'
if receipts:
 previous=json.loads(receipts[0])
 c.set_editor_property('show_flag_settings',[unreal.EngineShowFlagsSetting(show_flag_name=name,enabled=enabled) for name,enabled in previous])
 cap.set_editor_property('tags',[t for t in tags if not t.startswith({PREFIX!r})])
 print('DAWN_CAPTURE_SHOW_FLAGS_RESTORED '+json.dumps(previous))
else:print('DAWN_CAPTURE_SHOW_FLAGS_ALREADY_RESTORED')
'''
    codes={'00_fallback.py':switch,'10_pump.py':active+"c.capture_scene()\nprint('DAWN_CAPTURE_FALLBACK_PUMP')\n",
           '20_export.py':active+f"unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),{images.as_posix()!r},'conventional_landscape.png')\nprint('DAWN_CAPTURE_EXPORTED {images.as_posix()}/conventional_landscape.png')\n",
           '90_restore.py':restore}
    manifest=dict(status='prepared_not_run',order='Restore primitive A/B;00_fallback;10_pump twice in separate calls;20_export;90_restore',
        scope='Owned SceneCapture show flag only; conventional Landscape and other Nanite meshes use their non-Nanite view path. Not a persistent production change.',scripts={})
    for name,code in codes.items():
        capture.ground.checked(code);path=out/name;path.write_text(code,encoding='utf-8')
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('DAWN_CAPTURE_FALLBACK_READY',out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
