# Build M_UI_CRTTerminal in the live editor (UE 5.8, Pallbearer / Saskarta).
#
# Sent as the script of Hayba python_run. It is NOT a standalone module: the
# caller first substitutes the full text of Shaders/CRTTerminalUI.hlsl for the
# placeholder inside HLSL_SOURCE below (see Tools/GameFlow/RETRO_BOOT.md,
# section Build the CRT material).
#
# python_run rules this file obeys: 5 s cooperative deadline; no try/with
# statements; no getattr; no file-open, string-substitute or level-switch
# calls. The policy scanner also reads string contents, which is why the HLSL
# must not spell any banned call name either.
#
# Result: /Game/SaskartaGaea/GameFlow/Materials/M_UI_CRTTerminal
#   User Interface domain, blend mode Additive,
#   Final Color <- Custom node (code = CRTTerminalUI.hlsl, output Float3).
#   Custom inputs, in this exact order:
#     UV            <- TextureCoordinate 0
#     Tex           <- TextureObjectParameter Texture (the RetainerBox writes
#                      its render target into the parameter of this name)
#     Time          <- Time
#     Fade          <- VertexColor.A (widget opacity)
#     PhosphorColor <- vector parameter .RGB (the ONE terminal colour)
#     Brightness ... RasterGlow <- scalar parameters
#
# Idempotent: a re-run deletes every expression and rebuilds the graph.
# Saves only this one package. Prints CRT lines for readback; the caller must
# still run Hayba material_compile for shader errors and instruction counts.

import unreal

HLSL_SOURCE = r'''__HLSL__'''

PACKAGE_DIR = '/Game/SaskartaGaea/GameFlow/Materials'
ASSET_NAME = 'M_UI_CRTTerminal'
ASSET_PATH = PACKAGE_DIR + '/' + ASSET_NAME
TEXTURE_PARAM = 'Texture'  # RetainerBox.TextureParameter default; keep them equal
DEFAULT_TEXTURE = '/Engine/EngineResources/Black.Black'

CUSTOM_PINS = ['UV', 'Tex', 'Time', 'Fade', 'PhosphorColor',
               'Brightness', 'GlowStrength', 'GlowRadius', 'ScanlineCount', 'ScanlineDepth',
               'Curvature', 'Vignette', 'FlickerDepth', 'RollSpeed', 'RollGain',
               'JitterChance', 'JitterPx', 'RasterGlow']

SCALARS = [('Brightness', 1.0), ('GlowStrength', 0.8), ('GlowRadius', 2.5),
           ('ScanlineCount', 540.0), ('ScanlineDepth', 0.35), ('Curvature', 0.045),
           ('Vignette', 0.3), ('FlickerDepth', 0.035), ('RollSpeed', 0.11),
           ('RollGain', 0.07), ('JitterChance', 0.12), ('JitterPx', 2.0),
           ('RasterGlow', 0.012)]
PHOSPHOR_NAME = 'PhosphorColor'
# #FFB000 amber in linear. Green: (0.033, 1.0, 0.033). See RETRO_BOOT.md.
PHOSPHOR_DEFAULT = unreal.LinearColor(1.0, 0.434, 0.0, 1.0)
PARAM_GROUP = 'CRTTerminal'

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER

# ---- 0. Validate before touching anything --------------------------------------
if len(HLSL_SOURCE) < 2000 or 'FTerm' not in HLSL_SOURCE or 'TexSampler' not in HLSL_SOURCE:
    raise RuntimeError('HLSL_SOURCE holds ' + str(len(HLSL_SOURCE)) +
                       ' chars: substitute Shaders/CRTTerminalUI.hlsl into it before sending')

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

mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_UI)
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_ADDITIVE)

# ---- 2. Clear the graph (re-run) ------------------------------------------------
removed = 0
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
    removed += 1


def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)


# ---- 3. Nodes -------------------------------------------------------------------
custom = add(unreal.MaterialExpressionCustom, -350, 0)
custom.set_editor_property('description', 'CRTTerminal', QUIET)
custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3, QUIET)
custom.set_editor_property('code', HLSL_SOURCE, QUIET)
pins = []
for pin_name in CUSTOM_PINS:
    pin = unreal.CustomInput()
    pin.set_editor_property('input_name', pin_name)
    pins.append(pin)
custom.set_editor_property('inputs', pins, QUIET)

texcoord = add(unreal.MaterialExpressionTextureCoordinate, -800, -480)
texcoord.set_editor_property('coordinate_index', 0, QUIET)
tex = add(unreal.MaterialExpressionTextureObjectParameter, -800, -400)
tex.set_editor_property('parameter_name', TEXTURE_PARAM, QUIET)
tex.set_editor_property('texture', unreal.load_asset(DEFAULT_TEXTURE), QUIET)
tex.set_editor_property('group', PARAM_GROUP, QUIET)
time_node = add(unreal.MaterialExpressionTime, -800, -300)
vcolor = add(unreal.MaterialExpressionVertexColor, -800, -230)

phosphor = add(unreal.MaterialExpressionVectorParameter, -800, -140)
phosphor.set_editor_property('parameter_name', PHOSPHOR_NAME, QUIET)
phosphor.set_editor_property('default_value', PHOSPHOR_DEFAULT, QUIET)
phosphor.set_editor_property('group', PARAM_GROUP, QUIET)
phosphor.set_editor_property('sort_priority', 0, QUIET)

scalar_nodes = []
row = 0
for param_name, default in SCALARS:
    node = add(unreal.MaterialExpressionScalarParameter, -800, -40 + 70 * row)
    node.set_editor_property('parameter_name', param_name, QUIET)
    node.set_editor_property('default_value', default, QUIET)
    node.set_editor_property('group', PARAM_GROUP, QUIET)
    node.set_editor_property('sort_priority', row + 1, QUIET)
    scalar_nodes.append(node)
    row += 1

# ---- 4. Wires -------------------------------------------------------------------
# (source node, source output name, custom pin). '' = the node's first output.
links = [(texcoord, '', 'UV'), (tex, '', 'Tex'), (time_node, '', 'Time'),
         (vcolor, 'A', 'Fade'), (phosphor, 'RGB', PHOSPHOR_NAME)]
for index in range(len(SCALARS)):
    links.append((scalar_nodes[index], '', SCALARS[index][0]))

failed_links = []
for src, src_out, dst_pin in links:
    if not mel.connect_material_expressions(src, src_out, custom, dst_pin):
        failed_links.append(dst_pin)
final_ok = mel.connect_material_property(custom, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)

# ---- 5. Compile once, then save this package only ------------------------------
errors = mel.recompile_material(mat)
saved = eal.save_loaded_asset(mat, False)

# ---- 6. Readback -----------------------------------------------------------------
connected = mel.get_inputs_for_material_expression(mat, custom)
pin_names = mel.get_material_expression_input_names(custom)
wiring = []
for index in range(len(pin_names)):
    src = connected[index] if index < len(connected) else None
    wiring.append(str(pin_names[index]) + '<-' + ('NONE' if src is None else str(src.get_class().get_name())))
scalar_back = []
for param_name, default in SCALARS:
    scalar_back.append(param_name + '=' + str(mel.get_material_default_scalar_parameter_value(mat, param_name)))
phos_back = mel.get_material_default_vector_parameter_value(mat, PHOSPHOR_NAME)

print('CRT asset=' + ASSET_PATH + ' created=' + str(created) + ' removed_nodes=' + str(removed))
print('CRT domain=' + str(mat.get_editor_property('material_domain')) +
      ' blend=' + str(mat.get_editor_property('blend_mode')))
print('CRT nodes=' + str(mel.get_num_material_expressions(mat)) + ' (expect ' + str(6 + len(SCALARS)) + ')')
print('CRT custom output=' + str(custom.get_editor_property('output_type')) +
      ' code_chars=' + str(len(custom.get_editor_property('code'))) + '/' + str(len(HLSL_SOURCE)))
print('CRT pins=' + ','.join(wiring))
print('CRT failed_links=' + str(failed_links) + ' final_connect=' + str(final_ok) +
      ' final_is_custom=' + str(mel.get_material_property_input_node(mat, unreal.MaterialProperty.MP_EMISSIVE_COLOR) == custom))
print('CRT texture_param=' + str(tex.get_editor_property('parameter_name')) +
      ' default=' + str(tex.get_editor_property('texture')))
print('CRT scalars=' + ','.join(scalar_back))
print('CRT phosphor=' + str(round(phos_back.r, 3)) + ',' + str(round(phos_back.g, 3)) + ',' +
      str(round(phos_back.b, 3)))
print('CRT recompile_errors=' + str(len(errors)) + ' ' + ' | '.join([str(e) for e in errors]))
print('CRT saved=' + str(saved))
