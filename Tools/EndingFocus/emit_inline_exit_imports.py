"""Convert review JSON into plain literal controller chunks, no embedded I/O.

No dynamic decode, filesystem/network access, eval, try or imported helper is
used by generated editor scripts. SHA digests remain host-side receipt metadata.
"""
from pathlib import Path
import json
import hashlib
import argparse
ROOT=Path(__file__).resolve().parents[2]

CREATE='''import unreal
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
full={path!r}
assert not unreal.EditorAssetLibrary.does_asset_exist(full),'Read existing outcome before any replay'
f=unreal.AnimSequenceFactory()
f.set_editor_property('target_skeleton',unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SKEL_Traveller'))
an=unreal.AssetToolsHelpers.get_asset_tools().create_asset({name!r},'/Game/SaskartaGaea/Characters/Traveller/Anims',unreal.AnimSequence,f)
assert an
c=an.get_editor_property('controller')
c.set_frame_rate(unreal.FrameRate(30,1),False)
c.set_number_of_frames(unreal.FrameNumber({frames}),False)
an.set_editor_property('enable_root_motion',False)
print('EXIT_CREATE',full,{frames})
'''
KEYS='''import unreal
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
an=unreal.load_asset({path!r});assert an
c=an.get_editor_property('controller')
names=set(str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(an))
c.open_bracket('Measured capsule contact bone keys',False)
for bone,P,R,S in {data}:
    if bone.casefold() not in names:c.add_bone_curve(bone,False)
    count={keys}
    pos=[unreal.Vector(*P)]*count if len(P)==3 and isinstance(P[0],(int,float)) else [unreal.Vector(*p) for p in P]
    rot=[unreal.Quat(*R)]*count if len(R)==4 and isinstance(R[0],(int,float)) else [unreal.Quat(*q) for q in R]
    c.set_bone_track_keys(bone,pos,rot,[unreal.Vector(*S)]*count,False)
c.close_bracket(False)
print('EXIT_KEYS',{path!r},[x[0] for x in {names}],{keys})
'''
SAVE='''import unreal,json
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
an=unreal.load_asset({path!r});assert an
tracks=[str(n) for n in unreal.AnimationLibrary.get_animation_track_names(an)]
assert len(tracks)==68 and len(set(n.casefold() for n in tracks))==68
assert set(n.casefold() for n in tracks)==set(n.casefold() for n in {bones!r})
assert abs(an.get_play_length()-{frames}/30.)<.001
assert unreal.EditorAssetLibrary.save_asset({path!r},only_if_is_dirty=False)
print('EXIT_SAVED '+json.dumps(dict(asset={path!r},frames={frames},tracks=tracks,length=an.get_play_length(),production_accepted=False),separators=(',',':')))
'''


def emit(source,out,suffix='_InlineV5'):
    assert not out.exists(),'Preserve prior outcomes'
    out.mkdir(parents=True)
    count=0
    for file in sorted(source.glob('A_*.json')):
        data=json.loads(file.read_text());name=data['name']+suffix;path='/Game/SaskartaGaea/Characters/Traveller/Anims/'+name
        folder=out/name;folder.mkdir()
        (folder/'00_create.py').write_text(CREATE.format(path=path,name=name,frames=data['frames']))
        prepared=[]
        for bone,P,R,S in data['tracks']:
            if all(x==P[0] for x in P):P=P[0]
            if all(x==R[0] for x in R):R=R[0]
            prepared.append([bone,P,R,S])
        groups=[];batch=[]
        for track in prepared:
            if batch and (len(repr(batch+[track]))>96000 or len(batch)>=12):groups.append(batch);batch=[]
            batch.append(track)
        if batch:groups.append(batch)
        for i,batch in enumerate(groups):
            code=KEYS.format(path=path,data=repr(batch),keys=data['frames']+1,names=repr([[b[0]] for b in batch]))
            (folder/f'10_keys_{i:02d}.py').write_text(code)
        (folder/'90_save.py').write_text(SAVE.format(path=path,frames=data['frames'],bones=[x[0] for x in prepared]))
        count+=len(groups)+2
    (out/'manifest.json').write_text(json.dumps(dict(status='INLINE_CONTROLLER_PACKET_NOT_EXECUTED',editor_io=False,dynamic_decode=False,
        per_call_budget_s=5,call_count=count,files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.py')}),indent=2))
    print('INLINE_EXIT_CALLS',count,'folder',out)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('out',type=Path);args=ap.parse_args()
    emit(args.source,args.out)
