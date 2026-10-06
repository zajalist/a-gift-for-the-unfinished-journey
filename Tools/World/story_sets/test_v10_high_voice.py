"""Offline tests for V10 (the High Voice relay station): the layout rules and this set's own editor steps.

    python -m pytest Tools/World/story_sets/test_v10_high_voice.py -q

The editor steps (level, lines, hooks) are executed against a small fake `unreal` module whose landscape is the
real Gaea heightmap and whose actors are boxes (mesh bounds x scale x rotation), so the maths that decides where
the walls, the roof, the guys and the plate end up is exercised before an editor lane ever runs it.
"""
import json
import math
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'Story'))
import v10_high_voice as V  # noqa: E402

B = V.build()
G, S, Hk, RECS, BY_ITEM, GRECS, H, LINES = B
NOTES, BAD = V.checks(G, S, RECS, GRECS, H, LINES)


# ---------------------------------------------------------------------------- layout rules

def test_no_offline_violation():
    assert BAD == []


def test_every_asset_exists_on_disk():
    root = V.ROOT
    for r in RECS:
        assert os.path.exists(os.path.join(root, 'Content', r['asset'][len('/Game/'):] + '.uasset')), r['asset']
    for p in (V.EA_PIPE, V.BRASS, V.IRON, V.PLATE_MESH, V.MARK_MESH):
        assert os.path.exists(os.path.join(root, 'Content', p[len('/Game/'):] + '.uasset')), p


def test_contact_classes_and_supports():
    ids = {r['id'] for r in RECS}
    for r in RECS:
        if r['ism']:
            assert 'contact' not in r and r['collision'] is False
            continue
        assert r['contact'] in ('rigid', 'lie', 'rest', 'stack', 'bear'), r
        if r['contact'] == 'rigid':
            assert r['settle']['max_tilt_deg'] == 0 and r['settle']['z_rule'] == 'min'
        if r['contact'] == 'bear':
            assert r['bears_on'] and set(r['bears_on']) <= ids
            assert r['settle']['mode'] == 'none'          # the level step places it
        assert r['draw_distance_cm'] > 0                  # never 0 (= infinite)


def test_hut_is_one_block_and_closed():
    walls = [BY_ITEM[id(Hk['walls'][k])] for k in ('front', 'back', 'left', 'right')]
    assert {w['block'] for w in walls} == {'hut'}
    lv = V.level_blocks(S, Hk, BY_ITEM)
    assert [b['block'] for b in lv] == ['plinth', 'mastfoot', 'hut']   # the plinth is levelled before the hut on it
    hut = [b for b in lv if b['block'] == 'hut'][0]
    assert set(hut['members']) == {w['id'] for w in walls} and hut['base_on'] == 'plinth'
    assert hut['match'] == BY_ITEM[id(Hk['walls']['front'])]['id']    # the door arch sets the wall height


def local(it):
    _, X, Y = V.hut_axes()
    du, dv = it['u'] - V.HUT_C[0], it['v'] - V.HUT_C[1]
    return round(du * X[0] + dv * X[1], 3), round(du * Y[0] + dv * Y[1], 3)


def test_shell_and_the_frame_s26_reads():
    # S26 lays its room out against this shell: AB 300x400 on a 3.0 m square, the arch front at x = -1.5
    w = Hk['walls']
    assert local(w['front']) == (-1.5, 0.0) and w['front']['key'] == 'AB_Side_Arch_small'
    assert local(w['back']) == (1.5, 0.0)
    assert local(w['left']) == (0.0, -1.5) and local(w['right']) == (0.0, 1.5)
    fr = V.interior_frame(G, H, S, BY_ITEM, Hk)
    assert fr['inner_m'] == dict(front=-1.07, back=1.38, side=1.37)
    assert fr['floor']['label'] == 'SD_' + BY_ITEM[id(Hk['plinth'])]['id']
    assert fr['plate']['local_y'] == V.PLATE_Y and fr['door_opening_m']['w'] == V.DOOR_W
    names = {r['key'] for r in RECS}
    assert not names & {'MV_Chimney'}               # no stove, no chimney: none is modelled
    assert sum(1 for r in RECS if r['key'] == 'B01_floor01') == 2   # the roof slab and the plinth (the hut floor)


def test_walls_stand_on_the_plinth_and_the_plinth_clears_the_ground():
    pl = BY_ITEM[id(Hk['plinth'])]
    for k in ('front', 'back', 'left', 'right'):
        r = BY_ITEM[id(Hk['walls'][k])]
        assert r['contact'] == 'bear' and r['bears_on'] == [pl['id']]
    pd = V.plinth_dims()
    assert pd['x0'] == V.ARCH_OUT and pd['x1'] > V.HALF + 0.12       # flush with the arch face, past the back wall
    assert pd['half_y'] > V.HALF + V.SIDE_SCALE * 0.12              # past the side walls' outer faces
    lv = S.levels
    assert lv['plinth_top'] >= lv['plinth_ground'][1] + V.PLINTH_CLEAR_CM / 100 - 1e-6
    assert -0.05 <= lv['sill_minus_grade'] <= 0.15                   # the door sill at the outside grade


def test_collar_has_two_courses_and_stands_clear():
    c1, c2 = Hk['course1'], Hk['course2']
    assert len(c1) == 4 and len(c2) == 4
    ids1 = {BY_ITEM[id(it)]['id'] for it in c1}
    for it in c2:
        assert BY_ITEM[id(it)]['contact'] == 'bear' and set(BY_ITEM[id(it)]['bears_on']) == ids1
    assert S.levels['cap_min_clear'] >= V.COLLAR_EXPOSE_M
    # the reversed pinwheel keeps the same square hole: every block centre sits (L + W) / 2 out in plan
    _, L, W = V.collar_rect()
    for (dx, dy), yaw in V.collar_rect(course=2)[0]:
        assert abs(abs(dx) + abs(dy) - (L + W) / 2) < 1e-6


def test_no_ism_overlaps_left():
    assert V.clash_pairs(S) == []


def test_doorcheck_script_is_hayba_safe():
    import place_setdress as ps
    doc = json.load(open(V.OUT_JSON, encoding='utf8'))
    arch = [b for b in doc['level_blocks'] if b['block'] == 'hut'][0]['match']
    ps.validate(ps.build_script(V.GRID9_SRC + V.DOORCHECK_BODY, SITE=V.SID, ARCH=arch, GRADE=grade_data(),
                                HEIGHTS=[30.0, 100.0], PU=-105.0, PH=22.5, PLATE_UP=130.0))


def test_stand_point_reaches_the_plate_inside_the_tether():
    su, sv = H['stand_uv']
    assert G.road_dist([(su, sv)]) < V.BLOCK_M - 0.8
    px, py, pz = H['plate']
    sx, sy, sz = H['stand_feet']
    assert abs(math.hypot(px - sx, py - sy) - V.STAND_OUT_M) < 0.02      # 60 cm in front of the plate (ENDING 6c)
    assert 1.2 < pz - sz < 1.5          # a hand laid on the plate


def test_json_is_a_v2_doc():
    doc = json.load(open(V.OUT_JSON, encoding='utf8'))
    site = doc['sites'][0]
    assert site['id'] == V.SID and site['placements'] and site['ground'] and site['views']
    names = {v['name'] for v in site['views']}
    assert {'carrier_a', 'orbit_a', 'contact', 'far300', 'seat', 'mastup'} <= names
    assert doc['level_blocks'] and doc['lines'] and doc['story_hooks'] and doc['interior_frame']


# ---------------------------------------------------------------------------- a fake unreal

class Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class Rot:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll, self.pitch, self.yaw = float(roll), float(pitch), float(yaw)


def axes(yaw, pitch, roll):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    return ((cp * cy, cp * sy, sp), (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
            (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp))


def apply(ax, p):
    X, Y, Z = ax
    return tuple(p[0] * X[i] + p[1] * Y[i] + p[2] * Z[i] for i in range(3))


class Bounds:
    def __init__(self, origin, extent):
        self.origin, self.box_extent = Vec(*origin), Vec(*extent)


class Mesh:
    def __init__(self, path, size, pivot='base'):
        self.path = path
        e = [s / 2.0 for s in size]
        o = {'base': (0.0, 0.0, e[2]), 'centre': (0.0, 0.0, 0.0), 'end': (e[0], 0.0, 0.0)}[pivot]
        self.b = Bounds(o, e)

    def get_bounds(self):
        return self.b

    def get_name(self):
        return self.path.split('/')[-1]


class Pkg:
    def __init__(self, n):
        self.n = n

    def get_name(self):
        return self.n


class Comp:
    def __init__(self, owner, name, mesh=None, rel=(0.0, 0.0, 0.0)):
        self.owner, self.name, self.static_mesh, self.rel = owner, name, mesh, rel
        self.wloc, self.wrot, self.wscale = None, Rot(), Vec(1, 1, 1)
        self.mats = {}

    def get_name(self):
        return self.name

    def get_world_location(self):
        if self.wloc is not None:
            return self.wloc
        l = self.owner.loc
        return Vec(l.x + self.rel[0], l.y + self.rel[1], l.z + self.rel[2])

    def get_world_rotation(self):
        return self.wrot

    def get_world_scale(self):
        return self.wscale

    def set_world_location_and_rotation(self, loc, rot, sweep, teleport):
        self.wloc, self.wrot = loc, rot

    def set_world_scale3d(self, s):
        self.wscale = s

    def set_static_mesh(self, m):
        self.static_mesh = m

    def set_material(self, i, m):
        self.mats[i] = m

    def set_collision_profile_name(self, n):
        self.collision = n

    def set_editor_property(self, k, v):
        setattr(self, k, v)


class Actor:
    cls = 'StaticMeshActor'

    def __init__(self, mesh=None, loc=None, rot=None, label=''):
        self.loc, self.rot, self.scale = loc or Vec(), rot or Rot(), Vec(1, 1, 1)
        self.label, self.tags, self.comps = label, [], []
        self.static_mesh_component = Comp(self, 'StaticMeshComponent0', mesh)
        self.pkg = Pkg('/Game/__ExternalActors__/level/Saskarta_WP/fake/' + str(id(self)))

    def get_class(self):
        return types.SimpleNamespace(get_name=lambda: self.cls)

    def get_actor_location(self):
        return self.loc

    def get_actor_rotation(self):
        return self.rot

    def get_actor_scale3d(self):
        return self.scale

    def set_actor_location(self, v, sweep=False, teleport=False):
        self.loc = v

    def set_actor_rotation(self, r, teleport=False):
        self.rot = r

    def set_actor_scale3d(self, s):
        self.scale = s

    def set_actor_label(self, n):
        self.label = n

    def get_actor_label(self):
        return self.label

    def set_folder_path(self, p):
        self.folder = p

    def set_editor_property(self, k, v):
        setattr(self, k, v)

    def get_package(self):
        return self.pkg

    def modify(self):
        self.modified = True

    def get_components_by_class(self, cls):
        return [c for c in self.comps if cls is SceneComponent or c.static_mesh is not None or c.name == 'Plate']

    def corners(self):
        m = self.static_mesh_component.static_mesh
        b = m.get_bounds()
        ax = axes(self.rot.yaw, self.rot.pitch, self.rot.roll)
        out = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    p = ((b.origin.x + sx * b.box_extent.x) * self.scale.x, (b.origin.y + sy * b.box_extent.y) * self.scale.y,
                         (b.origin.z + sz * b.box_extent.z) * self.scale.z)
                    q = apply(ax, p)
                    out.append((self.loc.x + q[0], self.loc.y + q[1], self.loc.z + q[2]))
        return out

    def get_actor_bounds(self, only_colliding):
        c = self.corners()
        lo = [min(p[i] for p in c) for i in range(3)]
        hi = [max(p[i] for p in c) for i in range(3)]
        return Vec(*[(lo[i] + hi[i]) / 2 for i in range(3)]), Vec(*[(hi[i] - lo[i]) / 2 for i in range(3)])

    def top_at(self, x, y):
        """The box top under (x, y) for a plumb or flat piece (oriented footprint test), else None."""
        m = self.static_mesh_component.static_mesh
        b = m.get_bounds()
        ax = axes(self.rot.yaw, 0.0, 0.0)
        dx, dy = x - self.loc.x, y - self.loc.y
        lx, ly = dx * ax[0][0] + dy * ax[0][1], dx * ax[1][0] + dy * ax[1][1]
        if abs(self.rot.pitch) > 1:
            o, e = self.get_actor_bounds(False)
            return o.z + e.z if abs(x - o.x) <= e.x and abs(y - o.y) <= e.y else None
        if abs(lx - b.origin.x * self.scale.x) <= b.box_extent.x * self.scale.x and abs(ly - b.origin.y * self.scale.y) <= b.box_extent.y * self.scale.y:
            return self.loc.z + (b.origin.z + b.box_extent.z) * self.scale.z
        return None


class Land(Actor):
    cls = 'LandscapeStreamingProxy'


class Hit:
    def __init__(self, z, actor):
        self.t = (True, 0, 0, 0, 0, Vec(0, 0, z), 0, Vec(0, 0, 1), 0, actor)

    def to_tuple(self):
        return self.t


class SceneComponent:
    pass


class StaticMeshComponent(SceneComponent):
    pass


class World:
    def __init__(self):
        self.actors = []
        self.land = Land(label='Landscape')
        self.assets = {}

    def trace(self, start, end, ignore):
        best = None
        gz = G.gw(start.x / 100.0, start.y / 100.0) * 100.0
        if end.z <= gz <= start.z:
            best = (gz, self.land)
        for a in self.actors:
            if a in ignore or a.static_mesh_component.static_mesh is None:
                continue
            z = a.top_at(start.x, start.y)
            if z is not None and end.z <= z <= start.z and (best is None or z > best[0]):
                best = (z, a)
        return None if best is None else Hit(best[0], best[1])


def fake_unreal(W):
    u = types.ModuleType('unreal')
    u.Vector, u.Rotator, u.Name = Vec, Rot, str
    u.HitResult = Hit
    u.SceneComponent, u.StaticMeshComponent, u.StaticMeshActor = SceneComponent, StaticMeshComponent, Actor
    u.TraceTypeQuery = types.SimpleNamespace(TRACE_TYPE_QUERY1=1)
    u.DrawDebugTrace = types.SimpleNamespace(NONE=0)
    u.UnrealEditorSubsystem = 'ues'
    u.EditorActorSubsystem = 'eas'

    def spawn(mesh, loc, rot):
        a = Actor(mesh, loc, rot)
        W.actors.append(a)
        return a
    eas = types.SimpleNamespace(get_all_level_actors=lambda: [W.land] + W.actors, spawn_actor_from_object=spawn)
    u.get_editor_subsystem = lambda c: types.SimpleNamespace(get_editor_world=lambda: W) if c == 'ues' else eas
    u.EditorAssetLibrary = types.SimpleNamespace(does_asset_exist=lambda p: True)
    u.load_asset = lambda p: W.assets.get(p, p)
    u.SystemLibrary = types.SimpleNamespace(line_trace_single=lambda w, s, e, tt, cx, ign, dd, isf: W.trace(s, e, ign))
    u.GameplayStatics = types.SimpleNamespace(get_all_actors_with_tag=lambda w, t: [a for a in W.actors if t in a.tags])
    u.EditorLoadingAndSavingUtils = types.SimpleNamespace(save_packages=lambda p, d: True)
    return u


def scene(pivot='base'):
    """Spawn the site as `place` + `settle` would leave it (rigid pieces at their own min - sink)."""
    W = World()
    for r in RECS:
        if r['ism']:
            continue
        sz = V.asset(r['key'])['size_cm']
        m = Mesh(r['asset'], sz, pivot)
        sc = r['scale']
        a = Actor(m, Vec(), Rot(pitch=r['pitch'], yaw=r['yaw']), 'SD_' + r['id'])
        a.scale = Vec(sc, sc, sc)
        a.tags = ['SetDress', 'SD_' + V.SID, 'SDID_' + r['id']]
        o, e = a.get_actor_bounds(False)
        a.loc = Vec(r['x_cm'] - (o.x - a.loc.x), r['y_cm'] - (o.y - a.loc.y), 0.0)
        g = min(G.gw(x / 100, y / 100) for x, y, _ in a.corners()) * 100.0 - r['settle']['sink_cm']
        o, e = a.get_actor_bounds(False)
        a.loc = Vec(a.loc.x, a.loc.y, a.loc.z + (g + e.z) - o.z)
        W.actors.append(a)
    W.assets[V.EA_PIPE] = Mesh(V.EA_PIPE, (1000.0, 15.0, 15.0), 'end')
    W.assets[V.PLATE_MESH] = Mesh(V.PLATE_MESH, (100.0, 100.0, 100.0), pivot)
    W.assets[V.MARK_MESH] = Mesh(V.MARK_MESH, (170.0, 170.0, 20.0), 'centre')
    gz = G.gw(V.O_CM[0] / 100, V.O_CM[1] / 100) * 100.0
    hv = Actor(None, Vec(V.O_CM[0], V.O_CM[1], gz - 50.0), Rot(), 'HighVoice')
    hv.comps = [Comp(hv, 'Mast%d' % i, Mesh('/Game/EasyAtmos/X/Tile_10MPillar', (50.0, 100.0, 1000.0)), (0.0, 0.0, 1000.0 * i))
                for i in range(4)]
    W.actors.append(hv)
    end = Actor(None, Vec(V.O_CM[0], V.O_CM[1], gz), Rot(), 'HighVoice_Ending')
    end.tags = ['Saskarta.HighVoice']
    end.comps = [Comp(end, n) for n in ('MastBase', 'StandPoint', 'SeatPoint', 'Plate', 'Crown', 'Column')]
    W.actors.append(end)
    return W


def grade_data():
    fr = json.load(open(V.OUT_JSON, encoding='utf8'))['interior_frame']
    return [p + [z] for p, z in zip(fr['grade_points_cm'], fr['grade_z_cm'])]


def run_body(W, body, **data):
    import place_setdress as ps
    sys.modules['unreal'] = fake_unreal(W)
    try:
        src = ps.build_script(body, **data)
        ps.validate(src)
        out = []
        env = {'print': lambda *a: out.append(' '.join(str(x) for x in a))}
        exec(compile(src, 'v10', 'exec'), env)
        return out
    finally:
        sys.modules.pop('unreal', None)


def actor(W, rid):
    return [a for a in W.actors if a.label == 'SD_' + rid][0]


@pytest.mark.parametrize('pivot', ['base', 'centre'])
def test_level_step(pivot):
    W = scene(pivot)
    doc = json.load(open(V.OUT_JSON, encoding='utf8'))
    out = run_body(W, V.GRID9_SRC + V.LEVEL_BODY, SITE=V.SID, BLOCKS=doc['level_blocks'], GRADE=grade_data())
    assert any(line.startswith('LEVEL_CHECK hut OK') for line in out), out
    assert any(line.startswith('LEVEL_CHECK mastfoot OK') for line in out), out
    assert any(line.startswith('LEVEL_CHECK plinth OK') for line in out), out
    assert any(line.startswith('LEVEL_CHECK plinth top clears') and line.endswith(' OK') for line in out), out
    pl = [b for b in doc['level_blocks'] if b['block'] == 'plinth'][0]
    po, pe = actor(W, pl['members'][0]).get_actor_bounds(False)
    mf = [b for b in doc['level_blocks'] if b['block'] == 'mastfoot'][0]
    c1top = max(actor(W, i).get_actor_bounds(False)[0].z + actor(W, i).get_actor_bounds(False)[1].z for i in mf['members'])
    for sp in mf['supports']:
        o, e = actor(W, sp['id']).get_actor_bounds(False)
        assert abs((o.z - e.z) - c1top) < 0.5                             # the cap lies on course 1
    hut = [b for b in doc['level_blocks'] if b['block'] == 'hut'][0]
    bots, tops = [], []
    for rid in hut['members']:
        o, e = actor(W, rid).get_actor_bounds(False)
        bots.append(o.z - e.z)
        tops.append(o.z + e.z)
    assert max(bots) - min(bots) < 0.5 and max(tops) - min(tops) < 0.5       # one base, one height
    assert abs(min(bots) - (po.z + pe.z)) < 0.5                                # on the plinth top
    assert abs(tops[0] - bots[0] - 326.0) < 1.0                                # the arch height
    for sp in hut['supports']:
        o, e = actor(W, sp['id']).get_actor_bounds(False)
        if sp['rule'] == 'on_members':
            assert abs((o.z - e.z) - max(tops)) < 0.5                          # the slab lies on the wall tops
            for sup in [r for r in RECS if r['id'] == sp['id']][0]['bears_on']:
                so, se = actor(W, sup).get_actor_bounds(False)
                assert abs(so.z + se.z - (o.z - e.z)) < 0.5
        if sp['rule'] == 'grade':
            g = max(G.gw(q[0] / 100, q[1] / 100) * 100 for q in grade_data())
            assert abs((o.z - e.z) - (g + sp['offset_cm'])) < 0.5                # the shutter sill 1 m over the door grade
        assert abs(o.x - sp['x']) < 0.5 and abs(o.y - sp['y']) < 0.5


def test_lines_and_hooks_steps():
    W = scene('base')
    doc = json.load(open(V.OUT_JSON, encoding='utf8'))
    run_body(W, V.GRID9_SRC + V.LEVEL_BODY, SITE=V.SID, BLOCKS=doc['level_blocks'], GRADE=grade_data())
    lines = [{k: v for k, v in ln.items() if k != 'note'} for ln in doc['lines']]
    mb = doc['story_hooks']['MastBase_cm']
    out = run_body(W, V.GRID9_SRC + V.LINES_BODY, SITE=V.SID, LINES=lines, GRADE=grade_data(), PIPE=V.EA_PIPE,
                   MAST=[V.O_CM[0], V.O_CM[1], mb[2] - 50, 25.0, 50.0], PLATE_UP=130.0, PLATE_HALF=22.5)
    assert sum(1 for line in out if line.startswith('LINE ')) == len(lines)
    assert all(' OK' in line for line in out if 'conduit' in line), out
    hv_z = [a for a in W.actors if a.label == 'HighVoice'][0].loc.z
    for ln in lines:
        a = actor(W, ln['id'])
        ends = a.corners()
        if ln['role'] == 'guy':
            top = max(p[2] for p in ends)
            assert abs(top - (hv_z + 2800.0)) < 3.0                            # it reaches the mast 28 m up
            anc = actor(W, ln['a']['actor'])
            ao, ae = anc.get_actor_bounds(False)
            assert min(p[2] for p in ends) < ao.z + ae.z + 3.0                 # and starts on its deadman
    hk = doc['story_hooks']
    out = run_body(W, V.GRID9_SRC + V.HOOKS_BODY, SITE=V.SID, GRADE=grade_data(), MB=mb, PLATE=hk['Plate']['centre_cm'],
                   PLATE_YAW=hk['Plate']['yaw'], PLATE_SIZE=hk['Plate']['size_cm'], PLATE_UP=130.0, PLATE_MESH=V.PLATE_MESH,
                   BRASS=V.BRASS, STAND=hk['StandPoint']['feet_cm'], STAND_YAW=hk['StandPoint']['yaw'], HALF=92.0,
                   SEAT=hk['SeatPoint']['cm'], SEAT_EYE=100.0, SEAT_YAW=-3.5, SEAT_PITCH=-4.0, MARK=True,
                   MARK_MESH=V.MARK_MESH, MARK_CM=34.0)
    assert any(line.startswith('HOOKS package') for line in out), out
    end = [a for a in W.actors if a.label == 'HighVoice_Ending'][0]
    comps = {c.name: c for c in end.comps}
    ftop = max(G.gw(q[0] / 100, q[1] / 100) * 100 for q in grade_data())      # the door grade
    sp = comps['StandPoint'].wloc
    assert abs(sp.z - (G.gw(sp.x / 100, sp.y / 100) * 100 + 92.0)) < 1.0      # the capsule centre over the ground
    pl = comps['Plate']
    assert pl.static_mesh is not None and abs(pl.wscale.x * 100 - 6.0) < 0.1
    assert abs(pl.wloc.z + 50 * pl.wscale.z - (ftop + 130.0)) < 0.5           # the plate centre 1.30 m over the grade
    riser = actor(W, V.SID + '_riser')
    assert abs(max(p[2] for p in riser.corners()) - (ftop + 130.0 - 22.5)) < 3.0   # the riser ends under the plate
