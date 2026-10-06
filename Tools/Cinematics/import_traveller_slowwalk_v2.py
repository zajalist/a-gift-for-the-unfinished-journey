"""Stage the supplied SlowWalk V2 FBX against the existing Traveller skeleton.

Run with UnrealEditor-Cmd -ExecutePythonScript. This creates only a review
AnimSequence; the referenced production sequence is changed in a later step.
"""

from pathlib import Path
import hashlib
import json

import unreal


ROOT = Path(r"D:\UnrealEngine\saskartarad")
SOURCE = ROOT / "SourceArt/Characters/Traveller/Updates/traveller01_SlowWalk_V2.fbx"
EXPECTED_SHA256 = "7d54f209b7f04bb86429b4351aa9971f155b3419aca8ecee62e2d498127bd02e"
SKELETON = "/Game/SaskartaGaea/Characters/Traveller/SKEL_Traveller"
PRODUCTION = "/Game/SaskartaGaea/Characters/Traveller/Anims/A_Traveller_SlowWalk"
DEST = "/Game/SaskartaGaea/Characters/Traveller/Anims/Review"
NAME = "A_Traveller_SlowWalk_V2_Review"
REVIEW = f"{DEST}/{NAME}"
REPORT = ROOT / "Saved/Verification/traveller_slowwalk_v2_stage.json"


def run():
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world():
        raise RuntimeError("Stop PIE before animation import")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("Walk FBX hash differs")
    skeleton = unreal.load_asset(SKELETON)
    old = unreal.load_asset(PRODUCTION)
    if not isinstance(skeleton, unreal.Skeleton) or not isinstance(old, unreal.AnimSequence):
        raise RuntimeError("Existing Traveller skeleton or walk sequence missing")
    if old.get_editor_property("skeleton").get_path_name().split(".")[0] != SKELETON:
        raise RuntimeError("Production walk uses a different skeleton")
    if unreal.EditorAssetLibrary.does_asset_exist(REVIEW):
        raise RuntimeError("Review animation already exists; inspect it before rerunning")

    opts = unreal.FbxImportUI()
    for key, value in {
        "import_mesh": False,
        "import_animations": True,
        "import_as_skeletal": True,
        "import_materials": False,
        "import_textures": False,
        "automated_import_should_detect_type": False,
        "mesh_type_to_import": unreal.FBXImportType.FBXIT_ANIMATION,
        "skeleton": skeleton,
    }.items():
        opts.set_editor_property(key, value)
    task = unreal.AssetImportTask()
    for key, value in {
        "filename": str(SOURCE),
        "destination_path": DEST,
        "destination_name": NAME,
        "automated": True,
        "replace_existing": False,
        "save": False,
        "async_": False,
        "options": opts,
        "factory": unreal.FbxFactory(),
    }.items():
        task.set_editor_property(key, value)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    objects = list(task.get_objects())
    if len(objects) != 1 or not isinstance(objects[0], unreal.AnimSequence):
        raise RuntimeError(f"Expected one review AnimSequence, got {[o.get_path_name() for o in objects]}")
    anim = objects[0]
    if anim.get_path_name().split(".")[0] != REVIEW:
        raise RuntimeError(f"Unexpected review path {anim.get_path_name()}")
    if anim.get_editor_property("skeleton") != skeleton:
        raise RuntimeError("Review animation skeleton differs")
    if abs(anim.get_play_length() - 4.0) > 0.04:
        raise RuntimeError(f"Review animation length differs: {anim.get_play_length()}")
    if not unreal.EditorAssetLibrary.save_loaded_asset(anim, only_if_is_dirty=False):
        raise RuntimeError("Review animation save failed")
    result = {
        "status": "STAGED",
        "source": str(SOURCE),
        "source_sha256": EXPECTED_SHA256,
        "review": anim.get_path_name(),
        "skeleton": skeleton.get_path_name(),
        "duration_seconds": anim.get_play_length(),
        "production_duration_seconds": old.get_play_length(),
        "production_rate_scale": old.get_editor_property("rate_scale"),
        "review_rate_scale": anim.get_editor_property("rate_scale"),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("TRAVELLER_SLOWWALK_V2_STAGE", json.dumps(result))
    return result


if __name__ == "__main__":
    run()
