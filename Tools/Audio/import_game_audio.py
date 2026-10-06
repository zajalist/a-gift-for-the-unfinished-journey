"""Import the offline lanes' audio into the editor (tasks CARRIERVO and CARRIERSFX).

    python Tools/Audio/import_game_audio.py plan                 # offline: list what each step would import
    python Tools/Audio/import_game_audio.py carrier-vo           # Saved/GameAudio/CarrierVoice -> Audio/CarrierVoice
    python Tools/Audio/import_game_audio.py radio                # Saved/RadioRecordings/selected -> Audio/Lines, Audio/Station/Host
    python Tools/Audio/import_game_audio.py show                 # the 206 live-show takes (RADIOSHOW) -> Audio/Station/Host
    python Tools/Audio/import_game_audio.py amb-classes          # SC_Ambience, SC_Geiger (child), SMX_Ambience (Ambience 2)
    python Tools/Audio/import_game_audio.py ambience             # Saved/GameAudio/Ambience2 (150 WAVs) -> Audio/Ambience2
    python Tools/Audio/import_game_audio.py vehicle              # Saved/GameAudio/CarrierVehicle -> Audio/Carrier
    python Tools/Audio/import_game_audio.py story                # Saved/GameAudio/Story (manifest) -> Audio/Story
    python Tools/Audio/import_game_audio.py read <folder>        # print each SoundWave's key settings

Every import is an AssetImportTask (automated, replace_existing), so a reimport keeps the existing
SoundWave's settings (class, attenuation). Files go in batches of 4 per python_run (5 s limit), and each
batch saves only the packages it imported. Every call checks for PIE first (apply_look.python_run).

carrier-vo: the 9 new CV lines copy VO_Carrier_CV_BOOT_01's sound class, attenuation settings and
virtualization mode; looping off. The voice is 2D (no attenuation), as the existing assets have it.
radio:      STN_<X> -> /Game/SaskartaGaea/Audio/Station/Host/VO_Station_STN_<X>;
            RADIO_B*, IDLE_* -> /Game/SaskartaGaea/Audio/Lines/<ID>. Clean takes: the game filters them.
show:       every station.json segment of category SHOW, FILL, LINGER, REACT, INTRO or OUTRO ->
            /Game/SaskartaGaea/Audio/Station/Host/VO_Station_<ID> (placeholder edge-tts takes until the author's
            recordings replace <ID>.wav; same ids, so a reimport drops them in). Each take copies
            VO_Station_STN_ID_01's sound class and is routed to the station chain (SM_Saskarta_Station +
            SEC_Saskarta_Radio, Tools/Audio/station_chain.py).
ambience:   the manifest's 150 files (not _demo_road.wav) -> /Game/SaskartaGaea/Audio/Ambience2/<stem>
            (Tools/GameFlow/specs/README_Ambience.md). loop -> looping + LOAD_ON_DEMAND (streamed);
            one-shots -> RETAIN_ON_LOAD (inline), the Geiger clicks ADPCM. Class SC_Ambience (SFX_Geiger_*:
            SC_Geiger), submix SMX_Ambience.
vehicle:    44 WAVs; *_Loop: looping on, loading behaviour Prime on Load; the rest looping off.
            No sound class yet (none exist). The old SFX_Carrier_* elsewhere are not touched.
story:      the story runner's PlaySfx one-shots from Tools/Audio/make_story_sfx.py (SFX_CrestGust,
            SFX_TapeClick, SFX_Carrier_ServoUp), listed in Saved/GameAudio/Story/manifest.json ->
            /Game/SaskartaGaea/Audio/Story/<asset>. Looping off, no sound class (as vehicle). The runner finds
            them by name under /Game/SaskartaGaea/Audio, so no story data changes.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import python_run, check_banned  # noqa: E402

VO_SRC = ROOT / "Saved" / "GameAudio" / "CarrierVoice"
VO_DEST = "/Game/SaskartaGaea/Audio/CarrierVoice"
RADIO_SRC = ROOT / "Saved" / "RadioRecordings" / "selected"
VEH_SRC = ROOT / "Saved" / "GameAudio" / "CarrierVehicle"
VEH_DEST = "/Game/SaskartaGaea/Audio/Carrier"
BATCH = 4

IMPORT = r'''
import unreal
eal = unreal.EditorAssetLibrary
JOBS = __JOBS__
REF = "__REF__"
ref = eal.load_asset(REF) if REF else None
ROUTE = __ROUTE__
sm = eal.load_asset("/Game/SaskartaGaea/Audio/Station/Chain/SM_Saskarta_Station") if ROUTE else None
sec = eal.load_asset("/Game/SaskartaGaea/Audio/Station/Chain/SEC_Saskarta_Radio") if ROUTE else None
tasks = []
for src, dest, name, loop in JOBS:
    if not eal.does_directory_exist(dest):
        eal.make_directory(dest)
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", src)
    t.set_editor_property("destination_path", dest)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", False)
    tasks.append(t)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
pk = []
for src, dest, name, loop in JOBS:
    w = eal.load_asset(dest + "/" + name)
    if w is None:
        print("MISSING " + name)
        continue
    w.set_editor_property("looping", loop)
    if loop:
        w.set_editor_property("loading_behavior", unreal.SoundWaveLoadingBehavior.PRIME_ON_LOAD)
    if ref is not None and name != ref.get_name():
        w.set_editor_property("sound_class_object", ref.get_editor_property("sound_class_object"))
        w.set_editor_property("attenuation_settings", ref.get_editor_property("attenuation_settings"))
        w.set_editor_property("virtualization_mode", ref.get_editor_property("virtualization_mode"))
    if ROUTE:
        w.set_editor_property("sound_submix_object", sm)
        w.set_editor_property("source_effect_chain", sec)
    pk.append(w.get_package())
    print("OK " + name + " " + str(round(w.get_editor_property("duration"), 2)) + "s loop=" + str(loop))
print("SAVED " + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)) + " n=" + str(len(pk)))
'''

AMB_SRC = ROOT / "Saved" / "GameAudio" / "Ambience2"
AMB_DEST = "/Game/SaskartaGaea/Audio/Ambience2"

AMB_CLASSES = r'''
import unreal
eal = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
D = "__DEST__"
if not eal.does_directory_exist(D):
    eal.make_directory(D)
def make(name, cls, fac):
    if eal.does_asset_exist(D + "/" + name):
        return eal.load_asset(D + "/" + name)
    return AT.create_asset(name, D, cls, fac)
amb = make("SC_Ambience", unreal.SoundClass, unreal.SoundClassFactory())
gei = make("SC_Geiger", unreal.SoundClass, unreal.SoundClassFactory())
gei.set_editor_property("parent_class", amb)
kids = list(amb.get_editor_property("child_classes"))
if gei not in kids:
    kids.append(gei)
    amb.set_editor_property("child_classes", kids)
smx = make("SMX_Ambience", unreal.SoundSubmix, unreal.SoundSubmixFactory())
print("classes", amb.get_name(), gei.get_name(), "parent=" + str(gei.get_editor_property("parent_class").get_name()), smx.get_name())
print("SAVED", [eal.save_asset(D + "/" + n, False) for n in ("SC_Ambience", "SC_Geiger", "SMX_Ambience")])
'''

AMB_IMPORT = r'''
import unreal
eal = unreal.EditorAssetLibrary
JOBS = __JOBS__
D = "__DEST__"
amb = eal.load_asset(D + "/SC_Ambience")
gei = eal.load_asset(D + "/SC_Geiger")
smx = eal.load_asset(D + "/SMX_Ambience")
tasks = []
for src, dest, name, loop in JOBS:
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", src)
    t.set_editor_property("destination_path", dest)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", False)
    tasks.append(t)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
pk = []
for src, dest, name, loop in JOBS:
    w = eal.load_asset(dest + "/" + name)
    if w is None:
        print("MISSING " + name)
        continue
    w.set_editor_property("looping", loop)
    if loop:
        w.set_editor_property("loading_behavior", unreal.SoundWaveLoadingBehavior.LOAD_ON_DEMAND)
    else:
        w.set_editor_property("loading_behavior", unreal.SoundWaveLoadingBehavior.RETAIN_ON_LOAD)
    if name.startswith("SFX_Geiger_Click"):
        w.set_editor_property("sound_asset_compression_type", unreal.SoundAssetCompressionType.ADPCM)
    w.set_editor_property("sound_class_object", gei if name.startswith("SFX_Geiger_") else amb)
    w.set_editor_property("sound_submix_object", smx)
    pk.append(w.get_package())
    print("OK " + name + " " + str(round(w.get_editor_property("duration"), 2)) + "s loop=" + str(loop))
print("SAVED " + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)) + " n=" + str(len(pk)))
'''

READ = r'''
import unreal
eal = unreal.EditorAssetLibrary
for p in eal.list_assets("__DEST__", False, False):
    w = eal.load_asset(p)
    if isinstance(w, unreal.SoundWave):
        sc = w.get_editor_property("sound_class_object")
        at = w.get_editor_property("attenuation_settings")
        print(w.get_name() + " " + str(round(w.get_editor_property("duration"), 2)) + "s loop=" + str(w.get_editor_property("looping")) + " class=" + (sc.get_name() if sc else "-") + " att=" + (at.get_name() if at else "-") + " vol=" + str(round(w.get_editor_property("volume"), 2)))
'''


def vo_jobs(existing_only=False):
    """(src, dest, name, loop) for every VO_Carrier_*.wav in the source folder."""
    return [(p.as_posix(), VO_DEST, p.stem, False) for p in sorted(VO_SRC.glob("VO_Carrier_*.wav"))]


def radio_jobs():
    jobs = []
    for p in sorted(RADIO_SRC.glob("*.wav")):
        gid = p.stem
        if gid.startswith("STN_"):
            jobs.append((p.as_posix(), "/Game/SaskartaGaea/Audio/Station/Host", "VO_Station_" + gid, False))
        elif gid.startswith("RADIO_B") or gid.startswith("IDLE_"):
            jobs.append((p.as_posix(), "/Game/SaskartaGaea/Audio/Lines", gid, False))
    return jobs


SHOW_CATEGORIES = {"SHOW", "FILL", "LINGER", "REACT", "INTRO", "OUTRO"}
HOST_DEST = "/Game/SaskartaGaea/Audio/Station/Host"
SHOW_REF = HOST_DEST + "/VO_Station_STN_ID_01"


def show_jobs():
    data = json.loads((ROOT / "docs" / "story" / "station.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["segments"] if s.get("category") in SHOW_CATEGORIES]
    return [((RADIO_SRC / (i + ".wav")).as_posix(), HOST_DEST, "VO_Station_" + i, False) for i in ids]


def ambience_jobs():
    m = json.loads((AMB_SRC / "manifest.json").read_text(encoding="utf-8"))
    return [((AMB_SRC / f["file"]).as_posix(), AMB_DEST, f["asset"], bool(f["loop"])) for f in m["files"]
            if not f["file"].startswith("_")]


def vehicle_jobs():
    return [(p.as_posix(), VEH_DEST, p.stem, p.stem.endswith("_Loop"))
            for p in sorted(VEH_SRC.glob("SFX_Carrier_*.wav"))]


STORY_SRC = ROOT / "Saved" / "GameAudio" / "Story"


def story_jobs():
    """The make_story_sfx.py manifest (the import list); empty until that script has run."""
    path = STORY_SRC / "manifest.json"
    if not path.exists():
        return []
    return [((STORY_SRC / f["file"]).as_posix(), f["ue_folder"], f["asset"], bool(f["loop"]))
            for f in json.loads(path.read_text(encoding="utf-8"))]


LOG = ROOT / "Saved" / "Logs" / "saskartarad.log"
FAULTS = ("access violation", "unknown opcode", "HCR-NATIVE", "Traceback (most recent call last)", "LogPython: Error")


def log_size():
    return LOG.stat().st_size if LOG.exists() else 0


def check_log(since):
    """Stop the run on any native fault or Python error the editor logged since `since` (bytes)."""
    if not LOG.exists():
        return
    with LOG.open("rb") as f:
        f.seek(since)
        new = f.read().decode("utf-8", errors="replace")
    hits = [ln for ln in new.splitlines() if any(k.lower() in ln.lower() for k in FAULTS)]
    if hits:
        raise SystemExit("editor log shows a fault, stopping:\n" + "\n".join(hits[:8]))


def run_batches(jobs, ref="", route=False, template=None):
    for i in range(0, len(jobs), BATCH):
        since = log_size()
        if template is not None:
            script = check_banned(template.replace("__JOBS__", repr(jobs[i:i + BATCH])).replace("__DEST__", AMB_DEST))
            ok, out, err = python_run(script)
            print(out.strip())
            check_log(since)
            if not ok or "MISSING" in out:
                raise SystemExit(f"batch {i // BATCH} failed: {err}")
            continue
        script = check_banned(IMPORT.replace("__JOBS__", repr(jobs[i:i + BATCH])).replace("__REF__", ref)
                              .replace("__ROUTE__", repr(route)))
        ok, out, err = python_run(script)
        print(out.strip())
        check_log(since)
        if not ok or "MISSING" in out:
            raise SystemExit(f"batch {i // BATCH} failed: {err}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["plan", "carrier-vo", "radio", "show", "amb-classes", "ambience", "vehicle", "story", "read"])
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--start", type=int, default=0, help="show/ambience: first job index (resume after a stop)")
    ap.add_argument("--batch", type=int, default=4, help="files per python_run (long takes: 2)")
    ap.add_argument("--count", type=int, default=0, help="show/ambience: at most this many jobs (0 = all)")
    a = ap.parse_args(argv)
    globals()["BATCH"] = a.batch
    if a.step == "plan":
        for n, j in (("carrier-vo", vo_jobs()), ("radio", radio_jobs()), ("show", show_jobs()), ("ambience", ambience_jobs()),
                     ("vehicle", vehicle_jobs()), ("story", story_jobs())):
            print(n, len(j))
            for x in j[:3]:
                print("  ", x)
        return 0
    if a.step == "read":
        ok, out, err = python_run(check_banned(READ.replace("__DEST__", a.folder)))
        print(out.strip() or err)
        return 0
    if a.step == "carrier-vo":
        # reimport the existing lines first (no settings copied), then the new ones with BOOT_01's settings
        existing = {p.stem for p in (ROOT / "Content" / "SaskartaGaea" / "Audio" / "CarrierVoice").glob("*.uasset")}
        jobs = vo_jobs()
        run_batches([j for j in jobs if j[2] in existing])
        run_batches([j for j in jobs if j[2] not in existing], ref=VO_DEST + "/VO_Carrier_CV_BOOT_01")
    elif a.step == "radio":
        run_batches(radio_jobs())
    elif a.step == "show":
        jobs = show_jobs()[a.start:]
        run_batches(jobs[:a.count] if a.count else jobs, ref=SHOW_REF, route=True)
    elif a.step == "amb-classes":
        ok, out, err = python_run(check_banned(AMB_CLASSES.replace("__DEST__", AMB_DEST)))
        print(out.strip() or err)
    elif a.step == "ambience":
        jobs = ambience_jobs()[a.start:]
        run_batches(jobs[:a.count] if a.count else jobs, template=AMB_IMPORT)
    elif a.step == "story":
        jobs = story_jobs()
        if not jobs:
            raise SystemExit("no Saved/GameAudio/Story/manifest.json: run python Tools/Audio/make_story_sfx.py first")
        run_batches(jobs)
    else:
        run_batches(vehicle_jobs())
    return 0


if __name__ == "__main__":
    sys.exit(main())
