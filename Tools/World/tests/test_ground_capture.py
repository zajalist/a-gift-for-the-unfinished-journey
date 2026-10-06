import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_ground_capture as capture


def test_scene_capture_is_transient_and_independent_of_native_helper():
    assert 'spawn_actor_from_class(unreal.SceneCapture2D, location, rotation, True)' in capture.SETUP
    assert 'SCS_FINAL_COLOR_LDR' in capture.SETUP
    assert 'RTF_RGBA8_SRGB' in capture.SETUP
    assert "'capture_every_frame',False" in capture.SETUP
    assert 'HaybaMCPCaptureActor' not in capture.SETUP


def test_original_realtime_sky_flags_are_recorded_before_mutation():
    assert capture.SETUP.index("cap.set_editor_property('tags', restore_tags)") < capture.SETUP.index('s.set_real_time_capture(False)')
    assert capture.CLEANUP.index('s.set_real_time_capture(True)') < capture.CLEANUP.index('eas.destroy_actor(cap)')
    assert 'set(restored)!=set(restore)' in capture.CLEANUP


def test_capture_helper_cannot_save_or_destroy_unowned_actors():
    assert "'__TAG__' not in" in capture.OWNED
    assert 'eas.destroy_actor(cap)' in capture.CLEANUP
    for code in (capture.SETUP, capture.PUMP, capture.EXPORT, capture.CLEANUP):
        assert 'save_packages' not in code
        assert 'save_asset' not in code


def test_transient_capture_lookup_includes_object_iterator_and_current_world():
    # EditorActorSubsystem deliberately filters out transient actors.
    for code in (capture.SETUP, capture.OWNED):
        assert 'unreal.ObjectIterator(unreal.SceneCapture2D)' in code
        assert 'a.get_world() == world' in code
    assert 'matches = [a for a in eas.get_all_level_actors()' not in capture.OWNED
    assert 'unreal.ObjectIterator(unreal.SkyLightComponent)' in capture.CLEANUP
    assert 's.get_world() == world and s.get_path_name() in restore' in capture.CLEANUP


def test_export_names_the_png_extension_explicitly():
    assert "'__DIRECTORY__','__NAME__.png'" in capture.EXPORT


def test_lookup_recovers_transient_current_world_capture_and_rejects_unowned():
    world = object()
    component = object()

    class Actor:
        def __init__(self, actor_world, tags):
            self.world = actor_world
            self.tags = tags

        def get_world(self):
            return self.world

        def get_actor_label(self):
            return capture.LABEL

        def get_component_by_class(self, _kind):
            return component

    current = Actor(world, [capture.TAG])
    other = Actor(object(), [capture.TAG])
    eas = SimpleNamespace(get_all_level_actors=lambda: [])
    unreal = SimpleNamespace(EditorActorSubsystem=object(), SceneCapture2D=object(),
                             SceneCaptureComponent2D=object(),
                             get_editor_subsystem=lambda _kind: eas,
                             ObjectIterator=lambda _kind: [other, current])
    code = capture.OWNED[len(capture.HEAD):].replace('__LABEL__', capture.LABEL).replace('__TAG__', capture.TAG)
    scope = dict(unreal=unreal, world=world)
    exec(code, scope)
    assert scope['cap'] is current
    assert scope['c'] is component
    current.tags = []
    with pytest.raises(RuntimeError, match='Exactly one owned'):
        exec(code, dict(unreal=unreal, world=world))
