from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_dawn_pose_capture as capture


def test_preview_is_transient_and_never_saves_or_runs_gameplay(tmp_path):
    out=tmp_path/'packet';capture.prepare(out)
    setup=(out/'00_setup.py').read_text()
    assert 'unreal.SkeletalMeshActor' in setup and ',True)' in setup
    assert "body.set_editor_property('is_editor_only_actor',False)" in setup
    assert 'spawn_actor_from_class(unreal.SceneCapture2D, location, rotation, True)' in setup
    assert 'c.capture_scene()' not in setup
    assert "body.set_editor_property('tags',restore_tags)" in setup
    for script in out.glob('*.py'):
        code=script.read_text();compile(code,str(script),'exec')
        assert not any(word in code for word in ('save_asset','save_packages','editor_start_pie','tick_animation'))
    for path in out.glob('*_pump.py'):
        code=path.read_text()
        assert code.index("max(r['error_cm']")<code.index('c.capture_scene()')
        assert 'RTS_COMPONENT' in code
    for path in out.glob('*_pose.py'):
        code=path.read_text()
        assert code.index('mesh.set_position(')<code.index('mesh.override_animation_data(')
        assert 'mesh.set_update_animation_in_editor(False)' in code


def test_cleanup_is_idempotent_and_never_removes_an_unowned_actor():
    world=object();events=[]
    class Body:pass
    class Cap:pass
    class Sky:pass
    class MeshComponent:pass
    class CaptureComponent:pass
    target=object()
    mesh=SimpleNamespace(set_update_animation_in_editor=lambda value:events.append('stop_editor_tick'),stop=lambda:events.append('stop_animation'))
    component=SimpleNamespace(get_editor_property=lambda _:target,set_editor_property=lambda *_:events.append('detach_target'))
    def actor(cls,label):
        value=cls();value.tags=[capture.TAG,'GroundCaptureSkyRestore:sky']
        value.get_world=lambda:world;value.get_actor_label=lambda:label
        value.get_component_by_class=lambda kind:mesh if kind is MeshComponent else component
        return value
    body=actor(Body,capture.BODY);cap=actor(Cap,capture.CAPTURE)
    sky=SimpleNamespace(get_world=lambda:world,get_path_name=lambda:'sky',set_real_time_capture=lambda v:events.append('restore_sky'))
    inventory={Body:[body],Cap:[cap],Sky:[sky]}
    def destroy(value):
        inventory[type(value)].remove(value);events.append('destroy_'+value.get_actor_label());return True
    unreal=SimpleNamespace(EditorActorSubsystem=object(),SkeletalMeshActor=Body,SceneCapture2D=Cap,
        SkeletalMeshComponent=MeshComponent,SceneCaptureComponent2D=CaptureComponent,SkyLightComponent=Sky,
        get_editor_subsystem=lambda _:SimpleNamespace(destroy_actor=destroy),ObjectIterator=lambda cls:list(inventory[cls]),
        RenderingLibrary=SimpleNamespace(release_render_target2d=lambda _:events.append('release_target')))
    code=capture.CLEANUP[len(capture.HEAD):]
    import json
    scope=dict(unreal=unreal,world=world,json=json)
    exec(code,scope)
    assert events.index('restore_sky')<events.index('destroy_'+capture.BODY)
    assert events.index('release_target')<events.index('destroy_'+capture.CAPTURE)
    first=list(events);exec(code,dict(scope));assert events==first
    foreign=actor(Body,capture.BODY);foreign.tags=[];inventory[Body]=[foreign]
    with pytest.raises(AssertionError,match='unowned'):exec(code,dict(scope))
    assert events==first
