"""Check that the offstage Keeper actually animates during a live loading screen.

After filming, run through two separate Hayba Python calls while PIE is in its
loading phase: first with ACTION='mark', then >=0.5 s later with ACTION='check'.
This reads PIE state and writes only a verification receipt; it changes no actor.
"""
import json
import time
from pathlib import Path

import unreal

ACTION = 'mark'  # Change to 'check' for the second call.
OUT = Path(__file__).resolve().parents[2] / 'Saved/Verification/ending_focus_20261001/keeper_runtime_pose.json'
BONES = ('Head', 'LeftHand', 'RightHand', 'LeftFoot', 'RightFoot')

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
assert world, 'Start PIE and enter loading before sampling Keeper motion'
actors = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor)
          if a.get_actor_label() == 'KeeperPointCloud_Traveller']
assert len(actors) == 1, f'Expected one PIE KeeperPointCloud_Traveller, got {len(actors)}'
actor = actors[0]
mesh = actor.skeletal_mesh_component
def location(name):
    value = mesh.get_socket_location(name)
    return [value.x, value.y, value.z]

sample = {
    'actor': actor.get_path_name(),
    'seconds': time.time(),
    'bones_cm': {name: location(name) for name in BONES},
}
if ACTION == 'mark':
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sample, indent=2) + '\n', encoding='utf-8')
    print('KEEPER_POSE_MARK ' + json.dumps(sample, separators=(',', ':')))
elif ACTION == 'check':
    earlier = json.loads(OUT.read_text(encoding='utf-8'))
    assert sample['actor'] == earlier['actor'], 'PIE session or Keeper actor changed'
    elapsed = sample['seconds'] - earlier['seconds']
    assert elapsed >= 0.5, f'Wait at least 0.5 seconds between samples ({elapsed:.3f}s)'
    moved = {name: sum((a - b) ** 2 for a, b in zip(sample['bones_cm'][name], earlier['bones_cm'][name])) ** 0.5
             for name in BONES}
    result = {'elapsed_s': elapsed, 'bone_motion_cm': moved, 'max_motion_cm': max(moved.values())}
    print('KEEPER_POSE_CHECK ' + json.dumps(result, separators=(',', ':')))
    assert result['max_motion_cm'] > 2.0, 'Keeper bones appear frozen; inspect clip playback/ticking'
else:
    raise ValueError(ACTION)
