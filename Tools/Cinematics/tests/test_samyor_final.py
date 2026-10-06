"""Offline collapse grip/continuity checks against the production pose generator."""
from pathlib import Path
import math
import sys
import ast
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import samyor_final as final
import samyor_reveal as reveal
import build_cinematics as cinematics
import traveller_contacts as contacts
import traveller_terrain as terrain
import ending_staging as staging


def test_final_body_is_lying_on_its_surface_with_an_upright_actor_frame():
    """The old actor-roll workaround left a seated silhouette in mid-air."""
    vertices = contacts.skin(final.pose_at(final.COLLAPSE_S))
    assert terrain.clearances(vertices, staging.SUN_BEARING-90).min() == pytest.approx(0.4, abs=0.02)
    assert vertices[:, 2].max() < 65.0
    world = reveal.fk(final.pose_at(final.COLLAPSE_S))
    assert abs(world['Head'][0][2] - world['Hips'][0][2]) < 18.0


def test_staff_keeps_the_grip_until_it_slips_during_the_fall():
    for i in range(115):
        t = final.COLLAPSE_S * i / 114
        pose = final.pose_at(t)
        world = reveal.fk(pose)
        staff = world['staff011']
        expected = reveal.xcompose((world['RightHand'][0], world['RightHand'][1]), reveal.G_SI)
        if t <= 2.0:
            assert reveal.vlen(reveal.vsub(staff[0], expected[0])) < 0.001, t
            assert abs(sum(a * b for a, b in zip(staff[1], expected[1]))) == pytest.approx(1, abs=0.00001), t
        assert pose['Neck'][2] == (1, 1, 1)
        assert pose['Head'][2] == reveal.REF_LOCAL['Head'][2]
        assert all(math.isfinite(v) for state in pose.values() for values in state for v in values)


def test_final_still_is_exactly_the_collapse_endpoint_and_does_not_reanimate():
    baked = final.baked()
    count, fall = baked['A_Samyor_FinalCollapse']
    still_count, still = baked['A_Samyor_FinalStill']
    assert count / final.FPS == final.COLLAPSE_S
    assert still_count == final.FPS
    for bone in final.TRACKS:
        assert all(state == fall[bone][-1] for state in still[bone])
        assert len(fall[bone]) == count + 1


def test_final_animation_chunks_compile_and_save_separately(tmp_path):
    final.emit_anims(tmp_path)
    for script in tmp_path.glob('*.py'):
        code = script.read_text(encoding='utf-8')
        compile(code, str(script), 'exec')
        assert not any(word in code for word in ('try', 'getattr', 'import time', 'open(', '.replace(', 'new_level('))
        if '_save_' in script.name:
            assert 'save_asset' in code and 'saved' in code
        else:
            assert 'save_asset' not in code


def test_cin24_to_cin25_holds_the_identical_camera_body_and_staff_pose():
    transmission, credits = cinematics.plan_cin24(), cinematics.plan_cin25()
    last_camera = transmission['cams'][0]['keys'][-1][1:7]
    assert all(key[1:7] == last_camera for key in credits['cams'][0]['keys'])
    post = cinematics.radio_post()
    last_body = cinematics.radio_body_transform(post, transmission['duration'])[-1][1:7]
    assert all(key[1:7] == last_body for key in cinematics.radio_body_transform(post, credits['duration'], True))
    assert 'A_Samyor_FinalStill' in transmission['extra']['20_samyor.py']
    assert 'A_Samyor_FinalStill' in credits['extra']['20_samyor.py']


@pytest.mark.parametrize('change', ['none', 'missing', 'extra', 'duplicate', 'wrong_rate',
                                  'wrong_denominator', 'wrong_frames', 'wrong_keys', 'wrong_length'])
def test_generated_acceptance_source_frames_and_case_insensitive_exact_tracks(monkeypatch, change):
    """UE resamples at 30 fps and FName may stringify in lowercase."""
    module = ast.parse(final.readback_chunk())
    metadata = ast.Module(body=module.body[:3], type_ignores=[])
    tracks = [bone.lower() for bone in final.TRACKS]
    if change == 'missing':
        tracks.pop()
    elif change == 'extra':
        tracks.append('root')
    elif change == 'duplicate':
        tracks.append(tracks[0])

    def load_asset(package):
        frames = 57 if package.endswith('FinalCollapse') else 15
        model = SimpleNamespace(
            get_frame_rate=lambda: SimpleNamespace(numerator=30 if change == 'wrong_rate' else 15,
                                                   denominator=2 if change == 'wrong_denominator' else 1),
            get_number_of_frames=lambda: frames * 2 if change == 'wrong_frames' else frames,
            get_number_of_keys=lambda: frames if change == 'wrong_keys' else frames + 1)
        return SimpleNamespace(get_play_length=lambda: frames / (30 if change == 'wrong_length' else 15), get_editor_property=lambda key: model,
                               sampled_frames=frames * 2)

    monkeypatch.setitem(sys.modules, 'unreal', SimpleNamespace(load_asset=load_asset, AnimationLibrary=SimpleNamespace(
        get_num_frames=lambda clip: clip.sampled_frames, get_animation_track_names=lambda clip: tracks)))
    if change == 'none':
        exec(compile(metadata, '<generated-readback>', 'exec'), {})
    else:
        with pytest.raises(AssertionError):
            exec(compile(metadata, '<generated-readback>', 'exec'), {})


def test_landed_staff_is_supported_and_separate_from_body():
    points = contacts.skin(final.pose_at(final.COLLAPSE_S),'tripo_mesh_88102862.001')
    # The old plane approximation differs from measured ground at this prop:
    # actual minimum-plane-point clearance was4.139cm, not0.4cm. The approved
    # 3cm vertical settle therefore leaves that point1.139cm over real ground.
    assert terrain.clearances(points, staging.SUN_BEARING-90).min() == pytest.approx(0.4-final.STAFF_SETTLE_CM,abs=0.03)
    assert terrain.clearances(points, staging.SUN_BEARING-90).max() < 17.0
    assert points[:,1].min() > 50.0


def test_staff_settle_changes_only_released_prop_world_vertical_position():
    for t in (0.,1.,2.,2.05,2.5,3.,3.8):
        before=terrain.align(final.flat_pose_at(t),staging.SUN_BEARING-90)
        after=final.pose_at(t)
        assert all(after[b]==before[b] for b in before if b!='staff011')
        a,b=reveal.fk(before)['staff011'],reveal.fk(after)['staff011']
        assert a[0][:2]==pytest.approx(b[0][:2],abs=1e-10)
        assert a[1]==b[1] and a[2]==b[2]
        wanted=final.STAFF_SETTLE_CM*reveal.smooth((t-2.)/1.8)
        assert a[0][2]-b[0][2]==pytest.approx(wanted,abs=1e-10)


def test_entire_fall_keeps_real_body_surface_at_ground():
    for frame in range(58):
        vertices = contacts.skin(final.pose_at(final.COLLAPSE_S*frame/57))
        assert terrain.clearances(vertices, staging.SUN_BEARING-90).min() == pytest.approx(0.4,abs=0.02)
