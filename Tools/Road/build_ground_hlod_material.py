# Build M_Saskarta_GroundHLOD / MI_Saskarta_GroundHLOD, the landscape HLOD material (task HLODFIX).
#
# Sent as the script of Hayba python_run; run it through
#
#     python Tools/Road/prepare_ground_hlod_material.py --send
#
# which fills GROUND_HLOD_HLSL (Shaders/GroundHLOD.hlsl) and the mask mapping
# (Tools/Terrain/MASKS.md) below. It builds and saves only these two assets; it
# does not assign them (the HLOD proxy pass sets HLODMaterialOverride).
#
# Why: the landscape HLOD builder bakes the ground material from above, so the
# Nanite skirts it adds to every HLOD tile (up to a full component deep at the
# lowest LOD) come out as black, stretched walls, and the bake cannot follow
# LOOK2's RVT write pass. With HLODMaterialOverride set, the builder puts this
# material straight on the HLOD mesh: colour from world position, no RVT.
#
# Graph:
#   Mask UV = (AbsoluteWorldPosition.xy - MASK_ORIGIN_CM) / MASK_EXTENT_CM
#   T_Saskarta_Ecology, T_Saskarta_RoadInfluence at Mask UV
#   layer average colour = a vector parameter (linear mean of the colour map x its tint)
#   -> GroundHLOD (Custom) -> BaseColor (rgb), Roughness (a). Normal: vertex normal.

import unreal

GROUND_HLOD_HLSL = r'''__GROUND_HLOD__'''
MASK_ORIGIN_CM = None
MASK_EXTENT_CM = None

PACKAGE_DIR = '/Game/SaskartaGaea/Materials'
ASSET_NAME = 'M_Saskarta_GroundHLOD'
MI_NAME = 'MI_Saskarta_GroundHLOD'
ECO_TEXTURE = '/Game/SaskartaGaea/Masks/T_Saskarta_Ecology'
ROAD_TEXTURE = '/Game/SaskartaGaea/Masks/T_Saskarta_RoadInfluence'
# Layer average colours: the linear mean of each colour map MI_Saskarta_Ground uses, times its
# tint (Rock_Color, T_PH_dirt_aerial_02_diff, T_PH_forest_ground_04_diff, ClumpSnow_Color;
# measured 2026-09-27 from the exported source images).
LAYERS = [('Rock', (0.1114, 0.1012, 0.0727)), ('Dirt', (0.1697, 0.0938, 0.0374)),
          ('Grass', (0.1674, 0.0690, 0.0461)), ('Snow', (0.7272, 0.8597, 0.9601))]
# The ground MI's values, except the grass, snow and alpine ramps, widened by 0.06 each side
# for the breakup noise this material drops (see Shaders/GroundHLOD.hlsl).
SCALARS = [
    ('SlopeLo', 0.16), ('SlopeHi', 0.33), ('GrassLo', 0.36), ('GrassHi', 0.78),
    ('SnowLo', 0.72), ('SnowHi', 0.91), ('AlpineLo', 0.56), ('AlpineHi', 0.84),
    ('AlpineRock', 0.9), ('MacroTone', 0.12),
    ('HueAmount', 0.6), ('ScreeAmount', 0.35), ('RoadLift', 1.6),
    ('AO', 0.9),
]
COLORS = [('DryTint', (1.08, 1.02, 0.92)), ('GrassTint', (0.85, 0.95, 0.70))]
PINS = ['Eco', 'Road', 'N', 'WorldXY', 'RockC', 'DirtC', 'GrassC', 'SnowC', 'DryTint', 'GrassTint'] + \
       [s[0] for s in SCALARS if s[0] not in ('DryTint', 'GrassTint')]

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
ST = unreal.MaterialSamplerType



def build():
    if len(GROUND_HLOD_HLSL) < 500 or MASK_ORIGIN_CM is None or not MASK_EXTENT_CM:
        raise RuntimeError('placeholders not filled; run prepare_ground_hlod_material.py')
    path = PACKAGE_DIR + '/' + ASSET_NAME
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    created = not eal.does_asset_exist(path)
    mat = tools.create_asset(ASSET_NAME, PACKAGE_DIR, unreal.Material, unreal.MaterialFactoryNew()) if created \
        else eal.load_asset(path)
    removed = mel.get_num_material_expressions(mat)
    mel.delete_all_material_expressions(mat)
    mat.set_editor_property('used_with_nanite', True, QUIET)
    mat.set_editor_property('used_with_instanced_static_meshes', True, QUIET)

    links = []

    def add(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def link(s, so, d, dp):
        links.append((s, so, d, dp))

    wpos = add(unreal.MaterialExpressionWorldPosition, -2400, 0)
    origin = add(unreal.MaterialExpressionConstant3Vector, -2400, 120)
    origin.set_editor_property('constant', unreal.LinearColor(MASK_ORIGIN_CM[0], MASK_ORIGIN_CM[1], 0.0, 0.0), QUIET)
    rel = add(unreal.MaterialExpressionSubtract, -2200, 40)
    link(wpos, '', rel, 'A')
    link(origin, '', rel, 'B')
    rel_xy = add(unreal.MaterialExpressionComponentMask, -2050, 40)
    rel_xy.set_editor_property('r', True, QUIET)
    rel_xy.set_editor_property('g', True, QUIET)
    rel_xy.set_editor_property('b', False, QUIET)
    rel_xy.set_editor_property('a', False, QUIET)
    link(rel, '', rel_xy, '')
    extent = add(unreal.MaterialExpressionConstant, -2050, 160)
    extent.set_editor_property('r', MASK_EXTENT_CM, QUIET)
    mask_uv = add(unreal.MaterialExpressionDivide, -1900, 80)
    link(rel_xy, '', mask_uv, 'A')
    link(extent, '', mask_uv, 'B')

    samples = {}
    for key, tpath, y in (('Eco', ECO_TEXTURE, -300), ('Road', ROAD_TEXTURE, 300)):
        s = add(unreal.MaterialExpressionTextureSample, -1600, y)
        s.set_editor_property('texture', eal.load_asset(tpath), QUIET)
        s.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)
        link(mask_uv, '', s, 'UVs')
        samples[key] = s

    custom = add(unreal.MaterialExpressionCustom, -600, 0)
    custom.set_editor_property('description', 'GroundHLOD', QUIET)
    custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
    custom.set_editor_property('code', GROUND_HLOD_HLSL, QUIET)
    ins = []
    for pin_name in PINS:
        pin = unreal.CustomInput()
        pin.set_editor_property('input_name', pin_name)
        ins.append(pin)
    custom.set_editor_property('inputs', ins)   # notified: rebuilds the input pins

    link(samples['Eco'], 'RGBA', custom, 'Eco')
    link(samples['Road'], 'RGBA', custom, 'Road')
    vn = add(unreal.MaterialExpressionVertexNormalWS, -1600, 700)
    link(vn, '', custom, 'N')
    link(rel_xy, '', custom, 'WorldXY')

    order = 0
    for layer, rgb in LAYERS:
        p = add(unreal.MaterialExpressionVectorParameter, -1600, 900 + 120 * order)
        p.set_editor_property('parameter_name', layer + ' Color', QUIET)
        p.set_editor_property('default_value', unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0), QUIET)
        p.set_editor_property('group', 'Layers', QUIET)
        link(p, 'RGB', custom, layer + 'C')
        order += 1

    y = -1400
    for name, default in SCALARS:
        p = add(unreal.MaterialExpressionScalarParameter, -1000, y)
        p.set_editor_property('parameter_name', name, QUIET)
        p.set_editor_property('default_value', default, QUIET)
        p.set_editor_property('group', 'HLOD', QUIET)
        link(p, '', custom, name)
        y += 70
    for name, rgb in COLORS:
        p = add(unreal.MaterialExpressionVectorParameter, -1000, y)
        p.set_editor_property('parameter_name', name, QUIET)
        p.set_editor_property('default_value', unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0), QUIET)
        p.set_editor_property('group', 'HLOD', QUIET)
        link(p, 'RGB', custom, name)
        y += 70

    rgb = add(unreal.MaterialExpressionComponentMask, -300, -60)
    for ch, on in zip('rgba', (True, True, True, False)):
        rgb.set_editor_property(ch, on, QUIET)
    link(custom, '', rgb, '')
    alpha = add(unreal.MaterialExpressionComponentMask, -300, 60)
    for ch, on in zip('rgba', (False, False, False, True)):
        alpha.set_editor_property(ch, on, QUIET)
    link(custom, '', alpha, '')

    failed = []
    for s, so, d, dp in links:
        if not mel.connect_material_expressions(s, so, d, dp):
            failed.append(dp + '<-' + s.get_class().get_name()[18:] + '.' + so)
    MP = unreal.MaterialProperty
    props_ok = [mel.connect_material_property(rgb, '', MP.MP_BASE_COLOR),
                mel.connect_material_property(alpha, '', MP.MP_ROUGHNESS)]
    mel.recompile_material(mat)
    saved = eal.save_loaded_asset(mat, False)

    mi_path = PACKAGE_DIR + '/' + MI_NAME
    mi_created = not eal.does_asset_exist(mi_path)
    mi = tools.create_asset(MI_NAME, PACKAGE_DIR, unreal.MaterialInstanceConstant,
                            unreal.MaterialInstanceConstantFactoryNew()) if mi_created else eal.load_asset(mi_path)
    mel.set_material_instance_parent(mi, mat)
    mi_saved = eal.save_loaded_asset(mi, False)
    print('GH created=' + str(created) + ' removed=' + str(removed) + ' nodes=' + str(mel.get_num_material_expressions(mat)))
    print('GH failed_links=' + str(failed) + ' props_ok=' + str(props_ok))
    print('GH saved=' + str(saved) + ' mi_created=' + str(mi_created) + ' mi_saved=' + str(mi_saved))


build()
