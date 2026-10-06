#!/usr/bin/env python3
"""Plan/emit scoped voice sound-class installation. Root executes emitted scripts in an idle editor.

    python Tools/Audio/install_voice_class.py plan
    python Tools/Audio/install_voice_class.py emit --out <scratch-directory>
    python Tools/Audio/install_voice_class.py verify --out <prepared-directory>

Creation, assignment and saving are separate editor calls. Saves touch at most 20 voice assets each.
Install class and assignments first, then apply the updated BFL_SaskartaSettings ApplyAudio graph.
SC_Voice is an independent class: ApplyAudio supplies master * voice, leaving engine assets untouched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CLASS='/Game/SaskartaGaea/Audio/SC_Voice'
FOLDERS=('Lines','CarrierVoice','Station/Host','Scan')

def voice_assets(root=ROOT):
    base=root/'Content/SaskartaGaea/Audio'
    paths=[]
    for folder in FOLDERS:
        for p in sorted((base/folder).rglob('*.uasset')):
            if p.stem.startswith(('SFX_','SC_','SM_','SMX_','SMix_','ATT_','DA_')):
                continue
            paths.append('/Game/'+p.relative_to(root/'Content').with_suffix('').as_posix())
    return paths

def class_code():
    return f"""import unreal
eal=unreal.EditorAssetLibrary
path={CLASS!r}
voice=eal.load_asset(path)
if voice is None:
    voice=unreal.AssetToolsHelpers.get_asset_tools().create_asset('SC_Voice','/Game/SaskartaGaea/Audio',unreal.SoundClass,unreal.SoundClassFactory())
if voice is None:
    raise RuntimeError('SC_Voice creation failed')
if not isinstance(voice,unreal.SoundClass):
    raise RuntimeError('SC_Voice path contains a different asset type')
if voice.get_editor_property('parent_class') is not None:
    raise RuntimeError('SC_Voice already has a parent; inspect and detach its hierarchy before this independent-class install')
print('VOICE_CLASS '+voice.get_path_name())
"""

def assignment_code(paths):
    if not 1<=len(paths)<=20:
        raise ValueError('Voice assignment needs 1 to 20 paths')
    return f"""import unreal
eal=unreal.EditorAssetLibrary
voice=eal.load_asset({CLASS!r})
if not isinstance(voice,unreal.SoundClass):
    raise RuntimeError('Install SC_Voice first')
paths={paths!r}
waves=[]
for path in paths:
    wave=eal.load_asset(path)
    if not isinstance(wave,unreal.SoundBase):
        raise RuntimeError('Expected voice SoundBase at '+path)
    waves.append(wave)
for wave in waves:
    wave.set_editor_property('sound_class_object',voice)
    assigned=wave.get_editor_property('sound_class_object')
    if assigned is None or assigned.get_path_name()!=voice.get_path_name():
        raise RuntimeError('Voice routing readback failed '+wave.get_path_name())
print('VOICE_ASSIGNED '+str(len(paths)))
"""

def save_code(paths, *, sound_class=False):
    if not 1<=len(paths)<=20:
        raise ValueError('Voice save needs 1 to 20 paths')
    check = ("if not isinstance(asset,unreal.SoundClass) or asset.get_editor_property('parent_class') is not None:\n"
             "        raise RuntimeError('Expected independent voice class at '+path)" if sound_class else
             "if not isinstance(asset,unreal.SoundBase):\n"
             "        raise RuntimeError('Expected voice SoundBase at '+path)\n"
             "    assigned=asset.get_editor_property('sound_class_object')\n"
             f"    if assigned is None or assigned.get_path_name().split('.')[0]!={CLASS!r}:\n"
             "        raise RuntimeError('Voice routing missing before save '+path)")
    return f"""import unreal
eal=unreal.EditorAssetLibrary
paths={paths!r}
assets=[]
for path in paths:
    asset=eal.load_asset(path)
    {check}
    assets.append(asset)
for asset in assets:
    if not eal.save_loaded_asset(asset,False):
        raise RuntimeError('Voice asset save failed '+asset.get_path_name())
print('VOICE_SAVED '+str(len(paths)))
"""

def installation_steps(paths, batch_size=20):
    if not 1<=batch_size<=20:
        raise ValueError('Batch size must be between 1 and 20')
    steps=[('000_voice_class.py',class_code()),('001_voice_class_save.py',save_code([CLASS],sound_class=True))]
    for i in range(0,len(paths),batch_size):
        batch=paths[i:i+batch_size]
        steps.append((f'{len(steps):03d}_voice_assign.py',assignment_code(batch)))
        steps.append((f'{len(steps):03d}_voice_save.py',save_code(batch)))
    return steps

def fingerprints(out, steps):
    return {'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'steps_sha256':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in steps}}

def verify(out, root=ROOT):
    """Read-only: reject changed inventory, scripts, ordering or recorded fingerprints."""
    manifest=json.loads((out/'voice-manifest.json').read_text(encoding='utf-8'))
    paths=voice_assets(root)
    if manifest.get('class')!=CLASS or manifest.get('paths')!=paths or manifest.get('count')!=len(paths):
        raise ValueError('Voice inventory changed; emit a fresh plan before installation')
    steps=installation_steps(paths,manifest['batch_size'])
    if manifest.get('steps')!=[name for name,_ in steps]:
        raise ValueError('Voice steps or order changed; emit a fresh plan before installation')
    if {p.name for p in out.glob('*.py')}!={name for name,_ in steps}:
        raise ValueError('Missing or extra voice Python chunks')
    for name, expected in steps:
        if (out/name).read_text(encoding='utf-8')!=expected:
            raise ValueError('Voice script differs from current generator: '+name)
    actual=fingerprints(out,manifest['steps'])
    for field,value in actual.items():
        if field in manifest and manifest[field]!=value:
            raise ValueError('Stale voice manifest fingerprint: '+field)
    return manifest

def emit(out, paths, batch_size=20):
    steps=installation_steps(paths,batch_size)
    out.mkdir(parents=True,exist_ok=True)
    if any(out.glob('*.py')):
        raise ValueError('Use an output directory without old Python chunks')
    for name, code in steps:
        compile(code,name,'exec')
        (out/name).write_text(code,encoding='utf-8')
    manifest={'class':CLASS,'paths':paths,'count':len(paths),'batch_size':batch_size,
              'steps':[name for name,_ in steps]}
    manifest.update(fingerprints(out,manifest['steps']))
    (out/'voice-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=('plan','emit','verify'))
    ap.add_argument('--out',type=Path)
    ap.add_argument('--batch-size',type=int,default=20,choices=range(1,21))
    args=ap.parse_args()
    paths=voice_assets()
    if args.mode=='plan':
        print(json.dumps({'class':CLASS,'voice_assets':len(paths),'save_batches':(len(paths)+args.batch_size-1)//args.batch_size,'paths':paths},indent=2))
        return
    if args.out is None:
        ap.error(args.mode+' requires --out')
    if args.mode=='verify':
        manifest=verify(args.out)
        print(f'VOICE_PLAN_CURRENT {len(manifest["steps"])} scripts, {manifest["count"]} voice assets; no editor operations performed.')
        return
    manifest=emit(args.out,paths,args.batch_size)
    print(f'Emitted {len(manifest["steps"])} editor scripts for {len(paths)} voice assets; no editor operations performed.')

if __name__=='__main__':
    main()
