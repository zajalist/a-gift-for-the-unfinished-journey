"""Apply the approved three-line ambiguous ending after legacy generators."""
import copy
import csv
import io
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STORY=ROOT/'docs/story/story-events.json'
LINES=[('END_ELDER_01','ELDER','Just a little farther.',2.55),
       ('END_ELDER_02','ELDER','Places. People. Stories. Keep them together.',8.08),
       ('END_SYSTEM_01','SYSTEM','Transmission complete.',1.84)]

def patch(data):
    data=copy.deepcopy(data)
    hatch=data['cinematics']['CIN_19_HATCH']
    hatch['final_state']=[a for a in hatch['final_state'] if a.get('id')!='END_ELDER_01']
    hatch['final_state'].append({'type':'PlayRadioLine','id':'END_ELDER_01'})
    for beat in data['beats']:
        if beat['id']=='B24_TRANSMISSION':
            beat['actions']=[{'type':'PlayCinematic','id':'CIN_24_SIGNAL','priority':'Critical'},
                             {'type':'PlayCinematic','id':'CIN_25_END_CARD','priority':'Critical'}]
            beat['notes']='E at the Summit console: Elder speaks once, system confirms transmission, signal rises, sky opens, title and credits. No reply or confirmed recipient.'
            beat['final_shot']={'view':'Summit mast and rising signal','hold_s':21.0,'audio':'Only the two approved console lines, then silence.'}
    data['cinematics']['CIN_24_SIGNAL']={
        'beat':'B24_TRANSMISSION','tier':'mandatory',
        'sequence':'/Game/SaskartaGaea/GameFlow/Ending/LS_MinimalTransmission',
        'duration_s':21.0,'priority':'Critical','blend_in_s':0.0,'blend_out_s':0.0,
        'letterbox':False,'skip':'HoldAfterSeen','skip_min_s':1.0,
        'stop_pawn':True,'relative_to_pawn':False,'hand_back':'None',
        'note':'Approved minimal ending. Short signal shot; no old transmission animation or reply chain.',
        'cues':[
            {'at_s':0.0,'type':'SetFlowState','id':'Transmit'},
            {'at_s':0.0,'type':'CallHook','id':'StopHumanWalk','target_tag':'PC'},
            {'at_s':0.0,'type':'StopSfx','id':'HUT_NIGHT_A1','duration_s':0.0},
            {'at_s':0.0,'type':'CallHook','id':'Cine_ClearBlack','target_tag':'PC'},
            {'at_s':0.5,'type':'PlayRadioLine','id':'END_ELDER_02'},
            {'at_s':9.6,'type':'PlayRadioLine','id':'END_SYSTEM_01'},
            {'at_s':12.0,'type':'PlayDawn','duration_s':7.0,'value':3.0,'pitch':-0.5,'yaw':18.66,'keep_on_skip':True}
        ],'final_state':[]}
    for cue in data['cinematics']['CIN_25_END_CARD']['cues']:
        if cue['type']=='ShowEndCard' and cue.get('id')=='Title':
            cue['at_s']=0.0
            cue['duration_s']=10.0
    return data

def write_sources():
    STORY.write_text(json.dumps(patch(json.loads(STORY.read_text(encoding='utf-8'))),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tsv=ROOT/'docs/story/radio-lines-for-translation.tsv'
    rows=list(csv.reader(io.StringIO(tsv.read_text(encoding='utf-8')),delimiter='\t'))
    rows=[row for row in rows if len(row)<2 or row[1] not in {r[0] for r in LINES}]
    for ident,speaker,text,duration in LINES:
        rows.append(['ENDING',ident,'Story',speaker,'Approved minimal ending',text,
                     'Temporary neural voice; replace with author recording.',f'{duration:.2f} s','EN','','','TTS','Approved 2026-10-05'])
    stream=io.StringIO(newline='')
    csv.writer(stream,delimiter='\t',lineterminator='\n').writerows(rows)
    tsv.write_text(stream.getvalue(),encoding='utf-8')

if __name__=='__main__':
    write_sources()
    print('Approved minimal ending written to canonical story and dialogue source.')
