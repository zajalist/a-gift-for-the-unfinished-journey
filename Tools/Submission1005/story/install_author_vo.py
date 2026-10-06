"""Submission 2026-10-05: install the author's Elder takes and un-mute the ending.

Run in the editor:  py "D:/UnrealEngine/saskartarad/Tools/Submission1005/story/install_author_vo.py"
1. Reimports SourceArt/Audio/AuthorVO/<ID>.wav over /Game/SaskartaGaea/Audio/Lines/<ID>
   (existing SoundWave keeps its class/attenuation; only the audio data changes).
2. SCM_Saskarta_SilentEnding: every adjuster volume -> 1.0 (mix stays wired but is now neutral).
3. Re-imports DA_Saskarta_Story from docs/story/story-events.json (END_SYSTEM_01 moved to 9.6 s).
Saves only those packages.
"""
import os
import unreal

ROOT = "D:/UnrealEngine/saskartarad/"
SRC = ROOT + "SourceArt/Audio/AuthorVO/"
DEST = "/Game/SaskartaGaea/Audio/Lines"
IDS = [i[:-4] for i in sorted(os.listdir(SRC)) if i.endswith(".wav")]
MIX = "/Game/SaskartaGaea/Audio/Classes/SCM_Saskarta_SilentEnding"
STORY = "/Game/SaskartaGaea/Story/DA_Saskarta_Story"
save = []

# 1. audio
for ident in IDS:
    existing = unreal.load_asset(DEST + "/" + ident)
    keep = {}
    if existing:
        for p in ("sound_class_object", "attenuation_settings", "volume"):
            try: keep[p] = existing.get_editor_property(p)
            except Exception: pass
    t = unreal.AssetImportTask()
    t.filename = SRC + ident + ".wav"
    t.destination_path = DEST
    t.destination_name = ident
    t.replace_existing = True
    t.automated = True
    t.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    sw = unreal.load_asset(DEST + "/" + ident)
    for p, v in keep.items():
        try: sw.set_editor_property(p, v)
        except Exception: pass
    print("VO", ident, "duration", round(sw.get_editor_property("duration"), 2), "class", keep.get("sound_class_object"))
    save.append(sw)

# 2. neutralise the silent-ending mix
mix = unreal.load_asset(MIX)
adj = list(mix.get_editor_property("sound_class_effects"))
for a in adj:
    a.set_editor_property("volume_adjuster", 1.0)
mix.set_editor_property("sound_class_effects", adj)
print("MIX adjusters", len(adj), "-> volume 1.0")
save.append(mix)

# 3. story data
story = unreal.load_asset(STORY)
report = unreal.SaskartaStoryImport.import_story_from_files(story, unreal.Paths.project_dir())
print("STORY_IMPORT", report)
save.append(story)

ok = unreal.EditorAssetLibrary.save_loaded_assets(save, False)
print("AUTHOR_VO_DONE saved", ok)
