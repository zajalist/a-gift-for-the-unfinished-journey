import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_render_contact_probe as probe


def selected():
    return [dict(component='/Game/World.Cart.Mesh', mesh='/Game/Cart.Cart', instance=None,
                 transform='(Rotation=(X=0,Y=0,Z=0,W=1),Translation=(X=0,Y=0,Z=0),Scale3D=(X=1,Y=1,Z=1))')]


def test_full_render_is_checked_before_sampling_and_tracing():
    script = probe.render_contact_script(selected(), {'/Game/Cart.Cart': 1942})
    assert 'GeometryScriptLODType.RENDER_DATA' in script
    assert 'if len(vertices) != expected_count:' in script
    assert script.index('if len(vertices) != expected_count:') < script.index("item['local_contacts'] =")
    assert "'render_proofs': render_proofs" in script
    assert 'pose.export_text() !=' in script
    assert 'set_actor_' not in script


def test_large_or_unconfirmed_mesh_is_refused_offline():
    for count in [0, 12001]:
        with pytest.raises(ValueError, match='Confirm'):
            probe.render_contact_script(selected(), {'/Game/Cart.Cart': count})
    with pytest.raises(ValueError, match='Confirm'):
        probe.render_contact_script(selected(), {})


def test_existing_contacts_cannot_bypass_full_render_selection():
    selection = selected()
    selection[0]['local_contacts'] = [[0, 0, 0]]
    with pytest.raises(ValueError, match='catalog selection'):
        probe.render_contact_script(selection, {'/Game/Cart.Cart': 1942})


def test_explicit_bounded_larger_mesh_requires_whole_call_budget():
    assert '17964' in probe.render_contact_script(selected(), {'/Game/Cart.Cart': 17964}, 20000)
    with pytest.raises(ValueError, match='Combined'):
        probe.render_contact_script(selected()*2, {'/Game/Cart.Cart': 17964}, 20000)
    with pytest.raises(ValueError, match='3..20000'):
        probe.render_contact_script(selected(), {'/Game/Cart.Cart': 17964}, 25000)
