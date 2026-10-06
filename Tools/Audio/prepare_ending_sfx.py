"""Prepare missing ending sounds from existing local WAVs and emit separate import/save calls.

    python Tools/Audio/prepare_ending_sfx.py --out Saved/Verification/ending_voice_20260930/sfx

No downloads or editor calls. Original WAVs remain unchanged. This supplies mechanical,
wind and room sounds; BREATH_* and FOLEY_* actor performances still need actual takes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
RATE = 48000
DEST = '/Game/SaskartaGaea/Audio/Story'
# id: duration, looping, peak, (relative source, start time, gain) layers
SOUNDS = {
    'SFX_LampClick': (1.8, False, .32, [('Radio/SFX_Station_Room_MatchStrike_01.wav', 0, 1)]),
    'SFX_RelayClunk': (.7, False, .32, [('Radio/SFX_Radio_Knob_On_01.wav', 0, 1)]),
    'SFX_RelaySwitch': (.5, False, .24, [('Radio/SFX_Station_Room_SwitchClick_01.wav', 0, 1)]),
    'SFX_OpenChannelHiss': (8, True, .04, [('Radio/AMB_Radio_Static_Soft_Loop.wav', 0, 1)]),
    'SFX_WindLift': (8, False, .22, [('Ambience2/SFX_Above_WideWind_01.wav', 0, 1)]),
    'SFX_LiveRoomClick': (3, False, .25, [('Radio/SFX_Station_Room_SwitchClick_01.wav', 0, 1),
                                      ('Radio/SFX_Station_Room_ChairCreak_01.wav', .3, .6),
                                      ('Radio/SFX_Station_RoomTone_Loop.wav', 0, .15)]),
    'SFX_TapeRoom_A5': (16, False, .18, [('Radio/SFX_Station_RoomTone_Loop.wav', 0, .3),
                                      ('Radio/SFX_Station_Room_MugDown_01.wav', .6, .6),
                                      ('Radio/SFX_Station_Room_ChairCreak_01.wav', 3.2, .45),
                                      ('Radio/SFX_Station_Room_PaperRustle_01.wav', 7.2, .3)]),
}


def render(name, root=ROOT):
    duration, looping, peak, sources = SOUNDS[name]
    mix = np.zeros((round(duration * RATE), 2), dtype=np.float64)
    for relative, at, gain in sources:
        audio, rate = sf.read(root / 'Saved/GameAudio' / relative, always_2d=True)
        if rate != RATE or audio.shape[1] not in (1, 2):
            raise ValueError(f'Unexpected source format: {relative}, {rate} Hz, {audio.shape[1]} channels')
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        start = round(at * RATE)
        count = min(len(audio), len(mix) - start)
        mix[start:start + count] += audio[:count] * gain
    fade_in, fade_out = ((2.0, 3.0) if name == 'SFX_WindLift' else (.015, 1.0 if name == 'SFX_TapeRoom_A5' else .035))
    for seconds, tail in ((fade_in, False), (fade_out, True)):
        n = min(round(seconds * RATE), len(mix) // 2)
        ramp = np.linspace(0, 1, n)[:, None]
        if tail:
            mix[-n:] *= ramp[::-1]
        else:
            mix[:n] *= ramp
    observed = float(np.max(np.abs(mix)))
    if not np.isfinite(mix).all() or observed <= 1e-6:
        raise ValueError(f'Empty or invalid mix: {name}')
    return mix * (peak / observed)


def import_code(name, wav):
    loop = SOUNDS[name][1]
    return f"""import unreal
t=unreal.AssetImportTask()
t.set_editor_property('filename',{wav.resolve().as_posix()!r})
t.set_editor_property('destination_path',{DEST!r})
t.set_editor_property('destination_name',{name!r})
t.set_editor_property('automated',True)
t.set_editor_property('replace_existing',True)
t.set_editor_property('save',False)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
wave=unreal.load_asset({(DEST+'/'+name)!r})
if not isinstance(wave,unreal.SoundWave):
    raise RuntimeError('Ending sound import failed: {name}')
wave.set_editor_property('looping',{loop!r})
if {loop!r}:
    wave.set_editor_property('loading_behavior',unreal.SoundWaveLoadingBehavior.PRIME_ON_LOAD)
print('ENDING_SFX_IMPORTED {name}',wave.get_editor_property('duration'))
"""


def save_code(name):
    return f"""import unreal
wave=unreal.load_asset({(DEST+'/'+name)!r})
if not isinstance(wave,unreal.SoundWave) or wave.get_editor_property('looping')!={SOUNDS[name][1]!r}:
    raise RuntimeError('Ending sound missing or loop mode wrong: {name}')
if not unreal.EditorAssetLibrary.save_loaded_asset(wave,False):
    raise RuntimeError('Ending sound save failed: {name}')
print('ENDING_SFX_SAVED {name}')
"""


def prepare(out, root=ROOT):
    out.mkdir(parents=True, exist_ok=True)
    waves = out / 'wav'
    waves.mkdir(exist_ok=True)
    manifest = []
    for i, name in enumerate(SOUNDS):
        audio = render(name, root)
        wav = waves / (name + '.wav')
        sf.write(wav, audio, RATE, subtype='PCM_16')
        steps = [(f'{2*i:02d}_{name}_import.py', import_code(name, wav)),
                 (f'{2*i+1:02d}_{name}_save.py', save_code(name))]
        for filename, code in steps:
            compile(code, filename, 'exec')
            (out / filename).write_text(code, encoding='utf-8')
        manifest.append({'id': name, 'asset': DEST+'/'+name, 'duration_s': len(audio)/RATE,
                         'looping': SOUNDS[name][1], 'source_layers': SOUNDS[name][3],
                         'steps': [filename for filename, _ in steps]})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.out)
    print(f'Prepared {len(result)} ending sounds and {2*len(result)} import/save chunks; no editor calls.')
