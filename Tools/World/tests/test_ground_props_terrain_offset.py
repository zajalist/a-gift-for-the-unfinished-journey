"""Regression tests for measured landscape heights on regraded terrain."""

import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ground_props


def test_landscape_trace_offset_preserves_large_regrade():
    assert ground_props.landscape_offset(250.0, 150.0) == 100.0
    assert ground_props.landscape_offset(40.0, 150.0) == -110.0


def test_missing_landscape_trace_cannot_use_heightmap_baseline():
    with pytest.raises(ValueError, match="Current landscape trace required"):
        ground_props.landscape_offset(None, 150.0)


def test_plan_never_accepts_or_moves_unmeasured_prop(monkeypatch):
    def forbidden_heightmap(*_args):
        raise AssertionError("No fallback heightmap read is allowed for a missing current trace")
    monkeypatch.setattr(ground_props, 'ground', forbidden_heightmap)
    row = ['guid', 'SD_Cart', '/Game/Cart', [0, 0, 100], [0, 0, 0],
           [['Cart', [[0, 0, 95]]]], [], '/Game/Package']
    plan, reason = ground_props.plan(row)
    assert plan is None
    assert reason.startswith('unknown: current landscape not hit')


def test_following_old_root_offset_also_requires_current_terrain(monkeypatch, tmp_path):
    monkeypatch.setattr(ground_props, 'OUT', tmp_path)
    monkeypatch.setattr(ground_props, 'batch', lambda _n: [{'guid': 'child', 'follow': 'old-root'}])
    row = ['child', 'SD_Child', '/Game/Child', [0, 0, 100], [0, 0, 0], [], [], '/Game/Package']
    (tmp_path / 'measure_0.json').write_text(json.dumps([row]))
    (tmp_path / 'dz.json').write_text(json.dumps({'old-root': -90}))
    assert ground_props.main(['plan', '0']) == 0
    result = json.loads((tmp_path / 'plan_0.json').read_text())
    assert result['plan'] == {}
    assert result['log'][0]['result'].startswith('unknown: current landscape not hit')
