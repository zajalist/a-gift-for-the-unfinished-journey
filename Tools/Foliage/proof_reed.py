# Trample and wind proof rig for Task V4 (controller ruling R9).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/proof_reed.py "ACTION='spawn'"
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/proof_reed.py "ACTION='set'" PLAYER=100 WIND=0.0
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/proof_reed.py "ACTION='cleanup'"
#
# spawn:   a transient SkeletalMeshActor V4_PROOF_REED with the Megaplant reed
#          (material M_Saskarta_PlantFoliage) at LOC, high above the map so the
#          base-colour capture sees only the reed. Its component gets the
#          foliage WPO disable distance (6000 cm), to show it does not cut the
#          trample next to the camera.
# set:     writes the editor world's instance values (the assets are not
#          touched): MPC_Saskarta_Player.PlayerPosition = LOC + (PLAYER, 0, 0) cm,
#          and WindStrength = WIND in both MPC_Saskarta_Wind and its mirror in
#          MPC_Saskarta_Player.
# cleanup: destroys the reed and puts the instance values back to the assets'
#          defaults.
# Capture with Tools/Foliage/snap.sh between the calls. Nothing is saved.
import unreal

ACTION = ''
PLAYER = 100.0
WIND = 0.0
LOC = [389000.0, 408000.0, 60000.0]
MESH = '/Game/Megaplant_Library/Plant_Dry_Common_Reeds/Plant_Dry_Common_Reeds_01/Plant_Dry_Common_Reed_A'
LABEL = 'V4_PROOF_REED'

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
kml = unreal.MaterialLibrary
player = unreal.load_asset('/Game/SaskartaGaea/Materials/MPC_Saskarta_Player')
wind = unreal.load_asset('/Game/SaskartaGaea/Foliage/MPC_Saskarta_Wind')
old = [a for a in sub.get_all_level_actors() if a.get_actor_label().startswith('V4_PROOF')]


def default_of(mpc, name):
    for p in list(mpc.get_editor_property('scalar_parameters')) + list(mpc.get_editor_property('vector_parameters')):
        if str(p.get_editor_property('parameter_name')) == name:
            return p.get_editor_property('default_value')
    raise RuntimeError('no parameter ' + name)


if ACTION == 'spawn':
    for a in old:
        sub.destroy_actor(a)
    a = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(LOC[0], LOC[1], LOC[2]))
    a.set_actor_label(LABEL)
    c = a.skeletal_mesh_component
    c.set_skeletal_mesh_asset(unreal.load_asset(MESH))
    c.set_editor_property('world_position_offset_disable_distance', 6000)
    print('PROOF spawned ' + LABEL + ' mat=' + c.get_material(0).get_path_name() + ' wpo_disable=' +
          str(c.get_editor_property('world_position_offset_disable_distance')))
elif ACTION == 'set':
    pos = unreal.LinearColor(LOC[0] + PLAYER, LOC[1], LOC[2], 0.0)
    kml.set_vector_parameter_value(world, player, 'PlayerPosition', pos)
    kml.set_scalar_parameter_value(world, wind, 'WindStrength', WIND)
    kml.set_scalar_parameter_value(world, player, 'WindStrength', WIND)
    print('PROOF player=' + str(kml.get_vector_parameter_value(world, player, 'PlayerPosition')) +
          ' wind=' + str(kml.get_scalar_parameter_value(world, wind, 'WindStrength')) +
          '/' + str(kml.get_scalar_parameter_value(world, player, 'WindStrength')))
elif ACTION == 'cleanup':
    for a in old:
        sub.destroy_actor(a)
    kml.set_vector_parameter_value(world, player, 'PlayerPosition', default_of(player, 'PlayerPosition'))
    kml.set_scalar_parameter_value(world, wind, 'WindStrength', default_of(wind, 'WindStrength'))
    kml.set_scalar_parameter_value(world, player, 'WindStrength', default_of(player, 'WindStrength'))
    print('PROOF cleaned ' + str(len(old)) + ' actor(s), instance values reset to defaults')
else:
    raise RuntimeError('ACTION must be spawn, set or cleanup')
