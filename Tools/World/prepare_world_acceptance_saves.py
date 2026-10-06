"""Prepare narrow saves of root-accepted world visuals and a read-only dirty audit."""
from pathlib import Path
import ast
import hashlib
import json
import prepare_high_voice_mast as mast

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/WorldAcceptance/20261001'
HEAD="""import unreal,json
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE before saving accepted world assets'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
actors=list(unreal.EditorLevelLibrary.get_all_level_actors());assert len(actors)<2500
def exact(path):
 found=[a for a in actors if a.get_path_name()==path];assert len(found)==1,'Exact accepted actor missing'
 return found[0]
"""

def receipt(path,marker):
    e=json.loads((ROOT/path).read_text(encoding='utf-8'));assert e['status']=='ok'
    return json.loads(next(s.split(marker,1)[1] for s in e['output'].splitlines() if s.startswith(marker)))

STATION=HEAD+r'''
HOUSE=__HOUSE__
EXT=__EXT__
ext=exact('__EXT_PATH__');house=exact(HOUSE['actor'])
assert ext.get_actor_label()==EXT['label'] and 'S26_STATION_FOUNDATION_EXTENSION_20261001' in [str(t) for t in ext.tags]
assert ext.get_package().get_name()==EXT['package']
p=ext.get_actor_location();s=ext.get_actor_scale3d();r=ext.get_actor_rotation()
assert all(abs(a-b)<.02 for a,b in zip([p.x,p.y,p.z],EXT['position'])) and all(abs(a-b)<.0002 for a,b in zip([s.x,s.y,s.z],EXT['scale']))
assert abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-EXT['yaw']+180)%360-180)<.01
assert ext.static_mesh_component.static_mesh.get_path_name()=='/Game/SaskartaGaea/Environment/Batch01/SM_B01_floor01.SM_B01_floor01'
assert house.get_actor_label()=='SD_S26_HighVoiceTripo_001' and house.get_actor_transform().export_text()==HOUSE['transform']
hc=house.static_mesh_component
assert hc.static_mesh.get_path_name()==HOUSE['mesh'] and str(hc.get_collision_profile_name())=='BlockAll'
assert not house.get_editor_property('hidden') and not hc.get_editor_property('hidden_in_game')
assert list(hc.get_editor_property('override_materials'))==[],'Accepted imported shell material overrides changed'
for p in EXT['supports']:
 hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p['xy'][0],p['xy'][1],EXT['top']+40.),unreal.Vector(p['xy'][0],p['xy'][1],EXT['bottom']-20.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[house],unreal.DrawDebugTrace.NONE,True)
 if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
 assert hit is not None and hit.to_tuple()[0]
 h=hit.to_tuple();assert h[9]==ext and abs(h[5].z-p['z'])<.25,'Accepted extension surface changed'
packages=[house.get_package(),ext.get_package()]
assert len({p.get_name() for p in packages})==2 and all(p.get_name().startswith('/Game/__ExternalActors__/level/Saskarta_WP/') for p in packages)
ok=unreal.EditorLoadingAndSavingUtils.save_packages(packages,True);assert ok
print('ACCEPTED_STATION_SAVED '+json.dumps({'packages':[p.get_name() for p in packages],'saved':bool(ok)}))
'''

HAZE=HEAD+r'''
a=exact('/Game/level/Saskarta_WP.Saskarta_WP:PersistentLevel.StaticMeshActor_UAID_D8BBC14136F4CE0603_1687396424')
assert a.get_actor_label()=='Saskarta_HorizonHaze_Backdrop' and 'Saskarta_HorizonHaze_v1' in [str(t) for t in a.tags]
assert a.get_package().get_name()=='/Game/__ExternalActors__/level/Saskarta_WP/C/SN/23J3GZY27YPC7U6UW3C044'
c=a.static_mesh_component;mat=c.get_material(0)
assert c.static_mesh.get_path_name()=='/Engine/BasicShapes/Sphere.Sphere' and mat.get_path_name()=='/Game/SaskartaGaea/Look/M_Saskarta_HorizonHaze.M_Saskarta_HorizonHaze'
p=a.get_actor_location();s=a.get_actor_scale3d()
assert all(abs(x-y)<.02 for x,y in zip([p.x,p.y,p.z],[389079.6,408050.,0.])) and all(abs(x-400000.)<.02 for x in [s.x,s.y,s.z])
assert not a.get_actor_enable_collision() and c.get_collision_enabled()==unreal.CollisionEnabled.NO_COLLISION and str(c.get_collision_profile_name())=='NoCollision'
assert not c.get_editor_property('generate_overlap_events') and not c.is_simulating_physics()
assert not a.get_editor_property('hidden') and not a.is_temporarily_hidden_in_editor(),'Accepted haze must remain enabled after A/B'
assert unreal.MaterialEditingLibrary.get_num_material_expressions(mat)==6
assert not mat.get_editor_property('is_sky') and mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_MASKED
assert mat.get_editor_property('dither_opacity_mask') and abs(mat.get_editor_property('opacity_mask_clip_value')-.5)<.0001
mask=[m for m in unreal.ObjectIterator(unreal.MaterialExpressionCustom) if m.get_outer()==mat and m.get_editor_property('description')=='Only below geometric horizon; native upper sky and sun remain visible']
assert len(mask)==1 and mask[0].get_editor_property('code')=='return smoothstep(0.0, 0.05, normalize(CV).z);'
packages=[mat.get_package(),a.get_package()]
ok=unreal.EditorLoadingAndSavingUtils.save_packages(packages,True);assert ok
print('ACCEPTED_HORIZON_SAVED '+json.dumps({'packages':[p.get_name() for p in packages],'saved':bool(ok)}))
'''

MAST=HEAD+r'''
SAVE=__SAVE__
EXPECTED=__INSTANCE__
a=exact(EXPECTED['actor']);assert a.get_package().get_name()==EXPECTED['package'] and a.get_actor_label()=='HighVoice'
bp=unreal.load_asset('/Game/SaskartaGaea/Story/BP_Saskarta_HighVoice');mat=unreal.load_asset('/Game/SaskartaGaea/Story/M_Saskarta_HighVoiceMast')
assert isinstance(bp,unreal.Blueprint) and isinstance(mat,unreal.Material)
assert 'UP_TO_DATE' in str(bp.get_editor_property('status')),'Compiled Blueprint required'
components={c.get_name():c for c in a.get_components_by_class(unreal.StaticMeshComponent)}
assert set(components)=={r['component'] for r in EXPECTED['components']}
for r in EXPECTED['components']:
 c=components[r['component']]
 assert c.get_world_transform().export_text()==r['pose'] and c.static_mesh.get_path_name()==r['mesh'] and str(c.get_collision_enabled())==r['collision']
 assert [c.get_material(i).get_path_name() for i in range(c.get_num_materials())]==r['materials'],'Accepted crown/beam/mast materials changed'
sub=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem);lib=unreal.SubobjectDataBlueprintFunctionLibrary
found={n:{} for n in ['Mast0','Mast1','Mast2','Mast3']}
for h in sub.k2_gather_subobject_data_for_blueprint(bp):
 data=lib.get_data(h);name=str(lib.get_variable_name(data))
 if name in found:
  c=lib.get_object(data);found[name][c.get_path_name()]=c
assert all(len(values)==1 for values in found.values()),'One unique component object per mast template required'
rows=[]
for name,values in found.items():
 c=list(values.values())[0]
 assert c.static_mesh.get_path_name()=='/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar.Tile_10MPillar' and c.get_num_materials()==1 and c.get_material(0)==mat
 rows.append({'name':name,'component':c.get_path_name(),'pose':c.get_relative_transform().export_text(),'material':mat.get_path_name()})
assert mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_OPAQUE and unreal.MaterialEditingLibrary.get_num_material_expressions(mat)==6
packages=[mat.get_package(),bp.get_package(),a.get_package()]
ok=False
if SAVE:
 ok=unreal.EditorLoadingAndSavingUtils.save_packages(packages,True);assert ok
print('ACCEPTED_MAST '+json.dumps({'templates':rows,'status':str(bp.get_editor_property('status')),'packages':[p.get_name() for p in packages],'saved':bool(ok)},separators=(',',':')))
'''

DIRTY=HEAD+r'''
dirty={p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
dirty.update(p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
names=sorted(dirty)
helpers=[{'actor':a.get_path_name(),'label':a.get_actor_label(),'tags':[str(t) for t in a.tags]} for a in unreal.ObjectIterator(unreal.SceneCapture2D) if a.get_world()==world]
sky=[{'component':s.get_path_name(),'realtime':s.get_editor_property('real_time_capture')} for s in unreal.ObjectIterator(unreal.SkyLightComponent) if s.get_world()==world]
print('WORLD_DIRTY_AUDIT '+json.dumps({'dirty_count':len(names),'packages':names[:300],'truncated':len(names)>300,'capture_helpers':helpers,'sky':sky,'saved':False},separators=(',',':')))
'''

def main():
    ext=receipt('Saved/Tripo/20261001/station_foundation_extension/placement_readbacks/verify.readback.json','S26_STATION_EXTENSION ')
    placed=receipt('Saved/Tripo/20261001/station_foundation_extension/placement_readbacks/apply.readback.json','S26_STATION_EXTENSION ')
    house=receipt('Saved/Tripo/20261001/station_shell_placement/readbacks/10_replace_visual_hut.readback.json','S26_STATION_REPLACED ')['after']
    instance=receipt('Saved/HorizonRepair/mast/readbacks/30_read_instance.readback.json','HIGHVOICE_MAST_INSTANCE ')
    assert ext['surface_contact_pass']
    OUT.mkdir(parents=True,exist_ok=True);manifest=[]
    bodies=[('10_read_mast_templates.py',MAST.replace('__SAVE__','False')),('20_save_mast.py',MAST.replace('__SAVE__','True')),('30_save_station.py',STATION),('40_save_horizon.py',HAZE),('90_read_dirty_and_helpers.py',DIRTY)]
    for name,code in bodies:
        code=code.replace('__INSTANCE__',repr(instance)).replace('__HOUSE__',repr(house)).replace('__EXT__',repr(ext)).replace('__EXT_PATH__',placed['actor']);ast.parse(code)
        p=OUT/name;p.write_text(code,encoding='utf-8');manifest.append({'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(OUT)

if __name__=='__main__':main()
