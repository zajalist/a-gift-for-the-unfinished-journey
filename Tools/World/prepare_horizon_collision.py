"""Prepare exact horizon-actor collision readback and guarded collision removal."""
from pathlib import Path
import ast
from prepare_ground_contact_loading import HEAD

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/HorizonRepair'
BODY=HEAD+'''
APPLY=__APPLY__
path='/Game/level/Saskarta_WP.Saskarta_WP:PersistentLevel.StaticMeshActor_UAID_D8BBC14136F4CE0603_1687396424'
actors=list(unreal.EditorLevelLibrary.get_all_level_actors())
matches=[a for a in actors if a.get_path_name()==path]
assert len(matches)==1,'Exact observed horizon blocker required'
a=matches[0]
assert a.get_actor_label()=='Saskarta_HorizonHaze_Backdrop' and 'Saskarta_HorizonHaze_v1' in [str(t) for t in a.tags]
components=list(a.get_components_by_class(unreal.PrimitiveComponent))
assert len(components)==1 and isinstance(components[0],unreal.StaticMeshComponent),'Expected only the owned visual sphere'
c=components[0]
assert c.static_mesh.get_path_name()=='/Engine/BasicShapes/Sphere.Sphere'
assert c.get_material(0).get_path_name()=='/Game/SaskartaGaea/Look/M_Saskarta_HorizonHaze.M_Saskarta_HorizonHaze'
s=a.get_actor_scale3d();p=a.get_actor_location()
assert max(abs(v-400000) for v in [s.x,s.y,s.z])<.1
assert abs(p.x-389079.6)<.1 and abs(p.y-408050)<.1 and abs(p.z)<.1
def state():
 result={}
 result['actor_collision']=a.get_actor_enable_collision()
 result['component_collision']=str(c.get_collision_enabled())
 result['profile']=str(c.get_collision_profile_name())
 result['overlaps']=c.get_editor_property('generate_overlap_events')
 result['simulate_physics']=c.is_simulating_physics()
 result['pose']=a.get_actor_transform().export_text()
 result['mesh']=c.static_mesh.get_path_name()
 result['materials']=[c.get_material(i).get_path_name() for i in range(c.get_num_materials())]
 return result
def probe():
 result=[]
 for start,end in [([297375.,483055.,11011.],[297364.925,483084.5,11010.575]),([297254.,483334.,11009.],[297274.175,483293.75,11009.075])]:
  hit=unreal.SystemLibrary.capsule_trace_single_by_profile(world,unreal.Vector(*start),unreal.Vector(*end),32.,88.,'Pawn',False,[],unreal.DrawDebugTrace.NONE,True)
  if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
  hit=hit.to_tuple() if hit is not None and hit.to_tuple()[0] else None
  result.append({'blocked':hit is not None,'haze_hit':hit is not None and hit[9]==a,'actor':hit[9].get_path_name() if hit is not None and hit[9] else None,'initial_overlap':bool(hit[1]) if hit is not None else False})
 return result
before=state();before_probe=probe()
if APPLY:
 assert before['actor_collision'] or before['component_collision']!=str(unreal.CollisionEnabled.NO_COLLISION) or before['profile']!='NoCollision' or before['overlaps'] or any(r['haze_hit'] for r in before_probe),'Already fully disabled; use readback only'
 a.modify();c.modify()
 a.set_actor_enable_collision(False)
 c.set_simulate_physics(False)
 c.set_collision_profile_name('NoCollision')
 c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
 c.set_editor_property('generate_overlap_events',False)
after=state();after_probe=probe()
assert all(after[key]==before[key] for key in ['pose','mesh','materials']),'Collision-only repair changed visual presentation'
if APPLY:
 assert not after['actor_collision'] and after['component_collision']==str(unreal.CollisionEnabled.NO_COLLISION) and not after['overlaps'] and not after['simulate_physics']
 assert after['profile']=='NoCollision' and not any(r['haze_hit'] for r in after_probe),'Owned sphere still blocks Pawn; do not save'
print('HORIZON_COLLISION '+json.dumps({'actor':a.get_path_name(),'package':a.get_package().get_name(),'applied':APPLY,'before':before,'after':after,'before_probes':before_probe,'after_probes':after_probe,'saved':False},separators=(',',':')))
'''

def main():
    for name,apply in [('44_read_collision.py',False),('45_disable_collision.py',True)]:
        code=BODY.replace('__APPLY__',str(apply));ast.parse(code)
        for token in ('getattr','try','open(','save_packages','save_asset'):assert token not in code,token
        path=OUT/name;path.write_text(code,encoding='utf-8');print(path)

if __name__=='__main__':main()
