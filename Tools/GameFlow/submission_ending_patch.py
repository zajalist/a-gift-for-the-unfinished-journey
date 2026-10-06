"""Apply the approved silent Summit transmission to the canonical story source.

The original source and assets are backed up in Saved/Backups/Submission_20261005.
Run again after regenerating First Light to keep this submission's interaction.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'docs/story/story-events.json'
MUTE = {'PlayRadioLine', 'PlayCarrierLine', 'PlaySfx', 'ShowCaption'}


def patch(data):
    for beat in data['beats']:
        if beat['id'].startswith(('B20', 'B21', 'B22', 'B23', 'B24')):
            beat['actions'] = [a for a in beat.get('actions', []) if a['type'] not in MUTE]
            beat['radio_line_ids'] = []
            beat['carrier_line_ids'] = []
        if beat['id'] == 'B23_LAST_ENTRY':
            beat['required_flow_state'] = 'Human'
            beat['world'] = [297998, 482215, 13090]
            beat['prompts'] = ['Transmit']
            beat['actions'] = [{'type': 'Prompt', 'text': 'Transmit', 'next_beat': 'B24_TRANSMISSION'}]
            beat['notes'] = 'E at the Summit console starts transmission directly. Human only; no lamp interaction.'
    for name in ('CIN_19_HATCH', 'CIN_23_THE_MARK', 'CIN_24_TRANSMISSION', 'CIN_25_END_CARD'):
        cine = data['cinematics'].get(name)
        if cine:
            for field in ('cues', 'final_state'):
                cine[field] = [a for a in cine.get(field, []) if a['type'] not in MUTE]
            if name == 'CIN_25_END_CARD':
                if not any(a['type'] == 'SetFlowState' and a.get('id') == 'Title' for a in cine['final_state']):
                    cine['final_state'].insert(0, {'type': 'SetFlowState', 'id': 'Title'})
    if 'CIN_24_SIGNAL' in data['cinematics']:
        from minimal_ending_patch import patch as patch_minimal
        data = patch_minimal(data)
    return data


if __name__ == '__main__':
    data = patch(json.loads(PATH.read_text(encoding='utf-8')))
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    controller = ROOT / 'Tools/GameFlow/specs/PC_Saskarta.json'
    full = json.loads(controller.read_text(encoding='utf-8'))
    scoped = json.loads((controller.parent / 'PC_Saskarta.silent_ending.json').read_text(encoding='utf-8'))
    for field, key in [('functions', 'name'), ('graphs', 'graph')]:
        for definition in scoped[field]:
            full[field] = [item for item in full[field] if item[key] != definition[key]] + [definition]
    controller.write_text(json.dumps(full, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Patched Summit transmission and silent ending story source.')
