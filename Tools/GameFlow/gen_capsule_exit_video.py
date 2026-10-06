"""Prepare the approved video replacement for CIN19; installation is scoped."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / 'Tools/GameFlow/specs'
BASE = '/Game/SaskartaGaea/GameFlow/Video'
WIDGET = BASE + '/WBP_CapsuleExitVideo'
PC = '/Game/SaskartaGaea/GameFlow/PC_Saskarta'
PLAYER = BASE + '/MP_CapsuleExit.MP_CapsuleExit'
SOURCE = BASE + '/FMS_CapsuleExit.FMS_CapsuleExit'
def call(name, cls): return {'call': name, 'class': cls}
def save(name, data):
    (SPECS / name).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')

def prepare():
    save('WBP_CapsuleExitVideo.tree.json', {
        'asset': WIDGET, 'variables': [],
        'tree': [{'class': 'CanvasPanel', 'name': 'Root', 'children': [
            {'class':'Border','name':'BlackBackground','properties': {'BrushColor':[0,0,0,1]}},
            {'class':'ScaleBox','name':'VideoFit','properties':{'Stretch':'ScaleToFit'},'children':[
                {'class':'SizeBox','name':'VideoSize','properties':{'bOverride_WidthOverride':True,'bOverride_HeightOverride':True,'WidthOverride':1280,'HeightOverride':714},'children':[
                    {'class':'Image','name':'VideoImage','properties':{'Brush':{'ResourceObject':BASE+'/M_UI_CapsuleExit.M_UI_CapsuleExit','DrawAs':'Image'}}}
                ]}
            ]}
        ]}],
        'slots':{name:{'anchors':[0,0,1,1],'position':[0,0],'size':[0,0],'z_order':i} for i,name in enumerate(['Root','BlackBackground','VideoFit'])}
    })
    media_cls='/Script/MediaAssets.MediaPlayer'
    save('WBP_CapsuleExitVideo.graph.json', {
        'asset':WIDGET,
        'variables':[{'name':'ExitMediaPlayer','type':'object:'+media_cls},{'name':'ExitMediaSource','type':'object:/Script/MediaAssets.MediaSource'}],
        'cdo_defaults':{'ExitMediaPlayer':PLAYER,'ExitMediaSource':SOURCE},
        'graphs':[{'graph':'EventGraph','nodes':{
            'construct':{'event':'Construct'}, 'player':{'get':'ExitMediaPlayer'},'source':{'get':'ExitMediaSource'},
            'open':call('OpenSource',media_cls), 'destruct':{'event':'Destruct'},'closePlayer':{'get':'ExitMediaPlayer'},'close':call('Close',media_cls)
        },'links':[
            ['construct.then','open.execute'],['player.ExitMediaPlayer','open.self'],['source.ExitMediaSource','open.MediaSource'],
            ['destruct.then','close.execute'],['closePlayer.ExitMediaPlayer','close.self']
        ]}]
    })
    save('PC_Saskarta.capsule_video.json', {
        'asset':PC,
        'variables':[{'name':'CapsuleExitOverlay','type':'object:'+WIDGET+'.WBP_CapsuleExitVideo_C'},{'name':'CapsuleExitMediaPlayer','type':'object:'+media_cls}],
        'cdo_defaults':{'CapsuleExitMediaPlayer':PLAYER},
        'functions':[{'name':name,'inputs':[],'outputs':[],'pure':False} for name in ['StartCapsuleExitVideo','StopCapsuleExitVideo']],
        'graphs':[
            {'graph':'StartCapsuleExitVideo','nodes':{
                'entry':{'entry':True},'cleanup':{'call':'StopCapsuleExitVideo'},'me':{'self':True},
                'make':{'create_widget':WIDGET+'.WBP_CapsuleExitVideo_C'},'store':{'set':'CapsuleExitOverlay'},
                'add':call('AddToViewport','/Script/UMG.UserWidget')
            },'defaults':{'add.ZOrder':'10000'},'links':[
                ['entry.then','cleanup.execute'],['cleanup.then','make.execute'],['me.self','make.OwningPlayer'],
                ['make.then','store.execute'],['make.ReturnValue','store.CapsuleExitOverlay'],['store.then','add.execute'],['make.ReturnValue','add.self']
            ]},
            {'graph':'StopCapsuleExitVideo','nodes':{
                'entry':{'entry':True},'player':{'get':'CapsuleExitMediaPlayer'},'close':call('Close',media_cls),
                'overlay':{'get':'CapsuleExitOverlay'},'valid':call('IsValid','/Script/Engine.KismetSystemLibrary'),
                'branch':{'branch':True},'remove':call('RemoveFromParent','/Script/UMG.Widget')
            },'links':[
                ['entry.then','close.execute'],['player.CapsuleExitMediaPlayer','close.self'],['close.then','branch.execute'],
                ['overlay.CapsuleExitOverlay','valid.Object'],['valid.ReturnValue','branch.Condition'],
                ['branch.then','remove.execute'],['overlay.CapsuleExitOverlay','remove.self']
            ]}
        ]
    })

def patch_story():
    path=ROOT/'docs/story/story-events.json'
    story=json.loads(path.read_text(encoding='utf-8'))
    cine=story['cinematics']['CIN_19_HATCH']
    cine.update(sequence=BASE+'/LS_CapsuleExit_VideoClock',duration_s=18.5,blend_in_s=0.0,blend_out_s=0.0,
                letterbox=False,relative_to_pawn=False,skip_min_s=1.0,
                note='Approved 18-second video overlay replaces the capsule exit animation. No Rise pause. Final state hands back to the existing Traveller walk and removes/closes media on finish or skip.')
    cine['cues']=[{'at_s':0,'type':'CallHook','id':name,'target_tag':'PC'} for name in ['Cine_ClearBlack','StartCapsuleExitVideo']]
    cine['final_state']=[a for a in cine['final_state'] if not (a['type']=='CallHook' and a.get('id')=='StopCapsuleExitVideo')]
    cine['final_state'].append({'type':'CallHook','id':'StopCapsuleExitVideo','target_tag':'PC'})
    path.write_text(json.dumps(story,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    fullpath=SPECS/'PC_Saskarta.json'
    full=json.loads(fullpath.read_text(encoding='utf-8'))
    scoped=json.loads((SPECS/'PC_Saskarta.capsule_video.json').read_text(encoding='utf-8'))
    for field,key in [('variables','name'),('functions','name'),('graphs','graph')]:
        for item in scoped[field]:
            full[field]=[a for a in full.get(field,[]) if a[key]!=item[key]]+[item]
    full.setdefault('cdo_defaults',{}).update(scoped['cdo_defaults'])
    fullpath.write_text(json.dumps(full,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    import sys
    prepare()
    if '--patch-source' in sys.argv: patch_story()
    print('Capsule exit video specs prepared.')
