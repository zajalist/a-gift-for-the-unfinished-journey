"""The Low Voice's radio chain (LANE5, the user 2026-09-28: "add effects on top to make [the songs] more radio-like").

    python Tools/Audio/station_chain.py OUT_DIR     # writes the python_run chunks, run them in order

One submix for everything the station plays (host takes, songs, the title song, the static bed), so speech and
songs sound like the same radio:
- SM_Saskarta_Station (-> master) with the chain (DA_Station.ArchiveFilterChain, applied by the station at
  BeginPlay as an effect-chain override): high-pass 180 Hz, low-pass 5.5 kHz (the AM band; the reception
  narrows speech further per signal in C++), a speaker-cabinet EQ (-3 dB at 400 Hz, +3 dB at 1.8 kHz, +1.5 dB
  at 3.5 kHz), a gentle compressor (-20 dB, 3:1, 8 / 150 ms, +3 dB make-up).
- SEC_Saskarta_Radio, a source effect chain on each station sound: a light wave-shaper saturation and a slow,
  shallow chorus for the wow and flutter (0.6 Hz, depth 0.06).
The imperfections (dropouts, crackle, noise bursts, jitter, drift, squeals) are the station's C++ glitch engine
plus WBP_Saskarta_Radio's OnRadioGlitch one-shots; story/archive lines get only the light crackle.
Also imports the station room tone (the RADIO_SHOW fills and silence): SFX_Station_RoomTone_Loop (looping,
streamed) and the six SFX_Station_Room_* one-shots (inline) into /Game/SaskartaGaea/Audio/Station/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = "/Game/SaskartaGaea/Audio/Station"
FX = f"{AUD}/Chain"
SUBMIX = f"{FX}/SM_Saskarta_Station"
CHAIN = f"{FX}/SEC_Saskarta_Radio"
PRESETS = ["SMP_Station_HighPass", "SMP_Station_LowPass", "SMP_Station_Cabinet", "SMP_Station_Comp"]
ROOM = ["SFX_Station_RoomTone_Loop"] + [f"SFX_Station_Room_{n}_01" for n in
                                         ("PaperRustle", "MugDown", "ChairCreak", "KettleClick", "SwitchClick", "MatchStrike")]
ROUTED_FOLDERS = [f"{AUD}/Host", f"{AUD}/Songs"]
EXTRA_ROUTED = ["/Game/Pallbearer/UI/eyetae_title"]

C_SUBMIX = f'''import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
def make(name, cls, factory):
    p = '{FX}/' + name
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    return AT.create_asset(name, '{FX}', cls, factory)
sm = make('SM_Saskarta_Station', unreal.SoundSubmix, None)
print('submix', sm.get_path_name(), 'saved', eal.save_asset('{SUBMIX}', False))
'''

C_PRESETS = f'''import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
def make(name, cls):
    p = '{FX}/' + name
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    return AT.create_asset(name, '{FX}', cls, None)  # no preset factory in Python: AssetTools finds one
hp = make('SMP_Station_HighPass', unreal.SubmixEffectFilterPreset)
s = hp.get_editor_property('settings')
s.set_editor_property('filter_type', unreal.SubmixFilterType.HIGH_PASS)
s.set_editor_property('filter_frequency', 180.0)
s.set_editor_property('filter_q', 0.7)
hp.set_editor_property('settings', s)
lp = make('SMP_Station_LowPass', unreal.SubmixEffectFilterPreset)
s = lp.get_editor_property('settings')
s.set_editor_property('filter_type', unreal.SubmixFilterType.LOW_PASS)
s.set_editor_property('filter_frequency', 5500.0)
s.set_editor_property('filter_q', 0.7)
lp.set_editor_property('settings', s)
print('filters', hp.get_editor_property('settings').get_editor_property('filter_frequency'), lp.get_editor_property('settings').get_editor_property('filter_frequency'))
'''

C_PRESETS2 = f'''import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
def make(name, cls):
    p = '{FX}/' + name
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    return AT.create_asset(name, '{FX}', cls, None)  # no preset factory in Python: AssetTools finds one
eq = make('SMP_Station_Cabinet', unreal.SubmixEffectSubmixEQPreset)
s = eq.get_editor_property('settings')
bands = []
for fr, bw, g in ((400.0, 1.0, -3.0), (1800.0, 1.2, 3.0), (3500.0, 1.0, 1.5)):
    b = unreal.SubmixEffectEQBand()
    b.set_editor_property('frequency', fr)
    b.set_editor_property('bandwidth', bw)
    b.set_editor_property('gain_db', g)
    b.set_editor_property('enabled', True)
    bands.append(b)
s.set_editor_property('eq_bands', bands)
eq.set_editor_property('settings', s)
dp = make('SMP_Station_Comp', unreal.SubmixEffectDynamicsProcessorPreset)
s = dp.get_editor_property('settings')
s.set_editor_property('threshold_db', -20.0)
s.set_editor_property('ratio', 3.0)
s.set_editor_property('attack_time_msec', 8.0)
s.set_editor_property('release_time_msec', 150.0)
s.set_editor_property('output_gain_db', 3.0)
dp.set_editor_property('settings', s)
print('eq bands', len(eq.get_editor_property('settings').get_editor_property('eq_bands')), 'comp', dp.get_editor_property('settings').get_editor_property('ratio'))
'''

C_SOURCECHAIN = f'''import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
def make(name, cls, fac=None):
    p = '{FX}/' + name
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    return AT.create_asset(name, '{FX}', cls, None)
ws = make('SSP_Station_Saturation', unreal.SourceEffectWaveShaperPreset)
s = ws.get_editor_property('settings')
s.set_editor_property('amount', 1.6)
s.set_editor_property('output_gain_db', -1.5)
ws.set_editor_property('settings', s)
ch = make('SSP_Station_WowFlutter', unreal.SourceEffectChorusPreset)
s = ch.get_editor_property('settings')
for k, v in (('depth', 0.06), ('frequency', 0.6), ('feedback', 0.0), ('wet', 0.35), ('dry', 0.8), ('spread', 0.0)):
    m = s.get_editor_property(k + '_modulation')  # the plain fields are deprecated; the values live in the modulation structs
    m.set_editor_property('value', v)
    s.set_editor_property(k + '_modulation', m)
ch.set_editor_property('settings', s)
print('source presets', ws.get_class().get_name(), ch.get_class().get_name())
'''

C_CHAINASSET = f'''import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
p = '{CHAIN}'
if eal.does_asset_exist(p):
    sc = eal.load_asset(p)
else:
    sc = AT.create_asset('SEC_Saskarta_Radio', '{FX}', unreal.SoundEffectSourcePresetChain, None)
E = unreal.SourceEffectChainEntry  # (Hayba accepts it; apply_look.check_banned would not: send these chunks raw)
items = []
for n in ('SSP_Station_Saturation', 'SSP_Station_WowFlutter'):
    e = E()
    e.set_editor_property('preset', eal.load_asset('{FX}/' + n))
    e.set_editor_property('bypass', False)
    items.append(e)
sc.set_editor_property('chain', items)
print('chain', len(sc.get_editor_property('chain')))
sm = eal.load_asset('{SUBMIX}')
da = eal.load_asset('{AUD}/DA_Station')
da.set_editor_property('station_submix', sm)
da.set_editor_property('archive_filter_chain', [eal.load_asset('{FX}/' + n) for n in {PRESETS!r}])
print('DA submix', da.get_editor_property('station_submix'), 'filters', len(da.get_editor_property('archive_filter_chain')))
'''

C_SAVE = f'''import unreal
eal = unreal.EditorAssetLibrary
ok = [eal.save_asset('{FX}/' + n, False) for n in ['SM_Saskarta_Station', 'SEC_Saskarta_Radio'] + {PRESETS!r} + ['SSP_Station_Saturation', 'SSP_Station_WowFlutter']]
print('chain assets saved', sum(1 for x in ok if x), '/', len(ok), 'DA', eal.save_asset('{AUD}/DA_Station', False))
'''

C_ROUTE = '''import unreal
eal = unreal.EditorAssetLibrary
sm = eal.load_asset('__SUBMIX__')
sc = eal.load_asset('__CHAIN__')
n = 0
for p in __PATHS__:
    s = eal.load_asset(p)
    if s is None:
        continue
    s.set_editor_property('sound_submix_object', sm)
    s.set_editor_property('source_effect_chain', sc)
    if eal.save_asset(p, False):
        n += 1
print('routed', n, '/', len(__PATHS__))
'''

C_LIST = f'''import unreal
eal = unreal.EditorAssetLibrary
out = []
for d in {ROUTED_FOLDERS!r}:
    for a in eal.list_assets(d, True, False):
        out.append(str(a).split('.')[0])
print('PATHS', len(out))
for p in out:
    print(p)
'''

C_ROOM = f'''import unreal
eal = unreal.EditorAssetLibrary
tasks = []
for n in {ROOM!r}:
    t = unreal.AssetImportTask()
    t.set_editor_property('filename', '{(ROOT / "Saved/GameAudio/Radio").as_posix()}/' + n + '.wav')
    t.set_editor_property('destination_path', '{AUD}')
    t.set_editor_property('destination_name', n)
    t.set_editor_property('automated', True)
    t.set_editor_property('replace_existing', True)
    t.set_editor_property('save', False)
    tasks.append(t)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
print('room imported', len(tasks))
'''

C_ROOM2 = f'''import unreal
eal = unreal.EditorAssetLibrary
sm = eal.load_asset('{SUBMIX}')
for n in {ROOM!r}:
    s = eal.load_asset('{AUD}/' + n)
    loop = n.endswith('_Loop')
    s.set_editor_property('looping', loop)
    s.set_editor_property('loading_behavior', unreal.SoundWaveLoadingBehavior.RETAIN_ON_LOAD if loop else unreal.SoundWaveLoadingBehavior.FORCE_INLINE)
    s.set_editor_property('sound_submix_object', sm)
    print(n, round(s.get_editor_property('duration'), 1), 'saved', eal.save_asset('{AUD}/' + n, False))
'''


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for name, text in (("10_presets.py", C_PRESETS), ("11_presets2.py", C_PRESETS2), ("12_source.py", C_SOURCECHAIN),
                       ("05_submix.py", C_SUBMIX), ("13_chain_da.py", C_CHAINASSET), ("14_save.py", C_SAVE), ("20_list.py", C_LIST),
                       ("30_room.py", C_ROOM), ("31_room_settings.py", C_ROOM2)):
        (out / name).write_text(text, encoding="utf-8")
    (out / "route_template.py").write_text(C_ROUTE.replace("__SUBMIX__", SUBMIX).replace("__CHAIN__", CHAIN), encoding="utf-8")
    print("wrote chunks to", out)


def route_chunks(paths: list[str], out: Path, n: int = 6):
    t = (out / "route_template.py").read_text(encoding="utf-8")
    files = []
    for i in range(0, len(paths), n):
        f = out / f"40_route_{i // n:03d}.py"
        f.write_text(t.replace("__PATHS__", repr(paths[i:i + n])), encoding="utf-8")
        files.append(f)
    return files


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "route":
        out = Path(sys.argv[2])
        paths = [ln.strip() for ln in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if ln.strip().startswith("/Game/")] + EXTRA_ROUTED
        print(len(route_chunks(paths, out)), "route chunks")
    else:
        main(Path(sys.argv[1]))
