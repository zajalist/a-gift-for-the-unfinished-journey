"""Targeted read-only editor audit after removal of BOARD/learning captions.

Send this file's text as one Hayba python_run script (deadline_s <= 5). It does
not acquire a lease, load assets, compile Blueprints, or save packages. It reads
registry parent tags and the status of already loaded Blueprint objects only.
UNLOADED is explicitly inconclusive; a saved Blueprint is not certified by this
probe. Keep TARGETS small and explicit if investigating another reference hit.
"""
import json
import unreal

TARGETS = (
    "/Game/SaskartaGaea/GameFlow/BP_Saskarta_HUD",
    "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption",
    "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Subtitle",
    "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_BootLog",
    "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Radio",
    "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_EventCard",
    "/Game/SaskartaGaea/GameFlow/Debug/WBP_Saskarta_Debug",
    "/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier",
    "/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller",
)
REMOVED_CLASSES = ("SaskartaLearningCaptions", "SaskartaRouteLogWidget")
registry = unreal.AssetRegistryHelpers.get_asset_registry()
rows = []
for package in TARGETS:
    object_path = package + "." + package.rsplit("/", 1)[1]
    asset_data = registry.get_asset_by_object_path(unreal.SoftObjectPath(object_path), True)
    parent_tags = {
        key: str(unreal.AssetRegistryHelpers.get_tag_value(asset_data, key))
        for key in ("ParentClass", "NativeParentClass", "GeneratedClass")
    }
    blueprint = unreal.find_object(None, object_path)
    row = {
        "asset": package,
        "registry_asset_found": asset_data.is_valid(),
        "registry_tags": parent_tags,
        "removed_class_reference": any(
            name in value for name in REMOVED_CLASSES for value in parent_tags.values()
        ),
        "loaded": blueprint is not None,
        "compile_status": "UNLOADED; not checked",
    }
    if isinstance(blueprint, unreal.Blueprint):
        status = blueprint.get_editor_property("status")
        parent = blueprint.get_editor_property("parent_class")
        row["compile_status"] = str(status)
        row["parent_class"] = parent.get_path_name() if parent else None
        row["needs_attention"] = parent is None or status not in (
            unreal.BlueprintStatus.BS_UP_TO_DATE,
            unreal.BlueprintStatus.BS_UP_TO_DATE_WITH_WARNINGS,
        )
    elif blueprint is not None:
        row["compile_status"] = "Object exists but is not a Blueprint"
        row["needs_attention"] = True
    rows.append(row)
print(json.dumps({"read_only": True, "loaded_objects_only": True, "assets": rows}))
