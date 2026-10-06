"""Exercise descriptor identity guards with a tiny Unreal stand-in; no editor calls."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import pytest


def scripts():
    tree = ast.parse((Path(__file__).parents[1] / 'generate_tree_regions.py').read_text(encoding='utf-8'))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name == 'HEAD':
            values[name] = ast.literal_eval(node.value)
        elif name == 'LOAD':
            values[name] = values['HEAD'] + ast.literal_eval(node.value.right)
        elif name == 'SETUP':
            values[name] = values['HEAD'] + ast.literal_eval(node.value.right.func.value)
    return values


def harness(monkeypatch, count):
    descs = [NS(native_class=NS(get_name=lambda: 'PCGVolume'), label='PCG_Ecology_Trees_R0_0',
                guid=str(i), actor_path='/Game/World.Volume' + str(i),
                bounds=NS(min=NS(x=0, y=100), max=NS(x=100, y=200))) for i in range(count)]
    calls = []
    eas = NS(get_all_level_actors=lambda: [], spawn_actor_from_class=lambda *args: calls.append('spawn'))
    wpl = NS(get_intersecting_actor_descs=lambda box: descs, load_actors=lambda guids: calls.append(guids))
    monkeypatch.setitem(sys.modules, 'unreal', NS(get_editor_subsystem=lambda cls: eas,
        EditorActorSubsystem=object(), WorldPartitionBlueprintLibrary=wpl,
        Vector=lambda *args: args, Box=lambda *args: args))
    return calls


def test_duplicate_saved_regions_stop_before_loading_or_spawning(monkeypatch):
    calls = harness(monkeypatch, 2)
    for key in ('LOAD', 'SETUP'):
        with pytest.raises(RuntimeError, match='Duplicate saved'):
            exec(scripts()[key], {})
    assert calls == []


def test_unique_saved_volume_is_in_explicit_load_set(monkeypatch):
    calls = harness(monkeypatch, 1)
    exec(scripts()['LOAD'], {})
    assert calls == [['0']]


def test_setup_refuses_unloaded_saved_volume_instead_of_recreating_it(monkeypatch):
    calls = harness(monkeypatch, 1)
    with pytest.raises(RuntimeError, match='exact saved region volume must be loaded'):
        exec(scripts()['SETUP'], {})
    assert calls == []
