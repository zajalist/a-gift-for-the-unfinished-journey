"""Prepare bounded upright S26 props on measured stone plinths, offline only.

Preserves the original slope-fitting packet. Root runs the survey calls first,
then prepares guarded apply calls from their exact returned terrain evidence.
The station shell and every existing story anchor remain outside this packet.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import math
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import prepare_summit_expansion as original

OUT = ROOT / 'Saved/Tripo/20261001/station_plinths'
FLOOR = '/Game/SaskartaGaea/Environment/Batch01/SM_B01_floor01.SM_B01_floor01'
FLOOR_BOUNDS = [[-152.2162, -152.6798, -8.1794], [152.0206, 151.9715, 9.7597]]
TAG = 'S26_LEVEL_PLINTH_20261001'

GEOMETRY = '''
def support_rects(name, contacts):
    groups = [contacts]
    if name == 'Gate':
        assert all(abs(p[1]) > 65 for p in contacts), 'Gate contacts intrude into the known 120cm clear corridor'
        groups = [[p for p in contacts if p[1] < 0], [p for p in contacts if p[1] > 0]]
    result = []
    for points in groups:
        assert len(points) >= 2, 'Insufficient support cluster'
        margin = 5.0 if name == 'Gate' else 7.0
        lo = [min(p[i] for p in points)-margin for i in range(2)]
        hi = [max(p[i] for p in points)+margin for i in range(2)]
        for axis in range(2):
            if hi[axis]-lo[axis] < 40.0:
                centre=(hi[axis]+lo[axis])*.5
                lo[axis],hi[axis]=centre-20.0,centre+20.0
        if name == 'Gate':
            assert hi[1] <= -60 or lo[1] >= 60, 'Stone footing would obstruct the proven gate opening'
        result.append({'min':lo,'max':hi})
    return result

def support_geometry(rects, grounds, contacts, floor_bounds):
    assert len(rects) == len(grounds) and all(len(g) == 9 for g in grounds), 'Full 3x3 terrain grids required'
    top = max(h['z'] for g in grounds for h in g) + 5.0
    lo, hi = floor_bounds
    pads = []
    for rect, hits in zip(rects, grounds):
        bottom = min(h['z'] for h in hits)-8.0
        depth = top-bottom
        assert 12 <= depth <= 75, 'Measured support needs a different site or retaining design (>75cm)'
        scale = [(rect['max'][i]-rect['min'][i])/(hi[i]-lo[i]) for i in range(2)] + [depth/(hi[2]-lo[2])]
        local_origin = [(rect['min'][i]+rect['max'][i])*.5-(lo[i]+hi[i])*.5*scale[i] for i in range(2)]
        pads.append({'rect':rect,'scale':scale,'local_origin_xy':local_origin,'z':top-hi[2]*scale[2],
                     'top':top,'bottom':bottom,'height':depth})
    return pads, top-min(p[2] for p in contacts)-0.5
'''

exec(GEOMETRY)

EDITOR = '''import unreal,json,math,datetime
ROW=__ROW__
EXPECTED=__EXPECTED__
PHASE='__PHASE__'
FLOOR='__FLOOR__'
FLOOR_BOUNDS=__FLOOR_BOUNDS__
TAG='__TAG__'
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE before a plinth survey or apply'
world=es.get_editor_world()
assert world is not None and world.get_name()=='Saskarta_WP'
started=datetime.datetime.now(datetime.timezone.utc)
actors=list(unreal.EditorLevelLibrary.get_all_level_actors())
assert len(actors)<2500,'Bounded resident actor inventory exceeded'
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
assert any(a.get_actor_label()=='SD_S26_HighVoiceTripo_000' for a in actors),'Load the existing S26 foundation'
assert any(a.get_actor_label()=='LandscapeStreamingProxy_6_9_0' for a in actors),'Load the exact current S26 landscape proxy'

def unique(label):
    matches=[a for a in actors if a.get_actor_label()==label]
    assert len(matches)<=1,'Duplicate target label'
    if matches:assert TAG in [str(t) for t in matches[0].tags],'Existing actor belongs to another packet'
    return matches[0] if matches else None

old=unique(ROW['label'])
contacts=ROW['contacts']
mesh=None;cls=None
if ROW['kind']=='mesh':
    mesh=unreal.load_asset(ROW['asset'])
    assert isinstance(mesh,unreal.StaticMesh)
    box=mesh.get_bounding_box()
    size=[(box.max.x-box.min.x)*ROW['scale'],(box.max.y-box.min.y)*ROW['scale'],(box.max.z-box.min.z)*ROW['scale']]
    assert all(abs(a-b)<2 for a,b in zip(size,ROW['expected_size_cm'])),'Imported mesh bounds no longer match reviewed source'
    if old:assert old.static_mesh_component.static_mesh==mesh,'Existing prop mesh changed'
else:
    bp=unreal.load_asset(ROW['asset'])
    cls=unreal.EditorAssetLibrary.load_blueprint_class(ROW['asset'])
    assert bp is not None and cls is not None
    sub=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib=unreal.SubobjectDataBlueprintFunctionLibrary
    mounts={}
    for handle in sub.k2_gather_subobject_data_for_blueprint(bp):
        data=lib.get_data(handle)
        if str(lib.get_variable_name(data))=='Biofuel01_Mount':
            comp=lib.get_object(data);mounts[comp.get_path_name()]=comp
    assert len(mounts)==1,'Expected one actual intact tank mount template'
    comp=list(mounts.values())[0]
    box=comp.static_mesh.get_bounding_box();pose=comp.get_relative_transform()
    contacts=[]
    for x in (box.min.x,box.max.x):
        for y in (box.min.y,box.max.y):
            p=pose.transform_location(unreal.Vector(x,y,box.min.z));contacts.append([p.x,p.y,p.z])
    if old:assert old.get_class()==cls,'Existing tank class changed'

floor=unreal.load_asset(FLOOR)
assert isinstance(floor,unreal.StaticMesh)
bb=floor.get_bounding_box()
actual=[[bb.min.x,bb.min.y,bb.min.z],[bb.max.x,bb.max.y,bb.max.z]]
assert all(abs(actual[i][j]-FLOOR_BOUNDS[i][j])<.1 for i in range(2) for j in range(3)),'Existing floor mesh changed'
__GEOMETRY__
rects=support_rects(ROW['id'],contacts)
pad_labels=[ROW['label']+'_Stone'+str(i) for i in range(len(rects))]
old_pads=[unique(label) for label in pad_labels]
for a in old_pads:
    if a:assert a.static_mesh_component.static_mesh==floor,'Existing owned footing mesh changed'
ignored=[a for a in [old]+old_pads if a is not None]
angle=math.radians(ROW['yaw']);co=math.cos(angle);si=math.sin(angle)
def xy(local):
    return [ROW['world_xy_cm'][0]+local[0]*co-local[1]*si,
            ROW['world_xy_cm'][1]+local[0]*si+local[1]*co]
calls=0
def terrain(p):
    global calls
    skip=list(ignored)
    for layer in range(6):
        assert calls<120 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounded trace budget exceeded before mutation'
        calls+=1
        hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p[0],p[1],__Z__+5000),
            unreal.Vector(p[0],p[1],__Z__-10000),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,skip,unreal.DrawDebugTrace.NONE,True)
        if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
        assert hit is not None and hit.to_tuple()[0],'Current support unavailable; no heightmap fallback'
        h=hit.to_tuple();actor=h[9]
        assert actor is not None
        if isinstance(actor,unreal.LandscapeProxy):
            assert actor.get_actor_label()=='LandscapeStreamingProxy_6_9_0','Unexpected landscape support'
            return {'xy':p,'z':h[5].z,'actor':actor.get_path_name(),'transform':actor.get_actor_transform().export_text()}
        skip.append(actor)
    raise RuntimeError('Current Landscape unavailable through occluders')
grounds=[]
for rect in rects:
    grid=[]
    for u in (0.,.5,1.):
        for v in (0.,.5,1.):
            local=[rect['min'][0]+(rect['max'][0]-rect['min'][0])*u,
                   rect['min'][1]+(rect['max'][1]-rect['min'][1])*v]
            grid.append(terrain(xy(local)))
    grounds.append(grid)
pads,body_z=support_geometry(rects,grounds,contacts,actual)
body_z+=ROW.get('surface_adjustment_cm',0.0)
pad_adjustments=ROW.get('pad_surface_adjustment_cm',[0.0]*len(pads))
assert len(pad_adjustments)==len(pads) and all(abs(v)<=2 for v in pad_adjustments),'Only measured minor stone seating corrections allowed'
for pad,adjustment in zip(pads,pad_adjustments):
    for key in ['z','top','bottom']:pad[key]+=adjustment
if PHASE=='apply' and 'prior_body_z' in ROW:
    assert old is not None,'Measured seating correction requires the existing owned prop'
    p=old.get_actor_location();s=old.get_actor_scale3d();r=old.get_actor_rotation()
    assert abs(p.x-ROW['world_xy_cm'][0])<.02 and abs(p.y-ROW['world_xy_cm'][1])<.02 and abs(p.z-ROW['prior_body_z'])<.02,'Prop moved since actual contact measurement'
    assert all(abs(v-ROW['scale'])<.0002 for v in [s.x,s.y,s.z]) and abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-ROW['yaw']+180)%360-180)<.01,'Prop pose changed since actual contact measurement'
    for i,adjustment in enumerate(pad_adjustments):
        if adjustment:
            actor=old_pads[i];assert actor is not None,'Measured stone correction requires its existing owned actor'
            prior=EXPECTED['pads'][i];p=actor.get_actor_location();s=actor.get_actor_scale3d();r=actor.get_actor_rotation()
            assert all(abs(a-b)<.02 for a,b in zip([p.x,p.y,p.z],prior['world_xy']+[prior['z']])),'Stone moved since contact measurement'
            assert all(abs(a-b)<.0002 for a,b in zip([s.x,s.y,s.z],prior['scale'])) and abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-ROW['yaw']+180)%360-180)<.01,'Stone pose changed since contact measurement'
for pad in pads:pad['world_xy']=xy(pad['local_origin_xy'])
result={'id':ROW['id'],'label':ROW['label'],'contacts':contacts,'pads':pads,'body_z':body_z,
        'yaw':ROW['yaw'],'terrain':grounds,'trace_calls':calls,'floor_bounds':actual,'saved':False,'applied':False}
if EXPECTED is not None:
    assert EXPECTED['id']==ROW['id'] and EXPECTED['contacts']==contacts,'Survey identity or physical mount changed'
    assert EXPECTED['floor_bounds']==actual and len(EXPECTED['terrain'])==len(grounds),'Survey support definition changed'
    for prior,current in zip(EXPECTED['terrain'],grounds):
        assert len(prior)==len(current)
        for a,b in zip(prior,current):
            assert a['xy']==b['xy'] and a['actor']==b['actor'] and a['transform']==b['transform'] and abs(a['z']-b['z'])<.5,'Current terrain changed since survey'
if PHASE=='apply':
    assert EXPECTED is not None,'Apply requires an exact returned survey'
    rotation=unreal.Rotator(pitch=0.0,yaw=ROW['yaw'],roll=0.0)
    changed=[]
    selected_pads=[(i,pad) for i,pad in enumerate(pads) if pad_adjustments[i]] if 'surface_adjustment_cm' in ROW else list(enumerate(pads))
    for i,pad in selected_pads:
        location=unreal.Vector(pad['world_xy'][0],pad['world_xy'][1],pad['z'])
        if 'surface_adjustment_cm' in ROW:
            actor=old_pads[i];actor.modify();actor.set_actor_location(location,False,False)
        else:
            actor=old_pads[i] if old_pads[i] else eas.spawn_actor_from_class(unreal.StaticMeshActor,location,rotation)
            assert actor is not None,'Footing spawn failed'
            actor.modify();actor.set_actor_label(pad_labels[i]);actor.tags=[unreal.Name(TAG)]
            actor.static_mesh_component.set_static_mesh(floor)
            actor.static_mesh_component.set_collision_profile_name('BlockAll')
            actor.set_actor_location(location,False,False);actor.set_actor_rotation(rotation,False)
            actor.set_actor_scale3d(unreal.Vector(*pad['scale']));actor.set_folder_path('Set/S26_LevelSupports_20261001')
        changed.append({'actor':actor.get_path_name(),'package':actor.get_package().get_name(),'transform':actor.get_actor_transform().export_text()})
    location=unreal.Vector(ROW['world_xy_cm'][0],ROW['world_xy_cm'][1],body_z)
    if 'surface_adjustment_cm' in ROW:
        actor=old;actor.modify();actor.set_actor_location(location,False,False)
    else:
        actor=old if old else eas.spawn_actor_from_class(unreal.StaticMeshActor if mesh else cls,location,rotation)
        assert actor is not None,'Upright prop spawn failed; retain owned footing for review'
        actor.modify();actor.set_actor_label(ROW['label']);actor.tags=[unreal.Name(TAG)]
        if mesh:actor.static_mesh_component.set_static_mesh(mesh)
        actor.set_actor_location(location,False,False);actor.set_actor_rotation(rotation,False)
        actor.set_actor_scale3d(unreal.Vector(ROW['scale'],ROW['scale'],ROW['scale']))
        actor.set_folder_path('Set/S26_LevelSupports_20261001')
    changed.append({'actor':actor.get_path_name(),'package':actor.get_package().get_name(),'transform':actor.get_actor_transform().export_text()})
    result['applied']=True;result['changed']=changed
if PHASE=='verify':
    assert EXPECTED is not None and old is not None and all(a is not None for a in old_pads),'Placed owned prop and all footings required'
    intended=[([pad['world_xy'][0],pad['world_xy'][1],pad['z']],pad['scale']) for pad in pads]
    intended.append(([ROW['world_xy_cm'][0],ROW['world_xy_cm'][1],body_z],[ROW['scale']]*3))
    for actor,(want_position,want_scale) in zip(old_pads+[old],intended):
        p=actor.get_actor_location();s=actor.get_actor_scale3d();r=actor.get_actor_rotation()
        assert all(abs(a-b)<.02 for a,b in zip([p.x,p.y,p.z],want_position)),'Placed position differs from measured plan'
        assert all(abs(a-b)<.0002 for a,b in zip([s.x,s.y,s.z],want_scale)),'Placed scale differs from measured plan'
        assert abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-ROW['yaw']+180)%360-180)<.01,'Prop or footing is not upright at the intended yaw'
    surface=[]
    for local in contacts:
        point=xy(local);z=body_z+local[2]
        hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(point[0],point[1],z+100),
            unreal.Vector(point[0],point[1],z-200),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[old],unreal.DrawDebugTrace.NONE,True)
        if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
        assert hit is not None and hit.to_tuple()[0],'No real surface beneath a placed support point'
        h=hit.to_tuple();support=h[9]
        surface.append({'point':[point[0],point[1],z], 'actor':support.get_path_name() if support else None,
            'owned_footing':support in old_pads, 'clearance_cm':z-h[5].z})
    result['surface_contacts']=surface
    result['surface_contact_pass']=all(s['owned_footing'] and -4<=s['clearance_cm']<=4 for s in surface)
    result['verified_transforms']=True
    result['gate_collision_acceptance_pending']=ROW['id']=='Gate'
print('S26_LEVEL_PLINTH '+json.dumps(result,separators=(',',':')))
'''


def script(row, reference_z, expected=None, phase='survey'):
    assert phase in ('survey','apply','verify')
    assert phase=='survey' or expected is not None
    text = EDITOR.replace('__ROW__', repr(row)).replace('__EXPECTED__', repr(expected))
    text = text.replace('__PHASE__',phase)
    text = text.replace('__FLOOR__', FLOOR).replace('__FLOOR_BOUNDS__', repr(FLOOR_BOUNDS))
    text = text.replace('__TAG__', TAG).replace('__GEOMETRY__', GEOMETRY).replace('__Z__', str(reference_z))
    ast.parse(text)
    for word in ('getattr', 'import time', 'open(', 'save_asset', 'save_packages', '.replace(', 'destroy_actor'):
        assert word not in text, word
    return text


def read_receipt(path):
    text = path.read_text(encoding='utf-8')
    if text.lstrip().startswith('{'):
        envelope = json.loads(text)
        text = envelope.get('output', text)
    rows = [json.loads(line.split('S26_LEVEL_PLINTH ',1)[1]) for line in text.splitlines() if line.startswith('S26_LEVEL_PLINTH ')]
    if len(rows)!=1 or rows[0]['applied']:
        raise ValueError('One complete read-only plinth survey receipt required')
    return rows[0]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--survey-result',type=Path,help='Prepare one apply script only after root returns its survey')
    ap.add_argument('--surface-result',type=Path,help='Correct only a measured owned prop after real floor-surface verification')
    args=ap.parse_args()
    data=original.plan()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.survey_result:
        receipt=read_receipt(args.survey_result)
        rows=[r for r in data['rows'] if r['id']==receipt['id']]
        assert len(rows)==1
        for phase in ('apply','verify'):
            path=OUT/phase/f"{receipt['id']}.py"
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(script(rows[0],data['reference_z_cm'],receipt,phase),encoding='utf-8')
            print(path)
        return
    if args.surface_result:
        receipt=read_receipt(args.surface_result)
        surface=receipt.get('surface_contacts',[])
        assert surface and receipt.get('verified_transforms') and all(s['owned_footing'] for s in surface),'Exact owned top surface measurements required'
        clearances=[s['clearance_cm'] for s in surface]
        low,high=min(clearances),max(clearances)
        assert high-low<7.5,'Top surface spread requires a different support, not vertical adjustment'
        adjustment=-(low+high)*.5
        assert abs(adjustment)<6,'Measured correction exceeds narrow seating scope'
        rows=[dict(r) for r in data['rows'] if r['id']==receipt['id']]
        assert len(rows)==1
        row=rows[0];row['surface_adjustment_cm']=adjustment;row['prior_body_z']=receipt['body_z']
        for phase in ('apply','verify'):
            path=OUT/(phase+'_contact')/f"{receipt['id']}.py"
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(script(row,data['reference_z_cm'],receipt,phase),encoding='utf-8')
            print(path,'Z adjustment',adjustment)
        return
    sources={}
    for i,row in enumerate(data['rows']):
        path=OUT/'survey'/f"{i:02d}_{row['id']}.py"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(script(row,data['reference_z_cm']),encoding='utf-8')
        sources[str(path.relative_to(OUT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/'plan.json').write_text(json.dumps({'status':'survey_first_no_live_changes','floor':FLOOR,
        'floor_bounds':FLOOR_BOUNDS,'tag':TAG,'rows':data['rows'],'scripts':sources,
        'gates':'Paired side footings preserve the existing120cm clear opening; no raised full threshold',
        'requirements':['Root runs current terrain surveys first','No apply without exact returned survey',
          'Upright props; inspect actual floor surface contact and gate collision before scoped saves',
          'Existing station shell and protected story actors are untouched']},indent=2)+'\n',encoding='utf-8')
    print('S26_LEVEL_SUPPORT_SURVEYS_READY',len(sources),OUT)


if __name__=='__main__':
    main()
