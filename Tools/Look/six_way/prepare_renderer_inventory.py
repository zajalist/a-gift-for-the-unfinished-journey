"""Prepare three independent read-only ObjectIterator probes; never connects to UE."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'Saved/Verification/six_way_smoke_20261001/renderer_inventory_v1'
sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
import ending_editor

CANDIDATES = (
    ('RadialBurst', '/Niagara/DefaultAssets/Templates/Systems/RadialBurst'),
    ('MinimalLightweight', '/Niagara/DefaultAssets/Templates/Systems/MinimalLightweight'),
    ('FireSmallSmoke', '/Game/Vefects/Free_Fire/Shared/Particles/NS_Fire_Small_Smoke'),
)
SCRIPT = '''import unreal
import json
asset = unreal.load_asset({path!r})
assert asset is not None
namespace = asset.get_path_name()
print('NIAGARA_LOADED_ASSET', namespace, asset.get_class().get_name())
for class_path in ['/Script/Niagara.NiagaraEmitter', '/Script/Niagara.NiagaraSpriteRendererProperties']:
    cls = unreal.load_class(None, class_path)
    assert cls is not None
    rows = []
    for obj in unreal.ObjectIterator(cls):
        name = obj.get_path_name()
        if name.startswith(namespace + ':'):
            rows.append({{'path': name, 'class': obj.get_class().get_name()}})
    assert len(rows) <= 32
    print('NIAGARA_OWNED_OBJECTS', class_path, json.dumps(rows, sort_keys=True))
print('NIAGARA_PATH_INVENTORY_OK', namespace)
'''


def main():
    if OUT.exists():
        raise ValueError('Keep prior inventory evidence; output folder already exists')
    OUT.mkdir(parents=True)
    manifest = {'purpose': 'Read-only object paths; no protected properties, spawns, edits, simulation or saves',
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'scripts': {}}
    for index, (name, path) in enumerate(CANDIDATES):
        script = SCRIPT.format(path=path)
        compile(script, name, 'exec')
        if ending_editor.banned(script):
            raise ValueError('Unsupported bounded editor grammar')
        file = OUT / f'{index:02d}_{name}.py'
        file.write_text(script, encoding='utf-8')
        manifest['scripts'][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('NIAGARA_PATH_INVENTORY_PREPARED', OUT, len(manifest['scripts']))


if __name__ == '__main__':
    main()
