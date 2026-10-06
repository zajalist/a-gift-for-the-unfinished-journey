"""Import the new-style UI assets (Task TITLE, addenda 2-4): the Aref Ruqaa lettering, the user's
Saskartan title calligraphy and the loading screen's ember glow.

    python Tools/GameFlow/import_ui_assets.py fonts      # FF_ArefRuqaa_{Regular,Bold} + composite F_ArefRuqaa
    python Tools/GameFlow/import_ui_assets.py textures   # T_Saskarta_TitleName_Ivory, T_UI_EmberGlow (--replace reimports)
    python Tools/GameFlow/import_ui_assets.py read       # print what exists (read only)

Sources (committed): SourceArt/Fonts/ArefRuqaa-{Regular,Bold}.ttf (OFL), SourceArt/UI/*.png.
Destinations: /Game/SaskartaGaea/GameFlow/UI/Fonts and /Game/SaskartaGaea/GameFlow/UI/Textures.

- The composite font F_ArefRuqaa has one default typeface with two entries, "Regular" and
  "Bold", so a TextBlock picks the weight by typeface name (ui_set_text_style typeface "Bold").
  FCompositeFont's members are not Python-visible, so the typeface list is written as text
  (import_text on the CompositeFont struct).
- Textures: TextureGroup UI, no mips, sRGB, UserInterface2D compression (keeps the alpha clean),
  never streamed. T_UI_EmberGlow is a half radial glow (brightest at the bottom edge's centre),
  generated with numpy; it sits on the loading screen's bottom edge.

Runs through Hayba python_run (5 s per call, banned words checked); saves only the assets it
creates. Hold the editor gate (Tools/GameFlow/editor_gate.py) around every run.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))

from apply_look import python_run, check_banned  # noqa: E402

FONT_DIR = "/Game/SaskartaGaea/GameFlow/UI/Fonts"
TEX_DIR = "/Game/SaskartaGaea/GameFlow/UI/Textures"
FACES = [("Regular", ROOT / "SourceArt/Fonts/ArefRuqaa-Regular.ttf", "FF_ArefRuqaa_Regular"),
         ("Bold", ROOT / "SourceArt/Fonts/ArefRuqaa-Bold.ttf", "FF_ArefRuqaa_Bold")]
FONT = "F_ArefRuqaa"
TEXTURES = [(ROOT / "SourceArt/UI/T_Saskarta_TitleName_Ivory.png", "T_Saskarta_TitleName_Ivory"),
            (ROOT / "SourceArt/UI/T_UI_EmberGlow.png", "T_UI_EmberGlow")]
# The direction-A redo (addendum 2; Tools/GameFlow/gen_ui_textures.py) and the boot cards'
# logos (addendum 6, the user's files).
TEXTURES += [(ROOT / f"SourceArt/UI/{n}.png", n) for n in (
    "T_UI_TitleScrim", "T_UI_RowGlow", "T_UI_Toggle_Off", "T_UI_Toggle_On", "T_UI_Knob",
    "T_UI_FocusMark", "T_UI_Chip", "T_UI_Arrow_L", "T_UI_Arrow_R", "T_Saskarta_TitleName_Shadow", "T_Tripo_Logo", "T_Hayba_Logo",
    "T_UI_SoftPlate")]  # the caption plate (LANE5)

# One face per call: an import can take most of the 5 s budget.
IMPORT_FACE = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest, src, name = __ARGS__
if eal.does_asset_exist(dest + "/" + name):
    print("FACE have " + name)
else:
    fac = unreal.FontFileImportFactory()
    fac.set_editor_property("batch_create_font_asset", unreal.BatchCreateFontAsset.NO)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", src)
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    task.set_editor_property("factory", fac)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("FACE imported " + " | ".join([str(p) for p in task.get_editor_property("imported_object_paths")]))
print("FACE saved " + name + "=" + str(eal.save_asset(dest + "/" + name, False)))
'''

MAKE_FONT = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest, name, entries = __ARGS__
path = dest + "/" + name
if eal.does_asset_exist(path):
    font = eal.load_asset(path)
    print("FONT have " + name)
else:
    font = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, dest, unreal.Font, unreal.FontFactory())
    print("FONT created " + str(font.get_path_name()))
font.set_editor_property("font_cache_type", unreal.FontCacheType.RUNTIME)
parts = []
for typeface, face in entries:
    parts.append('(Name="' + typeface + '",Font=(FontFaceAsset="/Script/Engine.FontFace\'' + face + '\'"))')
text = "(DefaultTypeface=(Fonts=(" + ",".join(parts) + ")))"
cf = font.get_editor_property("composite_font")
cf.import_text(text)
font.set_editor_property("composite_font", cf)
print("FONT composite " + str(font.get_editor_property("composite_font").export_text())[:400])
print("FONT saved " + str(eal.save_asset(path, False)))
'''

IMPORT_TEXTURE = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest, src, name, replace = __ARGS__
path = dest + "/" + name
if eal.does_asset_exist(path) and not replace:
    print("TEX have " + name)
else:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", src)
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", replace)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("TEX imported " + name)
tex = eal.load_asset(path)
tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_EDITOR_ICON)
tex.set_editor_property("srgb", True)
tex.set_editor_property("never_stream", True)
print("TEX " + name + " size " + str(tex.blueprint_get_size_x()) + "x" + str(tex.blueprint_get_size_y())
      + " group " + str(tex.get_editor_property("lod_group")) + " comp " + str(tex.get_editor_property("compression_settings")))
print("TEX saved " + str(eal.save_asset(path, False)))
'''

READ = r'''
import unreal
eal = unreal.EditorAssetLibrary
for p in __ARGS__:
    print(p + " " + str(eal.does_asset_exist(p)))
'''


def run(template, args):
    script = check_banned(template.replace("__ARGS__", repr(args)))
    ok, out, err = python_run(script)
    print(out.rstrip())
    if not ok:
        raise SystemExit(err or "python_run failed")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["fonts", "textures", "read"])
    ap.add_argument("--replace", action="store_true", help="textures: reimport over existing assets")
    ap.add_argument("--only", nargs="*", help="textures: import only these asset names")
    a = ap.parse_args(argv)
    if a.step == "fonts":
        for _typeface, src, name in FACES:
            run(IMPORT_FACE, (FONT_DIR, src.as_posix(), name))
        entries = [(t, f"{FONT_DIR}/{n}.{n}") for t, _s, n in FACES]
        run(MAKE_FONT, (FONT_DIR, FONT, entries))
    elif a.step == "textures":
        for src, name in TEXTURES:
            if a.only and name not in a.only:
                continue
            run(IMPORT_TEXTURE, (TEX_DIR, src.as_posix(), name, a.replace))
    else:
        paths = [f"{FONT_DIR}/{n}" for _t, _s, n in FACES] + [f"{FONT_DIR}/{FONT}"] + [f"{TEX_DIR}/{n}" for _s, n in TEXTURES]
        run(READ, paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
