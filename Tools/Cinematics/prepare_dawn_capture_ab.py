"""Hide one measured suspect only in the owned SceneCapture, then restore it."""
from pathlib import Path
import argparse
import hashlib
import json
import prepare_dawn_pose_capture as capture

ROOT=capture.ROOT
EVIDENCE=ROOT/'Saved/Verification/dawn_pose_visibility_20261001_v1/readbacks/20_ray_bounds.readback.json'


def prepare(out):
    assert not out.exists(),'Preserve earlier A/B evidence'
    raw=json.loads(EVIDENCE.read_text())['output']
    result=json.loads(next(line.split(' ',1)[1] for line in raw.splitlines() if line.startswith('DAWN_PREVIEW_RAY_BOUNDS ')))
    selectors=[('road54','PCGSplineMeshComponent_SM_Saskarta_RoadRibbon_54'),
               ('hlod91ba','Saskarta_WP_HLODLayer_Merged_91ba2f6c7320dcbe.StaticMeshComponent_49'),
               ('landscape_nanite','LandscapeNaniteComponent_0')]
    selected=[]
    for label,suffix in selectors:
        rows=[row for row in result['rows'] if row['component'].endswith(suffix)]
        assert len(rows)==1,(label,rows)
        selected.append((label,rows[0]))
    paths=[row['component'] for _,row in selected]
    guard=capture.OWNED+capture.check_pose(capture.cases()[3])+f'''
assert mesh.get_editor_property('animation_data').get_editor_property('anim_to_play').get_path_name().endswith('A_Samyor_FinalCollapse.A_Samyor_FinalCollapse'),'Keep the standing-back comparison pose'
location=cap.get_actor_location()
assert max(abs(a-b) for a,b in zip(xyz(location),(298022.1275181769,482808.78355589515,11116.)))<.001,'Keep the paired standing-back camera'
current=[str(t).split('DawnCaptureHidden:',1)[1] for t in cap.tags if str(t).startswith('DawnCaptureHidden:')]
assert len(current)<=1,'Ambiguous owned capture comparison receipt'
assert all(path in {paths!r} for path in current),'Unexpected existing capture-hidden component'
'''
    out.mkdir(parents=True);images=out/'images';images.mkdir();codes={}
    manifest=dict(status='prepared_not_run',scope='Only the owned SceneCapture HiddenComponents list changes; no world primitive visibility/collision or CVar changes',
        baseline=str(ROOT/'Saved/Verification/dawn_pose_capture_20261001_v2/images/standing_back.png'),
        order='For one suspect: hide, pump twice in separate calls, export; repeat as needed.90_restore then optionally99_cleanup from capture packet.',scripts={},suspects=selected,
        caveat='Hiding the Nanite component may leave no conventional landscape fallback; a revealed body identifies that primitive as occluding, not a fully accepted terrain repair.')
    for i,(label,row) in enumerate(selected,1):
        prefix=f'{i}0_{label}'
        codes[prefix+'_hide.py']=guard+f'''
found=[v for v in unreal.ObjectIterator(unreal.PrimitiveComponent) if v.get_world()==world and v.get_path_name()=={row['component']!r}]
assert len(found)==1 and found[0].get_class().get_name()=={row['class_name']!r},'Exact measured suspect required'
c.clear_hidden_components();c.hide_component(found[0])
cap.set_editor_property('tags',[str(t) for t in cap.tags if not str(t).startswith('DawnCaptureHidden:')]+['DawnCaptureHidden:'+found[0].get_path_name()])
print('DAWN_CAPTURE_ONLY_HIDDEN '+found[0].get_path_name())
'''
        verify=f"assert current=={[row['component']]!r},'Comparison hidden target mismatch'\n"
        codes[prefix+'_pump.py']=guard+verify+f"c.capture_scene()\nprint('DAWN_AB_CAPTURE_PUMP {label}')\n"
        codes[prefix+'_export.py']=guard+verify+f"unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),{images.as_posix()!r},{(label+'.png')!r})\nprint('DAWN_AB_EXPORTED {images.as_posix()}/{label}.png')\n"
    codes['90_restore.py']=guard+"c.clear_hidden_components()\ncap.set_editor_property('tags',[str(t) for t in cap.tags if not str(t).startswith('DawnCaptureHidden:')])\nprint('DAWN_CAPTURE_HIDDEN_COMPONENTS_RESTORED_EMPTY')\n"
    for name,code in codes.items():
        capture.ground.checked(code);path=out/name;path.write_text(code,encoding='utf-8')
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('DAWN_CAPTURE_AB_READY',out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
