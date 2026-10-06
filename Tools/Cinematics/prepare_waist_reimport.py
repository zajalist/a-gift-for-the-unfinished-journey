"""Prepare bounded, staged Traveller weights-only reimport for the root editor."""
from pathlib import Path
import hashlib
import json
import numpy as np
import traveller_contacts as contacts
from validate_waist_repair import derivative_entries

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/traveller_waist_reimport_20261001'

PREFLIGHT='''import unreal,json
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'PIE must be stopped'
sk=unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SK_Traveller')
data=sk.get_editor_property('asset_import_data')
editor=unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
result=dict(asset=sk.get_path_name(),import_class=data.get_class().get_name(),source_files=list(data.extract_filenames()),
 skeleton=sk.get_editor_property('skeleton').get_path_name(),lod_count=editor.get_lod_count(sk),
 lods=[dict(vertices=editor.get_num_verts(sk,i),sections=editor.get_num_sections(sk,i)) for i in range(editor.get_lod_count(sk))])
result['materials']=[dict(slot=str(s.get_editor_property('material_slot_name')),imported=str(s.get_editor_property('imported_material_slot_name')),
 material=s.get_editor_property('material_interface').get_path_name() if s.get_editor_property('material_interface') else None) for s in sk.get_editor_property('materials')]
if isinstance(data,unreal.FbxSkeletalMeshImportData):
 result['fbx_options']={name:str(data.get_editor_property(name)) for name in ['import_content_type','last_import_content_type','update_skeleton_reference_pose','use_t0_as_ref_pose','normal_import_method','normal_generation_method','import_uniform_scale','convert_scene','convert_scene_unit','force_front_x_axis']}
print('TRAVELLER_WAIST_PREFLIGHT '+json.dumps(result,separators=(',',':')))
'''

COMMON='''import unreal,json,hashlib
from pathlib import Path
ROOT=Path('D:/UnrealEngine/saskartarad')
OUT=ROOT/'Saved/Verification/traveller_waist_reimport_20261001'
ORIGINAL='/Game/SaskartaGaea/Characters/Traveller/SK_Traveller'
STAGE='/Game/SaskartaGaea/Characters/Traveller/RepairReview/SK_Traveller_WaistReview'
DERIVATIVE=ROOT/'SourceArt/Characters/Traveller/Repairs/traveller01_waist_weights_20261001.fbx'
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'PIE must be stopped'
manifest=json.loads((OUT/'manifest.json').read_text())
assert hashlib.sha256(DERIVATIVE.read_bytes()).hexdigest()==manifest['derivative_sha256']
assert hashlib.sha256((ROOT/manifest['source']).read_bytes()).hexdigest()==manifest['source_sha256']
editor=unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
def obj_path(value):return value.get_path_name() if value else None
def metadata(sk):
 return dict(skeleton=obj_path(sk.get_editor_property('skeleton')),physics=obj_path(sk.get_editor_property('physics_asset')),
  lods=[dict(vertices=editor.get_num_verts(sk,i),sections=[editor.get_lod_material_slot(sk,i,s) for s in range(editor.get_num_sections(sk,i))]) for i in range(editor.get_lod_count(sk))],
  materials=[dict(slot=str(s.get_editor_property('material_slot_name')),imported=str(s.get_editor_property('imported_material_slot_name')),material=obj_path(s.get_editor_property('material_interface'))) for s in sk.get_editor_property('materials')],
  morphs=[m.get_name() for m in sk.get_editor_property('morph_targets')])
def copy_source(sk):
 dm=unreal.DynamicMesh();lod=unreal.GeometryScriptMeshReadLOD()
 lod.lod_type=unreal.GeometryScriptLODType.SOURCE_MODEL;lod.lod_index=0
 dm,outcome=unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(sk,dm,unreal.GeometryScriptCopyMeshFromAssetOptions(),lod)
 assert outcome==unreal.GeometryScriptOutcomePins.SUCCESS
 return dm
def import_weights(sk):
 data=sk.get_editor_property('asset_import_data')
 assert isinstance(data,unreal.InterchangeAssetImportData)
 pipes=list(data.get_pipelines())
 assert len(pipes)==1 and isinstance(pipes[0],unreal.InterchangeGenericAssetsPipeline),[p.get_class().get_name() for p in pipes]
 # Python UObject construction defaults to GetTransientPackage in UE5.8.
 owner=unreal.DynamicMesh()
 assert owner.get_outer().get_path_name()=='/Engine/Transient'
 pipe=unreal.SystemLibrary.duplicate_object(pipes[0],owner)
 assert pipe is not None and pipe.get_path_name()!=pipes[0].get_path_name()
 mesh=pipe.get_editor_property('mesh_pipeline')
 assert mesh.get_path_name()!=pipes[0].get_editor_property('mesh_pipeline').get_path_name(),'Nested pipeline must be copied'
 mesh.set_editor_property('skeletal_mesh_import_content_type',unreal.InterchangeSkeletalMeshContentType.SKINNING_WEIGHTS)
 mesh.set_editor_property('update_skeleton_reference_pose',False)
 mesh.set_editor_property('import_static_meshes',False)
 mesh.set_editor_property('import_skeletal_meshes',True)
 mesh.set_editor_property('create_physics_asset',False)
 mesh.set_editor_property('import_morph_targets',False)
 common=pipe.get_editor_property('common_skeletal_meshes_and_animations_properties')
 common.set_editor_property('skeleton',sk.get_editor_property('skeleton'))
 common.set_editor_property('use_t0_as_ref_pose',False)
 pipe.get_editor_property('animation_pipeline').set_editor_property('import_animations',False)
 materials=pipe.get_editor_property('material_pipeline')
 materials.set_editor_property('import_materials',False)
 materials.get_editor_property('texture_pipeline').set_editor_property('import_textures',False)
 params=unreal.ImportAssetParameters()
 params.reimport_asset=sk;params.reimport_source_index=2
 params.is_automated=True;params.force_show_dialog=False;params.replace_existing=True
 params.override_pipelines=[unreal.SoftObjectPath(pipe.get_path_name())]
 manager=unreal.InterchangeManager.get_interchange_manager_scripted()
 source=unreal.InterchangeManager.create_source_data(str(DERIVATIVE))
 # PyGenUtil removes the success bool when a UFUNCTION has output parameters:
 # this returns the imported-object array, or None on failure.
 imported=manager.import_asset(sk.get_path_name().rsplit('/',1)[0],source,params)
 assert imported is not None, 'Weights-only Interchange import failed'
 assert [x.get_path_name() for x in imported]==[sk.get_path_name()],[x.get_path_name() for x in imported]
 # LastSkeletalMeshImportContentType is not exposed to Python. Actual vertex
 # weights, binds and every other surface attribute are verified separately.
 return dict(imported=[x.get_path_name() for x in imported],requested_content_type='SKINNING_WEIGHTS')
'''

STAGE_IMPORT='''original=unreal.load_asset(ORIGINAL)
assert metadata(original)['lods']==[dict(vertices=52624,sections=[0,1,2])]
# Revision2 already duplicated/saved this isolated stage before the import call
# failed. Resume that exact unchanged copy; never duplicate a second time.
stage=unreal.load_asset(STAGE)
assert stage is not None,'Expected the existing isolated review stage'
original_files=list(original.get_editor_property('asset_import_data').extract_filenames())
stage_files=list(stage.get_editor_property('asset_import_data').extract_filenames())
assert original_files==[(ROOT/manifest['source']).as_posix()],original_files
# Duplication resolved its unchanged relative filename against Engine/BaseDir.
# Accept only the exact observed alias AND prove its whole source mesh, including
# weights and every enabled surface attribute, still equals the hashed original.
assert stage_files in (original_files,['C:/Program Files/Epic Games/SourceArt/Characters/Traveller/traveller01_animated.fbx']),stage_files
compare=unreal.GeometryScriptIsSameMeshOptions()
for name in ('check_connectivity','check_normals','check_colors','check_groups','check_attributes'):
 compare.set_editor_property(name,True)
compare.epsilon=.00001
unchanged=unreal.GeometryScript_MeshComparison.is_same_mesh_as(copy_source(original),copy_source(stage),compare)
assert unchanged[1],'Existing review stage differs from the original before reimport'
pipes=list(original.get_editor_property('asset_import_data').get_pipelines())
assert len(pipes)==1 and isinstance(pipes[0],unreal.InterchangeGenericAssetsPipeline),[p.get_class().get_name() for p in pipes]
before=metadata(original)
assert metadata(stage)==before
result=import_weights(stage)
assert metadata(stage)==before,dict(before=before,after=metadata(stage))
assert metadata(original)==before
print('TRAVELLER_WAIST_STAGE_IMPORTED '+json.dumps(result))
'''

VERIFY='''original=unreal.load_asset(ORIGINAL)
stage=unreal.load_asset(STAGE)
assert stage is not None
assert metadata(original)==metadata(stage),dict(original=metadata(original),stage=metadata(stage))
before=copy_source(original);after=copy_source(stage)
original_bones=unreal.GeometryScript_BoneWeights.get_all_bones_info(before)[1]
after_bones=unreal.GeometryScript_BoneWeights.get_all_bones_info(after)[1]
def bone_rows(bones):return [[b.index,str(b.name),b.parent_index,b.local_transform.export_text(),b.world_transform.export_text()] for b in bones]
assert bone_rows(original_bones)==bone_rows(after_bones),'Skeleton/bind-pose changed'
points=unreal.GeometryScript_MeshQueries.get_all_vertex_positions(after,False)
assert not points[2]
positions=unreal.GeometryScript_List.convert_vector_list_to_array(points[1])
lookup={}
for i,p in enumerate(positions):lookup.setdefault((round(p.x,3),round(p.y,3),round(p.z,3)),[]).append(i)
names={b.index:str(b.name) for b in after_bones}
targets=json.loads((OUT/'expected_weights.json').read_text())
assert hashlib.sha256((OUT/'expected_weights.json').read_bytes()).hexdigest()==manifest['expected_weights_sha256']
max_error=0.;checked=0
for item in targets:
 # Source and Unreal positions can straddle a rounding boundary by3e-6cm.
 # Search adjacent quantization cells, then require actual distance<1e-4cm.
 pos=item['position'];cell=tuple(round(v,3) for v in pos);ids=[]
 for dx in (-.001,0,.001):
  for dy in (-.001,0,.001):
   for dz in (-.001,0,.001):
    key=(round(cell[0]+dx,3),round(cell[1]+dy,3),round(cell[2]+dz,3))
    for index in lookup.get(key,[]):
     p=positions[index]
     if (p.x-pos[0])**2+(p.y-pos[1])**2+(p.z-pos[2])**2<1e-8:ids.append(index)
 assert ids,item['position']
 for index in ids:
  result=unreal.GeometryScript_BoneWeights.get_vertex_bone_weights(after,index)
  assert result[2]
  actual={names[w.bone_index]:w.weight for w in result[1]}
  for name in set(actual)|set(item['weights']):
   error=abs(actual.get(name,0)-item['weights'].get(name,0))
   max_error=max(max_error,error)
   assert error<.0001,dict(vertex=index,bone=name,actual=actual,expected=item['weights'])
  checked+=1
# Normalize only transient DynamicMesh copies to ignore their intended weight
# difference while comparing every other surface attribute natively.
neutral=unreal.GeometryScriptBoneWeight();neutral.bone_index=0;neutral.weight=1.
unreal.GeometryScript_BoneWeights.set_all_vertex_bone_weights(before,[neutral])
unreal.GeometryScript_BoneWeights.set_all_vertex_bone_weights(after,[neutral])
options=unreal.GeometryScriptIsSameMeshOptions()
for name in ('check_connectivity','check_normals','check_colors','check_groups','check_attributes'):
 options.set_editor_property(name,True)
options.epsilon=.00001
same=unreal.GeometryScript_MeshComparison.is_same_mesh_as(before,after,options)
assert same[1],same[2].export_text()
record=dict(stage=STAGE,checked_weight_vertices=checked,max_weight_error=max_error,metadata=metadata(stage),all_surface_attributes_equal=True)
print('TRAVELLER_WAIST_STAGE_VERIFIED '+json.dumps(record))
'''


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    compile(PREFLIGHT,'preflight','exec')
    (OUT/'00_read_preflight.py').write_text(PREFLIGHT)
    manifest=json.loads((ROOT/'SourceArt/Characters/Traveller/Repairs/waist_weights_manifest.json').read_text())
    manifest['editor_executed']=False
    manifest['packet_revision']=5
    manifest['previous_revision']='revision_4_transient_object_abstract'
    manifest['stage_exists']=True
    manifest['scripts']={'00_read_preflight.py':hashlib.sha256(PREFLIGHT.encode()).hexdigest()}
    points,old_entries,_=contacts.source_body()
    entries=derivative_entries()
    old=np.zeros((len(points),len(entries)));new=np.zeros_like(old)
    for i,((_,a,b,_),(_,c,d,_)) in enumerate(zip(old_entries,entries)):
        old[a,i]=b;new[c,i]=d
    changed=np.flatnonzero(np.abs(new-old).max(axis=1)>1e-12)
    selected=np.unique(np.concatenate((changed,np.linspace(0,len(points)-1,65,dtype=int))))
    targets=[dict(position=points[index].tolist(),weights={entries[i][0]:float(w) for i,w in enumerate(new[index]) if w>0}) for index in selected]
    weights=OUT/'expected_weights.json';weights.write_text(json.dumps(targets,separators=(',',':')))
    manifest['expected_weights_sha256']=hashlib.sha256(weights.read_bytes()).hexdigest()
    for name,body in [('10_stage_import.py',STAGE_IMPORT),('20_stage_verify.py',VERIFY)]:
        code=COMMON+body
        compile(code,name,'exec')
        (OUT/name).write_text(code)
        manifest['scripts'][name]=hashlib.sha256(code.encode()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(OUT/'00_read_preflight.py')


if __name__=='__main__':prepare()
