import unreal,json,math,datetime
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
ROW={'id': 'Gate', 'label': 'SD_S26_Upgrade_20261001_Gate', 'kind': 'mesh', 'asset': '/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_gate_open', 'source_key': 'S26_gate_open_clear', 'source_sha256': 'ef2c9164567e9ffada138b54bd9a24c8a239ccbab844841f8e3dc6ba7982af3c', 'local_xy_cm': [-500, 0], 'world_xy_cm': [297727.71693849546, 483493.9758174929], 'yaw': 198.66, 'scale': 1.0, 'contacts': [[66.1315, 72.4808, 1.7963], [26.587, 184.1819, 0.4164], [-8.2542, 185.7165, 1.3323], [-65.5069, 183.5515, 0.4045], [-66.982, 117.8631, 1.4394], [-64.2162, -184.1343, 0.3926], [-28.8056, -185.5737, 1.9152], [27.4851, -183.5871, 0.3926]], 'expected_size_cm': [157.22, 382.377, 280.026]}
actors=list(unreal.EditorLevelLibrary.get_all_level_actors());assert len(actors)<2500
matches=[a for a in actors if a.get_actor_label()==ROW['label']]
assert len(matches)==1 and 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in matches[0].tags],'Exact placed gate required'
gate=matches[0];comp=gate.static_mesh_component
assert comp.static_mesh.get_path_name()==ROW['asset']+'.'+ROW['asset'].split('/')[-1]
assert comp.get_collision_enabled()!=unreal.CollisionEnabled.NO_COLLISION,'Gate collision must exist for passage proof'
assert comp.static_mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag')==unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,'Source opening requires actual mesh collision'
r=gate.get_actor_rotation();assert abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-ROW['yaw']+180)%360-180)<.01
origin=gate.get_actor_location();angle=math.radians(ROW['yaw']);co=math.cos(angle);si=math.sin(angle)
started=datetime.datetime.now(datetime.timezone.utc)
def budget():assert (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounded passage probe exceeded'
def unpack(h):
 if isinstance(h,tuple) and len(h)==2 and not isinstance(h[0],unreal.HitResult):return h[1] if h[0] else None
 return h
rows=[]
for offset in (-15.,0.,15.):
 points=[];supports=[]
 for along in (-150.,-75.,0.,75.,150.):
  budget();x=origin.x+along*co-offset*si;y=origin.y+along*si+offset*co
  hit=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,origin.z+100),unreal.Vector(x,y,origin.z-250),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[],unreal.DrawDebugTrace.NONE,True))
  assert hit is not None and hit.to_tuple()[0],'Missing central walkway support'
  h=hit.to_tuple();support=h[9]
  ground=isinstance(support,unreal.LandscapeProxy) and support.get_actor_label()=='LandscapeStreamingProxy_6_9_0'
  walkable=h[7].z>=math.cos(math.radians(44.))
  supports.append({'along_cm':along,'point':[x,y,h[5].z],'actor':support.get_path_name() if support else None,'label':support.get_actor_label() if support else None,'landscape':ground,'normal_z':h[7].z,'walkable':walkable,'pass':ground and walkable})
  # A capsule bottom is spherical. On a slope its grounded centre is higher
  # than floor Z + half-height; use the actual surface normal plus 2cm skin.
  points.append(unreal.Vector(x,y,h[5].z+90.+32.*(1./max(h[7].z,.01)-1.)))
 hits=[]
 for a,b in zip(points,points[1:]):
  budget()
  hit=unpack(unreal.SystemLibrary.capsule_trace_single_by_profile(world,a,b,32.,88.,'Pawn',False,[],unreal.DrawDebugTrace.NONE,True))
  blocked=hit is not None and hit.to_tuple()[0]
  h=hit.to_tuple() if blocked else None
  hits.append({'blocked':bool(blocked),'actor':h[9].get_actor_label() if blocked and h[9] else None,'point':[h[5].x,h[5].y,h[5].z] if blocked else None})
 rows.append({'offset_cm':offset,'capsule_radius_cm':32,'capsule_half_height_cm':88,'supports':supports,'segments':hits,'pass':all(s['pass'] for s in supports) and not any(h['blocked'] for h in hits)})
print('S26_GATE_PASSAGE '+json.dumps({'gate':gate.get_path_name(),'rows':rows,'pass':all(r['pass'] for r in rows),'saved':False},separators=(',',':')))
