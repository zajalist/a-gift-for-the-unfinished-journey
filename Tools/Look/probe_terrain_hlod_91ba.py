"""Read-only Unreal editor probe for the reported terrain seam's merged HLOD.

Run under the existing editor gate with Hayba python_run. This does not select,
change, or save an actor. Keep its output alongside a matched Lit screenshot.
"""

import json
import unreal


ACTOR_PATH = (
    "/Game/level/Saskarta_WP.Saskarta_WP:PersistentLevel."
    "Saskarta_WP_HLODLayer_Merged_91ba2f6c7320dcbe"
)
LAYER_PATH = "/Game/level/Saskarta_WP_HLODLayer_Merged"


def path(value):
    return value.get_path_name() if value else None


world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
actor = next(
    (
        item
        for item in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        if item.get_path_name() == ACTOR_PATH
    ),
    None,
)
if not actor:
    raise RuntimeError("Exact merged HLOD actor is not resident: " + ACTOR_PATH)

origin, extent = actor.get_actor_bounds(False, False)
out = {
    "actor": path(actor),
    "label": actor.get_actor_label(),
    "bounds_origin": str(origin),
    "bounds_extent": str(extent),
    "components": [],
}
for component in actor.get_components_by_class(unreal.StaticMeshComponent):
    mesh = component.get_editor_property("static_mesh")
    row = {
        "path": path(component),
        "mesh": path(mesh),
        "material_count": component.get_num_materials(),
        "materials": [],
    }
    for index in range(component.get_num_materials()):
        row["materials"].append(
            {"slot": index, "effective": path(component.get_material(index))}
        )
    out["components"].append(row)

layer = unreal.load_asset(LAYER_PATH)
if not layer:
    raise RuntimeError("Merged HLOD layer asset missing: " + LAYER_PATH)
settings = layer.get_editor_property("hlod_builder_settings")
out["layer"] = {
    "asset": path(layer),
    "layer_type": str(layer.get_editor_property("layer_type")),
    "settings_class": settings.get_class().get_name() if settings else None,
    "settings": str(settings.get_editor_property("mesh_merge_settings")) if settings else None,
}

print("TERRAIN_HLOD_91BA_PROBE " + json.dumps(out, sort_keys=True))
