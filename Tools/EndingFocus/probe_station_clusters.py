"""Prepared Hayba Unreal-Python script. Root alone runs AFTER stopping human PIE.

Adds only its owned crate/lid/latch cluster at the saved summit shell. Contact
placement derives the asset's real local bounding box and current collision;
no landscape flattening, guessed pivot, tank duplication or automatic save.
"""
import json
import math
import unreal

editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert editor.get_game_world() is None, 'Stop human PIE before the station dressing pass'
world = editor.get_editor_world()
assert world and world.get_name() == 'Saskarta_WP'
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
loaded = list(actors.get_all_level_actors())
assert len(loaded) < 2500, 'Load only the summit region'
shells = [a for a in loaded if a.get_actor_label() == 'SD_S26_HighVoiceTripo_001']
assert len(shells) == 1
shell = shells[0]
assert shell.static_mesh_component.static_mesh.get_path_name().startswith('/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_radio_station.')
origin = shell.get_actor_location()
assert abs(origin.x-297342.918097)<.1 and abs(origin.y-483375.261496)<.1 and abs(origin.z-10897.9)<.1, 'Saved shell changed; resurvey'
yaw = 288.66
crate = '/Game/Pallbearer/PolyHaven/wooden_crate_01/wooden_crate_01_2k/StaticMeshes/wooden_crate_01'
recipe = [
    ('Crate00', crate, (340., 95.), .9, 13.),
    ('Crate01', crate, (425., 175.), .68, -23.),
    ('Lid00', crate+'_lid', (386., 258.), .68, 36.),
    ('Latch00', crate+'_latch', (434., 263.), .68, -11.),
]
tag = 'S26_ENDING_FOCUS_20261001'
prefix = 'SD_S26_EndFocus_'


def trace(x,y,ignore):
    result = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x,y,11250),unreal.Vector(x,y,10500),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ignore, unreal.DrawDebugTrace.NONE, True)
    if isinstance(result,tuple) and len(result)==2 and not isinstance(result[0],unreal.HitResult):
        result=result[1] if result[0] else None
    assert result and result.to_tuple()[0], 'Missing streamed collision; no floating placement allowed'
    hit=result.to_tuple()
    return hit[5].z, hit[9]


plans=[]


def norm(v):
    length=math.sqrt(sum(x*x for x in v))
    return tuple(x/length for x in v)


for suffix,path,offset,scale,turn in recipe:
    label=prefix+suffix
    existing=[a for a in loaded if a.get_actor_label()==label]
    assert len(existing)<=1, 'Duplicate owned prop'
    if existing:
        assert tag in [str(t) for t in existing[0].tags], 'Never claim an unowned prop'
    mesh=unreal.load_asset(path)
    assert isinstance(mesh,unreal.StaticMesh),path
    box=mesh.get_bounding_box()
    spin=math.radians(yaw)
    x=origin.x+offset[0]*math.cos(spin)-offset[1]*math.sin(spin)
    y=origin.y+offset[0]*math.sin(spin)+offset[1]*math.cos(spin)
    angle=math.radians(yaw+turn)
    samples=[]
    for lx,ly in ((box.min.x,box.min.y),(box.max.x,box.min.y),(box.min.x,box.max.y),(box.max.x,box.max.y)):
        wx=x+scale*(lx*math.cos(angle)-ly*math.sin(angle))
        wy=y+scale*(lx*math.sin(angle)+ly*math.cos(angle))
        z,owner=trace(wx,wy,[shell]+existing)
        assert owner is not None and owner != shell, 'Props must stand on current ground/footing'
        owner_label=owner.get_actor_label()
        assert not any(word in owner_label for word in ('Transmitter','Biofuel','Fence','Gate','Crate','Lid','Latch')), 'Never stack dressing on a protected device, fence, gate or another prop'
        samples.append(z)
    # Fit the measured local slope, retaining the prop's intended facing.
    # Flat-box pivot snapping would leave the downhill corners floating.
    dx=max(.01,(box.max.x-box.min.x)*scale)
    dy=max(.01,(box.max.y-box.min.y)*scale)
    sx=((samples[1]+samples[3])-(samples[0]+samples[2]))/(2*dx)
    sy=((samples[2]+samples[3])-(samples[0]+samples[1]))/(2*dy)
    a=sx*math.cos(angle)-sy*math.sin(angle)
    b=sx*math.sin(angle)+sy*math.cos(angle)
    n=norm((-a,-b,1.))
    print('STATION_SLOPE',label,round(math.degrees(math.acos(n[2])),3),samples)
    heading=(math.cos(angle),math.sin(angle),0.)
    dot=sum(heading[i]*n[i] for i in range(3))
    forward=norm(tuple(heading[i]-dot*n[i] for i in range(3)))
    side=(n[1]*forward[2]-n[2]*forward[1],n[2]*forward[0]-n[0]*forward[2],n[0]*forward[1]-n[1]*forward[0])
    rotation=unreal.MathLibrary.make_rot_from_zx(unreal.Vector(*n),unreal.Vector(*forward))
    support=[]
    for lx,ly in ((box.min.x,box.min.y),(box.max.x,box.min.y),(box.min.x,box.max.y),(box.max.x,box.max.y)):
        offset3=tuple(scale*(forward[i]*lx+side[i]*ly+n[i]*box.min.z) for i in range(3))
        ground,owner=trace(x+offset3[0],y+offset3[1],[shell]+existing)
        assert owner is not None and not any(word in owner.get_actor_label() for word in ('Transmitter','Biofuel','Fence','Gate','Crate','Lid','Latch'))
        support.append(ground-offset3[2])
    z=max(support)
    plans.append(dict(label=label,mesh=mesh,position=unreal.Vector(x,y,z),rotation=rotation,scale=scale,
        existing=existing[0] if existing else None,support_cm=samples,corner_clearance_cm=[z-h for h in support]))


print('STATION_PLANS',json.dumps([{'label':p['label'],'clearance':p['corner_clearance_cm'],'support':p['support_cm']} for p in plans],separators=(',',':')))
