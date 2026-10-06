"""Run separate guarded Unreal RPCs for each Sequencer time and pose readback."""
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/GameFlow'))
import editor_gate

owner = 'codex-saskarta-goal'
token = editor_gate.mirrored_token(owner)
assert token, 'Editor lease absent'
read_code = (ROOT / 'Tools/EndingFocus/read_v9_pose_current.py').read_text(encoding='utf-8')
set_template = (ROOT / 'Tools/EndingFocus/set_v9_time.py').read_text(encoding='utf-8')
out = ROOT / 'Saved/Verification/ending_focus_20261001/v9_ticking_pose_snapshots.json'
rows = []
for frame in (825, 849, 894, 900, 942, 984, 1032, 1077):
    assert 'set_current_time(1032)' in set_template
    set_code = set_template.replace('set_current_time(1032)', f'set_current_time({frame})')
    set_result = editor_gate.hayba('python_run', {'script': set_code}, owner=owner, lease=token, timeout_s=30)
    assert set_result.get('ok'), (frame, set_result)
    time.sleep(.15)
    read_result = editor_gate.hayba('python_run', {'script': read_code}, owner=owner, lease=token, timeout_s=30)
    assert read_result.get('ok'), (frame, read_result)
    marker = 'CIN19_V9_POSE_CURRENT '
    line = next(line for line in read_result['stdout'].splitlines() if line.startswith(marker))
    payload = json.loads(line[len(marker):])
    assert payload['frame'] == frame, (frame, payload['frame'])
    rows.append(payload)
    out.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    print(frame, payload['bones']['LeftFoot']['above_ground_cm'],
          payload['bones']['RightFoot']['above_ground_cm'],
          payload['bones']['staff011']['above_ground_cm'], flush=True)
print('V9_TICKING_POSE_SAVED', out)
