"""Condense the existing authoring data to five bounded native import calls.

This builds offline files only. It does not connect to Unreal. Source geometry
has rejected V3 for production; these assets are isolated visual-review drafts.
"""
from pathlib import Path
import ast
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'Saved/Verification/ending_focus_20261001/capsule_exit_full_v3'
OUT=ROOT/'Saved/Verification/ending_focus_20261001/capsule_exit_compact_review_v4'

SCRIPT='''import unreal,json,hashlib,pathlib
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE before importing a review-only animation'
source=pathlib.Path({data_path!r})
assert hashlib.sha256(source.read_bytes()).hexdigest()=={digest!r},'Authoring data changed'
data=json.loads(source.read_text())
full='/Game/SaskartaGaea/Characters/Traveller/Anims/'+data['name']
assert not unreal.EditorAssetLibrary.does_asset_exist(full),'Read existing partial outcome; do not overwrite or replay'
factory=unreal.AnimSequenceFactory()
factory.set_editor_property('target_skeleton',unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SKEL_Traveller'))
an=unreal.AssetToolsHelpers.get_asset_tools().create_asset(data['name'],'/Game/SaskartaGaea/Characters/Traveller/Anims',unreal.AnimSequence,factory)
assert an is not None
c=an.get_editor_property('controller')
c.set_frame_rate(unreal.FrameRate(30,1),False)
c.set_number_of_frames(unreal.FrameNumber(data['frames']),False)
c.open_bracket('Isolated full-contact review candidate',False)
for bone,P,R,S in data['tracks']:
    assert c.add_bone_curve(bone,False),bone
    positions=[unreal.Vector(*p) for p in P]
    rotations=[unreal.Quat(*q) for q in R]
    scales=[unreal.Vector(*S)]*len(R)
    assert c.set_bone_track_keys(bone,positions,rotations,scales,False),bone
c.close_bracket(False)
an.set_editor_property('enable_root_motion',False)
tracks=[str(n) for n in unreal.AnimationLibrary.get_animation_track_names(an)]
assert len(tracks)==68 and set(tracks)==set(x[0] for x in data['tracks'])
assert abs(an.get_play_length()-data['frames']/30.)<.001
saved=unreal.EditorAssetLibrary.save_asset(full,only_if_is_dirty=False)
assert saved
print('EXIT_REVIEW_IMPORTED '+json.dumps(dict(asset=full,frames=data['frames'],tracks=tracks,length=an.get_play_length(),saved=saved,production_accepted=False,sequence_modified=False),separators=(',',':')))
'''


def main():
    assert not OUT.exists(),'Preserve previous packet'
    OUT.mkdir(parents=True)
    for folder in SOURCE.iterdir():
        if not folder.is_dir():continue
        tracks=[]
        for p in sorted(folder.glob('10_keys_*.py')):
            node=next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.For))
            tracks.extend(ast.literal_eval(node.iter))
        assert len(tracks)==68
        rounded=[]
        for bone,P,R,S in tracks:
            rounded.append((bone,[[round(v,6) for v in p] for p in P],
                            [[round(v,7) for v in q] for q in R],[round(v,6) for v in S]))
        data=dict(name=folder.name+'_ReviewOnly',frames=len(rounded[0][2])-1,tracks=rounded)
        dst=OUT/(folder.name+'.json');dst.write_text(json.dumps(data,separators=(',',':')))
        script=SCRIPT.format(data_path=str(dst),digest=hashlib.sha256(dst.read_bytes()).hexdigest())
        (OUT/(folder.name+'_import.py')).write_text(script)
    (OUT/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()},indent=2))
    print('COMPACT_REVIEW_PACKET',OUT,'imports',len(list(OUT.glob('*_import.py'))))


if __name__=='__main__':main()
