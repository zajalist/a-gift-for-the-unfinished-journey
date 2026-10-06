"""Offline S26 service-yard plan and bounded, idempotent editor preview scripts.

Each generated call handles one prop and traces current Landscape collision.
It never moves existing station/cinematic actors and never saves the world.
Root imports the new meshes, loads the exact S26 proxy, then reviews previews.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Tools/Tripo'))
import tripo_ingest as ti

OUT=ROOT/'Saved/Tripo/20261001/station_expansion'
PREFIX='SD_S26_Upgrade_20261001_'
TAG='S26_UPGRADE_20261001'
DEST='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_'
FUEL='/Game/SaskartaGaea/Characters/Carrier/Biofuel/Assemblies/BP_Biofuel01_Assembly'


def source_contacts(key,scale=1.):
    path=ROOT/f'SourceArt/Tripo/20261001/{key}/{key}_ue.glb'
    g,b=ti.read_glb(path);points=[]
    for mesh,m in ti._mesh_instances(g):
        for primitive in g['meshes'][mesh]['primitives']:
            v=ti.read_accessor(g,b,primitive['attributes']['POSITION'])
            points.append((v@m[:3,:3].T+m[:3,3])*100*scale)
    points=np.concatenate(points)[:,[0,2,1]] # Verified UE5.8 GLTF ConvertVec3.
    low=points[points[:,2]<points[:,2].min()+2.]
    contacts=[]
    for angle in np.arange(8)*math.pi/4:
        i=np.argmax(low[:,0]*math.cos(angle)+low[:,1]*math.sin(angle))
        point=low[i].round(4).tolist()
        if point not in contacts:contacts.append(point)
    assert len(contacts)>=3
    return contacts,(points.max(0)-points.min(0)).round(3).tolist(),hashlib.sha256(path.read_bytes()).hexdigest()


def plan():
    post=json.loads((ROOT/'Tools/Cinematics/probe_ending.json').read_text())['radio_post']
    site=json.loads((ROOT/'Tools/World/story_sets/S26_Tripo.json').read_text())['anchor']
    centre=site['hut_centre_cm'];yaw=site['site_yaw'];a=math.radians(yaw)
    def local(world):
        x,y=world[0]-centre[0],world[1]-centre[1]
        return [x*math.cos(a)+y*math.sin(a),-x*math.sin(a)+y*math.cos(a)]
    rows=[]
    def add(name,key,suffix,xy,heading=0,scale=1.):
        contacts,size,sha=source_contacts(key,scale)
        rows.append(dict(id=name,label=PREFIX+name,kind='mesh',asset=DEST+suffix,source_key=key,source_sha256=sha,
            local_xy_cm=list(xy),world_xy_cm=[centre[0]+xy[0]*math.cos(a)-xy[1]*math.sin(a),centre[1]+xy[0]*math.sin(a)+xy[1]*math.cos(a)],
            yaw=yaw+heading,scale=scale,contacts=contacts,expected_size_cm=size))
    for i,x in enumerate((-400,-200,0,200,400)):
        add(f'FenceRear{i:02d}','S26_fence_panel','s26_fence_panel',(x,-550))
    for i,y in enumerate((-450,-250,-50,150,350)):
        add(f'FenceRight{i:02d}','S26_fence_panel','s26_fence_panel',(500,y),90)
    for i,(y,scale) in enumerate(((-450,1.),(-270,.79),(270,.79),(450,1.))):
        add(f'FenceLeft{i:02d}','S26_fence_panel','s26_fence_panel',(-500,y),90,scale)
    add('Gate','S26_gate_open_clear','s26_gate_open',(-500,0))
    add('Transmitter','S26_transmitter_cabinet','s26_transmitter_cabinet',(-315,-125),90)
    for i,x in enumerate((-310,-380)):
        xy=(x,-280)
        rows.append(dict(id=f'Biofuel{i:02d}',label=PREFIX+f'Biofuel{i:02d}',kind='biofuel',asset=FUEL,
            local_xy_cm=list(xy),world_xy_cm=[centre[0]+xy[0]*math.cos(a)-xy[1]*math.sin(a),centre[1]+xy[0]*math.sin(a)+xy[1]*math.cos(a)],
            yaw=yaw+90,scale=1.,contacts=None,expected_size_cm=None))
    routes=[[local(post[k]) for k in keys] for keys in (('entry_start','door','inside'),('inside','door','exit_mid','collapse'))]
    return dict(status='source_plan_not_placed',site_yaw=yaw,centre_cm=centre,reference_z_cm=post['inside'][2],
        protected_anchors=post,protected_paths_local_cm=routes,corridor_radius_cm=130,rows=rows,
        shell=dict(state='fit_review_required_not_in_apply_scripts',asset=DEST+'s26_radio_station',
            existing_label='SD_S26_HighVoiceTripo_001',door_world_cm=post['door'],inside_world_cm=post['inside'],outward_yaw=site['outward_yaw'],
            source_door_candidate_cm=[126,-58,18],source_window_glTF_z_cm=-175,
            note='Verify imported doorway/floor/height and window sightline before replacing shell; source approximate opening is not an accepted capsule clearance. Preserve existing shell/anchors until then.'))


EDITOR=r'''import unreal,json,math,datetime
ROW=__ROW__
APPLY=__APPLY__
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
assert world is not None and world.get_name()=='Saskarta_WP'
started=datetime.datetime.now(datetime.timezone.utc)
actors=list(unreal.EditorLevelLibrary.get_all_level_actors())
assert len(actors)<2500,'Bounded loaded actor inventory exceeded'
old=[a for a in actors if a.get_actor_label()==ROW['label']]
assert len(old)<=1,'Duplicate target label'
if old:assert '__TAG__' in [str(t) for t in old[0].tags],'Do not replace unowned actor'
assert any(a.get_actor_label()=='SD_S26_HighVoiceTripo_000' for a in actors),'Load current foundation first'
assert any(a.get_class().get_name().startswith('Landscape') for a in actors),'Load S26 terrain proxy first'
mesh=None;cls=None;contacts=ROW['contacts']
if ROW['kind']=='mesh':
    mesh=unreal.load_asset(ROW['asset']);assert isinstance(mesh,unreal.StaticMesh)
    box=mesh.get_bounding_box();size=[(box.max.x-box.min.x)*ROW['scale'],(box.max.y-box.min.y)*ROW['scale'],(box.max.z-box.min.z)*ROW['scale']]
    assert all(abs(a-b)<2 for a,b in zip(size,ROW['expected_size_cm'])),'Imported source bounds changed'
    if old:assert old[0].static_mesh_component.static_mesh==mesh,'Existing prop mesh changed'
else:
    bp=unreal.load_asset(ROW['asset']);cls=unreal.EditorAssetLibrary.load_blueprint_class(ROW['asset'])
    assert bp is not None and cls is not None
    sub=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem);lib=unreal.SubobjectDataBlueprintFunctionLibrary
    mounts={}
    for handle in sub.k2_gather_subobject_data_for_blueprint(bp):
        data=lib.get_data(handle)
        if str(lib.get_variable_name(data))=='Biofuel01_Mount':
            comp=lib.get_object(data);mounts[comp.get_path_name()]=comp
    assert len(mounts)==1,'Expected actual intact Biofuel01_Mount template'
    comp=list(mounts.values())[0];box=comp.static_mesh.get_bounding_box();pose=comp.get_relative_transform()
    contacts=[]
    for x in (box.min.x,box.max.x):
        for y in (box.min.y,box.max.y):
            p=pose.transform_location(unreal.Vector(x,y,box.min.z));contacts.append([p.x,p.y,p.z])
    if old:assert old[0].get_class()==cls,'Existing tank class changed'

def add(a,b):return [a[i]+b[i] for i in range(3)]
def mul(a,s):return [v*s for v in a]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def norm(a):return mul(a,1/math.sqrt(dot(a,a)))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
calls=0
def terrain(x,y):
    global calls
    ignored=list(old)
    for layer in range(6):
        assert calls<96 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Trace budget exceeded before mutation'
        calls+=1
        hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,__Z__+5000),unreal.Vector(x,y,__Z__-10000),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True)
        if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
        assert hit is not None and hit.to_tuple()[0],'No current collision hit; do not use heightmap fallback'
        data=hit.to_tuple();actor=data[9]
        assert actor is not None
        if isinstance(actor,unreal.LandscapeProxy):
            p,n=data[5],data[7]
            return dict(z=p.z,normal=[n.x,n.y,n.z],actor=actor.get_path_name(),transform=actor.get_actor_transform().export_text())
        ignored.append(actor)
    raise RuntimeError('No current Landscape within occluder budget')

yaw=math.radians(ROW['yaw']);forward=[math.cos(yaw),math.sin(yaw),0.];right=[-math.sin(yaw),math.cos(yaw),0.];up=[0.,0.,1.]
world_xy=ROW['world_xy_cm'];hits=[]
for phase in range(2):
    offsets=[add(add(mul(forward,p[0]),mul(right,p[1])),mul(up,p[2])) for p in contacts]
    hits=[terrain(world_xy[0]+p[0],world_xy[1]+p[1]) for p in offsets]
    if phase==0:
        up=norm([sum(h['normal'][i] for h in hits) for i in range(3)])
        assert up[2]>math.cos(math.radians(12 if ROW['kind']=='mesh' and ROW['id'].startswith(('Fence','Gate')) else 5)),'Slope too steep; choose supported placement'
        forward=norm(add(forward,mul(up,-dot(forward,up))));right=norm(cross(up,forward))
z=max(h['z']-p[2] for h,p in zip(hits,offsets))-.5
clearance=[z+p[2]-h['z'] for h,p in zip(hits,offsets)]
assert max(clearance)<=4.,'Uneven contact: requires measured footing adjustment, not a floating prop'
rotation=unreal.Rotator(math.degrees(math.asin(forward[2])),math.degrees(math.atan2(forward[1],forward[0])),math.degrees(math.atan2(-right[2],up[2])))
if APPLY:
    actor=old[0] if old else unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor if mesh else cls,unreal.Vector(world_xy[0],world_xy[1],z),rotation)
    assert actor is not None
    if mesh:actor.static_mesh_component.set_static_mesh(mesh)
    actor.set_actor_label(ROW['label'])
    tags=list(actor.tags)
    if '__TAG__' not in [str(t) for t in tags]:tags.append(unreal.Name('__TAG__'))
    actor.tags=tags
    actor.set_actor_location(unreal.Vector(world_xy[0],world_xy[1],z),False,False)
    actor.set_actor_rotation(rotation,False);actor.set_actor_scale3d(unreal.Vector(ROW['scale'],ROW['scale'],ROW['scale']))
    actor.set_folder_path('Set/S26_Upgrade_20261001')
    result=actor.get_actor_transform().export_text()
else:result=None
print('S26_PROP_PREVIEW '+json.dumps(dict(id=ROW['id'],applied=APPLY,saved=False,position=[*world_xy,z],rotation=[rotation.pitch,rotation.yaw,rotation.roll],clearance_cm=clearance,trace_calls=calls,terrain=hits,actor_transform=result),separators=(',',':')))
'''


def prepare():
    data=plan();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'plan.json').write_text(json.dumps(data,indent=2)+'\n')
    scripts={}
    for index,row in enumerate(data['rows']):
        for mode,apply in (('survey',False),('apply',True)):
            code=EDITOR.replace('__ROW__',repr(row)).replace('__APPLY__',repr(apply)).replace('__TAG__',TAG).replace('__Z__',repr(data['reference_z_cm']))
            compile(code,row['id'],'exec')
            file=OUT/mode/f'{index:02d}_{row["id"]}.py';file.parent.mkdir(parents=True,exist_ok=True);file.write_text(code)
            scripts[str(file.relative_to(OUT))]=hashlib.sha256(file.read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(dict(state='offline_prepared_not_placed',count=len(data['rows']),scripts=scripts,
        requirements=['Import/verify scoped meshes first','Load current S26 foundation and LandscapeStreamingProxy_6_9_0','Survey first; root reviews contact output','Apply one actor per call; no world save included','Shell replacement requires separate measured fit'],
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'Tools/Cinematics/probe_ending.json',ROOT/'Tools/World/story_sets/S26_Tripo.json']}),indent=2)+'\n')
    print('SUMMIT_EXPANSION_READY',len(data['rows']),'props',len(scripts),'scripts',OUT)


if __name__=='__main__':prepare()
