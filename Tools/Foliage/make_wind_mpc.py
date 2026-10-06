# Create /Game/SaskartaGaea/Foliage/MPC_Saskarta_Wind (world sprint, Task V4).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/make_wind_mpc.py
#
# Parameters (read by the SaskartaWind Custom node in both foliage masters):
#   WindDirection  vector  world XY direction the wind blows toward (Z ignored)
#   WindStrength   scalar  0..1, global; each material instance scales it with
#                          its own SaskartaWindAmount
#   GustPhase      scalar  advanced by BP_Saskarta_WindDriver every 0.1 s
#
# The same three parameters are mirrored into MPC_Saskarta_Player, with the
# same defaults: a material may reference only 2 collections, and M_MS_Foliage
# already uses QMPC_GlobalFoliageActor (Fab health, colour and wind functions)
# plus MPC_Saskarta_Player (trample), so its SaskartaWind node reads the mirror.
# BP_Saskarta_WindDriver copies Wind -> Player every 0.1 s, so MPC_Saskarta_Wind
# stays the one place to set wind.
#
# Idempotent: an existing collection keeps its parameter Ids (materials bind to
# them) and only gains missing parameters. A new CollectionScalarParameter gets
# a fresh Id from its C++ constructor, so no Guid is ever built by hand (that
# crashes the editor, see the hayba-python-quirks note). It never saves: save
# with Tools/Foliage/save_packages.py.
import unreal

PATH = '/Game/SaskartaGaea/Foliage/MPC_Saskarta_Wind'
PLAYER = '/Game/SaskartaGaea/Materials/MPC_Saskarta_Player'
DIRECTION = unreal.LinearColor(0.94, 0.34, 0.0, 0.0)
STRENGTH = 0.5

eal = unreal.EditorAssetLibrary
if eal.does_asset_exist(PATH):
    wind = unreal.load_asset(PATH)
else:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    wind = tools.create_asset('MPC_Saskarta_Wind', '/Game/SaskartaGaea/Foliage', unreal.MaterialParameterCollection,
                              unreal.MaterialParameterCollectionFactoryNew())


def add_wind_parameters(mpc):
    scalars = list(mpc.get_editor_property('scalar_parameters'))
    vectors = list(mpc.get_editor_property('vector_parameters'))
    have = [str(p.get_editor_property('parameter_name')) for p in scalars + vectors]
    added = 0
    for name, value in [('WindStrength', STRENGTH), ('GustPhase', 0.0)]:
        if name not in have:
            p = unreal.CollectionScalarParameter()
            p.set_editor_property('parameter_name', name)
            p.set_editor_property('default_value', value)
            scalars.append(p)
            added += 1
    if 'WindDirection' not in have:
        p = unreal.CollectionVectorParameter()
        p.set_editor_property('parameter_name', 'WindDirection')
        p.set_editor_property('default_value', DIRECTION)
        vectors.append(p)
        added += 1
    if added > 0:
        mpc.set_editor_property('scalar_parameters', scalars)
        mpc.set_editor_property('vector_parameters', vectors)
    for p in list(mpc.get_editor_property('scalar_parameters')) + list(mpc.get_editor_property('vector_parameters')):
        print('MPC ' + mpc.get_name() + ' ' + p.export_text())


add_wind_parameters(wind)
add_wind_parameters(unreal.load_asset(PLAYER))
