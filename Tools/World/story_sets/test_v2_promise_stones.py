"""Offline tests for V2 (the Promise Stones): the layout rules, the story frames and this set's own editor steps.

    python -m pytest Tools/World/story_sets/test_v2_promise_stones.py -q

The editor steps (stand, standcheck, inscribe, hooks) run against a small fake `unreal` module whose landscape is the
real Gaea heightmap, so the maths that stands the stones, judges their footprints and puts the inscription on the
tall stone's face is exercised before an editor lane ever runs it.
"""
import ast
import contextlib
import io
import json
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import v2_promise_stones as V  # noqa: E402
import place_setdress as ps  # noqa: E402

G, S, RECS, GRECS, TARGET = V.build()
NOTES, BAD = V.checks(G, S, RECS, GRECS, TARGET)
STONES = [r for r in RECS if r['contact'] == 'stand']


# ---------------------------------------------------------------------------- layout rules

def test_no_offline_violation():
    assert BAD == []


def test_every_asset_exists_on_disk():
    for r in RECS:
        assert os.path.exists(os.path.join(V.ROOT, 'Content', r['asset'][len('/Game/'):] + '.uasset')), r['asset']


def test_two_unequal_upright_stones():
    assert len(STONES) == 2
    tall = [s for s in S.items if s.get('stone') == 'tall'][0]
    short = [s for s in S.items if s.get('stone') == 'short'][0]
    for r in STONES:
        assert r['pitch'] == 90.0 and r['roll'] == 0.0
        assert r['settle']['mode'] == 'none'           # stood by `stand`, not by place_setdress settle
        assert r['size_m'][2] > r['size_m'][1] > r['size_m'][0]
    assert tall['pred']['top'] - short['pred']['top'] > 1.5   # the tops read unequal from the road
    assert tall['pred']['buried_min'] >= 0.15 and short['pred']['buried_min'] >= 0.15


def test_road_and_waystone_clearance():
    assert min(r['road_clear_m'] for r in RECS) >= V.CLEAR_M
    assert not any('WAYSTONE' in b or 'PATH over' in b for b in BAD)


def test_crown_in_the_notch_for_the_whole_hold():
    for eye in V.EYE_M:
        rows = V.glance_report(G, S, TARGET, eye)
        hold = [r for r in rows if V.GLANCE['ease_in_s'] <= r['t'] <= V.GLANCE['ease_in_s'] + V.GLANCE['hold_s']]
        assert hold and all(r['crown_in_gap'] for r in hold)
        assert all(r['crown_clear'] for r in rows)
    assert V.crown_occlusion(G, S) == []
    assert V.standing_frame(G, S)['framed']


def test_new_target_is_in_the_gap_and_low():
    gx, gy = S.frame['gap']
    assert math.hypot(TARGET[0] - gx, TARGET[1] - gy) < 0.01
    up = TARGET[2] - G.z(TARGET[0], TARGET[1])
    assert 2.0 < up < 10.0          # the old target stood 16 m up and aimed the hold into the sky


def test_records_carry_what_place_setdress_needs():
    need = ('id', 'key', 'asset', 'kind', 'cat', 'x_cm', 'y_cm', 'ground_z_cm', 'yaw', 'pitch', 'roll', 'scale', 'settle',
            'folder', 'ism', 'stack', 'attach', 'collision', 'foliage_exclude', 'draw_distance_cm', 'cast_shadow', 'size_m',
            'contact', 'group')
    for r in RECS:
        for k in need:
            assert k in r, (r['id'], k)
        assert r['draw_distance_cm'] > 0
        assert 'verdict' not in r        # no Batch01 'check' asset: nothing needs an approval
    doc = json.load(open(V.OUT_JSON, encoding='utf8'))
    site = doc['sites'][0]
    assert site['id'] == V.SID and site['placements'] and site['ground'] and site['views']
    assert {v['name'] for v in site['views']} >= {'carrier_a', 'glance_hold', 'orbit_a', 'contact', 'standing', 'far300'}


# ---------------------------------------------------------------------------- the editor steps, against a fake unreal

class Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class Rot:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll, self.pitch, self.yaw = float(roll), float(pitch), float(yaw)


class Bounds:
    def __init__(self, o, e):
        self.origin, self.box_extent = Vec(*o), Vec(*e)


class Mesh:
    def __init__(self, o, e):
        self.b = Bounds(o, e)

    def get_bounds(self):
        return self.b


class Klass:
    def __init__(self, n):
        self.n = n

    def get_name(self):
        return self.n


class Pkg:
    def __init__(self, n):
        self.n = n

    def get_name(self):
        return self.n


class SMC:
    def __init__(self, mesh):
        self.static_mesh = mesh
        self.props = {}

    def set_editor_property(self, k, v):
        self.props[k] = v


class TRC:
    def __init__(self):
        self.text = ''
        self.props = {}

    def set_text(self, t):
        self.text = t

    def set_editor_property(self, k, v):
        self.props[k] = v

    def set_text_render_color(self, c):
        self.props['color'] = c

    def set_horizontal_alignment(self, a):
        pass

    def set_vertical_alignment(self, a):
        pass


class Actor:
    def __init__(self, label='', loc=(0, 0, 0), rot=(0, 0, 0), tags=(), mesh=None, cls='StaticMeshActor', scale=1.0):
        self.label, self.loc, self.rot = label, Vec(*loc), Rot(*rot)
        self.tags = list(tags)
        self.static_mesh_component = SMC(mesh) if mesh else None
        self.text_render = TRC() if cls == 'TextRenderActor' else None
        self.cls = cls
        self.scale = scale

    def get_class(self):
        return Klass(self.cls)

    def get_actor_label(self):
        return self.label

    def set_actor_label(self, n):
        self.label = n

    def get_actor_location(self):
        return self.loc

    def get_actor_rotation(self):
        return self.rot

    def get_actor_scale3d(self):
        return Vec(self.scale, self.scale, self.scale)

    def set_actor_location(self, v, sweep=False, teleport=False):
        self.loc = v

    def set_actor_location_and_rotation(self, v, r, sweep, teleport):
        self.loc, self.rot = v, r

    def set_editor_property(self, k, v):
        if k == 'tags':
            self.tags = [str(t) for t in v]

    def set_folder_path(self, p):
        self.folder = p

    def get_package(self):
        return Pkg('/Game/__ExternalActors__/level/Saskarta_WP/0/AA/' + self.label)


class Hit:
    def __init__(self, z, actor):
        self.t = (True, None, None, None, None, Vec(0, 0, z), None, Vec(0, 0, 1), None, actor)

    def to_tuple(self):
        return self.t


def fake_unreal(actors):
    land = Actor('Landscape', cls='LandscapeStreamingProxy')
    u = types.ModuleType('unreal')
    u.Vector, u.Rotator = Vec, Rot
    u.Name = str
    u.Color = lambda r=0, g=0, b=0, a=255: (r, g, b, a)
    u.TextRenderActor = 'TextRenderActor'
    u.HitResult = Hit
    u.TraceTypeQuery = types.SimpleNamespace(TRACE_TYPE_QUERY1=1)
    u.DrawDebugTrace = types.SimpleNamespace(NONE=0)
    u.StaticMeshActor = Actor

    class SysLib:
        @staticmethod
        def line_trace_single(world, a, b, ch, cx, ignore, dbg, self_ign):
            if land in ignore:
                return None
            z = G.z(a.x / 100.0, a.y / 100.0) * 100.0
            return Hit(z, land) if b.z <= z <= a.z else None
    u.SystemLibrary = SysLib

    class EAS:
        def spawn_actor_from_class(self, cls, loc, rot):
            a = Actor('', (loc.x, loc.y, loc.z), (rot.roll, rot.pitch, rot.yaw), cls=cls)
            a.loc, a.rot = loc, rot
            actors.append(a)
            return a

        def get_all_level_actors(self):
            return actors

    eas = EAS()

    class World:
        pass
    world = World()
    u.get_editor_subsystem = lambda cls: types.SimpleNamespace(get_editor_world=lambda: world) if cls == 'UES' else eas
    u.UnrealEditorSubsystem, u.EditorActorSubsystem = 'UES', 'EAS'
    u.EditorAssetLibrary = types.SimpleNamespace(does_asset_exist=lambda p: True)
    u.GameplayStatics = types.SimpleNamespace(
        get_all_actors_with_tag=lambda w, tag: [a for a in actors if str(tag) in a.tags])
    u.EditorLoadingAndSavingUtils = types.SimpleNamespace(save_packages=lambda pk, only_dirty: True)
    u.find_package = lambda n: Pkg(n)
    return u


def run_body(src, actors):
    sys.modules['unreal'] = fake_unreal(actors)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(ps.validate(src), '<v2>', 'exec'), {})
    return buf.getvalue()


def placed_stones(origin=(3.0, -2.0, 34.5)):
    """The stones as `place` leaves them (bounds centre at x, y; any z), with an off-centre mesh origin."""
    sx, sy, sz = V.CAT['FAB_TempleStones']['size_cm']
    out = []
    for r in STONES:
        m = Mesh(origin, (sx / 2, sy / 2, sz / 2))
        out.append(Actor('SD_' + r['id'], (r['x_cm'], r['y_cm'], r['ground_z_cm'] + 900.0), (0.0, 90.0, r['yaw']),
                         tags=['SetDress', 'SD_' + V.SID], mesh=m, scale=r['scale']))
    return out


def stand_args():
    return [dict(id=p['id'], x_cm=p['x_cm'], y_cm=p['y_cm'], yaw=p['yaw'], pitch=p['pitch'],
                 sink_cm=float(p['settle']['sink_cm']), ground_z_cm=p['ground_z_cm']) for p in STONES]


def doc():
    return json.load(open(V.OUT_JSON, encoding='utf8'))


def test_stand_then_standcheck_pass_and_match_the_prediction():
    actors = placed_stones()
    out = run_body(ps.build_script(V.GRID_SRC + V.STAND_BODY, SITE=V.SID, STONES=stand_args()), actors)
    assert out.count('STAND S04') == 2, out
    for a, r in zip(actors, STONES):
        assert a.static_mesh_component.props.get('receives_decals') is False
        assert abs(a.rot.pitch - 90.0) < 1e-6 and a.rot.roll == 0.0
    d = doc()
    ins = d['sites'][0]['inscription']
    tall = [p for p in d['sites'][0]['placements'] if p['id'] == ins['stone_id']][0]
    out = run_body(ps.build_script(V.GRID_SRC + V.INSCRIBE_BODY, SITE=V.SID, STONE=ins['stone_id'],
                                   LINES=[{k: ln[k] for k in ('id', 'text', 'world_size_cm', 'up_from_face_foot_cm')}
                                          for ln in ins['lines']],
                                   OUT=float(ins['out_cm']), COLOR=ins['color_rgb'], SINK=float(tall['settle']['sink_cm'])),
                   actors)
    assert 'INSCRIBE made=2' in out, out
    out = run_body(ps.build_script(V.GRID_SRC + V.STANDCHECK_BODY, SITE=V.SID, STONES=stand_args()), actors)
    reps = {}
    for line in out.splitlines():
        if line.startswith('SC {'):
            r = ast.literal_eval(line[3:])
            reps[r['id']] = r
    assert V.judge_stand(reps, d) == []
    for r in STONES:
        assert abs(reps[r['id']]['top'] - r['stand']['top_z_cm']) < 3.0      # the frames were judged on this top
        assert max(reps[r['id']]['gaps']) <= -r['settle']['sink_cm'] + 0.5


def test_inscription_sits_on_the_road_face_of_the_tall_stone():
    actors = placed_stones()
    run_body(ps.build_script(V.GRID_SRC + V.STAND_BODY, SITE=V.SID, STONES=stand_args()), actors)
    d = doc()
    ins = d['sites'][0]['inscription']
    run_body(ps.build_script(V.GRID_SRC + V.INSCRIBE_BODY, SITE=V.SID, STONE=ins['stone_id'],
                             LINES=[{k: ln[k] for k in ('id', 'text', 'world_size_cm', 'up_from_face_foot_cm')}
                                    for ln in ins['lines']],
                             OUT=3.0, COLOR=[38, 30, 24], SINK=38.0), actors)
    texts = [a for a in actors if a.text_render is not None]
    assert [t.text_render.text for t in texts] == list(V.TEXT_LINES)
    tall = [a for a in actors if a.label == 'SD_' + ins['stone_id']][0]
    fwd = (math.cos(math.radians(tall.rot.yaw)), math.sin(math.radians(tall.rot.yaw)))
    for t in texts:
        # in front of the stone (toward the road), facing back along the stone's yaw + 180
        d_ = (t.loc.x - tall.loc.x) * fwd[0] + (t.loc.y - tall.loc.y) * fwd[1]
        assert d_ < 0
        assert abs(((t.rot.yaw - tall.rot.yaw - 180.0) + 180.0) % 360.0 - 180.0) < 1e-6
        assert 120.0 < t.loc.z - G.z(t.loc.x / 100.0, t.loc.y / 100.0) * 100.0 < 220.0


def test_judge_stand_catches_float_tilt_and_missing_text():
    d = doc()
    ok = {}
    for r in STONES:
        ok[r['id']] = dict(id=r['id'], rot=[r['yaw'], 90.0, 0.0], loc=[0, 0, 0], top=r['stand']['top_z_cm'],
                           base=r['stand']['base_z_cm'], gaps=[-30.0] * 16, hits=['landscape'] * 4)
    ok['text'] = dict(id='text', lines=[['a', 0, 0, 0], ['b', 0, 0, 0]])
    assert V.judge_stand(ok, d) == []
    bad = json.loads(json.dumps(ok))
    s0 = STONES[0]['id']
    bad[s0]['gaps'][5] = -3.0
    bad[s0]['rot'][1] = 88.0
    bad['text']['lines'] = []
    codes = {c for _, c, _ in V.judge_stand(bad, d)}
    assert {'FLOAT', 'TILT', 'INSCRIPTION'} <= codes


def test_hooks_moves_the_one_tagged_target():
    tp = Actor('Glance_PromiseStones', V.OLD_TARGET_CM, tags=[V.TARGET_TAG], cls='TargetPoint')
    new = doc()['sites'][0]['story_hooks']['GlanceTarget']['new_cm']
    out = run_body(ps.build_script(V.HOOKS_BODY, TAG=V.TARGET_TAG, NEW=new), [tp])
    assert 'HOOKS found 1' in out and 'HOOKS package ' in out
    assert (tp.loc.x, tp.loc.y, tp.loc.z) == tuple(float(c) for c in new)
