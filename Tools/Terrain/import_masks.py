"""Import the baked road-influence and ecology masks as Unreal textures.

Run in the live editor's Python console via ``py.mjs`` (Hayba `python_run`).
Source PNGs come from ``Tools/Terrain/bake_masks.py`` (Task P1), at
``Saved/Masks/T_Saskarta_RoadInfluence.png`` and ``Saved/Masks/T_Saskarta_Ecology.png``
(both 4096x4096 RGBA16, gitignored, not committed).

Produces, under ``/Game/SaskartaGaea/Masks/``:
  - T_Saskarta_RoadInfluence (R core, G verge, B neglect, A surface type)
  - T_Saskarta_Ecology       (R moisture, G exposure, B zone/altitude, A macro noise)

Both imported with: sRGB off, BC7 compression (TC_BC7; ruling R28), clamp addressing (U and V),
full 4096 resolution, LODGroup = TEXTUREGROUP_Terrain_Weightmap.

Call ``import_one(src_png, dest_path)`` per texture, or ``import_all()`` for both.
Only these two assets are ever saved by this script.
"""
import unreal

DEST_DIR = "/Game/SaskartaGaea/Masks"
# Ruling R28: keep the full 4096 resolution (2 m per texel). A 2048 cap made the 3.5-5.5 m road core
# about one texel wide. 0 means no cap.
MAX_MIP_LEVELS_TEXTURE_SIZE = 0

MASKS = [
    ("Saved/Masks/T_Saskarta_RoadInfluence.png", "T_Saskarta_RoadInfluence"),
    ("Saved/Masks/T_Saskarta_Ecology.png", "T_Saskarta_Ecology"),
]


def _abs_src(rel_png):
    return unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir() + rel_png
    )


def import_one(rel_png, asset_name, dest_dir=DEST_DIR):
    task = unreal.AssetImportTask()
    task.filename = _abs_src(rel_png)
    task.destination_path = dest_dir
    task.destination_name = asset_name
    task.replace_existing = True
    task.automated = True
    task.save = False

    options = unreal.TextureFactory()
    task.options = options

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    dest = dest_dir + "/" + asset_name
    if not unreal.EditorAssetLibrary.does_asset_exist(dest):
        return None

    tex = unreal.EditorAssetLibrary.load_asset(dest)
    tex.set_editor_property("srgb", False)
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
    tex.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
    tex.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
    tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_TERRAIN_WEIGHTMAP)
    tex.set_editor_property("max_texture_size", MAX_MIP_LEVELS_TEXTURE_SIZE)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    return dest


def import_all():
    results = []
    for rel_png, asset_name in MASKS:
        results.append(import_one(rel_png, asset_name))
    return results


def verify():
    out = {}
    for _, asset_name in MASKS:
        dest = DEST_DIR + "/" + asset_name
        exists = unreal.EditorAssetLibrary.does_asset_exist(dest)
        row = {"exists": exists}
        if exists:
            tex = unreal.EditorAssetLibrary.load_asset(dest)
            row["srgb"] = tex.get_editor_property("srgb")
            row["compression_settings"] = str(tex.get_editor_property("compression_settings"))
            row["address_x"] = str(tex.get_editor_property("address_x"))
            row["address_y"] = str(tex.get_editor_property("address_y"))
            row["lod_group"] = str(tex.get_editor_property("lod_group"))
            row["max_texture_size"] = tex.get_editor_property("max_texture_size")
        out[asset_name] = row
    return out
