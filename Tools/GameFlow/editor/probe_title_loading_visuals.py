"""Read exact title camera and loading carrier material before the visual repair."""

import json
import unreal

actors = [
    actor for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    if actor.get_actor_label() == "TitleCam"
]
assert len(actors) == 1, "Expected one loaded placed TitleCam"
actor = actors[0]
camera = actor.get_component_by_class(unreal.CineCameraComponent)
assert camera, "TitleCam has no CineCameraComponent"
material = unreal.load_asset("/Game/SaskartaGaea/GameFlow/UI/Materials/M_LoadingCarrierSplat")
assert material, "Loading carrier material missing"
methods = [member for member in dir(unreal.MaterialEditingLibrary) if "material" in member.lower() and "expression" in member.lower()]
expressions = []
for expression in unreal.MaterialEditingLibrary.get_material_expressions(material):
    row = {"class": expression.get_class().get_name(), "path": expression.get_path_name()}
    if isinstance(expression, unreal.MaterialExpressionTextureSample):
        row["texture"] = expression.get_editor_property("texture").get_path_name()
    if isinstance(expression, unreal.MaterialExpressionConstant):
        row["constant"] = expression.get_editor_property("r")
    expressions.append(row)
out = {
    "camera_actor": actor.get_path_name(),
    "camera_package": actor.get_package().get_name(),
    "constrain_aspect_ratio": camera.get_editor_property("constrain_aspect_ratio"),
    "filmback": str(camera.get_editor_property("filmback")),
    "material": material.get_path_name(),
    "material_domain": str(material.get_editor_property("material_domain")),
    "blend_mode": str(material.get_editor_property("blend_mode")),
    "material_methods": methods,
    "expressions": expressions,
}
print("TITLE_LOADING_VISUAL_PROBE " + json.dumps(out, sort_keys=True))
