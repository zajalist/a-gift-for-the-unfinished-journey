"""Offline packet/adapter contracts. Does not connect to an editor."""
import ast
import copy
import json
import math
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import install_sensor_cinematics as installer


def test_recipe_has_nine_scoped_assets_and_keeps_world_low_voice():
    recipe,_=installer.recipe()
    assert len(recipe['plans'])==9
    assert not set(recipe['plans'])&{'CIN_19_HATCH','CIN_24_TRANSMISSION','CIN_25_END_CARD'}
    assert all('sensor_eye_cm' not in c for c in recipe['plans']['CIN_PO01_LOW_VOICE']['cams'])
    assert recipe['plans']['CIN_PO01_LOW_VOICE']['frame']=='world'
    assert recipe['plans']['CIN_04_DUST_FRONT']['cams'][0]['sensor_eye_cm']>0
    assert len(recipe['plans']['CIN_04_DUST_FRONT']['cams'][0]['keys'])==9


def test_acceptance_is_read_only_and_uses_complete_binding_values():
    tree=ast.parse(installer.READ)
    methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not methods&{'save_asset','save_loaded_asset','set_editor_property','add_track','add_section',
                        'spawn_actor_from_class','set_value','remove','set_camera_binding_id'}
    assert 'get_camera_binding_id().export_text()' in installer.READ
    assert 'get_binding_id(by_name[name]).export_text()' in installer.READ
    assert 'get_interpolation_mode()' in installer.READ
    assert 'get_time(unreal.MovieSceneTimeUnit.TICK_RESOLUTION)' in installer.READ
    assert not installer.bounded.editor.banned(installer.READ)


def test_float32_contract_accepts_rounding_but_not_world_tolerance():
    tree=ast.parse(installer.READ)
    helpers=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'f32','exact'}],type_ignores=[])
    scope={'struct':struct};exec(compile(helpers,'<float32>','exec'),scope)
    for value in (155.1,400000.123,-34674.949,0.06):
        actual=struct.unpack('<f',struct.pack('<f',value))[0]
        assert scope['exact'](actual,value)
        assert not scope['exact'](actual+.01,value)


def test_section_seconds_use_exact_inclusive_upper_tick():
    tree=ast.parse(installer.READ)
    helpers=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'f32','ranged'}],type_ignores=[])
    def need(ok,label,value=None):
        assert ok,(label,value)
    scope={'struct':struct,'math':math,'need':need};exec(compile(helpers,'<section range>','exec'),scope)
    class Section:
        def __init__(self,start,end):self.start,self.end=start,end
        def get_start_frame_seconds(self):return self.start
        def get_end_frame_seconds(self):return self.end
    f32=scope['f32']
    for start,end in [(0.,6.),(1.23,6.02),(0.,10.5)]:
        low=math.floor(f32(start)*24000+.5);high=math.floor(f32(end)*24000+.5)
        scope['ranged'](Section(f32(low/24000),f32((high+1)/24000)),start,end)
        for wrong_high in (high,high+2):
            with pytest.raises(AssertionError):
                scope['ranged'](Section(f32(low/24000),f32(wrong_high/24000)),start,end)


def test_object_paths_are_not_duplicated_and_mpc_names_are_exact():
    tree=ast.parse(installer.READ)
    helper=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='path_for'],type_ignores=[])
    scope={};exec(compile(helper,'<object paths>','exec'),scope)
    for value,wanted in [('/Game/Scan/M_PP.M_PP','/Game/Scan/M_PP.M_PP'),
                         ('/Game/Scan/MPC_Scan','/Game/Scan/MPC_Scan.MPC_Scan')]:
        assert scope['path_for'](value)==wanted
    recipe,_=installer.recipe()
    e=installer.expected_for('CIN_P04_AIRSHIP',recipe['plans']['CIN_P04_AIRSHIP'])
    names=set(e['mpc']['named_channels'])
    expected={'ScanRadius','Intensity','ScanWidth','RetAlpha','RetSize','FocusAmount','FocusRadius'}
    expected|={name+axis for name in ['ScanOrigin','Tint','RetColor','FocusPos','FocusColor'] for axis in 'RGBA'}
    assert names==expected and len(names)==27
    assert "w.get_editor_property('weight')==1.0" in installer.READ
    assert "channel.get_editor_property('channel_name')" in installer.READ


def test_observed_cut_path_rejects_cross_asset_and_duplicates():
    package='/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_04_DustFront'
    path=package+'.LS_CIN_04_DustFront:MovieScene_0.MovieSceneCameraCutTrack_0'
    assert installer.observed_track('cuts 1 track '+path+'\n',package,'cuts')==path
    assert installer.observed_track('SENSOR_CAMERA_CUT_TRACK '+path,package,'read')==path
    for output in ('cuts 1 track /Game/Elsewhere.Other:MovieSceneCameraCutTrack_0',
                   'cuts 1 track '+path+'\ncuts 1 track '+path,
                   'cuts 1 track '+package+'.LS_CIN_04_DustFront:Actor_0'):
        with pytest.raises(ValueError):installer.observed_track(output,package,'cuts')


class Connection:
    owner='test';token=None
    def __init__(self,override=None):self.calls=[];self.override=override
    def guard(self):self.calls.append('guard')
    def rpc(self,command,params,owner,token,timeout):
        self.calls.append(command)
        if self.override is not None:return self.override
        return ({'path':params['path'],'ok':True,'applied':['bCanBlend']} if command=='object_set_property'
                else {'path':params['path'],'class':'MovieSceneCameraCutTrack','properties':{'bCanBlend':'True'}})


def test_native_blend_is_guarded_set_then_exact_readback(tmp_path):
    c=Connection();journal=tmp_path/'native.json'
    installer.native_blend(c,'observed-path',journal,True)
    assert c.calls==['guard','object_set_property','guard','guard','object_get_property','guard']
    assert all(e['status']=='ok' for e in json.loads(journal.read_text()))
    c=Connection();installer.native_blend(c,'observed-path',journal,False)
    assert 'object_set_property' not in c.calls


@pytest.mark.parametrize('response',[
    {'ok':False}, {'_truncated':[{'path':'properties'}]}, {'truncated':True},
    {'ok':True,'applied':[],'failed':[]}, {'ok':True,'applied':['bCanBlend'],'failed':['bCanBlend']},
])
def test_native_blend_stops_on_ambiguous_or_failed_set(tmp_path,response):
    with pytest.raises(RuntimeError):installer.native_blend(Connection({'path':'observed',**response}),'observed',tmp_path/'native.json',True)


@pytest.mark.parametrize('change',[
    {'path':'different-object'}, {'class':'MovieSceneFadeTrack'},
    {'properties':{'bCanBlend':'False'}}, {'properties':{'bCanBlend':'True','extra':'value'}},
])
def test_native_readback_rejects_wrong_identity_or_value(tmp_path,change):
    response={'path':'observed','class':'MovieSceneCameraCutTrack','properties':{'bCanBlend':'True'},**change}
    with pytest.raises(RuntimeError):installer.native_blend(Connection(response),'observed',tmp_path/'native.json',False)


def test_packet_hashes_strict_save_and_semantic_freshness(tmp_path,monkeypatch):
    packet=tmp_path/'packet'
    plans=installer.prepare(packet)
    assert len(plans)==9 and all(len(p['groups'])==1 for p in plans)
    manifest=json.loads((packet/'manifest.json').read_text())
    assert manifest['generator_snapshot_sha256']==installer.sha(packet/'generator-source.txt')
    for p in packet.glob('*/90_save.py'):assert 'assert saved is True' in p.read_text()
    for p in packet.glob('*/00_setup.py'):
        code=p.read_text()
        assert code.index('set_tick_resolution_directly(unreal.FrameRate(24000, 1))')<code.index('set_playback_start_seconds')
    current,source_hash=installer.recipe()
    # Unrelated CIN24/25 full-source edits are permitted only with an identical relevant recipe.
    monkeypatch.setattr(installer,'recipe',lambda:(copy.deepcopy(current),'later-unrelated-source-hash'))
    installer.check(packet,'CIN_04_DUST_FRONT')
    changed=copy.deepcopy(current);changed['plans']['CIN_04_DUST_FRONT']['duration']=7
    monkeypatch.setattr(installer,'recipe',lambda:(changed,source_hash))
    with pytest.raises(ValueError,match='Relevant camera recipe changed'):installer.check(packet,'CIN_04_DUST_FRONT')
    monkeypatch.setattr(installer,'recipe',lambda:(current,source_hash))
    script=packet/'CIN_04_DUST_FRONT/99_read.py';script.write_text(script.read_text()+'# changed\n')
    with pytest.raises(ValueError,match='Camera script changed'):installer.check(packet,'CIN_04_DUST_FRONT')
