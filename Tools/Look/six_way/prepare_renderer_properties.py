"""Prepare native read-only property requests from the actual renderer inventory."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
READBACK = ROOT / 'Saved/Verification/playtest_feedback_20261001'
OUT = ROOT / 'Saved/Verification/six_way_smoke_20261001/renderer_properties_v1'
FIELDS = ['Material', 'MaterialUserParamBinding', 'SourceMode', 'Alignment', 'FacingMode',
          'SubImageSize', 'bSubImageBlend', 'bEnableCameraDistanceCulling',
          'MinCameraDistance', 'MaxCameraDistance', 'PivotInUVSpace', 'SortMode',
          'bSortOnlyWhenTranslucent', 'bIsEnabled']


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def observed(file):
    prefix = 'NIAGARA_OWNED_OBJECTS /Script/Niagara.NiagaraSpriteRendererProperties '
    lines = file.read_text(encoding='utf-8').splitlines()
    matches = [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
    if len(matches) != 1 or not any(line.startswith('NIAGARA_PATH_INVENTORY_OK ') for line in lines):
        raise ValueError('Incomplete observed inventory: ' + str(file))
    return [row['path'] for row in matches[0] if row['class'] == 'NiagaraSpriteRendererProperties']


def main():
    smoke = READBACK / '02_FireSmallSmoke.readback.txt'
    minimal = READBACK / '01_MinimalLightweight.readback.txt'
    # Exact recorded objects, not paths synthesized from a naming convention.
    chosen = [('smoke_instance', p) for p in observed(smoke)
              if p.endswith(':NE_Smokes_02_4.NiagaraSpriteRendererProperties_0')]
    chosen += [('smoke_parent_copy', p) for p in observed(smoke)
               if p.endswith(':NE_Smokes_02_4.NiagaraEmitter_1.NiagaraSpriteRendererProperties_0')]
    chosen += [('minimal_lightweight', p) for p in observed(minimal)
               if p.endswith(':Minimal_1.Renderer')]
    if len(chosen) != 3:
        raise ValueError('The exact three observed renderer objects must be present')
    if OUT.exists():
        raise ValueError('Preserve existing request/evidence packet')
    OUT.mkdir(parents=True)
    manifest = {'read_only': True, 'source_sha256': digest(Path(__file__)),
                'observed_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (smoke, minimal)},
                'requests': {},
                'acceptance': ['Require properties to contain every requested native name.',
                               'Reject any _truncated response or redaction truncation; do not treat a clipped field as empty.',
                               'No object_set_property, material edits, duplicate, activation, simulation or save.',
                               'Renderer ownership is only a candidate: parent copies may be inactive. Active emitter handles/version, CPU/GPU target, spawn count/lifetime and compiled bindings must be established before integration.']}
    for index, (name, path) in enumerate(chosen):
        request = {'command': 'object_get_property', 'params': {'path': path, 'names': FIELDS}}
        file = OUT / f'{index:02d}_{name}.json'
        file.write_text(json.dumps(request, indent=2) + '\n', encoding='utf-8')
        manifest['requests'][file.name] = digest(file)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('NIAGARA_RENDERER_PROPERTIES_PREPARED', OUT, len(chosen))


if __name__ == '__main__':
    main()
