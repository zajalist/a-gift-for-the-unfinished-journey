import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setdress_contact as sc


def placement(id_, **kwargs):
    item = {
        'id': id_,
        'key': id_,
        'block': 'test_unit',
        'cat': 'cloth',
        'contact': 'rest',
        'attach': False,
        'x_cm': 100.0,
        'y_cm': 200.0,
        'yaw': 15.0,
        'pitch': 0.0,
        'roll': 0.0,
        'scale': 1.0,
        'settle': {'z_offset_cm': 0.0},
    }
    item.update(kwargs)
    return item


def report(id_, loc, rot=(15.0, 0.0, 0.0), scale=1.0, gaps=None):
    return {
        'id': id_,
        'loc': list(loc),
        'rot': list(rot),
        'scale': scale,
        'origin': [0.0, 0.0, 0.0],
        'extent': [10.0, 10.0, 10.0],
        'gaps': [0.0] * 9 if gaps is None else gaps,
        'hits': [],
    }


def test_shared_pivot_attachment_is_supported_by_measured_parent_not_landscape():
    items = {
        'frame': placement('frame', cat='wood'),
        'cloth': placement('cloth', attach=True, parent='frame', shares_pivot=True),
    }
    reps = {
        'frame': report('frame', (100.0, 200.0, 300.0)),
        # The cloth is well above the landscape, but exactly shares its frame's transform.
        'cloth': report('cloth', (100.0, 200.0, 300.0), gaps=[175.0] * 9),
    }

    assert sc.judge(reps, items)[0] == []


def test_shared_pivot_attachment_checks_explicit_vertical_offset():
    items = {
        'frame': placement('frame', cat='wood'),
        'cloth': placement('cloth', attach=True, parent='frame', shares_pivot=True,
                           settle={'z_offset_cm': 110.0}),
    }
    reps = {
        'frame': report('frame', (100.0, 200.0, 300.0)),
        'cloth': report('cloth', (100.0, 200.0, 410.0)),
    }

    assert sc.judge(reps, items)[0] == []


def test_shared_pivot_attachment_fails_when_transform_drifts():
    items = {
        'frame': placement('frame', cat='wood'),
        'cloth': placement('cloth', attach=True, parent='frame', shares_pivot=True),
    }
    reps = {
        'frame': report('frame', (100.0, 200.0, 300.0)),
        'cloth': report('cloth', (120.0, 200.0, 300.0)),
    }

    violations, _ = sc.judge(reps, items)
    assert [(v[0], v[1]) for v in violations] == [('cloth', 'DETACHED')]


def test_attachment_fails_closed_for_missing_or_unmeasured_parent():
    child = placement('cloth', attach=True, parent='frame', shares_pivot=True)
    child_rep = report('cloth', (100.0, 200.0, 300.0))

    missing_source, _ = sc.judge({'cloth': child_rep}, {'cloth': child})
    assert [(v[0], v[1]) for v in missing_source] == [('cloth', 'DETACHED')]

    unmeasured_parent, _ = sc.judge(
        {'cloth': child_rep},
        {'cloth': child, 'frame': placement('frame', cat='wood')},
    )
    assert [(v[0], v[1]) for v in unmeasured_parent] == [('cloth', 'DETACHED')]


def test_attachment_requires_named_parent():
    child = placement('cloth', attach=True, shares_pivot=True)
    violations, _ = sc.judge({'cloth': report('cloth', (100.0, 200.0, 300.0))}, {'cloth': child})
    assert [(v[0], v[1]) for v in violations] == [('cloth', 'DETACHED')]


def test_non_shared_attachment_checks_authored_xy_rotation_and_parent_height():
    items = {
        'frame': placement('frame', cat='wood'),
        'attached': placement('attached', attach=True, parent='frame', shares_pivot=False,
                              x_cm=500.0, y_cm=600.0, yaw=25.0, pitch=2.0, roll=-3.0,
                              settle={'z_offset_cm': 40.0}),
    }
    reps = {
        'frame': report('frame', (100.0, 200.0, 300.0)),
        'attached': report('attached', (500.0, 600.0, 340.0), rot=(25.0, 2.0, -3.0)),
    }

    assert sc.judge(reps, items)[0] == []
    reps['attached']['loc'][2] += 20.0
    violations, _ = sc.judge(reps, items)
    assert [(v[0], v[1]) for v in violations] == [('attached', 'DETACHED')]


def test_all_missing_landscape_samples_are_a_violation_for_rest_items():
    item = placement('prop')
    rep = report('prop', (100.0, 200.0, 300.0), gaps=[None] * 9)

    violations, _ = sc.judge({'prop': rep}, {'prop': item})
    assert [(v[0], v[1]) for v in violations] == [('prop', 'NOGROUND')]
