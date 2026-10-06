"""Offline safety checks for the two targeted ruin repairs."""

import ast
import json
import math
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "World"))
import fix_priority_sites as f  # noqa: E402


@pytest.fixture(scope="module")
def plan():
    # The approved removal snapshot remains valid test input after its actors are
    # intentionally deleted. Fresh editor validation still checks live inventory.
    return json.loads((f.OUT / 'priority_sites_plan.json').read_text(encoding='utf8'))


def test_exact_saved_actor_inventory_and_package_fingerprints(plan):
    old = plan["o05"]["old_remove"] + plan["s10"]["old_remove"]
    assert len(old) == 26
    assert len({a["guid"] for a in old}) == len(old)
    assert len({a["package"] for a in old}) == len(old)
    if any(not (ROOT / actor['file']).is_file() for actor in old):
        pytest.skip('Historical removal targets have been deleted; live validate must run before apply')
    for actor in old:
        path = ROOT / actor["file"]
        assert path.is_file()
        assert f.saved_actor(next(r for r in json.loads(f.DESCS.read_text())
                                  if r[3] == actor["label"])) == actor


def test_o05_ridge_footprints_are_supported_visible_and_clear_of_saved_actors(plan):
    candidates = plan["o05"]["new"]
    descs = json.loads(f.DESCS.read_text())
    for p in candidates:
        assert p["max_above_ground_cm"] <= 0
        assert p["max_burial_cm"] < 75
        assert p["minimum_clearance_m"] > 2
        assert p["distance_from_start_m"] < 725
        assert all(math.hypot((r[4] + r[7]) / 2 - p["x_cm"],
                              (r[5] + r[8]) / 2 - p["y_cm"]) > 3000 for r in descs)
    a, b = candidates
    spacing = math.hypot(a["x_cm"] - b["x_cm"], a["y_cm"] - b["y_cm"])
    assert spacing > 1500


def test_s10_removes_only_repeated_outer_wall_modules(plan):
    removed = plan["s10"]["old_remove"]
    assert {a["label"].rsplit("_", 1)[-1] for a in removed} == set(f.S10_REMOVE)
    assert all(a["mesh"].endswith("/SM_B01_wall01") for a in removed)
    assert not any("Arch" in a["mesh"] or "Tripo02" in a["mesh"] for a in removed)


def test_emitted_editor_steps_are_scoped_and_syntactically_valid(plan, tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path)
    for action in ("validate", "apply", "save"):
        path = f.write_editor_script(plan, action)
        source = path.read_text()
        compile(source, str(path), "exec")
        assert "actor_guid" in source and "package drift" in source
        assert "save_current_level" not in source
        assert f"ACTION = '{action}'" in source


def test_spawn_rotation_assigns_yaw_by_keyword(plan, tmp_path, monkeypatch):
    """UE's positional Rotator constructor uses roll, pitch, yaw order."""
    monkeypatch.setattr(f, "OUT", tmp_path)
    source = f.write_editor_script(plan, "apply").read_text()
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "Rotator"
             and any("row['yaw']" in ast.unparse(arg) for arg in [*node.args, *(k.value for k in node.keywords)])]
    assert len(calls) == 1
    assert calls[0].args == []
    values = {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}
    assert values == {"pitch": "0.0", "yaw": "row['yaw']", "roll": "0.0"}


def test_save_splits_packages_across_separate_editor_calls():
    rows = [{'label': f'old_{i}', 'package': f'old_package_{i}'} for i in range(26)]
    actor = SimpleNamespace(get_actor_label=lambda: 'new_actor', get_package=lambda: 'new_package',
                            static_mesh_component=SimpleNamespace(static_mesh=SimpleNamespace(
                                get_path_name=lambda: '/Game/new_mesh.new_mesh')))
    calls = []
    env = dict(world=SimpleNamespace(get_path_name=lambda: '/Game/level/Saskarta_WP.Saskarta_WP'),
               eas=SimpleNamespace(get_all_level_actors=lambda: [actor]), ACTION='save',
               PLAN={'o05': {'old_remove': rows, 'new': [{'label': 'new_actor', 'mesh': '/Game/new_mesh'}]},
                     's10': {'old_remove': [], 'new': []}},
               unreal=SimpleNamespace(find_package=lambda path: path,
                   EditorLoadingAndSavingUtils=SimpleNamespace(save_packages=lambda packages, dirty: calls.append(list(packages)) or True)))
    for batch in (0, 1):
        exec(f.EDITOR_BODY, dict(env, SAVE_BATCH_INDEX=batch))
    assert [len(call) for call in calls] == [20, 7]
    assert [package for call in calls for package in call] == ['new_package'] + [row['package'] for row in rows]


def test_failed_save_does_not_claim_success():
    actor = SimpleNamespace(get_actor_label=lambda: 'new_actor', get_package=lambda: 'new_package',
                            static_mesh_component=SimpleNamespace(static_mesh=SimpleNamespace(
                                get_path_name=lambda: '/Game/new_mesh.new_mesh')))
    env = dict(world=SimpleNamespace(get_path_name=lambda: '/Game/level/Saskarta_WP.Saskarta_WP'),
               eas=SimpleNamespace(get_all_level_actors=lambda: [actor]), ACTION='save', SAVE_BATCH_INDEX=0,
               PLAN={'o05': {'old_remove': [], 'new': [{'label': 'new_actor', 'mesh': '/Game/new_mesh'}]},
                     's10': {'old_remove': [], 'new': []}},
               unreal=SimpleNamespace(find_package=lambda path: path,
                   EditorLoadingAndSavingUtils=SimpleNamespace(save_packages=lambda packages, dirty: False)))
    with pytest.raises(RuntimeError, match='package save failed'):
        exec(f.EDITOR_BODY, env)


def test_tripo_helper_uses_separate_editor_calls_for_save_batches(monkeypatch):
    path = ROOT / 'Saved/Verification/world_placement/run_tripo_world.py'
    spec = importlib.util.spec_from_file_location('tripo_batch_runner_test', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls = []

    def fake_run(source):
        index = next(node.value.value for node in ast.parse(source).body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'SAVE_BATCH_INDEX' for target in node.targets))
        calls.append(index)
        return True, f'PRIORITY_SITE_SAVE batch={index} PASS', ''

    monkeypatch.setattr(runner, 'python_run', fake_run)
    monkeypatch.setattr(sys, 'argv', [str(path), 'o05', 'save'])
    runner.main()
    assert calls == [0, 1]
