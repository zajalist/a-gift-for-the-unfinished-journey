"""Prepare production weights-only reimport after the isolated stage proof."""
from pathlib import Path
import hashlib
import json
import numpy as np
import prepare_waist_reimport as stage
import traveller_contacts as contacts

ROOT=stage.ROOT
OUT=ROOT/'Saved/Verification/traveller_waist_production_20261001_v1'
PROOF=stage.OUT/'verification_readbacks/23_stage_verify_adjacent_cells.readback.json'

HELPERS='''def weight_proof(mesh,filename,digest):
 path=OUT/filename
 assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
 dm=copy_source(mesh)
 bones=unreal.GeometryScript_BoneWeights.get_all_bones_info(dm)[1]
 names={b.index:str(b.name) for b in bones}
 result=unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm,False)
 assert not result[2]
 points=unreal.GeometryScript_List.convert_vector_list_to_array(result[1]);lookup={}
 for index,p in enumerate(points):lookup.setdefault((round(p.x,3),round(p.y,3),round(p.z,3)),[]).append(index)
 checked=0;maximum=0.
 for item in json.loads(path.read_text()):
  pos=item['position'];cell=tuple(round(v,3) for v in pos);ids=[]
  for dx in (-.001,0,.001):
   for dy in (-.001,0,.001):
    for dz in (-.001,0,.001):
     key=(round(cell[0]+dx,3),round(cell[1]+dy,3),round(cell[2]+dz,3))
     for index in lookup.get(key,[]):
      p=points[index]
      if (p.x-pos[0])**2+(p.y-pos[1])**2+(p.z-pos[2])**2<1e-8:ids.append(index)
  assert ids,pos
  for index in ids:
   result=unreal.GeometryScript_BoneWeights.get_vertex_bone_weights(dm,index);assert result[2]
   actual={names[w.bone_index]:w.weight for w in result[1]}
   error=max(abs(actual.get(name,0)-item['weights'].get(name,0)) for name in set(actual)|set(item['weights']))
   assert error<.0001,dict(index=index,actual=actual,expected=item['weights'])
   maximum=max(maximum,error);checked+=1
 return dict(checked=checked,maximum_weight_error=maximum)

def same_surface(a,b,include_weights):
 left,right=copy_source(a),copy_source(b)
 def bone_rows(dm):
  return [[x.index,str(x.name),x.parent_index,x.local_transform.export_text(),x.world_transform.export_text()] for x in unreal.GeometryScript_BoneWeights.get_all_bones_info(dm)[1]]
 assert bone_rows(left)==bone_rows(right),'Skeleton/bind poses differ'
 if not include_weights:
  neutral=unreal.GeometryScriptBoneWeight();neutral.bone_index=0;neutral.weight=1.
  unreal.GeometryScript_BoneWeights.set_all_vertex_bone_weights(left,[neutral])
  unreal.GeometryScript_BoneWeights.set_all_vertex_bone_weights(right,[neutral])
 options=unreal.GeometryScriptIsSameMeshOptions()
 for name in ('check_connectivity','check_normals','check_colors','check_groups','check_attributes'):options.set_editor_property(name,True)
 options.epsilon=.00001
 same=unreal.GeometryScript_MeshComparison.is_same_mesh_as(left,right,options)
 assert same[1],same[2].export_text()

original=unreal.load_asset(ORIGINAL);review=unreal.load_asset(STAGE)
assert original is not None and review is not None
assert metadata(original)==manifest['verified_metadata']==metadata(review)
proof=ROOT/manifest['stage_proof']
assert hashlib.sha256(proof.read_bytes()).hexdigest()==manifest['stage_proof_sha256']
'''

IMPORT='''same_surface(original,review,False)
weight_proof(review,'expected_weights.json',manifest['expected_weights_sha256'])
before=weight_proof(original,'expected_original_weights.json',manifest['expected_original_weights_sha256'])
# Original must still have its old weights. A retry after an uncertain success
# stops above and requires the separate verification script, never reimports.
result=import_weights(original)
assert metadata(original)==manifest['verified_metadata']
print('TRAVELLER_WAIST_PRODUCTION_IMPORTED '+json.dumps(dict(before=before,import_result=result)))
'''

VERIFY='''same_surface(original,review,True)
weights=weight_proof(original,'expected_weights.json',manifest['expected_weights_sha256'])
print('TRAVELLER_WAIST_PRODUCTION_VERIFIED '+json.dumps(dict(asset=original.get_path_name(),weights=weights,metadata=metadata(original),all_surface_attributes_and_bind_poses_equal_to_verified_stage=True)))
'''

SAVE='''same_surface(original,review,True)
assert unreal.EditorAssetLibrary.save_asset(ORIGINAL,only_if_is_dirty=False),'Production mesh save failed'
print('TRAVELLER_WAIST_PRODUCTION_SAVED '+original.get_path_name())
'''


def prepare_review_save():
    """Preserve the verified review asset; never reimport or resave production."""
    verified = OUT / '32_save_verified.py'
    code = verified.read_text()
    assert code.count(SAVE) == 1, 'Expected frozen production-save packet shape'
    replacement = '''same_surface(original,review,True)
weights=weight_proof(review,'expected_weights.json',manifest['expected_weights_sha256'])
assert weights['checked']==1609
assert unreal.EditorAssetLibrary.save_asset(STAGE,only_if_is_dirty=True),'Review mesh save failed'
print('TRAVELLER_WAIST_REVIEW_SAVED '+json.dumps(dict(asset=review.get_path_name(),metadata=metadata(review),weights=weights,production_not_saved=True)))
'''
    code = code.replace(SAVE, replacement)
    compile(code, '33_save_verified_review.py', 'exec')
    target = ROOT / 'Saved/Verification/traveller_waist_review_save_20261001_v1'
    target.mkdir(parents=True, exist_ok=True)
    script = target / '33_save_verified_review.py'
    script.write_text(code)
    receipt = dict(script=str(script), sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                   source_script=str(verified), source_sha256=hashlib.sha256(verified.read_bytes()).hexdigest(),
                   editor_executed=False,
                   save_only='/Game/SaskartaGaea/Characters/Traveller/RepairReview/SK_Traveller_WaistReview')
    (target/'manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def prepare():
    assert not OUT.exists(),'Preserve production packets; choose a new revision'
    proof=json.loads(PROOF.read_text());assert proof['status']=='ok'
    row=next(json.loads(line.split(' ',1)[1]) for line in proof['output'].splitlines() if line.startswith('TRAVELLER_WAIST_STAGE_VERIFIED '))
    assert row['checked_weight_vertices']==1609 and row['all_surface_attributes_equal'] and row['max_weight_error']<.0001
    OUT.mkdir(parents=True)
    manifest=json.loads((stage.OUT/'manifest.json').read_text())
    targets=json.loads((stage.OUT/'expected_weights.json').read_text())
    points,entries,_=contacts.source_body()
    weights=np.zeros((len(points),len(entries)))
    for index,(_,ids,values,_) in enumerate(entries):weights[ids,index]=values
    lookup={tuple(point):index for index,point in enumerate(points)}
    old=[dict(position=item['position'],weights={entries[i][0]:float(w) for i,w in enumerate(weights[lookup[tuple(item['position'])]]) if w>0}) for item in targets]
    (OUT/'expected_original_weights.json').write_text(json.dumps(old,separators=(',',':')))
    (OUT/'expected_weights.json').write_bytes((stage.OUT/'expected_weights.json').read_bytes())
    manifest.update(status='prepared_not_imported',verified_metadata=row['metadata'],
        stage_proof=str(PROOF.relative_to(ROOT)),stage_proof_sha256=hashlib.sha256(PROOF.read_bytes()).hexdigest(),
        expected_original_weights_sha256=hashlib.sha256((OUT/'expected_original_weights.json').read_bytes()).hexdigest(),scripts={})
    common=stage.COMMON.replace("OUT=ROOT/'Saved/Verification/traveller_waist_reimport_20261001'",f"OUT=ROOT/{OUT.relative_to(ROOT).as_posix()!r}")
    common=common.replace('ok,imported=manager.import_asset','imported=manager.import_asset').replace("assert ok, 'Weights-only Interchange import failed'","assert imported is not None, 'Weights-only Interchange import failed'")
    for name,code in [('30_import_weights.py',common+HELPERS+IMPORT),('31_verify_production.py',common.split('def import_weights')[0]+HELPERS+VERIFY),('32_save_verified.py',common.split('def import_weights')[0]+HELPERS+SAVE)]:
        compile(code,name,'exec');path=OUT/name;path.write_text(code)
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('WAIST_PRODUCTION_READY',OUT)


if __name__=='__main__':prepare()
