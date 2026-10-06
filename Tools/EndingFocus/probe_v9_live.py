import json
import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
matches = [actor for actor in sub.get_all_level_actors()
           if 'Samyor' in actor.get_actor_label() or 'CIN19' in actor.get_actor_label()]
print('CIN19_V9_ACTORS ' + json.dumps([
    {'label': actor.get_actor_label(), 'class': actor.get_class().get_name(),
     'location': str(actor.get_actor_location())} for actor in matches], separators=(',', ':')))
