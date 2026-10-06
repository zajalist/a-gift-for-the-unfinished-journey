"""Read-only diagnostics for an occluded owned actual-pose preview."""
from pathlib import Path
import argparse
import hashlib
import json
import prepare_dawn_pose_capture as capture

STATE=capture.OWNED+'''
centre,extent,radius=unreal.SystemLibrary.get_component_bounds(mesh)
data=mesh.get_editor_property('animation_data')
anim=data.get_editor_property('anim_to_play')
result=dict(body=body.get_path_name(),body_transform=body.get_actor_transform().export_text(),
 body_hidden=body.get_editor_property('hidden'),editor_only=body.get_editor_property('is_editor_only_actor'),
 mesh=mesh.get_skeletal_mesh_asset().get_path_name(),mesh_transform=mesh.get_world_transform().export_text(),
 visible=mesh.is_visible(),bounds=dict(centre=xyz(centre),extent=xyz(extent),sphere_radius=radius),
 flags={k:mesh.get_editor_property(k) for k in ['hidden_in_game','owner_no_see','only_owner_see','hidden_in_scene_capture','visible_in_scene_capture_only','render_in_main_pass','render_in_depth_pass','cast_shadow']},
 materials=[mesh.get_material(i).get_path_name() if mesh.get_material(i) else None for i in range(mesh.get_num_materials())],
 animation=anim.get_path_name() if anim else None,position=mesh.get_position(),playing=mesh.is_playing(),
 camera=cap.get_actor_transform().export_text(),camera_component=c.get_world_transform().export_text(),fov=c.get_editor_property('fov_angle'),
 primitive_render_mode=str(c.get_editor_property('primitive_render_mode')),
 hidden_actors=[a.get_path_name() for a in c.get_editor_property('hidden_actors') if a],
 show_only_actors=[a.get_path_name() for a in c.get_editor_property('show_only_actors') if a])
print('DAWN_PREVIEW_VISIBILITY '+json.dumps(result,separators=(',',':')))
'''

TRACES=capture.OWNED+'''
import datetime
started=datetime.datetime.now(datetime.timezone.utc);calls=0
eye=c.get_world_location();rows=[]
def trace(a,b):
 global calls
 calls+=1
 assert calls<=18 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Trace budget'
 hit=unreal.SystemLibrary.line_trace_single(world,a,b,unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[body,cap],unreal.DrawDebugTrace.NONE,True)
 if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
 if hit is None or not hit.to_tuple()[0]:return dict(blocked=False)
 h=hit.to_tuple();actor=h[9];component=h[10]
 return dict(blocked=True,actor=actor.get_path_name() if actor else None,label=actor.get_actor_label() if actor else None,
  component=component.get_path_name() if component else None,point=xyz(h[5]),normal=xyz(h[7]),initial_overlap=bool(h[1]))
for bone in ['Hips','Head','LeftFoot','RightFoot','staff011']:
 target=mesh.get_socket_location(bone)
 rows.append(dict(kind='camera_to_bone',bone=bone,start=xyz(eye),end=xyz(target),hit=trace(eye,target)))
for name,p in [('camera',eye),('body_origin',body.get_actor_location()),('head',mesh.get_socket_location('Head'))]:
 rows.append(dict(kind='vertical_surface',name=name,start=xyz(p),hit=trace(p+unreal.Vector(0,0,1000),p-unreal.Vector(0,0,1500))))
print('DAWN_PREVIEW_OCCLUSION '+json.dumps(dict(rows=rows,calls=calls),separators=(',',':')))
'''

BOUNDS=capture.OWNED+'''
import datetime
started=datetime.datetime.now(datetime.timezone.utc)
eye=c.get_world_location();target=mesh.get_socket_location('Hips');a=xyz(eye);b=xyz(target)
components=[v for v in unreal.ObjectIterator(unreal.PrimitiveComponent) if v.get_world()==world]
assert len(components)<16000,'Bounded loaded-world component inventory required'
rows=[];intersections=0
for component in components:
 assert (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounds survey budget'
 if not component.is_visible():continue
 centre,extent,radius=unreal.SystemLibrary.get_component_bounds(component)
 lo=[v-w for v,w in zip(xyz(centre),xyz(extent))];hi=[v+w for v,w in zip(xyz(centre),xyz(extent))]
 near,far=0.,1.
 for axis in range(3):
  delta=b[axis]-a[axis]
  if abs(delta)<.000001:
   if a[axis]<lo[axis] or a[axis]>hi[axis]:near,far=1.,0.
  else:
   x,y=(lo[axis]-a[axis])/delta,(hi[axis]-a[axis])/delta
   near=max(near,min(x,y));far=min(far,max(x,y))
 if near>far:continue
 intersections+=1;owner=component.get_owner()
 rows.append(dict(component=component.get_path_name(),class_name=component.get_class().get_name(),
   actor=owner.get_path_name() if owner else None,label=owner.get_actor_label() if owner else None,
   centre=xyz(centre),extent=xyz(extent),near_fraction=near,far_fraction=far,
   collision=str(component.get_collision_enabled()),hidden=component.get_editor_property('hidden_in_game'),
   static_mesh=component.static_mesh.get_path_name() if isinstance(component,unreal.StaticMeshComponent) and component.static_mesh else None))
rows.sort(key=lambda r:(r['near_fraction'],sum(r['extent'])))
print('DAWN_PREVIEW_RAY_BOUNDS '+json.dumps(dict(components_checked=len(components),intersections=intersections,rows=rows[:20],limits='Bounds intersect the camera-to-hips ray; this does not prove visible triangle occlusion.'),separators=(',',':')))
'''


def prepare(out):
    assert not out.exists(),'Preserve earlier diagnostic packets'
    out.mkdir(parents=True);scripts={}
    for name,code in [('00_visibility.py',STATE),('10_camera_traces.py',TRACES),('20_ray_bounds.py',BOUNDS)]:
        capture.ground.checked(code);path=out/name;path.write_text(code,encoding='utf-8')
        scripts[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(dict(status='prepared_not_run',scripts=scripts,scope='Read-only owned preview visibility, current collision and loaded primitive bounds'),indent=2)+'\n')
    print('DAWN_VISIBILITY_PROBES_READY',out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
