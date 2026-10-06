"""Import the carrier barks into Unreal (run inside the editor's Python, not from a shell).

Sources: SourceArt/Audio/CarrierBarks/CARRIER_BARK_NN.wav (rendered with Tools/Audio/make_carrier_voice.py from
SourceArt/Audio/CarrierBarks/carrier_barks.tsv). Destination: /Game/SaskartaGaea/Audio/CarrierBarks, where
USaskartaCarrierBarks (Plugins/SaskartaCore/.../SaskartaCarrierBarks.cpp) looks for them by name.

Every import is an automated AssetImportTask with replace_existing, so a rerun reimports in place. Each wave gets
SC_Voice when that class exists (the voice volume setting applies), then the packages are saved in chunks of 20.
"""

import os
import unreal

DEST = "/Game/SaskartaGaea/Audio/CarrierBarks"
VOICE_CLASS = "/Game/SaskartaGaea/Audio/SC_Voice"
CHUNK = 20

project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
src = os.path.join(project, "SourceArt", "Audio", "CarrierBarks")
files = sorted(f for f in os.listdir(src) if f.startswith("CARRIER_BARK_") and f.lower().endswith(".wav"))
if not files:
    raise RuntimeError("no CARRIER_BARK_*.wav in " + src)

tasks = []
for name in files:
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", os.path.join(src, name))
    t.set_editor_property("destination_path", DEST)
    t.set_editor_property("destination_name", os.path.splitext(name)[0])
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", False)
    tasks.append(t)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

eal = unreal.EditorAssetLibrary
voice = eal.load_asset(VOICE_CLASS) if eal.does_asset_exist(VOICE_CLASS) else None
paths = []
for name in files:
    path = DEST + "/" + os.path.splitext(name)[0]
    wave = eal.load_asset(path)
    if not isinstance(wave, unreal.SoundWave):
        unreal.log_warning("carrier barks: import failed for " + name)
        continue
    if isinstance(voice, unreal.SoundClass):
        wave.set_editor_property("sound_class_object", voice)
    paths.append(path)

saved = 0
for i in range(0, len(paths), CHUNK):
    for path in paths[i:i + CHUNK]:
        if eal.save_asset(path, False):
            saved += 1
print("CARRIER_BARKS imported=%d saved=%d voice_class=%s" % (len(paths), saved, bool(voice)))
