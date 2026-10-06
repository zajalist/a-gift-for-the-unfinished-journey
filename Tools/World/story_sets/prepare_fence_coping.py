"""Prepare measured S26 fence supports with flat metal caps; never calls Unreal.

Straight panels partition their support at the centreline between neighbors.
The two perpendicular corner pairs share an elevation. This avoids a later,
higher support intruding beneath a previously accepted rail contact.
"""
from pathlib import Path
import ast
import hashlib
import json
import math
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import prepare_summit_expansion as original
import prepare_summit_plinths as plinth

BASE=ROOT/'Saved/Tripo/20261001/station_plinths'
OUT=BASE/'coping_v1'
METAL='/Game/SaskartaGaea/Story/M_Saskarta_HighVoiceMast'
CUBE='/Engine/BasicShapes/Cube.Cube'

def receipt(path):
    envelope=json.loads(path.read_text(encoding='utf-8'))
    assert envelope['status']=='ok'
    rows=[json.loads(s.split('S26_LEVEL_PLINTH ',1)[1]) for s in envelope['output'].splitlines() if s.startswith('S26_LEVEL_PLINTH ')]
    assert len(rows)==1
    return rows[0]

def xy(row,p):
    a=math.radians(row['yaw']);c,s=math.cos(a),math.sin(a)
    return [row['world_xy_cm'][0]+p[0]*c-p[1]*s,row['world_xy_cm'][1]+p[0]*s+p[1]*c]

def design(rows,surveys,gate):
    tops={r['id']:surveys[r['id']]['pads'][0]['top']+2. for r in rows}
    for a,b in [('FenceRear00','FenceLeft00'),('FenceRear04','FenceRight00')]:
        top=max(tops[a],tops[b]);tops[a]=top;tops[b]=top+.02
    # The shorter left panel lands partly over the existing negative-Y gate
    # stone. Match that measured foundation height, without moving the gate.
    tops['FenceLeft01']=max(tops['FenceLeft01'],gate['pads'][0]['top']+2.)
    designs=[]
    for row in rows:
        old=surveys[row['id']];rect=json.loads(json.dumps(old['pads'][0]['rect']))
        a=math.radians(row['yaw']);c,s=math.cos(a),math.sin(a)
        for other in rows:
            if row['id']==other['id'] or abs(row['yaw']-other['yaw'])>.01:continue
            dx,dy=[other['world_xy_cm'][i]-row['world_xy_cm'][i] for i in range(2)]
            along,across=dx*c+dy*s,-dx*s+dy*c
            if abs(across)>.1:continue
            if along<0:
                own=min(p[0] for p in row['contacts']);other_end=along+max(p[0] for p in other['contacts'])
                assert own>other_end,'Fence contacts themselves overlap'
                rect['min'][0]=max(rect['min'][0],(own+other_end)*.5+.10)
            else:
                own=max(p[0] for p in row['contacts']);other_end=along+min(p[0] for p in other['contacts'])
                assert other_end>own,'Fence contacts themselves overlap'
                rect['max'][0]=min(rect['max'][0],(own+other_end)*.5-.10)
        if row['id']=='FenceLeft01':rect['max'][0]=min(rect['max'][0],79.5)
        if row['id']=='FenceLeft02':rect['min'][0]=max(rect['min'][0],gate['pads'][1]['rect']['max'][1]+.10-row['local_xy_cm'][1])
        margin=min(min(p[i]-rect['min'][i],rect['max'][i]-p[i]) for p in row['contacts'] for i in range(2))
        assert margin>=.29,(row['id'],margin)
        # Both tiers use the partitioned rectangle. The 2cm cap embeds 0.5cm
        # into the stone's render bound; actual steel/stone appearance is reviewed.
        mate={'FenceRear00':'FenceLeft00','FenceLeft00':'FenceRear00','FenceRear04':'FenceRight00','FenceRight00':'FenceRear04'}.get(row['id'])
        designs.append({'row':row,'survey':old,'rect':rect,'cap_top':tops[row['id']],
                        'cap_thickness':2.,'stone_top':tops[row['id']]-1.5,
                        'corner_mate_label':original.PREFIX+mate+'_Coping' if mate else None,
                        'contact_margin_cm':margin,
                        'body_z':tops[row['id']]-(min(p[2] for p in row['contacts'])+max(p[2] for p in row['contacts']))*.5})
    return designs

EDITOR=r'''import unreal,json,math,datetime
DESIGN=__DESIGN__
PRIOR=__PRIOR__
PHASE='__PHASE__'
ROW=DESIGN['row'];SURVEY=DESIGN['survey'];TAG='S26_LEVEL_PLINTH_20261001'
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
actors=list(unreal.EditorLevelLibrary.get_all_level_actors());assert len(actors)<2500
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
started=datetime.datetime.now(datetime.timezone.utc);calls=0
def budget():assert calls<160 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<4.,'Bounded coping trace budget exceeded'
def unpack(h):
 if isinstance(h,tuple) and len(h)==2 and not isinstance(h[0],unreal.HitResult):return h[1] if h[0] else None
 return h
def unique(label):
 matches=[a for a in actors if a.get_actor_label()==label];assert len(matches)<=1,'Duplicate owned label'
 if matches:assert TAG in [str(t) for t in matches[0].tags],'Actor belongs to another packet'
 return matches[0] if matches else None
labels=[ROW['label']+'_Stone0',ROW['label']+'_Coping',ROW['label']]
old=[unique(n) for n in labels]
if PHASE=='apply':
 if PRIOR:
  assert old[0] is not None and old[1] is None and old[2] is not None,'Expected only the measured first stone and fence'
  for a,p in zip([old[0],old[2]],PRIOR):
   assert a.get_path_name()==p['actor'] and a.get_package().get_name()==p['package'] and a.get_actor_transform().export_text()==p['transform'],'Existing first fence moved since its receipt'
 else:assert all(a is None for a in old),'Initial coping placement refuses existing actors'
else:assert all(a is not None for a in old),'All three installed actors required'
floor=unreal.load_asset('__FLOOR__');cube=unreal.load_asset('__CUBE__');mesh=unreal.load_asset(ROW['asset']);metal=unreal.load_asset('__METAL__')
assert all(isinstance(m,unreal.StaticMesh) for m in [floor,cube,mesh]) and isinstance(metal,unreal.Material),'Exact loaded support assets required'
assert metal.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_OPAQUE,'Coping must be a solid textured physical surface'
fb=floor.get_bounding_box();lo=[fb.min.x,fb.min.y,fb.min.z];hi=[fb.max.x,fb.max.y,fb.max.z]
assert all(abs([lo,hi][i][j]-SURVEY['floor_bounds'][i][j])<.01 for i in range(2) for j in range(3))
bb=cube.get_bounding_box();assert all(abs(v-w)<.001 for v,w in zip([bb.min.x,bb.min.y,bb.min.z,bb.max.x,bb.max.y,bb.max.z],[-50.]*3+[50.]*3)),'Engine cube bounds changed'
bb=mesh.get_bounding_box();size=[(bb.max.x-bb.min.x)*ROW['scale'],(bb.max.y-bb.min.y)*ROW['scale'],(bb.max.z-bb.min.z)*ROW['scale']]
assert all(abs(a-b)<2 for a,b in zip(size,ROW['expected_size_cm'])),'Fence source mesh changed'
angle=math.radians(ROW['yaw']);c,s=math.cos(angle),math.sin(angle)
def xy(p):return [ROW['world_xy_cm'][0]+p[0]*c-p[1]*s,ROW['world_xy_cm'][1]+p[0]*s+p[1]*c]
ignored=[a for a in actors if TAG in [str(t) for t in a.tags]]
def terrain(p):
 global calls
 skip=list(ignored)
 for layer in range(8):
  budget();calls+=1
  h=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p[0],p[1],16000.),unreal.Vector(p[0],p[1],5000.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,skip,unreal.DrawDebugTrace.NONE,True))
  assert h is not None and h.to_tuple()[0],'Current terrain missing'
  h=h.to_tuple();a=h[9];assert a is not None
  if isinstance(a,unreal.LandscapeProxy):
   assert a.get_actor_label()=='LandscapeStreamingProxy_6_9_0','Wrong landscape proxy'
   return {'xy':p,'z':h[5].z,'actor':a.get_path_name(),'transform':a.get_actor_transform().export_text()}
  skip.append(a)
 raise RuntimeError('No current landscape through bounded occluders')
for previous in SURVEY['terrain'][0]:
 current=terrain(previous['xy'])
 assert current['actor']==previous['actor'] and current['transform']==previous['transform'] and abs(current['z']-previous['z'])<.5,'Terrain changed since the measured support plan'
rect=DESIGN['rect'];grounds=[]
for u in (0.,.5,1.):
 for v in (0.,.5,1.):grounds.append(terrain(xy([rect['min'][0]+(rect['max'][0]-rect['min'][0])*u,rect['min'][1]+(rect['max'][1]-rect['min'][1])*v])))
top=DESIGN['stone_top'];bottom=min(h['z'] for h in grounds)-8.;depth=top-bottom
assert top>=max(h['z'] for h in grounds)+4. and 12.<=depth<=105.,'Actual terrain no longer fits this bounded support'
width=[rect['max'][i]-rect['min'][i] for i in range(2)];centre=[(rect['max'][i]+rect['min'][i])*.5 for i in range(2)]
scale=[width[i]/(hi[i]-lo[i]) for i in range(2)]+[depth/(hi[2]-lo[2])]
origin=xy([centre[i]-(lo[i]+hi[i])*.5*scale[i] for i in range(2)])
pads=[{'kind':'stone','rect':rect,'world_xy':origin,'z':top-hi[2]*scale[2],'scale':scale,'top':top,'bottom':bottom,'height':depth},
      {'kind':'coping','rect':rect,'world_xy':xy(centre),'z':DESIGN['cap_top']-1.,'scale':[width[0]/100.,width[1]/100.,.02],'top':DESIGN['cap_top'],'bottom':DESIGN['cap_top']-2.,'height':2.}]
poses=[(p['world_xy']+[p['z']],p['scale']) for p in pads]+[(ROW['world_xy_cm']+[DESIGN['body_z']],[ROW['scale']]*3)]
rotation=unreal.Rotator(pitch=0.,yaw=ROW['yaw'],roll=0.);changed=[]
if PHASE=='apply':
 for i,(position,scale) in enumerate(poses):
  a=old[i] if old[i] else eas.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(*position),rotation)
  assert a is not None,'Support spawn failed; inspect receipt before retry'
  a.modify();a.set_actor_label(labels[i]);a.tags=[unreal.Name(TAG),unreal.Name('S26_FLAT_COPING_V1')]
  a.static_mesh_component.set_static_mesh([floor,cube,mesh][i])
  if i==1:a.static_mesh_component.set_material(0,metal)
  a.set_actor_location(unreal.Vector(*position),False,False);a.set_actor_rotation(rotation,False);a.set_actor_scale3d(unreal.Vector(*scale))
  a.set_actor_enable_collision(True);a.static_mesh_component.set_simulate_physics(False);a.static_mesh_component.set_collision_profile_name('BlockAll')
  a.set_folder_path('Set/S26_LevelSupports_20261001');old[i]=a
  changed.append({'actor':a.get_path_name(),'package':a.get_package().get_name(),'transform':a.get_actor_transform().export_text()})
else:
 for i,(a,(position,scale)) in enumerate(zip(old,poses)):
  p=a.get_actor_location();q=a.get_actor_scale3d();r=a.get_actor_rotation()
  assert all(abs(x-y)<.02 for x,y in zip([p.x,p.y,p.z],position)) and all(abs(x-y)<.0002 for x,y in zip([q.x,q.y,q.z],scale)),'Installed support pose differs'
  assert abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-ROW['yaw']+180)%360-180)<.01
  assert a.static_mesh_component.static_mesh==[floor,cube,mesh][i] and a.get_actor_enable_collision() and a.static_mesh_component.get_collision_enabled()!=unreal.CollisionEnabled.NO_COLLISION
 assert old[1].static_mesh_component.get_material(0)==metal,'Textured cap material changed'
surface=[];support_refs=[];body_refs=[];allowed=[old[1]];contact_ignored=[old[2]]
if DESIGN['corner_mate_label']:
 mate=unique(DESIGN['corner_mate_label'])
 if mate:
  assert mate.static_mesh_component.static_mesh==cube and mate.static_mesh_component.get_material(0)==metal
  assert 'S26_FLAT_COPING_V1' in [str(t) for t in mate.tags]
  allowed.append(mate);support_refs.append({'actor':mate.get_path_name(),'package':mate.get_package().get_name(),'transform':mate.get_actor_transform().export_text(),'mesh':cube.get_path_name(),'material':metal.get_path_name()})
  mate_body=unique(DESIGN['corner_mate_label'][:-7]);assert mate_body is not None
  assert mate_body.static_mesh_component.static_mesh==mesh and 'S26_FLAT_COPING_V1' in [str(t) for t in mate_body.tags]
  contact_ignored.append(mate_body);body_refs.append({'actor':mate_body.get_path_name(),'package':mate_body.get_package().get_name(),'transform':mate_body.get_actor_transform().export_text(),'mesh':mesh.get_path_name()})
started=datetime.datetime.now(datetime.timezone.utc)
for p in ROW['contacts']:
 budget();calls+=1;pt=xy(p);z=DESIGN['body_z']+p[2]
 h=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(pt[0],pt[1],z+100.),unreal.Vector(pt[0],pt[1],z-200.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,contact_ignored,unreal.DrawDebugTrace.NONE,True))
 assert h is not None and h.to_tuple()[0],'Physical contact missing'
 h=h.to_tuple();surface.append({'point':pt+[z],'actor':h[9].get_path_name() if h[9] else None,'owned_footing':h[9] in allowed,'clearance_cm':z-h[5].z})
result={'id':ROW['id'],'label':ROW['label'],'pads':pads,'body_z':DESIGN['body_z'],'terrain':[grounds],'changed':changed,'applied':PHASE=='apply','saved':False,'verified_transforms':True,'support_references':support_refs,'contact_body_references':body_refs,'surface_contacts':surface,'surface_contact_pass':all(p['owned_footing'] and abs(p['clearance_cm'])<=.5 for p in surface),'contact_margin_cm':DESIGN['contact_margin_cm'],'trace_calls':calls,'visual_acceptance_required':True}
print('S26_LEVEL_PLINTH '+json.dumps(result,separators=(',',':')))
'''

def main():
    rows=original.plan()['rows'][:14]
    surveys={r['id']:receipt(BASE/'survey_readbacks'/f"{i:02d}_{r['id']}.readback.json") for i,r in enumerate(rows)}
    prior=receipt(BASE/'fence_receipts/FenceRear00/apply.readback.json')['changed']
    manifest={'groups':[],'design':'partitioned stone + 2cm flat textured metal coping; corner pairs share height','first_visual_review':'FenceRear00 before remaining groups'}
    gate=receipt(BASE/'gate_contact_verify_readbacks/Gate_supported.readback.json')
    assert gate['surface_contact_pass']
    designs=design(rows,surveys,gate)
    for i,d in enumerate(designs):
        steps=[]
        for phase in ('apply','verify'):
            code=EDITOR.replace('__DESIGN__',repr(d)).replace('__PRIOR__',repr(prior if i==0 else None)).replace('__PHASE__',phase).replace('__FLOOR__',plinth.FLOOR).replace('__CUBE__',CUBE).replace('__METAL__',METAL)
            ast.parse(code)
            path=OUT/phase/(d['row']['id']+'.py');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(code,encoding='utf-8')
            steps.append({'phase':phase,'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        manifest['groups'].append({'id':d['row']['id'],'group':i//3,'calls':steps})
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'fence_execution_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    (OUT/'design.json').write_text(json.dumps(designs,indent=2)+'\n',encoding='utf-8')
    print(OUT/'fence_execution_manifest.json')

if __name__=='__main__':main()
