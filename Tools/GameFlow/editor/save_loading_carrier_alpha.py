"""Save and verify the repaired loading carrier UI material."""
import sys
sys.path.insert(0, 'Tools/Look')
from apply_look import python_run, check_banned

script = '''import unreal
path='/Game/SaskartaGaea/GameFlow/UI/Materials/M_LoadingCarrierSplat'
m=unreal.load_asset(path)
assert m
mel=unreal.MaterialEditingLibrary
nodes=mel.get_material_expressions(m)
sat=[n for n in nodes if isinstance(n,unreal.MaterialExpressionSaturate)]
dot=[n for n in nodes if isinstance(n,unreal.MaterialExpressionDotProduct)]
assert len(sat)==1 and len(dot)==1
assert mel.get_material_property_input_node(m,unreal.MaterialProperty.MP_OPACITY)==sat[0]
ok=unreal.EditorAssetLibrary.save_loaded_asset(m,False)
print('LOADING_ALPHA_SAVE '+str(ok))
'''
ok, out, err = python_run(check_banned(script))
print(ok, out, err)
assert ok and 'LOADING_ALPHA_SAVE True' in out
