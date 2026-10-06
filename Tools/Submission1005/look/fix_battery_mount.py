"""Submission 2026-10-05: give the battery mount real surface detail.

Run in the editor:  py "D:/UnrealEngine/saskartarad/Tools/Submission1005/look/fix_battery_mount.py"
Creates /Game/Submission1005/Look/M_BatteryMount_Worn (world-aligned worn metal from the
MedievalVillage T_Metal set, so it ignores the mount's flat/stretched UVs) and assigns it to
every slot of SM_Biofuel01_mount and SM_BiofuelBroken01_mount. Original slot materials are
written to Saved/Backups/Submission1005/battery_mount_backup.json; run with 'revert' to restore.
"""
import json, os, sys
import unreal

ROOT = "D:/UnrealEngine/saskartarad"
BACKUP = ROOT + "/Saved/Backups/Submission1005/battery_mount_backup.json"
MESHES = ["/Game/SaskartaGaea/Characters/Carrier/Biofuel/Intact/SM_Biofuel01_mount",
          "/Game/SaskartaGaea/Characters/Carrier/Biofuel/Broken/SM_BiofuelBroken01_mount"]
FOLDER, NAME = "/Game/Submission1005/Look", "M_BatteryMount_Worn"
BC = "/Game/MedievalVillage/Textures/T_Metal_BC"
NRM = "/Game/MedievalVillage/Textures/T_Metal_N"
ORM = "/Game/MedievalVillage/Textures/T_Metal_ORM"
WAT = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedTexture"
WAN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedNormal"
TILE_CM = 60.0

MEL = unreal.MaterialEditingLibrary
P = unreal.MaterialProperty

def node(m, cls, x, y):
    return MEL.create_material_expression(m, cls, x, y)

def tex_obj(m, path, x, y):
    t = node(m, unreal.MaterialExpressionTextureObject, x, y)
    t.set_editor_property("texture", unreal.load_asset(path))
    return t

def fcall(m, path, x, y):
    f = node(m, unreal.MaterialExpressionMaterialFunctionCall, x, y)
    f.set_editor_property("material_function", unreal.load_asset(path))
    return f

def const(m, v, x, y):
    c = node(m, unreal.MaterialExpressionConstant, x, y); c.set_editor_property("r", v); return c

def build():
    full = FOLDER + "/" + NAME
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        unreal.EditorAssetLibrary.delete_asset(full)
    m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    size = node(m, unreal.MaterialExpressionConstant3Vector, -1100, 0)
    size.set_editor_property("constant", unreal.LinearColor(TILE_CM, TILE_CM, TILE_CM, 1))

    # base colour, world aligned
    wbc = fcall(m, WAT, -700, -300)
    MEL.connect_material_expressions(tex_obj(m, BC, -1000, -350), "", wbc, "TextureObject")
    MEL.connect_material_expressions(size, "", wbc, "TextureSize")
    # large-scale grime variation: second, much bigger projection of the same BC as a mask
    big = node(m, unreal.MaterialExpressionConstant3Vector, -1100, -550)
    big.set_editor_property("constant", unreal.LinearColor(260, 260, 260, 1))
    wbig = fcall(m, WAT, -700, -600)
    MEL.connect_material_expressions(tex_obj(m, BC, -1000, -650), "", wbig, "TextureObject")
    MEL.connect_material_expressions(big, "", wbig, "TextureSize")
    desat = node(m, unreal.MaterialExpressionDesaturation, -450, -600)
    MEL.connect_material_expressions(wbig, "XYZ Texture", desat, "")
    grime = node(m, unreal.MaterialExpressionLinearInterpolate, -250, -450)
    tint_dark = node(m, unreal.MaterialExpressionConstant3Vector, -450, -450)
    tint_dark.set_editor_property("constant", unreal.LinearColor(0.32, 0.28, 0.24, 1))   # oily umber
    tint_lite = node(m, unreal.MaterialExpressionConstant3Vector, -450, -380)
    tint_lite.set_editor_property("constant", unreal.LinearColor(0.75, 0.70, 0.64, 1))
    MEL.connect_material_expressions(tint_dark, "", grime, "A")
    MEL.connect_material_expressions(tint_lite, "", grime, "B")
    MEL.connect_material_expressions(desat, "", grime, "Alpha")
    base = node(m, unreal.MaterialExpressionMultiply, -50, -300)
    MEL.connect_material_expressions(wbc, "XYZ Texture", base, "A")
    MEL.connect_material_expressions(grime, "", base, "B")
    MEL.connect_material_property(base, "", P.MP_BASE_COLOR)

    # ORM, world aligned
    worm = fcall(m, WAT, -700, 50)
    MEL.connect_material_expressions(tex_obj(m, ORM, -1000, 50), "", worm, "TextureObject")
    MEL.connect_material_expressions(size, "", worm, "TextureSize")
    mask_r = node(m, unreal.MaterialExpressionComponentMask, -450, 0)
    mask_r.set_editor_property("r", True); mask_r.set_editor_property("g", False); mask_r.set_editor_property("b", False)
    mask_g = node(m, unreal.MaterialExpressionComponentMask, -450, 80)
    mask_g.set_editor_property("r", False); mask_g.set_editor_property("g", True); mask_g.set_editor_property("b", False)
    mask_b = node(m, unreal.MaterialExpressionComponentMask, -450, 160)
    mask_b.set_editor_property("r", False); mask_b.set_editor_property("g", False); mask_b.set_editor_property("b", True)
    for k in (mask_r, mask_g, mask_b):
        MEL.connect_material_expressions(worm, "XYZ Texture", k, "")
    rough = node(m, unreal.MaterialExpressionMultiply, -250, 80)
    MEL.connect_material_expressions(mask_g, "", rough, "A")
    MEL.connect_material_expressions(const(m, 1.15, -450, 120), "", rough, "B")
    MEL.connect_material_property(mask_r, "", P.MP_AMBIENT_OCCLUSION)
    MEL.connect_material_property(rough, "", P.MP_ROUGHNESS)
    metal = node(m, unreal.MaterialExpressionMultiply, -250, 160)
    MEL.connect_material_expressions(mask_b, "", metal, "A")
    MEL.connect_material_expressions(const(m, 0.85, -450, 220), "", metal, "B")
    MEL.connect_material_property(metal, "", P.MP_METALLIC)

    # normal, world aligned (tangent-space output)
    wn = fcall(m, WAN, -700, 350)
    MEL.connect_material_expressions(tex_obj(m, NRM, -1000, 350), "", wn, "TextureObject")
    MEL.connect_material_expressions(size, "", wn, "TextureSize")
    MEL.connect_material_property(wn, "XYZ Texture", P.MP_NORMAL)

    MEL.recompile_material(m)
    unreal.EditorAssetLibrary.save_loaded_asset(m)
    return m

def apply():
    m = build()
    backup = json.load(open(BACKUP)) if os.path.exists(BACKUP) else {}
    for path in MESHES:
        sm = unreal.load_asset(path)
        if sm is None:
            print("missing", path); continue
        mats = sm.get_editor_property("static_materials")
        if path not in backup:
            backup[path] = [s.get_editor_property("material_interface").get_path_name() if s.get_editor_property("material_interface") else None for s in mats]
        for i in range(len(mats)):
            sm.set_material(i, m)
        unreal.EditorAssetLibrary.save_loaded_asset(sm)
        print("assigned", path, "slots", len(mats))
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    json.dump(backup, open(BACKUP, "w"), indent=1)
    print("BATTERY_MOUNT_OK")

def revert():
    backup = json.load(open(BACKUP))
    for path, mats in backup.items():
        sm = unreal.load_asset(path)
        for i, p in enumerate(mats):
            if p: sm.set_material(i, unreal.load_asset(p))
        unreal.EditorAssetLibrary.save_loaded_asset(sm)
    print("BATTERY_MOUNT_REVERTED")

if __name__ == "__main__":
    revert() if "revert" in sys.argv[1:] else apply()
