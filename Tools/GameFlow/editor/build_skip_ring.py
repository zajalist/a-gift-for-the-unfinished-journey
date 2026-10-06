# python_run (Hayba), LANE5: M_UI_SkipRing, the caption layer's "hold to skip" ring.
# User Interface domain, translucent. A Custom node draws a thin ring (UV disc, radius 0.78..1.0 of the half
# size, soft 0.06 edges) whose arc is lit clockwise from 12 o'clock up to Pct; the unlit arc stays at 22 %.
# Colour = the RingColor parameter (the caption gold), opacity = ring * VertexColor.A (widget opacity).
# WBP_Saskarta_Caption.SetSkipProgress sets Pct on the image's dynamic material. Saves only this package.
import unreal
PATH_DIR = '/Game/SaskartaGaea/GameFlow/Materials'
NAME = 'M_UI_SkipRing'
HLSL = '''float2 p = UV - 0.5;
float r = length(p) * 2.0;
float a = atan2(p.x, -p.y) / 6.2831853 + 0.5;
float ring = saturate((1.0 - r) / 0.06) * saturate((r - 0.78) / 0.06);
float lit = a <= Pct ? 1.0 : 0.22;
return ring * lit;'''
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
Q = unreal.PropertyAccessChangeNotifyMode.NEVER
path = PATH_DIR + '/' + NAME
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, PATH_DIR, unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_UI)
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
uv = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -700, -100)
pct = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -700, 0)
pct.set_editor_property('parameter_name', 'Pct', Q)
pct.set_editor_property('default_value', 0.0, Q)
col = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -400, -250)
col.set_editor_property('parameter_name', 'RingColor', Q)
col.set_editor_property('default_value', unreal.LinearColor(0.86, 0.66, 0.34, 1.0), Q)
vc = mel.create_material_expression(mat, unreal.MaterialExpressionVertexColor, -400, 150)
cu = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, -400, -50)
cu.set_editor_property('description', 'SkipRing', Q)
cu.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT1, Q)
cu.set_editor_property('code', HLSL, Q)
pins = []
for n in ('UV', 'Pct'):
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', n)
    pins.append(ci)
cu.set_editor_property('inputs', pins, Q)
mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -150, 50)
ok = [mel.connect_material_expressions(uv, '', cu, 'UV'), mel.connect_material_expressions(pct, '', cu, 'Pct'),
      mel.connect_material_expressions(cu, '', mul, 'A'), mel.connect_material_expressions(vc, 'A', mul, 'B'),
      mel.connect_material_property(col, 'RGB', unreal.MaterialProperty.MP_EMISSIVE_COLOR),
      mel.connect_material_property(mul, '', unreal.MaterialProperty.MP_OPACITY)]
errs = mel.recompile_material(mat)
print('RING links', str(ok), 'errors', str(len(errs)), 'nodes', str(mel.get_num_material_expressions(mat)))
print('RING saved', str(eal.save_loaded_asset(mat, False)))
