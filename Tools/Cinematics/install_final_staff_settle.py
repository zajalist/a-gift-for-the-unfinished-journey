"""Update only staff011 in the two installed final clips under the root lease."""
from pathlib import Path
import argparse
import ast
import json
import sys

import samyor_final as final
import samyor_reveal as rig

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools/GameFlow/editor'))
import install_ending_folder as bounded

BASELINE=ROOT/'Saved/Verification/ending_dawn_composition_20261001_v2/final'
FOLDER='final_staff'
SOURCES=('Tools/Cinematics/install_final_staff_settle.py','Tools/Cinematics/samyor_final.py',
         'Tools/Cinematics/samyor_reveal.py','Tools/Cinematics/traveller_contacts.py',
         'Tools/Cinematics/traveller_terrain.py','Tools/Cinematics/traveller_gaze.py',
         'Tools/Cinematics/ending_staging.py','Tools/Cinematics/traveller_pose_samples.json',
         'Tools/Cinematics/traveller_ref_pose.json')


def baseline_tracks():
    tracks={name:{} for name in final.CLIPS}
    for path in BASELINE.glob('*_keys_*.py'):
        name=next(name for name in tracks if name in path.name)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.For) and ast.unparse(node.target)=='(bone, P, R, S)':
                for bone,positions,rotations,scale in ast.literal_eval(node.iter):
                    tracks[name][bone]=[(tuple(p),tuple(q),tuple(scale)) for p,q in zip(positions,rotations)]
    assert all(set(row)==set(final.TRACKS) for row in tracks.values())
    return tracks


def inputs():
    paths=[ROOT/name for name in SOURCES]+sorted(BASELINE.glob('*_keys_*.py'))
    return {str(p):bounded.digest(p) for p in paths}


def read_code(name, old, new, allow_old):
    count=final.CLIPS[name]
    # All key times, local rotations and scales are checked. The two acceptable
    # position arrays make a partially completed save group safely repeatable.
    records=[(a[0],b[0],b[1],b[2]) for a,b in zip(old,new)]
    return f'''import unreal
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
an=unreal.load_asset({(rig.ANIM_DIR+'/'+name)!r});assert isinstance(an,unreal.AnimSequence)
assert an.get_editor_property('skeleton').get_path_name()=={(rig.SKEL+'.SKEL_Traveller')!r}
assert abs(an.get_play_length()-{count/final.FPS!r})<.0001 and abs(an.get_editor_property('rate_scale')-1.)<.0001
model=an.get_editor_property('data_model_interface');rate=model.get_frame_rate()
assert rate.numerator=={final.FPS} and rate.denominator==1 and model.get_number_of_frames()=={count} and model.get_number_of_keys()=={count+1}
names=[str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(an)]
assert len(names)=={len(final.TRACKS)} and set(names)=={set(b.casefold() for b in final.TRACKS)!r}
old_error=0.;new_error=0.
for index,(old_position,new_position,wanted_rotation,wanted_scale) in enumerate({records!r}):
 pose=unreal.AnimationLibrary.get_bone_pose_for_time(an,'staff011',index/{final.FPS}.,False)
 p=pose.get_editor_property('translation');q=pose.get_editor_property('rotation');s=pose.get_editor_property('scale3d')
 old_error=max(old_error,sum((a-b)**2 for a,b in zip((p.x,p.y,p.z),old_position))**.5)
 new_error=max(new_error,sum((a-b)**2 for a,b in zip((p.x,p.y,p.z),new_position))**.5)
 assert abs(sum(a*b for a,b in zip((q.x,q.y,q.z,q.w),wanted_rotation)))>.999999,'Staff rotation changed'
 assert max(abs(a-b) for a,b in zip((s.x,s.y,s.z),wanted_scale))<.0001,'Staff scale changed'
assert {'min(old_error,new_error)' if allow_old else 'new_error'}<.00005,('Unexpected installed staff keys',old_error,new_error)
print('STAFF_KEYS_ACCEPTED {name}', 'old_error',old_error,'new_error',new_error)
'''


def prepare(packet):
    assert not packet.exists(),'Preserve previous install receipts'
    old=baseline_tracks();new=final.baked();codes={};proof={}
    for i,(name,(count,tracks)) in enumerate(new.items()):
        changed=[bone for bone in tracks if tracks[bone]!=old[name][bone]]
        assert changed==['staff011'],(name,changed)
        assert all(a[1:]==b[1:] for a,b in zip(old[name]['staff011'],tracks['staff011']))
        before=read_code(name,old[name]['staff011'],tracks['staff011'],True)
        after=read_code(name,old[name]['staff011'],tracks['staff011'],False)
        states=tracks['staff011'];positions=[s[0] for s in states];rotations=[s[1] for s in states];scales=[s[2] for s in states]
        codes[f'{i}0_preflight_{name}.py']=before
        codes[f'{i}1_keys_{name}.py']=before+f'''
c=an.get_editor_property('controller')
c.open_bracket('Final released staff contact only',False)
c.set_bone_track_keys('staff011',[unreal.Vector(*p) for p in {positions!r}],[unreal.Quat(*q) for q in {rotations!r}],[unreal.Vector(*s) for s in {scales!r}],False)
c.close_bracket(False)
print('STAFF_TRACK_UPDATED {name} keys {len(states)}')
'''
        codes[f'{i}2_verify_{name}.py']=after
        codes[f'{i}9_save_{name}.py']=f'''import unreal
print('{name}', 'saved',unreal.EditorAssetLibrary.save_asset({(rig.ANIM_DIR+'/'+name)!r},only_if_is_dirty=False))
'''
        proof[name]=dict(changed_tracks=changed,unchanged_tracks=len(tracks)-1,frames=count,fps=final.FPS,all_rotations_scales_unchanged=True)
    codes['99_read.py']='\n'.join(read_code(name,old[name]['staff011'],new[name][1]['staff011'],False) for name in new)
    folder=packet/FOLDER;folder.mkdir(parents=True)
    for name,code in codes.items():
        compile(code,name,'exec');assert not bounded.editor.banned(code)
        (folder/name).write_text(code,encoding='utf-8')
    manifest=dict(scope='Only staff011 translations in two existing final clips; no track creation/removal, sequence, body, material or other animation changes',
        proof=proof,input_sha256=inputs(),script_sha256={name:bounded.digest(folder/name) for name in codes})
    bounded.save_state(packet/'manifest.json',manifest)
    return check(packet)


def check(packet):
    manifest=json.loads((packet/'manifest.json').read_text())
    assert manifest['input_sha256']==inputs(),'Source/baseline changed; prepare a new packet'
    expected=manifest['script_sha256'];folder=packet/FOLDER
    assert set(expected)=={p.name for p in folder.glob('*.py')}
    groups=[];pending=[]
    for name in sorted(expected):
        path=folder/name;assert bounded.digest(path)==expected[name],'Packet changed: '+name
        code=path.read_text();compile(code,name,'exec');assert not bounded.editor.banned(code)
        pending.append(name)
        if bounded.is_save(name):
            package=bounded.target_of_save(code);bounded.require_writable(bounded.package_file(package,ROOT))
            groups.append(dict(id=name,steps=pending,package=package));pending=[]
    assert pending==['99_read.py'] and len(groups)==2
    groups[-1]['steps']+=pending
    return dict(folder=FOLDER,prepared=str(packet),audit_sha256=bounded.digest(packet/'manifest.json'),
                script_sha256=expected,input_sha256=manifest['input_sha256'],groups=groups)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('prepare','check','run'));p.add_argument('--packet',type=Path,required=True)
    p.add_argument('--owner');p.add_argument('--max-groups',type=int,default=1)
    args=p.parse_args();packet=args.packet.resolve()
    plan=prepare(packet) if args.mode=='prepare' else check(packet)
    if args.mode!='run':
        print(json.dumps(dict(packet=str(packet),scripts=len(plan['script_sha256']),groups=len(plan['groups'])),indent=2));return
    if not args.owner:p.error('run requires existing owner')
    connection=bounded.EditorConnection(args.owner)
    def guard():check(packet);connection.guard()
    bounded.run_plan(plan,packet/'install_logs/final_staff.json',connection.send,guard,max_groups=args.max_groups)


if __name__=='__main__':main()
