"""Pure regressions for CHECK2's rest-prop samples and support policy."""
import os
import sys
import ast
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import place_setdress as ps
import setdress_contact as sc

M = {}
exec(ps.MATH_SRC, M)


def test_tilted_rest_prop_uses_full_bound_grid_and_edge_support_passes():
    points = M['contact_samples']((0.0, 0.0, 50.0), (100.0, 60.0, 50.0), 1.0,
                                 (30.0, 18.0, -7.0), (400.0, -250.0, 1000.0), 1.0)
    assert len(points) == 9
    # First point is the transformed full-bound corner. A tilted box may touch only at this edge.
    gaps = [24.0] * 9
    gaps[0] = -2.0
    item = {'cat': 'prop', 'contact': 'rest', 'attach': False}
    rep = {'gaps': gaps, 'hits': []}

    assert sc.contact_violations(rep, item) == []


def test_rest_prop_still_fails_when_every_full_bound_sample_floats():
    item = {'cat': 'prop', 'contact': 'rest', 'attach': False}
    rep = {'gaps': [13.0] * 9, 'hits': []}

    assert sc.contact_violations(rep, item)[0][0] == 'FLOAT'


def test_unstacked_rest_requires_landscape_while_stacks_accept_real_support_not_hlod():
    cart = {'contact': 'rest', 'stack': False}
    stack = {'contact': 'rest', 'stack': True}

    assert M['ground_only_contact'](cart)
    assert not M['support_kind_allowed'](cart, 'actor')
    assert not M['support_kind_allowed'](cart, 'ism')
    assert M['support_kind_allowed'](cart, 'landscape')
    assert not M['ground_only_contact'](stack)
    assert M['support_kind_allowed'](stack, 'actor')
    assert M['support_kind_allowed'](stack, 'ism')
    assert not M['support_kind_allowed'](stack, 'hlod')
    assert M['is_hlod_class']('WorldPartitionHLOD')
    assert M['is_hlod_class']('WorldPartitionHLODProxy')
    assert not M['is_hlod_class']('StaticMeshActor')


def test_editor_check2_script_compiles_with_shared_full_bound_and_support_helpers():
    script = ps.build_script(ps.CHECK2_BODY, SITE='S', ITEMS=[])
    ps.validate(script)
    assert 'contact_samples(org, ext, sc' in ps.CHECK2_BODY
    assert 'trace_support(x, y' in ps.CHECK2_BODY
    assert 'trace_support(x, y' in ps.SETTLE_BODY


def test_generated_trace_support_skips_hlod_and_fails_closed_at_pass_limit():
    script = ps.build_script(ps.SETTLE_BODY, SITE='S', ITEMS=[], LATER=[], OVERHEAD=[])
    ps.validate(script)
    assert ps.TRACE_SUPPORT_SRC.strip() in script

    class Actor:
        def __init__(self, name, tags=()):
            self.name = name
            self.tags = list(tags)

        def get_class(self):
            return SimpleNamespace(get_name=lambda: self.name)

    landscape = Actor('Landscape')
    hlod = Actor('WorldPartitionHLOD')
    ism = Actor('StaticMeshActor', ['SD_ism'])
    hits = [hlod, ism]
    trace_calls = []

    def fake_trace_down(x, y, ztop, zbot, ignore):
        trace_calls.append(list(ignore))
        for index, actor in enumerate(hits):
            if actor not in ignore:
                return (100.0 - index, (0.0, 0.0, 1.0), actor)
        return None

    def fake_trace_ground(x, y, ztop, zbot, ignore):
        return (0.0, (0.0, 0.0, 1.0), landscape)

    def fake_is_land(actor):
        return actor.name == 'Landscape'

    env = dict(M, trace_down=fake_trace_down, trace_ground=fake_trace_ground, is_land=fake_is_land)
    exec(ps.TRACE_SUPPORT_SRC, env)
    stack = {'contact': 'rest', 'stack': True}
    result = env['trace_support'](0.0, 0.0, 1000.0, -1000.0, [], stack)
    assert result[2] is ism
    assert trace_calls[1] == [hlod]

    hits[:] = [Actor('WorldPartitionHLOD%d' % index) for index in range(8)]
    trace_calls.clear()
    assert env['trace_support'](0.0, 0.0, 1000.0, -1000.0, [], stack) is None
    assert len(trace_calls) == 8

    trace_calls.clear()
    cart = {'contact': 'rest', 'stack': False}
    assert env['trace_support'](0.0, 0.0, 1000.0, -1000.0, [], cart)[2] is landscape
    assert trace_calls == []


def test_generated_ism_sampler_never_accepts_first_hlod_hit_in_legacy_mode():
    """Execute the real generated sampler, with the legacy flag that exposed S09."""
    sampler = next(n for n in ast.walk(ast.parse(ps.ISM_BODY))
                   if isinstance(n, ast.FunctionDef) and n.name == 'tr')
    calls = []
    env = dict(GROUND_ONLY=False, gz=100.0, host=object(),
               trace_down=lambda *args: (calls.append('hlod') or (296.0, (0, 0, 1), object())),
               trace_ground=lambda *args: (calls.append('landscape') or (100.0, (0, 0, 1), object())))
    exec(compile(ast.Module(body=[sampler], type_ignores=[]), '<real ISM sampler>', 'exec'), env)
    assert env['tr'](1.0, 2.0)[0] == 100.0
    assert calls == ['landscape']


@pytest.mark.parametrize('v2', [False, True])
@pytest.mark.parametrize('fault', ['missing', 'partial_instance', 'partial_host', 'different_selection', 'float', 'none'])
def test_both_save_modes_require_complete_current_ism_evidence(monkeypatch, v2, fault):
    items = [{'id': 'S_test_shrub_0', 'ism': True}]
    report = dict(measured=0, expected=0, selection=ps.selection_token(items, v2),
                  ism_measured=1, ism_expected=1, ism_hosts_measured=1,
                  ism_hosts_expected=1, violations=[])
    state = {'dirty': False, 'check2': report}
    if fault == 'missing':
        state.pop('check2')
    elif fault == 'partial_instance':
        report['ism_measured'] = 0
    elif fault == 'partial_host':
        report['ism_hosts_measured'] = 0
    elif fault == 'different_selection':
        report['selection'] = 'old-source'
    elif fault == 'float':
        report['violations'] = [['S_test_shrub_0', 'FLOAT', '196cm above terrain']]
    sent = []

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, script):
            sent.append(name)
            return 'SAVE 1 ok=True total=1 DONE'

    monkeypatch.setattr(ps, 'Runner', OfflineRunner)
    monkeypatch.setattr(ps, 'load_doc', lambda _v2: {'sites': [{'id': 'S_test'}]})
    monkeypatch.setattr(ps, 'select', lambda *_: (items, []))
    monkeypatch.setattr(ps, 'read_state', lambda *_: state)
    monkeypatch.setattr(ps, 'write_state', lambda *_: None)
    monkeypatch.setattr(ps, 'gate_check', lambda *_: None)
    monkeypatch.setattr(sys, 'argv', ['place_setdress.py', 'save', 'S_test'] + (['--v2'] if v2 else []))
    if fault == 'none':
        ps.main()
        assert sent == ['S_test_save']
    else:
        with pytest.raises(SystemExit, match='refusing to save'):
            ps.main()
        assert sent == [], 'incomplete contact evidence must stop before any editor request'


def test_ism_partial_landscape_footprint_cannot_authorize_save():
    assert ps.ism_gap_violation([0.0, None, None, None, None], {'cat': 'shrub'})[0] == 'NOGROUND'


@pytest.mark.parametrize('mode', ['ground', 'shared_pivot', 'attached_height', 'no_pose'])
def test_solo_settle_marks_actor_and_root_before_runtime_transform(mode):
    calls = []

    class Actor:
        def modify(self):
            calls.append('actor_modify')

        def get_editor_property(self, key):
            assert key == 'root_component'
            return SimpleNamespace(modify=lambda: calls.append('root_modify'))

        def get_actor_location(self):
            return SimpleNamespace(x=10.0, y=20.0, z=30.0)

        def get_actor_rotation(self):
            return SimpleNamespace(yaw=0.0, pitch=0.0, roll=0.0)

        def set_actor_location_and_rotation(self, *_):
            self.set_actor_location()

        def set_actor_location(self, *_):
            assert calls == ['actor_modify', 'root_modify'], 'clean existing actor must be dirtied before its transform changes'
            calls.append('set_pose')

    item = dict(id='prop', attach=mode in ('shared_pivot', 'attached_height'), parent='parent',
                shares_pivot=mode == 'shared_pivot', ground_z_cm=0.0, size_m=[1, 1, 1],
                x_cm=0, y_cm=0, yaw=0, pitch=0, roll=0,
                settle=dict(mode='trace', z_offset_cm=0, drop_cm=0, sink_cm=0,
                            max_tilt_deg=20, rand_tilt_deg=0, z_rule='min'))
    actor = Actor()
    env = dict(SITE='S_test', ITEMS=[item], LATER=[], OVERHEAD=[],
               site_actors=lambda _: {'SD_prop': actor, 'SD_parent': Actor()},
               V=lambda *args: args, unreal=SimpleNamespace(Rotator=lambda **kw: kw),
               local_bounds=lambda *_: ((0, 0, 0), []), rng=None,
               settle_pose=lambda *_: None if mode == 'no_pose' else (0, 0, 0, 0, 0, 0, {}))
    exec(ps.SETTLE_BODY, env)
    assert calls == ([] if mode == 'no_pose' else ['actor_modify', 'root_modify', 'set_pose'])
