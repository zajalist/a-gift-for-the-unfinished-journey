"""Prepare small read-only current-landscape probes for the revised ending.

Uses the verified production waist derivative for body skinning. Each probe has
eight named surface points, not arbitrary bounds. No editor operation is run here.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math

import numpy as np

import samyor_final as final
import samyor_dawn_turn as turn
import samyor_reveal as rig
import traveller_contacts as contacts
import traveller_terrain as terrain
import ending_staging as staging
from validate_waist_repair import derivative_entries, skin

ROOT = Path(__file__).resolve().parents[2]
DERIVATIVE = ROOT/'SourceArt/Characters/Traveller/Repairs/traveller01_waist_weights_20261001.fbx'
EXPECTED_DERIVATIVE = '757ff12556c6e5235b757ba72c141359e0a03a324bd9445ea223c7ce7af2ee57'
REGIONS = {
    'left_boot': ('LeftFoot','LeftToe'), 'right_boot': ('RightFoot','RightToe'),
    'left_hand': ('LeftHand',), 'right_hand': ('RightHand',),
    'hip_cloth': ('Hips',), 'torso_cloth': ('Spine',), 'hood': ('Neck','Head'),
}

PROBE = '''import unreal,json,datetime
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'PIE must be stopped'
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
started=datetime.datetime.now(datetime.timezone.utc);calls=0;rows=[]
for source in POINTS:
 point=source['body_surface'];ignored=[];result=None
 for layer in range(6):
  assert calls<48 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Trace budget exceeded'
  calls+=1
  hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(point[0],point[1],point[2]+1000),unreal.Vector(point[0],point[1],point[2]-2000),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True)
  if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
  assert hit is not None and hit.to_tuple()[0],'No current terrain collision'
  data=hit.to_tuple();actor=data[9];assert actor is not None
  if isinstance(actor,unreal.LandscapeProxy):
   p,n=data[5],data[7]
   result=dict(source,terrain_z=p.z,clearance_cm=point[2]-p.z,normal=[n.x,n.y,n.z],actor=actor.get_path_name());break
  ignored.append(actor)
 assert result is not None,'Landscape missing'
 rows.append(result)
print('DAWN_BODY_TERRAIN_V2 '+json.dumps(dict(SAMPLE,rows=rows,calls=calls),separators=(',',':')))
'''


def selected_points(pose, yaw, entries):
    vertices = skin(pose, entries)
    candidates = []
    for label, prefixes in REGIONS.items():
        weights = np.zeros(len(vertices))
        for bone, indices, values, _ in entries:
            if bone.startswith(prefixes): weights[indices] += values
        ids = np.flatnonzero(weights >= .35)
        assert len(ids)>10, (label,len(ids))
        index = int(ids[np.argmin(terrain.clearances(vertices[ids],yaw))])
        candidates.append((label,index,vertices[index]))
    staff = contacts.skin(pose,'tripo_mesh_88102862.001')
    index = int(np.argmin(terrain.clearances(staff,yaw)))
    candidates.append(('staff',index,staff[index]))
    spin = rig.qaxis((0,0,1),yaw)
    return [dict(region=label,source_vertex=index,
                 body_surface=[float(v) for v in rig.vadd(terrain.ORIGIN,rig.qrot(spin,point))],
                 predicted_plane_clearance_cm=float(terrain.clearances(np.array([point]),yaw)[0]))
            for label,index,point in candidates]


def prepare(out):
    assert not out.exists(), 'Preserve previous probes; use a new revision directory'
    assert hashlib.sha256(DERIVATIVE.read_bytes()).hexdigest()==EXPECTED_DERIVATIVE
    entries=derivative_entries()
    out.mkdir(parents=True)
    cases=[('collapse',t,final.pose_at(t),staging.SUN_BEARING-90) for t in (0.,1.,2.,3.8)]
    cases += [('arrival_settle',t,turn.pose_at(t),staging.arrival_yaw(turn.POST)+turn.DELTA*staging.turn_fraction(t)) for t in (0.,.55)]
    report=[]
    for number,(kind,at,pose,yaw) in enumerate(cases):
        points=selected_points(pose,yaw,entries)
        sample=dict(phase=kind,seconds=at,actor_yaw=yaw,derivative_sha256=EXPECTED_DERIVATIVE)
        script=out/f'{number:02d}_{kind}.py'
        code=PROBE.replace('POINTS',repr(points)).replace('SAMPLE',repr(sample))
        compile(code,str(script),'exec')
        script.write_text(code,encoding='utf-8')
        all_clearances=terrain.clearances(skin(pose,entries),yaw)
        report.append(dict(sample,points=points,minimum_body_plane_clearance_cm=float(all_clearances.min()),
                           script=script.name,script_sha256=hashlib.sha256(script.read_bytes()).hexdigest()))
    manifest=dict(status='prepared_not_run',terrain_origin=terrain.ORIGIN,slope_degrees=terrain.SLOPE_DEGREES,
                  origin_lift_cm=terrain.ORIGIN_LIFT_CM,cases=report,
                  limits='Named skinned surface points; an edge or hood is not automatically a weight-bearing contact. Actual imported pose and rendered support remain required.')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(directory=str(out),cases=len(report),minimum_plane_clearances=[r['minimum_body_plane_clearance_cm'] for r in report]),indent=2))


def prepare_final_support(out):
    """Resolve actual support through the lower thigh and the long staff ends."""
    assert not out.exists(), 'Preserve previous probes; use a new revision directory'
    assert hashlib.sha256(DERIVATIVE.read_bytes()).hexdigest()==EXPECTED_DERIVATIVE
    entries=derivative_entries();pose=final.pose_at(final.COLLAPSE_S)
    yaw=staging.SUN_BEARING-90;spin=rig.qaxis((0,0,1),yaw)
    vertices=skin(pose,entries);candidates=[]
    for prefix in ('LeftUpLeg','LeftLeg','LeftForeArm'):
        weights=np.zeros(len(vertices))
        for bone,ids,values,_ in entries:
            if bone.startswith(prefix):weights[ids]+=values
        ids=np.flatnonzero(weights>=.35)
        index=int(ids[np.argmin(terrain.clearances(vertices[ids],yaw))])
        candidates.append((prefix,index,vertices[index]))
    staff=contacts.skin(pose,'tripo_mesh_88102862.001')
    _,_,basis=np.linalg.svd(staff-staff.mean(axis=0),full_matrices=False)
    along=(staff-staff.mean(axis=0))@basis[0]
    for label,lo,hi in (('staff_end_a',0.,.2),('staff_middle',.4,.6),('staff_end_b',.8,1.)):
        alpha=(along-along.min())/(along.max()-along.min())
        ids=np.flatnonzero((alpha>=lo)&(alpha<=hi))
        index=int(ids[np.argmin(terrain.clearances(staff[ids],yaw))])
        candidates.append((label,index,staff[index]))
    points=[dict(region=label,source_vertex=index,body_surface=[float(v) for v in rig.vadd(terrain.ORIGIN,rig.qrot(spin,point))],
                 predicted_plane_clearance_cm=float(terrain.clearances(np.array([point]),yaw)[0])) for label,index,point in candidates]
    sample=dict(phase='final_support_paths',seconds=final.COLLAPSE_S,actor_yaw=yaw,derivative_sha256=EXPECTED_DERIVATIVE)
    code=PROBE.replace('POINTS',repr(points)).replace('SAMPLE',repr(sample));compile(code,'support','exec')
    out.mkdir(parents=True);script=out/'00_final_thigh_and_staff.py';script.write_text(code,encoding='utf-8')
    (out/'manifest.json').write_text(json.dumps(dict(sample,points=points,script_sha256=hashlib.sha256(script.read_bytes()).hexdigest()),indent=2)+'\n')
    print('FINAL_SUPPORT_PROBE_READY',out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    p.add_argument('--final-support',action='store_true');args=p.parse_args()
    (prepare_final_support if args.final_support else prepare)(args.out.resolve())
