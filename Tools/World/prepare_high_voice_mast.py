"""Prepare a material-only HighVoice mast repair; never contact the editor.

The confirmed white object is the original four-section beacon mast. Keep its
mesh, pose, collision, crown and beam. Preview the loaded instance first, then
update the four Blueprint templates only after visual acceptance.
"""
from pathlib import Path
import ast
from prepare_ground_contact_loading import HEAD

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/HorizonRepair/mast'
ASSET = '/Game/SaskartaGaea/Story/M_Saskarta_HighVoiceMast'
ACTOR = '/Game/level/Saskarta_WP.Saskarta_WP:PersistentLevel.BP_Saskarta_HighVoice_C_UAID_D8BBC14136F4930503_1480782157'
MESH = '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar.Tile_10MPillar'
OLD = '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Materials/M_Tile.M_Tile'

MATERIAL = HEAD + '''
path='__ASSET__'
assert not unreal.EditorAssetLibrary.does_asset_exist(path),'Inspect existing mast material before rebuilding'
bc=unreal.load_asset('/Game/MedievalVillage/Textures/T_Metal_BC.T_Metal_BC')
normal=unreal.load_asset('/Game/MedievalVillage/Textures/T_Metal_N.T_Metal_N')
assert isinstance(bc,unreal.Texture2D) and isinstance(normal,unreal.Texture2D),'Existing metal textures required'
M=unreal.MaterialEditingLibrary
mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_Saskarta_HighVoiceMast','/Game/SaskartaGaea/Story',unreal.Material,unreal.MaterialFactoryNew())
mat.set_editor_property('blend_mode',unreal.BlendMode.BLEND_OPAQUE)
mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
def node(cls,x,y):return M.create_material_expression(mat,cls,x,y)
color=node(unreal.MaterialExpressionTextureSample,-600,0)
color.set_editor_property('texture',bc)
color.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
nrm=node(unreal.MaterialExpressionTextureSample,-600,250)
nrm.set_editor_property('texture',normal)
nrm.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
tint=node(unreal.MaterialExpressionVectorParameter,-600,-180)
tint.set_editor_property('parameter_name','MastTint')
tint.set_editor_property('default_value',unreal.LinearColor(.22,.205,.18,1))
mul=node(unreal.MaterialExpressionMultiply,-300,0)
rough=node(unreal.MaterialExpressionScalarParameter,-300,180)
rough.set_editor_property('parameter_name','Roughness');rough.set_editor_property('default_value',.82)
metal=node(unreal.MaterialExpressionScalarParameter,-300,320)
metal.set_editor_property('parameter_name','Metallic');metal.set_editor_property('default_value',.15)
links=[M.connect_material_expressions(color,'RGB',mul,'A'),M.connect_material_expressions(tint,'',mul,'B'),
 M.connect_material_property(mul,'',unreal.MaterialProperty.MP_BASE_COLOR),
 M.connect_material_property(nrm,'RGB',unreal.MaterialProperty.MP_NORMAL),
 M.connect_material_property(rough,'',unreal.MaterialProperty.MP_ROUGHNESS),
 M.connect_material_property(metal,'',unreal.MaterialProperty.MP_METALLIC)]
assert all(links),'Mast material link failure; do not apply'
M.recompile_material(mat)
print('HIGHVOICE_MAST_MATERIAL '+json.dumps({'asset':mat.get_path_name(),'nodes':M.get_num_material_expressions(mat),'links':links,'saved':False}))
'''

INSTANCE = HEAD + '''
actors=[a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_path_name()=='__ACTOR__']
assert len(actors)==1 and actors[0].get_actor_label()=='HighVoice','Expected the exact confirmed original beacon'
a=actors[0]
components=list(a.get_components_by_class(unreal.StaticMeshComponent))
masts={c.get_name():c for c in components if c.get_name() in ['Mast0','Mast1','Mast2','Mast3']}
assert len(masts)==4,'Four original mast components required'
mat=unreal.load_asset('__ASSET__')
assert isinstance(mat,unreal.Material),'Compiled mast material required'
before={c.get_name():{'pose':c.get_world_transform().export_text(),'mesh':c.static_mesh.get_path_name(),'materials':[c.get_material(i).get_path_name() for i in range(c.get_num_materials())],'collision':str(c.get_collision_enabled())} for c in components}
for name,c in masts.items():
 assert c.static_mesh.get_path_name()=='__MESH__' and c.get_num_materials()==1
 assert c.get_material(0).get_path_name() in ['__OLD__',mat.get_path_name()],'Unexpected previous mast material'
 p=c.get_world_location();index=int(name[-1])
 assert abs(p.x-298079.6)<.02 and abs(p.y-483050)<.02 and abs(p.z-(10818.728159+index*1000))<.02,'Confirmed mast pose changed'
if __APPLY__:
 a.modify()
 for c in masts.values():c.modify();c.set_material(0,mat)
rows=[]
for c in components:
 row={'component':c.get_name(),'pose':c.get_world_transform().export_text(),'mesh':c.static_mesh.get_path_name(),'materials':[c.get_material(i).get_path_name() for i in range(c.get_num_materials())],'collision':str(c.get_collision_enabled())}
 assert row['pose']==before[c.get_name()]['pose'] and row['mesh']==before[c.get_name()]['mesh'] and row['collision']==before[c.get_name()]['collision'],'Presentation repair changed shape'
 if c.get_name() not in masts:assert row['materials']==before[c.get_name()]['materials'],'Crown or beam changed'
 rows.append(row)
print('HIGHVOICE_MAST_INSTANCE '+json.dumps({'applied':__APPLY__,'actor':a.get_path_name(),'package':a.get_package().get_name(),'components':rows,'saved':False},separators=(',',':')))
'''

TEMPLATE = HEAD + '''
bp=unreal.load_asset('/Game/SaskartaGaea/Story/BP_Saskarta_HighVoice')
mat=unreal.load_asset('__ASSET__')
assert isinstance(bp,unreal.Blueprint) and isinstance(mat,unreal.Material)
sub=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem);lib=unreal.SubobjectDataBlueprintFunctionLibrary
masts={}
for h in sub.k2_gather_subobject_data_for_blueprint(bp):
 data=lib.get_data(h);name=str(lib.get_variable_name(data))
 if name in ['Mast0','Mast1','Mast2','Mast3']:masts[name]=lib.get_object(data)
assert len(masts)==4
for c in masts.values():
 assert isinstance(c,unreal.StaticMeshComponent) and c.static_mesh.get_path_name()=='__MESH__'
 assert c.get_num_materials()==1 and c.get_material(0).get_path_name() in ['__OLD__',mat.get_path_name()]
before={name:c.get_relative_transform().export_text() for name,c in masts.items()}
bp.modify()
for c in masts.values():c.modify();c.set_material(0,mat)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
rows=[]
for h in sub.k2_gather_subobject_data_for_blueprint(bp):
 data=lib.get_data(h);name=str(lib.get_variable_name(data))
 if name in before:
  c=lib.get_object(data)
  assert c.get_relative_transform().export_text()==before[name] and c.get_material(0)==mat
  rows.append({'component':name,'material':c.get_material(0).get_path_name(),'pose':before[name]})
assert len(rows)==4
print('HIGHVOICE_MAST_TEMPLATES '+json.dumps({'blueprint':bp.get_path_name(),'components':rows,'saved':False},separators=(',',':')))
'''

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for name,body in [('10_material.py',MATERIAL),('20_preview_instance.py',INSTANCE.replace('__APPLY__','True')),
                      ('30_read_instance.py',INSTANCE.replace('__APPLY__','False')),('40_persist_templates.py',TEMPLATE)]:
        for token,value in [('__ASSET__',ASSET),('__ACTOR__',ACTOR),('__MESH__',MESH),('__OLD__',OLD)]:body=body.replace(token,value)
        ast.parse(body)
        for token in ('try','getattr','import time','open(','save_asset','save_packages','destroy_actor'):
            assert token not in body,token
        path=OUT/name;path.write_text(body,encoding='utf-8');print(path)

if __name__=='__main__':main()

