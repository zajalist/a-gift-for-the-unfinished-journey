"""The current ending returns to a visible, complete elder in third person."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'Tools/GameFlow'))
import gen_ending_specs as ending


def test_third_person_camera_and_full_head_survive_regeneration():
    spec = ending.traveller()
    variables = {v['name']: v.get('default') for v in spec['variables']}
    assert float(variables['ArmLength']) >= 250.0
    graph = next(g for g in spec['graphs'] if g['graph'] == 'ConfigureCamera')
    properties = {key.split('.')[0]: value for key, value in graph['defaults'].items()
                  if key.endswith('.PropertyName')}
    values = {name: graph['defaults'].get(node + '.Value') for node, name in properties.items()}
    assert values['bDoCollisionTest'] == 'true'
    assert values['bEnableCameraLag'] == 'true'
    assert values['bOrientRotationToMovement'] == 'true'
    assert values['bUseControllerRotationYaw'] == 'false'
    calls = [node.get('call') for node in graph['nodes'].values()]
    assert 'UnHideBoneByName' in calls
    assert 'HideBoneByName' not in calls
    assert json.loads((ROOT / 'Tools/GameFlow/specs/BP_Saskarta_Traveller.json').read_text()) == spec
