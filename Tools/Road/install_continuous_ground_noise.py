"""Install only the continuous-noise code in the two existing ground materials.

Run one editor phase per call after the 4K capture session. Requires the caller's
Hayba lease in HAYBA_LEASE/HAYBA_AGENT_ID. Never rebuilds the material graph or
changes landscape assignment, instance parameters, or HLOD meshes.
"""

import argparse
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools' / 'Look'))
from apply_look import check_banned, python_run  # noqa: E402

MATERIALS = {
    'auto': ('GroundAuto', 'M_Saskarta_Ground', ROOT / 'Shaders' / 'GroundAuto.hlsl',
             'frac(m1 * 5.13 + m2 * 3.71)', 'float mh = 0.6 * (m1 - 0.5) - 0.4 * (m2 - 0.5);'),
    'hlod': ('GroundHLOD', 'M_Saskarta_GroundHLOD', ROOT / 'Shaders' / 'GroundHLOD.hlsl',
             'frac(Eco.a * 7.31 + 0.37)', '1.6 * (Eco.a - 0.5)'),
}


def editor_script(kind: str, phase: str) -> str:
    description, asset, source_path, old, new = MATERIALS[kind]
    source = source_path.read_text(encoding='utf-8')
    assert old not in source and new in source and len(source) > 500
    path = f'/Game/SaskartaGaea/Materials/{asset}'
    header = f'''import unreal
m=unreal.load_asset({path!r})
assert isinstance(m,unreal.Material)
nodes=[n for n in unreal.MaterialEditingLibrary.get_material_expressions(m) if isinstance(n,unreal.MaterialExpressionCustom) and n.get_editor_property('description')=={description!r}]
assert len(nodes)==1
n=nodes[0]
'''
    if phase == 'set':
        body = f'''before=n.get_editor_property('code')
assert {old!r} in before and {new!r} not in before
n.modify()
n.set_editor_property('code',{source!r},unreal.PropertyAccessChangeNotifyMode.NEVER)
assert n.get_editor_property('code')=={source!r}
print('GROUND_CODE_SET {kind} {hashlib.sha256(source.encode()).hexdigest()}')
'''
    elif phase == 'save':
        body = f'''assert n.get_editor_property('code')=={source!r}
ok=unreal.EditorAssetLibrary.save_loaded_asset(m,False)
print('GROUND_CODE_SAVE {kind} '+str(ok))
'''
    elif phase == 'verify':
        body = f'''current=n.get_editor_property('code')
print('GROUND_CODE_VERIFY {kind} '+str(current=={source!r})+' '+str(len(current)))
'''
    else:
        raise ValueError(phase)
    return check_banned(header + body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('material', choices=MATERIALS)
    parser.add_argument('phase', choices=('check', 'set', 'save', 'verify'))
    args = parser.parse_args()
    description, asset, source_path, old, new = MATERIALS[args.material]
    source = source_path.read_text(encoding='utf-8')
    assert old not in source and new in source and len(source) > 500
    if args.phase == 'check':
        print(args.material, asset, description, len(source), hashlib.sha256(source.encode()).hexdigest())
        return
    ok, output, error = python_run(editor_script(args.material, args.phase))
    print(ok, output, error)
    assert ok and f'GROUND_CODE_{args.phase.upper()} {args.material}' in output


if __name__ == '__main__':
    main()
