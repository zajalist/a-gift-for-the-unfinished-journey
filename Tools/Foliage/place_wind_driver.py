# Place the one BP_Saskarta_WindDriver in the open level (world sprint, Task V4).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/place_wind_driver.py
#
# The driver is a plain actor, not spatially loaded, so World Partition always
# has it loaded and its 0.1 s gust timer runs wherever the player is. It sits
# beside BP_Saskarta_TrampleWriter. Idempotent: an existing driver is kept.
# Prints the actor's external package, which is the ONLY package to save for
# it (Tools/Foliage/save_packages.py); the level itself is not touched.
import unreal

BP = '/Game/SaskartaGaea/Foliage/BP_Saskarta_WindDriver'
LABEL = 'BP_Saskarta_WindDriver'

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cls = unreal.EditorAssetLibrary.load_blueprint_class(BP)
found = [a for a in sub.get_all_level_actors() if a.get_class() == cls]
anchor = unreal.Vector(0.0, 0.0, 0.0)
for a in sub.get_all_level_actors():
    if a.get_actor_label() == 'BP_Saskarta_TrampleWriter':
        anchor = a.get_actor_location()
if len(found) == 0:
    actor = sub.spawn_actor_from_class(cls, anchor + unreal.Vector(0.0, 200.0, 0.0))
    actor.set_actor_label(LABEL)
    found = [actor]
actor = found[0]
actor.set_editor_property('is_spatially_loaded', False)
print('DRIVER count=' + str(len(found)) + ' loc=' + str(actor.get_actor_location()) + ' spatially_loaded=' +
      str(actor.get_editor_property('is_spatially_loaded')) + ' package=' + actor.get_package().get_name())
