"""Place, settle, check and capture the Saskarta set dressing in the live editor, one site at a time.

Runs in plain CPython on the host. Each step builds a small, self-contained editor script (the
site's data embedded as literals, because python_run scripts may not open files) and sends it
to Hayba's python_run over the raw TCP port, in batches that stay inside the 5 s cooperative
deadline. It never saves, loads or unloads in the same call as an edit (WP pinning, see the
wp-scripted-load-save-unload memory note), and it never touches the user's viewport.

    python Tools/World/place_setdress.py list                              # the sites, in lane order
    python Tools/World/place_setdress.py probe                            # read-only API probe (run once first)
    python Tools/World/place_setdress.py <step> <SITE> --owner LANE_SD    # one step for one site

Steps, in the per-site loop (each is its own set of python_run calls):
    load      load the landscape proxies (and static actors) under the site + its camera views (<= 20)
    survey    list what already stands in the site radius (story-owned sets, earlier passes); read-only
    place     spawn the placements (folders Set/<Site>/<group>, tags, scale, cull, collision); ISM
              groups are added with their per-instance trace settle
    settle    ground settle: 'trace' (4-corner traces, plane fit, clamped tilt, z rule, sink) and
              'physics' (emulated drop: random-tilt candidates traced against the ground and the
              props already settled, lowest stable pose); attach items copy their parent
    check     road-core clearance, interpenetration, floating/buried corners; read-only report
    capture   4-5 viewpoints through temporary SceneCapture2D actors -> Saved/Screenshots/SetDress/<site>/
    save      save the site's actor packages, 20 per call
    unload    unload (and unpin) what 'load' loaded
    replace   destroy and re-place + settle the given ids (after editing the JSON in the fix pass)
    clear     destroy every actor of the site (needs --yes), then 'save' to write the deletions
    status    count the site's actors in the editor; read-only
    watch     per-second watchdog over saskartarad.log (no editor call): exits 2 the second PIE starts,
              3 on a native fault or fatal line; run it beside every mutating batch

Options: --dry-run (build and validate the scripts, write them to Saved/SetDress/scripts, send
nothing), --approve key,key (Batch01 'check' assets the lane has looked at and kept; the list is
also read from Tools/World/setdress_approvals.json), --with-optional (the optional FX),
--no-ism (individual actors instead of ISM groups), --skip-story (leave out the
placements that stand in for a story-owned set the survey found), --data-layer /Game/..DL asset (only if it exists),
--port (HAYBA_PORT, default 52342), --owner (the editor-gate owner; required for mutating steps).

Hayba python_run limits honoured here (see the hayba-python-quirks memory): 5 s deadline, and the
scripts contain none of: try, getattr, open(, .replace(, new_level(. They never construct
unreal.Guid and never rebuild mesh geometry. validate() enforces that before anything is sent.
"""
import argparse
import ast
import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SITES_JSON = os.path.join(HERE, 'setdress_sites.json')
SITES_V2_JSON = os.path.join(HERE, 'setdress_v2_sites.json')
MATERIAL_MAP_JSON = os.path.join(HERE, 'setdress_material_map.json')
LOG_PATH = os.path.join(ROOT, 'Saved', 'Logs', 'saskartarad.log')
GROUND_MI = '/Game/SaskartaGaea/Environment/SetDress/Ground/MI_SD_Ground_'
# material sets -> CPD 4..7: dust amount, tint r, g, b (the site palette; per-instance variation is in the shader)
MATERIAL_SETS = {'stone': [0.45, 0.96, 0.92, 0.88], 'wood': [0.3, 0.9, 0.86, 0.82], 'cloth': [0.25, 0.95, 0.9, 0.85]}
APPROVALS_JSON = os.path.join(HERE, 'setdress_approvals.json')
CAPTURE_SETTLE_S = 5.0
STATE_DIR = os.path.join(ROOT, 'Saved', 'SetDress', 'state')
SCRIPT_DIR = os.path.join(ROOT, 'Saved', 'SetDress', 'scripts')
SHOT_DIR_REL = 'Screenshots/SetDress'          # under Saved/
BANNED = ('try', 'getattr', 'open(', '.replace(', 'new_level(', 'unreal.Guid(', 'build_from_static_mesh_descriptions')
MUTATING = {'load', 'place', 'settle', 'capture', 'save', 'unload', 'replace', 'clear', 'ground', 'material'}
CLEAR_M = 5.0

BATCH = {'place': int(os.environ.get('SD_PLACE_BATCH', 15)), 'settle': int(os.environ.get('SD_SETTLE_BATCH', 8)), 'ism': int(os.environ.get('SD_ISM_BATCH', 60)), 'save': int(os.environ.get('SD_SAVE_BATCH', 20)), 'check': 60}
ISM_CHECK_BATCH = 12  # five landscape samples per instance; keep each editor call below its deadline
MAX_LANDSCAPE_PROXIES = 20

# ------------------------------------------------------------------------------------------------
# Editor-side source. MATH_SRC is pure Python (the tests exec it without Unreal).
# ------------------------------------------------------------------------------------------------

MATH_SRC = r'''
import math
import random


def axes(yaw, pitch, roll):
    """UE FRotationMatrix axes (X forward, Y right, Z up) for a rotator in degrees."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    X = (cp * cy, cp * sy, sp)
    Y = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    Z = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
    return X, Y, Z


def apply(ax, p):
    X, Y, Z = ax
    return (p[0] * X[0] + p[1] * Y[0] + p[2] * Z[0],
            p[0] * X[1] + p[1] * Y[1] + p[2] * Z[1],
            p[0] * X[2] + p[1] * Y[2] + p[2] * Z[2])


def contact_samples(origin, extent, scale, rotation, location, fraction=1.0):
    """World-space 3x3 points on an actor-local bounds bottom, corners first by row."""
    ax = axes(*rotation)
    z0 = (origin[2] - extent[2]) * scale
    pts = []
    for fx in (-fraction, 0.0, fraction):
        for fy in (-fraction, 0.0, fraction):
            q = apply(ax, ((origin[0] + fx * extent[0]) * scale,
                           (origin[1] + fy * extent[1]) * scale, z0))
            pts.append((location[0] + q[0], location[1] + q[1], location[2] + q[2]))
    return pts


def ground_only_contact(item):
    """Whether placement and readback require support from landscape, not nearby props."""
    contact = item.get('contact')
    return (contact in ('rigid', 'lie', 'channel') or bool(item.get('unit')) or
            (contact == 'rest' and not item.get('stack')))


def support_kind_allowed(item, kind):
    """HLOD proxies never support; stacks may use actual actors and ISM hosts."""
    if kind == 'hlod':
        return False
    if ground_only_contact(item):
        return kind == 'landscape'
    return kind in ('landscape', 'actor', 'ism')


def is_hlod_class(class_name):
    """Recognize World Partition HLOD collision proxies by their native class name."""
    return 'HLOD' in str(class_name)


def plane_normal(pts):
    """Least-squares plane z = a + b x + c y through (x, y, z) points; returns the unit normal."""
    n = float(len(pts))
    if n < 3:
        return (0.0, 0.0, 1.0)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    mz = sum(p[2] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    sxz = sum((p[0] - mx) * (p[2] - mz) for p in pts)
    syz = sum((p[1] - my) * (p[2] - mz) for p in pts)
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-6:
        return (0.0, 0.0, 1.0)
    b = (sxz * syy - syz * sxy) / det
    c = (syz * sxx - sxz * sxy) / det
    L = math.sqrt(b * b + c * c + 1.0)
    return (-b / L, -c / L, 1.0 / L)


def clamp_normal(n, max_tilt_deg):
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, n[2]))))
    if tilt <= max_tilt_deg or tilt < 1e-6:
        return n
    h = math.sqrt(n[0] * n[0] + n[1] * n[1])
    k = math.sin(math.radians(max_tilt_deg)) / h
    return (n[0] * k, n[1] * k, math.cos(math.radians(max_tilt_deg)))


def align_angles(n, yaw):
    """Pitch and roll (deg) that tilt an object with this yaw so its Z axis follows normal n."""
    fx, fy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    rx, ry = -fy, fx
    nf = n[0] * fx + n[1] * fy
    nr = n[0] * rx + n[1] * ry
    return math.degrees(math.atan2(-nf, n[2])), math.degrees(math.atan2(nr, n[2]))


def settle_pose(cx, cy, centre_local, bottom_local, yaw, pitch0, roll0, cfg, trace, rng):
    """Find a resting pose for one object.

    cx, cy: where the BOUNDS CENTRE must stay (cm). centre_local: the bounds centre relative to the
    pivot, in local scaled cm. bottom_local: local scaled 3x3 grid across the bottom footprint.
    cfg: mode ('trace' | 'physics'), sink, max_tilt, rand_tilt, z_rule, candidates,
    require_complete_support (reject a candidate if any footprint trace misses).
    trace(x, y) -> (ground_z, normal) or None: the first blocking hit straight down.
    Returns (loc_x, loc_y, loc_z, yaw, pitch, roll, info) or None when nothing was hit.
    """
    upright = abs(pitch0) + abs(roll0) < 1.0
    cands = []
    # candidate 0: follow the ground under a yaw-only footprint
    ax0 = axes(yaw, pitch0, roll0)
    ground_pts = []
    for p in bottom_local[:4]:
        q = apply(ax0, (p[0] - centre_local[0], p[1] - centre_local[1], 0.0))
        h = trace(cx + q[0], cy + q[1])
        if h is not None:
            ground_pts.append((cx + q[0], cy + q[1], h[0]))
    if len(ground_pts) >= 3 and upright:
        n = clamp_normal(plane_normal(ground_pts), cfg['max_tilt'])
        p_, r_ = align_angles(n, yaw)
        cands.append((yaw, p_, r_))
    else:
        cands.append((yaw, pitch0, roll0))
    if cfg['mode'] == 'physics' or cfg['rand_tilt'] > 0:
        extra = cfg.get('candidates', 7) if cfg['mode'] == 'physics' else 1
        for i in range(extra):
            t = cfg['rand_tilt']
            b = cands[0]
            cands.append((b[0] + rng.uniform(-t, t) * 0.5, b[1] + rng.uniform(-t, t), b[2] + rng.uniform(-t, t)))
        if cfg['mode'] != 'physics':
            cands = cands[1:]
    best = None
    sink = cfg['sink']
    for (yw, pt, rl) in cands:
        ax = axes(yw, pt, rl)
        oc = apply(ax, centre_local)
        lx, ly = cx - oc[0], cy - oc[1]
        req, gz, dzs = [], [], []
        for p in bottom_local:
            d = apply(ax, p)
            h = trace(lx + d[0], ly + d[1])
            if h is None:
                continue
            req.append(h[0] - d[2])
            gz.append(h[0])
            dzs.append(d[2])
        if len(req) < 3 or (cfg.get('require_complete_support', False) and len(req) != len(bottom_local)):
            continue
        rule = cfg['z_rule'] if cfg['mode'] != 'physics' else 'max'
        if rule == 'min':
            z = min(req)
        elif rule == 'max':
            z = max(req)
        else:
            z = sum(req) / len(req)
        z -= sink
        gaps = [z + dzs[i] - gz[i] for i in range(len(req))]
        contacts = sum(1 for g in gaps if g <= 3.0 - sink + 0.01)
        com = z + oc[2]
        score = sum(max(0.0, g) for g in gaps) / len(gaps) + 0.2 * (com - min(gz))
        if cfg['mode'] == 'physics' and contacts < 3:
            score += 5.0 * max(gaps)
        if best is None or score < best[0]:
            best = (score, lx, ly, z, yw, pt, rl, contacts, max(gaps), min(gaps))
    if best is None:
        return None
    s, lx, ly, z, yw, pt, rl, contacts, gmax, gmin = best
    return (lx, ly, z, yw, pt, rl, dict(score=round(s, 2), contacts=contacts,
                                         gap_max=round(gmax, 1), gap_min=round(gmin, 1)))
'''

MESH_BOUNDS_SRC = r'''
def aggregate_mesh_component_bounds(actor_transform, components, transform_point, inverse_actor_point, is_instanced):
    """Aggregate actual mesh bounds in actor-local space, including every ISM/HISM instance.

    transform_point(transform, point) and inverse_actor_point(actor_transform, world_point) operate on
    three-tuples. Returns (center, extent) in unscaled actor-local units, or None if no mesh bounds exist.
    """
    lo = [float('inf'), float('inf'), float('inf')]
    hi = [float('-inf'), float('-inf'), float('-inf')]
    found = False
    for comp in components:
        mesh = comp.static_mesh
        if mesh is None:
            continue
        bounds = mesh.get_bounds()
        origin, extent = bounds.origin, bounds.box_extent
        if is_instanced(comp):
            instance_count = comp.get_instance_count()
            transforms = (comp.get_instance_transform(i, True) for i in range(instance_count))
        else:
            transforms = (comp.get_world_transform(),)
        for instance_transform in transforms:
            for sx in (-1.0, 1.0):
                for sy in (-1.0, 1.0):
                    for sz in (-1.0, 1.0):
                        local_mesh_point = (origin.x + sx * extent.x,
                                            origin.y + sy * extent.y,
                                            origin.z + sz * extent.z)
                        world_point = transform_point(instance_transform, local_mesh_point)
                        actor_point = inverse_actor_point(actor_transform, world_point)
                        for axis in range(3):
                            lo[axis] = min(lo[axis], actor_point[axis])
                            hi[axis] = max(hi[axis], actor_point[axis])
                        found = True
    if not found:
        return None
    center = tuple((lo[i] + hi[i]) * 0.5 for i in range(3))
    extent = tuple((hi[i] - lo[i]) * 0.5 for i in range(3))
    return center, extent
'''
exec(MESH_BOUNDS_SRC, globals())

TRACE_SUPPORT_SRC = r'''
def trace_support(x, y, ztop, zbot, ignore, item):
    """Measure only the support allowed by the same policy used when the actor is settled."""
    if ground_only_contact(item):
        return trace_ground(x, y, ztop, zbot, ignore)
    ign = list(ignore)
    for _ in range(8):
        h = trace_down(x, y, ztop, zbot, ign)
        if h is None:
            return None
        actor = h[2]
        if is_land(actor):
            kind = 'landscape'
        elif is_hlod_class(actor.get_class().get_name()):
            kind = 'hlod'
        elif 'SD_ism' in [str(t) for t in actor.tags]:
            kind = 'ism'
        else:
            kind = 'actor'
        if support_kind_allowed(item, kind):
            return h
        ign.append(actor)
    return None
'''
exec(TRACE_SUPPORT_SRC, globals())

EDITOR_HEAD = r'''
import unreal
''' + MATH_SRC + MESH_BOUNDS_SRC + r'''
IMPACT_POINT = 5
IMPACT_NORMAL = 7
HIT_ACTOR = 9
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
eal = unreal.EditorAssetLibrary
syslib = unreal.SystemLibrary
rng = random.Random(SEED)


def V(x, y, z):
    return unreal.Vector(float(x), float(y), float(z))


def hit_of(r):
    if r is None:
        return None
    if isinstance(r, tuple):
        if len(r) == 2 and not isinstance(r[0], unreal.HitResult):
            return r[1] if r[0] else None
    return r


def trace_down(x, y, ztop, zbot, ignore):
    h = hit_of(syslib.line_trace_single(world, V(x, y, ztop), V(x, y, zbot),
                                        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ignore,
                                        unreal.DrawDebugTrace.NONE, True))
    if h is None:
        return None
    t = h.to_tuple()
    if not t[0]:
        return None
    p = t[IMPACT_POINT]
    n = t[IMPACT_NORMAL]
    return (p.z, (n.x, n.y, n.z), t[HIT_ACTOR])


def is_land(act):
    return act is not None and 'Landscape' in act.get_class().get_name()


def trace_ground(x, y, ztop, zbot, ignore):
    """The first LANDSCAPE hit straight down (other actors are passed through): walls never stand on rubble,
    and a unit's feet never stand on a wall top (V2). Returns (z, normal, first_hit_kind)."""
    ign = list(ignore)
    first = None
    for _ in range(6):
        h = trace_down(x, y, ztop, zbot, ign)
        if h is None:
            return None
        kind = 'landscape' if is_land(h[2]) else h[2].get_actor_label()
        if first is None:
            first = kind
        if kind == 'landscape':
            return (h[0], h[1], first)
        ign.append(h[2])
    return None

''' + TRACE_SUPPORT_SRC + r'''


def site_actors(site):
    out = {}
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, 'SD_' + site):
        out[a.get_actor_label()] = a
    return out


def local_bounds(a, it):
    """(centre_local, bottom_local) in actor-scaled cm, from actual mesh components and instances."""
    bounds = actor_mesh_bounds(a)
    if bounds is None:
        return None
    (ox, oy, oz), (ex, ey, ez) = bounds
    s = a.get_actor_scale3d().x
    c = (ox * s, oy * s, oz * s)
    z0 = (oz - ez) * s
    xs = (ox - ex, ox, ox + ex)
    ys = (oy - ey, oy, oy + ey)
    pts = [(x * s, y * s, z0) for x, y in
           ((xs[0], ys[0]), (xs[2], ys[0]), (xs[2], ys[2]), (xs[0], ys[2]),
            (xs[1], ys[1]), (xs[1], ys[0]), (xs[2], ys[1]), (xs[1], ys[2]), (xs[0], ys[1]))]
    return c, pts


def actor_mesh_bounds(a):
    """Actual static-mesh bounds in actor-local, unscaled units; None means no mesh bounds."""
    actor_transform = a.get_actor_transform()
    components = a.get_components_by_class(unreal.StaticMeshComponent)
    def transform_point(transform, point):
        q = unreal.MathLibrary.transform_location(transform, V(point[0], point[1], point[2]))
        return (q.x, q.y, q.z)
    def inverse_actor_point(transform, point):
        q = unreal.MathLibrary.inverse_transform_location(transform, V(point[0], point[1], point[2]))
        return (q.x, q.y, q.z)
    return aggregate_mesh_component_bounds(
        actor_transform, components, transform_point, inverse_actor_point,
        lambda comp: isinstance(comp, unreal.InstancedStaticMeshComponent))
'''

# ------------------------------------------------------------------------------------------------
# Step bodies. Each is appended to EDITOR_HEAD with its data lines (SITE, ITEMS, ...) prepended.
# ------------------------------------------------------------------------------------------------

PROBE_BODY = r'''
print('PROBE hit tuple: ' + str(len(unreal.HitResult().to_tuple())))
print('PROBE wp lib: ' + str(hasattr(unreal, 'WorldPartitionBlueprintLibrary')))
print('PROBE subobject subsystem: ' + str(hasattr(unreal, 'SubobjectDataSubsystem')))
print('PROBE data layer subsystem: ' + str(hasattr(unreal, 'DataLayerEditorSubsystem')))
print('PROBE world: ' + str(world.get_path_name()))
lib = unreal.WorldPartitionBlueprintLibrary
b = lib.get_editor_world_bounds()
r = lib.get_intersecting_actor_descs(unreal.Box(V(0, 0, -100000), V(1000, 1000, 100000)))
descs = r[1] if isinstance(r, tuple) else r
print('PROBE descs at origin: ' + str(len(descs)))
if len(descs) > 0:
    print('PROBE desc: ' + str(descs[0])[:600])
for k in BATCH01_KEYS:
    print('PROBE asset ' + k + ' ' + str(eal.does_asset_exist(k)))
print('PROBE DONE')
'''

LOAD_BODY = r'''
lib = unreal.WorldPartitionBlueprintLibrary
box = unreal.Box(V(BOX[0], BOX[1], -1000000), V(BOX[2], BOX[3], 1000000))
r = lib.get_intersecting_actor_descs(box)
descs = r[1] if isinstance(r, tuple) else r
want, names, land = [], [], 0
resident = {a.get_editor_property('actor_guid').export_text() for a in eas.get_all_level_actors()}
for d in descs:
    cls = str(d.get_editor_property(CLASS_FIELD))
    is_land = 'Landscape' in cls
    keep = is_land or ('StaticMeshActor' in cls) or ('DecalActor' in cls) or ('Blueprint' in cls and 'PCG' not in cls)
    if not keep or 'HLOD' in cls or 'PCG' in cls or 'WorldDataLayers' in cls:
        continue
    if is_land:
        land += 1
        if land > MAX_LAND:
            continue
    g = d.get_editor_property('guid')
    if g.export_text() in ALREADY and g.export_text() in resident:
        continue
    want.append(g)
    names.append(g.export_text())
    if len(want) >= LIMIT:
        break
if len(want) > 0:
    lib.load_actors(want)
print('LOADED ' + json_list(names))
print('LOAD landscape=' + str(land) + ' this_call=' + str(len(want)) + (' DONE' if len(want) < LIMIT else ' MORE'))
'''

UNLOAD_BODY = r'''
lib = unreal.WorldPartitionBlueprintLibrary
box = unreal.Box(V(BOX[0], BOX[1], -1000000), V(BOX[2], BOX[3], 1000000))
r = lib.get_intersecting_actor_descs(box)
descs = r[1] if isinstance(r, tuple) else r
gs = []
for d in descs:
    g = d.get_editor_property('guid')
    if g.export_text() in WANT:
        gs.append(g)
if len(gs) > 0:
    lib.unload_actors(gs)
    lib.unpin_actors(gs)
print('UNLOAD ' + str(len(gs)) + ' of ' + str(len(WANT)) + ' DONE')
'''

SURVEY_BODY = r'''
n = 0
mine = 0
for a in eas.get_all_level_actors():
    p = a.get_actor_location()
    dx, dy = p.x - CENTRE[0], p.y - CENTRE[1]
    if dx * dx + dy * dy > RADIUS * RADIUS:
        continue
    cls = a.get_class().get_name()
    if 'Landscape' in cls or 'PCG' in cls or 'Instanced' in cls or 'HLOD' in cls:
        continue
    tags = [str(t) for t in a.tags]
    if ('SD_' + SITE) in tags:
        mine += 1
        continue
    n += 1
    if n <= 80:
        print('SURVEY ' + a.get_actor_label() + ' | ' + cls + ' | ' + str(a.get_folder_path()) + ' | ' +
              str(int(p.x)) + ',' + str(int(p.y)) + ',' + str(int(p.z)))
print('SURVEY others=' + str(n) + ' this_site=' + str(mine) + ' DONE')
'''

PLACE_BODY = r'''
have = site_actors(SITE)
made, skipped, fell_back = 0, 0, 0
for it in ITEMS:
    label = 'SD_' + it['id']
    if label in have:
        skipped += 1
        continue
    path = it['asset']
    sc = float(it['scale'])
    if it.get('fallback') and not eal.does_asset_exist(path):
        path = it['fallback']['asset']
        sc = float(it['fallback']['scale'])
        fell_back += 1
    if not eal.does_asset_exist(path):
        print('MISSING ' + it['id'] + ' ' + path)
        continue
    x, y = it['x_cm'], it['y_cm']
    gz = it['ground_z_cm']
    h = trace_down(x, y, gz + 5000, gz - 5000, [])
    if h is not None:
        gz = h[0]
    rot = unreal.Rotator(roll=float(it['roll']), pitch=float(it['pitch']), yaw=float(it['yaw']))
    z0 = gz + it['size_m'][2] * 50.0 + it['settle']['drop_cm'] + it['settle']['z_offset_cm']
    if it['kind'] == 'SM' and '/Blueprints/BPP_' not in path:
        a = eas.spawn_actor_from_object(unreal.load_asset(path), V(x, y, z0), rot)
    elif it['kind'] == 'NS':
        a = eas.spawn_actor_from_class(unreal.NiagaraActor, V(x, y, gz), rot)
        a.get_component_by_class(unreal.NiagaraComponent).set_asset(unreal.load_asset(path))
    else:
        a = eas.spawn_actor_from_class(eal.load_blueprint_class(path), V(x, y, z0), rot)
    if a is None:
        print('SPAWN FAILED ' + it['id'])
        continue
    a.set_actor_scale3d(V(sc, sc, sc))
    if isinstance(a, unreal.StaticMeshActor):
        comp = a.static_mesh_component
        b = comp.static_mesh.get_bounds()
        ax = axes(float(it['yaw']), float(it['pitch']), float(it['roll']))
        oc = apply(ax, (b.origin.x * sc, b.origin.y * sc, b.origin.z * sc))
        a.set_actor_location(V(x - oc[0], y - oc[1], z0 - oc[2]), False, True)
        comp.set_editor_property('ld_max_draw_distance', float(it['draw_distance_cm']))
        comp.set_editor_property('cast_shadow', bool(it['cast_shadow']))
        if not it['collision']:
            comp.set_collision_profile_name('NoCollision')
        if max(it['size_m']) < 0.6:
            comp.set_editor_property('affect_distance_field_lighting', False)
    else:
        o, e = a.get_actor_bounds(False)
        loc = a.get_actor_location()
        a.set_actor_location(V(loc.x + (x - o.x), loc.y + (y - o.y), loc.z), False, True)
    tags = ['SetDress', 'SD_' + SITE, 'SDID_' + it['id'], 'SDMODE_' + it['settle']['mode']]
    if it.get('contact'):
        tags.append('SDC_' + it['contact'])
    if it.get('block'):
        tags.append('SDB_' + it['block'])
    if it.get('contact') == 'rigid' and isinstance(a, unreal.StaticMeshActor):
        # the ground decals must not smear up the wall faces (the material's ground blend does the wall base)
        a.static_mesh_component.set_editor_property('receives_decals', False)
    if it['foliage_exclude']:
        tags.append('PB_FoliageExclude')
    if it['stack'] or it['attach']:
        tags.append('SD_soft')
    a.set_editor_property('tags', [unreal.Name(t) for t in tags])
    a.set_actor_label(label)
    a.set_folder_path(it['folder'])
    made += 1
print('PLACE made=' + str(made) + ' skipped=' + str(skipped) + ' fallback=' + str(fell_back) + ' DONE')
'''

ISM_BODY = r'''
have = site_actors(SITE)
label = 'SD_' + GROUP_ID
if label in have:
    print('ISM exists ' + label + ' DONE')
else:
    path = ASSET
    if len(FALLBACK) > 0 and not eal.does_asset_exist(path):
        path = FALLBACK
    mesh = unreal.load_asset(path)
    host = eas.spawn_actor_from_class(unreal.StaticMeshActor, V(ITEMS[0]['x_cm'], ITEMS[0]['y_cm'], ITEMS[0]['ground_z_cm']), unreal.Rotator())
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    hs = sds.k2_gather_subobject_data_for_instance(host)
    root = hs[1] if len(hs) > 1 else hs[0]
    res = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root, new_class=unreal.InstancedStaticMeshComponent))
    handle = res[0] if isinstance(res, tuple) else res
    comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle))
    comp.set_static_mesh(mesh)
    if len(MAT) > 0 and eal.does_asset_exist(MAT):
        comp.set_material(0, unreal.load_asset(MAT))
    b = mesh.get_bounds()
    added = 0
    for it in ITEMS:
        sc = float(it['scale'])
        if path != ASSET:
            sc = float(it['fallback']['scale'])
        o, e = b.origin, b.box_extent
        c = (o.x * sc, o.y * sc, o.z * sc)
        z0 = (o.z - e.z) * sc
        pts = [((o.x + sx * e.x) * sc, (o.y + sy * e.y) * sc, z0) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        pts.append((c[0], c[1], z0))
        gz = it['ground_z_cm']

        def tr(x, y):
            # ISM scatter always rests on current Landscape. Legacy first-hit
            # placement could settle shrub roots onto a stale merged HLOD.
            h = trace_ground(x, y, gz + 3000, gz - 3000, [host])
            return None if h is None else (h[0], h[1])
        cfg = dict(mode='trace', sink=it['settle']['sink_cm'], max_tilt=it['settle']['max_tilt_deg'],
                   rand_tilt=it['settle']['rand_tilt_deg'], z_rule=it['settle']['z_rule'],
                   require_complete_support=True)
        pose = settle_pose(it['x_cm'], it['y_cm'], c, pts, float(it['yaw']), float(it['pitch']), float(it['roll']), cfg, tr, rng)
        if pose is None:
            print('ISM no ground ' + it['id'])
            continue
        lx, ly, lz, yw, pt, rl, info = pose
        t = unreal.Transform(V(lx, ly, lz), unreal.Rotator(roll=rl, pitch=pt, yaw=yw), V(sc, sc, sc))
        comp.add_instance(t, True)
        added += 1
    comp.set_editor_property('instance_end_cull_distance', int(ITEMS[0]['draw_distance_cm']))
    comp.set_editor_property('instance_start_cull_distance', int(ITEMS[0]['draw_distance_cm'] * 0.8))
    comp.set_editor_property('visible_in_ray_tracing', False)
    comp.set_editor_property('affect_distance_field_lighting', False)
    if not ITEMS[0]['collision']:
        comp.set_collision_profile_name('NoCollision')
    host.set_editor_property('tags', [unreal.Name(t) for t in ['SetDress', 'SD_' + SITE, 'SDID_' + GROUP_ID, 'SD_ism', 'SD_soft']])
    host.set_actor_label(label)
    host.set_folder_path(FOLDER)
    print('ISM ' + label + ' instances=' + str(added) + ' DONE')
'''

ISM_CHECK_BODY = r'''
have = site_actors(SITE)
host = have.get('SD_' + GROUP_ID)
if host is None:
    print('C2IHOST ' + str(dict(id=GROUP_ID, count=-1, expected=EXPECTED)))
else:
    comps = host.get_components_by_class(unreal.InstancedStaticMeshComponent)
    if len(comps) != 1 or comps[0].static_mesh is None:
        print('C2IHOST ' + str(dict(id=GROUP_ID, count=-1, expected=EXPECTED)))
    else:
        comp = comps[0]
        count = comp.get_instance_count()
        print('C2IHOST ' + str(dict(id=GROUP_ID, count=count, expected=EXPECTED)))
        b = comp.static_mesh.get_bounds()
        o, e = b.origin, b.box_extent
        z0 = o.z - e.z
        local = [(o.x + fx * e.x, o.y + fy * e.y, z0)
                 for fx, fy in ((-0.92, -0.92), (-0.92, 0.92), (0.92, -0.92), (0.92, 0.92), (0.0, 0.0))]
        for idx, it in ITEMS:
            if idx >= count:
                print('C2IMISS ' + it['id'])
                continue
            t = comp.get_instance_transform(idx, True)
            gaps = []
            for x, y, z in local:
                p = unreal.MathLibrary.transform_location(t, V(x, y, z))
                h = trace_ground(p.x, p.y, p.z + 300.0, p.z - 3000.0, [host])
                gaps.append(None if h is None else round(p.z - h[0], 1))
            print('C2I ' + str(dict(id=it['id'], gaps=gaps)))
print('C2I DONE')
'''

SETTLE_BODY = r'''
def mark_pose_edit(actor):
    # Runtime transform setters do not mark an existing package dirty. Actor
    # Modify covers native roots; include Blueprint-created roots explicitly.
    actor.modify()
    root = actor.get_editor_property('root_component')
    if root is not None:
        root.modify()

have = site_actors(SITE)
done = 0
for k, it in enumerate(ITEMS):
    a = have.get('SD_' + it['id'])
    if a is None:
        print('SETTLE missing ' + it['id'])
        continue
    st = it['settle']
    # not-yet-settled pieces of this run stand at their raised spawn poses: never land on them (LANE_SD)
    pend = [q['id'] for q in ITEMS[k + 1:]] + LATER
    if it['attach']:
        par = have.get('SD_' + it['parent']) if it.get('parent') else None
        if par is not None:
            pl = par.get_actor_location()
            pr = par.get_actor_rotation()
            mark_pose_edit(a)
            if it.get('shares_pivot'):
                # kit pairs (tent frame + cloth, cart + tarp) share one pivot: copy the parent transform
                a.set_actor_location_and_rotation(V(pl.x, pl.y, pl.z + st['z_offset_cm']), pr, False, True)
            else:
                me = a.get_actor_location()
                a.set_actor_location(V(me.x, me.y, pl.z + st['z_offset_cm']), False, True)
            print('SETTLE ' + it['id'] + ' attach->' + it['parent'])
            done += 1
            continue
    if st['mode'] == 'none':
        continue
    bounds = local_bounds(a, it)
    if bounds is None:
        print('SETTLE no mesh bounds ' + it['id'])
        continue
    c, pts = bounds
    gz = it['ground_z_cm']
    top = gz + it['size_m'][2] * 100.0 + st['drop_cm'] + 300.0
    ign = [a] + [have['SD_' + q] for q in pend if ('SD_' + q) in have]
    ign = ign + [have['SD_' + q] for q in OVERHEAD if ('SD_' + q) in have and q != it['id']]
    only_ground = it['attach']

    def tr(x, y):
        h = trace_support(x, y, top, gz - 3000, ign, it)
        if h is None:
            return None
        return (h[0], h[1])
    cfg = dict(mode=st['mode'], sink=st['sink_cm'], max_tilt=st['max_tilt_deg'], rand_tilt=st['rand_tilt_deg'],
               z_rule=st['z_rule'], candidates=7, require_complete_support=ground_only_contact(it))
    pose = settle_pose(it['x_cm'], it['y_cm'], c, pts, float(it['yaw']), float(it['pitch']), float(it['roll']), cfg, tr, rng)
    if pose is None:
        if ground_only_contact(it):
            # A partial footprint is not evidence of a grounded firepit/wall.
            # Stop the placement batch before its save phase rather than leave
            # a new actor at the raised spawn pose and report settlement done.
            raise RuntimeError('SETTLE incomplete Landscape support: ' + it['id'])
        print('SETTLE no-ground ' + it['id'])
        continue
    lx, ly, lz, yw, pt, rl, info = pose
    mark_pose_edit(a)
    a.set_actor_location_and_rotation(V(lx, ly, lz + st['z_offset_cm']), unreal.Rotator(roll=rl, pitch=pt, yaw=yw), False, True)
    done += 1
    print('SETTLE ' + it['id'] + ' ' + st['mode'] + ' ' + str(info))
print('SETTLE batch=' + str(done) + ' DONE')
'''

CHECK_BODY = r'''
have = site_actors(SITE)
boxes = []
no_mesh = 0
for it in ITEMS:
    a = have.get('SD_' + it['id'])
    if a is None or it['kind'] != 'SM':
        continue
    bounds = local_bounds(a, it)
    if bounds is None:
        no_mesh += 1
        print('CHECK no mesh bounds ' + it['id'])
        continue
    c, pts = bounds
    r = a.get_actor_rotation()
    ax = axes(r.yaw, r.pitch, r.roll)
    l = a.get_actor_location()
    wc = [(l.x + q[0], l.y + q[1], l.z + q[2]) for q in [apply(ax, p) for p in pts]]
    boxes.append((it, a, wc))
issues = 0
for it, a, wc in boxes:
    best = 1e12
    for (x, y, z) in wc:
        for i in range(len(ROAD) - 1):
            ax_, ay_ = ROAD[i]
            bx_, by_ = ROAD[i + 1]
            dx, dy = bx_ - ax_, by_ - ay_
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax_) * dx + (y - ay_) * dy) / L2))
            ex, ey = ax_ + t * dx - x, ay_ + t * dy - y
            best = min(best, ex * ex + ey * ey)
    d = best ** 0.5
    if d < CLEAR_CM - 30.0:
        issues += 1
        print('ROAD ' + it['id'] + ' clear=' + str(int(d)) + 'cm')
    gz = it['ground_z_cm']
    gaps = []
    if it['cat'] in ('fx', 'fx_card') or it['id'] in OVERHEAD:
        continue
    over = [have['SD_' + q] for q in OVERHEAD if ('SD_' + q) in have]
    for (x, y, z) in wc[:4]:
        h = trace_down(x, y, z + 400.0, gz - 3000, [a] + over)
        if h is not None:
            gaps.append(z - h[0])
    if not it['attach']:
        # bare-ground gap: a stack that holds itself up in mid-air passes the corner test (LANE_SD)
        oc, ec = a.get_actor_bounds(False)
        hg = trace_down(oc.x, oc.y, oc.z + ec.z + 400.0, gz - 3000, [have[k2] for k2 in have])
        if hg is not None and (oc.z - ec.z) - hg[0] > 150.0:
            issues += 1
            print('FLOAT_HIGH ' + it['id'] + ' above_ground=' + str(int((oc.z - ec.z) - hg[0])) + 'cm')
    if len(gaps) > 0 and not it['attach']:
        if min(gaps) > 12.0:
            issues += 1
            print('FLOAT ' + it['id'] + ' gap=' + str(int(min(gaps))) + 'cm')
        if it['cat'] in ('prop', 'wood', 'rubble_big') and max(gaps) < -45.0:
            issues += 1
            print('BURIED ' + it['id'] + ' ' + str(int(max(gaps))) + 'cm')
soft = [b for b in boxes if b[0]['stack'] or b[0]['attach'] or b[0]['cat'] in ('cloth', 'wood_post')]
hard = [b for b in boxes if b not in soft]
for i in range(len(hard)):
    ia, aa, wa = hard[i]
    oa, ea = aa.get_actor_bounds(False)
    for j in range(i + 1, len(hard)):
        ib, ab, wb = hard[j]
        if ia.get('run_id') and ia.get('run_id') == ib.get('run_id'):
            continue
        if ia['id'] in OVERHEAD or ib['id'] in OVERHEAD:
            continue
        ob, eb = ab.get_actor_bounds(False)
        ox = min(oa.x + ea.x, ob.x + eb.x) - max(oa.x - ea.x, ob.x - eb.x)
        oy = min(oa.y + ea.y, ob.y + eb.y) - max(oa.y - ea.y, ob.y - eb.y)
        oz = min(oa.z + ea.z, ob.z + eb.z) - max(oa.z - ea.z, ob.z - eb.z)
        if ox <= 0 or oy <= 0 or oz <= 0:
            continue
        # sample B's bottom points inside A's oriented box
        ra = aa.get_actor_rotation()
        axa = axes(ra.yaw, ra.pitch, ra.roll)
        la = aa.get_actor_location()
        ca, pa = local_bounds(aa, ia)
        hx = max(abs(p[0] - ca[0]) for p in pa[:4])
        hy = max(abs(p[1] - ca[1]) for p in pa[:4])
        zb = pa[0][2]
        zt = zb + ia['size_m'][2] * 100.0
        deep = 0.0
        for (x, y, z) in wb:
            v = (x - la.x, y - la.y, z - la.z)
            lx = v[0] * axa[0][0] + v[1] * axa[0][1] + v[2] * axa[0][2] - ca[0]
            ly = v[0] * axa[1][0] + v[1] * axa[1][1] + v[2] * axa[1][2] - ca[1]
            lz = v[0] * axa[2][0] + v[1] * axa[2][1] + v[2] * axa[2][2]
            if abs(lx) < hx and abs(ly) < hy and zb < lz < zt:
                deep = max(deep, min(hx - abs(lx), hy - abs(ly), lz - zb, zt - lz))
        if deep > TOL_CM:
            issues += 1
            print('OVERLAP ' + ia['id'] + ' x ' + ib['id'] + ' depth=' + str(int(deep)) + 'cm')
print('CHECK actors=' + str(len(boxes)) + ' no_mesh=' + str(no_mesh) + ' issues=' + str(issues) + ' DONE')
'''

CAPTURE_SHOOT_BODY = r'''
cam = V(CAM[0], CAM[1], CAM[2])
rot = unreal.MathLibrary.find_look_at_rotation(cam, V(LOOK[0], LOOK[1], LOOK[2]))
a = eas.spawn_actor_from_class(unreal.SceneCapture2D, cam, rot)
a.set_actor_label(LABEL)
a.set_editor_property('tags', [unreal.Name('SD_capture')])
comp = a.capture_component2d
rt = unreal.RenderingLibrary.create_render_target2d(world, SIZE[0], SIZE[1], unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
comp.set_editor_property('texture_target', rt)
comp.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
comp.set_editor_property('capture_every_frame', True)
comp.set_editor_property('always_persist_rendering_state', True)
comp.set_editor_property('capture_on_movement', False)
comp.set_editor_property('fov_angle', FOV)
pp = comp.get_editor_property('post_process_settings')
pp.set_editor_property('override_dynamic_global_illumination_method', True)
pp.set_editor_property('dynamic_global_illumination_method', unreal.DynamicGlobalIlluminationMethod.LUMEN)
pp.set_editor_property('override_reflection_method', True)
pp.set_editor_property('reflection_method', unreal.ReflectionMethod.LUMEN)
comp.set_editor_property('post_process_settings', pp)
flag = unreal.EngineShowFlagsSetting()
flag.set_editor_property('show_flag_name', 'PostProcessMaterial')
flag.set_editor_property('enabled', False)
comp.set_editor_property('show_flag_settings', [flag])
print('CAPTURE queued ' + LABEL + ' DONE')
'''

CAPTURE_EXPORT_BODY = r'''
out_dir = unreal.Paths.project_saved_dir() + OUT_REL
done = 0
for a in unreal.GameplayStatics.get_all_actors_with_tag(world, 'SD_capture'):
    if a.get_actor_label() == LABEL and done == 0:
        rt = a.capture_component2d.get_editor_property('texture_target')
        if rt is not None:
            unreal.RenderingLibrary.export_render_target(world, rt, out_dir, NAME + '.png')
            done = 1
    eas.destroy_actor(a)
print('CAPTURE ' + out_dir + '/' + NAME + '.png exported=' + str(done) + ' DONE')
'''

SAVE_BODY = r'''
have = site_actors(SITE)
labels = sorted(have.keys())
chunk = labels[OFFSET:OFFSET + LIMIT]
pkgs = [have[l].get_package() for l in chunk]
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True) if len(pkgs) > 0 else True
more = OFFSET + LIMIT < len(labels)
if len(DELETED) > 0 and not more:
    # save just the destroyed actors' own packages: that deletes their files, and unlike
    # save_current_level it never writes other lanes' unsaved edits (LANE_SD)
    gone = [unreal.find_package(n) for n in DELETED]
    gone = [g for g in gone if g is not None]
    ok = ok and (unreal.EditorLoadingAndSavingUtils.save_packages(gone, True) if len(gone) > 0 else True)
    print('SAVE deleted_packages=' + str(len(gone)))
print('SAVE ' + str(len(pkgs)) + ' ok=' + str(ok) + ' total=' + str(len(labels)) + (' MORE' if more else ' DONE'))
'''

CLEAR_BODY = r'''
have = site_actors(SITE)
n = 0
for label in sorted(have.keys()):
    if len(ONLY) > 0 and label not in ONLY:
        continue
    print('CLEARPKG ' + have[label].get_package().get_name())
    eas.destroy_actor(have[label])
    n += 1
    if n >= LIMIT:
        break
print('CLEAR destroyed=' + str(n) + (' MORE' if n >= LIMIT else ' DONE'))
'''

STATUS_BODY = r'''
have = site_actors(SITE)
ism = sum(1 for a in have.values() if 'SD_ism' in [str(t) for t in a.tags])
print('STATUS ' + SITE + ' actors=' + str(len(have)) + ' ism_hosts=' + str(ism) + ' DONE')
'''


# ------------------------------------------------------------------------------------------------
# V2 steps (docs/world/SETDRESS_V2.md): the strict check measures only; setdress_contact.py judges.
# ------------------------------------------------------------------------------------------------

CHECK2_BODY = r'''
have = site_actors(SITE)
blocks = {}
for lab, act in have.items():
    for t in act.tags:
        if str(t).startswith('SDB_'):
            blocks.setdefault(str(t), []).append(act)
isms = [act for act in have.values() if 'SD_ism' in [str(t) for t in act.tags]]
for it in ITEMS:
    a = have.get('SD_' + it['id'])
    if a is None:
        print('C2MISS ' + it['id'])
        continue
    r = a.get_actor_rotation()
    l = a.get_actor_location()
    sc = a.get_actor_scale3d().x
    bounds = actor_mesh_bounds(a)
    if bounds is None:
        print('C2NOGEOM ' + it['id'])
        continue
    org, ext = [list(bounds[0]), list(bounds[1])]
    rigid = it.get('contact') == 'rigid' or bool(it.get('unit'))
    bear = it.get('contact') == 'bear'
    footprint = 0.92 if rigid or bear else 1.0
    pts = contact_samples(org, ext, sc, (r.yaw, r.pitch, r.roll), (l.x, l.y, l.z), footprint)
    ign = [a] + blocks.get('SDB_' + str(it.get('block')), []) + isms
    # Stacks may rest on actual ISM/platform actors; non-stack ground-only items pass actors through.
    support_ignore = [a] if it.get('stack') else [a] + isms
    gaps, hits = [], []
    for k, (x, y, z) in enumerate(pts):
        if rigid:
            h = trace_ground(x, y, z + 300.0, z - 3000.0, [a] + isms)
            gaps.append(None if h is None else round(z - h[0], 1))
        else:
            h = trace_support(x, y, z + 40.0, z - 3000.0, support_ignore, it)
            gaps.append(None if h is None else round(z - h[0], 1))
        if bear:
            # a lintel: what each of the 9 samples rests on (the judge wants both ends on the named jambs)
            hits.append('none' if h is None else ('landscape' if is_land(h[2]) else h[2].get_actor_label()))
        if rigid and k in (0, 2, 6, 8):
            ign2 = list(ign)
            h2 = trace_down(x, y, z + 30.0, z - 3000.0, ign2)
            # World Partition HLOD proxies (old merged meshes) are not real support: pass through them
            for _ in range(4):
                if h2 is None or 'HLOD' not in h2[2].get_class().get_name():
                    break
                ign2.append(h2[2])
                h2 = trace_down(x, y, z + 30.0, z - 3000.0, ign2)
            hits.append('none' if h2 is None else ('landscape' if is_land(h2[2]) else h2[2].get_actor_label()))
    rep = dict(id=it['id'], loc=[l.x, l.y, l.z], rot=[r.yaw, r.pitch, r.roll], scale=sc, origin=org, extent=ext,
               gaps=gaps, hits=hits)
    print('C2 ' + str(rep))
print('C2 DONE')
'''

GROUND_BODY = r'''
have = site_actors(SITE)
made = 0
for g in G:
    label = 'SD_' + g['id']
    if label in have:
        continue
    mi = unreal.load_asset(MI[g['surface']])
    if mi is None:
        print('GROUND missing material ' + MI[g['surface']])
        continue
    a = eas.spawn_actor_from_class(unreal.DecalActor, V(g['x_cm'], g['y_cm'], g['z_cm']),
                                   unreal.Rotator(roll=0.0, pitch=-90.0, yaw=float(g['yaw'])))
    d = a.decal
    d.set_decal_material(mi)
    d.set_editor_property('decal_size', V(g['depth_m'] * 50.0, g['width_m'] * 50.0, g['length_m'] * 50.0))
    d.set_editor_property('sort_order', int(g['sort']))
    d.set_editor_property('fade_screen_size', FADE)
    if hasattr(d, 'set_decal_color'):
        d.set_decal_color(unreal.LinearColor(1.0 if g['shape'] == 'capsule' else 0.0,
                                             min(1.0, g['length_m'] / max(0.1, g['width_m']) / 16.0),
                                             (made * 0.618) % 1.0, float(g['strength'])))
    a.set_editor_property('tags', [unreal.Name(t) for t in ['SetDress', 'SD_' + SITE, 'SDID_' + g['id'], 'SD_ground']])
    a.set_actor_label(label)
    a.set_folder_path('Set/' + SITE + '/ground')
    made += 1
print('GROUND made=' + str(made) + ' DONE')
'''

MATSURVEY_BODY = r'''
have = site_actors(SITE)
seen = {}
for lab, a in have.items():
    if not isinstance(a, unreal.StaticMeshActor):
        continue
    comp = a.static_mesh_component
    for i in range(comp.get_num_materials()):
        m = comp.get_material(i)
        if m is not None:
            seen[m.get_path_name().split('.')[0]] = 1
for k in sorted(seen.keys()):
    print('MAT ' + k)
print('MATSURVEY ' + str(len(seen)) + ' DONE')
'''

MATERIAL_BODY = r'''
have = site_actors(SITE)
done = 0
for it in ITEMS:
    a = have.get('SD_' + it['id'])
    if a is None:
        continue
    comps = a.get_components_by_class(unreal.StaticMeshComponent)
    o, e = a.get_actor_bounds(False)
    valid = 0.0
    dz0, sx, sy = 0.0, 0.0, 0.0
    if not it.get('ism'):
        pts = []
        for fx in (-0.9, 0.0, 0.9):
            for fy in (-0.9, 0.0, 0.9):
                h = trace_ground(o.x + fx * e.x, o.y + fy * e.y, o.z + e.z + 200.0, o.z - e.z - 3000.0, [a])
                if h is not None:
                    pts.append((o.x + fx * e.x, o.y + fy * e.y, h[0]))
        if len(pts) >= 3:
            n = plane_normal(pts)
            mz = sum(p[2] for p in pts) / len(pts)
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            sx, sy = -n[0] / n[2], -n[1] / n[2]
            dz0 = mz + sx * (o.x - mx) + sy * (o.y - my) - o.z
            valid = 1.0
    ms = MSET.get(it.get('material_set') or 'stone', MSET['stone'])
    for comp in comps:
        for i in range(comp.get_num_materials()):
            m = comp.get_material(i)
            if m is None:
                continue
            k = m.get_path_name().split('.')[0]
            if k in MAP:
                comp.set_material(i, unreal.load_asset(MAP[k]))
        vals = [dz0, sx, sy, valid, ms[0], ms[1], ms[2], ms[3]]
        for j in range(len(vals)):
            comp.set_default_custom_primitive_data_float(j, float(vals[j]))
    done += 1
print('MATERIAL applied=' + str(done) + ' DONE')
'''

MATERIAL_ISM_BODY = r'''
have = site_actors(SITE)
n = 0
for lab, a in have.items():
    if 'SD_ism' not in [str(t) for t in a.tags]:
        continue
    ms = MSET['stone']
    for comp in a.get_components_by_class(unreal.StaticMeshComponent):
        for i in range(comp.get_num_materials()):
            m = comp.get_material(i)
            if m is not None and m.get_path_name().split('.')[0] in MAP:
                comp.set_material(i, unreal.load_asset(MAP[m.get_path_name().split('.')[0]]))
        vals = [0.0, 0.0, 0.0, 0.0, ms[0], ms[1], ms[2], ms[3]]
        for j in range(len(vals)):
            comp.set_default_custom_primitive_data_float(j, float(vals[j]))
    n += 1
print('MATERIAL ism_hosts=' + str(n) + ' DONE')
'''

JSON_LIST_HELPER = r'''
def json_list(xs):
    return '[' + ','.join('"' + x + '"' for x in xs) + ']'
'''

# ------------------------------------------------------------------------------------------------
# Host side
# ------------------------------------------------------------------------------------------------


def lit(v):
    """A Python literal for the data lines (repr is exact for dict/list/str/float/bool/None)."""
    return repr(v)


def build_script(body, seed=7, **data):
    head = EDITOR_HEAD.split('\n')
    lines = ['SEED = %d' % seed] + ['%s = %s' % (k, lit(v)) for k, v in data.items()]
    # the data must exist before EDITOR_HEAD uses SEED
    return '\n'.join(head[:2] + lines + head[2:]) + '\n' + JSON_LIST_HELPER + '\n' + body


def validate(script):
    bad = [b for b in BANNED if b in script]
    if bad:
        raise SystemExit('refusing to send: the script contains banned text %s' % bad)
    compile(script, '<setdress>', 'exec')
    return script


# V2 placement input = setdress_v2_sites.json (the composer: S07) + every group file in setdress_v2_groups/.
# A site already in the composer file wins. Story sets are placed by their own lane (Tools/World/story_sets): their
# sites stay out of the merge, and a story wrapper that swaps SITES_V2_JSON for its own file reads that file as is.
V2_GROUPS_DIR = os.path.join(HERE, 'setdress_v2_groups')
V2_STORY_SITES = {'S04_PromiseStones',    # story set V2 (story_sets/V2.json)
                  'S05_CartConvoy',       # story set V3 (story_sets/V3.json)
                  'S24_Ledge',            # story set V8
                  'S25_LastLookBack',     # story set V9 (verify only)
                  'S26_HighVoiceHut'}     # story set S26, inside V10
COMPOSER_V2_JSON = SITES_V2_JSON


def load_doc(v2=False):
    path = SITES_V2_JSON if v2 else SITES_JSON
    doc = json.load(open(path, encoding='utf8'))
    if v2 and os.path.abspath(path) == os.path.abspath(COMPOSER_V2_JSON):
        doc['sites'] = merge_v2_groups(doc['sites'])
    return doc


def merge_v2_groups(sites, groups_dir=V2_GROUPS_DIR):
    """The composer's sites, then each group file's sites by road metre (no duplicates, no story sets)."""
    out = [s for s in sites if s['id'] not in V2_STORY_SITES]
    seen = {s['id'] for s in out}
    extra = []
    if os.path.isdir(groups_dir):
        for f in sorted(os.listdir(groups_dir)):
            if not f.endswith('.json'):
                continue
            g = json.load(open(os.path.join(groups_dir, f), encoding='utf8'))
            for s in g.get('sites', []):
                if s['id'] in seen or s['id'] in V2_STORY_SITES:
                    continue
                s.setdefault('group', g.get('group') or f[:-5])
                seen.add(s['id'])
                extra.append(s)
    return out + sorted(extra, key=lambda s: (s.get('road_m', 0), s['id']))


def pie_running(path=LOG_PATH):
    """True when the user's play session is running: the last PIE start marker has no later shutdown."""
    if not os.path.exists(path):
        return False
    with open(path, 'rb') as fh:
        fh.seek(0, 2)
        n = fh.tell()
        fh.seek(max(0, n - 8000000))
        text = fh.read().decode('utf8', 'replace')
    start = max(text.rfind('Play in editor total start'), text.rfind('Creating play world package'),
                text.rfind('Repeating last play command'))
    return start > text.rfind('Shutting down PIE')


FAULT_MARKERS = ('HCR-NATIVE', 'SystemError: unknown opcode', 'EXCEPTION_ACCESS_VIOLATION', 'Fatal error',
                 '=== Critical error', 'appError')
PIE_START_MARKERS = ('Play in editor total start', 'Creating play world package', 'Repeating last play command')


def watch(path=LOG_PATH, period=1.0, max_s=0.0, out=print):
    """The per-second watchdog for an editor batch (reads the log only, sends nothing). Returns 2 when PIE is
    running or starts, 3 on a native fault / fatal line, 0 after max_s seconds (0 = run until one of those)."""
    if pie_running(path):
        out('WATCH PIE is running: send nothing')
        return 2
    pos = os.path.getsize(path) if os.path.exists(path) else 0
    t0 = time.time()
    while True:
        if os.path.exists(path):
            n = os.path.getsize(path)
            if n < pos:
                pos = 0                                   # the log rolled over (editor restart)
            if n > pos:
                with open(path, 'rb') as fh:
                    fh.seek(pos)
                    text = fh.read(n - pos).decode('utf8', 'replace')
                pos = n
                for line in text.splitlines():
                    if any(m in line for m in PIE_START_MARKERS):
                        out('WATCH PIE started: stop sending editor calls (%s)' % line.strip()[:160])
                        return 2
                    if any(m in line for m in FAULT_MARKERS):
                        out('WATCH fault: stop all editor calls, the editor needs a restart (%s)' % line.strip()[:200])
                        return 3
        if max_s and time.time() - t0 >= max_s:
            return 0
        time.sleep(period)


def site_of(doc, sid):
    for s in doc['sites']:
        if s['id'] == sid or s['id'].split('_')[0] == sid:
            return s
    raise SystemExit('unknown site %s (see: list)' % sid)


OVERHEAD_KEYS = {'B01_shelter01', 'BPP_Terrace_01'}   # decks on piers: pieces stand UNDER them (LANE_SD)


def overhead_ids(site):
    return [p['id'] for p in site['placements'] if p['key'] in OVERHEAD_KEYS]


def note_deleted(st, sid, out, args):
    """Remember the packages of destroyed actors, so 'save' writes (deletes) exactly those."""
    if args.dry_run:
        return
    pk = [l.split(' ', 1)[1].strip() for l in (out or '').splitlines() if l.startswith('CLEARPKG ')]
    st['deleted_pkgs'] = sorted(set(st.get('deleted_pkgs', []) + pk))
    st['deletions_pending'] = len(st['deleted_pkgs']) > 0
    write_state(sid, st)


def save_receipt(out, deleted=None):
    """Require the editor's package-save result, not just a successful transport reply."""
    lines = [line.strip() for line in (out or '').splitlines()]
    receipts = [line.split() for line in lines if line.startswith('SAVE ') and ' ok=' in line]
    if deleted is not None and ('SAVE deleted_packages=%d' % deleted) not in lines:
        raise SystemExit('SAVE missing deleted-package receipt; pending deletions retained')
    if len(receipts) != 1:
        raise SystemExit('SAVE missing or ambiguous package-save receipt; pending deletions retained')
    parts = receipts[0]
    if (len(parts) != 5 or not parts[1].isdigit() or parts[2] != 'ok=True'
            or not parts[3].startswith('total=') or not parts[3][6:].isdigit()
            or parts[4] not in ('MORE', 'DONE')):
        raise SystemExit('SAVE package save failed or receipt malformed; pending deletions retained')
    return parts[4] == 'MORE'


def editor_minimized():
    """True when UnrealEditor's main window is minimized (Windows only; False elsewhere or when unknown)."""
    if os.name != 'nt':
        return False
    import ctypes
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          '(Get-Process UnrealEditor -ErrorAction SilentlyContinue | Select-Object -First 1).MainWindowHandle'],
                         capture_output=True, text=True).stdout.strip()
    if not out.isdigit() or out == '0':
        return False
    return bool(ctypes.windll.user32.IsIconic(ctypes.c_void_p(int(out))))


def approvals(extra):
    keys = set()
    if os.path.exists(APPROVALS_JSON):
        keys |= set(json.load(open(APPROVALS_JSON, encoding='utf8')).get('approved', []))
    keys |= {k for k in (extra or '').split(',') if k}
    return keys


def slim(p):
    """The placement fields the editor needs (notes stripped: they are prose, and prose may hold banned text)."""
    keep = ('id', 'key', 'asset', 'kind', 'cat', 'x_cm', 'y_cm', 'ground_z_cm', 'yaw', 'pitch', 'roll', 'scale',
            'settle', 'folder', 'ism', 'stack', 'attach', 'collision', 'foliage_exclude', 'draw_distance_cm',
            'cast_shadow', 'size_m', 'fallback', 'parent', 'shares_pivot', 'run_id', 'group',
            'contact', 'unit', 'unit_role', 'block', 'material_set', 'bears_on', 'material')
    return {k: p[k] for k in keep if k in p}


def selection_token(items, v2):
    """Bind a contact readback to its selected source, including optional/story skips."""
    payload = json.dumps({'v2': bool(v2), 'placements': [slim(p) for p in items]},
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf8')).hexdigest()


def getattr_skip(args):
    return bool(vars(args).get('skip_story'))


def select(site, args):
    """Placements to place for this site: approved check-verdict assets, optional FX on request."""
    ok = approvals(args.approve)
    out, dropped = [], []
    last_solid = {}
    for p in site['placements']:
        if p.get('optional') and not args.with_optional:
            dropped.append((p['id'], 'optional'))
            continue
        if getattr_skip(args) and (p.get('story_owned_if_missing') or p.get('skip_if_existing_within_m')):
            dropped.append((p['id'], 'story-owned set exists (--skip-story)'))
            continue
        if p.get('verdict') == 'check' and p['key'] not in ok:
            if p.get('fallback'):
                q = dict(p)
                q['asset'] = p['fallback']['asset']
                q['scale'] = p['fallback']['scale']
                q.pop('fallback')
                q['kind'] = 'BPP' if '/Blueprints/BPP_' in q['asset'] else 'SM'
                out.append(q)
                dropped.append((p['id'], 'check -> fallback'))
            else:
                dropped.append((p['id'], 'check, not approved'))
            continue
        q = dict(p)
        if q.get('attach'):
            par = last_solid.get(q['group'])
            if par is not None:
                q['parent'] = par[0]
                q['shares_pivot'] = abs(par[1] - q['x_cm']) < 60 and abs(par[2] - q['y_cm']) < 60 and                     abs((par[3] - q['yaw'] + 180) % 360 - 180) < 2
        else:
            last_solid[q['group']] = (q['id'], q['x_cm'], q['y_cm'], q['yaw'])
        if args.no_ism:
            q['ism'] = False
        out.append(q)
    return out, dropped


def ism_jobs(sid, items, batch_size):
    """The stable host label and instance order shared by placement and contact readback."""
    groups = {}
    for p in items:
        if p['ism']:
            groups.setdefault((p['group'], p['asset']), []).append(p)
    for gi, ((grp, asset), ps) in enumerate(sorted(groups.items())):
        for j in range(0, len(ps), batch_size):
            gid = '%s_ism_%s_%02d_%d' % (sid, grp, gi, j // batch_size)
            yield gid, asset, ps[j:j + batch_size]


def ism_gap_violation(gaps, item, tol_cm=5.0):
    """Judge landscape contact for an ISM, including rubble/shrubs excluded by the solo judge."""
    if len(gaps) != 5 or any(g is None or not math.isfinite(g) for g in gaps):
        return ('NOGROUND', 'no complete landscape contact report')
    known = [g for g in gaps if g is not None]
    if item.get('contact') == 'rigid':
        if max(known) > tol_cm:
            return ('FLOAT', 'rigid instance has a %.0f cm corner gap' % max(known))
    elif min(known) > tol_cm:
        return ('FLOAT', 'instance has no ground contact; smallest gap %.0f cm' % min(known))
    return None


def solo_scatter_gap_violation(report, item, tol_cm=5.0):
    """Loose stones/shrubs may rest on another prop, but must touch a real support."""
    if item.get('cat') not in ('rubble', 'shrub') or item.get('attach'):
        return None
    known = [g for g in report.get('gaps', []) if g is not None]
    if not known:
        return ('NOGROUND', 'no ground or supporting actor beneath scatter prop')
    if min(known) > tol_cm:
        return ('FLOAT', 'scatter prop has no contact; smallest gap %.0f cm' % min(known))
    return None


class Hayba:
    def __init__(self, port):
        self.port = port
        self.n = 0
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection(('127.0.0.1', self.port), timeout=180)

    def run(self, script):
        self.n += 1
        env = {'cmd': 'python_run', 'id': 'setdress_%d_%d' % (os.getpid(), self.n), 'params': {'script': script}}
        if os.environ.get('HAYBA_LEASE'):
            env['lease'] = os.environ['HAYBA_LEASE']
        payload = json.dumps(env).encode('utf8')
        self.sock.sendall(struct.pack('>I', len(payload)) + payload)
        buf = b''
        while True:
            while len(buf) < 4:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise SystemExit('Hayba closed the connection')
                buf += chunk
            n = struct.unpack('>I', buf[:4])[0]
            while len(buf) < 4 + n:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise SystemExit('Hayba closed the connection')
                buf += chunk
            msg = json.loads(buf[4:4 + n].decode('utf8'))
            buf = buf[4 + n:]
            if msg.get('id') == env['id']:
                return msg


class Runner:
    def __init__(self, args):
        self.args = args
        self.h = None
        self.k = 0
        self.last_reply = 0.0

    def send(self, name, script):
        validate(script)
        if not self.args.dry_run and pie_running():
            raise SystemExit('PIE is running (saskartarad.log): no editor call sent. Wait for the play session to end.')
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        self.k += 1
        path = os.path.join(SCRIPT_DIR, '%s_%03d.py' % (name, self.k))
        with open(path, 'w', encoding='utf8') as fh:
            fh.write(script)
        if self.args.dry_run:
            print('[dry-run] %s (%d bytes) -> %s' % (name, len(script), os.path.relpath(path, ROOT)))
            return 'DONE (dry-run)'
        if self.h is None:
            self.h = Hayba(self.args.port)
            self.h.connect()
        elif time.monotonic() - self.last_reply >= 4.0:
            # Capture settle exceeds Hayba's 5 s idle timeout. Reconnect BEFORE
            # sending; rapid batches reuse their socket to respect the client cap.
            self.h.sock.close()
            self.h.connect()
        t0 = time.time()
        try:
            msg = self.h.run(script)
        except BaseException:
            # Never replay a mutation after a lost reply.
            self.h.sock.close()
            raise
        self.last_reply = time.monotonic()
        dt = time.time() - t0
        if not msg.get('ok'):
            err = json.dumps(msg.get('error') or msg.get('data'))
            print('%s: FAILED after %.1f s: %s' % (name, dt, err[:800]))
            if 'HCR-NATIVE' in err or 'SystemError' in err:
                raise SystemExit('A native fault inside python_run: STOP all editor calls; the editor must be restarted '
                                 '(python-mesh-rebuild-crashed-editor memory note). Do not retry.')
            raise SystemExit('step failed; stop and report (never retry a timed-out script unchanged)')
        out = (msg.get('data') or {}).get('stdout') or ''
        print('%s (%.1f s): %s' % (name, dt, out.strip()[-3000:]))
        return out


def state_path(sid):
    return os.path.join(STATE_DIR, sid + '.json')


def read_state(sid):
    p = state_path(sid)
    return json.load(open(p, encoding='utf8')) if os.path.exists(p) else {}


def write_state(sid, st):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(sid), 'w', encoding='utf8') as fh:
        json.dump(st, fh, indent=1)


def load_box(site):
    xs = [site['centre_cm'][0]]
    ys = [site['centre_cm'][1]]
    r = (site['radius_m'] + 30) * 100.0
    for v in site['views']:
        if v['name'] not in ('far300', 'road_best', 'road_near'):   # far views render whatever is loaded; they do not force tiles
            xs.append(v['cam_cm'][0])
            ys.append(v['cam_cm'][1])
    return [min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r]


def road_near(site, margin_m=80.0):
    sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
    import build_road_profile as brp
    P = brp.SPLINE_POINTS_CM[::-1, :2]
    cx, cy = site['centre_cm'][0], site['centre_cm'][1]
    R = (site['radius_m'] + margin_m) * 100.0
    keep = [i for i, p in enumerate(P) if (p[0] - cx) ** 2 + (p[1] - cy) ** 2 < (R + 60000) ** 2]
    if not keep:
        return []
    a, b = max(0, min(keep) - 1), min(len(P), max(keep) + 2)
    return [[float(x), float(y)] for x, y in P[a:b]]


def mark_dirty(st, sid, args):
    if not args.dry_run:
        st['dirty'] = True
        write_state(sid, st)


def gate_check(args, step):
    if step not in MUTATING or args.dry_run:
        return
    if not args.owner:
        raise SystemExit('mutating step: pass --owner <gate owner> after `python Tools/GameFlow/editor_gate.py acquire --owner ...`')
    if args.no_gate_check:
        return
    out = subprocess.run([sys.executable, os.path.join(ROOT, 'Tools', 'GameFlow', 'editor_gate.py'), 'status'],
                         capture_output=True, text=True, timeout=60).stdout
    if ('"%s"' % args.owner) not in out:
        raise SystemExit('the editor gate is not held by %s (editor_gate.py status); acquire it first' % args.owner)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('step', choices=['list', 'probe', 'load', 'survey', 'place', 'settle', 'check', 'capture',
                                     'save', 'unload', 'replace', 'clear', 'status',
                                     'ground', 'matsurvey', 'material', 'check2', 'watch'])
    ap.add_argument('site', nargs='?')
    ap.add_argument('ids', nargs='*', help='replace/clear: placement ids')
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--approve', default='')
    ap.add_argument('--with-optional', action='store_true')
    ap.add_argument('--no-ism', action='store_true')
    ap.add_argument('--skip-story', action='store_true',
                    help='leave out story_owned_if_missing / skip_if_existing items (the survey found the story set)')
    ap.add_argument('--views', default='carrier,orbit_a,orbit_b,high34,far300,road_best,road_near')
    ap.add_argument('--size', default='1600x900')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    ap.add_argument('--v2', action='store_true', help='use setdress_v2_sites.json (SETDRESS_V2.md) and Screenshots/SetDressV2')
    ap.add_argument('--max-s', type=float, default=0.0, help='watch: stop (exit 0) after this many seconds; 0 = never')
    args = ap.parse_args()
    if args.step == 'watch':
        raise SystemExit(watch(max_s=args.max_s))
    doc = load_doc(args.v2)
    global SHOT_DIR_REL
    if args.v2:
        SHOT_DIR_REL = 'Screenshots/SetDressV2'
        if args.views == ap.get_default('views'):
            args.views = 'carrier_a,carrier_b,carrier_c,orbit_a,orbit_b,orbit_c,contact,high34,far300'

    if args.step == 'list':
        print('%-24s %6s %5s %-8s %6s %6s  %s' % ('site', 'road_m', 'order', 'side', 'place', 'actors', 'name'))
        for s in doc['sites']:
            c = s['counts']
            print('%-24s %6d %5d %-8s %6d %6d  %s' % (s['id'], s['road_m'], s['order'], s['side'], c['placements'],
                                                     c['actors'], s['name']))
        return
    R = Runner(args)
    if args.step == 'probe':
        keys = sorted({p['asset'] for s in doc['sites'] for p in s['placements'] if p.get('requires_import')})
        R.send('probe', build_script(PROBE_BODY, BATCH01_KEYS=keys[:40]))
        return
    if not args.site:
        raise SystemExit('which site? (list)')
    site = site_of(doc, args.site)
    sid = site['id']
    gate_check(args, args.step)
    st = read_state(sid)
    items, dropped = select(site, args)

    if args.step == 'load':
        others = [f[:-5] for f in os.listdir(STATE_DIR) if f.endswith('.json') and f[:-5] != sid
                  and read_state(f[:-5]).get('loaded')] if os.path.isdir(STATE_DIR) else []
        if others:
            raise SystemExit('unload %s first: one site loaded at a time (landscape proxy cap)' % ', '.join(others))
        box = load_box(site)
        loaded = st.get('loaded', [])
        for _ in range(10):
            out = R.send('%s_load' % sid, build_script(LOAD_BODY, BOX=box, ALREADY=loaded, LIMIT=20,
                                                      MAX_LAND=MAX_LANDSCAPE_PROXIES, CLASS_FIELD='native_class'))
            for line in out.splitlines():
                if line.startswith('LOADED '):
                    loaded = list(dict.fromkeys(loaded + json.loads(line[7:])))
            if args.dry_run or ' DONE' in out:
                break
        if not args.dry_run:
            st.update(loaded=loaded, box=box)
            write_state(sid, st)
        return
    if args.step == 'unload':
        want = st.get('loaded', [])
        box = st.get('box') or load_box(site)
        for i in range(0, max(1, len(want)), 20):
            R.send('%s_unload' % sid, build_script(UNLOAD_BODY, BOX=box, WANT=want[i:i + 20]))
        if not args.dry_run:
            st['loaded'] = []
            write_state(sid, st)
        return
    if args.step == 'survey':
        R.send('%s_survey' % sid, build_script(SURVEY_BODY, SITE=sid, CENTRE=site['centre_cm'][:2],
                                               RADIUS=(site['radius_m'] + 20) * 100.0))
        for p in site['placements']:
            if p.get('story_owned_if_missing') or p.get('skip_if_existing_within_m'):
                print('NOTE %s (%s) is conditional: %s' % (p['id'], p['key'], 'story-owned if missing'
                                                           if p.get('story_owned_if_missing') else 'skip if one exists nearby'))
        return
    if args.step == 'status':
        R.send('%s_status' % sid, build_script(STATUS_BODY, SITE=sid))
        return
    if args.step in ('place', 'replace'):
        if site.get('verify_only'):
            print('%s is verify-only: nothing to place (capture it)' % sid)
            return
        if args.step == 'replace':
            if not args.ids:
                raise SystemExit('replace: which ids?')
            want = set(args.ids)
            # A failed clear or partial replace must not leave an old check2 valid.
            mark_dirty(st, sid, args)
            out = R.send('%s_clear' % sid, build_script(CLEAR_BODY, SITE=sid, ONLY=['SD_' + i for i in want], LIMIT=200))
            note_deleted(st, sid, out, args)
            items = [p for p in items if p['id'] in want]
        for d in dropped:
            print('SKIP %s: %s' % d)
        solo = [p for p in items if not p['ism']]
        for i in range(0, len(solo), BATCH['place']):
            R.send('%s_place' % sid, build_script(PLACE_BODY, SITE=sid, ITEMS=[slim(p) for p in solo[i:i + BATCH['place']]]))
        mark_dirty(st, sid, args)
        st['ism_batch_size'] = BATCH['ism']
        if not args.dry_run:
            write_state(sid, st)
        for gid, asset, ps in ism_jobs(sid, items, BATCH['ism']):
            fb = ps[0].get('fallback', {}).get('asset', '')
            R.send('%s_ism' % sid, build_script(ISM_BODY, SITE=sid, GROUP_ID=gid, ASSET=asset, FALLBACK=fb,
                                                MAT=ps[0].get('material', ''),
                                                FOLDER=ps[0]['folder'],
                                                ITEMS=[slim(p) for p in ps]))
        if args.step == 'replace':
            args.step = 'settle'
        else:
            return
    if args.step == 'settle':
        solo = [p for p in items if not p['ism']]
        if args.ids:
            solo = [p for p in solo if p['id'] in set(args.ids)]
        # order: solids first, then physics props (so stacks land on settled ground and pieces), then attached
        order = {'trace': 0, 'physics': 1, 'none': 3}
        # physics props land bottom layer first (ascending drop height), so a stack builds upward
        solo.sort(key=lambda p: (2 if p['attach'] else order[p['settle']['mode']], p['settle'].get('drop_cm', 0), p['id']))
        for i in range(0, len(solo), BATCH['settle']):
            R.send('%s_settle' % sid, build_script(SETTLE_BODY, SITE=sid, ITEMS=[slim(p) for p in solo[i:i + BATCH['settle']]],
                                                   LATER=[p['id'] for p in solo[i + BATCH['settle']:]],
                                                   OVERHEAD=overhead_ids(site),
                                                   seed=1000 + i))
        mark_dirty(st, sid, args)
        return
    if args.step == 'check':
        solo = [p for p in items if not p['ism']]
        road = road_near(site)
        R.send('%s_check' % sid, build_script(CHECK_BODY, SITE=sid, ITEMS=[slim(p) for p in solo], ROAD=road,
                                              OVERHEAD=overhead_ids(site),
                                              CLEAR_CM=CLEAR_M * 100.0, TOL_CM=8.0))
        return
    if args.step == 'capture':
        if not args.dry_run and editor_minimized():
            raise SystemExit('the editor window is minimized: it draws no frames, so every capture would be black. '
                             'Capture later, when the editor is visible (never restore the user window).')
        w, h = [int(v) for v in args.size.split('x')]
        sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Look'))
        import capture_look
        wanted = set(args.views.split(','))
        for v in site['views']:
            if v['name'] not in wanted:
                continue
            label = 'SD_CAPTURE_%s_%s' % (sid, v['name'])
            fov = 50.0 if v['name'] in ('far300', 'carrier') else (35.0 if v['name'] in ('road_best', 'road_near') else 60.0)
            setup = build_script(CAPTURE_SHOOT_BODY, CAM=v['cam_cm'], LOOK=v['look_cm'], LABEL=label,
                                 SIZE=[w, h], FOV=fov)
            export = build_script(CAPTURE_EXPORT_BODY, LABEL=label, NAME=v['name'],
                                  OUT_REL='%s/%s' % (SHOT_DIR_REL, sid))
            if args.dry_run:
                R.send('%s_shoot' % sid, setup)
                R.send('%s_export' % sid, export)
            else:
                # Match the lit game view even while the editor's main viewport is idle.
                # The shared helper restores skylights and destroys this capture on failure.
                ok, out, err = capture_look.run_capture_scripts(
                    setup, capture_look.PUMP_SCRIPT.replace('__LABEL__', label), export,
                    CAPTURE_SETTLE_S, True, capture_label=label)
                print(out)
                if not ok:
                    raise SystemExit(err or 'set dressing capture failed')
        print('shots -> Saved/%s/%s/' % (SHOT_DIR_REL, sid))
        return
    if args.step == 'ground':
        g = site.get('ground', [])
        mi = {k: GROUND_MI + k for k in {x['surface'] for x in g}}
        for i in range(0, len(g), 20):
            R.send('%s_ground' % sid, build_script(GROUND_BODY, SITE=sid, G=g[i:i + 20], MI=mi, FADE=0.0015))
        mark_dirty(st, sid, args)
        return
    if args.step == 'matsurvey':
        out = R.send('%s_matsurvey' % sid, build_script(MATSURVEY_BODY, SITE=sid))
        mats = [l[4:].strip() for l in (out or '').splitlines() if l.startswith('MAT ')]
        if not args.dry_run:
            st['materials'] = mats
            write_state(sid, st)
        print('%d materials -> state; next: python Tools/World/build_setdress_materials.py variants %s' % (len(mats), sid))
        return
    if args.step == 'material':
        mp = json.load(open(MATERIAL_MAP_JSON, encoding='utf8')) if os.path.exists(MATERIAL_MAP_JSON) else {}
        solo = [slim(p) for p in items if not p['ism'] and p.get('material_set')]
        for i in range(0, len(solo), 12):
            R.send('%s_material' % sid, build_script(MATERIAL_BODY, SITE=sid, ITEMS=solo[i:i + 12], MAP=mp, MSET=MATERIAL_SETS))
        R.send('%s_material' % sid, build_script(MATERIAL_ISM_BODY, SITE=sid, MAP=mp, MSET=MATERIAL_SETS))
        mark_dirty(st, sid, args)
        return
    if args.step == 'check2':
        import setdress_contact as sc
        solo = [p for p in items if not p['ism']]
        if args.ids:
            solo = [p for p in solo if p['id'] in set(args.ids)]
        reps = {}
        for i in range(0, len(solo), 10):
            out = R.send('%s_check2' % sid, build_script(CHECK2_BODY, SITE=sid, ITEMS=[slim(p) for p in solo[i:i + 10]]))
            for line in (out or '').splitlines():
                if line.startswith('C2 {'):
                    r = ast.literal_eval(line[3:])
                    reps[r['id']] = r
        ism_items = [p for p in items if p['ism']]
        ism_reps = {}
        host_counts = {}
        jobs = list(ism_jobs(sid, items, st.get('ism_batch_size', BATCH['ism'])))
        for gid, _, ps in jobs:
            indexed = list(enumerate(ps))
            for i in range(0, len(indexed), ISM_CHECK_BATCH):
                out = R.send('%s_ism_check2' % sid,
                             build_script(ISM_CHECK_BODY, SITE=sid, GROUP_ID=gid, EXPECTED=len(ps),
                                          ITEMS=[(j, slim(p)) for j, p in indexed[i:i + ISM_CHECK_BATCH]]))
                for line in (out or '').splitlines():
                    if line.startswith('C2IHOST {'):
                        report = ast.literal_eval(line[8:])
                        host_counts[gid] = report['count']
                    elif line.startswith('C2I {'):
                        report = ast.literal_eval(line[4:])
                        ism_reps[report['id']] = report
        if args.dry_run:
            return
        viol, waived = sc.judge(reps, {p['id']: p for p in solo}, site.get('waivers', []))
        waived_keys = {(w['id'], w['code']) for w in site.get('waivers', []) if w.get('reason')}
        for gid, _, ps in jobs:
            if host_counts.get(gid) != len(ps):
                viol.append((gid, 'ISM_COUNT', '%d instances expected; measured %s' %
                             (len(ps), host_counts.get(gid, 'no host receipt'))))
        for p in solo:
            rep = reps.get(p['id'])
            problem = solo_scatter_gap_violation(rep, p) if rep is not None else None
            if problem:
                entry = (p['id'], problem[0], problem[1])
                (waived if (entry[0], entry[1]) in waived_keys else viol).append(entry)
        for p in ism_items:
            rep = ism_reps.get(p['id'])
            problem = ('NOGROUND', 'instance transform or report missing') if rep is None else ism_gap_violation(rep['gaps'], p)
            if problem:
                entry = (p['id'], problem[0], problem[1])
                (waived if (entry[0], entry[1]) in waived_keys else viol).append(entry)
        for v in viol:
            print('VIOLATION %s %s: %s' % v)
        for v in waived:
            print('waived %s %s: %s' % v)
        st['check2'] = dict(time=time.time(), measured=len(reps), expected=len(solo),
                            selection=selection_token(items, args.v2),
                            ism_measured=len(ism_reps), ism_expected=len(ism_items),
                            ism_hosts_measured=sum(host_counts.get(gid) == len(ps) for gid, _, ps in jobs),
                            ism_hosts_expected=len(jobs),
                            violations=[list(v) for v in viol])
        st['dirty'] = False
        write_state(sid, st)
        print('CHECK2 measured=%d of %d ism=%d of %d hosts=%d of %d violations=%d waived=%d' %
              (len(reps), len(solo), len(ism_reps), len(ism_items), st['check2']['ism_hosts_measured'],
               len(jobs), len(viol), len(waived)))
        return
    if args.step == 'save':
        # Both source generations require current, complete contact evidence.
        c2 = st.get('check2')
        if st.get('dirty', True) or not c2:
            raise SystemExit('refusing to save %s: run check2 after the last place/settle/ground/material' % sid)
        if c2.get('selection') != selection_token(items, args.v2):
            raise SystemExit('refusing to save %s: run check2 for this source and placement selection' % sid)
        if c2['violations'] or c2['measured'] < c2['expected']:
            raise SystemExit('refusing to save %s: %d violations, %d of %d measured (check2). Fix them or waive '
                             'them with a reason in the site data.' % (sid, len(c2['violations']), c2['measured'], c2['expected']))
        if (c2['expected'] != sum(not p['ism'] for p in items) or
                c2.get('ism_expected') != sum(bool(p['ism']) for p in items) or
                c2.get('ism_measured') != c2.get('ism_expected') or
                c2.get('ism_hosts_measured') != c2.get('ism_hosts_expected')):
            raise SystemExit('refusing to save %s: run check2 with complete ISM instance and host readback' % sid)
        off = 0
        finished = False
        for _ in range(200):
            out = R.send('%s_save' % sid, build_script(SAVE_BODY, SITE=sid, OFFSET=off, LIMIT=BATCH['save'], DELETED=[]))
            off += BATCH['save']
            if args.dry_run or not save_receipt(out):
                finished = True
                break
        if not finished:
            raise SystemExit('SAVE never returned DONE; pending deletions retained')
        # deletions one package per call: the editor's Git provider runs git for each one, which is slow (LANE_SD)
        for pk in st.get('deleted_pkgs', []):
            out = R.send('%s_save' % sid, build_script(SAVE_BODY, SITE=sid, OFFSET=100000, LIMIT=0, DELETED=[pk]))
            if not args.dry_run and save_receipt(out, deleted=1):
                raise SystemExit('SAVE deletion batch unexpectedly returned MORE; pending deletions retained')
        if not args.dry_run:
            st['deletions_pending'] = False
            st['deleted_pkgs'] = []
            write_state(sid, st)
        return
    if args.step == 'clear':
        if not args.yes:
            raise SystemExit('clear destroys every actor of %s: pass --yes (then run save)' % sid)
        # Invalidate any earlier contact report before the first destructive batch.
        mark_dirty(st, sid, args)
        for _ in range(100):
            out = R.send('%s_clear' % sid, build_script(CLEAR_BODY, SITE=sid, ONLY=['SD_' + i for i in args.ids], LIMIT=60))
            note_deleted(st, sid, out, args)
            if args.dry_run or ' MORE' not in out:
                break
        if not args.dry_run:
            st['deletions_pending'] = True
            write_state(sid, st)
        if args.v2:
            print('run place/settle/ground/material/check2 for %s before V2 save; deletion packages remain pending' % sid)
        else:
            print('now run: save %s (it also saves the level so the deletions reach disk)' % sid)
        return


if __name__ == '__main__':
    main()
