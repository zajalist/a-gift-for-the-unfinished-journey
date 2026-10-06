"""Guarded Hayba python_run body: hide both legacy summit sky columns.

Pass this file's source plus ``run(False)`` for inspection, then ``run(True)``
after the exact Blueprint templates and loaded instances have been reviewed.
The method preserves the actors, audio hooks, crown, and interactions.
"""
import json
import unreal

TARGETS = (
    ('/Game/SaskartaGaea/Story/BP_Saskarta_HighVoice', 'Beam'),
    ('/Game/SaskartaGaea/Story/HighVoice/BP_Saskarta_HighVoice', 'Column'),
)


def run(apply=False):
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    assert editor.get_game_world() is None, 'Stop PIE before changing station assets'
    assert editor.get_editor_world().get_name() == 'Saskarta_WP'
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    eal = unreal.EditorAssetLibrary
    blueprints = []
    actors = []
    to_save = []
    for path, name in TARGETS:
        bp = eal.load_asset(path)
        assert isinstance(bp, unreal.Blueprint), 'Missing expected Blueprint: ' + path
        rows = []
        seen_components = set()
        for handle in sub.k2_gather_subobject_data_for_blueprint(bp):
            data = lib.get_data(handle)
            if str(lib.get_variable_name(data)) != name:
                continue
            comp = lib.get_object(data)
            assert isinstance(comp, unreal.StaticMeshComponent)
            component_path = comp.get_path_name()
            if component_path in seen_components:
                continue
            seen_components.add(component_path)
            before = dict(visible=bool(comp.get_editor_property('visible')),
                          hidden_in_game=bool(comp.get_editor_property('hidden_in_game')),
                          collision=str(comp.get_collision_enabled()))
            if apply:
                comp.set_editor_property('visible', False)
                comp.set_editor_property('hidden_in_game', True)
                comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            rows.append(before)
        assert len(rows) == 1, 'Expected one exact ' + name + ' component on ' + path
        blueprints.append(dict(path=path, component=name, before=rows[0]))
        if apply:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
            assert eal.save_loaded_asset(bp, False), 'Blueprint save failed: ' + path
    labels = {'HighVoice', 'HighVoice_Ending'}
    for actor in eas.get_all_level_actors():
        label = actor.get_actor_label()
        if label not in labels:
            continue
        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
            if comp.get_name() not in ('Beam', 'Column'):
                continue
            before = dict(visible=bool(comp.get_editor_property('visible')),
                          hidden_in_game=bool(comp.get_editor_property('hidden_in_game')),
                          collision=str(comp.get_collision_enabled()))
            if apply:
                comp.set_visibility(False, True)
                comp.set_editor_property('hidden_in_game', True)
                comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                to_save.append(actor.get_package())
            actors.append(dict(label=label, path=actor.get_path_name(),
                               component=comp.get_name(), before=before))
    if apply and to_save:
        assert unreal.EditorLoadingAndSavingUtils.save_packages(to_save, True), 'Actor save failed'
    print('HIGHVOICE_COLUMNS ' + json.dumps(dict(apply=apply, blueprints=blueprints,
                                                  actors=actors, saved=apply), separators=(',', ':')))
