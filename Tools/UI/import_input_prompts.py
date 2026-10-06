"""Import the input-prompt glyphs (Saved/UI/InputPrompts/{light,dark}) into /Game/SaskartaGaea/UI/Prompts/{Light,Dark}.

    python Tools/UI/import_input_prompts.py [--replace]

UI texture settings: TEXTUREGROUP_UI, no mips, TC_EditorIcon (UserInterface2D), sRGB, never streamed, bilinear.
Batches of 4: one python_run imports, a second sets the UI settings and saves (the 5 s limit).
Hold the editor gate around the run (HAYBA_LEASE / HAYBA_AGENT_ID in the environment).
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import python_run  # noqa: E402

SRC = ROOT / "Saved/UI/InputPrompts"
DEST = "/Game/SaskartaGaea/UI/Prompts"

SCRIPT = r'''
import unreal
eal = unreal.EditorAssetLibrary
items, replace = __ARGS__
tasks = []
for src, dest, name in items:
    if eal.does_asset_exist(dest + "/" + name) and not replace:
        continue
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", src)
    t.set_editor_property("destination_path", dest)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", False)
    tasks.append(t)
if tasks:
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
print("BATCH imported " + str(len(tasks)))
'''

FIX = r'''
import unreal
eal = unreal.EditorAssetLibrary
Q = unreal.PropertyAccessChangeNotifyMode.NEVER  # one rebuild per texture, on the last property
items, replace = __ARGS__
ok = 0
for src, dest, name in items:
    tex = eal.load_asset(dest + "/" + name)
    if tex is None:
        print("MISSING " + name)
        continue
    tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI, Q)
    tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS, Q)
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_EDITOR_ICON, Q)
    tex.set_editor_property("srgb", True, Q)
    tex.set_editor_property("never_stream", True, Q)
    tex.set_editor_property("filter", unreal.TextureFilter.TF_BILINEAR)
    if eal.save_asset(dest + "/" + name, False):
        ok += 1
    print("TEX " + name + " " + str(tex.blueprint_get_size_x()) + "x" + str(tex.blueprint_get_size_y()))
print("BATCH saved " + str(ok) + "/" + str(len(items)))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    man = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    items = []
    for g in man["glyphs"]:
        f = SRC / g["file"]
        variant = "Light" if g["variant"] == "light" else "Dark"
        items.append((f.as_posix(), f"{DEST}/{variant}", f.stem))
    for i in range(0, len(items), 4):
        for script in (SCRIPT, FIX):  # import, then settings + save, each in its own 5 s call
            ok, out, err = python_run(script.replace("__ARGS__", repr((items[i:i + 4], a.replace))))
            print(out.strip().splitlines()[-1] if out.strip() else "", err or "")
            if not ok:
                sys.exit("batch failed: " + str(err))


if __name__ == "__main__":
    main()
