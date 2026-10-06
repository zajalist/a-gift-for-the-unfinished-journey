"""Polish pass on the placed First Light marks (after place_first_light_marks.py place + save).

The author's review of the first placement (screenshots Saved/Screenshots/FirstLight/*.png):
  * wrecks read as a carrier in its driving pose -> tilted (road flank up), sunk 12-28 cm, dusty tint (MI children of the
    carrier's own MIs, no new material), no longer level;
  * the number decals did not show on the skinned husk -> a mesh decal (Plane with the same MI_FL_Stencil_NN, whose
    parent M_MS_Decal is a deferred decal) attached to the road flank, found by a sideways trace against the husk;
  * the grate dust (EasyAtmos hanging dust, a camera-volume effect) was invisible in storm light -> EasyAtmos' Smoke preset
    rising out of the plate (a fire-smoke Niagara was tried: it carries flames);
  * the depot mouth stood as a free arch on flat ground -> cliff masses left, right and over the arch, their faces
    flush with its front, so the arch reads as a mouth cut into rock; boulders at the feet.

Runs through Hayba python_run, one mark per call, never saves in an edit call. WP cells round a mark must be loaded
(place_first_light_marks.py load <id>) and the FL_ actors loaded (step `load-marks`).

    python Tools/World/polish_first_light_marks.py load-marks
    python Tools/World/polish_first_light_marks.py wreck WRECK_01 [...]
    python Tools/World/polish_first_light_marks.py grate G0 [...]
    python Tools/World/polish_first_light_marks.py mouth
    python Tools/World/polish_first_light_marks.py save
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import place_setdress as psd  # noqa: E402

MARKS = os.path.join(HERE, 'first_light_marks.json')
FL = '/Game/SaskartaGaea/Story/FirstLight/'
CARRIER_MI = '/Game/SaskartaGaea/Characters/Carrier/Materials/'
PLUME = '/Game/EasyAtmos/System/Presets/EasyAtmos_Smoke.EasyAtmos_Smoke'
DUST_BP = '/Game/EasyAtmos/Blueprints/BP_EasyAtmos.BP_EasyAtmos'
CLIFF = '/Game/Pallbearer/PolyHaven/namaqualand_cliff_02/namaqualand_cliff_02_2k/StaticMeshes/namaqualand_cliff_02_2k'
BOULDER = '/Game/Light_Foliage/Meshes/SM_Rock_05'
PLANE = '/Engine/BasicShapes/Plane.Plane'
FULL = '/Game/SaskartaGaea/Characters/Carrier/Full/SK_CarrierFull'
POSE = '/Game/SaskartaGaea/Characters/Carrier/Full/A_CarrierFull_OpenHatch'
NUM = [float(v) for v in os.environ.get('FL_NUM', '-90,84,90').split(',')]  # carrier frame: forward, out, up (cm)

BODY_LOAD_MARKS = r'''
L = unreal.WorldPartitionBlueprintLibrary
g = [d.guid for d in L.get_actor_descs() if str(d.label).startswith('FL_')]
L.load_actors(g)
print('LOADED_MARKS %d' % len(g))
'''

BODY_WRECK = r'''
it = ITEM
lbl = 'FL_' + it['id']
husk = None
for a in eas.get_all_level_actors():
    l = a.get_actor_label()
    if l == lbl + '_husk':
        husk = a
    elif l in (lbl + '_stencil', lbl + '_number'):
        eas.destroy_actor(a)
if husk is None:
    print('NO_HUSK ' + it['id'])
else:
    ML = unreal.MathLibrary
    x, y = it['loc_cm'][0], it['loc_cm'][1]
    yaw = it['yaw']
    side = 1.0 if it['lateral_m'] < 0 else -1.0   # +1: the road is on the carrier's right
    c0, s0 = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    # the carrier frame (X forward, Y right): the full carrier is 4.7 m long, 1.6 m wide
    zs = []
    for (ex, ey) in ((0.0, 0.0), (200.0, 75.0), (200.0, -75.0), (-200.0, 75.0), (-200.0, -75.0)):
        g = trace_ground(x + ex * c0 - ey * s0, y + ex * s0 + ey * c0, it['loc_cm'][2] + 3000.0, it['loc_cm'][2] - 3000.0, [husk])
        zs.append(g[0] if g is not None else it['loc_cm'][2])
    tp = math.degrees(math.atan2(((zs[1] + zs[2]) - (zs[3] + zs[4])) * 0.5, 400.0))
    tr = -math.degrees(math.atan2(((zs[1] + zs[3]) - (zs[2] + zs[4])) * 0.5, 150.0))
    sink = max(12.0, min(28.0, it['sink_cm'] if it['sink_cm'] > 0 else 14.0))
    roll = 14.0 * side
    pitch = tp - 3.0
    rc = unreal.Rotator(tr + roll, pitch, yaw)
    if ML.get_right_vector(rc).z * side < 0:
        roll = -roll
        rc = unreal.Rotator(tr + roll, pitch, yaw)
    f = ML.get_forward_vector(rc)
    r = ML.get_right_vector(rc)
    u = ML.get_up_vector(rc)
    # the wheels hang ~30 cm below the mesh floor in the pose: sink is measured from the wheel bottoms
    cz = sum(zs[1:]) / 4.0 - sink - WHEEL_CM
    # SK_CarrierFull (the BP turns it -90): the mesh origin is 156 cm ahead of the body centre; the bulk (cabin) is behind the centre, the tow tongue ahead
    husk.skeletal_mesh_component.set_skeletal_mesh_asset(eal.load_asset(FULL))
    husk.set_actor_rotation(ML.compose_rotators(unreal.Rotator(0.0, 0.0, -90.0), rc), False)
    husk.set_actor_location(V(x + f.x * 156.0, y + f.y * 156.0, cz + f.z * 156.0), False, False)
    comp = husk.skeletal_mesh_component
    for k in range(6):
        comp.set_material(k, None)   # the mesh's own materials (no dust MI: its FBX materials have no tint to use)
    anim = eal.load_asset(POSE)
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    comp.override_animation_data(anim, False, False, anim.get_play_length(), 0.0)
    # the number: a mesh decal on the road flank, front half, above the wheels
    nx, ny, nz = r.x * side, r.y * side, r.z * side
    o = V(x + f.x * NUM[0] + nx * NUM[1] + u.x * NUM[2], y + f.y * NUM[0] + ny * NUM[1] + u.y * NUM[2],
          cz + f.z * NUM[0] + nz * NUM[1] + u.z * NUM[2])
    p = eas.spawn_actor_from_object(eal.load_asset(PLANE), o, ML.make_rot_from_zx(V(nx, ny, nz), V(f.x * side, f.y * side, f.z * side)))
    p.set_actor_label(lbl + '_number')
    p.set_folder_path('Set/FirstLight/' + it['id'])
    p.tags = [unreal.Name('FL_MARK'), unreal.Name(it['id'])]
    p.set_actor_scale3d(V(0.55, 0.55, 1.0))
    sm = p.static_mesh_component
    sm.set_material(0, eal.load_asset(FL + 'MI_FL_Stencil_' + it['stencil']))
    sm.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    sm.set_editor_property('cast_shadow', False)
    sm.set_editor_property('ld_max_draw_distance', 6000.0)
    p.attach_to_actor(husk, '', unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                      unreal.AttachmentRule.KEEP_WORLD, False)
    gaps = []
    for (ex, ey) in ((200.0, 75.0), (200.0, -75.0), (-200.0, 75.0), (-200.0, -75.0)):
        wx = x + f.x * ex + r.x * ey
        wy = y + f.y * ex + r.y * ey
        g = trace_ground(wx, wy, cz + 2000.0, cz - 2000.0, [husk, p])
        if g is not None:
            gaps.append(cz + f.z * ex + r.z * ey - g[0])
    drop = max(gaps) + 5.0 if gaps and max(gaps) > -5.0 else 0.0
    if drop > 0.0:
        # a corner over a dip: lower the whole husk (the number rides with it) until every corner is in the ground
        hl = husk.get_actor_location()
        husk.set_actor_location(V(hl.x, hl.y, hl.z - drop), False, False)
        gaps = [v - drop for v in gaps]
    print('WRECK %s terrain p=%.0f r=%.0f  husk roll=%.0f pitch=%.0f sink=%.0f  corner base-ground=%s' % (
        it['id'], tp, tr, tr + roll, pitch, sink, ','.join('%+.0f' % v for v in gaps)))
'''

BODY_GRATE = r'''
it = ITEM
lbl = 'FL_' + it['id']
plate = None
for a in eas.get_all_level_actors():
    l = a.get_actor_label()
    if l == lbl + '_plate':
        plate = a
    elif l in (lbl + '_breath', lbl + '_plume'):
        eas.destroy_actor(a)
if plate is None:
    print('NO_PLATE ' + it['id'])
else:
    q = plate.get_actor_location()
    # BP_EasyAtmos draws its Preset in the construction script: the Smoke preset (set_editor_property reruns it), NOT warmed up: advance_simulation on it crashed the editor's RHI thread (NiagaraGpuComputeDispatch, 9/29)
    na = eas.spawn_actor_from_object(eal.load_asset(DUST_BP), V(q.x, q.y, q.z + 10.0), unreal.Rotator(0.0, 0.0, 0.0))
    na.set_actor_label(lbl + '_plume')
    na.set_folder_path('Set/FirstLight/' + it['id'])
    na.tags = [unreal.Name('FL_MARK'), unreal.Name(it['id'])]
    na.set_editor_property('Preset', eal.load_asset(PLUME))
    for nc in na.get_components_by_class(unreal.NiagaraComponent):
        nc.set_editor_property('ld_max_draw_distance', 5000.0)
    print('GRATE %s plume at %.0f %.0f %.0f' % (it['id'], q.x, q.y, q.z))
'''

BODY_MOUTH = r'''
it = ITEM
lbl = 'FL_' + it['id']
arch = None
for a in eas.get_all_level_actors():
    l = a.get_actor_label()
    if l == lbl + '_arch':
        arch = a
    elif l.startswith(lbl + '_rock'):
        eas.destroy_actor(a)
yaw = it['yaw']
cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
ax = arch.get_actor_location()
out = []
def ground_min(x, y, hx, hy, ry):
    c, s = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    zs = []
    for (ex, ey) in ((0.0, 0.0), (hx, hy), (hx, -hy), (-hx, hy), (-hx, -hy)):
        g = trace_ground(x + ex * c - ey * s, y + ex * s + ey * c, ax.z + 5000.0, ax.z - 5000.0, [])
        if g is not None:
            zs.append(g[0])
    return min(zs) if zs else ax.z - 300.0
def put(path, name, dx, dy, bottom, scale, yaw_add, fit=True):
    m = eal.load_asset(path)
    b = m.get_bounds()
    o, e = b.origin, b.box_extent
    ry = yaw + yaw_add
    c, s = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    wx = ax.x + dx * cy - dy * sy
    wy = ax.y + dx * sy + dy * cy
    if bottom is None:
        bottom = ground_min(wx, wy, e.x * scale[0] * 0.8, e.y * scale[1] * 0.8, ry) - 60.0
    ox, oy = o.x * scale[0], o.y * scale[1]
    px = wx - (ox * c - oy * s)
    py = wy - (ox * s + oy * c)
    pz = bottom - (o.z - e.z) * scale[2]
    a = eas.spawn_actor_from_object(m, V(px, py, pz), unreal.Rotator(0.0, 0.0, ry))
    a.set_actor_scale3d(V(scale[0], scale[1], scale[2]))
    a.set_actor_label(lbl + '_' + name)
    a.set_folder_path('Set/FirstLight/' + it['id'])
    a.tags = [unreal.Name('FL_MARK'), unreal.Name(it['id'])]
    a.static_mesh_component.set_editor_property('ld_max_draw_distance', 20000.0)
    out.append('%s z=%.0f' % (name, pz))
    return a
# the arch spans dy -395..+395 (x scale 1.6), top at +520; its front face at dx ~ +74. The cliff's local Y is its depth:
# yaw_add 90 turns local X across the mouth and local +Y into the mountain; the faces sit flush with the arch front.
ce = eal.load_asset(CLIFF).get_bounds().box_extent
sxs, sys_, szs = 0.8, 1.4, 1.5
w = ce.x * 2.0 * sxs
d = ce.y * 2.0 * sys_
dx = 60.0 - d * 0.5
top = ax.z + 163.0 * 1.6 - 60.0
put(CLIFF, 'rock_l', dx, -(395.0 + w * 0.5 - 120.0), None, (sxs, sys_, szs), 90.0 + FLIP)
put(CLIFF, 'rock_r', dx, (395.0 + w * 0.5 - 120.0), None, (sxs, sys_, szs), 90.0 + FLIP)
put(CLIFF, 'rock_top', dx - 40.0, 0.0, top, (0.55, sys_, 0.9), 90.0 + FLIP)
be = eal.load_asset(BOULDER).get_bounds().box_extent
for k, (bx, by, sc) in enumerate(((220.0, -560.0, 1.6), (180.0, 600.0, 1.4), (260.0, -900.0, 1.1), (240.0, 880.0, 1.2))):
    put(BOULDER, 'rock_b%d' % k, bx, by, None, (sc, sc, sc), 37.0 * k)
print('MOUTH ' + ' | '.join(out))
'''

BODY_SAVE = r'''
U = unreal.EditorLoadingAndSavingUtils
dirty = list(U.get_dirty_content_packages()) + list(U.get_dirty_map_packages())
mine = [p for p in dirty if '__ExternalActors__/level/Saskarta_WP/' in p.get_name() or p.get_name().startswith(FL)]
chunk = mine[:20]
ok = U.save_packages(chunk, True) if chunk else True
rest = [p.get_name() for p in dirty if p not in chunk]
print('SAVED %d of %d ok=%s other_dirty=%s' % (len(chunk), len(mine), ok, ','.join(rest[:10])))
'''


def items(ids):
    doc = json.load(open(MARKS, encoding='utf-8'))
    return [i for i in doc['items'] if i['id'] in ids]


def send(body, **data):
    h = psd.Hayba(int(os.environ.get('HAYBA_PORT', 52342)))
    h.connect()
    r = h.run(psd.validate(psd.build_script(body, FL=FL, CARRIER_MI=CARRIER_MI, PLUME=PLUME, DUST_BP=DUST_BP, CLIFF=CLIFF,
                                            BOULDER=BOULDER, PLANE=PLANE, FULL=FULL, POSE=POSE, NUM=NUM, WHEEL_CM=30.0, **data)))
    r = r.get('result', r)
    d = r.get('data', {}) if isinstance(r, dict) else {}
    print((d.get('stdout', '') + d.get('stderr', '')).strip() or json.dumps(r, ensure_ascii=False)[:1500])


def main(argv):
    if psd.pie_running():
        raise SystemExit('PIE is running: not sending anything')
    step, rest = argv[0], argv[1:]
    if step == 'load-marks':
        send(BODY_LOAD_MARKS)
    elif step in ('wreck', 'grate'):
        for it in items(rest):
            send(BODY_WRECK if step == 'wreck' else BODY_GRATE, ITEM=it)
    elif step == 'mouth':
        send(BODY_MOUTH, ITEM=items(['DEPOT_MOUTH'])[0], FLIP=float(os.environ.get('FL_CLIFF_FLIP', 0)))
    elif step == 'save':
        send(BODY_SAVE)
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
