"""Make black atlas pixels transparent in the loading carrier UI material."""
import sys
sys.path.insert(0, 'Tools/Look')
from apply_look import python_run, check_banned

script = '''import unreal
path='/Game/SaskartaGaea/GameFlow/UI/Materials/M_LoadingCarrierSplat'
m=unreal.load_asset(path)
assert m and m.get_editor_property('material_domain')==unreal.MaterialDomain.MD_UI
assert m.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT
mel=unreal.MaterialEditingLibrary
nodes=mel.get_material_expressions(m)
samples=[n for n in nodes if isinstance(n,unreal.MaterialExpressionTextureSample)]
constants=[n for n in nodes if isinstance(n,unreal.MaterialExpressionConstant)]
assert not any(isinstance(n,unreal.MaterialExpressionSaturate) for n in nodes)
assert len(samples)==1 and len(constants)==1
assert samples[0].get_editor_property('texture').get_name()=='T_LoadingCarrier_GaussianAtlas'
lum=mel.create_material_expression(m,unreal.MaterialExpressionDotProduct,180,170)
weights=mel.create_material_expression(m,unreal.MaterialExpressionConstant3Vector,-40,300)
weights.set_editor_property('constant',unreal.LinearColor(0.6,0.6,0.6,1.0))
mel.connect_material_expressions(samples[0],'RGB',lum,'A')
mel.connect_material_expressions(weights,'',lum,'B')
sat=mel.create_material_expression(m,unreal.MaterialExpressionSaturate,400,170)
mel.connect_material_expressions(lum,'',sat,'')
assert mel.connect_material_property(sat,'',unreal.MaterialProperty.MP_OPACITY)
print('LOADING_ALPHA_GRAPH_READY '+str(len(mel.get_material_expressions(m))))
'''
ok, out, err = python_run(check_banned(script))
print(ok, out, err)
assert ok and 'LOADING_ALPHA_GRAPH_READY' in out
