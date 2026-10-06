"""Guard the approved final route against legacy ending regeneration."""
import copy
import importlib.util
import json
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]/'minimal_ending_patch.py'
SPEC=importlib.util.spec_from_file_location('minimal_ending_patch',MODULE)
ENDING=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENDING)
ROOT=MODULE.parents[2]

def test_minimal_route_preserves_capsule_video_and_removes_reply_chain():
    original=json.loads((ROOT/'Saved/Backups/MinimalEnding_20261005/story-events.json').read_text(encoding='utf-8'))
    result=ENDING.patch(original)
    beat=next(b for b in result['beats'] if b['id']=='B24_TRANSMISSION')
    assert [a['id'] for a in beat['actions']]==['CIN_24_SIGNAL','CIN_25_END_CARD']
    signal=result['cinematics']['CIN_24_SIGNAL']
    assert signal['duration_s']==21
    assert [a['id'] for a in signal['cues'] if a['type']=='PlayRadioLine']==['END_ELDER_02','END_SYSTEM_01']
    assert all(not a.get('id','').startswith(('BELOW_','SHOW_A5','SAMYOR_B24')) for a in signal['cues'])
    hatch=result['cinematics']['CIN_19_HATCH']
    assert hatch['sequence']==original['cinematics']['CIN_19_HATCH']['sequence']
    assert any(a.get('id')=='StopCapsuleExitVideo' for a in hatch['final_state'])
    assert hatch['final_state'][-1]=={'type':'PlayRadioLine','id':'END_ELDER_01'}
    card=result['cinematics']['CIN_25_END_CARD']
    assert next(a for a in card['cues'] if a.get('id')=='Title')['at_s']==0
    assert ENDING.patch(result)==result
    assert original!=result

def test_exact_approved_text_and_no_extra_line():
    assert [text for _id,_speaker,text,_seconds in ENDING.LINES]==[
      'Just a little farther.','Places. People. Stories. Keep them together.','Transmission complete.']
