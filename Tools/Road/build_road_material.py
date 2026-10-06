# Build M_Saskarta_RoadRVT and MI_Saskarta_RoadRVT in the live editor (world sprint, Tasks V1, V1b).
#
# Sent as the script of Hayba python_run. It is NOT a standalone module: run
#
#     python Tools/Road/prepare_road_material.py --send
#
# which fills the three placeholders below (python_run may not read files):
#   HLSL_SOURCE     <- the full text of Shaders/RoadRVT.hlsl, road polyline filled in
#   MASK_ORIGIN_CM  <- (X0, Y0) of the mask UV mapping, from Tools/Terrain/MASKS.md
#   MASK_EXTENT_CM  <- the mapping extent, from Tools/Terrain/MASKS.md (Ruling R5)
#
# python_run rules this file obeys: 5 s cooperative deadline; none of the
# banned words (see Tools/Road/ROAD.md); the policy scanner also reads string
# contents, which is why the HLSL avoids them too.
#
# Result: /Game/SaskartaGaea/Road/M_Saskarta_RoadRVT (+ MI_Saskarta_RoadRVT)
#   Surface domain, Translucent (the RVT Opacity pin blends only when the
#   material is translucent), Used with Spline Meshes. The road ribbon draws
#   it ONLY into RVT_Saskarta_Terrain (render pass Never), so the main-pass
#   outputs stay unconnected.
#
#   Mask sample: T_Saskarta_RoadInfluence at
#       UV = (AbsoluteWorldPosition.xy - MASK_ORIGIN_CM) / MASK_EXTENT_CM
#     R road core, B neglect, A surface.
#   Wear = lerp(WearDirt, WearPaving, Surface)
#   RoadRVT (Custom, Shaders/RoadRVT.hlsl): from the world position (minus the
#     mask origin) and the mask channels only, never a mesh UV (V1b), so the
#     ribbon segments and the joint caps write identical texels. Returns
#     float4(BaseColor, Roughness); extra outputs RoadNormalWS (world normal)
#     and RoadOpacity (the noise-warped edge coverage).
#   RVT Output: BaseColor, Roughness, Normal, Opacity = Mask = RoadOpacity.
#
# Idempotent: a re-run deletes every expression in the master and rebuilds it.
# Saves only these two packages. Starts nothing: no PIE, and no level load.
# Shader compilation finishes asynchronously after this returns; read the
# shader errors and instruction counts with the Hayba material_compile tool, as ROAD.md says.

import unreal

HLSL_SOURCE = r'''__HLSL__'''
MASK_ORIGIN_CM = None
MASK_EXTENT_CM = None

PACKAGE_DIR = '/Game/SaskartaGaea/Road'
ASSET_NAME = 'M_Saskarta_RoadRVT'
MI_NAME = 'MI_Saskarta_RoadRVT'
ASSET_PATH = PACKAGE_DIR + '/' + ASSET_NAME
MI_PATH = PACKAGE_DIR + '/' + MI_NAME
MASK_TEXTURE = '/Game/SaskartaGaea/Masks/T_Saskarta_RoadInfluence'
# A new master is made by DUPLICATING this template, then its graph is rebuilt.
# Measured in UE 5.8 (task-V1-report.md): a material created with
# MaterialFactoryNew never drew into the RVT from a spline mesh, even as a bare
# red RVT Output with every usage flag matching; a duplicate of this working
# RVT writer, with the very same rebuilt graph, did.
TEMPLATE = '/Game/Pallbearer/Road/M_PB_RoadRVT'
GROUP = 'Road'

ROAD_PINS = ['P', 'Core', 'Surface', 'Neglect', 'Wear', 'HalfWidth',
             'DirtColor', 'GravelColor', 'PavingColor', 'CrownGrassColor']
# (name, default). RoadHalfWidth in metres: the road core wanders 3.5-5.5 m
# wide, and the ruts sit at about 0.45 of this from the centre line.
SCALARS = [('RoadHalfWidth', 2.25), ('WearDirt', 0.45), ('WearPaving', 0.78)]
# Linear albedo, kept in the dark, desaturated range of the lane-L board. V1b made
# them darker and warmer: V1's set read as a pale grey band on the red-brown ground.
COLORS = [('DirtColor', (0.130, 0.092, 0.066)), ('GravelColor', (0.145, 0.120, 0.096)),
          ('PavingColor', (0.140, 0.124, 0.104)), ('CrownGrassColor', (0.080, 0.086, 0.046))]

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER

# ---- 0. Validate before touching anything --------------------------------------
if len(HLSL_SOURCE) < 4000 or 'RoadNormalWS' not in HLSL_SOURCE or 'slabVis' not in HLSL_SOURCE or 'ROAD_POINTS' in HLSL_SOURCE:
    raise RuntimeError('HLSL_SOURCE holds ' + str(len(HLSL_SOURCE)) +
                       ' chars: run Tools/Road/prepare_road_material.py, do not send this file raw')
if MASK_ORIGIN_CM is None or MASK_EXTENT_CM is None or MASK_EXTENT_CM <= 0:
    raise RuntimeError('mask mapping missing: run Tools/Road/prepare_road_material.py')
mask_tex = eal.load_asset(MASK_TEXTURE)
if mask_tex is None:
    raise RuntimeError('missing ' + MASK_TEXTURE + ' (Task P1b imports it)')

# ---- 1. Load or create the master -----------------------------------------------
tools = unreal.AssetToolsHelpers.get_asset_tools()
created = False
if eal.does_asset_exist(ASSET_PATH):
    mat = eal.load_asset(ASSET_PATH)
else:
    mat = eal.duplicate_asset(TEMPLATE, ASSET_PATH)
    created = True
if not isinstance(mat, unreal.Material):
    raise RuntimeError('expected a Material at ' + ASSET_PATH + ', found ' + str(mat))

mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_SURFACE)
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
mat.set_editor_property('used_with_spline_meshes', True)
mat.set_editor_property('used_with_instanced_static_meshes', True)

removed = 0
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
    removed += 1


def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)


def custom(desc, code, out_type, pins, extra, x, y):
    # extra: [(output name, CustomMaterialOutputType)]
    node = add(unreal.MaterialExpressionCustom, x, y)
    node.set_editor_property('description', desc, QUIET)
    node.set_editor_property('output_type', out_type, QUIET)
    node.set_editor_property('code', code, QUIET)
    ins = []
    for pin_name in pins:
        pin = unreal.CustomInput()
        pin.set_editor_property('input_name', pin_name)
        ins.append(pin)
    node.set_editor_property('inputs', ins, QUIET)
    outs = []
    for out_name, out_kind in extra:
        out = unreal.CustomOutput()
        out.set_editor_property('output_name', out_name)
        out.set_editor_property('output_type', out_kind)
        outs.append(out)
    # notified set: the node rebuilds its output pins only on a property-change event
    node.set_editor_property('additional_outputs', outs)
    return node


def mask(src, r, g, b, a, x, y):
    node = add(unreal.MaterialExpressionComponentMask, x, y)
    node.set_editor_property('r', r, QUIET)
    node.set_editor_property('g', g, QUIET)
    node.set_editor_property('b', b, QUIET)
    node.set_editor_property('a', a, QUIET)
    links.append((src[0], src[1], node, ''))
    return node


links = []

# ---- 2. Nodes -------------------------------------------------------------------
wpos = add(unreal.MaterialExpressionWorldPosition, -2400, 100)
origin = add(unreal.MaterialExpressionConstant3Vector, -2400, 250)
origin.set_editor_property('constant', unreal.LinearColor(MASK_ORIGIN_CM[0], MASK_ORIGIN_CM[1], 0.0, 0.0), QUIET)
rel = add(unreal.MaterialExpressionSubtract, -2150, 150)
links.append((wpos, '', rel, 'A'))
links.append((origin, '', rel, 'B'))
rel_xy = mask((rel, ''), True, True, False, False, -1950, 150)
extent = add(unreal.MaterialExpressionConstant, -1950, 300)
extent.set_editor_property('r', MASK_EXTENT_CM, QUIET)
mask_uv = add(unreal.MaterialExpressionDivide, -1750, 200)
links.append((rel_xy, '', mask_uv, 'A'))
links.append((extent, '', mask_uv, 'B'))
tex = add(unreal.MaterialExpressionTextureSample, -1550, 150)
tex.set_editor_property('texture', mask_tex, QUIET)
tex.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR, QUIET)
links.append((mask_uv, '', tex, 'UVs'))

scalar_nodes = {}
row = 0
for name, default in SCALARS:
    node = add(unreal.MaterialExpressionScalarParameter, -2400, 450 + 80 * row)
    node.set_editor_property('parameter_name', name, QUIET)
    node.set_editor_property('default_value', default, QUIET)
    node.set_editor_property('group', GROUP, QUIET)
    node.set_editor_property('sort_priority', row, QUIET)
    scalar_nodes[name] = node
    row += 1
color_nodes = {}
for name, rgb in COLORS:
    node = add(unreal.MaterialExpressionVectorParameter, -2400, 450 + 80 * row)
    node.set_editor_property('parameter_name', name, QUIET)
    node.set_editor_property('default_value', unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0), QUIET)
    node.set_editor_property('group', GROUP, QUIET)
    node.set_editor_property('sort_priority', row, QUIET)
    color_nodes[name] = node
    row += 1

wear = add(unreal.MaterialExpressionLinearInterpolate, -1250, 500)
links.append((scalar_nodes['WearDirt'], '', wear, 'A'))
links.append((scalar_nodes['WearPaving'], '', wear, 'B'))
links.append((tex, 'A', wear, 'Alpha'))

road = custom('RoadRVT', HLSL_SOURCE, unreal.CustomMaterialOutputType.CMOT_FLOAT4, ROAD_PINS,
              [('RoadNormalWS', unreal.CustomMaterialOutputType.CMOT_FLOAT3),
               ('RoadOpacity', unreal.CustomMaterialOutputType.CMOT_FLOAT1)], -900, 0)
links.append((rel, '', road, 'P'))
links.append((tex, 'R', road, 'Core'))
links.append((tex, 'A', road, 'Surface'))
links.append((tex, 'B', road, 'Neglect'))
links.append((wear, '', road, 'Wear'))
links.append((scalar_nodes['RoadHalfWidth'], '', road, 'HalfWidth'))
for name, rgb in COLORS:
    links.append((color_nodes[name], 'RGB', road, name))

base_rgb = mask((road, ''), True, True, True, False, -550, -50)
rough = mask((road, ''), False, False, False, True, -550, 80)

out = add(unreal.MaterialExpressionRuntimeVirtualTextureOutput, -200, 0)
links.append((base_rgb, '', out, 'BaseColor'))
links.append((rough, '', out, 'Roughness'))
links.append((road, 'RoadNormalWS', out, 'Normal'))
links.append((road, 'RoadOpacity', out, 'Opacity'))
links.append((road, 'RoadOpacity', out, 'Mask'))

# ---- 3. Wires -------------------------------------------------------------------
failed_links = []
for src, src_out, dst, dst_pin in links:
    if not mel.connect_material_expressions(src, src_out, dst, dst_pin):
        failed_links.append(dst.get_class().get_name() + '.' + dst_pin + '<-' + src_out)

# ---- 4. Compile once, save the master, then the instance -------------------------
errors = mel.recompile_material(mat)
saved = eal.save_loaded_asset(mat, False)

mi_created = False
if eal.does_asset_exist(MI_PATH):
    mi = eal.load_asset(MI_PATH)
else:
    mi = tools.create_asset(MI_NAME, PACKAGE_DIR, unreal.MaterialInstanceConstant,
                            unreal.MaterialInstanceConstantFactoryNew())
    mi_created = True
mel.set_material_instance_parent(mi, mat)
mi_saved = eal.save_loaded_asset(mi, False)

# ---- 5. Readback ----------------------------------------------------------------
def wiring(node):
    names = mel.get_material_expression_input_names(node)
    srcs = mel.get_inputs_for_material_expression(mat, node)
    parts = []
    for i in range(len(names)):
        src = srcs[i] if i < len(srcs) else None
        parts.append(str(names[i]) + '<-' + ('NONE' if src is None else src.get_class().get_name()[18:]))
    return ','.join(parts)


print('RV asset=' + ASSET_PATH + ' created=' + str(created) + ' removed_nodes=' + str(removed))
print('RV domain=' + str(mat.get_editor_property('material_domain')) + ' blend=' +
      str(mat.get_editor_property('blend_mode')) + ' spline=' + str(mat.get_editor_property('used_with_spline_meshes')) +
      ' ism=' + str(mat.get_editor_property('used_with_instanced_static_meshes')))
print('RV nodes=' + str(mel.get_num_material_expressions(mat)))
print('RV mask_origin=' + str(MASK_ORIGIN_CM) + ' extent=' + str(MASK_EXTENT_CM) +
      ' tex=' + str(tex.get_editor_property('texture').get_path_name()))
print('RV road_code=' + str(len(road.get_editor_property('code'))) + '/' + str(len(HLSL_SOURCE)))
print('RV road_pins=' + wiring(road))
print('RV rvt_out=' + wiring(out))
print('RV failed_links=' + str(failed_links))
print('RV recompile_errors=' + str(len(errors)) + ' ' + ' | '.join([str(e) for e in errors]))
print('RV saved=' + str(saved) + ' mi=' + MI_PATH + ' mi_created=' + str(mi_created) + ' mi_parent=' +
      str(mi.get_editor_property('parent').get_path_name()) + ' mi_saved=' + str(mi_saved))
