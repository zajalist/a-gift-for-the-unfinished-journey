"""Import the title font the user picked (Task TITLE, part C) and restyle the title, settings and
pause menus with it.

    python Tools/GameFlow/import_title_font.py pick            # read title-font.txt, print the choice
    python Tools/GameFlow/import_title_font.py import          # copy the TTF to Saved/Fonts, import FF_/F_ assets

The user chose from samples A-H (scratchpad font_options.png); the choice is written to
.superpowers/sdd/2026-09-26-saskarta-world-sprint/title-font.txt as a letter and a family name.
All samples are OFL fonts from github.com/google/fonts; every glyph of the name, subtitle and menu
labels (including the circumflex in "dînefferesen") was checked with fontTools before import.

Runs through Hayba python_run (5 s per call, banned words checked). Saves only the new font assets
here; the widget restyle goes through the Hayba ui_* tools (see the TITLE report), because text
styles on a Widget Blueprint are not reachable from editor Python.
"""
import argparse
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))

from apply_look import python_run, check_banned  # noqa: E402

CHOICE_FILE = ROOT / ".superpowers" / "sdd" / "2026-09-26-saskarta-world-sprint" / "title-font.txt"
SAMPLE_DIR = pathlib.Path("C:/Users/Admin/AppData/Local/Temp/claude/D--UnrealEngine-saskartarad/"
                          "b9615e6a-f35d-4ad9-93d0-3f51e265951b/scratchpad/fonts")
FONT_DIR = "/Game/SaskartaGaea/GameFlow/UI/Fonts"

# letter -> (TTF in the sample folder, asset stem)
SAMPLES = {
    "A": ("Marcellus-Regular.ttf", "Marcellus"),
    "B": ("CormorantGaramond.ttf", "CormorantLight"),
    "C": ("EBGaramond.ttf", "EBGaramond"),
    "D": ("Spectral-Light.ttf", "SpectralLight"),
    "E": ("Italiana-Regular.ttf", "Italiana"),
    "F": ("TenorSans-Regular.ttf", "TenorSans"),
    "G": ("GildaDisplay-Regular.ttf", "GildaDisplay"),
    "H": ("Forum-Regular.ttf", "Forum"),
}


def pick(text=None):
    """(letter, ttf, stem) from the choice file: the first standalone capital A-H wins; failing
    that, a family name that matches a sample's file name; failing that, a lone lowercase letter
    (so the article "a" in "Gilda Display, a lovely one" never picks sample A)."""
    text = text if text is not None else CHOICE_FILE.read_text(encoding="utf-8")
    m = re.search(r"\b([A-H])\b", text)
    if m:
        return (m.group(1),) + SAMPLES[m.group(1)]
    squashed = re.sub(r"[^a-z]", "", text.lower())
    for letter, (ttf, stem) in SAMPLES.items():
        if re.sub(r"[^a-z]", "", ttf.split("-")[0].split(".")[0].lower()) in squashed:
            return (letter, ttf, stem)
    if text.strip().upper() in SAMPLES:
        return (text.strip().upper(),) + SAMPLES[text.strip().upper()]
    raise SystemExit(f"{CHOICE_FILE}: no sample letter A-H or family name found in {text!r}")


IMPORT = r'''
import unreal
DEST = "__FONT_DIR__"
src, face_name, font_name = __FONT__
eal = unreal.EditorAssetLibrary
if eal.does_asset_exist(DEST + "/" + font_name):
    print("FONT have " + font_name)
else:
    fac = unreal.FontFileImportFactory()
    fac.set_editor_property("batch_create_font_asset", unreal.BatchCreateFontAsset.YES)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", src)
    task.set_editor_property("destination_path", DEST)
    task.set_editor_property("destination_name", face_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    task.set_editor_property("factory", fac)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("FONT imported " + " | ".join([str(p) for p in task.get_editor_property("imported_object_paths")]))
    if eal.does_asset_exist(DEST + "/" + face_name + "_Font"):
        print("FONT rename " + str(eal.rename_asset(DEST + "/" + face_name + "_Font", DEST + "/" + font_name)))
saved = []
for name in (face_name, font_name):
    if eal.does_asset_exist(DEST + "/" + name):
        saved.append(name + "=" + str(eal.save_asset(DEST + "/" + name, False)))
print("FONT saved " + " ".join(saved))
'''


def do_import():
    letter, ttf, stem = pick()
    dst = ROOT / "Saved" / "Fonts" / ttf
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(SAMPLE_DIR / ttf, dst)
    face, font = f"FF_{stem}", f"F_{stem}"
    script = IMPORT.replace("__FONT_DIR__", FONT_DIR).replace("__FONT__", repr((dst.as_posix(), face, font)))
    ok, out, err = python_run(check_banned(script))
    print(out.rstrip())
    if not ok:
        raise SystemExit(err)
    print(f"choice {letter}: {FONT_DIR}/{font} (face {face}), source {dst}")
    return f"{FONT_DIR}/{font}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["pick", "import"])
    a = ap.parse_args(argv)
    if a.step == "pick":
        print(pick())
    else:
        do_import()
    return 0


if __name__ == "__main__":
    sys.exit(main())
