"""Prepare/check nine scoped camera assets offline; run only under root's editor lease.

Uses the existing bounded ending transport and journals. No CIN19/24/25 assets.
The relevant recipe fingerprint permits unrelated ending-generator edits while
retaining the exact full generator snapshot used to prepare these scripts.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import importlib
import inspect
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKET = ROOT / 'Saved/Verification/sensor_cinematics_20261001_v3'
sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
import install_ending_folder as bounded
import build_cinematics as bc

FOLDERS = ('CIN_04_DUST_FRONT', 'CIN_06_ROAD_AHEAD', 'CIN_11_WAYSTATION',
           'CIN_P04_AIRSHIP', 'CIN_P07_WAITING_WATER', 'CIN_06F_CREST_FORT',
           'CIN_P15_WORKS', 'CIN_P17_CISTERN', 'CIN_PO01_LOW_VOICE')
TEMPLATES = ('SETUP', 'CAMERA', 'CUTS', 'FADE', 'MPCTRACK')
RUNTIME_FILES = ('Tools/GameFlow/editor/install_ending_folder.py',
                 'Tools/GameFlow/editor/ending_editor.py', 'Tools/GameFlow/editor_gate.py',
                 'Tools/Look/apply_look.py', 'Tools/Perf/bounded_pie_profile.py')
_RECIPE_SIGNATURE = None
_RECIPE_DATA = None

READ = '''import unreal, json, struct, math
def need(ok, label, value=None):
    if not ok:
        print('SENSOR_ACCEPTANCE_FAIL '+json.dumps({'check':label,'actual':value},default=str))
        raise RuntimeError(label)
def f32(value):
    return struct.unpack('<f',struct.pack('<f',float(value)))[0]
def exact(actual, authored):
    return abs(float(actual)-f32(authored))<=0.000001
def ranged(section,start,end):
    values=[section.get_start_frame_seconds(),section.get_end_frame_seconds()]
    # UE5.8 SetRangeSeconds converts float seconds to inclusive frame bounds;
    # GetEndFrameSeconds returns DiscreteExclusiveUpper, one tick later.
    ticks=[math.floor(f32(value)*24000+0.5) for value in [start,end]]
    expected=[f32(ticks[0]/24000),f32((ticks[1]+1)/24000)]
    need(values==expected,'exact inclusive section range',{'actual':values,'expected':expected,'authored':[start,end]})
def path_for(package):
    leaf=package.rsplit('/',1)[1]
    return package if '.' in leaf else package+'.'+leaf
def key_data(key):
    time=key.get_time(unreal.MovieSceneTimeUnit.TICK_RESOLUTION)
    return [time.frame_number.value,float(key.get_value())]
MODE={'linear':unreal.RichCurveInterpMode.RCIM_LINEAR,'constant':unreal.RichCurveInterpMode.RCIM_CONSTANT,'cubic':unreal.RichCurveInterpMode.RCIM_CUBIC}
seq=unreal.load_asset(EXPECTED['asset'])
need(isinstance(seq,unreal.LevelSequence),'sequence type')
need(exact(seq.get_playback_start_seconds(),0) and exact(seq.get_playback_end_seconds(),EXPECTED['duration']),'playback range')
for actual,wanted,label in [(seq.get_display_rate(),[30,1],'display rate'),(seq.get_tick_resolution(),[24000,1],'tick resolution')]:
    need([actual.numerator,actual.denominator]==wanted,label)
bindings=list(seq.get_bindings())
names=[str(b.get_display_name()) for b in bindings]
need(len(names)==len(EXPECTED['cameras']) and set(names)==set(EXPECTED['cameras']),'exact camera bindings',names)
by_name=dict(zip(names,bindings))
checked=0
for name,camera in EXPECTED['cameras'].items():
    binding=by_name[name]
    template=unreal.MovieSceneBindingExtensions.get_object_template(binding)
    need(template is not None,'spawnable template',name)
    need(template.get_class().get_name()==camera['class'],'camera class',[name,template.get_class().get_name()])
    component=template.get_editor_property('camera_component')
    need(exact(component.get_editor_property('current_focal_length'),camera['focal']),'focal length',name)
    focus=component.get_editor_property('focus_settings')
    need(focus.get_editor_property('focus_method')==unreal.CameraFocusMethod.DISABLE,'disabled depth of field',name)
    if camera['sensor_eye'] is not None:
        need(exact(template.get_editor_property('authored_eye_height_cm'),camera['sensor_eye']),'sensor reference eye',name)
        need(component.get_class().get_name()=='SaskartaSensorCameraComponent','sensor view component',name)
    pp=component.get_editor_property('post_process_settings')
    weighted=pp.get_editor_property('weighted_blendables').get_editor_property('array')
    blendables=[w.get_editor_property('object').get_path_name() for w in weighted]
    need(blendables==[path_for(p) for p in camera['blendables']],'exact camera blendables',[name,blendables])
    need(all(w.get_editor_property('weight')==1.0 for w in weighted),'exact blendable weights',name)
    tracks=list(binding.get_tracks())
    need(all(t.get_class().get_name() in ['MovieScene3DTransformTrack','MovieSceneSpawnTrack'] for t in tracks),'camera track types',name)
    transforms=[t for t in tracks if t.get_class().get_name()=='MovieScene3DTransformTrack']
    need(len(transforms)==1 and len(transforms[0].get_sections())==1,'one camera transform',name)
    section=transforms[0].get_sections()[0]
    ranged(section,*camera['range'])
    channels=section.get_all_channels()
    need(len(channels)>=6,'six transform channels',name)
    need(all(c.get_num_keys()==0 for c in channels[6:]),'no extra scale/quaternion keys',name)
    for axis in range(6):
        keys=channels[axis].get_keys()
        need(len(keys)==len(camera['keys']),'exact transform key count',[name,axis,len(keys)])
        for key,wanted in zip(keys,camera['keys']):
            actual=key_data(key)
            need(actual[0]==wanted[0] and exact(actual[1],wanted[1][axis]),'exact float32 transform key',[name,axis,actual,wanted])
            need(key.get_interpolation_mode()==MODE[wanted[2]],'key interpolation',[name,axis,actual[0]])
            checked+=1
master=list(seq.get_tracks())
classes=[t.get_class().get_name() for t in master]
need(sorted(classes)==sorted(EXPECTED['master']),'exact master tracks',classes)
track=next(t for t in master if t.get_class().get_name()=='MovieSceneCameraCutTrack')
cuts=sorted(track.get_sections(),key=lambda s:s.get_start_frame_seconds())
need(len(cuts)==len(EXPECTED['cuts']),'exact cut count',len(cuts))
for index,(cut,wanted) in enumerate(zip(cuts,EXPECTED['cuts'])):
    start,end,name,ease=wanted
    ranged(cut,start,end)
    actual=cut.get_camera_binding_id().export_text()
    expected=seq.get_binding_id(by_name[name]).export_text()
    need(actual==expected,'complete camera binding ID',[name,actual,expected])
    if ease>0:
        need(cut.get_ease_in_duration()==int(ease*24000),'cut ease in',name)
    if index==len(cuts)-1 and EXPECTED['blend_out']>0:
        need(cut.get_ease_out_duration()==int(EXPECTED['blend_out']*24000),'cut ease out',name)
if EXPECTED['fade'] is not None:
    fade=next(t for t in master if t.get_class().get_name()=='MovieSceneFadeTrack')
    need(len(fade.get_sections())==1,'one fade section')
    section=fade.get_sections()[0]
    ranged(section,0,EXPECTED['duration'])
    keys=section.get_all_channels()[0].get_keys()
    need(len(keys)==len(EXPECTED['fade']),'fade key count')
    for key,wanted in zip(keys,EXPECTED['fade']):
        actual=key_data(key)
        need(actual[0]==wanted[0] and exact(actual[1],wanted[1]),'fade time/value',actual)
        need(key.get_interpolation_mode()==MODE[wanted[2]],'fade interpolation')
if EXPECTED['mpc'] is not None:
    material_track=next(t for t in master if t.get_class().get_name()=='MovieSceneMaterialParameterCollectionTrack')
    need(material_track.get_editor_property('mpc').get_path_name()==path_for(EXPECTED['mpc']['asset']),'MPC reference')
    need(len(material_track.get_sections())==1,'one MPC section')
    section=material_track.get_sections()[0]
    ranged(section,0,EXPECTED['duration'])
    channels=list(section.get_all_channels())
    names=[str(channel.get_editor_property('channel_name')).casefold() for channel in channels]
    expected={name.casefold():[[tick,f32(value)] for tick,value in keys] for name,keys in EXPECTED['mpc']['named_channels'].items()}
    need(len(names)==len(expected) and set(names)==set(expected),'exact MPC parameter channel identities',names)
    actual={name:[key_data(k) for k in channel.get_keys()] for name,channel in zip(names,channels)}
    need(actual==expected,'all named MPC channel times and float32 values')
print('SENSOR_CAMERA_CUT_TRACK '+track.get_path_name())
print('SENSOR_CINEMATIC_ACCEPTANCE_OK '+EXPECTED['id']+' '+json.dumps({'bindings':len(bindings),'cuts':len(cuts),'transform_values':checked}))
'''


def sha(path):
    return bounded.digest(path)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def recipe():
    # Re-read source and dependency-derived plans, even within a long root install.
    global _RECIPE_SIGNATURE, _RECIPE_DATA
    paths=(Path(bc.__file__),bc.PROBE_FILE,bc.PROBE_ENDING_FILE,bc.ROAD_PROFILE,bc.SETDRESS,bc.HEIGHTMAP)
    signature={str(p):sha(p) if p.is_file() else None for p in paths}
    if signature==_RECIPE_SIGNATURE:
        return json.loads(canonical(_RECIPE_DATA)),signature[str(Path(bc.__file__))]
    before = sha(Path(bc.__file__))
    importlib.reload(bc)
    result = dict(plans={name:bc.PLANS[name]() for name in FOLDERS},
                  templates={name:vars(bc)[name] for name in TEMPLATES},
                  emitter={name:inspect.getsource(vars(bc)[name]) for name in ('emit','cut_sections','cam_ranges')},
                  fps=bc.FPS,ticks=bc.TICKS,folder=bc.FOLDER)
    paths=(Path(bc.__file__),bc.PROBE_FILE,bc.PROBE_ENDING_FILE,bc.ROAD_PROFILE,bc.SETDRESS,bc.HEIGHTMAP)
    after={str(p):sha(p) if p.is_file() else None for p in paths}
    if signature!=after:
        raise ValueError('Generator/input changed while preparing camera recipes; wait for its owner to freeze')
    # JSON also normalizes tuple/list differences before later comparison.
    _RECIPE_SIGNATURE=signature
    _RECIPE_DATA=json.loads(canonical(result))
    return json.loads(canonical(result)), before


def expected_for(cid, plan):
    ranges=bc.cam_ranges(plan)
    cameras={c['name']:dict(
        sensor_eye=c.get('sensor_eye_cm'),
        **{'class':'SaskartaSensorCamera' if 'sensor_eye_cm' in c else 'CineCameraActor'},
        focal=round(c['focal'],3),blendables=c.get('blendables',[]),range=ranges[c['name']],
        keys=[[round(k[0]*bc.TICKS),[round(v,3) for v in k[1:7]],k[7]] for k in c['keys']]) for c in plan['cams']}
    master=['MovieSceneCameraCutTrack']
    fade=None;mpc=None
    if plan.get('fade'):
        master.append('MovieSceneFadeTrack')
        fade=[[round(t*bc.TICKS),v,mode] for t,v,mode in plan['fade']['keys']]
    if plan.get('mpc'):
        master.append('MovieSceneMaterialParameterCollectionTrack')
        m=plan['mpc']
        channels={name:[[round(t*bc.TICKS),v] for t,v in keys] for name,keys in m['scalars'].items()}
        # UE5.8 color-channel metadata appends R/G/B/A without a dot;
        # root confirmed these exact names in the live Airship MPC section.
        for name,keys in m['vectors'].items():
            channels.update({name+suffix:[[round(t*bc.TICKS),(list(v)+[1.])[axis]] for t,v in keys]
                             for axis,suffix in enumerate('RGBA')})
        mpc={'asset':m['asset'],'named_channels':channels}
    return dict(id=cid,asset=bc.FOLDER+'/'+plan['asset'],duration=plan['duration'],cameras=cameras,
                cuts=bc.cut_sections(plan),blend_out=plan['blend_out'],master=master,fade=fade,mpc=mpc)


def preflight(expected):
    dependencies=sorted(set(p for c in expected['cameras'].values() for p in c['blendables'])
                        | ({expected['mpc']['asset']} if expected['mpc'] else set()))
    return ('import unreal\n'
        "assert unreal.load_class(None,'/Script/SaskartaCore.SaskartaSensorCamera') is not None, 'Sensor camera DLL is required'\n"
        +f"path={expected['asset']!r}\n"
        +"if unreal.EditorAssetLibrary.does_asset_exist(path):\n    assert isinstance(unreal.load_asset(path),unreal.LevelSequence)\n"
        +f"for path in {dependencies!r}:\n    assert unreal.load_asset(path) is not None,path\n")


def prepare(packet):
    if packet.exists():raise ValueError('Preserve existing packet; choose a fresh revision')
    r,source_hash=recipe()
    packet.mkdir(parents=True)
    snapshot=packet/'generator-source.txt'
    snapshot.write_bytes(Path(bc.__file__).read_bytes())
    if sha(snapshot)!=source_hash:raise ValueError('Generator changed during snapshot')
    bounded.save_state(packet/'recipe.json',r)
    expected={}
    for cid,plan in r['plans'].items():
        assert not plan.get('extra') and plan.get('asset') and plan['shots']
        folder=packet/cid
        assert bc.emit(cid,folder)==0
        expected[cid]=e=expected_for(cid,plan)
        setup=folder/'00_setup.py'
        setup_code=setup.read_text(encoding='utf-8')
        anchor='seq.set_display_rate(unreal.FrameRate(30, 1))'
        assert setup_code.count(anchor)==1
        # Existing sequences may have a different tick rate. Old tracks have
        # already been cleared, so directly set the authored clock before keys.
        setup.write_text(setup_code.replace(anchor,
            'seq.set_tick_resolution_directly(unreal.FrameRate(24000, 1))\n'+anchor),encoding='utf-8')
        (folder/'00_preflight.py').write_text(preflight(e),encoding='utf-8')
        (folder/'90_save.py').write_text('import unreal\nsaved=unreal.EditorAssetLibrary.save_asset('
            +repr(e['asset'])+",only_if_is_dirty=False)\nprint('saved',saved)\nassert saved is True\n",encoding='utf-8')
        (folder/'99_read.py').write_text('EXPECTED = '+repr(e)+'\n'+READ,encoding='utf-8')
        for p in folder.glob('*.py'):
            code=p.read_text(encoding='utf-8')
            ast.parse(code,filename=p.name)
            assert not bounded.editor.banned(code),(p.name,bounded.editor.banned(code))
            assert len(code.encode())<22000,p.name
            p.write_text(code+'\nprint('+repr('SENSOR_STEP_OK '+cid+' '+p.name)+')\n',encoding='utf-8')
    scripts={p.relative_to(packet).as_posix():sha(p) for p in packet.rglob('*.py')}
    current,_=recipe()
    if current!=r:raise ValueError('Relevant camera recipe changed during preparation')
    dependencies=[Path(bc.__file__),bc.PROBE_FILE,bc.PROBE_ENDING_FILE,bc.ROAD_PROFILE,bc.SETDRESS,bc.HEIGHTMAP]
    manifest=dict(status='prepared_not_installed',scope=list(FOLDERS),script_sha256=scripts,expected=expected,
        recipe_sha256=sha(packet/'recipe.json'),generator_snapshot_sha256=sha(snapshot),
        historical_source_sha256={str(p.relative_to(ROOT)):sha(p) for p in dependencies if p.is_file()},
        installer_sha256=sha(Path(__file__)),
        runtime_sha256={p:sha(ROOT/p) for p in RUNTIME_FILES},blend_property={'bCanBlend':True},
        freshness='Exact selected plans, shared templates and emitter functions must match. Unrelated CIN24/25 edits may differ from historical full-file hash.',
        acceptance='All transform keys at observed float32 precision, tick times, modes, ranges, lenses, complete binding export_text, exact camera classes and native cut blend readback. Rendered viewpoint remains unverified.')
    bounded.save_state(packet/'manifest.json',manifest)
    return [check(packet,cid) for cid in FOLDERS]


def check(packet,cid):
    if cid not in FOLDERS:raise ValueError('Out-of-scope camera asset')
    manifest_path=packet/'manifest.json';m=json.loads(manifest_path.read_text())
    if m['scope']!=list(FOLDERS) or m['installer_sha256']!=sha(Path(__file__)):
        raise ValueError('Scope or installer changed since preparation')
    if m['runtime_sha256']!={p:sha(ROOT/p) for p in RUNTIME_FILES}:
        raise ValueError('Guarded transport changed since preparation')
    if sha(packet/'generator-source.txt')!=m['generator_snapshot_sha256'] or sha(packet/'recipe.json')!=m['recipe_sha256']:
        raise ValueError('Frozen source/recipe evidence changed')
    current,_=recipe()
    if current!=json.loads((packet/'recipe.json').read_text()):
        raise ValueError('Relevant camera recipe changed; prepare a fresh revision')
    expected={Path(n).name:h for n,h in m['script_sha256'].items() if Path(n).parent.as_posix()==cid}
    if not expected or set(expected)!={p.name for p in (packet/cid).glob('*.py')}:
        raise ValueError('Camera packet filenames changed')
    for name,digest in expected.items():
        p=packet/cid/name
        if sha(p)!=digest:raise ValueError('Camera script changed: '+name)
        code=p.read_text();ast.parse(code,filename=name)
        if bounded.editor.banned(code):raise ValueError('Forbidden editor operation: '+name)
    package=m['expected'][cid]['asset']
    bounded.require_writable(bounded.package_file(package,ROOT))
    steps=sorted(expected)
    assert steps[0]=='00_preflight.py' and steps[-2:]==['90_save.py','99_read.py']
    inputs={str(packet/name):sha(packet/name) for name in ('manifest.json','recipe.json','generator-source.txt')}
    inputs[str(Path(__file__).resolve())]=sha(Path(__file__))
    inputs.update({str(ROOT/p):h for p,h in m['runtime_sha256'].items()})
    return dict(folder=cid,prepared=str(packet),audit_sha256=sha(manifest_path),script_sha256=expected,
        input_sha256=inputs,groups=[dict(id='90_save.py',steps=steps,package=package)])


def observed_track(output,package,marker):
    if marker=='cuts':
        paths=re.findall(r'^cuts \d+ track (\S+)\s*$',output,re.MULTILINE)
    else:
        paths=re.findall(r'^SENSOR_CAMERA_CUT_TRACK (\S+)\s*$',output,re.MULTILINE)
    prefix=package+'.'+package.rsplit('/',1)[1]+':'
    if len(paths)!=1 or not paths[0].startswith(prefix) or 'MovieSceneCameraCutTrack' not in paths[0]:
        raise ValueError('Missing or out-of-scope observed camera cut track')
    return paths[0]


def native_blend(connection,path,journal,mutate):
    events=json.loads(journal.read_text()) if journal.exists() else []
    requests=([('object_set_property',{'path':path,'properties':{'bCanBlend':True}})] if mutate else [])
    requests += [('object_get_property',{'path':path,'names':['bCanBlend']})]
    for command,params in requests:
        event={'command':command,'params':params,'status':'started'}
        events.append(event);bounded.save_state(journal,events)
        connection.guard()
        result=connection.rpc(command,params,connection.owner,connection.token,20)
        event['result']=result;bounded.save_state(journal,events)
        connection.guard()
        if not isinstance(result,dict) or result.get('_truncated') or result.get('truncated') or result.get('ok') is False:
            raise RuntimeError('Native camera blend response failed/truncated')
        if result.get('path')!=path:
            raise RuntimeError('Native camera blend response identifies another object')
        if command=='object_set_property':
            if result.get('ok') is not True or result.get('failed') or result.get('applied')!=['bCanBlend']:
                raise RuntimeError('Native camera blend set was not confirmed')
        else:
            if result.get('class')!='MovieSceneCameraCutTrack' or set(result.get('properties',{}))!={'bCanBlend'}:
                raise RuntimeError('Native camera blend readback class/property mismatch')
            value=result.get('properties',{}).get('bCanBlend')
            if value is not True and value!='True':raise RuntimeError('Native camera blend readback was not True')
        event['status']='ok';bounded.save_state(journal,events)


def run(packet,cid,owner):
    plan=check(packet,cid)
    connection=bounded.EditorConnection(owner)
    journal=packet/'install_logs'/(cid+'.json')
    native_journal=packet/'install_logs'/(cid+'.native.json')
    package=plan['groups'][0]['package']
    backup=packet/'backups'/cid
    if not journal.exists() and not backup.exists():
        connection.guard();backup.mkdir(parents=True)
        original=bounded.package_file(package,ROOT)
        hashes={}
        for suffix in ('.uasset','.uexp','.ubulk'):
            p=original.with_suffix(suffix)
            if p.is_file():
                shutil.copy2(p,backup/p.name);hashes[p.name]=sha(p)
        bounded.save_state(backup/'before.json',hashes)
    def guard():
        check(packet,cid);connection.guard()
    def send(code,name):
        output=connection.send(code,name)
        if 'SENSOR_STEP_OK '+cid+' '+name not in output:raise RuntimeError('Missing camera step marker: '+name)
        if name in ('80_cuts.py','99_read.py'):
            path=observed_track(output,package,'cuts' if name=='80_cuts.py' else 'read')
            native_blend(connection,path,native_journal,name=='80_cuts.py')
        if name=='99_read.py' and 'SENSOR_CINEMATIC_ACCEPTANCE_OK '+cid not in output:
            raise RuntimeError('Camera metadata acceptance did not pass')
        return output
    return bounded.run_plan(plan,journal,send,guard,max_groups=1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','check','run'])
    parser.add_argument('--packet',type=Path,default=DEFAULT_PACKET)
    parser.add_argument('--folder',choices=FOLDERS)
    parser.add_argument('--owner')
    args=parser.parse_args();packet=args.packet.resolve()
    if args.mode=='prepare':plans=prepare(packet)
    elif args.mode=='check':plans=[check(packet,cid) for cid in ([args.folder] if args.folder else FOLDERS)]
    else:
        if not args.folder or not args.owner:parser.error('run requires one --folder and the root lease --owner')
        run(packet,args.folder,args.owner);return
    print(json.dumps({'packet':str(packet),'manifest_sha256':sha(packet/'manifest.json'),
        'folders':[{ 'id':p['folder'],'steps':len(p['script_sha256'])} for p in plans]},indent=2))


if __name__=='__main__':main()
