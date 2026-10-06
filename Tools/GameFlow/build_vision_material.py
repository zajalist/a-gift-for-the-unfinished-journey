# Build M_PP_CarrierVision in the live editor (UE 5.8, Pallbearer / Saskarta).
#
# Sent as the script of Hayba python_run. It is NOT a standalone module: the
# caller first substitutes the full text of Shaders/CarrierVision.hlsl for the
# placeholder inside HLSL_SOURCE below (see build_vision_material.md).
#
# python_run rules this file obeys: 5 s cooperative deadline; no try/with
# statements; no getattr; no file-open, string-substitute or level-switch
# calls. The policy scanner also reads string contents, which is why the HLSL
# must not spell any banned call name either.
#
# Result: /Game/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision
#   Post Process domain, blendable location Scene Color After Tonemapping,
#   Emissive Color <- Custom node (code = CarrierVision.hlsl, output Float3).
#   Custom inputs, in this exact order:
#     UV              <- ScreenPosition.ViewportUV
#     ViewSize        <- ViewSize
#     Time            <- Time (game time, pauses with the game)
#     SceneColorDummy <- SceneTexture PostProcessInput0 .Color (binds the
#                        scene texture; the HLSL never reads the pin)
#     VisionStart, VisionMode, GlitchSeed, RampTime, OffTime, BootBlack,
#     OnTime, Residual <- scalar parameters
#     OpticsTint      <- vector parameter .RGB
#
# Idempotent: a re-run deletes every expression and rebuilds the graph.
# Saves only this one package. Prints CV lines for readback; the caller must
# still run Hayba material_compile for shader errors and instruction counts,
# because shader compilation finishes asynchronously after this returns.

import unreal

HLSL_SOURCE = r'''__HLSL__'''

PACKAGE_DIR = '/Game/SaskartaGaea/GameFlow/Materials'
ASSET_NAME = 'M_PP_CarrierVision'
ASSET_PATH = PACKAGE_DIR + '/' + ASSET_NAME

# Custom node pins, in node order. Names are the HLSL parameter names.
CUSTOM_PINS = ['UV', 'ViewSize', 'Time', 'SceneColorDummy', 'VisionStart', 'VisionMode',
               'GlitchSeed', 'RampTime', 'OffTime', 'BootBlack', 'OnTime', 'Residual',
               'OpticsTint']

# Scalar parameters and defaults. BPC_CarrierVision pushes the timing values at
# Setup so Blueprint and shader share one set of numbers; these defaults match.
SCALARS = [('VisionStart', 0.0), ('VisionMode', 0.0), ('GlitchSeed', 0.0),
           ('RampTime', 0.8), ('OffTime', 0.3), ('BootBlack', 0.3),
           ('OnTime', 0.3), ('Residual', 1.0)]
TINT_NAME = 'OpticsTint'
TINT_DEFAULT = unreal.LinearColor(0.78, 0.93, 1.0, 1.0)
PARAM_GROUP = 'CarrierVision'

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary

# Node properties are set without change notification: every notified set on
# an expression recompiles the whole material (UMaterialExpression::
# PostEditChangeProperty), and one recompile at the end is enough.
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER

# ---- 0. Validate before touching anything --------------------------------------
if len(HLSL_SOURCE) < 2000 or 'SceneTextureLookup' not in HLSL_SOURCE or 'FCarrier' not in HLSL_SOURCE:
    raise RuntimeError('HLSL_SOURCE holds ' + str(len(HLSL_SOURCE)) +
                       ' chars: substitute Shaders/CarrierVision.hlsl into it before sending')

# ---- 1. Load or create the material ---------------------------------------------
created = False
if eal.does_asset_exist(ASSET_PATH):
    mat = eal.load_asset(ASSET_PATH)
else:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = tools.create_asset(ASSET_NAME, PACKAGE_DIR, unreal.Material, unreal.MaterialFactoryNew())
    created = True
if not isinstance(mat, unreal.Material):
    raise RuntimeError('expected a Material at ' + ASSET_PATH + ', found ' + str(mat))

# Material-level settings keep normal notification so UMaterial runs its own
# domain / blendable bookkeeping.
mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_POST_PROCESS)
mat.set_editor_property('blendable_location', unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)

# ---- 2. Clear the graph (re-run) ------------------------------------------------
# get_material_expressions returns a copy, so deleting while iterating is safe.
# (delete_all_material_expressions ranges over the live array while removing
# from it and can skip nodes.)
removed = 0
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
    removed += 1


def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)


# ---- 3. Nodes -------------------------------------------------------------------
custom = add(unreal.MaterialExpressionCustom, -350, 0)
custom.set_editor_property('description', 'CarrierVision', QUIET)
custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3, QUIET)
custom.set_editor_property('code', HLSL_SOURCE, QUIET)
pins = []
for pin_name in CUSTOM_PINS:
    pin = unreal.CustomInput()
    pin.set_editor_property('input_name', pin_name)
    pins.append(pin)
custom.set_editor_property('inputs', pins, QUIET)

screen = add(unreal.MaterialExpressionScreenPosition, -800, -420)
view_size = add(unreal.MaterialExpressionViewSize, -800, -330)
time_node = add(unreal.MaterialExpressionTime, -800, -260)
time_node.set_editor_property('ignore_pause', False, QUIET)
scene = add(unreal.MaterialExpressionSceneTexture, -800, -180)
scene.set_editor_property('scene_texture_id', unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0, QUIET)

scalar_nodes = []
row = 0
for param_name, default in SCALARS:
    node = add(unreal.MaterialExpressionScalarParameter, -800, -60 + 70 * row)
    node.set_editor_property('parameter_name', param_name, QUIET)
    node.set_editor_property('default_value', default, QUIET)
    node.set_editor_property('group', PARAM_GROUP, QUIET)
    node.set_editor_property('sort_priority', row, QUIET)
    scalar_nodes.append(node)
    row += 1

tint = add(unreal.MaterialExpressionVectorParameter, -800, -60 + 70 * row)
tint.set_editor_property('parameter_name', TINT_NAME, QUIET)
tint.set_editor_property('default_value', TINT_DEFAULT, QUIET)
tint.set_editor_property('group', PARAM_GROUP, QUIET)
tint.set_editor_property('sort_priority', row, QUIET)

# ---- 4. Wires -------------------------------------------------------------------
# (source node, source output name, custom pin). '' = the node's first output.
links = [(screen, 'ViewportUV', 'UV'), (view_size, '', 'ViewSize'), (time_node, '', 'Time'),
         (scene, 'Color', 'SceneColorDummy')]
for index in range(len(SCALARS)):
    links.append((scalar_nodes[index], '', SCALARS[index][0]))
links.append((tint, 'RGB', TINT_NAME))

failed_links = []
for src, src_out, dst_pin in links:
    if not mel.connect_material_expressions(src, src_out, custom, dst_pin):
        failed_links.append(dst_pin)
emissive_ok = mel.connect_material_property(custom, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)

# ---- 5. Compile once, then save this package only ------------------------------
errors = mel.recompile_material(mat)
saved = eal.save_loaded_asset(mat, False)

# ---- 6. Readback (every claim above, read from the asset) ----------------------
connected = mel.get_inputs_for_material_expression(mat, custom)
pin_names = mel.get_material_expression_input_names(custom)
wiring = []
for index in range(len(pin_names)):
    src = connected[index] if index < len(connected) else None
    wiring.append(str(pin_names[index]) + '<-' + ('NONE' if src is None else str(src.get_class().get_name())))
scalar_back = []
for param_name, default in SCALARS:
    scalar_back.append(param_name + '=' + str(mel.get_material_default_scalar_parameter_value(mat, param_name)))
tint_back = mel.get_material_default_vector_parameter_value(mat, TINT_NAME)

print('CV asset=' + ASSET_PATH + ' created=' + str(created) + ' removed_nodes=' + str(removed))
print('CV domain=' + str(mat.get_editor_property('material_domain')) +
      ' blendable=' + str(mat.get_editor_property('blendable_location')))
print('CV nodes=' + str(mel.get_num_material_expressions(mat)) + ' (expect 14)')
print('CV custom output=' + str(custom.get_editor_property('output_type')) +
      ' code_chars=' + str(len(custom.get_editor_property('code'))) + '/' + str(len(HLSL_SOURCE)))
print('CV pins=' + ','.join(wiring))
print('CV failed_links=' + str(failed_links) + ' emissive_connect=' + str(emissive_ok) +
      ' emissive_is_custom=' + str(mel.get_material_property_input_node(mat, unreal.MaterialProperty.MP_EMISSIVE_COLOR) == custom))
print('CV scalars=' + ','.join(scalar_back))
print('CV tint=' + str(round(tint_back.r, 3)) + ',' + str(round(tint_back.g, 3)) + ',' +
      str(round(tint_back.b, 3)) + ',' + str(round(tint_back.a, 3)))
print('CV recompile_errors=' + str(len(errors)) + ' ' + ' | '.join([str(e) for e in errors]))
print('CV saved=' + str(saved))
