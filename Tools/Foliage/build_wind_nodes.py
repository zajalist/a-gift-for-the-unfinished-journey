# Add the SaskartaWind Custom node to one foliage master (world sprint, Task V4).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/build_wind_nodes.py \
#        "MAT='/Game/SaskartaGaea/Materials/M_Saskarta_PlantFoliage'" CODE=@Shaders/FoliageWind.hlsl
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/build_wind_nodes.py \
#        "MAT='/Game/Fab/Materials/Standard/M_MS_Foliage'" CODE=@Shaders/FoliageWind.hlsl
#
# The runner turns CODE=@file into a list of the HLSL body lines (python_run
# may not read files itself). Then recompile with Tools/Foliage/recompile.py.
#
# What it builds, beside the existing trample WPO (which it never removes):
#
#   wpo_new = wpo_old + SaskartaWind(ObjectPositionWS, LocalPosition, Height01,
#                                    PerInstanceRandom, Time,
#                                    Mask_RGB(MPC_Saskarta_Wind.WindDirection),
#                                    MPC_Saskarta_Wind.WindStrength * SaskartaWindAmount,
#                                    MPC_Saskarta_Wind.GustPhase)
#
#   M_Saskarta_PlantFoliage (material attributes): wpo_old is what feeds
#     Make Material Attributes.WorldPositionOffset (Break.WPO + trample), and
#     Height01 is the trample's own saturate(LocalPos.z / TramplePlantHeight),
#     so wind and trample share one per-instance height.
#   M_MS_Foliage (plain outputs): wpo_old is the World Position Offset output
#     (Fab wind + trample); Height01 = saturate(LocalPos.z / SaskartaWindHeight).
#
# WIND_MPC is the collection the three wind inputs read. M_MS_Foliage must pass
# WIND_MPC='/Game/SaskartaGaea/Materials/MPC_Saskarta_Player' (the mirror, see
# Tools/Foliage/make_wind_mpc.py): a material may reference only 2 collections
# and it already uses QMPC_GlobalFoliageActor and MPC_Saskarta_Player.
#
# SaskartaWindAmount (default 1) lets a material instance turn the wind down
# or off. Idempotent: a master that already has the node only gets its code
# refreshed. It never saves: save with Tools/Foliage/save_packages.py.
import unreal

MAT = ''
CODE = []
WIND_MPC = '/Game/SaskartaGaea/Foliage/MPC_Saskarta_Wind'
X0 = -2400
Y0 = 2000

mel = unreal.MaterialEditingLibrary
MPC = unreal.load_asset(WIND_MPC)
PINS = ['WorldPos', 'LocalPos', 'Height01', 'PerInstanceRandom', 'Time', 'WindDir', 'Strength', 'Gust']

if MAT == '' or len(CODE) == 0:
    raise RuntimeError('run through Tools/Foliage/run_foliage.mjs with MAT and CODE=@Shaders/FoliageWind.hlsl')
m = unreal.load_asset(MAT)
body = chr(10).join(['// SaskartaWind: Shaders/FoliageWind.hlsl, built by Tools/Foliage/build_wind_nodes.py'] + CODE)


def node(cls, dx, dy):
    return mel.create_material_expression(m, cls, X0 + dx, Y0 + dy)


def input_of(expr, name):
    names = [str(n) for n in mel.get_material_expression_input_names(expr)]
    return mel.get_inputs_for_material_expression(m, expr)[names.index(name)]


def is_wind(expr):
    return isinstance(expr, unreal.MaterialExpressionCustom) and expr.get_editor_property('description') == 'SaskartaWind'


attrs = m.get_editor_property('use_material_attributes')
if attrs:
    make = mel.get_material_property_input_node(m, unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    old = input_of(make, 'WorldPositionOffset')
else:
    make = None
    old = mel.get_material_property_input_node(m, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
if old is None:
    raise RuntimeError('no WPO chain found in ' + MAT)

existing = None
if isinstance(old, unreal.MaterialExpressionAdd) and is_wind(input_of(old, 'B')):
    existing = input_of(old, 'B')

if existing is not None:
    existing.set_editor_property('code', body)
    names = [str(n) for n in mel.get_material_expression_input_names(existing)]
    feeds = mel.get_inputs_for_material_expression(m, existing)
    retarget = [mel.get_inputs_for_material_expression(m, feeds[names.index('WindDir')])[0],
                input_of(feeds[names.index('Strength')], 'A'), feeds[names.index('Gust')]]
    for c in retarget:
        c.set_editor_property('collection', MPC)
    print('WIND refreshed code in ' + MAT + ', collections -> ' + WIND_MPC + ': ' + str([c.get_editor_property('parameter_name') for c in retarget]))
else:
    custom = node(unreal.MaterialExpressionCustom, 900, 0)
    custom.set_editor_property('description', 'SaskartaWind')
    custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    custom.set_editor_property('code', body)
    ins = []
    for name in PINS:
        ci = unreal.CustomInput()
        ci.set_editor_property('input_name', name)
        ins.append(ci)
    custom.set_editor_property('inputs', ins)

    obj = node(unreal.MaterialExpressionObjectPositionWS, 0, 0)
    local = node(unreal.MaterialExpressionLocalPosition, 0, 80)
    rnd = node(unreal.MaterialExpressionPerInstanceRandom, 0, 320)
    tm = node(unreal.MaterialExpressionTime, 0, 400)
    wdir = node(unreal.MaterialExpressionCollectionParameter, 0, 480)
    wdir.set_editor_property('collection', MPC)
    wdir.set_editor_property('parameter_name', 'WindDirection')
    wmask = node(unreal.MaterialExpressionComponentMask, 300, 480)
    wmask.set_editor_property('r', True)
    wmask.set_editor_property('g', True)
    wmask.set_editor_property('b', True)
    wmask.set_editor_property('a', False)
    mel.connect_material_expressions(wdir, '', wmask, '')
    wstr = node(unreal.MaterialExpressionCollectionParameter, 0, 560)
    wstr.set_editor_property('collection', MPC)
    wstr.set_editor_property('parameter_name', 'WindStrength')
    amount = node(unreal.MaterialExpressionScalarParameter, 0, 640)
    amount.set_editor_property('parameter_name', 'SaskartaWindAmount')
    amount.set_editor_property('default_value', 1.0)
    amount.set_editor_property('group', 'Saskarta Wind')
    strength = node(unreal.MaterialExpressionMultiply, 300, 580)
    mel.connect_material_expressions(wstr, '', strength, 'A')
    mel.connect_material_expressions(amount, '', strength, 'B')
    gust = node(unreal.MaterialExpressionCollectionParameter, 0, 720)
    gust.set_editor_property('collection', MPC)
    gust.set_editor_property('parameter_name', 'GustPhase')

    if attrs:
        # The trample's Height01: Multiply_2.B of the trample chain is
        # saturate(LocalPos.z / TramplePlantHeight). Find it by walking from
        # the trample clamp: Add_1.B -> Clamp -> Add -> Multiply(bend) -> ...
        height = None
        stack = [input_of(old, 'B')]
        seen = []
        while len(stack) > 0 and height is None:
            e = stack.pop()
            if e is None or e.get_name() in seen:
                continue
            seen.append(e.get_name())
            if isinstance(e, unreal.MaterialExpressionSaturate):
                d = mel.get_inputs_for_material_expression(m, e)[0]
                if isinstance(d, unreal.MaterialExpressionDivide) and isinstance(input_of(d, 'A'), unreal.MaterialExpressionComponentMask):
                    height = e
            for i in mel.get_inputs_for_material_expression(m, e):
                stack.append(i)
        if height is None:
            raise RuntimeError('trample Height01 (saturate(LocalPos.z / TramplePlantHeight)) not found')
    else:
        lz = node(unreal.MaterialExpressionComponentMask, 300, 160)
        lz.set_editor_property('r', False)
        lz.set_editor_property('g', False)
        lz.set_editor_property('b', True)
        lz.set_editor_property('a', False)
        mel.connect_material_expressions(local, '', lz, '')
        hparam = node(unreal.MaterialExpressionScalarParameter, 300, 240)
        hparam.set_editor_property('parameter_name', 'SaskartaWindHeight')
        hparam.set_editor_property('default_value', 120.0)
        hparam.set_editor_property('group', 'Saskarta Wind')
        hdiv = node(unreal.MaterialExpressionDivide, 500, 180)
        mel.connect_material_expressions(lz, '', hdiv, 'A')
        mel.connect_material_expressions(hparam, '', hdiv, 'B')
        height = node(unreal.MaterialExpressionSaturate, 650, 180)
        mel.connect_material_expressions(hdiv, '', height, '')

    wires = [(obj, 'WorldPos'), (local, 'LocalPos'), (height, 'Height01'), (rnd, 'PerInstanceRandom'),
             (tm, 'Time'), (wmask, 'WindDir'), (strength, 'Strength'), (gust, 'Gust')]
    ok = [mel.connect_material_expressions(src, '', custom, pin) for (src, pin) in wires]

    total = node(unreal.MaterialExpressionAdd, 1200, -100)
    ok.append(mel.connect_material_expressions(old, '', total, 'A'))
    ok.append(mel.connect_material_expressions(custom, '', total, 'B'))
    if attrs:
        ok.append(mel.connect_material_expressions(total, '', make, 'WorldPositionOffset'))
    else:
        ok.append(mel.connect_material_property(total, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET))
        m.set_editor_property('used_with_instanced_static_meshes', True)
    print('WIND added to ' + MAT + ' connections_ok=' + str(ok.count(True)) + '/' + str(len(ok)))
